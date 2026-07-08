"""Start R70 pipeline - correct syntax."""
import asyncio
import json
import os
import sys

sys.path.insert(0, "/opt/data/ws-bridge/clients/python")
from ws_client import WsBridgeClient

received = []

def on_message(msg):
    received.append(msg)
    c = msg.get("content", json.dumps(msg, ensure_ascii=False))[:800]
    print(f"  [{msg.get('from_name','?')}] {c}")

async def send_and_wait(client, cmd, wait=6):
    print(f"\n➡️ {cmd}")
    await client.send_message(cmd)
    await asyncio.sleep(wait)

async def main():
    ws_url = os.environ.get("WS_BRIDGE_URL")
    agent_id = os.environ.get("WS_BRIDGE_AGENT_ID")
    app_id = os.environ.get("WS_BRIDGE_APP_ID")

    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name="小谷", on_message=on_message)
    ok = await client.connect()
    if not ok: return
    print("✅ Connected\n")
    await asyncio.sleep(1)

    # Use correct syntax: !pipeline_start R70
    await send_and_wait(client, "!pipeline_start R70", 8)
    
    # Check pipeline status
    await send_and_wait(client, "!pipeline_status", 6)

    # Print only new/important results
    for m in received:
        c = m.get("content", "")
        if any(kw in c for kw in ["管线", "pipeline", "R70", "活跃", "Step", "点名", "rollcall", "已创建", "工作区"]):
            if "未知命令" not in c and "当前无活跃管线" not in c:
                print(f"📌 {c[:800]}")

    await client.disconnect()
    print(f"\n=== {len(received)} msgs ===")

if __name__ == "__main__":
    asyncio.run(main())
