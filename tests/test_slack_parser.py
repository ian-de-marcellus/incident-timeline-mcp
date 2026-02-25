"""
Tests for parsers/slack.py — Slack workspace export parsing.
"""

import json
import os
import pytest
from datetime import datetime, timezone

from parsers.slack import (
    parse_users,
    clean_slack_text,
    _extract_message_text,
    parse_slack_messages,
    reconstruct_plaintext,
    _build_events_from_messages,
    _is_incident_relevant,
    parse_slack_export,
    SKIP_SUBTYPES,
)
from models import NormalizedMessage


# ── Test data helpers ────────────────────────────────────────────────

def _user(uid, display_name='', real_name='', name='', is_bot=False):
    """Build a minimal Slack user object."""
    return {
        'id': uid,
        'team_id': 'T001',
        'name': name,
        'deleted': False,
        'is_bot': is_bot,
        'is_app_user': is_bot,
        'profile': {
            'display_name': display_name,
            'real_name': real_name,
        },
    }


def _msg(ts, user='', text='', subtype=None, **kwargs):
    """Build a minimal Slack message object."""
    msg = {'type': 'message', 'ts': ts, 'text': text}
    if user:
        msg['user'] = user
    if subtype:
        msg['subtype'] = subtype
    msg.update(kwargs)
    return msg


SAMPLE_USER_MAP = {
    'U001': 'sarah.chen',
    'U002': 'james.rodriguez',
    'U003': 'alex.kim',
}


# ── TestParseUsers ───────────────────────────────────────────────────

class TestParseUsers:
    def test_basic_display_name(self):
        users = [_user('U001', display_name='sarah.chen')]
        result = parse_users(users)
        assert result == {'U001': 'sarah.chen'}

    def test_prefers_display_name_over_real_name(self):
        users = [_user('U001', display_name='sarah.chen', real_name='Sarah Chen')]
        result = parse_users(users)
        assert result['U001'] == 'sarah.chen'

    def test_falls_back_to_normalized_real_name(self):
        users = [_user('U001', real_name='Sarah Chen')]
        result = parse_users(users)
        assert result['U001'] == 'sarah.chen'

    def test_empty_display_name_uses_real_name(self):
        users = [_user('U001', display_name='', real_name='Sarah Chen')]
        result = parse_users(users)
        assert result['U001'] == 'sarah.chen'

    def test_missing_profile_uses_name_field(self):
        user = {'id': 'U001', 'name': 'sarah', 'profile': {}}
        result = parse_users([user])
        assert result['U001'] == 'sarah'

    def test_no_profile_key_uses_name(self):
        user = {'id': 'U001', 'name': 'sarah'}
        result = parse_users([user])
        assert result['U001'] == 'sarah'

    def test_empty_list(self):
        assert parse_users([]) == {}

    def test_bot_users_included(self):
        users = [_user('B001', display_name='PagerDuty', is_bot=True)]
        result = parse_users(users)
        assert result['B001'] == 'PagerDuty'

    def test_multiple_users(self):
        users = [
            _user('U001', display_name='sarah.chen'),
            _user('U002', display_name='james.rodriguez'),
        ]
        result = parse_users(users)
        assert len(result) == 2
        assert result['U001'] == 'sarah.chen'
        assert result['U002'] == 'james.rodriguez'

    def test_falls_back_to_id(self):
        user = {'id': 'U999', 'profile': {}}
        result = parse_users([user])
        assert result['U999'] == 'U999'


# ── TestCleanSlackText ───────────────────────────────────────────────

class TestCleanSlackText:
    def test_user_mention(self):
        result = clean_slack_text('<@U001>', SAMPLE_USER_MAP)
        assert result == '@sarah.chen'

    def test_user_mention_with_label_prefers_lookup(self):
        result = clean_slack_text('<@U001|sarah>', SAMPLE_USER_MAP)
        assert result == '@sarah.chen'

    def test_unknown_user(self):
        result = clean_slack_text('<@U999>', SAMPLE_USER_MAP)
        assert result == '@U999'

    def test_channel_link_with_label(self):
        result = clean_slack_text('<#C100|general>', SAMPLE_USER_MAP)
        assert result == '#general'

    def test_channel_link_without_label(self):
        result = clean_slack_text('<#C100>', SAMPLE_USER_MAP)
        assert result == '#C100'

    def test_url_with_label(self):
        result = clean_slack_text('<https://example.com|link>', SAMPLE_USER_MAP)
        assert result == 'link'

    def test_bare_url(self):
        result = clean_slack_text('<https://example.com>', SAMPLE_USER_MAP)
        assert result == 'https://example.com'

    def test_here_mention(self):
        assert clean_slack_text('<!here>', {}) == '@here'

    def test_channel_mention(self):
        assert clean_slack_text('<!channel>', {}) == '@channel'

    def test_everyone_mention(self):
        assert clean_slack_text('<!everyone>', {}) == '@everyone'

    def test_subteam_with_label(self):
        result = clean_slack_text('<!subteam^S123|@oncall>', {})
        assert result == '@oncall'

    def test_subteam_without_label(self):
        result = clean_slack_text('<!subteam^S123>', {})
        assert result == '@subteam'

    def test_html_entities(self):
        result = clean_slack_text('a &amp; b &lt; c &gt; d', {})
        assert result == 'a & b < c > d'

    def test_combined_patterns(self):
        text = '<@U001> check <#C100|general> for <https://example.com|details>'
        result = clean_slack_text(text, SAMPLE_USER_MAP)
        assert result == '@sarah.chen check #general for details'

    def test_plain_text_unchanged(self):
        assert clean_slack_text('hello world', {}) == 'hello world'

    def test_empty_text(self):
        assert clean_slack_text('', {}) == ''

    def test_none_text(self):
        assert clean_slack_text(None, {}) is None


