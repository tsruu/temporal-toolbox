# app/main.py

import logging
import os
import time

from typing import Annotated

from pydantic import Field
from fastapi import FastAPI
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.concurrency import run_in_threadpool

from app.schemas import ToolRequest, ToolResponse
from app.dispatcher import dispatch_tool


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("toolbox")
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.DEBUG)


# --------------------------------
# MCP configuration
# --------------------------------
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "sse")
REPLICA_ID = (
    os.getenv("HOSTNAME")
    or os.getenv("WEBSITE_INSTANCE_ID")
    or "local"
)


# --------------------------------
# MCP server definition (FastMCP)
# --------------------------------
mcp = FastMCP("toolbox")

logger.info(
    "MCP SERVER STARTUP: transport=%s replica_id=%s pid=%s",
    MCP_TRANSPORT,
    REPLICA_ID,
    os.getpid(),
)


@mcp.tool()
def before_absolute_reference(
    entity: Annotated[str, Field(description='The subject asked about.')],
    time: Annotated[str, Field(description='The date: YYYY, YYYY-MM, YYYY-MM-DD or Month YYYY.')],
) -> str:
    """
    Answers questions asking what an entity was associated with immediately before a given date.
    Arguments must be in English. The result is looked up from structured data, not inferred.
    """
    result = dispatch_tool(
        "before_absolute_reference",
        {"entity": entity, "time": time},
    )
    if result.status != "ok":
        return f"ERROR: {result.result_text}"
    return result.result_text


@mcp.tool()
def before_chronological_reference(
    entity: Annotated[str, Field(description='The series or subject whose history is asked about.')],
    event: Annotated[str, Field(description='The named item the question is anchored on.')],
) -> str:
    """
    Answers questions asking what came immediately before a named reference item in an entity's history.
    Use this when the reference point is a named item, not a date.
    Arguments must be in English. The answer is retrieved from structured records.
    """
    result = dispatch_tool(
        "before_chronological_reference",
        {"entity": entity, "event": event},
    )
    if result.status != "ok":
        return f"ERROR: {result.result_text}"
    return result.result_text


@mcp.tool()
def after_absolute_reference(
    entity: Annotated[str, Field(description='The subject asked about.')],
    time: Annotated[str, Field(description='The date: YYYY, YYYY-MM, YYYY-MM-DD or Month YYYY.')],
) -> str:
    """
    Answers questions asking what an entity was associated with immediately after a given date.
    Arguments must be in English. The result is looked up from structured data, not inferred.
    """
    result = dispatch_tool(
        "after_absolute_reference",
        {"entity": entity, "time": time},
    )
    if result.status != "ok":
        return f"ERROR: {result.result_text}"
    return result.result_text


@mcp.tool()
def after_chronological_reference(
    entity: Annotated[str, Field(description='The series or subject whose history is asked about.')],
    event: Annotated[str, Field(description='The named item the question is anchored on.')],
) -> str:
    """
    Answers questions asking what came immediately after a named reference item in an entity's history.
    Use this when the reference point is a named item, not a date.
    Arguments must be in English. The answer is retrieved from structured records.
    """
    result = dispatch_tool(
        "after_chronological_reference",
        {"entity": entity, "event": event},
    )
    if result.status != "ok":
        return f"ERROR: {result.result_text}"
    return result.result_text


@mcp.tool()
def event_time(event: Annotated[str, Field(description="The event's name or a short description.")]) -> str:
    """
    Retrieves the exact date or time when a specified event occurred.
    Use this when a question requires knowing when an event happened, e.g. to order several events.
    The result is looked up from structured data, not inference. The argument must be in English.
    """
    result = dispatch_tool(
        "event_time",
        {"event": event},
    )
    if result.status != "ok":
        return f"ERROR: {result.result_text}"
    return result.result_text


@mcp.tool()
def entity_time_event(
    entity: Annotated[str, Field(description='The subject asked about.')],
    time: Annotated[str, Field(description='The date: YYYY, YYYY-MM, YYYY-MM-DD or Month YYYY.')],
) -> str:
    """
    Answers questions asking what role, position, or affiliation an entity had at a specific time.
    Arguments must be in English. The answer is retrieved from structured data.
    """
    result = dispatch_tool(
        "entity_time_event",
        {"entity": entity, "time": time},
    )
    if result.status != "ok":
        return f"ERROR: {result.result_text}"
    return result.result_text


@mcp.tool()
def language_detection(text: str) -> str:
    """
    Detects the language of the provided text.
    Use this when the input language is unknown or needs to be identified before further processing.
    """
    result = dispatch_tool(
        "language_detection",
        {"text": text},
    )
    if result.status != "ok":
        return f"ERROR: {result.result_text}"
    return result.result_text


@mcp.tool()
def translation(
    text: str,
    source_language: Annotated[str, Field(description='A language name or ISO code.')],
    target_language: Annotated[str, Field(description='A language name or ISO code.')],
) -> str:
    """
    Translates the provided text from a source language into a target language.
    Use this to translate non-English names before using the lookup tools.
    """
    result = dispatch_tool(
        "translation",
        {
            "text": text,
            "source_language": source_language,
            "target_language": target_language,
        },
    )
    if result.status != "ok":
        return f"ERROR: {result.result_text}"
    return result.result_text


