"""
Slack workspace export parser.

Converts Slack export JSON (messages + users) into normalized plaintext
that feeds through the existing extraction pipeline in extractors.py.

Slack export format reference:
- users.json: array of user objects with id, name, profile.display_name, etc.
- channel/YYYY-MM-DD.json: array of message objects with type, user, text, ts, etc.
- Text uses Slack mrkdwn: <@U...> mentions, <#C...|name> channels, <!here>, etc.
"""

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from models import NormalizedMessage
from extractors import _analyze_timeline
from patterns import (
    NOISE_BOT_NAMES, OPS_BOT_NAMES, NOISE_PHRASES,
    ACTION_KEYWORDS, SEVERITY_KEYWORDS, IR_PHASE_KEYWORDS,
)


# Message subtypes with no IR signal — channel lifecycle/metadata events
SKIP_SUBTYPES = frozenset([
    'channel_join', 'channel_leave', 'channel_topic', 'channel_purpose',
    'channel_name', 'channel_archive', 'channel_unarchive',
    'pinned_item', 'unpinned_item',
    'message_changed', 'message_deleted',
    'file_reply', 'file_mention',
    'group_join', 'group_leave', 'group_topic', 'group_purpose',
    'group_name', 'group_archive', 'group_unarchive',
])


def parse_users(users_data: List[dict]) -> Dict[str, str]:
    """
    Build a user_id -> display_name mapping from users.json data.

    Resolution priority:
    1. profile.display_name or top-level display_name (clean identifier)
    2. profile.real_name (normalized: lowercase, spaces -> dots)
    3. name field (Slack handle / username)
    4. raw user id
    """
    user_map = {}
    for user in users_data:
        uid = user.get('id', '')
        if not uid:
            continue

        profile = user.get('profile', {})
        display_name = (
            profile.get('display_name') or
            user.get('display_name') or ''
        ).strip()
        real_name = (profile.get('real_name') or '').strip()
        name = (user.get('name') or '').strip()

        if display_name:
            user_map[uid] = display_name
        elif real_name:
            user_map[uid] = real_name.lower().replace(' ', '.')
        elif name:
            user_map[uid] = name
        else:
            user_map[uid] = uid

    return user_map


def clean_slack_text(text: str, user_map: Dict[str, str]) -> str:
    """
    Clean Slack mrkdwn formatting into plain text.

    Handles: user mentions, channel links, broadcasts, subteam mentions,
    date formatting, URLs with labels, bare URLs, and HTML entities.
    """
    if not text:
        return text

    def _replace_angle_bracket(match):
        content = match.group(1)

        # User mention: <@U024BE7LH> or <@U024BE7LH|label>
        if content.startswith('@'):
            uid = content[1:].split('|')[0]
            return '@' + user_map.get(uid, uid)

        # Channel link: <#C024BE7LR|general> or <#C024BE7LR>
        if content.startswith('#'):
            parts = content[1:].split('|', 1)
            if len(parts) == 2:
                return '#' + parts[1]
            return '#' + parts[0]

        # Special broadcasts: <!here>, <!channel>, <!everyone>
        if content == '!here':
            return '@here'
        if content == '!channel':
            return '@channel'
        if content == '!everyone':
            return '@everyone'

        # Subteam mention: <!subteam^SAZ94|@oncall>
        if content.startswith('!subteam^'):
            parts = content.split('|', 1)
            if len(parts) == 2:
                return parts[1]
            return '@subteam'

        # Date formatting: <!date^...|fallback>
        if content.startswith('!date^'):
            parts = content.split('|', 1)
            if len(parts) == 2:
                return parts[1]
            return content

        # URL with label: <https://example.com|click here>
        if '|' in content:
            parts = content.split('|', 1)
            return parts[1]

        # Bare URL: <https://example.com>
        return content

    # Replace all <...> patterns
    text = re.sub(r'<([^>]+)>', _replace_angle_bracket, text)

    # HTML entity decoding (last — earlier steps may produce encoded chars)
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')

    return text


