"""
Pattern definitions for incident text analysis.
Contains regex patterns and keyword lists for extracting structured data.
"""

# Timestamp patterns - matches common time formats in incident logs
# Note: Some ambiguous patterns (like "ratio of 3:45") will match and are
# filtered by context analysis in extractors.py
# Ordered from most specific to least specific (dict maintains insertion order in Python 3.7+)
TIMESTAMP_PATTERNS = {
    'iso8601': r'\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\b',
    'full_datetime': r'\b(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}(?::\d{2})?)\b',
    'time_with_seconds': r'(?<![:\w])([0-2]?\d):([0-5]\d):([0-5]\d)(?!:\d)\b',
    'simple_time': r'(?<![:\w])([0-2]?\d):([0-5]\d)(?!:\d)\b',
}

# Actor/person patterns - identifies who is taking action
# Ordered so speaker patterns (name before colon) are checked before @mentions.
# This ensures "sarah.chen: @alex.kim check this" extracts sarah.chen (the speaker).
# Note: Names with lowercase particles (de, von, van) are not captured
ACTOR_PATTERNS = {
    'name_with_dot': r'\b([a-z]+\.[a-z]+):',  # speaker: firstname.lastname:
    'name_colon': r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?):',  # speaker: "Sarah:", "Mike Jones:"
    'mention': r'@([\w.-]+)',  # fallback: Slack-style @mentions: @sarah, @mike.jones
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
        # Domain-specific investigation
        'tracing transaction', 'checking chain', 'reviewing ledger',
        'tracing requests', 'profiling', 'profiled',
        'auditing', 'audited',
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
        # Platform and operations actions
        'halted trading', 'paused withdrawals', 'disabled deposits',
        'froze', 'freezing', 'frozen',
        'circuit breaker', 'circuit breaker triggered',
        'paused', 'halted',
        'rerouting', 'rerouted',
        'load shedding', 'shedding load',
        'rate limiting', 'rate limited',
        'throttling', 'throttled',
        'failover', 'failed over',
        'draining', 'drained',
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
    'critical': ['critical', 'is down', 'went down', 'outage', 'offline', 'unavailable',
             'total failure', 'complete loss', 'service down', 'system down',
             # Financial / exchange
             'funds at risk', 'wallet compromised', 'trading halted',
             'withdrawals disabled', 'exploit', 'drained',
             'unauthorized withdrawal', 'private key exposed',
             'double spend', 'hot wallet compromised',
             # Marketplace / platform
             'dispatch down', 'matching failed', 'trips affected',
             'orders stuck', 'fulfillment halted'],
    'high': ['degraded', 'slow', 'timeout', 'elevated error',
             'high error', 'error rate', 'performance issue',
             'jumped', 'spike', 'surged',
             # Financial / exchange
             'liquidation', 'slippage', 'stale price', 'price feed',
             'failed transactions', 'gas spike', 'chain congestion',
             'oracle failure', 'oracle stale', 'deposits disabled',
             # Marketplace / platform
             'dispatch latency', 'routing errors', 'eta degraded',
             'demand spike', 'supply shortage'],
    'medium': ['intermittent', 'occasional', 'sporadic', 'some users',
               'affecting some',
               # Financial / exchange
               'delayed settlement', 'sync lag', 'chain reorg',
               'pending transactions', 'block delay',
               'confirmation delay',
               # Marketplace / platform
               'eta inaccurate', 'delayed dispatch', 'routing fallback'],
    'low': ['minor', 'cosmetic', 'edge case', 'rare'],
}

