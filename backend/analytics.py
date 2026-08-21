"""Defect Pattern Analytics (Milestone 4.1).

Every number here is computed with SQL/Python over the real ``bugs`` table.
There are no hardcoded statistics; empty datasets return empty lists and zeros.
"""

import json
import re
from collections import Counter

from config import SEVERITIES
from database import get_connection


STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on",
    "and", "or", "not", "for", "with", "when", "after", "before", "this",
    "that", "it", "be", "by", "at", "from", "as", "but", "if", "then",
    "there", "has", "have", "had", "does", "did", "do", "can", "cannot",
    "will", "would", "should", "user", "users", "error", "bug", "issue",
    "fails", "failed", "failing", "occurs", "during", "while", "into",
    "some", "any", "all", "new", "also",
}


def _rows(sql, args=()):
    """Execute a query and return rows as dictionaries."""
    conn = get_connection()

    try:
        rows = conn.execute(sql, args).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _scalar(sql, args=()):
    """Execute a query and return its first scalar value."""
    conn = get_connection()

    try:
        row = conn.execute(sql, args).fetchone()

        if row:
            return list(row)[0]

        return 0

    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Severity Analytics
# --------------------------------------------------------------------------- #

def severity_breakdown():
    """Return bug count grouped by severity."""

    counts = {severity: 0 for severity in SEVERITIES}
    other = {}

    rows = _rows(
        """
        SELECT severity, COUNT(*) AS count
        FROM bugs
        GROUP BY severity
        """
    )

    for row in rows:
        severity = (
            row["severity"] or "Unspecified"
        ).strip()

        count = int(row["count"])

        if severity in counts:
            counts[severity] = count
        else:
            other[severity] = (
                other.get(severity, 0) + count
            )

    counts.update(other)

    return [
        {
            "severity": severity,
            "count": count,
        }
        for severity, count in counts.items()
    ]


# --------------------------------------------------------------------------- #
# Component Analytics
# --------------------------------------------------------------------------- #

def component_frequency(limit=15):
    """Return most frequently affected components."""

    return _rows(
        """
        SELECT
            COALESCE(
                NULLIF(TRIM(component), ''),
                'Unclassified'
            ) AS component,
            COUNT(*) AS count
        FROM bugs
        GROUP BY component
        ORDER BY count DESC, component ASC
        LIMIT ?
        """,
        (limit,),
    )


# --------------------------------------------------------------------------- #
# Root Cause Analytics
# --------------------------------------------------------------------------- #

def root_cause_frequency(limit=10):
    """Return most common root causes."""

    return _rows(
        """
        SELECT
            TRIM(root_cause) AS root_cause,
            COUNT(*) AS count
        FROM bugs
        WHERE root_cause IS NOT NULL
          AND TRIM(root_cause) <> ''
        GROUP BY TRIM(root_cause)
        ORDER BY count DESC
        LIMIT ?
        """,
        (limit,),
    )


# --------------------------------------------------------------------------- #
# Error Type Analytics
# --------------------------------------------------------------------------- #

def error_type_frequency(limit=10):
    """Return most common error types from stored AI analysis."""

    counter = Counter()

    rows = _rows(
        """
        SELECT analysis_result
        FROM bugs
        WHERE analysis_result IS NOT NULL
          AND TRIM(analysis_result) <> ''
        """
    )

    for row in rows:

        try:
            data = json.loads(
                row["analysis_result"]
            )
        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ):
            continue

        if not isinstance(data, dict):
            continue

        error_types = data.get(
            "error_types",
            []
        )

        if isinstance(error_types, str):
            error_types = [error_types]

        if not isinstance(error_types, list):
            continue

        for error_type in error_types:

            if error_type:
                counter[str(error_type)] += 1

    return [
        {
            "error_type": error_type,
            "count": count,
        }
        for error_type, count
        in counter.most_common(limit)
    ]


# --------------------------------------------------------------------------- #
# Recurring Themes
# --------------------------------------------------------------------------- #

def recurring_themes(limit=12, min_count=2):
    """Find recurring words and phrases in bug reports."""

    rows = _rows(
        """
        SELECT title, description, error_message
        FROM bugs
        """
    )

    unigrams = Counter()
    bigrams = Counter()

    for row in rows:

        text = " ".join(
            str(row.get(field) or "")
            for field in (
                "title",
                "description",
                "error_message",
            )
        ).lower()

        words = [
            word
            for word in re.findall(
                r"[a-z][a-z0-9_.-]{2,}",
                text,
            )
            if word not in STOPWORDS
        ]

        # Count each word only once per bug.
        unigrams.update(set(words))

        # Count each adjacent pair.
        bigrams.update(
            f"{first} {second}"
            for first, second in zip(
                words,
                words[1:],
            )
        )

    themes = [
        {
            "theme": theme,
            "count": count,
        }
        for theme, count
        in bigrams.most_common(limit * 2)
        if count >= min_count
    ]

    if len(themes) < limit:

        existing = {
            item["theme"]
            for item in themes
        }

        themes.extend(
            {
                "theme": theme,
                "count": count,
            }
            for theme, count
            in unigrams.most_common(limit * 2)
            if count >= min_count
            and theme not in existing
        )

    return themes[:limit]


# --------------------------------------------------------------------------- #
# Status Analytics
# --------------------------------------------------------------------------- #

def status_breakdown():
    """Return bug count grouped by status."""

    return _rows(
        """
        SELECT
            COALESCE(
                NULLIF(TRIM(status), ''),
                'Open'
            ) AS status,
            COUNT(*) AS count
        FROM bugs
        GROUP BY status
        ORDER BY count DESC
        """
    )


