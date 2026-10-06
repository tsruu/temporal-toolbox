"""Regression checks for frozen Azure translation and MCP/REST contracts."""
import asyncio
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastmcp import Client
import requests

from app.main import app, mcp
from app.tools import language
from app.dispatcher import dispatch_tool


class TranslationTests(unittest.TestCase):
    text = 'uncached test string -- batch 1'
    args = {'text':text, 'source_language':'French', 'target_language':'English'}

    def test_cache_normalization_and_frozen(self):
        with patch.object(language, '_CACHE', {language.cache_key('école française','fr','en'):'French school'}):
            with patch.object(language,'_azure_translate',side_effect=AssertionError('network used')):
                self.assertEqual(language.translate(' e\u0301cole  française ','FRENCH','EN'),'French school')
        with self.assertRaises(TypeError): language._CACHE['new']='value'
        key, value = next(iter(language._CACHE.items()))
        text, source, target = json.loads(key)
        with patch.dict('os.environ', {}, clear=True):
            with patch.object(language, '_azure_translate', side_effect=AssertionError('network used')):
                self.assertEqual(language.translate(text, source, target), value)

    def test_same_language_shortcut_skips_cache_and_network(self):
        class CacheLookupForbidden:
            def __contains__(self, key):
                raise AssertionError('cache lookup used')

        with patch.object(language, '_CACHE', CacheLookupForbidden()), \
             patch.dict('os.environ', {
                 'AZURE_TRANSLATOR_KEY': 'test-only',
                 'AZURE_TRANSLATOR_REGION': 'test-only',
             }), \
             patch.object(language.requests, 'post', side_effect=requests.ConnectionError('offline')) as post:
            for source, target in [('English', 'English'), ('en', 'English')]:
                with self.subTest(source=source, target=target):
                    start = time.perf_counter()
                    result = language.translate('  keep  internal spacing  ', source, target)
                    elapsed = time.perf_counter() - start
                    self.assertEqual(result, 'keep  internal spacing')
                    self.assertLess(elapsed, .01)
            with self.assertRaisesRegex(language.TranslationError, 'unsupported language'):
                language.translate('hello', 'klingon', 'klingon')
            post.assert_not_called()

    def test_uncached_success_does_not_write_cache(self):
        before=dict(language._CACHE)
        with patch.object(language._FrozenMicrosoftTranslator,'translate',return_value='translated'):
            self.assertEqual(language.translate(**self.args),'translated')
        self.assertEqual(before,dict(language._CACHE))

    def test_missing_env_and_unsupported_language(self):
        with patch.dict('os.environ',{},clear=True):
            result=dispatch_tool('translation',self.args)
            self.assertEqual(result.status,'error')
            self.assertIn('translation failed:',result.result_text)
            self.assertNotEqual(result.result_text,self.text)
        for value in ('zz','made up language','','   '):
            with self.assertRaisesRegex(language.TranslationError,'unsupported language'):
                language.translate(self.text,value,'en')
        self.assertEqual(language._normalize_language('eNgLiSh'),'en')
        self.assertEqual(language._normalize_language('zh-Hans'),'zh-hans')
        for name, code in [('Chinese','zh-hans'),('zh-TW','zh-hant'),
                           ('Norwegian','nb'),('Serbian','sr-cyrl'),('tl','fil')]:
            self.assertEqual(language._normalize_language(name),code)

    def test_timeout_http_error_bad_key_and_empty_response(self):
        failures=[requests.Timeout(),requests.HTTPError('HTTP 500'),requests.HTTPError('HTTP 401')]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch.object(language._FrozenMicrosoftTranslator,'translate',side_effect=failure):
                    result=dispatch_tool('translation',self.args)
                    self.assertEqual(result.status,'error')
                    self.assertEqual(result.result_text,'translation failed: Azure API request failed')
        with patch.object(language._FrozenMicrosoftTranslator,'translate',return_value=None):
            with self.assertRaisesRegex(language.TranslationError,'Azure API request failed'):
                language.translate(**self.args)

    def test_wall_time_bound(self):
        def stalled(_self,text): time.sleep(.25);return text
        with patch.object(language,'TRANSLATION_TIMEOUT_SECONDS',.05):
            with patch.object(language._FrozenMicrosoftTranslator,'translate',stalled):
                start=time.perf_counter()
                with self.assertRaisesRegex(language.TranslationError,'timeout after'):
                    language.translate(**self.args)
                self.assertLess(time.perf_counter()-start,.15)

    def test_detection_failure_and_empty_text(self):
        with patch.object(language,'detect',side_effect=RuntimeError('failure')):
            result=dispatch_tool('language_detection',{'text':'un texte français'})
            self.assertEqual(result.status,'error')
            self.assertEqual(result.result_text,'language detection failed')
        with self.assertRaisesRegex(ValueError,'language detection failed'):language.detect_language('')
        with self.assertRaisesRegex(language.TranslationError,'text is empty'):language.translate('','fr','en')

    def test_rest_failure_is_error_string(self):
        with TestClient(app) as client:
            with patch.object(language._FrozenMicrosoftTranslator,'translate',side_effect=requests.HTTPError()):
                response=client.post('/tool',json={'tool_name':'translation','arguments':self.args}).json()
                self.assertEqual(response['status'],'error')
                self.assertEqual(response['result_text'],'ERROR: translation failed: Azure API request failed')

    def test_mcp_failure_is_error_string(self):
        async def run():
            async with Client(mcp) as client:
                with patch.object(language._FrozenMicrosoftTranslator,'translate',side_effect=requests.HTTPError()):
                    result=await client.call_tool('translation',self.args)
                    self.assertEqual(result.content[0].text,'ERROR: translation failed: Azure API request failed')
        asyncio.run(run())

    def test_lookup_smoke(self):
        result=dispatch_tool('before_chronological_reference',{'entity':'John Grisham','event':'The Pelican Brief'})
        self.assertEqual(result.status,'ok');self.assertEqual(result.result_text,'The Firm')


if __name__=='__main__':unittest.main()
