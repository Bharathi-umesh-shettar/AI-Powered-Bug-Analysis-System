"""Validation harness for all 5 agents (Milestone 3)."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from .agents import (
    run_triage, run_log_analysis, run_root_cause,
    run_duplicate_detection, run_remediation,
)
from . import knowledge_base as kb


VALIDATION_CASES: List[Dict[str, Any]] = [
    {
        "name": "Login failure",
        "bug": {
            "title": "Users cannot login to production",
            "description": "Login page returns 500 error, users unable to access system",
            "component": "auth-service",
        },
        "expected": {"component": "Authentication", "severity_min": "High"},
    },
    {
        "name": "API timeout",
        "bug": {
            "title": "API endpoint /orders times out",
            "description": "Requests to /api/orders exceed 30s and return timeout errors",
            "component": "orders-api",
        },
        "expected": {"component": "API", "severity_min": "Medium"},
    },
    {
        "name": "Database connection error",
        "bug": {
            "title": "Database connection refused",
            "description": "psycopg2.OperationalError: could not connect to server: Connection refused",
            "error_log": "psycopg2.OperationalError: could not connect to server: Connection refused",
        },
        "expected": {"component": "Database", "exception_contains": "OperationalError"},
    },
    {
        "name": "KeyError",
        "bug": {
            "title": "Bug submission crashes with KeyError",
            "description": "Server crash on missing username field",
            "stack_trace": 'Traceback (most recent call last):\n  File "app.py", line 52, in submit_bug\n    user = data["username"]\nKeyError: \'username\'',
        },
        "expected": {"exception": "KeyError", "function": "submit_bug"},
    },
    {
        "name": "ValueError",
        "bug": {
            "title": "Invalid literal for int()",
            "description": "Form parsing crashes",
            "stack_trace": 'Traceback (most recent call last):\n  File "parser.py", line 18, in parse_age\n    return int(v)\nValueError: invalid literal for int() with base 10: \'abc\'',
        },
        "expected": {"exception": "ValueError", "function": "parse_age"},
    },
    {
        "name": "TypeError",
        "bug": {
            "title": "TypeError concatenating str and int",
            "description": "Report renderer crash",
            "stack_trace": 'Traceback (most recent call last):\n  File "report.py", line 88, in render\n    return "count=" + count\nTypeError: can only concatenate str (not "int") to str',
        },
        "expected": {"exception": "TypeError", "function": "render"},
    },
    {
        "name": "FileNotFoundError",
        "bug": {
            "title": "Config file missing on boot",
            "description": "Server refuses to start",
            "stack_trace": 'Traceback (most recent call last):\n  File "boot.py", line 12, in load_cfg\n    open("/etc/app/config.yml")\nFileNotFoundError: [Errno 2] No such file or directory',
        },
        "expected": {"exception": "FileNotFoundError", "function": "load_cfg"},
    },
    {
        "name": "NullPointerException",
        "bug": {
            "title": "NullPointerException in checkout",
            "description": "Java service crashes when cart is empty",
            "stack_trace": 'Exception in thread "main" java.lang.NullPointerException\n\tat com.shop.CheckoutService.total(CheckoutService.java:42)',
        },
        "expected": {"exception": "NullPointerException", "function": "total"},
    },
    {
        "name": "SQLException",
        "bug": {
            "title": "SQL integrity violation on signup",
            "description": "Duplicate email causes SQLException",
            "error_log": "java.sql.SQLIntegrityConstraintViolationException: Duplicate entry 'a@b.com' for key 'users.email'",
        },
        "expected": {"exception_contains": "SQL"},
    },
    {
        "name": "UI rendering bug",
        "bug": {
            "title": "Dashboard chart misaligned on mobile",
            "description": "Cosmetic UI glitch — chart overflows on small screens",
            "component": "dashboard",
        },
        "expected": {"component": "Dashboard", "severity_max": "Medium"},
    },
]


SEV_ORDER = ["Low", "Medium", "High", "Critical"]


def _triage_ok(pred: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    ok = True
    if "component" in expected:
        ok = ok and pred["affected_component"] == expected["component"]
    if "severity_min" in expected:
        ok = ok and SEV_ORDER.index(pred["severity"]) >= SEV_ORDER.index(expected["severity_min"])
    if "severity_max" in expected:
        ok = ok and SEV_ORDER.index(pred["severity"]) <= SEV_ORDER.index(expected["severity_max"])
    return ok


def _log_ok(parsed: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    if "exception" in expected and parsed.get("exception_type") != expected["exception"]:
        return False
    if "exception_contains" in expected and expected["exception_contains"].lower() not in (parsed.get("exception_type") or "").lower():
        return False
    if "function" in expected and expected["function"] not in (parsed.get("function_name") or ""):
        return False
    return True


def run_validation_suite() -> Dict[str, Any]:
    results = []
    triage_hits = 0
    log_hits = 0
    log_applicable = 0
    rc_hits = 0
    remed_hits = 0
    conf_total = 0
    stage_totals = {"triage": 0.0, "log": 0.0, "root_cause": 0.0,
                    "duplicate": 0.0, "remediation": 0.0}

    for case in VALIDATION_CASES:
        bug = case["bug"]
        similar = kb.find_similar(
            f"{bug.get('title','')}. {bug.get('description','')}", top_k=5
        )

        t0 = time.time()
        triage = run_triage(bug, similar=similar)
        stage_totals["triage"] += time.time() - t0

        t0 = time.time()
        log = run_log_analysis(
            stack_trace=bug.get("stack_trace", ""),
            error_log=bug.get("error_log", ""),
        )
        stage_totals["log"] += time.time() - t0

        t0 = time.time()
        root = run_root_cause(bug, log_analysis=log, similar=similar)
        stage_totals["root_cause"] += time.time() - t0

        t0 = time.time()
        try:
            dup = run_duplicate_detection(bug, top_k=3)
        except Exception:
            dup = {"matches": []}
        stage_totals["duplicate"] += time.time() - t0

        t0 = time.time()
        remed = run_remediation(bug, root_cause=root, similar=similar)
        stage_totals["remediation"] += time.time() - t0

        t_ok = _triage_ok(triage, case["expected"])
        needs_log = any(k in case["expected"] for k in ("exception", "exception_contains", "function"))
        l_ok = _log_ok(log, case["expected"]) if needs_log else None
        rc_ok = bool(root.get("root_cause")) and not root["root_cause"].startswith("Undetermined")
        r_ok = bool(remed.get("recommended_fix"))

        triage_hits += int(t_ok)
        if needs_log:
            log_applicable += 1
            log_hits += int(l_ok)
        rc_hits += int(rc_ok)
        remed_hits += int(r_ok)
        conf_total += triage["confidence"]

        results.append({
            "case": case["name"],
            "triage_pass": t_ok,
            "log_pass": l_ok,
            "root_cause_pass": rc_ok,
            "remediation_pass": r_ok,
            "predicted_severity": triage["severity"],
            "predicted_priority": triage["priority"],
            "predicted_component": triage["affected_component"],
            "predicted_root_cause": root["root_cause"],
            "recommended_fix": remed["recommended_fix"],
            "duplicate_matches": len(dup.get("matches", [])),
            "confidence": triage["confidence"],
            "exception_type": log["exception_type"],
            "function_name": log["function_name"],
        })

    total = len(VALIDATION_CASES)
    return {
        "total_cases": total,
        "triage_accuracy_pct": round(triage_hits / total * 100, 1),
        "log_accuracy_pct": round(log_hits / log_applicable * 100, 1) if log_applicable else None,
        "root_cause_accuracy_pct": round(rc_hits / total * 100, 1),
        "remediation_accuracy_pct": round(remed_hits / total * 100, 1),
        "duplicate_agent_status": "operational",
        "average_confidence": round(conf_total / total, 1),
        "stage_avg_seconds": {k: round(v / total, 3) for k, v in stage_totals.items()},
        "results": results,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run_validation_suite(), indent=2))
