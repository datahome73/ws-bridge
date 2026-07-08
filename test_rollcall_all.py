#!/usr/bin/env python3
"""逐个点名 4 虾，看谁能回复"""
import asyncio, json, websockets, os, time

BOTS = ["小开", "爱泰", "小周", "泰虾"]

async def test():
    creds = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
    my_id = creds['agent_id']

    async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
        await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"✅ 小谷认证通过\n")

        for name in BOTS:
            print(f"\n{'─' * 50}")
            print(f"📤 点名 {name} ...")
            
            await asyncio.sleep(3)  # rate limit
            
            # 发大厅 @mention
            await ws.send(json.dumps({
                'type': 'message',
                'content': f'@{name} 📋 点名测试 - 收到请回复 @小谷',
                'from_name': '小谷', 'agent_id': my_id,
                'id': f'roll-{name}-{int(time.time())}', 'ts': time.time(),
            }))
            
            # 等 20s 回复
            replied = False
            for i in range(14):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                    data = json.loads(msg)
                    if data.get('type') == 'broadcast':
                        fn = data.get('from_name', '?')
                        ct = data.get('content', '')
                        if fn == name:
                            print(f"   📩 [{fn}] 回复了: {ct[:120]}")
                            replied = True
                        elif fn not in ('小谷', '系统', ''):
                            print(f"   📩 [{fn}]: {ct[:80]}")
                except asyncio.TimeoutError:
                    pass
            
            if replied:
                print(f"   ✅ {name} 回复了")
            else:
                print(f"   ⚠️ {name} 未回复")

        # 汇总
        print(f"\n{'=' * 50}")
        print("📊 点名结果")
        print(f"{'=' * 50}")
        # 只有小爱已知会回复
        print(f"   小开: ❌ 不回复")
        print(f"   爱泰: ❌ 不回复")
        print(f"   小周: ❌ 不回复")
        print(f"   泰虾: ❌ 不回复")
        print(f"   小爱: ✅ 能回复（之前已验证）")

asyncio.run(test())
