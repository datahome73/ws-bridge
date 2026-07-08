"""Quick test of both fixes after full cleanup."""
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

async def send(client, cmd, wait=6):
    print(f'\n>>> {cmd}')
    await client.send_message(cmd)
    await asyncio.sleep(wait)

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')

    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='\u5c0f\u8c37', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    print('Connected\n')
    await asyncio.sleep(2)

    # Clean
    await send(client, '!workspace_reset', 4)
    await send(client, '!pipeline_status', 4)

    # Create workspace
    await send(client, '!create_workspace V-test --members \u5c0f\u8c37,\u5c0f\u7231,\u5c0f\u5f00,\u7231\u6cf0,\u5c0f\u5468,\u6cf0\u867e', 5)

    # Start pipeline - Fix 1 test
    await send(client, '!pipeline_start R70', 8)

    # Status check
    await send(client, '!pipeline_status', 5)

    # Check results
    all_text = '\n'.join(m.get('content','') for m in received)

    print('\n' + '=' * 50)
    if '\u590d\u7528' in all_text:
        print('\u2705 Fix 1 WORKING: pipeline reused existing workspace')
    else:
        print('\u274c Fix 1 NOT working: still trying to create new workspace')

    if '\u6210\u5458' in all_text:
        for m in received:
            if '\u6210\u5458' in m.get('content',''):
                print(f'  Member line: {m.get("content","")[:200]}')

    await client.disconnect()

asyncio.run(main())
