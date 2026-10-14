"""Reproducible chronological profiling on examples and 200 distinct pairs."""

import argparse
import cProfile
import json
import math
from pathlib import Path
import pstats
import time

from app.tools import temporal
from tests_async_equivalence import baseline_module
from tests_async_support import EXAMPLES, ROOT, outcome, sampled_pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--examples-only", action="store_true")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/async_verification/current")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    directory, baseline = baseline_module()
    module = baseline if args.baseline else temporal
    label = "baseline" if args.baseline else "new"
    pairs = EXAMPLES + ([] if args.examples_only else sampled_pairs())
    profiler = cProfile.Profile()
    timings = {}
    try:
        if args.profile:
            profiler.enable()
        for name in ("before_chronological_reference", "after_chronological_reference"):
            values = []
            for index, pair in enumerate(pairs):
                start = time.perf_counter()
                outcome(getattr(module, name), pair)
                values.append((time.perf_counter() - start) * 1000)
                if index % 50 == 0:
                    print(name, index, round(values[-1], 3), "ms", flush=True)
            ordered = sorted(values)
            timings[name] = {"count": len(values), "p50_ms": ordered[len(values)//2],
                             "p95_ms": ordered[math.ceil(.95 * len(values))-1],
                             "max_ms": ordered[-1], "examples_ms": values[:3]}
        if args.profile:
            profiler.disable()
            profiler.dump_stats(str(args.output / (label + ".prof")))
            with (args.output / (label + "_profile.txt")).open("w") as stream:
                pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumtime").print_stats(30)
    finally:
        directory.cleanup()
    result = {"profiled": args.profile, "examples_only": args.examples_only, "tools": timings}
    (args.output / (label + "_timings.json")).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