def _extract_message_text(msg: dict) -> str:
    """
    Build full text for a message, including attachment content.

    Bot messages often put the real details in attachments rather than
    the top-level text field.
    """
    parts = []
    main_text = msg.get('text', '') or ''
    if main_text:
        parts.append(main_text)

    # Extract text from attachments
    for attachment in msg.get('attachments', []):
        att_parts = []
        title = (attachment.get('title') or '').strip()
        att_text = (attachment.get('text') or '').strip()
        if title:
            att_parts.append(title)
        if att_text:
            att_parts.append(att_text)
        if not att_parts:
            fallback = (attachment.get('fallback') or '').strip()
            if fallback:
                att_parts.append(fallback)
        if att_parts:
            parts.append(' — '.join(att_parts) if len(att_parts) > 1
                         else att_parts[0])

    # Extract file titles (screenshots, logs, etc.)
    file_titles = [
        f['title'] for f in msg.get('files', [])
        if f.get('title')
    ]
    if file_titles:
        parts.append('[Files: ' + ', '.join(file_titles) + ']')

    # If still empty, try blocks (rich_text)
    if not parts:
        for block in msg.get('blocks', []):
            if block.get('type') == 'rich_text':
                for element in block.get('elements', []):
                    for item in element.get('elements', []):
                        if item.get('type') == 'text' and item.get('text'):
                            parts.append(item['text'])

    return ' '.join(parts) if parts else ''


