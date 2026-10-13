VERDICT: Separate bars and spelling tolerance implemented and measured; the plan’s numeric no-match test conflicts with its unchanged score formula and remains an expected failure.

Baseline: main 281114b. Separate = independent entity/event thresholds plus one-edit word containment. No typo = identical separate thresholds with exact word containment. All three use the same six serving CSVs. Scores, exact priority, completeness and date handling retain their existing formulas.

## Findings against owner intent

**HIGH — the numeric “never matches” requirement is unmet.** Against a stored `Member of the 14th Parliament`, a `Member of the 15th Parliament` query scores 0.82667 for event and 0.93067 combined (entity exact). The numeric token does not count as present, but the remaining words and unchanged trigrams still pass. This violates the requested numeric test and intent rule 4. An explicit numeric-mismatch rejection would enforce it, but would add a new constraint beyond “everything else unchanged.” No reply to the clarification arrived during implementation; the specified formula was preserved. The test is recorded as an expected failure, not silently removed. No numeric rejection was added.

**HIGH — wrong-role and semantic-addition lookups remain accepted.** Assistant-coach HNK scores 0.86129 for entity, above the separate bar. Negated events, assistant/different prefixes and competing-owner queries still contain the stored key. This remains a rule-4 limitation of the requested formula; the explicit probes and frozen-sample counts below show its extent. A further semantic or token-completeness constraint would need a separate decision.

**MEDIUM — surface noise can lose existing matches.** Dropping “the” loses 365 gold matches; adding it loses 67; plural s loses 1,510 while gaining 4,284. Example: `John Grisham / Rainmaker` against `The Rainmaker` scores 0.54091 for event, so now fails. `heads of Chicago` scores 0.72051 against `head of Chicago`; a four-letter stored word receives no spelling tolerance. These are measured tradeoffs, not changes to normalization.

**MEDIUM — complete app-suite verification is blocked by missing dependencies.** All 25 ordinary temporal tests pass and the numeric requirement is one expected failure. Full discovery ran 77 tests: 58 passed, 16 platform skips, three import errors for missing fastapi/deep_translator. Installing repository requirements in a temporary environment was blocked by filesystem permissions; it was stopped under AGENTS.md. Offline replay validation is complete.

**MEDIUM — one-edit tolerance also accepts close distinct people.** The prior source review classifies `Nicolae Nedelcu` and `Nicolaie Nedelcu` as distinct. Query `head of Ziduri / Nicolae Nedelcu` matches the `Nicolaie Nedelcu` event row at before_chronological_reference.csv:4761 with event score 0.93571; no-typo separate bars reject it. Main already accepted it at event score 0.58571 through the combined bar. Thus the spelling allowance retains this wrong lookup that separate bars alone would remove. The probe is in distinct_event_probes.json. Spelling distance cannot distinguish such identities; this is a limitation of the requested allowance.

**LOW — lookup work increases.** A five-call local smoke benchmark of John Grisham / The Pelican Brief measured median 0.174 seconds on main and 0.299 seconds on the branch, both returning The Firm. This is an illustrative local timing, not a production latency estimate; the extra word comparisons account for the added work. Raw timings are in timing.json.

## Canonical correct arguments

| Corpus/family | Calls | Main gold | Separate gold | No typo gold | Separate lost gold | No typo lost gold |
|---|---|---|---|---|---|---|
| live questions/all | 19160 | 19158 | 19158 | 19158 | 0 | 0 |
| live questions/chronological | 12406 | 12406 | 12406 | 12406 | 0 | 0 |
| live questions/absolute/entity_time | 6754 | 6752 | 6752 | 6752 | 0 | 0 |
| all table rows/all | 16656 | 16647 | 16647 | 16647 | 0 | 0 |
| all table rows/chronological | 10920 | 10914 | 10914 | 10914 | 0 | 0 |
| all table rows/absolute/entity_time | 5636 | 5633 | 5633 | 5633 | 0 | 0 |
| all table rows/event_time | 100 | 100 | 100 | 100 | 0 | 0 |

