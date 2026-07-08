#!/usr/bin/env python3
"""点名 + 抓取在线 bot 的实时 agent_id"""
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

        # 点名小爱（她在线已知），抓她 agent_id
        print("📤 点名 @小爱 ...")
        await asyncio.sleep(1.5)
        await ws.send(json.dumps({
            'type': 'message',
            'content': '点名 @小爱 收到请回复',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'rollcall-xiaoai-{int(time.time())}', 'ts': time.time(),
        }))

        seen = {}
        for _ in range(20):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                data = json.loads(msg)
                if data.get('type') == 'broadcast':
                    fn = data.get('from_name', '?')
                    aid = data.get('agent_id', '?')
                    ct = data.get('content', '')
                    if fn not in seen and fn not in ('小谷', '系统'):
                        seen[fn] = aid
                        print(f"  📩 [{fn}] agent_id={aid}: {ct[:100]}")
            except asyncio.TimeoutError:
                pass

        print(f"\n📊 捕获到 {len(seen)} 个在线 bot:")
        for fn, aid in seen.items():
            print(f"  {fn}: {aid}")

        # 用捕获到的真实 agent_id 发 inbox
        print("\n📤 用真实 agent_id 发 inbox：")
        for name, aid in seen.items():
            if name == '小谷' or name == '系统' or aid == '?' or aid == my_id:
                continue
            inbox_ch = f"_inbox:{aid}"
            await asyncio.sleep(2)
            await ws.send(json.dumps({
                'type': 'message', 'channel': inbox_ch,
                'content': f'📋 收件箱测试 - 小谷→{name}，这条发到你收件箱，收到请回复 @小谷',
                'from_name': '小谷', 'agent_id': my_id,
                'id': f'inbox-{name}-{int(time.time())}', 'ts': time.time(),
            }))
            for _ in range(5):
                try:
                    r = await asyncio.wait_for(ws.recv(), timeout=2)
                    d = json.loads(r)
                    if d.get('type') == 'ack':
                        sent = d.get('sent', 0)
                        print(f"  ✅ {name:6s} → {inbox_ch}: ACK sent={sent}")
                        if sent > 0:
                            print(f"     🎉 投递成功！{name} 收到了 inbox 消息")
                        break
                    elif d.get('type') == 'error':
                        print(f"  ❌ {name:6s}: {d.get('error','')}")
                        break
                except asyncio.TimeoutError:
                    break

        print("\n✅ 测试完成")

asyncio.run(test())
