"""
Tests for extraction logic in extractors.py
"""

import pytest
from textwrap import dedent
from datetime import datetime
from extractors import (
    extract_timeline, _find_timestamp, _find_actor, _parse_timestamp_str,
    _detect_line_severity, _build_severity_timeline, _compute_metrics,
    identify_actions, extract_entities, _is_valid_ip, _is_likely_domain,
    _is_likely_service, detect_severity, generate_summary,
    _classify_ir_phase, _classify_timeline_phases, _group_by_phase,
    map_to_framework, _analyze_timeline,
)


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

    def test_filters_domains_with_colon(self):
        """Should not treat domains as actors even with colon"""
        assert _find_actor("google.com: returned 500") is None
        assert _find_actor("api.example.com: timeout") is None
        assert _find_actor("service.io: connection refused") is None
    
    def test_accepts_names_with_dots(self):
        """Should accept firstname.lastname as actors"""
        assert _find_actor("sarah.chen: investigating") == "sarah.chen"
        assert _find_actor("james.rodriguez: taking role") == "james.rodriguez"

class TestIdentifyActions:
    """Tests for identify_actions function"""
    
    def test_finds_investigation_actions(self):
        """Should identify investigation-type actions"""
        text = dedent("""
            @sarah investigating the database issue
            @mike checked the logs
            @alice analyzing error patterns
        """).strip()
        
        actions = identify_actions(text)
        
        assert len(actions) == 3
        assert all(a['category'] == 'investigation' for a in actions)
        assert actions[0]['action'] == 'investigating'
        assert actions[1]['action'] == 'checked'
        assert actions[2]['action'] == 'analyzing'
    
    def test_finds_remediation_actions(self):
        """Should identify remediation-type actions"""
        text = dedent("""
            @sarah deployed the fix
            @mike rolled back the change
            @alice restarted the service
        """).strip()
        
        actions = identify_actions(text)
        
        assert len(actions) == 3
        assert all(a['category'] == 'remediation' for a in actions)
        assert actions[0]['action'] == 'deployed'
        assert actions[1]['action'] == 'rolled back'

    def test_finds_communication_actions(self):
        """Should identify communication-type actions"""
        text = dedent("""
            @sarah notified the on-call team
            @mike escalated to management
            @alice confirmed the issue
        """).strip()
        
        actions = identify_actions(text)
        
        assert len(actions) == 3
        assert all(a['category'] == 'communication' for a in actions)
        assert actions[0]['action'] == 'notified'
        assert actions[1]['action'] == 'escalated'
        assert actions[2]['action'] == 'confirmed'

    def test_finds_status_actions(self):
        """Should identify status-change actions"""
        text = dedent("""
            @sarah resolved the incident
            @mike mitigated the impact
            @alice completed the rollback
        """).strip()
        
        actions = identify_actions(text)
        
        assert len(actions) == 3
        assert all(a['category'] == 'status' for a in actions)
        assert actions[0]['action'] == 'resolved'
        assert actions[1]['action'] == 'mitigated'
        assert actions[2]['action'] == 'completed'
    
    def test_case_insensitive_matching(self):
        """Should match actions regardless of case"""
        text = dedent("""
            @sarah DEPLOYED the fix
            @mike Rolled Back the change
            @alice ReStArTeD the service
        """).strip()
        
        actions = identify_actions(text)
        
        assert len(actions) == 3
        # Actions should be lowercase (as stored in keywords)
        assert actions[0]['action'] == 'deployed'
    
    def test_preserves_full_context(self):
        """Should preserve the full line as context"""
        text = "@sarah deployed payment-service v2.1.3 to production"
        
        actions = identify_actions(text)
        
        assert len(actions) == 1
        assert actions[0]['context'] == text
    
    def test_one_action_per_line(self):
        """Should only record first action per line"""
        text = "@sarah investigated and then deployed the fix"
        
        actions = identify_actions(text)
        
        # Should only get first action found
        assert len(actions) == 1
        assert actions[0]['action'] in ['investigated', 'deployed']
    
    def test_empty_input(self):
        """Should handle empty input"""
        assert identify_actions("") == []
        assert identify_actions("   \n\n   ") == []
    
    def test_no_actions_found(self):
        """Should return empty list when no actions found"""
        text = dedent("""
            Just some regular text
            With no action keywords
        """).strip()
        
        assert identify_actions(text) == []

    def test_finds_mixed_action_categories(self):
        """Should handle different action types in same text"""
        text = dedent("""
            @sarah investigating the error
            @mike deployed the fix
            @alice notified stakeholders
            @bob resolved the ticket
        """).strip()
        
        actions = identify_actions(text)
        
        assert len(actions) == 4
        assert actions[0]['category'] == 'investigation'
        assert actions[1]['category'] == 'remediation'
        assert actions[2]['category'] == 'communication'
        assert actions[3]['category'] == 'status'

    def test_handles_multi_word_actions(self):
        """Should match multi-word actions like 'rolled back'"""
        text = "@sarah rolled back the deploy"
        
        actions = identify_actions(text)
        
        assert len(actions) == 1
        assert actions[0]['action'] == 'rolled back'
        assert actions[0]['category'] == 'remediation'

    def test_action_at_different_positions(self):
        """Should find actions regardless of position in line"""
        text = dedent("""
            deployed new version @sarah
            @mike investigating in production
            the service was restarted by ops
        """).strip()
        
        actions = identify_actions(text)
        
        assert len(actions) == 3
        assert 'deployed' in [a['action'] for a in actions]
        assert 'investigating' in [a['action'] for a in actions]
        assert 'restarted' in [a['action'] for a in actions]

    def test_handles_verb_tense_variations(self):
        """Should match both -ing and past tense forms"""
        text = dedent("""
            @sarah investigating the issue now
            @mike investigated the logs earlier
            @alice deploying the fix
            @bob deployed to staging
        """).strip()
        
        actions = identify_actions(text)
        
        assert len(actions) == 4
        assert actions[0]['action'] == 'investigating'
        assert actions[1]['action'] == 'investigated'
        assert actions[2]['action'] == 'deploying'
        assert actions[3]['action'] == 'deployed'

    def test_ignores_action_keywords_in_nouns(self):
        """Should handle action keywords used as nouns/in other contexts"""
        # This might reveal edge cases where we match too broadly
        text = dedent("""
            The deployment was successful
            Investigation report attached
            @sarah deployed the fix
        """).strip()
        
        actions = identify_actions(text)
        
        # Should find at least the one with @sarah
        # Might also match 'deployment' and 'investigation' - that's okay
        assert len(actions) >= 1
        # The explicit action should be found
        assert any(a['action'] == 'deployed' and '@sarah' in a['context'] 
                for a in actions)
        
class TestExtractEntities:
    """Tests for extract_entities function"""
    
    def test_extracts_services(self):
        """Should find service names"""
        text = dedent("""
            payment-service is down
            user_service restarted
            auth-api responding slowly
        """).strip()
        
        entities = extract_entities(text)
        
        assert 'payment-service' in entities['services']
        assert 'user_service' in entities['services']
        assert 'auth-api' in entities['services']
    
    def test_extracts_ip_addresses(self):
        """Should find IP addresses"""
        text = dedent("""
            server at 192.168.1.1 is down
            connecting to 10.0.0.1 failed
            timeout from 172.16.0.1
        """).strip()
        
        entities = extract_entities(text)
        
        assert '192.168.1.1' in entities['ips']
        assert '10.0.0.1' in entities['ips']
        assert '172.16.0.1' in entities['ips']
    
    def test_extracts_domains(self):
        """Should find domain names"""
        text = dedent("""
            api.example.com returned 500
            timeout from service.uber.com
            resolved payment.stripe.com
        """).strip()
        
        entities = extract_entities(text)
        
        assert 'api.example.com' in entities['domains']
        assert 'service.uber.com' in entities['domains']
        assert 'payment.stripe.com' in entities['domains']
    
    def test_extracts_mixed_entities(self):
        """Should find all entity types in same text"""
        text = "payment-service at 10.0.0.1 calling api.example.com"
        
        entities = extract_entities(text)
        
        assert len(entities['services']) == 1
        assert len(entities['ips']) == 1
        assert len(entities['domains']) == 1
    
    def test_deduplicates_entities(self):
        """Should not list the same entity multiple times"""
        text = dedent("""
            payment-service is down
            payment-service was restarted
            payment-service is now up
        """).strip()
        
        entities = extract_entities(text)
        
        # Should only appear once
        assert entities['services'].count('payment-service') == 1
    
    def test_filters_invalid_ips(self):
        """Should filter out invalid IP addresses"""
        text = dedent("""
            server at 999.999.999.999 (invalid)
            valid server at 10.0.0.1
            another invalid 256.256.256.256
        """).strip()
        
        entities = extract_entities(text)
        
        # Should only get the valid IP
        assert '10.0.0.1' in entities['ips']
        assert '999.999.999.999' not in entities['ips']
        assert '256.256.256.256' not in entities['ips']
    
    def test_case_insensitive_services(self):
        """Should handle service names regardless of case"""
        text = "Payment-Service and USER_SERVICE are down"
        
        entities = extract_entities(text)
        
        # Should be lowercase
        assert 'payment-service' in entities['services']
        assert 'user_service' in entities['services']
    
    def test_empty_input(self):
        """Should handle empty input"""
        entities = extract_entities("")
        
        assert entities == {'services': [], 'ips': [], 'domains': []}
    
    def test_no_entities_found(self):
        """Should return empty lists when no entities found"""
        text = "Just some regular text with no entities"
        
        entities = extract_entities(text)
        
        assert entities['services'] == []
        assert entities['ips'] == []
        assert entities['domains'] == []


