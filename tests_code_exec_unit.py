"""Host-safe checks: submitted code, subprocesses and real limits never run."""
import ctypes
import errno
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
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
                                 'LANG':'C.UTF-8','LC_ALL':'C.UTF-8'})

    def test_validation_without_launch(self):
        with patch.object(code.subprocess, 'Popen', side_effect=AssertionError('launch forbidden')):
            for source in ('', ' ', None, 42, 'x'*(code.MAX_CODE_BYTES+1)):
                self.assertEqual(code.execute_python_code(source)['status'],'error')
            for timeout in (0,-1,6,float('inf'),float('nan'),'5'):
                self.assertEqual(code.execute_python_code('print(1)',timeout)['status'],'error')

    def test_saturation_without_launch(self):
        semaphore=code.threading.BoundedSemaphore(2)
        semaphore.acquire(); semaphore.acquire()
        with patch.object(code,'_CALL_SLOTS',semaphore), patch.object(code.subprocess,'Popen',side_effect=AssertionError('launch forbidden')):
            self.assertIn('Too many concurrent',code.execute_python_code('print(1)')['stderr'])
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

    def test_limit_respects_hard_cap(self):
        with patch.object(runner.resource,'getrlimit',return_value=(100,100)), patch.object(runner.resource,'setrlimit') as setter:
            runner._limit(runner.resource.RLIMIT_NOFILE,200)
            setter.assert_called_once_with(runner.resource.RLIMIT_NOFILE,(100,100))

    def test_launcher_order(self):
        events=[]
        args=['runner','/tmp/test/script.py','20001','20001',json.dumps({'cpu':5,'memory':1024,'file':8,'processes':32,'open_files':64})]
        with patch.object(runner.sys,'argv',args), patch.object(runner.sys,'platform','linux'), patch.object(runner.os,'umask'), patch.object(runner.os,'geteuid',side_effect=[0,20001]), patch.object(runner.os,'setgroups',side_effect=lambda x: events.append(('groups',x))), patch.object(runner.os,'setgid',side_effect=lambda x: events.append(('gid',x))), patch.object(runner.os,'setuid',side_effect=lambda x: events.append(('uid',x))), patch.object(runner,'_limit',side_effect=lambda k,v: events.append(('limit',k,v))), patch.object(runner.os,'getcwd',return_value='/tmp/test'), patch.object(runner,'_linux_sandbox',side_effect=lambda x: events.append(('policy',x))), patch.object(runner.os,'execv',side_effect=lambda x,y: events.append(('exec',x,y))):
            runner.main()
        self.assertEqual(events[:3],[('groups',[]),('gid',20001),('uid',20001)])
        self.assertEqual(sum(e[0]=='limit' for e in events),6)
        self.assertEqual(events[-2][0],'policy')
        self.assertEqual(events[-1][2],[sys.executable,'-I','/tmp/test/script.py'])

    def test_policy_failure_prevents_exec(self):
        args=['runner','/tmp/test/script.py','1000','1000',json.dumps({'cpu':5,'memory':1024,'file':8,'processes':32,'open_files':64})]
        with patch.object(runner.sys,'argv',args), patch.object(runner.sys,'platform','linux'), patch.object(runner.os,'umask'), patch.object(runner.os,'geteuid',return_value=1000), patch.object(runner,'_limit'), patch.object(runner,'_linux_sandbox',side_effect=OSError('denied')), patch.object(runner.os,'execv') as execute:
            with self.assertRaises(OSError): runner.main()
            execute.assert_not_called()

    def test_filter_network_forks_signals_escape(self):
        cases=[('x86_64',0xC000003E,[41,42,43,49,50,53,56,57,58,62,101,109,112,129,200,234,288,297,310,311,424,435,438]),
               ('aarch64',0xC00000B7,[117,129,130,131,138,154,157,198,199,200,201,202,203,220,240,242,270,271,424,435,438])]
        for machine,arch,deny in cases:
            captured=[]; rules=[]; libc=Mock()
            def syscall(number,*args):
                if number==444 and args[-1]==1: return 3
                if number==444: return 10
                if number==445: rules.append(args[2]._obj.allowed_access)
                return 0
            def prctl(number,*args):
                if number==22:
                    p=args[1]._obj
                    captured.extend((f.code,f.jt,f.jf,f.k) for f in p.filter[:p.len])
                return 0
            libc.syscall.side_effect=syscall; libc.prctl.side_effect=prctl
            with patch.object(runner.ctypes,'CDLL',return_value=libc), patch.object(runner.platform,'machine',return_value=machine), patch.object(runner.os,'O_PATH',0x200000,create=True), patch.object(runner.os.path,'exists',return_value=True), patch.object(runner.os,'open',return_value=11), patch.object(runner.os,'close'):
                runner._linux_sandbox('/tmp/test')
            self.assertEqual(captured[1][3],arch)
            emitted=[captured[i][3] for i in range(len(captured)-1) if captured[i][0]==0x15 and captured[i+1][3]==(0x00050000|errno.EPERM)]
            self.assertEqual(emitted,deny)
            self.assertEqual(captured[-1],(0x06,0,0,0x7FFF0000))
            self.assertEqual(rules[0],(1<<1)|(1<<2)|(1<<3)|sum(1<<b for b in range(4,15)))
            self.assertTrue(all(x in (1<<2,(1<<2)|(1<<3)) for x in rules[1:]))

    def test_old_landlock_fails_closed(self):
        libc=Mock(); libc.prctl.return_value=0; libc.syscall.return_value=2
        with patch.object(runner.ctypes,'CDLL',return_value=libc):
            with self.assertRaisesRegex(RuntimeError,'ABI >= 3'): runner._linux_sandbox('/tmp/test')

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
