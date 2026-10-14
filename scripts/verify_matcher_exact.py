"""Deterministic baseline oracle, exact comparison, and sequential timings.

Run from the repository root with python scripts/verify_matcher_exact.py MODE.
The oracle executes unmodified 4fddcdb source; only data paths are supplied by
the module's __file__. All artifacts stay under docs/async_verification.
"""
import argparse
from collections import Counter
import cProfile
import csv
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import pstats
import random
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs/async_verification"
BASELINE = "4fddcdb"
TOOLS = ("before_chronological_reference", "after_chronological_reference")
OTHER_TOOLS = ("before_absolute_reference", "after_absolute_reference",
               "entity_time_event", "event_time")
MODULE = None


def baseline_module():
    source = subprocess.check_output(
        ["git", "show", BASELINE + ":app/tools/temporal.py"], cwd=ROOT)
    module = types.ModuleType("matcher_baseline")
    module.__file__ = str(ROOT / "app/tools/temporal.py")
    exec(compile(source, "4fddcdb/app/tools/temporal.py", "exec"), module.__dict__)
    return module


def rows(name):
    with (ROOT / "app/tools" / (name + ".csv")).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def pairs():
    values = json.loads((OUT / "current/pairs.json").read_text())
    assert len(values) == 203
    return values


def edit(text):
    for index, char in enumerate(text):
        if char.isalpha():
            return text[:index] + ("x" if char.lower() != "x" else "z") + text[index + 1:]
    return text + "x"


def cases():
    tables = {name: rows(name) for name in TOOLS}
    for name, table in tables.items():
        for row in table:
            yield "first_alternative", name, (row["entity"].split("|")[0], row["event"].split("|")[0])
    for name in TOOLS:
        for pair in pairs():
            yield "203_pairs", name, tuple(pair)
    rng = random.Random(20261014)
    population = [(name, row) for name, table in tables.items() for row in table]
    for name, row in rng.sample(population, 1500):
        entity, event = row["entity"].split("|")[0], row["event"].split("|")[0]
        other = rng.choice(tables[name])
        for category, query in (
            ("uppercase", (entity.upper(), event.upper())),
            ("articles", ("the " + entity, "an " + event)),
            ("plural_suffix", (entity + "s", event + "s")),
            ("entity_edit", (edit(entity), event)),
            ("event_edit", (entity, edit(event))),
            ("swapped", (event, entity)),
            ("mismatched", (entity, other["event"].split("|")[0])),
        ):
            yield category, name, query
    # Additional coverage for all four other lookup tools whose pure helpers
    # are shared with the chronological scorer.
    for name in OTHER_TOOLS:
        for row in rows(name):
            query = ((row["event"],) if name == "event_time" else (row["entity"], row["time"]))
            yield "other_tool_rows", name, query
        for row in rows(name)[:20]:
            query = ((row["event"],) if name == "event_time" else (row["entity"], row["time"]))
            yield "other_uppercase", name, tuple(value.upper() for value in query)
            yield "other_articles", name, ("the " + query[0], *query[1:])


def outcome(module, name, query):
    try:
        return {"status": "ok", "text": getattr(module, name)(*query)}
    except LookupError as error:
        return {"status": "LookupError", "text": str(error)}


def init_worker():
    global MODULE
    MODULE = baseline_module()


def baseline_call(item):
    name, query = item
    return name, query, outcome(MODULE, name, query)


