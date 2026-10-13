VERDICT: Round 3 is implemented and measured on separate-bars; the measured rules still permit different-answer matches, so the owner’s hard safety limit is not met.

Main reference `281114b`; round-2 checkpoint `105d7e7` was already committed and clean before round-3 edits. Default component bar remains 0.75. No merge, push or deployment.

| Bar | Correct broken live / table | Wrong probes newly blocked | Noise gold/pass | Real new errors | Main-gold real new errors | Real answers changed | Practical collision pairs |
|---|---|---|---|---|---|---|---|
| main | 0 / 0 | 0 | 94,695/121,785 (77.76%) | 0 | 0 | 0 | — |
| 0.75 | 0 / 0 | 25 | 119,853/121,785 (98.41%) | 3668 | 3306 | 0 | 971 |
| 0.70 | 0 / 0 | 23 | 120,298/121,785 (98.78%) | 3023 | 2733 | 0 | 1164 |

Counts compare with live-main code, replayed locally against unchanged CSVs. “Correct broken” means main reached the corpus English gold and the branch no longer does. Historical totals retain occurrence weights. “Main-gold real new errors” is the automatic proxy requested for correct intent; matching historical gold does not prove that submitted arguments have the correct meaning. Wrong-probe blocking measures rejection, not semantic correctness.

## Material results

**BLOCKER — the prescribed lexical rules do not guarantee that different answers stay separate.** Numeric tokens are now ordinary scored words, as requested. Different ordinals may still clear a component bar from their shared wording and character trigrams. Hyphen/article cleanup and directional containment can still change which event wins within one timeline. All actual answer changes and all feasible collision pairs are listed below. No required-word rules, synonym lists, numeric veto or new ambiguity guard were added.

**MEDIUM — correct-intent calls remain sensitive to wording.** Separate event eligibility rejects some localized names, English name reorderings and reworded events that main answered. The automatic classification below distinguishes these from role and numeric differences and explicitly preserves unclassified cases.

## Compared with round 2

Round 2 had 166 lost table-canonical matches and 23 lost lowercase acronym variants at each bar. Round 3 has zero of either. The frozen plural noise corpus includes proper-name changes, so its aggregate acceptance falls under the requested stored-case restriction.

| Round / bar | Live / table gold lost | Wrong probes newly blocked | Noise gold/pass | Real new errors | Real changed answers |
|---|---|---|---|---|---|
| round 2 / 0.75 | 0 / 166 | 35 | 121,069/121,785 | 4464 | 6 |
| round 2 / 0.70 | 0 / 166 | 33 | 121,210/121,785 | 3861 | 6 |
| round 3 / 0.75 | 0 / 0 | 25 | 119,853/121,785 | 3668 | 0 |
| round 3 / 0.70 | 0 / 0 | 23 | 120,298/121,785 | 3023 | 0 |

**Historical answer changes:** none at either bar after correcting replay arithmetic. The round-2 report’s six Upadhyaya changes were an indexing near-tie artifact: direct CSV-reading calls retain the Marxist predecessor. The final harness checks every answer-change record and all displayed failure-class examples against the actual functions.

**Numeric safety example:** “Member of the 14th Parliament” and “Member of the 15th Parliament” score approximately 0.786 in both directions, clearing 0.75 and 0.70 even though their ordinal tokens receive no one-letter allowance. Names such as Williams/William can still receive a direct one-letter match; protecting them from plural normalization does not eliminate the separately retained spelling allowance.

## Implemented rules

Surface normalization keeps NFKC, quote/accent folding, punctuation and abbreviation-dot removal, dashes to spaces, ampersand to “and”, articles and possessive stripping. It preserves plural endings in normalized strings. Plural tolerance is applied pairwise in word containment only for alphabetic words written entirely lowercase in the stored alternative. Query case does not affect eligibility. Capitalized names and acronyms keep their spelling; HEOS/PSMS lowercase queries remain exact matches.

Plural equivalence and one-letter edits are independent paths over the original word. They cannot be stacked on one word. Stored words of at least five letters still receive one insertion/deletion/substitution/adjacent-swap allowance, excluding digit-containing, ordinal and Roman-numeral tokens on either side; spelled-out cardinals such as fourteen/thousand are ordinary words. The hard numeric token-set veto is removed. Ordinal canonicalization was omitted to keep this round focused; equivalent suffixes such as 1er/1st receive ordinary lexical scores.

Chronological entity and event scores must each reach the bar. Other tools keep their existing entity/event component requirement and time filtering. Combined weights, exact-full-match priority and completeness formulas are unchanged; plural equivalence does not alter exact flags, completeness or trigrams.

## Correct canonical extractions

