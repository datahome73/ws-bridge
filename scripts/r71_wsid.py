"""Start R71 pipeline on R71-v2 workspace with --workspace-id."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:500]
    print(f'  [{msg.get("from_name","?")}] {c[:500]}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='需求分析师', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(5)

    # 1. Reset any stale pipeline
    print('=== 1. RESET ===')
    await client.send_message('!workspace_reset')
    await asyncio.sleep(4)

    # 2. Check state
    print('\n=== 2. STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(4)

    # 3. Start pipeline with --workspace-id pointing to R71-v2 (6人)
    print('\n=== 3. !pipeline_start R71 --workspace-id ws:01KT6E4D-R71-v2 ===')
    work_plan_url = 'https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R71/WORK_PLAN.md'
    await client.send_message(f'!pipeline_start R71 --work-plan-url {work_plan_url} --workspace-id ws:01KT6E4D-R71-v2')
    await asyncio.sleep(10)

    # 4. Status - check members!
    print('\n=== 4. STATUS (check members) ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # 5. Handoff step2→step3 (doc already done: 833d558)
    print('\n=== 5. HANDOFF step2→step3 ===')
    await client.send_message('!step_handoff step2 --output 833d558')
    await asyncio.sleep(6)

    # 6. Final
    print('\n=== 6. FINAL STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # Report
    print('\n' + '=' * 55)
    print('MEMBER CHECK:')
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['成员', 'member', 'step', '当前', '管线状态', 'R71', '已启动', '已创建', '点名', '附着']):
            print(f'[{m.get("from_name","?")}] {c[:400]}')

    await client.disconnect()

asyncio.run(main())
