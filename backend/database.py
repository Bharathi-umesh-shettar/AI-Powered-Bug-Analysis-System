"""SQLite database layer for the Intelligent Bug Diagnosis Platform.

This module provides the database API used by the Flask server,
knowledge-base/RAG pipeline, agents, dashboard, and Auto-Watch features.

The schema is created and migrated non-destructively so existing data is
preserved whenever possible.
"""

import json
import sqlite3
from datetime import datetime, timezone

from .config import DB_PATH


# =============================================================================
# Utility
# =============================================================================

def now_iso():
    """Return the current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection():
    """Create a configured SQLite connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# =============================================================================
# Schema
# =============================================================================

BUG_COLUMNS = {
    "error_message": "TEXT",
    "component": "TEXT",
    "environment": "TEXT",
    "additional_info": "TEXT",
    "root_cause": "TEXT",
    "status": "TEXT DEFAULT 'Open'",
    "analysis_result": "TEXT",
    "recommendation": "TEXT",
    "resolution_details": "TEXT",
    "verified": "INTEGER DEFAULT 0",
    "resolved_at": "TEXT",
    "duplicate_of": "INTEGER",
    "duplicate_status": "TEXT",
    "duplicate_score": "REAL",
    "source": "TEXT DEFAULT 'manual'",
    "source_file": "TEXT",
    "in_knowledge_base": "INTEGER DEFAULT 0",
    "embedding_status": "TEXT",
    "updated_at": "TEXT",
}


KB_COLUMNS = {
    "error_message": "TEXT",
    "stack_trace": "TEXT",
    "component": "TEXT",
    "resolution_details": "TEXT",
    "origin": "TEXT DEFAULT 'dataset'",
    "source_bug_id": "INTEGER",
}


