"""
Shared test configuration.

Disables LLM enrichment by default so tests don't make real API calls.
Tests in test_llm_enrichment.py manage their own env/mock setup.
"""

import os
import pytest


@pytest.fixture(autouse=True)
def _disable_llm_enrichment(monkeypatch):
    """Ensure LLM enrichment is off unless a test explicitly overrides."""
    monkeypatch.setenv('LLM_ENRICHMENT', 'none')
    monkeypatch.setenv('ANTHROPIC_API_KEY', '')
    # Reset the client singleton so it doesn't leak between tests
    try:
        import llm.enrichment as mod
        mod._client = None
    except ImportError:
        pass
