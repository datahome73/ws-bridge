#!/usr/bin/env python3
"""用小爱真实 agent_id 测试 inbox 投递"""
import asyncio, json, websockets, os, time

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']
    uri = 'wss://wsim.datahome73.cloud/ws'

    async with websockets.connect(uri, max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"✅ 小谷认证通过")

        # 用小爱真实 agent_id 发 inbox
        real_xiaoai = "ws_c47032fa1f67"
        inbox_ch = f"_inbox:{real_xiaoai}"
        
        print(f"\n📤 发送 inbox 到小爱 (agent_id={real_xiaoai})...")
        await asyncio.sleep(2)
        await ws.send(json.dumps({
            'type': 'message', 'channel': inbox_ch,
            'content': '📋 inbox收件箱测试 - 小谷→小爱，用真实agent_id发送，收到请回复 @小谷',
            'from_name': '小谷', 'agent_id': my_id,
            'id': f'inbox-real-xa-{int(time.time())}', 'ts': time.time(),
        }))
        
        for _ in range(5):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(msg)
                t = data.get('type','')
                if t == 'ack':
                    sent = data.get('sent',0)
                    print(f"   ✅ ACK sent={sent}")
                    if sent > 0:
                        print(f"   🎉 投递成功！小爱有 {sent} 连接在线")
                elif t == 'error':
                    print(f"   ❌ 错误: {data.get('error')}")
            except asyncio.TimeoutError:
                print(f"   ⏱️ ACK 超时")
                break

        # 等小爱回复
        print("\n⏳ 等小爱回复...")
        for _ in range(20):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                data = json.loads(msg)
                t = data.get('type','')
                fn = data.get('from_name','?')
                ct = data.get('content','')
                aid = data.get('agent_id','?')
                if t == 'broadcast' and fn != '小谷' and fn != '系统':
                    print(f"   📩 [{fn}] aid={aid[:20]}: {ct[:150]}")
            except asyncio.TimeoutError:
                pass
        
        print(f"\n✅ 测试完成")

asyncio.run(test())
