"""
Core extraction logic for incident timeline analysis.
Uses patterns from patterns.py to extract structured information.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any
from models import AnalysisState
from patterns import (
    TIMESTAMP_PATTERNS,
    ACTOR_PATTERNS,
    ACTION_KEYWORDS,
    SEVERITY_KEYWORDS,
    IR_PHASE_KEYWORDS,
    DISCUSSION_INDICATORS,
    ENTITY_PATTERNS,
    INFRA_KEYWORDS,
    KNOWN_TLDS,
)


logger = logging.getLogger(__name__)

# ── Tuning constants ────────────────────────────────────────────────
# Context windows (chars) for false-positive filtering
TIMESTAMP_CONTEXT_CHARS = 20   # chars before timestamp to check for "ratio", etc.
NEGATION_CONTEXT_CHARS = 40    # chars before severity keyword to check for negation

# Domain validation
MIN_DOMAIN_LENGTH = 5          # shortest valid domain (e.g. "a.io")

# Severity confidence thresholds (number of matching indicators)
CONFIDENCE_HIGH_THRESHOLD = 3
CONFIDENCE_MEDIUM_THRESHOLD = 1

# Sentinel date for time-only timestamps (no date component).
# Allows time-only values to be sorted among themselves.
_SENTINEL_DATE = datetime(1970, 1, 1)


def _parse_timestamp_str(timestamp_str: str) -> datetime | None:
    """
    Parse a raw timestamp string into a datetime object.

    Handles:
    - ISO 8601: "2024-10-15T14:23:15Z"
    - Full datetime: "2024-10-15 14:23" or "2024-10-15 14:23:45"
    - Time with seconds: "14:23:45" (uses sentinel date 1970-01-01)
    - Simple time: "14:23" (uses sentinel date 1970-01-01)
    """
    # ISO 8601
    if 'T' in timestamp_str and timestamp_str.endswith('Z'):
        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

    # Full datetime
    if re.match(r'\d{4}-\d{2}-\d{2}\s', timestamp_str):
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                return datetime.strptime(timestamp_str, fmt)
            except ValueError:
                continue

    # Time-only
    parts = timestamp_str.split(':')
    try:
        if len(parts) == 3:
            return _SENTINEL_DATE.replace(
                hour=int(parts[0]), minute=int(parts[1]), second=int(parts[2]))
        if len(parts) == 2:
            return _SENTINEL_DATE.replace(
                hour=int(parts[0]), minute=int(parts[1]))
    except (ValueError, IndexError):
        pass

    return None


def extract_timeline(text: str) -> list[dict[str, str]]:
    """
    Extract chronological events with timestamps from incident text.

    Args:
        text: Raw incident text (chat logs, notes, etc.)

    Returns:
        List of events, each with:
        - time: extracted timestamp
        - text: the line/context containing the event
        - actor: person who took action (if identified)

    Example:
        >>> text = "@sarah 14:23: Seeing elevated errors"
        >>> extract_timeline(text)
        [{'time': '14:23', 'text': '@sarah 14:23: Seeing elevated errors', 'actor': 'sarah'}]
    """
    events = []

    # Split text into lines for processing
    lines = text.strip().split('\n')

    for line in lines:
        # Strip whitespace from each line
        line = line.strip()

        # Skip empty lines
        if not line:
            continue

        # Try to find a timestamp in this line
        timestamp = _find_timestamp(line)
        if not timestamp:
            continue

        # Parse timestamp into datetime
        timestamp_parsed = _parse_timestamp_str(timestamp)

        # Extract actor if present
        actor = _find_actor(line)

        # Create event entry
        event = {
            'time': timestamp,
            'text': line.strip(),
        }
        if timestamp_parsed:
            event['timestamp'] = timestamp_parsed.isoformat()
        if actor:
            event['actor'] = actor

        events.append(event)

    # Sort by parsed timestamp (unparsed events go last)
    events.sort(key=lambda e: e.get('timestamp', '\xff'))

    return events


def _find_timestamp(text: str) -> str | None:
    """
    Find first timestamp in text using TIMESTAMP_PATTERNS.
    Returns the timestamp string or None.
    """
    for pattern in TIMESTAMP_PATTERNS.values():
        match = re.search(pattern, text)
        if match:
            # Filter out false positives (context-based filtering)
            timestamp = match.group()
            if _is_likely_timestamp(text, timestamp):
                return timestamp
    return None


def _is_likely_timestamp(text: str, timestamp: str) -> bool:
    """
    Context-based filtering to reduce false positives.

    Filters out patterns like:
    - "error ratio of 3:45" (ratio, not time)
    - "running version 1:45" (version, not time)
    """
    text_lower = text.lower()

    # Check for false positive indicators
    false_positive_words = ['ratio', 'version', 'scaled']

    # Get text around the timestamp
    timestamp_index = text.find(timestamp)
    if timestamp_index > 0:
        context_before = text_lower[max(0, timestamp_index - TIMESTAMP_CONTEXT_CHARS):timestamp_index]

        for word in false_positive_words:
            if word in context_before:
                return False

    return True


def _find_actor(text: str) -> str | None:
    """
    Find actor (person) in text using ACTOR_PATTERNS.
    Returns actor name/username or None.
    """
    for pattern in ACTOR_PATTERNS.values():
        match = re.search(pattern, text)
        if match:
            actor = match.group(1)
            # Filter out common false positives (labels)
            if _is_likely_actor(actor):
                return actor
    return None


def _is_likely_actor(actor: str) -> bool:
    """
    Context-based filtering for actor names.

    Filters out common labels like:
    - Time, Error, Status, Note
    - Domain names (ending in .com, .org, etc.)
    """
    common_labels = ['time', 'error', 'status', 'note', 'warning',
                     'info', 'debug', 'system',
                     'channel', 'here', 'everyone']

    # Filter common labels
    if actor.lower() in common_labels:
        return False

    # Filter domain names - check if it ends with a known TLD
    actor_lower = actor.lower()
    if '.' in actor_lower:
        tld = actor_lower.rsplit('.', 1)[-1]
        if tld in KNOWN_TLDS:
            return False

    return True


def identify_actions(text: str) -> list[dict[str, str]]:
    """
    Identify actions taken during incident response.

    Args:
        text: Raw incident text

    Returns:
        List of actions found, each with:
        - action: the action keyword
        - category: type of action (investigation, remediation, etc.)
        - context: the line where action was found

    Example:
        >>> text = "@sarah deployed fix to production"
        >>> identify_actions(text)
        [{'action': 'deployed', 'category': 'remediation',
          'context': '@sarah deployed fix to production'}]
    """
    actions = []
    lines = text.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        line_lower = line.lower()

        # Check each category of actions (word-boundary matching to avoid
        # substring collisions like "scaled" matching inside "escalated").
        # Only record the first action found per line.
        found = False
        for category, keywords in ACTION_KEYWORDS.items():
            for keyword in keywords:
                pattern = r'\b' + re.escape(keyword) + r'\b'
                if re.search(pattern, line_lower):
                    actions.append({
                        'action': keyword,
                        'category': category,
                        'context': line,
                    })
                    found = True
                    break
            if found:
                break

    return actions


def extract_entities(text: str) -> dict[str, list[str]]:
    """
    Extract entities (systems, services, IPs, domains) from incident text.

    Args:
        text: Raw incident text

    Returns:
        Dict with entity types as keys:
        - services: list of service names found
        - ips: list of IP addresses found
        - domains: list of domains found

    Example:
        >>> text = "payment-service at 10.0.0.1 timeout from api.example.com"
        >>> extract_entities(text)
        {'services': ['payment-service'], 'ips': ['10.0.0.1'],
         'domains': ['api.example.com']}
    """
    services: set[str] = set()
    ips: set[str] = set()
    domains: set[str] = set()

    text_lower = text.lower()

    # Extract services — two strategies:
    # 1. Names ending in known suffixes (authservice, payment-api)
    for match in re.finditer(ENTITY_PATTERNS['service_suffix'], text_lower):
        services.add(match.group(1))
    # 2. Compound names with infrastructure keywords (checkout-db-primary)
    for match in re.finditer(ENTITY_PATTERNS['service_compound'], text_lower):
        service = match.group(1)
        if _is_likely_service(service):
            services.add(service)

    # Extract IPs
    for match in re.finditer(ENTITY_PATTERNS['ip'], text):
        ip = match.group(1)
        if _is_valid_ip(ip):
            ips.add(ip)

    # Extract domains
    for match in re.finditer(ENTITY_PATTERNS['domain'], text_lower):
        domain = match.group(1)
        if _is_likely_domain(domain):
            domains.add(domain)

    return {
        'services': sorted(services),
        'ips': sorted(ips),
        'domains': sorted(domains),
    }


def _is_valid_ip(ip: str) -> bool:
    """
    Validate that IP address has valid octets (0-255).
    Filters out invalid IPs like 999.999.999.999.
    """
    octets = ip.split('.')
    try:
        return all(0 <= int(octet) <= 255 for octet in octets)
    except ValueError:
        return False


def _is_likely_service(name: str) -> bool:
    """
    Validate that a compound name is likely a service/infrastructure name.
    Checks whether any segment of the name is a known infrastructure keyword.

    Examples:
        >>> _is_likely_service('checkout-db-primary')   # True (db, primary)
        >>> _is_likely_service('redis-cache-03')         # True (cache)
        >>> _is_likely_service('rolled-back')            # False
    """
    segments = re.split(r'[-_]', name)
    return any(seg in INFRA_KEYWORDS for seg in segments)


def _is_likely_domain(domain: str) -> bool:
    """
    Domain validation to filter false positives.

    Filters out:
    - Very short domains (likely false positives)
    - Domains with unrecognized TLDs (catches firstname.lastname like sarah.chen)
    - Known test/placeholder domains
    """
    # Filter very short domains (e.g., "a.b")
    if len(domain) < MIN_DOMAIN_LENGTH:
        return False

    # Filter common false positives
    false_positives = ['example.com', 'test.com', 'localhost.local']
    if domain in false_positives:
        return False

    # Check that the TLD is a known one (filters firstname.lastname patterns
    # like "sarah.chen" where "chen" is not a recognized TLD)
    tld = domain.rsplit('.', 1)[-1]
    return tld in KNOWN_TLDS


def _is_negated_severity(line: str, keyword: str) -> bool:
    """
    Check if a severity keyword is negated by surrounding context.

    Looks for negation/resolution words in the ~40 chars before the keyword
    on the same line. This catches patterns like "no longer down",
    "back to normal levels", "resolved the outage".
    """
    negation_context = ['no longer', 'resolved', 'fixed', 'restored',
                        'back to normal', 'returned to', 'back down to']
    keyword_idx = line.find(keyword)
    if keyword_idx < 0:
        return False
    # Hyphenated negation prefix (e.g., "non-critical", "pre-degraded")
    if keyword_idx > 0 and line[keyword_idx - 1] == '-':
        return True
    context_before = line[max(0, keyword_idx - NEGATION_CONTEXT_CHARS):keyword_idx]
    return any(neg in context_before for neg in negation_context)


def _severity_keyword_in_line(line_lower: str, keyword: str) -> bool:
    """Check if a severity keyword appears non-negated in a lowercased line."""
    pattern = r'\b' + re.escape(keyword) + r'\b'
    return bool(re.search(pattern, line_lower)) and not _is_negated_severity(line_lower, keyword)


def _detect_line_severity(line: str) -> dict[str, str] | None:
    """
    Assess severity of a single line.

    Returns {'level': ..., 'trigger': ...} for the highest-severity
    non-negated keyword found, or None if no severity signal present.
    """
    line_lower = line.lower()
    for level in ['critical', 'high', 'medium', 'low']:
        for keyword in SEVERITY_KEYWORDS[level]:
            if _severity_keyword_in_line(line_lower, keyword):
                return {'level': level, 'trigger': keyword}
    return None


def _build_severity_timeline(events: list[dict]) -> list[dict]:
    """
    Track severity changes across sorted timeline events.

    Only records transitions — if two consecutive events both have 'high'
    severity, only the first is recorded.
    """
    severity_timeline = []
    current_level = None
    for event in events:
        line_severity = _detect_line_severity(event['text'])
        if line_severity and line_severity['level'] != current_level:
            change = {
                'level': line_severity['level'],
                'trigger': line_severity['trigger'],
            }
            if event.get('timestamp'):
                change['timestamp'] = event['timestamp']
            severity_timeline.append(change)
            current_level = line_severity['level']
    return severity_timeline


def _find_incident_boundaries(
    timeline: list[dict],
) -> tuple:
    """
    Find incident start and end timestamps using keyword signals.

    Start: first event matching severity keywords or detection phase keywords.
    End: last event matching recovery or post_incident phase keywords.

    Returns (start_dt, end_dt) or (None, None) if no keyword boundaries found.
    """
    start_dt = None
    end_dt = None

    # Build flat keyword sets for efficient lookup
    start_keywords = []
    for keywords in SEVERITY_KEYWORDS.values():
        start_keywords.extend(keywords)
    start_keywords.extend(IR_PHASE_KEYWORDS.get('detection', []))

    end_keywords = []
    end_keywords.extend(IR_PHASE_KEYWORDS.get('recovery', []))
    end_keywords.extend(IR_PHASE_KEYWORDS.get('post_incident', []))

    for event in timeline:
        if not event.get('timestamp'):
            continue
        text_lower = event['text'].lower()

        if start_dt is None:
            for kw in start_keywords:
                if kw in text_lower:
                    start_dt = datetime.fromisoformat(event['timestamp'])
                    break

        for kw in end_keywords:
            if kw in text_lower:
                end_dt = datetime.fromisoformat(event['timestamp'])
                break

    return start_dt, end_dt


def _format_duration(minutes: int) -> str:
    """Format a minute count as 'Xh Ym' or 'Ym'."""
    if minutes >= 60:
        return f"{minutes // 60}h {minutes % 60}m"
    return f"{minutes}m"


def _compute_metrics(timeline: list[dict], actions: list[dict]) -> dict:
    """
    Compute incident metrics from sorted timeline and actions.

    Returns dict with num_events, num_responders, duration, duration_seconds,
    and time_to_resolve (when a "resolved" action is found).
    """
    metrics: dict[str, Any] = {
        'num_events': len(timeline),
        'num_responders': len({
            e['actor'] for e in timeline if e.get('actor')
        }),
    }

    parsed = [e for e in timeline if e.get('timestamp')]

    # Wall-clock duration: first → last timestamp
    if len(parsed) >= 2:
        first = datetime.fromisoformat(parsed[0]['timestamp'])
        last = datetime.fromisoformat(parsed[-1]['timestamp'])
        delta = last - first
        metrics['duration_seconds'] = int(delta.total_seconds())
        metrics['duration'] = _format_duration(int(delta.total_seconds()) // 60)

    # Incident-aware duration: severity keyword → recovery keyword
    _compute_incident_duration(timeline, metrics)

    # TTR: first event → last "resolved" action
    _compute_time_to_resolve(parsed, timeline, actions, metrics)

    # Phase-aware metrics: TTD and TTC from IR phase data
    _compute_phase_metrics(parsed, timeline, metrics)

    return metrics


def _compute_incident_duration(
    timeline: list[dict], metrics: dict[str, Any],
) -> None:
    """Add incident_duration based on severity/recovery keyword boundaries."""
    incident_start, incident_end = _find_incident_boundaries(timeline)
    if incident_start and incident_end and incident_end > incident_start:
        inc_delta = incident_end - incident_start
        metrics['incident_duration_seconds'] = int(inc_delta.total_seconds())
        metrics['incident_duration'] = _format_duration(
            int(inc_delta.total_seconds()) // 60
        )


def _compute_time_to_resolve(
    parsed: list[dict], timeline: list[dict],
    actions: list[dict], metrics: dict[str, Any],
) -> None:
    """Add time_to_resolve from first event to last 'resolved' action."""
    if not parsed:
        return
    for action in reversed(actions):
        if action['action'] == 'resolved' and action['category'] == 'status':
            for event in timeline:
                if event['text'] == action['context'] and event.get('timestamp'):
                    first_ts = datetime.fromisoformat(parsed[0]['timestamp'])
                    resolve_ts = datetime.fromisoformat(event['timestamp'])
                    ttr_delta = resolve_ts - first_ts
                    metrics['time_to_resolve'] = _format_duration(
                        int(ttr_delta.total_seconds()) // 60
                    )
                    return
            return


def _compute_phase_metrics(
    parsed: list[dict], timeline: list[dict], metrics: dict[str, Any],
) -> None:
    """Add TTD and TTC from IR phase classifications."""
    phase_events = [e for e in timeline if e.get('ir_phase')]
    if not phase_events or not parsed:
        return

    first_ts = datetime.fromisoformat(parsed[0]['timestamp'])

    # TTC: time to first containment event
    containment_events = [
        e for e in phase_events
        if e.get('ir_phase') == 'containment' and e.get('timestamp')
    ]
    if containment_events:
        contain_ts = datetime.fromisoformat(containment_events[0]['timestamp'])
        metrics['time_to_contain'] = _format_duration(
            int((contain_ts - first_ts).total_seconds()) // 60
        )


# ── NIST SP 800-61 IR phase mapping ─────────────────────────────────

# Canonical phase order (used for tie-breaking and display)
_PHASE_ORDER = [
    'detection', 'analysis', 'containment',
    'eradication', 'recovery', 'post_incident',
]

# Downgrade map: discussion of an action shifts it one phase earlier
_DOWNGRADE_MAP = {
    'containment': 'analysis',
    'eradication': 'containment',
    'recovery': 'containment',
}

# Tie-breaking priority: later/more-specific phases win
_PHASE_PRIORITY = {phase: i for i, phase in enumerate(_PHASE_ORDER)}


def _classify_ir_phase(
    line: str,
    event_index: int,
    total_events: int,
    containment_seen: bool,
) -> dict[str, str]:
    """
    Classify a single event line into a NIST SP 800-61 IR phase.

    Three-pass classification:
    1. Keyword matching against IR_PHASE_KEYWORDS
    2. Temporal/positional heuristics
    3. Confidence scoring

    Returns {'ir_phase': ..., 'phase_confidence': ...}
    """
    line_lower = line.lower()
    position = event_index / max(total_events - 1, 1)

    # ── Pass 1: keyword matching ──
    matched_phases = []
    for phase, keywords in IR_PHASE_KEYWORDS.items():
        for keyword in keywords:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, line_lower):
                matched_phases.append(phase)
                break  # one match per phase is enough

    # ── Pass 2: temporal heuristics ──
    is_discussion = any(ind in line_lower for ind in DISCUSSION_INDICATORS)

    if matched_phases:
        # Apply discussion downgrade
        if is_discussion:
            matched_phases = [
                _DOWNGRADE_MAP.get(p, p) for p in matched_phases
            ]

        # "monitoring"/"stable" early in incident → analysis, not recovery
        if position < 0.3:
            matched_phases = [
                'analysis' if p == 'recovery' else p
                for p in matched_phases
            ]

        # Containment/eradication disambiguation
        if not containment_seen:
            matched_phases = [
                'containment' if p == 'eradication' else p
                for p in matched_phases
            ]

        # Tie-break: highest priority (later phase) wins
        phase = max(matched_phases, key=lambda p: _PHASE_PRIORITY[p])

        # Confidence: keyword present + temporally consistent
        expected_range = _expected_position_range(phase)
        confidence = 'high' if expected_range[0] <= position <= expected_range[1] else 'medium'
    else:
        # ── No keyword match — positional fallback ──
        if position < 0.15:
            phase = 'detection'
        elif position > 0.85:
            phase = 'post_incident'
        elif position > 0.7:
            phase = 'recovery'
        else:
            phase = 'analysis'
        confidence = 'low'

    return {'ir_phase': phase, 'phase_confidence': confidence}


def _expected_position_range(phase: str) -> tuple:
    """Return (min_pos, max_pos) where a phase is temporally expected."""
    ranges = {
        'detection':     (0.0, 0.3),
        'analysis':      (0.0, 0.7),
        'containment':   (0.1, 0.8),
        'eradication':   (0.3, 1.0),
        'recovery':      (0.4, 1.0),
        'post_incident': (0.6, 1.0),
    }
    return ranges.get(phase, (0.0, 1.0))


def _classify_timeline_phases(events: list[dict]) -> list[dict]:
    """
    Classify each event in a sorted timeline into an IR phase.

    Iterates events in order, tracks containment_seen state, and adds
    'ir_phase' and 'phase_confidence' fields to each event in-place.
    """
    if not events:
        return events

    total = len(events)
    containment_seen = False

    for i, event in enumerate(events):
        result = _classify_ir_phase(
            event['text'], i, total, containment_seen,
        )
        event['ir_phase'] = result['ir_phase']
        event['phase_confidence'] = result['phase_confidence']
        if result['ir_phase'] == 'containment':
            containment_seen = True

    return events


def _group_by_phase(events: list[dict]) -> dict[str, list[dict]]:
    """
    Group classified events by IR phase in canonical NIST order.

    Only includes phases that have at least one event.
    """
    groups = {}
    for event in events:
        phase = event.get('ir_phase')
        if phase:
            groups.setdefault(phase, []).append(event)

    # Return in canonical order, omitting empty phases
    return {
        phase: groups[phase]
        for phase in _PHASE_ORDER
        if phase in groups
    }


def map_to_framework(text: str, framework: str = 'nist_800_61') -> dict:
    """
    Map incident text to NIST SP 800-61 IR framework phases.

    Runs the full pipeline: extraction → phase classification → grouping → metrics.

    Returns dict with:
    - framework: framework identifier
    - timeline: events with ir_phase and phase_confidence fields
    - phases: events grouped by IR phase (canonical order)
    - phase_summary: human-readable phase progression string
    - metrics: incident metrics including TTD and TTC
    """
    # 1. Extract and sort timeline
    timeline = extract_timeline(text)
    actions = identify_actions(text)

    # 2. Classify phases
    _classify_timeline_phases(timeline)

    # 3. Group by phase
    phases = _group_by_phase(timeline)

    # 4. Compute metrics (with phase-aware TTD/TTC)
    metrics = _compute_metrics(timeline, actions)

    # 5. Build phase summary string
    phase_summary = _build_phase_summary(phases)

    return {
        'framework': framework,
        'timeline': timeline,
        'phases': phases,
        'phase_summary': phase_summary,
        'metrics': metrics,
    }


def _extract_hhmm(time_str: str) -> str:
    """Extract HH:MM from any timestamp format for display."""
    # ISO 8601: "2024-10-15T14:23:15Z" → "14:23"
    if 'T' in time_str:
        t_part = time_str.split('T')[1]
        return t_part[:5]
    # Full datetime: "2024-10-15 14:23:45" → "14:23"
    if ' ' in time_str and '-' in time_str.split(' ', maxsplit=1)[0]:
        t_part = time_str.split(' ')[1]
        return t_part[:5]
    # Already HH:MM or HH:MM:SS → take first 5 chars
    return time_str[:5]


def _build_phase_summary(phases: dict[str, list[dict]]) -> str:
    """
    Build a human-readable phase progression string.

    Example: "Detection (14:23) → Analysis (14:24-14:29) → Containment (14:30)"
    """
    if not phases:
        return ''

    parts = []
    display_names = {
        'detection': 'Detection',
        'analysis': 'Analysis',
        'containment': 'Containment',
        'eradication': 'Eradication',
        'recovery': 'Recovery',
        'post_incident': 'Post-Incident',
    }

    for phase, events in phases.items():
        name = display_names.get(phase, phase)
        times = [e.get('time', '') for e in events if e.get('time')]
        if times:
            first = _extract_hhmm(times[0])
            last = _extract_hhmm(times[-1])
            if len(times) == 1 or first == last:
                parts.append(f"{name} ({first})")
            else:
                parts.append(f"{name} ({first}-{last})")
        else:
            parts.append(name)

    return ' -> '.join(parts)


def detect_severity(text: str) -> dict[str, Any]:
    """
    Detect incident severity based on keywords in text.

    Args:
        text: Raw incident text

    Returns:
        Dict with:
        - level: overall severity (critical/high/medium/low/unknown)
        - confidence: how confident we are (based on # of indicators)
        - indicators: list of keywords that influenced the decision

    Example:
        >>> text = "payment service is down, complete outage"
        >>> detect_severity(text)
        {'level': 'critical', 'confidence': 'high',
         'indicators': ['down', 'outage']}
    """
    lines = text.lower().strip().split('\n')

    # Count indicators for each severity level
    severity_scores = {
        'critical': [],
        'high': [],
        'medium': [],
        'low': [],
    }

    for level, keywords in SEVERITY_KEYWORDS.items():
        for keyword in keywords:
            # Count keyword once if it appears non-negated on any line
            for line in lines:
                if _severity_keyword_in_line(line, keyword):
                    severity_scores[level].append(keyword)
                    break

    # Determine overall severity (highest level with indicators)
    if severity_scores['critical']:
        level = 'critical'
        indicators = severity_scores['critical']
    elif severity_scores['high']:
        level = 'high'
        indicators = severity_scores['high']
    elif severity_scores['medium']:
        level = 'medium'
        indicators = severity_scores['medium']
    elif severity_scores['low']:
        level = 'low'
        indicators = severity_scores['low']
    else:
        level = 'unknown'
        indicators = []

    # Determine confidence based on number of indicators
    if len(indicators) >= CONFIDENCE_HIGH_THRESHOLD:
        confidence = 'high'
    elif len(indicators) >= CONFIDENCE_MEDIUM_THRESHOLD:
        confidence = 'medium'
    else:
        confidence = 'low'

    # After determining the level, collect ALL indicators
    all_indicators = []
    for level_indicators in severity_scores.values():
        all_indicators.extend(level_indicators)

    return {
        'level': level,
        'confidence': confidence,
        'indicators': all_indicators,  # Show everything found
    }

def _build_summary_text(
    state: AnalysisState,
    severity_timeline: list[dict],
    ir_phases: dict[str, list[dict]],
    metrics: dict,
) -> str:
    """Assemble human-readable summary text from analysis results."""
    timeline, actions, entities, severity = (
        state.events, state.actions, state.entities, state.severity,
    )
    summary_parts = []

    # Severity with evolution
    if severity['level'] != 'unknown':
        severity_line = (
            f"Severity: {severity['level'].upper()} "
            f"(confidence: {severity['confidence']})"
        )
        summary_parts.append(severity_line)
        if len(severity_timeline) > 1:
            evolution = ' -> '.join(s['level'] for s in severity_timeline)
            summary_parts.append(f"  Evolution: {evolution}")

    # Phase progression
    phase_summary = _build_phase_summary(ir_phases)
    if phase_summary:
        summary_parts.append(f"IR Phases: {phase_summary}")

    # Metrics
    if metrics.get('duration'):
        summary_parts.append(f"Duration: {metrics['duration']}")
    if metrics.get('incident_duration'):
        summary_parts.append(
            f"Incident duration: {metrics['incident_duration']}"
        )
    if metrics.get('time_to_contain'):
        summary_parts.append(f"Time to contain: {metrics['time_to_contain']}")
    if metrics.get('time_to_resolve'):
        summary_parts.append(f"Time to resolve: {metrics['time_to_resolve']}")
    if metrics['num_responders'] > 0:
        summary_parts.append(f"Responders: {metrics['num_responders']}")

    # Timeline summary
    if timeline:
        summary_parts.append(f"Timeline: {len(timeline)} events recorded")
        if timeline[0].get('time'):
            summary_parts.append(f"  First event: {timeline[0]['time']}")
        if timeline[-1].get('time'):
            summary_parts.append(f"  Last event: {timeline[-1]['time']}")

    # Actions summary
    if actions:
        action_categories = {}
        for action in actions:
            category = action['category']
            action_categories[category] = action_categories.get(category, 0) + 1

        summary_parts.append(f"Actions: {len(actions)} total")
        for category, count in action_categories.items():
            summary_parts.append(f"  {category}: {count}")

    # Entities summary
    entity_counts = {
        entity_type: len(entity_list)
        for entity_type, entity_list in entities.items()
        if entity_list
    }
    if entity_counts:
        summary_parts.append("Entities involved:")
        for entity_type, count in entity_counts.items():
            summary_parts.append(f"  {entity_type}: {count}")

    return "\n".join(summary_parts) if summary_parts else "No significant data extracted"


def format_report(result: dict) -> str:
    """Format a pipeline result dict as a human-readable report.

    Works with output from generate_summary() or parse_slack_export().
    """
    sections = []

    # Summary
    if result.get('summary_text'):
        sections.append(f"=== SUMMARY ===\n{result['summary_text']}")

    # Timeline with phase tags
    if result.get('timeline'):
        lines = []
        for event in result['timeline']:
            phase = event.get('ir_phase', 'unknown')
            time = event.get('time', '')
            actor = event.get('actor', '')
            text = event.get('text', '')
            if actor and text.startswith(actor):
                # Text already includes actor prefix from Slack parser
                lines.append(f"  [{phase}] {time} {text}")
            elif actor:
                lines.append(f"  [{phase}] {time} {actor}: {text}")
            else:
                lines.append(f"  [{phase}] {time} {text}")
        sections.append("=== TIMELINE ===\n" + "\n".join(lines))

    # Metrics
    if result.get('metrics'):
        metrics_json = json.dumps(result['metrics'], indent=2)
        sections.append(f"=== METRICS ===\n{metrics_json}")

    # Slack metadata (only present for Slack exports)
    if result.get('slack_metadata'):
        meta_json = json.dumps(result['slack_metadata'], indent=2)
        sections.append(f"=== SLACK METADATA ===\n{meta_json}")

    return "\n\n".join(sections)


def _get_llm_client():
    """Construct LLM client from config. Returns (client, level) or (None, 'none')."""
    try:
        from llm import ANTHROPIC_AVAILABLE
        if not ANTHROPIC_AVAILABLE:
            return None, 'none'
        from config import get_settings
        settings = get_settings()
        if not settings.anthropic_api_key or settings.llm_enrichment == 'none':
            return None, 'none'
        import anthropic
        return anthropic.Anthropic(api_key=settings.anthropic_api_key), settings.llm_enrichment
    except ImportError:
        return None, 'none'


def _enrich(state: AnalysisState, client, level: str) -> dict | None:
    """Run LLM enrichment with injected client. Returns dict or None."""
    try:
        from llm import enrich_timeline, DEFAULT_MODEL
        return enrich_timeline(
            state, client=client, model=DEFAULT_MODEL, level=level,
        )
    except Exception as e:
        logger.warning("LLM enrichment failed: %s", e)
        return None


def _apply_enrichment(state: AnalysisState, enrichment: dict) -> None:
    """Merge LLM enrichment results into existing analysis data."""
    events, actions, entities, severity = (
        state.events, state.actions, state.entities, state.severity,
    )

    # Phase updates: overwrite ir_phase, set confidence and source
    # Events classified as 'irrelevant' are removed from the timeline.
    irrelevant_texts: set[str] = set()
    if 'phase_updates' in enrichment:
        irrelevant_indices: set[int] = set()
        for update in enrichment['phase_updates']:
            idx = update['event_index']
            if 0 <= idx < len(events):
                if update['ir_phase'] == 'irrelevant':
                    irrelevant_indices.add(idx)
                else:
                    events[idx]['ir_phase'] = update['ir_phase']
                    events[idx]['phase_confidence'] = update['phase_confidence']
                    events[idx]['phase_source'] = 'llm'
        # Collect text of irrelevant events before removing them
        irrelevant_texts = {events[i]['text'] for i in irrelevant_indices}
        # Remove irrelevant events (iterate in reverse to preserve indices)
        for idx in sorted(irrelevant_indices, reverse=True):
            events.pop(idx)
        # Remove actions whose context contains removed event text
        # (action context includes timestamp+actor prefix, event text does not)
        actions[:] = [
            a for a in actions
            if not any(it in a['context'] for it in irrelevant_texts)
        ]

    # Severity: replace level/confidence/indicators
    if 'severity_update' in enrichment:
        update = enrichment['severity_update']
        severity['level'] = update['level']
        severity['confidence'] = update['confidence']
        severity['indicators'] = update['indicators']
        severity['source'] = 'llm'

    # Actions: append new actions (filtering any that reference removed events)
    if 'new_actions' in enrichment:
        for action in enrichment['new_actions']:
            if not any(it in action['context'] for it in irrelevant_texts):
                actions.append(action)

    # Entities: reclassify false-positive domains as persons
    if 'entity_updates' in enrichment:
        disambiguated = enrichment['entity_updates'].get('disambiguated', [])
        for item in disambiguated:
            if item.get('entity_type') == 'person':
                name = item.get('item', '')
                if name in entities.get('domains', []):
                    entities['domains'].remove(name)


def _analyze_timeline(
    events: list[dict],
    text: str,
    client=None,
    level: str = 'none',
) -> dict:
    """
    Run full analysis on pre-built timeline events.

    The events list provides the timeline (with actors, timestamps).
    The text is used for action/entity/severity extraction.
    Any source (plaintext extractor, Slack parser, etc.) can build
    events and feed them into this shared pipeline.

    Pass client and level to enable LLM enrichment. Without a client,
    enrichment is skipped entirely.
    """
    state = AnalysisState(
        events=events,
        text=text,
        actions=identify_actions(text),
        entities=extract_entities(text),
        severity=detect_severity(text),
    )

    _classify_timeline_phases(state.events)

    # LLM enrichment (no-op without client)
    if client and level != 'none':
        enrichment = _enrich(state, client, level)
        if enrichment:
            _apply_enrichment(state, enrichment)

    ir_phases = _group_by_phase(state.events)
    severity_timeline = _build_severity_timeline(state.events)
    metrics = _compute_metrics(state.events, state.actions)

    summary_text = _build_summary_text(
        state, severity_timeline, ir_phases, metrics,
    )

    return {
        'timeline': state.events,
        'actions': state.actions,
        'entities': state.entities,
        'severity': state.severity,
        'severity_timeline': severity_timeline,
        'ir_phases': ir_phases,
        'metrics': metrics,
        'summary_text': summary_text,
    }


def generate_summary(text: str) -> dict[str, Any]:
    """
    Generate comprehensive incident summary using all extractors.

    Args:
        text: Raw incident text

    Returns:
        Dict containing:
        - timeline: list of events with timestamps
        - actions: list of actions taken
        - entities: dict of services/ips/domains involved
        - severity: severity assessment
        - summary_text: human-readable summary

    Example:
        >>> text = "@sarah 14:23: payment-service down\\n@mike 14:25: deployed fix"
        >>> generate_summary(text)
        {'timeline': [...], 'actions': [...], 'entities': {...},
         'severity': {...}, 'summary_text': '...'}
    """
    timeline = extract_timeline(text)
    client, level = _get_llm_client()
    return _analyze_timeline(timeline, text, client=client, level=level)
