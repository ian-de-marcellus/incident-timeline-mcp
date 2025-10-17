#!/usr/bin/env python3
"""
MCP Server for incident timeline extraction.
Exposes extraction tools to Claude via Model Context Protocol.
"""

import asyncio
import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Import our extractors
from extractors import (
    extract_timeline,
    identify_actions,
    extract_entities,
    detect_severity,
    generate_summary,
)

# Create the server instance
app = Server("incident-timeline-extractor")

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
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    Handle tool calls from Claude.
    Routes to appropriate extractor function based on tool name.
    """
    # Get the incident text from arguments
    text = arguments.get("text", "")
    
    if not text:
        return [TextContent(
            type="text",
            text=json.dumps({"error": "No text provided"})
        )]
    
    # Route to appropriate extractor
    try:
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
    
async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())