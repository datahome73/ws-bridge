#!/usr/bin/env python3
"""Try pipeline_start on DEV server."""
import asyncio, json, os

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://ws-im-dev.datahome73.com/ws"

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    
    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=10, ping_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        print(f"AUTH: {json.loads(resp).get('type')}")

        # Check status first
        await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": "!pipeline_status"}))
        print("SENT: !pipeline_status")

        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=8)
                d = json.loads(resp)
                ct = str(d.get("content",""))
                print(f"[{d.get('type')}] {ct[:400]}")
            except asyncio.TimeoutError:
                break
            except Exception as e:
                print(f"CLOSED: {e}")
                break

asyncio.run(main())
