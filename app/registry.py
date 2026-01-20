# app/registry.py
from app.tools import temporal, language, code

TOOL_REGISTRY = {
    "before_absolute_reference": temporal.before_absolute_reference,
    "before_chronological_reference": temporal.before_chronological_reference,
    "after_absolute_reference": temporal.after_absolute_reference,
    "after_chronological_reference": temporal.after_chronological_reference,
    "event_time": temporal.event_time,
    "entity_time_event": temporal.entity_time_event,
    "language_detection": language.detect_language,
    "translation": language.translate,
    "code_excecutor": code.execute_python_code
}