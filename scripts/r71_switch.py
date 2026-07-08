"""Close old R71-dev, use R71-v2 with 6 members."""
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

    # 1. Reset pipeline
    print('=== 1. RESET ===')
    await client.send_message('!workspace_reset')
    await asyncio.sleep(4)

    # 2. Status
    print('\n=== 2. STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(4)

    # 3. Now join R71-v2 by sending msg there (set active channel)
    print('\n=== 3. SEND to R71-v2 workspace (activate it) ===')
    # Use the workspace channel
    await client.send_message('@全员 准备启动管线，各成员请确认', channel='ws:01KT6E4D-R71-v2')
    await asyncio.sleep(4)

    # 4. Start pipeline - hope it picks up current workspace
    print('\n=== 4. PIPELINE START ===')
    work_plan_url = 'https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R71/WORK_PLAN.md'
    await client.send_message(f'!pipeline_start R71 --work-plan-url {work_plan_url}')
    await asyncio.sleep(10)

    # 5. Status
    print('\n=== 5. STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # 6. Handoff step2→step3 if pipeline active with 6 members
    print('\n=== 6. HANDOFF step2→step3 ===')
    await client.send_message('!step_handoff step2 --output 833d558')
    await asyncio.sleep(6)

    # 7. Final
    print('\n=== 7. FINAL STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # Report
    print('\n' + '=' * 55)
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['成员', 'step2', 'step3', '当前', '管线状态', 'R71', '已创建', '已启动', 'resetting']):
            print(f'[{m.get("from_name","?")}] {c[:400]}')

    await client.disconnect()

asyncio.run(main())
