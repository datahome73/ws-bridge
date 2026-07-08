#!/usr/bin/env python3
"""关闭 R68 工作室 + 重建 R69 全成员工作室"""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
sys.path.insert(0, '/opt/data/ws-bridge')
from ws_client import WsBridgeClient

WS_URL = os.environ.get("WS_BRIDGE_URL", "wss://wsim.datahome73.cloud/ws")
AGENT_ID = os.environ.get("WS_BRIDGE_AGENT_ID", "01KT6E4DXGYVEX95PKEHCQE1RF")
APP_ID = os.environ.get("WS_BRIDGE_APP_ID", "298621237")
BOT_NAME = os.environ.get("WS_BRIDGE_BOT_NAME", "小谷")

async def send_cmd(client, cmd, label, wait=4):
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

    # 1) List workspaces to find R68 ID
    await send_cmd(client, '!list_workspaces', "查工作室列表", 5)

    # 2) Try to close R68 (common patterns)
    await send_cmd(client, '!close_workspace ws:01KT6E4D-R68-dev', "关 R68-dev", 4)
    
    # 3) Also try closing old R69 workspace
    await send_cmd(client, '!close_workspace ws:01KT6E4D-R69-dev', "关旧 R69", 4)

    # 4) Now create workspace with all members
    await send_cmd(client, '!create_workspace R69-full --owner 小谷 --members 小爱,小开,小周,泰虾,爱泰', "建全成员工作室", 5)

    # 5) Start pipeline
    await send_cmd(client, '!pipeline_start R69', "启动管线", 8)

    await client.disconnect()
    print("\n🔌 完成")

asyncio.run(main())
