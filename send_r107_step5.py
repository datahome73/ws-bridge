"""Send R107 Step 5 to 泰虾."""
import asyncio, json, time

creds_path = '/opt/data/home/.ws-bridge/小谷.json'
with open(creds_path) as f:
    creds = json.load(f)

API_KEY = creds['api_key']
AGENT_ID = creds['agent_id']

TAIXIA_ID = "ws_eab784ac7652"

async def main():
    import websockets
    uri = "wss://wsim.datahome73.cloud/ws"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": API_KEY}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"Auth: {auth_resp.get('type')}")
        if auth_resp.get('type') != 'auth_ok':
            print(f"FAIL: {auth_resp}")
            return

        content = (
            "📋 R107 Step 5 — 测试验证 到你了！\n\n"
            "R107: 消除重复代码 + 自动派活功能落地（代码完成，不通电）\n\n"
            "爱泰已完成编码 (1a76c2c)，小周审查通过 ✅\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R107/R107-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R107/WORK_PLAN.md\n\n"
            "🔍 验证 9 项验收标准：\n"
            "1. _handle_server_relay 只有一份\n"
            "2. 4 新字段序列化正确\n"
            "3. _render_template 渲染正确\n"
            "4. _auto_dispatch 存在可调用\n"
            "5. 开关关闭时不发消息\n"
            "6. 无上下文不执行\n"
            "7. 最后一步标记 completed\n"
            "8. 多轮次并行互不干扰\n"
            "9. 开关关闭时无行为变化\n\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R107 Step 5"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": TAIXIA_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R107 Step 5 to 泰虾 ({TAIXIA_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
