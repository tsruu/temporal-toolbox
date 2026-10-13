#!/usr/bin/env python3
"""Offline three-way replay; never executes logged code or calls services."""
import collections
import csv
import functools
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import random
import re
import subprocess
import sys

import numpy as np
import pyarrow.parquet as pq

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'analysis/fix_5_9'))
import verify as harness

def module(name, path):
    return harness.module(name, path)

g = module('prior_measure', ROOT/'analysis/gate_measure/measure.py')
live = module('live_bindings', ROOT/'analysis/gate_measure/remeasure_datafix10/remeasure.py')
noise = module('question_reader', ROOT/'analysis/typo_check/find.py')
MODES = ('main', 'separate', 'separate_no_typo')

def dump(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')

def sha(path):
    with path.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256')
    return digest.hexdigest()

def family(name):
    if name.endswith('chronological_reference'):
        return 'chronological'
    return 'event_time' if name == 'event_time' else 'absolute/entity_time'

class Replay(harness.IndexedTools):
    def __init__(self, mode):
        super().__init__('after')
        self.mode = mode
        self.module = module('temporal_'+mode, OUT/'main_temporal.py' if mode == 'main' else ROOT/'toolbox/app/tools/temporal.py')
        if mode == 'separate_no_typo':
            self.module.word_present = lambda key, query: key in query
        for name in self.tables:
            getattr(self.module, name).__defaults__ = (str(ROOT/f'toolbox/app/tools/{name}.csv'),)
        self.vocabulary = {word for _, _, _, posts, _ in self.columns.values() for word in posts[0]}
        self.deletions = collections.defaultdict(set)
        for word in self.vocabulary:
            for i in range(len(word)):
                self.deletions[word[:i]+word[i+1:]].add(word)
        # Current event cells are whole cells, never alternatives.
        assert all('|' not in row.get('event', '') for rows in self.tables.values() for row in rows)

    @functools.lru_cache(maxsize=50000)
    def matched_words(self, query):
        if self.mode != 'separate':
            return {query} & self.vocabulary
        candidates = {query} | self.deletions.get(query, set())
        for i in range(len(query)):
            deleted = query[:i]+query[i+1:]
            candidates.add(deleted)
            candidates.update(self.deletions.get(deleted, set()))
        for i in range(len(query)-1):
            candidates.add(query[:i]+query[i+1]+query[i]+query[i+2:])
        return {w for w in candidates & self.vocabulary if self.module.word_present(w, {query})}

    @functools.lru_cache(maxsize=160)
    def ranks(self, name, field, query):
        row_ids, tokens, grams, posts, exact_index = self.columns[name, field]
        intersections = np.zeros((2, len(row_ids)))
        query_words = set(query.split())
        for kind, words in enumerate((query_words, self.module.char_ngrams(query))):
            for word in words:
                indices = posts[kind].get(word)
                if indices is not None:
                    intersections[kind, indices] += 1
        fuzzy = intersections[0].copy()
        if self.mode == 'separate':
            fuzzy[:] = 0
            for word in set().union(*(self.matched_words(q) for q in query_words)):
                indices = posts[0].get(word)
                if indices is not None:
                    fuzzy[indices] += 1
        scores = .7*fuzzy/np.maximum(tokens, 1) + .3*intersections[1]/np.maximum(grams, 1)
        exact = np.zeros(len(row_ids), dtype=bool)
        if query:
            exact[exact_index.get(query, [])] = True
            scores[exact] = 1.0
        denominator = len(query_words)+tokens
        complete = np.divide(2*intersections[0], denominator, out=np.zeros(len(row_ids)), where=denominator != 0)
        size = len(self.tables[name])
        row_score, row_exact, row_complete = np.zeros(size), np.zeros(size, dtype=bool), np.zeros(size)
        np.maximum.at(row_score, row_ids, scores)
        np.logical_or.at(row_exact, row_ids, exact)
        np.maximum.at(row_complete, row_ids, np.where(scores == row_score[row_ids], complete, 0))
        return row_exact, row_score, row_complete

    @functools.lru_cache(maxsize=60000)
    def result(self, name, args):
        field = 'event' if name == 'event_time' else 'entity'
        first = self.ranks(name, field, self.module.normalize_entity(args[0]))
        exact, score, complete = first
        eligible = score >= .75
        event = None
        if family(name) == 'chronological':
            event = self.ranks(name, 'event', self.module.normalize_entity(args[1]))
            exact = exact & event[0]
            score = .6*score + .4*event[1]
            complete = .6*complete + .4*event[2]
            eligible = score >= .75 if self.mode == 'main' else eligible & (event[1] >= .75)
        if name in self.times:
            normalizer = self.module.normalize_time_key if 'absolute' in name else self.module.normalize_time
            try:
                time = normalizer(args[1])
            except ValueError as exc:
                return dict(error=str(exc), reason='time parse')
            eligible &= np.array([self.module.time_keys_match(time, t) if 'absolute' in name else
                time[0] == t[0] and (time[1] is None or t[1] is None or time[1] == t[1]) for t in self.times[name]])
        indices = np.flatnonzero(eligible)
        if not len(indices):
            return dict(error=harness.audit.ERROR_MESSAGES[name], reason='score or time constraint')
        i = max(indices, key=lambda i: (exact[i], score[i], complete[i], -i))
        result = dict(answer=self.tables[name][i]['answer'], row=int(i), score=float(score[i]))
        result[field+'_score'] = float(first[1][i])
        if event is not None:
            result['event_score'] = float(event[1][i])
        return result

    def row_scores(self, name, args, row):
        m = self.module
        first = m.event_match_rank(m.normalize_entity(args[0]), row['event']) if name == 'event_time' else m.lexical_match_rank(m.normalize_entity(args[0]), row['entity'])
        result = {('event_score' if name == 'event_time' else 'entity_score'):first[1]}
        if family(name) == 'chronological':
            event = m.event_match_rank(m.normalize_entity(args[1]), row['event'])
            result.update(event_score=event[1], combined_score=.6*first[1]+.4*event[1])
        return result

def passes(result, gold):
    return 'answer' in result and harness.audit.normalize_answer(result['answer']) == harness.audit.normalize_answer(gold)

def compare(tools, item, args=None):
    args = tuple(item['arguments'] if args is None else args)
    r = dict(item, arguments=args)
    for mode, t in tools.items():
        r[mode] = t.result(item['tool'], args)
        r[mode+'_gold'] = passes(r[mode], item.get('gold'))
    return r

def stats(records, weighted=False):
    s = collections.Counter()
    for r in records:
        n = r.get('count', 1) if weighted else 1
        s['calls'] += n
        for mode in MODES:
            s[mode+'_answers'] += n*('answer' in r[mode])
            s[mode+'_gold'] += n*r[mode+'_gold']
        for mode in MODES[1:]:
            s[mode+'_new_errors'] += n*('answer' in r['main'] and 'answer' not in r[mode])
            s[mode+'_changed_answers'] += n*('answer' in r['main'] and 'answer' in r[mode] and r['main']['answer'] != r[mode]['answer'])
            s[mode+'_lost_gold'] += n*(r['main_gold'] and not r[mode+'_gold'])
            s[mode+'_gained_gold'] += n*(not r['main_gold'] and r[mode+'_gold'])
    return dict(s)

def split_stats(records, weighted=False):
    return {'all':stats(records, weighted), **{f:stats([r for r in records if family(r['tool']) == f], weighted) for f in ('chronological','absolute/entity_time','event_time')}}

def diagnostics(tools, r):
    if 'row' not in r['main']:
        return r
    row = tools['main'].tables[r['tool']][r['main']['row']]
    r['main_winner'] = dict(csv_line=r['main']['row']+2, **row)
    r['scores_against_main_winner'] = {mode:t.row_scores(r['tool'],r['arguments'],row) for mode,t in tools.items()}
    fields = [('event' if r['tool'] == 'event_time' else 'entity',r['arguments'][0])]
    if family(r['tool']) == 'chronological':
        fields.append(('event',r['arguments'][1]))
    r['missing_exact_words'] = {f: min((sorted(set(tools['main'].module.normalize_entity(alt).split())-set(tools['main'].module.normalize_entity(q).split())) for alt in row[f].split('|')),key=len) for f,q in fields}
    failed = [f for f,_ in fields if r['scores_against_main_winner']['separate'][f+'_score'] < .75]
    if 'entity' in failed and 'event' in failed:
        cause = 'entity and event below 0.75'
    elif failed:
        cause = failed[0]+' below 0.75'
    else:
        cause = 'different ranking winner'
    r['cause'] = cause
    r['causes_by_mode'] = {}
    for mode in MODES[1:]:
        failed_mode = [f for f,_ in fields if r['scores_against_main_winner'][mode][f+'_score'] < .75]
        r['causes_by_mode'][mode] = 'entity and event below 0.75' if len(failed_mode)==2 else failed_mode[0]+' below 0.75' if failed_mode else 'different ranking winner'
    missing = set(w for f in failed for w in r['missing_exact_words'][f])
    r['detail'] = ('missing role words' if missing & {'head','coach','chair','owner','president','ceo','duke','chief','director'} else
                   'numeric/ordinal difference' if any(tools['separate'].module.is_number_word(w) for w in missing) else
                   'lexical extraction difference')
    return r

def canonical(tools):
    live.g.OUT = OUT
    corpus = live.active_corpus(tools['main'])
    # Choose a single approved alternative appearing in the question/reference.
    refs = harness.references()
    for item in corpus:
        if item['tool'] == 'event_time':
            continue
        choices = item['arguments'][0].split('|')
        texts = [item['question']]
        if item['dt'] == 'tempreason':
            index = int(item['id'].split(':')[1].split('_')[0])
            texts += sorted(refs[index])
        options = [c.strip() for c in choices if any(tools['main'].module.normalize_entity(c) in tools['main'].module.normalize_entity(q) for q in texts)]
        item['arguments'] = (options[0] if options else choices[0].strip(), *item['arguments'][1:])
    return [compare(tools,r) for r in corpus]

def parquet_coverage(corpus):
    by_id = {r['id']:r for r in corpus}
    by_question = collections.defaultdict(list)
    for r in corpus:
        by_question[r['question']].append(r)
    physical = collections.Counter()
    unmatched = []
    appearances = collections.defaultdict(list)
    refreshed = []
    for relative in noise.PARQUETS:
        rows = pq.read_table(ROOT/relative, columns=['data_source','group_id','prompt','extra_info','reward_model']).to_pylist()
        c = collections.Counter(total=len(rows))
        for row in rows:
            extra = row['extra_info']
            dt = extra['datatype']
            if dt not in ('temp-cofac','temprecon','tempreason') or extra.get('level') == 'l1':
                c['no_single_lookup'] += 1
                continue
            ident = f"{'val' if '-test-' in relative else 'train'}:{extra['group_id']}_{extra['variant']}"
            question = noise.extract_prompt_question(row['prompt'][0]['content'])
            question = re.split(r'give your single final answer in the <answer> block\s*after it\.\s*', question)[-1].strip()
            gold = extra.get('english_answer') or row['reward_model']['ground_truth']
            candidates = [by_id[ident]] if ident in by_id and by_id[ident]['question'] == question else by_question.get(question, [])
            candidates = [r for r in candidates if harness.audit.normalize_answer(r['gold']) == harness.audit.normalize_answer(gold)]
            if not candidates and dt == 'tempreason' and ident in by_id and harness.audit.normalize_answer(by_id[ident]['gold']) == harness.audit.normalize_answer(gold):
                # Three v4 surfaces predate the last minimal translation repairs.
                # Their stable ID, unchanged English gold and retained English
                # reference supply exactly the same canonical extraction.
                candidates = [by_id[ident]]
                refreshed.append(dict(file=relative,id=ident,parquet_question=question,current_question=candidates[0]['question'],arguments=candidates[0]['arguments'],gold=gold))
            if not candidates:
                unmatched.append(dict(file=relative,id=ident,question=question,gold=gold)); continue
            r = candidates[0]
            c['bound_lookup'] += 1
            for mode in MODES:
                c[mode+'_gold'] += r[mode+'_gold']
                c[mode+'_new_errors'] += 'answer' in r['main'] and 'answer' not in r[mode]
            appearances[r['id']].append(dict(file=relative,id=ident))
        physical[relative] = dict(c)
    dump('parquet_coverage.json', dict(files=dict(physical), unmatched=unmatched, refreshed_translation_surfaces=refreshed, appearances=dict(appearances)))
    assert not unmatched, ('unbound live parquet questions', unmatched[:5],len(unmatched))
    return dict(physical)

def wrong_probes(tools, corpus):
    sample_ids = set(json.loads((ROOT/'analysis/gate_measure/wrong_probes.json').read_text())['sample_ids'])
    sample = [r for r in corpus if r['id'] in sample_ids]
    records = []
    for item in sample:
        args = item['arguments']
        probes = [('assistant addition', ('assistant '+args[0],*args[1:])),
                  ('different addition', ('different '+args[0],*args[1:]))]
        if family(item['tool']) == 'chronological':
            probes.append(('negated event',(args[0],'not '+args[1])))
        for kind,values in probes:
            records.append(compare(tools,dict(item,kind=kind),values))
    # Deliberate substitutions, not just additions; fixed seed and current keys.
    rng = random.Random(1009)
    for item in rng.sample(corpus,min(500,len(corpus))):
        args = item['arguments']
        others = [r for r in corpus if r['tool']==item['tool'] and r['arguments'][0]!=args[0]]
        other = rng.choice(others)
        records.append(compare(tools,dict(item,kind='different entity'),(other['arguments'][0],*args[1:])))
        roleless = re.sub(r'^(?:head coach|chair|owner|president|CEO|duke|head) of (?:the )?(?:team |country )?', '', args[0], flags=re.I)
        if roleless != args[0]:
            records.append(compare(tools,dict(item,kind='role-less'),(roleless,*args[1:])))
    cases = [
        ('wrong company','before_chronological_reference',('CEO of Apple','Virginia M. (Ginni) Rometty'),'Samuel J Palmisano'),
        ('wrong role','after_chronological_reference',('assistant coach of the team HNK Rijeka','Simon Rožman'),'Goran Tomić'),
        ('role-less HNK','after_chronological_reference',('HNK Rijeka','Simon Rožman'),'Goran Tomić'),
        ('untranslated event French','before_chronological_reference',('John Grisham',"L’Affaire Pélican"),'The Firm'),
        ('untranslated event German','before_chronological_reference',('John Grisham','Die Akte'),'The Firm'),
        ('negated event','before_chronological_reference',('John Grisham','not The Pelican Brief'),'The Firm'),
        ('competing owners','after_chronological_reference',('Google | Apple','Mac OS 10.6 Snow Leopard'),'10.7 Lion'),
        ('assistant full role','after_chronological_reference',('assistant head coach of the team HNK Rijeka','Simon Rožman'),'Goran Tomić'),
    ]
    explicit = [diagnostics(tools,compare(tools,dict(id=kind,kind=kind,tool=name,arguments=args,gold=gold))) for kind,name,args,gold in cases]
    records += explicit
    dump('explicit_probes.json',explicit)
    dump('wrong_probes.json',records)
    return {k:split_stats([r for r in records if r['kind']==k]) for k in sorted({r['kind'] for r in records})}

def distinct_probes(tools):
    records,seen=[],set()
    for line in (ROOT/'analysis/typo_check/judgments.jsonl').read_text().splitlines():
        source=json.loads(line)
        if source.get('judgment')!='DIFFERENT' or not source.get('spelling_a'):
            continue
        a,b=source['spelling_a'],source['spelling_b']
        norm=tools['main'].module.normalize_entity
        for name,rows in tools['main'].tables.items():
            if family(name)!='chronological': continue
            for i,row in enumerate(rows):
                if norm(row['event']) not in (norm(a),norm(b)): continue
                wrong=b if norm(row['event'])==norm(a) else a
                key=name,i,norm(wrong)
                if key in seen: continue
                seen.add(key)
                item=dict(id=f'{name}:{i+2}',tool=name,arguments=(row['entity'].split('|')[0].strip(),wrong),gold=row['answer'],kind='source-reviewed distinct event',source_candidate=source['candidate_id'],original_event=row['event'])
                records.append(diagnostics(tools,compare(tools,item)))
    dump('distinct_event_probes.json',records)
    return split_stats(records)

def surface(tools, corpus):
    summaries, failures = {}, []
    for kind in ('lowercase','drop accents','drop the','add the','F.C. / FC','one character typo','singular/plural'):
        records = []
        for item in corpus:
            args, changed = g.noise_args(item,kind)
            if changed:
                r=compare(tools,dict(item,kind=kind),args)
                records.append(r)
                if any(not r[mode+'_gold'] for mode in MODES):
                    failures.append(diagnostics(tools,r))
        summaries[kind]=split_stats(records)
        print('Surface',kind,summaries[kind]['all'],flush=True)
    dump('surface_failures.json',failures)
    return summaries

def parse_logs(t):
    fields = {n:['event'] if n=='event_time' else ['entity','event' if family(n)=='chronological' else 'time'] for n in t.tables}
    pattern=re.compile(r'<tool_call>\s*(.*?)\s*</tool_call>',re.S)
    decoder=json.JSONDecoder()
    paths=sorted((ROOT/'rollouts').rglob('*.jsonl'))+[ROOT/'toolbox/rollouts.jsonl']
    search=subprocess.run(['rg','-l','<tool_call>',str(ROOT/'analysis'),'-g','*.jsonl','-g','!**/backup*/**','-g','!**/container-context/**','-g','!**/staged/**','-g','!**/gate_measure/**','-g','!**/role_entities/**','-g','!**/separate_bars/**','-g','!**/cache/**','-g','!**/mock/**'],text=True,capture_output=True)
    assert search.returncode in (0,1),search.stderr
    paths += [Path(p) for p in search.stdout.splitlines()]
    grouped, inventory={},[]
    for path in dict.fromkeys(paths):
        if not path.exists():
            continue
        counts=collections.Counter()
        def documents():
            if path==ROOT/'toolbox/rollouts.jsonl':
                text=path.read_text(); offset=0
                while offset<len(text):
                    start=re.search(r'\S',text[offset:])
                    if start is None: break
                    offset+=start.start(); obj,end=decoder.raw_decode(text,offset)
                    yield text.count('\n',0,offset)+1,obj
                    offset=end
            else:
                with path.open() as stream:
                    for line_no,line in enumerate(stream,1):
                        try: yield line_no,json.loads(line)
                        except ValueError: counts['invalid_record_json']+=1
        for line_no,row in documents():
            if not isinstance(row,dict): continue
            output=row.get('output','')
            if not isinstance(output,str): output=json.dumps(output)
            for match in pattern.finditer(output):
                try:
                    call=decoder.raw_decode(match[1].strip())[0]
                    call=call.get('function',call)
                    name,args=call.get('name'),call.get('arguments',{})
                    if name not in fields: continue
                    counts['temporal_calls']+=1
                    if isinstance(args,str): args=json.loads(args)
                    if not isinstance(args,dict) or set(args)!=set(fields[name]) or any(not isinstance(args[f],str) for f in fields[name]):
                        counts['invalid_temporal_arguments']+=1; continue
                    args=tuple(args[f] for f in fields[name])
                except (ValueError,AttributeError,KeyError,TypeError):
                    counts['invalid_call_json']+=1; continue
                gold=row.get('english_answer') or row.get('gts') or row.get('ground_truth')
                cohort='current' if path.is_relative_to(ROOT/'rollouts/current') else 'other'
                key=(name,args,str(gold),row.get('group_id'),row.get('variant'),cohort)
                item=grouped.setdefault(key,dict(tool=name,arguments=args,gold=gold,group_id=row.get('group_id'),variant=row.get('variant'),cohort=cohort,count=0,evidence=dict(file=str(path.relative_to(ROOT)),line=line_no)))
                item['count']+=1
        inventory.append(dict(file=str(path.relative_to(ROOT)),sha256=sha(path),**dict(counts)))
        if counts: print('Parsed',path.relative_to(ROOT),dict(counts),flush=True)
    dump('log_inventory.json',inventory)
    return list(grouped.values())

def real_calls(tools):
    groups=parse_logs(tools['main'])
    records=[]; regressions=[]
    for item in groups:
        r=compare(tools,item)
        records.append(r)
        if 'answer' in r['main'] and any(r['main'].get('answer')!=r[mode].get('answer') for mode in MODES[1:]):
            regressions.append(diagnostics(tools,r))
    dump('real_call_regressions.json',regressions)
    dump('real_calls.json',records)
    result=dict(unique_groups=len(groups),**split_stats(records,True),tools={n:stats([r for r in records if r['tool']==n],True) for n in tools['main'].tables},cohorts={c:split_stats([r for r in records if r['cohort']==c],True) for c in ('current','other')})
    causes=collections.defaultdict(collections.Counter)
    for r in regressions:
        for mode in MODES[1:]:
            if 'answer' not in r[mode]:
                causes[mode][r['causes_by_mode'][mode]+'; '+r['detail']]+=r['count']
    result['causes']={k:dict(v) for k,v in causes.items()}
    dump('real_call_summary.json',result)
    return result

def validate(tools):
    comparisons=0
    for mode,t in tools.items():
        rng=random.Random(10413)
        for name,rows in t.tables.items():
            for i in rng.sample(range(len(rows)),8):
                row=rows[i]
                args=harness.audit.arguments(name,row)
                if name!='event_time': args=(args[0].split('|')[0].strip(),*args[1:])
                for kind in (None,'one character typo','singular/plural'):
                    if kind: values,_=g.noise_args(dict(tool=name,arguments=args),kind)
                    else: values=args
                    expected=t.result(name,tuple(values))
                    try: actual=dict(answer=getattr(t.module,name)(*values))
                    except (LookupError,ValueError) as exc: actual=dict(error=str(exc))
                    assert actual.get('answer')==expected.get('answer'),(mode,name,values,actual,expected)
                    comparisons+=1
        # Validate rank vectors independently against production row scoring.
        for name,rows in t.tables.items():
            fields=['event'] if name=='event_time' else ['entity','event'] if family(name)=='chronological' else ['entity']
            for field in fields:
                for query in ('John Grishm','The Pelican Brif','Grihsam','Member of the 15th Parliament','president of america','latvia'):
                    query=t.module.normalize_entity(query)
                    ranks=t.ranks(name,field,query)
                    for i in rng.sample(range(len(rows)),20):
                        rank=(t.module.lexical_match_rank if field=='entity' else t.module.event_match_rank)(query,rows[i][field])
                        assert np.allclose(rank,[v[i] for v in ranks]),(mode,name,field,query,i,rank)
    return dict(real_function_comparisons=comparisons,rank_vectors_checked=True)

def table(lines,headers,rows):
    def cell(v): return str(v).replace('|','\\|').replace('\n',' ')
    lines += ['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']
    lines += ['| '+' | '.join(cell(v) for v in row)+' |' for row in rows]
    lines.append('')

def report(summary):
    lines=['VERDICT: Separate bars and spelling tolerance implemented and measured; the plan’s numeric no-match test conflicts with its unchanged score formula and remains an expected failure.','',
        'Baseline: main 281114b. Separate = independent entity/event thresholds plus one-edit word containment. No typo = identical separate thresholds with exact word containment. All three use the same six serving CSVs. Scores, exact priority, completeness and date handling retain their existing formulas.','']
    lines += ['## Findings against owner intent','',
        '**HIGH — the numeric “never matches” requirement is unmet.** Against a stored `Member of the 14th Parliament`, a `Member of the 15th Parliament` query scores 0.82667 for event and 0.93067 combined (entity exact). The numeric token does not count as present, but the remaining words and unchanged trigrams still pass. This violates the requested numeric test and intent rule 4. An explicit numeric-mismatch rejection would enforce it, but would add a new constraint beyond “everything else unchanged.” No reply to the clarification arrived during implementation; the specified formula was preserved. The test is recorded as an expected failure, not silently removed. No numeric rejection was added.','',
        '**HIGH — wrong-role and semantic-addition lookups remain accepted.** Assistant-coach HNK scores 0.86129 for entity, above the separate bar. Negated events, assistant/different prefixes and competing-owner queries still contain the stored key. This remains a rule-4 limitation of the requested formula; the explicit probes and frozen-sample counts below show its extent. A further semantic or token-completeness constraint would need a separate decision.','',
        '**MEDIUM — surface noise can lose existing matches.** Dropping “the” loses 365 gold matches; adding it loses 67; plural s loses 1,510 while gaining 4,284. Example: `John Grisham / Rainmaker` against `The Rainmaker` scores 0.54091 for event, so now fails. `heads of Chicago` scores 0.72051 against `head of Chicago`; a four-letter stored word receives no spelling tolerance. These are measured tradeoffs, not changes to normalization.','',
        '**MEDIUM — complete app-suite verification is blocked by missing dependencies.** All 25 ordinary temporal tests pass and the numeric requirement is one expected failure. Full discovery ran 77 tests: 58 passed, 16 platform skips, three import errors for missing fastapi/deep_translator. Installing repository requirements in a temporary environment was blocked by filesystem permissions; it was stopped under AGENTS.md. Offline replay validation is complete.','']
    lines += ['**MEDIUM — one-edit tolerance also accepts close distinct people.** The prior source review classifies `Nicolae Nedelcu` and `Nicolaie Nedelcu` as distinct. Query `head of Ziduri / Nicolae Nedelcu` matches the `Nicolaie Nedelcu` event row at before_chronological_reference.csv:4761 with event score 0.93571; no-typo separate bars reject it. Main already accepted it at event score 0.58571 through the combined bar. Thus the spelling allowance retains this wrong lookup that separate bars alone would remove. The probe is in distinct_event_probes.json. Spelling distance cannot distinguish such identities; this is a limitation of the requested allowance.','',
        '**LOW — lookup work increases.** A five-call local smoke benchmark of John Grisham / The Pelican Brief measured median 0.174 seconds on main and 0.299 seconds on the branch, both returning The Firm. This is an illustrative local timing, not a production latency estimate; the extra word comparisons account for the added work. Raw timings are in timing.json.','']
    lines += ['## Canonical correct arguments','']
    table(lines,['Corpus/family','Calls','Main gold','Separate gold','No typo gold','Separate lost gold','No typo lost gold'],[(label+'/'+f,s['calls'],s['main_gold'],s['separate_gold'],s['separate_no_typo_gold'],s['separate_lost_gold'],s['separate_no_typo_lost_gold']) for label,groups in [('live questions',summary['canonical']),('all table rows',summary['serving'])] for f,s in groups.items() if s.get('calls')])
    lines += ['Every single-lookup question in all nine live tools parquets was bound to the fresh v6 logical corpus, with trimmed question text and gold checked. Two translated questions contain trailing whitespace in v6 JSONL; their nine physical appearances bind by stable ID and identical English gold, recorded in parquet_coverage.json. No stale translation content was found. Arithmetic, ordering and multi-step L1 questions are outside a single canonical lookup; every event_time table row is separately covered. Multilingual canonical arguments use retained English reference/table strings, as in the prior harness; this does not test translation or extraction. Each entity argument is one approved alternative present in the question/reference where available; this avoids treating an entire pipe cell as model extraction.','']
    lines += ['Across 177,580 physical parquet rows, all 90,090 single-lookup appearances are covered. All six table-row controls retain their outcomes; nine existing serving-row gold failures remain (overlapping keys/duplicate answers), and the two live-question failures are the owner-held PRC cases below.','']
    failures=json.loads((OUT/'canonical_new_failures.json').read_text())
    lines += ['### Every newly failing live question','']
    if not failures: lines += ['None in either branch mode.','']
    else:
        table(lines,['ID','Question','Arguments','Gold','Main','Separate','No typo','Scores against main row','Why'],[(r['id'],r['question'],r['arguments'],r['gold'],r['main'],r['separate'],r['separate_no_typo'],r['scores_against_main_winner'],r['cause']) for r in failures])
    lines += ['### Existing canonical failures','']
    existing=json.loads((OUT/'canonical_existing_failures.json').read_text())
    table(lines,['ID','Arguments','Gold','Main result','Separate result'],[(r['id'],r['arguments'],r['gold'],r['main'],r['separate']) for r in existing])
    lines += ['## Wrong extraction probes','']
    table(lines,['Probe kind','Calls','Main answers','Separate answers','No typo answers','New errors separate','New errors no typo'],[(k,s['all']['calls'],s['all']['main_answers'],s['all']['separate_answers'],s['all']['separate_no_typo_answers'],s['all']['separate_new_errors'],s['all']['separate_no_typo_new_errors']) for k,s in summary['wrong'].items()])
    lines += ['The original reviewer sample IDs are reused for assistant/different additions and negated events, refreshed to current full-role keys. Different-entity substitutions and role omissions use a fixed 500-question sample (seed 1009). Returning an answer to a deliberate substitution may be a valid answer for the substituted timeline: newly blocked counts are rejection rates, while gold counts in JSON track leakage to the original question. The literal semantic additions still contain the full stored text and remain a limitation of directional containment.','']
    d=summary['distinct']['all']
    lines += [f"Additional source-reviewed close but distinct event probes: {d['calls']} deduplicated calls, main answers {d['main_answers']}, separate answers {d['separate_answers']}, no-typo answers {d['separate_no_typo_answers']}; separate newly blocks {d['separate_new_errors']}, no-typo newly blocks {d['separate_no_typo_new_errors']}. Sources are the DIFFERENT judgments from the completed typo audit; exact names, source candidate IDs, arguments and scores are in distinct_event_probes.json. A distinct event can legitimately reach its own table row; the counts describe rejection, not semantic correctness.",'']
    explicit=json.loads((OUT/'explicit_probes.json').read_text())
    table(lines,['Probe','Arguments','Main','Separate','No typo','Scores against main winner'],[(r['kind'],r['arguments'],r['main'].get('answer','ERROR'),r['separate'].get('answer','ERROR'),r['separate_no_typo'].get('answer','ERROR'),r.get('scores_against_main_winner')) for r in explicit])
    lines += ['## Surface noise','']
    table(lines,['Noise','Calls','Main gold/pass rate','Separate gold/pass rate','No typo gold/pass rate','Separate lost gold'],[(k,s['all']['calls'],rate(s['all'],'main'),rate(s['all'],'separate'),rate(s['all'],'separate_no_typo'),s['all']['separate_lost_gold']) for k,s in summary['surface'].items()])
    lines += ['Only changed variants count. Dates stay fixed. Lowercase, accent removal, adding/removing the, and F.C./FC reuse the previous harness. Typos replace the middle character of the first eligible word with length ≥5; plural s toggles the first eligible word with length ≥4. One word changes per call. No extra plural rule was added; ≥5-character stored words benefit from insertion/deletion tolerance. All failing variants and scores are in surface_failures.json.','']
    lines += ['## Real past model calls','']
    real=summary['real']
    lines += [f"Separate bars create {real['all']['separate_new_errors']:,} errors out of {real['all']['main_answers']:,} currently answering calls ({100*real['all']['separate_new_errors']/real['all']['main_answers']:.2f}%). Every new error is chronological ({100*real['all']['separate_new_errors']/real['chronological']['main_answers']:.2f}% of existing chronological answers). Spelling tolerance preserves 287 calls that the no-typo branch rejects and gains 574 answers over main; no still-answering call changes its answer.",'']
    lines += ['The rollouts/current cohort contributes 3,394 new errors; older/other logs contribute 188. Without spelling tolerance those counts are 3,670 and 199. Chronological gains are 241, time-filtered entity-tool gains 330, and event_time gains three; these offset some new errors in the total answers column.','']
    table(lines,['Family','Calls','Main answers','Separate answers','No typo answers','Separate new errors','No typo new errors','Separate changed answers','Separate lost historical gold'],[(f,s['calls'],s['main_answers'],s['separate_answers'],s['separate_no_typo_answers'],s['separate_new_errors'],s['separate_no_typo_new_errors'],s['separate_changed_answers'],s['separate_lost_gold']) for f,s in real.items() if f in ('all','chronological','absolute/entity_time','event_time') and s.get('calls')])
    table(lines,['Mode','Cause against main winner','Occurrences'],[(mode,c,n) for mode,cs in real['causes'].items() for c,n in sorted(cs.items(),key=lambda kv:-kv[1])])
    regressions=json.loads((OUT/'real_call_regressions.json').read_text())
    lines += ['### Top currently answering calls that become errors','']
    for mode in MODES[1:]:
        lines += [mode,'']
        top=sorted([r for r in regressions if 'answer' not in r[mode]],key=lambda r:-r['count'])[:12]
        table(lines,['Tool','Arguments','Occurrences','Current answer','Scores against current row','Cause','First evidence'],[(r['tool'],r['arguments'],r['count'],r['main']['answer'],r['scores_against_main_winner'][mode],r.get('causes_by_mode',{}).get(mode,r['cause'])+'; '+r['detail'],r['evidence']) for r in top])
    lines += [f"Parsed {real['unique_groups']:,} distinct tool/argument/historical-gold/cohort groups, retaining occurrence weights. Only output tool_call blocks are read; prompt examples and code are never executed. All local rollouts/current and deprecated files, toolbox/rollouts.jsonl and analysis call logs use the prior harness's exclusions plus this report directory. Current and other cohorts, every tool, and all failures are in JSON. Historical gold may differ from today's gold; event_time historical-gold counts compare an intermediate date to a final task answer and are diagnostic only. Failures include bad extraction and localized names; they are not all legitimate regressions.",'',
        '## Verification and scope','',f"{summary['validation']['real_function_comparisons']} replay comparisons against the actual CSV-reading lookup functions passed, across six tools and all three modes, plus independent rank-vector checks. Input and rollout SHA-256 hashes are recorded and checked after measurement.",'',
        'Existing test changed: tests_temporal_alternatives.EntityAlternativeTests.test_event_punctuation_has_original_score_and_eligibility (renamed test_event_punctuation_score_and_separate_eligibility): chronological eligibility now uses the event score ≥0.75 rather than 0.6 + 0.4 × event. No existing priority test was changed. Focused tests cover wrong company, role-less HNK, John Grishm, Pelican Brif, Rajshee/Rajshree, alternatives, all tools, edit operations, numeric exclusions, unchanged trigrams/completeness and dates.','',
        'No CSVs, datasets, translation cache or service state were changed. Run from the workspace root: `.venv/bin/python -B -u analysis/separate_bars/measure.py`. Code, tests and a report snapshot are committed only in toolbox on separate-bars; main stays at 281114b.','']
    lines += ['Blocked commands: `/private/tmp/temporal-separate-bars-venv/bin/python -m pip install --no-cache-dir -r toolbox/requirements.txt` failed with Operation not permitted creating `/var/folders/52/hw_1b9nd5qjd_f9bzb76kyb00000gp/T/tmp12q3op_9`; `/private/tmp/temporal-separate-bars-venv/bin/python3.13 -m ensurepip --upgrade --default-pip` also exited 1 during environment creation. No retry/workaround was attempted. `ps -Ao pid,etime,%cpu,command` was denied by the sandbox. None of these failures blocked offline measurements.','']
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    (ROOT/'handoffs/reports/separate_bars.md').write_text('\n'.join(lines))

def rate(s,mode):
    return f"{s[mode+'_gold']} / {100*s[mode+'_gold']/s['calls']:.2f}%" if s['calls'] else 'n/a'

def main():
    paths=[OUT/'main_temporal.py',ROOT/'toolbox/app/tools/temporal.py',Path(__file__)]+list((ROOT/'toolbox/app/tools').glob('*.csv'))+[ROOT/p for p in noise.PARQUETS]+list((ROOT/'v6').glob('*.jsonl'))+[ROOT/'analysis/fix_5_9/corpus.json',ROOT/'analysis/role_entities/active_canonical_calls.json',ROOT/'analysis/gate_measure/wrong_probes.json',ROOT/'analysis/fix_5_9/verify.py',ROOT/'analysis/gate_measure/measure.py',ROOT/'analysis/gate_measure/remeasure_datafix10/remeasure.py',ROOT/'analysis/typo_check/find.py']
    manifest={str(p.relative_to(ROOT)):sha(p) for p in paths}
    tools={mode:Replay(mode) for mode in MODES}
    validation=validate(tools)
    print('Validation',validation,flush=True)
    corpus=canonical(tools)
    dump('canonical_calls.json',corpus)
    dump('canonical_new_failures.json',[diagnostics(tools,r) for r in corpus if r['main_gold'] and any(not r[m+'_gold'] for m in MODES[1:])])
    dump('canonical_existing_failures.json',[diagnostics(tools,r) for r in corpus if not r['main_gold']])
    coverage=parquet_coverage(corpus)
    serving=[compare(tools,dict(id=f'{n}:{i+2}',tool=n,arguments=harness.audit.arguments(n,row),gold=row['answer'])) for n,rows in tools['main'].tables.items() for i,row in enumerate(rows)]
    dump('serving_calls.json',serving)
    dump('serving_new_failures.json',[diagnostics(tools,r) for r in serving if r['main_gold'] and any(not r[m+'_gold'] for m in MODES[1:])])
    summary=dict(base_commit='281114b',branch='separate-bars',validation=validation,canonical=split_stats(corpus),serving=split_stats(serving),parquet_coverage=coverage)
    print('Canonical',summary['canonical'],flush=True)
    manifest['analysis/typo_check/judgments.jsonl']=sha(ROOT/'analysis/typo_check/judgments.jsonl')
    summary['wrong']=wrong_probes(tools,corpus)
    summary['distinct']=distinct_probes(tools)
    summary['surface']=surface(tools,corpus)
    summary['real']=real_calls(tools)
    inventory=json.loads((OUT/'log_inventory.json').read_text())
    manifest.update({r['file']:r['sha256'] for r in inventory})
    assert all(sha(ROOT/p)==h for p,h in manifest.items()),'Inputs changed during measurement'
    dump('manifest.json',manifest)
    dump('summary.json',summary)
    report(summary)
    print('COMPLETE',json.dumps(summary['real']['all']),flush=True)

if __name__=='__main__':
    main()
