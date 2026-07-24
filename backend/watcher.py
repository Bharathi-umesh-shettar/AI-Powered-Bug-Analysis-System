"""Folder Watcher (Advanced Automation).

Watches <project>/logs/ for new .log/.txt files.

Workflow:
1. Detect new log file
2. Read content
3. Create bug record
4. Run AI multi-agent pipeline
5. Store result in database
6. Update dashboard automatically

Uses lightweight polling (no watchdog dependency).
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List

from . import database as db
from . import knowledge_base as kb
from .config import BASE_DIR
from .orchestrator import run_pipeline


# ---------------- Configuration ----------------

WATCH_DIR = os.path.join(BASE_DIR, "logs")
MANIFEST_PATH = os.path.join(BASE_DIR, "models", "watched_files.json")

POLL_INTERVAL_SEC = 3
ALLOWED_EXT = {".log", ".txt"}


# Create required folders
os.makedirs(WATCH_DIR, exist_ok=True)
os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)


# ---------------- Runtime State ----------------

_lock = threading.Lock()

_state: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "processed": [],
    "errors": []
}


# ---------------- Manifest Handling ----------------

def _load_manifest() -> Dict[str, float]:
    """Load already processed files."""

    if not os.path.exists(MANIFEST_PATH):
        return {}

    try:
        with open(
            MANIFEST_PATH,
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except Exception:
        return {}



def _save_manifest(manifest: Dict[str, float]) -> None:
    """Save processed files."""

    try:
        with open(
            MANIFEST_PATH,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                manifest,
                file,
                indent=4
            )

    except Exception:
        pass



# ---------------- Severity Detection ----------------

def _detect_severity(content: str) -> str:

    text = content.lower()

    if any(word in text for word in [
        "fatal",
        "critical",
        "system crash",
        "out of memory"
    ]):
        return "Critical"

    if any(word in text for word in [
        "exception",
        "failed",
        "error",
        "timeout"
    ]):
        return "High"

    if "warning" in text:
        return "Medium"

    return "Low"



# ---------------- File Processing ----------------

def _process_file(path: str) -> Dict[str, Any]:

    filename = os.path.basename(path)


    with open(
        path,
        "r",
        encoding="utf-8",
        errors="ignore"
    ) as file:

        content = file.read()



    title = f"[Auto] {filename}"

    description = (
        content.strip()[:800]
        or
        f"Auto ingested log file {filename}"
    )


    severity = _detect_severity(content)


    bug_data = {

        "title": title,

        "description": description,

        "severity": severity,

        "category": "Auto-Ingested",

        "component": "",

        "reporter": "folder-watcher",

        "stack_trace":
            content
            if "trace" in filename.lower()
            else "",

        "error_log": content
    }



    # Save bug
    bug_id = db.insert_bug(bug_data)

    db.update_bug_embedding_status(
        bug_id,
        "ok"
    )



    # RAG search
    similar = kb.find_similar(
        f"{title}. {description}",
        top_k=5
    )



    bug_record = {
        **bug_data,
        "bug_id": bug_id
    }



    # AI pipeline
    analysis = run_pipeline(
        bug_record,
        similar=similar,
        persist=True
    )



    return {

        "bug_id": bug_id,

        "file": filename,

        "severity":
            analysis.get(
                "severity",
                severity
            ),

        "exception_type":
            analysis.get(
                "exception_type"
            ),

        "affected_component":
            analysis.get(
                "affected_component"
            ),

        "confidence":
            analysis.get(
                "confidence"
            ),

        "processed_at":
            datetime.utcnow()
            .isoformat(timespec="seconds")
    }



# ---------------- Scanner ----------------

def _scan_once(
        manifest: Dict[str, float]
) -> List[Dict[str, Any]]:


    new_items = []


    try:
        files = os.listdir(WATCH_DIR)

    except FileNotFoundError:

        os.makedirs(
            WATCH_DIR,
            exist_ok=True
        )

        return new_items



    for filename in sorted(files):

        path = os.path.join(
            WATCH_DIR,
            filename
        )


        if not os.path.isfile(path):
            continue


        ext = os.path.splitext(filename)[1].lower()


        if ext not in ALLOWED_EXT:
            continue



        try:
            modified = os.path.getmtime(path)

        except OSError:
            continue



        file_key = f"{filename}:{int(modified)}"



        if file_key in manifest:
            continue



        try:

            result = _process_file(path)


            manifest[file_key] = time.time()


            new_items.append(result)



            with _lock:

                _state["processed"].insert(
                    0,
                    result
                )

                _state["processed"] = (
                    _state["processed"][:50]
                )


        except Exception as error:


            with _lock:

                _state["errors"].insert(
                    0,
                    {
                        "file": filename,
                        "error": str(error),
                        "at":
                            datetime.utcnow()
                            .isoformat(
                                timespec="seconds"
                            )
                    }
                )

                _state["errors"] = (
                    _state["errors"][:20]
                )



    if new_items:

        _save_manifest(manifest)



    return new_items



# ---------------- Background Worker ----------------

def _loop():

    manifest = _load_manifest()


    while True:

        with _lock:

            running = _state["running"]


        if not running:
            break


        try:

            _scan_once(manifest)


        except Exception as error:


            with _lock:

                _state["errors"].insert(
                    0,
                    {
                        "file": "*",
                        "error": str(error),
                        "at":
                            datetime.utcnow()
                            .isoformat(
                                timespec="seconds"
                            )
                    }
                )


        time.sleep(
            POLL_INTERVAL_SEC
        )



# ---------------- Public Controls ----------------

def start_watcher():

    with _lock:

        if _state["running"]:
            return


        _state["running"] = True

        _state["started_at"] = (
            datetime.utcnow()
            .isoformat(
                timespec="seconds"
            )
        )



    thread = threading.Thread(
        target=_loop,
        name="BugFolderWatcher",
        daemon=True
    )


    thread.start()



def stop_watcher():

    with _lock:

        _state["running"] = False



def watcher_status():

    with _lock:

        return {

            "running":
                _state["running"],

            "started_at":
                _state["started_at"],

            "watch_dir":
                WATCH_DIR,

            "poll_interval_sec":
                POLL_INTERVAL_SEC,

            "processed_count":
                len(
                    _state["processed"]
                ),

            "processed":
                list(
                    _state["processed"]
                ),

            "errors":
                list(
                    _state["errors"]
                )
        }



def scan_now():

    manifest = _load_manifest()

    return _scan_once(manifest)