class TestIsValidIp:
    """Tests for _is_valid_ip helper"""
    
    @pytest.mark.parametrize("ip", [
        "192.168.1.1",
        "10.0.0.1",
        "172.16.0.1",
        "0.0.0.0",
        "255.255.255.255",
    ])
    def test_accepts_valid_ips(self, ip):
        """Should accept valid IP addresses"""
        assert _is_valid_ip(ip) is True
    
    @pytest.mark.parametrize("ip", [
        "999.999.999.999",
        "256.256.256.256",
        "300.1.1.1",
        "1.1.1.256",
    ])
    def test_rejects_invalid_ips(self, ip):
        """Should reject IPs with out-of-range octets"""
        assert _is_valid_ip(ip) is False


class TestIsLikelyDomain:
    """Tests for _is_likely_domain helper"""
    
    @pytest.mark.parametrize("domain", [
        "api.example.com",
        "service.uber.com",
        "payment.stripe.com",
    ])
    def test_accepts_valid_domains(self, domain):
        """Should accept reasonable domain names"""
        assert _is_likely_domain(domain) is True
    
    @pytest.mark.parametrize("domain", [
        "a.b",          # Too short
        "x.co",         # Too short
    ])
    def test_rejects_too_short(self, domain):
        """Should reject very short domains"""
        assert _is_likely_domain(domain) is False

class TestDetectSeverity:
    """Tests for detect_severity function"""
    
    def test_detects_critical_severity(self):
        """Should identify critical incidents"""
        text = dedent("""
            payment service is down
            complete outage affecting all users
            critical system failure
        """).strip()
        
        result = detect_severity(text)
        
        assert result['level'] == 'critical'
        assert 'is down' in result['indicators']
        assert 'outage' in result['indicators']
        assert 'critical' in result['indicators']
    
    def test_detects_high_severity(self):
        """Should identify high severity incidents"""
        text = dedent("""
            service is degraded
            high error rate detected
            performance issues reported
        """).strip()
        
        result = detect_severity(text)
        
        assert result['level'] == 'high'
        assert 'degraded' in result['indicators']
        assert 'high error' in result['indicators']
    
    def test_detects_medium_severity(self):
        """Should identify medium severity incidents"""
        text = dedent("""
            intermittent issues reported
            affecting some users
        """).strip()
        
        result = detect_severity(text)
        
        assert result['level'] == 'medium'
        assert 'intermittent' in result['indicators']
        assert 'some users' in result['indicators']
    
    def test_detects_low_severity(self):
        """Should identify low severity incidents"""
        text = "minor cosmetic issue in UI"
        
        result = detect_severity(text)
        
        assert result['level'] == 'low'
        assert 'minor' in result['indicators']
        assert 'cosmetic' in result['indicators']
    
    def test_unknown_severity_when_no_indicators(self):
        """Should return unknown when no severity indicators found"""
        text = "Just some regular incident notes with no severity words"
        
        result = detect_severity(text)
        
        assert result['level'] == 'unknown'
        assert result['indicators'] == []
        assert result['confidence'] == 'low'
    
    def test_prioritizes_critical_over_lower(self):
        """Should return critical even if lower severity keywords present"""
        text = dedent("""
            system is down (critical)
            some minor issues also noted
            intermittent problems too
        """).strip()
        
        result = detect_severity(text)
        
        # Critical should win
        assert result['level'] == 'critical'
        assert 'is down' in result['indicators']
    
    def test_confidence_high_with_multiple_indicators(self):
        """Should have high confidence with 3+ indicators"""
        text = "critical outage, service down, complete failure"
        
        result = detect_severity(text)
        
        assert result['confidence'] == 'high'
        assert len(result['indicators']) >= 3
    
    def test_confidence_medium_with_few_indicators(self):
        """Should have medium confidence with 1-2 indicators"""
        text = "service is down"
        
        result = detect_severity(text)
        
        assert result['confidence'] == 'medium'
        assert len(result['indicators']) >= 1
        assert len(result['indicators']) < 3
    
    def test_confidence_low_with_no_indicators(self):
        """Should have low confidence with no indicators"""
        text = "regular incident description"
        
        result = detect_severity(text)
        
        assert result['confidence'] == 'low'
    
    def test_case_insensitive_matching(self):
        """Should match severity keywords regardless of case"""
        text = "CRITICAL OUTAGE - Service DOWN"
        
        result = detect_severity(text)
        
        assert result['level'] == 'critical'
        assert len(result['indicators']) >= 2
    
    def test_multi_word_indicators(self):
        """Should match multi-word severity indicators"""
        text = "experiencing high error rate and complete loss of service"
        
        result = detect_severity(text)
        
        # Should find multi-word indicators
        assert 'high error rate' in result['indicators'] or 'complete loss' in result['indicators']
    
    def test_empty_input(self):
        """Should handle empty input"""
        result = detect_severity("")
        
        assert result['level'] == 'unknown'
        assert result['indicators'] == []

