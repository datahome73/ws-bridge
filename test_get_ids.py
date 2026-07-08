#!/usr/bin/env python3
"""登录各 bot 抓取真实 agent_id"""
import asyncio, json, websockets, os, time

BOTS = ["小开", "爱泰", "小周", "泰虾", "小爱", "小谷"]

async def get_real_id(name):
    try:
        creds = json.load(open(os.path.expanduser(f'~/.ws-bridge/{name}.json')))
        async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
            await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
            if resp.get('type') == 'auth_ok':
                real_id = resp['agent_id']
                return (name, real_id, True, creds['api_key'][:20])
            else:
                return (name, creds.get('agent_id','?'), False, "auth failed")
    except Exception as e:
        return (name, "?", False, str(e)[:60])

async def test():
    print("=" * 60)
    print("🔍 获取各 bot 真实 agent_id")
    print("=" * 60)
    
    results = {}
    for name in BOTS:
        result = await get_real_id(name)
        n, rid, ok, info = result
        status = "✅" if ok else "❌"
        print(f"  {status} {n:6s}: agent_id={rid}  ({info})")
        results[n] = rid if ok else None
        await asyncio.sleep(2)
    
    print("\n📋 真实 agent_id 表：")
    for name, aid in results.items():
        print(f"  {name:6s} = {aid}")
    
    print(f"\n✅ 获取完成")

asyncio.run(test())
