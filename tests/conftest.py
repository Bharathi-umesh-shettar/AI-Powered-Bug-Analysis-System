"""
Pytest fixtures for the AI-Powered Bug Analysis System.

The test suite uses:
- Temporary SQLite database
- Temporary FAISS index
- Temporary watch directory
- Temporary report directory
- Offline hashing embeddings

The real project database and FAISS files are never modified.
"""

import os
import sys
import tempfile

import pytest


# ============================================================
# PROJECT PATHS
# ============================================================

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TESTS_DIR, ".."))
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures")


# ============================================================
# TEMPORARY TEST ENVIRONMENT
# ============================================================

_TMP = tempfile.mkdtemp(prefix="bugdiag-tests-")


os.environ["EMBEDDING_BACKEND"] = "hashing"

os.environ["BUG_DB_PATH"] = os.path.join(
    _TMP,
    "bugs.db",
)

os.environ["FAISS_INDEX_PATH"] = os.path.join(
    _TMP,
    "faiss.index",
)

os.environ["FAISS_META_PATH"] = os.path.join(
    _TMP,
    "faiss_meta.json",
)

os.environ["WATCH_DIR"] = os.path.join(
    _TMP,
    "logs_watch",
)

os.environ["REPORT_DIR"] = os.path.join(
    _TMP,
    "reports",
)

os.environ["AUTOWATCH_ON_START"] = "0"


# ============================================================
# PROJECT ROOT ON PYTHON PATH
# ============================================================

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ============================================================
# CREATE REQUIRED DIRECTORIES
# ============================================================

os.makedirs(os.environ["WATCH_DIR"], exist_ok=True)
os.makedirs(os.environ["REPORT_DIR"], exist_ok=True)
os.makedirs(FIXTURES_DIR, exist_ok=True)


# ============================================================
# FLASK APPLICATION
# ============================================================

@pytest.fixture(scope="session")
def flask_app():
    """
    Create the Flask application once for the entire test session.
    """

    # Import package correctly
    from backend.server import create_app

    # Import database after environment variables are configured
    from backend import database as db

    # Create database schema for the temporary test database
    db.init_db()

    # Create Flask application
    app = create_app()

    # Testing configuration
    app.config.update(
        TESTING=True,
        DEBUG=False,
    )

    return app


# ============================================================
# FLASK TEST CLIENT
# ============================================================

@pytest.fixture(scope="session")
def client(flask_app):
    """
    Flask test client.
    """

    return flask_app.test_client()


# ============================================================
# WATCH DIRECTORY
# ============================================================

@pytest.fixture(scope="session")
def watch_dir():
    """
    Temporary directory used by Auto-Watch tests.
    """

    path = os.environ["WATCH_DIR"]

    os.makedirs(
        path,
        exist_ok=True,
    )

    return path


# ============================================================
# TEST FIXTURES DIRECTORY
# ============================================================

@pytest.fixture(scope="session")
def fixtures_dir():
    """
    Directory containing test bug files.
    """

    return FIXTURES_DIR