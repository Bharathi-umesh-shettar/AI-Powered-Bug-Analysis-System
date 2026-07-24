"""Agents package.

Milestone 1 shipped agent design specs; Milestone 2 added Triage + Log
Analysis; Milestone 3 adds Root Cause, Duplicate Detection and
Remediation. All agents are re-exported here.
"""
from dataclasses import dataclass

from .triage_agent import TriageAgent, run_triage
from .log_analysis_agent import LogAnalysisAgent, run_log_analysis
from .root_cause_agent import RootCauseAgent, run_root_cause
from .duplicate_detection_agent import DuplicateDetectionAgent, run_duplicate_detection
from .remediation_agent import RemediationAgent, run_remediation


@dataclass
class AgentSpec:
    name: str
    responsibility: str
    inputs: str
    outputs: str
    status: str = "implemented"


TRIAGE_AGENT = AgentSpec(
    name="Triage Agent",
    responsibility="Classify bugs by severity, priority and affected component.",
    inputs="Bug title, description, environment, similar bugs.",
    outputs="severity, priority, affected_component, confidence, reasoning.",
)

LOG_ANALYSIS_AGENT = AgentSpec(
    name="Log Analysis Agent",
    responsibility="Parse Python/Java/Node.js/DB stack traces and error logs.",
    inputs="Stack trace text, error log text.",
    outputs="exception_type, failure_point, file, function, line, root_cause, summary.",
)

ROOT_CAUSE_AGENT = AgentSpec(
    name="Root Cause Agent",
    responsibility="Infer the most probable root cause via patterns + RAG.",
    inputs="Bug context + log analysis + Top-K similar KB entries.",
    outputs="root_cause, confidence, supporting_evidence, historical_refs.",
)

DUPLICATE_DETECTION_AGENT = AgentSpec(
    name="Duplicate Detection Agent",
    responsibility="Detect near-duplicate bug reports via semantic similarity.",
    inputs="New bug + prior bugs table.",
    outputs="is_duplicate, duplicate_of, top matches with similarity %.",
)

REMEDIATION_AGENT = AgentSpec(
    name="Remediation Agent",
    responsibility="Aggregate suggested fixes and best-practice guidance.",
    inputs="Bug + root-cause + similar KB entries.",
    outputs="recommended_fix, resolution_steps, best_practices, historical_fixes.",
)

ALL_AGENTS = [
    TRIAGE_AGENT, LOG_ANALYSIS_AGENT, ROOT_CAUSE_AGENT,
    DUPLICATE_DETECTION_AGENT, REMEDIATION_AGENT,
]


def agents_as_dict():
    return [a.__dict__ for a in ALL_AGENTS]


__all__ = [
    "AgentSpec", "ALL_AGENTS", "agents_as_dict",
    "TriageAgent", "run_triage",
    "LogAnalysisAgent", "run_log_analysis",
    "RootCauseAgent", "run_root_cause",
    "DuplicateDetectionAgent", "run_duplicate_detection",
    "RemediationAgent", "run_remediation",
]
