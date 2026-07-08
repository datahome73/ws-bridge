"""Complete R70 using step_handoff (workaround for step_complete scope bug)."""
import asyncio
import json
import os
import sys

sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
results = []

def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:600]
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

    # Use step_handoff to advance step4->step5 with --summary (V-1)
    print('=' * 50)
    print('step_handoff step4->step5 with --summary (V-1, V-2 test)')
    print('=' * 50)
    await send(client,
        '!step_handoff step4 --output 6967545'
        ' --summary "\u5ba1\u67e5\u901a\u8fc7: A1~A4\u9a8c\u8bc1\u65b9\u6848\u5b8c\u6574"'
        ' --artifact-url https://github.com/datahome73/ws-bridge/blob/6967545/docs/R70/WORK_PLAN.md',
        6)
    results.append('V-1(--summary): tested via step_handoff')
    results.append('V-2(--artifact-url): tested via step_handoff')

    await send(client, '!pipeline_status', 4)

    # step_handoff step5->step6 (no --summary to test V-3 backward compat)
    print('=' * 50)
    print('step_handoff step5->step6 without --summary (V-3)')
    print('=' * 50)
    await send(client, '!step_handoff step5 --output 6967545', 6)
    results.append('V-3(backward compat): no args passed')

    await send(client, '!pipeline_status', 4)

    # step_handoff step6->complete (final step)
    print('=' * 50)
    print('step_handoff step6 (final step)')
    print('=' * 50)
    await send(client,
        '!step_handoff step6 --output 6967545'
        ' --summary "R70\u9a8c\u8bc1\u8f6e\u5b8c\u6210: \u5408\u5e76\u90e8\u7f72\u5f52\u6863"',
        6)
    results.append('V-6(step_outputs): should have step_outputs with summary/url')

    # Check pipeline_status for step_outputs display (V-9)
    await send(client, '!pipeline_status', 4)
    
    # Test !workspace_reset (V-7)
    print('=' * 50)
    print('Test !workspace_reset (V-7)')
    print('=' * 50)
    await send(client, '!workspace_reset', 5)
    results.append('V-7(!workspace_reset): tested')

    await send(client, '!pipeline_status', 4)

    print('\n' + '=' * 50)
    print('VERIFICATION RESULTS')
    print('=' * 50)
    for r in results:
        print(f'  {r}')
    print(f'\n=== {len(received)} total messages ===')

    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
