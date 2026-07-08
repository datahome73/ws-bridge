"""Check if deployment actually has the fix."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:500]
    print(f'  [{msg.get("from_name","?")}] {c[:500]}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='需求分析师', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(5)

    # Reset
    print('=== RESET ===')
    await client.send_message('!workspace_reset')
    await asyncio.sleep(4)

    # Ask 小爱 to verify --workspace-id flag exists in handler.py
    print('\n=== @小爱 确认 --workspace-id 参数是否在运行代码中 ===')
    await client.send_message(
        '@小爱 请确认最新部署的 `ws-bridge:r71` 镜像中 handler.py 是否包含 `--workspace-id` 参数支持。'
        '在容器内跑：`grep -c "workspace_id" /app/server/handler.py`，返回 >0 则包含。',
        channel='ws:01KT6E4D-R71-v2'
    )
    await asyncio.sleep(8)

    print('\n=== Responses ===')
    for m in received:
        c = m.get('content', '')[:400]
        if c and m.get('from_name') in ('小爱','小谷','小开','系统'):
            print(f'  [{m.get("from_name")}] {c}')

    await client.disconnect()

asyncio.run(main())
