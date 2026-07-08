#!/usr/bin/env python3
"""检查在线状态 + inbox 发送测试（含回复监听）"""
import asyncio, json, websockets, os, time, uuid

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    uri = 'wss://wsim.datahome73.cloud/ws'

    async with websockets.connect(uri, max_size=2**20) as ws:
        # 认证
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get('type') == 'auth_ok'
        print(f"✅ 小谷认证通过 | agent_id={creds['agent_id']}")
        print(f"   活跃频道: {resp.get('active_channel', 'N/A')}\n")

        # 1. !agent_card list —— 看在线状态
        await asyncio.sleep(1.5)
        payload = {
            'type': 'message', 'content': '!agent_card list',
            'from_name': '小谷', 'agent_id': creds['agent_id'],
            'id': f'card-list-{int(time.time())}', 'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        await asyncio.sleep(3)
        print("📋 Agent Card 列表：")
        for _ in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                if 'content' in data:
                    print(f"  {data['content']}")
            except asyncio.TimeoutError:
                break
        print()

        # 2. 给全员发大厅 @mention
        print("📤 大厅广播点名（看谁在线能回复）：")
        await asyncio.sleep(2)
        payload = {
            'type': 'message', 'content': '@小开 @爱泰 @小周 @泰虾 @小爱 inbox收发测试 - 大家收到请回复 @小谷',
            'from_name': '小谷', 'agent_id': creds['agent_id'],
            'id': f'lobby-broad-{int(time.time())}', 'ts': time.time(),
        }
        await ws.send(json.dumps(payload))
        print("  已发，等 15 秒收回复...")

        for i in range(15):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1)
                data = json.loads(msg)
                mt = data.get('type', '')
                fn = data.get('from_name', '?')
                ct = data.get('content', '')
                if mt == 'broadcast':
                    print(f"  📩 [{fn}]: {ct[:150]}")
                elif mt == 'ack':
                    pass  # skip acks
                elif mt == 'error':
                    print(f"  ❌ [{fn}]: {data.get('error','')}")
                elif ct:
                    print(f"  📩 [{i}] {mt} {fn}: {ct[:200]}")
            except asyncio.TimeoutError:
                pass

        print("\n✅ 测试完成")

asyncio.run(test())
