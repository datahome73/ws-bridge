"""Send R106 Step 3 to 爱泰 via raw WebSocket."""
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
            "📋 R106 Step 3 — 编码实现 到你了！\n\n"
            "R106: Pipeline Context + Step 自动推进\n\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R106/R106-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R106/WORK_PLAN.md\n"
            "小开技术方案已推 dev (5ad5a35)\n\n"
            "🔍 任务：\n"
            "1. 新建 server/pipeline_context.py（~80 行）\n"
            "2. 修改 server/main.py 两副本 _handle_server_relay（+20 行）\n"
            "3. 增强 !pipeline_status 显示 Pipeline Context（+15 行）\n\n"
            "⚠️ 注意：两副本必须同步修改（R107 再消除重复）\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R106 Step 3"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": AITAI_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R106 Step 3 to 爱泰 ({AITAI_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
