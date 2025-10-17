"""
Pattern definitions for incident text analysis.
Contains regex patterns and keyword lists for extracting structured data.
"""

import re

# Timestamp patterns - matches common time formats in incident logs
# Note: Some ambiguous patterns (like "ratio of 3:45") will match and are
# filtered by context analysis in extractors.py
TIMESTAMP_PATTERNS = [
    # Matches: 14:23, 09:45, 23:59
    # Negative lookbehind blocks word chars, colons, and single letter prefixes
    r'(?<![:\w])([0-2]?\d):([0-5]\d)(?!:)\b',
    
    # Matches: 2024-01-15 14:23, 2024-01-15 14:23:45
    r'\b(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}(?::\d{2})?)\b',
    
    # Matches: 14:23:45, with optional seconds
    # Negative lookahead prevents matching part of longer sequences
    r'(?<![:\w])([0-2]?\d):([0-5]\d):([0-5]\d)(?!:)\b',
]

# Actor/person patterns - identifies who is taking action
# Note: Names with lowercase particles (de, von, van) are not captured
ACTOR_PATTERNS = [
    # Slack-style @mentions: @sarah, @mike.jones
    r'@([\w.-]+)',
    
    # Common name patterns in logs: "Sarah:", "Mike Jones:"
    r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?):',
]

# Action verb patterns - common incident response actions
ACTION_KEYWORDS = [
    # Investigation
    'investigating', 'checked', 'examined', 'analyzed', 'reviewing',
    'debugged', 'traced', 'monitoring', 'watching',
    
    # Remediation
    'deployed', 'rolled back', 'reverted', 'restarted', 'rebooted',
    'fixed', 'patched', 'updated', 'scaled', 'killed', 'stopped',
    
    # Communication
    'notified', 'alerted', 'paged', 'escalated', 'confirmed',
    'acknowledged', 'reported',
    
    # Status changes
    'resolved', 'mitigated', 'completed', 'started', 'initiated',
]

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
ENTITY_PATTERNS = [
    # Service names (common patterns): payment-service, user_service, authService
    r'\b([a-z][a-z0-9_-]*(?:service|api|worker|job|daemon))\b',
    
    # IP addresses: 192.168.1.1, 10.0.0.1
    r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b',
    
    # Domains: example.com, api.example.com
    r'\b([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})\b',
]