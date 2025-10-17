"""
Tests for pattern matching in patterns.py
"""

import re
import pytest
from patterns import TIMESTAMP_PATTERNS


class TestSimpleTimePattern:
    """Tests for TIMESTAMP_PATTERNS[0] - HH:MM format"""
    
    # Happy path
    @pytest.mark.parametrize("text,expected_match", [
        ("Error occurred at 14:23 in the logs", "14:23"),
        ("Started at 09:45 UTC", "09:45"),
        ("Completed at 23:59", "23:59"),
        ("Midnight at 00:00", "00:00"),
    ])
    def test_matches_valid_times(self, text, expected_match):
        """Should match valid HH:MM times"""
        pattern = TIMESTAMP_PATTERNS[0]
        match = re.search(pattern, text)
        assert match is not None
        assert match.group() == expected_match
    
    # Edge cases - should NOT match
    @pytest.mark.parametrize("text", [
        "server crashed on port 8080",
        "connected to localhost:3000",
        "listening on :8080",
    ])
    def test_no_match_port_numbers(self, text):
        """Port numbers should not match"""
        pattern = TIMESTAMP_PATTERNS[0]
        assert re.search(pattern, text) is None
    
    @pytest.mark.parametrize("text", [
        "ratio is 5:1",
        "deployed v2:30 to production",
    ])
    def test_no_match_clearly_not_times(self, text):
        """Non-time patterns should not match"""
        pattern = TIMESTAMP_PATTERNS[0]
        assert re.search(pattern, text) is None
    
    @pytest.mark.parametrize("text", [
        "Error code: 123:456",
        "EXIT_CODE:12:34",
    ])
    def test_no_match_error_codes(self, text):
        """Error codes should not match"""
        pattern = TIMESTAMP_PATTERNS[0]
        assert re.search(pattern, text) is None
    
    @pytest.mark.parametrize("text", [
        "ticket ID:2468",
        "ref:12:34:56:78",
    ])
    def test_no_match_ids_and_refs(self, text):
        """IDs and references should not match"""
        pattern = TIMESTAMP_PATTERNS[0]
        assert re.search(pattern, text) is None
    
    # Known limitations
    @pytest.mark.xfail(reason="Ambiguous - looks like valid time, filtered in extractor")
    @pytest.mark.parametrize("text", [
        "error ratio of 3:45",
        "running version 1:45",
        "scaled 10:30",
    ])
    def test_ambiguous_patterns(self, text):
        """Some patterns are indistinguishable from times at regex level"""
        pattern = TIMESTAMP_PATTERNS[0]
        assert re.search(pattern, text) is None


class TestFullDatetimePattern:
    """Tests for TIMESTAMP_PATTERNS[1] - YYYY-MM-DD HH:MM:SS format"""
    
    # Happy path
    @pytest.mark.parametrize("text", [
        "Incident started 2024-01-15 14:23 UTC",
        "Logged at 2025-12-31 23:59:59",
        "Occurred 2024-06-15 09:30",
    ])
    def test_matches_valid_datetimes(self, text):
        """Should match full datetime strings"""
        pattern = TIMESTAMP_PATTERNS[1]
        match = re.search(pattern, text)
        assert match is not None
        assert "202" in match.group()  # Year prefix
    
    # Edge cases - should NOT match
    @pytest.mark.parametrize("text", [
        "2024-01-15",      # Date only
        "14:23:45",        # Time only
        "just text",       # No datetime
        "15/01/2024 14:23", # Wrong date format
    ])
    def test_no_match_incomplete_or_wrong_format(self, text):
        """Should require both date and time in correct format"""
        pattern = TIMESTAMP_PATTERNS[1]
        assert re.search(pattern, text) is None


class TestTimeWithSecondsPattern:
    """Tests for TIMESTAMP_PATTERNS[2] - HH:MM:SS format"""
    
    # Happy path
    @pytest.mark.parametrize("text,expected_match", [
        ("Deploy started at 14:23:45", "14:23:45"),
        ("Completed at 00:00:00", "00:00:00"),
        ("Peak at 23:59:59", "23:59:59"),
    ])
    def test_matches_valid_times_with_seconds(self, text, expected_match):
        """Should match HH:MM:SS format"""
        pattern = TIMESTAMP_PATTERNS[2]
        match = re.search(pattern, text)
        assert match is not None
        assert match.group() == expected_match
    
    # Edge cases - should NOT match
    @pytest.mark.parametrize("text", [
        "12:34:56:78",  # Too many segments
        "12:34",        # Missing seconds (should match pattern[0] instead)
        "ref:12:34:56:78", # Reference ID, not time
    ])
    def test_no_match_wrong_format(self, text):
        """Should not match incorrect formats"""
        pattern = TIMESTAMP_PATTERNS[2]
        assert re.search(pattern, text) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])