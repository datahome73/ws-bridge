#!/usr/bin/env python3
"""Check pipeline status and coordinate remaining steps."""
import asyncio, json, os, time
import websockets

CREDS = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
WS_URL = "wss://wsim.datahome73.cloud/ws"
MY_AGENT_ID = CREDS['agent_id']
MY_API_KEY = CREDS['api_key']
MY_NAME = "小谷"
WORKSPACE_ID = "ws:ws_f26e5-R76-dev"

async def wait_and_collect(ws, timeout=8):
    msgs = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            content = data.get("content", "")
            if content:
                print(f"📩 [{data.get('from_name','?')}]: {content[:600]}")
                msgs.append(data)
        except asyncio.TimeoutError:
            pass
    return msgs

async def main():
    async with websockets.connect(WS_URL, max_size=2**20) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": MY_API_KEY}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert resp.get("type") == "auth_ok"
        print("✅ Auth OK\n")

        # 查 pipeline status
        for cmd in ["!pipeline_status R76", "!agent_card list"]:
            await ws.send(json.dumps({
                "type": "message", "channel": "_admin",
                "content": cmd, "from_name": MY_NAME,
                "agent_id": MY_AGENT_ID,
                "id": f"cmd-{int(time.time())}", "ts": time.time(),
            }))
            await asyncio.sleep(1)

        msgs = await wait_and_collect(ws, 10)

asyncio.run(main())