def _existing_columns(cur, table):
    """Return existing column names for a table."""
    return {
        row[1]
        for row in cur.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def _add_missing_columns(cur, table, wanted):
    """Add missing columns without deleting existing data."""
    existing = _existing_columns(cur, table)

    for name, ddl in wanted.items():
        if name not in existing:
            cur.execute(
                f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
            )


def init_db():
    """Create database tables and migrate missing columns."""
    conn = get_connection()
    cur = conn.cursor()

    # -------------------------------------------------------------------------
    # Bugs
    # -------------------------------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bugs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT NOT NULL,
            stack_trace TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    # -------------------------------------------------------------------------
    # Knowledge base
    # -------------------------------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_base (
            bug_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT,
            severity TEXT,
            root_cause TEXT,
            suggested_fix TEXT,
            created_at TEXT
        )
        """
    )

    # -------------------------------------------------------------------------
    # Auto-Watch events
    # -------------------------------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS watch_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            file_path TEXT,
            status TEXT NOT NULL,
            detail TEXT,
            bug_id INTEGER,
            detected_at TEXT NOT NULL,
            processed_at TEXT
        )
        """
    )

    # -------------------------------------------------------------------------
    # Analysis records
    # -------------------------------------------------------------------------

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bug_id INTEGER NOT NULL,
            root_cause TEXT,
            recommendation TEXT,
            structured_summary TEXT,
            exception_type TEXT,
            failure_point TEXT,
            resolution_summary TEXT,
            supporting_evidence TEXT,
            best_practices TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (bug_id) REFERENCES bugs(id)
        )
        """
    )

    # -------------------------------------------------------------------------
    # Migration
    # -------------------------------------------------------------------------

    _add_missing_columns(
        cur,
        "bugs",
        BUG_COLUMNS,
    )

    _add_missing_columns(
        cur,
        "knowledge_base",
        KB_COLUMNS,
    )

    # -------------------------------------------------------------------------
    # Indexes
    # -------------------------------------------------------------------------

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bugs_status
        ON bugs(status)
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bugs_component
        ON bugs(component)
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bugs_created
        ON bugs(created_at)
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_analysis_bug
        ON analyses(bug_id)
        """
    )

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_watch_file
        ON watch_events(file_path)
        """
    )

    conn.commit()
    conn.close()


# =============================================================================
# Bug helpers
# =============================================================================

def _decode_bug(bug):
    """Decode JSON analysis data stored in the database."""
    if not bug:
        return bug

    raw = bug.get("analysis_result")

    if raw:
        try:
            bug["findings"] = json.loads(raw)
        except (ValueError, TypeError):
            bug["findings"] = None
    else:
        bug["findings"] = None

    return bug


def insert_bug(data, description=None, severity=None, stack_trace=None, **extra):
    """Insert a bug.

    Supports both:
        insert_bug(dict)

    and the older:
        insert_bug(title, description, severity, stack_trace, **extra)
    """

    # -------------------------------------------------------------------------
    # New dictionary-style API used by server.py
    # -------------------------------------------------------------------------

    if isinstance(data, dict):
        payload = dict(data)

        title = (payload.get("title") or "").strip()
        desc = (payload.get("description") or "").strip()

        if not title:
            raise ValueError("Bug title is required")

        if not desc:
            raise ValueError("Bug description is required")

        payload["title"] = title
        payload["description"] = desc
        payload["severity"] = payload.get("severity") or "Medium"
        payload["stack_trace"] = payload.get("stack_trace") or ""
        payload["created_at"] = payload.get("created_at") or now_iso()
        payload["updated_at"] = now_iso()
        payload["status"] = payload.get("status") or "Open"

    # -------------------------------------------------------------------------
    # Backward-compatible positional API
    # -------------------------------------------------------------------------

    else:
        title = data

        payload = {
            "title": title,
            "description": description or "",
            "severity": severity or "Medium",
            "stack_trace": stack_trace or "",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "status": extra.pop("status", "Open"),
        }

        payload.update(extra)

    # Only insert actual database columns.
    allowed_columns = {
        "title",
        "description",
        "severity",
        "stack_trace",
        "created_at",
        "updated_at",
        "error_message",
        "component",
        "environment",
        "additional_info",
        "root_cause",
        "status",
        "analysis_result",
        "recommendation",
        "resolution_details",
        "verified",
        "resolved_at",
        "duplicate_of",
        "duplicate_status",
        "duplicate_score",
        "source",
        "source_file",
        "in_knowledge_base",
        "embedding_status",
    }

    payload = {
        key: value
        for key, value in payload.items()
        if key in allowed_columns
    }

    columns = ", ".join(payload.keys())
    placeholders = ", ".join("?" for _ in payload)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        f"""
        INSERT INTO bugs ({columns})
        VALUES ({placeholders})
        """,
        tuple(payload.values()),
    )

    bug_id = cur.lastrowid

    conn.commit()
    conn.close()

    return bug_id


def update_bug(bug_id, **fields):
    """Update allowed bug fields."""
    allowed = set(BUG_COLUMNS) | {
        "title",
        "description",
        "severity",
        "stack_trace",
    }

    data = {
        key: value
        for key, value in fields.items()
        if key in allowed
    }

    if not data:
        return False

    data["updated_at"] = now_iso()

    sets = ", ".join(
        f"{key} = ?"
        for key in data
    )

    conn = get_connection()

    cur = conn.cursor()

    cur.execute(
        f"""
        UPDATE bugs
        SET {sets}
        WHERE id = ?
        """,
        (*data.values(), bug_id),
    )

    changed = cur.rowcount

    conn.commit()
    conn.close()

    return changed > 0


def update_bug_embedding_status(bug_id, status):
    """Update embedding processing status for a bug."""
    return update_bug(
        bug_id,
        embedding_status=status,
    )


def fetch_all_bugs():
    """Return all bugs."""
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT *
        FROM bugs
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return [
        _decode_bug(dict(row))
        for row in rows
    ]


def fetch_bug(bug_id):
    """Return one bug."""
    conn = get_connection()

    row = conn.execute(
        """
        SELECT *
        FROM bugs
        WHERE id = ?
        """,
        (bug_id,),
    ).fetchone()

    conn.close()

    return (
        _decode_bug(dict(row))
        if row
        else None
    )


def search_bugs(
    query=None,
    status=None,
    severity=None,
    component=None,
    field="any",
    limit=500,
):
    """Search bugs."""
    sql = "SELECT * FROM bugs WHERE 1=1"
    args = []

    if query:
        like = f"%{query}%"

        if field == "title":
            sql += " AND title LIKE ?"
            args.append(like)

        elif field == "description":
            sql += " AND description LIKE ?"
            args.append(like)

        elif field == "component":
            sql += " AND component LIKE ?"
            args.append(like)

        else:
            sql += """
                AND (
                    title LIKE ?
                    OR description LIKE ?
                    OR error_message LIKE ?
                    OR root_cause LIKE ?
                    OR component LIKE ?
                )
            """

            args.extend([like] * 5)

    if status:
        sql += " AND status = ?"
        args.append(status)

    if severity:
        sql += " AND severity = ?"
        args.append(severity)

    if component:
        sql += " AND component = ?"
        args.append(component)

    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)

    conn = get_connection()

    rows = conn.execute(
        sql,
        tuple(args),
    ).fetchall()

    conn.close()

    return [
        _decode_bug(dict(row))
        for row in rows
    ]


# =============================================================================
# Knowledge Base
# =============================================================================

def count_kb():
    """Return number of knowledge-base records."""
    conn = get_connection()

    row = conn.execute(
        "SELECT COUNT(*) AS count FROM knowledge_base"
    ).fetchone()

    conn.close()

    return int(row["count"])


def fetch_knowledge_base(limit=None):
    """Return knowledge-base records."""
    conn = get_connection()

    if limit is None:
        rows = conn.execute(
            """
            SELECT *
            FROM knowledge_base
            ORDER BY bug_id ASC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT *
            FROM knowledge_base
            ORDER BY bug_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    conn.close()

    return [
        dict(row)
        for row in rows
    ]


