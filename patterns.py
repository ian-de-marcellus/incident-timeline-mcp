"""
Pattern definitions for incident text analysis.
Contains regex patterns and keyword lists for extracting structured data.
"""

import re

# Timestamp patterns - matches common time formats in incident logs
# Note: Some ambiguous patterns (like "ratio of 3:45") will match and are
# filtered by context analysis in extractors.py
# Ordered from most specific to least specific (dict maintains insertion order in Python 3.7+)
TIMESTAMP_PATTERNS = {
    'full_datetime': r'\b(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}(?::\d{2})?)\b',
    'time_with_seconds': r'(?<![:\w])([0-2]?\d):([0-5]\d):([0-5]\d)(?!:\d)\b',
    'simple_time': r'(?<![:\w])([0-2]?\d):([0-5]\d)(?!:\d)\b',
}

# Actor/person patterns - identifies who is taking action
# Note: Names with lowercase particles (de, von, van) are not captured
ACTOR_PATTERNS = {
    'mention': r'@([\w.-]+)',  # Slack-style @mentions: @sarah, @mike.jones
    'name_colon': r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?):',  # "Sarah:", "Mike Jones:"
}

# Action verb patterns - common incident response actions
ACTION_KEYWORDS = {
    'investigation': [
        'investigating', 'checked', 'examined', 'analyzed', 'reviewing',
        'debugged', 'traced', 'monitoring', 'watching',
    ],
    'remediation': [
        'deployed', 'rolled back', 'reverted', 'restarted', 'rebooted',
        'fixed', 'patched', 'updated', 'scaled', 'killed', 'stopped',
    ],
    'communication': [
        'notified', 'alerted', 'paged', 'escalated', 'confirmed',
        'acknowledged', 'reported',
    ],
    'status': [
        'resolved', 'mitigated', 'completed', 'started', 'initiated',
    ],
}

# Severity indicator keywords
SEVERITY_KEYWORDS = {
    'critical': ['critical', 'down', 'outage', 'offline', 'unavailable', 
                 'total failure', 'complete loss'],
    'high': ['degraded', 'slow', 'timeout', 'elevated errors', 
             'high error rate', 'performance issues'],
    'medium': ['intermittent', 'occasional', 'sporadic', 'some users'],
    'low': ['minor', 'cosmetic', 'edge case', 'rare'],
}

# Entity patterns - systems, services, IPs, domains
ENTITY_PATTERNS = {
    'service': r'\b([a-z][a-z0-9_-]*(?:service|api|worker|job|daemon))\b',
    'ip': r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b',
    'domain': r'\b([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})\b',
}