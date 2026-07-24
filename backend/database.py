"""SQLite database layer.

Tables:
    bugs             - user submitted bugs
    knowledge_base   - historical defect records
    embeddings       - embedding metadata / status tracking
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .config import DB_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS bugs (
                bug_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT NOT NULL,
                description  TEXT NOT NULL,
                severity     TEXT DEFAULT 'Medium',
                category     TEXT DEFAULT 'General',
                component    TEXT,
                stack_trace  TEXT,
                error_log    TEXT,
                reporter     TEXT,
                created_date TEXT NOT NULL,
                embedding_status TEXT DEFAULT 'pending'
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_base (
                kb_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                project      TEXT,
                title        TEXT NOT NULL,
                description  TEXT NOT NULL,
                severity     TEXT,
                category     TEXT,
                component    TEXT,
                root_cause   TEXT,
                suggested_fix TEXT,
                source       TEXT,
                created_date TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                emb_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ref_table    TEXT NOT NULL,
                ref_id       INTEGER NOT NULL,
                faiss_index  INTEGER,
                status       TEXT DEFAULT 'ok',
                created_date TEXT
            )
            """
        )
        # Milestone 2 + 3: combined structured analysis produced by the orchestrator
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                analysis_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                bug_id             INTEGER NOT NULL,
                severity           TEXT,
                priority           TEXT,
                affected_component TEXT,
                confidence         INTEGER,
                reasoning          TEXT,
                exception_type     TEXT,
                failure_point      TEXT,
                affected_file      TEXT,
                function_name      TEXT,
                line_number        INTEGER,
                affected_code_path TEXT,
                root_cause         TEXT,
                structured_summary TEXT,
                language           TEXT,
                similar_count      INTEGER,
                payload_json       TEXT,
                timestamp          TEXT,
                root_cause_confidence INTEGER,
                supporting_evidence   TEXT,
                duplicate_bug_id      INTEGER,
                duplicate_similarity  REAL,
                resolution_summary    TEXT,
                recommendation        TEXT,
                best_practices        TEXT,
                historical_reference  TEXT,
                analysis_timestamp    TEXT,
                FOREIGN KEY(bug_id) REFERENCES bugs(bug_id)
            )
            """
        )
        # Milestone 3 additive migration for pre-existing databases.
        _ensure_columns(c, "analyses", {
            "root_cause_confidence": "INTEGER",
            "supporting_evidence":   "TEXT",
            "duplicate_bug_id":      "INTEGER",
            "duplicate_similarity":  "REAL",
            "resolution_summary":    "TEXT",
            "recommendation":        "TEXT",
            "best_practices":        "TEXT",
            "historical_reference":  "TEXT",
            "analysis_timestamp":    "TEXT",
        })


def _ensure_columns(cursor, table: str, cols: dict):
    existing = {row["name"] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, decl in cols.items():
        if name not in existing:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            except Exception:
                pass



def insert_bug(data: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO bugs
              (title, description, severity, category, component,
               stack_trace, error_log, reporter, created_date, embedding_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("title", "").strip(),
                data.get("description", "").strip(),
                data.get("severity", "Medium"),
                data.get("category", "General"),
                data.get("component", ""),
                data.get("stack_trace", ""),
                data.get("error_log", ""),
                data.get("reporter", "anonymous"),
                datetime.utcnow().isoformat(timespec="seconds"),
                "pending",
            ),
        )
        return cur.lastrowid


def update_bug_embedding_status(bug_id: int, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE bugs SET embedding_status = ? WHERE bug_id = ?",
            (status, bug_id),
        )


def insert_kb_row(row: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO knowledge_base
              (project, title, description, severity, category, component,
               root_cause, suggested_fix, source, created_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("project", "Unknown"),
                row.get("title", ""),
                row.get("description", ""),
                row.get("severity", "Medium"),
                row.get("category", "General"),
                row.get("component", ""),
                row.get("root_cause", ""),
                row.get("suggested_fix", ""),
                row.get("source", "seed"),
                row.get("created_date", datetime.utcnow().isoformat(timespec="seconds")),
            ),
        )
        return cur.lastrowid


def fetch_all_bugs():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM bugs ORDER BY bug_id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def fetch_recent_bugs(limit=5):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM bugs ORDER BY bug_id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def fetch_knowledge_base(limit=None):
    with get_conn() as conn:
        q = "SELECT * FROM knowledge_base ORDER BY kb_id ASC"
        if limit:
            q += f" LIMIT {int(limit)}"
        rows = conn.execute(q).fetchall()
        return [dict(r) for r in rows]


def fetch_kb_by_ids(ids):
    if not ids:
        return []
    with get_conn() as conn:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT * FROM knowledge_base WHERE kb_id IN ({placeholders})",
            tuple(ids),
        ).fetchall()
        return [dict(r) for r in rows]


def count_bugs():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM bugs").fetchone()[0]


def count_critical_bugs():
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM bugs WHERE LOWER(severity) IN ('critical','high')"
        ).fetchone()[0]


def count_kb():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM knowledge_base").fetchone()[0]


def count_duplicate_bugs():
    """A simple heuristic: bugs sharing an identical title."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                SELECT COUNT(*) AS cnt FROM bugs
                GROUP BY LOWER(TRIM(title)) HAVING cnt > 1
            )
            """
        ).fetchone()
        return row[0] or 0


# --------------------------------------------------------------------------
# Milestone 2 — analyses table helpers
# --------------------------------------------------------------------------
import json as _json


def insert_analysis(analysis: dict) -> int:
    """Persist combined orchestrator output. Returns analysis_id."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO analyses (
                bug_id, severity, priority, affected_component, confidence, reasoning,
                exception_type, failure_point, affected_file, function_name, line_number,
                affected_code_path, root_cause, structured_summary, language,
                similar_count, payload_json, timestamp,
                root_cause_confidence, supporting_evidence,
                duplicate_bug_id, duplicate_similarity,
                resolution_summary, recommendation, best_practices,
                historical_reference, analysis_timestamp
            ) VALUES (?,?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?, ?,?, ?,?,?, ?,?)
            """,
            (
                analysis.get("bug_id"),
                analysis.get("severity"),
                analysis.get("priority"),
                analysis.get("affected_component"),
                analysis.get("confidence"),
                analysis.get("reasoning"),
                analysis.get("exception_type"),
                analysis.get("failure_point"),
                analysis.get("affected_file"),
                analysis.get("function_name"),
                analysis.get("line_number"),
                analysis.get("affected_code_path"),
                analysis.get("root_cause"),
                analysis.get("structured_summary"),
                analysis.get("language"),
                analysis.get("similar_count"),
                _json.dumps(analysis, default=str),
                analysis.get("timestamp") or datetime.utcnow().isoformat(timespec="seconds"),
                analysis.get("root_cause_confidence"),
                _json.dumps(analysis.get("supporting_evidence") or [], default=str),
                analysis.get("duplicate_bug_id"),
                analysis.get("duplicate_similarity"),
                analysis.get("resolution_summary"),
                analysis.get("recommendation"),
                _json.dumps(analysis.get("best_practices") or [], default=str),
                analysis.get("historical_reference"),
                analysis.get("analysis_timestamp") or datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        return cur.lastrowid


def fetch_analysis_for_bug(bug_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE bug_id = ? ORDER BY analysis_id DESC LIMIT 1",
            (bug_id,),
        ).fetchone()
        return dict(row) if row else None


def fetch_recent_analyses(limit: int = 10):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT a.*, b.title AS bug_title
            FROM analyses a LEFT JOIN bugs b ON b.bug_id = a.bug_id
            ORDER BY a.analysis_id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_analyses():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]


# --------------------------------------------------------------------------
# Milestone 3 — search / dashboard / bug lookups
# --------------------------------------------------------------------------

def fetch_bug(bug_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM bugs WHERE bug_id = ?", (bug_id,)).fetchone()
        return dict(row) if row else None


def search_bugs(query: str, field: str = "any", limit: int = 50):
    """Search bugs by title / description / reporter / component / root_cause / recommendation."""
    q = f"%{(query or '').strip().lower()}%"
    field = (field or "any").lower()
    with get_conn() as conn:
        if field == "reporter":
            sql = "SELECT b.* FROM bugs b WHERE LOWER(b.reporter) LIKE ? ORDER BY b.bug_id DESC LIMIT ?"
            rows = conn.execute(sql, (q, limit)).fetchall()
        elif field == "component":
            sql = "SELECT b.* FROM bugs b WHERE LOWER(b.component) LIKE ? ORDER BY b.bug_id DESC LIMIT ?"
            rows = conn.execute(sql, (q, limit)).fetchall()
        elif field == "root_cause":
            sql = """SELECT b.*, a.root_cause, a.recommendation FROM bugs b
                     JOIN analyses a ON a.bug_id = b.bug_id
                     WHERE LOWER(a.root_cause) LIKE ? ORDER BY b.bug_id DESC LIMIT ?"""
            rows = conn.execute(sql, (q, limit)).fetchall()
        elif field == "recommendation":
            sql = """SELECT b.*, a.root_cause, a.recommendation FROM bugs b
                     JOIN analyses a ON a.bug_id = b.bug_id
                     WHERE LOWER(a.recommendation) LIKE ? ORDER BY b.bug_id DESC LIMIT ?"""
            rows = conn.execute(sql, (q, limit)).fetchall()
        else:
            sql = """SELECT DISTINCT b.* FROM bugs b
                     LEFT JOIN analyses a ON a.bug_id = b.bug_id
                     WHERE LOWER(b.title) LIKE ? OR LOWER(b.description) LIKE ?
                        OR LOWER(b.reporter) LIKE ? OR LOWER(b.component) LIKE ?
                        OR LOWER(COALESCE(a.root_cause,'')) LIKE ?
                        OR LOWER(COALESCE(a.recommendation,'')) LIKE ?
                     ORDER BY b.bug_id DESC LIMIT ?"""
            rows = conn.execute(sql, (q, q, q, q, q, q, limit)).fetchall()
        return [dict(r) for r in rows]


def dashboard_summary():
    """Aggregated metrics for the Milestone 3 dashboard."""
    with get_conn() as conn:
        total_bugs = conn.execute("SELECT COUNT(*) FROM bugs").fetchone()[0]
        kb_size = conn.execute("SELECT COUNT(*) FROM knowledge_base").fetchone()[0]
        analyses_count = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        dup_count = conn.execute(
            "SELECT COUNT(*) FROM analyses WHERE duplicate_bug_id IS NOT NULL"
        ).fetchone()[0]
        critical = conn.execute(
            "SELECT COUNT(*) FROM bugs WHERE LOWER(severity) IN ('critical','high')"
        ).fetchone()[0]
        rc_rows = conn.execute(
            """SELECT root_cause, COUNT(*) AS c FROM analyses
               WHERE root_cause IS NOT NULL AND root_cause != ''
               GROUP BY root_cause ORDER BY c DESC LIMIT 8"""
        ).fetchall()
        top_root_causes = [dict(r) for r in rc_rows]
        sev_rows = conn.execute(
            "SELECT severity, COUNT(*) AS c FROM bugs GROUP BY severity"
        ).fetchall()
        severity_distribution = {r["severity"] or "Unknown": r["c"] for r in sev_rows}
        comp_rows = conn.execute(
            """SELECT affected_component AS component, COUNT(*) AS c FROM analyses
               WHERE affected_component IS NOT NULL AND affected_component != ''
               GROUP BY affected_component ORDER BY c DESC LIMIT 6"""
        ).fetchall()
        top_components = [dict(r) for r in comp_rows]
    return {
        "total_bugs": total_bugs,
        "kb_size": kb_size,
        "analyses": analyses_count,
        "duplicates": dup_count,
        "critical_bugs": critical,
        "top_root_causes": top_root_causes,
        "severity_distribution": severity_distribution,
        "top_components": top_components,
    }
