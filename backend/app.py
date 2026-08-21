"""Flask entry point — Creation of Intelligent Bug Diagnosis Platform
with Fix Recommendation Assistance (Group 1).

Milestone coverage:
  M1  bug submission, SQLite storage, RAG retrieval (FAISS + MiniLM)
  M2  validation, .txt/.log upload, Auto-Watch folder monitoring
  M3  multi-agent diagnosis -> structured findings, PDF/CSV reports
  M4  defect pattern analytics, knowledge-base growth for verified fixes
All Milestone 1 routes (/, /health, /submit-bug, /upload-bug, /all-bugs) keep
their original contracts so earlier demos and scripts still work.
"""
import os

from flask import Flask, Response, jsonify, render_template, request

import analytics
import reports
from config import APP_GROUP, APP_TITLE, PROJECT_ROOT, SEVERITIES, STATUSES, TOP_K
from agents import DiagnosisPipeline
from autowatch import AutoWatcher
from database import (
    fetch_all_bugs,
    fetch_all_knowledge,
    fetch_bug,
    init_db,
    now_iso,
    search_bugs,
    update_bug,
)
from ingest import parse_bug_text, validate_bug_fields
from knowledge import KnowledgeGrowthError, is_eligible, promote_to_knowledge_base, \
    resolve_and_verify
from rag import BugRAG
from service import diagnose_bug, ingest_and_diagnose

app = Flask(
    __name__,
    template_folder=os.path.join(PROJECT_ROOT, "templates"),
    static_folder=os.path.join(PROJECT_ROOT, "static"),
)

init_db()

# Seed the knowledge base from the historical dataset on first run only.
if not fetch_all_knowledge():
    try:
        from import_dataset import import_csv
        import_csv()
    except Exception as exc:
        print(f"[warn] dataset import skipped: {exc}")

rag = BugRAG()
pipeline = DiagnosisPipeline(rag)
watcher = AutoWatcher(pipeline)
if os.environ.get("AUTOWATCH_ON_START", "1") == "1":
    watcher.start()


def _fail(message, code=400):
    return jsonify({"error": message}), code


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@app.route("/")
def home():
    if request.args.get("format") == "json" or \
            request.accept_mimetypes.best == "application/json":
        return "Bug Analysis System Running"
    return render_template("index.html", app_title=APP_TITLE, app_group=APP_GROUP,
                           severities=SEVERITIES, statuses=STATUSES)


@app.route("/health")
def health():
    return "Bug Analysis System Running"


@app.route("/api/meta")
def meta():
    return jsonify({
        "title": APP_TITLE, "group": APP_GROUP,
        "rag": rag.stats(), "top_k": TOP_K,
        "severities": list(SEVERITIES), "statuses": list(STATUSES),
        "auto_watch": {"running": watcher.running, "directory": watcher.directory},
    })


# --------------------------------------------------------------------------- #
# Milestone 1 + 3: submission and diagnosis
# --------------------------------------------------------------------------- #
@app.route("/submit-bug", methods=["POST"])
def submit_bug():
    try:
        data = request.get_json(force=True, silent=True) or {}
        cleaned, errors = validate_bug_fields(data)
        if errors:
            return jsonify({"error": " ".join(errors), "errors": errors}), 400

        bug, findings = ingest_and_diagnose(cleaned, pipeline, source="manual")
        return jsonify({
            "message": "Bug submitted successfully",
            "bug": bug,
            "findings": findings,
            "similar_bugs": findings["similar_bugs"],
        })
    except Exception as exc:
        return _fail(str(exc), 500)


@app.route("/upload-bug", methods=["POST"])
def upload_bug():
    try:
        if "file" not in request.files:
            return _fail("no file uploaded (field name must be 'file')")
        f = request.files["file"]
        if not f.filename or not f.filename.lower().endswith((".txt", ".log")):
            return _fail("only .txt and .log files are supported")
        text = f.read().decode("utf-8", errors="ignore")
        if not text.strip():
            return _fail("uploaded file is empty")
        fields = parse_bug_text(text, file_name=f.filename)
        bug, findings = ingest_and_diagnose(fields, pipeline, source="upload",
                                            source_file=f.filename)
        return jsonify({
            "message": "Bug uploaded successfully",
            "bug": bug,
            "findings": findings,
            "similar_bugs": findings["similar_bugs"],
        })
    except Exception as exc:
        return _fail(str(exc), 500)


