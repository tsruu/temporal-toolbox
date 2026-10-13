#!/usr/bin/env python3
"""Round-2 four-way offline replay; no services or logged code execution."""
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
MODES = ('main', 'bar_075', 'bar_070', 'bar_065')
BARS = dict(bar_075=.75, bar_070=.70, bar_065=.65)

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
        self.mode = mode
        self.bar = BARS.get(mode, .75)
        self.module = module('temporal_'+mode, OUT/'main_temporal.py' if mode == 'main' else ROOT/'toolbox/app/tools/temporal.py')
        self.module.COMPONENT_BAR = self.bar
        self.priority = True
        self.tables, self.text, self.columns, self.times = {}, {}, {}, {}
        self.number_sets = {}
        for name in harness.audit.TABLES:
            path = ROOT / f'toolbox/app/tools/{name}.csv'
            getattr(self.module, name).__defaults__ = (str(path),)
            self.text[name] = path.read_text()
            self.tables[name] = list(csv.DictReader(io.StringIO(self.text[name])))
            fields = ['event'] if name == 'event_time' else ['entity']
            if family(name) == 'chronological': fields.append('event')
            for field in fields:
                keys, row_ids = [], []
                for i, row in enumerate(self.tables[name]):
                    alternatives = row[field].split('|') if field == 'entity' or mode != 'main' else [row[field]]
                    for alternative in alternatives:
                        keys.append(self.module.normalize_entity(alternative))
                        row_ids.append(i)
                tokens, grams = [], []
                posts = [collections.defaultdict(list), collections.defaultdict(list)]
                exact = collections.defaultdict(list)
                for i, key in enumerate(keys):
                    parts = (set(key.split()), self.module.char_ngrams(key))
                    tokens.append(len(parts[0])); grams.append(len(parts[1]))
                    for kind, words in enumerate(parts):
                        for word in words: posts[kind][word].append(i)
                    exact[key].append(i)
                self.columns[name, field] = (np.array(row_ids), np.array(tokens), np.array(grams),
                    [{k:np.array(v) for k,v in p.items()} for p in posts], exact)
                if mode != 'main':
                    sets = collections.defaultdict(list)
                    for i, key in enumerate(keys):
                        sets[frozenset(w for w in key.split() if self.module.is_number_word(w))].append(i)
                    self.number_sets[name, field] = {k:np.array(v) for k,v in sets.items()}
            if 'time' in self.tables[name][0]:
                normalizer = self.module.normalize_time_key if 'absolute' in name else self.module.normalize_time
                self.times[name] = [normalizer(row['time']) for row in self.tables[name]]
        self.vocabulary = {word for _, _, _, posts, _ in self.columns.values() for word in posts[0]}
        self.deletions = collections.defaultdict(set)
        for word in self.vocabulary:
            for i in range(len(word)):
                self.deletions[word[:i]+word[i+1:]].add(word)
        # Current event cells are whole cells, never alternatives.
        assert all('|' not in row.get('event', '') for rows in self.tables.values() for row in rows)

    @functools.lru_cache(maxsize=50000)
    def matched_words(self, query):
        if self.mode == 'main':
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
        if self.mode != 'main':
            fuzzy[:] = 0
            for word in set().union(*(self.matched_words(q) for q in query_words)):
                indices = posts[0].get(word)
                if indices is not None:
                    fuzzy[indices] += 1
        scores = .7*fuzzy/np.maximum(tokens, 1) + .3*intersections[1]/np.maximum(grams, 1)
        if self.mode != 'main':
            numbers = frozenset(w for w in query_words if self.module.is_number_word(w))
            mask = np.zeros(len(row_ids), dtype=bool)
            mask[self.number_sets[name, field].get(numbers, [])] = True
            scores[~mask] = 0.0
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
        eligible = score >= self.bar
        event = None
        if family(name) == 'chronological':
            event = self.ranks(name, 'event', self.module.normalize_entity(args[1]))
            exact = exact & event[0]
            score = .6*score + .4*event[1]
            complete = .6*complete + .4*event[2]
            eligible = score >= self.bar if self.mode == 'main' else eligible & (event[1] >= self.bar)
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
    r['causes_by_mode'], r['details_by_mode'] = {}, {}
    for mode in MODES[1:]:
        failed = [f for f,_ in fields if r['scores_against_main_winner'][mode][f+'_score'] < BARS[mode]]
        r['causes_by_mode'][mode] = ' and '.join(failed)+f' below {BARS[mode]:.2f}' if failed else 'different ranking winner'
        norm = tools[mode].module.normalize_entity
        missing = set(w for f,q in fields for w in set(norm(row[f]).split())-set(norm(q).split()))
        r['details_by_mode'][mode] = ('numeric/ordinal difference' if any(tools[mode].module.is_number_word(w) for w in missing) else
            'missing role words' if missing & {'head','coach','chair','owner','president','ceo','duke','chief','director'} else 'lexical extraction difference')
    r['cause'] = r['causes_by_mode']['bar_075']
    r['detail'] = r['details_by_mode']['bar_075']
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

