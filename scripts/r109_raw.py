#!/usr/bin/env python3
"""Raw WebSocket test - capture ALL bytes before close."""
import asyncio, json, os

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    
    import websockets
    ws = await websockets.connect(WS_URL, max_size=2**20, ping_interval=10, ping_timeout=5, close_timeout=2)
    try:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        print(f"AUTH: {json.loads(resp).get('type')}")

        await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": "!pipeline_start R109"}))
        print("SENT: !pipeline_start R109")

        # Try to receive, catch close
        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=10)
                d = json.loads(resp)
                print(f"RECV type={d.get('type')} ct={str(d.get('content',''))[:300]}")
            except websockets.exceptions.ConnectionClosed as e:
                print(f"CLOSE: code={e.code} reason={e.reason}")
                break
            except asyncio.TimeoutError:
                print("TIMEOUT - still alive, sending ping")
                await ws.send(json.dumps({"type": "ping"}))
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
    finally:
        await ws.close()

asyncio.run(main())
