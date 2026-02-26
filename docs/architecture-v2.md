# Incident Timeline MCP — V2 Architecture

## 1. Motivation: What's Wrong with V1

V1 works as a proof of concept, but running it against realistic incident data
(`incident_response_example.txt`) reveals concrete quality problems:

**Actor extraction confuses speakers with mentions.** Line 1 of the example has
`sarah.chen:` as the speaker and `@channel` as a mention — V1 extracts
`actor: "channel"`. Line 2 has `james.rodriguez:` speaking and mentioning
`@alex.kim` — V1 extracts `actor: "alex.kim"`. The `_find_actor` function
returns the first pattern match, but `@mentions` are checked before
`name.with.dot:` format, so mentions consistently win over speakers.

**People are detected as domains.** `sarah.chen`, `james.rodriguez`,
`alex.kim`, `maria.santos`, and `david.park` all appear in the domains list.
The `firstname.lastname` format matches the domain regex.

**The service pattern misses real service names.** The regex requires names
ending in `-service`, `-api`, `-worker`, `-job`, or `-daemon`. The actual
incident mentions `checkout-db-primary`, `redis-cache-03`, and
`order-processor` — none matched. Only `checkout-service` was found (from a
GitHub URL, not from the incident text).

**Keyword matching has substring collisions.** The remediation keyword `"scaled"`
is a substring of the communication keyword `"escalated"` — so
`"escalated to management"` can match as remediation. The action keyword
matching uses `if keyword in line_lower` with no word boundaries.

**Only 8 of 29 events produced actions.** Many clear actions were missed:
"Starting incident investigation", the rate limiting action, rollback initiation.
Meanwhile, `"deployed"` matched on a line about past context
("the merchant dashboard feature we deployed 2 hours ago"), not a current action.

**Severity detection found only one indicator.** The text contains "Database
performance degraded" but only `"down"` (from "slowing down"/"dropped down")
was caught. Severity is also assessed as a single snapshot across the entire
incident — an incident that was critical but got resolved still reads as
"critical."

**Timestamps are strings, not datetimes.** The code has a TODO comment
acknowledging this. Without parsing, we can't sort events, calculate incident
duration, compute time-to-resolution, or filter by time range.

---

## 2. V2 Goals

Turn this from a toy project into a tool that produces meaningfully better
incident analysis than "paste logs into an LLM and ask for a summary":

1. **Correct extraction** — fix the bugs above (actor priority, substring
   matching, entity disambiguation)
2. **Slack export support** — parse real Slack workspace exports (JSON), not
   just plaintext
3. **IR framework mapping** — classify each event into NIST SP 800-61 incident
   response phases (Detection, Analysis, Containment, Eradication, Recovery,
   Post-Incident)
4. **LLM enrichment** — use Haiku for cases where regex is insufficient:
   severity assessment, phase classification, lines regex couldn't parse
5. **Temporal analysis** — parse timestamps into datetimes, compute duration,
   track severity evolution over time
6. **Richer MCP interface** — add resources and new tools, not just five
   variants of "pass text, get JSON"

---

## 3. Architecture Overview

```
                    ┌─────────────────┐
                    │   MCP Client    │
                    │ (Claude Desktop)│
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │   server.py     │
                    │  Tools + Rsc    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────────┐
        │ Parsers  │  │Extractors│  │   Analysis   │
        │          │  │          │  │              │
        │ slack.py │  │ regex    │  │ framework.py │
        │ plain.py │  │ llm.py   │  │ severity.py  │
        └────┬─────┘  └────┬─────┘  └──────┬───────┘
             │              │               │
             ▼              ▼               ▼
        ┌────────────────────────────────────────┐
        │          models.py                     │
        │  NormalizedMessage, IncidentReport,    │
        │  TimelineEvent, IRPhase                │
        └────────────────────────────────────────┘
```

**Data flows left to right through three stages:**

1. **Parse** — raw input (Slack JSON or plaintext) is normalized into a common
   `NormalizedMessage` format with parsed timestamps and resolved actors
2. **Extract** — regex extractors run first, then LLM enrichment fills gaps
   on low-confidence lines
