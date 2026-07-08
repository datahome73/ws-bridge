"""Reset old pipeline, start fresh on R71-v2 with all 6, handoff to step3."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:500]
    if c:
        print(f'  [{msg.get("from_name","?")}] {c[:500]}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='需求分析师', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(5)

    # 1. Reset old pipeline
    print('=== 1. RESET OLD PIPELINE ===')
    await client.send_message('!workspace_reset')
    await asyncio.sleep(5)

    # 2. Check state
    print('\n=== 2. STATUS CHECK ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(4)

    # 3. Start fresh pipeline on R71-v2
    print('\n=== 3. PIPELINE START on new workspace (6人) ===')
    # Need to activate the new workspace first
    await client.send_message('!pipeline_activate R71-v2')
    await asyncio.sleep(4)
    
    # Check what workspace we're on
    print('\n=== 4. STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(5)

    # 5. Start pipeline
    work_plan_url = 'https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R71/WORK_PLAN.md'
    print('\n=== 5. !pipeline_start R71 --work-plan-url ... ===')
    await client.send_message(f'!pipeline_start R71 --work-plan-url {work_plan_url}')
    await asyncio.sleep(10)

    # 6. Check members
    print('\n=== 6. STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # 7. Handoff step2 -> step3 (doc already done: 833d558)
    print('\n=== 7. HANDOFF step2→step3 ===')
    await client.send_message('!step_handoff step2 --output 833d558')
    await asyncio.sleep(6)

    # 8. Final status
    print('\n=== 8. FINAL STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # Report
    print('\n' + '=' * 55)
    print('FINAL STATE:')
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['成员', 'step2', 'step3', '当前', '管线状态', '已创建', '已启动', 'R71', '已激活']):
            print(f'[{m.get("from_name","?")}] {c[:400]}')

    await client.disconnect()

asyncio.run(main())
