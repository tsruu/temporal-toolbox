# app/main.py

from fastapi import FastAPI, HTTPException
from app.schemas import ToolRequest, ToolResponse
from app.dispatcher import dispatch_tool
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("toolbox")

app = FastAPI()


# -------------------------------
# Existing internal API
# -------------------------------
@app.post("/tool", response_model=ToolResponse)
async def tool_endpoint(req: ToolRequest):
    return dispatch_tool(req.tool_name, req.arguments)


# -------------------------------
# MCP compatible endpoint
# -------------------------------
@app.post("/mcp")
async def mcp_endpoint(req: dict):
    """
    Expected MCP request format:
    {
        "name": "tool_name",
        "arguments": {...}
    }

    Expected MCP response format:
    {
        "content": [
            {"type": "text", "text": "..."}
        ]
    }
    """

    if "name" not in req:
        raise HTTPException(status_code=400, detail="Missing tool name")

    tool_name = req["name"]
    arguments = req.get("arguments", {})

    # Log the tool being called
    logger.info("Tool call: %s", tool_name)

    result = dispatch_tool(tool_name, arguments)

    # Log the result status
    logger.info("Tool result: %s -> %s", tool_name, result.status)

    # Error case
    if result.status != "ok":
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"ERROR: {result.result_text}"
                }
            ]
        }

    # Success case
    return {
        "content": [
            {
                "type": "text",
                "text": result.result_text
            }
        ]
    }

@app.get("/health")
def health():
    return {"status":"ok"}

@app.get("/tools")
async def list_tools():
    return [

        {
            "name": "before_absolute_reference",
            "description": "Answers questions of the form “What was the entity associated with immediately before a given absolute time?”. Use this to retrieve the entity’s role, affiliation, or state just prior to a specific date or year. The result is looked up from structured data, not inferred.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "time": {"type": "string"}
                },
                "required": ["entity", "time"]
            }
        },

        {
            "name": "before_chronological_reference",
            "description": "Answers questions asking what an entity was associated with immediately before another event. Use this when the reference point is a named event (e.g., a team, organization, or historical milestone), not a date. The answer is retrieved from structured records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "event": {"type": "string"}
                },
                "required": ["entity", "event"]
            }
        },

        {
            "name": "after_absolute_reference",
            "description": "Answers questions of the form “What was the entity associated with immediately after a given absolute time?”. Use this to retrieve the entity’s role, affiliation, or state just after a specific date or year. The result is looked up from structured data, not inferred.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "time": {"type": "string"}
                },
                "required": ["entity", "time"]
            }
        },

        {
            "name": "after_chronological_reference",
            "description": "Answers questions asking what an entity was associated with immediately after another event. Use this when the reference point is a named event (e.g., a team, organization, or historical milestone), not a date. The answer is retrieved from structured records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "event": {"type": "string"}
                },
                "required": ["entity", "event"]
            }
        },

        {
            "name": "event_time",
            "description": "Retrieves the exact date or time when a specified event occurred. Use this when a question requires knowing when an event happened, especially to compare or reason about the order of multiple events. The result is obtained via structured data lookup, not inference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event": {"type": "string"}
                },
                "required": ["event"]
            }
        },

        {
            "name": "entity_time_event",
            "description": "Answers questions asking what role, position, or event an entity had at a specific time. Use this when the question is “What was X doing / what was X’s status at time T?”. The answer is retrieved from structured data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "time": {"type": "string"}
                },
                "required": ["entity", "time"]
            }
        },

        {
            "name": "language_detection",
            "description": "Detects the language of the provided text. Use this when the input language is unknown or needs to be identified before further processing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"}
                },
                "required": ["text"]
            }
        },

        {
            "name": "translation",
            "description": "Translates the provided text from a specified source language into the specified target language. Use this when a translation is required before further processing",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": { "type": "string" },
                    "source_language": { "type": "string" },
                    "target_language": { "type": "string" }
                },
                "required": ["text", "source_language", "target_language"]
            }
        },

        {
            "name": "code_executor",
            "description": "Executes provided code to perform precise computations or transformations. Use this when a question requires exact calculation, iteration, or programmatic handling of quantities such as dates, times, intervals, units, or arithmetic that should not be approximated by reasoning alone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"}
                },
                "required": ["code"]
            }
        }

    ]