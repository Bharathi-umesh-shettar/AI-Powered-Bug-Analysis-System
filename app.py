"""
AI-Powered Bug Analysis System
Main Flask Application Entrypoint

Run with:
    python app.py
"""

import os
import sys

# Ensure backend package is importable
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from backend.server import create_app
from backend.database import init_db
from backend.knowledge_base import bootstrap_knowledge_base
from backend.watcher import start_watcher, WATCH_DIR


# ---------------------------------------------------------
# Create Flask application at module level
# ---------------------------------------------------------
# IMPORTANT:
# pytest imports this module and expects `app` to exist.
app = create_app()


# ---------------------------------------------------------
# Run application
# ---------------------------------------------------------
if __name__ == "__main__":

    # Initialize database schema
    init_db()

    # Load / build historical knowledge base + FAISS index
    bootstrap_knowledge_base()

    # Start folder watcher
    start_watcher()

    print("=" * 60)
    print(" AI-Powered Bug Analysis System")
    print(" Running on http://127.0.0.1:5000")
    print(f" Watching folder: {WATCH_DIR}")
    print("=" * 60)

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        use_reloader=False,
    )