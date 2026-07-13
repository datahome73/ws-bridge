"""Send R106 Step 5 to 泰虾."""
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
            "📋 R106 Step 5 — 测试验证 到你了！\n\n"
            "R106: Pipeline Context + Step 自动推进\n\n"
            "爱泰已完成编码 (381490b)，小周审查通过 ✅\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R106/R106-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R106/WORK_PLAN.md\n\n"
            "🔍 验证 7 项验收标准：\n"
            "1. create_context() 创建 JSON\n"
            "2. advance_step() 正确推进\n"
            "3. get_context() 返回正确状态\n"
            "4. Server 收到「已完成 ✅」后自动推进\n"
            "5. !pipeline_status 显示 Context\n"
            "6. 不自动派活（不突破 R106a 边界）\n"
            "7. 不破坏现有前缀匹配\n\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R106 Step 5"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": TAIXIA_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R106 Step 5 to 泰虾 ({TAIXIA_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