Every single-lookup question in all nine live tools parquets was bound to the fresh v6 logical corpus, with trimmed question text and gold checked. Two translated questions contain trailing whitespace in v6 JSONL; their nine physical appearances bind by stable ID and identical English gold, recorded in parquet_coverage.json. No stale translation content was found. Arithmetic, ordering and multi-step L1 questions are outside a single canonical lookup; every event_time table row is separately covered. Multilingual canonical arguments use retained English reference/table strings, as in the prior harness; this does not test translation or extraction. Each entity argument is one approved alternative present in the question/reference where available; this avoids treating an entire pipe cell as model extraction.

Across 177,580 physical parquet rows, all 90,090 single-lookup appearances are covered. All six table-row controls retain their outcomes; nine existing serving-row gold failures remain (overlapping keys/duplicate answers), and the two live-question failures are the owner-held PRC cases below.

### Every newly failing live question

None in either branch mode.

### Existing canonical failures

| ID | Arguments | Gold | Main result | Separate result |
|---|---|---|---|---|
| val:16176_Q2 | ["People's Republic of China", '2003-03'] | Wen Jiabao | {'answer': 'Hu Jintao', 'row': 349, 'score': 1.0, 'entity_score': 1.0} | {'answer': 'Hu Jintao', 'row': 349, 'score': 1.0, 'entity_score': 1.0} |
| train:16177_Q2 | ["People's Republic of China", '2013-03'] | Wen Jiabao | {'answer': 'Hu Jintao', 'row': 356, 'score': 1.0, 'entity_score': 1.0} | {'answer': 'Hu Jintao', 'row': 356, 'score': 1.0, 'entity_score': 1.0} |

## Wrong extraction probes

| Probe kind | Calls | Main answers | Separate answers | No typo answers | New errors separate | New errors no typo |
|---|---|---|---|---|---|---|
| assistant addition | 499 | 499 | 499 | 499 | 0 | 0 |
| assistant full role | 1 | 1 | 1 | 1 | 0 | 0 |
| competing owners | 1 | 1 | 1 | 1 | 0 | 0 |
| different addition | 499 | 499 | 499 | 499 | 0 | 0 |
| different entity | 500 | 16 | 6 | 6 | 10 | 10 |
| negated event | 333 | 333 | 333 | 333 | 0 | 0 |
| role-less | 133 | 34 | 24 | 24 | 10 | 10 |
| role-less HNK | 1 | 0 | 0 | 0 | 0 | 0 |
| untranslated event French | 1 | 0 | 0 | 0 | 0 | 0 |
| untranslated event German | 1 | 0 | 0 | 0 | 0 | 0 |
| wrong company | 1 | 1 | 0 | 0 | 1 | 1 |
| wrong role | 1 | 1 | 1 | 1 | 0 | 0 |

The original reviewer sample IDs are reused for assistant/different additions and negated events, refreshed to current full-role keys. Different-entity substitutions and role omissions use a fixed 500-question sample (seed 1009). Returning an answer to a deliberate substitution may be a valid answer for the substituted timeline: newly blocked counts are rejection rates, while gold counts in JSON track leakage to the original question. The literal semantic additions still contain the full stored text and remain a limitation of directional containment.

Additional source-reviewed close but distinct event probes: 118 deduplicated calls, main answers 50, separate answers 46, no-typo answers 45; separate newly blocks 4, no-typo newly blocks 5. Sources are the DIFFERENT judgments from the completed typo audit; exact names, source candidate IDs, arguments and scores are in distinct_event_probes.json. A distinct event can legitimately reach its own table row; the counts describe rejection, not semantic correctness.

