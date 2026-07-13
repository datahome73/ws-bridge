#!/usr/bin/env python3
"""Test if other ! commands also close connection."""
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

        # !agent_card_list — known working command
        await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": "!agent_card_list"}))
        print("SENT: !agent_card_list")

        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=8)
                d = json.loads(resp)
                ct = str(d.get("content",""))[:200]
                print(f"RECV type={d.get('type')} ct={ct}")
            except websockets.exceptions.ConnectionClosed as e:
                print(f"CLOSE: code={e.code}")
                break
            except asyncio.TimeoutError:
                print("TIMEOUT - still alive, sending ping")
                await ws.send(json.dumps({"type": "ping"}))

        # Now reconnect and try pipeline_start
        print("\n--- Reconnecting for pipeline_start ---")
        ws2 = await websockets.connect(WS_URL, max_size=2**20, ping_interval=10, ping_timeout=5, close_timeout=2)
        await ws2.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws2.recv(), timeout=15)
        print(f"AUTH: {json.loads(resp).get('type')}")

        await ws2.send(json.dumps({"type": "message", "channel": "lobby", "content": "!pipeline_start R109"}))
        print("SENT: !pipeline_start R109")

        while True:
            try:
                resp = await asyncio.wait_for(ws2.recv(), timeout=8)
                d = json.loads(resp)
                ct = str(d.get("content",""))[:300]
                print(f"RECV type={d.get('type')} ct={ct}")
            except websockets.exceptions.ConnectionClosed as e:
                print(f"CLOSE: code={e.code}")
                break
            except asyncio.TimeoutError:
                print("TIMEOUT")
                break
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        await ws.close()

asyncio.run(main())
