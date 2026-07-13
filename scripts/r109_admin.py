#!/usr/bin/env python3
"""Try !pipeline_start via _admin channel."""
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
        print(f"AUTH: {json.loads(resp).get('type')}")

        # Try _admin channel
        await ws.send(json.dumps({"type": "message", "channel": "_admin", "content": "!pipeline_start R109"}))
        print("SENT: !pipeline_start R109 → _admin")

        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=15)
                d = json.loads(resp)
                ct = str(d.get("content",""))
                ch = d.get("channel","")
                print(f"[{d.get('type')}] ch={ch}")
                if ct and ct != "None":
                    print(f"  {ct[:500]}")
            except asyncio.TimeoutError:
                print("DONE")
                break
            except Exception as e:
                print(f"CLOSED: {e}")
                break

asyncio.run(main())
