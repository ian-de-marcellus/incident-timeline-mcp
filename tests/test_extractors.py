"""
Tests for extraction logic in extractors.py
"""

import pytest
from textwrap import dedent
from extractors import extract_timeline, _find_timestamp, _find_actor


class TestExtractTimeline:
    """Tests for extract_timeline function"""
    
    def test_extracts_simple_timeline(self):
        """Should extract events with timestamps"""
        text = dedent("""
            This line has no timestamp
            @sarah 14:23: This line does
            Another line without time
        """).strip()
        
        events = extract_timeline(text)
        
        assert len(events) == 1
        assert events[0]['time'] == '14:23'
        assert events[0]['actor'] == 'sarah'
    
    def test_handles_lines_without_timestamps(self):
        """Should skip lines without timestamps"""
        text = dedent("""
        This line has no timestamp
        @sarah 14:23: This line does
        Another line without time
        """).strip()
        
        events = extract_timeline(text)
        
        assert len(events) == 1
        assert events[0]['time'] == '14:23'
    
    def test_filters_false_positive_timestamps(self):
        """Should filter 'ratio of 3:45' type false positives"""
        text = dedent("""
        error ratio of 3:45 compared to baseline
        @sarah 14:23: Actual event
        running version 1:45 in production
        """).strip()
        
        events = extract_timeline(text)
        
        # Should only get the real timestamp
        assert len(events) == 1
        assert events[0]['time'] == '14:23'

    def test_extracts_multiple_events(self):
        """Should handle multiple timestamped events"""
        text = dedent("""
            @sarah 14:23: Seeing elevated errors
            @mike 14:25: Confirmed error spike  
            @sarah 14:27: Rolling back deploy
            @mike 14:30: Rollback complete
            @sarah 14:35: Back to normal
        """).strip()
        
        events = extract_timeline(text)
        
        assert len(events) == 5
        assert events[0]['time'] == '14:23'
        assert events[0]['actor'] == 'sarah'
        assert events[1]['time'] == '14:25'
        assert events[1]['actor'] == 'mike'
        assert events[4]['time'] == '14:35'

    def test_handles_excessive_whitespace(self):
        """Should handle lines with extra whitespace"""
        text = dedent("""
            @sarah 14:23: Event with leading spaces      
            @mike 14:25: Event with trailing spaces   
            
            
            @alice 14:30: Event after blank lines
        """).strip()
        
        events = extract_timeline(text)
        
        assert len(events) == 3
        assert all('time' in event for event in events)
        # Text should be stripped
        assert not events[0]['text'].startswith(' ')
        assert not events[0]['text'].endswith(' ')

    def test_handles_mixed_timestamp_formats(self):
        """Should handle different timestamp formats in same text"""
        text = dedent("""
            @sarah 14:23: Simple time format
            @mike 14:25:30: Time with seconds
            @alice 2024-01-15 14:30: Full datetime
        """).strip()
        
        events = extract_timeline(text)
        
        assert len(events) == 3
        assert events[0]['time'] == '14:23'
        assert events[1]['time'] == '14:25:30'
        # Full datetime will match the date-time part
        assert '2024-01-15' in events[2]['time']

    def test_events_without_actors(self):
        """Should handle events where no actor is identified"""
        text = dedent("""
            System alert triggered at 14:23
            Automatic recovery started at 14:25
            @sarah 14:30: Manual intervention
        """).strip()
        
        events = extract_timeline(text)
        
        assert len(events) == 3
        # First two should not have 'actor' key
        assert 'actor' not in events[0]
        assert 'actor' not in events[1]
        # Third should have actor
        assert events[2]['actor'] == 'sarah'

    def test_preserves_original_text(self):
        """Should preserve the full original line text"""
        text = "@sarah 14:23: Seeing elevated errors on payment-service"
        
        events = extract_timeline(text)
        
        assert len(events) == 1
        # Full line should be preserved
        assert events[0]['text'] == text
        assert 'payment-service' in events[0]['text']

    def test_empty_input(self):
        """Should handle empty input gracefully"""
        assert extract_timeline("") == []
        assert extract_timeline("   ") == []
        assert extract_timeline("\n\n\n") == []

    def test_no_timestamps_found(self):
        """Should return empty list when no timestamps found"""
        text = dedent("""
            This is just regular text
            With no timestamps at all
            Just descriptions and notes
        """).strip()
        
        events = extract_timeline(text)
        
        assert events == []

    def test_filters_multiple_false_positives(self):
        """Should filter multiple false positive patterns"""
        text = dedent("""
            error ratio of 3:45 compared to baseline
            running version 1:45 in production
            scaled 10:30 compared to previous
            @sarah 14:23: Actual incident event
            another ratio of 2:15 after fix
        """).strip()
        
        events = extract_timeline(text)
        
        # Should only get the one real timestamp
        assert len(events) == 1
        assert events[0]['time'] == '14:23'

    def test_handles_colons_in_text(self):
        """Should handle lines with multiple colons correctly"""
        text = dedent("""
            Error: Database timeout: retry failed at 14:23
            Status: resolved: monitoring at 14:30
        """).strip()
        
        events = extract_timeline(text)
        
        assert len(events) == 2
        assert events[0]['time'] == '14:23'
        assert events[1]['time'] == '14:30'
        # 'Error' and 'Status' should be filtered as actors
        assert 'actor' not in events[0]
        assert 'actor' not in events[1]


class TestFindTimestamp:
    """Tests for _find_timestamp helper"""
    
    def test_finds_simple_time(self):
        """Should find HH:MM format"""
        result = _find_timestamp("Event occurred at 14:23 UTC")
        assert result == "14:23"
    
    def test_finds_time_with_seconds(self):
        """Should find HH:MM:SS format"""
        result = _find_timestamp("Deploy at 14:23:45")
        assert result == "14:23:45"
    
    def test_returns_none_for_no_timestamp(self):
        """Should return None when no timestamp found"""
        result = _find_timestamp("Just some text")
        assert result is None
    
    def test_filters_ratio_false_positive(self):
        """Should filter out 'ratio of 3:45' patterns"""
        result = _find_timestamp("error ratio of 3:45")
        assert result is None


class TestFindActor:
    """Tests for _find_actor helper"""
    
    def test_finds_mention(self):
        """Should find @mention actors"""
        result = _find_actor("@sarah investigating issue")
        assert result == "sarah"
    
    def test_finds_name_colon(self):
        """Should find 'Name:' format"""
        result = _find_actor("Sarah: checking logs")
        assert result == "Sarah"
    
    def test_filters_common_labels(self):
        """Should filter out labels like 'Error:', 'Time:'"""
        assert _find_actor("Error: connection failed") is None
        assert _find_actor("Time: 14:23") is None
        assert _find_actor("Status: resolved") is None
    
    def test_returns_none_for_no_actor(self):
        """Should return None when no actor found"""
        result = _find_actor("System automatically recovered")
        assert result is None