def init_new_worker():
    global MODULE
    from app.tools import temporal
    MODULE = temporal


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def oracle(workers):
    data_hashes = {}
    for path in sorted((ROOT / "app/tools").glob("*.csv")):
        committed = subprocess.check_output(["git", "show", BASELINE + ":app/tools/" + path.name], cwd=ROOT)
        assert committed == path.read_bytes(), path.name + " differs from baseline"
        data_hashes[path.name] = hashlib.sha256(committed).hexdigest()
    all_cases = list(cases())
    unique = list(dict.fromkeys((name, query) for _, name, query in all_cases))
    expected = {}
    started = time.perf_counter()
    # Incremental journal makes progress auditable while baseline calls run.
    with (OUT / "matcher_baseline_journal.jsonl").open("w", encoding="utf-8") as journal:
        with mp.Pool(workers, initializer=init_worker) as pool:
            for index, (name, query, result) in enumerate(pool.imap_unordered(baseline_call, unique, chunksize=1), 1):
                expected[name, tuple(query)] = result
                journal.write(json.dumps({"tool": name, "query": query, "expected": result}, ensure_ascii=False) + "\n")
                if index % 200 == 0 or index == len(unique):
                    journal.flush()
                    print(f"baseline {index}/{len(unique)} distinct calls; {time.perf_counter() - started:.1f}s", flush=True)
    with (OUT / "matcher_expected.jsonl").open("w", encoding="utf-8") as stream:
        for category, name, query in all_cases:
            stream.write(json.dumps({"category": category, "tool": name, "query": query,
                                     "expected": expected[name, query]}, ensure_ascii=False) + "\n")
    write_json(OUT / "matcher_oracle_summary.json", {
        "baseline": BASELINE, "workers": workers, "total": len(all_cases),
        "distinct_calls": len(unique), "categories": dict(Counter(category for category, _, _ in all_cases)),
        "data_sha256": data_hashes, "wall_seconds": time.perf_counter() - started,
    })


def compare(workers):
    memo, counts, differences = {}, Counter(), []
    with (OUT / "matcher_expected.jsonl").open(encoding="utf-8") as stream:
        items = [json.loads(line) for line in stream]
    unique = list(dict.fromkeys((item["tool"], tuple(item["query"])) for item in items))
    with mp.Pool(workers, initializer=init_new_worker) as pool:
        for index, (name, query, actual) in enumerate(pool.imap_unordered(baseline_call, unique, chunksize=1), 1):
            memo[name, tuple(query)] = actual
            if index % 1000 == 0:
                print(f"computed {index}/{len(unique)} new distinct calls", flush=True)
    for item in items:
        name, query = item["tool"], tuple(item["query"])
        actual = memo[name, query]
        counts[item["category"] + ":" + name] += 1
        # UTF-8 equality explicitly checks exact output/error bytes.
        if (actual["status"] != item["expected"]["status"] or
                actual["text"].encode("utf-8") != item["expected"]["text"].encode("utf-8")):
            differences.append({**item, "actual": actual})
    result = {"total": sum(counts.values()), "distinct_calls": len(memo),
              "counts": dict(counts), "difference_count": len(differences), "differences": differences}
    write_json(OUT / "matcher_comparison.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return bool(differences)


def timing(baseline=False, profile=False):
    if baseline:
        module = baseline_module()
    else:
        from app.tools import temporal as module
    label = "baseline" if baseline else "new"
    profiler = cProfile.Profile()
    results = {}
    for name in TOOLS:
        # Report cold initialization separately; the requested 203 calls are
        # sequential measurements after one untimed call for both modules.
        started = time.perf_counter()
        outcome(module, name, pairs()[0])
        cold_ms = (time.perf_counter() - started) * 1000
        values = []
        if profile:
            profiler.enable()
        for index, query in enumerate(pairs(), 1):
            started = time.perf_counter()
            outcome(module, name, query)
            values.append((time.perf_counter() - started) * 1000)
            if index % 50 == 0:
                print(f"{label} {name} {index}/203", flush=True)
        if profile:
            profiler.disable()
        ordered = sorted(values)
        results[name] = {"count": len(values), "cold_ms": cold_ms,
                         "p50_ms": ordered[len(values) // 2],
                         "p95_ms": ordered[math.ceil(.95 * len(values)) - 1],
                         "max_ms": ordered[-1], "values_ms": values}
    suffix = "profile" if profile else "timings"
    write_json(OUT / f"matcher_{label}_{suffix}.json", {"profiled": profile, "tools": results})
    if profile:
        profiler.dump_stats(str(OUT / f"matcher_{label}.prof"))
        with (OUT / f"matcher_{label}_profile.txt").open("w") as stream:
            pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumtime").print_stats(40)
    print(json.dumps({name: {key: value for key, value in result.items() if key != "values_ms"}
                      for name, result in results.items()}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("oracle", "compare", "timing"))
    parser.add_argument("--workers", type=int, default=os.cpu_count())
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.mode == "oracle":
        oracle(args.workers)
    elif args.mode == "compare":
        raise SystemExit(compare(args.workers))
    else:
        timing(args.baseline, args.profile)
