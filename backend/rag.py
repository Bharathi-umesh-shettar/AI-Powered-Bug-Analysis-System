"""Retrieval-Augmented Generation: Sentence Transformers embeddings + FAISS.

Extends the Milestone 1 implementation with:
  * a persisted FAISS index (saved to disk, reloaded on boot);
  * incremental `add_entry()` so verified bugs can grow the knowledge base
    without rebuilding or corrupting the existing index;
  * an offline deterministic fallback embedder for CI machines that cannot
    download the transformer weights (never used when the real model loads).

The public class name (`BugRAG`) and method (`search_similar_bugs`) are
unchanged so existing Milestone 1/2 callers keep working.
"""
import hashlib
import json
import os
import threading

import numpy as np

from config import (
    EMBEDDING_BACKEND,
    INDEX_META_PATH,
    INDEX_PATH,
    MODEL_NAME,
    TOP_K,
)
from database import fetch_all_knowledge

try:  # FAISS is the primary vector store.
    import faiss
    HAS_FAISS = True
except ImportError:  # pragma: no cover - exercised only on broken installs
    faiss = None
    HAS_FAISS = False

FALLBACK_DIM = 384  # matches all-MiniLM-L6-v2 so index files stay compatible


class HashingEmbedder:
    """Deterministic bag-of-words hashing embedder (offline fallback only).

    This is *not* a semantic model. It exists so the full pipeline, tests and
    analytics can run on a machine without the transformer weights. Whenever it
    is active, `BugRAG.backend` reports "hashing" and the UI/report says so.
    """

    dim = FALLBACK_DIM

    def encode(self, texts, convert_to_numpy=True, show_progress_bar=False):
        out = np.zeros((len(texts), self.dim), dtype="float32")
        for row, text in enumerate(texts):
            for token in str(text).lower().split():
                token = token.strip(".,:;()[]{}\"'`")
                if not token:
                    continue
                h = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16)
                out[row, h % self.dim] += 1.0
        return out


def _load_embedder():
    """Return (embedder, backend_name)."""
    if EMBEDDING_BACKEND == "hashing":
        return HashingEmbedder(), "hashing"
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(MODEL_NAME), f"sentence-transformers:{MODEL_NAME}"
    except Exception as exc:  # noqa: BLE001 - any load/download failure
        if EMBEDDING_BACKEND == "sentence-transformers":
            raise RuntimeError(
                f"Could not load '{MODEL_NAME}'. Install sentence-transformers "
                f"and allow the first-run download, or set "
                f"EMBEDDING_BACKEND=hashing for offline mode. Cause: {exc}"
            ) from exc
        print(f"[warn] sentence-transformers unavailable ({exc}); "
              f"falling back to offline hashing embedder.")
        return HashingEmbedder(), "hashing"


