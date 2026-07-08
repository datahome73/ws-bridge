#!/usr/bin/env python3
"""小爱 inbox 测试（回复到小谷收件箱）"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    my_inbox = f"_inbox:{my_id}"

    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        await asyncio.wait_for(ws.recv(), timeout=5)
        print(f"✅ 认证通过\n")

        print(f"📤 [小爱] inbox（指定回复到小谷收件箱）...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': '_inbox:ws_c47032fa1f67',
            'content': '📋 inbox测试 - 小爱好，现在需要你也走 inbox 通道测试。收到后请回复到 _inbox:ws_f26e585f6479（小谷收件箱） @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'inbox-xa-{int(time.time())}', 'ts': time.time(),
        }))
        for _ in range(3):
            try:
                m = await asyncio.wait_for(ws.recv(), timeout=2)
                d = json.loads(m)
                if d.get('type') == 'ack':
                    print(f"   ✅ ACK sent={d.get('sent',0)}")
                    break
            except: break

        print("⏳ 监听 60s...")
        for i in range(40):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                data = json.loads(msg)
                ch = data.get('channel','')
                fn = data.get('from_name','?')
                ct = data.get('content','')
                if ch == my_inbox:
                    print(f"\n🎯 [小谷收件箱][{fn}]: {ct[:200]}")
                    break
                elif fn not in ('小谷','系统',''):
                    print(f"📩 [{fn}]: {ct[:120]}")
            except: pass

        print(f"\n✅ 完成")

asyncio.run(test())
