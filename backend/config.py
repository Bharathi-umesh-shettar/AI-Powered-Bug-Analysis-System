"""
Central configuration for the Intelligent Bug Diagnosis Platform.

All application paths and tunable settings are defined here.
Values can be overridden using environment variables so the same
configuration works locally, in CI, Docker, or other environments.
"""

import os


# =============================================================================
# BASE PATHS
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))


def _path(env_var, *default_parts):
    """
    Resolve a path from an environment variable.

    If the environment variable exists, its value is expanded and converted
    to an absolute path. Otherwise, the supplied default path is used.
    """
    value = os.environ.get(env_var)

    if value:
        return os.path.abspath(os.path.expanduser(value))

    return os.path.abspath(os.path.join(*default_parts))


# =============================================================================
# APPLICATION
# =============================================================================

APP_TITLE = os.environ.get(
    "APP_TITLE",
    "Creation of Intelligent Bug Diagnosis Platform with Fix Recommendation Assistance",
)

APP_GROUP = os.environ.get(
    "APP_GROUP",
    "Group 1",
)


# =============================================================================
# DATABASE / STORAGE
# =============================================================================

DB_PATH = _path(
    "BUG_DB_PATH",
    BASE_DIR,
    "bugs.db",
)

INDEX_PATH = _path(
    "FAISS_INDEX_PATH",
    BASE_DIR,
    "faiss.index",
)

INDEX_META_PATH = _path(
    "FAISS_META_PATH",
    BASE_DIR,
    "faiss_meta.json",
)

DATASET_PATH = _path(
    "BUG_DATASET_PATH",
    PROJECT_ROOT,
    "datasets",
    "bug_dataset.csv",
)

DATASETS_DIR = _path(
    "BUG_DATASETS_DIR",
    PROJECT_ROOT,
    "datasets",
)


# =============================================================================
# FILE UPLOAD
# =============================================================================

UPLOAD_DIR = _path(
    "UPLOAD_DIR",
    PROJECT_ROOT,
    "uploads",
)

MAX_UPLOAD_MB = int(
    os.environ.get(
        "MAX_UPLOAD_MB",
        "10",
    )
)

ALLOWED_UPLOAD_EXT = tuple(
    extension.strip().lower()
    for extension in os.environ.get(
        "ALLOWED_UPLOAD_EXT",
        ".txt,.log,.trace,.stacktrace,.csv",
    ).split(",")
    if extension.strip()
)


# =============================================================================
# AUTO-WATCH
# =============================================================================

WATCH_DIR = _path(
    "WATCH_DIR",
    PROJECT_ROOT,
    "logs_watch",
)

WATCH_INTERVAL_SECONDS = float(
    os.environ.get(
        "WATCH_INTERVAL_SECONDS",
        "5",
    )
)

WATCH_EXTENSIONS = tuple(
    extension.strip().lower()
    for extension in os.environ.get(
        "WATCH_EXTENSIONS",
        ".log,.txt",
    ).split(",")
    if extension.strip()
)

WATCH_MAX_BYTES = int(
    os.environ.get(
        "WATCH_MAX_BYTES",
        str(2 * 1024 * 1024),
    )
)


# =============================================================================
# AUTO-WATCH STARTUP
# =============================================================================

AUTOWATCH_ON_START = (
    os.environ.get(
        "AUTOWATCH_ON_START",
        "1",
    ).strip().lower()
    in ("1", "true", "yes", "on")
)


# =============================================================================
# REPORTS
# =============================================================================

REPORT_DIR = _path(
    "REPORT_DIR",
    PROJECT_ROOT,
    "reports",
)


# =============================================================================
# EMBEDDINGS / RAG
# =============================================================================

MODEL_NAME = os.environ.get(
    "EMBEDDING_MODEL",
    "all-MiniLM-L6-v2",
)

EMBEDDING_BACKEND = os.environ.get(
    "EMBEDDING_BACKEND",
    "auto",
).strip().lower()

TOP_K = int(
    os.environ.get(
        "RAG_TOP_K",
        "5",
    )
)


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================

EMBEDDING_MODEL = MODEL_NAME

# all-MiniLM-L6-v2 uses 384-dimensional embeddings.
EMBEDDING_DIM = 384

FAISS_INDEX_PATH = INDEX_PATH

KB_META_PATH = INDEX_META_PATH


# =============================================================================
# AGENT THRESHOLDS
# =============================================================================

DUPLICATE_THRESHOLD = float(
    os.environ.get(
        "DUPLICATE_THRESHOLD",
        "0.85",
    )
)

SIMILAR_THRESHOLD = float(
    os.environ.get(
        "SIMILAR_THRESHOLD",
        "0.60",
    )
)


# =============================================================================
# ALLOWED VALUES
# =============================================================================

SEVERITIES = (
    "Critical",
    "High",
    "Medium",
    "Low",
)

STATUSES = (
    "Open",
    "In Progress",
    "Resolved",
    "Resolved & Verified",
    "Closed",
)


# =============================================================================
# REQUIRED DIRECTORIES
# =============================================================================

for directory in (
    REPORT_DIR,
    WATCH_DIR,
    UPLOAD_DIR,
):
    os.makedirs(
        directory,
        exist_ok=True,
    )