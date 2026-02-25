"""
Test environment configuration.

Sets LLM_ENRICHMENT=none so tests that call parse_slack_export()
or generate_summary() don't make real API calls.
"""

import pytest


@pytest.fixture(autouse=True)
def _disable_llm_enrichment(monkeypatch):
    """Set enrichment to 'none' for all tests by default."""
    monkeypatch.setenv('LLM_ENRICHMENT', 'none')
