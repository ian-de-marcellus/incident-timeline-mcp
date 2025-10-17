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
    """
    common_labels = ['time', 'error', 'status', 'note', 'warning', 
                     'info', 'debug', 'system']
    
    return actor.lower() not in common_labels