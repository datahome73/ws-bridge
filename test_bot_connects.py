#!/usr/bin/env python3
"""逐个连接各 bot 的 api_key 来获取实时 agent_id"""
import asyncio, json, websockets, os, time

BOT_CREDS = {
    "小爱": "~/.ws-bridge/小爱.json",
    "小开": "~/.ws-bridge/小开.json",
    "爱泰": "~/.ws-bridge/爱泰.json",
    "小周": "~/.ws-bridge/小周.json",
    "泰虾": "~/.ws-bridge/泰虾.json",
}

async def connect_bot(name, cred_path):
    try:
        creds = json.load(open(os.path.expanduser(cred_path)))
        async with websockets.connect('wss://wsim.datahome73.cloud/ws', max_size=2**20) as ws:
            await ws.send(json.dumps({'type': 'auth', 'api_key': creds['api_key']}))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
            if resp.get('type') == 'auth_ok':
                aid = resp.get('agent_id', '?')
                active = resp.get('active_channel', 'N/A')
                offline = resp.get('type') == 'auth_ok' and 'offline_messages' in str(resp)
                return (name, aid, active, "✅ 成功", None)
            else:
                return (name, creds.get('agent_id','?'), "?", f"❌ auth_ok=false: {resp.get('type')}", None)
    except Exception as e:
        err = str(e)
        # Try to get more info
        if "connect" in err.lower() or "refused" in err.lower():
            return (name, "?", "?", f"❌ 连接失败: {err}", None)
        return (name, "?", "?", f"❌ {err}", None)

async def test():
    print("=" * 60)
    print("🔌 逐个连接各 bot 获取实时 agent_id")
    print("=" * 60)
    
    for name, cred_path in BOT_CREDS.items():
        print(f"\n⏳ 连接 {name} ...")
        result = await connect_bot(name, cred_path)
        na, aid, active, status, _ = result
        print(f"   {status}")
        if aid != "?":
            print(f"   agent_id: {aid}")
            print(f"   活跃频道: {active}")
        await asyncio.sleep(2)  # avoid rate limit

asyncio.run(test())
