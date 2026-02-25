"""
Prompt templates and tool schemas for LLM enrichment.

Each enrichment pass has a prompt template (system instructions)
and a tool schema (structured output via tool_use).
"""

# ── IR Phase Classification ─────────────────────────────────────────

IR_PHASE_PROMPT = """\
You are an incident response analyst. Classify each numbered event \
into a NIST SP 800-61 incident response lifecycle phase.

Phase definitions:
- detection: Initial alerts, anomaly observations, incident declaration
- analysis: Investigation, root cause analysis, debugging, triage
- containment: Immediate actions to limit damage (rollbacks, rate limits, \
circuit breakers, halting operations)
- eradication: Deploying permanent fixes, patching, config changes
- recovery: Restoring normal operations, metrics returning to baseline
- post_incident: Postmortem, lessons learned, action items
- irrelevant: Not related to any incident (casual chat, routine \
deployments before the incident, social messages, general work \
discussion unrelated to an active incident)

Context events (marked [context]) are provided for reference only. \
Only classify the events marked [CLASSIFY].

Consider:
- What action is being described?
- Where does this fit in the incident lifecycle?
- Does the surrounding context support your classification?
- If a message has no connection to incident response, classify \
it as irrelevant
"""

IR_PHASE_TOOL = {
    "name": "classify_phases",
    "description": "Classify incident events into NIST SP 800-61 IR phases",
    "input_schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_number": {
                            "type": "integer",
                            "description": "The event number to classify",
                        },
                        "phase": {
                            "type": "string",
                            "enum": [
                                "detection", "analysis", "containment",
                                "eradication", "recovery", "post_incident",
                                "irrelevant",
                            ],
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Brief explanation for the classification",
                        },
                    },
                    "required": ["event_number", "phase", "reasoning"],
                },
            },
        },
        "required": ["classifications"],
    },
}


# ── Severity Assessment ──────────────────────────────────────────────

SEVERITY_PROMPT = """\
You are an incident response analyst. Assess the overall severity \
of this incident based on the text excerpt provided.

Severity levels:
- critical: Complete outage, data loss, security breach, funds at risk
- high: Major degradation, significant user impact, elevated errors
- medium: Partial impact, intermittent issues, limited user effect
- low: Minor cosmetic issues, edge cases, minimal user impact

Consider:
- What systems are affected?
- What is the scope of user impact?
- Are there any data integrity or security concerns?
- How urgent is the response?
"""

SEVERITY_TOOL = {
    "name": "assess_severity",
    "description": "Assess incident severity from text",
    "input_schema": {
        "type": "object",
        "properties": {
            "level": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low"],
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "indicators": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key phrases indicating this severity level",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief explanation for the assessment",
            },
        },
        "required": ["level", "confidence", "indicators", "reasoning"],
    },
}


# ── Action Identification ────────────────────────────────────────────

ACTION_PROMPT = """\
You are an incident response analyst. For each numbered line, \
identify the primary action being taken and categorize it.

Action categories:
- investigation: Examining, debugging, analyzing, profiling, tracing
- remediation: Deploying, reverting, restarting, patching, scaling, \
rate limiting, failover
- communication: Notifying, escalating, paging, alerting, confirming
- status: Resolving, completing, initiating, mitigating

Only identify clear, concrete actions. Skip lines that are purely \
informational with no action verb.
"""

ACTION_TOOL = {
    "name": "identify_actions",
    "description": "Identify actions from incident timeline lines",
    "input_schema": {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "line_number": {
                            "type": "integer",
                            "description": "The line number from the input",
                        },
                        "action": {
                            "type": "string",
                            "description": "The action verb or phrase",
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "investigation", "remediation",
                                "communication", "status",
                            ],
                        },
                    },
                    "required": ["line_number", "action", "category"],
                },
            },
        },
        "required": ["actions"],
    },
}


# ── Entity Disambiguation ───────────────────────────────────────────

ENTITY_PROMPT = """\
You are an incident response analyst. For each item listed, \
determine whether it is a person's name, a domain name, or a \
service/system name based on the incident context provided.

Common patterns:
- firstname.lastname (e.g., sarah.chen, mike.jones) → person
- subdomain.domain.tld (e.g., api.example.com) → domain
- name-with-infra-word (e.g., payment-api, auth-service) → service

Use the incident context to resolve ambiguous cases.
"""

ENTITY_TOOL = {
    "name": "disambiguate_entities",
    "description": "Classify ambiguous entities by type",
    "input_schema": {
        "type": "object",
        "properties": {
            "disambiguated": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {
                            "type": "string",
                            "description": "The entity being classified",
                        },
                        "entity_type": {
                            "type": "string",
                            "enum": ["person", "domain", "service"],
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Brief explanation",
                        },
                    },
                    "required": ["item", "entity_type", "reasoning"],
                },
            },
        },
        "required": ["disambiguated"],
    },
}
