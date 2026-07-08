#!/usr/bin/env python3
"""Inbox 测试 v4 — 先测自收发（发给自己的收件箱）"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    uri = 'wss://wsim.datahome73.cloud/ws'

    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f"✅ 小谷认证通过 agent_id={my_id}")
        print(f"   活跃频道: {resp.get('active_channel', 'N/A')}")

        # 1. 自己给自己发 inbox（必须有 sent>=1 因为本连接已认证）
        inbox_self = f"_inbox:{my_id}"
        await asyncio.sleep(1.5)
        await ws.send(json.dumps({
            'type': 'message', 'channel': inbox_self,
            'content': '自检: 收件箱测试',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'self-{int(time.time())}', 'ts': time.time(),
        }))
        
        for _ in range(6):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                mt = data.get('type', '')
                if mt == 'ack':
                    sent = data.get('sent', 0)
                    print(f"📤 自收件箱 → sent={sent}")
                    if sent > 0:
                        print(f"   ✅ 本连接在 _connections 中！")
                else:
                    print(f"   [{mt}]: {str(data)[:200]}")
            except asyncio.TimeoutError:
                break
        
        # 2. 再发一条，然后看能不能从 broadcast 收到
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': inbox_self,
            'content': '自检2: 收件箱自收发测试',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'self2-{int(time.time())}', 'ts': time.time(),
        }))
        
        for _ in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                mt = data.get('type', '')
                if mt == 'ack':
                    sent = data.get('sent', 0)
                    print(f"📤 自收件箱2 → sent={sent}")
                elif mt == 'broadcast':
                    ch = data.get('channel', '')
                    if ch.startswith('_inbox:'):
                        fn = data.get('from_name', '?')
                        ct = data.get('content', '')
                        print(f"📩 收到自己的 inbox 广播! from={fn}: {ct[:100]}")
                elif mt == 'error':
                    print(f"❌ 错误: {data.get('error','')}")
            except asyncio.TimeoutError:
                break
        
        # 3. 查小开的 Agent Card 详情，拿实际 agent_id
        await asyncio.sleep(1.5)
        await ws.send(json.dumps({
            'type': 'message', 'content': '!agent_card get 小开',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'get-xiaokai-{int(time.time())}', 'ts': time.time(),
        }))
        await asyncio.sleep(2)
        for _ in range(3):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                if 'content' in data:
                    print(f"\n📇 小开 Agent Card:\n{data['content']}")
            except asyncio.TimeoutError:
                break

asyncio.run(test())
