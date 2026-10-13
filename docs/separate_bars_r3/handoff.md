Round 3 is implemented and measured on `separate-bars`; the prescribed rules still permit different-answer matches, so the owner’s hard safety limit is not met.

Round 2 was already committed as `105d7e7` and the working tree was clean. Round 3 removes numeric score zeroing, keeps plural endings in normalized text, applies pairwise plural tolerance only to lowercase stored words, and prevents stacking a plural change with a spelling edit. Case-independent exact acronym/name matching, separate component bars and existing ranking/time behavior are retained.

| Bar | Correct broken live / table | Wrong probes newly blocked | Noise gold/pass | Real new errors | Main-gold real new errors | Real answers changed | Practical collision pairs |
|---|---|---|---|---|---|---|---|
| main | 0 / 0 | 0 | 94,695/121,785 (77.76%) | 0 | 0 | 0 | — |
| 0.75 | 0 / 0 | 25 | 119,853/121,785 (98.41%) | 3668 | 3306 | 0 | 971 |
| 0.70 | 0 / 0 | 23 | 120,298/121,785 (98.78%) | 3023 | 2733 | 0 | 1164 |

Counts compare with live-main code, replayed locally against unchanged CSVs. “Correct broken” means main reached the corpus English gold and the branch no longer does. Historical totals retain occurrence weights. “Main-gold real new errors” is the automatic proxy requested for correct intent; matching historical gold does not prove that submitted arguments have the correct meaning. Wrong-probe blocking measures rejection, not semantic correctness.

Full results, five examples per automatic failure class, every answer change and all plausible different-answer collision pairs: [analysis/separate_bars_r3/REPORT.md](../../analysis/separate_bars_r3/REPORT.md). Reproduce with `.venv/bin/python -B -u analysis/separate_bars_r3/measure.py`.

No merge to main, push or deployment. Default component bar remains 0.75. Lowering it to 0.70 improves acceptance but does not establish the hard safety limit. Verification logs and input hashes are retained with the report.
