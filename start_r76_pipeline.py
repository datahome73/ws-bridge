#!/usr/bin/env python3
"""Check current pipeline state and start R76 if needed."""
import asyncio, json, os, time, sys
import websockets

CREDS = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
WS_URL = "wss://wsim.datahome73.cloud/ws"
WORK_PLAN_URL = "https://raw.githubusercontent.com/datahome73/ws-bridge/ac20da5/docs/R76/WORK_PLAN.md"
REQS_URL = "https://raw.githubusercontent.com/datahome73/ws-bridge/ca8979a/docs/R76/R76-product-requirements.md"

MY_AGENT_ID = CREDS['agent_id']
MY_API_KEY = CREDS['api_key']
MY_NAME = "小谷"

BOTS = {
    "小开": "ws_3f7cdd736c1c",  # arch
    "爱泰": "ws_0bb747d3ea2a",  # dev
    "小周": "ws_fcf496ca1b4f",  # review
    "泰虾": "ws_eab784ac7652",  # qa
    "小爱": "ws_c47032fa1f67",  # operations
}

async def main():
    print("🔌 连接 WebSocket...")
    async with websockets.connect(WS_URL, max_size=2**20) as ws:
        # Auth
        await ws.send(json.dumps({"type": "auth", "api_key": MY_API_KEY}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert resp.get("type") == "auth_ok", f"Auth failed: {resp}"
        print(f"✅ Auth OK — agent_id={MY_AGENT_ID[:16]}...")

        my_inbox = f"_inbox:{MY_AGENT_ID}"

        # 检查当前状态
        await ws.send(json.dumps({
            "type": "message", "channel": "_admin",
            "content": "!pipeline_status R76",
            "from_name": MY_NAME, "agent_id": MY_AGENT_ID,
            "id": f"status-{int(time.time())}", "ts": time.time(),
        }))

        # 等几秒收集响应
        print("⏳ 等待响应...")
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(raw)
                ch = data.get("channel", "")
                content = data.get("content", "")
                if content:
                    print(f"📩 [{data.get('from_name','?')}]: {content[:500]}")
            except asyncio.TimeoutError:
                pass

        # 通知全员
        for name, aid in BOTS.items():
            inbox = f"_inbox:{aid}"
            msg = f"""【R76 管线启动 📋】

方向：Inbox 可视化 + 时间切片归档
需求文档: {REQS_URL}
WORK_PLAN: {WORK_PLAN_URL}

管线计划：
Step 2 → 架构师 / 技术方案
Step 3 → 开发工程师 / 编码实现
Step 4 → 审查工程师 / 代码审查
Step 5 → 测试工程师 / 测试验证
Step 6 → 项目管理 / 合并部署

— 需求分析师 PM"""

            await ws.send(json.dumps({
                "type": "message", "channel": inbox,
                "content": msg, "from_name": MY_NAME,
                "agent_id": MY_AGENT_ID,
                "id": f"kickoff-{name}-{int(time.time())}",
                "ts": time.time(),
            }))
            print(f"📨 已通知 {name}")
            await asyncio.sleep(0.5)

        # 启动管线
        cmd = f"!pipeline_start R76 --work_plan_url {WORK_PLAN_URL}"
        await ws.send(json.dumps({
            "type": "message", "channel": "_admin",
            "content": cmd, "from_name": MY_NAME,
            "agent_id": MY_AGENT_ID,
            "id": f"pstart-R76-{int(time.time())}",
            "ts": time.time(),
        }))
        print(f"\n🚀 已发送: {cmd}")

        # 等待响应
        deadline = time.time() + 10
        print("⏳ 等待管线启动响应...")
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(raw)
                content = data.get("content", "")
                ch = data.get("channel", "")
                sender = data.get("from_name", "?")
                if content:
                    print(f"📩 [{sender}][{ch}]: {content[:600]}")
            except asyncio.TimeoutError:
                pass

        print("\n✅ 启动完成。下一步请观察管线 Step 1 → 2 自动推进。")

if __name__ == "__main__":
    asyncio.run(main())
