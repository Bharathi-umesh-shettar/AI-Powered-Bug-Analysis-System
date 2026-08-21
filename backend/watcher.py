"""
Folder Watcher for the Intelligent Bug Diagnosis Platform.

Responsibilities:
1. Monitor the configured logs folder.
2. Detect new .log and .txt files.
3. Read file contents.
4. Create bug records in the database.
5. Run RAG similarity search.
6. Run the AI multi-agent pipeline.
7. Store the analysis.
8. Maintain a manifest so the same file is not processed repeatedly.
9. Support scan_once() for tests.
10. Support scan_now() for Flask API.
11. Support background polling.
12. Respect WATCH_DIR from central configuration/environment.
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
from .config import (
    WATCH_DIR,
    WATCH_EXTENSIONS,
    WATCH_INTERVAL_SECONDS,
)
from .orchestrator import run_pipeline


# =============================================================================
# CONFIGURATION
# =============================================================================

# IMPORTANT:
# Use WATCH_DIR from config.py.
#
# conftest.py sets:
#
#     os.environ["WATCH_DIR"] = temporary_directory
#
# Therefore tests and production can use different watch folders.

WATCH_DIR = os.path.abspath(
    os.path.expanduser(WATCH_DIR)
)

POLL_INTERVAL_SEC = float(
    WATCH_INTERVAL_SECONDS
)

# Use extensions from config.py.
ALLOWED_EXT = {
    extension.strip().lower()
    for extension in WATCH_EXTENSIONS
    if extension.strip()
}

# Fallback in case configuration is empty.
if not ALLOWED_EXT:
    ALLOWED_EXT = {
        ".log",
        ".txt",
    }


# =============================================================================
# MANIFEST
# =============================================================================

# Keep manifest inside the configured watch directory.
#
# This is especially useful for tests because every test session gets its
# own temporary WATCH_DIR.

MANIFEST_PATH = os.path.join(
    WATCH_DIR,
    ".watched_files.json",
)


# =============================================================================
# CREATE REQUIRED DIRECTORIES
# =============================================================================

os.makedirs(
    WATCH_DIR,
    exist_ok=True,
)


# =============================================================================
# RUNTIME STATE
# =============================================================================

_lock = threading.Lock()

_state: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "processed": [],
    "errors": [],
}


# =============================================================================
# TIME HELPER
# =============================================================================

def _now() -> str:
    """
    Return current UTC timestamp.
    """

    return datetime.utcnow().isoformat(
        timespec="seconds"
    )


# =============================================================================
# MANIFEST
# =============================================================================

def _load_manifest() -> Dict[str, float]:
    """
    Load already processed files.

    Manifest format:

        {
            "filename.log:123456789": 1234567890.0
        }
    """

    if not os.path.exists(
        MANIFEST_PATH
    ):
        return {}

    try:

        with open(
            MANIFEST_PATH,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        if isinstance(
            data,
            dict,
        ):
            return data

        return {}

    except Exception:

        return {}


def _save_manifest(
    manifest: Dict[str, float],
) -> None:
    """
    Save processed-file information.
    """

    try:

        os.makedirs(
            os.path.dirname(
                MANIFEST_PATH
            ),
            exist_ok=True,
        )

        temporary_path = (
            MANIFEST_PATH + ".tmp"
        )

        with open(
            temporary_path,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                manifest,
                file,
                indent=4,
            )

        # Replace old manifest safely.
        os.replace(
            temporary_path,
            MANIFEST_PATH,
        )

    except Exception:
        # Manifest failure should never crash the watcher.
        pass


# =============================================================================
# SEVERITY DETECTION
# =============================================================================

def _detect_severity(
    content: str,
) -> str:
    """
    Determine bug severity from log content.
    """

    text = (
        content or ""
    ).lower()

    # Critical
    if any(
        word in text
        for word in (
            "fatal",
            "critical",
            "system crash",
            "out of memory",
        )
    ):
        return "Critical"

    # High
    if any(
        word in text
        for word in (
            "exception",
            "failed",
            "error",
            "timeout",
            "connection refused",
            "deadlock",
        )
    ):
        return "High"

    # Medium
    if any(
        word in text
        for word in (
            "warning",
            "slow",
            "degraded",
        )
    ):
        return "Medium"

    # Low
    return "Low"


# =============================================================================
# COMPONENT DETECTION
# =============================================================================

def _detect_component(
    content: str,
) -> str:
    """
    Extract component from log content.

    Example:

        Component: Reporting

    returns:

        Reporting
    """

    if not content:
        return ""

    for line in content.splitlines():

        line = line.strip()

        if line.lower().startswith(
            "component:"
        ):

            return line.split(
                ":",
                1,
            )[1].strip()

    return ""


# =============================================================================
# ERROR TYPE DETECTION
# =============================================================================

def _detect_error_type(
    content: str,
) -> str:
    """
    Try to detect a common error type.
    """

    text = (
        content or ""
    ).lower()

    if "deadlock" in text:
        return "Deadlock"

    if "timeout" in text:
        return "Timeout"

    if "connection refused" in text:
        return "Connection Error"

    if "authentication" in text:
        return "Authentication Error"

    if "unauthorized" in text:
        return "Authorization Error"

    if "exception" in text:
        return "Exception"

    if "error" in text:
        return "Error"

    return "Unknown"


# =============================================================================
# BUG PROCESSING
# =============================================================================

def _process_file(
    path: str,
) -> Dict[str, Any]:
    """
    Process one log file completely.

    Steps:

        file
          ↓
        read content
          ↓
        create bug
          ↓
        database
          ↓
        RAG similarity
          ↓
        AI pipeline
          ↓
        return processed result
    """

    filename = os.path.basename(
        path
    )

    # -------------------------------------------------------------------------
    # Read file
    # -------------------------------------------------------------------------

    with open(
        path,
        "r",
        encoding="utf-8",
        errors="ignore",
    ) as file:

        content = file.read()

    # -------------------------------------------------------------------------
    # Extract information
    # -------------------------------------------------------------------------

    title = (
        f"[Auto] {filename}"
    )

    description = (
        content.strip()[:800]
        or
        f"Auto ingested log file {filename}"
    )

    severity = _detect_severity(
        content
    )

    component = _detect_component(
        content
    )

    error_type = _detect_error_type(
        content
    )

    # -------------------------------------------------------------------------
    # Build bug record
    # -------------------------------------------------------------------------

    bug_data = {
        "title": title,

        "description": description,

        "severity": severity,

        "category": "Auto-Ingested",

        "component": component,

        "reporter": "folder-watcher",

        "stack_trace": (
            content
            if (
                "trace" in filename.lower()
                or
                "traceback" in content.lower()
                or
                "stack trace" in content.lower()
            )
            else ""
        ),

        "error_log": content,
    }

    # -------------------------------------------------------------------------
    # Insert into database
    # -------------------------------------------------------------------------

    bug_id = db.insert_bug(
        bug_data
    )

    # -------------------------------------------------------------------------
    # Update embedding status
    # -------------------------------------------------------------------------

    try:

        db.update_bug_embedding_status(
            bug_id,
            "ok",
        )

    except Exception:
        # Do not stop ingestion if this optional update fails.
        pass

    # -------------------------------------------------------------------------
    # RAG similarity search
    # -------------------------------------------------------------------------

    query_text = (
        f"{title}. "
        f"{description}. "
        f"{component}. "
        f"{error_type}. "
        f"{content[:1500]}"
    )

    try:

        similar = kb.find_similar(
            query_text,
            top_k=5,
        )

    except Exception:

        similar = []

    # -------------------------------------------------------------------------
    # Run AI pipeline
    # -------------------------------------------------------------------------

    bug_record = {
        **bug_data,
        "bug_id": bug_id,
    }

    try:

        analysis = run_pipeline(
            bug_record,
            similar=similar,
            persist=True,
        )

    except TypeError:

        # Compatibility with older orchestrator versions that may not accept
        # persist=True.

        analysis = run_pipeline(
            bug_record,
            similar=similar,
        )

    # -------------------------------------------------------------------------
    # Make sure analysis is a dictionary
    # -------------------------------------------------------------------------

    if not isinstance(
        analysis,
        dict,
    ):
        analysis = {}

    # -------------------------------------------------------------------------
    # Build watcher result
    # -------------------------------------------------------------------------

    result = {
        "file_name": filename,

        "file": filename,

        "bug_id": bug_id,

        "severity": analysis.get(
            "severity",
            severity,
        ),

        "exception_type": analysis.get(
            "exception_type",
            error_type,
        ),

        "affected_component": analysis.get(
            "affected_component",
            component,
        ),

        "component": analysis.get(
            "component",
            component,
        ),

        "confidence": analysis.get(
            "confidence"
        ),

        "processed_at": _now(),
    }

    return result


# =============================================================================
# INTERNAL SCANNER
# =============================================================================

def _scan_files(
    manifest: Dict[str, float],
) -> List[Dict[str, Any]]:
    """
    Scan WATCH_DIR and process new .log/.txt files.
    """

    new_items: List[
        Dict[str, Any]
    ] = []

    # -------------------------------------------------------------------------
    # Ensure directory exists
    # -------------------------------------------------------------------------

    os.makedirs(
        WATCH_DIR,
        exist_ok=True,
    )

    # -------------------------------------------------------------------------
    # Read directory
    # -------------------------------------------------------------------------

    try:

        files = os.listdir(
            WATCH_DIR
        )

    except OSError:

        return new_items

    # -------------------------------------------------------------------------
    # Process files
    # -------------------------------------------------------------------------

    for filename in sorted(files):

        path = os.path.join(
            WATCH_DIR,
            filename,
        )

        # Ignore directories.
        if not os.path.isfile(
            path
        ):
            continue

        # Ignore manifest.
        if filename == os.path.basename(
            MANIFEST_PATH
        ):
            continue

        # ---------------------------------------------------------------------
        # Check extension
        # ---------------------------------------------------------------------

        extension = os.path.splitext(
            filename
        )[1].lower()

        if extension not in ALLOWED_EXT:
            continue

        # ---------------------------------------------------------------------
        # Get modification time
        # ---------------------------------------------------------------------

        try:

            modified = os.path.getmtime(
                path
            )

        except OSError:

            continue

        # ---------------------------------------------------------------------
        # Unique file/version key
        # ---------------------------------------------------------------------

        file_key = (
            f"{filename}:{int(modified)}"
        )

        # ---------------------------------------------------------------------
        # Skip already processed file
        # ---------------------------------------------------------------------

        if file_key in manifest:
            continue

        # ---------------------------------------------------------------------
        # Process file
        # ---------------------------------------------------------------------

        try:

            result = _process_file(
                path
            )

            # Mark file as processed.
            manifest[file_key] = time.time()

            new_items.append(
                result
            )

            # Update runtime state.
            with _lock:

                _state[
                    "processed"
                ].insert(
                    0,
                    result,
                )

                _state[
                    "processed"
                ] = _state[
                    "processed"
                ][:50]

        except Exception as error:

            # Do not stop other files if one file fails.

            with _lock:

                _state[
                    "errors"
                ].insert(
                    0,
                    {
                        "file": filename,
                        "error": str(error),
                        "at": _now(),
                    },
                )

                _state[
                    "errors"
                ] = _state[
                    "errors"
                ][:20]

    # -------------------------------------------------------------------------
    # Save manifest
    # -------------------------------------------------------------------------

    if new_items:

        _save_manifest(
            manifest
        )

    return new_items


# =============================================================================
# PUBLIC scan_once()
# =============================================================================

def scan_once() -> Dict[str, Any]:
    """
    Run one synchronous scan.

    Returns:

        {
            "processed": [...],
            "processed_count": 2,
            "errors": [...],
            "watch_dir": "...",
            "directory": "...",
            "scanned_at": "..."
        }

    The additional "directory" field is provided for API/test compatibility.
    """

    manifest = _load_manifest()

    processed = _scan_files(
        manifest
    )

    return {
        "processed": processed,

        "processed_count": len(
            processed
        ),

        "errors": list(
            _state.get(
                "errors",
                [],
            )
        ),

        "watch_dir": WATCH_DIR,

        # Compatibility field.
        "directory": WATCH_DIR,

        "scanned_at": _now(),
    }


# =============================================================================
# scan_now()
# =============================================================================

def scan_now() -> List[Dict[str, Any]]:
    """
    Compatibility function for Flask API.

    Returns only newly processed files.
    """

    summary = scan_once()

    return summary[
        "processed"
    ]


# =============================================================================
# BACKGROUND WATCHER LOOP
# =============================================================================

def _loop() -> None:
    """
    Background polling loop.
    """

    while True:

        with _lock:

            running = _state[
                "running"
            ]

        if not running:
            break

        try:

            scan_once()

        except Exception as error:

            with _lock:

                _state[
                    "errors"
                ].insert(
                    0,
                    {
                        "file": "*",
                        "error": str(error),
                        "at": _now(),
                    },
                )

                _state[
                    "errors"
                ] = _state[
                    "errors"
                ][:20]

        time.sleep(
            POLL_INTERVAL_SEC
        )


# =============================================================================
# START WATCHER
# =============================================================================

def start_watcher() -> None:
    """
    Start background watcher.
    """

    with _lock:

        if _state[
            "running"
        ]:
            return

        _state[
            "running"
        ] = True

        _state[
            "started_at"
        ] = _now()

    thread = threading.Thread(
        target=_loop,
        name="BugFolderWatcher",
        daemon=True,
    )

    thread.start()


# =============================================================================
# STOP WATCHER
# =============================================================================

def stop_watcher() -> None:
    """
    Stop background watcher.
    """

    with _lock:

        _state[
            "running"
        ] = False


# =============================================================================
# WATCHER STATUS
# =============================================================================

def watcher_status() -> Dict[str, Any]:
    """
    Return current watcher status.
    """

    with _lock:

        processed = list(
            _state[
                "processed"
            ]
        )

        errors = list(
            _state[
                "errors"
            ]
        )

        running = _state[
            "running"
        ]

        started_at = _state[
            "started_at"
        ]

    return {
        "running": running,

        "started_at": started_at,

        # Main field.
        "watch_dir": WATCH_DIR,

        # Compatibility field expected by some APIs/tests.
        "directory": WATCH_DIR,

        "poll_interval_sec": (
            POLL_INTERVAL_SEC
        ),

        "processed_count": len(
            processed
        ),

        "processed": processed,

        "errors": errors,

        # Useful information for debugging.
        "manifest": MANIFEST_PATH,

        "extensions": sorted(
            ALLOWED_EXT
        ),
    }


# =============================================================================
# RESET WATCHER STATE
# =============================================================================

def reset_watcher_state() -> None:
    """
    Reset in-memory watcher state.

    Useful during tests.
    """

    with _lock:

        _state[
            "processed"
        ] = []

        _state[
            "errors"
        ] = []

        _state[
            "started_at"
        ] = None


# =============================================================================
# RESET MANIFEST
# =============================================================================

def reset_manifest() -> None:
    """
    Delete the watcher manifest.

    Useful for testing or manually re-processing all files.
    """

    try:

        if os.path.exists(
            MANIFEST_PATH
        ):

            os.remove(
                MANIFEST_PATH
            )

    except OSError:
        pass


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================

def _scan_once(
    manifest: Dict[str, float],
) -> List[Dict[str, Any]]:
    """
    Backward-compatible internal scanner.
    """

    return _scan_files(
        manifest
    )