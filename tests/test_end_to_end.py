"""End-to-end tests (Milestone 4.3) — five distinct bug types.

Coverage per bug type: ingestion (manual JSON, .txt upload, Auto-Watch folder),
structured findings from the agent pipeline, similar-bug retrieval, duplicate
detection, status workflow, knowledge-base growth for verified fixes, defect
pattern analytics, and report exports.
"""
import json
import os
import shutil

import pytest

FIVE_BUGS = [
    {
        "key": "database",
        "channel": "manual",
        "payload": {
            "title": "Inventory sync job deadlocks on stock_levels table",
            "description": (
                "The nightly inventory sync fails halfway through. Two workers "
                "update stock_levels in a different order and deadlock, leaving "
                "stock counts stale until the job is re-run manually."
            ),
            "severity": "Critical",
            "component": "Database",
            "environment": "Production",
            "error_message": "OperationalError: deadlock detected",
            "stack_trace": (
                'File "backend/inventory/sync.py", line 140, in apply_batch\n'
                "    cursor.execute(UPDATE_STOCK, params)\n"
                "psycopg2.errors.DeadlockDetected: deadlock detected"
            ),
        },
    },
    {
        "key": "authentication",
        "channel": "upload",
        "file": "bug_auth_token.txt",
    },
    {
        "key": "frontend",
        "channel": "upload",
        "file": "bug_ui_render.txt",
    },
    {
        "key": "performance",
        "channel": "watch",
        "file": "bug_performance_export.log",
    },
    {
        "key": "integration",
        "channel": "watch",
        "file": "bug_api_integration.log",
    },
]

STATE = {}


def _findings_are_structured(findings):
    for field in ("bug_summary", "error_types", "component",
                  "possible_root_cause", "recommended_fix", "similar_bugs",
                  "duplicate", "duplicate_status", "remediation", "rag"):
        assert field in findings, f"missing findings field: {field}"
    assert findings["possible_root_cause"].strip()
    assert findings["recommended_fix"].strip()
    assert isinstance(findings["similar_bugs"], list)


# --------------------------------------------------------------------------- #
# Boot / Milestone 1 contracts
# --------------------------------------------------------------------------- #
def test_health_and_meta(client):
    assert client.get("/health").data.decode() == "Bug Analysis System Running"
    meta = client.get("/api/meta").get_json()
    assert meta["rag"]["entries"] > 0, "knowledge base did not seed from the CSV"
    assert meta["rag"]["index_size"] == meta["rag"]["entries"]
    assert meta["top_k"] >= 1


def test_home_page_renders(client):
    body = client.get("/").data.decode()
    assert "Intelligent Bug Diagnosis Platform" in body


# --------------------------------------------------------------------------- #
# Milestone 1-3: five bug types through three ingestion channels
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case", FIVE_BUGS, ids=[c["key"] for c in FIVE_BUGS])
def test_bug_types_end_to_end(case, client, fixtures_dir, watch_dir, flask_app):
    if case["channel"] == "manual":
        res = client.post("/submit-bug", json=case["payload"])
        assert res.status_code == 200, res.data
        body = res.get_json()
        bug, findings = body["bug"], body["findings"]
    elif case["channel"] == "upload":
        path = os.path.join(fixtures_dir, case["file"])
        with open(path, "rb") as fh:
            res = client.post("/upload-bug", data={"file": (fh, case["file"])},
                              content_type="multipart/form-data")
        assert res.status_code == 200, res.data
        body = res.get_json()
        bug, findings = body["bug"], body["findings"]
    else:  # Auto-Watch folder monitoring
        shutil.copy(os.path.join(fixtures_dir, case["file"]), watch_dir)
        summary = flask_app.watcher.scan_once()
        match = [p for p in summary["processed"] if p["file_name"] == case["file"]]
        assert match, f"Auto-Watch did not process {case['file']}: {summary}"
        bug_id = match[0]["bug_id"]
        detail = client.get(f"/api/bugs/{bug_id}").get_json()
        bug, findings = detail["bug"], detail["findings"]

    assert bug["title"].strip()
    assert bug["severity"] in ("Critical", "High", "Medium", "Low")
    assert bug["status"] in ("Open", "In Progress")
    _findings_are_structured(findings)
    STATE[case["key"]] = bug["id"]


def test_validation_rejects_bad_submission(client):
    res = client.post("/submit-bug", json={"title": "x", "description": "short"})
    assert res.status_code == 400
    assert res.get_json()["errors"]


def test_upload_rejects_unsupported_type(client):
    res = client.post("/upload-bug",
                      data={"file": (open(__file__, "rb"), "notes.pdf")},
                      content_type="multipart/form-data")
    assert res.status_code == 400


def test_all_bugs_and_search(client):
    assert len(client.get("/all-bugs").get_json()["bugs"]) >= len(FIVE_BUGS)
    filtered = client.get("/api/bugs?q=deadlock").get_json()
    assert filtered["count"] >= 1