| Corpus / family | Calls | main | bar_075 | bar_070 | Lost gold 0.75 / 0.70 |
|---|---|---|---|---|---|
| live/all | 19160 | 19158 | 19158 | 19158 | 0 / 0 |
| live/chronological | 12406 | 12406 | 12406 | 12406 | 0 / 0 |
| live/absolute/entity_time | 6754 | 6752 | 6752 | 6752 | 0 / 0 |
| table/all | 16656 | 16647 | 16647 | 16647 | 0 / 0 |
| table/chronological | 10920 | 10914 | 10914 | 10914 | 0 / 0 |
| table/absolute/entity_time | 5636 | 5633 | 5633 | 5633 | 0 / 0 |
| table/event_time | 100 | 100 | 100 | 100 | 0 / 0 |

All nine tools parquets are bound to current v6 logical questions. Translated canonical calls retain the English reference/table extraction. The table fixture also retains round 2’s whole-pipe queries for direct comparison; approved single-alternative live queries are measured separately. Arithmetic/ordering are outside single-lookup coverage; every event_time table row is covered. Full hashes and physical parquet coverage are retained.

### Every newly failing extraction: canonical_new_failures.json

None.

### Every newly failing extraction: serving_new_failures.json

None.

Existing failures: [canonical_existing_failures.json](canonical_existing_failures.json). No gold or data changes were made.

## Wrong-extraction probes

| Kind | Calls | Main answers | 0.75 answers | 0.70 answers | Newly blocked 0.75 / 0.70 |
|---|---|---|---|---|---|
| assistant addition | 499 | 499 | 499 | 499 | 0 / 0 |
| assistant full role | 1 | 1 | 1 | 1 | 0 / 0 |
| competing owners | 1 | 1 | 1 | 1 | 0 / 0 |
| different addition | 499 | 499 | 499 | 499 | 0 / 0 |
| different entity | 500 | 16 | 6 | 7 | 10 / 9 |
| negated event | 333 | 333 | 333 | 333 | 0 / 0 |
| role-less | 133 | 34 | 24 | 28 | 10 / 9 |
| role-less HNK | 1 | 0 | 0 | 0 | 0 / 0 |
| untranslated event French | 1 | 0 | 0 | 0 | 0 / 0 |
| untranslated event German | 1 | 0 | 0 | 0 | 0 / 0 |
| wrong company | 1 | 1 | 0 | 0 | 1 / 1 |
| wrong role | 1 | 1 | 1 | 1 | 0 / 0 |

Source-reviewed distinct-event probes: 118 calls; newly blocked 0.75 / 0.70: 4 / 4. Full records: [wrong_probes.json](wrong_probes.json), [distinct_event_probes.json](distinct_event_probes.json).

| Probe | Arguments | main | bar_075 | bar_070 |
|---|---|---|---|---|
| wrong company | ['CEO of Apple', 'Virginia M. (Ginni) Rometty'] | Samuel J Palmisano | ERROR | ERROR |
| wrong role | ['assistant coach of the team HNK Rijeka', 'Simon Rožman'] | Goran Tomić | Goran Tomić | Goran Tomić |
| role-less HNK | ['HNK Rijeka', 'Simon Rožman'] | ERROR | ERROR | ERROR |
| untranslated event French | ['John Grisham', 'L’Affaire Pélican'] | ERROR | ERROR | ERROR |
| untranslated event German | ['John Grisham', 'Die Akte'] | ERROR | ERROR | ERROR |
| negated event | ['John Grisham', 'not The Pelican Brief'] | The Firm | The Firm | The Firm |
| competing owners | ['Google \| Apple', 'Mac OS 10.6 Snow Leopard'] | 10.7 Lion | 10.7 Lion | 10.7 Lion |
| assistant full role | ['assistant head coach of the team HNK Rijeka', 'Simon Rožman'] | Goran Tomić | Goran Tomić | Goran Tomić |

## Surface noise

| Kind | Calls | Gold/pass main | Gold/pass bar_075 | Gold/pass bar_070 |
|---|---|---|---|---|
| lowercase | 19153 | 19,151 / 99.99% | 19,151 / 99.99% | 19,151 / 99.99% |
| drop accents | 2239 | 2,239 / 100.00% | 2,239 / 100.00% | 2,239 / 100.00% |
| drop the | 4028 | 4,021 / 99.83% | 4,028 / 100.00% | 4,028 / 100.00% |
| add the | 19160 | 19,158 / 99.99% | 19,158 / 99.99% | 19,158 / 99.99% |
| F.C. / FC | 1085 | 1,085 / 100.00% | 1,085 / 100.00% | 1,085 / 100.00% |
| one character typo | 18982 | 10,424 / 54.92% | 18,879 / 99.46% | 18,980 / 99.99% |
| singular/plural | 19128 | 13,213 / 69.08% | 17,307 / 90.48% | 17,651 / 92.28% |
| possessive | 19114 | 19,112 / 99.99% | 19,112 / 99.99% | 19,112 / 99.99% |
| hyphen | 18896 | 6,292 / 33.30% | 18,894 / 99.99% | 18,894 / 99.99% |

