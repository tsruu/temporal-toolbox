# app/main.py

from fastapi import FastAPI, HTTPException
from app.schemas import ToolRequest, ToolResponse
from app.dispatcher import dispatch_tool

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

    result = dispatch_tool(tool_name, arguments)

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

@app.get("/tools")
async def list_tools():
    return [

        {
            "name": "before_absolute_reference",
            "description": "",
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
            "description": "",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "event": {"type": "string"}
                },
                "required": ["entity", "time"]
            }
        },

        {
            "name": "after_absolute_reference",
            "description": "",
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
            "description": "",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "event": {"type": "string"}
                },
                "required": ["entity", "time"]
            }
        },

        {
            "name": "event_time",
            "description": "",
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
            "description": "",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "time": {"type": "string"}
                },
                "required": ["entity", "event"]
            }
        },

        {
            "name": "language_detection",
            "description": "",
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
            "description": "",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "target_language": {"type": "string"}
                },
                "required": ["text", "target_language"]
            }
        },

        {
            "name": "code_excecutor",
            "description": "",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"}
                },
                "required": ["code"]
            }
        }

    ]