# ── TestExtractMessageText ───────────────────────────────────────────

class TestExtractMessageText:
    def test_plain_text(self):
        msg = {'text': 'Hello world'}
        assert _extract_message_text(msg) == 'Hello world'

    def test_bot_with_attachments(self):
        msg = {
            'text': 'Incident triggered',
            'attachments': [{
                'title': 'Service Down',
                'text': 'Severity: SEV-1',
            }],
        }
        result = _extract_message_text(msg)
        assert 'Incident triggered' in result
        assert 'Service Down' in result
        assert 'Severity: SEV-1' in result

    def test_empty_text_uses_attachment_fallback(self):
        msg = {
            'text': '',
            'attachments': [{
                'fallback': 'Alert: Service X is Down',
            }],
        }
        result = _extract_message_text(msg)
        assert result == 'Alert: Service X is Down'

    def test_attachment_title_and_text(self):
        msg = {
            'text': '',
            'attachments': [{
                'title': 'CPU Alert',
                'text': 'CPU at 95%',
            }],
        }
        result = _extract_message_text(msg)
        assert 'CPU Alert' in result
        assert 'CPU at 95%' in result

    def test_no_text_no_attachments(self):
        msg = {}
        assert _extract_message_text(msg) == ''

    def test_attachment_only_title(self):
        msg = {
            'text': '',
            'attachments': [{'title': 'Alert Title'}],
        }
        assert _extract_message_text(msg) == 'Alert Title'

    def test_attachment_only_text(self):
        msg = {
            'text': '',
            'attachments': [{'text': 'Alert body text'}],
        }
        assert _extract_message_text(msg) == 'Alert body text'

    def test_blocks_rich_text(self):
        msg = {
            'blocks': [{
                'type': 'rich_text',
                'elements': [{
                    'type': 'rich_text_section',
                    'elements': [
                        {'type': 'text', 'text': 'Hello from blocks'},
                    ],
                }],
            }],
        }
        assert _extract_message_text(msg) == 'Hello from blocks'

    def test_file_title_appended(self):
        msg = {
            'text': 'Here is the traffic graph.',
            'files': [{'title': 'Traffic Spike at 23:50 UTC'}],
        }
        result = _extract_message_text(msg)
        assert 'Here is the traffic graph.' in result
        assert '[Files: Traffic Spike at 23:50 UTC]' in result

    def test_multiple_file_titles(self):
        msg = {
            'text': 'Screenshots attached',
            'files': [
                {'title': 'CPU Graph'},
                {'title': 'Error Logs'},
            ],
        }
        result = _extract_message_text(msg)
        assert '[Files: CPU Graph, Error Logs]' in result

    def test_file_without_title_skipped(self):
        msg = {
            'text': 'Here is a file',
            'files': [{'id': 'F001', 'name': 'image.png'}],
        }
        result = _extract_message_text(msg)
        assert result == 'Here is a file'

    def test_file_only_no_text(self):
        """Message with only a file upload and no text."""
        msg = {
            'text': '',
            'files': [{'title': 'Screenshot of dashboard'}],
        }
        result = _extract_message_text(msg)
        assert result == '[Files: Screenshot of dashboard]'


# ── TestParseSlackMessages ───────────────────────────────────────────

