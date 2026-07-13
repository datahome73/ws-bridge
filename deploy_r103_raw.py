"""Send R103 deploy request to 小爱 via raw WebSocket (no client ACK)."""
import asyncio, json, os, sys

# Load credentials
creds_path = '/opt/data/home/.ws-bridge/小谷.json'
with open(creds_path) as f:
    creds = json.load(f)

API_KEY = creds['api_key']
AGENT_ID = creds['agent_id']

AI_ID = "ws_c47032fa1f67"

async def main():
    import websockets
    uri = "wss://wsim.datahome73.cloud/ws"
    async with websockets.connect(uri) as ws:
        # Auth
        auth_msg = json.dumps({"type": "auth", "api_key": API_KEY})
        await ws.send(auth_msg)
        auth_resp = await asyncio.wait_for(ws.recv(), timeout=5)
        print(f"Auth: {auth_resp[:80]}")

        # Send deploy request to 小爱 inbox
        payload = {
            "type": "message",
            "content": "【R103 部署】小爱，R103 Step 4 审查通过 ✅，已合并到 main (404d39a)。前端 templates.py 有改动，需重建 Docker 镜像部署。",
            "from": AGENT_ID,
            "channel": f"_inbox:{AI_ID}",
            "to_agent": AI_ID,
        }
        await ws.send(json.dumps(payload))
        print("Deploy request sent to 小爱 ✅")

        # Wait a moment for confirmation
        await asyncio.sleep(2)

asyncio.run(main())
