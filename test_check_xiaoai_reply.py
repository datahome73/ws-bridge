#!/usr/bin/env python3
"""检查小谷收件箱有没有小爱的回复"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    my_inbox = f"_inbox:{my_id}"

    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = await asyncio.wait_for(ws.recv(), timeout=5)
        print(f"✅ 认证通过")

        # 先检查自己的收件箱有没有离线消息
        offline = json.loads(resp).get('offline_messages', [])
        if offline:
            print(f"\n📬 有 {len(offline)} 条离线消息:")
            for m in offline:
                fn = m.get('from_name','?')
                ct = m.get('content','')
                ch = m.get('channel','')
                print(f"   [{ch}][{fn}]: {ct[:200]}")
        else:
            print(f"\n📭 无离线消息")

        # 发一条新消息问小爱
        print(f"\n📤 再发一条 inbox 给小爱...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': '_inbox:ws_c47032fa1f67',
            'content': '📋 小爱好，上一轮你回复我没收到。请再回一次这条，回复到 _inbox:ws_f26e585f6479（小谷收件箱） @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'inbox-xa2-{int(time.time())}', 'ts': time.time(),
        }))
        for _ in range(3):
            try:
                m = await asyncio.wait_for(ws.recv(), timeout=2)
                d = json.loads(m)
                if d.get('type') == 'ack':
                    print(f"   ✅ ACK sent={d.get('sent',0)}")
                    break
            except: break

        # 长时间监听
        print("⏳ 监听 60s（收件箱）...")
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
                    print(f"📩 [{fn}]: {ct[:100]}")
            except: pass

        print(f"\n✅ 完成")

asyncio.run(test())
