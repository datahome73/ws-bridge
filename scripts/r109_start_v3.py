#!/usr/bin/env python3
"""Ping-pong keepalive approach to send pipeline_start."""
import asyncio, json, os

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    
    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=10, ping_timeout=5) as ws:
        # Auth
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        data = json.loads(resp)
        print(f"AUTH: type={data.get('type')} agent_id={str(data.get('agent_id',''))[:16]}")
        if data.get("type") != "auth_ok":
            return

        # Send ping to test connection
        await ws.send(json.dumps({"type": "ping"}))
        pong = await asyncio.wait_for(ws.recv(), timeout=5)
        print(f"PONG: {json.loads(pong)}")

        # Send pipeline_start
        payload = {"type": "message", "channel": "lobby", "content": "!pipeline_start R109"}
        await ws.send(json.dumps(payload))
        print(f"SENT: !pipeline_start R109")

        # Listen for responses with ping keepalive
        for i in range(30):
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(resp)
                t = data.get("type","?")
                ch = data.get("channel","")
                ct = str(data.get("content",""))[:200]
                print(f"[{i+1}] type={t} channel={ch}")
                if ct:
                    print(f"    content: {ct}")
            except asyncio.TimeoutError:
                # Send ping to keep alive
                await ws.send(json.dumps({"type": "ping"}))
                pass

asyncio.run(main())