class TestParseSlackMessages:
    def test_basic_message(self):
        messages = [_msg('1729000995.000001', user='U001', text='Hello')]
        result, skipped = parse_slack_messages(messages, SAMPLE_USER_MAP)
        assert len(result) == 1
        assert result[0].text == 'Hello'
        assert result[0].actor == 'sarah.chen'
        assert result[0].source == 'slack'
        assert skipped == 0

    def test_timestamp_parsing(self):
        messages = [_msg('1729002195.000000', user='U001', text='test')]
        result, _ = parse_slack_messages(messages, SAMPLE_USER_MAP)
        expected = datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc)
        assert result[0].timestamp == expected

    def test_actor_resolved_via_user_map(self):
        messages = [_msg('1729000000.000001', user='U002', text='test')]
        result, _ = parse_slack_messages(messages, SAMPLE_USER_MAP)
        assert result[0].actor == 'james.rodriguez'

    def test_bot_message_actor(self):
        msg = _msg('1729000000.000001', text='Alert',
                    subtype='bot_message', username='PagerDuty', bot_id='B001')
        result, _ = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert result[0].actor == 'PagerDuty'

    def test_bot_message_text_includes_attachments(self):
        msg = _msg('1729000000.000001', text='Incident triggered',
                    subtype='bot_message', username='PagerDuty',
                    attachments=[{'title': 'Service Down', 'text': 'SEV-1'}])
        result, _ = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert 'Service Down' in result[0].text
        assert 'SEV-1' in result[0].text

    def test_channel_join_filtered(self):
        messages = [
            _msg('1729000000.000001', user='U001', text='joined', subtype='channel_join'),
            _msg('1729000001.000001', user='U001', text='Hello'),
        ]
        result, skipped = parse_slack_messages(messages, SAMPLE_USER_MAP)
        assert len(result) == 1
        assert result[0].text == 'Hello'
        assert skipped == 1

    def test_bot_message_not_filtered(self):
        msg = _msg('1729000000.000001', text='Alert',
                    subtype='bot_message', username='Bot')
        result, skipped = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert len(result) == 1
        assert skipped == 0

    def test_preserves_thread_ts(self):
        msg = _msg('1729000000.000001', user='U001', text='reply',
                    thread_ts='1728999000.000001')
        result, _ = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert result[0].metadata['thread_ts'] == '1728999000.000001'

    def test_preserves_reactions(self):
        reactions = [{'name': 'thumbsup', 'count': 1, 'users': ['U001']}]
        msg = _msg('1729000000.000001', user='U001', text='test',
                    reactions=reactions)
        result, _ = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert result[0].metadata['reactions'] == reactions

    def test_preserves_edited(self):
        msg = _msg('1729000000.000001', user='U001', text='edited msg',
                    edited={'user': 'U001', 'ts': '1729000100.000001'})
        result, _ = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert result[0].metadata['edited'] == '1729000100.000001'

    def test_preserves_bot_id(self):
        msg = _msg('1729000000.000001', text='Alert',
                    subtype='bot_message', username='Bot', bot_id='B123')
        result, _ = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert result[0].metadata['bot_id'] == 'B123'

    def test_missing_user_field(self):
        msg = {'type': 'message', 'ts': '1729000000.000001', 'text': 'anonymous'}
        result, _ = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert result[0].actor is None

    def test_empty_text(self):
        msg = _msg('1729000000.000001', user='U001')
        result, _ = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert result[0].text == ''

    def test_sorted_by_timestamp(self):
        messages = [
            _msg('1729000002.000001', user='U001', text='second'),
            _msg('1729000001.000001', user='U001', text='first'),
        ]
        result, _ = parse_slack_messages(messages, SAMPLE_USER_MAP)
        assert result[0].text == 'first'
        assert result[1].text == 'second'

    def test_cleans_slack_formatting(self):
        msg = _msg('1729000000.000001', user='U001',
                    text='Check <@U002> in <#C100|general>')
        result, _ = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert result[0].text == 'Check @james.rodriguez in #general'

    def test_non_message_type_skipped(self):
        msg = {'type': 'file', 'ts': '1729000000.000001', 'text': 'x'}
        result, skipped = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert len(result) == 0
        assert skipped == 1

    def test_all_skip_subtypes_filtered(self):
        """Every subtype in SKIP_SUBTYPES should be filtered."""
        for subtype in SKIP_SUBTYPES:
            msg = _msg('1729000000.000001', user='U001', text='x', subtype=subtype)
            result, skipped = parse_slack_messages([msg], SAMPLE_USER_MAP)
            assert len(result) == 0, f"{subtype} was not filtered"
            assert skipped == 1

    def test_bot_fallback_to_bot_id(self):
        msg = _msg('1729000000.000001', text='Alert',
                    subtype='bot_message', bot_id='B123')
        result, _ = parse_slack_messages([msg], SAMPLE_USER_MAP)
        assert result[0].actor == 'B123'


# ── TestReconstructPlaintext ─────────────────────────────────────────

