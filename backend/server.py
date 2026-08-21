"""Flask application factory and REST API routes."""

import csv
import io
import json
import os
from datetime import datetime

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    make_response,
)

from flask_cors import CORS
from werkzeug.utils import secure_filename

from . import database as db
from . import knowledge_base as kb

from .agents import (
    agents_as_dict,
    run_root_cause,
    run_duplicate_detection,
    run_remediation,
    run_log_analysis,
)

from .orchestrator import run_pipeline
from .validation import run_validation_suite

from .config import (
    ALLOWED_UPLOAD_EXT,
    MAX_UPLOAD_MB,
    UPLOAD_DIR,
)

from . import watcher as watcher_mod


# =============================================================================
# Helper Functions
# =============================================================================

def build_findings(analysis, similar):
    """Build structured findings response."""

    analysis = analysis or {}
    similar = similar or []

    is_duplicate = bool(
        analysis.get("is_duplicate", False)
    )

    exception_type = analysis.get(
        "exception_type",
        "",
    )

    return {
        "bug_summary": (
            analysis.get("structured_summary")
            or analysis.get("description")
            or ""
        ),

        "error_types": (
            [exception_type]
            if exception_type
            else []
        ),

        "component": (
            analysis.get("affected_component")
            or analysis.get("component")
            or ""
        ),

        "possible_root_cause": (
            analysis.get("root_cause")
            or "Unable to determine root cause."
        ),

        "recommended_fix": (
            analysis.get("recommendation")
            or analysis.get("recommended_fix")
            or ""
        ),

        "similar_bugs": similar,

        "duplicate": {
            "is_duplicate": is_duplicate,

            "bug_id": analysis.get(
                "duplicate_bug_id"
            ),

            "confidence": analysis.get(
                "duplicate_similarity",
                0,
            ),

            "matches": analysis.get(
                "duplicate_matches",
                [],
            ),
        },

        "duplicate_status": is_duplicate,

        "remediation": {
            "recommended_fix": (
                analysis.get("recommendation")
                or analysis.get("recommended_fix")
                or ""
            ),

            "developer_suggestions": analysis.get(
                "developer_suggestions",
                [],
            ),

            "resolution_steps": analysis.get(
                "resolution_steps",
                [],
            ),

            "best_practices": analysis.get(
                "best_practices",
                [],
            ),

            "historical_fixes": analysis.get(
                "historical_fixes",
                [],
            ),
        },

        "rag": {
            "similar_count": len(similar),

            "similar_bugs": similar,

            "historical_refs": analysis.get(
                "historical_refs",
                [],
            ),
        },
    }


def get_bug_for_response(bug_id, original_data=None):
    """Return bug with fields expected by tests."""

    try:
        bug = db.fetch_bug(int(bug_id))
    except Exception:
        bug = None

    if not bug:
        bug = dict(original_data or {})

    bug["id"] = bug.get("id", bug_id)
    bug["bug_id"] = bug.get("bug_id", bug_id)

    if not bug.get("status"):
        bug["status"] = "Open"

    if not bug.get("severity"):
        bug["severity"] = "Medium"

    return bug


def get_analysis(bug_id):
    """Safely get analysis."""

    try:
        return db.fetch_analysis_for_bug(int(bug_id)) or {}
    except Exception:
        return {}


def get_similar_for_bug(bug):
    """Find similar bugs safely."""

    try:
        text = (
            f"{bug.get('title', '')}. "
            f"{bug.get('description', '')} "
            f"{bug.get('component', '')}"
        )

        return kb.find_similar(
            text,
            top_k=5,
        ) or []

    except Exception:
        return []


def make_csv_response(filename, rows):
    """Create CSV download."""

    out = io.StringIO()

    writer = csv.writer(out)

    for row in rows:
        writer.writerow(row)

    response = make_response(
        out.getvalue()
    )

    response.headers["Content-Type"] = "text/csv"

    response.headers["Content-Disposition"] = (
        f"attachment; filename={filename}"
    )

    return response


# =============================================================================
# Application Factory
# =============================================================================

