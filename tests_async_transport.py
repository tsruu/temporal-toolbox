"""Fresh-SSE event-loop and mixed-load verification against a staged checkout.

Run with --root /tmp/toolbox-async-baseline --label baseline for comparison.
--fake-executor is only for runtimes without the kernel sandbox; no submitted
Python is evaluated in that mode.
"""
import argparse
import asyncio
from contextlib import contextmanager
from datetime import timedelta
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client

from tests_async_support import EXAMPLES, ROOT, rows


def summary(values):
    values = sorted(values)
    if not values:
        return {}
    return {'count': len(values), 'p50_ms': round(values[len(values)//2], 3),
            'p95_ms': round(values[math.ceil(.95*len(values))-1], 3),
            'max_ms': round(values[-1], 3)}


# A process-local test double, never a production modification. It retains the
# real executor semaphore and queue deadline without executing submitted code.
BOOTSTRAP = '''
import os, time
if os.environ.get('ASYNC_TEST_FAKE_EXECUTOR') == '1':
    from app.tools import code
    def fake(source, timeout_seconds=5):
        if not code._CALL_SLOTS.acquire(timeout=code.SLOT_WAIT_SECONDS):
            return code._error('executor busy')
        try:
            time.sleep(3 if 'sleep(3)' in source else .1)
            return {'stdout': '1\\n', 'stderr': '', 'status': 'success'}
        finally:
            code._CALL_SLOTS.release()
    code.execute_python_code = fake
import uvicorn
uvicorn.run('app.main:app', host='127.0.0.1', port=int(os.environ['ASYNC_TEST_PORT']), workers=1, log_level='warning')
'''


@contextmanager
def server(root, port, output, fake=False):
    env = dict(os.environ, PYTHONPATH=str(root), MCP_TRANSPORT='sse',
               CODE_EXEC_ALLOW_SAME_UID='1', ASYNC_TEST_PORT=str(port),
               PYTHONDONTWRITEBYTECODE='1',
               ASYNC_TEST_FAKE_EXECUTOR='1' if fake else '0')
    # Ensure the tests exercise only frozen-cache / same-language translation.
    env.pop('AZURE_TRANSLATOR_KEY', None)
    env.pop('AZURE_TRANSLATOR_REGION', None)
    with output.open('w') as stream:
        process = subprocess.Popen([sys.executable, '-c', BOOTSTRAP], cwd=root,
                                   env=env, stdout=stream, stderr=stream)
        try:
            for _ in range(300):
                if process.poll() is not None:
                    raise RuntimeError('staged server exited; see ' + str(output))
                try:
                    if httpx.get(f'http://127.0.0.1:{port}/health', timeout=.5).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('staged server did not start')
            yield f'http://127.0.0.1:{port}'
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


async def call(base, name, arguments):
    async with sse_client(base + '/sse', timeout=30, sse_read_timeout=30) as streams:
        async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=30)) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            return result.content[0].text


async def schema(base):
    async with sse_client(base + '/sse') as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            result = await session.list_tools()
            return [tool.model_dump(mode='json') for tool in result.tools]


async def event_loop(base):
    errors = []
    async def code_call():
        try:
            value = await call(base, 'code_executor', {'code': 'import time; time.sleep(3); print(1)'})
            if value.startswith('ERROR:'):
                errors.append(value)
        except Exception as error:
            errors.append(type(error).__name__)
    jobs = [asyncio.create_task(code_call()) for _ in range(8)]
    await asyncio.sleep(.2)
    timings, health = [], []
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(20):
            start = time.perf_counter()
            try:
                value = await call(base, 'event_time', {'event': rows('event_time')[0]['event']})
                if value.startswith('ERROR:'):
                    errors.append(value)
            except Exception as error:
                errors.append(type(error).__name__)
            timings.append((time.perf_counter()-start)*1000)
            start = time.perf_counter()
            response = await client.get(base + '/health')
            health.append((time.perf_counter()-start)*1000)
            if response.status_code != 200:
                errors.append('health ' + str(response.status_code))
    await asyncio.gather(*jobs)
    return {'lookups': summary(timings), 'health': summary(health),
            'errors': errors, 'pass': not errors and max(timings) < 300 and max(health) < 300}


