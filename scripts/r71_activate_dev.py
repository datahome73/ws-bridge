"""Activate 爱泰 for step3 F-9 diagnosis."""
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

    channel = "ws:01KT6E4D-R71-v2"
    
    print('=== @爱泰 Step 3 点名激活 ===')
    await client.send_message(
        f"@爱泰 💻 **Step 3 — F-9 诊断执行** 到你了！\n\n"
        f"🏠 工作室：{channel}\n\n"
        f"📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R71/R71-product-requirements.md\n"
        f"📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R71/WORK_PLAN.md\n"
        f"🏗️ 诊断范围：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R71/R71-f9-diagnosis-scope.md\n"
        f"🔗 上一步产出：833d558\n\n"
        f"执行 F-9 Web 端诊断 4 Phase 流程：\n"
        f"  Phase A — 进程端口检查\n"
        f"  Phase B — 浏览器 DevTools 6 项检查\n"
        f"  Phase C — 日志检查\n"
        f"  Phase D — Token/Session 验证\n\n"
        f"产出诊断报告 docs/R71/R71-f9-diagnosis.md，推 dev 后 !step_complete step3 --output <sha>",
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
