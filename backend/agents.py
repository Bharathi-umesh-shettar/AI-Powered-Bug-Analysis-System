"""Multi-agent bug diagnosis pipeline (Milestone 3).

Pipeline:
    Bug Information -> RAG Retrieval -> Analysis Agent
                    -> Duplicate Detection Agent -> Remediation Agent
                    -> Structured Findings

Every agent is evidence-driven: it only asserts what it can support from the
submitted bug text plus the retrieved historical records. Nothing is fabricated.
"""
import re
from collections import Counter

from config import DUPLICATE_THRESHOLD, SIMILAR_THRESHOLD, TOP_K

# --------------------------------------------------------------------------- #
# Error signature knowledge (pattern -> canonical type + likely causes)
# --------------------------------------------------------------------------- #
ERROR_PATTERNS = [
    (r"nullpointerexception|none[\s_]?type.*not|null reference|cannot read propert",
     "Null / Undefined Reference",
     "An object reference was dereferenced before it was assigned or after a "
     "lookup returned nothing.",
     ["Add an explicit null/None guard before dereferencing the value.",
      "Assert the invariant at the boundary where the object is created.",
      "Return an empty object instead of null from the producing function."]),
    (r"indexerror|index out of (range|bounds)|arrayindexoutofbounds",
     "Index Out Of Bounds",
     "A collection was accessed with an index derived from an unvalidated length.",
     ["Bound-check the index against len()/size() before access.",
      "Prefer iteration or slicing over manual index arithmetic."]),
    (r"keyerror|no such key|missing key|undefined key",
     "Missing Key / Field",
     "A dictionary or payload field the code assumed to be present was absent.",
     ["Use .get() with a default, or validate the payload schema on entry.",
      "Log the actual received keys to confirm the contract with the caller."]),
    (r"timeout|timed out|deadline exceeded|etimedout",
     "Timeout",
     "A downstream call exceeded its time budget, usually due to slow queries, "
     "connection saturation, or a missing index.",
     ["Set explicit connect/read timeouts and a bounded retry with backoff.",
      "Profile the slow call; add the missing index or cache the hot path.",
      "Raise the pool size only after confirming saturation in metrics."]),
    (r"deadlock|lock wait|could not obtain lock",
     "Database Lock / Deadlock",
     "Two transactions acquired the same rows in opposite order, or a "
     "transaction stayed open across a slow operation.",
     ["Acquire rows in a single consistent order in every transaction.",
      "Shorten transactions: do I/O outside the transactional block.",
      "Add a retry on the serialization-failure error code."]),
    (r"connection refused|econnrefused|could not connect|connection reset|"
     r"operationalerror.*connect|unable to connect",
     "Connection Failure",
     "The target service was unreachable: wrong host/port, service down, or "
     "network/ACL blocking.",
     ["Verify host, port and credentials resolved from configuration, not code.",
      "Add a readiness check plus retry with exponential backoff.",
      "Confirm the service is listening and the firewall/security group allows it."]),
    (r"integrityerror|unique constraint|duplicate key|foreign key constraint",
     "Database Constraint Violation",
     "A write violated a uniqueness or referential constraint, usually from a "
     "retry, race, or missing upsert.",
     ["Use an idempotent upsert (INSERT ... ON CONFLICT) for retryable writes.",
      "Insert parent rows before children, or defer the constraint.",
      "Add a de-duplication key so replays cannot double-insert."]),
    (r"no such column|no such table|undefined column|relation .* does not exist|"
     r"schema mismatch|column .* does not exist",
     "Schema Mismatch",
     "The running code expects a schema version that the database does not have.",
     ["Apply the pending migration, then redeploy.",
      "Make the migration additive so old and new code can both run.",
      "Assert the schema version at startup and fail fast on mismatch."]),
    (r"\b(401|403)\b|unauthorized|forbidden|invalid token|jwt|expired token|"
     r"authentication failed",
     "Authentication / Authorization Failure",
     "Credentials or a token were missing, malformed, expired, or lacked scope.",
     ["Verify the token audience, issuer, clock skew and expiry window.",
      "Refresh the token before expiry instead of reacting to the 401.",
      "Check the cookie SameSite/Secure flags if the flow crosses origins."]),
    (r"\b500\b|internal server error|502|503|504|bad gateway|service unavailable",
     "Upstream / Server Error",
     "The backend or an upstream dependency failed while handling the request.",
     ["Correlate the request ID with the upstream logs to find the real failure.",
      "Add a circuit breaker and a typed error response for the caller.",
      "Return a retry-after hint for transient upstream failures."]),
    (r"\b404\b|not found|no route|cannot (get|post)",
     "Route / Resource Not Found",
     "The requested path or resource does not exist in the running build.",
     ["Compare the client URL against the registered routes.",
      "Check for a trailing-slash or base-path mismatch behind the proxy."]),
    (r"cors|cross-origin|access-control-allow-origin",
     "CORS Misconfiguration",
     "The browser blocked the response because the origin was not allowed.",
     ["Allow the exact origin and required headers on the server.",
      "Handle the OPTIONS preflight explicitly on the affected route."]),
    (r"modulenotfounderror|importerror|cannot find module|no module named|"
     r"unresolved (import|dependency)|package .* not found",
     "Dependency / Import Error",
     "A required package is missing from the environment or is the wrong version.",
     ["Pin the package in requirements.txt and reinstall in a clean venv.",
      "Confirm the interpreter running the app is the one with the packages.",
      "Check for a name shadowing a stdlib or third-party module."]),
    (r"version (conflict|mismatch)|incompatible version|dependencyresolution|"
     r"conflicting dependencies",
     "Version Conflict",
     "Two dependencies require incompatible versions of a shared transitive "
     "package.",
     ["Resolve the constraint with a lockfile and a single pinned version.",
      "Upgrade the older consumer, or vendor the conflicting dependency."]),
    (r"config|environment variable|env var|missing setting|\.env|not configured",
     "Configuration Error",
     "A required setting was absent or wrong for this environment.",
     ["Validate all required settings at startup and fail fast with the key name.",
      "Move the value out of code into environment configuration."]),
    (r"syntaxerror|typeerror|compilation (error|failed)|cannot compile|"
     r"ts\d{4}|type '.*' is not assignable|does not compile",
     "Compilation / Type Error",
     "The source does not satisfy the compiler or type checker.",
     ["Fix the reported type at the declaration site rather than casting it away.",
      "Run the type checker in CI so the error cannot reach a branch build.",
      "Regenerate stale generated types before compiling."]),
    (r"memoryerror|out of memory|oom|heap (space|limit)",
     "Memory Exhaustion",
     "The process exceeded its memory budget, typically from unbounded "
     "accumulation or an oversized result set.",
     ["Stream or paginate the data instead of loading it all in memory.",
      "Cap the batch size and release references inside the loop."]),
    (r"race condition|concurrent modification|thread.?safe|non-atomic",
     "Concurrency Race",
     "Shared state was mutated without synchronisation.",
     ["Guard the shared state with a lock, or make the update atomic in the DB.",
      "Make the operation idempotent so ordering no longer matters."]),
    (r"zerodivisionerror|division by zero",
     "Division By Zero",
     "A denominator derived from data was zero.",
     ["Guard the denominator and define the zero case explicitly."]),
    (r"valueerror|invalid literal|could not (convert|parse)|json.*decode|"
     r"unmarshal|deserializ",
     "Parsing / Validation Error",
     "Input did not match the expected format or type.",
     ["Validate and coerce input at the boundary with a schema.",
      "Log the offending payload (redacted) to identify the producer."]),
    (r"filenotfound|no such file or directory|permission denied|ioerror",
     "Filesystem / Permission Error",
     "A path did not exist or the process lacked permission for it.",
     ["Resolve paths from configuration and create parents before writing.",
      "Check the runtime user's ownership of the target directory."]),
]

