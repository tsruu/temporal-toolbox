# app/tools/language.py

from langdetect import detect, DetectorFactory
from deep_translator import GoogleTranslator
import pycountry

DetectorFactory.seed = 0


def _iso_to_language_name(iso_code: str) -> str:
    """
    Convert ISO 639-1 code to full language name.
    Falls back to 'Unknown' if not found.
    """
    try:
        language = pycountry.languages.get(alpha_2=iso_code)
        if language and hasattr(language, "name"):
            return language.name
    except Exception:
        pass
    return "Unknown"


def _normalize_language(lang: str) -> str:
    """
    Normalize language input to ISO 639-1 code.
    Accepts full language names ('English') or ISO codes ('en').
    """
    if not lang:
        return lang

    lang = lang.strip()

    # Already ISO 639-1
    if len(lang) == 2:
        return lang.lower()

    try:
        language = pycountry.languages.get(name=lang)
        if language and hasattr(language, "alpha_2"):
            return language.alpha_2
    except Exception:
        pass

    return lang


def detect_language(text: str) -> str:
    """
    Detect the language of the input text.
    Returns full language name (e.g., 'English', 'French').
    """
    if not text or not text.strip():
        return "Unknown"

    try:
        iso_code = detect(text)
        return _iso_to_language_name(iso_code)
    except Exception:
        return "Unknown"


def translate(text: str, source_language: str, target_language: str) -> str:
    """
    Translate text from source_language to target_language.
    Languages may be full names ('English') or ISO codes ('en').
    """
    if not text or not text.strip():
        return text

    try:
        source = _normalize_language(source_language)
        target = _normalize_language(target_language)

        return GoogleTranslator(
            source=source,
            target=target
        ).translate(text)

    except Exception:
        return text