"""Root Cause Agent (Milestone 3).

Determines the most probable root cause of a bug by fusing:
  - Log analysis output (exception + parsed root cause hint)
  - Historical KB matches retrieved via FAISS RAG
  - Bug description keywords

Outputs: root_cause, confidence, supporting_evidence, historical_refs.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional


ROOT_CAUSE_PATTERNS = [
    ("Connection Pool Exhausted", ["connection pool", "too many connections", "pool exhausted", "max_connections"]),
    ("Database Timeout", ["db timeout", "query timeout", "database timeout", "lock wait timeout"]),
    ("Network Timeout", ["timeout", "timed out", "read timeout", "socket timeout"]),
    ("Authentication Failure", ["auth", "login", "unauthorized", "invalid token", "jwt", "credentials"]),
    ("Null / Missing Reference", ["nullpointer", "null pointer", "undefined is not", "cannot read prop"]),
    ("Missing Configuration / File", ["filenotfound", "no such file", "missing config", "env var"]),
    ("Invalid Input / Validation", ["valueerror", "invalid literal", "validation failed", "bad request"]),
    ("Integrity Constraint Violation", ["integrityerror", "duplicate entry", "unique constraint", "foreign key"]),
    ("Memory / Resource Exhaustion", ["outofmemory", "memory leak", "heap", "oom"]),
    ("Race Condition / Deadlock", ["deadlock", "race condition", "concurrent modification"]),
    ("Third-Party API Failure", ["503", "502", "bad gateway", "upstream", "third-party"]),
    ("Permission / Access Denied", ["forbidden", "403", "permission denied", "access denied"]),
]


class RootCauseAgent:
    name = "Root Cause Agent"

    def analyze(
        self,
        bug: Dict[str, Any],
        log_analysis: Optional[Dict[str, Any]] = None,
        similar: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        log_analysis = log_analysis or {}
        similar = similar or []

        blob = " ".join([
            bug.get("title", ""), bug.get("description", ""),
            bug.get("stack_trace", ""), bug.get("error_log", ""),
            log_analysis.get("exception_type", ""),
            log_analysis.get("exception_message", ""),
            log_analysis.get("root_cause", ""),
        ]).lower()

        # 1) Pattern-based candidate
        pattern_hits = []
        for label, kws in ROOT_CAUSE_PATTERNS:
            for kw in kws:
                if kw in blob:
                    pattern_hits.append(label)
                    break

        # 2) Historical evidence — most common root_cause in similar KB matches
        hist_causes = [s.get("root_cause") for s in similar if s.get("root_cause")]
        hist_top, hist_top_count = ("", 0)
        if hist_causes:
            hist_top, hist_top_count = Counter(hist_causes).most_common(1)[0]

        # 3) Choose best cause
        candidate_scores: Counter = Counter()
        for h in pattern_hits:
            candidate_scores[h] += 2
        if hist_top:
            candidate_scores[hist_top] += hist_top_count
        # fall-back: log-analysis provided cause
        log_cause = log_analysis.get("root_cause") or ""
        if log_cause and log_cause != "Unclassified failure — review stack trace manually." \
                and not log_cause.startswith("No stack trace"):
            candidate_scores[log_cause] += 1

        if candidate_scores:
            root_cause = candidate_scores.most_common(1)[0][0]
        elif log_cause:
            root_cause = log_cause
        else:
            root_cause = "Undetermined — insufficient signals in the report."

        # 4) Confidence
        top_score = candidate_scores.most_common(1)[0][1] if candidate_scores else 0
        avg_sim = (sum(s.get("similarity_pct", 0) for s in similar) / len(similar)) if similar else 0
        confidence = int(min(97, 55 + top_score * 8 + avg_sim / 6))

        # 5) Evidence
        evidence: List[str] = []
        if pattern_hits:
            evidence.append(f"Pattern signals: {', '.join(sorted(set(pattern_hits)))}")
        if log_analysis.get("exception_type"):
            evidence.append(f"Exception observed: {log_analysis['exception_type']}")
        if log_analysis.get("failure_point"):
            evidence.append(f"Failure at {log_analysis['failure_point']}")
        for s in similar[:3]:
            evidence.append(
                f"KB #{s.get('kb_id')} “{s.get('title','')[:60]}” "
                f"({s.get('similarity_pct',0)}% match)"
            )
        if not evidence:
            evidence.append("No corroborating evidence found.")

        historical_refs = [
            {
                "kb_id": s.get("kb_id"),
                "title": s.get("title"),
                "similarity_pct": s.get("similarity_pct"),
                "root_cause": s.get("root_cause"),
                "suggested_fix": s.get("suggested_fix"),
            }
            for s in similar[:5]
        ]

        return {
            "root_cause": root_cause,
            "confidence": confidence,
            "supporting_evidence": evidence,
            "historical_refs": historical_refs,
        }


def run_root_cause(bug, log_analysis=None, similar=None):
    return RootCauseAgent().analyze(bug, log_analysis=log_analysis, similar=similar)
