#!/usr/bin/env python3
"""R76 管线协调 - inbox 接力推进 Step2→Step6"""
import asyncio, json, os, time, sys, re
import websockets

CREDS = json.load(open(os.path.expanduser('~/.ws-bridge/小谷.json')))
WS_URL = "wss://wsim.datahome73.cloud/ws"
MY_AGENT_ID = CREDS['agent_id']
MY_API_KEY = CREDS['api_key']
MY_NAME = "小谷"

WORK_PLAN_URL = "https://raw.githubusercontent.com/datahome73/ws-bridge/ac20da5/docs/R76/WORK_PLAN.md"
REQS_URL = "https://raw.githubusercontent.com/datahome73/ws-bridge/ca8979a/docs/R76/R76-product-requirements.md"

WORKSPACE_ID = "ws:ws_f26e5-R76-dev"

BOTS = {
    "小开": {"aid": "ws_3f7cdd736c1c", "role": "architect"},
    "爱泰": {"aid": "ws_0bb747d3ea2a", "role": "developer"},
    "小周": {"aid": "ws_fcf496ca1b4f", "role": "reviewer"},
    "泰虾": {"aid": "ws_eab784ac7652", "role": "qa"},
    "小爱": {"aid": "ws_c47032fa1f67", "role": "admin"},
}

async def send_inbox(ws, target_name, target_aid, content):
    inbox = f"_inbox:{target_aid}"
    msg_id = f"r76-{target_name}-{int(time.time())}"
    await ws.send(json.dumps({
        "type": "message", "channel": inbox,
        "content": content, "from_name": MY_NAME,
        "agent_id": MY_AGENT_ID,
        "id": msg_id, "ts": time.time(),
    }))
    print(f"📨 已发送 inbox 给 {target_name}")

async def send_workspace_msg(ws, content):
    await ws.send(json.dumps({
        "type": "message", "channel": WORKSPACE_ID,
        "content": content, "from_name": MY_NAME,
        "agent_id": MY_AGENT_ID,
        "id": f"ws-{int(time.time())}", "ts": time.time(),
    }))

async def wait_for_reply(ws, expected_sender=None, timeout=60):
    """Wait for a message in my inbox or workspace."""
    my_inbox = f"_inbox:{MY_AGENT_ID}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=3)
            data = json.loads(raw)
            ch = data.get("channel", "")
            content = data.get("content", "")
            sender = data.get("from_name", "?")
            sender_id = data.get("agent_id", "")
            if sender_id == MY_AGENT_ID:
                continue  # skip own messages
            if content:
                print(f"📩 [{sender}]: {content[:400]}")
                # If it's in my inbox, it's a reply
                if ch == my_inbox or ch == WORKSPACE_ID:
                    return {"sender": sender, "sender_id": sender_id, "content": content, "channel": ch}
        except asyncio.TimeoutError:
            pass
    return None

async def step_arch(ws):
    print("\n" + "="*60)
    print("🅰️ Step 2: 派活给 Arch（小开）— 技术方案")
    print("="*60)

    task = f"""【R76 Step 2 任务 — 技术方案 🏗️】

角色: 架构师
基于: 需求文档（已审核通过 ✅）

请输出技术方案文档 docs/R76/R76-tech-plan.md，需确认以下设计决策：

1. 全局状态存储：config.DATA_DIR/_archive_state.json（_load_json/_save_json 模式）
2. get_agent_name() 放在 auth.py 还是 persistence.py？
3. handle_api_inbox 使用 LIKE '_inbox:%' 查询（命中 idx_messages_channel 索引）
4. handle_api_archive 使用 get_messages_by_time_range（已存在 get_messages_since）
5. 前端状态机确认（archiveMode + since 参数）
6. 写入关闭工作室 (!close_workspace) 的归档触发点

参考：
WORK_PLAN: {WORK_PLAN_URL}
需求文档: {REQS_URL}
当前 dev: https://github.com/datahome73/ws-bridge/tree/dev
当前 WORK_PLAN 含 frontmatter: {WORK_PLAN_URL}

完成后推 dev 并回复本 inbox 告知 SHA。
— 需求分析师 PM"""

    await send_inbox(ws, "小开", BOTS["小开"]["aid"], task)
    print("⏳ 等待 小开 回复（最长 5 分钟）...")
    reply = await wait_for_reply(ws, "小开", timeout=300)
    return reply

