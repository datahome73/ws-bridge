"""Clean slate then test both fixes."""
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

    # Full cleanup
    print('=== RESET ALL ===')
    for i in range(3):
        await send(client, '!workspace_reset', 3)
    await send(client, '!pipeline_status', 3)

    # Fresh workspace for R71 (new round, avoids R70 name collision)
    await send(client, '!create_workspace R71-test --members \u5c0f\u8c37,\u5c0f\u7231,\u5c0f\u5f00,\u7231\u6cf0,\u5c0f\u5468,\u6cf0\u867e', 5)

    # Start pipeline for R70 (reuse workspace)
    await send(client, '!pipeline_start R70', 8)

    # Check status
    await send(client, '!pipeline_status', 5)

    # Print key results
    print('\n' + '=' * 60)
    for m in received:
        c = m.get('content', '')
        f = m.get('from_name', '?')
        if any(kw in c for kw in ['\u590d\u7528', '\u6210\u5458', 'R70', '\u5f53\u524d', '\u6267\u884c\u5931\u8d25']):
            print(f'  [{f}] {c[:400]}')

    # Test step_complete via handoff then direct
    await send(client, '!step_handoff step2 --output 0636aba --summary R70fix', 5)
    await send(client, '!step_handoff step3 --output 0636aba', 5)
    await send(client, '!step_handoff step4 --output 0636aba', 5)

    # Test step_complete (Fix 2)
    print('\n=== STEP_COMPLETE TEST ===')
    await send(client, '!step_complete step5 --output 0636aba --summary "R70\u4fee\u590d\u9a8c\u8bc1\u901a\u8fc7"', 6)
    for m in received[-5:]:
        c = m.get('content', '')
        if '\u6267\u884c\u5931\u8d25' in c:
            print(f'  ❌ {c[:300]}')
        elif 'test-report' in c or '\u5b8c\u6210' in c:
            print(f'  ✅ {c[:300]}')

    await send(client, '!workspace_reset', 4)
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
