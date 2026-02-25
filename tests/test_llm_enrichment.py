"""
Tests for LLM enrichment (Phase 6).

All tests mock the Anthropic SDK — no real API calls.
"""

import sys
import pytest
from unittest.mock import patch, MagicMock, PropertyMock


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


# ── TestIsAvailable ──────────────────────────────────────────────────

class TestIsAvailable:
    """Test is_available() checks."""

    def test_unavailable_without_sdk(self):
        """Should return False when anthropic SDK is not installed."""
        import llm.enrichment as mod
        original = mod._ANTHROPIC_AVAILABLE
        try:
            mod._ANTHROPIC_AVAILABLE = False
            assert mod.is_available() is False
        finally:
            mod._ANTHROPIC_AVAILABLE = original

    def test_unavailable_without_key(self):
        """Should return False when API key is empty."""
        env = {'ANTHROPIC_API_KEY': '', 'LLM_ENRICHMENT': 'regular'}
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            original = mod._ANTHROPIC_AVAILABLE
            try:
                mod._ANTHROPIC_AVAILABLE = True
                assert mod.is_available() is False
            finally:
                mod._ANTHROPIC_AVAILABLE = original

    def test_unavailable_when_none_level(self):
        """Should return False when enrichment level is 'none'."""
        env = {'ANTHROPIC_API_KEY': 'sk-test', 'LLM_ENRICHMENT': 'none'}
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            original = mod._ANTHROPIC_AVAILABLE
            try:
                mod._ANTHROPIC_AVAILABLE = True
                assert mod.is_available() is False
            finally:
                mod._ANTHROPIC_AVAILABLE = original

    def test_available_with_key_and_low(self):
        """Should return True with API key and 'low' level."""
        env = {'ANTHROPIC_API_KEY': 'sk-test', 'LLM_ENRICHMENT': 'low'}
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            original = mod._ANTHROPIC_AVAILABLE
            try:
                mod._ANTHROPIC_AVAILABLE = True
                assert mod.is_available() is True
            finally:
                mod._ANTHROPIC_AVAILABLE = original

    def test_available_with_key_and_regular(self):
        """Should return True with API key and 'regular' level."""
        env = {'ANTHROPIC_API_KEY': 'sk-test', 'LLM_ENRICHMENT': 'regular'}
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            original = mod._ANTHROPIC_AVAILABLE
            try:
                mod._ANTHROPIC_AVAILABLE = True
                assert mod.is_available() is True
            finally:
                mod._ANTHROPIC_AVAILABLE = original


# ── Helper: mock API response ────────────────────────────────────────

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


def _patch_enrichment_env(level='regular'):
    """Return env dict for enrichment tests."""
    return {
        'ANTHROPIC_API_KEY': 'sk-ant-test',
        'LLM_ENRICHMENT': level,
    }


# ── TestCallHaiku ────────────────────────────────────────────────────

