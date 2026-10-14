"""Compare exact lookup outcomes with the source at 4fddcdb.

The default checks every CSV row, the 200 sampled chronological pairs and
spelling/case/plural/article variants. --sample-only provides an explicitly
partial check when the plan's profiling stop condition prevents a full run.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import tempfile
import types

from app.tools import temporal
from tests_async_support import BASELINE, EXAMPLES, LOOKUPS, ROOT, outcome, rows, sampled_pairs


def baseline_module():
    source = subprocess.check_output(
        ["git", "show", BASELINE + ":app/tools/temporal.py"], cwd=ROOT, text=True)
    # Give the temporary baseline package its own byte-identical data files.
    directory = tempfile.TemporaryDirectory(prefix="toolbox-baseline-reference-")
    package = Path(directory.name) / "baseline_tools"
    package.mkdir()
    (package / "__init__.py").write_text("")
    for path in (ROOT / "app/tools").glob("*.csv"):
        (package / path.name).write_bytes(path.read_bytes())
    path = package / "temporal.py"
    path.write_text(source)
    module = types.ModuleType("baseline_tools.temporal")
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return directory, module


def variants(entity, reference):
    yield entity.upper(), reference.upper()
    yield "the " + entity, "an " + reference
    yield entity + "s", reference + "s"
    for position, text in enumerate((entity, reference)):
        for index, char in enumerate(text):
            if char.isalpha():
                changed = text[:index] + ("x" if char.lower() != "x" else "z") + text[index+1:]
                pair = [entity, reference]
                pair[position] = changed
                yield tuple(pair)
                break


def cases(sample_only=False, quick=False):
    for name in LOOKUPS:
        keys = ("event",) if name == "event_time" else (
            "entity", "event" if "chronological" in name else "time")
        table = rows(name)
        for row in (table[:10] if sample_only else table):
            yield "csv_rows", name, tuple(row[key] for key in keys)
        if "chronological" in name:
            for pair in EXAMPLES + (sampled_pairs()[:5] if quick else sampled_pairs()):
                yield "sampled_pairs", name, pair
                for variant in variants(*pair):
                    yield "variants", name, variant
        else:
            for row in table[:10]:
                args = tuple(row[key] for key in keys)
                yield "variants", name, tuple(value.upper() for value in args)
                yield "variants", name, ("the " + args[0], *args[1:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-only", action="store_true")
    parser.add_argument("--quick", action="store_true",
                        help="explicit partial check: ten rows per tool, examples, five sampled pairs and variants")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/async_verification/current_equivalence.json")
    args = parser.parse_args()
    counts, differences, memo = Counter(), [], {}
    directory, baseline = baseline_module()
    try:
        for category, name, query in cases(args.sample_only or args.quick, args.quick):
            key = name, query
            if key not in memo:
                memo[key] = (outcome(getattr(baseline, name), query),
                             outcome(getattr(temporal, name), query))
            expected, actual = memo[key]
            counts[category + ":" + name] += 1
            if expected != actual:
                differences.append({"tool": name, "query": query,
                                    "expected": expected, "actual": actual})
            if sum(counts.values()) % 100 == 0:
                print("compared", sum(counts.values()), "differences", len(differences), flush=True)
    finally:
        directory.cleanup()
    result = {"scope": "quick partial" if args.quick else "sample-only" if args.sample_only else "every row",
              "counts": dict(counts), "total": sum(counts.values()),
              "distinct_calls": len(memo), "difference_count": len(differences),
              "differences": differences}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return bool(differences)


if __name__ == "__main__":
    raise SystemExit(main())
