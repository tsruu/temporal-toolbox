"""Shared deterministic fixtures for staged async verification."""
import csv
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASELINE = '4fddcdb'
EXAMPLES = [
    ('Allgemeiner Deutscher Fahrrad-Club', 'Anne Modersohn'),
    ('Game Award for Best Independent Game', 'Cuphead'),
    ('Sir Horace Rumbold, 8th Baronet', 'ambassador of the United Kingdom to Switzerland'),
]
LOOKUPS = (
    'before_absolute_reference', 'after_absolute_reference',
    'before_chronological_reference', 'after_chronological_reference',
    'event_time', 'entity_time_event',
)


def rows(name):
    with (ROOT / 'app/tools' / (name + '.csv')).open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def sampled_pairs():
    pairs = sorted({(row['entity'], row['event'])
                    for name in LOOKUPS if 'chronological' in name for row in rows(name)})
    return random.Random(20261014).sample(pairs, min(200, len(pairs)))


def outcome(fn, args):
    try:
        return 'ok', fn(*args)
    except Exception as error:
        return type(error).__name__, str(error)