| Probe | Arguments | Main | Separate | No typo | Scores against main winner |
|---|---|---|---|---|---|
| wrong company | ['CEO of Apple', 'Virginia M. (Ginni) Rometty'] | Samuel J Palmisano | ERROR | ERROR | {'main': {'entity_score': 0.6541666666666666, 'event_score': 1.0, 'combined_score': 0.7925}, 'separate': {'entity_score': 0.6541666666666666, 'event_score': 1.0, 'combined_score': 0.7925}, 'separate_no_typo': {'entity_score': 0.6541666666666666, 'event_score': 1.0, 'combined_score': 0.7925}} |
| wrong role | ['assistant coach of the team HNK Rijeka', 'Simon Rožman'] | Goran Tomić | Goran Tomić | Goran Tomić | {'main': {'entity_score': 0.8612903225806452, 'event_score': 1.0, 'combined_score': 0.9167741935483871}, 'separate': {'entity_score': 0.8612903225806452, 'event_score': 1.0, 'combined_score': 0.9167741935483871}, 'separate_no_typo': {'entity_score': 0.8612903225806452, 'event_score': 1.0, 'combined_score': 0.9167741935483871}} |
| role-less HNK | ['HNK Rijeka', 'Simon Rožman'] | ERROR | ERROR | ERROR | None |
| untranslated event French | ['John Grisham', 'L’Affaire Pélican'] | ERROR | ERROR | ERROR | None |
| untranslated event German | ['John Grisham', 'Die Akte'] | ERROR | ERROR | ERROR | None |
| negated event | ['John Grisham', 'not The Pelican Brief'] | The Firm | The Firm | The Firm | {'main': {'entity_score': 1.0, 'event_score': 1.0, 'combined_score': 1.0}, 'separate': {'entity_score': 1.0, 'event_score': 1.0, 'combined_score': 1.0}, 'separate_no_typo': {'entity_score': 1.0, 'event_score': 1.0, 'combined_score': 1.0}} |
| competing owners | ['Google \| Apple', 'Mac OS 10.6 Snow Leopard'] | 10.7 Lion | 10.7 Lion | 10.7 Lion | {'main': {'entity_score': 1.0, 'event_score': 1.0, 'combined_score': 1.0}, 'separate': {'entity_score': 1.0, 'event_score': 1.0, 'combined_score': 1.0}, 'separate_no_typo': {'entity_score': 1.0, 'event_score': 1.0, 'combined_score': 1.0}} |
| assistant full role | ['assistant head coach of the team HNK Rijeka', 'Simon Rožman'] | Goran Tomić | Goran Tomić | Goran Tomić | {'main': {'entity_score': 1.0, 'event_score': 1.0, 'combined_score': 1.0}, 'separate': {'entity_score': 1.0, 'event_score': 1.0, 'combined_score': 1.0}, 'separate_no_typo': {'entity_score': 1.0, 'event_score': 1.0, 'combined_score': 1.0}} |

## Surface noise

| Noise | Calls | Main gold/pass rate | Separate gold/pass rate | No typo gold/pass rate | Separate lost gold |
|---|---|---|---|---|---|
| lowercase | 19153 | 19151 / 99.99% | 19151 / 99.99% | 19151 / 99.99% | 0 |
| drop accents | 2239 | 2239 / 100.00% | 2239 / 100.00% | 2239 / 100.00% | 0 |
| drop the | 4028 | 4021 / 99.83% | 3656 / 90.76% | 3656 / 90.76% | 365 |
| add the | 19160 | 19151 / 99.95% | 19084 / 99.60% | 19084 / 99.60% | 67 |
| F.C. / FC | 1085 | 1085 / 100.00% | 1085 / 100.00% | 1085 / 100.00% | 0 |
| one character typo | 18982 | 10424 / 54.92% | 18866 / 99.39% | 6843 / 36.05% | 6 |
| singular/plural | 19128 | 13213 / 69.08% | 15987 / 83.58% | 6957 / 36.37% | 1510 |