def _normalize(matrix):
    matrix = np.ascontiguousarray(matrix, dtype="float32")
    if HAS_FAISS:
        faiss.normalize_L2(matrix)
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class BugRAG:
    def __init__(self, auto_build=True):
        self.model, self.backend = _load_embedder()
        self.index = None
        self.records = []
        self._vectors = None  # kept for the numpy fallback path
        self._lock = threading.RLock()
        if auto_build:
            if not self.load_index():
                self.build_index()

    # -- text preparation ---------------------------------------------------
    def _text_of(self, r):
        """Knowledge text for one record (kept close to the original format)."""
        parts = [
            r.get("title", ""),
            r.get("description", ""),
            f"Component: {r.get('component') or r.get('category', '')}",
            f"Category: {r.get('category', '')}",
        ]
        if r.get("error_message"):
            parts.append(f"Error: {r['error_message']}")
        if r.get("root_cause"):
            parts.append(f"Root cause: {r['root_cause']}")
        if r.get("suggested_fix"):
            parts.append(f"Fix: {r['suggested_fix']}")
        return ". ".join(str(p) for p in parts if p)

    def embed(self, texts):
        vecs = self.model.encode(list(texts), convert_to_numpy=True,
                                 show_progress_bar=False)
        return _normalize(np.asarray(vecs, dtype="float32"))

    # -- index lifecycle ----------------------------------------------------
    def _new_index(self, dim):
        if HAS_FAISS:
            return faiss.IndexFlatIP(dim)
        return None

    def build_index(self, persist=True):
        """(Re)build the index from the knowledge_base table."""
        with self._lock:
            self.records = fetch_all_knowledge()
            if not self.records:
                self.index = None
                self._vectors = None
                return 0
            embeddings = self.embed(self._text_of(r) for r in self.records)
            self._vectors = embeddings
            self.index = self._new_index(embeddings.shape[1])
            if self.index is not None:
                self.index.add(embeddings)
            if persist:
                self.save_index()
            return len(self.records)

    def save_index(self):
        """Persist the index + metadata atomically (temp file then rename)."""
        with self._lock:
            if not self.records:
                return False
            meta = {
                "backend": self.backend,
                "count": len(self.records),
                "ids": [r.get("bug_id") for r in self.records],
            }
            tmp_meta = INDEX_META_PATH + ".tmp"
            with open(tmp_meta, "w", encoding="utf-8") as fh:
                json.dump(meta, fh)
            if HAS_FAISS and self.index is not None:
                tmp_index = INDEX_PATH + ".tmp"
                faiss.write_index(self.index, tmp_index)
                os.replace(tmp_index, INDEX_PATH)
            elif self._vectors is not None:
                tmp_index = INDEX_PATH + ".tmp"
                np.save(tmp_index + ".npy", self._vectors)
                os.replace(tmp_index + ".npy", INDEX_PATH)
            os.replace(tmp_meta, INDEX_META_PATH)
            return True

    def load_index(self):
        """Load a persisted index; returns False when it is missing or stale."""
        with self._lock:
            if not (os.path.exists(INDEX_PATH) and os.path.exists(INDEX_META_PATH)):
                return False
            try:
                with open(INDEX_META_PATH, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if meta.get("backend") != self.backend:
                    return False
                records = fetch_all_knowledge()
                if len(records) != meta.get("count") or \
                        [r.get("bug_id") for r in records] != meta.get("ids"):
                    return False  # DB changed behind our back -> rebuild
                if HAS_FAISS:
                    self.index = faiss.read_index(INDEX_PATH)
                    if self.index.ntotal != len(records):
                        return False
                else:
                    self._vectors = np.load(INDEX_PATH)
                    if self._vectors.shape[0] != len(records):
                        return False
                self.records = records
                return True
            except Exception as exc:  # noqa: BLE001 - never fail startup
                print(f"[warn] could not load FAISS index ({exc}); rebuilding.")
                return False

    # -- growth -------------------------------------------------------------
    def add_entry(self, record):
        """Append one knowledge-base record to the live index and persist it."""
        with self._lock:
            vec = self.embed([self._text_of(record)])
            if self.index is None and self._vectors is None:
                self.records = [record]
                self.index = self._new_index(vec.shape[1])
                if self.index is not None:
                    self.index.add(vec)
                else:
                    self._vectors = vec
            else:
                existing = [i for i, r in enumerate(self.records)
                            if r.get("bug_id") == record.get("bug_id")]
                if existing:
                    # Replacing an entry means the flat index must be rebuilt.
                    self.build_index()
                    return len(self.records)
                self.records.append(record)
                if self.index is not None:
                    self.index.add(vec)
                else:
                    self._vectors = np.vstack([self._vectors, vec])
            self.save_index()
            return len(self.records)

    # -- retrieval ----------------------------------------------------------
    def search_similar_bugs(self, query, k=TOP_K):
        if not self.records or not str(query).strip():
            return []
        with self._lock:
            vec = self.embed([query])
            k = min(k, len(self.records))
            if self.index is not None:
                scores, idxs = self.index.search(vec, k)
                pairs = zip(scores[0], idxs[0])
            else:
                sims = (self._vectors @ vec[0])
                order = np.argsort(-sims)[:k]
                pairs = ((sims[i], i) for i in order)
            results = []
            for score, i in pairs:
                if i < 0:
                    continue
                rec = dict(self.records[int(i)])
                rec["similarity"] = round(float(score), 4)
                results.append(rec)
            return results

    def stats(self):
        return {
            "backend": self.backend,
            "vector_store": "faiss" if HAS_FAISS else "numpy-fallback",
            "entries": len(self.records),
            "index_size": int(self.index.ntotal) if self.index is not None
            else (0 if self._vectors is None else int(self._vectors.shape[0])),
            "index_path": INDEX_PATH,
            "dimension": FALLBACK_DIM if not self.records else int(
                self.index.d if self.index is not None else self._vectors.shape[1]
            ),
        }
