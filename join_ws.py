"""Send !workspace_join via WS bridge websocket (to lobby)."""
import asyncio, json, time
import websockets

WS_URL = "wss://wsim.datahome73.cloud/ws"
API_KEY = "sk_ws_162c7a271cb54b80c042e7a849d5d000"
AGENT_ID = "ws_0bb747d3ea2a"

async def main():
    async with websockets.connect(WS_URL) as ws:
        # Auth
        await ws.send(json.dumps({"type": "auth", "api_key": API_KEY}))
        resp = await asyncio.wait_for(ws.recv(), timeout=10)
        auth_resp = json.loads(resp)
        print(f"Auth: {auth_resp.get('type')}")

        # Send workspace_join command to lobby (not inbox, so universal routing kicks in)
        msg = {
            "type": "message",
            "channel": "lobby",
            "content": "!workspace_join --workspace ws:ws_f26e5-R84-dev",
            "from_agent": AGENT_ID,
            "from_name": "爱泰",
            "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"Sent: {msg['content']}")

        # Wait for response
        await asyncio.sleep(3)
        try:
            while True:
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(resp)
                ct = str(data.get('content', ''))
                ch = data.get('channel', '')
                print(f"Got: channel={ch} type={data.get('type')} content={ct[:300]}")
        except asyncio.TimeoutError:
            print("Done (no more messages)")

asyncio.run(main())
