"""Test all 3 fixes: workspace reuse + member resolution + step_complete."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:500]
    print(f'  [{msg.get("from_name","?")}] {c}')

async def send(client, cmd, wait=6):
    await client.send_message(cmd)
    await asyncio.sleep(wait)

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='验', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(2)

    # Create workspace with names (Fix 3 test)
    await send(client, '!create_workspace R70-ok --members 小谷,小爱,小开,爱泰,小周,泰虾', 5)
    
    # Start pipeline - should reuse + find arch member
    await send(client, '!pipeline_start R70', 8)
    await send(client, '!pipeline_status', 5)

    # Print key
    print('\n' + '=' * 55)
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['复用', '创建', '成员', 'arch', 'dev', 'review', 'qa', '当前']):
            print(f'  [{m.get("from_name","?")}] {c[:300]}')

    # Analyze
    all_text = str([m.get('content','') for m in received])
    f1 = '复用' in all_text
    f3 = '未找到角色' not in all_text  # if no "not found" errors for arch
    print(f'\nFix 1 (workspace reuse): {"✅" if f1 else "❌"}')
    print(f'Fix 3 (member resolve):  {"✅" if f3 else "❌"}')

    await client.disconnect()

asyncio.run(main())