def noise_args(item, kind):
    if kind not in ('possessive', 'hyphen'):
        return g.noise_args(item, kind)
    args = list(item['arguments'])
    fields = range(len(args)) if family(item['tool']) == 'chronological' or item['tool'] == 'event_time' else range(1)
    for i in fields:
        if kind == 'hyphen':
            value = re.sub(r'[-–—]', ' ', args[i]) if re.search(r'[-–—]', args[i]) else re.sub(r'\s+', '-', args[i], count=1)
        else:
            matches = list(re.finditer(r"[^\W\d_]+", args[i]))
            value = args[i]
            for match in matches:
                w = match[0]
                if g.fold(w) in g.STOP or tools_number_word(w) or len(w) < 3 or (w.isupper() and len(w) <= 4): continue
                if args[i][match.end():match.end()+2] in ("'s", '’s'):
                    value = args[i][:match.end()] + args[i][match.end()+2:]
                else:
                    value = args[i][:match.end()] + '’s' + args[i][match.end():]
                break
        if value != args[i]:
            args[i] = value
            return tuple(args), True
    return tuple(args), False

def tools_number_word(word):
    return number_module.is_number_word(g.fold(word))

number_module = module('r2_number_check', ROOT/'toolbox/app/tools/temporal.py')

def surface(tools, corpus):
    summaries, failures, changed = {}, [], []
    for kind in ('lowercase','drop accents','drop the','add the','F.C. / FC','one character typo','singular/plural','possessive','hyphen'):
        records = []
        for item in corpus:
            args, differs = noise_args(item,kind)
            if differs:
                r=compare(tools,dict(item,kind=kind),args)
                records.append(r)
                if any(not r[mode+'_gold'] for mode in MODES): failures.append(diagnostics(tools,r))
                if any('answer' in r['main'] and 'answer' in r[mode] and r['main']['answer'] != r[mode]['answer'] for mode in MODES[1:]): changed.append(diagnostics(tools,r))
        summaries[kind]=split_stats(records)
        print('Surface',kind,summaries[kind]['all'],flush=True)
    dump('surface_failures.json',failures)
    dump('surface_answer_changes.json',changed)
    return summaries

def parse_logs(t):
    fields = {n:['event'] if n=='event_time' else ['entity','event' if family(n)=='chronological' else 'time'] for n in t.tables}
    pattern=re.compile(r'<tool_call>\s*(.*?)\s*</tool_call>',re.S)
    decoder=json.JSONDecoder()
    paths=sorted((ROOT/'rollouts').rglob('*.jsonl'))+[ROOT/'toolbox/rollouts.jsonl']
    search=subprocess.run(['rg','-l','<tool_call>',str(ROOT/'analysis'),'-g','*.jsonl','-g','!**/backup*/**','-g','!**/container-context/**','-g','!**/staged/**','-g','!**/gate_measure/**','-g','!**/role_entities/**','-g','!**/separate_bars/**','-g','!**/separate_bars_r2/**','-g','!**/cache/**','-g','!**/mock/**'],text=True,capture_output=True)
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
                causes[mode][r['causes_by_mode'][mode]+'; '+r['details_by_mode'][mode]]+=r['count']
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
                    if kind: values,_=noise_args(dict(tool=name,arguments=args),kind)
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

