"""Minimal test - no timestamp filter."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

def on_message(msg):
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:400]
    print(f'  [{msg.get("from_name","?")}] {c}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='t', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(6)  # drain backlog

    # 1. Clean
    print('\n=== CLEAN ===')
    await client.send_message('!workspace_reset')
    await asyncio.sleep(5)
    await client.send_message('!pipeline_status')
    await asyncio.sleep(4)

    # 2. Create with names
    print('\n=== CREATE WORKSPACE ===')
    await client.send_message('!create_workspace R71-x --members 小谷,小爱,小开,爱泰,小周,泰虾')
    await asyncio.sleep(7)

    # 3. Pipeline start (use --work-plan-url to bypass validation)
    print('\n=== PIPELINE START ===')
    await client.send_message('!pipeline_start R71 --work-plan-url https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R70/WORK_PLAN.md')
    await asyncio.sleep(10)

    # 4. Status
    print('\n=== STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    print('\n' + '=' * 55)
    print('RAW OUTPUT (last 20 msgs):')
    for m in received[-20:]:
        c = m.get('content', '')[:350]
        print(f"  [{m.get('from_name','?')}] {c}")

    await client.disconnect()

received = []
asyncio.run(main())
