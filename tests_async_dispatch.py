"""Host-safe concurrency contracts with a fake blocking dispatcher."""

import asyncio
import ast
import importlib.util
from pathlib import Path
import sys
import subprocess
import threading
import time
import types
import unittest
from unittest.mock import patch

import anyio

from app.schemas import ToolResponse


def load_dispatcher():
    # Only the blocking dispatcher is replaced; exercise real AnyIO offloading,
    # admission deadlines and pool isolation without MCP or submitted Python.
    stub = types.ModuleType("app.dispatcher")
    stub.dispatch_tool = lambda *_: ToolResponse(status="ok", result_text="1")
    spec = importlib.util.spec_from_file_location(
        "async_dispatch_under_test", Path(__file__).parent / "app/async_dispatcher.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"app.dispatcher": stub}):
        spec.loader.exec_module(module)
    return module


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_baseline_and_new_event_loop_with_eight_sleeping_calls(self):
        module = load_dispatcher()

        def blocking(name, arguments):
            if name == "code_executor":
                time.sleep(3)
            return ToolResponse(status="ok", result_text="1")

        def wrapper(source, name):
            node = next(n for n in ast.parse(source).body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
            node.decorator_list = []
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
            tree = ast.Module(body=[node], type_ignores=[])
            namespace = {"dispatch_tool": blocking,
                         "dispatch_tool_async": module.dispatch_tool_async}
            exec(compile(tree, "tool_wrapper_under_test", "exec"), namespace)
            return namespace[name]

        baseline = subprocess.check_output(
            ["git", "show", "4fddcdb:app/main.py"], text=True)
        current = (Path(__file__).parent / "app/main.py").read_text()
        results = {}
        with patch.object(module, "dispatch_tool", blocking):
            for label, source in (("baseline", baseline), ("new", current)):
                execute = wrapper(source, "code_executor")
                lookup = wrapper(source, "event_time")
                async def code_call():
                    if label == "baseline":
                        return execute("import time; time.sleep(3); print(1)")
                    return await execute("import time; time.sleep(3); print(1)")
                start = time.perf_counter()
                jobs = [asyncio.create_task(code_call()) for _ in range(8)]
                await asyncio.sleep(.2)
                responsiveness = (time.perf_counter() - start) * 1000
                values = []
                for _ in range(20):
                    start = time.perf_counter()
                    if label == "baseline":
                        lookup("event")
                    else:
                        await lookup("event")
                    values.append((time.perf_counter() - start) * 1000)
                await asyncio.gather(*jobs)
                results[label] = {"loop_delay_ms": responsiveness,
                                  "lookup_max_ms": max(values)}
        self.assertGreater(results["baseline"]["loop_delay_ms"], 23000)
        self.assertLess(results["new"]["loop_delay_ms"], 300)
        self.assertLess(results["new"]["lookup_max_ms"], 300)
        print("Host-only wrapper/fake comparison (no SSE or health):", results, flush=True)

    async def test_executor_queue_leaves_default_pool_and_loop_available(self):
        module = load_dispatcher()
        entered = threading.Event()
        release = threading.Event()
        active = peak = 0
        guard = threading.Lock()

        def blocking(name, arguments):
            nonlocal active, peak
            if name == "code_executor":
                with guard:
                    active += 1
                    peak = max(peak, active)
                    if active == 2:
                        entered.set()
                try:
                    if not release.wait(3):
                        raise AssertionError("test release missing")
                finally:
                    with guard:
                        active -= 1
            return ToolResponse(status="ok", result_text=name)

        with patch.object(module, "MAX_CONCURRENT_EXECUTIONS", 2), \
             patch.object(module, "dispatch_tool", blocking):
            pool = anyio.to_thread.current_default_thread_limiter()
            original = pool.total_tokens
            pool.total_tokens = 2
            tasks = [asyncio.create_task(module.dispatch_tool_async("code_executor", {}))
                     for _ in range(60)]
            try:
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(.01)
                self.assertTrue(entered.is_set())
                self.assertEqual(pool.borrowed_tokens, 0)
                for _ in range(20):
                    start = time.perf_counter()
                    result = await module.dispatch_tool_async("event_time", {})
                    self.assertEqual(result.result_text, "event_time")
                    self.assertLess(time.perf_counter() - start, .3)
            finally:
                release.set()
                await asyncio.gather(*tasks)
                pool.total_tokens = original
            self.assertEqual(peak, 2)

    async def test_admission_deadline_preserves_busy_text(self):
        module = load_dispatcher()
        with patch.object(module, "MAX_CONCURRENT_EXECUTIONS", 1), \
             patch.object(module, "SLOT_WAIT_SECONDS", .01):
            admission, threads = module._code_limiters()
            await admission.acquire()
            try:
                result = await asyncio.create_task(module.dispatch_tool_async(
                    "code_executor", {"code": "print(1)"}))
            finally:
                admission.release()
            self.assertEqual(result.status, "error")
            self.assertEqual(result.result_text,
                             "{'stdout': '', 'stderr': 'executor busy', 'status': 'error'}")
            self.assertEqual(result.metadata["protections"], {"landlock_abi": 0, "seccomp": False})
            self.assertEqual(threads.borrowed_tokens, 0)

    async def test_failure_and_cancelled_queue_release_capacity(self):
        module = load_dispatcher()
        with patch.object(module, "MAX_CONCURRENT_EXECUTIONS", 1):
            admission, threads = module._code_limiters()
            await admission.acquire()
            queued = asyncio.create_task(module.dispatch_tool_async("code_executor", {}))
            await asyncio.sleep(.01)
            queued.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await queued
            admission.release()
            with patch.object(module, "dispatch_tool", side_effect=RuntimeError("test failure")):
                with self.assertRaisesRegex(RuntimeError, "test failure"):
                    await module.dispatch_tool_async("code_executor", {})
            self.assertEqual(admission.borrowed_tokens, 0)
            self.assertEqual(threads.borrowed_tokens, 0)


if __name__ == "__main__":
    unittest.main()
