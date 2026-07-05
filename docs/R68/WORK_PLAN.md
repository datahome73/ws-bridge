# R68 工作计划 — Bot 私有收件箱通道 📥

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** 📋 定稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R68/R68-product-requirements.md v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动极小，严禁 scope creep**

- 不改入：`server/web_viewer.py`、`server/templates.py`、`server/workspace.py`、`shared/protocol.py`（除新增常量外）
- 不改出：不引入 bot 端收件箱客户端、不修改工作室消息路由（workspace broadcast）、不引入消息加密
- 编码者超出 scope 的改动，审查者直接打回

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | admin | arch | — |

---

## 1. 管线总览

### 改动范围

仅 4 个文件，精确改动点（基于 `origin/dev` 基线 `638a02b`）：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A1 | 新增 `INBOX_CHANNEL_PREFIX` 常量 | `shared/protocol.py` L165 后 | ~2 行 |
| 2 | A1 | 新增 3 个收件箱工具函数 | `server/persistence.py` 文件末尾 | ~15 行 |
| 3 | A2 | `handle_broadcast()` 新增 `_inbox` 路由分支 | `server/handler.py` L4000-L4020 后（_admin 拦截后，channel resolution 前） | ~30 行 |
| 4 | A3 | `_cmd_step_complete()` 收件箱派活 + 工作室轻量通知 | `server/handler.py` L2516-L2533 区域改造 | ~20 行 |
| 5 | A3 | `_cmd_step_handoff()` 收件箱派活 + 工作室轻量通知 | `server/handler.py` 对应区域（与 step_complete 对称） | ~10 行 |
| 6 | A1 | Agent 注册后自动创建收件箱 | `server/auth.py` 审批通过后逻辑 | ~5 行 |

**总估算：** ~82 行净改

### 改造对照

**方向 A 改造前后对比：**

```
当前（广播模式）：
  !step_complete stepN
    → 全量广播到工作室：所有成员收到完整任务消息
    → Bot 上下文被噪声污染
    → @mention 从噪声中识别 → 可能不触发

改造后（收件箱 + 轻量通知）：
  !step_complete stepN
    → 📥 向 _inbox:<next_bot_id> 发完整任务消息（仅目标 bot 收到）
    → 🏠 向 workspace 发 @bot_name 🔔 轻量通知（全员可见进展）
    → Bot 的收件箱 = 干净上下文
    → _admin 频道可见任务历史
```

---

## 2. 管线步骤

### Step 2 — 🏗️ 技术方案（Arch）

**主角：** arch | **备用：** dev

**完成条件：** 技术方案文档推 dev，`!step_complete step2 --output <sha>`

**方向 A1 — 协议层常量（~2 行）：**

`shared/protocol.py` L165 后新增：

```python
# ── R68: Inbox Channel ─────────────────────────────────────────
INBOX_CHANNEL_PREFIX = "_inbox:"
```

**方向 A1 — 持久化工具函数（~15 行）：**

`server/persistence.py` 文件末尾新增：

```python
# ── R68: Inbox channel helpers ─────────────────────────────────
INBOX_CHANNEL_PREFIX = "_inbox:"

def get_inbox_channel(agent_id: str) -> str:
    """Get agent's dedicated inbox channel ID."""
    return f"{INBOX_CHANNEL_PREFIX}{agent_id}"

def is_inbox_channel(channel: str) -> bool:
    """Check if a channel ID is an inbox channel."""
    return channel.startswith(INBOX_CHANNEL_PREFIX)

def resolve_inbox_owner(channel: str) -> str | None:
    """Extract agent_id from inbox channel ID, or None."""
    if channel.startswith(INBOX_CHANNEL_PREFIX):
        return channel[len(INBOX_CHANNEL_PREFIX):]
    return None
```

> ⚠️ **注意：** `INBOX_CHANNEL_PREFIX` 在 `protocol.py` 和 `persistence.py` 中各定义一次（persistence 工具函数独立，不依赖 protocol import）。或者统一导入 `shared.protocol` 常量。**技术方案决定。**

**方向 A2 — 收件箱路由分支（~30 行）：**

`server/handler.py` 的 `handle_broadcast()` L4000-L4020（`_admin` 通道拦截后）与 L4022（channel resolution 前）之间新增：

```python
    # ── R68 A2: Inbox channel intercept ──
    INBOX_PREFIX = "_inbox:"
    if channel.startswith(INBOX_PREFIX):
        owner_id = channel[len(INBOX_PREFIX):]
        if not owner_id:
            await _send(ws, {"type": "error", "error": "❌ 无效的收件箱通道"})
            return

        # 权限：仅 admin 可向收件箱发消息
        if sender_role != "admin":
            await _send(ws, {"type": "error", "error": "❌ 权限不足：仅管理员可向收件箱发消息"})
            return

        # 仅投递给目标 agent（单播）
        targets = [(aid, conns) for aid, conns in _connections.items() if aid == owner_id]
        # 写日志
        write_chat_log(sender_name, content, channel=channel)
        # 构建广播消息
        broadcast = json.dumps({
            "type": "broadcast", "channel": channel,
            "from_name": sender_name, "agent_id": sender_id,
            "from": sender_name, "from_agent": sender_id,
            "content": content, "ts": time.time(),
        })
        sent = 0
        for agent_id, conns in targets:
            for conn in list(conns):
                try:
                    if hasattr(conn, "send_str"):
                        await conn.send_str(broadcast)
                    elif hasattr(conn, "send"):
                        await conn.send(broadcast)
                    sent += 1
                except Exception:
                    pass
        logger.info("Inbox [%s] %s→%s: %s", channel, sender_name, owner_id[:12] if owner_id else "?", content[:60])
        await _send(ws, {"type": "ack", "channel": channel, "sent": sent, "to": owner_id})
        return
```

