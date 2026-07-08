#!/usr/bin/env python3
"""双向 inbox 测试：小开"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']

    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"✅ 小谷认证通过\n")

        # 1. 发 inbox 给小开
        print("=" * 50)
        print("📤 [小开] inbox 发送...")
        print("=" * 50)
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': '_inbox:ws_3f7cdd736c1c',
            'content': '@小开 📋 双向测试 - 小谷→小开 inbox，收到后请回复 @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'inbox-xk-{int(time.time())}', 'ts': time.time(),
        }))

        # 等 ACK
        for _ in range(5):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                if data.get('type') == 'ack':
                    print(f"   ✅ ACK: sent={data.get('sent',0)}")
                    break
            except asyncio.TimeoutError:
                break

        # 2. 等小开回复（45s）
        print("   ⏳ 等小开回复中（最多 45s）...")
        replied = False
        for i in range(30):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                data = json.loads(msg)
                mt = data.get('type', '')
                fn = data.get('from_name', '?')
                ct = data.get('content', '')
                ch = data.get('channel', '')
                
                if mt == 'broadcast' and fn not in ('小谷', '系统', ''):
                    print(f"   [{i+1}s] [{fn}]: {ct[:150]}")
                    if '小开' in fn:
                        replied = True
            except asyncio.TimeoutError:
                pass

        if replied:
            print(f"\n🎉 小开已回复！双向测试通过 ✅")
        else:
            print(f"\n⚠️ 小开未回复（45s 超时）")

        # 3. 确认大厅可见
        print(f"\n📤 发大厅确认消息（让大宏可见）...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message',
            'content': f'📋 小开inbox测试: {"双向通 ✅" if replied else "未回复"}',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'result-{int(time.time())}', 'ts': time.time(),
        }))

        print(f"\n✅ 完成")

asyncio.run(test())
