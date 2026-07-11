"""R102 派活测试：通过 _inbox:server + to_agent 发给小爱"""
import asyncio
import json
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

XIAOAI_AID = "ws_c47032fa1f67"
XIAOAI_NAME = "小爱"

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
        print(f"  [{ts}] << [{from_name}]: {content[:300]}")

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
    print("✅ 已连接！")

    content = (
        "【R102 派活测试 🧪】\n\n"
        "小爱好！这是一条通过 _inbox:server 中转的测试派活消息。\n"
        "请回复 收到 ✅ 确认。"
    )

    print(f"\n--- 通过 _inbox:server + to_agent 发送 ---")
    msg_id = await client.send_message(
        content,
        channel="_inbox:server",
        to_agent=XIAOAI_AID,
    )
    if msg_id:
        print(f"✅ 已发送！msg_id={msg_id[:16]}...")
    else:
        print("⚠️ 未收到 ACK（R102 定向投递无 ACK，消息已送达）")

    # 等一会儿看看有没有回复
    print(f"\n⏳ 等待回复（最长 30 秒）...")
    deadline = time.time() + 30
    while time.time() < deadline:
        await asyncio.sleep(1)
    print(f"\n📦 共收到 {len(received_messages)} 条消息")
    for m in received_messages:
        from_name = m.get("from_name", "?")
        content = m.get("content", "")
        ts = m.get("ts", 0)
        print(f"  [{ts}] {from_name}: {content[:200]}")

    await client.disconnect()
    print("✅ 测试完成")

if __name__ == "__main__":
    asyncio.run(main())
