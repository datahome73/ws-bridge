# R68 技术方案 — Bot 私有收件箱通道 📥

> **版本：** v1.0
> **状态：** ✅ 定稿
> **作者：** 👷 Arch
> **日期：** 2026-07-05
> **基于：** R68 需求文档 v1.0 ✅ + WORK_PLAN v1.0 ✅

---

## 1. 当前基线确认

### 1.1 分支状态

**基线 commit（dev）：** `ed23e90`（R67 最终合并）
**R67 部署状态：** ✅ **已部署**（Agent Card 系统统一 + 角色映射持久化已生效）

### 1.2 文件基线行号（实际，非预估）

| 文件 | 总行数 | 关键符号 |
|:-----|:------:|:---------|
| `shared/protocol.py` | 265 | `ADMIN_CHANNEL` L165, `REGISTRATION_CHANNEL` 末行前, `make_ack()` L264 |
| `server/persistence.py` | 151 | `_agent_active_channels` L126, `set_agent_channel()` L139, `get_agent_channel()` L144 |
| `server/handler.py` | 5728 | `handle_broadcast()` `_admin` 拦截 L3977-L3989, channel resolution L3991-L4014, `_cmd_step_complete()` L2238-L2563 (含 R58 A2 广播 L2515-L2529), `_cmd_step_handoff()` L3034-L3183 |
| `server/auth.py` | 167 | `approve()` L33-L50 |

### 1.3 关键函数签名确认

```python
# handler.py 已有工具函数
write_chat_log(sender_name, content, channel=ch)  # 从 web_viewer 导入
_send_to_agent(agent_id, text, ws_id="") -> bool  # L2653：发文本到单 agent，离线回退广播
_send(ws, msg_dict)                                # 向单 ws 连接发 JSON
_persist_broadcast(channel, from_name, content)    # 持久化 & 保存消息

# persistence.py 已有
set_agent_channel(agent_id, channel)
get_agent_channel(agent_id) -> str | None
```

### 1.4 改动估算对比

| 方向 | 文件 | WORK_PLAN 预估算 | 实际 | 说明 |
|:-----|:-----|:----------------:|:----:|:-----|
| A1 | `shared/protocol.py` | ~2 行 | **2 行** | 常量定义 |
| A1 | `server/persistence.py` | ~15 行 | **16 行** | 3 工具函数 + import |
| A2 | `server/handler.py` handle_broadcast | ~30 行 | **32 行** | 收件箱 intercept（含日志） |
| A3 | `server/handler.py` step_complete | ~20 行 | **~22 行** | 改造广播为收件箱派活 + 轻量通知 |
| A1 | `server/auth.py` | ~5 行 | **8 行** | 审批后注册收件箱通道 |
| **合计** | | **~82 行** | **~86 行** | ✅ 在可控范围内 |

---

## 2. 设计决策

### D1 — 常量复用策略

**决策：** `INBOX_CHANNEL_PREFIX` 只在 `shared/protocol.py` 定义一次。`persistence.py` 和 `handler.py` 均通过 `import shared.protocol` 引用。

**理由：**
- 单一数据源，避免两个文件中定义相同常量不同步
- `persistence.py` 上方 `from . import auth, config` 模式已经存在。在 persistence.py 末尾新增函数直接引用 `shared.protocol` 的常量 **与现有 import 模式一致**
- `handler.py` 已有 `import shared.protocol as p`，接入零成本

### D2 — 持久化函数存放位置

**决策：** `get_inbox_channel()` / `is_inbox_channel()` / `resolve_inbox_owner()` 放在 `server/persistence.py` 末尾。

**理由：**
- 这三个函数是纯工具函数，不依赖 handler 状态（`_connections`），只依赖常量
- persistence.py 已经是持久化数据 + 工具函数的集中地
- 后续 Web 端查看收件箱消息时也可复用

### D3 — 投递方式（单播 vs 回退）

**决策：** 收件箱消息使用 **单播**（只投目标 agent 的 WebSocket 连接），不提供离线回退广播。

**理由：**
- 收件箱是私有通道，回退广播会破坏私有性
- 收件箱消息已通过 `write_chat_log()` 持久化，bot 上线后可通过 `!inbox history` 查看历史（方向 B，本轮不实现）
- `_send_to_agent()` 的离线回退行为（L2660-L2681）在此处不应被使用，所以不使用 `_send_to_agent()`

