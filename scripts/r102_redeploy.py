"""R102 重部署：去掉 _inbox:_system，仅 _inbox:server"""
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
        print(f"  << [{from_name}]: {content[:400]}")

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
        "【R102 定向修复 🛠️ 重部署】\n\n"
        "小爱好！之前 R102 发到 _inbox:_system 导致广播风暴，"
        "现已修复：\n"
        "  - 去掉 _inbox:_system 通道支持\n"
        "  - 只保留 _inbox:server + 定向 _send_to_agent\n"
        "  - 派活→目标bot，ACK/完成→PM，不会广播\n"
        "  - ws_client.send_message() 新增 to_agent 参数\n"
        "  - to_agent 提取兼容顶层字段和内嵌 JSON\n\n"
        "改动文件：\n"
        "  server/main.py（2处 _handle_server_relay: channel 判断 + to_agent 提取）\n"
        "  clients/python/ws_client.py（send_message 新增 to_agent 参数）\n\n"
        "请重新部署上线，部署后回复 已完成 ✅"
    )

    print(f"\n--- 通过 _inbox:server + to_agent 发送给 {XIAOAI_NAME} ---")
    # R102 的 _handle_server_relay 返回 True 后不发 ACK，所以 No ACK 是正常的
    # 消息已通过 _send_to_agent 投递到目标
    msg_id = await client.send_message(
        content,
        channel="_inbox:server",
        to_agent=XIAOAI_AID,
    )
    if not msg_id:
        print("⚠️ 未收到 ACK（R102 定向投递无 ACK，但消息可能已送达）")
    else:
        print(f"✅ 已发送！msg_id={msg_id[:16]}...")

    # 等待回复
    print(f"\n⏳ 等待 {XIAOAI_NAME} 回复（最长 120 秒）...")
    deadline = time.time() + 120
    while time.time() < deadline:
        await asyncio.sleep(2)
        for m in received_messages:
            c = m.get("content", "")
            fn = m.get("from_name", "")
            if c and ("已完成" in c or "收到" in c):
                print(f"\n📩 [{fn}]: {c[:500]}")
                break
        else:
            continue
        break
    else:
        print("\n⏰ 超时未收到回复（消息已发送，小爱上线后会看到）")

    await asyncio.sleep(2)
    print(f"\n📦 总共收到 {len(received_messages)} 条消息")
    await client.disconnect()
    print("✅ 断开连接。完成！")

if __name__ == "__main__":
    asyncio.run(main())
