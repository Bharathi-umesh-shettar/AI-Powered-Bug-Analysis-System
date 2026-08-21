"""
Duplicate Detection Agent (Milestone 3).

Performs semantic similarity search against previously submitted bugs
in the SQLite `bugs` table using the shared SentenceTransformer model.

Returns the top-K most likely duplicates with similarity percentage,
status, and historical resolution.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from .. import database as db
from .. import embeddings as emb


DUPLICATE_THRESHOLD = 0.80
RELATED_THRESHOLD = 0.60


def _bug_text(bug: Dict[str, Any]) -> str:
    """Build searchable text from a bug."""
    return " ".join(
        [
            bug.get("title", "") or "",
            bug.get("description", "") or "",
            bug.get("component", "") or "",
        ]
    ).strip()


class DuplicateDetectionAgent:
    name = "Duplicate Detection Agent"

    def analyze(
        self,
        bug: Dict[str, Any],
        top_k: int = 5,
    ) -> Dict[str, Any]:

        query = _bug_text(bug)
        current_id = bug.get("bug_id")

        # Get previously submitted bugs
        prior = [
            existing_bug
            for existing_bug in db.fetch_all_bugs()
            if existing_bug.get("bug_id") != current_id
        ]

        # Nothing to compare against
        if not prior or not query:
            return {
                "is_duplicate": False,
                "duplicate_of": None,
                "top_similarity_pct": 0,
                "matches": [],
            }

        # Encode current bug
        query_vec = emb.encode([query])[0]

        # Encode previous bugs
        prior_texts = [
            _bug_text(existing_bug)
            or (existing_bug.get("title") or "bug")
            for existing_bug in prior
        ]

        prior_vecs = emb.encode(prior_texts)

        # SentenceTransformer embeddings are normalized,
        # therefore dot product gives cosine similarity.
        sims = (prior_vecs @ query_vec).astype(float)

        # Highest similarity first
        order = np.argsort(-sims)[:top_k]

        matches: List[Dict[str, Any]] = []

        for idx in order:
            existing_bug = prior[idx]
            score = float(sims[idx])

            # Get latest analysis/resolution
            analysis = (
                db.fetch_analysis_for_bug(existing_bug["bug_id"])
                or {}
            )

            resolution = (
                analysis.get("root_cause")
                or analysis.get("structured_summary")
                or "No historical resolution recorded."
            )

            # Determine match status
            if score >= DUPLICATE_THRESHOLD:
                status = "Duplicate"
            elif score >= RELATED_THRESHOLD:
                status = "Likely Related"
            else:
                status = "Weak Match"

            matches.append(
                {
                    "bug_id": existing_bug["bug_id"],
                    "title": existing_bug.get("title"),
                    "similarity_pct": round(score * 100, 2),
                    "similarity": round(score, 4),
                    "status": status,
                    "severity": existing_bug.get("severity"),
                    "component": existing_bug.get("component"),
                    "reporter": existing_bug.get("reporter"),
                    "created_date": existing_bug.get("created_date"),
                    "historical_resolution": resolution,
                }
            )

        # Best match
        top = matches[0] if matches else None

        is_duplicate = bool(
            top and top["similarity"] >= DUPLICATE_THRESHOLD
        )

        return {
            "is_duplicate": is_duplicate,
            "duplicate_of": top["bug_id"] if is_duplicate else None,
            "top_similarity_pct": top["similarity_pct"] if top else 0,
            "matches": matches,
        }


def run_duplicate_detection(
    bug: Dict[str, Any],
    top_k: int = 5,
) -> Dict[str, Any]:
    """Run duplicate detection for a bug."""
    return DuplicateDetectionAgent().analyze(
        bug,
        top_k=top_k,
    )