class TestGenerateSummary:
    """Tests for generate_summary function"""
    
    def test_combines_all_extractors(self):
        """Should run all extractors and include their results"""
        text = dedent("""
            @sarah 14:23: payment-service is down, critical outage
            @mike 14:25: investigating the issue
            @sarah 14:30: deployed fix to 10.0.0.1
            @mike 14:35: service restored, monitoring api.example.com
        """).strip()
        
        summary = generate_summary(text)
        
        # Should have all components
        assert 'timeline' in summary
        assert 'actions' in summary
        assert 'entities' in summary
        assert 'severity' in summary
        assert 'summary_text' in summary
        
        # Check each component has data
        assert len(summary['timeline']) == 4
        assert len(summary['actions']) > 0
        assert summary['severity']['level'] == 'critical'
    
    def test_generates_readable_summary_text(self):
        """Should create human-readable summary"""
        text = dedent("""
            @sarah 14:23: payment-service down, critical issue
            @mike 14:25: deployed fix
        """).strip()
        
        summary = generate_summary(text)
        
        summary_text = summary['summary_text']
        
        # Should mention severity
        assert 'CRITICAL' in summary_text.upper()
        # Should mention timeline
        assert '2 events' in summary_text.lower()
        # Should mention actions
        assert 'actions' in summary_text.lower()
    
    def test_includes_timeline_timerange(self):
        """Should show first and last event times"""
        text = dedent("""
            @sarah 14:23: First event
            @mike 14:30: Middle event
            @alice 14:45: Last event
        """).strip()
        
        summary = generate_summary(text)
        
        summary_text = summary['summary_text']
        
        # Should show time range
        assert '14:23' in summary_text
        assert '14:45' in summary_text
    
    def test_categorizes_actions_in_summary(self):
        """Should break down actions by category"""
        text = dedent("""
            @sarah investigating the issue
            @mike deployed the fix
            @alice notified stakeholders
            @bob resolved the ticket
        """).strip()
        
        summary = generate_summary(text)
        
        summary_text = summary['summary_text']
        
        # Should mention action categories
        assert 'investigation' in summary_text.lower()
        assert 'remediation' in summary_text.lower()
        assert 'communication' in summary_text.lower()
        assert 'status' in summary_text.lower()
    
    def test_lists_entity_counts(self):
        """Should summarize entities found"""
        text = dedent("""
            payment-service at 10.0.0.1 calling api.example.com
            user-service at 10.0.0.2 calling auth.example.com
        """).strip()
        
        summary = generate_summary(text)
        
        summary_text = summary['summary_text']
        
        # Should mention entity types and counts
        assert 'services' in summary_text.lower()
        assert 'ips' in summary_text.lower()
        assert 'domains' in summary_text.lower()
    
    def test_handles_minimal_incident(self):
        """Should handle incident with minimal information"""
        text = "@sarah 14:23: Something happened"
        
        summary = generate_summary(text)
        
        # Should still have structure
        assert summary['timeline']
        assert summary['severity']['level'] == 'unknown'
        assert summary['summary_text']
    
    def test_handles_empty_input(self):
        """Should handle empty input gracefully"""
        summary = generate_summary("")
        
        assert summary['timeline'] == []
        assert summary['actions'] == []
        assert summary['entities'] == {'services': [], 'ips': [], 'domains': []}
        assert summary['severity']['level'] == 'unknown'
        assert 'No significant data' in summary['summary_text']
    
    def test_no_data_produces_clear_message(self):
        """Should clearly indicate when no data extracted"""
        text = "Just some random text with no incident information"
        
        summary = generate_summary(text)
        
        assert 'No significant data' in summary['summary_text']
    
    def test_complete_incident_example(self):
        """Integration test with realistic incident"""
        text = dedent("""
            @sarah 14:23: Seeing elevated error rates on payment-service
            @mike 14:25: Confirmed. Error rate jumped from 0.1% to 15%
            @sarah 14:27: Rolling back deploy from 14:15
            @mike 14:30: Rollback complete. Error rate dropping
            @sarah 14:35: Back to normal levels. Monitoring api.stripe.com
            @mike 14:40: Incident resolved. Postmortem scheduled.
        """).strip()
        
        summary = generate_summary(text)
        
        # Timeline
        assert len(summary['timeline']) == 6
        assert summary['timeline'][0]['actor'] == 'sarah'
        
        # Actions
        assert len(summary['actions']) >= 3  # rolling back, monitoring, resolved
        
        # Entities
        assert 'payment-service' in summary['entities']['services']
        assert 'api.stripe.com' in summary['entities']['domains']
        
        # Severity (might be medium/high due to error rates)
        assert summary['severity']['level'] in ['high', 'medium', 'unknown']
        
        # Summary text should be comprehensive
        assert len(summary['summary_text']) > 50

        print(summary)


# ============================================================
# Phase 1 regression tests — one class per bug fix
# ============================================================

class TestActorPriority:
    """Regression tests: speaker patterns should take priority over @mentions."""

    def test_speaker_over_mention(self):
        """name.dot: speaker should win over @mention in body"""
        actor = _find_actor("sarah.chen: @alex.kim can you check the logs?")
        assert actor == "sarah.chen"

    def test_mention_fallback(self):
        """@mention should still work when no speaker pattern matches"""
        actor = _find_actor("@sarah 14:23: Seeing elevated errors")
        assert actor == "sarah"

    def test_channel_mention_filtered(self):
        """@channel is a broadcast, not a person"""
        actor = _find_actor("@channel alert fired on payment-service")
        assert actor is None

    def test_here_mention_filtered(self):
        """@here is a broadcast, not a person"""
        actor = _find_actor("@here incident declared")
        assert actor is None

    def test_everyone_mention_filtered(self):
        """@everyone is a broadcast, not a person"""
        actor = _find_actor("@everyone please join the war room")
        assert actor is None

    def test_timeline_extracts_speaker_not_mention(self):
        """End-to-end: extract_timeline should use the speaker as actor"""
        text = "2024-10-15T14:23:15Z sarah.chen: @channel Seeing elevated response times"
        events = extract_timeline(text)
        assert len(events) == 1
        assert events[0]['actor'] == 'sarah.chen'

    def test_timeline_mention_with_speaker(self):
        """When a speaker mentions someone else, actor should be the speaker"""
        text = "2024-10-15T14:23:47Z james.rodriguez: @alex.kim can you check customer impact?"
        events = extract_timeline(text)
        assert len(events) == 1
        assert events[0]['actor'] == 'james.rodriguez'


class TestActionWordBoundary:
    """Regression tests: action keyword matching should use word boundaries."""

    def test_escalated_not_matched_as_scaled(self):
        """'escalated' should match as communication, not remediation ('scaled')"""
        actions = identify_actions("@mike escalated to management")
        assert len(actions) == 1
        assert actions[0]['action'] == 'escalated'
        assert actions[0]['category'] == 'communication'

    def test_scaled_still_matches(self):
        """'scaled' should still match as remediation when used standalone"""
        actions = identify_actions("@sarah scaled the service to 10 replicas")
        assert len(actions) == 1
        assert actions[0]['action'] == 'scaled'
        assert actions[0]['category'] == 'remediation'

    def test_no_partial_match_in_compound_words(self):
        """Action keywords should not match inside compound words"""
        # "prefixed" contains "fixed" but should not match
        actions = identify_actions("the variable was prefixed with env_")
        fixed_actions = [a for a in actions if a['action'] == 'fixed']
        assert len(fixed_actions) == 0


class TestDomainFiltering:
    """Regression tests: firstname.lastname should not be detected as domains."""

    def test_person_name_not_domain(self):
        """sarah.chen should NOT appear in domains"""
        entities = extract_entities("sarah.chen: investigating the issue")
        assert 'sarah.chen' not in entities['domains']

    def test_multiple_person_names_filtered(self):
        """All firstname.lastname patterns should be filtered"""
        text = dedent("""
            sarah.chen: checking logs
            james.rodriguez: escalated
            alex.kim: monitoring
            david.park: deployed fix
        """).strip()
        entities = extract_entities(text)
        for name in ['sarah.chen', 'james.rodriguez', 'alex.kim', 'david.park']:
            assert name not in entities['domains']

    def test_real_domain_still_detected(self):
        """api.stripe.com should still be detected as a domain"""
        entities = extract_entities("timeout from api.stripe.com")
        assert 'api.stripe.com' in entities['domains']

    def test_domain_with_known_tld(self):
        """Domains with recognized TLDs should pass"""
        entities = extract_entities("checking meet.company.com and github.io")
        assert 'meet.company.com' in entities['domains']
        assert 'github.io' in entities['domains']


class TestServiceBroadening:
    """Regression tests: service detection should catch infra compound names."""

    def test_db_primary_detected(self):
        """checkout-db-primary should be detected as a service"""
        entities = extract_entities("elevated response times on checkout-db-primary")
        assert 'checkout-db-primary' in entities['services']

    def test_cache_service_detected(self):
        """redis-cache-03 should be detected as a service"""
        entities = extract_entities("redis-cache-03 is unresponsive")
        assert 'redis-cache-03' in entities['services']

    def test_processor_detected(self):
        """order-processor should be detected as a service"""
        entities = extract_entities("order-processor queue is backed up")
        assert 'order-processor' in entities['services']

    def test_non_service_compound_rejected(self):
        """rolled-back should NOT be detected as a service"""
        entities = extract_entities("we rolled-back the deploy")
        assert 'rolled-back' not in entities['services']

    def test_original_suffix_pattern_still_works(self):
        """Single-word service names like authservice should still match"""
        entities = extract_entities("authservice failed to start")
        assert 'authservice' in entities['services']

    def test_is_likely_service_helper(self):
        """_is_likely_service should validate infra keywords"""
        assert _is_likely_service('checkout-db-primary') is True
        assert _is_likely_service('redis-cache-03') is True
        assert _is_likely_service('order-processor') is True
        assert _is_likely_service('rolled-back') is False
        assert _is_likely_service('error-rate') is False


