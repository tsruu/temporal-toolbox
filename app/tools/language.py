"""Azure translation with a frozen, package-local cache and bounded calls."""

import json
import logging
import os
from pathlib import Path
from queue import Empty, Queue
from threading import BoundedSemaphore, Thread
from types import MappingProxyType
import unicodedata

import requests
from deep_translator import MicrosoftTranslator
from deep_translator.exceptions import MicrosoftAPIerror
from deep_translator.validate import is_input_valid
from langdetect import detect, DetectorFactory
import pycountry

DetectorFactory.seed = 0
PACKAGE_DIR = Path(__file__).resolve().parent
TRANSLATION_TIMEOUT_SECONDS = 1.8
_CALL_SLOTS = BoundedSemaphore(16)
_LANGUAGES = json.loads((PACKAGE_DIR / "translation_languages.json").read_text(encoding="utf-8"))
_LANGUAGE_CODES = frozenset(_LANGUAGES.values())
_CODE_ALIASES = {
    "zh": "zh-hans", "zh-cn": "zh-hans", "zh-tw": "zh-hant",
    "sr": "sr-cyrl", "tl": "fil", "no": "nb", "iw": "he",
}


class TranslationError(ValueError):
    """Safe error text: never include credentials or raw HTTP exceptions."""


def _normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _normalize_language(lang: str) -> str:
    """Accept Azure-supported language names or ISO codes, case-insensitively."""
    value = lang.strip().casefold() if isinstance(lang, str) else ""
    value = _CODE_ALIASES.get(value, value)
    if value in _LANGUAGE_CODES:
        return value
    if value in _LANGUAGES:
        return _LANGUAGES[value]
    # ISO names sometimes differ from Azure's names.
    for language in pycountry.languages:
        names = (getattr(language, k, "") for k in ("name", "common_name"))
        if value and value in (name.casefold() for name in names):
            code = getattr(language, "alpha_2", "")
            code = _CODE_ALIASES.get(code, code)
            if code in _LANGUAGE_CODES:
                return code
    raise TranslationError("unsupported language")


def cache_key(text: str, source_language: str, target_language: str) -> str:
    return json.dumps([_normalize_text(text), _normalize_language(source_language),
                       _normalize_language(target_language)], ensure_ascii=False)


def _load_cache():
    data = json.loads((PACKAGE_DIR / "translation_cache.json").read_text(encoding="utf-8"))
    entries = data["entries"]
    for key, value in entries.items():
        text, source, target = json.loads(key)
        if key != cache_key(text, source, target) or not isinstance(value, str) or not value.strip():
            raise ValueError("invalid frozen translation cache")
    return MappingProxyType(entries)


_CACHE = _load_cache()


class _FrozenMicrosoftTranslator(MicrosoftTranslator):
    def _get_supported_languages(self):
        # deep-translator otherwise performs an unbounded GET on every constructor.
        return dict(_LANGUAGES)

    def translate(self, text: str, **kwargs) -> str:
        # Mirror deep-translator 1.11.4, adding a timeout to its HTTP request.
        response = None
        if is_input_valid(text):
            self._url_params["from"] = self._source
            self._url_params["to"] = self._target
            valid_microsoft_json = [{"text": text}]
            try:
                response = requests.post(
                    self._base_url,
                    params=self._url_params,
                    headers=self.headers,
                    json=valid_microsoft_json,
                    proxies=self.proxies,
                    timeout=TRANSLATION_TIMEOUT_SECONDS,
                )
            except requests.exceptions.RequestException as error:
                logging.warning("Returned error: %s", type(error).__name__)

            if type(response.json()) is dict:
                error_message = response.json()["error"]
                raise MicrosoftAPIerror(error_message)
            elif type(response.json()) is list:
                all_translations = [
                    i["text"] for i in response.json()[0]["translations"]
                ]
                return "\n".join(all_translations)


def _azure_translate(text: str, source: str, target: str) -> str:
    key = os.environ.get("AZURE_TRANSLATOR_KEY")
    region = os.environ.get("AZURE_TRANSLATOR_REGION")
    if not key or not region:
        raise TranslationError("AZURE_TRANSLATOR_KEY and AZURE_TRANSLATOR_REGION are required")
    if not _CALL_SLOTS.acquire(blocking=False):
        raise TranslationError("too many pending Azure calls")
    result = Queue(maxsize=1)

    def call():
        try:
            value = _FrozenMicrosoftTranslator(api_key=key, region=region,
                                              source=source, target=target).translate(text)
            if not isinstance(value, str) or not value.strip():
                raise TranslationError("empty Azure response")
            result.put((True, value))
        except Exception:
            # Azure/client exceptions can contain request details. Do not expose them.
            result.put((False, "Azure API request failed"))
        finally:
            _CALL_SLOTS.release()

    Thread(target=call, daemon=True, name="azure-translation").start()
    try:
        ok, value = result.get(timeout=TRANSLATION_TIMEOUT_SECONDS)
    except Empty:
        raise TranslationError(f"timeout after {TRANSLATION_TIMEOUT_SECONDS:g} seconds") from None
    if not ok:
        raise TranslationError(value)
    return value


def detect_language(text: str) -> str:
    """Detect the language, returning its full name or raising on failure."""
    try:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("empty text")
        code = _normalize_language(detect(text))
        language = pycountry.languages.get(alpha_2=code)
        if language and hasattr(language, "name"):
            return language.name
        return next(name.title() for name, value in _LANGUAGES.items() if value == code)
    except Exception:
        raise ValueError("language detection failed") from None


def translate(text: str, source_language: str, target_language: str) -> str:
    """Translate via the frozen cache first, then Azure; failures always raise."""
    try:
        if not isinstance(text, str) or not text.strip():
            raise TranslationError("text is empty")
        key = cache_key(text, source_language, target_language)
        if key in _CACHE:
            return _CACHE[key]
        normalized, source, target = json.loads(key)
        return _azure_translate(normalized, source, target)
    except TranslationError as error:
        raise TranslationError(f"translation failed: {error}") from None
