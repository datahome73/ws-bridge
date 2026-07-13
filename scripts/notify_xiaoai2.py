#!/usr/bin/env python3
"""Ask 小爱 to deploy the second fix."""
import asyncio, json, os

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"
XIAOAI_ID = "ws_c47032fa1f67"

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    
    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=10, ping_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        print(f"AUTH: {json.loads(resp).get('type')}")

        content = (
            "收到 ✅ 还有一个 bug 要修复\n"
            "commands/pipeline.py 缺少 _ensure_pipeline_manager import，\n"
            "导致 !pipeline_start 调用时报 NameError\n\n"
            "已推送 main: 14d534d\n"
            "请重新部署：git pull && docker build -t ws-bridge:r109-fix2 . && 重启\n\n"
            "部署后回复 ✅"
        )
        payload = {"type": "message", "channel": f"_inbox:{XIAOAI_ID}", "content": content}
        await ws.send(json.dumps(payload))
        print("SENT to 小爱")

        for i in range(5):
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=8)
                print(f"[{json.loads(resp).get('type')}]")
            except asyncio.TimeoutError:
                print("DONE")
                break

asyncio.run(main())