class TestReconstructPlaintext:
    def test_format(self):
        msg = NormalizedMessage(
            timestamp=datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc),
            actor='sarah.chen',
            text='Seeing elevated errors',
            raw='Seeing elevated errors',
            source='slack',
        )
        result = reconstruct_plaintext([msg])
        assert result == '2024-10-15T14:23:15Z sarah.chen: Seeing elevated errors'

    def test_without_actor(self):
        msg = NormalizedMessage(
            timestamp=datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc),
            actor=None,
            text='System alert',
            raw='System alert',
            source='slack',
        )
        result = reconstruct_plaintext([msg])
        assert result == '2024-10-15T14:23:15Z System alert'

    def test_multiline_text_flattened(self):
        msg = NormalizedMessage(
            timestamp=datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc),
            actor='sarah.chen',
            text='Line one\nLine two',
            raw='Line one\nLine two',
            source='slack',
        )
        result = reconstruct_plaintext([msg])
        assert '\n' not in result.split('\n')[0]  # first output line has no internal newlines
        assert 'Line one Line two' in result

    def test_empty_messages_skipped(self):
        messages = [
            NormalizedMessage(
                timestamp=datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc),
                actor='sarah.chen', text='', raw='', source='slack',
            ),
            NormalizedMessage(
                timestamp=datetime(2024, 10, 15, 14, 24, 0, tzinfo=timezone.utc),
                actor='sarah.chen', text='Real message', raw='Real message', source='slack',
            ),
        ]
        result = reconstruct_plaintext(messages)
        lines = result.strip().split('\n')
        assert len(lines) == 1
        assert 'Real message' in lines[0]

    def test_empty_list(self):
        assert reconstruct_plaintext([]) == ''

    def test_no_timestamp(self):
        msg = NormalizedMessage(
            timestamp=None, actor='sarah.chen', text='No time',
            raw='No time', source='slack',
        )
        result = reconstruct_plaintext([msg])
        assert result == 'sarah.chen: No time'

    def test_no_timestamp_no_actor(self):
        msg = NormalizedMessage(
            timestamp=None, actor=None, text='Just text',
            raw='Just text', source='slack',
        )
        result = reconstruct_plaintext([msg])
        assert result == 'Just text'


# ── TestBuildEventsFromMessages ───────────────────────────────────────

class TestBuildEventsFromMessages:
    def test_preserves_actor(self):
        msg = NormalizedMessage(
            timestamp=datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc),
            actor='carol.dev', text='Fixed it', raw='Fixed it', source='slack',
        )
        events = _build_events_from_messages([msg])
        assert events[0]['actor'] == 'carol.dev'

    def test_preserves_timestamp(self):
        msg = NormalizedMessage(
            timestamp=datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc),
            actor='sarah.chen', text='test', raw='test', source='slack',
        )
        events = _build_events_from_messages([msg])
        assert events[0]['time'] == '2024-10-15T14:23:15Z'
        assert 'timestamp' in events[0]

    def test_preserves_text(self):
        msg = NormalizedMessage(
            timestamp=datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc),
            actor='sarah.chen', text='Message text here', raw='raw', source='slack',
        )
        events = _build_events_from_messages([msg])
        assert events[0]['text'] == 'Message text here'

    def test_skips_empty_messages(self):
        messages = [
            NormalizedMessage(
                timestamp=datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc),
                actor='sarah.chen', text='', raw='', source='slack',
            ),
            NormalizedMessage(
                timestamp=datetime(2024, 10, 15, 14, 24, 0, tzinfo=timezone.utc),
                actor='sarah.chen', text='Real message', raw='Real', source='slack',
            ),
        ]
        events = _build_events_from_messages(messages)
        assert len(events) == 1

    def test_no_actor(self):
        msg = NormalizedMessage(
            timestamp=datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc),
            actor=None, text='System event', raw='System event', source='slack',
        )
        events = _build_events_from_messages([msg])
        assert 'actor' not in events[0]

    def test_no_timestamp(self):
        msg = NormalizedMessage(
            timestamp=None, actor='sarah.chen', text='No time',
            raw='No time', source='slack',
        )
        events = _build_events_from_messages([msg])
        assert 'time' not in events[0]
        assert 'timestamp' not in events[0]

    def test_flattens_newlines(self):
        msg = NormalizedMessage(
            timestamp=datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc),
            actor='sarah.chen', text='Line one\nLine two', raw='raw', source='slack',
        )
        events = _build_events_from_messages([msg])
        assert '\n' not in events[0]['text']

    def test_tld_named_actor_preserved(self):
        """Actors with TLD-like names (carol.dev) are preserved, not filtered."""
        msg = NormalizedMessage(
            timestamp=datetime(2024, 10, 15, 14, 23, 15, tzinfo=timezone.utc),
            actor='carol.dev', text='I merged the PR', raw='raw', source='slack',
        )
        events = _build_events_from_messages([msg])
        assert events[0]['actor'] == 'carol.dev'


