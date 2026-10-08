"""Bounded Python execution. Linux containers use a dedicated code-exec uid.

The trusted launcher applies child-only limits before evaluation; no Python preexec_fn
runs in the threaded toolbox process. See docs/code_exec/SERVER_CHANGE.md for the
rootless fallback and the limits of this sandbox.
"""
import json
import logging
import math
import os
from pathlib import Path
import pwd
import selectors
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from typing import Any, Dict


def _slot_count():
    value = os.getenv('CODE_EXEC_SLOTS')
    if value is None:
        return min(16, max(2, (os.cpu_count() or 1) // 4))
    try:
        slots = int(value)
    except ValueError as exc:
        raise ValueError('CODE_EXEC_SLOTS must be a positive integer') from exc
    if slots < 1:
        raise ValueError('CODE_EXEC_SLOTS must be a positive integer')
    return slots


MAX_CONCURRENT_EXECUTIONS = _slot_count()
SLOT_WAIT_SECONDS = 10
MAX_OUTPUT_BYTES = 64 * 1024  # per stream, including truncation marker
MAX_CODE_BYTES = 256 * 1024
MAX_TIMEOUT_SECONDS = 5
MEMORY_BYTES = 1024 * 1024 * 1024
FILE_BYTES = 8 * 1024 * 1024
MAX_PROCESSES = 32  # Linux counts processes/threads across the execution uid
MAX_OPEN_FILES = 64
_CALL_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_EXECUTIONS)
_RUNNER = str(Path(__file__).with_name('_code_runner.py').resolve())
_TRUNCATED = b'\n[output truncated]\n'
logger = logging.getLogger(__name__)


def _error(message):
    protections = {'landlock_abi': 0, 'seccomp': False}
    logger.info('code_executor protections=%s status=error reason=%s', protections, message)
    return {'stdout': '', 'stderr': message, 'status': 'error',
            'metadata': {'protections': protections}}


class CodeExecutionError(Exception):
    pass


def _identity():
    if sys.platform != 'linux':
        raise CodeExecutionError('Code execution requires the Linux kernel sandbox')
    if os.geteuid() == 0:
        try:
            account = pwd.getpwnam('code-exec')
        except KeyError as exc:
            raise CodeExecutionError('Missing dedicated code-exec user') from exc
        if account.pw_uid == 0:
            raise CodeExecutionError('code-exec user must be non-root')
        return account.pw_uid, account.pw_gid
    if os.getenv('CODE_EXEC_ALLOW_SAME_UID') != '1':
        raise CodeExecutionError(
            'Cannot switch to code-exec uid without root; rootless operation requires '
            'explicit CODE_EXEC_ALLOW_SAME_UID=1 (see sandbox limitations)')
    # An explicitly enabled rootless Linux runtime still requires kernel policies.
    return os.geteuid(), os.getegid()


def _environment(tmpdir):
    # Never copy the server environment: credentials, proxies, Python path and
    # inherited HOME are intentionally absent. Helper options come via argv.
    return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': tmpdir,
            'TMPDIR': tmpdir, 'TMP': tmpdir, 'TEMP': tmpdir,
            'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
            # Avoid CPU-count-sized BLAS pools exhausting AS/NPROC across slots.
            'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
            'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1'}