@app.route("/all-bugs", methods=["GET"])
def all_bugs():
    try:
        return jsonify({"bugs": fetch_all_bugs()})
    except Exception as exc:
        return _fail(str(exc), 500)


@app.route("/api/bugs", methods=["GET"])
def api_bugs():
    try:
        bugs = search_bugs(
            query=request.args.get("q"),
            status=request.args.get("status"),
            severity=request.args.get("severity"),
            component=request.args.get("component"),
        )
        return jsonify({"count": len(bugs), "bugs": bugs})
    except Exception as exc:
        return _fail(str(exc), 500)


@app.route("/api/bugs/<int:bug_id>", methods=["GET"])
def api_bug(bug_id):
    bug = fetch_bug(bug_id)
    if not bug:
        return _fail(f"bug #{bug_id} not found", 404)
    eligible, reason = is_eligible(bug)
    return jsonify({"bug": bug, "findings": bug.get("findings"),
                    "kb_eligible": eligible, "kb_reason": reason})


@app.route("/api/bugs/<int:bug_id>/analyze", methods=["POST"])
def api_analyze(bug_id):
    try:
        bug, findings = diagnose_bug(bug_id, pipeline)
        return jsonify({"message": "Analysis complete", "bug": bug,
                        "findings": findings})
    except ValueError as exc:
        return _fail(str(exc), 404)
    except Exception as exc:
        return _fail(str(exc), 500)


@app.route("/api/bugs/<int:bug_id>/status", methods=["POST"])
def api_status(bug_id):
    try:
        data = request.get_json(force=True, silent=True) or {}
        status = (data.get("status") or "").strip()
        if status not in STATUSES:
            return _fail(f"status must be one of {', '.join(STATUSES)}")
        if not fetch_bug(bug_id):
            return _fail(f"bug #{bug_id} not found", 404)
        update_bug(bug_id, status=status)
        return jsonify({"message": "Status updated", "bug": fetch_bug(bug_id)})
    except Exception as exc:
        return _fail(str(exc), 500)


@app.route("/api/similar", methods=["POST"])
def api_similar():
    try:
        data = request.get_json(force=True, silent=True) or {}
        query = (data.get("query") or "").strip()
        if not query:
            return _fail("query is required")
        return jsonify({"similar_bugs": rag.search_similar_bugs(
            query, k=int(data.get("k") or TOP_K))})
    except Exception as exc:
        return _fail(str(exc), 500)


