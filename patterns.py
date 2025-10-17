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