COMPONENT_HINTS = [
    (r"\b(sql|database|db|postgres|mysql|sqlite|query|migration|table|column|"
     r"transaction|orm)\b", "Database"),
    (r"\b(login|logout|auth|token|jwt|session|oauth|password|credential|"
     r"permission|role)\b", "Authentication"),
    (r"\b(api|endpoint|rest|http|request|response|route|controller|webhook|"
     r"payload)\b", "API"),
    (r"\b(ui|frontend|browser|css|react|render|component|button|form|page|"
     r"javascript)\b", "Frontend"),
    (r"\b(config|environment|deploy|docker|build|pipeline|ci|cd|dependency|"
     r"package|version)\b", "Configuration"),
    (r"\b(cache|redis|memcache)\b", "Caching"),
    (r"\b(queue|kafka|rabbit|worker|job|cron|scheduler)\b", "Background Jobs"),
    (r"\b(file|upload|storage|s3|bucket|disk)\b", "Storage"),
    (r"\b(report|export|pdf|csv|excel)\b", "Reporting"),
]

SEVERITY_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}


def _blob(bug):
    return " \n".join(str(bug.get(k) or "") for k in (
        "title", "description", "error_message", "stack_trace",
        "component", "environment", "additional_info",
    )).lower()


def classify_error(bug):
    """Return every error signature matched by the bug text, best first."""
    text = _blob(bug)
    matches = []
    for pattern, name, cause, fixes in ERROR_PATTERNS:
        hit = re.search(pattern, text)
        if hit:
            matches.append({
                "type": name,
                "matched_on": hit.group(0)[:80],
                "explains": cause,
                "fixes": fixes,
            })
    return matches


