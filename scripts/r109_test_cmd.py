#!/usr/bin/env python3
"""Test if ! commands work at all from lobby."""
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
        print("AUTH OK")

        # Try !my_id — simplest command
        await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": "!my_id"}))
        print("SENT: !my_id")

        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=8)
                d = json.loads(resp)
                print(f"[{d.get('type')}] ch={d.get('channel','')} error={d.get('error','')} content={str(d.get('content',''))[:300]}")
            except asyncio.TimeoutError:
                print("DONE")
                break
            except Exception as e:
                print(f"CLOSED: {e}")
                break

asyncio.run(main())
