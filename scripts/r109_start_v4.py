#!/usr/bin/env python3
"""Send !pipeline_start R109 and capture any error."""
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

        # Send pipeline_start
        await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": "!pipeline_start R109"}))
        print("SENT: !pipeline_start R109")
        
        # Collect ALL responses until close or timeout
        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=15)
                data = json.loads(resp)
                ct = str(data.get("content",""))[:500]
                ch = data.get("channel","")
                err = data.get("error","")
                print(f"[{data.get('type')}] ch={ch}")
                if ct and ct != "None":
                    print(f"  content: {ct}")
                if err:
                    print(f"  ERROR: {err}")
            except asyncio.TimeoutError:
                print("TIMEOUT (connection still alive)")
                continue
            except Exception as e:
                print(f"CLOSED: {e}")
                break

asyncio.run(main())
