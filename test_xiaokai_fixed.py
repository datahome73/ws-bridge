#!/usr/bin/env python3
"""小开 inbox 双向测试（修复后）"""
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
            'content': '📋 inbox双向测试 - 小谷→小开，收到请回复 @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'inbox-xk-{int(time.time())}', 'ts': time.time(),
        }))

        # 等 ACK
        got_ack = False
        sent_count = 0
        for _ in range(5):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                if data.get('type') == 'ack':
                    sent_count = data.get('sent', 0)
                    got_ack = True
                    print(f"   ✅ ACK: sent={sent_count}")
                    break
            except asyncio.TimeoutError:
                break

        # 2. 等小开回复（45s）
        print("   ⏳ 等小开回复...")
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
                    if fn == '小开':
                        replied = True
            except asyncio.TimeoutError:
                pass

        if replied:
            print(f"\n🎉 小开回复了！双向测试通过 ✅")
        elif got_ack and sent_count > 0:
            print(f"\n⚠️ 小开 inbox 投递成功（sent={sent_count}），但 45s 内未回复")
        else:
            print(f"\n❌ 小开 inbox 投递失败")

        # 3. 再发大厅点名确认
        print(f"\n📤 大厅点名 @小开 ...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message',
            'content': '@小开 📋 收到 inbox 消息了吗？回复确认 @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'lobby-xk-{int(time.time())}', 'ts': time.time(),
        }))
        for i in range(20):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                data = json.loads(msg)
                if data.get('type') == 'broadcast':
                    fn = data.get('from_name', '?')
                    ct = data.get('content', '')
                    if fn not in ('小谷', '系统', ''):
                        print(f"   [{fn}]: {ct[:150]}")
            except asyncio.TimeoutError:
                pass

        print(f"\n✅ 完成")

asyncio.run(test())
