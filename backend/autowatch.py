"""Auto-Watch folder monitoring service (Milestone 2).

A background thread polls WATCH_DIR for new .log/.txt reports. Every new file is
parsed, stored as a bug, diagnosed by the agent pipeline, and recorded in the
watch_events table so the UI can show a live activity feed. Polling (instead of
watchdog) keeps the dependency list small and works identically on every OS.
"""
import os
import threading

from config import (
    WATCH_DIR,
    WATCH_EXTENSIONS,
    WATCH_INTERVAL_SECONDS,
    WATCH_MAX_BYTES,
)
from database import fetch_watch_events, record_watch_event, watch_event_exists
from ingest import parse_bug_text
from service import ingest_and_diagnose


class AutoWatcher:
    def __init__(self, pipeline, directory=WATCH_DIR,
                 interval=WATCH_INTERVAL_SECONDS):
        self.pipeline = pipeline
        self.directory = directory
        self.interval = interval
        self._thread = None
        self._stop = threading.Event()
        self.last_scan = None
        os.makedirs(self.directory, exist_ok=True)

    # -- lifecycle ----------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="auto-watch")
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        return True

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive() and
                    not self._stop.is_set())

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception as exc:  # keep the thread alive
                print(f"[auto-watch] scan failed: {exc}")
            self._stop.wait(self.interval)

    # -- work ---------------------------------------------------------------
    def scan_once(self):
        """Process every unseen file in the watch folder. Returns a summary."""
        processed, skipped, failed = [], [], []
        for name in sorted(os.listdir(self.directory)):
            path = os.path.join(self.directory, name)
            if not os.path.isfile(path):
                continue
            if not name.lower().endswith(tuple(WATCH_EXTENSIONS)):
                continue
            if watch_event_exists(path) in ("processed", "failed"):
                skipped.append(name)
                continue
            try:
                result = self.process_file(path)
                processed.append(result)
            except Exception as exc:
                record_watch_event(name, path, "failed", detail=str(exc))
                failed.append({"file_name": name, "error": str(exc)})
        from database import now_iso
        self.last_scan = now_iso()
        return {"processed": processed, "skipped": skipped, "failed": failed,
                "scanned_at": self.last_scan}

    def process_file(self, path):
        name = os.path.basename(path)
        size = os.path.getsize(path)
        if size > WATCH_MAX_BYTES:
            raise ValueError(f"file is {size} bytes, larger than the "
                             f"{WATCH_MAX_BYTES} byte limit")
        record_watch_event(name, path, "detected", detail=f"{size} bytes")
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
        if not text.strip():
            raise ValueError("file is empty")

        fields = parse_bug_text(text, file_name=name)
        bug, findings = ingest_and_diagnose(
            fields, self.pipeline, source="auto-watch", source_file=path
        )
        detail = (f"Bug #{bug['id']} | {findings['duplicate_status']} | "
                  f"{findings['component']}")
        record_watch_event(name, path, "processed", detail=detail,
                           bug_id=bug["id"], processed=True)
        return {"file_name": name, "bug_id": bug["id"],
                "title": bug["title"], "severity": bug["severity"],
                "component": findings["component"],
                "duplicate_status": findings["duplicate_status"]}

    # -- reporting ----------------------------------------------------------
    def status(self):
        return {
            "running": self.running,
            "directory": self.directory,
            "interval_seconds": self.interval,
            "extensions": list(WATCH_EXTENSIONS),
            "last_scan": self.last_scan,
            "events": fetch_watch_events(50),
        }
