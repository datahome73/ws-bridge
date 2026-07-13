#!/usr/bin/env python3
"""Send !pipeline_start R110 to _admin channel via temp bot."""
import json, asyncio, websockets, time

WS_URL = "wss://wsim.datahome73.cloud/ws"

async def main():
    # Register temp bot
    suffix = str(int(time.time()))[-6:]
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'go2-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get('type') != 'register_ok':
            print(f'❌ Register failed: {resp}')
            return
        api_key = resp['api_key']
        temp_id = resp.get('agent_id', '?')
        print(f'✅ Registered: {temp_id}')

    # Auth + send to _admin
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Auth: {resp.get("display_name")}')

        # Send !pipeline_start R110 to _admin (action commands go here)
        await ws.send(json.dumps({
            "type": "message",
            "channel": "_admin",
            "content": "!pipeline_start R110",
        }))
        print('📤 !pipeline_start R110 → _admin')

        for i in range(30):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                msg = json.loads(raw)
                ct = str(msg.get("content",""))
                ch = msg.get("channel","")
                fn = msg.get("from_name","")
                err = msg.get("error","")
                if err: print(f'  ❌ ERROR: {err}')
                if ct and ct != "None":
                    print(f'  ← [{ch}] {fn}: {ct[:300]}')
                    if '已启动' in ct:
                        print('  ✅ PIPELINE STARTED!')
            except asyncio.TimeoutError:
                break
            except websockets.exceptions.ConnectionClosed:
                break

    # Query status to confirm
    print('\n--- Verifying ---')
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'register', 'display_name': f'vfy-{suffix}'}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        ak = resp['api_key']

    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': ak}))
        await asyncio.wait_for(ws.recv(), timeout=10)
        await ws.send(json.dumps({
            'type': 'message', 'channel': '_inbox:server',
            'content': '!pipeline_status',
        }))
        print('📤 !pipeline_status')
        for i in range(20):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                msg = json.loads(raw)
                ct = str(msg.get("content",""))
                if ct and ct != "None": print(f'  {ct[:400]}')
            except asyncio.TimeoutError:
                break
            except websockets.exceptions.ConnectionClosed:
                break

asyncio.run(main())
