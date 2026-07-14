#!/usr/bin/env python3
"""Send !pipeline_start R109 via WS inbox to kick off the pipeline."""
import asyncio, json, os, sys

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"

async def main():
    # Load credentials
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    agent_id = creds["agent_id"]

    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=10) as ws:
        # Auth
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(resp)
        if data.get("type") != "auth_ok":
            print(f"❌ Auth failed: {data}")
            return
        print(f"✅ Auth OK as {agent_id[:16]}...")

        # Send pipeline start
        payload = {
            "type": "message",
            "channel": "lobby",
            "content": "!pipeline_start R109"
        }
        await ws.send(json.dumps(payload))
        print("✅ !pipeline_start R109 sent to lobby")
        
        # Wait a moment for ACK
        try:
            ack = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"📩 Response: {json.dumps(json.loads(ack), ensure_ascii=False)[:200]}")
        except asyncio.TimeoutError:
            print("⏱️ No immediate response (normal)")

asyncio.run(main())
