#!/usr/bin/env python3
"""关 R69-dev + 建新工作室 + 启动管线"""
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

    # 1) Close R69-dev
    await send_cmd(client, '!close_workspace ws:01KT6E4D-R69-dev', "关 R69-dev", 4)

    # 2) Create workspace with ALL members
    await send_cmd(client, '!create_workspace R69-dev --owner 小谷 --members 小爱,小开,小周,泰虾,爱泰', "建全成员工作室", 5)

    # 3) Start pipeline
    await send_cmd(client, '!pipeline_start R69', "启动管线", 10)

    await client.disconnect()
    print("\n🔌 完成")

asyncio.run(main())
