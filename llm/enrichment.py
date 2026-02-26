"""
LLM enrichment for incident timeline analysis.

All functions are pure — they receive the Anthropic client and model
as parameters. No module-level state or config reads.

The caller (extractors._get_llm_client) is responsible for
constructing the client and reading settings.
"""

import logging

from .prompts import (
    IR_PHASE_PROMPT, IR_PHASE_TOOL,
    SEVERITY_PROMPT, SEVERITY_TOOL,
    ACTION_PROMPT, ACTION_TOOL,
    ENTITY_PROMPT, ENTITY_TOOL,
)

logger = logging.getLogger(__name__)

try:
    import anthropic  # noqa: F401 — availability check, not used directly
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Valid IR phases (used to filter bad LLM output)
_VALID_PHASES = {
    'detection', 'analysis', 'containment',
    'eradication', 'recovery', 'post_incident',
    'irrelevant',
}


def _call_llm(
    client,
    model: str,
    system: str,
    user_content: str,
    tool_schema: dict,
    tool_name: str,
) -> dict | None:
    """
    Single LLM API call with forced tool use.

    Returns the parsed tool input dict, or None on any failure.
    """
    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            tools=[tool_schema],
            tool_choice={"type": "tool", "name": tool_name},
            timeout=15.0,
        )

        # Extract tool_use block from response
        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                return block.input

        logger.warning("No tool_use block in response for %s", tool_name)
        return None

    except Exception as e:
        logger.warning("LLM call failed for %s: %s", tool_name, e)
        return None


# ── Enrichment passes ────────────────────────────────────────────────

def enrich_ir_phases(
    events: list[dict],
    client,
    model: str,
) -> list[dict] | None:
    """
    Enrich IR phase classifications for low-confidence events.

    Collects events where phase_confidence == 'low', sends them
    in batches of 10 with 2 context events before/after each target.

    Returns list of {event_index, ir_phase, phase_confidence} or None.
    """
    # Find low-confidence events
    low_conf_indices = [
        i for i, e in enumerate(events)
        if e.get('phase_confidence') == 'low'
    ]

    if not low_conf_indices:
        return None

    all_updates = []

    # Process in batches of 10
    for batch_start in range(0, len(low_conf_indices), 10):
        batch_indices = low_conf_indices[batch_start:batch_start + 10]

        # Build user content with context
        lines = []
        included = set()
        for idx in batch_indices:
            # Add 2 context events before and after
            context_start = max(0, idx - 2)
            context_end = min(len(events), idx + 3)
            for ci in range(context_start, context_end):
                if ci in included:
                    continue
                included.add(ci)
                tag = "[CLASSIFY]" if ci in batch_indices else "[context]"
                text = events[ci].get('text', '')
                time = events[ci].get('time', '')
                lines.append(f"Event {ci} {tag} [{time}]: {text}")

        user_content = "\n".join(lines)
        result = _call_llm(
            client, model,
            IR_PHASE_PROMPT, user_content,
            IR_PHASE_TOOL, "classify_phases",
        )

        if not result or 'classifications' not in result:
            continue

        for classification in result['classifications']:
            event_num = classification.get('event_number')
            phase = classification.get('phase')
            if (event_num is not None
                    and phase in _VALID_PHASES
                    and event_num in batch_indices):
                all_updates.append({
                    'event_index': event_num,
                    'ir_phase': phase,
                    'phase_confidence': 'medium',
                })

    return all_updates if all_updates else None


def enrich_severity(
    text: str,
    current_severity: dict,
    client,
    model: str,
) -> dict | None:
    """
    Enrich severity assessment when regex confidence is low or level is unknown.

    Returns {level, confidence, indicators, reasoning} or None.
    """
    level = current_severity.get('level', 'unknown')
    confidence = current_severity.get('confidence', 'low')

    if level != 'unknown' and confidence != 'low':
        return None

    # Truncate text for token efficiency
    truncated = text[:2000]

    result = _call_llm(
        client, model,
        SEVERITY_PROMPT, truncated,
        SEVERITY_TOOL, "assess_severity",
    )

    if not result:
        return None

    llm_level = result.get('level')
    if llm_level not in ('critical', 'high', 'medium', 'low'):
        return None

    return {
        'level': llm_level,
        'confidence': result.get('confidence', 'medium'),
        'indicators': result.get('indicators', []),
        'reasoning': result.get('reasoning', ''),
    }


