"""Test R70 fix: pipeline with all 6 members."""
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

    # Step 1: Create workspace with all 6 members
    await send(client, '!create_workspace R70-test --members \u5c0f\u8c37,\u5c0f\u7231,\u5c0f\u5f00,\u7231\u6cf0,\u5c0f\u5468,\u6cf0\u867e', 5)

    # Step 2: Start pipeline
    await send(client, '!pipeline_start R70', 6)

    # Step 3: Check pipeline status - look at member list
    await send(client, '!pipeline_status', 5)

    # Step 4: Do rollcall
    await send(client, '!rollcall_next arch --context "R70\u9a8c\u8bc1\u6d4b\u8bd5"', 5)

    # Step 5: Handoff to test step_complete fix
    await send(client, '!step_handoff step2 --output 0636aba --summary "R70\u4fee\u590d\u6d4b\u8bd5"', 5)
    await send(client, '!step_handoff step3 --output 0636aba', 5)
    await send(client, '!pipeline_status', 4)

    # Test step_complete with --summary (was broken before fix)
    print('\n=== Testing !step_complete with --summary (was F-22) ===')
    await send(client, '!step_complete step4 --output 0636aba --summary "R70\u4fee\u590d\u9a8c\u8bc1\u901a\u8fc7" --artifact-url https://github.com/datahome73/ws-bridge/blob/0636aba/server/handler.py', 5)

    await send(client, '!pipeline_status', 4)

    # Print member lines and key results
    print('\n' + '=' * 60)
    print('KEY RESULTS')
    print('=' * 60)
    for m in received:
        c = m.get('content', '')
        f = m.get('from_name', '?')
        if any(kw in c for kw in ['\u6210\u5458', 'session', 'R70', '\u590d\u7528', 'pipeline', 'Step', 'step']):
            if '\u672a\u77e5\u547d\u4ee4' not in c and '\u5f53\u524d\u65e0\u6d3b\u8dc3' not in c:
                print(f'  [{f}] {c[:500]}')

    # Close workspace
    await send(client, '!workspace_reset', 4)

    await client.disconnect()
    print(f'\n=== {len(received)} msgs ===')

if __name__ == '__main__':
    asyncio.run(main())
