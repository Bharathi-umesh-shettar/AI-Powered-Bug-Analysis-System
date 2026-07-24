"""Triage Agent (Milestone 2).

Predicts Severity, Priority, Affected Component, Confidence and Reasoning
for an incoming bug report. Uses transparent keyword + heuristic rules
combined with signals from RAG-retrieved similar historical bugs so it
runs entirely offline without an LLM dependency.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Keyword vocabularies
# ---------------------------------------------------------------------------
SEVERITY_KEYWORDS = {
    "Critical": [
        "crash", "outage", "data loss", "corrupt", "cannot login", "cannot log in",
        "unable to login", "production down", "system down", "not responding",
        "security breach", "sql injection", "xss", "payment failed", "500",
        "segfault", "kernel panic", "deadlock", "fatal",
    ],
    "High": [
        "login fail", "authentication fail", "cannot access", "broken", "error",
        "exception", "timeout", "unauthorized", "forbidden", "regression",
        "blocker", "500 error", "database error", "connection refused",
        "null pointer", "nullpointer", "stack trace",
    ],
    "Medium": [
        "slow", "delay", "warning", "unexpected", "sometimes", "occasionally",
        "intermittent", "wrong", "incorrect", "misaligned",
    ],
    "Low": [
        "typo", "cosmetic", "ui glitch", "minor", "spelling", "color", "padding",
        "alignment", "hover", "tooltip", "label",
    ],
}

COMPONENT_KEYWORDS = {
    "Authentication": ["login", "logout", "signup", "sign in", "sign up", "auth",
                       "password", "token", "jwt", "session", "oauth", "2fa"],
    "Payment": ["payment", "checkout", "stripe", "paypal", "refund", "invoice",
                "billing", "charge", "subscription"],
    "Database": ["database", "sql", "query", "postgres", "mysql", "sqlite",
                 "mongo", "deadlock", "migration", "schema"],
    "API": ["api", "endpoint", "rest", "graphql", "request", "response",
            "http 4", "http 5", "webhook"],
    "Frontend": ["frontend", "react", "vue", "angular", "component", "render",
                 "css", "html", "javascript", "typescript"],
    "Backend": ["backend", "server", "flask", "django", "spring", "node",
                "express", "microservice"],
    "Dashboard": ["dashboard", "chart", "graph", "widget", "kpi", "analytics"],
    "UI": ["ui", "button", "modal", "dropdown", "layout", "responsive", "mobile"],
    "Search": ["search", "filter", "autocomplete", "query bar", "faceted"],
    "Notifications": ["notification", "email", "sms", "push", "alert", "toast"],
    "Security": ["security", "xss", "csrf", "injection", "encryption", "leak",
                 "vulnerability", "breach"],
}

SEVERITY_TO_PRIORITY = {
    "Critical": "P1",
    "High": "P2",
    "Medium": "P3",
    "Low": "P4",
}

SEVERITY_ORDER = ["Low", "Medium", "High", "Critical"]


def _score_keywords(text: str, vocab: Dict[str, List[str]]) -> Dict[str, int]:
    text_l = text.lower()
    scores: Dict[str, int] = {label: 0 for label in vocab}
    for label, kws in vocab.items():
        for kw in kws:
            if kw in text_l:
                scores[label] += 1
    return scores


def _pick_top(scores: Dict[str, int], default: str) -> str:
    best_label, best_score = default, 0
    for label, score in scores.items():
        if score > best_score:
            best_label, best_score = label, score
    return best_label


def _blend_with_similar(
    base: str,
    similar: Optional[List[Dict[str, Any]]],
    field: str,
) -> str:
    """If retrieved similar bugs strongly agree on a value, promote it."""
    if not similar:
        return base
    values = [s.get(field) for s in similar if s.get(field)]
    if not values:
        return base
    top_value, top_count = Counter(values).most_common(1)[0]
    # Only override when historical evidence is strong (majority of top-K).
    if top_count >= max(2, len(values) // 2 + 1):
        return top_value
    return base


class TriageAgent:
    """Predicts severity, priority, component + confidence + reasoning."""

    name = "Triage Agent"

    def analyze(
        self,
        bug: Dict[str, Any],
        similar: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        title = bug.get("title", "") or ""
        description = bug.get("description", "") or ""
        component_hint = bug.get("component", "") or ""
        steps = bug.get("steps_to_reproduce", "") or ""
        expected = bug.get("expected_behavior", "") or ""
        actual = bug.get("actual_behavior", "") or ""
        environment = bug.get("environment", "") or ""
        stack = bug.get("stack_trace", "") or ""
        logs = bug.get("error_log", "") or ""
        user_severity = bug.get("severity") or "Medium"

        combined = " ".join([
            title, description, component_hint, steps, expected, actual,
            environment, stack, logs,
        ])

        sev_scores = _score_keywords(combined, SEVERITY_KEYWORDS)
        comp_scores = _score_keywords(combined, COMPONENT_KEYWORDS)

        predicted_severity = _pick_top(sev_scores, default=user_severity)
        # Never downgrade below what the user reported.
        if SEVERITY_ORDER.index(user_severity) > SEVERITY_ORDER.index(predicted_severity):
            predicted_severity = user_severity

        predicted_component = _pick_top(comp_scores, default=component_hint or "Backend")

        # Blend with historical evidence.
        predicted_severity = _blend_with_similar(predicted_severity, similar, "severity")
        predicted_component = _blend_with_similar(predicted_component, similar, "component")

        priority = SEVERITY_TO_PRIORITY.get(predicted_severity, "P3")

        # Confidence: signal strength normalized + agreement with history.
        top_sev = max(sev_scores.values()) if sev_scores else 0
        top_comp = max(comp_scores.values()) if comp_scores else 0
        base_conf = 55 + min(25, top_sev * 5) + min(15, top_comp * 3)
        if similar:
            avg_sim = sum(s.get("similarity_pct", 0) for s in similar) / len(similar)
            base_conf += min(10, avg_sim / 10)
        confidence = int(max(50, min(99, base_conf)))

        reasoning = self._build_reasoning(
            predicted_severity, priority, predicted_component,
            sev_scores, comp_scores, similar,
        )

        return {
            "severity": predicted_severity,
            "priority": priority,
            "affected_component": predicted_component,
            "confidence": confidence,
            "reasoning": reasoning,
        }

    @staticmethod
    def _build_reasoning(sev, prio, comp, sev_scores, comp_scores, similar):
        matched_sev = [k for k, v in sev_scores.items() if v > 0]
        matched_comp = [k for k, v in comp_scores.items() if v > 0]
        parts = [
            f"Predicted severity {sev} (priority {prio}) for the {comp} component.",
        ]
        if matched_sev:
            parts.append(f"Severity signals matched: {', '.join(matched_sev)}.")
        if matched_comp:
            parts.append(f"Component signals matched: {', '.join(matched_comp)}.")
        if similar:
            parts.append(
                f"Cross-checked against {len(similar)} similar historical bugs; "
                f"top match at {similar[0].get('similarity_pct', 0)}% similarity."
            )
        if sev in ("Critical", "High"):
            parts.append("Impact assessed as blocking core user-facing functionality.")
        return " ".join(parts)


def run_triage(bug: Dict[str, Any], similar=None) -> Dict[str, Any]:
    return TriageAgent().analyze(bug, similar=similar)
