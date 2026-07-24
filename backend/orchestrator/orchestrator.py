"""Multi-Agent Orchestrator (Milestones 2 + 3).

Runs the full agent pipeline for every submitted bug:
    Triage → Log Analysis → Root Cause → Duplicate Detection → Remediation
and returns a combined "structured findings" record that the API + UI
render together.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..agents import (
    run_triage,
    run_log_analysis,
    run_root_cause,
    run_duplicate_detection,
    run_remediation,
)
from .. import database as db


class Orchestrator:
    def __init__(self):
        self.pipeline = [
            "triage", "log_analysis", "root_cause",
            "duplicate_detection", "remediation",
        ]

    def run(
        self,
        bug: Dict[str, Any],
        similar: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        stage_times: Dict[str, float] = {}

        t0 = time.time()
        triage = run_triage(bug, similar=similar)
        stage_times["triage"] = round(time.time() - t0, 3)

        t0 = time.time()
        log = run_log_analysis(
            stack_trace=bug.get("stack_trace", ""),
            error_log=bug.get("error_log", ""),
        )
        stage_times["log_analysis"] = round(time.time() - t0, 3)

        t0 = time.time()
        root = run_root_cause(bug, log_analysis=log, similar=similar)
        stage_times["root_cause"] = round(time.time() - t0, 3)

        t0 = time.time()
        try:
            dup = run_duplicate_detection(bug, top_k=5)
        except Exception as e:  # never fail the pipeline on dup errors
            dup = {"is_duplicate": False, "duplicate_of": None,
                   "top_similarity_pct": 0, "matches": [], "error": str(e)}
        stage_times["duplicate_detection"] = round(time.time() - t0, 3)

        t0 = time.time()
        remed = run_remediation(bug, root_cause=root, similar=similar)
        stage_times["remediation"] = round(time.time() - t0, 3)

        top_dup = (dup.get("matches") or [None])[0]

        combined = {
            "bug_id": bug.get("bug_id"),
            # Triage
            "severity": triage["severity"],
            "priority": triage["priority"],
            "affected_component": triage["affected_component"],
            "confidence": triage["confidence"],
            "reasoning": triage["reasoning"],
            # Log
            "exception_type": log["exception_type"],
            "failure_point": log["failure_point"],
            "affected_file": log["affected_file"],
            "function_name": log["function_name"],
            "line_number": log["line_number"],
            "affected_code_path": log["affected_code_path"],
            "structured_summary": log["structured_summary"],
            "language": log["language"],
            # Root cause
            "root_cause": root["root_cause"],
            "root_cause_confidence": root["confidence"],
            "supporting_evidence": root["supporting_evidence"],
            "historical_refs": root["historical_refs"],
            # Duplicates
            "is_duplicate": dup.get("is_duplicate", False),
            "duplicate_bug_id": dup.get("duplicate_of"),
            "duplicate_similarity": dup.get("top_similarity_pct", 0),
            "duplicate_matches": dup.get("matches", []),
            "historical_reference": (top_dup or {}).get("historical_resolution", ""),
            "resolution_summary": (top_dup or {}).get("historical_resolution", ""),
            # Remediation
            "recommendation": remed["recommended_fix"],
            "developer_suggestions": remed["developer_suggestions"],
            "resolution_steps": remed["resolution_steps"],
            "best_practices": remed["best_practices"],
            "historical_fixes": remed["historical_fixes"],
            "remediation_confidence": remed["confidence"],
            # Meta
            "similar_count": len(similar or []),
            "stage_times": stage_times,
            "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
            "analysis_timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        }
        return combined


def run_pipeline(
    bug: Dict[str, Any],
    similar: Optional[List[Dict[str, Any]]] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    analysis = Orchestrator().run(bug, similar=similar)
    if persist and bug.get("bug_id"):
        db.insert_analysis(analysis)
    return analysis