def enrich_actions(
    events: list[dict],
    existing_actions: list[dict],
    client,
    model: str,
) -> list[dict] | None:
    """
    Find actions in events where regex found none.

    Compares timestamped events against existing action contexts
    to find gaps, then sends those lines for LLM classification.

    Returns list of {action, category, context} or None.
    """
    # Find events with timestamps but no corresponding action
    action_contexts = {a['context'] for a in existing_actions}
    missing = [
        (i, e) for i, e in enumerate(events)
        if e.get('timestamp') and e['text'] not in action_contexts
    ]

    if not missing:
        return None

    all_new_actions = []

    # Process in batches of 10
    for batch_start in range(0, len(missing), 10):
        batch = missing[batch_start:batch_start + 10]

        lines = []
        index_map = {}  # line_number → event text
        for line_num, (_event_idx, event) in enumerate(batch, start=1):
            text = event.get('text', '')
            time = event.get('time', '')
            lines.append(f"Line {line_num} [{time}]: {text}")
            index_map[line_num] = text

        user_content = "\n".join(lines)
        result = _call_llm(
            client, model,
            ACTION_PROMPT, user_content,
            ACTION_TOOL, "identify_actions",
        )

        if not result or 'actions' not in result:
            continue

        for action_item in result['actions']:
            line_num = action_item.get('line_number')
            action = action_item.get('action')
            category = action_item.get('category')
            if (line_num in index_map
                    and action
                    and category in ('investigation', 'remediation',
                                     'communication', 'status')):
                all_new_actions.append({
                    'action': action,
                    'category': category,
                    'context': index_map[line_num],
                    'source': 'llm',
                })

    return all_new_actions if all_new_actions else None


def enrich_entities(
    entities: dict[str, list[str]],
    text: str,
    client,
    model: str,
) -> dict | None:
    """
    Disambiguate entities that might be misclassified.

    Checks the domains list for firstname.lastname patterns
    that could be person names rather than actual domains.

    Returns {disambiguated: [{item, entity_type, reasoning}]} or None.
    """
    # Find suspicious domains (firstname.lastname pattern)
    suspects = []
    for domain in entities.get('domains', []):
        parts = domain.split('.')
        if (len(parts) == 2
                and parts[0].isalpha()
                and parts[1].isalpha()
                and len(parts[1]) > 3):  # TLD would be short
            suspects.append(domain)

    if not suspects:
        return None

    # Build user content
    context = text[:2000]
    items_list = "\n".join(f"- {s}" for s in suspects)
    user_content = (
        f"Items to classify:\n{items_list}\n\n"
        f"Incident context:\n{context}"
    )

    result = _call_llm(
        client, model,
        ENTITY_PROMPT, user_content,
        ENTITY_TOOL, "disambiguate_entities",
    )

    if not result or 'disambiguated' not in result:
        return None

    return result


# ── Orchestrator ─────────────────────────────────────────────────────

def enrich_timeline(
    state,
    client,
    model: str,
    level: str,
) -> dict:
    """
    Run LLM enrichment passes based on enrichment level.

    Args:
        state: AnalysisState with events, text, severity, actions, entities
        client: Anthropic client instance
        model: Model ID to use
        level: 'low' (phases + severity) or 'regular' (all four passes)

    Each pass is independent; failures in one don't affect others.
    Returns dict with keys: phase_updates, severity_update,
    new_actions, entity_updates (each present only if enrichment found).
    """
    results = {}

    # Phase classification (low + regular)
    try:
        phase_updates = enrich_ir_phases(state.events, client, model)
        if phase_updates:
            results['phase_updates'] = phase_updates
    except Exception as e:
        logger.warning("Phase enrichment failed: %s", e)

    # Severity (low + regular)
    try:
        severity_update = enrich_severity(state.text, state.severity, client, model)
        if severity_update:
            results['severity_update'] = severity_update
    except Exception as e:
        logger.warning("Severity enrichment failed: %s", e)

    # Actions (regular only)
    if level == 'regular':
        try:
            new_actions = enrich_actions(state.events, state.actions, client, model)
            if new_actions:
                results['new_actions'] = new_actions
        except Exception as e:
            logger.warning("Action enrichment failed: %s", e)

    # Entities (regular only)
    if level == 'regular':
        try:
            entity_updates = enrich_entities(state.entities, state.text, client, model)
            if entity_updates:
                results['entity_updates'] = entity_updates
        except Exception as e:
            logger.warning("Entity enrichment failed: %s", e)

    return results
