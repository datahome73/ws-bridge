#!/usr/bin/env python3
"""获取 小周 的 agent_id 并发送到收件箱"""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
sys.path.insert(0, '/opt/data/ws-bridge')
from ws_client import WsBridgeClient

WS_URL = os.environ.get("WS_BRIDGE_URL", "wss://wsim.datahome73.cloud/ws")
AGENT_ID = os.environ.get("WS_BRIDGE_AGENT_ID", "01KT6E4DXGYVEX95PKEHCQE1RF")
APP_ID = os.environ.get("WS_BRIDGE_APP_ID", "298621237")
BOT_NAME = os.environ.get("WS_BRIDGE_BOT_NAME", "小谷")

async def main():
    msgs = []
    def on_msg(m):
        msgs.append(m)
        c = m.get("content","") or m.get("error","") or json.dumps(m,ensure_ascii=False)
        print(f"[{m.get('type','?')}] {c[:400]}")
    
    client = WsBridgeClient(ws_url=WS_URL, app_id=APP_ID, agent_id=AGENT_ID, name=BOT_NAME, auto_reconnect=False)
    client.on_message = on_msg
    print("🔄 连接...")
    await client.connect()
    await asyncio.sleep(2)
    
    # Get agent card list (shows IDs)
    print("\n📋 !agent_card_list")
    await client.send_message("!agent_card_list")
    await asyncio.sleep(4)
    
    # Get workspace info
    print("\n📋 !list_workspaces")
    await client.send_message("!list_workspaces")
    await asyncio.sleep(4)

    # Try to add 小周 to workspace - send to _admin channel
    print("\n📋 检查可用的 agent_status")
    await client.send_message("!agent_status 小周")
    await asyncio.sleep(4)
    
    await client.disconnect()
    print("\n🔌 完成")

asyncio.run(main())