def fetch_all_knowledge():
    """Backward-compatible alias."""
    return fetch_knowledge_base()


def insert_kb_row(row):
    """Insert one knowledge-base record from a dictionary."""
    if not row:
        return None

    bug_id = row.get("bug_id")

    if bug_id is None:
        bug_id = next_knowledge_id()

    data = {
        "bug_id": bug_id,
        "title": row.get("title") or "",
        "description": row.get("description") or "",
        "category": row.get("category"),
        "severity": row.get("severity"),
        "root_cause": row.get("root_cause"),
        "suggested_fix": row.get("suggested_fix"),
        "created_at": row.get("created_at") or now_iso(),
        "error_message": row.get("error_message"),
        "stack_trace": row.get("stack_trace"),
        "component": row.get("component"),
        "resolution_details": row.get("resolution_details"),
        "origin": row.get("origin") or "dataset",
        "source_bug_id": row.get("source_bug_id"),
    }

    columns = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)

    conn = get_connection()

    conn.execute(
        f"""
        INSERT OR REPLACE INTO knowledge_base
        ({columns})
        VALUES ({placeholders})
        """,
        tuple(data.values()),
    )

    conn.commit()
    conn.close()

    return bug_id


def insert_knowledge_entry(entry):
    """Insert/replace one knowledge-base entry."""
    return insert_kb_row(entry)


def insert_knowledge_bulk(records):
    """Bulk insert knowledge-base records."""
    for record in records:
        if isinstance(record, dict):
            insert_kb_row(record)
        else:
            (
                bug_id,
                title,
                description,
                category,
                severity,
                root_cause,
                suggested_fix,
                created_at,
            ) = record

            insert_kb_row(
                {
                    "bug_id": bug_id,
                    "title": title,
                    "description": description,
                    "category": category,
                    "severity": severity,
                    "root_cause": root_cause,
                    "suggested_fix": suggested_fix,
                    "created_at": created_at,
                }
            )


def next_knowledge_id():
    """Return next available knowledge-base ID."""
    conn = get_connection()

    row = conn.execute(
        """
        SELECT COALESCE(MAX(bug_id), 0) AS maximum
        FROM knowledge_base
        """
    ).fetchone()

    conn.close()

    return int(row["maximum"]) + 1


