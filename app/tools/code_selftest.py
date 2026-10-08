"""Operator runtime matrix: python -m app.tools.code_selftest (Linux container)."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

from app.tools import code


def run_matrix(execute=None):
    """Run bounded probes through the production executor, returning table rows."""
    execute = execute or code.execute_python_code
    rows = []
    protections = []

    def check(name, source, predicate, timeout=5):
        start = time.monotonic()
        try:
            result = execute(source, timeout)
            active = result.get('metadata', {}).get('protections', {})
            if active not in protections:
                protections.append(active)
            passed = bool(predicate(result))
            detail = result['stderr'][-500:] if not passed else result['stdout'].strip()[:100]
        except Exception as exc:
            passed, detail = False, str(exc)
        rows.append((name, 'PASS' if passed else 'FAIL', time.monotonic() - start, detail))

    def printed(expected):
        return lambda r: r['status'] == 'success' and r['stdout'] == expected and not r['stderr']

    check('normal print', 'print("hello")', printed('hello\n'))
    check('stdlib + script semantics', '''
import datetime, math, re, json, itertools, sys, __main__
assert sys.argv == [__file__] and __main__.__file__ == __file__
assert datetime.datetime.strptime('2026-10-08', '%Y-%m-%d').year == 2026
assert math.sqrt(9) == 3 and re.match('a+', 'aaa')
assert json.loads('[1]') == [1] and list(itertools.product([1], [2])) == [(1, 2)]
print('ok')
''', printed('ok\n'))
    check('exception', 'print("partial", flush=True); raise ValueError("selftest")',
          lambda r: r['status'] == 'error' and r['stdout'] == 'partial\n' and 'ValueError: selftest' in r['stderr'])
    check('infinite loop timeout', 'print("started", flush=True)\nwhile True: pass',
          lambda r: r['stdout'] == 'started\n' and (r['status'] == 'timeout' or
                   r['status'] == 'error' and 'signal' in r['stderr']), timeout=1)
    # A finite fork loop instead of an unbounded bomb; the parent always kills
    # the process group. A fallback without seccomp is reported as a failure.
    check('fork bomb (bounded)', '''
import os, time
children = []
for _ in range(40):
    try:
        pid = os.fork()
    except (PermissionError, BlockingIOError):
        print('blocked' if not children else 'escaped', flush=True)
        break
    if pid == 0:
        time.sleep(30)
        os._exit(0)
    children.append(pid)
else:
    print('escaped', flush=True)
time.sleep(30)
''', lambda r: r['stdout'] == 'blocked\n' and r['status'] == 'timeout', timeout=1)
    check('memory hog', 'bytearray(2 * 1024 * 1024 * 1024)',
          lambda r: r['status'] == 'error' and 'MemoryError' in r['stderr'])
    check('huge output', 'import os\nwhile True: os.write(1, b"x" * 16384)',
          lambda r: r['status'] == 'error' and 'output limit exceeded' in r['stderr'] and
          all(len(r[s].encode('utf-8')) <= code.MAX_OUTPUT_BYTES for s in ('stdout', 'stderr')))
    with tempfile.TemporaryDirectory(prefix='code-selftest-outside-') as outside:
        fixture = Path(outside, 'synthetic.txt')
        fixture.write_text('synthetic fixture')
        os.chmod(outside, 0o777)
        os.chmod(fixture, 0o666)
        check('outside write + truncate', f'''
import os
from pathlib import Path
for operation in (lambda: Path({str(fixture)!r}).write_text('escaped'),
                  lambda: os.truncate({str(fixture)!r}, 0),
                  lambda: os.open({str(fixture)!r}, os.O_RDONLY | os.O_TRUNC)):
    try:
        operation()
        print('escaped')
    except PermissionError:
        print('blocked')
Path('local.txt').write_text('ok')
assert Path('local.txt').read_text() == 'ok'
''', lambda r: printed('blocked\nblocked\nblocked\n')(r) and fixture.read_text() == 'synthetic fixture')
    check('socket attempt', '''
import socket
try:
    socket.socket()
    print('escaped')
except PermissionError:
    print('blocked')
''', printed('blocked\n'))
    marker_name = 'CODE_EXEC_SELFTEST_SECRET'
    previous = os.environ.get(marker_name)
    os.environ[marker_name] = 'synthetic-selftest-marker'
    try:
        check('/proc/self/environ secrets', '''
from pathlib import Path
try:
    data = Path('/proc/self/environ').read_bytes()
    assert b'CODE_EXEC_SELFTEST_SECRET' not in data
    assert b'synthetic-selftest-marker' not in data
    print('scrubbed')
except PermissionError:
    print('blocked')
''', lambda r: r['status'] == 'success' and not r['stderr'] and r['stdout'] in ('scrubbed\n', 'blocked\n'))
    finally:
        if previous is None:
            os.environ.pop(marker_name, None)
        else:
            os.environ[marker_name] = previous
    check('exec after startup', '''
import os, sys
try:
    os.execv(sys.executable, [sys.executable, '-I', '-c', "print('escaped')"])
except PermissionError:
    print('blocked')
''', printed('blocked\n'))
    check('threads', '''
import threading
result = []
t = threading.Thread(target=lambda: result.append('ok'))
t.start()
t.join()
print(result[0])
''', printed('ok\n'))
    for package, operation in (
            ('numpy', "assert package.dot([1, 2], [3, 4]) == 11"),
            ('pandas', "assert package.Series([1, 2]).sum() == 3")):
        check(f'{package} import if installed', f'''
import importlib.util
if importlib.util.find_spec({package!r}) is None:
    print('not installed')
else:
    import {package} as package
    {operation}
    print('ok')
''', lambda r: r['status'] == 'success' and not r['stderr'] and r['stdout'] in ('ok\n', 'not installed\n'))

    # Force two slots in this standalone CLI so twenty calls actually exercise
    # queueing even if the operator configured >=20 production slots.
    start = time.monotonic()
    original_slots = code._CALL_SLOTS
    code._CALL_SLOTS = threading.BoundedSemaphore(2)
    barrier = threading.Barrier(20)
    try:
        def queued_call(_):
            barrier.wait(timeout=10)
            return execute('import time; time.sleep(.2); print("queued")')

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(queued_call, range(20)))
        for result in results:
            active = result.get('metadata', {}).get('protections', {})
            if active not in protections:
                protections.append(active)
        passed = all(printed('queued\n')(r) for r in results)
        passed = passed and any(r.get('metadata', {}).get('queue_wait_ms', 0) >= 100 for r in results)
        successes = sum(printed('queued\n')(r) for r in results)
        detail = f'{successes}/20 successful; two slots'
    except Exception as exc:
        passed, detail = False, str(exc)
    finally:
        code._CALL_SLOTS = original_slots
    rows.append(('20 parallel calls queued', 'PASS' if passed else 'FAIL', time.monotonic() - start, detail))
    return rows, protections


def main():
    if sys.platform != 'linux':
        print('FAIL: runtime self-test requires a Linux container; no submitted code was run.')
        return 2
    print(f'Configured slots: {code.MAX_CONCURRENT_EXECUTIONS}; queue timeout: {code.SLOT_WAIT_SECONDS}s')
    rows, protections = run_matrix()
    print(f"{'TEST':36} {'RESULT':6} {'SECONDS':>7}  DETAIL")
    for name, status, elapsed, detail in rows:
        print(f'{name:36} {status:6} {elapsed:7.2f}  {detail.replace(chr(10), " | ")}')
    print('Active protections: ' + json.dumps(protections, sort_keys=True))
    failures = sum(row[1] == 'FAIL' for row in rows)
    print(f'{len(rows) - failures}/{len(rows)} PASS; {failures} FAIL')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