3. **Analyze** — extracted data is mapped to IR framework phases, severity is
   tracked over time, and incident metrics are computed

---

## 4. Component Design

### 4.1 Data Models (`models.py`)

Central data structures that all components work with:

```python
@dataclass
class NormalizedMessage:
    """A single message from any source, normalized to a common format."""
    timestamp: datetime | None
    actor: str | None           # resolved human name, not a user ID
    text: str                   # cleaned message text
    raw: str                    # original source (for debugging)
    source: str                 # "slack" | "plaintext"
    metadata: dict              # source-specific extras (reactions, thread, etc.)

@dataclass
class TimelineEvent:
    """An extracted event with all enrichments applied."""
    timestamp: datetime | None
    actor: str | None
    text: str
    actions: list[Action]       # actions identified in this event
    entities: dict              # services, IPs, domains in this event
    severity_indicators: list[str]
    ir_phase: str | None        # NIST 800-61 phase
    phase_confidence: str       # "regex" | "llm"

@dataclass
class Action:
    keyword: str
    category: str               # investigation, remediation, communication, status

@dataclass
class IncidentReport:
    """Complete analysis output."""
    timeline: list[TimelineEvent]
    ir_phases: dict[str, list[TimelineEvent]]  # phase -> events in that phase
    severity_timeline: list[SeverityChange]
    overall_severity: SeverityAssessment
    entities: dict[str, list[str]]
    metrics: IncidentMetrics
    summary_text: str

@dataclass
class IncidentMetrics:
    duration: timedelta | None
    time_to_contain: timedelta | None  # detection to containment action
    time_to_resolve: timedelta | None  # detection to resolution
    num_responders: int
    num_events: int

@dataclass
class SeverityChange:
    timestamp: datetime
    level: str                  # critical/high/medium/low
    trigger: str                # what caused the change
```

### 4.2 Parsers

#### Plaintext Parser (`parsers/plaintext.py`)

Extracts from the existing plaintext format. Largely what V1 does today, but
outputs `NormalizedMessage` objects with parsed `datetime` timestamps instead of
raw strings.

**Key fix:** Actor extraction priority. When a line has the format
`sarah.chen: @alex.kim can you check...`, the _speaker_ is `sarah.chen` (the
`name.dot:` pattern at the start of the line) and `alex.kim` is a _mention_.
The parser should identify the speaker, not the first regex match.

Strategy: check for speaker patterns (actor followed by colon at/near start of
line) before checking for @mentions. @mentions become metadata, not the actor.

#### Slack Parser (`parsers/slack.py`)

Parses Slack workspace export format:

```
export.zip
├── users.json              # user ID → profile mapping
├── channels.json           # channel metadata
└── incident-channel/
    └── 2024-10-15.json     # messages for that date
```

Each message in the daily JSON:
```json
{
  "type": "message",
  "user": "U2147483697",
  "text": "Hello <@U06ABCDEF> check <#C01234|general>",
  "ts": "1355517523.000005"
}
```

The parser needs to:
1. Load `users.json` to build a `user_id → display_name` lookup
2. Parse each message's `ts` (Unix epoch string) into a `datetime`
3. Resolve `<@U...>` mentions in message text to real names
4. Clean Slack formatting: `<#C...|channel>` → `#channel`,
   `<http://url|label>` → `label`, `<!here>` / `<!channel>` → `@here` /
   `@channel`
5. Handle message subtypes: `channel_join`, `bot_message`, `me_message`, etc.
   (skip non-human messages or flag them)
6. Preserve thread structure in metadata (`thread_ts`, `reply_count`)
7. Preserve reactions in metadata (useful signal — a checkmark reaction on
   "deployed fix" confirms success)
8. Output `NormalizedMessage` with `source="slack"`

**Input interface:** The MCP tool accepts either a path to an extracted export
directory or the raw JSON content of a single channel's messages (plus
optionally the users.json content for ID resolution).

### 4.3 Extractors

#### Regex Extractors (`extractors.py` — improved)

Fixes to the existing extraction logic:

