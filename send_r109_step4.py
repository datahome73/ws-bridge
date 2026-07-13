"""Send R109 Step 4 to 小周."""
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
            "📋 R109 Step 4 — 代码审查 到你了！\n\n"
            "R109: 架构大重构 server/ → ws_server/ + web_ui/ + common/ 拆分\n\n"
            "爱泰已完成编码，commit: a889f0d\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R109/R109-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R109/WORK_PLAN.md\n"
            "📋 技术方案：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R109/r109-step2-tech-plan.md\n\n"
            "🔍 审查重点：\n"
            "- 目录结构：ws_server/ + web_ui/ + common/ 拆分是否正确\n"
            "- import 链：web_ui 是否全改为本 package 绝对路径\n"
            "- ws_server 内部是否保持相对 import\n"
            "- config.py 减法（176→~45 行）\n"
            "- auth.py 拆分边界\n"
            "- 回滚方案可行性\n\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R109 Step 4"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": XIAOZHOU_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R109 Step 4 to 小周 ({XIAOZHOU_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
