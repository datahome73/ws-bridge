#!/usr/bin/env python3
"""Check agent cards and workspace state."""
import asyncio, json, os, time
import websockets

CREDS = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
WS_URL = "wss://wsim.datahome73.cloud/ws"
MY_AGENT_ID = CREDS['agent_id']
MY_API_KEY = CREDS['api_key']

async def main():
    async with websockets.connect(WS_URL, max_size=2**20) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": MY_API_KEY}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert resp.get("type") == "auth_ok"
        print(f"✅ Auth OK")

        # 查 Agent Cards
        await ws.send(json.dumps({
            "type": "message", "channel": "_admin",
            "content": "!agent_card list",
            "from_name": "小谷", "agent_id": MY_AGENT_ID,
            "id": f"cards-{int(time.time())}", "ts": time.time(),
        }))

        # 查 workspace 状态
        await ws.send(json.dumps({
            "type": "message", "channel": "_admin",
            "content": "!pipeline_status R76",
            "from_name": "小谷", "agent_id": MY_AGENT_ID,
            "id": f"status-{int(time.time())}", "ts": time.time(),
        }))

        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(raw)
                content = data.get("content", "")
                if content:
                    print(f"📩 [{data.get('from_name','?')}]: {content[:800]}")
            except asyncio.TimeoutError:
                pass

asyncio.run(main())
