"""Ask 小爱 to coordinate - redirect 爱泰 to step3."""
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
    await asyncio.sleep(4)

    channel = "ws:01KT6E4D-R71-v2"
    
    print('=== @小爱 请协调爱泰接step3 ===')
    await client.send_message(
        "@小爱 管线已到 step3（F-9 诊断），爱泰认识 @爱泰 但说「非我方任务」拒绝接手。\n"
        "可能是因为管线角色名是 `dev` 但他的 agent card 角色是 `developer`。\n"
        "你能帮我直接转发任务给他吗？或者你在工作室 @爱泰 告诉他这是他的活。",
        channel=channel
    )
    await asyncio.sleep(10)

    print('\n=== Responses ===')
    for m in received:
        c = m.get('content', '')[:400]
        if c and m.get('from_name') in ('爱泰','小爱','小谷','小开','小周','泰虾','系统'):
            print(f'  [{m.get("from_name")}] {c}')
    await client.disconnect()

asyncio.run(main())
