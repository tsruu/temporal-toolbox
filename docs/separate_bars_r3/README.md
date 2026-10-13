# Separate bars round 3

Code and tests are committed on toolbox branch `separate-bars`, starting from the already committed round-2 checkpoint `105d7e7`. Default bar remains 0.75. No merge, push or deployment.

From the Temporal workspace root, reproduce the automatic measurements with:

```
.venv/bin/python -B -u analysis/separate_bars_r3/measure.py
```

Read REPORT.md for measured outcomes and limitations. The harness reuses round 2’s corpus, wrong probes, noise transforms, log parsing, hashes and parquet coverage, with stored-case plural indexing, production-order floating-point arithmetic, automatic failure classification, direct outcome verification and a practical collision filter. No live services or logged code are executed.

The compact Git snapshot in toolbox/docs/separate_bars_r3 archives this report, helpers, baseline modules, complete change/collision evidence, summary and verification logs. Larger corpus and historical result files remain in the parent analysis directory. The snapshot scripts retain original workspace-relative paths; use the analysis copy for reproduction.
