#!/usr/bin/env python3
"""Test basic message send vs command send."""
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

        # Send a plain text message
        await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": "测试消息 R109"}))
        print("SENT: plain text")
        
        for i in range(3):
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
                d = json.loads(resp)
                print(f"  [{d.get('type')}] {str(d.get('content',''))[:200]}")
            except asyncio.TimeoutError:
                print("  (no response / connection alive)")
                break
            except Exception as e:
                print(f"  CLOSED after plain text: {e}")
                return
        
        # Now try !pipeline_start
        await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": "!pipeline_start R109"}))
        print("SENT: !pipeline_start R109")
        
        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
                d = json.loads(resp)
                ct = str(d.get("content",""))[:500]
                print(f"[{d.get('type')}] ch={d.get('channel','')} error={d.get('error','')}")
                if ct and ct != "None": print(f"  content: {ct}")
            except asyncio.TimeoutError:
                print("  (timeout)")
                continue
            except Exception as e:
                print(f"  CLOSED after command: {e}")
                break

asyncio.run(main())
