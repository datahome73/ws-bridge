#!/usr/bin/env python3
"""启动 R69 管线 — 连接 ws-bridge 服务器并发送 !pipeline_start R69"""
import asyncio
import json
import os
import sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
sys.path.insert(0, '/opt/data/ws-bridge')

from ws_client import WsBridgeClient

WS_URL = os.environ.get("WS_BRIDGE_URL", "wss://wsim.datahome73.cloud/ws")
AGENT_ID = os.environ.get("WS_BRIDGE_AGENT_ID", "01KT6E4DXGYVEX95PKEHCQE1RF")
APP_ID = os.environ.get("WS_BRIDGE_APP_ID", "298621237")
BOT_NAME = os.environ.get("WS_BRIDGE_BOT_NAME", "小谷")

async def main():
    """Connect, send !pipeline_start R69, wait for response, disconnect."""
    received = []

    def on_message(msg):
        received.append(msg)
        content = msg.get("content", json.dumps(msg, ensure_ascii=False))
        print(f"[{msg.get('type','?')}] {content[:200]}")

    client = WsBridgeClient(
        ws_url=WS_URL,
        app_id=APP_ID,
        agent_id=AGENT_ID,
        name=BOT_NAME,
        on_message=on_message,
        auto_reconnect=False,
    )

    print(f"🔄 连接 ws-bridge ({WS_URL})...")
    ok = await client.connect()
    if not ok:
        print("❌ 连接失败")
        return

    print(f"✅ 已连接 (agent_id={AGENT_ID})")

    # 等待认证完成
    await asyncio.sleep(2)

    # 发送 !pipeline_start R69
    print("\n🚀 发送: !pipeline_start R69")
    msg_id = await client.send_message("!pipeline_start R69")
    if msg_id:
        print(f"✅ 已发送 (msg_id={msg_id[:8]})")
    else:
        print("❌ 发送失败")

    # 等待响应
    await asyncio.sleep(10)

    # 检查是否收到响应
    if received:
        print(f"\n📨 收到 {len(received)} 条消息:")
        for i, msg in enumerate(received[-5:], 1):
            content = msg.get("content", "") or msg.get("error", "")
            if content:
                print(f"  {i}. {content[:200]}")
    else:
        print("\n⚠️ 未收到响应消息（可能命令已执行但无回显）")

    await client.disconnect()
    print("🔌 已断开连接")

if __name__ == "__main__":
    asyncio.run(main())