The frozen round-2 noise transforms are retained, including mechanical plural changes to capitalized names and identifiers. Those are not all legitimate surface variants under round-3 rules. Possessives and hyphens use the same transforms as round 2. Every failing variant: [surface_failures.json](surface_failures.json). Focused unit tests separately exercise legitimate lowercase common-noun plurals in all six tools.

## Real past calls

| Family | Occurrences | Main answers | 0.75 answers | 0.70 answers | New errors 0.75 / 0.70 | Changed answers 0.75 / 0.70 | Lost gold 0.75 / 0.70 |
|---|---|---|---|---|---|---|---|
| all | 623291 | 446214 | 443154 | 444267 | 3668 / 3023 | 0 / 0 | 3306 / 2733 |
| chronological | 97662 | 46934 | 43562 | 44191 | 3634 / 3023 | 0 / 0 | 3304 / 2733 |
| absolute/entity_time | 101400 | 32660 | 33001 | 33426 | 2 / 0 | 0 / 0 | 2 / 0 |
| event_time | 424229 | 366620 | 366591 | 366650 | 32 / 0 | 0 / 0 | 0 / 0 |

Parsed 93,854 tool/argument/gold/cohort groups and 623,291 occurrences. Full results and cohort splits: [real_calls.json](real_calls.json), [real_call_summary.json](real_call_summary.json). Historical event_time gold usually represents a downstream answer rather than the intermediate time.

## Correct-intent real calls that would now fail

Automatic selection: the call reaches historical gold on main and returns an error on the branch. Classifiers use only failed components against the main winning row. Priority: differing numeric tokens; missing entity-role words; foreign-language markers; English content-word reorderings/function-word changes; remaining event rewordings; other. The English-rendering class is an automatic wording candidate, not proof that a model translated it; the event-rewording class likewise does not certify semantic equivalence. Wrong numbers and missing roles are included because historical gold alone can hide wrong extraction. The complete record, classification evidence and scores are in [correct_intent_real_failures.json](correct_intent_real_failures.json).

| Automatic class | 0.75 occurrences / groups | 0.70 occurrences / groups |
|---|---|---|
| missing role words | 1575 / 427 | 1268 / 337 |
| untranslated/foreign-language name | 791 / 91 | 787 / 89 |
| model's own English rendering of a translated name | 72 / 53 | 35 / 26 |
| paraphrased/reworded event | 613 / 168 | 550 / 148 |
| wrong or different number | 85 / 37 | 55 / 31 |
| other | 170 / 87 | 38 / 22 |

### Five examples per class at 0.75

**missing role words**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Gravesend town pier', 'Thames Clippers'] | ['owner of Gravesend town pier', 'Thames Clippers'] | 22 | Gravesham Borough Council | {'entity_score': 0.624, 'event_score': 1.0, 'combined_score': 0.7744} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 6587} |
| ['Primrose Hill Tunnel', 'Network Rail'] | ['owner of Primrose Hill Tunnel', 'Network Rail'] | 22 | Railtrack | {'entity_score': 0.62, 'event_score': 1.0, 'combined_score': 0.772} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 11159} |
| ['Primrose Hill Tunnel', 'London and North Western Railway'] | ['owner of Primrose Hill Tunnel', 'London and North Western Railway'] | 21 | London, Midland and Scottish Railway | {'entity_score': 0.62, 'event_score': 1.0, 'combined_score': 0.772} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 10561} |
| ["Sweden men's national ice hockey team", 'Leif Boork'] | ["head coach of the team Sweden men's national ice hockey team", 'Leif Boork'] | 21 | Tommy Sandlin | {'entity_score': 0.6666666666666666, 'event_score': 1.0, 'combined_score': 0.8} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 1926} |
| ['Gravesend town pier', 'London, Tilbury and Southend Railway'] | ['owner of Gravesend town pier', 'London, Tilbury and Southend Railway'] | 20 | Gravesham Borough Council | {'entity_score': 0.624, 'event_score': 1.0, 'combined_score': 0.7744} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 3953} |

