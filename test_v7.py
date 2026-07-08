"""Test pipeline_start only - workspace already exists."""
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

    print('=== PIPELINE START R70 ===')
    await client.send_message('!pipeline_start R70')
    await asyncio.sleep(12)

    print('\n=== STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(8)

    print('\n' + '=' * 50)
    print('RESULTS:')
    found_reuse = False
    found_members = False
    found_role_ok = True
    for m in msgs:
        c = m.get('content', '')
        if '复用' in c:
            found_reuse = True
            print(f"  ✅ Fix 1: {c[:300]}")
        if '成员' in c and '🟢' in c:
            found_members = True
            members_line = c
        if '未找到角色' in c:
            found_role_ok = False
            print(f"  ❌ Role issue: {c[:200]}")
    
    if found_members:
        print(f"  Members: {members_line[:200]}")
    print(f'\nFix 1 (reuse): {"✅" if found_reuse else "❌"}')
    print(f'Fix 3 (members): {"✅" if found_members else "❌"}')
    print(f'Role mapping: {"✅" if found_role_ok else "❌"}')

    await client.disconnect()

asyncio.run(main())