Only changed variants count. Dates stay fixed. Lowercase, accent removal, adding/removing the, and F.C./FC reuse the previous harness. Typos replace the middle character of the first eligible word with length ≥5; plural s toggles the first eligible word with length ≥4. One word changes per call. No extra plural rule was added; ≥5-character stored words benefit from insertion/deletion tolerance. All failing variants and scores are in surface_failures.json.

## Real past model calls

Separate bars create 3,582 errors out of 446,214 currently answering calls (0.80%). Every new error is chronological (7.63% of existing chronological answers). Spelling tolerance preserves 287 calls that the no-typo branch rejects and gains 574 answers over main; no still-answering call changes its answer.

The rollouts/current cohort contributes 3,394 new errors; older/other logs contribute 188. Without spelling tolerance those counts are 3,670 and 199. Chronological gains are 241, time-filtered entity-tool gains 330, and event_time gains three; these offset some new errors in the total answers column.

| Family | Calls | Main answers | Separate answers | No typo answers | Separate new errors | No typo new errors | Separate changed answers | Separate lost historical gold |
|---|---|---|---|---|---|---|---|---|
| all | 623291 | 446214 | 443206 | 442345 | 3582 | 3869 | 0 | 3266 |
| chronological | 97662 | 46934 | 43593 | 43065 | 3582 | 3869 | 0 | 3266 |
| absolute/entity_time | 101400 | 32660 | 32990 | 32660 | 0 | 0 | 0 | 0 |
| event_time | 424229 | 366620 | 366623 | 366620 | 0 | 0 | 0 | 0 |

| Mode | Cause against main winner | Occurrences |
|---|---|---|
| separate | entity below 0.75; missing role words | 1618 |
| separate | event below 0.75; lexical extraction difference | 1603 |
| separate | entity below 0.75; lexical extraction difference | 198 |
| separate | event below 0.75; numeric/ordinal difference | 147 |
| separate | entity below 0.75; numeric/ordinal difference | 12 |
| separate | event below 0.75; missing role words | 4 |
| separate_no_typo | event below 0.75; lexical extraction difference | 1764 |
| separate_no_typo | entity below 0.75; missing role words | 1618 |
| separate_no_typo | entity below 0.75; lexical extraction difference | 324 |
| separate_no_typo | event below 0.75; numeric/ordinal difference | 147 |
| separate_no_typo | entity below 0.75; numeric/ordinal difference | 12 |
| separate_no_typo | event below 0.75; missing role words | 4 |

### Top currently answering calls that become errors

separate

