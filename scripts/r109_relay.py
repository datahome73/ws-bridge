#!/usr/bin/env python3
"""Send !pipeline_start R109 via _inbox:server to_agent routing."""
import asyncio, json, os

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    agent_id = creds.get("agent_id", "ws_f26e585f6479")

    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=10, ping_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        print(f"AUTH OK: {json.loads(resp).get('display_name')}")

        # Try sending !pipeline_start as a relay message to_agent=server
        # The server's _handle_server_relay will process to_agent
        payload = {
            "type": "message",
            "channel": "_inbox:server",
            "content": json.dumps({
                "to_agent": agent_id,
                "content": "!pipeline_start R109"
            })
        }
        await ws.send(json.dumps(payload))
        print("SENT: !pipeline_start R109 via relay")

        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=15)
                d = json.loads(resp)
                ct = str(d.get("content",""))
                print(f"[{d.get('type')}] ch={d.get('channel','')}")
                if ct and ct != "None": print(f"  {ct[:500]}")
            except asyncio.TimeoutError:
                print("DONE (timeout)")
                break
            except Exception as e:
                print(f"CLOSED: {e}")
                break

asyncio.run(main())
