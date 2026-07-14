#!/usr/bin/env python3
"""Check 小谷's role and try to send command through inbox to_agent."""
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

        # Try !agent_card_get 小谷 to see role
        await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": "!agent_card_get 小谷"}))
        print("SENT: !agent_card_get 小谷")

        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=8)
                d = json.loads(resp)
                ct = str(d.get("content",""))
                err = d.get("error","")
                print(f"[{d.get('type')}]")
                if ct and ct != "None": print(f"  {ct[:500]}")
                if err: print(f"  ERROR: {err}")
            except asyncio.TimeoutError:
                print("DONE")
                break
            except Exception as e:
                print(f"CLOSED: {e}")
                break

asyncio.run(main())