class TestSeverityNegation:
    """Regression tests: negated severity keywords should not count."""

    def test_negated_down_not_critical(self):
        """'back to normal' before 'down' should negate severity"""
        result = detect_severity("CPU went back down to normal levels")
        assert result['level'] != 'critical'

    def test_resolved_outage_not_critical(self):
        """'resolved' before 'outage' should negate severity"""
        result = detect_severity("resolved the outage at 14:30")
        assert 'outage' not in result['indicators']

    def test_non_negated_still_detected(self):
        """severity keywords without negation should still work"""
        result = detect_severity("service is down, complete outage")
        assert result['level'] == 'critical'
        assert 'is down' in result['indicators']
        assert 'outage' in result['indicators']

    def test_fixed_issue_not_severe(self):
        """'fixed' before severity keyword should negate"""
        result = detect_severity("fixed the timeout issue yesterday")
        # "timeout" should be negated by "fixed"
        assert 'timeout' not in result['indicators']

    def test_restored_service_not_critical(self):
        """'restored' before 'down' should negate"""
        result = detect_severity("restored the service that was down")
        assert 'is down' not in result['indicators'] or result['level'] != 'critical'

    @pytest.mark.parametrize("text", [
        "load shedding non-critical endpoints",
        "non-critical alert from monitoring",
        "this is a non-critical update",
    ])
    def test_hyphenated_negation_not_critical(self, text):
        """'non-critical' should not trigger critical severity"""
        result = detect_severity(text)
        assert 'critical' not in result['indicators']
        assert result['level'] != 'critical'

    def test_hyphenated_negation_other_keywords(self):
        """Hyphenated prefixes should negate any severity keyword"""
        result = detect_severity("pre-degraded state is normal for this service")
        assert 'degraded' not in result['indicators']


# ============================================================
# Phase 2 regression tests — temporal analysis
# ============================================================

