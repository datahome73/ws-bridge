#!/usr/bin/env python3
"""诊断 R69 管线状态 + 修复成员列表"""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
sys.path.insert(0, '/opt/data/ws-bridge')
from ws_client import WsBridgeClient

WS_URL = os.environ.get("WS_BRIDGE_URL", "wss://wsim.datahome73.cloud/ws")
AGENT_ID = os.environ.get("WS_BRIDGE_AGENT_ID", "01KT6E4DXGYVEX95PKEHCQE1RF")
APP_ID = os.environ.get("WS_BRIDGE_APP_ID", "298621237")
BOT_NAME = os.environ.get("WS_BRIDGE_BOT_NAME", "小谷")

async def main():
    client = WsBridgeClient(ws_url=WS_URL, app_id=APP_ID, agent_id=AGENT_ID, name=BOT_NAME, auto_reconnect=False)
    msgs = []
    client.on_message = lambda m: (msgs.append(m), print(f"  [{m.get('type','?')}] {m.get('content','')[:200]}"))
    
    print("🔄 连接...")
    await client.connect()
    await asyncio.sleep(2)
    
    # 1) 查管线状态
    print("\n📊 !pipeline_status R69")
    await client.send_message("!pipeline_status R69")
    await asyncio.sleep(3)
    
    # 2) 查 agent 列表看角色
    print("\n📋 !list_agents --role review")
    await client.send_message("!list_agents --role review")
    await asyncio.sleep(3)
    
    print("\n📋 !list_agents")
    await client.send_message("!list_agents")
    await asyncio.sleep(3)
    
    # 3) 查 agent_card_list
    print("\n📋 !agent_card_list")
    await client.send_message("!agent_card_list")
    await asyncio.sleep(3)

    # 4) 查 workspace 列表
    print("\n📋 !list_workspaces")
    await client.send_message("!list_workspaces")
    await asyncio.sleep(3)

    await client.disconnect()
    print("\n🔌 完成")

asyncio.run(main())
