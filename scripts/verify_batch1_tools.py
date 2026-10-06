#!/usr/bin/env python3
"""Verify a local toolbox REST + SSE endpoint and report acceptance timings."""
import argparse
import asyncio
import json
from pathlib import Path
import statistics
import sys
import time

import httpx
from fastmcp import Client

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.tools import language

COUNTS={'before_chronological_reference':(260,242),'after_chronological_reference':(259,241),
        'before_absolute_reference':(271,182),'after_absolute_reference':(267,181),
        'entity_time_event':(217,170),'event_time':(265,255),'translation':(163,146)}


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:18010')
    parser.add_argument('--prompt',type=Path,help='Training prompt JSON from a rebuilt parquet')
    args=parser.parse_args()
    url=args.url
    with httpx.Client(trust_env=False) as rest:
        rest_tools={t['name']:t for t in rest.get(url+'/tools').json()}
        async with Client(url+'/sse') as mcp:
            tools={t.name:t for t in await mcp.list_tools()}
            for name,(before,after) in COUNTS.items():
                r=rest_tools[name];t=tools[name]
                assert r['description']==t.description
                assert len(t.description)==after<=before
                for param,prop in r['parameters']['properties'].items():
                    if param=='text':continue  # no new text-parameter wording in approved spec
                    assert prop['description']==t.inputSchema['properties'][param]['description']
                print(name,f'{before} -> {len(t.description)} characters; parameters match')
            result=await mcp.call_tool('before_chronological_reference',{'entity':'John Grisham','event':'The Pelican Brief'})
            assert result.content[0].text=='The Firm'
            print('SSE lookup smoke: The Firm')
        # Render exactly the tool contract prepended to a training user prompt.
        prompt=json.loads(args.prompt.read_text()) if args.prompt else [{'role':'user','content':'test'}]
        rendered='# Tools\n<tools>\n'+'\n'.join(json.dumps({'type':'function','function':t},ensure_ascii=False) for t in rest_tools.values())+'\n</tools>\n'+prompt[-1]['content']
        for name in COUNTS:
            assert json.dumps(rest_tools[name]['description'],ensure_ascii=False) in rendered
        print('Rendered training prompt: new descriptions present')
        key,value=next(iter(language._CACHE.items()))
        text,source,target=json.loads(key)
        payload={'tool_name':'translation','arguments':{'text':text,'source_language':source,'target_language':target}}
        direct=[];http=[]
        rest.post(url+'/tool',json=payload).raise_for_status()
        for _ in range(30):
            start=time.perf_counter();assert language.translate(text,source,target)==value;direct.append(1000*(time.perf_counter()-start))
            start=time.perf_counter();response=rest.post(url+'/tool',json=payload).json();http.append(1000*(time.perf_counter()-start))
            assert response['status']=='ok' and response['result_text']==value
        print('Cache direct min/median/max ms:',min(direct),statistics.median(direct),max(direct))
        print('Cache REST min/median/max ms:',min(http),statistics.median(http),max(http))
        assert max(direct)<10 and max(http)<10
        print('RESULT: PASS')


if __name__=='__main__':asyncio.run(main())
