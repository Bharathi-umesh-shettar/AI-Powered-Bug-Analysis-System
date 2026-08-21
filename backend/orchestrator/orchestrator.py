"""Multi-Agent Orchestrator for the Intelligent Bug Diagnosis Platform.

Runs the complete bug-analysis pipeline:

    Triage
        ↓
    Log Analysis
        ↓
    Root Cause Analysis
        ↓
    Duplicate Detection
        ↓
    Remediation

The orchestrator combines all agent results into one structured
analysis object that can be used by the Flask API, dashboard,
reports, tests, and database layer.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..agents import (
    run_triage,
    run_log_analysis,
    run_root_cause,
    run_duplicate_detection,
    run_remediation,
)

from .. import database as db


# =============================================================================
# Utility helpers
# =============================================================================

def _utc_now():
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_dict(value):
    """Return a dictionary even if an agent returns None or another type."""
    if isinstance(value, dict):
        return value

    return {}


def _safe_list(value):
    """Return a list even if the supplied value is None or another type."""
    if isinstance(value, list):
        return value

    if value is None:
        return []

    return [value]


# =============================================================================
# Orchestrator
# =============================================================================

class Orchestrator:
    """Run all bug-analysis agents in a controlled sequence."""

    def __init__(self):
        self.pipeline = [
            "triage",
            "log_analysis",
            "root_cause",
            "duplicate_detection",
            "remediation",
        ]

    # -------------------------------------------------------------------------
    # Main pipeline
    # -------------------------------------------------------------------------

    def run(
        self,
        bug: Dict[str, Any],
        similar: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Run the complete multi-agent analysis pipeline."""

        if not isinstance(bug, dict):
            bug = {}

        if similar is None:
            similar = []

        stage_times: Dict[str, float] = {}

        # =====================================================================
        # 1. TRIAGE
        # =====================================================================

        start = time.time()

        try:
            triage = run_triage(
                bug,
                similar=similar,
            )
            triage = _safe_dict(triage)
        except Exception as exc:
            triage = {
                "severity": bug.get("severity") or "Medium",
                "priority": "Medium",
                "affected_component": bug.get("component") or "Unknown",
                "confidence": 0,
                "reasoning": f"Triage failed: {exc}",
            }

        stage_times["triage"] = round(
            time.time() - start,
            3,
        )

        # =====================================================================
        # 2. LOG ANALYSIS
        # =====================================================================

        start = time.time()

        try:
            log = run_log_analysis(
                stack_trace=bug.get("stack_trace", "") or "",
                error_log=bug.get("error_log", "") or "",
            )
            log = _safe_dict(log)
        except Exception as exc:
            log = {
                "exception_type": "",
                "failure_point": "",
                "affected_file": "",
                "function_name": "",
                "line_number": "",
                "affected_code_path": "",
                "structured_summary": f"Log analysis failed: {exc}",
                "language": "",
            }

        stage_times["log_analysis"] = round(
            time.time() - start,
            3,
        )

        # =====================================================================
        # 3. ROOT CAUSE ANALYSIS
        # =====================================================================

        start = time.time()

        try:
            root = run_root_cause(
                bug,
                log_analysis=log,
                similar=similar,
            )
            root = _safe_dict(root)
        except Exception as exc:
            root = {
                "root_cause": "Unable to determine root cause.",
                "confidence": 0,
                "supporting_evidence": [],
                "historical_refs": [],
                "error": str(exc),
            }

        stage_times["root_cause"] = round(
            time.time() - start,
            3,
        )

        # =====================================================================
        # 4. DUPLICATE DETECTION
        # =====================================================================

        start = time.time()

        try:
            dup = run_duplicate_detection(
                bug,
                top_k=5,
            )
            dup = _safe_dict(dup)

        except Exception as exc:
            # Duplicate detection must never stop the complete pipeline.
            dup = {
                "is_duplicate": False,
                "duplicate_of": None,
                "top_similarity_pct": 0,
                "matches": [],
                "error": str(exc),
            }

        stage_times["duplicate_detection"] = round(
            time.time() - start,
            3,
        )

        # =====================================================================
        # 5. REMEDIATION
        # =====================================================================

        start = time.time()

        try:
            remed = run_remediation(
                bug,
                root_cause=root,
                similar=similar,
            )
            remed = _safe_dict(remed)

        except Exception as exc:
            remed = {
                "recommended_fix": "Unable to generate a remediation recommendation.",
                "developer_suggestions": [],
                "resolution_steps": [],
                "best_practices": [],
                "historical_fixes": [],
                "confidence": 0,
                "error": str(exc),
            }

        stage_times["remediation"] = round(
            time.time() - start,
            3,
        )

        # =====================================================================
        # Duplicate information
        # =====================================================================

        duplicate_matches = _safe_list(
            dup.get("matches")
        )

        top_duplicate = (
            duplicate_matches[0]
            if duplicate_matches
            and isinstance(duplicate_matches[0], dict)
            else {}
        )

        historical_resolution = (
            top_duplicate.get("historical_resolution")
            or top_duplicate.get("resolution")
            or ""
        )

        # =====================================================================
        # Build final structured findings
        # =====================================================================

        analysis = {
            # -----------------------------------------------------------------
            # Bug information
            # -----------------------------------------------------------------

            "bug_id": bug.get("bug_id"),

            "title": bug.get("title", ""),
            "description": bug.get("description", ""),
            "error_message": bug.get("error_message", ""),
            "component": bug.get("component", ""),
            "environment": bug.get("environment", ""),
            "severity": (
                triage.get("severity")
                or bug.get("severity")
                or "Medium"
            ),

            # -----------------------------------------------------------------
            # Triage
            # -----------------------------------------------------------------

            "priority": triage.get(
                "priority",
                "Medium",
            ),

            "affected_component": triage.get(
                "affected_component",
                bug.get("component", ""),
            ),

            "confidence": triage.get(
                "confidence",
                0,
            ),

            "reasoning": triage.get(
                "reasoning",
                "",
            ),

            # -----------------------------------------------------------------
            # Log analysis
            # -----------------------------------------------------------------

            "exception_type": log.get(
                "exception_type",
                "",
            ),

            "failure_point": log.get(
                "failure_point",
                "",
            ),

            "affected_file": log.get(
                "affected_file",
                "",
            ),

            "function_name": log.get(
                "function_name",
                "",
            ),

            "line_number": log.get(
                "line_number",
                "",
            ),

            "affected_code_path": log.get(
                "affected_code_path",
                "",
            ),

            "structured_summary": log.get(
                "structured_summary",
                "",
            ),

            "language": log.get(
                "language",
                "",
            ),

            # -----------------------------------------------------------------
            # Root cause
            # -----------------------------------------------------------------

            "root_cause": root.get(
                "root_cause",
                "",
            ),

            "root_cause_confidence": root.get(
                "confidence",
                0,
            ),

            "supporting_evidence": _safe_list(
                root.get("supporting_evidence")
            ),

            "historical_refs": _safe_list(
                root.get("historical_refs")
            ),

            # -----------------------------------------------------------------
            # Duplicate detection
            # -----------------------------------------------------------------

            "is_duplicate": bool(
                dup.get("is_duplicate", False)
            ),

            "duplicate_bug_id": dup.get(
                "duplicate_of"
            ),

            "duplicate_of": dup.get(
                "duplicate_of"
            ),

            "duplicate_similarity": dup.get(
                "top_similarity_pct",
                0,
            ),

            "duplicate_score": dup.get(
                "top_similarity_pct",
                0,
            ),

            "duplicate_matches": duplicate_matches,

            "historical_reference": historical_resolution,

            # -----------------------------------------------------------------
            # Resolution
            # -----------------------------------------------------------------

            "resolution_summary": (
                remed.get("resolution_summary")
                or historical_resolution
                or root.get("resolution_summary", "")
            ),

            "recommendation": remed.get(
                "recommended_fix",
                remed.get(
                    "recommendation",
                    "",
                ),
            ),

            "recommended_fix": remed.get(
                "recommended_fix",
                "",
            ),

            "developer_suggestions": _safe_list(
                remed.get("developer_suggestions")
            ),

            "resolution_steps": _safe_list(
                remed.get("resolution_steps")
            ),

            "best_practices": _safe_list(
                remed.get("best_practices")
            ),

            "historical_fixes": _safe_list(
                remed.get("historical_fixes")
            ),

            "remediation_confidence": remed.get(
                "confidence",
                0,
            ),

            # -----------------------------------------------------------------
            # Metadata
            # -----------------------------------------------------------------

            "similar_count": len(similar),

            "similar_bugs": similar,

            "stage_times": stage_times,

            "timestamp": _utc_now(),

            "analysis_timestamp": _utc_now(),
        }

        return analysis


# =============================================================================
# Public pipeline function
# =============================================================================

def run_pipeline(
    bug: Dict[str, Any],
    similar: Optional[List[Dict[str, Any]]] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Run the complete analysis pipeline.

    If ``persist=True`` and the bug has an ID, the analysis is saved
    through the database layer.
    """

    analysis = Orchestrator().run(
        bug,
        similar=similar,
    )

    # -------------------------------------------------------------------------
    # Save analysis using the database API that exists in database.py
    # -------------------------------------------------------------------------

    bug_id = bug.get("bug_id") if isinstance(bug, dict) else None

    if persist and bug_id:
        try:
            db.save_analysis(
                bug_id,
                analysis,
            )
        except Exception as exc:
            # Do not destroy a successful analysis merely because
            # database persistence failed.
            analysis["persistence_error"] = str(exc)

    return analysis