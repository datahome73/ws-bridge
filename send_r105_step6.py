"""Send R105 Step 6 deploy to 小爱."""
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
            "📋 R105 Step 6 — 上线确认 到你了！\n\n"
            "R105: 统一 Bot 回复模板\n"
            "✅ 全管线通过：小开方案 → 爱泰创建文档 → 小周审查 ✅ → 泰虾测试 11/11 🟢\n"
            "✅ 已合并到 main (cdc0973)\n\n"
            "🔍 本轮是文档变更（skills/reply-format-protocol.md），无 Server 代码变动，无需重建 Docker 镜像。\n"
            "任务：确认各 bot 配置已生效，回复格式按照协议执行。\n\n"
            "⚠️ 完成后回复此 inbox，前缀用：已完成 ✅ R105 Step 6"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": XIAOAI_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R105 Step 6 to 小爱 ({XIAOAI_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
