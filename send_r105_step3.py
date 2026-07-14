"""Send R105 Step 3 to 爱泰 via raw WebSocket."""
import asyncio, json, time

creds_path = '/opt/data/home/.ws-bridge/小谷.json'
with open(creds_path) as f:
    creds = json.load(f)

API_KEY = creds['api_key']
AGENT_ID = creds['agent_id']

AITAI_ID = "ws_0bb747d3ea2a"

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
            "📋 R105 Step 3 — 编码实现 到你了！\n\n"
            "R105: 统一 Bot 回复模板\n\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R105/R105-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R105/WORK_PLAN.md\n\n"
            "🔍 任务：逐个配置各 bot 的系统提示词，添加回复模板。不涉及 Server 代码变更。\n"
            "小开技术方案已推 dev (ddc1ad7)\n\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R105 Step 3"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": AITAI_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R105 Step 3 to 爱泰 ({AITAI_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
