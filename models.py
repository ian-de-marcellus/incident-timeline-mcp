"""
Data models for incident timeline analysis.
Foundation types used across parsers, extractors, and analysis modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class NormalizedMessage:
    """A single message from any source, normalized to a common format."""
    timestamp: Optional[datetime]
    actor: Optional[str]
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
    timestamp: Optional[datetime]
    actor: Optional[str]
    text: str
    actions: list[Action] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    severity_indicators: list[str] = field(default_factory=list)
    ir_phase: Optional[str] = None
    phase_confidence: Optional[str] = None  # "regex" | "llm"


@dataclass
class IncidentMetrics:
    """Computed metrics for an incident."""
    duration: Optional[timedelta] = None
    time_to_detect: Optional[timedelta] = None
    time_to_contain: Optional[timedelta] = None
    time_to_resolve: Optional[timedelta] = None
    num_responders: int = 0
    num_events: int = 0


@dataclass
class IncidentReport:
    """Complete analysis output."""
    timeline: list[TimelineEvent] = field(default_factory=list)
    ir_phases: dict[str, list[TimelineEvent]] = field(default_factory=dict)
    severity_timeline: list[SeverityChange] = field(default_factory=list)
    overall_severity: Optional[SeverityAssessment] = None
    entities: dict[str, list[str]] = field(default_factory=dict)
    metrics: Optional[IncidentMetrics] = None
    summary_text: str = ""