| Tool | Arguments | Occurrences | Current answer | Scores against current row | Cause | First evidence |
|---|---|---|---|---|---|---|
| before_chronological_reference | ['Tata Sumo', "Tata model's induction"] | 164 | Estate | {'entity_score': 1.0, 'event_score': 0.47857142857142854, 'combined_score': 0.7914285714285714} | event below 0.75; lexical extraction difference | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 5546} |
| before_chronological_reference | ['Tata Sierra', 'induction by Tata'] | 40 | Estate | {'entity_score': 1.0, 'event_score': 0.43571428571428567, 'combined_score': 0.7742857142857142} | event below 0.75; lexical extraction difference | {'file': 'rollouts/current/Qwen3-8B/tools_outputs2.jsonl', 'line': 9530} |
| before_chronological_reference | ['Gravesend town pier', 'Thames Clippers'] | 22 | Gravesham Borough Council | {'entity_score': 0.624, 'event_score': 1.0, 'combined_score': 0.7744} | entity below 0.75; missing role words | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 6587} |
| before_chronological_reference | ['Primrose Hill Tunnel', 'Network Rail'] | 22 | Railtrack | {'entity_score': 0.62, 'event_score': 1.0, 'combined_score': 0.772} | entity below 0.75; missing role words | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 11159} |
| after_chronological_reference | ['Primrose Hill Tunnel', 'London and North Western Railway'] | 21 | London, Midland and Scottish Railway | {'entity_score': 0.62, 'event_score': 1.0, 'combined_score': 0.772} | entity below 0.75; missing role words | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 10561} |
| after_chronological_reference | ["Sweden men's national ice hockey team", 'Leif Boork'] | 21 | Tommy Sandlin | {'entity_score': 0.6046153846153846, 'event_score': 1.0, 'combined_score': 0.7627692307692308} | entity below 0.75; missing role words | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 1926} |
| after_chronological_reference | ['Gravesend town pier', 'London, Tilbury and Southend Railway'] | 20 | Gravesham Borough Council | {'entity_score': 0.624, 'event_score': 1.0, 'combined_score': 0.7744} | entity below 0.75; missing role words | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 3953} |
| after_chronological_reference | ["Sweden men's national ice hockey team", 'Leif Boork'] | 20 | Tommy Sandlin | {'entity_score': 0.6046153846153846, 'event_score': 1.0, 'combined_score': 0.7627692307692308} | entity below 0.75; missing role words | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 6397} |
| before_chronological_reference | ['Jaroslav Pelikan', 'Seminarul Concordia'] | 19 | Valparaiso University | {'entity_score': 1.0, 'event_score': 0.575, 'combined_score': 0.83} | event below 0.75; lexical extraction difference | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 786} |
| before_chronological_reference | ['Patrick du Val', 'Universitatea din Georgia'] | 19 | Victoria University of Manchester | {'entity_score': 1.0, 'event_score': 0.43859649122807015, 'combined_score': 0.775438596491228} | event below 0.75; lexical extraction difference | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 4035} |
| before_chronological_reference | ['Friedrich Leo', 'Universität Göttingen'] | 19 | University of Strasbourg | {'entity_score': 1.0, 'event_score': 0.4476190476190476, 'combined_score': 0.779047619047619} | event below 0.75; lexical extraction difference | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 4132} |
| after_chronological_reference | ['Young man in Mayo costume', 'Paul Durand-Ruel'] | 19 | Ernest Hoschedé | {'entity_score': 0.7129032258064516, 'event_score': 1.0, 'combined_score': 0.827741935483871} | entity below 0.75; missing role words | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 4889} |

separate_no_typo

