"""Create new R71 workspace with ALL 6 members + restart pipeline."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:500]
    if c:
        print(f'  [{msg.get("from_name","?")}] {c}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='需求分析师', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(5)

    # 1. Clean slate
    print('=== 1. RESET ===')
    await client.send_message('!workspace_reset')
    await asyncio.sleep(4)

    # 2. Create workspace with ALL 6 members
    print('\n=== 2. CREATE WORKSPACE (6人) ===')
    await client.send_message('!create_workspace R71-v2 --members 小谷,小爱,小开,爱泰,小周,泰虾')
    await asyncio.sleep(6)

    # 3. Start pipeline
    print('\n=== 3. PIPELINE START ===')
    work_plan_url = 'https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R71/WORK_PLAN.md'
    await client.send_message(f'!pipeline_start R71 --work-plan-url {work_plan_url}')
    await asyncio.sleep(10)

    # 4. Check members
    print('\n=== 4. PIPELINE STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # Report member line
    print('\n' + '=' * 55)
    print('MEMBER CHECK:')
    for m in received:
        c = m.get('content', '')
        if '成员' in c or 'member' in c.lower():
            print(f'  [{m.get("from_name","?")}] {c[:400]}')

    print('\nFULL PIPELINE STATUS:')
    for m in received:
        c = m.get('content', '')
        if '管线状态' in c or 'R71' in c[:10]:
            print(f'  [{m.get("from_name","?")}] {c[:500]}')

    await client.disconnect()

asyncio.run(main())
