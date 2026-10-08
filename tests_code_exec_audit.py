"""Bounded audit-only probes in fresh interpreters; no kernel policies/limits.

Safe on the development host: local address lookups, loopback port 9, and
/bin/true only. Never install an irreversible audit hook in the test process.
"""
from pathlib import Path
import subprocess
import sys
import unittest

RUNNER = Path(__file__).parent / 'app/tools/_code_runner.py'


class AuditIntegrationTests(unittest.TestCase):
    def run_audited(self, source):
        bootstrap = f'''
import importlib.util
spec = importlib.util.spec_from_file_location('runner', {str(RUNNER)!r})
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner._install_audit_policy()
exec({source!r})
'''
        return subprocess.run([sys.executable, '-I', '-c', bootstrap],
                              capture_output=True, text=True, timeout=5)

    def test_network_process_and_ctypes_operations_have_clear_denials(self):
        probes = (
            ('import socket; socket.socket()', 'socket.__new__'),
            ('import socket; socket.getaddrinfo("localhost", 80)', 'socket.getaddrinfo'),
            ('import socket; socket.gethostbyname("localhost")', 'socket.gethostbyname'),
            ('import urllib.request; urllib.request.urlopen("http://127.0.0.1:9", timeout=1)', 'urllib.Request'),
            ('import http.client; http.client.HTTPConnection("127.0.0.1", 9, timeout=1).connect()', ('http.client.connect', 'socket.getaddrinfo')),
            ('import ftplib; ftplib.FTP().connect("127.0.0.1", 9, timeout=1)', 'ftplib.connect'),
            ('import smtplib; smtplib.SMTP(local_hostname="localhost", timeout=1).connect("127.0.0.1", 9)', 'smtplib.connect'),
            ('import subprocess; subprocess.run(["/bin/true"])', 'subprocess.Popen'),
            ('import os; os.system("true")', 'os.system'),
            ('import ctypes; ctypes.CDLL(None)', 'ctypes.dlopen'),
            ('import ctypes; ctypes.CDLL("nonexistent-audit-test-library")', 'ctypes.dlopen'),
        )
        for source, event in probes:
            with self.subTest(event=event, source=source):
                result = self.run_audited(source)
                self.assertNotEqual(result.returncode, 0)
                events = event if isinstance(event, tuple) else (event,)
                self.assertTrue(any(f'Code execution policy blocked: {name}' in result.stderr
                                    for name in events), result.stderr)
                self.assertEqual(result.stdout, '')

    def test_math_date_stdlib_and_threads(self):
        result = self.run_audited('''
import math, datetime, decimal, fractions, statistics, itertools, re, json
import collections, calendar, threading
assert math.sqrt(9) == 3
assert datetime.datetime.strptime('2026-10-08', '%Y-%m-%d').weekday() == 3
assert decimal.Decimal('0.1') + decimal.Decimal('0.2') == decimal.Decimal('0.3')
assert fractions.Fraction(1, 3) * 3 == 1
assert statistics.mean([1, 2, 3]) == 2
assert list(itertools.product([1], [2])) == [(1, 2)]
assert re.match('a+', 'aaa') and json.loads('[1]') == [1]
assert collections.Counter('aba')['a'] == 2 and calendar.isleap(2024)
try:
    import zoneinfo
except ImportError:
    pass
else:
    assert zoneinfo.ZoneInfo('UTC').utcoffset(None) == datetime.timedelta(0)
values = []
t = threading.Thread(target=lambda: values.append('ok'))
t.start()
t.join()
assert values == ['ok']
print('ok')
''')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'ok\n', ''))

    def test_requests_if_installed(self):
        result = self.run_audited('''
import importlib.util
if importlib.util.find_spec('requests') is None:
    print('not installed')
else:
    import requests
    requests.get('http://127.0.0.1:9', timeout=1)
''')
        if result.returncode == 0:
            self.assertEqual(result.stdout, 'not installed\n')
            self.skipTest('requests is not installed in isolated interpreter')
        self.assertIn('Code execution policy blocked: socket.', result.stderr)


if __name__ == '__main__':
    unittest.main()
