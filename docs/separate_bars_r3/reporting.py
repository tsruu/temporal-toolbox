"""Render complete replay evidence and a concise owner handoff."""
import json
import re


def report(m, summary):
    def read(name):
        return json.loads((m.OUT/name).read_text())
    def table(lines, headers, rows):
        m.table(lines, headers, rows)
    modes = m.MODES
    total = sum(s['all']['calls'] for s in summary['surface'].values())
    noise = {mode:sum(s['all'][mode+'_gold'] for s in summary['surface'].values()) for mode in modes}
    wrong = {mode:sum(s['all'].get(mode+'_new_errors',0) for s in summary['wrong'].values())+summary['distinct']['all'].get(mode+'_new_errors',0) for mode in modes}
    changes = {mode:sum('answer' in r['main'] and 'answer' in r[mode] and r['main']['answer'] != r[mode]['answer'] for f in ('canonical_answer_changes.json','serving_answer_changes.json','surface_answer_changes.json') for r in read(f)) for mode in modes}
    lines = ['VERDICT: Round 3 is implemented and measured on separate-bars; the measured rules still permit different-answer matches, so the owner’s hard safety limit is not met.', '',
             f"Main reference `{summary['base_commit'][:7]}`; round-2 checkpoint `105d7e7` was already committed and clean before round-3 edits. Default component bar remains 0.75. No merge, push or deployment.", '']
    table(lines, ['Bar','Correct broken live / table','Wrong probes newly blocked','Noise gold/pass','Real new errors','Main-gold real new errors','Real answers changed','Practical collision pairs'],
          [('main' if mode=='main' else f'{m.BARS[mode]:.2f}',
            f"{summary['canonical']['all'].get(mode+'_lost_gold',0)} / {summary['serving']['all'].get(mode+'_lost_gold',0)}", wrong[mode],
            f"{noise[mode]:,}/{total:,} ({100*noise[mode]/total:.2f}%)", summary['real']['all'].get(mode+'_new_errors',0),
            sum(v['occurrences'] for v in summary['correct_intent_failures'].get(mode,{}).values()),
            summary['real']['all'].get(mode+'_changed_answers',0), summary['collisions']['by_bar'].get(mode,{}).get('practical_pairs','—')) for mode in modes])
    lines += ['Counts compare with live-main code, replayed locally against unchanged CSVs. “Correct broken” means main reached the corpus English gold and the branch no longer does. Historical totals retain occurrence weights. “Main-gold real new errors” is the automatic proxy requested for correct intent; matching historical gold does not prove that submitted arguments have the correct meaning. Wrong-probe blocking measures rejection, not semantic correctness.', '',
              '## Material results', '',
              '**BLOCKER — the prescribed lexical rules do not guarantee that different answers stay separate.** Numeric tokens are now ordinary scored words, as requested. Different ordinals may still clear a component bar from their shared wording and character trigrams. Hyphen/article cleanup and directional containment can still change which event wins within one timeline. All actual answer changes and all feasible collision pairs are listed below. No required-word rules, synonym lists, numeric veto or new ambiguity guard were added.', '',
              '**MEDIUM — correct-intent calls remain sensitive to wording.** Separate event eligibility rejects some localized names, English name reorderings and reworded events that main answered. The automatic classification below distinguishes these from role and numeric differences and explicitly preserves unclassified cases.', '',
              '## Compared with round 2', '',
              'Round 2 had 166 lost table-canonical matches and 23 lost lowercase acronym variants at each bar. Round 3 has zero of either. The frozen plural noise corpus includes proper-name changes, so its aggregate acceptance falls under the requested stored-case restriction.', '']
    # Full frozen-baseline comparison from the previous measurement.
    r2 = json.loads((m.ROOT/'analysis/separate_bars_r2/summary.json').read_text())
    table(lines, ['Round / bar','Live / table gold lost','Wrong probes newly blocked','Noise gold/pass','Real new errors','Real changed answers'],
          [(f'{label} / {m.BARS[mode]:.2f}', f"{s['canonical']['all'].get(mode+'_lost_gold',0)} / {s['serving']['all'].get(mode+'_lost_gold',0)}",
            sum(v['all'].get(mode+'_new_errors',0) for v in s['wrong'].values())+s['distinct']['all'].get(mode+'_new_errors',0),
            f"{sum(v['all'][mode+'_gold'] for v in s['surface'].values()):,}/{total:,}",
            s['real']['all'].get(mode+'_new_errors',0), s['real']['all'].get(mode+'_changed_answers',0))
           for label,s in [('round 2',r2),('round 3',summary)] for mode in modes[1:]])
    lines += ['**Historical answer changes:** none at either bar after correcting replay arithmetic. The round-2 report’s six Upadhyaya changes were an indexing near-tie artifact: direct CSV-reading calls retain the Marxist predecessor. The final harness checks every answer-change record and all displayed failure-class examples against the actual functions.', '',
              '**Numeric safety example:** “Member of the 14th Parliament” and “Member of the 15th Parliament” score approximately 0.786 in both directions, clearing 0.75 and 0.70 even though their ordinal tokens receive no one-letter allowance. Names such as Williams/William can still receive a direct one-letter match; protecting them from plural normalization does not eliminate the separately retained spelling allowance.', '',
              '## Implemented rules', '',
              'Surface normalization keeps NFKC, quote/accent folding, punctuation and abbreviation-dot removal, dashes to spaces, ampersand to “and”, articles and possessive stripping. It preserves plural endings in normalized strings. Plural tolerance is applied pairwise in word containment only for alphabetic words written entirely lowercase in the stored alternative. Query case does not affect eligibility. Capitalized names and acronyms keep their spelling; HEOS/PSMS lowercase queries remain exact matches.', '',
              'Plural equivalence and one-letter edits are independent paths over the original word. They cannot be stacked on one word. Stored words of at least five letters still receive one insertion/deletion/substitution/adjacent-swap allowance, excluding digit-containing, ordinal and Roman-numeral tokens on either side; spelled-out cardinals such as fourteen/thousand are ordinary words. The hard numeric token-set veto is removed. Ordinal canonicalization was omitted to keep this round focused; equivalent suffixes such as 1er/1st receive ordinary lexical scores.', '',
              'Chronological entity and event scores must each reach the bar. Other tools keep their existing entity/event component requirement and time filtering. Combined weights, exact-full-match priority and completeness formulas are unchanged; plural equivalence does not alter exact flags, completeness or trigrams.', '',
              '## Correct canonical extractions', '']
    table(lines,['Corpus / family','Calls',*modes,'Lost gold 0.75 / 0.70'],
          [(label+'/'+family,s['calls'],*(s[mode+'_gold'] for mode in modes),' / '.join(str(s.get(mode+'_lost_gold',0)) for mode in modes[1:]))
           for label,groups in [('live',summary['canonical']),('table',summary['serving'])] for family,s in groups.items() if s.get('calls')])
    lines += ['All nine tools parquets are bound to current v6 logical questions. Translated canonical calls retain the English reference/table extraction. The table fixture also retains round 2’s whole-pipe queries for direct comparison; approved single-alternative live queries are measured separately. Arithmetic/ordering are outside single-lookup coverage; every event_time table row is covered. Full hashes and physical parquet coverage are retained.', '']
    for filename in ('canonical_new_failures.json','serving_new_failures.json'):
        rows = read(filename)
        lines += [f'### Every newly failing extraction: {filename}', '']
        if not rows:
            lines += ['None.', '']
        else:
            table(lines,['ID','Tool','Arguments','Gold','Main',*modes[1:],'Scores / causes'],
                  [(r['id'],r['tool'],r['arguments'],r['gold'],r['main'],*(r[mode] for mode in modes[1:]),[r.get('scores_against_main_winner'),r.get('causes_by_mode')]) for r in rows])
    lines += ['Existing failures: [canonical_existing_failures.json](canonical_existing_failures.json). No gold or data changes were made.', '', '## Wrong-extraction probes', '']
    table(lines,['Kind','Calls','Main answers','0.75 answers','0.70 answers','Newly blocked 0.75 / 0.70'],
          [(kind,s['all']['calls'],s['all']['main_answers'],s['all']['bar_075_answers'],s['all']['bar_070_answers'],
            ' / '.join(str(s['all'].get(mode+'_new_errors',0)) for mode in modes[1:])) for kind,s in summary['wrong'].items()])
    d=summary['distinct']['all']
    lines += [f"Source-reviewed distinct-event probes: {d['calls']} calls; newly blocked 0.75 / 0.70: {d.get('bar_075_new_errors',0)} / {d.get('bar_070_new_errors',0)}. Full records: [wrong_probes.json](wrong_probes.json), [distinct_event_probes.json](distinct_event_probes.json).", '']
    table(lines,['Probe','Arguments',*modes],[(r['kind'],r['arguments'],*(r[mode].get('answer','ERROR') for mode in modes)) for r in read('explicit_probes.json')])
    lines += ['## Surface noise', '']
    table(lines,['Kind','Calls',*['Gold/pass '+mode for mode in modes]],
          [(kind,s['all']['calls'],*(f"{s['all'][mode+'_gold']:,} / {100*s['all'][mode+'_gold']/s['all']['calls']:.2f}%" for mode in modes)) for kind,s in summary['surface'].items()])
    lines += ['The frozen round-2 noise transforms are retained, including mechanical plural changes to capitalized names and identifiers. Those are not all legitimate surface variants under round-3 rules. Possessives and hyphens use the same transforms as round 2. Every failing variant: [surface_failures.json](surface_failures.json). Focused unit tests separately exercise legitimate lowercase common-noun plurals in all six tools.', '', '## Real past calls', '']
    table(lines,['Family','Occurrences','Main answers','0.75 answers','0.70 answers','New errors 0.75 / 0.70','Changed answers 0.75 / 0.70','Lost gold 0.75 / 0.70'],
          [(family,s['calls'],s['main_answers'],s['bar_075_answers'],s['bar_070_answers'],
            ' / '.join(str(s.get(mode+'_new_errors',0)) for mode in modes[1:]),
            ' / '.join(str(s.get(mode+'_changed_answers',0)) for mode in modes[1:]),
            ' / '.join(str(s.get(mode+'_lost_gold',0)) for mode in modes[1:]))
           for family,s in summary['real'].items() if family in ('all','chronological','absolute/entity_time','event_time') and s.get('calls')])
    lines += [f"Parsed {summary['real']['unique_groups']:,} tool/argument/gold/cohort groups and {summary['real']['all']['calls']:,} occurrences. Full results and cohort splits: [real_calls.json](real_calls.json), [real_call_summary.json](real_call_summary.json). Historical event_time gold usually represents a downstream answer rather than the intermediate time.", '',
              '## Correct-intent real calls that would now fail', '',
              'Automatic selection: the call reaches historical gold on main and returns an error on the branch. Classifiers use only failed components against the main winning row. Priority: differing numeric tokens; missing entity-role words; foreign-language markers; English content-word reorderings/function-word changes; remaining event rewordings; other. The English-rendering class is an automatic wording candidate, not proof that a model translated it; the event-rewording class likewise does not certify semantic equivalence. Wrong numbers and missing roles are included because historical gold alone can hide wrong extraction. The complete record, classification evidence and scores are in [correct_intent_real_failures.json](correct_intent_real_failures.json).', '']
    from details import CLASSES
    table(lines,['Automatic class','0.75 occurrences / groups','0.70 occurrences / groups'],
          [(kind,*(f"{summary['correct_intent_failures'][mode][kind]['occurrences']} / {summary['correct_intent_failures'][mode][kind]['groups']}" for mode in modes[1:])) for kind in CLASSES])
    classified = read('correct_intent_real_failures.json')
    for mode in modes[1:]:
        lines += [f'### Five examples per class at {m.BARS[mode]:.2f}', '']
        for kind in CLASSES:
            rows=sorted([r for r in classified if r['failure_class_by_mode'].get(mode)==kind],key=lambda r:-r['count'])[:5]
            lines += [f'**{kind}**', '']
            if not rows:
                lines += ['No observed examples.', '']
            else:
                table(lines,['Arguments','Stored entity / event','Occurrences','Main gold','Entity/event scores','Evidence'],
                      [(r['arguments'],[r['main_winner'].get('entity'),r['main_winner'].get('event')],r['count'],r['gold'],r['scores_against_main_winner'][mode],r['evidence']) for r in rows])
    lines += ['## Every answer change', '']
    for filename,label in [('canonical_answer_changes.json','Live canonical'),('serving_answer_changes.json','Table canonical'),('real_answer_changes.json','Historical calls'),('surface_answer_changes.json','Surface calls')]:
        rows=read(filename)
        lines += [f'### {label}: {len(rows)} distinct records', '']
        if not rows:
            lines += ['None.', '']
            continue
        detail=['Every still-answering call whose literal answer differs from main. CSV lines are one-based and include the header.', '']
        table(detail,['ID / evidence','Tool','Arguments','Occurrences','Main answer / line','0.75 answer / line','0.70 answer / line','Scores against main row'],
              [(r.get('evidence',r.get('id')),r['tool'],r['arguments'],r.get('count',1),f"{r['main']['answer']} / {r['main']['row']+2}",
                *(f"{r[mode]['answer']} / {r[mode]['row']+2}" if 'answer' in r[mode] else 'ERROR' for mode in modes[1:]),r.get('scores_against_main_winner')) for r in rows])
        artifact=filename.replace('.json','.md')
        (m.OUT/artifact).write_text('\n'.join(detail).rstrip()+'\n')
        lines += [f'Complete list: [{artifact}]({artifact}); arguments, outcomes and scores: [{filename}]({filename}).', '']
    lines += ['## Collisions and plausible different-answer lookups', '',
              'Every distinct entity/event alternative in every lookup table is compared at both bars, in both score directions, against main, round 1 and round 2. The practical filter requires different answers and a feasible second lookup condition: event pairs share a stored entity alternative; entity pairs have a qualifying event in either direction, or time rows in the same year (a year-only query can cover both). This is a conservative plausibility filter, not an observed wrong-answer count. Exact priority may protect clean calls while noisy wording still exposes a collision. Existing risks are retained as well as newly crossing pairs.', '']
    table(lines,['Bar','All practical pairs','New vs main','New vs round 2'],
          [(f'{m.BARS[mode]:.2f}',s['practical_pairs'],s['new_vs_main'],s['new_vs_round2']) for mode,s in summary['collisions']['by_bar'].items()])
    detail=['Every pair passing the practical different-answer filter. Up to five actual row witnesses are retained per bar; JSON contains all CSV line memberships and both directional baseline/branch scores.', '']
    table(detail,['Table / field','A','B','Branch scores A→B / B→A','Main scores','Round-2 scores','Newly crosses','Rows with different answers'],
          [(r['table']+'/'+r['field'],r['a'],r['b'],r['new_scores'],r['baseline_scores']['main'],r['baseline_scores']['round2'],r['newly_reaches'],r['practical_risk_witnesses']) for r in read('practical_collision_pairs.json')])
    (m.OUT/'practical_collision_pairs.md').write_text('\n'.join(detail).rstrip()+'\n')
    lines += ['Complete practical pair list: [practical_collision_pairs.md](practical_collision_pairs.md), [practical_collision_pairs.json](practical_collision_pairs.json). All reported crossing pairs, normalized strings and row memberships: [collisions.json](collisions.json); domain coverage: [collision_coverage.json](collision_coverage.json).', '', '## Verification and reproduction', '',
              f"{summary['validation']['real_function_comparisons']} indexed replay comparisons passed against actual CSV-reading functions across six tools and three modes, plus independent rank-vector checks (case, plural, typos and numbers). Collision indexing passed {summary['collisions']['direct_score_validations']:,} independent direct-score comparisons across main and rounds 1–3. An additional {summary['validation']['supplemental_real_function_comparisons']} actual-function comparisons cover every answer-change record and the displayed failure-class examples. The round-2 index multiplied before dividing, which could change floating-point near-tie winners; the round-3 index now follows production arithmetic order and these checks enforce agreement. Input SHA-256 hashes were verified after replay: [manifest.json](manifest.json).", '',
              'All 37 focused temporal tests pass. The full suite passes 104 tests with 19 platform skips (85 passed), using explicit test-only translator settings; logs are retained in temporal_tests.log and unittest.log. Existing numeric-veto tests now assert the ordinary scoring formula and bar behavior; event-alternative tests accept additional numeric query words. Plural tests assert pairwise containment and stored-case restrictions rather than normalized-string equality. Ranking, time, alternatives and exact-priority regressions are retained.', '',
              'Reproduce from the Temporal workspace root: `.venv/bin/python -B -u analysis/separate_bars_r3/measure.py`. Reports and machine-readable evidence live outside the toolbox Git repository; the code, tests and compact reproducible evidence snapshot are committed on separate-bars. No serving CSVs, parquets, source datasets, caches or services were changed.', '']
    (m.OUT/'REPORT.md').write_text('\n'.join(lines).rstrip()+'\n')
    handoff = ['Round 3 is implemented and measured on `separate-bars`; the prescribed rules still permit different-answer matches, so the owner’s hard safety limit is not met.', '',
               'Round 2 was already committed as `105d7e7` and the working tree was clean. Round 3 removes numeric score zeroing, keeps plural endings in normalized text, applies pairwise plural tolerance only to lowercase stored words, and prevents stacking a plural change with a spelling edit. Case-independent exact acronym/name matching, separate component bars and existing ranking/time behavior are retained.', '']
    handoff += lines[4:8+len(modes)]
    handoff += ['', 'Full results, five examples per automatic failure class, every answer change and all plausible different-answer collision pairs: [analysis/separate_bars_r3/REPORT.md](../../analysis/separate_bars_r3/REPORT.md). Reproduce with `.venv/bin/python -B -u analysis/separate_bars_r3/measure.py`.', '',
                'No merge to main, push or deployment. Default component bar remains 0.75. Lowering it to 0.70 improves acceptance but does not establish the hard safety limit. Verification logs and input hashes are retained with the report.', '']
    (m.ROOT/'handoffs/reports/separate_bars_r3.md').write_text('\n'.join(handoff))