def infer_component(bug):
    """Use the declared component; otherwise infer it from the text."""
    declared = (bug.get("component") or "").strip()
    if declared:
        return declared, "declared by reporter"
    text = _blob(bug)
    scores = Counter()
    for pattern, comp in COMPONENT_HINTS:
        scores[comp] += len(re.findall(pattern, text))
    best, count = (scores.most_common(1) or [("Unclassified", 0)])[0]
    if count == 0:
        return "Unclassified", "no component keywords found"
    return best, f"inferred from {count} keyword match(es)"


def extract_stack_frames(stack_trace, limit=3):
    """Pull the most informative frames out of a stack trace."""
    if not stack_trace:
        return []
    frames = []
    for line in str(stack_trace).splitlines():
        line = line.strip()
        if not line:
            continue
        if re.search(r'(File ".+", line \d+|at [\w.$<>]+\(|\w+\.(py|js|ts|java|go|rb|cs):\d+)', line):
            frames.append(line[:200])
    return frames[-limit:] if frames else []


# --------------------------------------------------------------------------- #
# Agent 1 - Analysis
# --------------------------------------------------------------------------- #
class AnalysisAgent:
    """Analyses error patterns, stack traces, description, component, history."""

    name = "Analysis Agent"

    def run(self, bug, similar):
        signatures = classify_error(bug)
        component, component_basis = infer_component(bug)
        frames = extract_stack_frames(bug.get("stack_trace"))

        strong = [s for s in similar if s.get("similarity", 0) >= SIMILAR_THRESHOLD]
        historical_causes = [s.get("root_cause") for s in strong if s.get("root_cause")]

        root_cause, confidence, basis = self._root_cause(
            signatures, historical_causes, strong, frames
        )

        explanation = self._explain(bug, signatures, frames, strong, component,
                                    component_basis)
        return {
            "agent": self.name,
            "error_types": [s["type"] for s in signatures] or ["Unclassified"],
            "signatures": signatures,
            "component": component,
            "component_basis": component_basis,
            "stack_frames": frames,
            "possible_root_cause": root_cause,
            "root_cause_confidence": confidence,
            "root_cause_basis": basis,
            "explanation": explanation,
            "historical_matches": len(strong),
            "next_steps": self._next_steps(signatures, frames, strong),
        }

    def _root_cause(self, signatures, historical_causes, strong, frames):
        if historical_causes and strong and strong[0].get("similarity", 0) >= 0.75:
            top = Counter(historical_causes).most_common(1)[0]
            score = round(min(0.95, strong[0]["similarity"]), 2)
            return (top[0], score,
                    f"matched historical bug #{strong[0].get('bug_id')} "
                    f"(similarity {strong[0]['similarity']:.2f})")
        if signatures:
            conf = 0.7 if frames else 0.55
            if historical_causes:
                conf = 0.75
            return (signatures[0]["explains"], conf,
                    f"error signature '{signatures[0]['type']}' matched on "
                    f"\"{signatures[0]['matched_on']}\"")
        if historical_causes:
            top = Counter(historical_causes).most_common(1)[0]
            return (top[0], 0.4, "weak historical similarity only")
        return ("Not determined from the supplied evidence. More detail is "
                "needed: exact error message, full stack trace, and the "
                "component where it occurs.", 0.0,
                "no error signature and no similar historical bug")

    def _explain(self, bug, signatures, frames, strong, component, basis):
        lines = []
        sev = bug.get("severity") or "Medium"
        lines.append(
            f"Severity {sev} bug attributed to the {component} component ({basis})."
        )
        if signatures:
            lines.append(
                "Error-pattern analysis matched: "
                + ", ".join(f"{s['type']} (on \"{s['matched_on']}\")"
                            for s in signatures[:3]) + "."
            )
        else:
            lines.append("No known error signature matched the supplied text, so "
                         "the diagnosis relies on historical similarity only.")
        if frames:
            lines.append(f"Stack trace points at: {frames[-1]}")
        else:
            lines.append("No parsable stack frames were supplied.")
        if strong:
            lines.append(
                f"{len(strong)} historical bug(s) scored above the "
                f"{SIMILAR_THRESHOLD:.2f} similarity threshold; the closest is "
                f"#{strong[0].get('bug_id')} \"{strong[0].get('title')}\" at "
                f"{strong[0]['similarity']:.2f}."
            )
        else:
            lines.append("No historical bug passed the similarity threshold; this "
                         "appears to be new territory for the knowledge base.")
        return " ".join(lines)

    def _next_steps(self, signatures, frames, strong):
        steps = []
        if not frames:
            steps.append("Attach the full stack trace so the failing frame can be "
                         "pinpointed.")
        if signatures:
            steps.append(f"Reproduce the {signatures[0]['type']} case in a test "
                         f"before changing code.")
        if strong and strong[0].get("suggested_fix"):
            steps.append(f"Review the fix applied to historical bug "
                         f"#{strong[0].get('bug_id')} for reuse.")
        if not steps:
            steps.append("Collect the exact error message and the environment "
                         "where it reproduces.")
        steps.append("Add a regression test that fails before the fix and passes "
                     "after it.")
        return steps


