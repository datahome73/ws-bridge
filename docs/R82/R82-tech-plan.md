# R82 技术方案 — Inbox-Only 架构重构 🏗️

> **版本：** v1.0
> **状态：** ✅ 技术方案
> **架构师：** 👷 架构师
> **日期：** 2026-07-10
> **基于需求：** docs/R82/R82-product-requirements.md v1.0 ✅
> **基线：** `7698241`（dev）
> **改动范围：** `server/handler.py` `shared/protocol.py` `server/workspace.py` `server/persistence.py` `server/config.py`

---

## 目录

1. [删除路径 vs 保留路径决策树](#1-删除路径-vs-保留路径决策树)
2. [精确改动点（函数名/行号）](#2-精确改动点函数名行号)
3. [handle_broadcast 简化](#3-handle_broadcast-简化)
4. [inbox:server 查询路由](#4-inboxserver-查询路由)
5. [工作室元数据模型](#5-工作室元数据模型)
6. [1-0 配置与协议常量清理](#6-配置与协议常量清理)
7. [改动汇总](#7-改动汇总)
8. [兼容性分析](#8-兼容性分析)
9. [风险与缓解](#9-风险与缓解)

---

## 1. 删除路径 vs 保留路径决策树

### 1.1 决策树总览

```
[函数/机制] → 保留？删除？简化？
```

```
handle_broadcast
├── inbox 消息 (channel.startswith("_inbox:"))
│   ├── 定向投递给目标 agent          → ✅ 保留（核心功能）
│   └── filter: _is_nonsense/duplicate → ❌ 删除（inbox 直达，不经滤网）
├── lobby 消息 (channel == "lobby")
│   ├── 从 admin/bot → lobby          → ⚠️ 简化（只投给真人 Web 端，不投 bot 连接）
│   └── filter 滤网                    → ⚠️ 简化（减少 → 只保留防刷限流）
├── admin 消息 (channel == "_admin")
│   ├── ! 命令路由                     → ✅ 保留（真人通过 admin 执行管理）
│   └── 进度通知                       → ✅ 保留（给 Web 端看）
├── workspace 消息 (channel startswith "ws:")
│   ├── 工作室消息路由                  → ❌ 删除（bot 不走工作室频道）
│   └── 工作室 ACL 守卫                 → ❌ 删除
└── channel 回退逻辑 (auto-resolve)    → ❌ 删除（bot 不再需要频道推断）

_broadcast_active_channel()
├── _cmd_create_workspace 调用         → ❌ 删除
├── _cmd_rollcall / _cmd_rollcall_role → ❌ 删除
├── _cmd_pipeline_start                → ❌ 删除
├── !activate_pipeline                 → ❌ 删除
├── _cmd_step_handoff                  → ❌ 删除
├── admin rollcall                     → ❌ 删除
└── _cmd_pipeline_shrink               → ❌ 删除

persistence.get/set_agent_channel()
├── register 流程设置 inbox            → ❌ 删除（不再维护活跃频道）
├── handle_agent_card_register 频道切换 → ❌ 删除
├── _cmd_create_workspace 绑定         → ❌ 删除
├── _cmd_step_complete 推断            → ❌ 删除
├── _cmd_workspace_join 切换           → ❌ 删除
└── handle_broadcast 频道回退          → ❌ 删除

protocol.py 频道相关常量
├── MSG_SET_ACTIVE_CHANNEL             → ❌ 删除
├── MSG_CHANNEL_UPDATED               → ❌ 删除
├── FIELD_ACTIVE_CHANNEL               → ❌ 删除
├── LOBBY                              → ⚠️ 保留（admin/Web 端仍需）
├── ADMIN_CHANNEL                      → ⚠️ 保留
└── INBOX_CHANNEL_PREFIX               → ✅ 保留（核心）

workspace.py
├── Workspace dataclass (频道模型)      → ⚠️ 重写为元数据模型
├── create_workspace (创建频道)        → ❌ 删除频道创建逻辑
├── close_workspace (关闭频道)         → ⚠️ 简化为时间戳标记
├── add_member / remove_member         → ⚠️ 保留（元数据记录成员）
└── get_workspace / get_all            → ⚠️ 保留
```

### 1.2 按文件统计

| 文件 | 删除 | 保留 | 简化 |
|:-----|:----|:-----|:-----|
| `server/handler.py` | ~-210 行 | ~+50 行（inbox:server） | ~-90 行 |
| `shared/protocol.py` | ~-10 行 | — | — |
| `server/workspace.py` | ~-50 行 | ~+30 行 | ~+50 行 |
| `server/persistence.py` | ~-15 行 | ~+30 行 | — |
| `server/config.py` | ~-5 行 | — | — |
| **合计** | **~-290 行** | **~+110 行** | **净删 ~-180 行** |

---

## 2. 精确改动点（函数名/行号）

### 2.1 handler.py — 按改动类型分组

#### 🗑️ 整函数删除

| 函数 | 行号 | 长度 | 原因 | 替代 |
|:-----|:----:|:----:|:-----|:-----|
| `_broadcast_active_channel()` | L5456-5510 | ~55 行 | MSG_SET_ACTIVE_CHANNEL 整机制删除 | inbox 直发 Step 任务 |
| `MSG_SET_ACTIVE_CHANNEL` handler | L6526 | ~3 行 | ws_handler 中的处理分支 | 无 |
| `_is_nonsense()` | — | ~20 行 | lobby 滤网，bot 不读 lobby | 无 |
| `_is_duplicate()` | — | ~15 行 | inbox 直达，不需要去重 | 无 |

#### 🗑️ 函数内代码块删除

| 函数 | 行号 | 删除内容 |
|:-----|:----:|:---------|
| `handle_broadcast()` | L4890 | `channel = msg.get(...) or persistence.get_agent_channel(...) or p.LOBBY` → 直接取 `msg.get(p.FIELD_CHANNEL, "")` |
| `handle_broadcast()` | L4893-4894 | 注册频道限制（bot 注册后直接 inbox） |
| `handle_broadcast()` | L4909-4915 | nonsense/duplicate 过滤（inbox 消息跳过） |
| `handle_broadcast()` | L4940-4970 | lobby/workspace 路由中投给 bot 连接的分支 |
| `handle_broadcast()` | L5147-5170 | workspace 消息的 admin/bot 分发逻辑 |
| `_cmd_create_workspace()` | L676-677 | `asyncio.create_task(_broadcast_active_channel(ws_id))` |
| `_cmd_create_workspace()` | L663-665 | `persistence.set_agent_channel(sender_id, ws_id)` 活跃频道绑定 |
| `_cmd_rollcall()` | L1081 | `ack_result = await _broadcast_active_channel(sender_ch)` |
| `_cmd_rollcall_role()` | L1115 | `ack_result = await _broadcast_active_channel(sender_ch)` |
| `_cmd_pipeline_start()` | L2680-2682 | `await _broadcast_active_channel(ws_id)` |
| `!activate_pipeline` handler | L2800-2801 | `switch_count = await _broadcast_active_channel(ws_id)` |
| `_cmd_step_handoff()` | L4112-4113 | `switch_count = await _broadcast_active_channel(ws_id)` |
| `admin rollcall` | L5449-5450 | `ack_result = await _broadcast_active_channel(target_ch)` |
| `handle_register()` | L254-255 | `persistence.set_agent_channel(agent_id, inbox_ch)` |
| `handle_agent_card_register()` | L393 | `persistence.set_agent_channel(agent_id, p.LOBBY)`（R79 追加） |
| `_cmd_workspace_join()` | — | `persistence.set_agent_channel(sender_id, ws_id)`（R81 新增） |
| 各 `sender_ch = persistence.get_agent_channel(...)` | 多处 | 替换为 `p.LOBBY` 常量或 workspace 元数据查询 |

#### ✨ 新增代码

| 函数 | 行数 | 说明 |
|:-----|:----:|:------|
| `_detect_server_query()` | ~15 | 检测 `channel == "_inbox:server"` 的查询命令 |
| `_handle_server_query()` | ~30 | 执行查询命令并回复到发送者 inbox |
| `handle_broadcast` 中 inbox 跳过过滤 | ~5 | 在 inbox 分支开头跳过 nonsense/duplicate |

#### 🔧 简化（保留但精简）

| 函数 | 改动 |
|:-----|:------|
| `handle_broadcast()` lobby 分支 | 删除投递给 bot 连接的代码，只保留投递给 Web viewer + 日志持久化 |
| `handle_broadcast()` workspace 分支 | 删除投递给 bot 连接的代码，只保留 admin/Web viewer |
| `_SILENT_PREFIXES` | 保留（admin 频道仍需要），inbox 路径跳过 |

### 2.2 protocol.py — 删除的常量

| 常量 | 行号 | 原因 |
|:-----|:----:|:------|
| `MSG_SET_ACTIVE_CHANNEL = "set_active_channel"` | L83 | 频道切换机制删除 |
| `MSG_CHANNEL_UPDATED = "channel_updated"` | L84 | 频道切换确认删除 |
| `FIELD_ACTIVE_CHANNEL = "active_channel"` | L150 | 活跃频道字段删除 |

### 2.3 persistence.py — 删除的函数

| 函数 | 行号 | 原因 |
|:-----|:----:|:------|
| `get_agent_channel()` | ~L155 | 活跃频道持久化不需要 |
| `set_agent_channel()` | 相邻行 | 同上 |
| `save_agent_channels()` | 相邻行 | 同上 |
| `_agent_channels` 字典 | 模块级 | 活跃频道全局变量删除 |

### 2.4 config.py — 删除的配置

| 配置 | 原因 |
|:-----|:------|
| `BROADCAST_ADMINS` | 不再需要区分 admin 广播（bot 只看 inbox） |

### 2.5 workspace.py — 改动

**Workspace dataclass 保持结构**（元数据仍然需要 owner_id、members、timestamps），但**删除**：

- `token_ring` 字段（R10 令牌环 — 通道消息流控，bot 不再需要）
- 与频道广播相关的逻辑

**新增**：
- `workflow_url` 字段（WORK_PLAN 链接）
- `pipeline_round` 字段（关联的管线轮次名）
- 时间切片查询 API

---

## 3. handle_broadcast 简化

### 3.1 当前流程（~200 行路由代码）

```
handle_broadcast(ws, sender_id, msg)
  ├── (1) 频道推断: channel = msg.channel or persistence.get_agent_channel() or LOBBY
  ├── (2) R23: 注册频道过滤
  ├── (3) R12: 限流检查
  ├── (4) nonsense/duplicate/SILENT_PREFIXES 过滤
  ├── (5) R57 rollcall ACK hook
  ├── (6) R63 rollcall auto-register
  ├── (7) R63 Phase 4: step ACK 检测
  ├── (8) 📢 admin-only 广播检查
  ├── (9) 解析 @mentions → task 检测
  ├── (10) ! 命令路由
  ├── (11) _admin 频道 intercept
  ├── (12) inbox 频道 intercept → 投递给目标 agent
  ├── (13) 未知频道回退逻辑
  ├── (14) workspace 频道路由 (ACL + 成员分发)
  ├── (15) lobby 频道投递
  ├── (16) 写入 3 个持久化 + 内容审核
  └── (17) 返回 ack
```

### 3.2 改造后流程（~120 行）

```
handle_broadcast(ws, sender_id, msg)
  ├── (1) 获取 channel: msg.get("channel", "")
  │        ← 删除 get_agent_channel 回退（bot 必须显式指定 channel）
  ├── (2) inbox 快速通道 (channel.startswith("_inbox:"))
  │     ├── _inbox:server → _handle_server_query()（查询命令）
  │     ├── 其他 _inbox:xxx → 直投目标 agent
  │     └── 跳过限流、nonsense、duplicate、SILENT_PREFIXES
  │         ← 删除 ~30 行过滤代码
  ├── (3) R12: 限流检查（仅 lobby/admin）
  ├── (4) ! 命令路由（admin 频道保持）
  ├── (5) _admin 频道 intercept（保留，投递 Web viewer）
  ├── (6) lobby 频道（简化 — 只投 Web viewer，不投 bot 连接）
  ├── (7) 写入持久化 + 日志
  └── (8) 返回 ack
```

**关键变化：**

| 变化 | 旧代码 | 新代码 |
|:-----|:-------|:-------|
| 频道推断 | `msg.channel or get_agent_channel() or LOBBY` | `msg.get("channel", "")` — bot 必须显式指定 |
| inbox 过滤 | 经过 nonsense/duplicate 过滤 | **直达**，跳过所有滤网 |
| lobby 投递 | 投给所有 bot + Web viewer | 只投 Web viewer |
| workspace 投递 | 投给 workspace 成员 + admin | 只投 admin/Web viewer |
| rollcall/step ACK | 嵌入广播流程 | 删除（不再需要） |

### 3.3 Inbox 快速通道伪代码

```python
# 在 handle_broadcast 最开头（限流之前）

# R82 A1: Inbox 快速通道 — 跳过所有过滤和路由
channel = msg.get(p.FIELD_CHANNEL, "")
if channel.startswith(p.INBOX_CHANNEL_PREFIX):
    # _inbox:server → 查询命令
    if channel == f"{p.INBOX_CHANNEL_PREFIX}server":
        await _handle_server_query(ws, sender_id, content)
        return
    
    # 目标 inbox → 直投目标 agent
    owner_id = persistence.resolve_inbox_owner(channel)
    if not owner_id:
        await _send(ws, {"type": "error", "error": "❌ 无效的收件箱通道"})
        return
    
    # 投递给目标 agent（单播）
    sent = 0
    for conn in list(_connections.get(owner_id, set())):
        try:
            payload = json.dumps({
                "type": "broadcast", "channel": channel,
                "from_name": sender_name, "agent_id": sender_id,
                "from": sender_name, "from_agent": sender_id,
                "content": content, "ts": time.time(),
            })
            if hasattr(conn, "send_str"):
                await conn.send_str(payload)
            elif hasattr(conn, "send"):
                await conn.send(payload)
            sent += 1
        except Exception:
            pass
    
    # 持久化并返回
    write_chat_log(sender_name, content, channel=channel)
    ms.save_message(...)
    await _send(ws, {"type": "ack", "channel": channel, "sent": sent, "to": owner_id})
    return
```

---

## 4. inbox:server 查询路由

### 4.1 路由规则

**入口：** `handle_broadcast` 中 `channel == "_inbox:server"` 时调用

**报文格式：**

```
Bot → Server:
{
  "type": "message",
  "channel": "_inbox:server",
  "content": "!agent_card list",
  "from_name": "架构师",
  "agent_id": "ws_xxx",
  "id": "...",
  "ts": ...
}

Server → Bot (回复到 Bot 的 inbox):
{
  "type": "broadcast",
  "channel": "_inbox:ws_xxx",
  "from_name": "系统",
  "agent_id": "_system",
  "content": "<查询结果文本>",
  "ts": ...
}
```

### 4.2 实现

```python
async def _handle_server_query(ws, sender_id: str, content: str) -> None:
    """处理发往 _inbox:server 的查询命令。
    
    识别以 ! 开头的命令，执行后回复到发送者的 inbox。
    不广播到 admin/其他 bot。
    """
    if not content.startswith("!"):
        # 非命令消息 → 静默忽略（不做任何处理）
        return
    
    sender_name = auth.get_agent_name(sender_id, sender_id[:12])
    reply_ch = persistence.get_inbox_channel(sender_id)
    if not reply_ch:
        logger.warning("R82: Cannot reply to %s — no inbox channel", sender_id[:12])
        return
    
    # 解析命令
    parts = content.strip().split(maxsplit=1)
    cmd = parts[0].lower() if parts else ""
    params_str = parts[1] if len(parts) > 1 else ""
    
    reply_text = ""
    
    if cmd == "!agent_card":
        sub_parts = params_str.split(maxsplit=1)
        sub_cmd = sub_parts[0] if sub_parts else ""
        if sub_cmd == "list":
            cards = ac_mod.get_all_cards()
            lines = [f"📇 Agent Cards ({len(cards)}):"]
            for aid, card in sorted(cards.items()):
                name = card.get("display_name", aid[:12])
                roles = ", ".join(card.get("pipeline_roles", []))
                status = card.get("status", "offline")
                lines.append(f"  {name} ({aid[:12]}...) [{status}] 角色: {roles}")
            reply_text = "\n".join(lines)
        else:
            reply_text = f"❌ 未知子命令: !agent_card {sub_cmd}"
    
    elif cmd == "!pipeline_status":
        round_name = params_str.strip()
        if round_name:
            mgr = _ensure_pipeline_manager()
            ctx = mgr.get(round_name)
            if ctx:
                reply_text = _format_pipeline_context(ctx)
            else:
                reply_text = f"❌ 管线 {round_name} 不存在"
        else:
            mgr = _ensure_pipeline_manager()
            active = mgr.get_all_active()
            if active:
                lines = ["📋 活跃管线:"]
                for ctx in sorted(active, key=lambda c: c.round_name):
                    lines.append(f"  {ctx.round_name} [{ctx.task_kind.value}] {ctx.status.value} step={ctx.current_step}/{ctx.total_steps}")
                reply_text = "\n".join(lines)
            else:
                reply_text = "📋 当前无活跃管线"
    
    elif cmd == "!list_workspaces":
        ws_list = ws_mod.get_all_workspaces()
        if ws_list:
            lines = [f"📋 工作区 ({len(ws_list)}):"]
            for ws in ws_list:
                state = ws.state.value
                lines.append(f"  {ws.id} '{ws.name}' [{state}] members={len(ws.members)}")
            reply_text = "\n".join(lines)
        else:
            reply_text = "📋 当前无工作区"
    
    elif cmd == "!my_id":
        reply_text = f"🆔 你的 agent_id: {sender_id}"
    
    elif cmd == "!help":
        reply_text = "📖 可用查询: !agent_card list, !pipeline_status [R], !list_workspaces, !my_id"
    
    else:
        reply_text = f"❌ 未知命令: {cmd}\n可用查询: !agent_card list, !pipeline_status [R], !list_workspaces, !my_id"
    
    if not reply_text:
        return
    
    # 回复到发送者的 inbox
    try:
        await _broadcast_to_channel(reply_ch, {
            "type": "broadcast", "channel": reply_ch,
            "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
            "content": reply_text, "ts": time.time(),
        })
        logger.info("R82: Replied to %s via %s for '%s'", sender_id[:12], reply_ch, content[:40])
    except Exception as e:
        logger.warning("R82: Failed to reply to %s: %s", sender_id[:12], e)
```

### 4.3 查询命令清单（v1）

| 命令 | 参数 | 回复内容 |
|:-----|:------|:---------|
| `!agent_card list` | — | 所有 Agent Card（名字 + id + 角色 + 状态） |
| `!pipeline_status` | [R{N}] | 无参数 → 活跃管线列表；有参数 → 指定管线详情 |
| `!list_workspaces` | — | 活跃工作区列表 |
| `!my_id` | — | 自己的 agent_id |
| `!help` | — | 可用命令列表 |

---

## 5. 工作室元数据模型

### 5.1 Workspace dataclass 改造

```python
@dataclass
class Workspace:
    """R82: 工作区不再是频道，而是时间切片索引元数据。"""
    
    id: str                              # "ws_R82_dev"（简短 ID，不含 agent_id 前缀）
    name: str                            # 展示名 "R82-dev"
    pipeline_round: str                  # 关联管线轮次 "R82"
    workflow_url: str                    # WORK_PLAN URL
    
    owner_id: str                        # 创建者 agent_id
    owner_name: str                      # 创建者显示名
    
    state: WorkspaceState = WorkspaceState.ACTIVE
    members: set[str] = field(default_factory=set)
    
    created_at: float = 0.0              # 创建时间戳
    closed_at: float | None = None       # 关闭时间戳（归档标记）
    last_active_at: float = 0.0
    
    # R82 新增：工作流元数据
    roles: list[str] = field(default_factory=list)  # 该管线所需的角色列表
```

### 5.2 create_workspace 简化

```python
async def _cmd_create_workspace(sender_id: str, params: dict) -> str:
    """R82: 创建工作室元数据（不再创建频道）。"""
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法: !create_workspace <name>"
    
    ws_name = positional[0]
    round_name = params.get("round", "")
    ws_id = f"ws_{ws_name[:20]}"  # 简短 ID
    
    users = auth.get_users()
    sender_name = users.get(sender_id, {}).get("name", sender_id[:12])
    
    # 创建元数据（不创建频道、不广播 MSG_SET_ACTIVE_CHANNEL）
    result = ws_mod.create_workspace(
        ws_id, ws_name, sender_id, sender_name,
        pipeline_round=round_name,
    )
    if not result:
        return f"❌ 创建失败：{ws_name} 可能已存在"
    
    return f"✅ 工作区 {ws_name} 已创建（ID: {ws_id}）"
```

### 5.3 close_workspace 简化

```python
async def _cmd_close_workspace(sender_id: str, params: dict) -> str:
    """R82: 关闭工作室 = 标记 closed_at。"""
    ws_id = params.get("_positional", [None])[0] or params.get("workspace")
    if not ws_id:
        return "❌ 用法: !close_workspace <ws_id>"
    
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区 {ws_id} 不存在"
    
    # 简化为时间戳标记（不广播频道关闭通知）
    ws.state = WorkspaceState.ARCHIVED
    ws.closed_at = time.time()
    ws_mod._save()
    
    _audit_logger.log(f"[R82] !close_workspace by {sender_id}: {ws_id}")
    return f"✅ 工作区 {ws.name} 已归档"
```

### 5.4 workspace view — 时间切片查询

```python
async def _cmd_workspace_view(sender_id: str, params: dict) -> str:
    """查看工作室历史消息（从 inbox 消息按时间区间筛选）。"""
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法: !workspace view <ws_id>"
    
    ws_id = positional[0]
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区 {ws_id} 不存在"
    
    # 从 message_store 按时间区间查询所有 inbox 消息
    start = ws.created_at
    end = ws.closed_at or time.time()
    
    try:
        msgs = ms.get_messages_by_time_range(start, end, config.DATA_DIR)
        # 筛选出 inbox 频道消息（_inbox:*）
        inbox_msgs = [m for m in msgs if m.get("channel", "").startswith("_inbox:")]
    except Exception:
        inbox_msgs = []
    
    if not inbox_msgs:
        return f"📋 工作区 {ws.name}: 该时间段内无 inbox 消息"
    
    lines = [f"📋 工作区 {ws.name} ({len(inbox_msgs)} 条 inbox 消息)"]
    for m in inbox_msgs[-20:]:  # 最多显示 20 条
        ts = m.get("ts", 0)
        from_name = m.get("from_name", "?")
        content = (m.get("content", "") or "")[:80]
        lines.append(f"  [{format_timestamp(ts)}] {from_name}: {content}")
    
    return "\n".join(lines)
```

---

## 6. 配置与协议常量清理

### 6.1 protocol.py 删除

```python
# ── R7: Active Channel Messages ── ← 整个区块删除（L82-84）
# MSG_SET_ACTIVE_CHANNEL = "set_active_channel"  ← 删除
# MSG_CHANNEL_UPDATED = "channel_updated"        ← 删除

# FIELD_ACTIVE_CHANNEL = "active_channel"  ← 删除（L150）
```

### 6.2 config.py 删除

```python
# BROADCAST_ADMINS ← 删除（不再需要区分 admin 广播目标）
```

### 6.3 persistence.py 删除

```python
# _agent_channels: dict[str, str] = {}  ← 删除模块级变量
# def get_agent_channel(...)         ← 删除
# def set_agent_channel(...)         ← 删除
# def save_agent_channels(...)       ← 删除
# def load_agent_channels(...)       ← 删除
```

---

## 7. 改动汇总

### 7.1 文件清单

| 文件 | 删除 | 新增/简化 | 净变 |
|:-----|:----:|:----------:|:----:|
| `server/handler.py` | ~-210 行 | ~+80 行 | **~-130 行** |
| `shared/protocol.py` | ~-3 行 | ~0 行 | **~-3 行** |
| `server/workspace.py` | ~-50 行 | ~+80 行 | **~+30 行** |
| `server/persistence.py` | ~-20 行 | ~+20 行 | **~0 行** |
| `server/config.py` | ~-5 行 | ~0 行 | **~-5 行** |
| **合计** | **~-288 行** | **~+180 行** | **净删 ~-108 行** |

### 7.2 无改动项

| 模块 | 原因 |
|:-----|:------|
| `clients/` | 旧 ws_client.py 不需要改（inbox 收发协议不变） |
| `server/web_viewer.py` | Web 端只看 lobby/admin/inbox，不受影响 |
| `server/auth.py` | 认证体系不动 |
| `server/agent_card.py` | 卡片注册不变 |
| `server/gateway-plugin/` | Gateway 不受 server 端路由更改影响 |

---

## 8. 兼容性分析

### 8.1 Bot 连接兼容性

| 场景 | 旧行为 | 新行为 | 是否兼容 |
|:-----|:-------|:-------|:---------|
| Bot 连接后收 lobby 广播 | 收所有 lobby 消息 | 不收到 lobby 消息 | ⚠️ 行为改变（bot 不应依赖 lobby） |
| Bot 连接后收 workspace 消息 | 收工作室消息 | 不收到 workspace 消息 | ⚠️ 行为改变 |
| Bot 收发 inbox 消息 | 正常 | 正常 | ✅ 完全兼容 |
| Bot 回复自动路由到发送者 inbox | 正常 | 正常 | ✅ 完全兼容 |
| Bot 发送 `!` 命令到 admin | 经 admin 路由 | 仍可经 admin 路由（保留） | ✅ 兼容 |
| Bot 发送 `!` 命令到 `_inbox:server` | 无此功能 | 新增查询回复 | ✅ 新增 |
| Bot 发送消息到 lobby/workspace | 广播给所有人 | 只传给 Web viewer | ⚠️ 行为改变 |

**结论：** R82 属于 **clean break**——部署后立即生效。旧 bot 如果依赖 lobby/workspace 消息会察觉到变化，但不影响 inbox 收发。**server 部署即生效，bot 端无需任何更新。**

### 8.2 现有命令兼容性

| 命令 | 旧行为 | 新行为 | 兼容性 |
|:-----|:-------|:-------|:-------|
| `!create_workspace` | 创建频道 + 广播 | 创建元数据 | ⚠️ 无广播（bot 不再依赖） |
| `!close_workspace` | 关闭频道 + 广播 | 标记时间戳 | ✅ 语义等效 |
| `!pipeline_start` | 创建 + 广播 ACK | 创建元数据 + inbox 派活 | ✅ 行为等效（bot 收到 inbox 任务） |
| `!step_complete` | 推进 + 广播 | 推进 + 写 admin 通知 | ✅ 行为等效 |
| `!agent_card list` | 从 admin 执行 | 从 admin 或 `_inbox:server` | ✅ 兼容 + 新增入口 |
| `!workspace_join/leave/add/remove` | 操作频道成员 | 操作元数据成员 | ✅ 语义等效 |

### 8.3 Web 端兼容性

| Web Tab | 数据源 | 影响 |
|:--------|:-------|:------|
| 🌐 大厅 | `GET /api/chat?channel=lobby` | ✅ 不变 |
| 📋 活跃 | workspace channel 消息 | ⚠️ workspace 消息现在只从 inbox 中筛选 |
| 🔧 管理员 | `_admin` 频道 | ✅ 不变 |
| 📬 收件箱 | `GET /api/chat/inbox` | ✅ 不变 |
| 🗂️ 历史查看器 | workspace archive API | ✅ 不变 |

### 8.4 部署顺序

```
1. 修改 protocol.py 常量
2. 修改 persistence.py（删除活跃频道，保留其余）
3. 修改 config.py（清理 BROADCAST_ADMINS）
4. 修改 workspace.py（元数据模型）
5. 修改 handler.py（最核心改动）
   a. 删除 _broadcast_active_channel()
   b. 简化 handle_broadcast（inbox 快速通道 + lobby 简化）
   c. 新增 _handle_server_query()
   d. 删除所有 get/set_agent_channel 调用点
   e. 删除 MSG_SET_ACTIVE_CHANNEL handler
   f. !create/close_workspace 简化
6. git push && build && deploy
7. 验证 inbox 收发正常
```

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:-----|:---------|
| `persistence.get_agent_channel()` 被遗漏的引用点导致 import error | 中 | 高 | grep 全量确认 ~20 处引用全部替换后再删除函数 |
| bot 连接后收不到任何消息（inbox 路由改了） | 低 | 🔴致命 | R82 中 inbox 投递逻辑不变，仅在入口处加了快速通道，原有 inbox handler 保留 |
| 旧 bot 仍在发消息到 lobby/workspace | 高 | 低 | 消息仍被持久化（写日志），只是不广播给其他 bot，真人仍可在 Web 端看到 |
| `_broadcast_active_channel` 删除后 pipeline_start 点名无 ACK | 中 | 中 | 用 inbox 消息替代 ACK — bot 收到 Step 任务 inbox 后等价于「点名」 |
| `!create_workspace` 无频道广播后 bot 无法感知 | 中 | 中 | bot 通过 inbox 接收 Step 任务通知，不依赖 workspace 频道感知 |
| 删除 `BROADCAST_ADMINS` 后 admin 通知逻辑变化 | 低 | 低 | admin 频道通知由 `_broadcast_to_channel(_ADMIN)` 直接控制，不依赖该环境变量 |
| 工作室元数据模型改后旧 JSON 不兼容 | 低 | 中 | `from_dict()` 做兼容处理，缺失字段用默认值 |

---

## 10. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-10 | 初稿 — R82 Inbox-Only 架构重构：净删 ~108 行，简化 handle_broadcast，删除 _broadcast_active_channel + MSG_SET_ACTIVE_CHANNEL + 活跃频道持久化，新增 _inbox:server 查询路由 |
