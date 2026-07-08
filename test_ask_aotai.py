#!/usr/bin/env python3
"""问爱泰收到没"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        await asyncio.wait_for(ws.recv(), timeout=5)

        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': '_inbox:ws_0bb747d3ea2a',
            'content': '@爱泰 📋 爱泰收到最新那条 inbox 消息了吗？我发了3条了都没收到回复。你那边能看到内容吗？回复到 _inbox:ws_f26e585f6479 @小谷',
            'from_name': '小谷', 'agent_id': creds['agent_id'],
            'id': f'at-ask-{int(time.time())}', 'ts': time.time(),
        }))
        print("📤 inbox 已发，等回复...")
        for i in range(40):
            try:
                m = await asyncio.wait_for(ws.recv(), timeout=1.5)
                d = json.loads(m)
                if d.get('type') == 'broadcast':
                    fn = d.get('from_name','?')
                    ct = d.get('content','')
                    ch = d.get('channel','')
                    if fn == '爱泰' or ch.startswith('_inbox:'):
                        print(f"   [{fn}] [{ch}]: {ct[:200]}")
                    elif fn not in ('小谷','系统',''):
                        print(f"   [{fn}]: {ct[:100]}")
            except: pass

asyncio.run(test())
