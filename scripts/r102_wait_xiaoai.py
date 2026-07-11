"""R102 Step 6: 等待小爱部署完成"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
import importlib.util
spec = importlib.util.spec_from_file_location(
    "ws_client",
    "/opt/data/ws-bridge/clients/python/ws_client.py"
)
ws_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_client)

WsBridgeClient = ws_client.WsBridgeClient
load_creds = ws_client.load_creds

received_messages = []

async def main():
    name = "小谷"
    creds = load_creds(name)
    print(f"✅ 小谷 / {creds['agent_id'][:16]}...")

    def on_message(msg):
        received_messages.append(msg)
        content = msg.get("content", "")
        from_name = msg.get("from_name", "?")
        ts = msg.get("ts", 0)
        print(f"  << [{from_name}] {content[:500]}")

    client = WsBridgeClient(
        name=name,
        api_key=creds["api_key"],
        agent_id=creds["agent_id"],
        auto_reconnect=False,
        on_message=on_message,
    )

    connected = await client.connect()
    if not connected:
        print("❌ 连接失败")
        return

    print("✅ 已连接！等候小爱消息...")

    # 等待 90 秒看有没有新消息
    deadline = time.time() + 90
    while time.time() < deadline:
        await asyncio.sleep(2)

    print(f"\n📦 共收到 {len(received_messages)} 条消息")
    for i, m in enumerate(received_messages):
        c = m.get("content", "")[:300]
        fn = m.get("from_name", "?")
        print(f"\n  [{i}] {fn}: {c}")

    await client.disconnect()
    print("✅ 断开连接。")

if __name__ == "__main__":
    asyncio.run(main())
