#!/usr/bin/env python3
"""R76 Step5 complete + Step6 ops — 快速推进"""
import asyncio, json, os, time, re
import websockets

CREDS = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
MY_AGENT_ID = CREDS['agent_id']
MY_API_KEY = CREDS['api_key']
WORKSPACE_ID = "ws:ws_f26e5-R76-dev"
QA_SHA = "556fc1e"

BOTS = {"小爱": {"aid": "ws_c47032fa1f67"}}

async def main():
    async with websockets.connect("wss://wsim.datahome73.cloud/ws", max_size=2**20) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": MY_API_KEY}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert resp.get("type") == "auth_ok"
        print("✅ Auth OK\n")

        await ws.send(json.dumps({"type": "set_active_channel", "channel": WORKSPACE_ID, "agent_id": MY_AGENT_ID}))

        # === Step 5 Complete ===
        print("📌 Step 5 Complete: 10/10 ALL GREEN 🟢")
        await ws.send(json.dumps({
            "type": "message", "channel": WORKSPACE_ID,
            "content": f"!step_complete step5 --output {QA_SHA} --summary '测试验证完成 ✅ 10/10 ALL GREEN 🟢'",
            "from_name": "小谷", "agent_id": MY_AGENT_ID,
            "id": f"step5done-{int(time.time())}", "ts": time.time(),
        }))
        await asyncio.sleep(3)

        # Collect responses
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                d = json.loads(raw)
                if d.get("content"):
                    print(f"📩 [{d.get('from_name','?')}]: {d['content'][:500]}")
            except asyncio.TimeoutError:
                pass

        # === Step 6: Inbox to 小爱 ===
        print("\n" + "="*60)
        print("🦸 Step 6: 派活给 小爱 — 合并部署")
        print("="*60)
        task = f"""【R76 Step 6 任务 — 合并部署归档 🦸】

角色: 项目管理
全链路状态：
✅ Step2 技术方案 — 架构师 de7f437
✅ Step3 编码 — 开发工程师 3db77b0 (+411行, 5文件)
✅ Step4 审查 — 审查工程师 c2b31ff (🟡条件通过，3项修复)
✅ Step5 测试 — 测试工程师 {QA_SHA} (10/10 ALL GREEN 🟢)

请执行：
1. git checkout main && git merge dev
2. git push origin main
3. docker build -t ws-bridge:r76 .
4. 部署生产容器（替换运行中的 ws-bridge 容器）
5. !pipeline_status R76 确认健康
6. 关闭工作室（触发归档，各 Tab 干净）
7. TODO.md 更新版本号

完成后回复本 inbox 告知合并 SHA 和部署结果。
— 需求分析师 PM"""

        aid = BOTS["小爱"]["aid"]
        await ws.send(json.dumps({
            "type": "message", "channel": f"_inbox:{aid}",
            "content": task, "from_name": "小谷",
            "agent_id": MY_AGENT_ID,
            "id": f"step6-{int(time.time())}", "ts": time.time(),
        }))
        print("📨 Inbox → 小爱")
        print("⏳ 等待 小爱 合并部署（最长 5 分钟）...")

        my_inbox = f"_inbox:{MY_AGENT_ID}"
        deadline = time.time() + 300
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                d = json.loads(raw)
                ch = d.get("channel", "")
                content = d.get("content", "")
                sid = d.get("agent_id", "")
                if content and ch == my_inbox and sid != MY_AGENT_ID:
                    print(f"\n📩 [小爱回复]: {content[:500]}")
                    print("\n✅ R76 管线完成！")
                    return
                elif content:
                    print(f"📩 [{d.get('from_name','?')}]: {content[:300]}")
            except asyncio.TimeoutError:
                pass

        print("\n⚠️ 小爱未回复，请手动确认部署状态")

asyncio.run(main())
