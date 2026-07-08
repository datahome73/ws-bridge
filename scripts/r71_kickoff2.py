"""Send !pipeline_start R71 — minimal script, no ACK check needed."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:400]
    print(f'  [{msg.get("from_name","?")}] {c}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='需求分析师', on_message=on_message)
    ok = await client.connect()
    if not ok:
        print("CONNECT FAILED")
        return
    await asyncio.sleep(5)  # drain backlog

    # pipeline_start
    print('=== !pipeline_start R71 ===')
    work_plan_url = 'https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R71/WORK_PLAN.md'
    await client.send_message(f'!pipeline_start R71 --work-plan-url {work_plan_url}')
    await asyncio.sleep(12)

    # status
    print('\n=== !pipeline_status ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(8)

    # report
    print('\n' + '=' * 55)
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['复用', '成员', '创建', '已启动', '当前', '未找到', '管线已', '已创建', '点名', '🟢', '🔴', '✅', '❌', '工作室']):
            print(f'  [{m.get("from_name","?")}] {c[:400]}')

    await client.disconnect()

asyncio.run(main())
