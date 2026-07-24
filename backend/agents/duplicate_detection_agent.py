"""Duplicate Detection Agent (Milestone 3).

Performs semantic similarity search against previously submitted bugs
(SQLite `bugs` table) using the shared SentenceTransformer model.
Returns the top-K most likely duplicates with similarity %, status and
historical resolution (from the latest linked analysis, if any).

Threshold logic: bugs with similarity ≥ 0.80 are flagged as "Duplicate",
0.60–0.80 as "Likely Related", below as "Unique".
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from .. import database as db
from .. import embeddings as emb


DUPLICATE_THRESHOLD = 0.80
RELATED_THRESHOLD = 0.60


def _bug_text(b: Dict[str, Any]) -> str:
    return " ".join([
        b.get("title", "") or "",
        b.get("description", "") or "",
        b.get("component", "") or "",
    ]).strip()


class DuplicateDetectionAgent:
    name = "Duplicate Detection Agent"

    def analyze(
        self,
        bug: Dict[str, Any],
        top_k: int = 5,
    ) -> Dict[str, Any]:
        query = _bug_text(bug)
        current_id = bug.get("bug_id")

        prior = [b for b in db.fetch_all_bugs() if b.get("bug_id") != current_id]
        if not prior or not query:
            return {
                "is_duplicate": False,
                "duplicate_of": None,
                "top_similarity_pct": 0,
                "matches": [],
            }

        # Encode query + all prior bug texts
        query_vec = emb.encode([query])[0]
        prior_texts = [_bug_text(b) or (b.get("title") or "bug") for b in prior]
        prior_vecs = emb.encode(prior_texts)

        # cosine similarity via normalized dot product
        sims = (prior_vecs @ query_vec).astype(float)
        order = np.argsort(-sims)[:top_k]

        matches: List[Dict[str, Any]] = []
        for idx in order:
            b = prior[idx]
            score = float(sims[idx])
            analysis = db.fetch_analysis_for_bug(b["bug_id"]) or {}
            resolution = (
                analysis.get("root_cause")
                or analysis.get("structured_summary")
                or "No historical resolution recorded."
            )
            if score >= DUPLICATE_THRESHOLD:
                status = "Duplicate"
            elif score >= RELATED_THRESHOLD:
                status = "Likely Related"
            else:
                status = "Weak Match"
            matches.append({
                "bug_id": b["bug_id"],
                "title": b.get("title"),
                "similarity_pct": round(score * 100, 2),
                "similarity": round(score, 4),
                "status": status,
                "severity": b.get("severity"),
                "component": b.get("component"),
                "reporter": b.get("reporter"),
                "created_date": b.get("created_date"),
                "historical_resolution": resolution,
            })

        top = matches[0] if matches else None
        is_dup = bool(top and top["similarity"] >= DUPLICATE_THRESHOLD)

        return {
            "is_duplicate": is_dup,
            "duplicate_of": top["bug_id"] if is_dup else None,
            "top_similarity_pct": top["similarity_pct"] if top else 0,
            "matches": matches,
        }


def run_duplicate_detection(bug, top_k: int = 5):
    return DuplicateDetectionAgent().analyze(bug, top_k=top_k)
