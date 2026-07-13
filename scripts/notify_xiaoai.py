#!/usr/bin/env python3
"""Send inbox message to 小爱 asking to merge + deploy the fix."""
import asyncio, json, os

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"
XIAOAI_ID = "ws_c47032fa1f67"  # 小爱/ops

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    
    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=10, ping_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        d = json.loads(resp)
        print(f"AUTH: {d.get('type')}")

        # Send to 小爱's inbox
        content = (
            "收到 ✅ R109 fix 已推送 main (796dfed)\n"
            "请合并部署到生产环境：\n"
            "1. git pull origin main\n"
            "2. docker build -t ws-bridge:r109-fix .\n"
            "3. 重启容器\n\n"
            "部署成功后回复 ✅，我再启动 !pipeline_start R109"
        )
        payload = {
            "type": "message",
            "channel": f"_inbox:{XIAOAI_ID}",
            "content": content
        }
        await ws.send(json.dumps(payload))
        print(f"SENT inbox to 小爱")

        # Wait for ACK
        for i in range(5):
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=10)
                d = json.loads(resp)
                print(f"[{d.get('type')}] {str(d.get('content',''))[:200]}")
            except asyncio.TimeoutError:
                print("DONE")
                break

asyncio.run(main())
