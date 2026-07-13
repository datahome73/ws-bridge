"""Send R107 Step 6 deploy to 小爱."""
import asyncio, json, time

creds_path = '/opt/data/home/.ws-bridge/小谷.json'
with open(creds_path) as f:
    creds = json.load(f)

API_KEY = creds['api_key']
AGENT_ID = creds['agent_id']

XIAOAI_ID = "ws_c47032fa1f67"

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
            "📋 R107 Step 6 — 部署 到你了！\n\n"
            "R107: 消除重复代码 + 自动派活功能落地（代码完成，不通电）\n"
            "✅ 全管线通过：小开方案 → 爱泰编码 → 小周审查 ✅ → 泰虾测试 40/40 🟢\n"
            "✅ 已合并到 main (f016ee4)\n\n"
            "🔍 部署操作：\n"
            "1. main 拉取最新代码 (f016ee4)\n"
            "2. server/main.py/pipeline_context.py/config.py 有改动，需重建 Docker 镜像\n"
            "3. 重启容器，确认 8765 🟢 8766 🟢\n"
            "4. 验证：重启后手工派活一次，管线操作不受影响（AUTO_DISPATCH_ENABLED 默认关闭）\n\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R107 Step 6"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": XIAOAI_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R107 Step 6 to 小爱 ({XIAOAI_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
