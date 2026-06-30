#!/usr/bin/env python3
"""Test broadcast via WS Bridge as admin."""
import asyncio
import json
import os
import time
import sys

sys.path.insert(0, "/home/hermes/.hermes/home/hermes-ws-bridge")

async def main():
    import websockets
    
    ws_url = os.environ.get("WS_BRIDGE_URL", "ws://localhost:8765")
    agent_id = os.environ.get("WS_BRIDGE_AGENT_ID", "test-agent-001")
    app_id = os.environ.get("WS_BRIDGE_APP_ID", "ws-bridge")
    
    print(f"Connecting to {ws_url}...")
    ws = await websockets.connect(ws_url, ping_interval=20, ping_timeout=10)
    print("Connected! Sending auth...")
    
    # Auth
    await ws.send(json.dumps({
        "type": "auth",
        "app_id": app_id,
        "agent_id": agent_id,
        "name": os.environ.get("WS_BRIDGE_BOT_NAME", "test-bot"),
    }))
    
    # Wait for auth response
    raw = await asyncio.wait_for(ws.recv(), timeout=10)
    resp = json.loads(raw)
    print(f"Auth response: {resp}")
    
    if resp.get("type") == "auth_ok":
        print("Authenticated as admin!")
        
        # Send broadcast to all
        await ws.send(json.dumps({
            "type": "message",
            "content": f"🌉 互联互通测试：{os.environ.get('WS_BRIDGE_BOT_NAME', 'test-bot')} 已连入 WS Bridge！请回复确认 over",
            "to": "*",
            "id": f"test-{time.time()}",
            "ts": time.time(),
        }))
        print("Test broadcast sent!")
        
        # Wait a bit for any responses
        print("Waiting for responses...")
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                msg = json.loads(raw)
                print(f"<< {msg}")
        except asyncio.TimeoutError:
            print("No more messages received (timeout)")
    else:
        print(f"Auth failed: {resp}")
    
    await ws.close()

asyncio.run(main())
