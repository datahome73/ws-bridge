#!/usr/bin/env python3
"""Capture close frame details."""
import asyncio, json, os

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]

    import websockets
    ws = await websockets.connect(WS_URL, max_size=2**20)
    await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
    resp = await asyncio.wait_for(ws.recv(), timeout=15)
    print(f"AUTH: {json.loads(resp).get('type')}")

    await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": "!pipeline_start R109"}))
    print("SENT")
    
    # Don't wrap in async with — catch close manually
    try:
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            d = json.loads(msg)
            print(f"RECV: {d.get('type')} ct={str(d.get('content',''))[:200]}")
    except websockets.exceptions.ConnectionClosedOK as e:
        print(f"\nCLOSE OK: code={e.code} rcvd={e.rcvd} sent={e.sent}")
        # Check if there was a response before close
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"\nCLOSE ERROR: code={e.code} rcvd={e.rcvd} sent={e.sent}")
    except asyncio.TimeoutError:
        print("\nTIMEOUT - connection still alive")

asyncio.run(main())
