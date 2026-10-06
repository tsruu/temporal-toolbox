#!/usr/bin/env python3
"""Pre-warm Azure translations from dataset arguments, lookup values and rollouts.

Run with toolbox/venv/bin/python. --collect-only reports coverage without Azure calls.
The package cache is frozen at serve time; this is the only writer.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import json
from pathlib import Path
import re
import sys
import time
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.tools import language

# These are the literal question generator frames. The remainder is the tool
# argument, not a whole-question translation. Variations are handled below.
PREFIX = re.compile(
    r"^(?:Quel poste (?:a occupé|occupait)|Ce (?:poziţie|poziție|funcţie) (?:a avut|a deţinut)|"
    r"Welche Position (?:hat|Hut)|Für (?:welche Mannschaft|welches Team|welchen Arbeitgeber) (?:spielte|arbeitete|hat|war)|"
    r"Pentru ce (?:echipă a jucat|angajator a lucrat)|"
    r"Pour (?:quelle équipe|quel employeur)|"
    r"(?:Cine (?:a fost|era)|Qui (?:était|a été)|Wer (?:war|Krieg)) "
    r"(?:le |la |l'|der |die |das )?"
    r"(?:preşedintele|președintele|şeful|șeful|antrenorul|proprietarul|président|chef|propriétaire|"
    r"entraîneur|Vorsitzende|Leiter|Head Coach|Cheftrainer|Chef|Eigentümer|Besitzer|Staatsoberhaupt)"
    r"(?: principal| şef| principal de| de| du| des| der| von| al)?|"
    r"(?:Unde|Wo|Où) (?:era|a fost|war|wurde|hat|Hat|était))\s+", re.I)
BOUNDARY = re.compile(r"\s+(?:avant|après|apres|înainte(?: de)?|după|dupa|vor|nach)\s+", re.I)
DATE = re.compile(r"\s+(?:en|în|im)\s+[^?]+?\d{4}\??$", re.I)
TRAILING = re.compile(r"\s+(?:inne|gespielt|gearbeitet|educat[ă]?|ausgebildet|gebildet|studiert|étudié|a-t-il joué|a-t-elle joué|a-t-il travaillé|a-t-elle travaillé)\??$", re.I)


def question_language(q):
    first = q.split()[0].casefold()
    if first in ('which','who','where','what','when','the','how'): return 'en'
    if first in ('ce','cine','pentru','unde','din'): return 'ro'
    if first in ('quel','quelle','qui','pour','où','quel(le)'): return 'fr'
    if first in ('für','welche','welches','wer','wo','zu','als','das','was'): return 'de'
    return language._normalize_language(language.detect_language(q))


def collect(root):
    entries = defaultdict(set)
    counts = Counter()
    def add(text, source, origin):
        text = language._normalize_text(text).strip(' ?')
        if text and source != 'en':
            entries[(text, source, 'en')].add(origin)
            counts[origin] += 1

    known = set()
    csv_values = []
    for path in sorted((root / 'toolbox/app/tools').glob('*.csv')):
        for row in csv.DictReader(path.open(encoding='utf-8')):
            for field in ('entity', 'event', 'answer'):
                value = row.get(field, '').strip()
                if value:
                    known.add(value)
                    csv_values.append(value)
    # langdetect is imperfect for short proper names. Preserve the entire
    # non-English detected superset, including ambiguous proper names.
    for value in sorted(set(csv_values)):
        try: source = language._normalize_language(language.detect_language(value))
        except ValueError: counts['undetectable CSV values'] += 1; continue
        add(value, source, 'lookup CSV values')

    seen = set()
    paths = list((root / 'v4').glob('*.jsonl')) + list((root / 'v6').glob('*-train.jsonl')) + list((root / 'v6').glob('*-test.jsonl'))
    # English canonical entities help retain exact proper-name spans inside the
    # translated questions, even when the generator changes their spelling.
    for path in paths:
        for line in path.open(encoding='utf-8'):
            row = json.loads(line)
            if row.get('datatype') != 'tempreason' or row.get('level') not in ('l2', 'l3'): continue
            for variant, answer in (('Q1','Answer 1'),('Q2','Answer 2')):
                q = row[variant]
                if q in seen: continue
                seen.add(q)
                source = question_language(q)
                if source == 'en': continue
                counts['non-English l2/l3 questions'] += 1
                add(row.get(answer,''), source, 'l2/l3 answer positions')
                # Anchor is a translated position/entity; strip a terminal verb.
                parts = BOUNDARY.split(q, maxsplit=1)
                if len(parts) == 2:
                    add(TRAILING.sub('',parts[1]).rstrip('?'),source,'l3 anchors')
                core = PREFIX.sub('', DATE.sub('', parts[0])).rstrip('?')
                core = TRAILING.sub('',core)
                # Exact canonical names that survive translation, and maximal
                # remaining nominal spans. Also keep prefix/suffix spans for
                # atypical or malformed generator frames, a conservative superset.
                words = core.split()
                for i in range(len(words)):
                    add(' '.join(words[i:]),source,'question suffix spans')
                    add(' '.join(words[:i+1]),source,'question prefix spans')
                for value in known:
                    if value in q: add(value,source,'exact canonical names in questions')

    # Inspect actual translation calls, including nested/string-encoded JSON.
    def visit(value):
        if isinstance(value, dict):
            name=value.get('name',value.get('tool_name'))
            if name=='translation':
                args=value.get('arguments',{})
                if isinstance(args,str):
                    try: args=json.loads(args)
                    except ValueError: args={}
                if isinstance(args,dict) and args.get('text'):
                    try: source=language._normalize_language(args.get('source_language',''))
                    except ValueError:
                        try: source=language._normalize_language(language.detect_language(args['text']))
                        except ValueError: source=''
                    if source: add(args['text'],source,'rollout translation arguments')
            for child in value.values(): visit(child)
        elif isinstance(value,list):
            for child in value: visit(child)
        elif isinstance(value,str) and 'translation' in value:
            for payload in re.findall(r'<tool_call>\s*(.*?)\s*</tool_call>',value,re.S):
                try: visit(json.loads(payload))
                except ValueError: pass
    for path in (root/'rollouts').rglob('*.jsonl'):
        for line in path.open(encoding='utf-8'):
            try: visit(json.loads(line))
            except ValueError: pass
    return entries, counts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--collect-only',action='store_true')
    parser.add_argument('--characters-per-second',type=int,default=400,
                        help='Pre-warm pacing to respect Azure character quotas')
    parser.add_argument('--candidates',type=Path,
                        help='Save/reuse the collected candidate manifest for resumable builds')
    parser.add_argument('--output',type=Path,default=language.PACKAGE_DIR/'translation_cache.json')
    args=parser.parse_args()
    if args.candidates and args.candidates.exists():
        manifest=json.loads(args.candidates.read_text(encoding='utf-8'))
        candidates={tuple(item) for item in manifest['candidates']}
        counts=manifest['selection_counts']
    else:
        candidates, counts=collect(args.root)
        if args.candidates:
            args.candidates.write_text(json.dumps({'candidates':sorted(candidates),
                'selection_counts':dict(counts)},ensure_ascii=False),encoding='utf-8')
    print('Selection counts:',dict(counts),flush=True)
    print('Unique candidates:',len(candidates),'characters:',sum(len(t) for t,_,_ in candidates),flush=True)
    if args.collect_only: return
    cache=json.loads(args.output.read_text(encoding='utf-8')) if args.output.exists() else {'entries':{}}
    entries=cache['entries']
    pending=[k for k in sorted(candidates) if language.cache_key(*k) not in entries]
    characters=0
    calls=0
    failures=Counter()
    # Azure supports many texts per request. Batch by language to avoid paying
    # network setup for every short name; serve-time calls remain individually capped.
    groups = defaultdict(list)
    for item in pending:
        groups[item[1:]].append(item)
    batches = [items[i:i+200] for items in groups.values() for i in range(0,len(items),200)]
    def task(batch):
        import os
        translator = language._FrozenMicrosoftTranslator(
            api_key=os.environ.get('AZURE_TRANSLATOR_KEY'),
            region=os.environ.get('AZURE_TRANSLATOR_REGION'),
            source=batch[0][1], target=batch[0][2])
        params = dict(translator._url_params, **{'from':batch[0][1], 'to':batch[0][2]})
        try:
            response = requests.post(translator._base_url, params=params,
                headers=translator.headers, json=[{'text':item[0]} for item in batch],timeout=10)
            if response.status_code != 200:
                raise language.TranslationError(f'Azure batch HTTP {response.status_code}')
            values=response.json()
            if not isinstance(values,list) or len(values)!=len(batch):
                raise ValueError('invalid batch response')
            return [(language.cache_key(*item),value['translations'][0]['text'])
                    for item,value in zip(batch,values)]
        except language.TranslationError:
            raise
        except Exception:
            raise language.TranslationError('Azure batch request failed') from None
    history=list(cache.get('build_history',[]))
    with ThreadPoolExecutor(max_workers=1) as pool:
        # Submit bounded batches gradually rather than bursting the full corpus.
        # This also preserves completed entries after a rate-limit failure.
        for i,batch in enumerate(batches,1):
            start=time.monotonic()
            characters += sum(len(item[0]) for item in batch)
            calls += 1
            try:
                entries.update(pool.submit(task,batch).result())
            except language.TranslationError as error:
                failures[str(error)]+=1
                print('Stopped on',str(error),flush=True)
                break
            if i%5==0:
                print('Completed batches',i,'of',len(batches),'failures',failures,flush=True)
                args.output.write_text(json.dumps({'build_history':history,
                    'entries':dict(sorted(entries.items()))},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            if args.characters_per_second and i<len(batches):
                delay=sum(len(item[0]) for item in batch)/args.characters_per_second
                time.sleep(max(0,delay-(time.monotonic()-start)))
    metadata={'selection_counts':dict(counts),'candidate_entries':len(candidates),
              'entries':len(entries),'characters_sent_this_build':characters,
              'calls_this_build':calls,'failures':dict(failures)}
    args.output.write_text(json.dumps({'metadata':metadata,'build_history':history+[metadata],
        'entries':dict(sorted(entries.items()))},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Cache build:',metadata,flush=True)
    if failures: raise SystemExit('Cache build incomplete; inspect failures before freezing')


if __name__=='__main__': main()
