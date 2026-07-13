"""Send R104 Step 5 to 泰虾 via raw WebSocket."""
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
            "📋 R104 Step 5 — 测试验证 到你了！\n\n"
            "R104: Web 服务增加工作区列表 API\n\n"
            "爱泰已完成编码 (f984bb9)，小周审查通过 ✅\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R104/R104-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R104/WORK_PLAN.md\n\n"
            "🔍 验证 7 项验收标准：\n"
            "1. GET /api/workspaces 返回工作区列表\n"
            "2. 返回格式含 workspaces + count\n"
            "3. 每个工作区含 pipeline_round + roles\n"
            "4. 前端面板正常加载\n"
            "5. 点击工作区可切换 Tab\n"
            "6. 无 token 返回 401\n"
            "7. WSS 核心端点不受影响\n\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R104 Step 5"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": TAIXIA_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R104 Step 5 to 泰虾 ({TAIXIA_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
