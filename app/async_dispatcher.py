"""Offload blocking tools while keeping execution queues off lookup threads."""

import logging
import time

import anyio
from anyio.lowlevel import RunVar

from app.dispatcher import dispatch_tool
from app.schemas import ToolResponse
from app.tools.code import MAX_CONCURRENT_EXECUTIONS, SLOT_WAIT_SECONDS, _error


logger = logging.getLogger("toolbox")
# RunVar scopes these to the running event loop, including isolated test loops.
_CODE_LIMITERS = RunVar("toolbox_code_limiters")


def _code_limiters():
    try:
        return _CODE_LIMITERS.get()
    except LookupError:
        limiters = (anyio.CapacityLimiter(MAX_CONCURRENT_EXECUTIONS),
                    anyio.CapacityLimiter(MAX_CONCURRENT_EXECUTIONS))
        _CODE_LIMITERS.set(limiters)
        return limiters


async def dispatch_tool_async(tool_name: str, arguments: dict) -> ToolResponse:
    start = time.perf_counter()
    try:
        if tool_name != "code_executor":
            return await anyio.to_thread.run_sync(dispatch_tool, tool_name, arguments)

        admission, threads = _code_limiters()
        try:
            with anyio.fail_after(SLOT_WAIT_SECONDS):
                await admission.acquire()
        except TimeoutError:
            # Preserve the executor's visible busy result and protection metadata.
            result = _error("executor busy")
            return ToolResponse(
                status="error",
                result_text=str({k: v for k, v in result.items() if k != "metadata"}),
                metadata={"latency_ms": int((time.perf_counter() - start) * 1000),
                          **result["metadata"]},
            )
        try:
            return await anyio.to_thread.run_sync(
                dispatch_tool, tool_name, arguments, limiter=threads,
            )
        finally:
            admission.release()
    finally:
        logger.info("TOOL REQUEST: tool=%s wall_ms=%.3f", tool_name,
                    (time.perf_counter() - start) * 1000)
