"""Check R71 pipeline status and arch (小开) progress."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:400]
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
    await asyncio.sleep(5)  # drain backlog

    # Check status
    print('=== !pipeline_status ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # Report only key status messages
    print('\n' + '=' * 55)
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['管线状态', 'step2', 'step3', '小开', 'arch', '当前', '❌', 'Provider', 'auth', '认证', 'FAILED']):
            print(f'  [{m.get("from_name","?")}] {c[:400]}')

    await client.disconnect()

asyncio.run(main())