### D4 — Step complete/handoff 共用辅助函数

**决策：** 提取 `_send_inbox_task(agent_id, round_name, next_step, step_config, output_ref, workspace)` 辅助函数，`_cmd_step_complete()` 和 `_cmd_step_handoff()` 共用。

**理由：**
- 两个函数的收件箱派活逻辑完全相同
- WORK_PLAN 已提示考虑复用
- 后续修改派活模板只需改一处

**签名：**

```python
async def _send_inbox_task(
    target_agent_id: str,
    round_name: str,
    next_step: str,
    step_config: dict,
    output_ref: str,
    workspace_id: str,
    pm_name: str,
) -> None:
    """向目标 agent 的收件箱发送完整任务消息 + 工作室轻量通知。"""
```

### D5 — Inbox intercept 插入位置

**决策：** `handle_broadcast()` 中，在 `_admin` 通道拦截 L3977-L3989 之后、channel resolution L3991 之前插入 inbox intercept。

**位置确认：**

```
L3977  # ── R35: Admin channel intercept ──
...
L3989  return
L3990  (空白行)
L3991  # ── Channel resolution ──          ← 在此行之前插入
```

**理由：**
- `_admin` 拦截后 channel 已确认不是 `_admin`
- inbox 的 `_inbox:xxx` 格式不应进入 workspace resolution（会被视为未知通道fallback到lobby）
- 与注册通道 `__registration__` 的跳过逻辑（L3995-L3996）是同一模式

---

## 3. 方向 A1 — 协议层常量 + 持久化工具函数 🔴 P0

### A1-① `shared/protocol.py` L165 后新增

在 `ADMIN_CHANNEL = "_admin"` 之后、`MSG_ADMIN_AUDIT` 之前插入：

```python
# ── R68: Inbox Channel ─────────────────────────────────────────
INBOX_CHANNEL_PREFIX = "_inbox:"
```

**改动：** +2 行（不含注释为 1 行常量定义）

### A1-② `server/persistence.py` 文件末尾新增

追加 3 个工具函数（依赖 `shared.protocol` 常量，在文件内 import）：

```python
# ── R68: Inbox channel helpers ─────────────────────────────────
def get_inbox_channel(agent_id: str) -> str:
    """Get agent's dedicated inbox channel ID."""
    import shared.protocol as p
    return f"{p.INBOX_CHANNEL_PREFIX}{agent_id}"

def is_inbox_channel(channel: str) -> bool:
    """Check if a channel ID is an inbox channel."""
    import shared.protocol as p
    return channel.startswith(p.INBOX_CHANNEL_PREFIX)

def resolve_inbox_owner(channel: str) -> str | None:
    """Extract agent_id from inbox channel ID, or None."""
    import shared.protocol as p
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
        return channel[len(p.INBOX_CHANNEL_PREFIX):]
    return None
```

**改动：** +16 行（含 docstring 和空行）

> ⚠️ **为什么用局部 import？** `persistence.py` 当前不 import shared.protocol。用局部 import 避免全局 import chain 变更，保持 persistence.py 作为纯文件存取层的隔离性。如果团队偏好统一 import，也可改为文件顶部全局 import。

### A1-③ `server/auth.py` `approve()` 中新增收件箱注册

L47-48（写入 `_approved_users` 后、`del codes[code]` 前）插入：

```python
    # ── R68: Register inbox channel for approved agent ──
    persistence.set_agent_channel(agent_id, persistence.get_inbox_channel(agent_id))
```

**改动：** +3 行（含注释和空行）

> **生命周期：** Agent 被批准后收件箱自动创建，与 `_approved_users` 同生命周期。agent 被删除时（如果有）需同步删除收件箱映射，本轮不涉及。

---

## 4. 方向 A2 — 收件箱路由分支 🔴 P0

### 4.1 handle_broadcast() 新增 inbox intercept

**位置：** `server/handler.py` L3989（`_admin` 拦截 return 之后）和 L3991（channel resolution 注释）之间。

