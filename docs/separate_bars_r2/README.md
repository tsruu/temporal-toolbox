# Separate bars round 2

Committed evidence snapshot for the normalization and threshold sweep on `separate-bars`, comparing main `281114b`. The default component bar remains 0.75. No merge, push or deployment.

The full reproducible measurement, detailed JSON evidence and logs live in the parent Temporal workspace at `analysis/separate_bars_r2/`; the requested handoff is `handoffs/reports/separate_bars_r2.md`. These paths are outside the toolbox Git repository. From the Temporal root run `.venv/bin/python -B -u analysis/separate_bars_r2/measure.py`. `measure_snapshot.py` archives that script and retains its original workspace-relative paths.

All 34 temporal tests pass. The full toolbox suite passes with 101 tests, 19 platform skips, using `venv/bin/python` and explicit `AZURE_TRANSLATOR_KEY=test-only AZURE_TRANSLATOR_REGION=test-only`; translation HTTP calls use mocks or the test-local server. The round-1 numeric expected failure is now an ordinary passing regression.

Read REPORT.md before promotion: all bars change historical answers; 152 new entity/event collision pairs and 23 lowercase regressions are documented. The report retains the synthetic whole-pipe table failures separately from live canonical extractions.