def collision_check(tools):
    """Vectorize every cell pair, with independent direct-score validation."""
    old = module('round1_collision', OUT/'round1_temporal.py')
    new = tools['bar_075'].module
    records, coverage = [], []
    def score_index(mod, normalized, numeric_guard):
        vocab = {w for text in normalized for w in text.split()}
        deletion = collections.defaultdict(set)
        for w in vocab:
            for i in range(len(w)): deletion[w[:i]+w[i+1:]].add(w)
        posts = [collections.defaultdict(list),collections.defaultdict(list)]
        exact, numbers = collections.defaultdict(list),collections.defaultdict(list)
        lengths = np.zeros((2,len(normalized)))
        for i,text in enumerate(normalized):
            parts = (set(text.split()),mod.char_ngrams(text))
            lengths[:,i] = [len(v) for v in parts]
            for kind,words in enumerate(parts):
                for w in words: posts[kind][w].append(i)
            exact[text].append(i)
            if numeric_guard: numbers[frozenset(w for w in parts[0] if mod.is_number_word(w))].append(i)
        posts = [{k:np.array(v) for k,v in p.items()} for p in posts]
        @functools.lru_cache(maxsize=None)
        def matching(q):
            candidates = {q} | deletion.get(q,set())
            for i in range(len(q)):
                d = q[:i]+q[i+1:]
                candidates.add(d); candidates.update(deletion.get(d,set()))
            for i in range(len(q)-1): candidates.add(q[:i]+q[i+1]+q[i]+q[i+2:])
            return {w for w in candidates & vocab if mod.word_present(w,{q})}
        def scores(q):
            found = np.zeros_like(lengths)
            for w in set().union(*(matching(w) for w in q.split())):
                indices=posts[0].get(w)
                if indices is not None: found[0,indices] += 1
            for gram in mod.char_ngrams(q):
                indices=posts[1].get(gram)
                if indices is not None: found[1,indices] += 1
            result = .7*found[0]/np.maximum(lengths[0],1) + .3*found[1]/np.maximum(lengths[1],1)
            if numeric_guard:
                nums=frozenset(w for w in q.split() if mod.is_number_word(w))
                mask=np.zeros(len(normalized),bool); mask[numbers.get(nums,[])] = True
                result[~mask] = 0
            if q: result[exact.get(q,[])] = 1
            return result
        return scores
    validated=0
    for name,rows in tools['main'].tables.items():
        for field in rows[0]:
            cells=collections.defaultdict(list)
            for i,row in enumerate(rows):
                for alt in row[field].split('|'): cells[alt.strip()].append(i+2)
            raw=sorted(cells)
            a=[old.normalize_entity(s) for s in raw]; b=[new.normalize_entity(s) for s in raw]
            old_index=score_index(old,a,False); new_index=score_index(new,b,True)
            pairs={}
            for i,q in enumerate(b):
                after=new_index(q); before=old_index(a[i])
                for j in np.flatnonzero((after >= .75 - 1e-12) & (before < .75 + 1e-12)):
                    if i != j: pairs[min(i,int(j)),max(i,int(j))] = True
                # Even empty newly identical cells are reported.
                for j in range(i+1,len(raw)):
                    if q == b[j] and a[i] != a[j]: pairs[i,j] = True
                if i < 8:
                    for j in random.Random(10413+i).sample(range(len(raw)),min(12,len(raw))):
                        assert np.isclose(after[j],new.entity_similarity(q,b[j]))
                        assert np.isclose(before[j],old.entity_similarity(a[i],a[j]))
                        validated += 2
            count_before = len(records)
            for i,j in sorted(pairs):
                ns=(new.entity_similarity(b[i],b[j]),new.entity_similarity(b[j],b[i]))
                os=(old.entity_similarity(a[i],a[j]),old.entity_similarity(a[j],a[i]))
                identical=b[i]==b[j] and a[i]!=a[j]
                newly_reaches=any(x >= .75 and y < .75 for x,y in zip(ns,os))
                if not identical and not newly_reaches: continue
                records.append(dict(table=name,field=field,a=raw[i],b=raw[j],a_lines=cells[raw[i]],b_lines=cells[raw[j]],
                    old_normalized=[a[i],a[j]],new_normalized=[b[i],b[j]],old_scores=os,new_scores=ns,identical=identical,newly_reaches=newly_reaches))
            coverage.append(dict(table=name,field=field,distinct_cells=len(raw),new_collisions=len(records)-count_before))
            print('Collision',name,field,len(raw),len(records)-count_before,flush=True)
    dump('collisions.json',records); dump('collision_coverage.json',coverage)
    return dict(pairs=len(records),identical=sum(r['identical'] for r in records),coverage=coverage,direct_score_validations=validated)

