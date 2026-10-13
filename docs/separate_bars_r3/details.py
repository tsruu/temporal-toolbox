"""Automatic reporting classifiers and collision audit; never used by the matcher."""
import collections
import functools
import json
import random
import re

import numpy as np

CLASSES = ('missing role words', 'untranslated/foreign-language name',
           "model's own English rendering of a translated name", 'paraphrased/reworded event',
           'wrong or different number', 'other')
ROLE_WORDS = {'head', 'coach', 'chair', 'owner', 'president', 'ceo', 'duke', 'chief', 'director'}
FOREIGN_WORDS = set(('universitatea universite universitat universitateaului seminarul partidul parti '
    'ministerul minister fur pentru din des der die das du de la le les al au aux von und '
    'orchestre orchestra simfonica symphonique colegiul centrul cercetare stat grupul '
    'national coopération cooperare presedinte président ambassadeur antrenor principal').split())
FUNCTION_WORDS = {'of', 'in', 'at', 'to', 'for', 'and', 'by', 'on'}


def install(m):
    globals()['m'] = m


def classify_failures(tools):
    records = json.loads((m.OUT/'real_call_regressions.json').read_text())
    classified = []
    for r in records:
        modes = [mode for mode in m.MODES[1:] if r['main_gold'] and 'answer' not in r[mode]]
        if not modes:
            continue
        norm = tools['bar_075'].module.normalize_entity
        fields = [('event' if r['tool'] == 'event_time' else 'entity', r['arguments'][0])]
        if m.family(r['tool']) == 'chronological':
            fields.append(('event', r['arguments'][1]))
        by_mode, evidence = {}, {}
        for mode in modes:
            reasons = []
            for field, query in fields:
                if r['scores_against_main_winner'][mode][field+'_score'] >= m.BARS[mode]:
                    continue
                alternatives = r['main_winner'][field].split('|')
                stored = max(alternatives, key=lambda a: tools[mode].module._surface_match_rank(norm(query), a))
                q, k = set(norm(query).split()), set(norm(stored).split())
                missing = k-q
                number = tools[mode].module.is_number_word
                qn, kn = {w for w in q if number(w)}, {w for w in k if number(w)}
                if qn != kn:
                    cause = 'wrong or different number'
                elif field == 'entity' and missing & ROLE_WORDS:
                    cause = 'missing role words'
                elif (q-k) & FOREIGN_WORDS or any(c in query for c in 'äöüßăâșţțî'):
                    cause = 'untranslated/foreign-language name'
                elif (q-FUNCTION_WORDS == k-FUNCTION_WORDS and q-FUNCTION_WORDS
                      and norm(query) != norm(stored)):
                    cause = "model's own English rendering of a translated name"
                elif field == 'event':
                    # English event rewording candidates, including abbreviations/omissions.
                    cause = 'paraphrased/reworded event'
                else:
                    cause = 'other'
                reasons.append((cause, dict(field=field, query=query, stored=stored,
                    missing_words=sorted(missing), query_numbers=sorted(qn), stored_numbers=sorted(kn))))
            # One mutually exclusive class per group/bar; numeric and role differences take priority.
            priority = ['wrong or different number', 'missing role words', 'untranslated/foreign-language name',
                        "model's own English rendering of a translated name", 'paraphrased/reworded event', 'other']
            chosen = min(reasons, key=lambda v: priority.index(v[0])) if reasons else ('other', {})
            by_mode[mode], evidence[mode] = chosen
        r.update(failure_class_by_mode=by_mode, classification_evidence=evidence)
        classified.append(r)
    m.dump('correct_intent_real_failures.json', classified)
    summaries = {}
    for mode in m.MODES[1:]:
        summaries[mode] = {kind: dict(groups=sum(r['failure_class_by_mode'].get(mode) == kind for r in classified),
            occurrences=sum(r['count'] for r in classified if r['failure_class_by_mode'].get(mode) == kind)) for kind in CLASSES}
    return summaries


