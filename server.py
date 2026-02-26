#!/usr/bin/env python3
"""
MCP Server for incident timeline extraction.
Exposes extraction tools to Claude via Model Context Protocol.
"""

import asyncio
import json
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import AnyUrl
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import Tool, TextContent, Resource

# Import our extractors
from extractors import (
    extract_timeline,
    identify_actions,
    extract_entities,
    detect_severity,
    generate_summary,
    map_to_framework,
    _get_llm_client,
)
from parsers.slack import parse_slack_export

# Create the server instance
app = Server("incident-timeline-extractor")

EXAMPLES_DIR = Path(__file__).parent / "examples"

@app.list_tools()
async def list_tools() -> list[Tool]:
    """
    List available tools for Claude to use.
    Each tool corresponds to one of our extractor functions.
    """
    return [
        Tool(
            name="extract_timeline",
            description="Extract chronological timeline of events from incident text. "
                       "Returns events with timestamps, actors, and full context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Raw incident text (chat logs, notes, etc.)"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="identify_actions",
            description="Identify actions taken during incident response. "
                       "Categorizes actions by type (investigation, remediation, communication, status).",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Raw incident text"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="extract_entities",
            description="Extract entities involved in the incident. "
                       "Finds services, IP addresses, and domains mentioned in text.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Raw incident text"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="detect_severity",
            description="Detect incident severity based on keywords and context. "
                       "Returns severity level (critical/high/medium/low/unknown) with confidence score.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Raw incident text"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="generate_summary",
            description="Generate comprehensive incident summary. "
                       "Combines timeline, actions, entities, and severity into structured report.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Raw incident text"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="map_to_framework",
            description="Map incident events to NIST SP 800-61 IR framework phases "
                       "(Detection, Analysis, Containment, Eradication, Recovery, Post-Incident). "
                       "Returns structured phase mapping with timeline, groupings, and metrics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Raw incident text (chat logs, notes, etc.)"
                    },
                    "framework": {
                        "type": "string",
                        "description": "Framework identifier (default: nist_800_61)",
                        "default": "nist_800_61"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="parse_slack_export",
            description="Parse Slack workspace export and extract incident timeline. "
                       "Converts Slack JSON messages into structured incident analysis "
                       "with timeline, actions, entities, severity, and IR phase mapping.",
            inputSchema={
                "type": "object",
                "properties": {
                    "messages_json": {
                        "type": "string",
                        "description": "JSON string of Slack messages — either a single array "
                                       "or a date-keyed object for multi-day incidents "
                                       '(e.g. {"2024-10-15": [...], "2024-10-16": [...]})'
                    },
                    "users_json": {
                        "type": "string",
                        "description": "Optional JSON string of users.json for resolving user mentions"
                    }
                },
                "required": ["messages_json"]
            }
        ),
        Tool(
            name="analyze_resource",
            description="Read a sample incident resource by URI and run the full analysis pipeline. "
                        "Automatically detects format (plaintext or Slack export) and returns "
                        "structured incident analysis with timeline, actions, entities, severity, "
                        "IR phase mapping, and metrics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uri": {
                        "type": "string",
                        "description": "Resource URI (e.g. incident://examples/simple, "
                                       "incident://examples/detailed, incident://examples/slack-export)"
                    }
                },
                "required": ["uri"]
            }
        ),
    ]

@app.list_resources()
async def list_resources() -> list[Resource]:
    """List sample incident resources available for analysis."""
    return [
        Resource(
            uri="incident://examples/simple",
            name="Simple Incident (plaintext)",
            description="Sample payment-service incident with @mentions "
                        "and simple timestamps (11 events, ~2 min)",
            mimeType="text/plain",
        ),
        Resource(
            uri="incident://examples/detailed",
            name="Detailed Incident (plaintext)",
            description="Sample database performance incident with ISO 8601 "
                        "timestamps, 5 responders, and IR lifecycle from "
                        "detection through post-incident review (30 events)",
            mimeType="text/plain",
        ),
        Resource(
            uri="incident://examples/slack-export",
            name="Slack Export Incident",
            description="Sample Slack workspace export with 18 messages "
                        "including bot messages and @mentions. Returns JSON "
                        "with 'messages' and 'users' keys for use with "
                        "parse_slack_export tool",
            mimeType="application/json",
        ),
        Resource(
            uri="incident://examples/phishing-export",
            name="Phishing Incident (Slack export)",
            description="Phishing attack with executive account compromise — "
                        "12 messages with Splunk, Okta, and Google Workspace "
                        "bot alerts across detection, containment, and eradication",
            mimeType="application/json",
        ),
        Resource(
            uri="incident://examples/coinflux-export",
            name="Database Migration Incident (Slack export)",
            description="Database migration locks causing wallet API latency — "
                        "12 messages with Datadog, PagerDuty, and GitHub bot alerts",
            mimeType="application/json",
        ),
        Resource(
            uri="incident://examples/company-export",
            name="Multi-Day Incident (Slack export)",
            description="5-day image-processor memory leak incident from false alarm "
                        "through crash loop to root cause fix — 24 messages across "
                        "5 days with noise (birthday bot, taco chat)",
            mimeType="application/json",
        ),
        Resource(
            uri="incident://examples/security-export",
            name="Cross-Year Security Incident (Slack export)",
            description="DDoS attack escalating to account compromise spanning "
                        "New Year's Eve — 8 messages across 2 days with AWS WAF alerts",
            mimeType="application/json",
        ),
    ]