**untranslated/foreign-language name**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Jaroslav Pelikan', 'Seminarul Concordia'] | ['Jaroslav Pelikan', 'Concordia Seminary'] | 19 | Valparaiso University | {'entity_score': 1.0, 'event_score': 0.575, 'combined_score': 0.83} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 786} |
| ['Patrick du Val', 'Universitatea din Georgia'] | ['Patrick du Val', 'University of Georgia'] | 19 | Victoria University of Manchester | {'entity_score': 1.0, 'event_score': 0.43859649122807015, 'combined_score': 0.775438596491228} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 4035} |
| ['Friedrich Leo', 'Universität Göttingen'] | ['Friedrich Leo', 'University of Göttingen'] | 19 | University of Strasbourg | {'entity_score': 1.0, 'event_score': 0.4476190476190476, 'combined_score': 0.779047619047619} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 4132} |
| ['Leonid Kantorovich', "Université d'État de Novosibirsk"] | ['Leonid Kantorovich', 'Novosibirsk State University'] | 19 | Military Engineering-Technical University | {'entity_score': 1.0, 'event_score': 0.6743589743589743, 'combined_score': 0.8697435897435897} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 5491} |
| ['Leonid Kantorovich', 'Universitatea de Stat din Novosibirsk'] | ['Leonid Kantorovich', 'Novosibirsk State University'] | 19 | Military Engineering-Technical University | {'entity_score': 1.0, 'event_score': 0.6974358974358974, 'combined_score': 0.8789743589743589} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 5492} |

**model's own English rendering of a translated name**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Infosys CEO', "Nandan Nilekani's tenure"] | ['CEO of Infosys \| role of CEO of Infosys \| CEO position of Infosys \| chief executive officer position at Infosys \| Chief Executive position at Infosys company \| Chief Executive Officer position in Infosys company', 'Nandan Nilekani'] | 4 | Narayan Murthy | {'entity_score': 0.6166666666666666, 'event_score': 1.0, 'combined_score': 0.77} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 2282} |
| ['Volkswagen CEO position', "Martin Winterkom's appointment as CEO"] | ['CEO of Volkswagen \| CEO position of Volkswagen \| role of CEO of Volkswagen \| Chief Executive Officer position in Volkswagen company \| chief executive officer position at Volkswagen \| Chief Executive position at Volkswagen company', 'Martin Winterkom'] | 4 | Bernd Pischetsrieder | {'entity_score': 0.7499999999999999, 'event_score': 1.0, 'combined_score': 0.8499999999999999} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 9161} |
| ['KwaZulu-Natal head', "S'bu Ndebele"] | ['head of KwaZulu-Natal', "S'bu Ndebele"] | 3 | Zweli Mkhize | {'entity_score': 0.7302631578947367, 'event_score': 1.0, 'combined_score': 0.838157894736842} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 2321} |
| ['Microsoft CEO', "Steve Ballmer's tenure"] | ['CEO of Microsoft \| CEO position of Microsoft \| chief executive officer position at Microsoft \| Chief Executive position at Microsoft company \| role of CEO of Microsoft \| Chief Executive Officer position in Microsoft company', 'Steve Ballmer'] | 3 | Satya Nadella | {'entity_score': 0.638095238095238, 'event_score': 1.0, 'combined_score': 0.7828571428571429} | {'file': 'rollouts/current/trained/consistency_grpo_600ckpt.jsonl', 'line': 784} |
| ['UK Prime Minister', "John Major's term"] | ['role of Prime Minister of the UK \| Prime Minister of the UK \| British Prime Minister \| position of Prime Minister of the UK', 'John Major'] | 3 | Tony Blair | {'entity_score': 0.7249999999999999, 'event_score': 1.0, 'combined_score': 0.835} | {'file': 'rollouts/current/trained/consistencyv6.jsonl', 'line': 10355} |

**paraphrased/reworded event**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Tata Sumo', "Tata model's induction"] | ['Tata Motors \| Tata', 'Tata Sumo'] | 164 | Estate | {'entity_score': 1.0, 'event_score': 0.47857142857142854, 'combined_score': 0.7914285714285714} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 5546} |
| ['Tata Sierra', 'induction by Tata'] | ['Tata Motors \| Tata', 'Tata Sumo'] | 40 | Estate | {'entity_score': 1.0, 'event_score': 0.43571428571428567, 'combined_score': 0.7742857142857142} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs2.jsonl', 'line': 9530} |
| ['Ridley Scott', 'Legend'] | ['Ridley Scott \| Director Ridley Scott', 'movie Legend'] | 18 | Blade Runner | {'entity_score': 1.0, 'event_score': 0.47, 'combined_score': 0.788} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 4237} |
| ['Ridley Scott', 'Legend'] | ['Ridley Scott \| Director Ridley Scott', 'movie Legend'] | 18 | Blade Runner | {'entity_score': 1.0, 'event_score': 0.47, 'combined_score': 0.788} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 4238} |
| ['Cyril Granon', 'Clubul de Renne de Ferrol'] | ['Cyril Granon', 'Racing Club de Ferrol'] | 13 | A.C. Ajaccio | {'entity_score': 1.0, 'event_score': 0.5078947368421052, 'combined_score': 0.8031578947368421} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 2363} |

