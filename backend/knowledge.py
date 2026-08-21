"""Knowledge Base Growth mechanism (Milestone 4.2).

Only bugs that are BOTH resolved AND verified become knowledge-base entries.
Adding an entry prepares the knowledge text, generates its embedding with the
existing Sentence Transformer, appends it to the FAISS index, and stores the
metadata so future RAG retrieval can find it.
"""
from database import (
    fetch_bug,
    find_knowledge_by_source_bug,
    insert_knowledge_entry,
    next_knowledge_id,
    now_iso,
    update_bug,
)

VERIFIED_STATUS = "Resolved & Verified"


class KnowledgeGrowthError(Exception):
    """Raised when a bug is not eligible for the knowledge base."""


def is_eligible(bug):
    """A bug qualifies only when resolved and explicitly verified."""
    if not bug:
        return False, "Bug not found."
    if int(bug.get("verified") or 0) != 1:
        return False, ("Bug is not verified. Mark it 'Resolved & Verified' with a "
                       "confirmed fix before promoting it.")
    if (bug.get("status") or "") not in ("Resolved", VERIFIED_STATUS, "Closed"):
        return False, f"Bug status is '{bug.get('status')}', not resolved."
    if not (bug.get("resolution_details") or bug.get("recommendation")):
        return False, "A confirmed fix / resolution detail is required."
    return True, "Eligible."


def resolve_and_verify(bug_id, root_cause=None, confirmed_fix=None,
                       resolution_details=None, verified=True):
    """Mark a bug resolved, and optionally verified, recording the real fix."""
    bug = fetch_bug(bug_id)
    if not bug:
        raise KnowledgeGrowthError(f"Bug #{bug_id} does not exist.")
    if verified and not (confirmed_fix or resolution_details or
                         bug.get("resolution_details")):
        raise KnowledgeGrowthError(
            "A confirmed fix is required to verify a resolution."
        )
    fields = {
        "status": VERIFIED_STATUS if verified else "Resolved",
        "verified": 1 if verified else 0,
        "resolved_at": now_iso(),
    }
    if root_cause:
        fields["root_cause"] = root_cause
    if confirmed_fix:
        fields["recommendation"] = confirmed_fix
    if resolution_details:
        fields["resolution_details"] = resolution_details
    update_bug(bug_id, **fields)
    return fetch_bug(bug_id)


def build_entry(bug, kb_id=None):
    """Assemble the knowledge-base record for a verified bug."""
    findings = bug.get("findings") or {}
    component = bug.get("component") or findings.get("component") or "Unclassified"
    return {
        "bug_id": kb_id if kb_id is not None else next_knowledge_id(),
        "title": bug.get("title"),
        "description": bug.get("description"),
        "category": component,
        "component": component,
        "severity": bug.get("severity"),
        "root_cause": bug.get("root_cause") or findings.get("possible_root_cause") or "",
        "suggested_fix": bug.get("recommendation")
                         or findings.get("recommended_fix") or "",
        "error_message": bug.get("error_message") or "",
        "stack_trace": bug.get("stack_trace") or "",
        "resolution_details": bug.get("resolution_details") or "",
        "created_at": now_iso(),
        "origin": "verified_bug",
        "source_bug_id": bug.get("id"),
    }


def promote_to_knowledge_base(bug_id, rag):
    """Full growth workflow for one verified bug.

    Returns a dict describing what happened; raises KnowledgeGrowthError when the
    bug is not eligible. Re-promoting the same bug updates the existing entry
    rather than creating a duplicate, so the FAISS index never accumulates
    conflicting copies.
    """
    bug = fetch_bug(bug_id)
    ok, reason = is_eligible(bug)
    if not ok:
        raise KnowledgeGrowthError(reason)

    existing = find_knowledge_by_source_bug(bug_id)
    entry = build_entry(bug, kb_id=existing["bug_id"] if existing else None)
    insert_knowledge_entry(entry)

    before = len(rag.records)
    total = rag.add_entry(entry)
    update_bug(bug_id, in_knowledge_base=1)

    return {
        "knowledge_id": entry["bug_id"],
        "source_bug_id": bug_id,
        "updated_existing": bool(existing),
        "entries_before": before,
        "entries_after": total,
        "index_size": rag.stats()["index_size"],
        "embedding_backend": rag.backend,
        "knowledge_text_preview": rag._text_of(entry)[:400],
        "entry": entry,
    }
