"""Host-safe checks: submitted code, subprocesses and real limits never run."""
import ctypes
import errno
import importlib.util
import json
import os
from pathlib import Path
import sys
import struct
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, mock_open, patch
from app.tools import code

spec = importlib.util.spec_from_file_location('runner', Path(__file__).parent/'app/tools/_code_runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

class PolicyTests(unittest.TestCase):
    def test_environment_allowlist(self):
        with patch.dict(os.environ, {'AZURE_TEST_SECRET':'test-only', 'HTTPS_PROXY':'test-only',
                                    'HOME':'/secret', 'PYTHONPATH':'/secret'}, clear=True):
            actual=code._environment('/test')
        self.assertEqual(actual, {'PATH':'/usr/local/bin:/usr/bin:/bin', 'HOME':'/test',
                                 'TMPDIR':'/test','TMP':'/test','TEMP':'/test',
                                 'LANG':'C.UTF-8','LC_ALL':'C.UTF-8',
                                 'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1',
                                 'MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'})

    def test_validation_without_launch(self):
        with patch.object(code.subprocess, 'Popen', side_effect=AssertionError('launch forbidden')):
            for source in ('', ' ', None, 42, 'x'*(code.MAX_CODE_BYTES+1)):
                self.assertEqual(code.execute_python_code(source)['status'],'error')
            for timeout in (0,-1,6,float('inf'),float('nan'),'5'):
                self.assertEqual(code.execute_python_code('print(1)',timeout)['status'],'error')

    def test_slot_default_and_override(self):
        for cpus, expected in ((None, 2), (1, 2), (8, 2), (40, 10), (128, 16)):
            with patch.dict(os.environ, {}, clear=True), patch.object(code.os, 'cpu_count', return_value=cpus):
                self.assertEqual(code._slot_count(), expected)
        for value in ('1', '20'):
            with patch.dict(os.environ, {'CODE_EXEC_SLOTS': value}):
                self.assertEqual(code._slot_count(), int(value))
        for value in ('0', '-1', 'many', '1.5'):
            with patch.dict(os.environ, {'CODE_EXEC_SLOTS': value}):
                with self.assertRaises(ValueError): code._slot_count()

    def test_saturation_wait_timeout_without_launch(self):
        semaphore = Mock()
        semaphore.acquire.return_value = False
        with patch.object(code, '_CALL_SLOTS', semaphore), patch.object(code.subprocess, 'Popen') as launch:
            result = code.execute_python_code('print(1)')
        self.assertEqual(result['stderr'], 'executor busy')
        semaphore.acquire.assert_called_once_with(timeout=10)
        semaphore.release.assert_not_called()
        launch.assert_not_called()

    def test_twenty_calls_queue_and_release_host_safe(self):
        semaphore = threading.BoundedSemaphore(2)
        entered, release = threading.Event(), threading.Event()
        lock = threading.Lock()
        active = peak = calls = 0
        def hold():
            nonlocal active, peak, calls
            with lock:
                active += 1
                calls += 1
                peak = max(peak, active)
                if active == 2: entered.set()
            try:
                if not release.wait(3): raise AssertionError('test release missing')
                raise code.CodeExecutionError('mock setup: never launches code')
            finally:
                with lock: active -= 1
        with patch.object(code, '_CALL_SLOTS', semaphore), patch.object(code, '_identity', side_effect=hold), patch.object(code.subprocess, 'Popen') as launch:
            with ThreadPoolExecutor(max_workers=20) as pool:
                first = [pool.submit(code.execute_python_code, 'print(1)') for _ in range(2)]
                try:
                    self.assertTrue(entered.wait(2))
                    rest = [pool.submit(code.execute_python_code, 'print(1)') for _ in range(18)]
                    self.assertFalse(any(f.done() for f in rest))
                finally:
                    release.set()
                results = [f.result(timeout=3) for f in first + rest]
        self.assertEqual(peak, 2)
        self.assertEqual(calls, 20)
        self.assertTrue(all('mock setup' in r['stderr'] for r in results))
        launch.assert_not_called()
        self.assertTrue(semaphore.acquire(blocking=False))
        self.assertTrue(semaphore.acquire(blocking=False))
        semaphore.release(); semaphore.release()

    def test_root_requires_separate_identity(self):
        with patch.object(code.sys,'platform','linux'), patch.object(code.os,'geteuid',return_value=0):
            with patch.object(code.pwd,'getpwnam',side_effect=KeyError):
                with self.assertRaisesRegex(code.CodeExecutionError,'Missing dedicated'): code._identity()
            with patch.object(code.pwd,'getpwnam',return_value=Mock(pw_uid=0,pw_gid=0)):
                with self.assertRaisesRegex(code.CodeExecutionError,'non-root'): code._identity()
            with patch.object(code.pwd,'getpwnam',return_value=Mock(pw_uid=20001,pw_gid=20001)):
                self.assertEqual(code._identity(),(20001,20001))

    def test_non_linux_fails_closed(self):
        with patch.object(code.sys,'platform','darwin'), patch.object(code.subprocess,'Popen') as launch:
            result=code.execute_python_code('print(1)')
            self.assertEqual(result['status'],'error')
            self.assertIn('requires the Linux kernel sandbox',result['stderr'])
            launch.assert_not_called()

    def test_rootless_opt_in(self):
        with patch.object(code.sys,'platform','linux'), patch.object(code.os,'geteuid',return_value=1000), patch.object(code.os,'getegid',return_value=1000), patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(code.CodeExecutionError,'explicit'): code._identity()
            with patch.dict(os.environ,{'CODE_EXEC_ALLOW_SAME_UID':'1'}): self.assertEqual(code._identity(),(1000,1000))

    def test_setup_failure_releases_slot(self):
        semaphore=code.threading.BoundedSemaphore(1)
        with patch.object(code,'_CALL_SLOTS',semaphore), patch.object(code,'_identity',side_effect=code.CodeExecutionError('test-only')):
            self.assertEqual(code.execute_python_code('print(1)')['status'],'error')
            self.assertTrue(semaphore.acquire(blocking=False)); semaphore.release()

    def test_parent_reports_trusted_metadata_and_closes_descriptors(self):
        semaphore = threading.BoundedSemaphore(1)
        directory = Mock()
        directory.__enter__ = Mock(return_value='/mock/work')
        directory.__exit__ = Mock(return_value=False)
        process = Mock()
        protections = {'landlock_abi': 2, 'landlock_policy_abi': 2, 'seccomp': True}
        opener = mock_open()
        with patch.object(code, '_CALL_SLOTS', semaphore), patch.object(code, '_identity', return_value=(1000, 1000)), patch.object(code.os, 'geteuid', return_value=1000), patch.object(code.tempfile, 'TemporaryDirectory', return_value=directory), patch('builtins.open', opener), patch.object(code.os, 'chmod'), patch.object(code.os, 'pipe', return_value=(8, 9)), patch.object(code.os, 'close') as close, patch.object(code.os, 'read', return_value=json.dumps(protections).encode()), patch.object(code.subprocess, 'Popen', return_value=process) as launch, patch.object(code, '_capture', return_value={'stdout':'5\n', 'stderr':'', 'status':'success'}), patch.object(code, '_kill_group'):
            result = code.execute_python_code('    print(5)')
        self.assertEqual(result['metadata']['protections'], protections)
        self.assertGreaterEqual(result['metadata']['queue_wait_ms'], 0)
        self.assertEqual(result['stdout'], '5\n')
        self.assertEqual(launch.call_args.args[0][:3], [sys.executable, '-I', code._RUNNER])
        self.assertEqual(launch.call_args.args[0][-1], '9')
        options = launch.call_args.kwargs
        self.assertEqual(options['pass_fds'], (9,))
        self.assertTrue(options['close_fds']); self.assertTrue(options['start_new_session'])
        self.assertEqual(options['env'], code._environment('/mock/work'))
        self.assertEqual([call.args[0] for call in close.call_args_list], [9, 8])
        opener().write.assert_called_once_with('print(5)')
        process.stdout.close.assert_called_once(); process.stderr.close.assert_called_once()
        self.assertTrue(semaphore.acquire(blocking=False)); semaphore.release()

    def test_metadata_pipe_is_closed_when_launch_fails(self):
        directory = Mock()
        directory.__enter__ = Mock(return_value='/mock/work')
        directory.__exit__ = Mock(return_value=False)
        with patch.object(code, '_identity', return_value=(1000, 1000)), patch.object(code.os, 'geteuid', return_value=1000), patch.object(code.tempfile, 'TemporaryDirectory', return_value=directory), patch('builtins.open', mock_open()), patch.object(code.os, 'chmod'), patch.object(code.os, 'pipe', return_value=(8, 9)), patch.object(code.os, 'close') as close, patch.object(code.subprocess, 'Popen', side_effect=OSError('mock launch failure')):
            result = code.execute_python_code('print(5)')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['metadata']['protections'], {'landlock_abi': 0, 'seccomp': False})
        self.assertEqual([call.args[0] for call in close.call_args_list], [9, 8])

    def test_dispatch_propagates_protections_for_success_and_failure(self):
        # Load just the dispatcher with dependency stubs, avoiding server imports
        # and any credential/network initialization on the host-safe interpreter.
        import types
        registry = types.ModuleType('app.registry')
        schemas = types.ModuleType('app.schemas')
        schemas.ToolResponse = lambda **kwargs: types.SimpleNamespace(**kwargs)
        dispatch_spec = importlib.util.spec_from_file_location('dispatch_unit', Path(__file__).parent / 'app/dispatcher.py')
        dispatch = importlib.util.module_from_spec(dispatch_spec)
        with patch.dict(sys.modules, {'app.registry': registry, 'app.schemas': schemas}):
            registry.TOOL_REGISTRY = {}
            dispatch_spec.loader.exec_module(dispatch)
        for status, outer_status in (('success', 'ok'), ('error', 'error'), ('timeout', 'error')):
            metadata = {'protections': {'landlock_abi': 2, 'seccomp': True}, 'queue_wait_ms': 120}
            result = {'stdout': 'partial', 'stderr': '', 'status': status, 'metadata': metadata}
            registry.TOOL_REGISTRY['code_executor'] = Mock(return_value=result)
            response = dispatch.dispatch_tool('code_executor', {'code': 'mock only'})
            self.assertEqual(response.status, outer_status)
            self.assertEqual(response.result_text, str(result))
            self.assertEqual(response.metadata['protections'], metadata['protections'])
            self.assertEqual(response.metadata['queue_wait_ms'], 120)
            self.assertIn('latency_ms', response.metadata)

    def test_limit_respects_hard_cap(self):
        with patch.object(runner.resource,'getrlimit',return_value=(100,100)), patch.object(runner.resource,'setrlimit') as setter:
            runner._limit(runner.resource.RLIMIT_NOFILE,200)
            setter.assert_called_once_with(runner.resource.RLIMIT_NOFILE,(100,100))

    def test_launcher_order(self):
        events = []
        protections = {'landlock_abi': 2, 'seccomp': True}
        args = ['runner', '/tmp/test/script.py', '20001', '20001',
                json.dumps({'cpu':5,'memory':1024,'file':8,'processes':32,'open_files':64}), '9']
        with patch.object(runner.sys, 'argv', args), patch.object(runner.sys, 'platform', 'linux'), patch.object(runner.os, 'umask'), patch.object(runner.os, 'geteuid', side_effect=[0, 20001]), patch.object(runner.os, 'setgroups', side_effect=lambda x: events.append(('groups', x))), patch.object(runner.os, 'setgid', side_effect=lambda x: events.append(('gid', x))), patch.object(runner.os, 'setuid', side_effect=lambda x: events.append(('uid', x))), patch.object(runner, '_limit', side_effect=lambda k,v: events.append(('limit', k, v))), patch.object(runner.os, 'getcwd', return_value='/tmp/test'), patch.object(runner, '_linux_sandbox', side_effect=lambda x: events.append(('policy', x)) or protections), patch.object(runner, '_write_metadata', side_effect=lambda fd,p: events.append(('metadata', fd, p))), patch.object(runner, '_execute_script', side_effect=lambda x: events.append(('execute', x))):
            runner.main()
            self.assertEqual(runner.sys.argv, ['/tmp/test/script.py'])
        self.assertEqual(events[:3], [('groups', []), ('gid', 20001), ('uid', 20001)])
        self.assertEqual(sum(e[0] == 'limit' for e in events), 6)
        self.assertEqual(events[-3:], [('policy', '/tmp/test'), ('metadata', 9, protections), ('execute', '/tmp/test/script.py')])

    def test_policy_failure_prevents_execution_and_reports(self):
        protections = {'landlock_abi': 0, 'seccomp': False}
        args = ['runner', '/tmp/test/script.py', '1000', '1000',
                json.dumps({'cpu':5,'memory':1024,'file':8,'processes':32,'open_files':64}), '9']
        with patch.object(runner.sys, 'argv', args), patch.object(runner.sys, 'platform', 'linux'), patch.object(runner.os, 'umask'), patch.object(runner.os, 'geteuid', return_value=1000), patch.object(runner, '_limit'), patch.object(runner, '_linux_sandbox', side_effect=runner.SandboxUnavailable(protections)), patch.object(runner, '_write_metadata') as metadata, patch.object(runner, '_execute_script') as execute:
            with self.assertRaisesRegex(RuntimeError, 'No kernel protections'): runner.main()
            execute.assert_not_called()
            metadata.assert_called_once_with(9, protections)

    def test_landlock_abi_masks(self):
        for abi in (1, 2, 3, 6):
            rules, masks = [], []
            libc = Mock()
            def syscall(number, *args):
                if number == 444 and args[-1] == 1: return abi
                if number == 444:
                    masks.append(args[0]._obj.handled_access_fs)
                    return 10
                if number == 445: rules.append(args[2]._obj.allowed_access)
                return 0
            libc.syscall.side_effect = syscall
            with patch.object(runner.os, 'O_PATH', 0x200000, create=True), patch.object(runner.os.path, 'exists', return_value=True), patch.object(runner.os, 'open', return_value=11), patch.object(runner.os, 'close'):
                self.assertEqual(runner._landlock(libc, '/tmp/test'), abi)
            expected = sum(1 << b for b in range(1, 13))
            if abi >= 2: expected |= 1 << 13
            if abi >= 3: expected |= 1 << 14
            self.assertEqual(masks, [expected])
            self.assertEqual(rules[0], expected)
            self.assertTrue(all(x in (1 << 2, (1 << 2) | (1 << 3)) for x in rules[1:]))

    def test_policy_fallbacks_and_fail_closed(self):
        for abi, seccomp_ok in ((1, True), (2, True), (6, True), (0, True), (2, False), (0, False)):
            libc = Mock()
            libc.prctl.return_value = 0
            landlock = {'return_value': abi} if abi else {'side_effect': OSError(errno.ENOSYS, 'unavailable')}
            seccomp = {} if seccomp_ok else {'side_effect': OSError(errno.EPERM, 'unavailable')}
            with patch.object(runner.ctypes, 'CDLL', return_value=libc), patch.object(runner, '_landlock', **landlock), patch.object(runner, '_seccomp', **seccomp):
                if not abi and not seccomp_ok:
                    with self.assertRaises(runner.SandboxUnavailable) as caught:
                        runner._linux_sandbox('/tmp/test')
                    result = caught.exception.protections
                else:
                    result = runner._linux_sandbox('/tmp/test')
            self.assertEqual(result['landlock_abi'], abi)
            self.assertEqual(result['seccomp'], seccomp_ok)
            if abi: self.assertEqual(result['landlock_policy_abi'], min(3, abi))
            if not abi: self.assertIn('landlock_error', result)
            if not seccomp_ok: self.assertIn('seccomp_error', result)

    def test_no_new_privs_failure_prevents_policies(self):
        libc = Mock(); libc.prctl.return_value = -1
        with patch.object(runner.ctypes, 'CDLL', return_value=libc), patch.object(runner, '_landlock') as landlock, patch.object(runner, '_seccomp') as seccomp:
            with self.assertRaises(OSError): runner._linux_sandbox('/tmp/test')
            landlock.assert_not_called(); seccomp.assert_not_called()

    def test_seccomp_decisions_for_both_architectures(self):
        # Evaluate classic BPF over synthetic seccomp_data; no kernel changes.
        def evaluate(program, arch, number, arg0=0, arg1=0, arg2=0):
            data = struct.pack('<IIQ6Q', number, arch, 0, arg0, arg1, arg2, 0, 0, 0)
            pc = accumulator = 0
            for _ in range(len(program) + 1):
                op, jt, jf, k = program[pc]
                if op == 0x20: accumulator = struct.unpack_from('<I', data, k)[0]
                elif op == 0x15: pc += jt if accumulator == k else jf
                elif op == 0x45: pc += jt if accumulator & k else jf
                elif op == 0x06: return k
                else: self.fail(f'unknown BPF instruction {op}')
                pc += 1
            self.fail('BPF program did not terminate')
        deny, allow = 0x00050000 | errno.EPERM, 0x7FFF0000
        cases = [('x86_64', 0xC000003E, 56, [41,42,43,49,50,53,57,58,59,62,76,101,109,112,129,200,234,288,297,310,311,322,424,425,426,427,438]),
                 ('aarch64', 0xC00000B7, 220, [45,117,129,130,131,138,154,157,198,199,200,201,202,203,221,240,242,270,271,281,424,425,426,427,438])]
        for machine, arch, clone, denied in cases:
            program = runner._seccomp_instructions(machine)
            for number in denied: self.assertEqual(evaluate(program, arch, number), deny, (machine, number))
            self.assertEqual(evaluate(program, arch, clone), deny)
            self.assertEqual(evaluate(program, arch, clone, 0x10000 | 0x800 | 0x100), allow)
            self.assertEqual(evaluate(program, arch, 435), 0x00050000 | errno.ENOSYS)
            self.assertEqual(evaluate(program, arch, 437), 0x00050000 | errno.ENOSYS)
            for number in (0, 1, 9, 12, 202 if machine == 'x86_64' else 98):
                self.assertEqual(evaluate(program, arch, number), allow, (machine, number))
            # openat arg2 flags: prevent O_RDONLY|O_TRUNC bypass on ABI 1/2.
            openat = 257 if machine == 'x86_64' else 56
            self.assertEqual(evaluate(program, arch, openat, arg2=os.O_TRUNC), deny)
            self.assertEqual(evaluate(program, arch, openat, arg2=os.O_TRUNC | os.O_WRONLY), allow)
            self.assertEqual(evaluate(program, arch, openat, arg2=os.O_RDONLY), allow)
            if machine == 'x86_64':
                self.assertEqual(evaluate(program, arch, 2, arg1=os.O_TRUNC), deny)
                self.assertEqual(evaluate(program, arch, 2, arg1=os.O_TRUNC | os.O_RDWR), allow)
                self.assertEqual(evaluate(program, arch, 0x40000000), 0x80000000)
            self.assertEqual(evaluate(program, 0, 1), 0x80000000)
        with self.assertRaisesRegex(RuntimeError, 'Unsupported'): runner._seccomp_instructions('unknown')


