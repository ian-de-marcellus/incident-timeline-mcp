"""
Data models for incident timeline analysis.
Foundation types used across parsers, extractors, and analysis modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class AnalysisState:
    """Mutable state threaded through the analysis pipeline.

    Bundles the four parallel collections that are created together,
    enriched together, and packed into the final result together.
    """
    events: list[dict]
    text: str
    actions: list[dict]
    entities: dict[str, list[str]]
    severity: dict[str, Any]


@dataclass
class NormalizedMessage:
    """A single message from any source, normalized to a common format."""
    timestamp: datetime | None
    actor: str | None
    text: str
    raw: str
    source: str  # "slack" | "plaintext"
    metadata: dict = field(default_factory=dict)


@dataclass
class Action:
    """An action identified in incident text."""
    keyword: str
    category: str  # investigation, remediation, communication, status


@dataclass
class SeverityAssessment:
    """Severity assessment at a point in time."""
    level: str  # critical, high, medium, low, unknown
    confidence: str  # high, medium, low
    indicators: list[str] = field(default_factory=list)


@dataclass
class SeverityChange:
    """A change in severity during an incident."""
    timestamp: datetime
    level: str
    trigger: str


@dataclass
class TimelineEvent:
    """An extracted event with all enrichments applied."""
    timestamp: datetime | None
    actor: str | None
    text: str
    actions: list[Action] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    severity_indicators: list[str] = field(default_factory=list)
    ir_phase: str | None = None
    phase_confidence: str | None = None  # "regex" | "llm"


@dataclass
class IncidentMetrics:
    """Computed metrics for an incident."""
    duration: timedelta | None = None
    time_to_contain: timedelta | None = None
    time_to_resolve: timedelta | None = None
    num_responders: int = 0
    num_events: int = 0


@dataclass
class IncidentReport:
    """Complete analysis output."""
    timeline: list[TimelineEvent] = field(default_factory=list)
    ir_phases: dict[str, list[TimelineEvent]] = field(default_factory=dict)
    severity_timeline: list[SeverityChange] = field(default_factory=list)
    overall_severity: SeverityAssessment | None = None
    entities: dict[str, list[str]] = field(default_factory=dict)
    metrics: IncidentMetrics | None = None
    summary_text: str = ""
