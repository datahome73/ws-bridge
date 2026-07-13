"""Send R104 Step 3 to 爱泰 via raw WebSocket."""
import asyncio, json

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
        # Auth
        await ws.send(json.dumps({"type": "auth", "api_key": API_KEY}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"Auth: {auth_resp.get('type')}")
        if auth_resp.get('type') != 'auth_ok':
            print(f"FAIL: {auth_resp}")
            return

        content = (
            "📋 R104 Step 3 — 编码实现 到你了！\n\n"
            "R104: Web 服务增加工作区列表 API\n\n"
            "📄 需求：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R104/R104-product-requirements.md\n"
            "📋 WORK_PLAN：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R104/WORK_PLAN.md\n\n"
            "🔍 任务（1 文件 +15 行）：\n"
            "在 server/web_viewer.py 新增 handle_api_workspaces() 函数 + 在 setup_routes() 注册 /api/workspaces 路由\n"
            "- 调用 workspace.get_all_workspaces() 读取数据\n"
            "- 返回格式与 workspace_api.py 一致\n"
            "- 验证 token 授权\n\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R104 Step 3"
        )

        import time
        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": AITAI_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R104 Step 3 to 爱泰 ({AITAI_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
