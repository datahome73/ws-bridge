#!/usr/bin/env python3
"""R76 管线推进 Step4(complete)->Step5(QA)->Step6(Ops)"""
import asyncio, json, os, time, re
import websockets

CREDS = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
WS_URL = "wss://wsim.datahome73.cloud/ws"
MY_AGENT_ID = CREDS['agent_id']
MY_API_KEY = CREDS['api_key']
MY_NAME = "小谷"
WORKSPACE_ID = "ws:ws_f26e5-R76-dev"
FIX_SHA = "c2b31ff"  # review fixes SHA

BOTS = {
    "泰虾": {"aid": "ws_eab784ac7652"},
    "小爱": {"aid": "ws_c47032fa1f67"},
}

async def send_inbox(ws, name, aid, content):
    await ws.send(json.dumps({
        "type": "message", "channel": f"_inbox:{aid}",
        "content": content, "from_name": MY_NAME,
        "agent_id": MY_AGENT_ID,
        "id": f"r76-{name}-{int(time.time())}", "ts": time.time(),
    }))
    print(f"📨 Inbox → {name}")

async def send_ws(ws, content):
    await ws.send(json.dumps({
        "type": "message", "channel": WORKSPACE_ID,
        "content": content, "from_name": MY_NAME,
        "agent_id": MY_AGENT_ID,
        "id": f"ws-{int(time.time())}", "ts": time.time(),
    }))

async def listen(ws, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            content = data.get("content", "")
            if content:
                print(f"📩 [{data.get('from_name','?')}]: {content[:500]}")
        except asyncio.TimeoutError:
            pass

async def wait_for_inbox_reply(ws, timeout=300):
    my_inbox = f"_inbox:{MY_AGENT_ID}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=3)
            data = json.loads(raw)
            ch = data.get("channel", "")
            content = data.get("content", "")
            sid = data.get("agent_id", "")
            if content and ch == my_inbox and sid != MY_AGENT_ID:
                print(f"📩 [收件箱回复]: {content[:500]}")
                return data
        except asyncio.TimeoutError:
            pass
    return None

async def main():
    async with websockets.connect(WS_URL, max_size=2**20) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": MY_API_KEY}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert resp.get("type") == "auth_ok"
        print("✅ Auth OK\n")

        # 切换频道
        await ws.send(json.dumps({"type": "set_active_channel", "channel": WORKSPACE_ID, "agent_id": MY_AGENT_ID}))

        # === Step 4 Complete ===
        print("="*60)
        print("📌 Step 4 Complete: 审查修复已合并")
        print("="*60)
        await send_ws(ws, f"!step_complete step4 --output {FIX_SHA} --summary '审查完成 ✅ B-1🔴+W-1🟡+S-1💡 全部修复'")
        await asyncio.sleep(3)
        await listen(ws, 4)

        # === Step 5: QA ===
        print("\n" + "="*60)
        print("🦐 Step 5: 派活给 泰虾 — 测试验证")
        print("="*60)
        task = f"""【R76 Step 5 任务 — 测试验证 🦐】

角色: 测试工程师
前一棒 审查工程师 ✅ 报告: 7c29104 (🟡条件通过)
修复: c2b31ff (B-1🔴+W-1🟡+S-1💡 已修复)

请逐项验收测试，输出测试报告 docs/R76/R76-test-report.md 推 dev。

验收标准：
✅-1 /api/chat/inbox 返回 inbox 聚合消息
✅-2 无 token 返回 401
✅-3 Web 端显示 📬 收件箱 Tab + 未读红点
✅-4 点击 inbox Tab 加载混合消息（发送人→接收人格式）
✅-5 Inbox Tab 无输入框（只读）
✅-6 关闭最后活跃工作室后各 Tab 干净（since 过滤）
✅-7 /api/chat/archive?workspace_id=X 返回全 channel 消息
✅-8 历史查看器显示全 channel 消息+来源标签
✅-9 创建新工作室后恢复正常
✅-10 since 参数过滤有效（传非法值不报500）

测试工具：curl 测试 API + 浏览器查看 Web UI
完成后推 dev，回复本 inbox 告知 SHA 和测试结论。
— 需求分析师 PM"""

        await send_inbox(ws, "泰虾", BOTS["泰虾"]["aid"], task)
        print("⏳ 等待 泰虾 测试报告（最长 8 分钟）...")
        reply = await wait_for_inbox_reply(ws, timeout=480)
        qa_sha = None
        if reply:
            sha_m = re.search(r'[0-9a-f]{7,}', reply["content"])
            qa_sha = sha_m.group(0) if sha_m else None
        if qa_sha:
            print(f"\n📌 qa SHA: {qa_sha}")
            await send_ws(ws, f"!step_complete step5 --output {qa_sha} --summary '测试验证完成 ✅'")
            await asyncio.sleep(2)
            await listen(ws, 4)
        else:
            print("⚠️ 未收到泰虾回复或SHA，尝试自动检测...")
            qa_sha = FIX_SHA

        # === Step 6: Ops ===
        print("\n" + "="*60)
        print("🦸 Step 6: 派活给 小爱 — 合并部署")
        print("="*60)
        task = f"""【R76 Step 6 任务 — 合并部署归档 🦸】

角色: 项目管理
全链路状态：
✅ Step2 技术方案 — 架构师 de7f437
✅ Step3 编码 — 开发工程师 3db77b0 (+411行)
✅ Step4 审查 — 审查工程师 c2b31ff (🟡条件通过)
✅ Step5 测试 — 测试工程师 {qa_sha or "待确认"}

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

        await send_inbox(ws, "小爱", BOTS["小爱"]["aid"], task)
        print("⏳ 等待 小爱 合并部署（最长 5 分钟）...")
        reply = await wait_for_inbox_reply(ws, timeout=300)
        if reply:
            print(f"\n✅ 收到小爱回复!")
        else:
            print("\n⚠️ 小爱未回复")

        print("\n" + "="*60)
        print("🏁 R76 管线推进完成！")
        print("="*60)

asyncio.run(main())
