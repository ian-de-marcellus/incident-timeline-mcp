"""
Tests for extraction logic in extractors.py
"""

import pytest
from textwrap import dedent
from extractors import extract_timeline, _find_timestamp, _find_actor, identify_actions, extract_entities, _is_valid_ip, _is_likely_domain, detect_severity, generate_summary


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