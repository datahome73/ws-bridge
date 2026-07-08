#!/usr/bin/env python3
"""用小爱真实 agent_id 测试 inbox"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    uri = 'wss://wsim.datahome73.cloud/ws'

    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"✅ 小谷认证通过")

        # 用小爱真实 agent_id 发 inbox
        real_xiaoai = "ws_c47032fa1f67"
        inbox_ch = f"_inbox:{real_xiaoai}"
        
        print(f"\n📤 [小爱] → {inbox_ch} (真实ID)")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': inbox_ch,
            'content': '📋 inbox测试 - 小谷→小爱（用真实agent_id），收到请回复 @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'inbox-xa-real-{int(time.time())}', 'ts': time.time(),
        }))
        
        for _ in range(5):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                t = data.get('type','')
                if t == 'ack':
                    sent = data.get('sent',0)
                    print(f"   ✅ ACK sent={sent}")
                    if sent > 0:
                        print(f"   🎉 投递成功！")
                elif t == 'error':
                    print(f"   ❌ {data.get('error')}")
                elif t == 'broadcast':
                    ch = data.get('channel','')
                    if ch.startswith('_inbox:'):
                        print(f"   📩 收到 inbox 回声!")
            except asyncio.TimeoutError:
                break
        
        print(f"\n📤 再发一条 @小爱 到大厅确认...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message',
            'content': '@小爱 收到 inbox 消息了吗？回复确认',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'confirm-{int(time.time())}', 'ts': time.time(),
        }))
        for _ in range(20):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                data = json.loads(msg)
                t = data.get('type','')
                if t == 'broadcast':
                    fn = data.get('from_name','?')
                    ct = data.get('content','')
                    aid = data.get('agent_id','?')
                    print(f"   [{fn}] id={aid[:16]}: {ct[:150]}")
            except asyncio.TimeoutError:
                pass

asyncio.run(test())
