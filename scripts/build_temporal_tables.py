#!/usr/bin/env python3
"""Rebuild reviewed temporal tables from toolbox/data/temporal.

Apply-X owns these package-local sources. Dataset builders and their mirrors
are separate inputs and are deliberately outside this rebuild's write scope.
"""
from pathlib import Path
import csv
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/temporal'
TARGET = ROOT / 'app/tools'


def build():
    for source in sorted(SOURCE.glob('*.csv')):
        with source.open(newline='', encoding='utf-8') as stream:
            reader = csv.DictReader(stream)
            required = {'question', 'entity', 'answer',
                        'event' if 'chronological' in source.name else 'time'}
            if set(reader.fieldnames or ()) != required:
                raise ValueError(f'Unexpected columns: {source.name}')
            rows = list(reader)
            if not rows or any(None in row or any(value is None for value in row.values()) for row in rows):
                raise ValueError(f'Invalid rows: {source.name}')
        shutil.copyfile(source, TARGET / source.name)
        print(f'{source.name}: {len(rows)} rows')


if __name__ == '__main__': build()
