"""Bug report ingestion helpers (Milestone 2).

A single parser is shared by the manual upload endpoint and the Auto-Watch
service so a file dropped in the watch folder is processed exactly like a file
uploaded through the browser.
"""
import re

FIELD_PATTERNS = {
    "title": r"(?i)^\s*(?:bug\s*)?title\s*[:\-]\s*(.+)$",
    "description": r"(?i)^\s*(?:description|summary)\s*[:\-]\s*(.+)$",
    "severity": r"(?i)^\s*severity\s*[:\-]\s*(.+)$",
    "component": r"(?i)^\s*(?:component|module)\s*[:\-]\s*(.+)$",
    "environment": r"(?i)^\s*(?:environment|env)\s*[:\-]\s*(.+)$",
    "error_message": r"(?i)^\s*(?:error|error[_\s]?message|exception)\s*[:\-]\s*(.+)$",
    "additional_info": r"(?i)^\s*(?:additional[_\s]?info|notes|extra)\s*[:\-]\s*(.+)$",
}

STACK_HEADER = r"(?i)^\s*stack[_\s]?trace\s*[:\-]?\s*(.*)$"

VALID_SEVERITIES = {"critical": "Critical", "high": "High",
                    "medium": "Medium", "low": "Low"}

# Heuristics used when a log file has no labelled fields at all.
TRACE_HINTS = ("Traceback (most recent call last)", "    at ", "\tat ",
               "File \"", "Caused by:")


def normalise_severity(value, default="Medium"):
    return VALID_SEVERITIES.get(str(value or "").strip().lower(), default)


def parse_bug_text(text, file_name=None):
    """Turn free-form report/log text into the bug fields the platform stores."""
    lines = text.splitlines()
    fields = {
        "title": "", "description": "", "severity": "Medium", "component": "",
        "environment": "", "error_message": "", "additional_info": "",
        "stack_trace": "",
    }
    stack_lines = []
    in_stack = False

    for line in lines:
        matched = False
        for key, pattern in FIELD_PATTERNS.items():
            m = re.match(pattern, line)
            if m:
                fields[key] = m.group(1).strip()
                matched = True
                in_stack = False
                break
        if matched:
            continue
        m = re.match(STACK_HEADER, line)
        if m:
            in_stack = True
            if m.group(1).strip():
                stack_lines.append(m.group(1).strip())
            continue
        if in_stack:
            if line.strip() == "":
                continue
            stack_lines.append(line.rstrip())
        elif any(hint in line for hint in TRACE_HINTS):
            stack_lines.append(line.rstrip())

    fields["stack_trace"] = "\n".join(stack_lines).strip()
    fields["severity"] = normalise_severity(fields["severity"])

    if not fields["title"]:
        first = next((l.strip() for l in lines if l.strip()), "")
        fields["title"] = (first or f"Untitled report ({file_name or 'unknown'})")[:200]
    if not fields["description"]:
        fields["description"] = text.strip()[:4000] or fields["title"]
    if not fields["error_message"]:
        candidate = next(
            (l.strip() for l in lines
             if re.search(r"(?i)\b(error|exception|failed|failure|timeout)\b", l)),
            "",
        )
        fields["error_message"] = candidate[:500]
    return fields


def validate_bug_fields(data):
    """Return (cleaned, errors) for a manually submitted bug."""
    errors = []
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    if len(title) < 5:
        errors.append("Title must be at least 5 characters.")
    if len(description) < 10:
        errors.append("Description must be at least 10 characters.")

    cleaned = {
        "title": title[:200],
        "description": description[:8000],
        "severity": normalise_severity(data.get("severity")),
        "stack_trace": (data.get("stack_trace") or "").strip()[:8000],
        "error_message": (data.get("error_message") or "").strip()[:500],
        "component": (data.get("component") or "").strip()[:120],
        "environment": (data.get("environment") or "").strip()[:120],
        "additional_info": (data.get("additional_info") or "").strip()[:2000],
    }
    return cleaned, errors