| Tool | Arguments | Occurrences | Current answer | Scores against current row | Cause | First evidence |
|---|---|---|---|---|---|---|
| before_chronological_reference | ['Tata Sumo', "Tata model's induction"] | 164 | Estate | {'entity_score': 1.0, 'event_score': 0.47857142857142854, 'combined_score': 0.7914285714285714} | event below 0.75; lexical extraction difference | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 5546} |
| before_chronological_reference | ['Tata Sierra', 'induction by Tata'] | 40 | Estate | {'entity_score': 1.0, 'event_score': 0.43571428571428567, 'combined_score': 0.7742857142857142} | event below 0.75; lexical extraction difference | {'file': 'rollouts/current/Qwen3-8B/tools_outputs2.jsonl', 'line': 9530} |
| before_chronological_reference | ['Gravesend town pier', 'Thames Clippers'] | 22 | Gravesham Borough Council | {'entity_score': 0.624, 'event_score': 1.0, 'combined_score': 0.7744} | entity below 0.75; missing role words | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 6587} |
| before_chronological_reference | ['Primrose Hill Tunnel', 'Network Rail'] | 22 | Railtrack | {'entity_score': 0.62, 'event_score': 1.0, 'combined_score': 0.772} | entity below 0.75; missing role words | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 11159} |
| before_chronological_reference | ['Mikel Anta Mendiaraz', 'Real Sociedad'] | 21 | Real Valladolid | {'entity_score': 0.719298245614035, 'event_score': 1.0, 'combined_score': 0.831578947368421} | entity below 0.75; lexical extraction difference | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 9182} |
| before_chronological_reference | ['Pedro J. Ramrez', 'El Mundo'] | 21 | Diario 16 | {'entity_score': 0.6974358974358974, 'event_score': 1.0, 'combined_score': 0.8184615384615385} | entity below 0.75; lexical extraction difference | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 9349} |
| after_chronological_reference | ['Primrose Hill Tunnel', 'London and North Western Railway'] | 21 | London, Midland and Scottish Railway | {'entity_score': 0.62, 'event_score': 1.0, 'combined_score': 0.772} | entity below 0.75; missing role words | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 10561} |
| after_chronological_reference | ["Sweden men's national ice hockey team", 'Leif Boork'] | 21 | Tommy Sandlin | {'entity_score': 0.6046153846153846, 'event_score': 1.0, 'combined_score': 0.7627692307692308} | entity below 0.75; missing role words | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 1926} |
| after_chronological_reference | ['Gravesend town pier', 'London, Tilbury and Southend Railway'] | 20 | Gravesham Borough Council | {'entity_score': 0.624, 'event_score': 1.0, 'combined_score': 0.7744} | entity below 0.75; missing role words | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 3953} |
| after_chronological_reference | ["Sweden men's national ice hockey team", 'Leif Boork'] | 20 | Tommy Sandlin | {'entity_score': 0.6046153846153846, 'event_score': 1.0, 'combined_score': 0.7627692307692308} | entity below 0.75; missing role words | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 6397} |
| before_chronological_reference | ['Jaroslav Pelikan', 'Seminarul Concordia'] | 19 | Valparaiso University | {'entity_score': 1.0, 'event_score': 0.575, 'combined_score': 0.83} | event below 0.75; lexical extraction difference | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 786} |
| after_chronological_reference | ['Philip Franklin', 'Université Princeton'] | 19 | Harvard University | {'entity_score': 1.0, 'event_score': 0.5833333333333333, 'combined_score': 0.8333333333333333} | event below 0.75; lexical extraction difference | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 1990} |

Parsed 93,854 distinct tool/argument/historical-gold/cohort groups, retaining occurrence weights. Only output tool_call blocks are read; prompt examples and code are never executed. All local rollouts/current and deprecated files, toolbox/rollouts.jsonl and analysis call logs use the prior harness's exclusions plus this report directory. Current and other cohorts, every tool, and all failures are in JSON. Historical gold may differ from today's gold; event_time historical-gold counts compare an intermediate date to a final task answer and are diagnostic only. Failures include bad extraction and localized names; they are not all legitimate regressions.

## Verification and scope

432 replay comparisons against the actual CSV-reading lookup functions passed, across six tools and all three modes, plus independent rank-vector checks. Input and rollout SHA-256 hashes are recorded and checked after measurement.

Existing test changed: tests_temporal_alternatives.EntityAlternativeTests.test_event_punctuation_has_original_score_and_eligibility (renamed test_event_punctuation_score_and_separate_eligibility): chronological eligibility now uses the event score ≥0.75 rather than 0.6 + 0.4 × event. No existing priority test was changed. Focused tests cover wrong company, role-less HNK, John Grishm, Pelican Brif, Rajshee/Rajshree, alternatives, all tools, edit operations, numeric exclusions, unchanged trigrams/completeness and dates.

No CSVs, datasets, translation cache or service state were changed. Run from the workspace root: `.venv/bin/python -B -u analysis/separate_bars/measure.py`. Code, tests and a report snapshot are committed only in toolbox on separate-bars; main stays at 281114b.

Blocked commands: `/private/tmp/temporal-separate-bars-venv/bin/python -m pip install --no-cache-dir -r toolbox/requirements.txt` failed with Operation not permitted creating `/var/folders/52/hw_1b9nd5qjd_f9bzb76kyb00000gp/T/tmp12q3op_9`; `/private/tmp/temporal-separate-bars-venv/bin/python3.13 -m ensurepip --upgrade --default-pip` also exited 1 during environment creation. No retry/workaround was attempted. `ps -Ao pid,etime,%cpu,command` was denied by the sandbox. None of these failures blocked offline measurements.