def report(summary):
    total_surface = {mode:sum(s['all'][mode+'_gold'] for s in summary['surface'].values()) for mode in MODES}
    noise_total = sum(s['all']['calls'] for s in summary['surface'].values())
    wrong = {mode:sum(s['all'].get(mode+'_new_errors',0) for s in summary['wrong'].values()) + summary['distinct']['all'].get(mode+'_new_errors',0) for mode in MODES}
    lines = ['VERDICT: Round-2 normalization and the threshold sweep are complete on separate-bars; answer changes and normalization collisions require review before promotion.','',
        f"Reference: toolbox main {summary['base_commit'][:7]}; the serving code retains a default component bar of 0.75. No merge, push or deployment.",'']
    table(lines,['Bar','Correct broken (live / table)','Wrong probes newly blocked','Noise gold/pass','Real calls newly failing','Real answers changed'],
          [(('main' if mode=='main' else f'{BARS[mode]:.2f}'),
            f"{summary['canonical']['all'].get(mode+'_lost_gold',0)} / {summary['serving']['all'].get(mode+'_lost_gold',0)}",
            wrong[mode],f"{total_surface[mode]:,}/{noise_total:,} ({100*total_surface[mode]/noise_total:.2f}%)",
            summary['real']['all'].get(mode+'_new_errors',0),summary['real']['all'].get(mode+'_changed_answers',0)) for mode in MODES])
    lines += ['Counts compare each bar with main, including both normalization and separate eligibility. Wrong-blocked counts cover the frozen extraction probes plus source-reviewed distinct-event probes. They measure rejection, not semantic correctness. Noise aggregates changed variants; per-kind rates follow. Correct broken means a call that reached English gold on main no longer does. Real counts retain historical occurrence weights.','',
        '## Material findings','',
        '**HIGH — answers change.** Bars 0.75 and 0.70 each change six historical call occurrences (four groups), all R.N. Upadhyaya Communist Party events: CSV line 4605 becomes line 4604. Hyphen normalization changes the winning event rank. Bar 0.65 changes 25 occurrences (seven groups), also including Richard Ryder and William Plumer Parliament calls. Every changed call is linked below. This is the most consequential result for intent rule 4.','',
        '**MEDIUM — the numeric guard rejects concatenated alternatives.** All 166 lost table-canonical matches occur when the round-1 synthetic harness submits a whole pipe cell as entity: 86 G20/G-20 cells and 80 10000/10K ODI-run cells. Their numeric token sets contain multiple representations. Live extraction selects one approved alternative and loses zero matches. Exact numeric matching also rejects historical omissions and differing numeric qualifiers, included in real-call counts.','',
        '**MEDIUM — lowercase acronym regressions.** Twenty-three lowercase variants that reach gold on main fail at every new bar: 22 HEOS-A1/A2 calls and one PSMS Medan call. The lowercase word receives plural normalization while its uppercase stored form is protected. They are listed in surface_failures.json.','',
        '**MEDIUM — new partial-name collisions remain.** There are 152 new entity/event collision pairs, 38 newly identical. All 38 newly identical pairs differ by articles, such as album Meteora / the album Meteora. The other 114 pairs cross the score bar in a new direction and include distinct names. For example Estate normalizes to estate and United States Ambassador to China includes states normalized to state: the one-edit allowance then treats estate as present. This is a concrete false-name match introduced by the combination of plural normalization and retained spelling tolerance (intent rule 4). Detection reports it without adding synonyms or changing the requested tolerance. Wrong-role and semantic-addition probes also continue to pass.','',
        '## Rules and safety','',
        'NFKC, existing accent folding, straight quotes, dashes to spaces, ampersand to and, article removal and conservative regular trailing s/es apply identically to queries and each stored alternative. Existing punctuation removal already handles F.C./FC and U.S./US. Apostrophe possessives are removed; mens becomes men through the plural rule. Short uppercase acronyms, numeric/ordinal/Roman tokens, series, and ss/us/is endings are protected. No synonym dictionary or general stemmer was added.','',
        'A hard equality check on the numeric/ordinal token sets enforces exact numbers, including omissions and extra numeric qualifiers. This intentionally closes round 1’s expected failure; all effects are included in the measurements. Token containment retains the one-edit allowance for stored words of at least five characters; trigrams retain their formula. Exact priority, ranking weights, completeness and time filtering retain their formulas. Event alternatives now split before normalization, as required for every stored alternative.','',
        '## Canonical correct extractions','']
    table(lines,['Corpus/family','Calls',*MODES,'Broken 0.75 / 0.70 / 0.65'],
        [(label+'/'+f,s['calls'],*(s[m+'_gold'] for m in MODES), ' / '.join(str(s[m+'_lost_gold']) for m in MODES[1:]))
         for label,groups in [('live',summary['canonical']),('table',summary['serving'])] for f,s in groups.items() if s.get('calls')])
    lines += ['All nine live tools parquets are bound by the round-1 harness to the current v6 logical corpus. Multilingual arguments use retained English reference/table text. Arithmetic and ordering are outside single lookup coverage; every event_time table row is separately covered. Physical coverage, input hashes and stable IDs are retained in JSON.','']
    for filename,label in [('canonical_new_failures.json','Every newly failing live extraction'),('serving_new_failures.json','Every newly failing table extraction')]:
        rows=json.loads((OUT/filename).read_text())
        lines += ['### '+label,'']
        if not rows: lines += ['None.','']
        else:
            table(lines,['ID','Arguments','Gold','Main',*MODES[1:],'Scores against main row','Causes'],
                [(r['id'],r['arguments'],r['gold'],r['main'],*(r[m] for m in MODES[1:]),r.get('scores_against_main_winner'),r.get('causes_by_mode')) for r in rows])
    lines += ['Existing failures are listed in canonical_existing_failures.json; their golds and table data were not changed.','', '## Wrong extraction probes','']
    table(lines,['Kind','Calls','Main answers',*['Answers '+m for m in MODES[1:]],'Newly blocked 0.75 / 0.70 / 0.65'],
        [(k,s['all']['calls'],s['all']['main_answers'],*(s['all'][m+'_answers'] for m in MODES[1:]),' / '.join(str(s['all'][m+'_new_errors']) for m in MODES[1:])) for k,s in summary['wrong'].items()])
    d=summary['distinct']['all']
    lines += [f"Additional source-reviewed distinct events: {d['calls']} calls; newly blocked 0.75 / 0.70 / 0.65 = "+' / '.join(str(d[m+'_new_errors']) for m in MODES[1:])+'.','']
    explicit=json.loads((OUT/'explicit_probes.json').read_text())
    table(lines,['Probe','Arguments','Main',*MODES[1:]],[(r['kind'],r['arguments'],r['main'].get('answer','ERROR'),*(r[m].get('answer','ERROR') for m in MODES[1:])) for r in explicit])
    lines += ['Assistant/different prefixes, negations and competing-owner text can still contain a complete stored name and pass. Lower bars also admit more role omissions; this remains a directional-containment limitation. All individual probes and scores are in wrong_probes.json and distinct_event_probes.json.','', '## Surface noise','']
    table(lines,['Noise','Calls',*['Gold/pass '+m for m in MODES]],
        [(k,s['all']['calls'],*(f"{s['all'][m+'_gold']} / {100*s['all'][m+'_gold']/s['all']['calls']:.2f}%" for m in MODES)) for k,s in summary['surface'].items()])
    lines += ['Original round-1 noise variants are retained exactly, including its mechanical singular/plural toggle; this sometimes pluralizes a proper name or a number, so the safety rules deliberately reject some variants. New possessive variants add/drop an apostrophe-s on the first eligible nonnumeric word. Hyphen variants replace dashes with spaces, or insert one hyphen at the first space. Dates are fixed. Full failing variants are in surface_failures.json; noise answer changes are listed separately.','', '## Real past calls','']
    real=summary['real']
    table(lines,['Family','Calls','Main answers',*['Answers '+m for m in MODES[1:]],'New failures 0.75 / 0.70 / 0.65','Changed answers 0.75 / 0.70 / 0.65'],
        [(f,s['calls'],s['main_answers'],*(s[m+'_answers'] for m in MODES[1:]),' / '.join(str(s[m+'_new_errors']) for m in MODES[1:]),' / '.join(str(s[m+'_changed_answers']) for m in MODES[1:])) for f,s in real.items() if f in ('all','chronological','absolute/entity_time','event_time') and s.get('calls')])
    table(lines,['Bar','Cause against main winner','Occurrences'],[(f'{BARS[m]:.2f}',cause,n) for m,causes in real['causes'].items() for cause,n in sorted(causes.items(),key=lambda x:-x[1])])
    regressions=json.loads((OUT/'real_call_regressions.json').read_text())
    for mode in MODES[1:]:
        lines += [f"### Top failures at {BARS[mode]:.2f}",'']
        top=sorted([r for r in regressions if 'answer' not in r[mode]],key=lambda r:-r['count'])[:10]
        table(lines,['Tool','Arguments','Occurrences','Main answer','Scores','Cause','Evidence'],[(r['tool'],r['arguments'],r['count'],r['main']['answer'],r['scores_against_main_winner'][mode],r['causes_by_mode'][mode]+'; '+r['details_by_mode'][mode],r['evidence']) for r in top])
    lines += [f"Parsed {real['unique_groups']:,} distinct tool/argument/historical-gold/cohort groups from {len(json.loads((OUT/'log_inventory.json').read_text()))} logs, {real['all']['calls']:,} call occurrences. Current and other cohorts and every tool are in real_call_summary.json. Calls include wrong extraction/localized names; new failures are not all valid regressions. Historical event_time gold often describes a downstream answer rather than this intermediate date.",'', '## Every answer change','']
    for filename,label in [('canonical_answer_changes.json','Live canonical'),('serving_answer_changes.json','Table canonical'),('real_answer_changes.json','Real calls'),('surface_answer_changes.json','Surface noise')]:
        rows=json.loads((OUT/filename).read_text())
        lines += [f"### {label}: {len(rows)} distinct records",'']
        if not rows: lines += ['None.','']; continue
        detail=['Every still-answering call returning a different answer than main. Row numbers below are CSV line numbers.','']
        table(detail,['ID/evidence','Tool','Arguments','Occurrences','Main answer/line',*['Answer/line '+m for m in MODES[1:]]],
            [(r.get('evidence',r.get('id')),r['tool'],r['arguments'],r.get('count',1),f"{r['main']['answer']} / {r['main']['row']+2}",*(f"{r[m]['answer']} / {r[m]['row']+2}" if 'answer' in r[m] else 'ERROR' for m in MODES[1:])) for r in rows])
        artifact=filename.replace('.json','.md'); (OUT/artifact).write_text('\n'.join(detail))
        lines += [f"Complete list: [{artifact}]({artifact}); machine-readable arguments, scores and evidence: [{filename}]({filename}).",'']
    collisions=json.loads((OUT/'collisions.json').read_text())
    lines += ['## Normalization collisions','',
        f"{summary['collisions']['pairs']:,} pairs of distinct cells newly become identical or reach >=0.75 in at least one score direction; {summary['collisions']['identical']:,} newly identical pairs. The reference here is round 1 with one-edit containment, isolating round-2 rules. Every column of every serving table is scanned, splitting alternatives; comparisons are within the same column, the domain compared by a lookup. Question, answer and time columns are also audited but are not lookup key domains. Existing collisions are excluded.",'']
    table(lines,['Table','Column','Distinct cells','New collision pairs'],[(r['table'],r['field'],r['distinct_cells'],r['new_collisions']) for r in summary['collisions']['coverage']])
    key_collisions=[r for r in collisions if r['field'] in ('entity','event')]
    lines += [f"Lookup entity/event domains contain {len(key_collisions):,} newly colliding pairs. All pairs, original cells, normalized values, both directional scores and CSV line memberships are listed in [collisions.json](collisions.json). A collision does not always change an answer: eligibility, dates and exact/completeness priority also matter.",'']
    table(lines,['Table/column','Cell A','Cell B','Old scores','New scores','Identical'],[(r['table']+'/'+r['field'],r['a'],r['b'],r['old_scores'],r['new_scores'],r['identical']) for r in key_collisions[:25]])
    lines += ['## Verification','',
        f"{summary['validation']['real_function_comparisons']} indexed replay comparisons with actual CSV-reading functions passed across all six tools and four modes, plus independent rank vectors. Exact input SHA-256 hashes were checked after measurement and are recorded in manifest.json.",'',
        'All 34 temporal tests pass. Full suite: 101 tests, 82 passed and 19 platform skips, using toolbox/venv with AZURE_TRANSLATOR_KEY=test-only and AZURE_TRANSLATOR_REGION=test-only (mocked translation calls). The first full run failed because the older tests expected these environment variables; no credentials were read. Collision vectors passed 4,032 direct score comparisons and every reported pair was rescored directly. Unit logs: temporal_tests.log and unittest.log. Tests changed for this plan: event-alternative tests now expect best-alternative matching; punctuation-score tests compute best-alternative score; the numeric expected failure is now an ordinary passing regression; the short-key article-A assertion now expects article removal. Round-1’s separate-eligibility change is retained.','',
        'Reproduce from workspace root: `.venv/bin/python -B -u analysis/separate_bars_r2/measure.py`. The snapshot of round 1 and main, all result JSON, coverage and logs are retained in this directory. Code, tests, measurement harness and report snapshots are committed only in toolbox on separate-bars. No serving CSVs, datasets, caches or services were changed.','']
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    handoff = re.sub(r'\]\(([^:)]+\.(?:json|md))\)', lambda match: ']('+ '../../analysis/separate_bars_r2/'+match[1]+')', '\n'.join(lines))
    (ROOT/'handoffs/reports/separate_bars_r2.md').write_text(handoff)

