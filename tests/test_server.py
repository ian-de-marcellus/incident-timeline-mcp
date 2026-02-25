"""
Tests for MCP server: imports, resource handlers, and tool routing.
"""

import asyncio
import json

import pytest


# ── Smoke tests ──────────────────────────────────────────────────────

class TestServerImports:
    """Test that server.py can be imported without errors"""

    def test_server_imports_successfully(self):
        import server
        assert server.app is not None

    def test_server_has_correct_name(self):
        import server
        assert server.app.name == "incident-timeline-extractor"


class TestExtractorsStillWork:
    """Verify extractors work when imported by server"""

    def test_extractors_accessible_from_server(self):
        from server import extract_timeline
        result = extract_timeline("@sarah 14:23: test")
        assert isinstance(result, list)


# ── Resource tests ───────────────────────────────────────────────────

class TestListResources:
    """Test list_resources() returns correct resource metadata."""

    def test_returns_three_resources(self):
        from server import list_resources
        resources = asyncio.run(list_resources())
        assert len(resources) == 3

    def test_resource_uris(self):
        from server import list_resources
        resources = asyncio.run(list_resources())
        uris = {str(r.uri) for r in resources}
        assert uris == {
            "incident://examples/simple",
            "incident://examples/detailed",
            "incident://examples/slack-export",
        }

    def test_plaintext_resources_have_text_mimetype(self):
        from server import list_resources
        resources = asyncio.run(list_resources())
        by_uri = {str(r.uri): r for r in resources}
        assert by_uri["incident://examples/simple"].mimeType == "text/plain"
        assert by_uri["incident://examples/detailed"].mimeType == "text/plain"

    def test_slack_resource_has_json_mimetype(self):
        from server import list_resources
        resources = asyncio.run(list_resources())
        by_uri = {str(r.uri): r for r in resources}
        assert by_uri["incident://examples/slack-export"].mimeType == "application/json"

    def test_all_resources_have_names_and_descriptions(self):
        from server import list_resources
        resources = asyncio.run(list_resources())
        for r in resources:
            assert r.name, f"Resource {r.uri} missing name"
            assert r.description, f"Resource {r.uri} missing description"


class TestReadResource:
    """Test read_resource() returns correct content for each URI."""

    def _read(self, uri_str):
        from server import read_resource
        result = asyncio.run(read_resource(uri_str))
        # Returns list[ReadResourceContents]
        assert len(result) == 1
        return result[0].content

    def test_simple_contains_payment_service(self):
        content = self._read("incident://examples/simple")
        assert "payment-service" in content

    def test_simple_is_plaintext(self):
        content = self._read("incident://examples/simple")
        assert "@sarah" in content
        assert "14:23" in content

    def test_detailed_contains_expected_actors(self):
        content = self._read("incident://examples/detailed")
        assert "sarah.chen" in content
        assert "james.rodriguez" in content

    def test_detailed_contains_expected_entities(self):
        content = self._read("incident://examples/detailed")
        assert "checkout-db-primary" in content

    def test_slack_export_is_valid_json(self):
        content = self._read("incident://examples/slack-export")
        data = json.loads(content)
        assert "messages" in data
        assert "users" in data

    def test_slack_export_messages_are_json_string(self):
        content = self._read("incident://examples/slack-export")
        data = json.loads(content)
        # messages value is a JSON string (not pre-parsed)
        messages = json.loads(data["messages"])
        assert isinstance(messages, list)
        assert len(messages) > 0

    def test_slack_export_users_are_json_string(self):
        content = self._read("incident://examples/slack-export")
        data = json.loads(content)
        users = json.loads(data["users"])
        assert isinstance(users, list)
        assert len(users) > 0

    def test_unknown_uri_raises(self):
        from server import read_resource
        with pytest.raises(ValueError, match="Unknown resource"):
            asyncio.run(read_resource("incident://examples/nonexistent"))


# ── Tool routing tests ───────────────────────────────────────────────

class TestToolRouting:
    """Test call_tool() routes to each tool and returns valid JSON."""

    SAMPLE_TEXT = (
        "sarah.chen 14:23: Seeing elevated errors on payment-service. "
        "IP 10.0.1.42 returning 500s from api.stripe.com. "
        "Rolled back deploy, monitoring recovery."
    )

    def _call(self, name, arguments):
        from server import call_tool
        result = asyncio.run(call_tool(name, arguments))
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert "error" not in data, f"Tool {name} returned error: {data}"
        return data

    def test_extract_timeline(self):
        data = self._call("extract_timeline", {"text": self.SAMPLE_TEXT})
        assert isinstance(data, list)

    def test_identify_actions(self):
        data = self._call("identify_actions", {"text": self.SAMPLE_TEXT})
        assert isinstance(data, list)

    def test_extract_entities(self):
        data = self._call("extract_entities", {"text": self.SAMPLE_TEXT})
        assert isinstance(data, dict)
        assert "services" in data

    def test_detect_severity(self):
        data = self._call("detect_severity", {"text": self.SAMPLE_TEXT})
        assert isinstance(data, dict)
        assert "level" in data

    def test_generate_summary(self):
        data = self._call("generate_summary", {"text": self.SAMPLE_TEXT})
        assert isinstance(data, dict)
        assert "timeline" in data

    def test_map_to_framework(self):
        data = self._call("map_to_framework", {"text": self.SAMPLE_TEXT})
        assert isinstance(data, dict)
        assert "phases" in data

    def test_parse_slack_export(self):
        messages = json.dumps([{
            "type": "message",
            "user": "U001",
            "text": "Server down",
            "ts": "1729000995.000001",
        }])
        data = self._call("parse_slack_export", {"messages_json": messages})
        assert isinstance(data, dict)
        assert "timeline" in data

    def test_unknown_tool_returns_error(self):
        from server import call_tool
        result = asyncio.run(call_tool("nonexistent_tool", {"text": "test"}))
        data = json.loads(result[0].text)
        assert "error" in data

    def test_missing_text_returns_error(self):
        from server import call_tool
        result = asyncio.run(call_tool("extract_timeline", {}))
        data = json.loads(result[0].text)
        assert "error" in data

    def test_missing_messages_json_returns_error(self):
        from server import call_tool
        result = asyncio.run(call_tool("parse_slack_export", {}))
        data = json.loads(result[0].text)
        assert "error" in data