**wrong or different number**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Miloslav Penner', 'FK Příbram'] | ['Miloslav Penner', '1. FK Příbram'] | 17 | SK Dynamo České Budějovice | {'entity_score': 1.0, 'event_score': 0.7066666666666666, 'combined_score': 0.8826666666666666} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 9537} |
| ['Lukáš Vytlacil', 'Institute of Czech Literature, Czech Academy of Sciences'] | ['Lukáš M. Vytlačil', 'Institute of Czech Literature, Czech Academy of Sciences'] | 7 | Institute of Ethnology, Czech Academy of Sciences | {'entity_score': 0.7023809523809523, 'event_score': 1.0, 'combined_score': 0.8214285714285714} | {'file': 'rollouts/current/trained/consistencyv4.jsonl', 'line': 5415} |
| ['Roscosmos', 'Sputnik 1'] | ['Roscosmos \| Roscosmos, India', 'Sputnik 3'] | 6 | Sputnik 2 | {'entity_score': 1.0, 'event_score': 0.6071428571428571, 'combined_score': 0.8428571428571429} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 1212} |
| ['Chetan Bhagat', 'Two States'] | ['Chetan Bhagat', '2 States'] | 5 | Revolution 2020 | {'entity_score': 1.0, 'event_score': 0.6, 'combined_score': 0.84} | {'file': 'rollouts/current/trained/consistencyv2.jsonl', 'line': 2429} |
| ['John Russell, 1st Earl Russell', 'Fifth Parliament of the United Kingdom'] | ['John Russell, 1st Earl Russell', 'Member of the 5th Parliament of the United Kingdom'] | 4 | Member of the 6th Parliament of the United Kingdom | {'entity_score': 1.0, 'event_score': 0.6956140350877192, 'combined_score': 0.8782456140350876} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 3663} |

**other**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Best Independent Game', 'Rocket League'] | ['Game Award for Best Independent Game \| Best Independent Game Award', 'Rocket League'] | 18 | Inside | {'entity_score': 0.7499999999999999, 'event_score': 1.0, 'combined_score': 0.8499999999999999} | {'file': 'rollouts/current/trained/grpo_fix.jsonl', 'line': 9021} |
| ['Game of the Year', 'God of War'] | ['Game Award for Game of the Year \| Game of the Year Award', 'God of War'] | 9 | Sekiro: Shadows Die Twice | {'entity_score': 0.7124999999999999, 'event_score': 1.0, 'combined_score': 0.8274999999999999} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 7670} |
| ['Best Feature Film', 'Pulijanmam'] | ['National Film Award for Best Feature Film \| Best Feature Film award', 'Pulijanmam'] | 7 | Kaalpurush | {'entity_score': 0.7392857142857142, 'event_score': 1.0, 'combined_score': 0.8435714285714285} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 4246} |
| ['Orm Finnend Dahl', 'Folkwang University of the Arts'] | ['Orm Finnendahl', 'Folkwang University of the Arts'] | 6 | Hochschule für Musik Freiburg | {'entity_score': 0.625, 'event_score': 1.0, 'combined_score': 0.775} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 11283} |
| ['Best Feature Film', 'Pulijanmam'] | ['National Film Award for Best Feature Film \| Best Feature Film award', 'Pulijanmam'] | 6 | Kaalpurush | {'entity_score': 0.7392857142857142, 'event_score': 1.0, 'combined_score': 0.8435714285714285} | {'file': 'rollouts/current/trained/consistency_grpo_600ckpt.jsonl', 'line': 1297} |

### Five examples per class at 0.70

**missing role words**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Gravesend town pier', 'Thames Clippers'] | ['owner of Gravesend town pier', 'Thames Clippers'] | 22 | Gravesham Borough Council | {'entity_score': 0.624, 'event_score': 1.0, 'combined_score': 0.7744} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 6587} |
| ['Primrose Hill Tunnel', 'Network Rail'] | ['owner of Primrose Hill Tunnel', 'Network Rail'] | 22 | Railtrack | {'entity_score': 0.62, 'event_score': 1.0, 'combined_score': 0.772} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 11159} |
| ['Primrose Hill Tunnel', 'London and North Western Railway'] | ['owner of Primrose Hill Tunnel', 'London and North Western Railway'] | 21 | London, Midland and Scottish Railway | {'entity_score': 0.62, 'event_score': 1.0, 'combined_score': 0.772} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 10561} |
| ["Sweden men's national ice hockey team", 'Leif Boork'] | ["head coach of the team Sweden men's national ice hockey team", 'Leif Boork'] | 21 | Tommy Sandlin | {'entity_score': 0.6666666666666666, 'event_score': 1.0, 'combined_score': 0.8} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 1926} |
| ['Gravesend town pier', 'London, Tilbury and Southend Railway'] | ['owner of Gravesend town pier', 'London, Tilbury and Southend Railway'] | 20 | Gravesham Borough Council | {'entity_score': 0.624, 'event_score': 1.0, 'combined_score': 0.7744} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 3953} |