# --------------------------------------------------------------------------- #
# Milestone 4.2: knowledge base growth
# --------------------------------------------------------------------------- #
@app.route("/api/bugs/<int:bug_id>/resolve", methods=["POST"])
def api_resolve(bug_id):
    """Mark resolved (+ optionally verified) and grow the knowledge base."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        verified = bool(data.get("verified", True))
        bug = resolve_and_verify(
            bug_id,
            root_cause=(data.get("root_cause") or "").strip() or None,
            confirmed_fix=(data.get("confirmed_fix") or "").strip() or None,
            resolution_details=(data.get("resolution_details") or "").strip() or None,
            verified=verified,
        )
        payload = {"message": "Bug updated", "bug": bug, "promotion": None}
        if verified and data.get("promote", True):
            payload["promotion"] = promote_to_knowledge_base(bug_id, rag)
            payload["bug"] = fetch_bug(bug_id)
            payload["message"] = ("Bug resolved, verified and added to the "
                                  "knowledge base")
        return jsonify(payload)
    except KnowledgeGrowthError as exc:
        return _fail(str(exc), 409)
    except Exception as exc:
        return _fail(str(exc), 500)


@app.route("/api/bugs/<int:bug_id>/promote", methods=["POST"])
def api_promote(bug_id):
    try:
        return jsonify({"message": "Knowledge base updated",
                        "promotion": promote_to_knowledge_base(bug_id, rag),
                        "bug": fetch_bug(bug_id)})
    except KnowledgeGrowthError as exc:
        return _fail(str(exc), 409)
    except Exception as exc:
        return _fail(str(exc), 500)


@app.route("/api/knowledge", methods=["GET"])
def api_knowledge():
    entries = fetch_all_knowledge()
    q = (request.args.get("q") or "").strip().lower()
    if q:
        entries = [e for e in entries
                   if q in " ".join(str(v).lower() for v in e.values())]
    return jsonify({"count": len(entries), "entries": entries,
                    "rag": rag.stats()})


# --------------------------------------------------------------------------- #
# Milestone 2: Auto-Watch
# --------------------------------------------------------------------------- #
@app.route("/api/watch/status", methods=["GET"])
def api_watch_status():
    return jsonify(watcher.status())


@app.route("/api/watch/scan", methods=["POST"])
def api_watch_scan():
    try:
        return jsonify(watcher.scan_once())
    except Exception as exc:
        return _fail(str(exc), 500)


@app.route("/api/watch/start", methods=["POST"])
def api_watch_start():
    watcher.start()
    return jsonify({"message": "Auto-Watch started", "status": watcher.status()})


@app.route("/api/watch/stop", methods=["POST"])
def api_watch_stop():
    watcher.stop()
    return jsonify({"message": "Auto-Watch stopped", "running": watcher.running})


# --------------------------------------------------------------------------- #
# Milestone 4.1: analytics
# --------------------------------------------------------------------------- #
@app.route("/api/analytics", methods=["GET"])
def api_analytics():
    try:
        return jsonify(analytics.full_report(request.args.get("granularity")))
    except Exception as exc:
        return _fail(str(exc), 500)


# --------------------------------------------------------------------------- #
# Milestone 3/4: exports
# --------------------------------------------------------------------------- #
def _download(data, filename, mimetype):
    return Response(data, mimetype=mimetype, headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


@app.route("/api/bugs/<int:bug_id>/report.pdf", methods=["GET"])
def api_bug_pdf(bug_id):
    bug = fetch_bug(bug_id)
    if not bug:
        return _fail(f"bug #{bug_id} not found", 404)
    try:
        data = reports.findings_to_pdf(bug, bug.get("findings"), now_iso())
        return _download(data, f"bug_{bug_id}_report.pdf", "application/pdf")
    except reports.ReportError as exc:
        return _fail(str(exc), 501)


@app.route("/api/bugs/<int:bug_id>/report.csv", methods=["GET"])
def api_bug_csv(bug_id):
    bug = fetch_bug(bug_id)
    if not bug:
        return _fail(f"bug #{bug_id} not found", 404)
    return _download(reports.findings_to_csv(bug, bug.get("findings")),
                     f"bug_{bug_id}_report.csv", "text/csv")


@app.route("/api/bugs/export.csv", methods=["GET"])
def api_bugs_csv():
    return _download(reports.bugs_to_csv(fetch_all_bugs()),
                     "all_bugs.csv", "text/csv")


@app.route("/api/analytics/report.pdf", methods=["GET"])
def api_analytics_pdf():
    try:
        data = reports.analytics_to_pdf(analytics.full_report(), now_iso())
        return _download(data, "defect_pattern_analytics.pdf", "application/pdf")
    except reports.ReportError as exc:
        return _fail(str(exc), 501)


@app.route("/api/analytics/report.csv", methods=["GET"])
def api_analytics_csv():
    return _download(reports.analytics_to_csv(analytics.full_report()),
                     "defect_pattern_analytics.csv", "text/csv")


if __name__ == "__main__":
    print(f"{APP_TITLE} — {APP_GROUP}")
    app.run(host="0.0.0.0", port=5000, debug=True)
