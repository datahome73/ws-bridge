"""Send R107 Step 4 to 小周."""
import asyncio, json, time

creds_path = '/opt/data/home/.ws-bridge/小谷.json'
with open(creds_path) as f:
    creds = json.load(f)

API_KEY = creds['api_key']
AGENT_ID = creds['agent_id']

XIAOZHOU_ID = "ws_fcf496ca1b4f"

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
            "📋 R107 Step 4 — 代码审查 到你了！\n\n"
            "R107: 消除重复代码 + 自动派活功能落地（代码完成，不通电）\n\n"
            "爱泰已完成编码，commit: 1a76c2c\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R107/R107-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R107/WORK_PLAN.md\n\n"
            "🔍 审查内容：\n"
            "- server/main.py（-200/+85 行，删副本2）\n"
            "- server/pipeline_context.py（+15 行，4新字段）\n"
            "- server/config.py（+3 行）\n\n"
            "重点关注：\n"
            "- 副本2 删除后零引用\n"
            "- 开关关闭时绝不发消息\n"
            "- 旧 context 反序列化兼容\n\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R107 Step 4"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": XIAOZHOU_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R107 Step 4 to 小周 ({XIAOZHOU_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
