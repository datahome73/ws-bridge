#!/usr/bin/env python3
"""快速测试：给小开发 inbox + 大厅 @全员 点名"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    uri = 'wss://wsim.datahome73.cloud/ws'

    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"✅ 小谷认证通过")

        # 第一步：发 inbox 给小开
        print(f"\n📤 [小开] inbox...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': '_inbox:ws_f8a816527f9e',
            'content': '📋 小开 inbox测试 - 来自小谷，收到请回复 @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'inbox-xk-{int(time.time())}', 'ts': time.time(),
        }))
        for _ in range(5):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                t = data.get('type','')
                if t == 'ack': print(f"    ✅ ACK (sent={data.get('sent',0)})")
                elif t == 'error': print(f"    ❌ {data.get('error')}")
                elif t == 'broadcast':
                    print(f"    📩 [{data.get('from_name')}]: {data.get('content','')[:100]}")
            except asyncio.TimeoutError:
                break

        # 第二步：发大厅 @点名，看谁能回
        print(f"\n📤 大厅 @点名...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message',
            'content': '@小开 @爱泰 @小周 @泰虾 @小爱 inbox收发测试 - 来自小谷，收到请回复 @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'lobby-all-{int(time.time())}', 'ts': time.time(),
        }))
        print("    等回复（最多 60s）：")
        for i in range(40):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                data = json.loads(msg)
                t = data.get('type','')
                if t == 'broadcast':
                    fn = data.get('from_name','?')
                    ct = data.get('content','')
                    aid = data.get('agent_id','?')
                    ch = data.get('channel','')
                    if fn not in ('小谷', '系统'):
                        print(f"    [{i+1}] [{fn}] agent_id={aid[:20]}: {ct[:150]}")
                elif t == 'ack':
                    pass  # skip lobby acks
            except asyncio.TimeoutError:
                pass

        print(f"\n✅ 完成")

asyncio.run(test())
