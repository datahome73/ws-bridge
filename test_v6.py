"""Test fixes - use R70 (has WORK_PLAN), workspace R71-z (has 'R7' match)."""
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
    await asyncio.sleep(8)
    msgs.clear()

    # R70 has WORK_PLAN, workspace "R71-z" won't match "R70" name check
    # So let's reset and create "R70" workspace
    print('--- Clean ---')
    await client.send_message('!workspace_reset')
    await asyncio.sleep(5)

    print('\n--- Create R70-v3 ---')
    await client.send_message('!create_workspace R70-v3 --members 小谷,小爱,小开,爱泰,小周,泰虾')
    await asyncio.sleep(8)

    print('\n--- Pipeline start R70 ---')
    await client.send_message('!pipeline_start R70')
    await asyncio.sleep(12)

    print('\n--- Status ---')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    print('\n' + '=' * 50)
    print('FILTERED RESULTS:')
    for m in msgs:
        c = m.get('content', '')
        if any(kw in c for kw in ['复用', '成员', '创建', 'arch', 'dev', '未找到', '管线已', '已创建']):
            print(f"  [{m.get('from_name','?')}] {c[:300]}")

    await client.disconnect()

asyncio.run(main())
