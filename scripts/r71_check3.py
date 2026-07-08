"""Check R71 exactly what's stuck - workspace members, pipeline step state."""
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
    if not ok: return
    await asyncio.sleep(4)

    # Check pipeline status
    print('=== !pipeline_status ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # Print fresh messages only
    print('\n=== FRESH RESPONSES ===')
    for m in received:
        c = m.get('content', '')[:400]
        if c and ('管线状态' in c or '成员' in c or 'step' in c or '小周' in c or '爱泰' in c or '泰虾' in c):
            print(f'[{m.get("from_name","?")}] {c}')

    await client.disconnect()

asyncio.run(main())
