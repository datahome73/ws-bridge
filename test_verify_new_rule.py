#!/usr/bin/env python3
"""验证新规则 + inbox 给爱泰"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    my_inbox = f"_inbox:{my_id}"

    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"✅ 小谷认证通过")

        # 验证：给自己发 inbox → 应该被拒
        print(f"\n🔍 验证新规则：发给自己 inbox...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': my_inbox,
            'content': '自检',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'self-{int(time.time())}', 'ts': time.time(),
        }))
        for _ in range(3):
            try:
                m = await asyncio.wait_for(ws.recv(), timeout=2)
                d = json.loads(m)
                if d.get('type') == 'error':
                    print(f"   ✅ 新规则生效: {d.get('error')}")
                    break
                elif d.get('type') == 'ack':
                    print(f"   ⚠️ 旧规则还在（ACK sent={d.get('sent')}）")
            except: break

        # 发 inbox 给爱泰
        print(f"\n📤 inbox 给爱泰（回复到小谷收件箱）...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': '_inbox:ws_0bb747d3ea2a',
            'content': f'📋 inbox测试 - 爱泰收到后，请直接回复到 _inbox:ws_f26e585f6479（小谷的收件箱），我会在收件箱里等 @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'at3-{int(time.time())}', 'ts': time.time(),
        }))
        for _ in range(3):
            try:
                m = await asyncio.wait_for(ws.recv(), timeout=2)
                d = json.loads(m)
                if d.get('type') == 'ack':
                    print(f"   ✅ ACK sent={d.get('sent',0)}")
            except: break

        # 监听
        print("⏳ 监听 60s（收件箱 + 大厅）...")
        for i in range(40):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                data = json.loads(msg)
                mt = data.get('type', '')
                ch = data.get('channel', '')
                fn = data.get('from_name', '?')
                ct = data.get('content', '')
                if mt == 'broadcast':
                    if ch == my_inbox:
                        print(f"\n🎯 [小谷收件箱][{fn}]: {ct[:200]}")
                    elif ch.startswith('_inbox:'):
                        print(f"📩 [{ch}][{fn}]: {ct[:100]}")
                    elif fn not in ('小谷', '系统', ''):
                        print(f"📩 [{fn}]: {ct[:120]}")
            except:
                pass

        print(f"\n✅ 完成")

asyncio.run(test())
