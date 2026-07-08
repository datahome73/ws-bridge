#!/usr/bin/env python3
"""推进 R69 管线：跳过 Step 2/3，推进到 Step 4 (审查)"""
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

async def send_and_wait(client, command, wait=8):
    """Send a command and collect responses."""
    received = []
    def on_message(msg):
        received.append(msg)
        content = msg.get("content", "") or msg.get("error", "")
        if content:
            print(f"  📨 {content[:300]}")

    client.on_message = on_message
    print(f"\n🚀 发送: {command}")
    msg_id = await client.send_message(command)
    if msg_id:
        print(f"  ✅ 已发送 (id={msg_id[:8]})")
    else:
        print(f"  ⚠️ 发送无 ACK（可能命令已执行但通道不同）")
    await asyncio.sleep(wait)
    return received

async def main():
    client = WsBridgeClient(
        ws_url=WS_URL, app_id=APP_ID, agent_id=AGENT_ID, name=BOT_NAME,
        auto_reconnect=False,
    )
    print("🔄 连接 ws-bridge...")
    ok = await client.connect()
    if not ok:
        print("❌ 连接失败"); return
    print("✅ 已连接\n")

    # Wait for auth
    await asyncio.sleep(2)

    # Step 1: Skip Step 2 (tech plan) — already committed at 7248bfc
    await send_and_wait(client, "!step_handoff step2 --output 7248bfc --summary \"技术方案完成: step_outputs扩展+_infer_artifact_url+收件箱模板增强\" --artifact-url https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R69/R69-tech-plan.md")

    await asyncio.sleep(3)

    # Step 2: Skip Step 3 (coding) — already committed at eb29a73
    await send_and_wait(client, "!step_handoff step3 --output eb29a73 --summary \"编码完成: ~47行净增 9个改动点 全handler.py\" --artifact-url https://github.com/datahome73/ws-bridge/commit/eb29a73")

    await asyncio.sleep(5)

    print("\n🔌 断开连接")
    await client.disconnect()
    print("✅ 已完成")

if __name__ == "__main__":
    asyncio.run(main())
