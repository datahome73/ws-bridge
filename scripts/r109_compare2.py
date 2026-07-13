#!/usr/bin/env python3
"""Compare: normal cmd stays alive, pipeline_start closes."""
import asyncio, json, os

CRED_PATH = os.path.expanduser("~/.ws-bridge/小谷.json")
WS_URL = "wss://wsim.datahome73.cloud/ws"

async def test_cmd(ws, cmd, label):
    await ws.send(json.dumps({"type": "message", "channel": "lobby", "content": cmd}))
    print(f"SENT: {label}")
    
    while True:
        try:
            resp = await asyncio.wait_for(ws.recv(), timeout=5)
            d = json.loads(resp)
            print(f"  [{d.get('type')}] {str(d.get('content',''))[:150]}")
        except asyncio.TimeoutError:
            print(f"  (alive - no more responses)")
            return True
        except websockets.exceptions.ConnectionClosed as e:
            print(f"  ❌ CONNECTION CLOSED (code={e.code})")
            return False

async def main():
    creds = json.loads(open(CRED_PATH).read())
    api_key = creds["api_key"]
    
    import websockets
    async with websockets.connect(WS_URL, max_size=2**20, ping_interval=10, ping_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        print(f"AUTH: {json.loads(resp).get('type')}\n")

        # Test 1: normal command
        print("--- Test 1: !agent_card_list (normal command) ---")
        alive = await test_cmd(ws, "!agent_card_list", "!agent_card_list")
        print(f"Connection after test 1: {'🟢 ALIVE' if alive else '🔴 CLOSED'}\n")
        
        if not alive:
            print("Cannot continue - connection lost")
            return
        
        # Test 2: pipeline_start
        print("--- Test 2: !pipeline_start R109 ---")
        alive = await test_cmd(ws, "!pipeline_start R109", "!pipeline_start R109")
        print(f"Connection after test 2: {'🟢 ALIVE' if alive else '🔴 CLOSED'}\n")

asyncio.run(main())
