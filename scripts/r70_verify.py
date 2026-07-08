"""FINAL verification of both fixes."""
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

    # Create workspace with "R70" in name
    await send(client, '!create_workspace R70-v --members 小谷,小爱,小开,爱泰,小周,泰虾', 5)
    
    # pipeline_start should reuse if name contains "R70"
    await send(client, '!pipeline_start R70', 8)
    await send(client, '!pipeline_status', 5)

    # Print key
    print('\n' + '=' * 55)
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['复用', '创建失败', '成员', 'step2']):
            print(f'  [{m.get("from_name","?")}] {c[:300]}')

    # Conclusion
    all_text = str([m.get('content','') for m in received])
    if '复用' in all_text:
        print('\n✅✅✅ Fix 1 CONFIRMED: pipeline_start reuses existing workspace')
    elif '创建失败' in all_text:
        print('\n❌ Fix 1 NOT working - still seeing "创建失败"')
    else:
        print('\n⚠️ Cannot determine')

    await client.disconnect()

asyncio.run(main())
