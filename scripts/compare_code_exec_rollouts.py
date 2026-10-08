#!/usr/bin/env python3
"""Replay a handful of recorded successful calls; makes no Azure/network calls."""
import argparse
import ast
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.tools.code import execute_python_code

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--rollouts', type=Path, default=Path('../rollouts/current'))
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--limit', type=int, default=8)
args = parser.parse_args()
if not 1 <= args.limit <= 12:
    parser.error('--limit must be 1..12')
pattern = re.compile(r'<tool_call>\s*(.*?)\s*</tool_call>.*?<tool_response>\s*(.*?)\s*</tool_response>', re.S)
# Replay only standard-library calculation code from real rollouts. Avoid
# arbitrary external side effects in records collected from model output.
allowed_imports = {'datetime', 'calendar', 'math', 'statistics', 'itertools',
                   'functools', 'operator', 're', 'collections', 'fractions', 'decimal'}
samples = []
seen = set()
for path in sorted(args.rollouts.rglob('*.jsonl')):
    with path.open() as stream:
        for line_number, line in enumerate(stream, 1):
            row = json.loads(line)
            for match in pattern.finditer(row.get('output', '')):
                try:
                    call = json.loads(match[1])
                    if call.get('name') != 'code_executor':
                        continue
                    source = call['arguments']['code']
                    recorded = ast.literal_eval(match[2])
                    tree = ast.parse(source)
                except (ValueError, SyntaxError, KeyError, TypeError):
                    continue
                if source in seen or not isinstance(recorded, dict) or recorded.get('status') != 'success':
                    continue
                if any(isinstance(node, ast.Import) and any(alias.name.split('.')[0] not in allowed_imports for alias in node.names)
                       or isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] not in allowed_imports
                       or isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in
                       {'open', 'exec', 'eval', '__import__', 'compile', 'input'} for node in ast.walk(tree)):
                    continue
                seen.add(source)
                actual = execute_python_code(source)
                samples.append({'file': str(path), 'line': line_number,
                                'group_id': row.get('group_id'), 'code': source,
                                'recorded': recorded, 'local': actual, 'match': all(recorded.get(k) == actual.get(k) for k in ('stdout', 'stderr', 'status'))})
                if len(samples) == args.limit:
                    break
            if len(samples) == args.limit:
                break
    if len(samples) == args.limit:
        break
report = {'comparison': 'recorded Azure code_executor results (no live Azure calls)',
          'count': len(samples), 'matches': sum(sample['match'] for sample in samples), 'samples': samples}
args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(f"Recorded comparisons: {report['matches']}/{report['count']} exact matches")
if len(samples) != args.limit or report['matches'] != report['count']:
    sys.exit(1)