def test_similarity_endpoint(client):
    res = client.post("/api/similar", json={"query": "database deadlock timeout",
                                            "k": 3})
    hits = res.get_json()["similar_bugs"]
    assert 1 <= len(hits) <= 3
    assert all("similarity" in h for h in hits)


def test_duplicate_detection_flags_resubmission(client):
    original = FIVE_BUGS[0]["payload"]
    res = client.post("/submit-bug", json=dict(original))
    findings = res.get_json()["findings"]
    assert findings["duplicate_status"]
    assert findings["duplicate"]["confidence"] >= 0


# --------------------------------------------------------------------------- #
# Milestone 4.2: knowledge base growth (verified fixes only)
# --------------------------------------------------------------------------- #
def test_unverified_bug_cannot_be_promoted(client):
    bug_id = STATE["frontend"]
    res = client.post(f"/api/bugs/{bug_id}/promote", json={})
    assert res.status_code == 409
    assert "verified" in res.get_json()["error"].lower()


def test_resolved_and_verified_bug_grows_knowledge_base(client):
    before = client.get("/api/knowledge").get_json()["count"]
    bug_id = STATE["database"]
    res = client.post(f"/api/bugs/{bug_id}/resolve", json={
        "root_cause": "Workers updated stock_levels rows in inconsistent order.",
        "confirmed_fix": "Order updates by primary key and retry on deadlock.",
        "resolution_details": "Deployed in release 4.12; sync completed cleanly.",
        "verified": True,
        "promote": True,
    })
    assert res.status_code == 200, res.data
    body = res.get_json()
    assert body["bug"]["status"] == "Resolved & Verified"
    assert body["promotion"]

    after = client.get("/api/knowledge").get_json()
    assert after["count"] == before + 1
    assert after["rag"]["index_size"] == after["count"]

    hits = client.post("/api/similar", json={
        "query": "stock_levels deadlock detected during inventory sync", "k": 5,
    }).get_json()["similar_bugs"]
    assert any("stock_levels" in json.dumps(h).lower() for h in hits), \
        "promoted fix is not retrievable from the FAISS index"


def test_promotion_is_idempotent(client):
    res = client.post(f"/api/bugs/{STATE['database']}/promote", json={})
    assert res.status_code in (200, 409)


def test_status_workflow(client):
    bug_id = STATE["integration"]
    assert client.post(f"/api/bugs/{bug_id}/status",
                       json={"status": "Resolved"}).status_code == 200
    assert client.post(f"/api/bugs/{bug_id}/status",
                       json={"status": "Nope"}).status_code == 400


def test_reanalysis_is_repeatable(client):
    res = client.post(f"/api/bugs/{STATE['performance']}/analyze", json={})
    assert res.status_code == 200
    _findings_are_structured(res.get_json()["findings"])


# --------------------------------------------------------------------------- #
# Milestone 4.1: defect pattern analytics
# --------------------------------------------------------------------------- #
def test_analytics_reflect_real_data(client):
    report = client.get("/api/analytics").get_json()
    kpis = report["kpis"]
    assert kpis["total_defects"] >= len(FIVE_BUGS)
    assert kpis["knowledge_base_entries"] >= 1
    assert report["severity"]
    assert report["components"]
    assert report["trend"]["points"]
    assert report["recent"]
    total_by_severity = sum(r["count"] for r in report["severity"])
    assert total_by_severity == kpis["total_defects"]


# --------------------------------------------------------------------------- #
# Milestone 3/4: exports
# --------------------------------------------------------------------------- #
def test_bug_reports_export(client):
    bug_id = STATE["database"]
    csv_res = client.get(f"/api/bugs/{bug_id}/report.csv")
    assert csv_res.status_code == 200
    assert csv_res.data.startswith(b"Section,Field,Value")
    assert b"Bug,Title" in csv_res.data

    pdf_res = client.get(f"/api/bugs/{bug_id}/report.pdf")
    assert pdf_res.status_code in (200, 501)
    if pdf_res.status_code == 200:
        assert pdf_res.data.startswith(b"%PDF")


def test_analytics_exports(client):
    assert client.get("/api/analytics/report.csv").status_code == 200
    pdf = client.get("/api/analytics/report.pdf")
    assert pdf.status_code in (200, 501)
    if pdf.status_code == 200:
        assert pdf.data.startswith(b"%PDF")


def test_bulk_bug_export(client):
    res = client.get("/api/bugs/export.csv")
    assert res.status_code == 200
    assert len(res.data.splitlines()) >= len(FIVE_BUGS) + 1


# --------------------------------------------------------------------------- #
# Milestone 2: Auto-Watch bookkeeping
# --------------------------------------------------------------------------- #
def test_watch_status_and_rescan_skips_known_files(client, flask_app):
    status = client.get("/api/watch/status").get_json()
    assert status["directory"]
    assert status["events"]
    again = flask_app.watcher.scan_once()
    assert again["skipped"], "already-processed files were not skipped"
    assert not again["processed"]
