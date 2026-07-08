#!/usr/bin/env python3
"""用小谷自己验证 agent_id 套路"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    uri = 'wss://wsim.datahome73.cloud/ws'

    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"✅ 小谷 auth_ok")
        
        # 1. 查自己的 card（用自己 agent_id 应当有卡）
        await asyncio.sleep(1.5)
        await ws.send(json.dumps({
            'type': 'message', 'content': f'!agent_card get {my_id}',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'get-self-{int(time.time())}', 'ts': time.time(),
        }))
        await asyncio.sleep(1.5)
        for _ in range(3):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                if 'content' in data:
                    print(f"📇 小谷 card: {data['content'][:300]}")
            except asyncio.TimeoutError:
                break
        
        # 2. 试小爱（用她 card 的已知 ID）
        # card list 显示小爱在线，但 agent_id 不同
        # 小爱之前回复过 "小爱收到 ✅" 那她的 broadcast 带有 agent_id
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message',
            'content': '@小爱 inbox测试，请回复确认',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'ping-xiaoai-{int(time.time())}', 'ts': time.time(),
        }))
        print(f"\n⏳ 等小爱回复中...")
        for _ in range(15):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1)
                data = json.loads(msg)
                if data.get('type') == 'broadcast':
                    fn = data.get('from_name', '?')
                    aid = data.get('agent_id', '?')
                    ct = data.get('content', '')
                    print(f"  📩 [{fn}] agent_id={aid}: {ct[:150]}")
                    if '小爱' in str(fn):
                        print(f"\n🎯 小爱实时 agent_id = {aid}")
                        # 用小爱在线的 agent_id 发 inbox
                        inbox_ch = f"_inbox:{aid}"
                        await asyncio.sleep(2)
                        await ws.send(json.dumps({
                            'type': 'message', 'channel': inbox_ch,
                            'content': f'📋 收件箱测试 - 小谷→小爱，这条走 inbox 发送',
                            'from_name': '小谷', 'agent_id': my_id,
                            'id': f'inbox-xiaoai-{int(time.time())}', 'ts': time.time(),
                        }))
                        for _ in range(5):
                            try:
                                r = await asyncio.wait_for(ws.recv(), timeout=2)
                                d = json.loads(r)
                                if d.get('type') == 'ack':
                                    print(f"   ✅ 小爱 inbox: sent={d.get('sent',0)}")
                                    # 等 2 秒看看小爱有没有通过 inbox 回复
                                    await asyncio.sleep(3)
                                    for _ in range(5):
                                        try:
                                            r2 = await asyncio.wait_for(ws.recv(), timeout=1)
                                            d2 = json.loads(r2)
                                            if d2.get('type') == 'broadcast' and d2.get('channel','').startswith('_inbox:'):
                                                print(f"   📩 inbox回声: from={d2.get('from_name')}: {d2.get('content','')[:120]}")
                                        except asyncio.TimeoutError:
                                            pass
                                    break
                            except asyncio.TimeoutError:
                                break
            except asyncio.TimeoutError:
                pass

asyncio.run(test())
