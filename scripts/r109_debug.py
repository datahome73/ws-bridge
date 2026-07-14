#!/usr/bin/env python3
"""Try !pipeline_start R109 with explicit async error catching."""
import asyncio, json, os, traceback, sys

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    
    import websockets
    try:
        async with websockets.connect(WS_URL, max_size=2**20, ping_interval=10, ping_timeout=5) as ws:
            await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
            resp = await asyncio.wait_for(ws.recv(), timeout=15)
            j = json.loads(resp)
            print(f"AUTH: {j.get('type')} ({j.get('display_name')})")

            # Send command
            await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": "!pipeline_start R109"}))
            print("SENT: !pipeline_start R109")

            # Listen with very long timeout
            while True:
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=30)
                    d = json.loads(resp)
                    ct = str(d.get("content",""))
                    err = d.get("error","")
                    print(f"\n[{d.get('type')}] ch={d.get('channel','')}")
                    if ct and ct != "None": print(f"  content: {ct}")
                    if err: print(f"  ERROR: {err}")
                except asyncio.TimeoutError:
                    print("DONE (no more responses)")
                    break
    except websockets.exceptions.ConnectionClosed as e:
        # If we get here without seeing a response, there was an issue
        print(f"\nCONNECTION CLOSED ({e.code}: {e.reason})")
        print("This means the server did NOT send a successful response")
        sys.exit(1)

asyncio.run(main())