**untranslated/foreign-language name**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Jaroslav Pelikan', 'Seminarul Concordia'] | ['Jaroslav Pelikan', 'Concordia Seminary'] | 19 | Valparaiso University | {'entity_score': 1.0, 'event_score': 0.575, 'combined_score': 0.83} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 786} |
| ['Patrick du Val', 'Universitatea din Georgia'] | ['Patrick du Val', 'University of Georgia'] | 19 | Victoria University of Manchester | {'entity_score': 1.0, 'event_score': 0.43859649122807015, 'combined_score': 0.775438596491228} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 4035} |
| ['Friedrich Leo', 'Universität Göttingen'] | ['Friedrich Leo', 'University of Göttingen'] | 19 | University of Strasbourg | {'entity_score': 1.0, 'event_score': 0.4476190476190476, 'combined_score': 0.779047619047619} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 4132} |
| ['Leonid Kantorovich', "Université d'État de Novosibirsk"] | ['Leonid Kantorovich', 'Novosibirsk State University'] | 19 | Military Engineering-Technical University | {'entity_score': 1.0, 'event_score': 0.6743589743589743, 'combined_score': 0.8697435897435897} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 5491} |
| ['Leonid Kantorovich', 'Universitatea de Stat din Novosibirsk'] | ['Leonid Kantorovich', 'Novosibirsk State University'] | 19 | Military Engineering-Technical University | {'entity_score': 1.0, 'event_score': 0.6974358974358974, 'combined_score': 0.8789743589743589} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 5492} |

**model's own English rendering of a translated name**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Infosys CEO', "Nandan Nilekani's tenure"] | ['CEO of Infosys \| role of CEO of Infosys \| CEO position of Infosys \| chief executive officer position at Infosys \| Chief Executive position at Infosys company \| Chief Executive Officer position in Infosys company', 'Nandan Nilekani'] | 4 | Narayan Murthy | {'entity_score': 0.6166666666666666, 'event_score': 1.0, 'combined_score': 0.77} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 2282} |
| ['Microsoft CEO', "Steve Ballmer's tenure"] | ['CEO of Microsoft \| CEO position of Microsoft \| chief executive officer position at Microsoft \| Chief Executive position at Microsoft company \| role of CEO of Microsoft \| Chief Executive Officer position in Microsoft company', 'Steve Ballmer'] | 3 | Satya Nadella | {'entity_score': 0.638095238095238, 'event_score': 1.0, 'combined_score': 0.7828571428571429} | {'file': 'rollouts/current/trained/consistency_grpo_600ckpt.jsonl', 'line': 784} |
| ['Infosys CEO', 'Vishal Sikka'] | ['CEO of Infosys \| role of CEO of Infosys \| CEO position of Infosys \| chief executive officer position at Infosys \| Chief Executive position at Infosys company \| Chief Executive Officer position in Infosys company', 'Vishal Sikka'] | 3 | UB Pravin Rao | {'entity_score': 0.6166666666666666, 'event_score': 1.0, 'combined_score': 0.77} | {'file': 'rollouts/deprecated/plain_grpo_think_ok_400ckpt.jsonl', 'line': 6172} |
| ['Ralph Duncan James', 'Cambridge University'] | ['Ralph Duncan James', 'University of Cambridge'] | 2 | California Institute of Technology | {'entity_score': 1.0, 'event_score': 0.6809523809523809, 'combined_score': 0.8723809523809523} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 97} |
| ['Infosys CEO', "Nandan Nilekani's tenure"] | ['CEO of Infosys \| role of CEO of Infosys \| CEO position of Infosys \| chief executive officer position at Infosys \| Chief Executive position at Infosys company \| Chief Executive Officer position in Infosys company', 'Nandan Nilekani'] | 2 | Narayan Murthy | {'entity_score': 0.6166666666666666, 'event_score': 1.0, 'combined_score': 0.77} | {'file': 'rollouts/current/trained/consistencyv6.jsonl', 'line': 2281} |

