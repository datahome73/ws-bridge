#!/usr/bin/env python3
"""Inbox 消息监听 — 等待小爱回复 R76 Step6"""
import asyncio, json, os, time
import websockets

CREDS = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
MY_AGENT_ID = CREDS['agent_id']
MY_API_KEY = CREDS['api_key']
my_inbox = f"_inbox:{MY_AGENT_ID}"

async def main():
    async with websockets.connect("wss://wsim.datahome73.cloud/ws", max_size=2**20) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": MY_API_KEY}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert resp.get("type") == "auth_ok"
        print("✅ Auth OK — 监听收件箱...")

        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                d = json.loads(raw)
                ch = d.get("channel", "")
                content = d.get("content", "")
                sid = d.get("agent_id", "")
                sender = d.get("from_name", "?")
                if content and ch == my_inbox and sid != MY_AGENT_ID:
                    print(f"\n📩 [收件箱][{sender}]: {content[:600]}")
                elif content:
                    print(f"📩 [{sender}]: {content[:300]}")
            except asyncio.TimeoutError:
                pass

        print("\n监听结束")

asyncio.run(main())