def score_index(mod, raw, one_edit, numeric_guard=False, stored_case=False):
    normalized = [mod.normalize_entity(s) for s in raw]
    vocab = {w for text in normalized for w in text.split()}
    deletion = collections.defaultdict(set)
    plural_stems = collections.defaultdict(set)
    posts = [collections.defaultdict(list), collections.defaultdict(list)]
    plural_posts = collections.defaultdict(list)
    exact, numbers = collections.defaultdict(list), collections.defaultdict(list)
    lengths = np.zeros((2, len(raw)))
    for i, text in enumerate(normalized):
        parts = (set(text.split()), mod.char_ngrams(text))
        lengths[:, i] = [len(v) for v in parts]
        for kind, words in enumerate(parts):
            for w in words:
                posts[kind][w].append(i)
        exact[text].append(i)
        if numeric_guard:
            numbers[frozenset(w for w in parts[0] if mod.is_number_word(w))].append(i)
        if stored_case:
            for w in mod.stored_plural_words(raw[i]):
                plural_posts[w].append(i)
                plural_stems[mod._singular_surface(w)].add(w)
    for w in vocab:
        for i in range(len(w)):
            deletion[w[:i]+w[i+1:]].add(w)
    posts = [{k:np.array(v) for k,v in p.items()} for p in posts]
    plural_posts = {w:np.array(v) for w,v in plural_posts.items()}
    @functools.lru_cache(maxsize=None)
    def matching(q):
        if not one_edit:
            return {q} & vocab
        candidates = {q} | deletion.get(q, set())
        for i in range(len(q)):
            d = q[:i]+q[i+1:]
            candidates.add(d)
            candidates.update(deletion.get(d, set()))
        for i in range(len(q)-1):
            candidates.add(q[:i]+q[i+1]+q[i]+q[i+2:])
        return {w for w in candidates & vocab if mod.word_present(w, {q})}
    def scores(query):
        q = mod.normalize_entity(query)
        found = np.zeros_like(lengths)
        matched = set().union(*(matching(w) for w in q.split()))
        for w in matched:
            found[0, posts[0][w]] += 1
        if stored_case:
            plurals = set().union(*(plural_stems.get(mod._singular_surface(w), set())
                for w in q.split() if w.isalpha() and len(w) >= 3 and not mod.is_number_word(w)))
            for w in plurals-matched:
                found[0, plural_posts[w]] += 1
        for gram in mod.char_ngrams(q):
            if gram in posts[1]:
                found[1, posts[1][gram]] += 1
        result = .7*(found[0]/np.maximum(lengths[0], 1)) + .3*(found[1]/np.maximum(lengths[1], 1))
        if numeric_guard:
            nums = frozenset(w for w in q.split() if mod.is_number_word(w))
            mask = np.zeros(len(raw), bool)
            mask[numbers.get(nums, [])] = True
            result[~mask] = 0
        if q:
            result[exact.get(q, [])] = 1
        return result
    return normalized, scores


