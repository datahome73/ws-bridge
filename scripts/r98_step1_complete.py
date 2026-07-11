"""Send ✅ 完成 to _inbox:server — direct WebSocket."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main():
    # Load credentials
    cred_path = os.path.expanduser("~/.ws-bridge/小谷.json")
    with open(cred_path) as f:
        cred = json.load(f)
    agent_id = cred["agent_id"]
    api_key = cred["api_key"]

    # Connect via websockets
    import websockets
    uri = "wss://wsim.datahome73.cloud/ws"
    async with websockets.connect(uri) as ws:
        # Auth
        await ws.send(json.dumps({
            "type": "auth",
            "agent_id": agent_id,
            "api_key": api_key,
        }))
        resp = await ws.recv()
        auth_resp = json.loads(resp)
        print(f"  ← auth: {auth_resp.get('type')} — {auth_resp.get('status', '')}")

        # Send completion
        content = "✅ R98 完成 — 标注 WORK_PLAN 已审核通过，已推 dev 4d5f3c3"
        msg_payload = {
            "type": "message",
            "content": content,
            "channel": "_inbox:server",
            "ts": asyncio.get_event_loop().time() if hasattr(asyncio, 'get_event_loop') else 0,
        }
        await ws.send(json.dumps(msg_payload))
        print(f"  → sent: {content}")
        print(f"  → channel: _inbox:server")

        # Wait a moment for any response
        try:
            ack = await asyncio.wait_for(ws.recv(), timeout=3)
            ack_data = json.loads(ack)
            print(f"  ← ack: {json.dumps(ack_data, ensure_ascii=False)[:120]}")
        except asyncio.TimeoutError:
            print("  ← (no response within 3s — OK, message sent)")

    print("\n✅ Step 1 完成信号已发送到 _inbox:server")
    print("   AutoRouter 将检测到 ✅ 完成并派活 Step 2 → arch（小开）")


if __name__ == "__main__":
    asyncio.run(main())