def parse_slack_messages(
    messages_data: List[dict],
    user_map: Dict[str, str],
    skip_subtypes: Optional[frozenset] = None,
) -> tuple[List[NormalizedMessage], int]:
    """
    Parse Slack message JSON into NormalizedMessage objects.

    Returns (messages, skipped_count) tuple.
    """
    if skip_subtypes is None:
        skip_subtypes = SKIP_SUBTYPES

    messages = []
    skipped = 0

    for msg in messages_data:
        if msg.get('type') != 'message':
            skipped += 1
            continue

        subtype = msg.get('subtype')
        if subtype and subtype in skip_subtypes:
            skipped += 1
            continue

        # Parse timestamp
        ts_str = msg.get('ts', '')
        try:
            timestamp = datetime.fromtimestamp(float(ts_str), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            timestamp = None

        # Resolve actor
        if subtype == 'bot_message':
            actor = msg.get('username') or msg.get('bot_id') or None
        else:
            user_id = msg.get('user', '')
            actor = user_map.get(user_id, user_id) if user_id else None

        # Extract and clean text
        raw_text = _extract_message_text(msg)
        cleaned_text = clean_slack_text(raw_text, user_map)

        # Build metadata
        metadata = {}
        if msg.get('thread_ts'):
            metadata['thread_ts'] = msg['thread_ts']
        if msg.get('reactions'):
            metadata['reactions'] = msg['reactions']
        if msg.get('edited'):
            metadata['edited'] = msg['edited'].get('ts')
        if msg.get('bot_id'):
            metadata['bot_id'] = msg['bot_id']

        messages.append(NormalizedMessage(
            timestamp=timestamp,
            actor=actor,
            text=cleaned_text,
            raw=raw_text,
            source='slack',
            metadata=metadata,
        ))

    # Sort by timestamp (None timestamps go last)
    messages.sort(key=lambda m: m.timestamp or datetime.max.replace(tzinfo=timezone.utc))

    return messages, skipped


def reconstruct_plaintext(messages: List[NormalizedMessage]) -> str:
    """
    Convert NormalizedMessage list into plaintext for the extraction pipeline.

    Format: "2024-10-15T14:23:15Z actor: text" — one line per event.
    """
    lines = []
    for msg in messages:
        text = msg.text.replace('\n', ' ').strip()
        if not text:
            continue

        if msg.timestamp:
            ts = msg.timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            ts = ''

        if msg.actor and ts:
            lines.append(f"{ts} {msg.actor}: {text}")
        elif ts:
            lines.append(f"{ts} {text}")
        elif msg.actor:
            lines.append(f"{msg.actor}: {text}")
        else:
            lines.append(text)

    return '\n'.join(lines)


def _build_events_from_messages(messages: List[NormalizedMessage]) -> List[dict]:
    """
    Convert NormalizedMessages into timeline event dicts.

    Produces the same format as extract_timeline() but preserves
    trusted actors from the Slack user map instead of re-extracting.
    """
    events = []
    for msg in messages:
        text = msg.text.replace('\n', ' ').strip()
        if not text:
            continue
        event = {'text': text}
        if msg.timestamp:
            ts_str = msg.timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
            event['time'] = ts_str
            event['timestamp'] = msg.timestamp.isoformat()
        if msg.actor:
            event['actor'] = msg.actor
        events.append(event)
    return events


def _has_incident_keyword(text_lower: str) -> bool:
    """Check if text contains any incident-related keyword."""
    for keywords in ACTION_KEYWORDS.values():
        for kw in keywords:
            if kw in text_lower:
                return True
    for keywords in SEVERITY_KEYWORDS.values():
        for kw in keywords:
            if kw in text_lower:
                return True
    for keywords in IR_PHASE_KEYWORDS.values():
        for kw in keywords:
            if kw in text_lower:
                return True
    return False


def _is_incident_relevant(msg: NormalizedMessage) -> bool:
    """
    Determine if a NormalizedMessage is relevant to incident analysis.

    Decision order:
    1. Ops bot messages -> always keep
    2. Noise bot messages -> always filter
    3. Messages matching noise phrases -> filter (unless also has incident keyword)
    4. Default -> keep (permissive)
    """
    actor_lower = (msg.actor or '').lower()

    # 1. Ops bots: always relevant
    if actor_lower in OPS_BOT_NAMES:
        return True

    # 2. Noise bots: never relevant
    if actor_lower in NOISE_BOT_NAMES:
        return False

    text_lower = msg.text.lower()

    # 3. Noise phrases: filter unless also has incident keyword
    for phrase in NOISE_PHRASES:
        if phrase in text_lower:
            if _has_incident_keyword(text_lower):
                return True
            return False

    # 4. Default: keep
    return True


def parse_slack_export(
    messages_json: str,
    users_json: Optional[str] = None,
) -> dict:
    """
    Public entry point: parse Slack export JSON and run full analysis.

    Args:
        messages_json: JSON string — either:
            - A single array of messages (one day)
            - An object keyed by date with arrays as values (multi-day),
              e.g. {"2024-10-15": [...], "2024-10-16": [...]}
        users_json: Optional JSON string of users.json array

    Returns:
        Full incident summary dict with additional slack_metadata key.
    """
    raw = json.loads(messages_json)

    # Accept either a flat array or a date-keyed object
    if isinstance(raw, list):
        messages_data = raw
    elif isinstance(raw, dict):
        messages_data = []
        for key in sorted(raw.keys()):
            messages_data.extend(raw[key])
    else:
        raise ValueError(
            "messages_json must be a JSON array or date-keyed object")

    if users_json:
        users_data = json.loads(users_json)
        user_map = parse_users(users_data)
    else:
        user_map = {}

    normalized, skipped = parse_slack_messages(messages_data, user_map)

    # Noise filtering — remove irrelevant messages before analysis
    total_before_filter = len(normalized)
    normalized = [m for m in normalized if _is_incident_relevant(m)]
    noise_filtered = total_before_filter - len(normalized)

    # Build events directly from NormalizedMessages (preserves actors)
    # and plaintext for action/entity/severity extraction
    events = _build_events_from_messages(normalized)
    plaintext = reconstruct_plaintext(normalized)

    result = _analyze_timeline(events, plaintext)

    # Count threads and unique users (from filtered set)
    threaded = sum(1 for m in normalized if m.metadata.get('thread_ts'))
    actors = set(m.actor for m in normalized if m.actor)

    result['slack_metadata'] = {
        'total_messages': total_before_filter,
        'noise_filtered': noise_filtered,
        'message_count': len(normalized),
        'user_count': len(actors),
        'skipped_count': skipped,
        'threaded_count': threaded,
    }

    return result
