"""Query pipeline status via inbox:server (no role check)."""
import asyncio, json, time
import websockets

WS_URL = "wss://wsim.datahome73.cloud/ws"
API_KEY = "sk_ws_162c7a271cb54b80c042e7a849d5d000"
AGENT_ID = "ws_0bb747d3ea2a"

async def main():
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": API_KEY}))
        resp = await asyncio.wait_for(ws.recv(), timeout=10)
        auth_resp = json.loads(resp)
        print(f"Auth: {auth_resp.get('type')}")

        msg = {
            "type": "message",
            "channel": "_inbox:server",
            "content": "!pipeline_status R84",
            "from_agent": AGENT_ID,
            "from_name": "爱泰",
            "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"Sent: {msg['content']}")

        await asyncio.sleep(3)
        try:
            while True:
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(resp)
                ct = str(data.get('content', ''))
                ch = data.get('channel', '')
                print(f"[{ch}] {ct[:400]}")
        except asyncio.TimeoutError:
            print("Done")

asyncio.run(main())
