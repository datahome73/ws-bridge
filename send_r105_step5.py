"""Send R105 Step 5 to 泰虾 via raw WebSocket."""
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
            "📋 R105 Step 5 — 测试验证 到你了！\n\n"
            "R105: 统一 Bot 回复模板\n\n"
            "爱泰已创建回复格式协议 (57b2a56)，小周审查通过 ✅\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R105/R105-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R105/WORK_PLAN.md\n"
            "📋 协议文档：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/skills/reply-format-protocol.md\n\n"
            "🔍 验证内容：\n"
            "1. 回复格式协议文档覆盖完整（4种场景、示例、常见错误）\n"
            "2. 各 bot 是否已引用该协议\n"
            "3. 协议格式是否可被 bot 正确理解执行\n\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R105 Step 5"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": TAIXIA_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R105 Step 5 to 泰虾 ({TAIXIA_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
