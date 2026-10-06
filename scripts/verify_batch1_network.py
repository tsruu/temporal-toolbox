#!/usr/bin/env python3
"""Check uncached errors on a local server started with an unroutable proxy."""
import asyncio
import argparse
import time

import httpx
from fastmcp import Client

URL='http://127.0.0.1:18011'
ARGS={'text':'Cette chaîne est volontairement absente du cache: batch1-network-check',
      'source_language':'fr','target_language':'en'}


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default=URL)
    url=parser.parse_args().url
    with httpx.Client(trust_env=False) as rest:
        start=time.perf_counter()
        response=rest.post(url+'/tool',json={'tool_name':'translation','arguments':ARGS}).json()
        elapsed=time.perf_counter()-start
        assert response['status']=='error'
        assert response['result_text'].startswith('ERROR: translation failed:')
        assert response['result_text']!=ARGS['text'] and elapsed<1.8
        print('Network blocked REST:',response['result_text'],f'({elapsed:.6f} s)')
    async with Client(url+'/sse') as client:
        start=time.perf_counter();response=await client.call_tool('translation',ARGS)
        elapsed=time.perf_counter()-start
        assert response.content[0].text.startswith('ERROR: translation failed:')
        assert response.content[0].text!=ARGS['text'] and elapsed<1.8
        print('Network blocked SSE:',response.content[0].text,f'({elapsed:.6f} s)')
    print('RESULT: PASS')


if __name__=='__main__':asyncio.run(main())
