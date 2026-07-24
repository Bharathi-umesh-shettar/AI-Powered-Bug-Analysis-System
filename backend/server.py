"""Flask application factory and REST API routes."""
import csv
import io
import json
import os
from datetime import datetime

from flask import (
    Flask, jsonify, render_template, request, send_from_directory,
    Response, make_response,
)
from flask_cors import CORS
from werkzeug.utils import secure_filename

from . import database as db
from . import knowledge_base as kb
from .agents import (
    agents_as_dict, run_root_cause, run_duplicate_detection, run_remediation,
    run_log_analysis,
)
from .orchestrator import run_pipeline
from .validation import run_validation_suite
from .config import ALLOWED_UPLOAD_EXT, MAX_UPLOAD_MB, UPLOAD_DIR
from . import watcher as watcher_mod



def create_app() -> Flask:
    template_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "frontend", "templates")
    )
    static_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "frontend", "static")
    )
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    CORS(app)

    # -------------------- Pages --------------------
    @app.route("/")
    def index():
        return render_template("index.html")

    # -------------------- REST APIs ----------------
    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})

    @app.route("/submit-bug", methods=["POST"])
    def submit_bug():
        try:
            data = request.get_json(silent=True) or {}
        except Exception:
            return jsonify({"error": "Invalid JSON"}), 400

        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        if not title:
            return jsonify({"error": "Missing title"}), 400
        if not description:
            return jsonify({"error": "Missing description"}), 400

        try:
            bug_id = db.insert_bug(data)
            db.update_bug_embedding_status(bug_id, "ok")
        except Exception as e:
            return jsonify({"error": f"Database error: {e}"}), 500

        query_text = f"{title}. {description} {data.get('component','')}"
        similar = kb.find_similar(query_text, top_k=5)

        # Milestone 2 — multi-agent orchestration
        bug_record = {**data, "bug_id": bug_id}
        analysis = run_pipeline(bug_record, similar=similar, persist=True)

        return jsonify(
            {
                "bug_id": bug_id,
                "similar_bugs": similar,
                "count": len(similar),
                "analysis": analysis,
            }
        )


    @app.route("/upload-bug", methods=["POST"])
    def upload_bug():
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        f = request.files["file"]
        if not f.filename:
            return jsonify({"error": "Empty filename"}), 400
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXT:
            return jsonify({"error": f"Wrong file type: {ext}"}), 400

        filename = secure_filename(f.filename)
        path = os.path.join(UPLOAD_DIR, filename)
        f.save(path)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
        except Exception as e:
            return jsonify({"error": f"Read error: {e}"}), 500

        title = request.form.get("title") or filename
        description = request.form.get("description") or content[:500]
        data = {
            "title": title,
            "description": description,
            "severity": request.form.get("severity", "Medium"),
            "category": request.form.get("category", "General"),
            "component": request.form.get("component", ""),
            "reporter": request.form.get("reporter", "uploader"),
            "stack_trace": content if "trace" in filename.lower() else "",
            "error_log": content if "log" in filename.lower() else content,
        }
        bug_id = db.insert_bug(data)
        db.update_bug_embedding_status(bug_id, "ok")

        query_text = f"{title}. {description}"
        similar = kb.find_similar(query_text, top_k=5)
        bug_record = {**data, "bug_id": bug_id}
        analysis = run_pipeline(bug_record, similar=similar, persist=True)
        return jsonify(
            {
                "bug_id": bug_id,
                "similar_bugs": similar,
                "count": len(similar),
                "analysis": analysis,
            }
        )

    @app.route("/all-bugs", methods=["GET"])
    def all_bugs():
        return jsonify({"bugs": db.fetch_all_bugs()})

    @app.route("/knowledge-base", methods=["GET"])
    def knowledge_base_endpoint():
        limit = request.args.get("limit", type=int)
        return jsonify({"knowledge_base": db.fetch_knowledge_base(limit=limit)})

    @app.route("/analysis/<int:bug_id>", methods=["GET"])
    def analysis_for_bug(bug_id):
        row = db.fetch_analysis_for_bug(bug_id)
        if not row:
            return jsonify({"error": "No analysis found for this bug"}), 404
        return jsonify({"analysis": row})

    @app.route("/analyses", methods=["GET"])
    def analyses_endpoint():
        limit = request.args.get("limit", default=10, type=int)
        return jsonify({"analyses": db.fetch_recent_analyses(limit=limit)})

    @app.route("/validate", methods=["POST", "GET"])
    def validate_endpoint():
        return jsonify(run_validation_suite())

    @app.route("/stats", methods=["GET"])
    def stats():
        return jsonify(
            {
                "total_bugs": db.count_bugs(),
                "critical_bugs": db.count_critical_bugs(),
                "kb_records": db.count_kb(),
                "duplicate_bugs": db.count_duplicate_bugs(),
                "analyses": db.count_analyses(),
                "recent_bugs": db.fetch_recent_bugs(limit=5),
                "recent_analyses": db.fetch_recent_analyses(limit=5),
            }
        )


    @app.route("/agents", methods=["GET"])
    def agents():
        return jsonify({"agents": agents_as_dict()})

    # -------------------- Milestone 3 endpoints ----
    @app.route("/dashboard-summary", methods=["GET"])
    def dashboard_summary():
        return jsonify(db.dashboard_summary())

    @app.route("/structured-findings/<int:bug_id>", methods=["GET"])
    def structured_findings(bug_id):
        bug = db.fetch_bug(bug_id)
        if not bug:
            return jsonify({"error": "Bug not found"}), 404
        analysis = db.fetch_analysis_for_bug(bug_id)
        similar = kb.find_similar(
            f"{bug.get('title','')}. {bug.get('description','')}", top_k=5
        )
        if not analysis:
            analysis = run_pipeline({**bug, "bug_id": bug_id},
                                    similar=similar, persist=True)
        else:
            for key in ("supporting_evidence", "best_practices"):
                v = analysis.get(key)
                if isinstance(v, str):
                    try:
                        analysis[key] = json.loads(v)
                    except Exception:
                        analysis[key] = [v] if v else []
            if analysis.get("payload_json"):
                try:
                    payload = json.loads(analysis["payload_json"])
                    payload.update({k: v for k, v in analysis.items() if v is not None})
                    analysis = payload
                except Exception:
                    pass
        return jsonify({"bug": bug, "analysis": analysis, "similar_bugs": similar})

    @app.route("/root-cause", methods=["POST"])
    def root_cause_endpoint():
        data = request.get_json(silent=True) or {}
        bug_id = data.get("bug_id")
        bug = db.fetch_bug(int(bug_id)) if bug_id else data
        bug = bug or {}
        log = run_log_analysis(bug.get("stack_trace", ""), bug.get("error_log", ""))
        similar = kb.find_similar(
            f"{bug.get('title','')}. {bug.get('description','')}", top_k=5
        )
        return jsonify(run_root_cause(bug, log_analysis=log, similar=similar))

    @app.route("/duplicate-check", methods=["POST"])
    def duplicate_check_endpoint():
        data = request.get_json(silent=True) or {}
        bug_id = data.get("bug_id")
        if bug_id:
            bug = db.fetch_bug(int(bug_id)) or {}
            bug["bug_id"] = int(bug_id)
        else:
            bug = data
        return jsonify(run_duplicate_detection(bug, top_k=int(data.get("top_k", 5))))

    @app.route("/recommendation", methods=["POST"])
    def recommendation_endpoint():
        data = request.get_json(silent=True) or {}
        bug_id = data.get("bug_id")
        bug = db.fetch_bug(int(bug_id)) if bug_id else data
        bug = bug or {}
        log = run_log_analysis(bug.get("stack_trace", ""), bug.get("error_log", ""))
        similar = kb.find_similar(
            f"{bug.get('title','')}. {bug.get('description','')}", top_k=5
        )
        root = run_root_cause(bug, log_analysis=log, similar=similar)
        return jsonify(run_remediation(bug, root_cause=root, similar=similar))

    @app.route("/search", methods=["GET"])
    def search_endpoint():
        q = request.args.get("q", "").strip()
        field = request.args.get("field", "any")
        limit = request.args.get("limit", default=50, type=int)
        if not q:
            return jsonify({"results": [], "count": 0})
        rows = db.search_bugs(q, field=field, limit=limit)
        return jsonify({"results": rows, "count": len(rows), "query": q, "field": field})

    @app.route("/report/<int:bug_id>", methods=["GET"])
    def report_page(bug_id):
        return render_template("report.html", bug_id=bug_id)

    # -------------------- Export --------------------
    @app.route("/export/<int:bug_id>.json", methods=["GET"])
    def export_json(bug_id):
        bug = db.fetch_bug(bug_id)
        if not bug:
            return jsonify({"error": "Bug not found"}), 404
        analysis = db.fetch_analysis_for_bug(bug_id) or {}
        payload = {"bug": bug, "analysis": analysis,
                   "exported_at": datetime.utcnow().isoformat(timespec="seconds")}
        resp = make_response(json.dumps(payload, indent=2, default=str))
        resp.headers["Content-Type"] = "application/json"
        resp.headers["Content-Disposition"] = f"attachment; filename=bug_{bug_id}_report.json"
        return resp

    @app.route("/export/<int:bug_id>.csv", methods=["GET"])
    def export_csv(bug_id):
        bug = db.fetch_bug(bug_id)
        if not bug:
            return jsonify({"error": "Bug not found"}), 404
        analysis = db.fetch_analysis_for_bug(bug_id) or {}
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["Field", "Value"])
        for k, v in {**bug, **{f"analysis_{k}": v for k, v in analysis.items()}}.items():
            writer.writerow([k, str(v)[:2000]])
        resp = make_response(out.getvalue())
        resp.headers["Content-Type"] = "text/csv"
        resp.headers["Content-Disposition"] = f"attachment; filename=bug_{bug_id}_report.csv"
        return resp

    @app.route("/export/<int:bug_id>.pdf", methods=["GET"])
    def export_pdf(bug_id):
        bug = db.fetch_bug(bug_id)
        if not bug:
            return jsonify({"error": "Bug not found"}), 404
        analysis = db.fetch_analysis_for_bug(bug_id) or {}
        try:
            from reportlab.lib.pagesizes import LETTER
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        except Exception:
            html = render_template("report.html", bug_id=bug_id)
            resp = make_response(html)
            resp.headers["Content-Type"] = "text/html"
            return resp

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=LETTER)
        styles = getSampleStyleSheet()
        story = [Paragraph(f"Bug Report #{bug_id}", styles["Title"]), Spacer(1, 12)]
        story.append(Paragraph(f"<b>Title:</b> {bug.get('title','')}", styles["Normal"]))
        story.append(Paragraph(f"<b>Reporter:</b> {bug.get('reporter','')}", styles["Normal"]))
        story.append(Paragraph(f"<b>Severity:</b> {bug.get('severity','')}", styles["Normal"]))
        story.append(Paragraph(f"<b>Component:</b> {bug.get('component','')}", styles["Normal"]))
        story.append(Spacer(1, 10))
        story.append(Paragraph("<b>Description</b>", styles["Heading2"]))
        story.append(Paragraph((bug.get("description") or "").replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 10))
        story.append(Paragraph("<b>AI Analysis</b>", styles["Heading2"]))
        for k in ("root_cause", "recommendation", "structured_summary",
                  "exception_type", "failure_point", "resolution_summary"):
            v = analysis.get(k)
            if v:
                story.append(Paragraph(f"<b>{k}:</b> {v}", styles["Normal"]))
        doc.build(story)
        resp = make_response(buf.getvalue())
        resp.headers["Content-Type"] = "application/pdf"
        resp.headers["Content-Disposition"] = f"attachment; filename=bug_{bug_id}_report.pdf"
        return resp

    # -------------------- Folder Watcher -----------
    @app.route("/watcher/status", methods=["GET"])
    def watcher_status():
        return jsonify(watcher_mod.watcher_status())

    @app.route("/watcher/scan", methods=["POST", "GET"])
    def watcher_scan():
        new_items = watcher_mod.scan_now()
        return jsonify({"new": new_items, "count": len(new_items)})

    @app.route("/watcher/start", methods=["POST"])
    def watcher_start():
        watcher_mod.start_watcher()
        return jsonify(watcher_mod.watcher_status())

    @app.route("/watcher/stop", methods=["POST"])
    def watcher_stop():
        watcher_mod.stop_watcher()
        return jsonify(watcher_mod.watcher_status())

    # -------------------- Error handlers -----------
    @app.errorhandler(413)
    def too_large(_):
        return jsonify({"error": f"File exceeds {MAX_UPLOAD_MB} MB"}), 413

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": f"Server error: {e}"}), 500

    return app
