"""Sentence embedding + FAISS index wrapper.

Uses SentenceTransformer (all-MiniLM-L6-v2) and a FAISS IndexFlatIP
on L2-normalized vectors, which is equivalent to cosine similarity.
"""
import os
import pickle
import threading

import numpy as np

from .config import EMBEDDING_MODEL, EMBEDDING_DIM, FAISS_INDEX_PATH, KB_META_PATH

_model = None
_index = None
_id_map = []  # position in FAISS -> kb_id
_lock = threading.Lock()


def get_model():
    """Lazy-load the sentence transformer to speed up app boot."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def encode(texts):
    """Encode a list of strings to normalized float32 embeddings."""
    if isinstance(texts, str):
        texts = [texts]
    model = get_model()
    vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return vecs.astype("float32")


def _new_index():
    import faiss
    return faiss.IndexFlatIP(EMBEDDING_DIM)


def build_index(id_vector_pairs):
    """Rebuild FAISS index from a list of (kb_id, vector) pairs."""
    global _index, _id_map
    import faiss

    with _lock:
        _index = _new_index()
        _id_map = []
        if id_vector_pairs:
            ids, vecs = zip(*id_vector_pairs)
            arr = np.vstack(vecs).astype("float32")
            _index.add(arr)
            _id_map = list(ids)
        faiss.write_index(_index, FAISS_INDEX_PATH)
        with open(KB_META_PATH, "wb") as f:
            pickle.dump(_id_map, f)


def load_index():
    """Load a persisted FAISS index from disk, if present."""
    global _index, _id_map
    import faiss

    if os.path.exists(FAISS_INDEX_PATH) and os.path.exists(KB_META_PATH):
        _index = faiss.read_index(FAISS_INDEX_PATH)
        with open(KB_META_PATH, "rb") as f:
            _id_map = pickle.load(f)
        return True
    return False


def ensure_index():
    if _index is None:
        load_index()
    return _index is not None


def search(query_text, top_k=5):
    """Return list of (kb_id, similarity_score) top-K matches."""
    if not ensure_index() or _index.ntotal == 0:
        return []
    vec = encode([query_text])
    scores, idxs = _index.search(vec, min(top_k, _index.ntotal))
    out = []
    for score, i in zip(scores[0], idxs[0]):
        if i == -1 or i >= len(_id_map):
            continue
        out.append((_id_map[i], float(score)))
    return out


def chunk_text(text, size=500):
    """Split long text into overlapping chunks for embedding."""
    text = text or ""
    if len(text) <= size:
        return [text] if text else []
    chunks = []
    step = size - 50
    for i in range(0, len(text), step):
        chunks.append(text[i : i + size])
    return chunks
