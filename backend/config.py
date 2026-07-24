"""Central configuration for the Bug Analysis System."""
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DB_PATH = os.path.join(BASE_DIR, "bug_analysis.sqlite")
MODELS_DIR = os.path.join(BASE_DIR, "models")
DATASETS_DIR = os.path.join(BASE_DIR, "datasets")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
FAISS_INDEX_PATH = os.path.join(MODELS_DIR, "faiss.index")
KB_META_PATH = os.path.join(MODELS_DIR, "kb_meta.pkl")

os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(DATASETS_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
TOP_K = 5
CHUNK_SIZE = 500  # characters per chunk for long reports
MAX_UPLOAD_MB = 5
ALLOWED_UPLOAD_EXT = {".txt", ".log"}
