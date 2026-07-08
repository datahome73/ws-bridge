#!/usr/bin/env python3
"""给爱泰发 inbox + 明确回复路由"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    my_inbox = f"_inbox:{my_id}"

    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"✅ 小谷认证通过\n")

        # 发 inbox 给爱泰，明确回复到小谷inbox
        print(f"📤 [爱泰] inbox（指定回复到 {my_inbox}）...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': '_inbox:ws_0bb747d3ea2a',
            'content': f'📋 inbox回复路由测试 - 爱泰收到后，请回复到 _inbox:ws_f26e585f6479 @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'inbox-at-rr-{int(time.time())}', 'ts': time.time(),
        }))
        for _ in range(5):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                if data.get('type') == 'ack':
                    print(f"   ✅ ACK: sent={data.get('sent',0)}")
                    break
            except asyncio.TimeoutError:
                break

        # 等回复（可能从小谷的 inbox 来）
        print("   ⏳ 等爱泰回复到小谷的收件箱...")
        for i in range(30):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                data = json.loads(msg)
                mt = data.get('type', '')
                ch = data.get('channel', '')
                fn = data.get('from_name', '?')
                ct = data.get('content', '')

                if mt == 'broadcast':
                    if ch == my_inbox:
                        print(f"   📩 [小谷inbox][{fn}]: {ct[:200]}")
                    elif ch.startswith('_inbox:'):
                        print(f"   📩 [{ch}][{fn}]: {ct[:150]}")
                    elif fn not in ('小谷', '系统', ''):
                        print(f"   [{i+1}s][{fn}]: {ct[:120]}")
            except asyncio.TimeoutError:
                pass

        print(f"\n✅ 完成")

asyncio.run(test())
