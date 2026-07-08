"""Simple test - one command at a time, check output."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

msgs = []
def on_message(msg):
    msgs.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:400]
    print(f'  [{msg.get("from_name","?")}] {c}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='t', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    print('Draining...')
    await asyncio.sleep(8)
    msgs.clear()
    print('GO!\n')

    # Create workspace
    print('--- Create workspace ---')
    await client.send_message('!create_workspace R71-z --members 小谷,小爱,小开,爱泰,小周,泰虾')
    await asyncio.sleep(8)

    # Start pipeline
    print('\n--- Pipeline start ---')
    await client.send_message('!pipeline_start R71 --work-plan-url https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R70/WORK_PLAN.md')
    await asyncio.sleep(12)

    # Status - look for members
    print('\n--- Pipeline status ---')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    print('\n' + '=' * 50)
    print('RESULTS (filtered):')
    for m in msgs:
        c = m.get('content', '')
        if any(kw in c for kw in ['成员', '复用', '创建', 'arch', 'dev', 'review', 'qa', 'admin', '当前', 'Step']):
            print(f"  [{m.get('from_name','?')}] {c[:300]}")

    await client.disconnect()

asyncio.run(main())
