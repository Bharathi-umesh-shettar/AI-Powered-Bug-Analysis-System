"""Log Analysis Agent (Milestone 2).

Parses stack traces / error logs from Python, Java, Node.js and generic
database drivers. Extracts a structured summary usable by downstream agents.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
PY_FRAME_RE = re.compile(
    r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>[^\n]+)'
)
PY_EXCEPTION_RE = re.compile(
    r'(?P<exc>[A-Z][A-Za-z0-9_.]*Error|[A-Z][A-Za-z0-9_.]*Exception|KeyError|ValueError|TypeError|FileNotFoundError|IndexError|AttributeError|ZeroDivisionError|RuntimeError)\s*:?\s*(?P<msg>.*)'
)

JAVA_EXCEPTION_RE = re.compile(
    r'(?P<exc>(?:[a-z]+\.)+[A-Z][A-Za-z0-9_]*(?:Exception|Error))\s*:?\s*(?P<msg>[^\n]*)'
)
JAVA_FRAME_RE = re.compile(
    r'at\s+(?P<qualified>[\w\.\$]+)\.(?P<func>[\w\$<>]+)\((?P<file>[^:]+):(?P<line>\d+)\)'
)

NODE_FRAME_RE = re.compile(
    r'at\s+(?P<func>[\w\.<>\[\]$ ]+)?\s*\(?(?P<file>[^\s():]+):(?P<line>\d+):(?P<col>\d+)\)?'
)
NODE_EXCEPTION_RE = re.compile(
    r'(?P<exc>[A-Z][A-Za-z]*Error)\s*:\s*(?P<msg>[^\n]*)'
)

SQL_ERROR_RE = re.compile(
    r'(?P<exc>(?:ORA-\d+|SQLSTATE\[[^\]]+\]|SQLException|OperationalError|IntegrityError|ProgrammingError|psycopg2\.\w+|sqlite3\.\w+|pymysql\.\w+))\s*:?\s*(?P<msg>[^\n]*)',
    re.IGNORECASE,
)


ROOT_CAUSE_HINTS = {
    "KeyError": "Missing dictionary key referenced by the code.",
    "ValueError": "A value provided did not meet the expected format or range.",
    "TypeError": "An operation was applied to an incompatible type.",
    "FileNotFoundError": "The referenced file or path does not exist at runtime.",
    "IndexError": "List/array index out of range.",
    "AttributeError": "Attempted to access an attribute that does not exist on the object.",
    "ZeroDivisionError": "Division by zero occurred in a numeric computation.",
    "NullPointerException": "Dereferenced a null object reference.",
    "SQLException": "Database rejected the query — check schema, constraints, or connectivity.",
    "OperationalError": "Database connection or operational failure.",
    "IntegrityError": "Database integrity constraint violated (unique / foreign key).",
    "TimeoutError": "Operation exceeded its allowed time budget.",
    "ConnectionError": "Network / socket connection failed or was refused.",
}


def _first(match_iter):
    for m in match_iter:
        return m
    return None


class LogAnalysisAgent:
    name = "Log Analysis Agent"

    # -------------------- Language detection --------------------
    @staticmethod
    def detect_language(text: str) -> str:
        t = text or ""
        if "Traceback (most recent call last)" in t or PY_FRAME_RE.search(t):
            return "python"
        if JAVA_FRAME_RE.search(t) or "Exception in thread" in t:
            return "java"
        if NODE_FRAME_RE.search(t) and (".js" in t or ".ts" in t):
            return "nodejs"
        if SQL_ERROR_RE.search(t):
            return "database"
        return "generic"

    # -------------------- Public entry --------------------------
    def analyze(self, stack_trace: str = "", error_log: str = "") -> Dict[str, Any]:
        text = "\n".join(filter(None, [stack_trace, error_log])).strip()
        if not text:
            return self._empty_result()

        language = self.detect_language(text)
        if language == "python":
            parsed = self._parse_python(text)
        elif language == "java":
            parsed = self._parse_java(text)
        elif language == "nodejs":
            parsed = self._parse_node(text)
        elif language == "database":
            parsed = self._parse_database(text)
        else:
            parsed = self._parse_generic(text)

        parsed["language"] = language
        parsed["root_cause"] = self._infer_root_cause(parsed)
        parsed["affected_code_path"] = self._infer_code_path(parsed)
        parsed["structured_summary"] = self._summarize(parsed)
        return parsed

    # -------------------- Parsers -------------------------------
    def _parse_python(self, text: str) -> Dict[str, Any]:
        frames = list(PY_FRAME_RE.finditer(text))
        exc = _first(PY_EXCEPTION_RE.finditer(text.splitlines()[-1] if text else ""))
        if not exc:
            exc = _first(PY_EXCEPTION_RE.finditer(text))
        last = frames[-1] if frames else None
        return {
            "exception_type": exc.group("exc") if exc else "UnknownError",
            "exception_message": exc.group("msg").strip() if exc else "",
            "affected_file": last.group("file") if last else "",
            "function_name": (last.group("func").strip() if last else ""),
            "line_number": int(last.group("line")) if last else None,
            "failure_point": f"{last.group('file')} line {last.group('line')}" if last else "",
        }

    def _parse_java(self, text: str) -> Dict[str, Any]:
        exc = _first(JAVA_EXCEPTION_RE.finditer(text))
        frame = _first(JAVA_FRAME_RE.finditer(text))
        exc_type = ""
        if exc:
            exc_type = exc.group("exc").split(".")[-1]
        return {
            "exception_type": exc_type or "UnknownException",
            "exception_message": exc.group("msg").strip() if exc else "",
            "affected_file": frame.group("file") if frame else "",
            "function_name": frame.group("func") if frame else "",
            "line_number": int(frame.group("line")) if frame else None,
            "failure_point": f"{frame.group('file')} line {frame.group('line')}" if frame else "",
        }

    def _parse_node(self, text: str) -> Dict[str, Any]:
        exc = _first(NODE_EXCEPTION_RE.finditer(text))
        frame = _first(NODE_FRAME_RE.finditer(text))
        return {
            "exception_type": exc.group("exc") if exc else "Error",
            "exception_message": exc.group("msg").strip() if exc else "",
            "affected_file": frame.group("file") if frame else "",
            "function_name": (frame.group("func") or "").strip() if frame else "",
            "line_number": int(frame.group("line")) if frame else None,
            "failure_point": f"{frame.group('file')} line {frame.group('line')}" if frame else "",
        }

    def _parse_database(self, text: str) -> Dict[str, Any]:
        m = SQL_ERROR_RE.search(text)
        return {
            "exception_type": m.group("exc") if m else "DatabaseError",
            "exception_message": m.group("msg").strip() if m else text[:200],
            "affected_file": "",
            "function_name": "",
            "line_number": None,
            "failure_point": "Database driver",
        }

    def _parse_generic(self, text: str) -> Dict[str, Any]:
        first_line = text.splitlines()[0][:200] if text else ""
        return {
            "exception_type": "GenericError",
            "exception_message": first_line,
            "affected_file": "",
            "function_name": "",
            "line_number": None,
            "failure_point": "",
        }

    # -------------------- Enrichment ---------------------------
    @staticmethod
    def _infer_root_cause(parsed: Dict[str, Any]) -> str:
        exc = parsed.get("exception_type", "")
        for key, hint in ROOT_CAUSE_HINTS.items():
            if key.lower() in exc.lower():
                return hint
        msg = parsed.get("exception_message", "")
        if msg:
            return f"Underlying failure reported by runtime: {msg}"
        return "Unclassified failure — review stack trace manually."

    @staticmethod
    def _infer_code_path(parsed: Dict[str, Any]) -> str:
        fn = parsed.get("function_name") or ""
        f = parsed.get("affected_file") or ""
        if fn and f:
            return f"{f} → {fn}()"
        return f or fn or "unknown"

    @staticmethod
    def _summarize(parsed: Dict[str, Any]) -> str:
        exc = parsed.get("exception_type", "an error")
        loc = parsed.get("failure_point") or "an unknown location"
        return (
            f"A {exc} was raised at {loc}. "
            f"Root cause: {parsed.get('root_cause', 'not determined')}."
        )

    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        return {
            "language": "none",
            "exception_type": "",
            "exception_message": "",
            "affected_file": "",
            "function_name": "",
            "line_number": None,
            "failure_point": "",
            "affected_code_path": "",
            "root_cause": "No stack trace or error log supplied.",
            "structured_summary": "No log content available for analysis.",
        }


def run_log_analysis(stack_trace: str = "", error_log: str = "") -> Dict[str, Any]:
    return LogAnalysisAgent().analyze(stack_trace=stack_trace, error_log=error_log)
