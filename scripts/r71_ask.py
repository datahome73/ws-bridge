"""Ask 小爱 what's stuck on step2 handoff."""
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
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='需求分析师', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(5)

    # Send to R71 workspace
    channel = "ws:01KT6E4D-R71-dev"
    
    print('=== Ask 小爱 what happened with step2 ===')
    await client.send_message(
        "@小爱 Step 2 产出文档 833d558 已确认收到 ✅ 但管线状态还停在 ⬜ step2 — arch ◀ 当前。\n\n"
        "是不是 `!step_complete step2` 因为角色权限（你是admin不是arch）没推进状态机？\n\n"
        "另外，小周/爱泰/泰虾 3 人在线但没在工作室，你能用全员点名拉他们进来吗？",
        channel=channel
    )
    await asyncio.sleep(10)

    print('\n=== Responses ===')
    for m in received:
        c = m.get('content', '')[:500]
        if c and m.get('from_name') in ('小爱', '小谷', '小开'):
            print(f'  [{m.get("from_name","?")}] {c}')

    await client.disconnect()

asyncio.run(main())
