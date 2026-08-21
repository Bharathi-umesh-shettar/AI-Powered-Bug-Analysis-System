"""Report export: PDF and CSV (Milestone 3.4).

PDF uses ReportLab. CSV uses the stdlib. Both render the real structured
findings produced by the multi-agent pipeline.
"""
import csv
import io
import os

from config import APP_GROUP, APP_TITLE, REPORT_DIR

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )
    HAS_REPORTLAB = True
except ImportError:  # pragma: no cover
    HAS_REPORTLAB = False


class ReportError(Exception):
    pass


def _esc(value):
    return (str(value if value is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
BUG_CSV_FIELDS = [
    "id", "title", "description", "error_message", "component", "severity",
    "environment", "status", "verified", "root_cause", "duplicate_status",
    "duplicate_score", "duplicate_of", "recommendation", "resolution_details",
    "source", "created_at", "resolved_at", "in_knowledge_base",
]


def bugs_to_csv(bugs):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=BUG_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for bug in bugs:
        writer.writerow({k: bug.get(k, "") for k in BUG_CSV_FIELDS})
    return buf.getvalue()


def findings_to_csv(bug, findings):
    """Flatten one bug's complete analysis into a section/field/value CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Section", "Field", "Value"])
    rows = [
        ("Bug", "ID", bug.get("id")),
        ("Bug", "Title", bug.get("title")),
        ("Bug", "Severity", bug.get("severity")),
        ("Bug", "Component", findings.get("component")),
        ("Bug", "Environment", bug.get("environment")),
        ("Bug", "Status", bug.get("status")),
        ("Bug", "Created", bug.get("created_at")),
        ("Bug", "Description", bug.get("description")),
        ("Bug", "Error message", bug.get("error_message")),
        ("Bug", "Stack trace", bug.get("stack_trace")),
        ("Summary", "Bug summary", findings.get("bug_summary")),
        ("RAG", "Entries in knowledge base", findings.get("rag", {}).get("knowledge_entries")),
        ("RAG", "Records retrieved", findings.get("rag", {}).get("retrieved")),
        ("RAG", "Top similarity", findings.get("rag", {}).get("top_score")),
        ("RAG", "Embedding backend", findings.get("rag", {}).get("backend")),
        ("Analysis", "Error types", ", ".join(findings.get("error_types", []))),
        ("Analysis", "Possible root cause", findings.get("possible_root_cause")),
        ("Analysis", "Root cause confidence", findings.get("root_cause_confidence")),
        ("Analysis", "Root cause basis", findings.get("root_cause_basis")),
        ("Analysis", "Explanation", findings.get("analysis", {}).get("explanation")),
        ("Duplicate", "Status", findings.get("duplicate_status")),
        ("Duplicate", "Confidence", findings.get("duplicate_confidence")),
        ("Duplicate", "Duplicate of", findings.get("duplicate", {}).get("duplicate_of")),
        ("Duplicate", "Explanation", findings.get("duplicate", {}).get("explanation")),
        ("Remediation", "Primary recommendation", findings.get("recommended_fix")),
        ("Findings", "Suggested next action", findings.get("next_action")),
    ]
    for section, field, value in rows:
        writer.writerow([section, field, value])
    for i, sim in enumerate(findings.get("similar_bugs", []), 1):
        writer.writerow(["Similar bugs", f"#{i} KB entry {sim.get('bug_id')}",
                         f"{sim.get('title')} | similarity={sim.get('similarity')} | "
                         f"component={sim.get('component') or sim.get('category')} | "
                         f"severity={sim.get('severity')} | "
                         f"fix={sim.get('suggested_fix')}"])
    for i, rec in enumerate(findings.get("remediation", {}).get("recommendations", []), 1):
        writer.writerow(["Recommendations", f"#{i} (conf {rec.get('confidence')})",
                         f"{rec.get('action')} [source: {rec.get('source')}]"])
    for i, ev in enumerate(findings.get("supporting_evidence", []), 1):
        writer.writerow(["Evidence", f"#{i} KB entry {ev.get('bug_id')}",
                         f"{ev.get('title')} | similarity={ev.get('similarity')} | "
                         f"root_cause={ev.get('root_cause')} | fix={ev.get('fix')}"])
    for i, step in enumerate(findings.get("remediation", {}).get("verification", []), 1):
        writer.writerow(["Verification", f"Step {i}", step])
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=15, leading=19),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=11.5,
                             textColor=colors.HexColor("#1c3d5a"), spaceBefore=10,
                             spaceAfter=4),
        "body": ParagraphStyle("b", parent=base["BodyText"], fontSize=9,
                               leading=12.5, alignment=TA_LEFT),
        "small": ParagraphStyle("s", parent=base["BodyText"], fontSize=7.6,
                                leading=10, textColor=colors.HexColor("#444444")),
        "mono": ParagraphStyle("m", parent=base["BodyText"], fontSize=7.6,
                               leading=10, fontName="Courier"),
    }


def _kv_table(pairs, st, widths=(45 * mm, 125 * mm)):
    data = [[Paragraph(f"<b>{_esc(k)}</b>", st["small"]),
             Paragraph(_esc(v) or "&mdash;", st["body"])] for k, v in pairs]
    tbl = Table(data, colWidths=list(widths))
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5dde5")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f6fa")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tbl


def _flow_for_bug(bug, findings, st, generated_at):
    flow = [
        Paragraph(_esc(APP_TITLE), st["title"]),
        Paragraph(f"{_esc(APP_GROUP)} &middot; Bug Diagnosis Report &middot; "
                  f"generated {_esc(generated_at)}", st["small"]),
        Spacer(1, 6),
        Paragraph("1. Bug Information", st["h2"]),
        _kv_table([
            ("Bug ID", bug.get("id")),
            ("Title", bug.get("title")),
            ("Severity", bug.get("severity")),
            ("Component", findings.get("component")),
            ("Environment", bug.get("environment")),
            ("Status", bug.get("status")),
            ("Source", bug.get("source")),
            ("Created", bug.get("created_at")),
            ("Description", bug.get("description")),
            ("Error message", bug.get("error_message")),
        ], st),
    ]
    if bug.get("stack_trace"):
        flow += [Paragraph("Stack trace", st["h2"]),
                 Paragraph(_esc(bug["stack_trace"]).replace("\n", "<br/>"), st["mono"])]

    rag = findings.get("rag", {})
    flow += [
        Paragraph("2. RAG Retrieval", st["h2"]),
        _kv_table([
            ("Knowledge entries", rag.get("knowledge_entries")),
            ("Records retrieved", rag.get("retrieved")),
            ("Top similarity", rag.get("top_score")),
            ("Embedding backend", rag.get("backend")),
        ], st),
        Paragraph("3. Bug Analysis", st["h2"]),
        _kv_table([
            ("Error types", ", ".join(findings.get("error_types", []))),
            ("Possible root cause", findings.get("possible_root_cause")),
            ("Confidence", findings.get("root_cause_confidence")),
            ("Basis", findings.get("root_cause_basis")),
            ("Explanation", findings.get("analysis", {}).get("explanation")),
        ], st),
    ]

    sims = findings.get("similar_bugs", [])
    flow.append(Paragraph("4. Similar Historical Bugs", st["h2"]))
    if sims:
        data = [[Paragraph(f"<b>{h}</b>", st["small"]) for h in
                 ("KB ID", "Title", "Comp.", "Sev.", "Score", "Known fix")]]
        for s in sims:
            data.append([
                Paragraph(_esc(s.get("bug_id")), st["small"]),
                Paragraph(_esc(s.get("title")), st["small"]),
                Paragraph(_esc(s.get("component") or s.get("category")), st["small"]),
                Paragraph(_esc(s.get("severity")), st["small"]),
                Paragraph(f"{s.get('similarity', 0):.3f}", st["small"]),
                Paragraph(_esc(s.get("suggested_fix")), st["small"]),
            ])
        tbl = Table(data, colWidths=[13 * mm, 47 * mm, 22 * mm, 16 * mm, 14 * mm, 58 * mm])
        tbl.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5dde5")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eff6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        flow.append(tbl)
    else:
        flow.append(Paragraph("No historical bugs were retrieved.", st["body"]))

    dup = findings.get("duplicate", {})
    flow += [
        Paragraph("5. Duplicate Detection Agent", st["h2"]),
        _kv_table([
            ("Verdict", dup.get("status")),
            ("Confidence", dup.get("confidence")),
            ("Duplicate of", dup.get("duplicate_of")),
            ("Reasoning", dup.get("explanation")),
        ], st),
        Paragraph("6. Remediation Agent", st["h2"]),
    ]
    recs = findings.get("remediation", {}).get("recommendations", [])
    flow.append(_kv_table(
        [(f"Fix {i} (conf {r.get('confidence')})",
          f"{r.get('action')}  —  source: {r.get('source')}")
         for i, r in enumerate(recs, 1)] or [("Recommendations", "None")], st))

    causes = findings.get("remediation", {}).get("possible_causes", [])
    if causes:
        flow += [Paragraph("Possible causes", st["h2"]),
                 _kv_table([(f"{c.get('confidence')}",
                             f"{c.get('cause')}  ({c.get('basis')})")
                            for c in causes], st)]

    flow += [
        Paragraph("7. Structured Findings", st["h2"]),
        _kv_table([
            ("Bug summary", findings.get("bug_summary")),
            ("Severity", findings.get("severity")),
            ("Component", findings.get("component")),
            ("Possible root cause", findings.get("possible_root_cause")),
            ("Duplicate status", findings.get("duplicate_status")),
            ("Duplicate confidence", findings.get("duplicate_confidence")),
            ("Recommended fix", findings.get("recommended_fix")),
            ("Supporting evidence", "; ".join(
                f"KB #{e.get('bug_id')} ({e.get('similarity')})"
                for e in findings.get("supporting_evidence", [])) or "None"),
            ("Suggested next action", findings.get("next_action")),
            ("Resolution details", bug.get("resolution_details")),
            ("In knowledge base", "Yes" if bug.get("in_knowledge_base") else "No"),
        ], st),
    ]
    steps = findings.get("remediation", {}).get("verification", [])
    if steps:
        flow += [Paragraph("8. Verification Plan", st["h2"]),
                 _kv_table([(f"Step {i}", s) for i, s in enumerate(steps, 1)], st)]
    return flow


def findings_to_pdf(bug, findings, generated_at):
    """Single-bug PDF. Returns bytes."""
    return bugs_to_pdf([(bug, findings)], generated_at)


def bugs_to_pdf(pairs, generated_at):
    """pairs = list of (bug, findings). Returns PDF bytes."""
    if not HAS_REPORTLAB:
        raise ReportError(
            "PDF export needs ReportLab. Install it with: pip install reportlab"
        )
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=APP_TITLE, author=APP_GROUP,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    flow = []
    for i, (bug, findings) in enumerate(pairs):
        if i:
            flow.append(PageBreak())
        flow += _flow_for_bug(bug, findings or {}, st, generated_at)
    doc.build(flow)
    return buf.getvalue()


def analytics_to_pdf(report, generated_at):
    if not HAS_REPORTLAB:
        raise ReportError("PDF export needs ReportLab. Run: pip install reportlab")
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Defect Pattern Analytics",
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)
    k = report["kpis"]
    flow = [
        Paragraph(_esc(APP_TITLE), st["title"]),
        Paragraph(f"{_esc(APP_GROUP)} &middot; Defect Pattern Analytics &middot; "
                  f"generated {_esc(generated_at)}", st["small"]),
        Paragraph("Key metrics", st["h2"]),
        _kv_table([(key.replace("_", " ").title(), val) for key, val in k.items()], st),
    ]
    for heading, rows, cols in (
        ("Severity distribution", report["severity"], ("severity", "count")),
        ("Most affected components", report["components"], ("component", "count")),
        ("Frequent root causes", report["root_causes"], ("root_cause", "count")),
        ("Frequent error types", report["error_types"], ("error_type", "count")),
        ("Recurring themes", report["themes"], ("theme", "count")),
        ("Status breakdown", report["statuses"], ("status", "count")),
    ):
        flow.append(Paragraph(heading, st["h2"]))
        flow.append(_kv_table([(r[cols[0]], r[cols[1]]) for r in rows] or
                              [("No data", "0")], st))
    flow.append(Paragraph(
        f"Defect trend ({report['trend']['granularity']})", st["h2"]))
    flow.append(_kv_table([(p["period"], p["count"])
                           for p in report["trend"]["points"]] or
                          [("No data", "0")], st))
    doc.build(flow)
    return buf.getvalue()


def analytics_to_csv(report):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Section", "Key", "Value"])
    for key, val in report["kpis"].items():
        w.writerow(["KPI", key, val])
    for section, rows, cols in (
        ("Severity", report["severity"], ("severity", "count")),
        ("Component", report["components"], ("component", "count")),
        ("Root cause", report["root_causes"], ("root_cause", "count")),
        ("Error type", report["error_types"], ("error_type", "count")),
        ("Theme", report["themes"], ("theme", "count")),
        ("Status", report["statuses"], ("status", "count")),
    ):
        for row in rows:
            w.writerow([section, row[cols[0]], row[cols[1]]])
    for point in report["trend"]["points"]:
        w.writerow([f"Trend ({report['trend']['granularity']})",
                    point["period"], point["count"]])
    return buf.getvalue()


def save_bytes(name, data):
    """Persist a report next to the app (useful for demo evidence)."""
    path = os.path.join(REPORT_DIR, name)
    mode = "wb" if isinstance(data, bytes) else "w"
    kwargs = {} if isinstance(data, bytes) else {"encoding": "utf-8"}
    with open(path, mode, **kwargs) as fh:
        fh.write(data)
    return path
