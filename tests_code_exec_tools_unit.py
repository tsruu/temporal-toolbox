"""Host-safe operator-tool checks. No recorded/submitted Python is executed."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from app.tools import code, code_replay, code_selftest


class ReplayTests(unittest.TestCase):
    def test_extraction_pairs_distinct_code_all_statuses_and_provenance(self):
        def call(name, arguments):
            return '<tool_call>' + json.dumps({'name': name, 'arguments': arguments}) + '</tool_call>'
        def response(result):
            return '<tool_response>' + repr(result) + '</tool_response>'
        success = {'stdout': '5\n', 'stderr': '', 'status': 'success'}
        failure = {'stdout': '', 'stderr': 'bad', 'status': 'error'}
        output = (call('code_executor', {'code': 'print(5)'}) + response(success) +
                  call('code_executor', {'code': 'print(5)'}) + response(success) +
                  call('code_executor', {'code': 'unpaired'}) +
                  call('lookup', {'code': 'not code'}) + response(success) +
                  call('code_executor', json.dumps({'code': 'bad source'})) + response(failure) +
                  call('code_executor', {'code': 'invalid result'}) + '<tool_response>None</tool_response>')
        root = Path('/mock/rollouts')
        path = root / 'tools_outputs.jsonl'
        stream = Mock()
        stream.__enter__ = Mock(return_value=iter([json.dumps({'output': output, 'group_id': 123}) + '\n']))
        stream.__exit__ = Mock(return_value=False)
        with patch.object(Path, 'rglob', return_value=[path]), patch.object(Path, 'open', return_value=stream):
            actual = list(code_replay.extract_cases(root))
            self.assertEqual([case['code'] for case in actual], ['print(5)', 'bad source'])
            self.assertEqual(actual[0]['recorded'], success)
            self.assertEqual(actual[1]['recorded'], failure)
            self.assertEqual(actual[0]['source_file'], 'tools_outputs.jsonl')
            self.assertEqual(actual[0]['source_line'], 1)
            self.assertEqual(actual[0]['group_id'], 123)
            stream.__enter__.return_value = iter([json.dumps({'output': output, 'group_id': 123}) + '\n'])
            self.assertEqual(len(list(code_replay.extract_cases(root, 1))), 1)

    def test_recorded_json_python_and_error_prefix(self):
        expected = {'stdout': '', 'stderr': 'bad', 'status': 'error'}
        for value in (json.dumps(expected), repr(expected), 'ERROR: ' + repr(expected)):
            self.assertEqual(code_replay.recorded_result(value), expected)
        for value in ('None', '[]', '{"stdout": 42}'):
            with self.assertRaises(ValueError): code_replay.recorded_result(value)

    def test_replay_parity_excludes_metadata_but_includes_stderr_and_status(self):
        expected = {'stdout': '5\n', 'stderr': '', 'status': 'success'}
        cases = [{'code': 'print(5)', 'recorded': expected}] * 3
        execute = Mock(side_effect=[{**expected, 'metadata': {'protections': {'seccomp': True}}},
                                    {**expected, 'stderr': 'different'},
                                    {**expected, 'status': 'error'}])
        results = list(code_replay.replay_cases(cases, execute))
        self.assertEqual([r['match'] for r in results], [True, False, False])
        self.assertEqual([r['differing_fields'] for r in results], [[], ['stderr'], ['status']])
        self.assertEqual(execute.call_count, 3)

    def test_non_linux_replay_and_selftest_never_run_code(self):
        with patch.object(code_replay.sys, 'platform', 'darwin'), patch.object(code_replay, 'execute_python_code') as execute, patch('builtins.print'):
            self.assertEqual(code_replay.main(['/unused/cases.jsonl']), 2)
            execute.assert_not_called()
        with patch.object(code_selftest.sys, 'platform', 'darwin'), patch.object(code_selftest, 'run_matrix') as run, patch('builtins.print'):
            self.assertEqual(code_selftest.main(), 2)
            run.assert_not_called()

    def test_committed_replay_fixture(self):
        path = Path(__file__).parent / 'docs/code_exec/replay_cases.jsonl'
        cases = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len(cases), 200)
        self.assertEqual(len({case['code'] for case in cases}), 200)
        self.assertTrue(all(set(case['recorded']) == set(code_replay.RESULT_FIELDS) for case in cases))


class SelftestTests(unittest.TestCase):
    def test_matrix_collects_failures_protections_and_restores_state(self):
        original_slots = code._CALL_SLOTS
        original_marker = os.environ.get('CODE_EXEC_SELFTEST_SECRET')
        execute = Mock(return_value={'stdout': '', 'stderr': 'mock result', 'status': 'error',
                                     'metadata': {'protections': {'landlock_abi': 2, 'seccomp': True}}})
        context = Mock()
        context.__enter__ = Mock(return_value='/mock/outside')
        context.__exit__ = Mock(return_value=False)
        with patch.object(code_selftest.tempfile, 'TemporaryDirectory', return_value=context), patch.object(Path, 'write_text'), patch.object(code_selftest.os, 'chmod'):
            rows, protections = code_selftest.run_matrix(execute)
        self.assertEqual(len(rows), 21)
        self.assertEqual(execute.call_count, 40)  # 20 probes + 20 queued calls
        self.assertEqual(rows[-1][0], '20 parallel calls queued')
        self.assertTrue(all(row[1] == 'FAIL' for row in rows))
        self.assertEqual(protections, [{'landlock_abi': 2, 'seccomp': True}])
        self.assertIs(code._CALL_SLOTS, original_slots)
        self.assertEqual(os.environ.get('CODE_EXEC_SELFTEST_SECRET'), original_marker)


if __name__ == '__main__':
    unittest.main()