def fetch_kb_by_ids(ids):
    """Fetch knowledge-base rows by IDs."""
    if not ids:
        return []

    placeholders = ", ".join("?" for _ in ids)

    conn = get_connection()

    rows = conn.execute(
        f"""
        SELECT *
        FROM knowledge_base
        WHERE bug_id IN ({placeholders})
        """,
        tuple(ids),
    ).fetchall()

    conn.close()

    return [
        dict(row)
        for row in rows
    ]


def find_knowledge_by_source_bug(bug_id):
    """Find a knowledge-base entry created from a bug."""
    conn = get_connection()

    row = conn.execute(
        """
        SELECT *
        FROM knowledge_base
        WHERE source_bug_id = ?
        """,
        (bug_id,),
    ).fetchone()

    conn.close()

    return dict(row) if row else None


# =============================================================================
# Analysis
# =============================================================================

def save_analysis(bug_id, analysis):
    """Save or update AI analysis for a bug."""
    if not isinstance(analysis, dict):
        analysis = {}

    root_cause = analysis.get("root_cause")
    recommendation = analysis.get("recommendation")
    structured_summary = analysis.get("structured_summary")
    exception_type = analysis.get("exception_type")
    failure_point = analysis.get("failure_point")
    resolution_summary = analysis.get("resolution_summary")
    supporting_evidence = analysis.get("supporting_evidence")
    best_practices = analysis.get("best_practices")

    payload_json = json.dumps(
        analysis,
        default=str,
    )

    supporting_evidence_json = (
        json.dumps(
            supporting_evidence,
            default=str,
        )
        if not isinstance(supporting_evidence, str)
        else supporting_evidence
    )

    best_practices_json = (
        json.dumps(
            best_practices,
            default=str,
        )
        if not isinstance(best_practices, str)
        else best_practices
    )

    conn = get_connection()

    existing = conn.execute(
        """
        SELECT id
        FROM analyses
        WHERE bug_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (bug_id,),
    ).fetchone()

    values = (
        root_cause,
        recommendation,
        structured_summary,
        exception_type,
        failure_point,
        resolution_summary,
        supporting_evidence_json,
        best_practices_json,
        payload_json,
        now_iso(),
    )

    if existing:
        conn.execute(
            """
            UPDATE analyses
            SET
                root_cause = ?,
                recommendation = ?,
                structured_summary = ?,
                exception_type = ?,
                failure_point = ?,
                resolution_summary = ?,
                supporting_evidence = ?,
                best_practices = ?,
                payload_json = ?,
                created_at = ?
            WHERE id = ?
            """,
            (*values, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO analyses (
                bug_id,
                root_cause,
                recommendation,
                structured_summary,
                exception_type,
                failure_point,
                resolution_summary,
                supporting_evidence,
                best_practices,
                payload_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bug_id,
                *values,
            ),
        )

    # Keep bug table synchronized with analysis.
    conn.execute(
        """
        UPDATE bugs
        SET
            root_cause = ?,
            recommendation = ?,
            analysis_result = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            root_cause,
            recommendation,
            payload_json,
            now_iso(),
            bug_id,
        ),
    )

    conn.commit()
    conn.close()


def insert_analysis(analysis):
    """Compatibility API used by the orchestrator.

    The orchestrator passes the complete analysis dictionary, while the
    lower-level database API uses save_analysis(bug_id, analysis).

    This function bridges those two APIs.
    """
    if not isinstance(analysis, dict):
        raise ValueError("Analysis must be a dictionary")

    # The orchestrator normally includes bug_id directly.
    bug_id = analysis.get("bug_id")

    # Support a nested bug dictionary as well.
    if bug_id is None:
        bug = analysis.get("bug")

        if isinstance(bug, dict):
            bug_id = bug.get("bug_id") or bug.get("id")

    if bug_id is None:
        raise ValueError(
            "Cannot save analysis because bug_id is missing"
        )

    save_analysis(
        int(bug_id),
        analysis,
    )

    return analysis