class TestParseTimestampStr:
    """Tests for _parse_timestamp_str helper."""

    def test_parses_iso8601(self):
        """Should parse ISO 8601 timestamps"""
        result = _parse_timestamp_str("2024-10-15T14:23:15Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 10
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 23
        assert result.second == 15

    def test_parses_full_datetime(self):
        """Should parse full datetime format"""
        result = _parse_timestamp_str("2024-10-15 14:23:45")
        assert result is not None
        assert result.year == 2024
        assert result.hour == 14
        assert result.minute == 23
        assert result.second == 45

    def test_parses_full_datetime_no_seconds(self):
        """Should parse full datetime without seconds"""
        result = _parse_timestamp_str("2024-10-15 14:23")
        assert result is not None
        assert result.year == 2024
        assert result.hour == 14
        assert result.minute == 23

    def test_parses_time_with_seconds(self):
        """Should parse time with seconds using sentinel date"""
        result = _parse_timestamp_str("14:23:45")
        assert result is not None
        assert result.year == 1970  # sentinel date
        assert result.hour == 14
        assert result.minute == 23
        assert result.second == 45

    def test_parses_simple_time(self):
        """Should parse simple HH:MM time using sentinel date"""
        result = _parse_timestamp_str("14:23")
        assert result is not None
        assert result.year == 1970
        assert result.hour == 14
        assert result.minute == 23

    def test_returns_none_for_invalid(self):
        """Should return None for unparseable strings"""
        assert _parse_timestamp_str("not a time") is None
        assert _parse_timestamp_str("") is None

    def test_time_only_are_sortable(self):
        """Time-only values should be sortable among themselves"""
        t1 = _parse_timestamp_str("14:23")
        t2 = _parse_timestamp_str("14:30")
        t3 = _parse_timestamp_str("09:00")
        assert t3 < t1 < t2


class TestTimelineSorting:
    """Tests for timestamp sorting in extract_timeline."""

    def test_events_include_timestamp_field(self):
        """Events should have a timestamp field with ISO format"""
        text = "@sarah 14:23: Something happened"
        events = extract_timeline(text)
        assert len(events) == 1
        assert 'timestamp' in events[0]
        assert '14:23' in events[0]['timestamp']

    def test_iso_events_include_timestamp(self):
        """ISO 8601 events should have parsed timestamp"""
        text = "2024-10-15T14:23:15Z sarah.chen: investigating"
        events = extract_timeline(text)
        assert len(events) == 1
        assert '2024-10-15' in events[0]['timestamp']

    def test_out_of_order_events_sorted(self):
        """Events should be sorted by timestamp"""
        text = dedent("""
            @sarah 14:30: Third event
            @mike 14:23: First event
            @alice 14:25: Second event
        """).strip()
        events = extract_timeline(text)
        assert len(events) == 3
        assert events[0]['time'] == '14:23'
        assert events[1]['time'] == '14:25'
        assert events[2]['time'] == '14:30'

    def test_already_sorted_stays_sorted(self):
        """Already-sorted events should maintain order"""
        text = dedent("""
            @sarah 14:23: First
            @mike 14:25: Second
            @alice 14:30: Third
        """).strip()
        events = extract_timeline(text)
        assert events[0]['time'] == '14:23'
        assert events[1]['time'] == '14:25'
        assert events[2]['time'] == '14:30'

    def test_time_field_preserved(self):
        """Original time field should be unchanged (backwards compatible)"""
        text = "@sarah 14:23: Event"
        events = extract_timeline(text)
        assert events[0]['time'] == '14:23'


class TestDetectLineSeverity:
    """Tests for _detect_line_severity helper."""

    def test_detects_critical(self):
        """Should detect critical severity in a line"""
        result = _detect_line_severity("payment service is down")
        assert result is not None
        assert result['level'] == 'critical'
        assert result['trigger'] == 'is down'

    def test_detects_high(self):
        """Should detect high severity"""
        result = _detect_line_severity("service is degraded, latency increasing")
        assert result is not None
        assert result['level'] == 'high'

    def test_returns_none_for_no_severity(self):
        """Should return None when no severity signal"""
        result = _detect_line_severity("checking the logs now")
        assert result is None

    def test_negated_keyword_ignored(self):
        """Should not detect negated severity"""
        result = _detect_line_severity("resolved the outage successfully")
        assert result is None

    def test_highest_severity_wins(self):
        """Should return highest severity when multiple present"""
        result = _detect_line_severity("critical outage with degraded performance")
        assert result['level'] == 'critical'


class TestSeverityTimeline:
    """Tests for _build_severity_timeline."""

    def test_tracks_severity_changes(self):
        """Should record severity transitions"""
        events = [
            {'text': 'service is degraded', 'timestamp': '1970-01-01T14:23:00'},
            {'text': 'service is down completely', 'timestamp': '1970-01-01T14:25:00'},
            {'text': 'checking the logs', 'timestamp': '1970-01-01T14:27:00'},
        ]
        timeline = _build_severity_timeline(events)
        assert len(timeline) == 2
        assert timeline[0]['level'] == 'high'
        assert timeline[1]['level'] == 'critical'

    def test_no_duplicate_for_same_level(self):
        """Should not record when severity stays the same"""
        events = [
            {'text': 'service is degraded', 'timestamp': '1970-01-01T14:23:00'},
            {'text': 'still slow and degraded', 'timestamp': '1970-01-01T14:25:00'},
        ]
        timeline = _build_severity_timeline(events)
        assert len(timeline) == 1

    def test_empty_events(self):
        """Should handle empty input"""
        assert _build_severity_timeline([]) == []

    def test_includes_timestamps(self):
        """Should include timestamps in severity changes"""
        events = [
            {'text': 'service is down', 'timestamp': '2024-10-15T14:23:00'},
        ]
        timeline = _build_severity_timeline(events)
        assert len(timeline) == 1
        assert timeline[0]['timestamp'] == '2024-10-15T14:23:00'


class TestComputeMetrics:
    """Tests for _compute_metrics."""

    def test_counts_events(self):
        """Should count total events"""
        timeline = [
            {'text': 'event 1', 'actor': 'sarah'},
            {'text': 'event 2', 'actor': 'mike'},
        ]
        metrics = _compute_metrics(timeline, [])
        assert metrics['num_events'] == 2

    def test_counts_unique_responders(self):
        """Should count unique actors"""
        timeline = [
            {'text': 'e1', 'actor': 'sarah'},
            {'text': 'e2', 'actor': 'mike'},
            {'text': 'e3', 'actor': 'sarah'},  # duplicate
        ]
        metrics = _compute_metrics(timeline, [])
        assert metrics['num_responders'] == 2

    def test_computes_duration(self):
        """Should compute duration from first to last event"""
        timeline = [
            {'text': 'first', 'timestamp': '1970-01-01T14:23:00'},
            {'text': 'middle', 'timestamp': '1970-01-01T14:30:00'},
            {'text': 'last', 'timestamp': '1970-01-01T14:53:00'},
        ]
        metrics = _compute_metrics(timeline, [])
        assert metrics['duration'] == '30m'
        assert metrics['duration_seconds'] == 1800

    def test_computes_hours_duration(self):
        """Should format duration with hours when >= 60 min"""
        timeline = [
            {'text': 'first', 'timestamp': '1970-01-01T14:00:00'},
            {'text': 'last', 'timestamp': '1970-01-01T16:30:00'},
        ]
        metrics = _compute_metrics(timeline, [])
        assert metrics['duration'] == '2h 30m'

    def test_no_duration_for_single_event(self):
        """Should not compute duration with only one event"""
        timeline = [
            {'text': 'only event', 'timestamp': '1970-01-01T14:23:00'},
        ]
        metrics = _compute_metrics(timeline, [])
        assert 'duration' not in metrics

    def test_empty_timeline(self):
        """Should handle empty timeline"""
        metrics = _compute_metrics([], [])
        assert metrics['num_events'] == 0
        assert metrics['num_responders'] == 0
        assert 'duration' not in metrics

    def test_ttr_from_resolved_action(self):
        """Should compute time to resolve from 'resolved' action"""
        timeline = [
            {'text': '@sarah 14:23: issue detected', 'timestamp': '1970-01-01T14:23:00'},
            {'text': '@mike 14:35: incident resolved', 'timestamp': '1970-01-01T14:35:00'},
        ]
        actions = [
            {'action': 'resolved', 'category': 'status',
             'context': '@mike 14:35: incident resolved'},
        ]
        metrics = _compute_metrics(timeline, actions)
        assert metrics['time_to_resolve'] == '12m'


class TestGenerateSummaryPhase2:
    """Tests for updated generate_summary with metrics and severity timeline."""

    def test_summary_includes_metrics(self):
        """Summary should include metrics dict"""
        text = dedent("""
            @sarah 14:23: payment-service is down
            @mike 14:25: investigating
            @sarah 14:35: incident resolved
        """).strip()
        summary = generate_summary(text)
        assert 'metrics' in summary
        assert summary['metrics']['num_events'] == 3
        assert summary['metrics']['num_responders'] == 2

    def test_summary_includes_severity_timeline(self):
        """Summary should include severity_timeline list"""
        text = dedent("""
            @sarah 14:23: payment-service is down
            @mike 14:30: service restored, back to normal
        """).strip()
        summary = generate_summary(text)
        assert 'severity_timeline' in summary
        assert len(summary['severity_timeline']) >= 1

    def test_summary_text_includes_duration(self):
        """Summary text should mention duration"""
        text = dedent("""
            @sarah 14:00: issue started
            @mike 14:30: issue ended
        """).strip()
        summary = generate_summary(text)
        assert '30m' in summary['summary_text']

    def test_summary_text_includes_responders(self):
        """Summary text should mention responder count"""
        text = dedent("""
            @sarah 14:23: event one
            @mike 14:25: event two
            @alice 14:30: event three
        """).strip()
        summary = generate_summary(text)
        assert 'Responders: 3' in summary['summary_text']


# ── Crypto/fintech domain keyword tests ──────────────────────────────

class TestCryptoSeverityKeywords:
    """Severity detection for crypto/fintech-specific incidents"""

    @pytest.mark.parametrize("text,expected_level", [
        ("@ops 14:23: hot wallet drained, funds at risk", "critical"),
        ("@ops 14:23: wallet compromised, investigating", "critical"),
        ("@ops 14:23: trading halted across all pairs", "critical"),
        ("@ops 14:23: withdrawals disabled for all users", "critical"),
        ("@ops 14:23: possible exploit detected on bridge", "critical"),
        ("@ops 14:23: unauthorized withdrawal from vault", "critical"),
        ("@ops 14:23: private key exposed in logs", "critical"),
    ])
    def test_crypto_critical_severity(self, text, expected_level):
        """Crypto-specific critical keywords should be detected"""
        severity = detect_severity(text)
        assert severity['level'] == expected_level

    @pytest.mark.parametrize("text,expected_level", [
        ("@ops 14:23: seeing significant slippage on BTC/USD", "high"),
        ("@ops 14:23: price feed stale for 5 minutes", "high"),
        ("@ops 14:23: gas spike causing failed transactions", "high"),
        ("@ops 14:23: chain congestion delaying confirmations", "high"),
        ("@ops 14:23: oracle failure on ETH price", "high"),
        ("@ops 14:23: mass liquidation events triggered", "high"),
    ])
    def test_crypto_high_severity(self, text, expected_level):
        """Crypto-specific high keywords should be detected"""
        severity = detect_severity(text)
        assert severity['level'] == expected_level

    @pytest.mark.parametrize("text,expected_level", [
        ("@ops 14:23: delayed settlement on CRO withdrawals", "medium"),
        ("@ops 14:23: sync lag on ethereum node", "medium"),
        ("@ops 14:23: chain reorg detected, 2 blocks deep", "medium"),
        ("@ops 14:23: pending transactions backing up", "medium"),
        ("@ops 14:23: block delay on polygon", "medium"),
    ])
    def test_crypto_medium_severity(self, text, expected_level):
        """Crypto-specific medium keywords should be detected"""
        severity = detect_severity(text)
        assert severity['level'] == expected_level


class TestCryptoActionKeywords:
    """Action detection for crypto/fintech-specific responses"""

    @pytest.mark.parametrize("text,expected_category", [
        ("@ops 14:23: halted trading on all pairs", "remediation"),
        ("@ops 14:23: paused withdrawals as precaution", "remediation"),
        ("@ops 14:23: disabled deposits pending investigation", "remediation"),
        ("@ops 14:23: froze affected accounts", "remediation"),
        ("@ops 14:23: circuit breaker triggered on matching engine", "remediation"),
    ])
    def test_crypto_remediation_actions(self, text, expected_category):
        """Crypto-specific remediation actions should be categorized"""
        actions = identify_actions(text)
        categories = [a['category'] for a in actions]
        assert expected_category in categories

    @pytest.mark.parametrize("text,expected_category", [
        ("@ops 14:23: tracing transaction on chain", "investigation"),
        ("@ops 14:23: checking chain for double spend", "investigation"),
        ("@ops 14:23: reviewing ledger entries", "investigation"),
        ("@ops 14:23: auditing wallet balances", "investigation"),
    ])
    def test_crypto_investigation_actions(self, text, expected_category):
        """Crypto-specific investigation actions should be categorized"""
        actions = identify_actions(text)
        categories = [a['category'] for a in actions]
        assert expected_category in categories


class TestCryptoServiceDetection:
    """Entity extraction for crypto/fintech infrastructure"""

    @pytest.mark.parametrize("text,expected_service", [
        ("hot-wallet unreachable", "hot-wallet"),
        ("matching-engine latency spike", "matching-engine"),
        ("order-book sync failed", "order-book"),
        ("price-oracle returning stale data", "price-oracle"),
        ("custody-vault offline", "custody-vault"),
        ("eth-bridge unresponsive", "eth-bridge"),
    ])
    def test_crypto_services_detected(self, text, expected_service):
        """Crypto infrastructure names should be recognized as services"""
        entities = extract_entities(text)
        assert expected_service in entities['services']


class TestCryptoIntegration:
    """End-to-end test with a realistic crypto incident"""

    def test_crypto_incident_full_extraction(self):
        """Full extraction from a realistic crypto exchange incident"""
        text = dedent("""
            2024-11-20T09:15:00Z sarah.chen: price-oracle returning stale ETH prices, last update 10 min ago
            2024-11-20T09:16:30Z james.rodriguez: confirmed oracle failure, price feed frozen
            2024-11-20T09:17:00Z alex.kim: halted trading on ETH pairs as precaution
            2024-11-20T09:18:00Z sarah.chen: checking chain - ethereum node sync lag detected
            2024-11-20T09:22:00Z james.rodriguez: disabled deposits for ETH pending fix
            2024-11-20T09:35:00Z alex.kim: oracle provider switched to backup feed
            2024-11-20T09:40:00Z sarah.chen: prices updating again, reviewing ledger for bad fills
            2024-11-20T09:45:00Z james.rodriguez: no bad fills found, re-enabling trading
            2024-11-20T09:50:00Z alex.kim: trading resumed, deposits re-enabled, monitoring
        """).strip()

        summary = generate_summary(text)

        # Should detect high severity (oracle failure, price feed)
        assert summary['severity']['level'] == 'high'

        # Should extract crypto services
        services = summary['entities']['services']
        assert 'price-oracle' in services

        # Should find crypto-specific actions
        action_categories = [a['category'] for a in summary['actions']]
        assert 'remediation' in action_categories
        assert 'investigation' in action_categories

        # Should have 3 responders
        assert summary['metrics']['num_responders'] == 3

        # Should have duration (~35 min)
        assert summary['metrics']['duration'] == '35m'

        # Events should be sorted and have timestamps
        tl = summary['timeline']
        assert len(tl) == 9
        assert all('timestamp' in e for e in tl)


# ── Marketplace / platform keyword tests ──────────────────────────────

class TestPlatformSeverityKeywords:
    """Severity detection for marketplace/platform-specific incidents"""

    @pytest.mark.parametrize("text,expected_level", [
        ("@ops 14:23: dispatch down, no trips being matched", "critical"),
        ("@ops 14:23: matching failed across all regions", "critical"),
        ("@ops 14:23: trips affected for 50k users", "critical"),
        ("@ops 14:23: orders stuck in fulfillment pipeline", "critical"),
        ("@ops 14:23: fulfillment halted, orders backing up", "critical"),
    ])
    def test_platform_critical_severity(self, text, expected_level):
        """Platform-specific critical keywords should be detected"""
        severity = detect_severity(text)
        assert severity['level'] == expected_level

    @pytest.mark.parametrize("text,expected_level", [
        ("@ops 14:23: dispatch latency at 30s, normally 2s", "high"),
        ("@ops 14:23: routing errors for 10% of requests", "high"),
        ("@ops 14:23: eta degraded, showing wrong estimates", "high"),
        ("@ops 14:23: demand spike in downtown, no supply", "high"),
        ("@ops 14:23: supply shortage in three regions", "high"),
    ])
    def test_platform_high_severity(self, text, expected_level):
        """Platform-specific high keywords should be detected"""
        severity = detect_severity(text)
        assert severity['level'] == expected_level

    @pytest.mark.parametrize("text,expected_level", [
        ("@ops 14:23: eta inaccurate by 5-10 minutes", "medium"),
        ("@ops 14:23: delayed dispatch in low-priority queue", "medium"),
        ("@ops 14:23: routing fallback to secondary provider", "medium"),
    ])
    def test_platform_medium_severity(self, text, expected_level):
        """Platform-specific medium keywords should be detected"""
        severity = detect_severity(text)
        assert severity['level'] == expected_level


class TestPlatformActionKeywords:
    """Action detection for large-scale platform operations"""

    @pytest.mark.parametrize("text,expected_category", [
        ("@ops 14:23: rerouting traffic to us-east-2", "remediation"),
        ("@ops 14:23: load shedding non-critical endpoints", "remediation"),
        ("@ops 14:23: rate limiting external API calls", "remediation"),
        ("@ops 14:23: throttling batch jobs to free capacity", "remediation"),
        ("@ops 14:23: failover to secondary datacenter", "remediation"),
        ("@ops 14:23: draining traffic from unhealthy nodes", "remediation"),
    ])
    def test_platform_remediation_actions(self, text, expected_category):
        """Platform-specific remediation actions should be categorized"""
        actions = identify_actions(text)
        categories = [a['category'] for a in actions]
        assert expected_category in categories

    @pytest.mark.parametrize("text,expected_category", [
        ("@ops 14:23: tracing requests through dispatch pipeline", "investigation"),
        ("@ops 14:23: profiling matching-engine latency", "investigation"),
    ])
    def test_platform_investigation_actions(self, text, expected_category):
        """Platform-specific investigation actions should be categorized"""
        actions = identify_actions(text)
        categories = [a['category'] for a in actions]
        assert expected_category in categories


class TestPlatformServiceDetection:
    """Entity extraction for marketplace/platform infrastructure"""

    @pytest.mark.parametrize("text,expected_service", [
        ("trip-dispatch unresponsive", "trip-dispatch"),
        ("ride-matcher latency spike", "ride-matcher"),
        ("surge-pricing returning errors", "surge-pricing"),
        ("order-fulfillment queue backed up", "order-fulfillment"),
        ("geo-routing falling back to defaults", "geo-routing"),
        ("trip-scheduler not assigning jobs", "trip-scheduler"),
        ("us-east-shard responding slowly", "us-east-shard"),
        ("api-ingress dropping connections", "api-ingress"),
    ])
    def test_platform_services_detected(self, text, expected_service):
        """Platform infrastructure names should be recognized as services"""
        entities = extract_entities(text)
        assert expected_service in entities['services']


class TestPlatformIntegration:
    """End-to-end test with a realistic marketplace platform incident"""

    def test_dispatch_incident_full_extraction(self):
        """Full extraction from a realistic dispatch/matching incident"""
        text = dedent("""
            2024-11-20T15:00:00Z sarah.chen: trip-dispatch latency spiking, dispatch latency at 30s
            2024-11-20T15:02:00Z james.rodriguez: confirmed routing errors in us-east, tracing requests
            2024-11-20T15:04:00Z alex.kim: load shedding non-critical endpoints to free capacity
            2024-11-20T15:06:00Z sarah.chen: root cause: us-east-shard overloaded after config push
            2024-11-20T15:08:00Z james.rodriguez: rerouting traffic to us-west, draining us-east
            2024-11-20T15:15:00Z alex.kim: failover complete, dispatch latency recovering
            2024-11-20T15:20:00Z sarah.chen: latency back to normal, monitoring
            2024-11-20T15:30:00Z james.rodriguez: us-east shard rebalanced, rerouting traffic back
            2024-11-20T15:35:00Z alex.kim: all regions healthy, resolved
        """).strip()

        summary = generate_summary(text)

        # Should detect high severity (dispatch latency, routing errors)
        assert summary['severity']['level'] == 'high'

        # Should extract platform services
        services = summary['entities']['services']
        assert 'trip-dispatch' in services

        # Should find platform-specific actions
        action_categories = [a['category'] for a in summary['actions']]
        assert 'remediation' in action_categories
        assert 'investigation' in action_categories

        # Should have 3 responders
        assert summary['metrics']['num_responders'] == 3

        # Should have duration (35 min)
        assert summary['metrics']['duration'] == '35m'

        # Events should be sorted and have timestamps
        timeline = summary['timeline']
        assert len(timeline) == 9
        assert all('timestamp' in e for e in timeline)


# ============================================================
# _analyze_timeline — split pipeline tests
# ============================================================

class TestAnalyzeTimeline:
    """Tests for _analyze_timeline with pre-built events."""

    def test_preserves_trusted_actors(self):
        """Pre-built events with actors should keep those actors in output."""
        events = [
            {'time': '14:23', 'text': 'Seeing elevated errors on checkout-service',
             'timestamp': '1970-01-01T14:23:00', 'actor': 'carol.dev'},
            {'time': '14:25', 'text': 'Rollback deployed to production',
             'timestamp': '1970-01-01T14:25:00', 'actor': 'bob.io'},
        ]
        text = "carol.dev: Seeing elevated errors on checkout-service\nbob.io: Rollback deployed to production"
        result = _analyze_timeline(events, text)
        # Actors from pre-built events are preserved, not re-extracted
        assert result['timeline'][0]['actor'] == 'carol.dev'
        assert result['timeline'][1]['actor'] == 'bob.io'

    def test_responder_count_from_events(self):
        """num_responders should use actors from pre-built events."""
        events = [
            {'time': '14:23', 'text': 'Investigating errors',
             'timestamp': '1970-01-01T14:23:00', 'actor': 'carol.dev'},
            {'time': '14:25', 'text': 'Deployed rollback',
             'timestamp': '1970-01-01T14:25:00', 'actor': 'bob.io'},
        ]
        text = "Investigating errors\nDeployed rollback"
        result = _analyze_timeline(events, text)
        assert result['metrics']['num_responders'] == 2

    def test_actions_extracted_from_text(self):
        """Actions should still be extracted from the text parameter."""
        events = [
            {'time': '14:23', 'text': 'Investigating',
             'timestamp': '1970-01-01T14:23:00', 'actor': 'sarah'},
        ]
        text = "@sarah 14:23: Investigating the checkout-service outage"
        result = _analyze_timeline(events, text)
        assert len(result['actions']) > 0

    def test_entities_extracted_from_text(self):
        """Entities should be extracted from the text parameter."""
        events = [
            {'time': '14:23', 'text': 'checkout-service is down',
             'timestamp': '1970-01-01T14:23:00', 'actor': 'sarah'},
        ]
        text = "@sarah 14:23: checkout-service at 10.0.0.1 is down"
        result = _analyze_timeline(events, text)
        assert 'checkout-service' in result['entities']['services']
        assert '10.0.0.1' in result['entities']['ips']

    def test_ir_phases_classified(self):
        """Events should get ir_phase classifications."""
        events = [
            {'time': '14:23', 'text': 'Seeing elevated errors',
             'timestamp': '1970-01-01T14:23:00', 'actor': 'sarah'},
            {'time': '14:30', 'text': 'Rolling back deployment',
             'timestamp': '1970-01-01T14:30:00', 'actor': 'bob'},
        ]
        text = "14:23 sarah: Seeing elevated errors\n14:30 bob: Rolling back deployment"
        result = _analyze_timeline(events, text)
        assert result['timeline'][0].get('ir_phase')
        assert result['ir_phases']

    def test_backward_compatible_with_generate_summary(self):
        """_analyze_timeline should produce same keys as generate_summary."""
        text = dedent("""
            @sarah 14:23: Seeing elevated errors on checkout-service
            @bob 14:25: Rolling back the deployment
            @sarah 14:30: Metrics returning to normal
        """).strip()
        old_result = generate_summary(text)
        new_events = extract_timeline(text)
        new_result = _analyze_timeline(new_events, text)
        assert set(old_result.keys()) == set(new_result.keys())


# ============================================================
# Phase 3 — IR framework mapping tests
# ============================================================

class TestClassifyIRPhase:
    """Tests for _classify_ir_phase per-event classifier."""

    def test_detection_by_keyword(self):
        """Should classify detection keywords"""
        result = _classify_ir_phase(
            "Alert fired on payment-service", 0, 10, False)
        assert result['ir_phase'] == 'detection'

    def test_analysis_by_keyword(self):
        """Should classify analysis keywords"""
        result = _classify_ir_phase(
            "Investigating root cause of latency spike", 2, 10, False)
        assert result['ir_phase'] == 'analysis'

    def test_containment_by_keyword(self):
        """Should classify containment keywords"""
        result = _classify_ir_phase(
            "Rolling back deployment to v2.14.3", 5, 10, False)
        assert result['ir_phase'] == 'containment'

    def test_eradication_by_keyword(self):
        """Should classify eradication after containment seen"""
        result = _classify_ir_phase(
            "PR ready with proper index fix", 7, 10, True)
        assert result['ir_phase'] == 'eradication'

    def test_recovery_by_keyword(self):
        """Should classify recovery keywords"""
        result = _classify_ir_phase(
            "All metrics stable, back to normal", 8, 10, True)
        assert result['ir_phase'] == 'recovery'

    def test_post_incident_by_keyword(self):
        """Should classify post-incident keywords"""
        result = _classify_ir_phase(
            "Postmortem scheduled for tomorrow", 9, 10, True)
        assert result['ir_phase'] == 'post_incident'

    def test_early_monitoring_is_analysis_not_recovery(self):
        """'stable'/'monitoring' early in timeline → analysis, not recovery"""
        result = _classify_ir_phase(
            "Metrics stable for now, monitoring closely", 1, 10, False)
        assert result['ir_phase'] == 'analysis'

    def test_late_monitoring_is_recovery(self):
        """'stable'/'monitoring' late in timeline → recovery"""
        result = _classify_ir_phase(
            "Metrics stable, back to normal", 8, 10, True)
        assert result['ir_phase'] == 'recovery'

    def test_eradication_before_containment_becomes_containment(self):
        """Eradication keywords before containment_seen → containment"""
        result = _classify_ir_phase(
            "Fix deployed to mitigate impact", 3, 10, False)
        assert result['ir_phase'] == 'containment'

    def test_discussion_downgrades_containment(self):
        """Discussion of rollback → analysis, not containment"""
        result = _classify_ir_phase(
            "I vote rollback while we add the index", 4, 10, False)
        assert result['ir_phase'] == 'analysis'

    def test_no_keyword_early_position_detection(self):
        """No keyword + early position → detection with low confidence"""
        result = _classify_ir_phase(
            "Something is happening with the service", 0, 10, False)
        assert result['ir_phase'] == 'detection'
        assert result['phase_confidence'] == 'low'

    def test_no_keyword_late_position_recovery_or_post(self):
        """No keyword + late position → post_incident with low confidence"""
        result = _classify_ir_phase(
            "Calendar invite sent", 9, 10, True)
        assert result['ir_phase'] == 'post_incident'
        assert result['phase_confidence'] == 'low'

    def test_keyword_match_high_confidence(self):
        """Keyword + expected position → high confidence"""
        result = _classify_ir_phase(
            "Alert fired on the service", 0, 10, False)
        assert result['phase_confidence'] == 'high'

    def test_keyword_match_unexpected_position_medium(self):
        """Keyword + unexpected position → medium confidence"""
        # detection keyword very late in timeline
        result = _classify_ir_phase(
            "Another alert fired", 9, 10, True)
        assert result['phase_confidence'] == 'medium'

    def test_empty_line(self):
        """Should handle empty line gracefully"""
        result = _classify_ir_phase("", 0, 1, False)
        assert 'ir_phase' in result
        assert 'phase_confidence' in result


class TestClassifyTimelinePhases:
    """Tests for _classify_timeline_phases orchestrator."""

    def test_simple_progression(self):
        """Should classify a simple 6-event incident with correct phases"""
        events = [
            {'text': 'Alert fired on service', 'time': '14:23'},
            {'text': 'Investigating the root cause', 'time': '14:24'},
            {'text': 'Rolling back the deployment', 'time': '14:27'},
            {'text': 'Fix deployed with proper index', 'time': '14:35'},
            {'text': 'Metrics stable, back to normal', 'time': '14:40'},
            {'text': 'Postmortem scheduled for tomorrow', 'time': '14:45'},
        ]
        result = _classify_timeline_phases(events)

        assert result[0]['ir_phase'] == 'detection'
        assert result[1]['ir_phase'] == 'analysis'
        assert result[2]['ir_phase'] == 'containment'
        # After containment, eradication keywords → eradication
        assert result[3]['ir_phase'] == 'eradication'
        assert result[4]['ir_phase'] == 'recovery'
        assert result[5]['ir_phase'] == 'post_incident'

    def test_adds_fields_to_events(self):
        """Should add ir_phase and phase_confidence to event dicts"""
        events = [
            {'text': 'Alert fired on service', 'time': '14:23'},
        ]
        _classify_timeline_phases(events)
        assert 'ir_phase' in events[0]
        assert 'phase_confidence' in events[0]

    def test_empty_input(self):
        """Should handle empty list"""
        result = _classify_timeline_phases([])
        assert result == []

    def test_containment_seen_propagates(self):
        """After containment event, eradication keywords should map to eradication"""
        events = [
            {'text': 'Seeing elevated errors', 'time': '14:23'},
            {'text': 'Rolling back deploy', 'time': '14:30'},
            {'text': 'PR ready with fix', 'time': '14:45'},
        ]
        _classify_timeline_phases(events)
        assert events[1]['ir_phase'] == 'containment'
        assert events[2]['ir_phase'] == 'eradication'


class TestGroupByPhase:
    """Tests for _group_by_phase."""

    def test_groups_events_correctly(self):
        """Should group events into correct phase buckets"""
        events = [
            {'text': 'e1', 'ir_phase': 'detection'},
            {'text': 'e2', 'ir_phase': 'analysis'},
            {'text': 'e3', 'ir_phase': 'analysis'},
            {'text': 'e4', 'ir_phase': 'containment'},
            {'text': 'e5', 'ir_phase': 'recovery'},
        ]
        groups = _group_by_phase(events)
        assert len(groups['detection']) == 1
        assert len(groups['analysis']) == 2
        assert len(groups['containment']) == 1
        assert len(groups['recovery']) == 1
        assert 'eradication' not in groups
        assert 'post_incident' not in groups

    def test_canonical_order(self):
        """Groups should be in NIST canonical order"""
        events = [
            {'text': 'e1', 'ir_phase': 'recovery'},
            {'text': 'e2', 'ir_phase': 'detection'},
            {'text': 'e3', 'ir_phase': 'containment'},
        ]
        groups = _group_by_phase(events)
        phases = list(groups.keys())
        assert phases == ['detection', 'containment', 'recovery']

    def test_empty_input(self):
        """Should handle empty list"""
        assert _group_by_phase([]) == {}


class TestComputeMetricsPhase3:
    """Tests for TTD/TTC in _compute_metrics."""

    def test_ttc_computed(self):
        """Should compute time to contain from first event to first containment"""
        timeline = [
            {'text': 'Alert fired', 'timestamp': '1970-01-01T14:23:00',
             'ir_phase': 'detection'},
            {'text': 'Investigating', 'timestamp': '1970-01-01T14:25:00',
             'ir_phase': 'analysis'},
            {'text': 'Rolling back', 'timestamp': '1970-01-01T14:30:00',
             'ir_phase': 'containment'},
        ]
        metrics = _compute_metrics(timeline, [])
        assert metrics['time_to_contain'] == '7m'

    def test_ttd_zero_when_first_event_is_detection(self):
        """TTD = 0m when first event is already detection"""
        timeline = [
            {'text': 'Alert fired on service', 'timestamp': '1970-01-01T14:23:00',
             'ir_phase': 'detection'},
            {'text': 'Investigating', 'timestamp': '1970-01-01T14:25:00',
             'ir_phase': 'analysis'},
        ]
        metrics = _compute_metrics(timeline, [])
        assert metrics['time_to_detect'] == '0m'

    def test_no_ttc_without_containment(self):
        """Should not have TTC without containment events"""
        timeline = [
            {'text': 'Alert fired', 'timestamp': '1970-01-01T14:23:00',
             'ir_phase': 'detection'},
            {'text': 'Investigating', 'timestamp': '1970-01-01T14:25:00',
             'ir_phase': 'analysis'},
        ]
        metrics = _compute_metrics(timeline, [])
        assert 'time_to_contain' not in metrics

    def test_backward_compatible_no_phases(self):
        """Without ir_phase, no TTD/TTC should be computed"""
        timeline = [
            {'text': 'event 1', 'timestamp': '1970-01-01T14:23:00'},
            {'text': 'event 2', 'timestamp': '1970-01-01T14:25:00'},
        ]
        metrics = _compute_metrics(timeline, [])
        assert 'time_to_detect' not in metrics
        assert 'time_to_contain' not in metrics


class TestMapToFramework:
    """Tests for map_to_framework public function."""

    def test_returns_expected_structure(self):
        """Should return dict with all expected keys"""
        text = dedent("""
            @sarah 14:23: Alert fired on payment-service
            @mike 14:25: Investigating root cause
            @sarah 14:30: Rolling back deployment
            @mike 14:35: Metrics stable, back to normal
        """).strip()
        result = map_to_framework(text)
        assert 'framework' in result
        assert 'timeline' in result
        assert 'phases' in result
        assert 'phase_summary' in result
        assert 'metrics' in result
        assert result['framework'] == 'nist_800_61'

    def test_timeline_has_phase_fields(self):
        """Timeline events should have ir_phase and phase_confidence"""
        text = "@sarah 14:23: Alert fired on service"
        result = map_to_framework(text)
        assert len(result['timeline']) == 1
        assert 'ir_phase' in result['timeline'][0]
        assert 'phase_confidence' in result['timeline'][0]

    def test_phase_summary_string(self):
        """Should produce a readable phase summary"""
        text = dedent("""
            @sarah 14:23: Alert fired on payment-service
            @mike 14:25: Investigating root cause
            @sarah 14:30: Rolling back deployment
            @mike 14:35: Back to normal, metrics stable
        """).strip()
        result = map_to_framework(text)
        assert 'Detection' in result['phase_summary']
        assert '->' in result['phase_summary']

    def test_empty_input(self):
        """Should handle empty input"""
        result = map_to_framework("")
        assert result['timeline'] == []
        assert result['phases'] == {}
        assert result['phase_summary'] == ''


class TestGenerateSummaryPhase3:
    """Tests for generate_summary with IR phase integration."""

    def test_summary_includes_ir_phases(self):
        """Summary should include ir_phases dict"""
        text = dedent("""
            @sarah 14:23: Alert fired on payment-service
            @mike 14:25: Investigating the issue
            @sarah 14:30: Rolling back deploy
            @mike 14:35: Back to normal
        """).strip()
        summary = generate_summary(text)
        assert 'ir_phases' in summary
        assert isinstance(summary['ir_phases'], dict)

    def test_summary_text_includes_phase_progression(self):
        """Summary text should mention IR phases"""
        text = dedent("""
            @sarah 14:23: Alert fired on payment-service
            @mike 14:25: Investigating the issue
            @sarah 14:30: Rolling back deploy
            @mike 14:35: Back to normal
        """).strip()
        summary = generate_summary(text)
        assert 'IR Phases' in summary['summary_text']

    def test_summary_text_includes_ttc(self):
        """Summary text should include time to contain when available"""
        text = dedent("""
            @sarah 14:23: Alert fired on payment-service
            @mike 14:25: Investigating the issue
            @sarah 14:30: Rolling back deploy
            @mike 14:35: Back to normal
        """).strip()
        summary = generate_summary(text)
        assert 'Time to contain' in summary['summary_text']


class TestIRPhaseIntegration:
    """End-to-end test with realistic incident."""

    def test_realistic_incident_phase_progression(self):
        """Realistic incident should produce reasonable phase mapping"""
        text = dedent("""
            2024-10-15T14:23:15Z sarah.chen: Seeing elevated response times on checkout-db-primary. Starting incident investigation.
            2024-10-15T14:23:47Z james.rodriguez: Taking IC role. Declared SEV-2.
            2024-10-15T14:24:12Z alex.kim: Checking support queue now.
            2024-10-15T14:25:03Z sarah.chen: Database CPU at 94%. Looking at slow query log.
            2024-10-15T14:27:01Z sarah.chen: Found it! Query hitting orders table without index.
            2024-10-15T14:28:45Z james.rodriguez: What are our options for immediate mitigation?
            2024-10-15T14:30:15Z james.rodriguez: Agreed. Start rollback.
            2024-10-15T14:30:42Z david.park: Rollback initiated. ETA 3 minutes.
            2024-10-15T14:31:05Z sarah.chen: Setting rate limit on dashboard endpoint.
            2024-10-15T14:33:48Z david.park: Rollback complete.
            2024-10-15T14:34:20Z sarah.chen: Query count dropped. CPU back to 23%. Metrics stable.
            2024-10-15T14:35:01Z james.rodriguez: Rollback complete. Metrics returning to normal.
            2024-10-15T14:55:30Z sarah.chen: 30 min mark. All metrics stable.
            2024-10-15T14:56:15Z james.rodriguez: INCIDENT RESOLVED. Action items assigned. Post-incident review scheduled for tomorrow.
            2024-10-15T15:12:45Z david.park: PR ready for review. Added proper index.
            2024-10-15T15:45:22Z david.park: Load test passed!
            2024-10-15T16:45:12Z james.rodriguez: Incident report published. Post-incident review tomorrow.
        """).strip()

        result = map_to_framework(text)

        # Should have phases in correct NIST order
        phase_names = list(result['phases'].keys())
        assert 'detection' in phase_names
        assert 'analysis' in phase_names
        assert 'containment' in phase_names

        # TTD should be 0m (first event is detection)
        assert result['metrics'].get('time_to_detect') == '0m'

        # TTC should be ~7m (14:23 → 14:30)
        ttc = result['metrics'].get('time_to_contain')
        assert ttc is not None
        # Extract minutes for range check
        ttc_min = int(ttc.replace('m', ''))
        assert 6 <= ttc_min <= 8

        # Phase summary should be non-empty
        assert 'Detection' in result['phase_summary']
        assert '->' in result['phase_summary']

    def test_generate_summary_with_phases(self):
        """generate_summary should include phase data for realistic input"""
        text = dedent("""
            @sarah 14:23: Seeing elevated errors on payment-service
            @mike 14:25: Investigating the database
            @sarah 14:27: Rolling back deploy
            @mike 14:30: Rollback complete, metrics stable
            @sarah 14:35: All clear, back to normal
            @mike 14:40: Postmortem scheduled for tomorrow
        """).strip()

        summary = generate_summary(text)

        assert 'ir_phases' in summary
        assert len(summary['ir_phases']) >= 3
        assert 'IR Phases' in summary['summary_text']