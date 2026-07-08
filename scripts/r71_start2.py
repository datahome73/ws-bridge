"""Start pipeline on R71-v2 workspace with all 6 members."""
import asyncio, json, os, sys
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')
from ws_client import WsBridgeClient

received = []
def on_message(msg):
    received.append(msg)
    c = msg.get('content', json.dumps(msg, ensure_ascii=False))[:500]
    if c:
        print(f'  [{msg.get("from_name","?")}] {c}')

async def main():
    ws_url = os.environ.get('WS_BRIDGE_URL')
    agent_id = os.environ.get('WS_BRIDGE_AGENT_ID')
    app_id = os.environ.get('WS_BRIDGE_APP_ID')
    client = WsBridgeClient(ws_url=ws_url, app_id=app_id, agent_id=agent_id, name='需求分析师', on_message=on_message)
    ok = await client.connect()
    if not ok: return
    await asyncio.sleep(6)

    # Check current state
    print('=== PIPELINE STATUS ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # Check R71 state (old pipeline might still be active)
    print('\n=== PIPELINE_ACTIVATE (try restore old R71) ===')
    await client.send_message('!pipeline_activate R71')
    await asyncio.sleep(4)

    print('\n=== STATUS AGAIN ===')
    await client.send_message('!pipeline_status')
    await asyncio.sleep(6)

    # If no pipeline, start fresh
    has_pipeline = any('无活跃管线' not in m.get('content','') and ('R71' in m.get('content','') or 'step' in m.get('content','')) for m in received[-3:])
    
    if not has_pipeline:
        print('\n=== FRESH PIPELINE START ===')
        work_plan_url = 'https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R71/WORK_PLAN.md'
        await client.send_message(f'!pipeline_start R71 --work-plan-url {work_plan_url}')
        await asyncio.sleep(10)
        
        print('\n=== STATUS AFTER START ===')
        await client.send_message('!pipeline_status')
        await asyncio.sleep(6)

    # Report
    print('\n' + '=' * 55)
    for m in received:
        c = m.get('content', '')
        if any(kw in c for kw in ['成员', 'step2', 'step3', '当前', '管线状态', '已创建', '已启动', '活跃', 'R71', '点名']):
            print(f'[{m.get("from_name","?")}] {c[:400]}')

    await client.disconnect()

asyncio.run(main())
