"""Cross-check every answer-change record and the displayed failure examples."""
import json


def validate(m, tools):
    records = json.loads((m.OUT/'real_answer_changes.json').read_text()) + json.loads((m.OUT/'surface_answer_changes.json').read_text())
    selected = {(r['tool'], tuple(r['arguments'])):r for r in records}
    classified = json.loads((m.OUT/'correct_intent_real_failures.json').read_text())
    for mode in m.MODES[1:]:
        for kind in m.details.CLASSES:
            examples = sorted([r for r in classified if r['failure_class_by_mode'].get(mode) == kind], key=lambda r:-r['count'])[:5]
            for r in examples:
                selected[(r['tool'], tuple(r['arguments']))] = r
    comparisons = 0
    for mode, t in tools.items():
        for (name, args), r in selected.items():
            try:
                answer = getattr(t.module, name)(*args)
            except (ValueError, LookupError):
                answer = None
            assert answer == r[mode].get('answer'), (mode, name, args, answer, r[mode])
            comparisons += 1
    return dict(supplemental_real_function_comparisons=comparisons,
                all_answer_changes_and_failure_examples_checked=True)
