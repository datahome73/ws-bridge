"""Handoff step2→step3 now that workspace is set."""
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

    # Handoff step2→step3
    print('=== HANDOFF step2→step3 ===')
    await client.send_message('!step_handoff step2 --output 833d558')
    await asyncio.sleep(8)

    # Status
    print('\n=== STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # Report
    print('\n' + '=' * 55)
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['成员', 'step2', 'step3', '当前', '管线状态', 'step', '当前', 'handoff']):
            print(f'[{m.get("from_name","?")}] {c[:400]}')

    await client.disconnect()

asyncio.run(main())
