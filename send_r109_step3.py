"""Send R109 Step 3 to 爱泰."""
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
            "📋 R109 Step 3 — 编码实现 到你了！\n\n"
            "R109: 架构大重构 — server/ 拆分为 ws-server/ + web-ui/\n"
            "小开技术方案已推 dev (b7f1024)\n\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R109/R109-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R109/WORK_PLAN.md\n"
            "📋 技术方案：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R109/r109-step2-tech-plan.md\n\n"
            "🔍 任务：\n"
            "1. server/ → ws-server/ 目录重命名\n"
            "2. 新建 web-ui/ 目录（从 server/web_service.py + web_viewer.py 搬迁）\n"
            "3. auth.py 拆分为 ws-server/auth.py + web-ui/auth.py\n"
            "4. config.py 减法（181→~40 行）\n"
            "5. message_store.py 拆分（ws-server 完整 + web-ui 只读）\n"
            "6. persistence.py 拆分（web-ui 仅 sessions/bind）\n"
            "7. 更新 Dockerfile + supervisord.conf 路径\n"
            "8. 删除 entrypoint.py\n\n"
            "⚠️ 完成 git 推 dev 后回复此 inbox\n"
            "⚠️ 前缀：已完成 ✅ R109 Step 3"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": AITAI_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R109 Step 3 to 爱泰 ({AITAI_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