def collision_check(tools):
    new = tools['bar_075'].module
    main = tools['main'].module
    r1 = m.module('r1_collision_r3', m.OUT/'round1_temporal.py')
    r2 = m.module('r2_collision_r3', m.OUT/'round2_temporal.py')
    records, risks, coverage = [], [], []
    validations = 0
    for name, rows in tools['main'].tables.items():
        fields = ['event'] if name == 'event_time' else ['entity', 'event'] if m.family(name) == 'chronological' else ['entity']
        for field in fields:
            cells = collections.defaultdict(list)
            for i, row in enumerate(rows):
                for alt in row[field].split('|'):
                    cells[alt.strip()].append(i)
            raw = sorted(cells)
            bn, ni = score_index(new, raw, True, stored_case=True)
            mn, mi = score_index(main, raw, False)
            rn, ri = score_index(r1, raw, True)
            tn, ti = score_index(r2, raw, True, numeric_guard=True)
            pairs = set()
            for i, q in enumerate(raw):
                after = ni(q)
                for j in np.flatnonzero(after >= .70-1e-12):
                    if i != j:
                        pairs.add((min(i, int(j)), max(i, int(j))))
                if i < 8:
                    for j in random.Random(10413+i).sample(range(len(raw)), min(12, len(raw))):
                        for mod, vector, norm, case in ((new, after, bn, True), (main, mi(q), mn, False),
                                                        (r1, ri(q), rn, False), (r2, ti(q), tn, False)):
                            value = mod.entity_similarity(mod.normalize_entity(q), norm[j], mod.stored_plural_words(raw[j])) if case else mod.entity_similarity(mod.normalize_entity(q), norm[j])
                            assert np.isclose(vector[j], value), (name, field, q, raw[j], vector[j], value)
                            validations += 1
            start, risk_start = len(records), len(risks)
            for i, j in sorted(pairs):
                a, b = raw[i], raw[j]
                def direct(mod, query, stored):
                    return mod.entity_similarity(mod.normalize_entity(query), mod.normalize_entity(stored), mod.stored_plural_words(stored)) if mod is new else mod.entity_similarity(mod.normalize_entity(query), mod.normalize_entity(stored))
                scores = [direct(new, a, b), direct(new, b, a)]
                baselines = {label:[direct(mod, a, b), direct(mod, b, a)] for label,mod in [('main',main), ('round1',r1), ('round2',r2)]}
                rec = dict(table=name, field=field, a=a, b=b, a_lines=[k+2 for k in cells[a]], b_lines=[k+2 for k in cells[b]],
                    new_normalized=[bn[i],bn[j]], new_scores=scores, baseline_scores=baselines,
                    identical=bn[i] == bn[j], newly_reaches={mode:{label:any(s >= bar and old < bar for s,old in zip(scores,vals)) for label,vals in baselines.items()} for mode,bar in m.BARS.items()})
                witnesses = collections.defaultdict(list)
                for ai in cells[a]:
                    ar = rows[ai]
                    for bi in cells[b]:
                        br = rows[bi]
                        if ar['answer'] == br['answer']:
                            continue
                        for mode,bar in m.BARS.items():
                            if max(scores) < bar:
                                continue
                            # Event collisions must share the same actual owner; entity
                            # collisions also need a feasible event or compatible time.
                            if field == 'event' and name != 'event_time':
                                owners_a = {main.normalize_entity(v) for v in ar['entity'].split('|')}
                                owners_b = {main.normalize_entity(v) for v in br['entity'].split('|')}
                                feasible = bool(owners_a & owners_b)
                            elif m.family(name) == 'chronological':
                                feasible = max(new.event_match_rank(new.normalize_entity(ar['event']), br['event'])[1],
                                               new.event_match_rank(new.normalize_entity(br['event']), ar['event'])[1]) >= bar
                            elif name == 'event_time':
                                feasible = True
                            else:
                                # A year-only or month-only query can cover any two
                                # transitions in the same year, including distinct days.
                                feasible = new.normalize_time(ar['time'])[0] == new.normalize_time(br['time'])[0]
                            if feasible:
                                witness = dict(a_line=ai+2, b_line=bi+2, a_answer=ar['answer'], b_answer=br['answer'],
                                    a_other=ar.get('entity' if field == 'event' else 'event', ar.get('time')),
                                    b_other=br.get('entity' if field == 'event' else 'event', br.get('time')))
                                if len(witnesses[mode]) < 5:
                                    witnesses[mode].append(witness)
                if witnesses:
                    rec['practical_risk_witnesses'] = dict(witnesses)
                    risks.append(rec)
                if any(any(vals.values()) for vals in rec['newly_reaches'].values()) or witnesses:
                    records.append(rec)
            coverage.append(dict(table=name, field=field, distinct_cells=len(raw), qualifying_pairs=len(pairs),
                                 reported_pairs=len(records)-start, practical_risks=len(risks)-risk_start))
            print('Collision', coverage[-1], flush=True)
    m.dump('collisions.json', records)
    m.dump('practical_collision_pairs.json', risks)
    m.dump('collision_coverage.json', coverage)
    return dict(coverage=coverage, reported_pairs=len(records), practical_pairs=len(risks),
        direct_score_validations=validations,
        by_bar={mode:dict(practical_pairs=sum(mode in r.get('practical_risk_witnesses', {}) for r in risks),
                         new_vs_main=sum(mode in r.get('practical_risk_witnesses', {}) and r['newly_reaches'][mode]['main'] for r in risks),
                         new_vs_round2=sum(mode in r.get('practical_risk_witnesses', {}) and r['newly_reaches'][mode]['round2'] for r in risks)) for mode in m.BARS})