# --------------------------------------------------------------------------- #
# Agent 2 - Duplicate Detection
# --------------------------------------------------------------------------- #
class DuplicateDetectionAgent:
    """Decides: Duplicate / Similar but different / New unseen bug."""

    name = "Duplicate Detection Agent"

    def run(self, bug, similar):
        if not similar:
            return {
                "agent": self.name,
                "status": "New / Unseen",
                "confidence": 0.0,
                "duplicate_of": None,
                "candidates": [],
                "explanation": "The knowledge base returned no candidates, so "
                               "this bug has no precedent on record.",
            }

        candidates = []
        for cand in similar[:TOP_K]:
            score = float(cand.get("similarity", 0))
            candidates.append({
                "bug_id": cand.get("bug_id"),
                "title": cand.get("title"),
                "component": cand.get("component") or cand.get("category"),
                "severity": cand.get("severity"),
                "similarity": round(score, 4),
                "root_cause": cand.get("root_cause"),
                "suggested_fix": cand.get("suggested_fix"),
                "verdict": self._verdict(score),
                "shared_terms": self._shared_terms(bug, cand),
            })

        top = candidates[0]
        score = top["similarity"]
        status = self._verdict(score)
        dup_of = top["bug_id"] if status == "Duplicate" else None
        return {
            "agent": self.name,
            "status": status,
            "confidence": score,
            "duplicate_of": dup_of,
            "candidates": candidates,
            "explanation": self._explain(status, top, bug),
        }

    def _verdict(self, score):
        if score >= DUPLICATE_THRESHOLD:
            return "Duplicate"
        if score >= SIMILAR_THRESHOLD:
            return "Similar but different"
        return "New / Unseen"

    def _shared_terms(self, bug, cand, limit=8):
        stop = {"the", "a", "an", "is", "are", "was", "were", "of", "to", "in",
                "on", "and", "or", "not", "for", "with", "when", "after", "this",
                "that", "it", "be", "by", "at", "from", "as", "but"}
        def terms(text):
            return {w for w in re.findall(r"[a-z0-9_.]{3,}", str(text).lower())
                    if w not in stop}
        left = terms(_blob(bug))
        right = terms(f"{cand.get('title','')} {cand.get('description','')} "
                      f"{cand.get('root_cause','')}")
        return sorted(left & right)[:limit]

    def _explain(self, status, top, bug):
        shared = ", ".join(top["shared_terms"][:6]) or "no distinctive shared terms"
        base = (f"Closest record is knowledge-base entry #{top['bug_id']} "
                f"(\"{top['title']}\") at cosine similarity "
                f"{top['similarity']:.3f}. Overlapping terms: {shared}.")
        if status == "Duplicate":
            return (base + f" This is at or above the duplicate threshold of "
                    f"{DUPLICATE_THRESHOLD:.2f}, and both records describe the "
                    f"same failure mode, so it is treated as a duplicate rather "
                    f"than a new defect.")
        if status == "Similar but different":
            same_comp = (top.get("component") or "").lower() == \
                        (bug.get("component") or "").lower()
            return (base + f" It clears the similarity threshold of "
                    f"{SIMILAR_THRESHOLD:.2f} but not the duplicate threshold of "
                    f"{DUPLICATE_THRESHOLD:.2f}"
                    + (", and the component matches, " if same_comp else ", ")
                    + "so it is useful evidence but describes a different defect.")
        return (base + f" That is below the {SIMILAR_THRESHOLD:.2f} similarity "
                f"threshold, so no historical record explains this bug; it is "
                f"treated as new.")


