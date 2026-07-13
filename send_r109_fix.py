"""Send R109 Step 3 fix request to 爱泰."""
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
            "退回 🔄 R109 Step 3 — 测试发现11项失败，需修复\n\n"
            "📄 测试报告：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R109/R109-test-report.md\n\n"
            "🔴 P0 — 必须修复：\n"
            "1. common/config.py 缺少 AUTO_DISPATCH_ENABLED → 运行时 AttributeError\n\n"
            "🟡 需修复：\n"
            "2. ws_server 未实现 _bot_status.json 写入\n"
            "3. web_ui 仍用 HTTP 轮询，未改为文件读取\n"
            "4. 前端减法：BIND_TEMPLATE/管理员Tab/bind路由未删除\n\n"
            "🟢 顺手清理：\n"
            "5. common/config.py 中 HTTP_PORT/APP_ID 死代码删除\n\n"
            "⚠️ 修复后重新推 dev，前缀用：已完成 ✅ R109 Step 3 (fix)"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": AITAI_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R109 Step 3 fix request to 爱泰 ({AITAI_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