@mcp.tool()
def code_executor(code: str) -> str:
    """
    Executes raw Python code in an isolated subprocess and returns stdout/stderr.
    Use for exact calculations involving dates, times, arithmetic, or any computation that should not be approximated.

    Rules:
    - Submit raw Python only — no markdown fences (no ```python), no shell commands
    - Always use print() for output; bare expressions produce no output
    - Import everything you need; no libraries are pre-imported
    """
    result = dispatch_tool(
        "code_executor",
        {"code": code},
    )
    if result.status != "ok":
        return f"ERROR: {result.result_text}"
    return result.result_text


# -------------------------------
# Existing internal FastAPI API
# -------------------------------
api_app = FastAPI()


@api_app.middleware("http")
async def logging_middleware(request: Request, call_next):
    body = await request.body()
    truncated_body = body[:500] if body else b""
    try:
        body_repr = truncated_body.decode("utf-8", errors="replace")
    except Exception:
        body_repr = str(truncated_body)

    logger.info(
        "REQUEST: %s %s | body: %s",
        request.method,
        request.url,
        body_repr,
    )

    response = await call_next(request)

    logger.info(
        "RESPONSE: %s for %s %s",
        response.status_code,
        request.method,
        request.url,
    )
    return response


@api_app.post("/tool", response_model=ToolResponse)
async def tool_endpoint(req: ToolRequest):
    # Execution and translation can block. Keep health/lookup requests and the
    # executor's queue responsive while those calls run.
    result = await run_in_threadpool(dispatch_tool, req.tool_name, req.arguments)
    if result.status != "ok":
        result.result_text = f"ERROR: {result.result_text}"
    return result


@api_app.get("/health")
def health():
    return {"status": "ok"}

@api_app.get("/debug")
def debug():
    routes = []

    for r in app.routes:
        methods = getattr(r, "methods", None)
        routes.append({
            "path": getattr(r, "path", str(r)),
            "name": getattr(r, "name", None),
            "methods": list(methods) if methods else None
        })

    return {
        "server_version": "3",
        "routes": routes
    }

@api_app.get("/tools")
async def list_tools():
    return [

        {
            "name": "before_absolute_reference",
            "description": "Answers questions asking what an entity was associated with immediately before a given date.\nArguments must be in English. The result is looked up from structured data, not inferred.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "The subject asked about."},
                    "time": {"type": "string", "description": "The date: YYYY, YYYY-MM, YYYY-MM-DD or Month YYYY."}
                },
                "required": ["entity", "time"]
            }
        },

        {
            "name": "before_chronological_reference",
            "description": "Answers questions asking what came immediately before a named reference item in an entity's history.\nUse this when the reference point is a named item, not a date.\nArguments must be in English. The answer is retrieved from structured records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "The series or subject whose history is asked about."},
                    "event": {"type": "string", "description": "The named item the question is anchored on."}
                },
                "required": ["entity", "event"]
            }
        },

        {
            "name": "after_absolute_reference",
            "description": "Answers questions asking what an entity was associated with immediately after a given date.\nArguments must be in English. The result is looked up from structured data, not inferred.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "The subject asked about."},
                    "time": {"type": "string", "description": "The date: YYYY, YYYY-MM, YYYY-MM-DD or Month YYYY."}
                },
                "required": ["entity", "time"]
            }
        },

        {
            "name": "after_chronological_reference",
            "description": "Answers questions asking what came immediately after a named reference item in an entity's history.\nUse this when the reference point is a named item, not a date.\nArguments must be in English. The answer is retrieved from structured records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "The series or subject whose history is asked about."},
                    "event": {"type": "string", "description": "The named item the question is anchored on."}
                },
                "required": ["entity", "event"]
            }
        },

        {
            "name": "event_time",
            "description": "Retrieves the exact date or time when a specified event occurred.\nUse this when a question requires knowing when an event happened, e.g. to order several events.\nThe result is looked up from structured data, not inference. The argument must be in English.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event": {"type": "string", "description": "The event's name or a short description."}
                },
                "required": ["event"]
            }
        },

        {
            "name": "entity_time_event",
            "description": "Answers questions asking what role, position, or affiliation an entity had at a specific time.\nArguments must be in English. The answer is retrieved from structured data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "The subject asked about."},
                    "time": {"type": "string", "description": "The date: YYYY, YYYY-MM, YYYY-MM-DD or Month YYYY."}
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
            "description": "Translates the provided text from a source language into a target language.\nUse this to translate non-English names before using the lookup tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": { "type": "string" },
                    "source_language": {"type": "string", "description": "A language name or ISO code."},
                    "target_language": {"type": "string", "description": "A language name or ISO code."}
                },
                "required": ["text", "source_language", "target_language"]
            }
        },

        {
            "name": "code_executor",
            "description": (
                "Executes raw Python code in an isolated subprocess and returns stdout/stderr.\n"
                "Use for exact calculations involving dates, times, arithmetic, or any computation that should not be approximated.\n"
                "\n"
                "Rules:\n"
                "- Submit raw Python only — no markdown fences (no ```python), no shell commands\n"
                "- Always use print() for output; bare expressions produce no output\n"
                "- Import everything you need; no libraries are pre-imported"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"}
                },
                "required": ["code"]
            }
        }

    ]


app = mcp.http_app(transport=MCP_TRANSPORT)
app.mount("/", api_app)  # Starlette's mount method
