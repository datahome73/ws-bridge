#!/usr/bin/env python3
"""只点名小开抓他的 agent_id"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']

    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f"✅ 小谷认证通过\n")

        # 点名小开（用广播点名格式）
        print("📤 点名 @小开 ...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message',
            'content': '@小开 📋点名 小开在线吗？收到请回 @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'roll-xk-{int(time.time())}', 'ts': time.time(),
        }))

        # 等 30s 看回复
        for i in range(20):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                data = json.loads(msg)
                t = data.get('type','')
                if t == 'broadcast':
                    fn = data.get('from_name','?')
                    ct = data.get('content','')
                    aid = data.get('agent_id','?')
                    if fn not in ('小谷', '系统', ''):
                        print(f"  [{i+1}] [{fn}] agent_id={aid}: {ct[:150]}")
                elif t == 'error':
                    print(f"  ❌ {data.get('error')}")
            except asyncio.TimeoutError:
                pass
        
        print(f"\n✅ 完成")

asyncio.run(test())