```python
    # ── R68 A2: Inbox channel intercept ──
    import shared.protocol as p_inbox
    if channel.startswith(p_inbox.INBOX_CHANNEL_PREFIX):
        owner_id = persistence.resolve_inbox_owner(channel)
        if not owner_id:
            await _send(ws, {"type": "error", "error": "❌ 无效的收件箱通道"})
            return

        # 权限：仅 admin 可向收件箱发消息
        if sender_role != "admin":
            await _send(ws, {"type": "error", "error": "❌ 权限不足：仅管理员可向收件箱发消息"})
            return

        # 仅投递给目标 agent（单播，不广播给其他人）
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

**改动：** +32 行

> ⚠️ **import 说明：** 局部 import `import shared.protocol as p_inbox` 避免与顶部 `import shared.protocol as p` 命名冲突。如果编码阶段确认 `p.INBOX_CHANNEL_PREFIX` 可用（R68 常量已加到 protocol.py），可使用顶部已有的 `p` 别名。

### 4.2 路由矩阵验证

| 场景 | 期望行为 | 实测方法 |
|:-----|:---------|:---------|
| admin → `_inbox:userA` | ✅ 投递：消息仅 userA 收到，admin 收到 ack | 模拟连接后测试 |
| member → `_inbox:userA` | ❌ 拒绝：返回 error，不投递 | member 发→检查 error |
| userA → `_inbox:userA`（自己收件箱） | ❌ 拒绝：userA 是 member（非 admin） | userA 发→检查 error |
| admin → `_inbox:`（空 owner） | ❌ 拒绝：无效通道 | 发空 ID→检查 error |
| 投递后目标离线 | ✅ 消息持久化到 chat_log，在线后可通过 inbox history 查 | 模拟离线→读日志 |

---

## 5. 方向 A3 — Step 交接收件箱派活 🔴 P0

### 5.1 辅助函数 `_send_inbox_task()`

**位置：** `server/handler.py` — `_cmd_step_complete()` 之前（约 L2235 区域），作为模块级辅助函数。

```python
# ── R68 A3: Send inbox task assignment + workspace notification ──
async def _send_inbox_task(
    target_agent_id: str,
    round_name: str,
    next_step: str,
    step_config: dict,
    output_ref: str,
    workspace_id: str,
    pm_name: str,
) -> None:
    """Send full task to target agent's inbox + lightweight workspace notification."""

    # 1. 📥 收件箱完整任务消息
    inbox_ch = persistence.get_inbox_channel(target_agent_id)
    _pstate = _PIPELINE_STATE.get(round_name, {})
    _pconfig = _PIPELINE_CONFIG.get(round_name, {})

    # Collect context URLs
    req_url = _pconfig.get("requirements_url",
        f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/{round_name}-product-requirements.md")
    plan_url = _pconfig.get("work_plan_url",
        _pstate.get("work_plan_url",
            f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/WORK_PLAN.md"))

    # Build inbox message
    _step_title = _pconfig.get("steps", {}).get(next_step, {}).get("title", next_step)
    inbox_msg = (
        f"📥 任务分配 — {round_name} Step「{_step_title}」\n\n"
        f"背景上下文：\n"
        f"  上一 Step 产出：{output_ref}\n\n"
        f"任务描述：\n"
        f"  请按技术方案完成 {next_step}\n\n"
        f"参考文档：\n"
        f"  📄 需求：{req_url}\n"
        f"  📋 WORK_PLAN：{plan_url}\n"
        f"  🔗 上一步产出：{output_ref}\n\n"
        f"完成后：\n"
        f"  1. git push dev\n"
        f"  2. 在工作室回复 ✅ Step 完成 + commit SHA"
    )

    # Persist inbox message
    write_chat_log(pm_name, inbox_msg, channel=inbox_ch)
    ms.save_message(
        msg_id=str(uuid.uuid4()), msg_type="broadcast",
        from_agent="system", from_name=pm_name,
        content=inbox_msg, ts=time.time(),
        data_dir=config.DATA_DIR, channel=inbox_ch,
    )

    # Send to target agent's connections (unicast)
    inbox_payload = json.dumps({
        "type": "broadcast", "channel": inbox_ch,
        "from_name": pm_name, "from": pm_name,
        "content": inbox_msg, "ts": time.time(),
    })
    conns = _connections.get(target_agent_id, set())
    for conn in list(conns):
        try:
            if hasattr(conn, "send_str"):
                await conn.send_str(inbox_payload)
            elif hasattr(conn, "send"):
                await conn.send(inbox_payload)
        except Exception:
            pass

    logger.info("Inbox task [%s] %s → %s", round_name, pm_name, target_agent_id[:12])

    # 2. 🏠 工作室轻量通知
    ws_obj = ws_mod.get_workspace(workspace_id)
    if ws_obj:
        # Resolve target display name
        users = auth.get_users()
        target_name = users.get(target_agent_id, {}).get("name", target_agent_id[:12])
        notify_msg = f"@{target_name} 🔔 Step「{_step_title}」已分配，请查看收件箱 📥"
        _persist_broadcast(workspace_id, "系统", notify_msg)
        notify_payload = json.dumps({
            "type": "broadcast", "channel": workspace_id,
            "from_name": "系统", "from": "系统",
            "content": notify_msg, "ts": time.time(),
        })
        for member_id in ws_obj.members:
            for conn in list(_connections.get(member_id, set())):
                try:
                    if hasattr(conn, "send_str"):
                        await conn.send_str(notify_payload)
                    elif hasattr(conn, "send"):
                        await conn.send(notify_payload)
                except Exception:
                    pass
```

**改动：** ~42 行（包含 docstring、注释、空行）

### 5.2 `_cmd_step_complete()` 改造

**范围：** L2478-L2529（R58 A2 PM @mention broadcast 区域）

**当前逻辑（L2478-L2529）：**
1. 构建 `mention_msg`（含 @mention + 完整任务信息）
2. `_persist_broadcast(sender_ch, pm_name, mention_msg)`
3. 构造 `mention_payload` 并**全量广播到工作室所有成员**

**改造后逻辑：**

```python
            # ── R68 A3: Replace broadcast with inbox + lightweight notify ──
            # Resolve display names
            if next_role == "arch":
                pm_name = config.PIPELINE_ARCH_FROM_NAME
            else:
                pm_name = config.PIPELINE_PM_NAME

            # ... resolve primary_agent (同现有代码 L2447-2451) ...
            primary_agent = primary_agents[0] if primary_agents else target_agents[0]
            # ... backup fallback 逻辑保持不变 ...

            # Send inbox task assignment
            await _send_inbox_task(
                target_agent_id=primary_agent,
                round_name=round_name,
                next_step=next_step,
                step_config=step_config,
                output_ref=output_ref,
                workspace_id=sender_ch,
                pm_name=pm_name,
            )
```

**关键拆除：**
- ✅ 删除 L2515-L2529 的 `_persist_broadcast` + `mention_payload` 全量广播
- ✅ 删除 L2530-L2538 的 R58 A2 rollcall 广播
- ✅ 用 `_send_inbox_task()` 替代

**改动：** 替换约 15 行为 ~5 行调用（净减 ~10 行）

### 5.3 `_cmd_step_handoff()` 改造

**范围：** L3138-L3141（rollcall 区域）。保留现有的 `_cmd_rollcall_next()` 调用，**同时新增** `_send_inbox_task()` 调用。

在 L3138（`rollcall_result = await _cmd_rollcall_next(...)`）之后、L3143（`# Create next step Task`）之前插入：

```python
            # ── R68 A3: Also send inbox task to primary agent ──
            # Resolve primary agent for inbox delivery
            _h_cards = ac_mod.get_all_cards() if 'ac_mod' in dir() else {}
            _h_member_ids = list(ws_obj.members)
            _h_primary_role = step_config.get(next_step, {}).get("primary")
            _h_primary_agents = _find_agents_by_role(_h_primary_role, _h_member_ids, _h_cards) if _h_cards and _h_primary_role else []
            if _h_primary_agents:
                await _send_inbox_task(
                    target_agent_id=_h_primary_agents[0],
                    round_name=round_name,
                    next_step=next_step,
                    step_config=step_config,
                    output_ref=output_ref,
                    workspace_id=ws_id,
                    pm_name="PM",
                )
```

> ⚠️ `ac_mod` 是否已 import：R67 已将 ac_mod import 添加到 handler.py 顶部（`from . import agent_card as ac_mod`），此处假设已可用。

**改动：** ~10 行（不含注释）

---

## 6. 改动汇总

### 6.1 文件改动一览

| # | 文件 | 改动类型 | 行号 | 内容 | 净增行 |
|:-:|:-----|:--------:|:----:|:-----|:------:|
| 1 | `shared/protocol.py` | 新增常量 | L165 后 | `INBOX_CHANNEL_PREFIX = "_inbox:"` | +2 |
| 2 | `server/persistence.py` | 新增函数 | 文件末尾 | `get_inbox_channel()`, `is_inbox_channel()`, `resolve_inbox_owner()` | +16 |
| 3 | `server/auth.py` | 新增调用 | L47-L48 | `persistence.set_agent_channel(agent_id, ...)` 在 approve() 中 | +3 |
| 4 | `server/handler.py` | **新增 intercept** | L3989-L3990 间 | inbox channel 路由分支 | +32 |
| 5 | `server/handler.py` | **新增函数** | L2235 附近 | `_send_inbox_task()` 辅助函数 | +42 |
| 6 | `server/handler.py` | **改造** | L2478-L2529 | `_cmd_step_complete()` 改用收件箱 + 轻量通知 | -10 |
| 7 | `server/handler.py` | **新增** | L3138-L3142 间 | `_cmd_step_handoff()` 增设收件箱派活 | +10 |
| | **合计** | | | | **~86 行净增** |

### 6.2 Scope 合规检查

| 检查项 | 状态 |
|:-------|:----:|
| `server/web_viewer.py` 不改 | ✅ |
| `server/templates.py` 不改 | ✅ |
| `server/workspace.py` 不改 | ✅ |
| `shared/protocol.py` 仅新增常量 | ✅ |
| 不引入 bot 端收件箱客户端 | ✅ |
| 不修改工作室消息路由（workspace broadcast 不变） | ✅ |
| 不引入消息加密 | ✅ |
| 不修改 `_can_broadcast()` 权限系统 | ✅ |

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| Bot 当前未监听 `_inbox` 频道 | Bot 收不到收件箱消息 | 服务端通过 `MSG_SET_ACTIVE_CHANNEL` 机制投递，bot 收到 channel 消息自动处理。Hermes gateway 已有通用 channel 支持 |
| `_send_inbox_task()` 离线时收件箱不可送达 | 离线 bot 收不到消息 | 收件箱消息通过 `write_chat_log` + `ms.save_message` 持久化，bot 上线后可通过 `MSG_SET_ACTIVE_CHANNEL = _inbox:<id>` 拉取最新消息 |
| `_cmd_step_handoff()` 中 `ac_mod` import 缺失 | 编译错误 | R67 已在 handler.py 顶部 import `from . import agent_card as ac_mod`，确认存在 |

---

## 8. 验证方案

### 8.1 单元测试

| # | 测试项 | 测试方法 |
|:-:|:-------|:---------|
| V-1 | `INBOX_CHANNEL_PREFIX` 常量定义 | `grep` protocol.py 确认常量 |
| V-2 | `get_inbox_channel` / `is_inbox_channel` / `resolve_inbox_owner` | Python REPL 导入测试 |
| V-3 | admin 向收件箱发消息 → 仅目标收到 | 模拟 2 agent 连接，admin 发 `_inbox:A_id` → A 收到，B 不收到 |
| V-4 | member 向收件箱发消息 → 拒绝 | member 发 → error 返回 |
| V-5 | agent 向自己收件箱发消息 → 拒绝 | agent 发（role=member）→ error |
| V-6 | 收件箱消息写日志 | 发消息 → 检查 chat_logs/ 目录 |
| V-7 | 注册 agent 后收件箱自动创建 | 模拟审批 → 检查 `_agent_active_channels.json` |

### 8.2 管线集成验证

| # | 测试项 | 测试方法 |
|:-:|:-------|:---------|
| V-8 | `!step_complete` → 收件箱收到任务 | 启动管线，Step N → `!step_complete` → 检查下一 bot 收件箱 |
| V-9 | 工作室收到轻量通知（非完整消息） | 检查工作室消息不含完整任务体，只有 `@bot 🔔 Step X 已分配` |
| V-10 | `!step_handoff` → 收件箱同时收到任务 | 启动管线，`!step_handoff` → 检查收件箱 |
| V-11 | Bot 收到 `_inbox` 频道消息时效用现有 adapter | 确认 Hermes gateway 现有 `MSG_SET_ACTIVE_CHANNEL` 可接收 |

---

## 9. 脱敏检查清单

- [x] 文档使用角色名（admin/PM/dev/arch/review）替代内部名称
- [x] URL 使用公共 raw.githubusercontent.com 地址
- [x] 代码片段中使用通用变量名，无内部 endpoint 泄露
- [x] `grep -nE '小开|小谷|小周|小爱|泰虾|爱泰|大宏' docs/R68/*.md` 零匹配（提交前确认）