def fetch_analysis_for_bug(bug_id):
    """Return analysis for a bug."""
    conn = get_connection()

    row = conn.execute(
        """
        SELECT *
        FROM analyses
        WHERE bug_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (bug_id,),
    ).fetchone()

    conn.close()

    if not row:
        return None

    result = dict(row)

    # Decode JSON fields where possible.
    for key in (
        "supporting_evidence",
        "best_practices",
    ):
        value = result.get(key)

        if isinstance(value, str):
            try:
                result[key] = json.loads(value)
            except (ValueError, TypeError):
                pass

    return result


def fetch_recent_analyses(limit=10):
    """Return recent analyses."""
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT
            analyses.*,
            bugs.title AS bug_title,
            bugs.severity AS bug_severity
        FROM analyses
        LEFT JOIN bugs
            ON bugs.id = analyses.bug_id
        ORDER BY analyses.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    conn.close()

    return [
        dict(row)
        for row in rows
    ]


def count_analyses():
    """Return number of analyses."""
    conn = get_connection()

    row = conn.execute(
        "SELECT COUNT(*) AS count FROM analyses"
    ).fetchone()

    conn.close()

    return int(row["count"])


# =============================================================================
# Statistics / Dashboard
# =============================================================================

def count_bugs():
    """Return total bug count."""
    conn = get_connection()

    row = conn.execute(
        "SELECT COUNT(*) AS count FROM bugs"
    ).fetchone()

    conn.close()

    return int(row["count"])


def count_critical_bugs():
    """Return number of critical bugs."""
    conn = get_connection()

    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM bugs
        WHERE LOWER(severity) = 'critical'
        """
    ).fetchone()

    conn.close()

    return int(row["count"])


def count_duplicate_bugs():
    """Return number of duplicate bugs."""
    conn = get_connection()

    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM bugs
        WHERE duplicate_of IS NOT NULL
           OR LOWER(COALESCE(duplicate_status, '')) = 'duplicate'
        """
    ).fetchone()

    conn.close()

    return int(row["count"])


def fetch_recent_bugs(limit=5):
    """Return recently submitted bugs."""
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT *
        FROM bugs
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    conn.close()

    return [
        _decode_bug(dict(row))
        for row in rows
    ]


def dashboard_summary():
    """Return dashboard statistics."""
    return {
        "total_bugs": count_bugs(),
        "critical_bugs": count_critical_bugs(),
        "kb_records": count_kb(),
        "duplicate_bugs": count_duplicate_bugs(),
        "analyses": count_analyses(),
        "recent_bugs": fetch_recent_bugs(5),
        "recent_analyses": fetch_recent_analyses(5),
    }


# =============================================================================
# Auto-Watch
# =============================================================================

def record_watch_event(
    file_name,
    file_path,
    status,
    detail=None,
    bug_id=None,
    processed=False,
):
    """Record or update an Auto-Watch event."""
    conn = get_connection()

    conn.execute(
        """
        INSERT INTO watch_events (
            file_name,
            file_path,
            status,
            detail,
            bug_id,
            detected_at,
            processed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(file_path)
        DO UPDATE SET
            status = excluded.status,
            detail = excluded.detail,
            bug_id = COALESCE(
                excluded.bug_id,
                watch_events.bug_id
            ),
            processed_at = excluded.processed_at
        """,
        (
            file_name,
            file_path,
            status,
            detail,
            bug_id,
            now_iso(),
            now_iso() if processed else None,
        ),
    )

    conn.commit()
    conn.close()


def watch_event_exists(file_path):
    """Return existing watch event status for a file."""
    conn = get_connection()

    row = conn.execute(
        """
        SELECT status
        FROM watch_events
        WHERE file_path = ?
        """,
        (file_path,),
    ).fetchone()

    conn.close()

    return row["status"] if row else None


def fetch_watch_events(limit=100):
    """Return recent Auto-Watch events."""
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT *
        FROM watch_events
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    conn.close()

    return [
        dict(row)
        for row in rows
    ]