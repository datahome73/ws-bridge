"""Send R107 Step 3 to 爱泰."""
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
            "📋 R107 Step 3 — 编码实现 到你了！\n\n"
            "R107: 消除重复代码 + 自动派活功能落地（代码完成，不通电）\n\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R107/R107-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R107/WORK_PLAN.md\n"
            "小开技术方案已推 dev (db12f7f)\n\n"
            "🔍 任务：\n"
            "1. server/config.py: 新增 AUTO_DISPATCH_ENABLED = False\n"
            "2. server/pipeline_context.py: 4 新字段 + to_dict/from_dict 同步\n"
            "3. server/main.py: 删副本2 + _render_template + _auto_dispatch(asyncio.ensure_future)\n"
            "4. 单元测试验证 _render_template\n\n"
            "⚠️ 开关关闭时绝不发消息\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R107 Step 3"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": AITAI_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R107 Step 3 to 爱泰 ({AITAI_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
