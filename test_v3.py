"""Verify all 3 fixes after r71 deploy."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []

def on_message(msg):
    received.append(msg)
    ts = msg.get('ts', 0)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:400]
    if ts < 100:  # Skip backlog (old ts)
        return
    print(f'  [{msg.get("from_name","?")}] {c}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='验', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(5)  # Drain backlog

    # Clean slate
    print('--- Cleanup ---')
    await client.send_message('!workspace_reset')
    await asyncio.sleep(4)
    await client.send_message('!pipeline_status')
    await asyncio.sleep(4)

    # Create workspace with NAMES (tests Fix 3)
    print('\n--- Create workspace ---')
    await client.send_message('!create_workspace R71-v2 --members 小谷,小爱,小开,爱泰,小周,泰虾')
    await asyncio.sleep(6)

    # Start pipeline - test Fix 1 (reuse) + Fix 3 (member resolve)
    print('\n--- Pipeline start ---')
    await client.send_message('!pipeline_start R71 --work-plan-url https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R70/WORK_PLAN.md')
    await asyncio.sleep(8)

    # Check status
    print('\n--- Status ---')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(5)

    # Report
    print('\n' + '=' * 55)
    for m in received:
        c = m.get('content', '')
        if m.get('ts', 0) > 100 and any(kw in c for kw in ['复用', '成员', '创建', 'arch', 'dev', '当前', '未找到', '管线已启动', '已创建']):
            print(f'  [{m.get("from_name","?")}] {c[:300]}')

    await client.disconnect()

asyncio.run(main())
