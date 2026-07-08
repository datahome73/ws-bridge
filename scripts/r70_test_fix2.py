"""Test Fix 2: step_complete scope bug fix."""
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

async def send(client, cmd, wait=5):
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
    await asyncio.sleep(1)

    # Create ws + start pipeline
    await send(client, '!create_workspace R70-scope --members \u5c0f\u8c37,\u5c0f\u7231,\u5c0f\u5f00,\u7231\u6cf0,\u5c0f\u5468,\u6cf0\u867e', 5)
    await send(client, '!pipeline_start R70', 8)

    # Advance via handoff to reach step where we can test step_complete
    await send(client, '!step_handoff step2 --output 0636aba --summary "R70\u4fee\u590d\u6d4b\u8bd5"', 5)
    await send(client, '!step_handoff step3 --output 0636aba', 5)
    await send(client, '!step_handoff step4 --output 0636aba', 5)

    # NOW test step_complete (was broken before Fix 2)
    print('\n=== TESTING FIX 2: step_complete with --summary ===')
    await send(client, '!step_complete step5 --output 0636aba --summary "R70\u4fee\u590d\u9a8c\u8bc1\u901a\u8fc7 --summary\u53c2\u6570\u6b63\u5e38"', 6)
    await send(client, '!pipeline_status', 4)

    # Check for the error
    has_bug = False
    for m in received:
        c = m.get('content', '')
        if '\u6267\u884c\u5931\u8d25' in c and 'step_config' in c:
            has_bug = True
            print(f'\n  ❌ BUG STILL PRESENT: {c[:300]}')

    if has_bug:
        print('\n  ❌ Fix 2 NOT working - step_config bug still there')
    else:
        print('\n  ✅ Fix 2 WORKING - no step_config error')

    # Clean up
    await send(client, '!workspace_reset', 4)
    await client.disconnect()
    print(f'\n=== {len(received)} msgs ===')

if __name__ == '__main__':
    asyncio.run(main())
