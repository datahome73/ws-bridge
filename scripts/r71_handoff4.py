"""Handoff step4→step5 and check status."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:500]
    print(f'  [{msg.get("from_name","?")}] {c[:500]}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='需求分析师', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(5)

    # Check git for 小周's commit
    print('=== STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # Handoff step4→step5
    print('\n=== HANDOFF step4→step5 ===')
    # Need to find 小周's commit SHA first
    await client.send_message('!step_handoff step4')
    await asyncio.sleep(8)

    print('\n=== STATUS AFTER ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    print('\n=== KEY ===')
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['step4', 'step5', '当前', '管线状态', '交接', '成员', '完成']):
            print(f'[{m.get("from_name","?")}] {c[:400]}')
    await client.disconnect()

asyncio.run(main())
