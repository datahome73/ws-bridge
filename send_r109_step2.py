"""Send R109 Step 2 to 小开 via raw WebSocket."""
import asyncio, json, time

creds_path = '/opt/data/home/.ws-bridge/小谷.json'
with open(creds_path) as f:
    creds = json.load(f)

API_KEY = creds['api_key']
AGENT_ID = creds['agent_id']

XIAOKAI_ID = "ws_3f7cdd736c1c"

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
            "【R109 Step 2 架构方案】auto_chain=true，Step 1 ✅ 已完成。请输出技术方案文档 `docs/R109/r109-step2-tech-plan.md`，涵盖：\n\n"
            "1. 整体迁移策略（分步：先 web-ui，再 ws-server，最后删 server/）\n"
            "2. auth.py 拆分边界\n"
            "3. message_store.py 只读副本\n"
            "4. persistence.py 拆分 + JSON 竞争\n"
            "5. config.py 减法（181→~40 行，列出删除项）\n"
            "6. Bot 状态文件传递（时序与竞争条件）\n"
            "7. Dockerfile + supervisor 更新\n"
            "8. import 迁移清单\n\n"
            "⚠️ 产出：docs/R109/r109-step2-tech-plan.md，完成后回复此 inbox"
        )

        msg = {
            "type": "message", "channel": "_inbox:server",
            "content": content,
            "agent_id": AGENT_ID,
            "to_agent": XIAOKAI_ID,
            "id": f"msg-{int(time.time()*1000)}", "ts": time.time(),
        }
        await ws.send(json.dumps(msg))
        print(f"📤 Sent R109 Step 2 to 小开 ({XIAOKAI_ID})")
        await asyncio.sleep(2)

asyncio.run(main())
