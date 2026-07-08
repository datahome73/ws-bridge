#!/usr/bin/env python3
"""验证 R69 部署状态"""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
sys.path.insert(0, '/opt/data/ws-bridge')
from ws_client import WsBridgeClient

WS_URL = os.environ.get("WS_BRIDGE_URL", "wss://wsim.datahome73.cloud/ws")
AGENT_ID = os.environ.get("WS_BRIDGE_AGENT_ID", "01KT6E4DXGYVEX95PKEHCQE1RF")
APP_ID = os.environ.get("WS_BRIDGE_APP_ID", "298621237")
BOT_NAME = os.environ.get("WS_BRIDGE_BOT_NAME", "小谷")

async def send_cmd(client, cmd, label, wait=5):
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

    # 1) Test R69 new command: workspace_reset
    await send_cmd(client, '!workspace_reset', "测试 !workspace_reset (R69)", 4)

    # 2) Test pipeline_status (should no longer error with 'pstate')
    await send_cmd(client, '!pipeline_status', "测试 !pipeline_status", 4)

    # 3) Test list_workspaces (was broken pre-R69)
    await send_cmd(client, '!list_workspaces', "测试 !list_workspaces", 4)

    # 4) Check agent cards
    await send_cmd(client, '!agent_card_list', "查卡片", 4)

    await client.disconnect()
    print("\n🔌 完成")

asyncio.run(main())