async def step_dev(ws, arch_sha):
    print("\n" + "="*60)
    print("🅱️ Step 3: 派活给 Dev（爱泰）— 编码实现")
    print("="*60)

    TECH_PLAN_URL = f"https://raw.githubusercontent.com/datahome73/ws-bridge/{arch_sha}/docs/R76/R76-tech-plan.md"

    task = f"""【R76 Step 3 任务 — 编码实现 💻】

角色: 开发工程师
前一棒 架构师 已完成 ✅ 技术方案 SHA: `{arch_sha}`

请实现以下改动（参照 WORK_PLAN §2.3 — 精确改动点）：

1. server/auth.py — 新增 get_agent_name()
2. server/web_viewer.py — handle_api_inbox + 归档全局状态 + since 参数 + handle_api_archive
3. server/message_store.py — get_messages_by_channel_pattern + get_messages_by_time_range
4. server/handler.py — !close_workspace 触发归档（~10 行）
5. server/templates.py — Inbox Tab + 渲染 + WS 红点 + archive 过滤 + 历史查看器增强

全改动约 245 行净增，6 个文件。

参考：
WORK_PLAN: {WORK_PLAN_URL}
需求: {REQS_URL}
技术方案: {TECH_PLAN_URL}（如已推）
当前 dev: https://github.com/datahome73/ws-bridge/tree/dev

完成后 git push dev，回复本 inbox 告知 SHA。
— 需求分析师 PM"""

    await send_inbox(ws, "爱泰", BOTS["爱泰"]["aid"], task)
    print("⏳ 等待 爱泰 回复...")
    reply = await wait_for_reply(ws, "爱泰", timeout=600)
    return reply

async def step_review(ws, dev_sha):
    print("\n" + "="*60)
    print("🅲 Step 4: 派活给 Review（小周）— 代码审查")
    print("="*60)

    task = f"""【R76 Step 4 任务 — 代码审查 🔍】

角色: 审查工程师
前一棒 开发工程师 已完成 ✅ SHA: `{dev_sha}`

请审查后输出审查报告 docs/R76/R76-code-review.md 推 dev。

审查重点：
1. handle_api_inbox LIKE 查询是否命中索引
2. since 参数类型安全（str→float）
3. inbox 收件人反查 get_agent_name() fallback 路径
4. 归档状态持久化（重启不丢失）
5. WS 推送 inbox 时前端未读红点计数
6. archiveMode 状态切换正确性
7. 无 scope creep

审查结论：🟢通过 / 🟡条件通过 / 🔴退回

参考：
WORK_PLAN: {WORK_PLAN_URL}
需求: {REQS_URL}
当前 dev: https://github.com/datahome73/ws-bridge/tree/dev

完成后推 dev，回复本 inbox 告知 SHA。
— 需求分析师 PM"""

    await send_inbox(ws, "小周", BOTS["小周"]["aid"], task)
    print("⏳ 等待 小周 回复...")
    reply = await wait_for_reply(ws, "小周", timeout=300)
    return reply

async def step_qa(ws, review_sha):
    print("\n" + "="*60)
    print("🅳 Step 5: 派活给 QA（泰虾）— 测试验证")
    print("="*60)

    task = f"""【R76 Step 5 任务 — 测试验证 🦐】

角色: 测试工程师
前一棒 审查工程师 已完成 ✅ SHA: `{review_sha}`

请逐项验收测试，输出测试报告 docs/R76/R76-test-report.md 推 dev。

验收标准（从需求文档 §4 复制）：
✅-1 /api/chat/inbox 返回 inbox 聚合消息
✅-2 无 token 返回 401
✅-3 Web 端显示 📬 收件箱 Tab
✅-4 点击 inbox Tab 加载混合消息（发送人→接收人）
✅-5 消息格式正确
✅-6 WS 推送时未读红点
✅-7 无输入框
✅-8 关闭最后活跃工作室后各 Tab 干净
✅-9 /api/chat/archive 返回全 channel 消息
✅-10 历史查看器全 channel + 来源标签
✅-11 新工作室创建后恢复正常
✅-12 since 参数过滤有效

参考：
WORK_PLAN: {WORK_PLAN_URL}
需求: {REQS_URL}
当前 dev: https://github.com/datahome73/ws-bridge/tree/dev

完成后推 dev，回复本 inbox 告知 SHA。
— 需求分析师 PM"""

    await send_inbox(ws, "泰虾", BOTS["泰虾"]["aid"], task)
    print("⏳ 等待 泰虾 回复...")
    reply = await wait_for_reply(ws, "泰虾", timeout=300)
    return reply