# --------------------------------------------------------------------------- #
# Agent 3 - Remediation
# --------------------------------------------------------------------------- #
class RemediationAgent:
    """Turns analysis + duplicate evidence into specific, actionable fixes."""

    name = "Remediation Agent"

    def run(self, bug, similar, analysis, duplicate):
        recommendations = []
        evidence = []

        # 1. Confirmed historical fixes carry the most weight.
        for cand in duplicate.get("candidates", []):
            if cand["similarity"] >= SIMILAR_THRESHOLD and cand.get("suggested_fix"):
                recommendations.append({
                    "action": cand["suggested_fix"],
                    "source": f"Historical fix from knowledge-base entry "
                              f"#{cand['bug_id']}",
                    "confidence": round(cand["similarity"], 2),
                    "priority": 1 if cand["verdict"] == "Duplicate" else 2,
                })
                evidence.append({
                    "bug_id": cand["bug_id"],
                    "title": cand["title"],
                    "similarity": cand["similarity"],
                    "root_cause": cand.get("root_cause"),
                    "fix": cand.get("suggested_fix"),
                })

        # 2. Signature-driven remediations tied to the matched pattern.
        for sig in analysis.get("signatures", [])[:3]:
            for fix in sig["fixes"]:
                recommendations.append({
                    "action": fix,
                    "source": f"{sig['type']} pattern matched on "
                              f"\"{sig['matched_on']}\"",
                    "confidence": 0.65,
                    "priority": 2,
                })

        # 3. Frame-specific instruction when a stack trace was supplied.
        frames = analysis.get("stack_frames") or []
        if frames:
            recommendations.append({
                "action": f"Instrument and inspect the failing frame "
                          f"({frames[-1]}): log the inputs it receives and assert "
                          f"the precondition that is being violated there.",
                "source": "Stack-trace analysis",
                "confidence": 0.6,
                "priority": 2,
            })

        # 4. Severity-driven containment.
        if SEVERITY_RANK.get(bug.get("severity"), 2) >= 3:
            recommendations.append({
                "action": "Because this is a high-impact defect, ship a "
                          "containment step first (feature flag, guard clause or "
                          "rollback of the last change to "
                          f"{analysis.get('component')}), then land the root-cause "
                          "fix behind a test.",
                "source": f"Severity {bug.get('severity')} policy",
                "confidence": 0.5,
                "priority": 1,
            })

        if duplicate.get("status") == "Duplicate":
            recommendations.insert(0, {
                "action": f"Link this report to knowledge-base entry "
                          f"#{duplicate['duplicate_of']} and apply that verified "
                          f"fix instead of opening a parallel investigation.",
                "source": "Duplicate Detection Agent",
                "confidence": duplicate.get("confidence", 0),
                "priority": 1,
            })

        if not recommendations:
            recommendations.append({
                "action": "No evidence-backed fix could be derived. Capture the "
                          "exact error message, the full stack trace, the "
                          "component, and a minimal reproduction, then resubmit "
                          "so retrieval has something to match on.",
                "source": "Insufficient evidence",
                "confidence": 0.0,
                "priority": 3,
            })

        # De-duplicate identical actions, keep the highest confidence one.
        unique = {}
        for rec in recommendations:
            key = rec["action"].strip().lower()
            if key not in unique or rec["confidence"] > unique[key]["confidence"]:
                unique[key] = rec
        ordered = sorted(unique.values(),
                         key=lambda r: (r["priority"], -r["confidence"]))

        return {
            "agent": self.name,
            "possible_causes": self._causes(analysis, duplicate),
            "recommendations": ordered,
            "primary_recommendation": ordered[0]["action"],
            "supporting_evidence": evidence,
            "verification": self._verification(analysis, bug),
        }

    def _causes(self, analysis, duplicate):
        causes = []
        if analysis.get("possible_root_cause"):
            causes.append({
                "cause": analysis["possible_root_cause"],
                "confidence": analysis.get("root_cause_confidence", 0),
                "basis": analysis.get("root_cause_basis"),
            })
        for cand in duplicate.get("candidates", [])[:3]:
            if cand.get("root_cause") and cand["similarity"] >= SIMILAR_THRESHOLD:
                if any(c["cause"] == cand["root_cause"] for c in causes):
                    continue
                causes.append({
                    "cause": cand["root_cause"],
                    "confidence": round(cand["similarity"] * 0.8, 2),
                    "basis": f"root cause of similar entry #{cand['bug_id']}",
                })
        return causes

    def _verification(self, analysis, bug):
        comp = analysis.get("component", "the affected component")
        steps = [
            f"Reproduce the failure in {bug.get('environment') or 'the reported environment'} "
            f"and capture the current error as the baseline.",
            f"Apply the fix, then re-run the reproduction against {comp}.",
            "Add the reproduction as an automated regression test.",
        ]
        if analysis.get("error_types"):
            steps.append(
                f"Confirm the '{analysis['error_types'][0]}' signature no longer "
                f"appears in the logs after the change."
            )
        steps.append("Mark the bug Resolved & Verified so the confirmed fix enters "
                     "the knowledge base.")
        return steps


