#!/usr/bin/env python3
"""激活 R69 管线 + 通知小周审查"""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
sys.path.insert(0, '/opt/data/ws-bridge')
from ws_client import WsBridgeClient

WS_URL = os.environ.get("WS_BRIDGE_URL", "wss://wsim.datahome73.cloud/ws")
AGENT_ID = os.environ.get("WS_BRIDGE_AGENT_ID", "01KT6E4DXGYVEX95PKEHCQE1RF")
APP_ID = os.environ.get("WS_BRIDGE_APP_ID", "298621237")
BOT_NAME = os.environ.get("WS_BRIDGE_BOT_NAME", "小谷")

async def send_cmd(client, cmd, label, wait=6):
    print(f"\n🚀 [{label}] {cmd}")
    mid = await client.send_message(cmd)
    if mid: print(f"  ✅ 已发送")
    else: print(f"  ⚠️ 无 ACK")
    await asyncio.sleep(wait)

async def main():
    msgs = []
    def on_msg(m):
        msgs.append(m)
        c = m.get("content","") or m.get("error","") or ""
        if c: print(f"  📨 {c[:500]}")
    
    client = WsBridgeClient(ws_url=WS_URL, app_id=APP_ID, agent_id=AGENT_ID, name=BOT_NAME, auto_reconnect=False)
    client.on_message = on_msg
    print("🔄 连接 ws-bridge...")
    await client.connect(); await asyncio.sleep(2)

    # 1) Activate pipeline to re-send MSG_SET_ACTIVE_CHANNEL
    await send_cmd(client, '!pipeline_activate R69', "激活管线 → 通知全员新工作室", 6)

    # 2) Check status
    await send_cmd(client, '!pipeline_status R69', "查状态", 6)

    # 3) Try step_handoff step4 with context — this will try inbox send to review
    await send_cmd(client, '!step_handoff step4 --output eb29a73 --summary "编码完成，请小周审查代码"', "推进到审查", 8)

    # 4) Check status again
    await send_cmd(client, '!pipeline_status R69', "最终状态", 6)

    await client.disconnect()
    print("\n🔌 完成")

asyncio.run(main())
