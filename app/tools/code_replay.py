"""Extract recorded code calls or replay their stdout/stderr/status in Linux."""
import argparse
import ast
import json
from pathlib import Path
import re
import sys

from app.tools.code import execute_python_code


RESULT_FIELDS = ('stdout', 'stderr', 'status')
EVENT = re.compile(r'<(tool_call|tool_response)>\s*(.*?)\s*</\1>', re.S)


def recorded_result(text):
    text = text.strip()
    if text.startswith('ERROR: '):
        text = text[len('ERROR: '):]
    try:
        value = json.loads(text)
    except ValueError:
        value = ast.literal_eval(text)
    if not isinstance(value, dict) or not all(isinstance(value.get(k), str) for k in RESULT_FIELDS):
        raise ValueError('recorded result needs string stdout/stderr/status')
    return {k: value[k] for k in RESULT_FIELDS}


def extract_cases(root, limit=200):
    """Keep distinct code, all statuses and provenance, without executing it."""
    seen = set()
    paths = sorted(root.rglob('*.jsonl'))
    # Tool-bearing output files first; deterministic order within each group.
    paths.sort(key=lambda p: ('tools_outputs' not in p.name, str(p)))
    for path in paths:
        with path.open(encoding='utf-8') as stream:
            for line_number, line in enumerate(stream, 1):
                row = json.loads(line)
                pending = None
                for match in EVENT.finditer(row.get('output', '')):
                    if match[1] == 'tool_call':
                        pending = None
                        try:
                            call = json.loads(match[2])
                            arguments = call.get('arguments', {})
                            if isinstance(arguments, str):
                                arguments = json.loads(arguments)
                            source = arguments.get('code')
                            if call.get('name') == 'code_executor' and isinstance(source, str):
                                pending = source
                        except (ValueError, AttributeError, TypeError):
                            continue
                    elif pending is not None:
                        source, pending = pending, None
                        if source in seen:
                            continue
                        try:
                            recorded = recorded_result(match[2])
                        except (ValueError, SyntaxError, TypeError):
                            continue
                        seen.add(source)
                        yield {'code': source, 'recorded': recorded,
                               'source_file': path.relative_to(root).as_posix(),
                               'source_line': line_number, 'group_id': row.get('group_id')}
                        if len(seen) >= limit:
                            return


def replay_cases(cases, execute=None):
    execute = execute or execute_python_code
    for index, case in enumerate(cases, 1):
        if not isinstance(case.get('code'), str):
            raise ValueError(f'case {index} needs a code string')
        recorded = case['recorded']
        if not all(isinstance(recorded.get(k), str) for k in RESULT_FIELDS):
            raise ValueError(f'case {index} needs recorded stdout/stderr/status strings')
        actual = execute(case['code'])
        differing = [k for k in RESULT_FIELDS if actual.get(k) != recorded[k]]
        yield {**case, 'case': index, 'actual': actual,
               'match': not differing, 'differing_fields': differing}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path, help='JSONL replay cases (or extraction destination)')
    parser.add_argument('--extract', type=Path, metavar='ROLLOUTS', help='extract only; runs no code')
    parser.add_argument('--limit', type=int, default=200, help='maximum distinct extraction cases (1..200)')
    parser.add_argument('--report', type=Path, help='write full actual/recorded JSON report')
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 200:
        parser.error('--limit must be 1..200')
    if args.extract:
        cases = list(extract_cases(args.extract, args.limit))
        args.file.write_text(''.join(json.dumps(case, ensure_ascii=False) + '\n' for case in cases), encoding='utf-8')
        print(f'Extracted {len(cases)} distinct real calls to {args.file}; no code executed.')
        return 0 if cases else 1
    if sys.platform != 'linux':
        print('FAIL: replay requires a Linux container; no submitted code was run.', file=sys.stderr)
        return 2
    with args.file.open(encoding='utf-8') as stream:
        cases = [json.loads(line) for line in stream if line.strip()]
    samples = list(replay_cases(cases))
    print(f"{'CASE':>4}  {'PARITY':8}  DIFFERING FIELDS / PROTECTIONS")
    for sample in samples:
        protections = sample['actual'].get('metadata', {}).get('protections', {})
        print(f"{sample['case']:4}  {'PASS' if sample['match'] else 'FAIL':8}  "
              f"{','.join(sample['differing_fields']) or '-'} / {json.dumps(protections, sort_keys=True)}")
    matches = sum(sample['match'] for sample in samples)
    report = {'count': len(samples), 'matches': matches, 'samples': samples}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Output parity: {matches}/{len(samples)} (stdout, stderr, status; metadata excluded)')
    return 0 if samples and matches == len(samples) else 1


if __name__ == '__main__':
    sys.exit(main())
