"""Double check - is pipeline really gone?"""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:400]
    f = msg.get('from_name','?')
    if f in ('系统','小爱','小谷','小开','小周','泰虾','爱泰') or c:
        print(f'  [{f}] {c[:400]}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='需求分析师', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(5)
    
    # Create workspace if pipeline is gone
    print('=== !create_workspace R71-dev --members 小谷,小爱,小开,爱泰,小周,泰虾 ===')
    await client.send_message('!create_workspace R71-dev --members 小谷,小爱,小开,爱泰,小周,泰虾')
    await asyncio.sleep(6)
    
    print('\n=== !pipeline_status ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)
    
    for m in received[-10:]:
        c = m.get('content','')[:400]
        if c:
            print(f'  [{m.get("from_name")}] {c}')
    await client.disconnect()

asyncio.run(main())