class CaptureTests(unittest.TestCase):
    def capture(self,chunks,returncode=0,wait_timeout=False):
        process=Mock(pid=123,returncode=returncode)
        selector=Mock(); context=Mock()
        context.__enter__=Mock(return_value=selector); context.__exit__=Mock(return_value=False)
        selector.get_map.side_effect=[True]*len(chunks)+[False]
        keys=[Mock(fd=i,data=name) for i,(name,_) in enumerate(chunks)]
        selector.select.side_effect=[[(key,1)] for key in keys]
        if wait_timeout: process.wait.side_effect=[code.subprocess.TimeoutExpired('fake',.1),0]
        with patch.object(code.selectors,'DefaultSelector',return_value=context), patch.object(code.os,'set_blocking'), patch.object(code.os,'read',side_effect=[v for _,v in chunks]), patch.object(code,'_kill_group') as kill:
            result=code._capture(process,code.time.monotonic()+1)
            kill.assert_called_once_with(process)
        return result

    def test_success_exception(self):
        self.assertEqual(self.capture([('stdout',b'5\n')]),{'stdout':'5\n','stderr':'','status':'success'})
        result=self.capture([('stderr',b'ValueError\n')],1)
        self.assertEqual(result['status'],'error'); self.assertEqual(result['stderr'],'ValueError\n')

    def test_output_utf8_caps(self):
        for name,byte in [('stdout',b'x'),('stderr',b'x'),('stdout',b'\xff')]:
            result=self.capture([(name,byte*(code.MAX_OUTPUT_BYTES+1))])
            self.assertEqual(result['status'],'error'); self.assertIn('output limit exceeded',result['stderr'])
            self.assertLessEqual(len(result['stdout'].encode()),code.MAX_OUTPUT_BYTES)
            self.assertLessEqual(len(result['stderr'].encode()),code.MAX_OUTPUT_BYTES)

    def test_closed_pipes_timeout(self):
        result=self.capture([],wait_timeout=True)
        self.assertEqual(result['status'],'timeout'); self.assertEqual(result['stderr'],'Execution timed out')

    def test_signal_failure(self):
        result=self.capture([],returncode=-9)
        self.assertEqual(result['status'],'error'); self.assertIn('signal 9',result['stderr'])

if __name__=='__main__': unittest.main()
