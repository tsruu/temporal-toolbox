"""Execution contracts and containment probes; Linux-only hazards are bounded.

Run with zsh -ic and TMPDIR set under analysis/code_exec/tmp. On a Linux test
container, run as root with the image's dedicated code-exec account. Non-Linux runs
skip all runtime probes; submitted code fails closed on those hosts.
"""
import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import resource
import sys
import threading
import time
import unittest
from unittest.mock import patch

from app.tools import code

LINUX = sys.platform == 'linux'


@unittest.skipUnless(LINUX, 'Submitted code requires the Linux kernel sandbox')
class SandboxTests(unittest.TestCase):
    def run_code(self, source, timeout=5):
        start = time.monotonic()
        result = code.execute_python_code(source, timeout)
        self.assertLess(time.monotonic() - start, timeout + 1)
        self.assertEqual(set(result), {'stdout', 'stderr', 'status', 'metadata'})
        self.assertTrue(all(isinstance(result[k], str) for k in ('stdout', 'stderr', 'status')))
        self.assertIn('protections', result['metadata'])
        return result

    def test_normal_indented_code_and_unicode(self):
        result = self.run_code('    from datetime import date\n    print(date(2026, 10, 8).strftime("%A"))\n    print("école")')
        self.assertEqual({k: result[k] for k in ('stdout', 'stderr', 'status')},
                         {'stdout': 'Thursday\nécole\n', 'stderr': '', 'status': 'success'})

    def test_exception_and_empty_input(self):
        result = self.run_code('print("partial", flush=True); raise ValueError("failure")')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['stdout'], 'partial\n')
        self.assertIn('ValueError: failure', result['stderr'])
        for value in ('', '   ', None):
            self.assertEqual(code.execute_python_code(value)['status'], 'error')

    def test_input_and_timeout_limits(self):
        for timeout in (0, -1, 6, float('inf'), float('nan'), '5'):
            self.assertEqual(code.execute_python_code('print(1)', timeout)['status'], 'error')
        self.assertEqual(code.execute_python_code('x' * (code.MAX_CODE_BYTES + 1))['status'], 'error')

    def test_infinite_loop_default_wall_limit(self):
        result = self.run_code('print("partial", flush=True)\nwhile True: pass')
        self.assertIn(result['status'], ('timeout', 'error'))  # CPU SIGKILL may win the wall timer
        self.assertEqual(result['stdout'], 'partial\n')
        self.assertTrue('timed out' in result['stderr'] or 'signal' in result['stderr'])
        self.assertEqual(self.run_code('print("recovered")')['status'], 'success')

    def test_sleep_timeout_and_closed_streams(self):
        for source in ('import time; print("partial", flush=True); time.sleep(30)',
                       'import os, time; os.close(1); os.close(2); time.sleep(30)'):
            result = self.run_code(source, .5)
            self.assertEqual(result['status'], 'timeout')
            self.assertIn('Execution timed out', result['stderr'])

    def test_output_floods_and_invalid_utf8_are_bounded(self):
        for fd, byte in ((1, 'b"x"'), (2, 'b"x"'), (1, 'b"\\xff"')):
            result = self.run_code(f'import os\nwhile True: os.write({fd}, {byte} * 16384)')
            self.assertEqual(result['status'], 'error')
            self.assertIn('output limit exceeded', result['stderr'])
            for stream in ('stdout', 'stderr'):
                self.assertLessEqual(len(result[stream].encode('utf-8')), code.MAX_OUTPUT_BYTES)

    def test_environment_isolated_stdin_and_temp_cleanup(self):
        with patch.dict(os.environ, {'AZURE_EXEC_TEST_SECRET': 'do-not-inherit',
                                    'HTTP_PROXY': 'http://example.invalid:3128',
                                    'https_proxy': 'http://example.invalid:3128',
                                    'PYTHONPATH': '/secret/path', 'OTHER_EXEC_SECRET': 'test-only'}):
            result = self.run_code('''
import json, os, sys
from pathlib import Path
Path('written.txt').write_text('temporary data')
print(json.dumps({'env': dict(os.environ), 'cwd': os.getcwd(),
                  'isolated': sys.flags.isolated, 'stdin': sys.stdin.read(),
                  'groups': os.getgroups(), 'uid': os.geteuid()}))
''')
        self.assertEqual(result['status'], 'success', result)
        payload = json.loads(result['stdout'])
        env = payload['env']
        self.assertEqual(set(env) - {'LC_CTYPE'}, set(code._environment(payload['cwd'])))
        self.assertEqual(env['HOME'], payload['cwd'])
        self.assertEqual(env['TMPDIR'], payload['cwd'])
        self.assertEqual(payload['isolated'], 1)
        self.assertEqual(payload['stdin'], '')
        self.assertNotEqual(payload['uid'], 0)
        self.assertFalse(Path(payload['cwd']).exists())
        if LINUX and os.geteuid() == 0:
            self.assertEqual(payload['uid'], code._identity()[0])
            self.assertEqual(payload['groups'], [])

    def test_parallel_work_queues_and_slots_recover(self):
        entered, release = threading.Event(), threading.Event()
        active = peak = 0
        lock = threading.Lock()
        original = code._capture
        def hold(process, deadline):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2: entered.set()
            try:
                self.assertTrue(release.wait(2))
                return original(process, deadline)
            finally:
                with lock: active -= 1
        with patch.object(code, '_CALL_SLOTS', threading.BoundedSemaphore(2)), patch.object(code, '_capture', hold), ThreadPoolExecutor(max_workers=20) as pool:
            first = [pool.submit(code.execute_python_code, 'import time; time.sleep(.1); print(1)') for _ in range(2)]
            try:
                self.assertTrue(entered.wait(2))
                rest = [pool.submit(code.execute_python_code, 'print(1)') for _ in range(18)]
                time.sleep(.1)
                self.assertFalse(any(f.done() for f in rest))
            finally:
                release.set()
            self.assertTrue(all(f.result(timeout=10)['status'] == 'success' for f in first + rest))
        self.assertEqual(peak, 2)
        self.assertEqual(self.run_code('print("after saturation")')['status'], 'success')

    def test_setup_failure_releases_slot(self):
        with patch.object(code.subprocess, 'Popen', side_effect=OSError('test launch failure')):
            self.assertEqual(self.run_code('print(1)')['status'], 'error')
        self.assertEqual(self.run_code('print(1)')['status'], 'success')

    @unittest.skipUnless(LINUX, 'Linux kernel and dedicated uid required')
    def test_resource_limits_and_memory_hog(self):
        result = self.run_code('''
import json, resource
print(json.dumps({name: resource.getrlimit(getattr(resource, name)) for name in
 ['RLIMIT_CPU', 'RLIMIT_AS', 'RLIMIT_FSIZE', 'RLIMIT_NPROC', 'RLIMIT_NOFILE', 'RLIMIT_CORE']}))
''')
        self.assertEqual(result['status'], 'success', result)
        limits = json.loads(result['stdout'])
        for name, value in [('RLIMIT_CPU', 5), ('RLIMIT_AS', code.MEMORY_BYTES),
                            ('RLIMIT_FSIZE', code.FILE_BYTES), ('RLIMIT_NPROC', code.MAX_PROCESSES),
                            ('RLIMIT_NOFILE', code.MAX_OPEN_FILES), ('RLIMIT_CORE', 0)]:
            self.assertEqual(limits[name], [value, value])
        result = self.run_code('x = bytearray(2 * 1024 * 1024 * 1024)')
        self.assertEqual(result['status'], 'error')
        self.assertIn('MemoryError', result['stderr'])

    @unittest.skipUnless(LINUX, 'Linux kernel confinement required')
    def test_network_group_escape_and_filesystem_confinement(self):
        # Probe outside writes and reads against a synthetic, non-secret file.
        with code.tempfile.TemporaryDirectory() as outside:
            synthetic = Path(outside, 'synthetic.txt')
            synthetic.write_text('non-secret test fixture')
            # Ordinary permissions would allow access; kernel policy must deny it.
            os.chmod(outside, 0o777)
            os.chmod(synthetic, 0o666)
            result = self.run_code(f'''
import errno, os, socket
from pathlib import Path
operations = [lambda: socket.socket(), lambda: os.setsid(),
              lambda: os.setpgid(0, 0),
              lambda: Path({str(synthetic)!r}).write_text('outside'),
              lambda: Path({str(synthetic)!r}).read_text(),
              lambda: Path('/proc/self/environ').read_bytes()]
for operation in operations:
    try:
        operation()
        raise AssertionError('operation escaped sandbox')
    except PermissionError:
        print('blocked')
Path('local.txt').write_text('ok')
print(Path('local.txt').read_text())
''')
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(result['stdout'], 'blocked\n' * 6 + 'ok\n')
            self.assertEqual(synthetic.read_text(), 'non-secret test fixture')

    @unittest.skipUnless(LINUX, 'RLIMIT_NPROC not safe to probe under macOS development uid')
    def test_bounded_fork_bomb_probe(self):
        # Finite upper bound even if NPROC is broken; no recursive forking.
        result = self.run_code('''
import os, time
children = []
for _ in range(40):
    try:
        pid = os.fork()
    except (BlockingIOError, PermissionError):
        print('fork limited', flush=True)
        break
    if pid == 0:
        time.sleep(30)
        os._exit(0)
    children.append(pid)
else:
    raise AssertionError('process limit failed')
print(','.join(map(str, children)), flush=True)
time.sleep(30)
''', 1)
        self.assertEqual(result['status'], 'timeout', result)
        self.assertIn('fork limited', result['stdout'])
        lines = result['stdout'].splitlines()
        pids = [int(p) for p in (lines[1] if len(lines) > 1 else '').split(',') if p]
        for pid in pids:
            status_file = Path(f'/proc/{pid}/status')
            if status_file.exists():
                self.assertIn('State:\tZ', status_file.read_text())  # inert, awaiting init reaping
        self.assertEqual(self.run_code('print("after forks")')['status'], 'success')

    @unittest.skipUnless(LINUX, 'Linux seccomp required')
    def test_threads_and_optional_libraries(self):
        result = self.run_code('''
import threading
values = []
t = threading.Thread(target=lambda: values.append('ok'))
t.start()
t.join()
assert values == ['ok']
import datetime, math, re, json, itertools, importlib.util
assert datetime.datetime.strptime('2026-10-08', '%Y-%m-%d').year == 2026
for name in ('numpy', 'pandas'):
    if importlib.util.find_spec(name) is not None:
        __import__(name)
print('ok')
''')
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(result['stdout'], 'ok\n')

    def test_exec_is_denied_after_startup(self):
        result = self.run_code('''
import os, sys
try:
    os.execv(sys.executable, [sys.executable, '-I', '-c', "print('escaped')"])
except PermissionError:
    print('blocked')
''')
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(result['stdout'], 'blocked\n')

    @unittest.skipUnless(LINUX, 'Linux resource limits required')
    def test_file_size_and_open_file_limits(self):
        result = self.run_code(f"with open('huge.bin', 'wb') as f:\n while True: f.write(b'x' * 65536)")
        self.assertEqual(result['status'], 'error')
        self.assertTrue('File too large' in result['stderr'] or 'signal' in result['stderr'])
        result = self.run_code("files = [open('file-' + str(i), 'w') for i in range(100)]")
        self.assertEqual(result['status'], 'error')
        self.assertIn('Too many open files', result['stderr'])


@unittest.skipUnless(LINUX, 'Submitted code requires the Linux kernel sandbox')
class ContractTests(unittest.TestCase):
    def test_dispatch_rest_and_mcp(self):
        from fastapi.testclient import TestClient
        from fastmcp import Client
        from app.dispatcher import dispatch_tool
        from app.main import app, mcp
        for source in ('print(5)', '1 / 0', ''):
            success = source == 'print(5)'
            response = dispatch_tool('code_executor', {'code': source})
            self.assertEqual(response.status, 'ok' if success else 'error')
            with TestClient(app) as client:
                response = client.post('/tool', json={'tool_name': 'code_executor',
                                                      'arguments': {'code': source}}).json()
                self.assertEqual(response['status'], 'ok' if success else 'error')
                self.assertEqual(response['result_text'].startswith('ERROR: '), not success)

            async def run():
                async with Client(mcp) as client:
                    result = await client.call_tool('code_executor', {'code': source})
                    text = result.content[0].text
                    self.assertEqual(text.startswith('ERROR: '), not success)
                    payload = ast.literal_eval(text.removeprefix('ERROR: '))
                    self.assertEqual(payload['status'], 'success' if success else 'error')
            asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
