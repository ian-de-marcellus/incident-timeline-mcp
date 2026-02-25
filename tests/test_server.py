"""
Smoke tests for MCP server in server.py
"""


class TestServerImports:
    """Test that server.py can be imported without errors"""

    def test_server_imports_successfully(self):
        """Server module should import without errors"""
        import server
        assert server.app is not None

    def test_server_has_correct_name(self):
        """Server should have correct name"""
        import server
        assert server.app.name == "incident-timeline-extractor"


class TestExtractorsStillWork:
    """Verify extractors work when imported by server"""

    def test_extractors_accessible_from_server(self):
        """Server should have access to all extractors"""

        # These should be importable
        from server import (
            extract_timeline,
        )

        # Quick smoke test - they should be callable
        result = extract_timeline("@sarah 14:23: test")
        assert isinstance(result, list)
