"""Remediation Agent (Milestone 3).

Generates a consolidated remediation plan:
  - Recommended fix (aggregated from similar KB entries + heuristics)
  - Developer suggestions
  - Resolution steps
  - Best practices

Runs offline; combines pattern-based templates with historical suggested_fix
strings pulled from FAISS-retrieved KB matches.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional


FIX_TEMPLATES = {
    "Connection Pool Exhausted": {
        "fix": "Increase the database connection pool size and add a retry/backoff on acquire.",
        "steps": [
            "Raise `pool_max` (e.g. 20 → 50) in the DB client config.",
            "Ensure every request closes/returns its connection (use context managers).",
            "Add exponential backoff around connection acquisition.",
            "Instrument pool usage metrics to catch regressions.",
        ],
    },
    "Database Timeout": {
        "fix": "Add query timeouts and index the slow columns; introduce a retry policy.",
        "steps": [
            "EXPLAIN the slow query and add composite indexes.",
            "Set a statement timeout (e.g. `statement_timeout=5s`).",
            "Cache read-heavy responses.",
        ],
    },
    "Network Timeout": {
        "fix": "Increase the client timeout and implement retries with exponential backoff.",
        "steps": [
            "Wrap external calls in a retry policy (max 3 attempts).",
            "Add circuit-breaker to prevent cascading failures.",
            "Log correlation IDs for downstream debugging.",
        ],
    },
    "Authentication Failure": {
        "fix": "Validate credentials, refresh tokens, and log the failing auth step.",
        "steps": [
            "Verify token expiry + clock skew.",
            "Add token-refresh logic on 401 responses.",
            "Rate-limit failed attempts to block brute-force.",
        ],
    },
    "Null / Missing Reference": {
        "fix": "Add null / undefined guards and default values before dereferencing.",
        "steps": [
            "Add `if obj is None: return` (or optional chaining `?.`) at the failure site.",
            "Backfill missing data or seed defaults.",
            "Extend unit tests for the null-input branch.",
        ],
    },
    "Missing Configuration / File": {
        "fix": "Ship the missing configuration and validate presence on boot.",
        "steps": [
            "Add a startup config-validation step that fails fast.",
            "Document required env vars in README.",
            "Provide a `.env.example` template.",
        ],
    },
    "Invalid Input / Validation": {
        "fix": "Validate input at the API boundary and return a friendly 400.",
        "steps": [
            "Add a schema validator (pydantic / marshmallow) at the endpoint.",
            "Reject bad payloads with a clear error message.",
            "Add regression tests for the invalid inputs seen.",
        ],
    },
    "Integrity Constraint Violation": {
        "fix": "Pre-check the constraint and surface a domain-friendly conflict error.",
        "steps": [
            "SELECT before INSERT for uniqueness-critical fields, or catch the constraint error.",
            "Return HTTP 409 with a helpful message instead of 500.",
        ],
    },
    "Memory / Resource Exhaustion": {
        "fix": "Profile allocations and stream large payloads instead of loading them in memory.",
        "steps": [
            "Use generators / streaming for large datasets.",
            "Raise container memory limits temporarily.",
            "Add a heap-dump collector for post-mortem analysis.",
        ],
    },
    "Race Condition / Deadlock": {
        "fix": "Serialize the critical section with a lock or a queue.",
        "steps": [
            "Introduce a mutex / DB row-level lock around the contended write.",
            "Retry the transaction on deadlock detection.",
        ],
    },
    "Third-Party API Failure": {
        "fix": "Add a circuit breaker and a graceful fallback for the upstream call.",
        "steps": [
            "Wrap the call with a circuit breaker (e.g. failure ratio > 50%).",
            "Cache the last-known-good response as a fallback.",
        ],
    },
    "Permission / Access Denied": {
        "fix": "Fix the caller's role/permissions and add a preflight check.",
        "steps": [
            "Verify the RBAC role assigned to the failing user.",
            "Add an authorization check at the route level.",
        ],
    },
}

DEFAULT_TEMPLATE = {
    "fix": "Review the stack trace and reproduce locally, then patch the failing branch.",
    "steps": [
        "Reproduce the bug in a local/dev environment.",
        "Add a failing unit test for the observed behaviour.",
        "Patch the code and confirm the test now passes.",
        "Ship behind a feature flag if the change is broad.",
    ],
}

BEST_PRACTICES = [
    "Use structured logging with correlation IDs.",
    "Implement retries with exponential backoff for transient errors.",
    "Add input validation at every trust boundary.",
    "Cover regressions with an automated unit / integration test.",
    "Monitor SLOs and alert on error-rate anomalies.",
]


class RemediationAgent:
    name = "Remediation Agent"

    def analyze(
        self,
        bug: Dict[str, Any],
        root_cause: Optional[Dict[str, Any]] = None,
        similar: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        similar = similar or []
        rc_label = (root_cause or {}).get("root_cause", "")
        template = None
        for label, tmpl in FIX_TEMPLATES.items():
            if label.lower() in rc_label.lower():
                template = tmpl
                break
        if template is None:
            template = DEFAULT_TEMPLATE

        # Aggregate historical fixes
        hist_fixes: List[str] = []
        for s in similar[:5]:
            fix = (s.get("suggested_fix") or "").strip()
            if fix:
                hist_fixes.append(fix)

        # Deduplicate keeping order
        seen = set()
        historical_fixes: List[str] = []
        for f in hist_fixes:
            key = f.lower()[:120]
            if key not in seen:
                seen.add(key)
                historical_fixes.append(f)

        recommended_fix = template["fix"]
        resolution_steps = list(template["steps"])
        if historical_fixes:
            resolution_steps.append(
                f"Cross-reference historical fix: {historical_fixes[0]}"
            )

        developer_suggestions = [
            f"Focus on component: {bug.get('component') or 'unspecified'}.",
            f"Investigate exception: {(root_cause or {}).get('root_cause', 'see logs')}.",
        ]
        if similar:
            developer_suggestions.append(
                f"Reuse patterns from {len(similar)} similar past incidents."
            )

        confidence = int(min(96, 60 + len(historical_fixes) * 6 + (10 if template is not DEFAULT_TEMPLATE else 0)))

        summary = (
            f"Recommended: {recommended_fix} "
            f"(based on {len(historical_fixes)} historical fixes and pattern match)."
        )

        return {
            "recommended_fix": recommended_fix,
            "developer_suggestions": developer_suggestions,
            "resolution_steps": resolution_steps,
            "best_practices": BEST_PRACTICES,
            "historical_fixes": historical_fixes,
            "confidence": confidence,
            "summary": summary,
        }


def run_remediation(bug, root_cause=None, similar=None):
    return RemediationAgent().analyze(bug, root_cause=root_cause, similar=similar)
