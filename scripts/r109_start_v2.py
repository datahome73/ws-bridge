#!/usr/bin/env python3
"""Send !pipeline_start R109 and capture full response."""
import asyncio, json, os, sys

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    agent_id = creds["agent_id"]

    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=30, ping_timeout=10) as ws:
        # Auth
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        data = json.loads(resp)
        print(f"AUTH: {json.dumps(data, ensure_ascii=False)[:200]}")
        if data.get("type") != "auth_ok":
            return

        # Send pipeline start - try lobby
        payload = {"type": "message", "channel": "lobby", "content": "!pipeline_start R109"}
        await ws.send(json.dumps(payload))
        print(f"SENT: !pipeline_start R109 → lobby")
        
        # Wait for response - longer timeout
        for i in range(5):
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(resp)
                print(f"RESP #{i+1}: type={data.get('type')} channel={data.get('channel','')} content={str(data.get('content',''))[:200]}")
            except asyncio.TimeoutError:
                print(f"DONE: no more responses after {i+1} waits")
                break

asyncio.run(main())
