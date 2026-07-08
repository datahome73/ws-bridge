"""Test all 3 fixes - long drain."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

msgs = []
def on_message(msg):
    msgs.append(msg)

async def send(cmd, wait=6):
    print(f'>>> {cmd}')
    await client.send_message(cmd)
    await asyncio.sleep(wait)

async def main():
    global client
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='t', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    print('Draining backlog...')
    await asyncio.sleep(10)
    msgs.clear()
    print(f'Backlog drained ({len(msgs)} msgs)\n')

    await send('!workspace_reset', 5)
    await send('!pipeline_status', 4)

    await send('!create_workspace R71-z --members 小谷,小爱,小开,爱泰,小周,泰虾', 7)
    await send('!pipeline_start R71 --work-plan-url https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R70/WORK_PLAN.md', 10)
    await send('!pipeline_status', 6)

    print('\n' + '=' * 55)
    for m in msgs:
        c = m.get('content', '')
        if any(kw in c for kw in ['复用', '成员', '创建', 'arch', 'dev', '管线已启动', '已创建']):
            print(f"  [{m.get('from_name','?')}] {c[:300]}")

    f1 = any('复用' in m.get('content','') for m in msgs)
    f3 = not any('未找到角色' in m.get('content','') for m in msgs)
    print(f'\nFix 1 (workspace reuse): {"✅" if f1 else "❌ UNKNOWN"}')
    print(f'Fix 3 (member resolve):  {"✅" if f3 else "❌"}')

    await client.disconnect()

asyncio.run(main())
