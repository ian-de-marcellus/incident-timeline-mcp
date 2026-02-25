"""
Core extraction logic for incident timeline analysis.
Uses patterns from patterns.py to extract structured information.
"""

import re
from datetime import datetime
from typing import List, Dict, Optional
from patterns import (
    TIMESTAMP_PATTERNS,
    ACTOR_PATTERNS,
    ACTION_KEYWORDS,
    SEVERITY_KEYWORDS,
    ENTITY_PATTERNS,
    INFRA_KEYWORDS,
    KNOWN_TLDS,
)


# Sentinel date for time-only timestamps (no date component).
# Allows time-only values to be sorted among themselves.
_SENTINEL_DATE = datetime(1970, 1, 1)


def _parse_timestamp_str(timestamp_str: str) -> Optional[datetime]:
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
        elif len(parts) == 2:
            return _SENTINEL_DATE.replace(
                hour=int(parts[0]), minute=int(parts[1]))
    except (ValueError, IndexError):
        pass

    return None


def extract_timeline(text: str) -> List[Dict[str, str]]:
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


def _find_timestamp(text: str) -> Optional[str]:
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
        # Look at ~20 chars before timestamp
        context_before = text_lower[max(0, timestamp_index-20):timestamp_index]
        
        for word in false_positive_words:
            if word in context_before:
                return False
    
    return True


def _find_actor(text: str) -> Optional[str]:
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


def identify_actions(text: str) -> List[Dict[str, str]]:
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


def extract_entities(text: str) -> Dict[str, List[str]]:
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
    entities = {
        'services': [],
        'ips': [],
        'domains': [],
    }
    
    text_lower = text.lower()
    
    # Extract services — two strategies:
    # 1. Names ending in known suffixes (authservice, payment-api)
    for match in re.finditer(ENTITY_PATTERNS['service_suffix'], text_lower):
        service = match.group(1)
        if service not in entities['services']:
            entities['services'].append(service)
    # 2. Compound names with infrastructure keywords (checkout-db-primary)
    for match in re.finditer(ENTITY_PATTERNS['service_compound'], text_lower):
        service = match.group(1)
        if _is_likely_service(service) and service not in entities['services']:
            entities['services'].append(service)
    
    # Extract IPs
    ip_pattern = ENTITY_PATTERNS['ip']
    for match in re.finditer(ip_pattern, text):
        ip = match.group(1)
        if _is_valid_ip(ip) and ip not in entities['ips']:
            entities['ips'].append(ip)
    
    # Extract domains
    domain_pattern = ENTITY_PATTERNS['domain']
    for match in re.finditer(domain_pattern, text_lower):
        domain = match.group(1)
        if _is_likely_domain(domain) and domain not in entities['domains']:
            entities['domains'].append(domain)
    
    return entities


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
    if len(domain) < 5:
        return False

    # Filter common false positives
    false_positives = ['example.com', 'test.com', 'localhost.local']
    if domain in false_positives:
        return False

    # Check that the TLD is a known one (filters firstname.lastname patterns
    # like "sarah.chen" where "chen" is not a recognized TLD)
    tld = domain.rsplit('.', 1)[-1]
    if tld not in KNOWN_TLDS:
        return False

    return True


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
    context_before = line[max(0, keyword_idx - 40):keyword_idx]
    return any(neg in context_before for neg in negation_context)


def _severity_keyword_in_line(line_lower: str, keyword: str) -> bool:
    """Check if a severity keyword appears non-negated in a lowercased line."""
    pattern = r'\b' + re.escape(keyword) + r'\b'
    return bool(re.search(pattern, line_lower)) and not _is_negated_severity(line_lower, keyword)


def _detect_line_severity(line: str) -> Optional[Dict[str, str]]:
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


def _build_severity_timeline(events: List[Dict]) -> List[Dict]:
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


def _compute_metrics(timeline: List[Dict], actions: List[Dict]) -> Dict:
    """
    Compute incident metrics from sorted timeline and actions.

    Returns dict with num_events, num_responders, duration, duration_seconds,
    and time_to_resolve (when a "resolved" action is found).
    """
    metrics = {
        'num_events': len(timeline),
        'num_responders': len(set(
            e['actor'] for e in timeline if e.get('actor')
        )),
    }

    # Duration: last timestamp - first timestamp
    parsed = [e for e in timeline if e.get('timestamp')]
    if len(parsed) >= 2:
        first = datetime.fromisoformat(parsed[0]['timestamp'])
        last = datetime.fromisoformat(parsed[-1]['timestamp'])
        delta = last - first
        metrics['duration_seconds'] = int(delta.total_seconds())
        minutes = int(delta.total_seconds()) // 60
        if minutes >= 60:
            metrics['duration'] = f"{minutes // 60}h {minutes % 60}m"
        else:
            metrics['duration'] = f"{minutes}m"

    # TTR heuristic: find last "resolved" action and compute time from start
    if parsed:
        for action in reversed(actions):
            if action['action'] == 'resolved' and action['category'] == 'status':
                for event in timeline:
                    if event['text'] == action['context'] and event.get('timestamp'):
                        first_ts = datetime.fromisoformat(parsed[0]['timestamp'])
                        resolve_ts = datetime.fromisoformat(event['timestamp'])
                        ttr_delta = resolve_ts - first_ts
                        ttr_minutes = int(ttr_delta.total_seconds()) // 60
                        metrics['time_to_resolve'] = f"{ttr_minutes}m"
                        break
                break

    return metrics


def detect_severity(text: str) -> Dict[str, any]:
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
    if len(indicators) >= 3:
        confidence = 'high'
    elif len(indicators) >= 1:
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

def generate_summary(text: str) -> Dict[str, any]:
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
    # Run all extractors
    timeline = extract_timeline(text)
    actions = identify_actions(text)
    entities = extract_entities(text)
    severity = detect_severity(text)

    # Compute temporal analysis
    severity_timeline = _build_severity_timeline(timeline)
    metrics = _compute_metrics(timeline, actions)

    # Generate human-readable summary text
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

    # Metrics
    if metrics.get('duration'):
        summary_parts.append(f"Duration: {metrics['duration']}")
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

    summary_text = "\n".join(summary_parts) if summary_parts else "No significant data extracted"

    return {
        'timeline': timeline,
        'actions': actions,
        'entities': entities,
        'severity': severity,
        'severity_timeline': severity_timeline,
        'metrics': metrics,
        'summary_text': summary_text,
    }
