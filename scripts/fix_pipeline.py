#!/usr/bin/env python3
"""修复 R69：注册小周 agent card + 重置管线重跑"""
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
        if c: print(f"  📨 {c[:300]}")
    
    client = WsBridgeClient(ws_url=WS_URL, app_id=APP_ID, agent_id=AGENT_ID, name=BOT_NAME, auto_reconnect=False)
    client.on_message = on_msg
    print("🔄 连接 ws-bridge...")
    await client.connect(); await asyncio.sleep(2)
    
    # 1) Reset the broken workspace
    await send_cmd(client, "!workspace_reset", "重置工作室", 4)
    
    # 2) Register 小周 agent card
    await send_cmd(client, '!agent_card_set 小周 role=review skills=code-review,report', "注册小周卡片", 4)
    
    # 3) Register 泰虾 agent card (for qa later)
    await send_cmd(client, '!agent_card_set 泰虾 role=qa skills=test-automation,report', "注册泰虾卡片", 4)
    
    # 4) Register 爱泰 agent card (for dev)
    await send_cmd(client, '!agent_card_set 爱泰 role=dev skills=implement-code', "注册爱泰卡片", 4)
    
    # 5) Check cards
    await send_cmd(client, "!agent_card_list", "查卡片", 4)
    
    # 6) Start pipeline fresh
    await send_cmd(client, "!pipeline_start R69", "启动管线", 8)
    
    await client.disconnect()
    print("\n🔌 完成")

asyncio.run(main())
