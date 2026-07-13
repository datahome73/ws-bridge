"""R102: 通知泰虾更新网关插件 — 加 '✅ ' 通用前缀"""
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

TAIXIA_AID = "ws_eab784ac7652"
received_messages = []

async def main():
    name = "小谷"
    creds = load_creds(name)
    print(f"✅ 小谷 / {creds['agent_id'][:16]}...")

    def on_message(msg):
        received_messages.append(msg)
        content = msg.get("content", "")
        from_name = msg.get("from_name", "?")
        print(f"  << [{from_name}]: {content[:300]}")

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
        "泰虾，麻烦更新一下网关插件。\n\n"
        "`gateway-plugin/__init__.py` 的 `_determine_channel()` 加了一个"
        "通用前缀 `\"✅ \"`，任何以 ✅ 开头的消息都走 `_inbox:server`。"
        "之前 `✅ R102 部署完成` 这种消息没被 `✅ 完成` 匹配到，"
        "仍然走了 `_system`。\n\n"
        "改动只有一行：\n"
        "```python\n"
        "or started_content.startswith(\"✅ \")\n"
        "```\n\n"
        "在 `失败 ❌` 后面加这一行就行。\n"
        "改完 reload + 重启。\n"
        "改好回 已完成 ✅"
    )

    print("═══ 发送给泰虾 ═══")
    await client.send_message(
        content,
        channel=f"_inbox:{TAIXIA_AID}",
    )
    print("📨 已发送，等泰虾确认...")

    deadline = time.time() + 60
    while time.time() < deadline:
        await asyncio.sleep(2)
        for m in received_messages:
            c = m.get("content", "")
            if "已完成 ✅" in c:
                print("\n✅ 泰虾确认完成")
                return
    print("\n⏰ 超时未收到确认")

    await client.disconnect()

asyncio.run(main())