# --------------------------------------------------------------------------- #
# Defect Trend
# --------------------------------------------------------------------------- #

def defect_trend(granularity="daily", limit=30):
    """Return bug counts over time."""

    formats = {
        "daily": "%Y-%m-%d",
        "weekly": "%Y-W%W",
        "monthly": "%Y-%m",
    }

    if granularity not in formats:
        granularity = "daily"

    rows = _rows(
        f"""
        SELECT
            strftime(
                '{formats[granularity]}',
                created_at
            ) AS period,
            COUNT(*) AS count
        FROM bugs
        WHERE created_at IS NOT NULL
        GROUP BY period
        ORDER BY period ASC
        """
    )

    rows = [
        row
        for row in rows
        if row["period"]
    ]

    return rows[-limit:]


# --------------------------------------------------------------------------- #
# Best Granularity
# --------------------------------------------------------------------------- #

def best_granularity():
    """Select suitable trend granularity based on recorded data."""

    days = _scalar(
        """
        SELECT COUNT(
            DISTINCT date(created_at)
        )
        FROM bugs
        """
    )

    if not days:
        return "daily"

    if days > 90:
        return "monthly"

    if days > 21:
        return "weekly"

    return "daily"


# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #

def kpis():
    """Return dashboard KPI statistics."""

    total = _scalar(
        "SELECT COUNT(*) FROM bugs"
    )

    resolved = _scalar(
        """
        SELECT COUNT(*)
        FROM bugs
        WHERE status IN (
            'Resolved',
            'Resolved & Verified',
            'Closed'
        )
        """
    )

    verified = _scalar(
        """
        SELECT COUNT(*)
        FROM bugs
        WHERE verified = 1
        """
    )

    in_kb = _scalar(
        """
        SELECT COUNT(*)
        FROM bugs
        WHERE in_knowledge_base = 1
        """
    )

    critical = _scalar(
        """
        SELECT COUNT(*)
        FROM bugs
        WHERE severity = 'Critical'
        """
    )

    high = _scalar(
        """
        SELECT COUNT(*)
        FROM bugs
        WHERE severity = 'High'
        """
    )

    duplicates = _scalar(
        """
        SELECT COUNT(*)
        FROM bugs
        WHERE duplicate_status = 'Duplicate'
        """
    )

    analyzed = _scalar(
        """
        SELECT COUNT(*)
        FROM bugs
        WHERE analysis_result IS NOT NULL
          AND TRIM(analysis_result) <> ''
        """
    )

    kb_total = _scalar(
        """
        SELECT COUNT(*)
        FROM knowledge_base
        """
    )

    components = component_frequency(1)
    causes = root_cause_frequency(1)
    error_types = error_type_frequency(1)

    granularity = best_granularity()

    trend = defect_trend(
        granularity
    )

    recent_trend = "no data"

    if len(trend) >= 2:

        previous = int(
            trend[-2]["count"]
        )

        current = int(
            trend[-1]["count"]
        )

        delta = current - previous

        if delta > 0:
            direction = "rising"
        elif delta < 0:
            direction = "falling"
        else:
            direction = "flat"

        recent_trend = (
            f"{direction} "
            f"({previous} -> {current} "
            f"in the latest period)"
        )

    elif len(trend) == 1:

        recent_trend = (
            f"{trend[0]['count']} defect(s) "
            f"in the only recorded period"
        )

    return {
        "total_defects": int(total),

        "open_defects": int(
            total - resolved
        ),

        "resolved_defects": int(
            resolved
        ),

        "verified_defects": int(
            verified
        ),

        "critical_defects": int(
            critical
        ),

        "high_defects": int(
            high
        ),

        "duplicate_defects": int(
            duplicates
        ),

        "analyzed_defects": int(
            analyzed
        ),

        "knowledge_base_entries": int(
            kb_total
        ),

        "bugs_promoted_to_kb": int(
            in_kb
        ),

        "most_affected_component": (
            components[0]["component"]
            if components
            else None
        ),

        "most_affected_component_count": (
            int(components[0]["count"])
            if components
            else 0
        ),

        "most_common_root_cause": (
            causes[0]["root_cause"]
            if causes
            else None
        ),

        "most_common_root_cause_count": (
            int(causes[0]["count"])
            if causes
            else 0
        ),

        "most_frequent_error_type": (
            error_types[0]["error_type"]
            if error_types
            else None
        ),

        "most_frequent_error_type_count": (
            int(error_types[0]["count"])
            if error_types
            else 0
        ),

        "recent_defect_trend": recent_trend,
    }


# --------------------------------------------------------------------------- #
# Recent Bugs
# --------------------------------------------------------------------------- #

def recent_bugs(limit=10):
    """Return recently created bugs."""

    return _rows(
        """
        SELECT
            id,
            title,
            severity,
            component,
            status,
            created_at,
            duplicate_status,
            verified
        FROM bugs
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )


# --------------------------------------------------------------------------- #
# Complete Analytics Report
# --------------------------------------------------------------------------- #

def full_report(granularity=None):
    """Return the complete Milestone 4 analytics report."""

    granularity = (
        granularity
        or best_granularity()
    )

    return {
        "kpis": kpis(),

        "severity": severity_breakdown(),

        "components": component_frequency(),

        "root_causes": root_cause_frequency(),

        "error_types": error_type_frequency(),

        "themes": recurring_themes(),

        "statuses": status_breakdown(),

        "trend": {
            "granularity": granularity,
            "points": defect_trend(
                granularity
            ),
        },

        "recent": recent_bugs(),
    }