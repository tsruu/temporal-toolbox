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


def translate(text: str, target_language: str) -> str:
    """
    Translate text to the target language.
    target_language can be full name ('English') or ISO code ('en').
    """
    if not text or not text.strip():
        return text

    try:
        # Normalize target language
        if len(target_language) > 2:
            lang = pycountry.languages.get(name=target_language)
            if lang and hasattr(lang, "alpha_2"):
                target_language = lang.alpha_2

        return GoogleTranslator(
            source="auto",
            target=target_language
        ).translate(text)

    except Exception:
        return text