**Action keyword matching — word boundaries:**
```python
# V1 (broken): substring match
if keyword in line_lower  # "scaled" matches "escalated"

# V2: word boundary regex
pattern = r'\b' + re.escape(keyword) + r'\b'
if re.search(pattern, line_lower)
```

**Service entity pattern — broader matching:**
```python
# V1: only matches names ending in -service, -api, etc.
r'\b([a-z][a-z0-9_-]*(?:service|api|worker|job|daemon))\b'

# V2: also match names with infra suffixes and common patterns
# Match: checkout-db-primary, redis-cache-03, order-processor
# Strategy: match compound names (word-word or word_word patterns)
# that appear near infrastructure context words
```

The improved service pattern should use a two-pass approach:
1. Match compound names (`word[-_]word` patterns with 2+ segments)
2. Filter by nearby context: does the surrounding text contain infra signals
   like "deploy", "restart", "down", "latency", "CPU", "error rate", etc.?

This is also a natural candidate for LLM fallback — ask Haiku "what services
or systems are mentioned in this text?"

**Severity detection — word boundaries + negation awareness:**
```python
# V1: "CPU went down to normal" triggers "went down" (critical)
# V2: check for negation/resolution context around severity keywords
# "back down to normal", "no longer down", "resolved the outage"
# should not contribute to current severity
```

#### LLM Enrichment (`llm/enrichment.py`)

Selective Haiku calls for lines where regex extraction has low confidence or
known blind spots.

**Design principles:**
- **Fallback, not primary.** Regex runs first. LLM only runs on lines that
  regex couldn't fully extract from, or for tasks that are fundamentally
  semantic (IR phase classification, severity-in-context).
- **Per-line, not whole-document.** Send individual lines (or small groups)
  to Haiku, not the entire incident log. This keeps costs low and latency
  manageable.
- **Structured output.** Use tool_use / JSON mode to get structured responses,
  not free-form text that needs parsing.
- **Graceful degradation.** If the API key is missing or the call fails,
  fall back to regex-only results. The tool should work without LLM access,
  just with lower quality.

**When to invoke Haiku:**

| Situation | What to ask |
|-----------|-------------|
| Line has timestamp but no action extracted | "What action is being described?" |
| Severity assessment (always) | "Given the full context, what is the current severity?" |
| IR phase classification (always) | "Which incident response phase does this event belong to?" |
| Entity disambiguation | "Is 'sarah.chen' a person or a domain?" (when domain regex matches a potential person name) |
| Service identification | "What services or systems are mentioned?" (when compound-name regex has low confidence) |

**Batching:** For efficiency, group multiple lines into a single Haiku call
where possible. For example, IR phase classification can send 5-10 events at
once:

```python
prompt = """Classify each event into an incident response phase.
Phases: detection, analysis, containment, eradication, recovery, post_incident

Events:
1. "Seeing elevated response times on checkout-db-primary"
2. "Database CPU is at 94%. Looking at slow query log now..."
3. "Rollback initiated. ETA 3 minutes."
...

Respond with a JSON array of {event_number, phase, reasoning}."""
```

**API integration:** Use the `anthropic` Python SDK with `claude-haiku-4-5-20251001`.
The API key can be provided via environment variable (`ANTHROPIC_API_KEY`) or
MCP server configuration.

### 4.4 Analysis

#### IR Framework Mapping (`analysis/framework.py`)

Maps extracted events to NIST SP 800-61 phases. This is the feature that
transforms raw extraction into actual incident analysis.

**Phase definitions and mapping signals:**

| Phase | Description | Regex signals | LLM signals |
|-------|-------------|---------------|-------------|
| **Detection** | Initial discovery | "seeing", "alert", "noticed", "triggered", "flagged", first event with severity keyword | First message reporting an anomaly |
| **Analysis** | Understanding scope/impact | investigation action keywords, "root cause", "found it", "checking" | Questions being asked, diagnostic activity |
| **Containment** | Stopping the bleeding | "rolling back", "rate limit", "kill", "block", "temporary", "stopgap" | Short-term tactical actions |
| **Eradication** | Removing root cause | "fix", "patch", "proper", "PR ready", "deploy" (post-containment) | Permanent fixes, code changes |
| **Recovery** | Restoring normal ops | "restored", "stable", "back to normal", "resolved", "all clear", "monitoring" (post-fix) | Confirmation of normal metrics |
| **Post-Incident** | Learning/documentation | "postmortem", "PIR", "incident report", "action items", "lessons learned", "scheduled" | Retrospective activity |

