"""
LLM enrichment package for incident timeline analysis.

Provides Claude Haiku as a fallback enrichment layer for
low-confidence regex extractions. Gracefully degrades when
the anthropic SDK is missing or unconfigured.
"""

from .enrichment import enrich_timeline, is_available

__all__ = ['enrich_timeline', 'is_available']