@app.read_resource()
async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
    """Read a sample incident resource by URI."""
    uri_str = str(uri)
    if uri_str == "incident://examples/simple":
        content = (EXAMPLES_DIR / "sample_incident.txt").read_text()
        return [ReadResourceContents(content=content, mime_type="text/plain")]

    if uri_str == "incident://examples/detailed":
        content = (EXAMPLES_DIR / "incident_response_example.txt").read_text()
        return [ReadResourceContents(content=content, mime_type="text/plain")]

    if uri_str == "incident://examples/slack-export":
        messages = (EXAMPLES_DIR / "slack" / "incident-channel" / "2024-10-15.json").read_text()
        users = (EXAMPLES_DIR / "slack" / "users.json").read_text()
        content = json.dumps({"messages": messages, "users": users})
        return [ReadResourceContents(content=content, mime_type="application/json")]

    if uri_str == "incident://examples/phishing-export":
        messages = (EXAMPLES_DIR / "phishing-export" / "sec-ops" / "2023-10-25.json").read_text()
        users = (EXAMPLES_DIR / "phishing-export" / "users.json").read_text()
        content = json.dumps({"messages": messages, "users": users})
        return [ReadResourceContents(content=content, mime_type="application/json")]

    if uri_str == "incident://examples/coinflux-export":
        messages = (EXAMPLES_DIR / "coinflux-export" / "incidents-sev1" / "2023-11-14.json").read_text()
        users = (EXAMPLES_DIR / "coinflux-export" / "users.json").read_text()
        content = json.dumps({"messages": messages, "users": users})
        return [ReadResourceContents(content=content, mime_type="application/json")]

    if uri_str == "incident://examples/company-export":
        channel_dir = EXAMPLES_DIR / "company-export" / "team-backend"
        messages = json.dumps({
            p.stem: p.read_text() for p in sorted(channel_dir.glob("*.json"))
        })
        users = (EXAMPLES_DIR / "company-export" / "users.json").read_text()
        content = json.dumps({"messages": messages, "users": users})
        return [ReadResourceContents(content=content, mime_type="application/json")]

    if uri_str == "incident://examples/security-export":
        channel_dir = EXAMPLES_DIR / "security-export" / "incidents-security"
        messages = json.dumps({
            p.stem: p.read_text() for p in sorted(channel_dir.glob("*.json"))
        })
        users = (EXAMPLES_DIR / "security-export" / "users.json").read_text()
        content = json.dumps({"messages": messages, "users": users})
        return [ReadResourceContents(content=content, mime_type="application/json")]

    raise ValueError(f"Unknown resource: {uri_str}")


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    Handle tool calls from Claude.
    Routes to appropriate extractor function based on tool name.
    """
    # Route to appropriate extractor
    try:
        # analyze_resource: read resource URI and run appropriate pipeline
        if name == "analyze_resource":
            uri = arguments.get("uri", "")
            if not uri:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "No uri provided"})
                )]
            resource_contents = await read_resource(uri)
            content = resource_contents[0].content
            mime = resource_contents[0].mime_type or ""
            client, level = _get_llm_client()
            if "json" in mime:
                data = json.loads(content)
                result = parse_slack_export(
                    data["messages"], data.get("users"),
                    client=client, level=level,
                )
            else:
                result = generate_summary(content)

        # Slack parser uses messages_json, not text
        elif name == "parse_slack_export":
            messages_json = arguments.get("messages_json", "")
            if not messages_json:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "No messages_json provided"})
                )]
            users_json = arguments.get("users_json")
            client, level = _get_llm_client()
            result = parse_slack_export(
                messages_json, users_json, client=client, level=level,
            )
        else:
            # All other tools use text
            text = arguments.get("text", "")
            if not text:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "No text provided"})
                )]

            if name == "extract_timeline":
                result = extract_timeline(text)
            elif name == "identify_actions":
                result = identify_actions(text)
            elif name == "extract_entities":
                result = extract_entities(text)
            elif name == "detect_severity":
                result = detect_severity(text)
            elif name == "generate_summary":
                result = generate_summary(text)
            elif name == "map_to_framework":
                framework = arguments.get("framework", "nist_800_61")
                result = map_to_framework(text, framework=framework)
            else:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": f"Unknown tool: {name}"})
                )]

        # Return result as JSON
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    except Exception as e:
        # Handle any errors gracefully
        return [TextContent(
            type="text",
            text=json.dumps({"error": str(e)})
        )]

async def main() -> None:
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
