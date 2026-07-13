#!/usr/bin/env python3
"""Test: send to 小开 inbox as 小谷, check for errors."""
import json, asyncio, websockets, time, os

WS_URL = "wss://wsim.datahome73.cloud/ws"
CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
XIAOKAI_ID = "ws_3f7cdd736c1c"

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds['api_key']

    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': api_key}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f'✅ Auth: {resp.get("display_name")}')

        # Send to 小开 inbox - expect either:
        # - success (level >=4): message delivered, connection closes
        # - error (level <4): "权限不足" error message
        await ws.send(json.dumps({
            'type': 'message', 'channel': f'_inbox:{XIAOKAI_ID}',
            'from_name': '小谷', 'from_agent': 'ws_f26e585f6479',
            'content': '🔧 R110 连通测试 — 如果你看到这条消息，说明路由正常',
        }))
        print(f'📤 Sent to _inbox:{XIAOKAI_ID}')

        # Read everything before connection closes
        responses = []
        for i in range(20):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.3)
                try:
                    msg = json.loads(raw) if isinstance(raw, str) else raw
                except:
                    msg = {'raw': str(raw)[:100]}
                responses.append(msg)
                ct = str(msg.get('content',''))
                err = msg.get('error','')
                mt = msg.get('type','')
                ch = msg.get('channel','')
                if err: print(f'  ❌ {mt} ERROR: {err}')
                if ct and ct != 'None': print(f'  ← {mt} {ch}: {ct[:200]}')
            except asyncio.TimeoutError:
                break
            except websockets.exceptions.ConnectionClosed:
                break

        print(f'\n📊 {len(responses)} response(s)')
        for r in responses:
            print(f'   {json.dumps(r, ensure_ascii=False)[:200]}')

asyncio.run(main())
