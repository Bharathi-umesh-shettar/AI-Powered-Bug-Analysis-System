"""Historical defect knowledge base.

On first boot we seed the KB from a bundled sample dataset (curated from
public Mozilla / Apache / Eclipse / Kaggle-style bug entries) and build a
FAISS index. Subsequent boots simply load the persisted index.
"""
import os

import pandas as pd

from . import database as db
from . import embeddings as emb
from .config import DATASETS_DIR


SEED_CSV = os.path.join(DATASETS_DIR, "historical_bugs.csv")


def _clean(text):
    if not isinstance(text, str):
        return ""
    return " ".join(text.split()).strip()


def _load_seed_dataframe() -> pd.DataFrame:
    if not os.path.exists(SEED_CSV):
        raise FileNotFoundError(f"Seed dataset missing: {SEED_CSV}")
    df = pd.read_csv(SEED_CSV)
    # Clean
    for col in ("title", "description", "root_cause", "suggested_fix"):
        if col in df.columns:
            df[col] = df[col].map(_clean)
    # Drop empties + duplicates
    df = df.dropna(subset=["title", "description"])
    df = df.drop_duplicates(subset=["title", "description"])
    df = df.reset_index(drop=True)
    return df


def _seed_database():
    """Insert KB rows from CSV if the table is empty."""
    if db.count_kb() > 0:
        return
    df = _load_seed_dataframe()
    for _, row in df.iterrows():
        db.insert_kb_row(row.to_dict())


def _build_faiss_from_kb():
    rows = db.fetch_knowledge_base()
    pairs = []
    for r in rows:
        # Chunk long descriptions but store one representative vector per KB row
        # (mean-pool of chunk vectors) so retrieval maps 1:1 to a KB entry.
        text = f"{r['title']}. {r['description']} {r.get('component','')} {r.get('category','')}"
        chunks = emb.chunk_text(text, size=500) or [text]
        vecs = emb.encode(chunks)
        mean_vec = vecs.mean(axis=0)
        # re-normalize
        import numpy as np
        norm = np.linalg.norm(mean_vec) or 1.0
        mean_vec = (mean_vec / norm).astype("float32")
        pairs.append((r["kb_id"], mean_vec))
    emb.build_index(pairs)


def bootstrap_knowledge_base():
    """Idempotent: seed DB + build/load FAISS index."""
    _seed_database()
    if not emb.load_index():
        print("[KB] Building FAISS index from knowledge base...")
        _build_faiss_from_kb()
        print(f"[KB] Indexed {db.count_kb()} records.")
    else:
        print(f"[KB] Loaded existing FAISS index ({db.count_kb()} KB records).")


def find_similar(query_text, top_k=5):
    """Return enriched top-K similar KB records for a query."""
    hits = emb.search(query_text, top_k=top_k)
    if not hits:
        return []
    id_to_score = {kb_id: score for kb_id, score in hits}
    rows = db.fetch_kb_by_ids(list(id_to_score.keys()))
    enriched = []
    for r in rows:
        score = id_to_score.get(r["kb_id"], 0.0)
        enriched.append(
            {
                **r,
                "similarity": round(float(score), 4),
                "similarity_pct": round(float(score) * 100, 2),
            }
        )
    enriched.sort(key=lambda x: x["similarity"], reverse=True)
    return enriched
