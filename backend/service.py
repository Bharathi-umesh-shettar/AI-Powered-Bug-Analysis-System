"""Shared application service layer.

Both the HTTP layer (app.py) and the Auto-Watch service (autowatch.py) go
through these functions, so a bug ingested from a watched folder gets exactly
the same diagnosis pipeline, duplicate detection and persistence as one
submitted through the UI.
"""
import json

from database import fetch_bug, insert_bug, update_bug


def create_bug(fields, source="manual", source_file=None):
    return insert_bug(
        fields["title"],
        fields["description"],
        fields.get("severity") or "Medium",
        fields.get("stack_trace") or "",
        error_message=fields.get("error_message"),
        component=fields.get("component"),
        environment=fields.get("environment"),
        additional_info=fields.get("additional_info"),
        source=source,
        source_file=source_file,
        status="Open",
    )


def diagnose_bug(bug_id, pipeline):
    """Run the agent pipeline for a stored bug and persist structured findings."""
    bug = fetch_bug(bug_id)
    if not bug:
        raise ValueError(f"Bug #{bug_id} does not exist.")
    findings = pipeline.run(bug)
    dup = findings["duplicate"]
    update_bug(
        bug_id,
        analysis_result=json.dumps(findings),
        root_cause=findings["possible_root_cause"],
        recommendation=findings["recommended_fix"],
        component=findings["component"],
        duplicate_of=dup.get("duplicate_of"),
        duplicate_status=dup.get("status"),
        duplicate_score=dup.get("confidence"),
        status="In Progress",
    )
    return fetch_bug(bug_id), findings


def ingest_and_diagnose(fields, pipeline, source="manual", source_file=None):
    bug_id = create_bug(fields, source=source, source_file=source_file)
    bug, findings = diagnose_bug(bug_id, pipeline)
    return bug, findings
