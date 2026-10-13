#!/usr/bin/env python3
"""Round-3 three-way offline replay; no services or logged code execution."""
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
MODES = ('main', 'bar_075', 'bar_070')
BARS = dict(bar_075=.75, bar_070=.70)

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
        self.plural_posts = {}
        for name in harness.audit.TABLES:
            path = ROOT / f'toolbox/app/tools/{name}.csv'
            getattr(self.module, name).__defaults__ = (str(path),)
            self.text[name] = path.read_text()
            self.tables[name] = list(csv.DictReader(io.StringIO(self.text[name])))
            fields = ['event'] if name == 'event_time' else ['entity']
            if family(name) == 'chronological': fields.append('event')
            for field in fields:
                keys, row_ids, plural_keys = [], [], []
                for i, row in enumerate(self.tables[name]):
                    alternatives = row[field].split('|') if field == 'entity' or mode != 'main' else [row[field]]
                    for alternative in alternatives:
                        keys.append(self.module.normalize_entity(alternative))
                        row_ids.append(i)
                        plural_keys.append(self.module.stored_plural_words(alternative) if mode != 'main' else set())
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
                plural_posts = collections.defaultdict(list)
                for i, words in enumerate(plural_keys):
                    for word in words:
                        plural_posts[word].append(i)
                self.plural_posts[name, field] = {w:np.array(ids) for w,ids in plural_posts.items()}
            if 'time' in self.tables[name][0]:
                normalizer = self.module.normalize_time_key if 'absolute' in name else self.module.normalize_time
                self.times[name] = [normalizer(row['time']) for row in self.tables[name]]
        self.vocabulary = {word for _, _, _, posts, _ in self.columns.values() for word in posts[0]}
        self.plural_stems = collections.defaultdict(set)
        if mode != 'main':
            for posts in self.plural_posts.values():
                for word in posts:
                    self.plural_stems[self.module._singular_surface(word)].add(word)
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
            matched = set().union(*(self.matched_words(q) for q in query_words))
            for word in matched:
                indices = posts[0].get(word)
                if indices is not None:
                    fuzzy[indices] += 1
            plural_matched = set().union(*(self.plural_stems.get(self.module._singular_surface(q), set())
                for q in query_words if q.isalpha() and len(q) >= 3 and not self.module.is_number_word(q)))
            for word in plural_matched - matched:
                indices = self.plural_posts[name, field].get(word)
                if indices is not None:
                    fuzzy[indices] += 1
        scores = .7*(fuzzy/np.maximum(tokens, 1)) + .3*(intersections[1]/np.maximum(grams, 1))
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
    search=subprocess.run(['rg','-l','<tool_call>',str(ROOT/'analysis'),'-g','*.jsonl','-g','!**/backup*/**','-g','!**/container-context/**','-g','!**/staged/**','-g','!**/gate_measure/**','-g','!**/role_entities/**','-g','!**/separate_bars/**','-g','!**/separate_bars_r2/**','-g','!**/separate_bars_r3/**','-g','!**/cache/**','-g','!**/mock/**'],text=True,capture_output=True)
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
                for query in ('John Grishm','The Pelican Brif','Grihsam','Member of the 15th Parliament','president of america','latvia','heos a1','coaches of teams','India','1er Baronet','2011 2012'):
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

import details
import reporting
import validate_evidence
details.install(sys.modules[__name__])
classify_failures = details.classify_failures
collision_check = details.collision_check

def report(summary):
    reporting.report(sys.modules[__name__], summary)

def main():
    base=subprocess.check_output(['git','-C',str(ROOT/'toolbox'),'rev-parse','main'],text=True).strip()
    assert subprocess.check_output(['git','-C',str(ROOT/'toolbox'),'show','main:app/tools/temporal.py']) == (OUT/'main_temporal.py').read_bytes()
    paths=[OUT/'main_temporal.py',OUT/'round1_temporal.py',OUT/'round2_temporal.py',ROOT/'toolbox/app/tools/temporal.py',Path(__file__),OUT/'details.py',OUT/'reporting.py',OUT/'validate_evidence.py',ROOT/'analysis/separate_bars/measure.py']+list((ROOT/'toolbox/app/tools').glob('*.csv'))+[ROOT/p for p in noise.PARQUETS]+list((ROOT/'v6').glob('*.jsonl'))+[ROOT/'analysis/fix_5_9/corpus.json',ROOT/'analysis/role_entities/active_canonical_calls.json',ROOT/'analysis/gate_measure/wrong_probes.json',ROOT/'analysis/fix_5_9/verify.py',ROOT/'analysis/gate_measure/measure.py',ROOT/'analysis/gate_measure/remeasure_datafix10/remeasure.py',ROOT/'analysis/typo_check/find.py',ROOT/'analysis/typo_check/judgments.jsonl']
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
    summary['correct_intent_failures']=classify_failures(tools)
    summary['collisions']=collision_check(tools)
    summary['validation'].update(validate_evidence.validate(sys.modules[__name__], tools))
    inventory=json.loads((OUT/'log_inventory.json').read_text())
    manifest.update({r['file']:r['sha256'] for r in inventory})
    assert all(sha(ROOT/p)==h for p,h in manifest.items()),'Inputs changed during measurement'
    dump('manifest.json',manifest)
    dump('summary.json',summary)
    report(summary)
    print('COMPLETE',json.dumps(summary['real']['all']),flush=True)

if __name__=='__main__':
    main()
