"""Check R71 status - who's in workspace, who's online."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:500]
    print(f'  [{msg.get("from_name","?")}] {c}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='需求分析师', on_message=on_message)
    ok = await client.connect()
    if not ok:
        print("CONNECT FAILED")
        return
    await asyncio.sleep(5)

    # Check pipeline status
    print('=== PIPELINE STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # Check agent card list
    print('\n=== AGENT CARD LIST ===')
    await client.send_message("!agent_card list")
    await asyncio.sleep(6)

    # Print ALL unique messages
    print('\n' + '=' * 55)
    seen = set()
    for m in received:
        c = m.get('content', '')[:500]
        if c and c not in seen:
            seen.add(c)
            if any(kw in c for kw in ['成员', '在线', 'agent', 'Agent', '卡片', '卡', '角色', '🟢', '🔴', '缺失', '不在']):
                print(f'[{m.get("from_name","?")}] {c}')

    await client.disconnect()

asyncio.run(main())
