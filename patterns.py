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
# Note: Includes common present participle (-ing) and past tense forms
# Some less common verb forms may not be caught
ACTION_KEYWORDS = {
    'investigation': [
        'investigating', 'investigated',
        'checking', 'checked',
        'examining', 'examined',
        'analyzing', 'analyzed',
        'reviewing', 'reviewed',
        'debugging', 'debugged',
        'tracing', 'traced',
        'monitoring', 'monitored',
        'watching',
    ],
    'remediation': [
        'deploying', 'deployed',
        'rolling back', 'rolled back',
        'reverting', 'reverted',
        'restarting', 'restarted',
        'rebooting', 'rebooted',
        'fixing', 'fixed',
        'patching', 'patched',
        'updating', 'updated',
        'scaling', 'scaled',
        'killing', 'killed',
        'stopping', 'stopped',
    ],
    'communication': [
        'notifying', 'notified',
        'alerting', 'alerted',
        'paging', 'paged',
        'escalating', 'escalated',
        'confirming', 'confirmed',
        'acknowledging', 'acknowledged',
        'reporting', 'reported',
    ],
    'status': [
        'resolving', 'resolved',
        'mitigating', 'mitigated',
        'completing', 'completed',
        'starting', 'started',
        'initiating', 'initiated',
    ],
}

# Severity indicator keywords
SEVERITY_KEYWORDS = {
    'critical': ['critical', 'down', 'outage', 'offline', 'unavailable', 
                 'total failure', 'complete loss', 'service down'],
    'high': ['degraded', 'slow', 'timeout', 'elevated error', 
             'high error', 'error rate', 'performance issue',
             'jumped', 'spike', 'surged'],
    'medium': ['intermittent', 'occasional', 'sporadic', 'some users',
               'affecting some'],
    'low': ['minor', 'cosmetic', 'edge case', 'rare'],
}

# Entity patterns - systems, services, IPs, domains
ENTITY_PATTERNS = {
    'service': r'\b([a-z][a-z0-9_-]*(?:service|api|worker|job|daemon))\b',
    'ip': r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b',
    'domain': r'\b([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})\b',
}