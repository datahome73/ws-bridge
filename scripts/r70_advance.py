"""Advance R70 pipeline - manual handoff through all steps."""
import asyncio
import json
import os
import sys

sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []

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

    # Step 2: Roll call
    print('=' * 50)
    print('STEP 2: Roll call')
    print('=' * 50)
    await send(client, '!rollcall_next', 6)

    # Check status
    await send(client, '!pipeline_status', 4)

    # Step 3: Handoff to arch with summary (V-1 test)
    summary_arch = '\u9a8c\u8bc1\u8303\u56f4\u6587\u6863 v1.0'
    print('=' * 50)
    print('STEP 3: Handoff to arch -> verification scope doc')
    print('=' * 50)
    await send(client, f'!step_handoff step2 --output 6967545 --summary {summary_arch}', 6)
    await send(client, '!pipeline_status', 4)

    # Step 4: Handoff to dev
    summary_dev = 'Dev\u73af\u5883\u786e\u8ba4 + V-1~V-4\u9a8c\u8bc1'
    print('=' * 50)
    print('STEP 4: Handoff to dev -> env verification')
    print('=' * 50)
    await send(client, f'!step_handoff step3 --output 6967545 --summary {summary_dev}', 6)
    await send(client, '!pipeline_status', 4)

    # Step 5: Handoff to review
    summary_review = '\u9a8c\u8bc1\u65b9\u6848\u5ba1\u67e5\u901a\u8fc7'
    print('=' * 50)
    print('STEP 5: Handoff to review ->方案审查')
    print('=' * 50)
    await send(client, f'!step_handoff step4 --output 6967545 --summary {summary_review}', 6)
    await send(client, '!pipeline_status', 4)

    # Step 6: Handoff to qa
    summary_qa = '\u5168\u91cf\u56de\u5f52 V-1~V-9 + F-9\u8bca\u65ad'
    print('=' * 50)
    print('STEP 6: Handoff to qa -> full regression')
    print('=' * 50)
    await send(client, f'!step_handoff step5 --output 6967545 --summary {summary_qa}', 6)
    await send(client, '!pipeline_status', 4)

    # Print verification-relevant results
    print('\n' + '=' * 50)
    print('VERIFICATION FINDINGS')
    print('=' * 50)
    for m in received:
        c = m.get('content', '')
        f = m.get('from_name', '?')
        if any(kw in c for kw in ['R70', 'pipeline', 'Step', 'step', 'handoff', 'rollcall', 'arch', 'dev', 'review', 'qa', 'admin']):
            if '\u672a\u77e5\u547d\u4ee4' not in c:
                print(f'  [{f}] {c[:500]}')

    await client.disconnect()
    print(f'\n=== {len(received)} msgs ===')

if __name__ == '__main__':
    asyncio.run(main())
