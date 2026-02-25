"""
Tests for LLM enrichment (Phase 6).

All enrichment functions are pure — tests pass a mock client directly.
No module globals, no monkeypatching, no conftest fixtures needed.
"""

import pytest
from unittest.mock import patch, MagicMock

from llm.enrichment import (
    enrich_ir_phases,
    enrich_severity,
    enrich_actions,
    enrich_entities,
    enrich_timeline,
    _call_haiku,
)


# ── Test helpers ─────────────────────────────────────────────────────

def _make_tool_use_block(name, input_data):
    """Create a mock tool_use content block."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_data
    return block


def _make_text_block(text="OK"):
    """Create a mock text content block."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_response(*blocks):
    """Create a mock API response with content blocks."""
    response = MagicMock()
    response.content = list(blocks)
    return response


MODEL = "test-model"


# ── TestSettings ─────────────────────────────────────────────────────

class TestSettings:
    """Test config.py Settings class."""

    def test_default_values(self):
        """Settings should have safe defaults (no API key, enrichment off)."""
        with patch.dict('os.environ', {}, clear=True):
            from config import Settings
            s = Settings(_env_file=None)
            assert s.anthropic_api_key == ""
            assert s.llm_enrichment == "none"

    def test_env_override(self):
        """Settings should read from environment variables."""
        env = {
            'ANTHROPIC_API_KEY': 'sk-ant-test123',
            'LLM_ENRICHMENT': 'regular',
        }
        with patch.dict('os.environ', env, clear=True):
            from config import Settings
            s = Settings(_env_file=None)
            assert s.anthropic_api_key == 'sk-ant-test123'
            assert s.llm_enrichment == 'regular'

    def test_enrichment_level_low(self):
        """Low enrichment level should be accepted."""
        env = {'LLM_ENRICHMENT': 'low', 'ANTHROPIC_API_KEY': 'sk-test'}
        with patch.dict('os.environ', env, clear=True):
            from config import Settings
            s = Settings(_env_file=None)
            assert s.llm_enrichment == 'low'

    def test_enrichment_level_none(self):
        """None enrichment level is the default."""
        with patch.dict('os.environ', {}, clear=True):
            from config import Settings
            s = Settings(_env_file=None)
            assert s.llm_enrichment == 'none'


# ── TestCallHaiku ────────────────────────────────────────────────────