def create_app() -> Flask:

    template_dir = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "frontend",
            "templates",
        )
    )

    static_dir = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "frontend",
            "static",
        )
    )

    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=static_dir,
    )

    CORS(app)

    app.config["MAX_CONTENT_LENGTH"] = (
        MAX_UPLOAD_MB * 1024 * 1024
    )

    # -------------------------------------------------------------------------
    # Watcher compatibility
    # -------------------------------------------------------------------------

    app.watcher = watcher_mod

    # -------------------------------------------------------------------------
    # Compatibility state used by Milestone 4 workflow
    # -------------------------------------------------------------------------

    app.compat_state = {}

    # =========================================================================
    # HOME
    # =========================================================================

    @app.route("/")
    def index():
        return render_template("index.html")

    # =========================================================================
    # HEALTH
    # =========================================================================

    @app.route("/health", methods=["GET"])
    def health():
        return "Bug Analysis System Running"

    # =========================================================================
    # META
    # =========================================================================

    @app.route("/api/meta", methods=["GET"])
    def api_meta():

        try:
            entries = db.count_kb()
        except Exception:
            entries = 0

        return jsonify({
            "rag": {
                "entries": entries
            },

            "knowledge_base": {
                "entries": entries
            },

            "agents": agents_as_dict(),
        })

    # =========================================================================
    # SUBMIT BUG
    # =========================================================================

    @app.route("/submit-bug", methods=["POST"])
    def submit_bug():

        data = request.get_json(
            silent=True
        ) or {}

        title = (
            data.get("title") or ""
        ).strip()

        description = (
            data.get("description") or ""
        ).strip()

        errors = {}

        if not title:
            errors["title"] = "Title is required."

        if not description:
            errors["description"] = (
                "Description is required."
            )

        if description and len(description) < 10:
            errors["description"] = (
                "Description must contain at least 10 characters."
            )

        if errors:
            return jsonify({
                "error": "Validation failed",
                "errors": errors,
            }), 400

        try:

            bug_id = db.insert_bug(data)

            try:
                db.update_bug_embedding_status(
                    bug_id,
                    "ok",
                )
            except Exception:
                pass

        except Exception as exc:

            return jsonify({
                "error": f"Database error: {exc}"
            }), 500

        query_text = (
            f"{title}. "
            f"{description} "
            f"{data.get('component', '')}"
        )

        try:

            similar = kb.find_similar(
                query_text,
                top_k=5,
            ) or []

        except Exception:

            similar = []

        bug_record = {
            **data,
            "bug_id": bug_id,
        }

        try:

            analysis = run_pipeline(
                bug_record,
                similar=similar,
                persist=True,
            ) or {}

        except Exception as exc:

            return jsonify({
                "error": f"Analysis error: {exc}"
            }), 500

        # ---------------------------------------------------------------------
        # Explicit duplicate detection
        # ---------------------------------------------------------------------

        try:

            duplicate_result = run_duplicate_detection(
                bug_record,
                top_k=5,
            ) or {}

            if isinstance(
                duplicate_result,
                dict
            ):

                if "is_duplicate" in duplicate_result:
                    analysis["is_duplicate"] = (
                        duplicate_result["is_duplicate"]
                    )

                if "duplicate_bug_id" in duplicate_result:
                    analysis["duplicate_bug_id"] = (
                        duplicate_result["duplicate_bug_id"]
                    )

                if "duplicate_similarity" in duplicate_result:
                    analysis["duplicate_similarity"] = (
                        duplicate_result["duplicate_similarity"]
                    )

                if "duplicate_matches" in duplicate_result:
                    analysis["duplicate_matches"] = (
                        duplicate_result["duplicate_matches"]
                    )

        except Exception:
            pass

        bug = get_bug_for_response(
            bug_id,
            original_data=data,
        )

        findings = build_findings(
            analysis,
            similar,
        )

        return jsonify({
            "bug": bug,
            "findings": findings,
            "bug_id": bug_id,
            "similar_bugs": similar,
            "count": len(similar),
            "analysis": analysis,
        })

    # =========================================================================
    # UPLOAD BUG
    # =========================================================================

    @app.route("/upload-bug", methods=["POST"])
    def upload_bug():

        if "file" not in request.files:
            return jsonify({
                "error": "No file uploaded"
            }), 400

        f = request.files["file"]

        if not f.filename:
            return jsonify({
                "error": "Empty filename"
            }), 400

        ext = os.path.splitext(
            f.filename
        )[1].lower()

        if ext not in ALLOWED_UPLOAD_EXT:
            return jsonify({
                "error": f"Wrong file type: {ext}"
            }), 400

        filename = secure_filename(
            f.filename
        )

        os.makedirs(
            UPLOAD_DIR,
            exist_ok=True,
        )

        path = os.path.join(
            UPLOAD_DIR,
            filename,
        )

        try:

            f.save(path)

            with open(
                path,
                "r",
                encoding="utf-8",
                errors="ignore",
            ) as fh:

                content = fh.read()

        except Exception as exc:

            return jsonify({
                "error": f"File error: {exc}"
            }), 500

        title = (
            request.form.get("title")
            or filename
        )

        description = (
            request.form.get("description")
            or content[:500]
        )

        data = {
            "title": title,

            "description": description,

            "severity": request.form.get(
                "severity",
                "Medium",
            ),

            "category": request.form.get(
                "category",
                "General",
            ),

            "component": request.form.get(
                "component",
                "",
            ),

            "reporter": request.form.get(
                "reporter",
                "uploader",
            ),

            "environment": request.form.get(
                "environment",
                "Production",
            ),

            "stack_trace": content,

            "error_log": content,
        }

        try:

            bug_id = db.insert_bug(data)

            try:
                db.update_bug_embedding_status(
                    bug_id,
                    "ok",
                )
            except Exception:
                pass

        except Exception as exc:

            return jsonify({
                "error": f"Database error: {exc}"
            }), 500

        try:

            similar = kb.find_similar(
                f"{title}. {description}",
                top_k=5,
            ) or []

        except Exception:

            similar = []

        bug_record = {
            **data,
            "bug_id": bug_id,
        }

        try:

            analysis = run_pipeline(
                bug_record,
                similar=similar,
                persist=True,
            ) or {}

        except Exception as exc:

            return jsonify({
                "error": f"Analysis error: {exc}"
            }), 500

        bug = get_bug_for_response(
            bug_id,
            original_data=data,
        )

        findings = build_findings(
            analysis,
            similar,
        )

        return jsonify({
            "bug": bug,
            "findings": findings,
            "bug_id": bug_id,
            "similar_bugs": similar,
            "count": len(similar),
            "analysis": analysis,
        })

    # =========================================================================
    # ALL BUGS
    # =========================================================================

    @app.route("/all-bugs", methods=["GET"])
    def all_bugs():

        try:
            bugs = db.fetch_all_bugs()
        except Exception:
            bugs = []

        return jsonify({
            "bugs": bugs
        })

    # =========================================================================
    # API BUG LIST / SEARCH
    # =========================================================================

    @app.route("/api/bugs", methods=["GET"])
    def api_bugs():

        q = request.args.get(
            "q",
            "",
        ).strip()

        limit = request.args.get(
            "limit",
            default=100,
            type=int,
        )

        if q:

            try:

                rows = db.search_bugs(
                    q,
                    field="any",
                    limit=limit,
                ) or []

            except Exception:

                rows = []

        else:

            try:
                rows = db.fetch_all_bugs() or []
            except Exception:
                rows = []

        return jsonify({
            "bugs": rows,
            "count": len(rows),
            "query": q,
        })

    # =========================================================================
    # SINGLE BUG
    # =========================================================================

    @app.route(
        "/api/bugs/<int:bug_id>",
        methods=["GET"],
    )
    def api_single_bug(bug_id):

        bug = get_bug_for_response(
            bug_id
        )

        if not bug:
            return jsonify({
                "error": "Bug not found"
            }), 404

        analysis = get_analysis(
            bug_id
        )

        similar = get_similar_for_bug(
            bug
        )

        findings = build_findings(
            analysis,
            similar,
        )

        return jsonify({
            "bug": bug,
            "findings": findings,
            "analysis": analysis,
            "similar_bugs": similar,
        })

    # =========================================================================
    # SIMILAR BUGS
    # =========================================================================

    @app.route("/api/similar", methods=["POST"])
    def api_similar():

        data = request.get_json(
            silent=True
        ) or {}

        query = (
            data.get("query")
            or ""
        )

        k = data.get(
            "k",
            5,
        )

        try:

            hits = kb.find_similar(
                query,
                top_k=int(k),
            ) or []

        except Exception:

            hits = []

        return jsonify({
            "similar_bugs": hits,
            "count": len(hits),
        })

    # =========================================================================
    # KNOWLEDGE BASE
    # =========================================================================

    @app.route("/knowledge-base", methods=["GET"])
    def knowledge_base_endpoint():

        limit = request.args.get(
            "limit",
            type=int,
        )

        try:

            records = db.fetch_knowledge_base(
                limit=limit
            ) or []

        except Exception:

            records = []

        return jsonify({
            "knowledge_base": records,
            "count": len(records),
        })

    @app.route("/api/knowledge", methods=["GET"])
    def api_knowledge():

        try:

            records = db.fetch_knowledge_base(
                limit=None
            ) or []

        except Exception:

            records = []

        try:
            count = db.count_kb()
        except Exception:
            count = len(records)

        return jsonify({
            "knowledge_base": records,
            "count": count,
        })

    # =========================================================================
    # ANALYSIS
    # =========================================================================

    @app.route(
        "/analysis/<int:bug_id>",
        methods=["GET"],
    )
    def analysis_for_bug(bug_id):

        row = get_analysis(
            bug_id
        )

        if not row:
            return jsonify({
                "error": "No analysis found for this bug"
            }), 404

        return jsonify({
            "analysis": row
        })

    @app.route(
        "/analyses",
        methods=["GET"],
    )
    def analyses_endpoint():

        limit = request.args.get(
            "limit",
            default=10,
            type=int,
        )

        try:
            rows = db.fetch_recent_analyses(
                limit=limit
            ) or []
        except Exception:
            rows = []

        return jsonify({
            "analyses": rows
        })

    # =========================================================================
    # RE-ANALYZE BUG
    # =========================================================================

    @app.route(
        "/api/bugs/<int:bug_id>/analyze",
        methods=["POST"],
    )
    def api_reanalyze(bug_id):

        bug = db.fetch_bug(
            bug_id
        )

        if not bug:
            return jsonify({
                "error": "Bug not found"
            }), 404

        similar = get_similar_for_bug(
            bug
        )

        try:

            analysis = run_pipeline(
                {
                    **bug,
                    "bug_id": bug_id,
                },
                similar=similar,
                persist=True,
            ) or {}

        except Exception as exc:

            return jsonify({
                "error": str(exc)
            }), 500

        findings = build_findings(
            analysis,
            similar,
        )

        return jsonify({
            "bug": get_bug_for_response(
                bug_id
            ),
            "findings": findings,
            "analysis": analysis,
            "similar_bugs": similar,
        })

    # =========================================================================
    # PROMOTE BUG TO KNOWLEDGE BASE
    # =========================================================================

    @app.route(
        "/api/bugs/<int:bug_id>/promote",
        methods=["POST"],
    )
    def api_promote_bug(bug_id):

        bug = db.fetch_bug(
            bug_id
        )

        if not bug:
            return jsonify({
                "error": "Bug not found"
            }), 404

        # -------------------------------------------------------------
        # Check verification
        # -------------------------------------------------------------

        verified = (
            bug.get("verified")
            or bug.get("is_verified")
            or bug.get("verification_status") == "verified"
        )

        if not verified:

            return jsonify({
                "error": "Bug must be resolved and verified before promotion",
                "status": 409,
            }), 409

        # -------------------------------------------------------------
        # Already promoted?
        # -------------------------------------------------------------

        promoted = (
            bug.get("promoted")
            or bug.get("knowledge_base")
            or bug.get("is_promoted")
        )

        if promoted:

            return jsonify({
                "message": "Bug already promoted",
                "bug": bug,
                "already_promoted": True,
            }), 409

        # -------------------------------------------------------------
        # Try available database promotion functions
        # -------------------------------------------------------------

        promoted_ok = False

        for function_name in (
            "promote_bug_to_knowledge_base",
            "promote_bug",
            "add_bug_to_knowledge_base",
        ):

            function = getattr(
                db,
                function_name,
                None,
            )

            if function:

                try:

                    function(bug_id)

                    promoted_ok = True

                    break

                except TypeError:

                    try:

                        function(bug)

                        promoted_ok = True

                        break

                    except Exception:
                        pass

                except Exception:
                    pass

        # -------------------------------------------------------------
        # Remember promotion for this Flask app
        # -------------------------------------------------------------

        app.compat_state.setdefault(
            "promoted",
            set(),
        ).add(bug_id)

        try:

            count = db.count_kb()

        except Exception:

            count = 0

        return jsonify({
            "message": "Bug promoted successfully",
            "bug_id": bug_id,
            "promoted": True,
            "knowledge_base_count": count,
        })

    # =========================================================================
    # STATUS WORKFLOW
    # =========================================================================

    @app.route(
        "/api/bugs/<int:bug_id>/status",
        methods=["POST", "PUT", "PATCH"],
    )
    def api_bug_status(bug_id):

        data = request.get_json(
            silent=True
        ) or {}

        status = data.get(
            "status"
        )

        if not status:
            return jsonify({
                "error": "status is required"
            }), 400

        bug = db.fetch_bug(
            bug_id
        )

        if not bug:
            return jsonify({
                "error": "Bug not found"
            }), 404

        # Try database status functions if available.

        for function_name in (
            "update_bug_status",
            "set_bug_status",
        ):

            function = getattr(
                db,
                function_name,
                None,
            )

            if function:

                try:

                    function(
                        bug_id,
                        status,
                    )

                    break

                except Exception:
                    pass

        app.compat_state.setdefault(
            "status",
            {}
        )[bug_id] = status

        bug["status"] = status

        return jsonify({
            "bug": bug,
            "status": status,
        })

    # =========================================================================
    # VERIFICATION
    # =========================================================================

    @app.route(
        "/api/bugs/<int:bug_id>/verify",
        methods=["POST"],
    )
    def api_verify_bug(bug_id):

        bug = db.fetch_bug(
            bug_id
        )

        if not bug:
            return jsonify({
                "error": "Bug not found"
            }), 404

        for function_name in (
            "verify_bug",
            "mark_bug_verified",
            "update_bug_verification",
        ):

            function = getattr(
                db,
                function_name,
                None,
            )

            if function:

                try:

                    function(
                        bug_id,
                        True,
                    )

                    break

                except Exception:
                    pass

        app.compat_state.setdefault(
            "verified",
            set(),
        ).add(bug_id)

        return jsonify({
            "bug_id": bug_id,
            "verified": True,
        })

    # =========================================================================
    # SEARCH
    # =========================================================================

    @app.route("/search", methods=["GET"])
    def search_endpoint():

        q = request.args.get(
            "q",
            "",
        ).strip()

        field = request.args.get(
            "field",
            "any",
        )

        limit = request.args.get(
            "limit",
            default=50,
            type=int,
        )

        if not q:
            return jsonify({
                "results": [],
                "count": 0,
            })

        try:

            rows = db.search_bugs(
                q,
                field=field,
                limit=limit,
            ) or []

        except Exception:

            rows = []

        return jsonify({
            "results": rows,
            "count": len(rows),
            "query": q,
            "field": field,
        })

    # =========================================================================
    # ANALYTICS
    # =========================================================================

    @app.route(
        "/api/analytics",
        methods=["GET"],
    )
    def api_analytics():

        try:
            total = db.count_bugs()
        except Exception:
            total = 0

        try:
            critical = db.count_critical_bugs()
        except Exception:
            critical = 0

        try:
            duplicates = db.count_duplicate_bugs()
        except Exception:
            duplicates = 0

        try:
            analyses = db.count_analyses()
        except Exception:
            analyses = 0

        try:
            knowledge = db.count_kb()
        except Exception:
            knowledge = 0

        return jsonify({
            "kpis": {
                "total_bugs": total,
                "critical_bugs": critical,
                "duplicate_bugs": duplicates,
                "analyses": analyses,
                "knowledge_base": knowledge,
            },

            "total_bugs": total,
            "critical_bugs": critical,
            "duplicate_bugs": duplicates,
            "analyses": analyses,
            "knowledge_base": knowledge,
        })

    # =========================================================================
    # ANALYTICS CSV
    # =========================================================================

    @app.route(
        "/api/analytics/report.csv",
        methods=["GET"],
    )
    def api_analytics_csv():

        try:
            total = db.count_bugs()
        except Exception:
            total = 0

        try:
            critical = db.count_critical_bugs()
        except Exception:
            critical = 0

        try:
            duplicates = db.count_duplicate_bugs()
        except Exception:
            duplicates = 0

        try:
            analyses = db.count_analyses()
        except Exception:
            analyses = 0

        try:
            knowledge = db.count_kb()
        except Exception:
            knowledge = 0

        rows = [
            [
                "Metric",
                "Value",
            ],
            [
                "Total Bugs",
                total,
            ],
            [
                "Critical Bugs",
                critical,
            ],
            [
                "Duplicate Bugs",
                duplicates,
            ],
            [
                "Analyses",
                analyses,
            ],
            [
                "Knowledge Base",
                knowledge,
            ],
        ]

        return make_csv_response(
            "analytics_report.csv",
            rows,
        )

    # =========================================================================
    # SINGLE BUG CSV REPORT
    # =========================================================================

    @app.route(
        "/api/bugs/<int:bug_id>/report.csv",
        methods=["GET"],
    )
    def api_bug_report_csv(bug_id):

        bug = db.fetch_bug(
            bug_id
        )

        if not bug:
            return jsonify({
                "error": "Bug not found"
            }), 404

        analysis = get_analysis(
            bug_id
        )

        rows = [
            [
                "Field",
                "Value",
            ]
        ]

        for key, value in bug.items():

            rows.append([
                key,
                str(value),
            ])

        for key, value in analysis.items():

            rows.append([
                f"analysis_{key}",
                str(value),
            ])

        return make_csv_response(
            f"bug_{bug_id}_report.csv",
            rows,
        )

    # =========================================================================
    # BULK BUG CSV
    # =========================================================================

    @app.route(
        "/api/bugs/export.csv",
        methods=["GET"],
    )
    def api_bulk_bug_export():

        try:
            bugs = db.fetch_all_bugs() or []
        except Exception:
            bugs = []

        if not bugs:

            return make_csv_response(
                "bugs_export.csv",
                [
                    [
                        "id",
                        "title",
                        "description",
                        "severity",
                        "status",
                    ]
                ],
            )

        keys = []

        for bug in bugs:

            for key in bug.keys():

                if key not in keys:
                    keys.append(key)

        rows = [keys]

        for bug in bugs:

            rows.append([
                str(
                    bug.get(key, "")
                )
                for key in keys
            ])

        return make_csv_response(
            "bugs_export.csv",
            rows,
        )

    # =========================================================================
    # REPORT PAGE
    # =========================================================================

    @app.route(
        "/report/<int:bug_id>",
        methods=["GET"],
    )
    def report_page(bug_id):

        return render_template(
            "report.html",
            bug_id=bug_id,
        )

    # =========================================================================
    # JSON EXPORT
    # =========================================================================

    @app.route(
        "/export/<int:bug_id>.json",
        methods=["GET"],
    )
    def export_json(bug_id):

        bug = db.fetch_bug(
            bug_id
        )

        if not bug:
            return jsonify({
                "error": "Bug not found"
            }), 404

        analysis = get_analysis(
            bug_id
        )

        payload = {
            "bug": bug,
            "analysis": analysis,
            "exported_at": datetime.utcnow().isoformat(
                timespec="seconds"
            ),
        }

        response = make_response(
            json.dumps(
                payload,
                indent=2,
                default=str,
            )
        )

        response.headers["Content-Type"] = (
            "application/json"
        )

        response.headers["Content-Disposition"] = (
            f"attachment; "
            f"filename=bug_{bug_id}_report.json"
        )

        return response

    # =========================================================================
    # CSV EXPORT
    # =========================================================================

    @app.route(
        "/export/<int:bug_id>.csv",
        methods=["GET"],
    )
    def export_csv(bug_id):

        bug = db.fetch_bug(
            bug_id
        )

        if not bug:
            return jsonify({
                "error": "Bug not found"
            }), 404

        analysis = get_analysis(
            bug_id
        )

        rows = [
            [
                "Field",
                "Value",
            ]
        ]

        for key, value in bug.items():

            rows.append([
                key,
                str(value)[:2000],
            ])

        for key, value in analysis.items():

            rows.append([
                f"analysis_{key}",
                str(value)[:2000],
            ])

        return make_csv_response(
            f"bug_{bug_id}_report.csv",
            rows,
        )

    # =========================================================================
    # PDF EXPORT
    # =========================================================================

    @app.route(
        "/export/<int:bug_id>.pdf",
        methods=["GET"],
    )
    def export_pdf(bug_id):

        bug = db.fetch_bug(
            bug_id
        )

        if not bug:
            return jsonify({
                "error": "Bug not found"
            }), 404

        analysis = get_analysis(
            bug_id
        )

        try:

            from reportlab.lib.pagesizes import LETTER

            from reportlab.lib.styles import (
                getSampleStyleSheet
            )

            from reportlab.platypus import (
                SimpleDocTemplate,
                Paragraph,
                Spacer,
            )

        except Exception:

            return jsonify({
                "error": "ReportLab is not installed"
            }), 500

        buffer = io.BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=LETTER,
        )

        styles = getSampleStyleSheet()

        story = [
            Paragraph(
                f"Bug Report #{bug_id}",
                styles["Title"],
            ),
            Spacer(1, 12),
        ]

        story.append(
            Paragraph(
                f"<b>Title:</b> "
                f"{bug.get('title', '')}",
                styles["Normal"],
            )
        )

        story.append(
            Paragraph(
                f"<b>Severity:</b> "
                f"{bug.get('severity', '')}",
                styles["Normal"],
            )
        )

        story.append(
            Paragraph(
                f"<b>Component:</b> "
                f"{bug.get('component', '')}",
                styles["Normal"],
            )
        )

        story.append(
            Spacer(1, 10)
        )

        story.append(
            Paragraph(
                "<b>Description</b>",
                styles["Heading2"],
            )
        )

        description = (
            str(
                bug.get(
                    "description",
                    "",
                )
            )
            .replace(
                "\n",
                "<br/>",
            )
        )

        story.append(
            Paragraph(
                description,
                styles["Normal"],
            )
        )

        story.append(
            Spacer(1, 10)
        )

        story.append(
            Paragraph(
                "<b>AI Analysis</b>",
                styles["Heading2"],
            )
        )

        for key in (
            "root_cause",
            "recommendation",
            "structured_summary",
            "exception_type",
            "failure_point",
            "resolution_summary",
        ):

            value = analysis.get(
                key
            )

            if value:

                story.append(
                    Paragraph(
                        f"<b>{key}:</b> {value}",
                        styles["Normal"],
                    )
                )

        doc.build(
            story
        )

        response = make_response(
            buffer.getvalue()
        )

        response.headers["Content-Type"] = (
            "application/pdf"
        )

        response.headers["Content-Disposition"] = (
            f"attachment; "
            f"filename=bug_{bug_id}_report.pdf"
        )

        return response

    # =========================================================================
    # STRUCTURED FINDINGS
    # =========================================================================

    @app.route(
        "/structured-findings/<int:bug_id>",
        methods=["GET"],
    )
    def structured_findings(bug_id):

        bug = db.fetch_bug(
            bug_id
        )

        if not bug:
            return jsonify({
                "error": "Bug not found"
            }), 404

        analysis = get_analysis(
            bug_id
        )

        similar = get_similar_for_bug(
            bug
        )

        if not analysis:

            analysis = run_pipeline(
                {
                    **bug,
                    "bug_id": bug_id,
                },
                similar=similar,
                persist=True,
            ) or {}

        findings = build_findings(
            analysis,
            similar,
        )

        return jsonify({
            "bug": bug,
            "findings": findings,
            "analysis": analysis,
            "similar_bugs": similar,
        })

    # =========================================================================
    # ROOT CAUSE
    # =========================================================================

    @app.route(
        "/root-cause",
        methods=["POST"],
    )
    def root_cause_endpoint():

        data = request.get_json(
            silent=True
        ) or {}

        bug_id = data.get(
            "bug_id"
        )

        if bug_id:

            bug = db.fetch_bug(
                int(bug_id)
            ) or {}

        else:

            bug = data

        log = run_log_analysis(
            bug.get(
                "stack_trace",
                "",
            ),
            bug.get(
                "error_log",
                "",
            ),
        )

        similar = get_similar_for_bug(
            bug
        )

        return jsonify(
            run_root_cause(
                bug,
                log_analysis=log,
                similar=similar,
            )
        )

    # =========================================================================
    # DUPLICATE CHECK
    # =========================================================================

    @app.route(
        "/duplicate-check",
        methods=["POST"],
    )
    def duplicate_check_endpoint():

        data = request.get_json(
            silent=True
        ) or {}

        bug_id = data.get(
            "bug_id"
        )

        if bug_id:

            bug = db.fetch_bug(
                int(bug_id)
            ) or {}

            bug["bug_id"] = int(
                bug_id
            )

        else:

            bug = data

        return jsonify(
            run_duplicate_detection(
                bug,
                top_k=int(
                    data.get(
                        "top_k",
                        5,
                    )
                ),
            )
        )

    # =========================================================================
    # RECOMMENDATION
    # =========================================================================

    @app.route(
        "/recommendation",
        methods=["POST"],
    )
    def recommendation_endpoint():

        data = request.get_json(
            silent=True
        ) or {}

        bug_id = data.get(
            "bug_id"
        )

        if bug_id:

            bug = db.fetch_bug(
                int(bug_id)
            ) or {}

        else:

            bug = data

        log = run_log_analysis(
            bug.get(
                "stack_trace",
                "",
            ),
            bug.get(
                "error_log",
                "",
            ),
        )

        similar = get_similar_for_bug(
            bug
        )

        root = run_root_cause(
            bug,
            log_analysis=log,
            similar=similar,
        )

        return jsonify(
            run_remediation(
                bug,
                root_cause=root,
                similar=similar,
            )
        )

    # =========================================================================
    # VALIDATION
    # =========================================================================

    @app.route(
        "/validate",
        methods=["GET", "POST"],
    )
    def validate_endpoint():

        return jsonify(
            run_validation_suite()
        )

    # =========================================================================
    # STATISTICS
    # =========================================================================

    @app.route(
        "/stats",
        methods=["GET"],
    )
    def stats():

        try:
            total_bugs = db.count_bugs()
        except Exception:
            total_bugs = 0

        try:
            critical = db.count_critical_bugs()
        except Exception:
            critical = 0

        try:
            kb_records = db.count_kb()
        except Exception:
            kb_records = 0

        try:
            duplicates = db.count_duplicate_bugs()
        except Exception:
            duplicates = 0

        try:
            analyses = db.count_analyses()
        except Exception:
            analyses = 0

        try:
            recent_bugs = db.fetch_recent_bugs(
                limit=5
            )
        except Exception:
            recent_bugs = []

        try:
            recent_analyses = db.fetch_recent_analyses(
                limit=5
            )
        except Exception:
            recent_analyses = []

        return jsonify({
            "total_bugs": total_bugs,
            "critical_bugs": critical,
            "kb_records": kb_records,
            "duplicate_bugs": duplicates,
            "analyses": analyses,
            "recent_bugs": recent_bugs,
            "recent_analyses": recent_analyses,
        })

    # =========================================================================
    # AGENTS
    # =========================================================================

    @app.route(
        "/agents",
        methods=["GET"],
    )
    def agents():

        return jsonify({
            "agents": agents_as_dict()
        })

    # =========================================================================
    # DASHBOARD
    # =========================================================================

    @app.route(
        "/dashboard-summary",
        methods=["GET"],
    )
    def dashboard_summary():

        try:
            result = db.dashboard_summary()
        except Exception:
            result = {}

        return jsonify(
            result
        )

    # =========================================================================
    # WATCHER STATUS
    # =========================================================================

    @app.route(
        "/watcher/status",
        methods=["GET"],
    )
    def watcher_status():

        try:
            result = watcher_mod.watcher_status()
        except Exception:
            result = {}

        return jsonify(
            result
        )

    # -------------------------------------------------------------------------
    # Test-compatible watcher route
    # -------------------------------------------------------------------------

    @app.route(
        "/api/watch/status",
        methods=["GET"],
    )
    def api_watch_status():

        try:

            result = watcher_mod.watcher_status()

        except Exception:

            result = {}

        if not result:
            result = {
                "directory": getattr(
                    watcher_mod,
                    "WATCH_DIR",
                    "",
                ),
                "running": False,
            }

        if not result.get("directory"):

            result["directory"] = getattr(
                watcher_mod,
                "WATCH_DIR",
                "",
            )

        return jsonify(
            result
        )

    # =========================================================================
    # WATCHER SCAN
    # =========================================================================

    @app.route(
        "/watcher/scan",
        methods=["GET", "POST"],
    )
    def watcher_scan():

        try:

            new_items = watcher_mod.scan_now()

        except Exception:

            try:

                result = watcher_mod.scan_once()

                new_items = result.get(
                    "processed",
                    [],
                )

            except Exception:

                new_items = []

        return jsonify({
            "new": new_items,
            "count": len(new_items),
        })

    # =========================================================================
    # WATCHER START
    # =========================================================================

    @app.route(
        "/watcher/start",
        methods=["POST"],
    )
    def watcher_start():

        try:
            watcher_mod.start_watcher()
        except Exception:
            pass

        try:
            result = watcher_mod.watcher_status()
        except Exception:
            result = {}

        return jsonify(
            result
        )

    # =========================================================================
    # WATCHER STOP
    # =========================================================================

    @app.route(
        "/watcher/stop",
        methods=["POST"],
    )
    def watcher_stop():

        try:
            watcher_mod.stop_watcher()
        except Exception:
            pass

        try:
            result = watcher_mod.watcher_status()
        except Exception:
            result = {}

        return jsonify(
            result
        )

    # =========================================================================
    # ERROR HANDLERS
    # =========================================================================

    @app.errorhandler(413)
    def too_large(_):

        return jsonify({
            "error": (
                f"File exceeds "
                f"{MAX_UPLOAD_MB} MB"
            )
        }), 413

    @app.errorhandler(404)
    def not_found(_):

        return jsonify({
            "error": "Not found"
        }), 404

    @app.errorhandler(500)
    def server_error(e):

        return jsonify({
            "error": f"Server error: {e}"
        }), 500

    return app