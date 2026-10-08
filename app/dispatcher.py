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
        metadata = {"latency_ms": int((time.time() - start) * 1000)}
        if tool_name == "code_executor":
            metadata.update(result.get("metadata", {}))
        if tool_name == "code_executor" and result["status"] != "success":
            return ToolResponse(
                status="error",
                result_text=str(result),
                metadata=metadata,
            )
        return ToolResponse(
            status="ok",
            result_text=str(result),
            metadata=metadata,
        )
    except Exception as e:
        return ToolResponse(
            status="error",
            result_text=str(e),
        )