class TestCallHaiku:
    """Test _call_haiku() API wrapper."""

    def test_success(self):
        """Should return tool input on successful API call."""
        tool_input = {"classifications": [{"event_number": 0, "phase": "detection", "reasoning": "test"}]}
        response = _make_response(_make_tool_use_block("classify_phases", tool_input))

        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        from llm.prompts import IR_PHASE_TOOL
        result = _call_haiku(mock_client, MODEL, "system", "user", IR_PHASE_TOOL, "classify_phases")
        assert result == tool_input

    def test_api_exception(self):
        """Should return None on API exception."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")

        from llm.prompts import IR_PHASE_TOOL
        result = _call_haiku(mock_client, MODEL, "system", "user", IR_PHASE_TOOL, "classify_phases")
        assert result is None

    def test_no_tool_use_block(self):
        """Should return None when response has no tool_use block."""
        response = _make_response(_make_text_block("I can't do that"))

        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        from llm.prompts import IR_PHASE_TOOL
        result = _call_haiku(mock_client, MODEL, "system", "user", IR_PHASE_TOOL, "classify_phases")
        assert result is None

    def test_wrong_tool_name(self):
        """Should return None when tool_use block has wrong name."""
        response = _make_response(_make_tool_use_block("wrong_tool", {}))

        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        from llm.prompts import IR_PHASE_TOOL
        result = _call_haiku(mock_client, MODEL, "system", "user", IR_PHASE_TOOL, "classify_phases")
        assert result is None


# ── TestEnrichIRPhases ───────────────────────────────────────────────

class TestEnrichIRPhases:
    """Test enrich_ir_phases() function."""

    def test_skip_when_no_low_confidence(self):
        """Should return None when no events have low confidence."""
        events = [
            {'text': 'Alert fired', 'time': '14:00', 'ir_phase': 'detection', 'phase_confidence': 'high'},
            {'text': 'Investigating', 'time': '14:05', 'ir_phase': 'analysis', 'phase_confidence': 'medium'},
        ]
        result = enrich_ir_phases(events, MagicMock(), MODEL)
        assert result is None

    def test_correct_index_mapping(self):
        """Should map LLM classifications back to correct event indices."""
        events = [
            {'text': 'Alert fired', 'time': '14:00', 'ir_phase': 'detection', 'phase_confidence': 'high'},
            {'text': 'Checking logs', 'time': '14:05', 'ir_phase': 'analysis', 'phase_confidence': 'low'},
            {'text': 'Found issue', 'time': '14:10', 'ir_phase': 'analysis', 'phase_confidence': 'high'},
        ]

        tool_input = {
            "classifications": [
                {"event_number": 1, "phase": "containment", "reasoning": "Taking action"},
            ]
        }
        response = _make_response(_make_tool_use_block("classify_phases", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = enrich_ir_phases(events, mock_client, MODEL)
        assert result is not None
        assert len(result) == 1
        assert result[0]['event_index'] == 1
        assert result[0]['ir_phase'] == 'containment'
        assert result[0]['phase_confidence'] == 'medium'

    def test_api_failure_returns_none(self):
        """Should return None when API call fails."""
        events = [
            {'text': 'Something', 'time': '14:00', 'ir_phase': 'analysis', 'phase_confidence': 'low'},
        ]

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")

        result = enrich_ir_phases(events, mock_client, MODEL)
        assert result is None

    def test_invalid_phase_filtered(self):
        """Should filter out invalid phase names from LLM response."""
        events = [
            {'text': 'Something', 'time': '14:00', 'ir_phase': 'analysis', 'phase_confidence': 'low'},
        ]

        tool_input = {
            "classifications": [
                {"event_number": 0, "phase": "invalid_phase", "reasoning": "Bad"},
            ]
        }
        response = _make_response(_make_tool_use_block("classify_phases", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = enrich_ir_phases(events, mock_client, MODEL)
        assert result is None

    def test_irrelevant_phase_accepted(self):
        """Should accept 'irrelevant' as a valid phase from LLM."""
        events = [
            {'text': 'Happy Monday everyone', 'time': '09:00', 'ir_phase': 'detection', 'phase_confidence': 'low'},
            {'text': 'Alert fired on payment-api', 'time': '14:00', 'ir_phase': 'detection', 'phase_confidence': 'high'},
        ]

        tool_input = {
            "classifications": [
                {"event_number": 0, "phase": "irrelevant", "reasoning": "Social greeting"},
            ]
        }
        response = _make_response(_make_tool_use_block("classify_phases", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = enrich_ir_phases(events, mock_client, MODEL)
        assert result is not None
        assert len(result) == 1
        assert result[0]['ir_phase'] == 'irrelevant'

    def test_batching_large_set(self):
        """Should batch events into groups of 10."""
        events = [
            {'text': f'Event {i}', 'time': f'14:{i:02d}',
             'ir_phase': 'analysis', 'phase_confidence': 'low'}
            for i in range(15)
        ]

        call_count = [0]
        def side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                tool_input = {
                    "classifications": [
                        {"event_number": 0, "phase": "detection", "reasoning": "First"}
                    ]
                }
                return _make_response(_make_tool_use_block("classify_phases", tool_input))
            else:
                tool_input = {"classifications": []}
                return _make_response(_make_tool_use_block("classify_phases", tool_input))

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = side_effect

        result = enrich_ir_phases(events, mock_client, MODEL)
        assert call_count[0] == 2  # Two batches
        assert result is not None
        assert len(result) == 1


# ── TestEnrichSeverity ───────────────────────────────────────────────

class TestEnrichSeverity:
    """Test enrich_severity() function."""

    def test_skip_when_confident(self):
        """Should return None when severity is already confident."""
        severity = {'level': 'high', 'confidence': 'high', 'indicators': ['error rate']}
        result = enrich_severity("some text", severity, MagicMock(), MODEL)
        assert result is None

    def test_enriches_unknown_level(self):
        """Should enrich when level is 'unknown'."""
        severity = {'level': 'unknown', 'confidence': 'low', 'indicators': []}

        tool_input = {
            "level": "high",
            "confidence": "medium",
            "indicators": ["elevated errors", "degraded"],
            "reasoning": "Multiple error signals",
        }
        response = _make_response(_make_tool_use_block("assess_severity", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = enrich_severity("error text here", severity, mock_client, MODEL)
        assert result is not None
        assert result['level'] == 'high'
        assert result['confidence'] == 'medium'

    def test_enriches_low_confidence(self):
        """Should enrich when confidence is 'low' even if level is known."""
        severity = {'level': 'medium', 'confidence': 'low', 'indicators': ['intermittent']}

        tool_input = {
            "level": "high",
            "confidence": "high",
            "indicators": ["degraded", "timeout"],
            "reasoning": "Widespread impact",
        }
        response = _make_response(_make_tool_use_block("assess_severity", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = enrich_severity("degraded service with timeouts", severity, mock_client, MODEL)
        assert result is not None
        assert result['level'] == 'high'

    def test_text_truncation(self):
        """Should truncate long text to 2000 chars."""
        severity = {'level': 'unknown', 'confidence': 'low', 'indicators': []}
        long_text = "x" * 5000

        tool_input = {
            "level": "low",
            "confidence": "low",
            "indicators": [],
            "reasoning": "Minimal info",
        }
        response = _make_response(_make_tool_use_block("assess_severity", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        enrich_severity(long_text, severity, mock_client, MODEL)
        # Verify the user content was truncated
        call_args = mock_client.messages.create.call_args
        user_msg = call_args.kwargs['messages'][0]['content']
        assert len(user_msg) == 2000


# ── TestEnrichActions ────────────────────────────────────────────────

class TestEnrichActions:
    """Test enrich_actions() function."""

    def test_skip_when_all_have_actions(self):
        """Should return None when all events have corresponding actions."""
        events = [
            {'text': 'Deployed fix', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00'},
        ]
        actions = [
            {'action': 'deployed', 'category': 'remediation', 'context': 'Deployed fix'},
        ]
        result = enrich_actions(events, actions, MagicMock(), MODEL)
        assert result is None

    def test_extract_missed_actions(self):
        """Should find actions in events that regex missed."""
        events = [
            {'text': 'Deployed fix', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00'},
            {'text': 'Switched traffic to backup', 'time': '14:05', 'timestamp': '2024-01-01T14:05:00'},
        ]
        actions = [
            {'action': 'deployed', 'category': 'remediation', 'context': 'Deployed fix'},
        ]

        tool_input = {
            "actions": [
                {"line_number": 1, "action": "switched traffic", "category": "remediation"},
            ]
        }
        response = _make_response(_make_tool_use_block("identify_actions", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = enrich_actions(events, actions, mock_client, MODEL)
        assert result is not None
        assert len(result) == 1
        assert result[0]['action'] == 'switched traffic'
        assert result[0]['source'] == 'llm'

    def test_empty_response(self):
        """Should return None when LLM finds no actions."""
        events = [
            {'text': 'Just a note', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00'},
        ]
        actions = []

        tool_input = {"actions": []}
        response = _make_response(_make_tool_use_block("identify_actions", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = enrich_actions(events, actions, mock_client, MODEL)
        assert result is None

    def test_invalid_category_filtered(self):
        """Should filter actions with invalid categories."""
        events = [
            {'text': 'Did something', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00'},
        ]
        actions = []

        tool_input = {
            "actions": [
                {"line_number": 1, "action": "did", "category": "invalid_category"},
            ]
        }
        response = _make_response(_make_tool_use_block("identify_actions", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = enrich_actions(events, actions, mock_client, MODEL)
        assert result is None


# ── TestEnrichEntities ───────────────────────────────────────────────

class TestEnrichEntities:
    """Test enrich_entities() function."""

    def test_skip_when_no_suspects(self):
        """Should return None when no firstname.lastname domains found."""
        entities = {
            'services': ['payment-api'],
            'ips': ['10.0.0.1'],
            'domains': ['api.example.com'],
        }
        result = enrich_entities(entities, "some text", MagicMock(), MODEL)
        assert result is None

    def test_person_name_detected(self):
        """Should identify firstname.lastname as a person."""
        entities = {
            'services': [],
            'ips': [],
            'domains': ['sarah.chen'],
        }

        tool_input = {
            "disambiguated": [
                {"item": "sarah.chen", "entity_type": "person", "reasoning": "Name pattern"},
            ]
        }
        response = _make_response(_make_tool_use_block("disambiguate_entities", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = enrich_entities(entities, "sarah.chen reported the issue", mock_client, MODEL)
        assert result is not None
        assert result['disambiguated'][0]['entity_type'] == 'person'

    def test_real_domain_kept(self):
        """Should not flag actual domains as suspects (short TLD)."""
        entities = {
            'services': [],
            'ips': [],
            'domains': ['api.io', 'status.co'],  # Short TLDs, not suspected
        }
        result = enrich_entities(entities, "some text", MagicMock(), MODEL)
        assert result is None  # TLDs too short to be lastname

    def test_mixed_results(self):
        """Should handle mix of person names and actual domains."""
        entities = {
            'services': [],
            'ips': [],
            'domains': ['sarah.chen', 'mike.jones'],
        }

        tool_input = {
            "disambiguated": [
                {"item": "sarah.chen", "entity_type": "person", "reasoning": "Name"},
                {"item": "mike.jones", "entity_type": "person", "reasoning": "Name"},
            ]
        }
        response = _make_response(_make_tool_use_block("disambiguate_entities", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = enrich_entities(entities, "sarah.chen and mike.jones on call", mock_client, MODEL)
        assert result is not None
        assert len(result['disambiguated']) == 2


# ── TestEnrichTimeline (orchestrator) ────────────────────────────────

class TestEnrichTimeline:
    """Test enrich_timeline() orchestrator."""

    def _make_mock_client(self, return_value=None):
        mock = MagicMock()
        mock.messages.create.return_value = return_value
        return mock

    def test_all_passes_run_on_regular(self):
        """In 'regular' mode, all four passes should be attempted."""
        events = [
            {'text': 'Something', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00',
             'ir_phase': 'analysis', 'phase_confidence': 'low'},
        ]
        severity = {'level': 'unknown', 'confidence': 'low', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': ['sarah.chen']}

        # Client that returns None-equivalent (no tool_use block)
        response = _make_response(_make_text_block("no result"))
        mock_client = self._make_mock_client(response)

        result = enrich_timeline(
            events, "text", severity, actions, entities,
            client=mock_client, model=MODEL, level="regular",
        )
        # All four passes attempted — 4 API calls
        assert mock_client.messages.create.call_count == 4

    def test_partial_failure(self):
        """Should continue when some passes fail."""
        events = [
            {'text': 'Alert', 'time': '14:00', 'ir_phase': 'detection', 'phase_confidence': 'low'},
        ]
        severity = {'level': 'unknown', 'confidence': 'low', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': []}

        call_count = [0]
        def side_effect(**kwargs):
            call_count[0] += 1
            tool_name = kwargs.get('tool_choice', {}).get('name', '')
            if tool_name == 'classify_phases':
                raise Exception("Phase API down")
            elif tool_name == 'assess_severity':
                tool_input = {
                    "level": "high", "confidence": "medium",
                    "indicators": ["degraded"], "reasoning": "test",
                }
                return _make_response(_make_tool_use_block("assess_severity", tool_input))
            return _make_response(_make_text_block("no result"))

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = side_effect

        result = enrich_timeline(
            events, "text", severity, actions, entities,
            client=mock_client, model=MODEL, level="regular",
        )
        assert 'severity_update' in result
        assert 'phase_updates' not in result

    def test_nothing_needed(self):
        """Should return empty dict when all data is already high-confidence."""
        events = [
            {'text': 'Alert fired', 'time': '14:00', 'ir_phase': 'detection', 'phase_confidence': 'high'},
        ]
        severity = {'level': 'high', 'confidence': 'high', 'indicators': ['degraded']}
        actions = [{'action': 'detected', 'category': 'investigation', 'context': 'Alert fired'}]
        entities = {'services': ['auth-api'], 'ips': [], 'domains': []}

        mock_client = MagicMock()

        result = enrich_timeline(
            events, "text", severity, actions, entities,
            client=mock_client, model=MODEL, level="regular",
        )
        # No low-conf phases, severity already confident, all events have actions,
        # no suspicious domains — nothing to enrich
        assert result == {}
        assert mock_client.messages.create.call_count == 0


# ── TestPipelineIntegration ──────────────────────────────────────────

class TestPipelineIntegration:
    """Test _enrich / _apply_enrichment / _get_llm_client in extractors.py."""

    def test_without_llm(self):
        """Pipeline should work identically without LLM client."""
        from extractors import _analyze_timeline, extract_timeline
        text = "@sarah 14:23: Payment service showing elevated errors\n@mike 14:30: Investigating root cause"
        events = extract_timeline(text)
        result = _analyze_timeline(events, text)
        assert 'timeline' in result
        assert 'actions' in result
        assert 'severity' in result

    def test_analyze_timeline_no_client_skips_enrichment(self):
        """_analyze_timeline with no client should skip enrichment entirely."""
        from extractors import _analyze_timeline
        events = [
            {'text': 'Alert', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00Z'},
        ]
        result = _analyze_timeline(events, "Alert at 14:00")
        # No phase_source = 'llm' on any event
        for e in result['timeline']:
            assert e.get('phase_source') != 'llm'

    def test_analyze_timeline_with_client(self):
        """_analyze_timeline with a mock client should attempt enrichment."""
        from extractors import _analyze_timeline

        tool_input = {
            "classifications": [
                {"event_number": 0, "phase": "detection", "reasoning": "Alert"},
            ]
        }
        response = _make_response(_make_tool_use_block("classify_phases", tool_input))
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        events = [
            {'text': 'Something happened', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00Z'},
        ]
        result = _analyze_timeline(events, "Something happened", client=mock_client, level='low')
        # Client was used
        assert mock_client.messages.create.called

    def test_apply_enrichment_phases(self):
        """_apply_enrichment should update event phases from LLM results."""
        from extractors import _apply_enrichment

        events = [
            {'text': 'Something', 'ir_phase': 'analysis', 'phase_confidence': 'low'},
            {'text': 'Other', 'ir_phase': 'analysis', 'phase_confidence': 'high'},
        ]
        severity = {'level': 'high', 'confidence': 'high', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': []}

        enrichment = {
            'phase_updates': [
                {'event_index': 0, 'ir_phase': 'containment', 'phase_confidence': 'medium'},
            ]
        }

        _apply_enrichment(events, severity, actions, entities, enrichment)

        assert events[0]['ir_phase'] == 'containment'
        assert events[0]['phase_confidence'] == 'medium'
        assert events[0]['phase_source'] == 'llm'
        assert events[1]['ir_phase'] == 'analysis'
        assert 'phase_source' not in events[1]

    def test_apply_enrichment_severity(self):
        """_apply_enrichment should update severity from LLM results."""
        from extractors import _apply_enrichment

        events = []
        severity = {'level': 'unknown', 'confidence': 'low', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': []}

        enrichment = {
            'severity_update': {
                'level': 'high',
                'confidence': 'medium',
                'indicators': ['degraded', 'timeout'],
            }
        }

        _apply_enrichment(events, severity, actions, entities, enrichment)

        assert severity['level'] == 'high'
        assert severity['source'] == 'llm'

    def test_apply_enrichment_actions(self):
        """_apply_enrichment should append new LLM-found actions."""
        from extractors import _apply_enrichment

        events = []
        severity = {'level': 'high', 'confidence': 'high', 'indicators': []}
        actions = [{'action': 'deployed', 'category': 'remediation', 'context': 'Deployed fix'}]
        entities = {'services': [], 'ips': [], 'domains': []}

        enrichment = {
            'new_actions': [
                {'action': 'switched', 'category': 'remediation', 'context': 'Switched traffic', 'source': 'llm'},
            ]
        }

        _apply_enrichment(events, severity, actions, entities, enrichment)

        assert len(actions) == 2
        assert actions[1]['source'] == 'llm'

    def test_apply_enrichment_entities(self):
        """_apply_enrichment should remove false-positive domains."""
        from extractors import _apply_enrichment

        events = []
        severity = {'level': 'high', 'confidence': 'high', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': ['sarah.chen', 'api.example.com']}

        enrichment = {
            'entity_updates': {
                'disambiguated': [
                    {'item': 'sarah.chen', 'entity_type': 'person', 'reasoning': 'Name'},
                ]
            }
        }

        _apply_enrichment(events, severity, actions, entities, enrichment)

        assert 'sarah.chen' not in entities['domains']
        assert 'api.example.com' in entities['domains']

    def test_apply_enrichment_irrelevant_removed(self):
        """_apply_enrichment should remove events classified as irrelevant."""
        from extractors import _apply_enrichment

        events = [
            {'text': 'Deploying v2.0', 'ir_phase': 'detection', 'phase_confidence': 'low'},
            {'text': 'Alert fired', 'ir_phase': 'detection', 'phase_confidence': 'high'},
            {'text': 'Happy Monday', 'ir_phase': 'analysis', 'phase_confidence': 'low'},
        ]
        severity = {'level': 'high', 'confidence': 'high', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': []}

        enrichment = {
            'phase_updates': [
                {'event_index': 0, 'ir_phase': 'irrelevant', 'phase_confidence': 'medium'},
                {'event_index': 2, 'ir_phase': 'irrelevant', 'phase_confidence': 'medium'},
            ]
        }

        _apply_enrichment(events, severity, actions, entities, enrichment)

        assert len(events) == 1
        assert events[0]['text'] == 'Alert fired'

    def test_apply_enrichment_irrelevant_removes_orphan_actions(self):
        """Removing irrelevant events should also remove their associated actions."""
        from extractors import _apply_enrichment

        events = [
            {'text': 'Deploying v2.0', 'ir_phase': 'detection', 'phase_confidence': 'low'},
            {'text': 'Alert fired', 'ir_phase': 'detection', 'phase_confidence': 'high'},
        ]
        severity = {'level': 'high', 'confidence': 'high', 'indicators': []}
        actions = [
            {'action': 'deploying', 'category': 'remediation',
             'context': '2024-01-01T10:00:00Z sarah: Deploying v2.0'},
            {'action': 'alerted', 'category': 'communication',
             'context': '2024-01-01T14:00:00Z mike: Alert fired'},
        ]
        entities = {'services': [], 'ips': [], 'domains': []}

        enrichment = {
            'phase_updates': [
                {'event_index': 0, 'ir_phase': 'irrelevant', 'phase_confidence': 'medium'},
            ]
        }

        _apply_enrichment(events, severity, actions, entities, enrichment)

        assert len(events) == 1
        assert len(actions) == 1
        assert 'Alert fired' in actions[0]['context']

    def test_apply_enrichment_irrelevant_mixed_with_reclassify(self):
        """_apply_enrichment should handle mix of irrelevant and reclassified events."""
        from extractors import _apply_enrichment

        events = [
            {'text': 'Casual chat', 'ir_phase': 'detection', 'phase_confidence': 'low'},
            {'text': 'Investigating issue', 'ir_phase': 'detection', 'phase_confidence': 'low'},
            {'text': 'Rolled back', 'ir_phase': 'analysis', 'phase_confidence': 'low'},
        ]
        severity = {'level': 'high', 'confidence': 'high', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': []}

        enrichment = {
            'phase_updates': [
                {'event_index': 0, 'ir_phase': 'irrelevant', 'phase_confidence': 'medium'},
                {'event_index': 1, 'ir_phase': 'analysis', 'phase_confidence': 'medium'},
                {'event_index': 2, 'ir_phase': 'containment', 'phase_confidence': 'medium'},
            ]
        }

        _apply_enrichment(events, severity, actions, entities, enrichment)

        assert len(events) == 2
        assert events[0]['ir_phase'] == 'analysis'
        assert events[0]['phase_source'] == 'llm'
        assert events[1]['ir_phase'] == 'containment'

    def test_apply_enrichment_out_of_bounds_index(self):
        """_apply_enrichment should handle out-of-bounds event indices safely."""
        from extractors import _apply_enrichment

        events = [{'text': 'Something', 'ir_phase': 'analysis', 'phase_confidence': 'low'}]
        severity = {'level': 'high', 'confidence': 'high', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': []}

        enrichment = {
            'phase_updates': [
                {'event_index': 99, 'ir_phase': 'containment', 'phase_confidence': 'medium'},
            ]
        }

        _apply_enrichment(events, severity, actions, entities, enrichment)
        assert events[0]['ir_phase'] == 'analysis'  # Unchanged


# ── TestGetLlmClient ─────────────────────────────────────────────────

class TestGetLlmClient:
    """Test _get_llm_client() boundary function."""

    def test_returns_none_when_sdk_missing(self):
        """Should return (None, 'none') when anthropic SDK is missing."""
        from extractors import _get_llm_client
        with patch.dict('sys.modules', {'llm': None}):
            client, level = _get_llm_client()
            assert client is None
            assert level == 'none'

    def test_returns_none_when_no_key(self):
        """Should return (None, 'none') when API key is empty."""
        from extractors import _get_llm_client
        env = {'ANTHROPIC_API_KEY': '', 'LLM_ENRICHMENT': 'regular'}
        with patch.dict('os.environ', env, clear=True):
            client, level = _get_llm_client()
            assert client is None
            assert level == 'none'

    def test_returns_none_when_level_none(self):
        """Should return (None, 'none') when enrichment is disabled."""
        from extractors import _get_llm_client
        env = {'ANTHROPIC_API_KEY': 'sk-test', 'LLM_ENRICHMENT': 'none'}
        with patch.dict('os.environ', env, clear=True):
            client, level = _get_llm_client()
            assert client is None
            assert level == 'none'


# ── TestGracefulDegradation ──────────────────────────────────────────

class TestGracefulDegradation:
    """Test that the pipeline degrades gracefully."""

    def test_enrich_catches_exceptions(self):
        """_enrich should catch all exceptions."""
        from extractors import _enrich

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("Boom")

        result = _enrich([], "text", {}, [], {}, mock_client, 'regular')
        # enrich_timeline will catch the exception internally,
        # but if something unexpected happens, _enrich catches it too
        assert isinstance(result, dict) or result is None

    def test_generate_summary_without_llm(self):
        """generate_summary should work perfectly without LLM."""
        from extractors import generate_summary
        text = (
            "@sarah 14:23: Alert: payment-service showing elevated error rates\n"
            "@mike 14:25: Investigating - checking payment-service logs\n"
            "@sarah 14:30: Found root cause - bad deploy at 14:20\n"
            "@mike 14:35: Rolling back payment-service to v2.3.1\n"
            "@sarah 14:40: Rollback complete, errors returning to normal\n"
            "@mike 14:45: Confirmed - all metrics stable, incident resolved"
        )
        # This calls _get_llm_client() which reads .env — but without
        # a valid key or with level='none', it returns (None, 'none')
        # and _analyze_timeline skips enrichment entirely.
        result = generate_summary(text)
        assert result['timeline']
        assert result['actions']
        assert result['severity']['level'] != 'unknown'


# ── TestEnrichmentLevels ─────────────────────────────────────────────

class TestEnrichmentLevels:
    """Test that enrichment levels control which passes run."""

    def test_low_skips_actions_and_entities(self):
        """Level 'low' should only run phases and severity."""
        events = [
            {'text': 'Alert', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00',
             'ir_phase': 'detection', 'phase_confidence': 'low'},
        ]
        severity = {'level': 'unknown', 'confidence': 'low', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': ['sarah.chen']}

        calls = []
        def track_calls(**kwargs):
            tool_name = kwargs.get('tool_choice', {}).get('name', '')
            calls.append(tool_name)
            return _make_response(_make_text_block("no result"))

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = track_calls

        enrich_timeline(
            events, "text", severity, actions, entities,
            client=mock_client, model=MODEL, level="low",
        )
        assert 'classify_phases' in calls
        assert 'assess_severity' in calls
        assert 'identify_actions' not in calls
        assert 'disambiguate_entities' not in calls

    def test_regular_runs_all(self):
        """Level 'regular' should run all four passes."""
        events = [
            {'text': 'Alert', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00',
             'ir_phase': 'detection', 'phase_confidence': 'low'},
        ]
        severity = {'level': 'unknown', 'confidence': 'low', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': ['sarah.chen']}

        calls = []
        def track_calls(**kwargs):
            tool_name = kwargs.get('tool_choice', {}).get('name', '')
            calls.append(tool_name)
            return _make_response(_make_text_block("no result"))

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = track_calls

        enrich_timeline(
            events, "text", severity, actions, entities,
            client=mock_client, model=MODEL, level="regular",
        )
        assert 'classify_phases' in calls
        assert 'assess_severity' in calls
        assert 'identify_actions' in calls
        assert 'disambiguate_entities' in calls