class TestCallHaiku:
    """Test _call_haiku() API wrapper."""

    def setup_method(self):
        """Reset client singleton between tests."""
        import llm.enrichment as mod
        mod._client = None

    def test_success(self):
        """Should return tool input on successful API call."""
        tool_input = {"classifications": [{"event_number": 0, "phase": "detection", "reasoning": "test"}]}
        response = _make_response(_make_tool_use_block("classify_phases", tool_input))

        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            original_avail = mod._ANTHROPIC_AVAILABLE
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                from llm.prompts import IR_PHASE_TOOL
                result = mod._call_haiku("system", "user", IR_PHASE_TOOL, "classify_phases")
                assert result == tool_input
            finally:
                mod._ANTHROPIC_AVAILABLE = original_avail
                mod._client = None

    def test_api_exception(self):
        """Should return None on API exception."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            original_avail = mod._ANTHROPIC_AVAILABLE
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                from llm.prompts import IR_PHASE_TOOL
                result = mod._call_haiku("system", "user", IR_PHASE_TOOL, "classify_phases")
                assert result is None
            finally:
                mod._ANTHROPIC_AVAILABLE = original_avail
                mod._client = None

    def test_no_tool_use_block(self):
        """Should return None when response has no tool_use block."""
        response = _make_response(_make_text_block("I can't do that"))

        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            original_avail = mod._ANTHROPIC_AVAILABLE
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                from llm.prompts import IR_PHASE_TOOL
                result = mod._call_haiku("system", "user", IR_PHASE_TOOL, "classify_phases")
                assert result is None
            finally:
                mod._ANTHROPIC_AVAILABLE = original_avail
                mod._client = None

    def test_wrong_tool_name(self):
        """Should return None when tool_use block has wrong name."""
        response = _make_response(_make_tool_use_block("wrong_tool", {}))

        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            original_avail = mod._ANTHROPIC_AVAILABLE
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                from llm.prompts import IR_PHASE_TOOL
                result = mod._call_haiku("system", "user", IR_PHASE_TOOL, "classify_phases")
                assert result is None
            finally:
                mod._ANTHROPIC_AVAILABLE = original_avail
                mod._client = None

    def test_client_not_available(self):
        """Should return None when client is not available."""
        env = {'ANTHROPIC_API_KEY': '', 'LLM_ENRICHMENT': 'none'}
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._client = None
            from llm.prompts import IR_PHASE_TOOL
            result = mod._call_haiku("system", "user", IR_PHASE_TOOL, "classify_phases")
            assert result is None


# ── TestEnrichIRPhases ───────────────────────────────────────────────

class TestEnrichIRPhases:
    """Test enrich_ir_phases() function."""

    def setup_method(self):
        import llm.enrichment as mod
        mod._client = None

    def test_skip_when_no_low_confidence(self):
        """Should return None when no events have low confidence."""
        events = [
            {'text': 'Alert fired', 'time': '14:00', 'ir_phase': 'detection', 'phase_confidence': 'high'},
            {'text': 'Investigating', 'time': '14:05', 'ir_phase': 'analysis', 'phase_confidence': 'medium'},
        ]
        import llm.enrichment as mod
        result = mod.enrich_ir_phases(events)
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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_ir_phases(events)
                assert result is not None
                assert len(result) == 1
                assert result[0]['event_index'] == 1
                assert result[0]['ir_phase'] == 'containment'
                assert result[0]['phase_confidence'] == 'medium'
            finally:
                mod._client = None

    def test_api_failure_returns_none(self):
        """Should return None when API call fails."""
        events = [
            {'text': 'Something', 'time': '14:00', 'ir_phase': 'analysis', 'phase_confidence': 'low'},
        ]

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_ir_phases(events)
                assert result is None
            finally:
                mod._client = None

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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_ir_phases(events)
                assert result is None
            finally:
                mod._client = None

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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_ir_phases(events)
                assert result is not None
                assert len(result) == 1
                assert result[0]['ir_phase'] == 'irrelevant'
            finally:
                mod._client = None

    def test_batching_large_set(self):
        """Should batch events into groups of 10."""
        events = [
            {'text': f'Event {i}', 'time': f'14:{i:02d}',
             'ir_phase': 'analysis', 'phase_confidence': 'low'}
            for i in range(15)
        ]

        # Return valid results for first batch, empty for second
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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_ir_phases(events)
                assert call_count[0] == 2  # Two batches
                assert result is not None
                assert len(result) == 1
            finally:
                mod._client = None


# ── TestEnrichSeverity ───────────────────────────────────────────────

class TestEnrichSeverity:
    """Test enrich_severity() function."""

    def setup_method(self):
        import llm.enrichment as mod
        mod._client = None

    def test_skip_when_confident(self):
        """Should return None when severity is already confident."""
        severity = {'level': 'high', 'confidence': 'high', 'indicators': ['error rate']}
        import llm.enrichment as mod
        result = mod.enrich_severity("some text", severity)
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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_severity("error text here", severity)
                assert result is not None
                assert result['level'] == 'high'
                assert result['confidence'] == 'medium'
            finally:
                mod._client = None

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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_severity("degraded service with timeouts", severity)
                assert result is not None
                assert result['level'] == 'high'
            finally:
                mod._client = None

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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                mod.enrich_severity(long_text, severity)
                # Verify the user content was truncated
                call_args = mock_client.messages.create.call_args
                user_msg = call_args.kwargs['messages'][0]['content']
                assert len(user_msg) == 2000
            finally:
                mod._client = None


# ── TestEnrichActions ────────────────────────────────────────────────

class TestEnrichActions:
    """Test enrich_actions() function."""

    def setup_method(self):
        import llm.enrichment as mod
        mod._client = None

    def test_skip_when_all_have_actions(self):
        """Should return None when all events have corresponding actions."""
        events = [
            {'text': 'Deployed fix', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00'},
        ]
        actions = [
            {'action': 'deployed', 'category': 'remediation', 'context': 'Deployed fix'},
        ]
        import llm.enrichment as mod
        result = mod.enrich_actions(events, actions)
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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_actions(events, actions)
                assert result is not None
                assert len(result) == 1
                assert result[0]['action'] == 'switched traffic'
                assert result[0]['source'] == 'llm'
            finally:
                mod._client = None

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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_actions(events, actions)
                assert result is None
            finally:
                mod._client = None

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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_actions(events, actions)
                assert result is None
            finally:
                mod._client = None


# ── TestEnrichEntities ───────────────────────────────────────────────

class TestEnrichEntities:
    """Test enrich_entities() function."""

    def setup_method(self):
        import llm.enrichment as mod
        mod._client = None

    def test_skip_when_no_suspects(self):
        """Should return None when no firstname.lastname domains found."""
        entities = {
            'services': ['payment-api'],
            'ips': ['10.0.0.1'],
            'domains': ['api.example.com'],
        }
        import llm.enrichment as mod
        result = mod.enrich_entities(entities, "some text")
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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_entities(entities, "sarah.chen reported the issue")
                assert result is not None
                assert result['disambiguated'][0]['entity_type'] == 'person'
            finally:
                mod._client = None

    def test_real_domain_kept(self):
        """Should not flag actual domains as suspects (short TLD)."""
        entities = {
            'services': [],
            'ips': [],
            'domains': ['api.io', 'status.co'],  # Short TLDs, not suspected
        }
        import llm.enrichment as mod
        result = mod.enrich_entities(entities, "some text")
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

        env = _patch_enrichment_env()
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            mod._client = mock_client
            try:
                result = mod.enrich_entities(entities, "sarah.chen and mike.jones on call")
                assert result is not None
                assert len(result['disambiguated']) == 2
            finally:
                mod._client = None


# ── TestEnrichTimeline (orchestrator) ────────────────────────────────

class TestEnrichTimeline:
    """Test enrich_timeline() orchestrator."""

    def setup_method(self):
        import llm.enrichment as mod
        mod._client = None

    def test_all_passes_run_on_regular(self):
        """In 'regular' mode, all four passes should be attempted."""
        events = [
            {'text': 'Something', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00',
             'ir_phase': 'analysis', 'phase_confidence': 'low'},
        ]
        severity = {'level': 'unknown', 'confidence': 'low', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': ['sarah.chen']}

        # Mock _call_haiku to return None (we just test that passes run)
        env = _patch_enrichment_env('regular')
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True

            with patch.object(mod, '_call_haiku', return_value=None):
                result = mod.enrich_timeline(events, "text", severity, actions, entities)
                # Should return empty dict (all passes returned None)
                assert isinstance(result, dict)

    def test_partial_failure(self):
        """Should continue when some passes fail."""
        events = [
            {'text': 'Alert', 'time': '14:00', 'ir_phase': 'detection', 'phase_confidence': 'low'},
        ]
        severity = {'level': 'unknown', 'confidence': 'low', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': []}

        env = _patch_enrichment_env('regular')
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True

            # Phase enrichment raises, severity succeeds
            call_count = [0]
            def mock_call(system, user, tool_schema, tool_name):
                call_count[0] += 1
                if tool_name == "classify_phases":
                    raise Exception("Phase API down")
                elif tool_name == "assess_severity":
                    return {
                        "level": "high",
                        "confidence": "medium",
                        "indicators": ["degraded"],
                        "reasoning": "test",
                    }
                return None

            with patch.object(mod, '_call_haiku', side_effect=mock_call):
                result = mod.enrich_timeline(events, "text", severity, actions, entities)
                # Severity should still work despite phase failure
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

        env = _patch_enrichment_env('regular')
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True

            with patch.object(mod, '_call_haiku', return_value=None):
                result = mod.enrich_timeline(events, "text", severity, actions, entities)
                assert result == {}


# ── TestPipelineIntegration ──────────────────────────────────────────

class TestPipelineIntegration:
    """Test _try_enrich / _apply_enrichment in extractors.py."""

    def test_without_llm(self):
        """Pipeline should work identically without LLM."""
        from extractors import generate_summary
        text = "@sarah 14:23: Payment service showing elevated errors\n@mike 14:30: Investigating root cause"
        result = generate_summary(text)
        assert 'timeline' in result
        assert 'actions' in result
        assert 'severity' in result

    def test_try_enrich_returns_none_when_disabled(self):
        """_try_enrich should return None when enrichment is disabled."""
        from extractors import _try_enrich
        env = {'ANTHROPIC_API_KEY': '', 'LLM_ENRICHMENT': 'none'}
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            original = mod._ANTHROPIC_AVAILABLE
            mod._ANTHROPIC_AVAILABLE = False
            try:
                result = _try_enrich([], "text", {}, [], {})
                assert result is None
            finally:
                mod._ANTHROPIC_AVAILABLE = original

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
        # Second event unchanged
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
        assert severity['confidence'] == 'medium'
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
        # Action context has timestamp+actor prefix (like reconstructed text)
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

        # Should not raise
        _apply_enrichment(events, severity, actions, entities, enrichment)
        assert events[0]['ir_phase'] == 'analysis'  # Unchanged


# ── TestGracefulDegradation ──────────────────────────────────────────

class TestGracefulDegradation:
    """Test that the pipeline degrades gracefully."""

    def test_import_error(self):
        """_try_enrich should handle ImportError gracefully."""
        from extractors import _try_enrich

        with patch.dict('sys.modules', {'llm': None}):
            result = _try_enrich([], "text", {}, [], {})
            # Should not raise, returns None
            assert result is None

    def test_exception_in_enrichment(self):
        """_try_enrich should catch all exceptions."""
        from extractors import _try_enrich

        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.enrich_timeline.side_effect = RuntimeError("Boom")

        with patch.dict('sys.modules', {'llm': mock_llm}):
            result = _try_enrich([], "text", {}, [], {})
            assert result is None

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
        result = generate_summary(text)
        assert result['timeline']
        assert result['actions']
        assert result['severity']['level'] != 'unknown'
        assert 'summary_text' in result


# ── TestEnrichmentLevels ─────────────────────────────────────────────

class TestEnrichmentLevels:
    """Test that enrichment levels control which passes run."""

    def setup_method(self):
        import llm.enrichment as mod
        mod._client = None

    def test_none_runs_nothing(self):
        """Level 'none' should not be available."""
        env = {'ANTHROPIC_API_KEY': 'sk-test', 'LLM_ENRICHMENT': 'none'}
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True
            assert mod.is_available() is False

    def test_low_skips_actions_and_entities(self):
        """Level 'low' should only run phases and severity."""
        events = [
            {'text': 'Alert', 'time': '14:00', 'timestamp': '2024-01-01T14:00:00',
             'ir_phase': 'detection', 'phase_confidence': 'low'},
        ]
        severity = {'level': 'unknown', 'confidence': 'low', 'indicators': []}
        actions = []
        entities = {'services': [], 'ips': [], 'domains': ['sarah.chen']}

        env = _patch_enrichment_env('low')
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True

            calls = []
            def track_calls(system, user, tool_schema, tool_name):
                calls.append(tool_name)
                return None

            with patch.object(mod, '_call_haiku', side_effect=track_calls):
                result = mod.enrich_timeline(events, "text", severity, actions, entities)
                # Should only call phase and severity, not actions or entities
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

        env = _patch_enrichment_env('regular')
        with patch.dict('os.environ', env, clear=True):
            import llm.enrichment as mod
            mod._ANTHROPIC_AVAILABLE = True

            calls = []
            def track_calls(system, user, tool_schema, tool_name):
                calls.append(tool_name)
                return None

            with patch.object(mod, '_call_haiku', side_effect=track_calls):
                result = mod.enrich_timeline(events, "text", severity, actions, entities)
                assert 'classify_phases' in calls
                assert 'assess_severity' in calls
                assert 'identify_actions' in calls
                assert 'disambiguate_entities' in calls