**Temporal ordering constraint:** Phases generally progress forward. If regex
classifies an event as "Recovery" but it occurs before any "Containment" event,
that's suspicious and should be flagged for LLM review. This is a heuristic,
not a hard rule — real incidents can have overlapping phases.

**Output:** Each `TimelineEvent` gets an `ir_phase` field. The `IncidentReport`
includes an `ir_phases` dict grouping events by phase, making it easy to see
the incident narrative: "Detection happened at 14:23, Analysis ran from
14:24-14:29, Containment started at 14:30..."

#### Severity Timeline (`analysis/severity.py`)

Instead of a single severity snapshot, track how severity evolves:

```python
severity_timeline = [
    SeverityChange(timestamp=14:23, level="high",     trigger="elevated response times"),
    SeverityChange(timestamp=14:25, level="critical",  trigger="CPU at 94%, customer impact"),
    SeverityChange(timestamp=14:34, level="medium",    trigger="rollback complete, metrics recovering"),
    SeverityChange(timestamp=14:55, level="resolved",  trigger="30 min stable, all metrics normal"),
]
```

This requires per-event severity assessment rather than whole-text keyword
scanning. Each event is evaluated for severity signals in the context of what
came before it. This is a strong LLM use case — understanding that "CPU back
to 23%" means severity is _decreasing_ requires contextual understanding.

#### Incident Metrics (`analysis/metrics.py`)

Computed from parsed timestamps:
- **Duration**: last event timestamp - first event timestamp
- **Time to detect (TTD)**: first event → detection confirmed
- **Time to contain (TTC)**: detection → first containment action
- **Time to resolve (TTR)**: detection → resolution declared
- **Responder count**: unique actors
- **Event count**: total timeline events

These are standard incident management KPIs. They're trivial to compute once
timestamps are parsed into datetimes but impossible with string timestamps.

---

## 5. MCP Interface

### 5.1 Tools (Updated)

**Existing tools** (same interface, richer output):
- `extract_timeline` — now returns parsed timestamps, correct actors, IR phase
  per event
- `identify_actions` — word-boundary matching, fewer false positives
- `extract_entities` — no more people-as-domains, broader service detection
- `detect_severity` — returns severity timeline, not just peak severity
- `generate_summary` — full `IncidentReport` with IR phases, metrics, severity
  evolution

**New tools:**

`parse_slack_export` — accepts Slack export data and runs the full analysis
pipeline:
```json
{
  "name": "parse_slack_export",
  "inputSchema": {
    "properties": {
      "messages_json": {
        "type": "string",
        "description": "JSON string of Slack messages array from a channel export file"
      },
      "users_json": {
        "type": "string",
        "description": "JSON string of Slack users.json for resolving user IDs to names (optional)"
      }
    },
    "required": ["messages_json"]
  }
}
```

`map_to_framework` — takes already-extracted timeline and classifies by IR
phase (useful when Claude wants to re-classify or when input comes from a
different source):
```json
{
  "name": "map_to_framework",
  "inputSchema": {
    "properties": {
      "text": {
        "type": "string",
        "description": "Raw incident text"
      },
      "framework": {
        "type": "string",
        "enum": ["nist_800_61"],
        "description": "IR framework to map to (currently only NIST SP 800-61)"
      }
    },
    "required": ["text"]
  }
}
```

### 5.2 Resources (New)

MCP resources expose data for Claude to read. These make the demo interactive —
Claude can list available sample incidents, pick one, and analyze it.

