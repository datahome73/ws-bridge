"""Send R99 Step 2 task to 小开 via inbox - no ACK wait."""
import asyncio, sys, json, time, uuid
sys.path.insert(0, '/opt/data/ws-bridge/clients/python')

async def main():
    import websockets

    # Load 小谷 creds
    with open("/opt/data/home/.ws-bridge/小谷.json") as f:
        creds = json.load(f)

    ws_url = "wss://wsim.datahome73.cloud/ws"
    api_key = creds["api_key"]
    agent_id = creds["agent_id"]

    async with websockets.connect(ws_url, max_size=2**20, ping_interval=20, ping_timeout=10) as ws:
        # Auth
        await ws.send(json.dumps({"type": "auth", "api_key": api_key}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print(f"Auth: {auth_resp.get('type')}")

        PM_AGENT_ID = "ws_f26e585f6479"

        task = f"""🧱 R99 Step 2 — 技术方案

需求文档：https://github.com/datahome73/ws-bridge/blob/dev/docs/R99/R99-product-requirements.md

工作计划：https://github.com/datahome73/ws-bridge/blob/dev/docs/R99/WORK_PLAN.md

请根据产品需求设计技术方案：
1. 4 级权限等级（L1-L4）在 _api_key 文件中的 level 字段存储方案（字段定义、初始化值、升级逻辑）
2. 安全检查插入位置⑦的实现：ws_handler() 收到 _inbox:server → auto 放行；_inbox:<bot_id> → 检查发送者 level>=4
3. Agent Card 提交时 L2→L3 自动晋升逻辑
4. 系统名称统一为"系统"的改动点（Web端 + 服务端）

产出：docs/R99/R99-tech-plan.md
推 dev 分支后回复 ✅ 完成到我的收件箱 _inbox:{PM_AGENT_ID}"""

        target = "ws_3f7cdd736c1c"
        payload = {
            "type": "message",
            "channel": f"_inbox:{target}",
            "content": task,
            "from_name": "小谷",
            "agent_id": agent_id,
            "id": f"r99-step2-{int(time.time())}",
            "ts": time.time(),
        }
        await ws.send(json.dumps(payload))
        print(f"✅ Sent task to 小开 ({target[:16]}...)")

        # Read responses for a bit
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                msg = json.loads(raw)
                mt = msg.get("type", "")
                ch = msg.get("channel", "")
                ct = msg.get("content", "")[:150]
                if "error" in mt or "ack" in mt.lower():
                    print(f"  << {mt}: {ct}")
            except asyncio.TimeoutError:
                pass

        print("Done.")

asyncio.run(main())