# NIST SP 800-61 incident response phase keywords.
# Maps each IR lifecycle phase to indicator strings.
# Note: Some overlap with ACTION_KEYWORDS is intentional —
# ACTION_KEYWORDS classifies *what kind of action* (investigation vs remediation),
# IR_PHASE_KEYWORDS classifies *where in the lifecycle* (analysis vs containment).
IR_PHASE_KEYWORDS = {
    'detection': [
        'seeing', 'noticed', 'alert fired', 'alert triggered',
        'flagged', 'detected', 'anomaly', 'elevated',
        'spike detected', 'pagerduty',
        'starting incident', 'started incident',
        'declared', 'sev-1', 'sev-2', 'sev-3',
    ],
    'analysis': [
        'investigating', 'checking', 'analyzing', 'debugging',
        'tracing', 'root cause', 'found it', 'looking at',
        'examining', 'reviewing', 'profiling', 'auditing',
        'what are our', 'options',
        'checking chain', 'tracing transaction', 'reviewing ledger',
        'tracing requests',
    ],
    'containment': [
        'rolling back', 'rolled back', 'rollback',
        'rate limiting', 'rate limited',
        'killing', 'killed', 'blocking', 'blocked',
        'circuit breaker', 'circuit breaker triggered',
        'halted trading', 'paused withdrawals', 'disabled deposits',
        'froze', 'freezing', 'frozen',
        'throttling', 'throttled',
        'load shedding', 'shedding load',
        'draining', 'failover', 'failed over',
        'rerouting', 'rerouted',
        'temporary', 'stopgap', 'quick fix',
    ],
    'eradication': [
        'fix deployed', 'deploying fix', 'deployed fix',
        'proper fix', 'permanent fix',
        'patched', 'patching',
        'updated config', 'config updated',
        'pr ready', 'pull request',
        'added index', 'created index',
        'load test', 'load test passed',
        'redeploying', 'redeploy',
    ],
    'recovery': [
        'restored', 'back to normal', 'returning to normal',
        'metrics stable', 'all clear', 'all-clear',
        'stable', 'recovered', 'monitor recovered',
        'recovering', 'recovery',
        're-enabled', 'resumed',
        'back to baseline', 'healthy',
    ],
    'post_incident': [
        'postmortem', 'post-mortem', 'post mortem',
        'pir', 'post-incident review',
        'incident report', 'lessons learned',
        'action items', 'scheduled for tomorrow',
        'retrospective', 'write up', 'write-up',
        'resolved', 'incident resolved',
    ],
}

# Lines matching these indicators are *discussing* an action, not performing it.
# They get downgraded one phase (containment → analysis, eradication → containment).
DISCUSSION_INDICATORS = [
    'options:', 'i vote', 'what are our', 'should we',
    "let's", 'we could', 'what if', 'how about',
]

# Entity patterns - systems, services, IPs, domains
ENTITY_PATTERNS = {
    # Single-word names ending in known suffixes (e.g., authservice, payment-api)
    'service_suffix': r'\b([a-z][a-z0-9_-]*(?:service|api|worker|job|daemon))\b',
    # Compound names: 2+ segments joined by hyphens or underscores.
    # Filtered by INFRA_KEYWORDS in extractors.py to avoid false positives.
    'service_compound': r'\b([a-z][a-z0-9]*(?:[-_][a-z0-9]+)+)\b',
    'ip': r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b',
    'domain': r'\b([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})\b',
}

# Infrastructure keywords for service name validation.
# A compound name is considered a service if any segment matches one of these.
INFRA_KEYWORDS = {
    'service', 'api', 'worker', 'job', 'daemon',
    'db', 'database', 'cache', 'queue', 'proxy', 'gateway',
    'server', 'cluster', 'node', 'primary', 'secondary',
    'master', 'replica', 'processor', 'handler',
    # Financial / exchange
    'exchange', 'ledger', 'vault', 'wallet', 'bridge',
    'oracle', 'chain', 'custody', 'engine', 'book',
    # Marketplace / platform
    'dispatch', 'routing', 'matcher', 'pricing',
    'fulfillment', 'geofence', 'marketplace',
    'shard', 'balancer', 'ingress', 'scheduler',
}

# Known TLDs for domain validation.
# Domains whose TLD isn't in this set are rejected (catches firstname.lastname
# false positives like "sarah.chen" where "chen" is not a TLD).
KNOWN_TLDS = {
    'com', 'org', 'net', 'io', 'co', 'edu', 'gov', 'dev', 'app',
    'us', 'uk', 'de', 'fr', 'jp', 'au', 'ca', 'info', 'biz', 'xyz',
    'cloud', 'tech', 'ai', 'ly', 'me', 'tv', 'cc', 'ru', 'cn', 'br',
}