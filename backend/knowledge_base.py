"""Historical defect knowledge base.

On first boot, the knowledge base is seeded from:
    datasets/historical_bugs.csv

Then a FAISS index is built for semantic retrieval.
Subsequent boots load the existing FAISS index.
"""

import os

import numpy as np
import pandas as pd

from . import database as db
from . import embeddings as emb
from .config import DATASETS_DIR


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

SEED_CSV = os.path.join(
    DATASETS_DIR,
    "historical_bugs.csv"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(text):
    """Clean text values safely."""
    if not isinstance(text, str):
        return ""

    return " ".join(text.split()).strip()


# ---------------------------------------------------------------------------
# Load dataset
# ---------------------------------------------------------------------------

def _load_seed_dataframe() -> pd.DataFrame:
    """Load and clean the historical bug dataset."""

    if not os.path.exists(SEED_CSV):
        raise FileNotFoundError(
            f"Seed dataset missing: {SEED_CSV}"
        )

    df = pd.read_csv(SEED_CSV)

    # Clean available text columns.
    for col in (
        "title",
        "description",
        "root_cause",
        "suggested_fix",
        "category",
        "severity",
        "component",
        "error_message",
        "stack_trace",
        "resolution_details",
    ):
        if col in df.columns:
            df[col] = df[col].map(_clean)

    # Required columns.
    required_columns = {
        "title",
        "description",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            "historical_bugs.csv is missing required columns: "
            + ", ".join(sorted(missing))
        )

    # Remove empty records.
    df = df.dropna(
        subset=[
            "title",
            "description"
        ]
    )

    # Remove duplicate bugs.
    df = df.drop_duplicates(
        subset=[
            "title",
            "description"
        ]
    )

    df = df.reset_index(drop=True)

    return df


# ---------------------------------------------------------------------------
# Seed SQLite knowledge base
# ---------------------------------------------------------------------------

def _seed_database():
    """Insert dataset records into the SQLite knowledge base."""

    # Do not insert again if KB already contains records.
    if db.count_kb() > 0:
        return

    df = _load_seed_dataframe()

    for _, row in df.iterrows():
        db.insert_kb_row(
            row.to_dict()
        )


# ---------------------------------------------------------------------------
# Build FAISS index
# ---------------------------------------------------------------------------

def _build_faiss_from_kb():
    """Build FAISS index from SQLite knowledge-base records."""

    rows = db.fetch_knowledge_base()

    if not rows:
        print("[KB] No knowledge-base records found.")
        return

    pairs = []

    for r in rows:

        # Create text used for semantic embedding.
        text = (
            f"{r.get('title', '')}. "
            f"{r.get('description', '')}. "
            f"{r.get('component', '')}. "
            f"{r.get('category', '')}. "
            f"{r.get('root_cause', '')}. "
            f"{r.get('suggested_fix', '')}"
        )

        # Split long text into chunks.
        chunks = emb.chunk_text(
            text,
            size=500
        )

        if not chunks:
            chunks = [text]

        # Generate embeddings.
        vecs = emb.encode(chunks)

        # Mean pooling.
        mean_vec = vecs.mean(
            axis=0
        )

        # Normalize vector.
        norm = np.linalg.norm(
            mean_vec
        )

        if norm > 0:
            mean_vec = mean_vec / norm

        mean_vec = mean_vec.astype(
            "float32"
        )

        # IMPORTANT:
        # Your SQLite database uses "bug_id",
        # NOT "kb_id".
        kb_id = r.get("bug_id")

        if kb_id is None:
            print(
                "[KB] Warning: skipping record "
                "without bug_id."
            )
            continue

        pairs.append(
            (
                kb_id,
                mean_vec
            )
        )

    if not pairs:
        print(
            "[KB] No valid records available "
            "for FAISS index."
        )
        return

    # Build and persist FAISS index.
    emb.build_index(
        pairs
    )

    print(
        f"[KB] FAISS index built successfully "
        f"with {len(pairs)} records."
    )


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def bootstrap_knowledge_base():
    """Seed database and load/build FAISS index."""

    # Step 1: Seed SQLite database.
    _seed_database()

    # Step 2: Load existing FAISS index.
    if emb.load_index():

        print(
            f"[KB] Loaded existing FAISS index "
            f"({db.count_kb()} KB records)."
        )

        return

    # Step 3: Build FAISS index if one does not exist.
    print(
        "[KB] Building FAISS index "
        "from knowledge base..."
    )

    _build_faiss_from_kb()

    print(
        f"[KB] Indexed {db.count_kb()} records."
    )


# ---------------------------------------------------------------------------
# Similarity search
# ---------------------------------------------------------------------------

def find_similar(
    query_text,
    top_k=5
):
    """Return top-K similar historical bugs."""

    hits = emb.search(
        query_text,
        top_k=top_k
    )

    if not hits:
        return []

    # FAISS returns:
    # (bug_id, similarity_score)
    id_to_score = {
        bug_id: score
        for bug_id, score in hits
    }

    # Database also uses bug_id.
    rows = db.fetch_kb_by_ids(
        list(id_to_score.keys())
    )

    enriched = []

    for r in rows:

        bug_id = r.get("bug_id")

        score = id_to_score.get(
            bug_id,
            0.0
        )

        enriched.append(
            {
                **r,

                "similarity": round(
                    float(score),
                    4
                ),

                "similarity_pct": round(
                    float(score) * 100,
                    2
                ),
            }
        )

    # Highest similarity first.
    enriched.sort(
        key=lambda x: x["similarity"],
        reverse=True
    )

    return enriched