def mixed_requests(count):
    requests = []
    absolute = rows('before_absolute_reference')[0]
    event = rows('event_time')[0]
    for index in range(count):
        if index < round(.4*count):
            if index % 4 < 2:
                entity, reference = EXAMPLES[index % len(EXAMPLES)]
                requests.append(('before_chronological_reference' if index % 2 else
                                 'after_chronological_reference', {'entity': entity, 'event': reference}))
            elif index % 4 == 2:
                requests.append(('before_absolute_reference', {k: absolute[k] for k in ('entity', 'time')}))
            else:
                requests.append(('event_time', {'event': event['event']}))
        elif index < round(.65*count):
            requests.append(('code_executor', {'code': 'import time; time.sleep(.1); print(1)'}))
        elif index % 7 == 0:
            # Same-language path requires no API credential.
            requests.append(('translation', {'text': 'Hello world', 'source_language': 'en', 'target_language': 'English'}))
        else:
            requests.append(('language_detection', {'text': 'This is a clear English sentence for language detection.'}))
    return requests


async def load(base, count):
    gate = asyncio.Event()
    elapsed, lookup_elapsed, errors = [], [], []
    async def request(name, args):
        await gate.wait()
        start = time.perf_counter()
        try:
            value = await call(base, name, args)
            if value.startswith('ERROR:'):
                errors.append({'tool': name, 'kind': 'tool_error', 'text': value})
        except Exception as error:
            # Avoid raw request details / exception text in saved logs.
            errors.append({'tool': name, 'kind': type(error).__name__})
        duration = (time.perf_counter()-start)*1000
        elapsed.append(duration)
        if name in ('before_absolute_reference', 'event_time') or 'chronological' in name:
            lookup_elapsed.append(duration)
    tasks = [asyncio.create_task(request(*item)) for item in mixed_requests(count)]
    gate.set()
    await asyncio.gather(*tasks)
    return {'concurrency': count, 'all': summary(elapsed), 'lookups': summary(lookup_elapsed),
            'errors': errors, 'error_count': len(errors),
            'pass': not errors and summary(elapsed)['p95_ms'] < 5000}


class TransportVerification(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.environ.get('ASYNC_TEST_URL'), 'run CLI to start an isolated test server')
    async def test_event_loop(self):
        result = await event_loop(os.environ['ASYNC_TEST_URL'])
        self.assertTrue(result['pass'], result)


async def verify(base, output, label, fake=False):
    from app.tools.code import MAX_CONCURRENT_EXECUTIONS
    async with httpx.AsyncClient(timeout=30) as rest:
        response = await rest.post(base + '/tool', json={
            'tool_name': 'code_executor', 'arguments': {'code': 'print(1)'}})
        probe = response.json()
    tools = await schema(base)
    (output / (label + '_list_tools.json')).write_text(json.dumps(tools, indent=2, ensure_ascii=False) + '\n')
    results = {'label': label, 'translation': 'same-language only',
               'runtime': {'uid': os.geteuid(), 'cpus': os.cpu_count(),
                           'MAX_CONCURRENT_EXECUTIONS': MAX_CONCURRENT_EXECUTIONS,
                           'sandbox_probe_status': probe['status'],
                           'protections': (probe.get('metadata') or {}).get('protections'),
                           'fake_executor': fake},
               'event_loop': await event_loop(base),
               'load_60': await load(base, 60), 'load_120': await load(base, 120)}
    (output / (label + '_transport.json')).write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--label', default='new')
    parser.add_argument('--port', type=int, default=8011)
    parser.add_argument('--fake-executor', action='store_true')
    args = parser.parse_args()
    if args.port < 8011:
        parser.error('test port must be at least 8011')
    output = ROOT / 'docs/async_verification'
    output.mkdir(parents=True, exist_ok=True)
    with server(args.root, args.port, output / (args.label + '_server.log'), args.fake_executor) as base:
        results = asyncio.run(verify(base, output, args.label, args.fake_executor))
    return 0 if all(results[key]['pass'] for key in ('event_loop', 'load_60', 'load_120')) else 1


if __name__ == '__main__':
    sys.exit(main())