```python
@app.list_resources()
async def list_resources():
    return [
        Resource(
            uri="incident://examples/simple",
            name="Simple Incident (Slack-style)",
            description="Brief payment-service incident with @mentions and simple timestamps",
            mimeType="text/plain",
        ),
        Resource(
            uri="incident://examples/realistic",
            name="Realistic Incident (ISO 8601)",
            description="30-event database incident with full timestamps, multiple responders, "
                       "and complete lifecycle from detection through post-incident",
            mimeType="text/plain",
        ),
    ]
```

---

## 6. Implementation Phases

Ordered by dependency and value. Each phase produces a working, testable
increment.

### Phase 1: Foundation — Models + Bug Fixes
- Create `models.py` with data classes
- Fix actor extraction priority (speaker > mention)
- Fix action keyword matching (word boundaries)
- Fix entity extraction (people ≠ domains, broader service pattern)
- Fix severity keyword context (negation/resolution awareness)
- Update existing tests, add regression tests for each bug
- **Result:** V1 tools work correctly on existing examples

### Phase 2: Temporal Analysis
- Parse timestamps into `datetime` objects in extractors
- Add event sorting by timestamp
- Compute incident metrics (duration, TTD, TTC, TTR)
- Add severity timeline tracking (per-event assessment)
- Update `generate_summary` output with metrics + severity evolution
- **Result:** timeline is temporally aware, summary includes duration/metrics

### Phase 3: IR Framework Mapping
- Implement `analysis/framework.py` with regex-based phase classification
- Add `ir_phase` to `TimelineEvent` output
- Add `ir_phases` grouping to `IncidentReport`
- Add `map_to_framework` MCP tool
- Add phase progression to summary text
- **Result:** events are classified by IR phase, summary tells the incident
  story in framework terms

### Phase 4: Slack Export Parsing
- Implement `parsers/slack.py` with full Slack mrkdwn cleanup
- Handle user ID resolution, bot message attribution, epoch timestamps
- Extract text from attachments, blocks (rich_text), and file titles
- Split `generate_summary()` into `_analyze_timeline()` shared core —
  Slack path builds events directly (preserving trusted actors) while
  plaintext path continues through `extract_timeline()`
- Add `parse_slack_export` MCP tool
- Create sample Slack exports in `examples/` for testing
- **Result:** tool works on real Slack data with correct actor attribution

### Phase 5: Signal Filtering + Incident-Aware Metrics
- Multi-day Slack export support (date-keyed JSON objects)
- Noise filtering: `_is_incident_relevant()` removes noise bots
  (BirthdayBot, Giphy) and casual phrases while preserving ops bot
  messages (Datadog, PagerDuty, Jira)
- Incident-aware duration: `_find_incident_boundaries()` detects
  start (severity/detection keywords) and end (recovery/post_incident
  keywords), reports `incident_duration` alongside raw `duration`
- Phase keyword tuning: `monitor triggered`/`monitor warning` added
  to detection; `resolved` moved to post_incident
- **Result:** clean timelines from noisy multi-day exports, accurate
  incident duration metrics

### Phase 6: LLM Enrichment
- Implement `llm/enrichment.py` with Haiku integration
- Add LLM fallback for: phase classification, severity assessment, entity
  disambiguation, missed action extraction
- Add graceful degradation (works without API key, just lower quality)
- Add confidence indicators to output (regex vs. LLM sourced)
- **Result:** significantly improved accuracy on ambiguous inputs

### Phase 7: MCP Resources + Polish
- Add MCP resources for sample incidents
- Update README with v2 capabilities and examples
- End-to-end testing with realistic inputs
- **Result:** complete, demo-ready v2

---

## 7. What This Demonstrates (Interview Talking Points)

- **Hybrid architecture**: deterministic extraction where possible, LLM where
  needed — not "throw everything at GPT" and not "regex for everything"
- **Domain modeling**: NIST 800-61 framework mapping shows understanding of
  incident response as a discipline, not just text processing
- **MCP depth**: tools, resources, structured schemas — not just a
  hello-world server
- **Data quality engineering**: false positive filtering, confidence scoring,
  disambiguation — the hard part of extraction is knowing when you're wrong
- **Practical scope**: Slack export support targets a real integration point,
  not a hypothetical one
- **Incremental design**: each phase produces working software, not a
  big-bang rewrite
