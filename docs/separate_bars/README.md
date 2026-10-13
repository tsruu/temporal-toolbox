# Separate bars measurement snapshot

This directory commits the report, summary, input hashes, test logs and measurement-script snapshot alongside the implementation on `separate-bars`.

The complete reproducible experiment and detailed JSON evidence live in the parent Temporal workspace at `analysis/separate_bars/`; the requested handoff is `handoffs/reports/separate_bars.md`. Those directories are outside this Git repository. Run the experiment from the Temporal workspace root with `.venv/bin/python -B -u analysis/separate_bars/measure.py`. `measure_snapshot.py` archives the script used there; its relative workspace paths are intended for that original location.

The numeric mismatch requirement remains one expected-failure test because preserving the specified score formula does not enforce numeric rejection. See REPORT.md for the conflict, measured tradeoffs and test-environment limits.
