"""Apply-X: execution error contracts, Azure failures and short exact keys."""
import asyncio
import ast
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastmcp import Client
import requests

from app.dispatcher import dispatch_tool
from app.main import app, mcp
from app.tools import code, language, temporal


@unittest.skipUnless(sys.platform == 'linux', 'code_executor runs only under the Linux kernel sandbox')
class ExecutionTests(unittest.TestCase):
    def test_current_interpreter_and_success(self):
        result = code.execute_python_code('import sys; print(sys.executable)')
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['stdout'].strip(), sys.executable)
        response = dispatch_tool('code_executor', {'code': 'print(2 + 3)'})
        self.assertEqual(response.status, 'ok')
        self.assertEqual(ast.literal_eval(response.result_text)['stdout'], '5\n')

    def test_real_failure_empty_and_timeout_surface_as_errors(self):
        for args, expected in [({'code': 'raise ValueError("failure")'}, 'error'),
                               ({'code': ''}, 'error'),
                               ({'code': 'import time; print("partial", flush=True); time.sleep(5)',
                                 'timeout_seconds': .1}, 'timeout')]:
            with self.subTest(expected=expected, args=args):
                result = dispatch_tool('code_executor', args)
                self.assertEqual(result.status, 'error')
                payload = ast.literal_eval(result.result_text)
                self.assertEqual(payload['status'], expected)
                self.assertIsInstance(payload['stdout'], str)
                if expected == 'timeout': self.assertEqual(payload['stdout'], 'partial\n')

    def test_rest_and_mcp_failure_contract(self):
        with TestClient(app) as client:
            result = client.post('/tool', json={'tool_name': 'code_executor',
                'arguments': {'code': '1 / 0'}}).json()
            self.assertEqual(result['status'], 'error')
            self.assertTrue(result['result_text'].startswith('ERROR: '))
            self.assertIn('ZeroDivisionError', result['result_text'])
        async def run():
            async with Client(mcp) as client:
                result = await client.call_tool('code_executor', {'code': '1 / 0'})
                self.assertTrue(result.content[0].text.startswith('ERROR: '))
                self.assertIn('ZeroDivisionError', result.content[0].text)
        asyncio.run(run())


class AzureExceptionTests(unittest.TestCase):
    def test_request_exception_stops_without_secondary_exception(self):
        translator = language._FrozenMicrosoftTranslator(api_key='test-only', region='test-only',
                                                         source='fr', target='en')
        for error in (requests.ConnectionError('test-only'), requests.Timeout('test-only')):
            with patch.object(language.requests, 'post', side_effect=error) as post:
                with self.assertRaisesRegex(language.TranslationError, '^Azure API request failed$'):
                    translator.translate('Bonjour')
                post.assert_called_once()
        with patch.dict('os.environ', {'AZURE_TRANSLATOR_KEY': 'test-only',
                                      'AZURE_TRANSLATOR_REGION': 'test-only'}), \
             patch.object(language.requests, 'post', side_effect=requests.ConnectionError('test-only')):
            result = dispatch_tool('translation', {'text': 'apply X uncached test',
                'source_language': 'fr', 'target_language': 'en'})
            self.assertEqual(result.status, 'error')
            self.assertEqual(result.result_text, 'translation failed: Azure API request failed')


class ShortEntityTests(unittest.TestCase):
    def test_normalized_short_exact_matches_and_only_exact_scores_change(self):
        for q, k in [('I', 'i'), ('Î', 'i'), (' A! ', 'a'), ('AI', 'ai')]:
            self.assertEqual(temporal.entity_similarity(temporal.normalize_entity(q),
                                                       temporal.normalize_entity(k)), 1.0)
        for q, k in [('', ''), ('i', 'a'), ('i word', 'i'), ('words', 'word'), ('foo', 'foo')]:
            original = .7 * temporal.containment_score(q, k) + .3 * temporal.char_ngram_similarity(q, k)
            self.assertEqual(temporal.entity_similarity(q, k), original)

    def test_actual_i_rows(self):
        # val:17360_Q2, train:17359_Q2 and train:17361_Q2.
        for tool, date, answer in [
                ('after_absolute_reference', 'November 2018', 'JPIMedia'),
                ('before_absolute_reference', 'November 2018', 'Johnston Press'),
                ('before_absolute_reference', 'November 2019', 'JPIMedia')]:
            with self.subTest(tool=tool, date=date):
                self.assertEqual(getattr(temporal, tool)('i', date), answer)



if __name__ == '__main__': unittest.main()
