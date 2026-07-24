"""Multi-Agent Architecture — DESIGN ONLY (Milestone 1).

Each agent is a lightweight class documenting its responsibility.
Orchestration is stubbed for future milestones.
"""
from dataclasses import dataclass


@dataclass
class AgentSpec:
    name: str
    responsibility: str
    inputs: str
    outputs: str


TRIAGE_AGENT = AgentSpec(
    name="Triage Agent",
    responsibility="Classify incoming bugs by severity, category and component; "
                   "assign priority and route to downstream agents.",
    inputs="Raw bug submission (title, description, metadata).",
    outputs="Normalized bug record + priority label.",
)

LOG_ANALYSIS_AGENT = AgentSpec(
    name="Log Analysis Agent",
    responsibility="Parse stack traces and error logs, extract key exceptions, "
                   "file paths, and error signatures.",
    inputs="Stack trace text, error log text.",
    outputs="Structured log summary + extracted signatures.",
)

ROOT_CAUSE_AGENT = AgentSpec(
    name="Root Cause Agent",
    responsibility="Correlate bug context with historical KB (via RAG) to infer "
                   "the most likely root cause.",
    inputs="Bug context + Top-K similar historical bugs.",
    outputs="Ranked root-cause hypotheses.",
)

DUPLICATE_DETECTION_AGENT = AgentSpec(
    name="Duplicate Detection Agent",
    responsibility="Detect near-duplicate bug reports using semantic similarity "
                   "thresholds (cosine ≥ 0.85).",
    inputs="New bug embedding + KB vector index.",
    outputs="Duplicate flag + reference to canonical bug.",
)

REMEDIATION_AGENT = AgentSpec(
    name="Remediation Agent",
    responsibility="Aggregate suggested fixes from similar historical bugs and "
                   "produce a consolidated remediation plan.",
    inputs="Similar bugs list with suggested fixes.",
    outputs="Consolidated remediation recommendation.",
)

ALL_AGENTS = [
    TRIAGE_AGENT,
    LOG_ANALYSIS_AGENT,
    ROOT_CAUSE_AGENT,
    DUPLICATE_DETECTION_AGENT,
    REMEDIATION_AGENT,
]


def agents_as_dict():
    return [a.__dict__ for a in ALL_AGENTS]
