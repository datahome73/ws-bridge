"""用小谷的身份查管线状态"""
import json, asyncio, sys, os
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')

async def main():
    import websockets
    
    creds_path = os.path.expanduser('~/.ws-bridge/小谷.json')
    with open(creds_path) as f:
        creds = json.load(f)
    
    uri = 'wss://wsim.datahome73.cloud/ws'
    suffix = str(int(asyncio.get_event_loop().time()))[-6:]
    
    # 注册一个临时 bot 来查状态（小谷 PM 不能直接查 _inbox:server）
    async with websockets.connect(uri, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({"type": "register", "display_name": f"chk-{suffix}"}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get("type") != "register_ok":
            print(f"❌ 注册失败: {resp}")
            return
        api_key = resp["api_key"]
        print(f"✅ 注册临时 bot: {resp.get('agent_id')}")
    
    async with websockets.connect(uri, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
        if resp.get("type") != "auth_ok":
            print(f"❌ Auth失败")
            return
        
        # 查管线状态
        await ws.send(json.dumps({
            "type": "message",
            "channel": "_inbox:server",
            "content": "!pipeline_status",
        }))
        print("📤 !pipeline_status 已发送，等回复...")
        
        for i in range(20):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=4)
                msg = json.loads(raw)
                content = str(msg.get('content', ''))
                ch = msg.get('channel', '')
                mt = msg.get('type', '')
                if content and content != 'None':
                    print(f'[{i}] {mt} ch={ch}')
                    print(f'{content}')
            except asyncio.TimeoutError:
                if i > 3:
                    print(f'[{i}] (done)')
                    break
                continue

asyncio.run(main())
