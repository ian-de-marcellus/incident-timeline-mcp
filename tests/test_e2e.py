"""
End-to-end tests that exercise the full pipeline via MCP tool handlers.

These read example incident data and run it through the server's call_tool(),
verifying that the output quality is reasonable across the whole stack.

LLM enrichment is disabled (patched to return no client) so these tests
run fast and free. LLM-specific behavior is tested with mocks in
test_llm_enrichment.py.
"""

import asyncio
import json
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _disable_llm():
    """Patch _get_llm_client so no real API calls are made."""
    with patch("extractors._get_llm_client", return_value=(None, "none")):
        yield


# ── Plaintext pipeline ───────────────────────────────────────────────

class TestPlaintextE2E:
    """Full pipeline test using the detailed plaintext example."""

    def _run_summary(self):
        from server import read_resource, call_tool
        resource = asyncio.run(read_resource("incident://examples/detailed"))
        text = resource[0].content
        result = asyncio.run(call_tool("generate_summary", {"text": text}))
        return json.loads(result[0].text)

    def test_timeline_has_expected_event_count(self):
        data = self._run_summary()
        assert len(data["timeline"]) >= 25

    def test_metrics_has_duration(self):
        data = self._run_summary()
        assert data["metrics"]["duration_seconds"] > 0
        assert "duration" in data["metrics"]

    def test_severity_is_high_or_critical(self):
        data = self._run_summary()
        assert data["severity"]["level"] in ("high", "critical")

    def test_ir_phases_cover_full_lifecycle(self):
        data = self._run_summary()
        phases = set(data["ir_phases"].keys())
        assert {"detection", "containment", "recovery"} <= phases

    def test_entities_include_primary_service(self):
        data = self._run_summary()
        services = data["entities"]["services"]
        assert "checkout-db-primary" in services

    def test_actors_include_all_responders(self):
        data = self._run_summary()
        actors = {e.get("actor") for e in data["timeline"] if e.get("actor")}
        assert "sarah.chen" in actors
        assert "james.rodriguez" in actors
        assert len(actors) >= 5

    def test_time_to_contain_is_present(self):
        data = self._run_summary()
        assert "time_to_contain" in data["metrics"]

    def test_summary_text_is_nonempty(self):
        data = self._run_summary()
        assert len(data["summary_text"]) > 50


# ── Slack pipeline ───────────────────────────────────────────────────

class TestSlackE2E:
    """Full pipeline test using the Slack export example."""

    def _run_slack(self):
        from server import read_resource, call_tool
        resource = asyncio.run(read_resource("incident://examples/slack-export"))
        content = json.loads(resource[0].content)
        result = asyncio.run(call_tool("parse_slack_export", {
            "messages_json": content["messages"],
            "users_json": content["users"],
        }))
        return json.loads(result[0].text)

    def test_timeline_present(self):
        data = self._run_slack()
        assert len(data["timeline"]) >= 10

    def test_actors_are_resolved_names(self):
        data = self._run_slack()
        actors = {e.get("actor") for e in data["timeline"] if e.get("actor")}
        # Actors should be display names, not raw user IDs
        assert not any(a.startswith("U0") for a in actors)
        assert "sarah.chen" in actors

    def test_ir_phases_present(self):
        data = self._run_slack()
        assert len(data["ir_phases"]) >= 3

    def test_metrics_computed(self):
        data = self._run_slack()
        assert data["metrics"]["num_events"] > 0
        assert data["metrics"]["num_responders"] > 0
        assert data["metrics"]["duration_seconds"] > 0

    def test_slack_metadata_present(self):
        data = self._run_slack()
        assert "slack_metadata" in data
        assert data["slack_metadata"]["message_count"] > 0


# ── Resource → Tool flow ─────────────────────────────────────────────

class TestResourceToToolFlow:
    """Test the intended user workflow: read resource, then analyze it."""

    def test_simple_resource_through_summary(self):
        from server import read_resource, call_tool
        resource = asyncio.run(read_resource("incident://examples/simple"))
        text = resource[0].content
        result = asyncio.run(call_tool("generate_summary", {"text": text}))
        data = json.loads(result[0].text)
        assert "timeline" in data
        assert "severity" in data
        assert len(data["timeline"]) > 0

    def test_detailed_resource_through_framework(self):
        from server import read_resource, call_tool
        resource = asyncio.run(read_resource("incident://examples/detailed"))
        text = resource[0].content
        result = asyncio.run(call_tool("map_to_framework", {"text": text}))
        data = json.loads(result[0].text)
        assert "phases" in data
        assert data["framework"] == "nist_800_61"

    def test_slack_resource_through_parse(self):
        from server import read_resource, call_tool
        resource = asyncio.run(read_resource("incident://examples/slack-export"))
        content = json.loads(resource[0].content)
        result = asyncio.run(call_tool("parse_slack_export", {
            "messages_json": content["messages"],
            "users_json": content["users"],
        }))
        data = json.loads(result[0].text)
        assert "timeline" in data
        assert len(data["timeline"]) > 0
