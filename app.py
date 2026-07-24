"""
AI-Powered Bug Analysis System
Main Flask Application Entrypoint

Run with:
    python app.py
"""
import os
import sys

# Ensure backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from backend.server import create_app  # noqa: E402
from backend.database import init_db  # noqa: E402
from backend.knowledge_base import bootstrap_knowledge_base  # noqa: E402
from backend.watcher import start_watcher, WATCH_DIR  # noqa: E402

if __name__ == "__main__":
    # Initialize DB schema
    init_db()
    # Load / build historical knowledge base + FAISS index (idempotent)
    bootstrap_knowledge_base()
    # Start folder watcher — drop .log/.txt files into ./logs to auto-ingest
    start_watcher()

    app = create_app()
    print("=" * 60)
    print(" AI-Powered Bug Analysis System")
    print(" Running on http://127.0.0.1:5000")
    print(f" Watching folder: {WATCH_DIR}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