def _kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _capture(process, deadline):
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    reason = None
    with selectors.DefaultSelector() as selector:
        for name in buffers:
            stream = getattr(process, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reason = 'Execution timed out'
                break
            for key, _ in selector.select(min(remaining, .05)):
                chunk = os.read(key.fd, 16384)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffer = buffers[key.data]
                room = MAX_OUTPUT_BYTES - len(buffer)
                buffer.extend(chunk[:room])
                if len(chunk) > room:
                    buffer[-len(_TRUNCATED):] = _TRUNCATED
                    reason = 'Execution output limit exceeded'
                    break
            if reason:
                break
        # A program can close stdout/stderr and continue running.
        if reason is None:
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                reason = 'Execution timed out'
    # Kill descendants even when the original Python process exited normally.
    _kill_group(process)
    process.wait()
    stdout = buffers['stdout'].decode('utf-8', errors='replace')
    stderr = buffers['stderr'].decode('utf-8', errors='replace')
    # Replacement characters can expand invalid bytes; enforce the UTF-8 cap too.
    stdout = stdout.encode('utf-8')[:MAX_OUTPUT_BYTES].decode('utf-8', errors='ignore')
    stderr = stderr.encode('utf-8')[:MAX_OUTPUT_BYTES].decode('utf-8', errors='ignore')
    if reason:
        stderr = (reason + ('\n' + stderr if stderr else ''))
        stderr = stderr.encode('utf-8')[:MAX_OUTPUT_BYTES].decode('utf-8', errors='ignore')
        status = 'timeout' if reason == 'Execution timed out' else 'error'
    else:
        status = 'success' if process.returncode == 0 else 'error'
        if process.returncode < 0:
            stderr = f'Execution terminated by signal {-process.returncode}\n' + stderr
            stderr = stderr.encode('utf-8')[:MAX_OUTPUT_BYTES].decode('utf-8', errors='ignore')
    return {'stdout': stdout, 'stderr': stderr, 'status': status}


def execute_python_code(code: str, timeout_seconds: float = 5) -> Dict[str, Any]:
    """Return stdout/stderr/status and active kernel protections.

    Wait up to ten seconds for a slot, then return executor busy. The five-second
    wall limit starts after queueing and includes launcher startup. Callers may
    shorten it, but cannot raise it. The MCP code-only signature is unchanged.
    """
    if not isinstance(code, str) or not code.strip():
        return _error('Empty code input')
    if len(code.encode('utf-8')) > MAX_CODE_BYTES:
        return _error('Code input limit exceeded')
    if (not isinstance(timeout_seconds, (int, float)) or
            not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS):
        return _error('Timeout must be positive and at most 5 seconds')
    queued_at = time.monotonic()
    if not _CALL_SLOTS.acquire(timeout=SLOT_WAIT_SECONDS):
        return _error('executor busy')
    queue_wait_ms = int((time.monotonic() - queued_at) * 1000)
    process = None
    try:
        uid, gid = _identity()
        with tempfile.TemporaryDirectory(prefix='code-exec-') as tmpdir:
            script = os.path.join(tmpdir, 'script.py')
            with open(script, 'w', encoding='utf-8') as stream:
                stream.write(textwrap.dedent(code))
            os.chmod(script, 0o600)
            if os.geteuid() == 0:
                os.chown(tmpdir, uid, gid)
                os.chown(script, uid, gid)
            limits = json.dumps({'cpu': math.ceil(timeout_seconds), 'memory': MEMORY_BYTES,
                                 'file': FILE_BYTES, 'processes': MAX_PROCESSES,
                                 'open_files': MAX_OPEN_FILES})
            deadline = time.monotonic() + timeout_seconds
            # Trusted launcher closes this pipe before evaluating submitted code.
            # It never shares stdout/stderr framing with untrusted output.
            metadata_read, metadata_write = os.pipe()
            try:
                process = subprocess.Popen(
                    [sys.executable, '-I', _RUNNER, script, str(uid), str(gid),
                     limits, str(metadata_write)],
                    cwd=tmpdir, env=_environment(tmpdir), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=True, close_fds=True, pass_fds=(metadata_write,))
            finally:
                os.close(metadata_write)
                if process is None:
                    os.close(metadata_read)
            try:
                result = _capture(process, deadline)
                raw = os.read(metadata_read, 4096)
                protections = json.loads(raw) if raw else {'landlock_abi': 0, 'seccomp': False}
                result['metadata'] = {'protections': protections, 'queue_wait_ms': queue_wait_ms}
                logger.info('code_executor protections=%s status=%s', protections, result['status'])
                return result
            finally:
                os.close(metadata_read)
                _kill_group(process)
                process.wait()
                process.stdout.close()
                process.stderr.close()
    except Exception as exc:
        return _error(f'Execution setup failed: {exc}')
    finally:
        _CALL_SLOTS.release()