# --------------------------------------------------------------------------- #
# Orchestrator -> Structured Findings
# --------------------------------------------------------------------------- #
class DiagnosisPipeline:
    """Runs RAG retrieval and all three agents, producing structured findings."""

    def __init__(self, rag):
        self.rag = rag
        self.analysis_agent = AnalysisAgent()
        self.duplicate_agent = DuplicateDetectionAgent()
        self.remediation_agent = RemediationAgent()

    @staticmethod
    def query_text(bug):
        parts = [bug.get("title"), bug.get("description"),
                 bug.get("error_message"), bug.get("stack_trace"),
                 bug.get("component")]
        return ". ".join(str(p) for p in parts if p)

    def run(self, bug, k=TOP_K):
        query = self.query_text(bug)
        similar = self.rag.search_similar_bugs(query, k=k)
        analysis = self.analysis_agent.run(bug, similar)
        duplicate = self.duplicate_agent.run(bug, similar)
        remediation = self.remediation_agent.run(bug, similar, analysis, duplicate)

        findings = {
            "bug_summary": self._summary(bug, analysis),
            "bug": {
                "id": bug.get("id"),
                "title": bug.get("title"),
                "severity": bug.get("severity"),
                "component": analysis["component"],
                "environment": bug.get("environment"),
                "status": bug.get("status", "Open"),
            },
            "severity": bug.get("severity"),
            "component": analysis["component"],
            "error_types": analysis["error_types"],
            "possible_root_cause": analysis["possible_root_cause"],
            "root_cause_confidence": analysis["root_cause_confidence"],
            "root_cause_basis": analysis["root_cause_basis"],
            "analysis": analysis,
            "similar_bugs": similar,
            "duplicate": duplicate,
            "duplicate_status": duplicate["status"],
            "duplicate_confidence": duplicate["confidence"],
            "remediation": remediation,
            "recommended_fix": remediation["primary_recommendation"],
            "supporting_evidence": remediation["supporting_evidence"],
            "next_action": self._next_action(duplicate, remediation, analysis),
            "rag": {
                "retrieved": len(similar),
                "top_score": similar[0]["similarity"] if similar else 0.0,
                "backend": self.rag.backend,
                "knowledge_entries": len(self.rag.records),
                "query_preview": query[:300],
            },
        }
        return findings

    def _summary(self, bug, analysis):
        return (f"\"{bug.get('title')}\" — {bug.get('severity') or 'Medium'} "
                f"severity issue in {analysis['component']}, classified as "
                f"{', '.join(analysis['error_types'])}. "
                f"{analysis['explanation']}")

    def _next_action(self, duplicate, remediation, analysis):
        if duplicate["status"] == "Duplicate":
            return (f"Close as duplicate of #{duplicate['duplicate_of']} and apply "
                    f"the verified fix from that entry.")
        if analysis["root_cause_confidence"] >= 0.6:
            return f"Assign to the {analysis['component']} owner and apply: " \
                   f"{remediation['primary_recommendation']}"
        return ("Gather more diagnostic detail (full stack trace, exact error "
                "message, reproduction steps) before assigning ownership.")
