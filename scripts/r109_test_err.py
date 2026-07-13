#!/usr/bin/env python3
"""Show the actual error response for plain text messages."""
import asyncio, json, os

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    
    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=10, ping_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        d = json.loads(resp)
        print(f"AUTH: {json.dumps(d, ensure_ascii=False)}")

        # Send plain text
        await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": "test"}))
        print("SENT: test message")
        
        for i in range(3):
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
                d = json.loads(resp)
                print(f"RESP: {json.dumps(d, ensure_ascii=False)}")
            except asyncio.TimeoutError:
                print("  (no more responses)")
                break
            except Exception as e:
                print(f"CLOSED: {e}")
                break

asyncio.run(main())
