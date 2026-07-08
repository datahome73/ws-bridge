"""Check server version and clean state."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:500]
    print(f'  [{msg.get("from_name","?")}] {c}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='测试', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    print('Connected\n')
    await asyncio.sleep(2)

    # Send status to see if old pipeline is still active
    await client.send_message('!pipeline_status')
    await asyncio.sleep(4)
    
    # Then try resetting the old pipeline
    await client.send_message('!workspace_reset')
    await asyncio.sleep(5)
    
    await client.send_message('!pipeline_status')
    await asyncio.sleep(4)

    # Print all
    for m in received:
        c = m.get('content', '')
        print(f'  [{m.get("from_name","?")}] {c[:300]}')

    await client.disconnect()

asyncio.run(main())
