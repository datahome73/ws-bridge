"""Clean up old pipeline then test fix."""
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

    # 1. Reset old pipeline
    print('=== Cleanup old pipeline ===')
    await send(client, '!workspace_reset', 4)
    await send(client, '!pipeline_status', 3)

    # 2. Create test workspace
    print('=== Create test workspace ===')
    await send(client, '!create_workspace R70-fix --members \u5c0f\u8c37,\u5c0f\u7231,\u5c0f\u5f00,\u7231\u6cf0,\u5c0f\u5468,\u6cf0\u867e', 5)

    # 3. Start pipeline - use direct command, skip WORK_PLAN check for now
    # Since R70 WORK_PLAN exists on dev, pipeline_start R70 should find it
    print('=== Start R70 pipeline ===')
    await send(client, '!pipeline_start R70', 8)

    # 4. Check status for member list
    print('=== Check pipeline status ===')
    await send(client, '!pipeline_status', 5)

    # Print all results
    print('\n' + '=' * 60)
    print('RESULTS')
    print('=' * 60)
    for m in received:
        c = m.get('content', '')
        f = m.get('from_name', '?')
        if any(kw in c for kw in ['\u590d\u7528', '\u5df2\u521b\u5efa', '\u6210\u5458', '\u590d\u7528', 'R70', '\u5f53\u524d']):
            print(f'  [{f}] {c[:500]}')
        if '\u6267\u884c\u5931\u8d25' in c and 'step_config' in c:
            print(f'  ❌ [{f}] STEP_CONFIG BUG STILL PRESENT: {c[:200]}')

    await client.disconnect()
    print(f'\n=== {len(received)} msgs ===')

if __name__ == '__main__':
    asyncio.run(main())
