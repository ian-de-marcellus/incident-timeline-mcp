"""
Data models for incident timeline analysis.
Foundation types used across parsers, extractors, and analysis modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
