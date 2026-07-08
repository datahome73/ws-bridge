"""Quick test: just pipeline_start to check workspace reuse."""
import asyncio
import json
import os
import sys

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

    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='\u5c0f\u8c37', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    print('Connected\n')
    await asyncio.sleep(2)

    # Just send pipeline_start
    print('>>> !pipeline_start R70')
    await client.send_message('!pipeline_start R70')
    await asyncio.sleep(8)

    # Check status
    print('\n>>> !pipeline_status')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # Print key results
    print('\n' + '=' * 60)
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['\u590d\u7528', '\u5df2\u521b\u5efa', '\u6210\u5458', 'step2', '\u5f53\u524d']):
            print(f'  [{m.get("from_name","?")}] {c[:400]}')
        if '\u590d\u7528' in c:
            print(f'\n  \u2705 Fix 1 VERIFIED: {c[:200]}')
            break
    else:
        print('  \u274c Fix 1 NOT detected in output')

    await client.disconnect()

asyncio.run(main())
