"""Check if 小爱 actually pushed step2 forward."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:500]
    pt = msg.get('from_name','?')
    if pt in ('系统', '小爱', '小谷', '小开'):
        print(f'  [{pt}] {c}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='需求分析师', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(6)

    print('=== STATUS CHECK ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    print('\n=== KEY ===')
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['step', '当前', 'arch', 'dev', '成员', '推进', 'handoff', 'complete', '已切换', '点名']):
            print(f'[{m.get("from_name","?")}] {c[:400]}')

    await client.disconnect()

asyncio.run(main())