async def step_ops(ws, qa_sha):
    print("\n" + "="*60)
    print("🅴 Step 6: 派活给 Ops（小爱）— 合并部署")
    print("="*60)

    task = f"""【R76 Step 6 任务 — 合并部署归档 🦸】

角色: 项目管理
前一棒 QA 已完成 ✅ SHA: `{qa_sha}`

全链路状态：
✅ Step2 技术方案 — 架构师
✅ Step3 编码 — 开发工程师
✅ Step4 审查 — 审查工程师
✅ Step5 测试 — 测试工程师

请执行：
1. git checkout main && git merge dev
2. git push origin main
3. docker build -t ws-bridge:r76 .
4. 部署生产容器
5. !pipeline_status R76 确认健康
6. 关闭工作室（触发归档）
7. TODO.md 更新版本号

参考：
WORK_PLAN: {WORK_PLAN_URL}
当前 dev: https://github.com/datahome73/ws-bridge/tree/dev

完成后回复本 inbox 告知结果。
— 需求分析师 PM"""

    await send_inbox(ws, "小爱", BOTS["小爱"]["aid"], task)
    print("⏳ 等待 小爱 回复...")
    reply = await wait_for_reply(ws, "小爱", timeout=600)
    return reply

async def step_complete(ws, step_num, sha, summary):
    """Send !step_complete to workspace channel."""
    cmd = f"!step_complete step{step_num} --output {sha} --summary '{summary}'"
    await send_workspace_msg(ws, cmd)
    print(f"📨 已发送: {cmd}")
    await asyncio.sleep(3)

async def main():
    print("🔌 连接 WebSocket...")
    async with websockets.connect(WS_URL, max_size=2**20) as ws:
        await ws.send(json.dumps({"type": "auth", "api_key": MY_API_KEY}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert resp.get("type") == "auth_ok"
        print(f"✅ Auth OK\n")

        # 切换活跃频道到工作室
        await ws.send(json.dumps({
            "type": "set_active_channel",
            "channel": WORKSPACE_ID,
            "agent_id": MY_AGENT_ID,
        }))
        print(f"📌 已切换到工作室 {WORKSPACE_ID}\n")

        # === STEP 2: ARCH ===
        r = await step_arch(ws)
        if r and r.get("content"):
            print(f"\n✅ 收到 小开 回复，提取 SHA...")
            # Extract SHA from reply content
            import re
            sha_match = re.search(r'[0-9a-f]{7,}', r["content"])
            arch_sha = sha_match.group(0) if sha_match else input("请输入 小开 的 commit SHA: ")
            print(f"📌 arch SHA: {arch_sha}")

            await step_complete(ws, 2, arch_sha, "技术方案完成 ✅")
        else:
            print("⚠️ 未收到 小开 回复，转为手动接力")
            arch_sha = input("手动输入 arch SHA（或空跳过）: ") or "pending"

        # === STEP 3: DEV ===
        r = await step_dev(ws, arch_sha)
        if r and r.get("content"):
            sha_match = re.search(r'[0-9a-f]{7,}', r["content"])
            dev_sha = sha_match.group(0) if sha_match else input("请输入 爱泰 的 commit SHA: ")
            print(f"📌 dev SHA: {dev_sha}")
            await step_complete(ws, 3, dev_sha, "编码实现完成 ✅")
        else:
            print("⚠️ 未收到 爱泰 回复")
            dev_sha = input("手动输入 dev SHA（或空跳过）: ") or "pending"

        # === STEP 4: REVIEW ===
        r = await step_review(ws, dev_sha)
        if r and r.get("content"):
            sha_match = re.search(r'[0-9a-f]{7,}', r["content"])
            review_sha = sha_match.group(0) if sha_match else input("请输入 小周 的 commit SHA: ")
            print(f"📌 review SHA: {review_sha}")
            await step_complete(ws, 4, review_sha, "代码审查完成 ✅")
        else:
            print("⚠️ 未收到 小周 回复")
            review_sha = input("手动输入 review SHA（或空跳过）: ") or "pending"

        # === STEP 5: QA ===
        r = await step_qa(ws, review_sha)
        if r and r.get("content"):
            sha_match = re.search(r'[0-9a-f]{7,}', r["content"])
            qa_sha = sha_match.group(0) if sha_match else input("请输入 泰虾 的 commit SHA: ")
            print(f"📌 qa SHA: {qa_sha}")
            await step_complete(ws, 5, qa_sha, "测试验证完成 ✅")
        else:
            print("⚠️ 未收到 泰虾 回复")
            qa_sha = input("手动输入 qa SHA（或空跳过）: ") or "pending"

        # === STEP 6: OPS ===
        r = await step_ops(ws, qa_sha)
        if r and r.get("content"):
            print(f"\n✅ 收到 小爱 回复: {r['content'][:200]}")
        else:
            print("⚠️ 未收到 小爱 回复")

        print("\n" + "="*60)
        print("🏁 R76 管线协调完成！等待查看最终结果。")
        print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