**paraphrased/reworded event**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Tata Sumo', "Tata model's induction"] | ['Tata Motors \| Tata', 'Tata Sumo'] | 164 | Estate | {'entity_score': 1.0, 'event_score': 0.47857142857142854, 'combined_score': 0.7914285714285714} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 5546} |
| ['Tata Sierra', 'induction by Tata'] | ['Tata Motors \| Tata', 'Tata Sumo'] | 40 | Estate | {'entity_score': 1.0, 'event_score': 0.43571428571428567, 'combined_score': 0.7742857142857142} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs2.jsonl', 'line': 9530} |
| ['Ridley Scott', 'Legend'] | ['Ridley Scott \| Director Ridley Scott', 'movie Legend'] | 18 | Blade Runner | {'entity_score': 1.0, 'event_score': 0.47, 'combined_score': 0.788} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 4237} |
| ['Ridley Scott', 'Legend'] | ['Ridley Scott \| Director Ridley Scott', 'movie Legend'] | 18 | Blade Runner | {'entity_score': 1.0, 'event_score': 0.47, 'combined_score': 0.788} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 4238} |
| ['Cyril Granon', 'Clubul de Renne de Ferrol'] | ['Cyril Granon', 'Racing Club de Ferrol'] | 13 | A.C. Ajaccio | {'entity_score': 1.0, 'event_score': 0.5078947368421052, 'combined_score': 0.8031578947368421} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 2363} |

**wrong or different number**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Roscosmos', 'Sputnik 1'] | ['Roscosmos \| Roscosmos, India', 'Sputnik 3'] | 6 | Sputnik 2 | {'entity_score': 1.0, 'event_score': 0.6071428571428571, 'combined_score': 0.8428571428571429} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 1212} |
| ['Chetan Bhagat', 'Two States'] | ['Chetan Bhagat', '2 States'] | 5 | Revolution 2020 | {'entity_score': 1.0, 'event_score': 0.6, 'combined_score': 0.84} | {'file': 'rollouts/current/trained/consistencyv2.jsonl', 'line': 2429} |
| ['John Russell, 1st Earl Russell', 'Fifth Parliament of the United Kingdom'] | ['John Russell, 1st Earl Russell', 'Member of the 5th Parliament of the United Kingdom'] | 4 | Member of the 6th Parliament of the United Kingdom | {'entity_score': 1.0, 'event_score': 0.6956140350877192, 'combined_score': 0.8782456140350876} | {'file': 'rollouts/current/trained/consistency_grpo_400ckpt.jsonl', 'line': 3663} |
| ['John Russell, 1st Earl Russell', 'Fifth Parliament of the United Kingdom'] | ['John Russell, 1st Earl Russell', 'Member of the 5th Parliament of the United Kingdom'] | 4 | Member of the 6th Parliament of the United Kingdom | {'entity_score': 1.0, 'event_score': 0.6956140350877192, 'combined_score': 0.8782456140350876} | {'file': 'rollouts/current/trained/consistency_grpo_600ckpt.jsonl', 'line': 744} |
| ['Sir Charles Burrell, 3rd Baronet', 'Third Parliament of the United Kingdom'] | ['Sir Charles Burrell, 3rd Baronet', 'Member of the 3rd Parliament of the United Kingdom'] | 3 | Member of the 4th Parliament of the United Kingdom | {'entity_score': 1.0, 'event_score': 0.6956140350877192, 'combined_score': 0.8782456140350876} | {'file': 'rollouts/current/trained/consistencyv2.jsonl', 'line': 407} |

**other**

