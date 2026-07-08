#!/usr/bin/env python3
"""查所有 card 的实际 agent_id，再发 inbox"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    uri = 'wss://wsim.datahome73.cloud/ws'

    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f"✅ 小谷认证通过\n")

        # 用 !agent_card get 逐个查 — 用 agent_id 查
        known = {
            "小开": "ws_f8a816527f9e",
            "爱泰": "ws_0ee70be2d59e", 
            "小周": "ws_4e1a1b3ba0b9",
            "泰虾": "ws_cd771242975a",
            "小爱": "ws_7f0e931af04b",
        }
        
        print("📇 查 Agent Card 详情（验证 agent_id 的准确性）：")
        for name, aid in known.items():
            await asyncio.sleep(1.5)
            await ws.send(json.dumps({
                'type': 'message', 'content': f'!agent_card get {aid}',
                'from_name': '小谷', 'agent_id': my_id,
                'id': f'get-{name}-{int(time.time())}', 'ts': time.time(),
            }))
            await asyncio.sleep(0.5)
            for _ in range(3):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    data = json.loads(msg)
                    if 'content' in data:
                        c = data['content']
                        # 提取 display_name 和 agent_id
                        print(f"  {name}: {c[:200]}")
                except asyncio.TimeoutError:
                    break
        
        # 现在用实际 card 里的 agent_id 发 inbox
        print("\n📤 重新发 inbox（到真正的在线 agent_id）：")
        for name, aid in known.items():
            inbox_ch = f"_inbox:{aid}"
            await asyncio.sleep(2)
            await ws.send(json.dumps({
                'type': 'message', 'channel': inbox_ch,
                'content': f'📋 inbox测试 - 小谷→{name}，收件箱消息，收到请回复 @小谷',
                'from_name': '小谷', 'agent_id': my_id,
                'id': f'inbox-{name}-{int(time.time())}', 'ts': time.time(),
            }))
            for _ in range(5):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    data = json.loads(msg)
                    if data.get('type') == 'ack':
                        sent = data.get('sent', 0)
                        print(f"  ✅ {name:6s} → _inbox:{aid[:16]}: ACK sent={sent}")
                        break
                    elif data.get('type') == 'error':
                        print(f"  ❌ {name:6s}: {data.get('error','')}")
                        break
                except asyncio.TimeoutError:
                    print(f"  ⚠️ {name:6s}: 超时")
                    break

asyncio.run(test())
