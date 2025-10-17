"""
Core extraction logic for incident timeline analysis.
Uses patterns from patterns.py to extract structured information.
"""

import re
from typing import List, Dict, Optional
from patterns import (
    TIMESTAMP_PATTERNS,
    ACTOR_PATTERNS,
    ACTION_KEYWORDS,
    SEVERITY_KEYWORDS,
    ENTITY_PATTERNS,
)


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
        
        # Extract actor if present
        actor = _find_actor(line)
        
        # Create event entry
        event = {
            'time': timestamp,
            'text': line.strip(),
        }
        if actor:
            event['actor'] = actor
        
        events.append(event)
    
    # Sort by time (if possible)
    # For now, keep original order - we can add sorting later
    
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
                     'info', 'debug', 'system']
    
    # Filter common labels
    if actor.lower() in common_labels:
        return False
    
    # Filter domain names - check if it ends with common TLD
    common_tlds = ['.com', '.org', '.net', '.io', '.co', '.edu', '.gov']
    actor_lower = actor.lower()
    if any(actor_lower.endswith(tld) for tld in common_tlds):
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
        
        # Check each category of actions
        for category, keywords in ACTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in line_lower:
                    actions.append({
                        'action': keyword,
                        'category': category,
                        'context': line,
                    })
                    # Only record first action found per line
                    break
            if actions and actions[-1]['context'] == line:
                # Already found an action in this line
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
    
    # Extract services
    service_pattern = ENTITY_PATTERNS['service']
    for match in re.finditer(service_pattern, text_lower):
        service = match.group(1)
        if service not in entities['services']:
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


def _is_likely_domain(domain: str) -> bool:
    """
    Basic domain validation to filter false positives.
    
    Filters out:
    - Very short domains (likely false positives)
    - Domains that are just common words
    """
    # Filter very short domains (e.g., "a.b")
    if len(domain) < 5:
        return False
    
    # Filter common false positives
    false_positives = ['example.com', 'test.com', 'localhost.local']
    if domain in false_positives:
        return False
    
    return True

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
    text_lower = text.lower()
    
    # Count indicators for each severity level
    severity_scores = {
        'critical': [],
        'high': [],
        'medium': [],
        'low': [],
    }
    
    for level, keywords in SEVERITY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                severity_scores[level].append(keyword)
    
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
    
    return {
        'level': level,
        'confidence': confidence,
        'indicators': indicators,
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
    
    # Generate human-readable summary text
    summary_parts = []
    
    # Severity
    if severity['level'] != 'unknown':
        summary_parts.append(
            f"Severity: {severity['level'].upper()} "
            f"(confidence: {severity['confidence']})"
        )
    
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
        'summary_text': summary_text,
    }