| Arguments | Stored entity / event | Occurrences | Main gold | Entity/event scores | Evidence |
|---|---|---|---|---|---|
| ['Orm Finnend Dahl', 'Folkwang University of the Arts'] | ['Orm Finnendahl', 'Folkwang University of the Arts'] | 6 | Hochschule für Musik Freiburg | {'entity_score': 0.625, 'event_score': 1.0, 'combined_score': 0.775} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 11283} |
| ['1970 F1 World Championship', 'Austria'] | ['Formula One race for the 1970 F1 World Championship \| F1 race of the 1970 season \| F1 Grand Prix for the 1970 season \| Formula One Grand Prix for the 1970 season \| F1 Grand Prix of the 1970 season \| F1 Grand Prix for the 1970 Formula One World Championship \| F1 race for the 1970 Formula One World Championship \| F1 race for the 1970 F1 World Championship \| F1 Grand Prix for the 1970 F1 World Championship \| Formula One Grand Prix for the 1970 F1 World Championship \| Formula One race for the 1970 season', 'Austria'] | 3 | Germany | {'entity_score': 0.6723809523809523, 'event_score': 1.0, 'combined_score': 0.8034285714285714} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 338} |
| ['IBM chief executive officer', 'John Fellows Akers becoming IBM CEO'] | ['CEO of IBM \| chief executive officer position at IBM \| CEO position of IBM \| Chief Executive position in IBM company \| role of CEO of IBM', 'John Fellows Akers'] | 3 | John R Opel | {'entity_score': 0.645045045045045, 'event_score': 1.0, 'combined_score': 0.787027027027027} | {'file': 'rollouts/current/trained/consistency_grpo_600ckpt.jsonl', 'line': 1767} |
| ['2019 MotoGP World Championship', 'Germany race'] | ['MotoGP race for the 2019 MotoGP World Championship \| MotoGP Grand Prix of the 2019 season \| MotoGP Grand Prix for the 2019 season \| MotoGP Grand Prix for the 2019 MotoGP World Championship \| MotoGP race for the 2019 season \| MotoGP race of the 2019 season', 'Germany'] | 3 | Czech Republic | {'entity_score': 0.682051282051282, 'event_score': 1.0, 'combined_score': 0.8092307692307692} | {'file': 'rollouts/current/trained/consistencyv3.jsonl', 'line': 3080} |
| ['2019 F1 World Championship', 'Austria'] | ['Formula One race for the 2019 F1 World Championship \| F1 Grand Prix for the 2019 season \| F1 Grand Prix of the 2019 season \| F1 race of the 2019 season \| F1 race for the 2019 Formula One World Championship \| F1 race for the 2019 F1 World Championship \| F1 Grand Prix for the 2019 Formula One World Championship \| Formula One race for the 2019 season \| Formula One Grand Prix for the 2019 F1 World Championship \| Formula One Grand Prix for the 2019 season \| F1 Grand Prix for the 2019 F1 World Championship', 'Austria'] | 2 | England | {'entity_score': 0.6723809523809523, 'event_score': 1.0, 'combined_score': 0.8034285714285714} | {'file': 'rollouts/current/Qwen3-8B/tools_outputs.jsonl', 'line': 5344} |

## Every answer change

### Live canonical: 0 distinct records

None.

### Table canonical: 0 distinct records

None.

### Historical calls: 0 distinct records

None.

### Surface calls: 59 distinct records

Complete list: [surface_answer_changes.md](surface_answer_changes.md); arguments, outcomes and scores: [surface_answer_changes.json](surface_answer_changes.json).

## Collisions and plausible different-answer lookups

Every distinct entity/event alternative in every lookup table is compared at both bars, in both score directions, against main, round 1 and round 2. The practical filter requires different answers and a feasible second lookup condition: event pairs share a stored entity alternative; entity pairs have a qualifying event in either direction, or time rows in the same year (a year-only query can cover both). This is a conservative plausibility filter, not an observed wrong-answer count. Exact priority may protect clean calls while noisy wording still exposes a collision. Existing risks are retained as well as newly crossing pairs.

| Bar | All practical pairs | New vs main | New vs round 2 |
|---|---|---|---|
| 0.75 | 971 | 26 | 520 |
| 0.70 | 1164 | 41 | 555 |

Complete practical pair list: [practical_collision_pairs.md](practical_collision_pairs.md), [practical_collision_pairs.json](practical_collision_pairs.json). All reported crossing pairs, normalized strings and row memberships: [collisions.json](collisions.json); domain coverage: [collision_coverage.json](collision_coverage.json).

## Verification and reproduction

432 indexed replay comparisons passed against actual CSV-reading functions across six tools and three modes, plus independent rank-vector checks (case, plural, typos and numbers). Collision indexing passed 3,072 independent direct-score comparisons across main and rounds 1–3. An additional 153 actual-function comparisons cover every answer-change record and the displayed failure-class examples. The round-2 index multiplied before dividing, which could change floating-point near-tie winners; the round-3 index now follows production arithmetic order and these checks enforce agreement. Input SHA-256 hashes were verified after replay: [manifest.json](manifest.json).

All 37 focused temporal tests pass. The full suite passes 104 tests with 19 platform skips (85 passed), using explicit test-only translator settings; logs are retained in temporal_tests.log and unittest.log. Existing numeric-veto tests now assert the ordinary scoring formula and bar behavior; event-alternative tests accept additional numeric query words. Plural tests assert pairwise containment and stored-case restrictions rather than normalized-string equality. Ranking, time, alternatives and exact-priority regressions are retained.

Reproduce from the Temporal workspace root: `.venv/bin/python -B -u analysis/separate_bars_r3/measure.py`. Reports and machine-readable evidence live outside the toolbox Git repository; the code, tests and compact reproducible evidence snapshot are committed on separate-bars. No serving CSVs, parquets, source datasets, caches or services were changed.
