#!/usr/bin/env python3
"""Check R110 pipeline status as 小谷 (level 4, no extra registration)."""
import json, asyncio, websockets, time, os

WS_URL = "wss://wsim.datahome73.cloud/ws"
CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds['api_key']

    # Query !pipeline_status as 小谷 via _admin (action commands go here)
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ {resp.get("display_name")}')

        await ws.send(json.dumps({
            'type': 'message', 'channel': '_admin',
            'content': '!pipeline_status',
        }))
        print('📤 !pipeline_status → _admin')

        for i in range(20):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1)
                msg = json.loads(raw) if isinstance(raw, str) else raw
                ct = str(msg.get('content',''))
                err = msg.get('error','')
                if err: print(f'  ❌ {err}')
                if ct and ct != 'None': print(f'  {ct[:400]}')
            except asyncio.TimeoutError:
                break
            except websockets.exceptions.ConnectionClosed:
                break

asyncio.run(main())