def main():
    base=subprocess.check_output(['git','-C',str(ROOT/'toolbox'),'rev-parse','main'],text=True).strip()
    assert subprocess.check_output(['git','-C',str(ROOT/'toolbox'),'show','main:app/tools/temporal.py']) == (OUT/'main_temporal.py').read_bytes()
    paths=[OUT/'main_temporal.py',OUT/'round1_temporal.py',ROOT/'toolbox/app/tools/temporal.py',Path(__file__),ROOT/'analysis/separate_bars/measure.py']+list((ROOT/'toolbox/app/tools').glob('*.csv'))+[ROOT/p for p in noise.PARQUETS]+list((ROOT/'v6').glob('*.jsonl'))+[ROOT/'analysis/fix_5_9/corpus.json',ROOT/'analysis/role_entities/active_canonical_calls.json',ROOT/'analysis/gate_measure/wrong_probes.json',ROOT/'analysis/fix_5_9/verify.py',ROOT/'analysis/gate_measure/measure.py',ROOT/'analysis/gate_measure/remeasure_datafix10/remeasure.py',ROOT/'analysis/typo_check/find.py',ROOT/'analysis/typo_check/judgments.jsonl']
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
    for kind,rows in [('canonical',corpus),('serving',serving)]:
        dump(kind+'_answer_changes.json',[diagnostics(tools,r) for r in rows if any('answer' in r['main'] and 'answer' in r[m] and r['main']['answer'] != r[m]['answer'] for m in MODES[1:])])
    summary=dict(base_commit=base,branch='separate-bars',validation=validation,canonical=split_stats(corpus),serving=split_stats(serving),parquet_coverage=coverage)
    print('Canonical',summary['canonical'],flush=True)
    summary['wrong']=wrong_probes(tools,corpus)
    summary['distinct']=distinct_probes(tools)
    summary['surface']=surface(tools,corpus)
    summary['real']=real_calls(tools)
    rs=json.loads((OUT/'real_call_regressions.json').read_text())
    dump('real_answer_changes.json',[r for r in rs if any('answer' in r[m] and r['main']['answer'] != r[m]['answer'] for m in MODES[1:])])
    summary['collisions']=collision_check(tools)
    inventory=json.loads((OUT/'log_inventory.json').read_text())
    manifest.update({r['file']:r['sha256'] for r in inventory})
    assert all(sha(ROOT/p)==h for p,h in manifest.items()),'Inputs changed during measurement'
    dump('manifest.json',manifest)
    dump('summary.json',summary)
    report(summary)
    print('COMPLETE',json.dumps(summary['real']['all']),flush=True)

if __name__=='__main__':
    main()
