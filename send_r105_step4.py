"""Send R105 Step 4 to 小周 via raw WebSocket."""
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
            "📋 R105 Step 4 — 代码审查 到你了！\n\n"
            "R105: 统一 Bot 回复模板\n\n"
            "爱泰已完成配置，commit: 57b2a56\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R105/R105-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R105/WORK_PLAN.md\n\n"
            "🔍 审查内容：各 bot 系统提示词的回复模板配置变更（不涉及 Server 代码变更）\n\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R105 Step 4"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": XIAOZHOU_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R105 Step 4 to 小周 ({XIAOZHOU_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