# ── TestParseUsersTopLevel ───────────────────────────────────────────

class TestParseUsersTopLevel:
    """Tests for parse_users with top-level fields (non-standard exports)."""

    def test_top_level_display_name(self):
        user = {'id': 'U001', 'display_name': 'sarah.chen'}
        result = parse_users([user])
        assert result['U001'] == 'sarah.chen'

    def test_top_level_real_name_not_used_alone(self):
        """Top-level real_name alone doesn't resolve (could contain titles/parens)."""
        user = {'id': 'U001', 'real_name': 'Sarah Chen'}
        result = parse_users([user])
        # Falls to raw ID since only profile.real_name is checked
        assert result['U001'] == 'U001'

    def test_top_level_real_name_with_name_field(self):
        """When name field exists alongside top-level real_name, name wins."""
        user = {'id': 'U001', 'name': 'sarah', 'real_name': 'Sarah Chen'}
        result = parse_users([user])
        assert result['U001'] == 'sarah'

    def test_profile_takes_priority_over_top_level(self):
        user = {
            'id': 'U001',
            'display_name': 'top-level',
            'profile': {'display_name': 'from-profile'},
        }
        result = parse_users([user])
        assert result['U001'] == 'from-profile'

    def test_coinflux_style_user(self):
        """Flat user objects like the coinflux export should resolve correctly."""
        user = {
            'id': 'U_CAROL',
            'name': 'carol.dev',
            'real_name': 'Carol (Backend)',
            'is_bot': False,
        }
        result = parse_users([user])
        # No profile.display_name or profile.real_name → falls to name field
        assert result['U_CAROL'] == 'carol.dev'


# ── TestParseSlackExport ─────────────────────────────────────────────

class TestParseSlackExport:
    def test_full_pipeline(self):
        users = [_user('U001', display_name='sarah.chen')]
        messages = [
            _msg('1729000995.000001', user='U001',
                 text='Seeing elevated response times. Starting investigation.'),
        ]
        result = parse_slack_export(
            json.dumps(messages),
            json.dumps(users),
        )
        assert 'timeline' in result
        assert 'actions' in result
        assert 'entities' in result
        assert 'severity' in result
        assert 'slack_metadata' in result

    def test_without_users_json(self):
        messages = [
            _msg('1729000995.000001', user='U001', text='Test message'),
        ]
        result = parse_slack_export(json.dumps(messages))
        assert 'timeline' in result
        # Without users.json, actor shows as user ID
        assert result['slack_metadata']['message_count'] == 1

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            parse_slack_export('not valid json')

    def test_empty_messages(self):
        result = parse_slack_export('[]')
        assert result['slack_metadata']['message_count'] == 0
        assert result['timeline'] == []

    def test_slack_metadata_keys(self):
        messages = [_msg('1729000000.000001', user='U001', text='test')]
        result = parse_slack_export(json.dumps(messages))
        meta = result['slack_metadata']
        assert 'message_count' in meta
        assert 'user_count' in meta
        assert 'skipped_count' in meta
        assert 'threaded_count' in meta

    def test_has_summary_keys(self):
        messages = [
            _msg('1729000995.000001', user='U001',
                 text='Elevated errors on checkout-service. Investigating.'),
        ]
        result = parse_slack_export(json.dumps(messages))
        assert 'ir_phases' in result
        assert 'metrics' in result
        assert 'summary_text' in result

    def test_skipped_count(self):
        messages = [
            _msg('1729000000.000001', user='U001', text='join', subtype='channel_join'),
            _msg('1729000001.000001', user='U001', text='Hello'),
        ]
        result = parse_slack_export(json.dumps(messages))
        assert result['slack_metadata']['skipped_count'] == 1
        assert result['slack_metadata']['message_count'] == 1

    def test_threaded_count(self):
        messages = [
            _msg('1729000000.000001', user='U001', text='parent'),
            _msg('1729000001.000001', user='U001', text='reply',
                 thread_ts='1729000000.000001'),
        ]
        result = parse_slack_export(json.dumps(messages))
        assert result['slack_metadata']['threaded_count'] == 1

    def test_multi_day_date_keyed(self):
        """Date-keyed object merges messages from multiple days."""
        day1 = [_msg('1729000000.000001', user='U001', text='Day 1 event')]
        day2 = [_msg('1729086400.000001', user='U001', text='Day 2 event')]
        multi = {'2024-10-15': day1, '2024-10-16': day2}
        result = parse_slack_export(json.dumps(multi))
        assert result['slack_metadata']['message_count'] == 2
        assert len(result['timeline']) == 2

    def test_multi_day_sorted_by_timestamp(self):
        """Messages from multiple days should be sorted chronologically."""
        day1 = [_msg('1729000002.000001', user='U001', text='second')]
        day2 = [_msg('1729000001.000001', user='U001', text='first')]
        # Keys out of order, but timestamps determine sort
        multi = {'2024-10-16': day1, '2024-10-15': day2}
        result = parse_slack_export(json.dumps(multi))
        assert result['timeline'][0]['text'] == 'first'
        assert result['timeline'][1]['text'] == 'second'

    def test_multi_day_metrics_span_days(self):
        """Duration should span across day boundary."""
        # Day 1 at 23:00, Day 2 at 01:00 → 2 hour span
        ts_day1 = '1729029600.000001'  # 2024-10-15T22:00:00Z
        ts_day2 = '1729036800.000001'  # 2024-10-16T00:00:00Z
        day1 = [_msg(ts_day1, user='U001', text='Incident started, investigating')]
        day2 = [_msg(ts_day2, user='U001', text='Rollback complete, back to normal')]
        multi = {'2024-10-15': day1, '2024-10-16': day2}
        result = parse_slack_export(json.dumps(multi))
        assert result['metrics']['duration_seconds'] == 7200
        assert result['metrics']['duration'] == '2h 0m'

    def test_multi_day_empty_days_ok(self):
        """Empty day arrays don't break anything."""
        multi = {
            '2024-10-15': [_msg('1729000000.000001', user='U001', text='event')],
            '2024-10-16': [],
        }
        result = parse_slack_export(json.dumps(multi))
        assert result['slack_metadata']['message_count'] == 1

    def test_invalid_input_type_raises(self):
        """Non-array, non-object JSON should raise ValueError."""
        with pytest.raises(ValueError):
            parse_slack_export('"just a string"')


