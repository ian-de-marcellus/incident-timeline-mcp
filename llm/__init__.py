"""
LLM enrichment package for incident timeline analysis.

All functions are pure — the caller constructs the Anthropic client
and passes it in. No module-level state or config reads.
"""

from .enrichment import enrich_timeline, ANTHROPIC_AVAILABLE, DEFAULT_MODEL

__all__ = ['enrich_timeline', 'ANTHROPIC_AVAILABLE', 'DEFAULT_MODEL']
