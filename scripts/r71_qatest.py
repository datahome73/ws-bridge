"""Activate 泰虾 for step5 - regression verification."""
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

    print('=== @泰虾 Step 5 激活 ===')
    await client.send_message(
        "@泰虾 🦐 **Step 5 — 回归验证 + 治理** 到你了！\n\n"
        "审查结论：🟢 通过（198674d）\n\n"
        "回归验证 3 项：\n"
        "  ✅-8 Web 端可见消息 → docker logs 无 RuntimeWarning\n"
        "  ✅-9 各 Tab 可切换\n"
        "  ✅-10 WebSocket 实时推送\n\n"
        "治理 3 项：\n"
        "  ✅-11 TODO.md v2.36→v2.37\n"
        "  ✅-12 F-22 标记 ✅ 已修复\n"
        "  ✅-13 D-3 docs/README.md 脱敏\n\n"
        "产出推 dev → !step_complete step5 --output <sha>",
        channel=channel
    )
    await asyncio.sleep(10)

    print('\n=== Responses ===')
    for m in received:
        c = m.get('content', '')[:400]
        if c and m.get('from_name') in ('泰虾','小爱','小谷','小开','小周','爱泰','系统'):
            print(f'  [{m.get("from_name")}] {c}')
    await client.disconnect()

asyncio.run(main())