> 位置已在图中标注。**注意：** `INBOX_PREFIX` 可用 `p.INBOX_CHANNEL_PREFIX` 替换，由技术方案决定是直接引用 `protocol.py` 常量还是本地定义。

**方向 A1 — Agent 注册后创建收件箱（~5 行）：**

`server/auth.py` 审批通过逻辑中，在批准 agent 加入 `_approved_users` 后，新增：

```python
# R68: Register inbox channel for approved agent
persistence.set_agent_channel(agent_id, persistence.get_inbox_channel(agent_id))
```

> 或采用单独注册机制，由技术方案决定。目的：agent 审批通过后，其 `_inbox:<agent_id>` 通道即就绪。

**方向 A3 — `_cmd_step_complete` 收件箱派活（~20 行）：**

`server/handler.py` L2516-L2533 区域改造。当前逻辑：

```python
# 当前 L2516-L2530: 全量广播到工作室
_persist_broadcast(sender_ch, pm_name, mention_msg)
mention_payload = json.dumps({...})
for member_id in ws_obj.members:
    for conn in list(_connections.get(member_id, set())):
        ...全量发送...
```

改造为：
1. 📥 向下一 bot 的收件箱发送**完整任务消息**（含需求/WORK_PLAN/技术方案 URL + 产出要求 + 上下文）
2. 🏠 向工作室发送**轻量通知**（`@bot_name 🔔 Step N 已分配`）
3. 收件箱消息持久化到 `write_chat_log(channel=inbox_ch)`
4. Bot 回复路径：无需改造。bot 收到收件箱消息后，通过现有 `_admin` 通道回复 ACK/产出

> 技术方案需确定 `_cmd_step_handoff()` 的对称改造是否与 `_cmd_step_complete()` 公用同一辅助函数。

---

### Step 3 — 💻 编码（Dev）

**主角：** dev | **备用：** arch

**完成条件：** 4 个文件按技术方案编码完成，git push dev，`!step_complete step3 --output <sha>`

| 文件 | 改动 |
|:-----|:------|
| `shared/protocol.py` | +`INBOX_CHANNEL_PREFIX` 常量 |
| `server/persistence.py` | +3 个收件箱工具函数 |
| `server/handler.py` | +`handle_broadcast` 收件箱路由 + step_complete/handoff 收件箱派活 |
| `server/auth.py` | +agent 注册后收件箱注册 |

---

### Step 4 — 🔍 审查（Review）

**主角：** review | **备用：** qa

**审查重点：**
1. ✅ `_inbox` 路由权限：仅 admin 可写，agent 不可写
2. ✅ 收件箱消息不会广播到工作室（不破坏现有 workspace broadcast）
3. ✅ `handle_broadcast` 新增分支在 `_admin` 拦截后、channel resolution 前，不影响其他通道
4. ✅ step_complete/handoff 改造不破坏现有管线流程
5. ✅ Scope 合规：没有引入不在范围内的改动
6. ✅ `grep` 零内部名残留

---

### Step 5 — 🦐 测试（QA）

**主角：** qa | **备用：** review

**测试项：** 见 §3 验收清单

---

### Step 6 — 🦸 合并部署（Admin）

**主角：** admin | **备用：** arch

**操作：**
- 合并 dev→main
- 部署生产容器
- TODO.md 更新（新增 R68 条目）
- 关闭工作室，恢复大厅

---

## 3. 验收清单（从需求文档复制）

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | `_inbox:<agent_id>` 通道格式定义，前缀常量在 `protocol.py` 中 | ⏳ |
| ✅-2 | Agent 注册后自动创建收件箱 | ⏳ |
| ✅-3 | 收件箱消息仅投递给目标 agent | ⏳ |
| ✅-4 | 权限：仅 admin 可向收件箱发消息 | ⏳ |
| ✅-5 | admin 可向任何 agent 收件箱发消息 | ⏳ |
| ✅-6 | `handle_broadcast` 新增收件箱路由 | ⏳ |
| ✅-7 | 收件箱消息持久化到聊天日志（有时间戳） | ⏳ |
| ✅-8 | Agent 不能向收件箱回复写 | ⏳ |
| ✅-9 | `!step_complete` 后任务消息发到收件箱 | ⏳ |
| ✅-10 | 工作室同时收到轻量进展通知 | ⏳ |
| ✅-11 | Bot 收信后向 `_admin` 回复 ACK（可选, bot 端适配） | ⏳ |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-05 | 初稿 — 基于需求文档 v1.0 ✅ |
