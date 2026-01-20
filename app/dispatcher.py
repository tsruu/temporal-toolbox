# app/dispatcher.py
import time
from app.registry import TOOL_REGISTRY
from app.schemas import ToolResponse


def dispatch_tool(tool_name: str, arguments: dict) -> ToolResponse:
    start = time.time()

    if tool_name not in TOOL_REGISTRY:
        return ToolResponse(
            status="error",
            result_text=f"Unknown tool: {tool_name}",
        )

    tool_fn = TOOL_REGISTRY[tool_name]

    try:
        result = tool_fn(**arguments)
        return ToolResponse(
            status="ok",
            result_text=str(result),
            metadata={"latency_ms": int((time.time() - start) * 1000)},
        )
    except Exception as e:
        return ToolResponse(
            status="error",
            result_text=str(e),
        )