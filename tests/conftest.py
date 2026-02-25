"""
Test environment configuration.

Sets LLM_ENRICHMENT=none so tests that call generate_summary()
or parse_slack_export() don't make real API calls. This is
environment configuration, not module patching — equivalent to
setting env vars in CI.
"""

import pytest


@pytest.fixture(autouse=True)
def _disable_llm_enrichment(monkeypatch):
    """Set enrichment to 'none' for all tests by default."""
    monkeypatch.setenv('LLM_ENRICHMENT', 'none')
