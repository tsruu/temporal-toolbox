"""Regression checks for bounded Azure HTTP requests and released worker slots."""
import socket
import statistics
import threading
import time
import unittest
from unittest.mock import Mock, patch

from deep_translator.constants import BASE_URLS
from deep_translator.exceptions import MicrosoftAPIerror
from fastapi.testclient import TestClient

from app.main import app
from app.tools import language


class BoundedAzureTests(unittest.TestCase):
    def test_request_and_response_match_library(self):
        translator = language._FrozenMicrosoftTranslator(
            api_key="test-only", region="test-only", source="fr", target="en",
            proxies={"https": "http://localhost:9999"},
        )
        response = Mock()
        response.json.return_value = [
            {"translations": [{"text": "Hello", "to": "en"}, {"text": "World", "to": "en"}]}
        ]
        with patch.object(language.requests, "post", return_value=response) as post:
            self.assertEqual(translator.translate("Bonjour"), "Hello\nWorld")
            post.assert_called_once_with(
                translator._base_url,
                params=translator._url_params,
                headers=translator.headers,
                json=[{"text": "Bonjour"}],
                proxies=translator.proxies,
                timeout=language.TRANSLATION_TIMEOUT_SECONDS,
            )
            self.assertEqual(translator._url_params["from"], "fr")
            self.assertEqual(translator._url_params["to"], "en")
            response.json.return_value = {"error": {"code": 400, "message": "test error"}}
            with self.assertRaises(MicrosoftAPIerror):
                translator.translate("Bonjour")

    def test_stalled_http_releases_all_slots_after_twenty_calls(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(32)
        listener.settimeout(.1)
        connections = []
        stop = threading.Event()

        def accept_without_responding():
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                    connections.append(connection)
                except socket.timeout:
                    continue

        server = threading.Thread(target=accept_without_responding, daemon=True)
        server.start()
        elapsed = []
        acquired = 0
        try:
            endpoint = f"http://127.0.0.1:{listener.getsockname()[1]}/translate"
            # Test credentials only; ensure environment proxies cannot bypass the local server.
            with patch.dict("os.environ", {
                "AZURE_TRANSLATOR_KEY": "test-only", "AZURE_TRANSLATOR_REGION": "test-only",
                "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1",
            }), patch.dict(BASE_URLS, {"MICROSOFT_TRANSLATE": endpoint}):
                with TestClient(app) as client:
                    for index in range(20):
                        text = f"Texte de régression absent du cache, requête {index}."
                        self.assertNotIn(language.cache_key(text, "fr", "en"), language._CACHE)
                        start = time.perf_counter()
                        response = client.post("/tool", json={
                            "tool_name": "translation",
                            "arguments": {"text": text, "source_language": "fr", "target_language": "en"},
                        }).json()
                        elapsed.append(time.perf_counter() - start)
                        self.assertEqual(response["status"], "error")
                        self.assertTrue(response["result_text"].startswith("ERROR: translation failed:"))
                        self.assertNotIn("too many pending", response["result_text"])
                        self.assertLess(elapsed[-1], language.TRANSLATION_TIMEOUT_SECONDS + .5)

                # The queue backstop can return just before the final HTTP timeout fires.
                deadline = time.perf_counter() + .5
                for _ in range(16):
                    self.assertTrue(language._CALL_SLOTS.acquire(
                        timeout=max(0, deadline - time.perf_counter())))
                    acquired += 1
                self.assertFalse(language._CALL_SLOTS.acquire(blocking=False))
                while acquired:
                    language._CALL_SLOTS.release()
                    acquired -= 1
                response = Mock()
                response.json.return_value = [{"translations": [{"text": "Twenty-first call"}]}]
                with patch.object(language.requests, "post", return_value=response):
                    self.assertEqual(language.translate("Vingt et unième requête.", "fr", "en"),
                                     "Twenty-first call")
                self.assertEqual(len(connections), 20)
                print("Stalled HTTP: 20 errors; min/median/max seconds:",
                      min(elapsed), statistics.median(elapsed), max(elapsed),
                      "; all 16 slots released; 21st call succeeded")
        finally:
            while acquired:
                language._CALL_SLOTS.release()
                acquired -= 1
            stop.set()
            server.join(timeout=1)
            listener.close()
            for connection in connections:
                connection.close()
            self.assertFalse(server.is_alive(), "local fake server did not stop")


if __name__ == "__main__":
    unittest.main()