# ── TestSlackIntegration ─────────────────────────────────────────────

class TestSlackIntegration:
    """End-to-end tests using the sample data files."""

    @pytest.fixture
    def sample_data(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        users_path = os.path.join(base, 'examples', 'slack', 'users.json')
        msgs_path = os.path.join(
            base, 'examples', 'slack', 'incident-channel', '2024-10-15.json')
        with open(users_path) as f:
            users_json = f.read()
        with open(msgs_path) as f:
            messages_json = f.read()
        return messages_json, users_json

    def test_end_to_end(self, sample_data):
        messages_json, users_json = sample_data
        result = parse_slack_export(messages_json, users_json)
        assert result['timeline']
        assert result['slack_metadata']['message_count'] > 0

    def test_channel_join_filtered(self, sample_data):
        messages_json, users_json = sample_data
        result = parse_slack_export(messages_json, users_json)
        # The sample has 18 messages, 1 channel_join → 17 parsed
        raw_count = len(json.loads(messages_json))
        parsed = result['slack_metadata']['message_count']
        skipped = result['slack_metadata']['skipped_count']
        assert parsed + skipped == raw_count
        assert skipped >= 1  # at least the channel_join

    def test_bot_messages_kept(self, sample_data):
        messages_json, users_json = sample_data
        result = parse_slack_export(messages_json, users_json)
        # PagerDuty bot message should be in timeline
        all_text = ' '.join(e['text'] for e in result['timeline'])
        assert 'PagerDuty' in all_text or 'SEV-2' in all_text or 'checkout-db-primary' in all_text

    def test_actors_are_display_names(self, sample_data):
        messages_json, users_json = sample_data
        result = parse_slack_export(messages_json, users_json)
        actors = set(e.get('actor', '') for e in result['timeline'])
        # No raw user IDs in actors
        for actor in actors:
            if actor:
                assert not actor.startswith('U0'), f"Raw user ID in actors: {actor}"

    def test_slack_formatting_cleaned(self, sample_data):
        messages_json, users_json = sample_data
        result = parse_slack_export(messages_json, users_json)
        all_text = ' '.join(e['text'] for e in result['timeline'])
        assert '<@' not in all_text
        assert '<#' not in all_text
        assert '<!channel>' not in all_text

    def test_ir_phases_present(self, sample_data):
        messages_json, users_json = sample_data
        result = parse_slack_export(messages_json, users_json)
        assert result['ir_phases']

    def test_metrics_computed(self, sample_data):
        messages_json, users_json = sample_data
        result = parse_slack_export(messages_json, users_json)
        metrics = result['metrics']
        assert metrics['num_events'] > 0
        assert metrics['num_responders'] > 0
        assert 'duration' in metrics or 'duration_seconds' in metrics


# ── TestCoinfluxIntegration ──────────────────────────────────────────

class TestCoinfluxIntegration:
    """End-to-end tests using the coinflux export sample data."""

    @pytest.fixture
    def coinflux_data(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        users_path = os.path.join(
            base, 'examples', 'coinflux-export', 'users.json')
        msgs_path = os.path.join(
            base, 'examples', 'coinflux-export', 'incidents-sev1',
            '2023-11-14.json')
        with open(users_path) as f:
            users_json = f.read()
        with open(msgs_path) as f:
            messages_json = f.read()
        return messages_json, users_json

    def test_carol_actor_preserved(self, coinflux_data):
        """carol.dev should appear as actor, not filtered as domain."""
        messages_json, users_json = coinflux_data
        result = parse_slack_export(messages_json, users_json)
        actors = set(e.get('actor', '') for e in result['timeline'])
        assert 'carol.dev' in actors

    def test_bot_actors_correct(self, coinflux_data):
        """Bot messages should be attributed to bot names, not mentioned users."""
        messages_json, users_json = coinflux_data
        result = parse_slack_export(messages_json, users_json)
        # Find the PagerDuty message (contains "Incident #892 Triggered")
        for event in result['timeline']:
            if 'Incident #892 Triggered' in event['text']:
                assert event.get('actor') == 'PagerDuty', (
                    f"PagerDuty message attributed to {event.get('actor')}")
                break

    def test_github_bot_actor(self, coinflux_data):
        """GitHub bot message should be attributed to GitHub."""
        messages_json, users_json = coinflux_data
        result = parse_slack_export(messages_json, users_json)
        for event in result['timeline']:
            if 'Pull Request merged' in event['text']:
                assert event.get('actor') == 'GitHub', (
                    f"GitHub message attributed to {event.get('actor')}")
                break

    def test_responder_count(self, coinflux_data):
        """Should count all actors including those with TLD-like names."""
        messages_json, users_json = coinflux_data
        result = parse_slack_export(messages_json, users_json)
        assert result['metrics']['num_responders'] >= 4

    def test_no_raw_user_ids(self, coinflux_data):
        """No U_ or B_ prefixed IDs should leak into actor fields."""
        messages_json, users_json = coinflux_data
        result = parse_slack_export(messages_json, users_json)
        for event in result['timeline']:
            actor = event.get('actor', '')
            if actor:
                assert not actor.startswith('U_'), f"Raw user ID: {actor}"
                assert not actor.startswith('B_'), f"Raw bot ID: {actor}"


# ── TestNoiseFiltering ──────────────────────────────────────────────

def _relevant_msg(actor, text):
    """Build a NormalizedMessage for relevance testing."""
    return NormalizedMessage(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        actor=actor, text=text,
        raw=text, source='slack',
    )


class TestNoiseFiltering:
    """Tests for _is_incident_relevant noise filtering."""

    def test_noise_bot_filtered(self):
        msg = _relevant_msg('BirthdayBot', 'Happy Birthday to Jim!')
        assert _is_incident_relevant(msg) is False

    def test_ops_bot_kept(self):
        msg = _relevant_msg('Datadog', 'Monitor Triggered')
        assert _is_incident_relevant(msg) is True

    def test_noise_phrase_filtered(self):
        msg = _relevant_msg('jim.product', 'Anyone for tacos today?')
        assert _is_incident_relevant(msg) is False

    def test_giphy_command_filtered(self):
        msg = _relevant_msg('mike.junior', '/giphy fingers crossed')
        assert _is_incident_relevant(msg) is False

    def test_incident_keyword_kept(self):
        msg = _relevant_msg('sarah.eng', 'We are down. Get on Zoom.')
        assert _is_incident_relevant(msg) is True

    def test_default_keeps_ambiguous_message(self):
        msg = _relevant_msg('sarah.eng', 'Can you look at that?')
        assert _is_incident_relevant(msg) is True

    def test_noise_bot_case_insensitive(self):
        """BirthdayBot (mixed case) should still be filtered."""
        msg = _relevant_msg('BirthdayBot', 'Celebrating today!')
        assert _is_incident_relevant(msg) is False

    def test_ops_bot_case_insensitive(self):
        """PagerDuty (mixed case) should still be kept."""
        msg = _relevant_msg('PagerDuty', 'Incident triggered')
        assert _is_incident_relevant(msg) is True

    def test_no_actor_message_kept(self):
        msg = _relevant_msg(None, 'Some system message')
        assert _is_incident_relevant(msg) is True

    def test_noise_phrase_with_incident_keyword_kept(self):
        """Noise phrase + incident keyword = keep (escape hatch)."""
        msg = _relevant_msg('user', 'good morning, service is down')
        assert _is_incident_relevant(msg) is True

    def test_ops_bot_with_noise_phrase_kept(self):
        """Ops bot messages kept even if text looks like noise."""
        msg = _relevant_msg('Datadog', 'good morning check passed')
        assert _is_incident_relevant(msg) is True

    def test_drinks_at_filtered(self):
        msg = _relevant_msg('jim.product', 'Drinks at 5?')
        assert _is_incident_relevant(msg) is False

    def test_technical_message_kept(self):
        msg = _relevant_msg('sarah.eng', 'Deploying v2.0 of image-processor')
        assert _is_incident_relevant(msg) is True


# ── TestSlackMetadataFiltering ──────────────────────────────────────

class TestSlackMetadataFiltering:
    """Tests for noise filtering stats in slack_metadata."""

    def test_metadata_has_filtering_fields(self):
        messages = [
            _msg('1729000000.000001', text='Happy Birthday!',
                 subtype='bot_message', username='BirthdayBot'),
            _msg('1729000001.000001', user='U001', text='Service is down'),
        ]
        result = parse_slack_export(json.dumps(messages))
        meta = result['slack_metadata']
        assert 'total_messages' in meta
        assert 'noise_filtered' in meta
        assert meta['total_messages'] == 2
        assert meta['noise_filtered'] == 1
        assert meta['message_count'] == 1

    def test_no_noise_means_zero_filtered(self):
        messages = [
            _msg('1729000000.000001', user='U001', text='Investigating issue'),
        ]
        result = parse_slack_export(json.dumps(messages))
        meta = result['slack_metadata']
        assert meta['noise_filtered'] == 0
        assert meta['total_messages'] == meta['message_count']

    def test_all_noise_filtered(self):
        messages = [
            _msg('1729000000.000001', text='Happy Birthday!',
                 subtype='bot_message', username='BirthdayBot'),
            _msg('1729000001.000001', text='/giphy celebrate',
                 subtype='bot_message', username='Giphy'),
        ]
        result = parse_slack_export(json.dumps(messages))
        meta = result['slack_metadata']
        assert meta['noise_filtered'] == 2
        assert meta['message_count'] == 0


# ── TestCompanyExportIntegration ────────────────────────────────────

class TestCompanyExportIntegration:
    """End-to-end tests using the company-export multi-day sample."""

    @pytest.fixture
    def company_data(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        users_path = os.path.join(
            base, 'examples', 'company-export', 'users.json')
        msg_dir = os.path.join(
            base, 'examples', 'company-export', 'team-backend')
        if not os.path.exists(users_path):
            pytest.skip('company-export example data not found')
        with open(users_path) as f:
            users_json = f.read()
        import glob as globmod
        messages = {}
        for path in sorted(globmod.glob(os.path.join(msg_dir, '*.json'))):
            date_key = os.path.basename(path).replace('.json', '')
            with open(path) as f:
                messages[date_key] = json.load(f)
        return json.dumps(messages), users_json

    def test_birthday_bot_filtered(self, company_data):
        messages_json, users_json = company_data
        result = parse_slack_export(messages_json, users_json)
        all_text = ' '.join(e['text'] for e in result['timeline'])
        assert 'Happy Birthday' not in all_text

    def test_giphy_filtered(self, company_data):
        messages_json, users_json = company_data
        result = parse_slack_export(messages_json, users_json)
        all_text = ' '.join(e['text'] for e in result['timeline'])
        assert '/giphy' not in all_text

    def test_tacos_filtered(self, company_data):
        messages_json, users_json = company_data
        result = parse_slack_export(messages_json, users_json)
        all_text = ' '.join(e['text'] for e in result['timeline'])
        assert 'tacos' not in all_text

    def test_datadog_alerts_kept(self, company_data):
        messages_json, users_json = company_data
        result = parse_slack_export(messages_json, users_json)
        actors = [e.get('actor') for e in result['timeline']]
        assert 'Datadog' in actors

    def test_noise_filtered_count_positive(self, company_data):
        messages_json, users_json = company_data
        result = parse_slack_export(messages_json, users_json)
        assert result['slack_metadata']['noise_filtered'] > 0

    def test_incident_duration_shorter_than_duration(self, company_data):
        messages_json, users_json = company_data
        result = parse_slack_export(messages_json, users_json)
        metrics = result['metrics']
        if 'incident_duration_seconds' in metrics and 'duration_seconds' in metrics:
            assert metrics['incident_duration_seconds'] < metrics['duration_seconds']

    def test_jira_deployments_kept(self, company_data):
        messages_json, users_json = company_data
        result = parse_slack_export(messages_json, users_json)
        all_text = ' '.join(e['text'] for e in result['timeline'])
        assert 'Deployment' in all_text or 'SUCCESS' in all_text
