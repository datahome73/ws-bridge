"""通过临时 bot 通知小爱部署"""
import json, asyncio, sys, os
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')

async def main():
    import websockets
    import time
    
    uri = 'wss://wsim.datahome73.cloud/ws'
    suffix = str(int(time.time()))[-6:]
    
    # 1. Register temp bot
    async with websockets.connect(uri, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({"type": "register", "display_name": f"dep-{suffix}"}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get("type") != "register_ok":
            print(f"❌ 注册失败: {resp}")
            return
        api_key = resp["api_key"]
        agent_id = resp["agent_id"]
        print(f"✅ 注册: {agent_id}")
    
    # 2. Fresh connection to send message to 小爱
    async with websockets.connect(uri, max_size=2**20, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if resp.get("type") != "auth_ok":
            print(f"❌ Auth失败: {resp}")
            return
        print(f"✅ 连接")
        
        # Send 小爱 deploy request (via _inbox:server with to_agent)
        ai_id = "ws_c47032fa1f67"
        content = (
            "小爱，请执行 **R109 Step 6 — 合并部署归档**\n\n"
            "1. PR: dev → main\n"
            "2. 重建 Docker 镜像\n"
            "3. 重启容器\n"
            "4. 更新 TODO.md\n\n"
            "测试报告：26/37 通过，失败项已记录 backlog，后续轮次修复。"
        )
        
        await ws.send(json.dumps({
            "type": "message",
            "channel": f"_inbox:{ai_id}",
            "content": content,
            "to_agent": ai_id,
        }))
        print("📤 已通知小爱部署")
        
        # Wait for ACK or reply
        for i in range(20):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                msg = json.loads(raw)
                mt = msg.get('type', '?')
                ch = msg.get('channel', '')
                content = str(msg.get('content', ''))
                if content and content != 'None':
                    print(f'\n[{i}] {mt} ch={ch}')
                    print(f'  {content[:800]}')
            except asyncio.TimeoutError:
                if i > 5:
                    break
                continue

asyncio.run(main())
