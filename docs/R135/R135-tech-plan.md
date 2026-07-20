# R135 技术方案 — handle_broadcast 死代码清理 + 频道体系精简

> **版本：** v1.0
> **日期：** 2026-07-20
> **依据：** [R135 产品需求](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R135/R135-product-requirements.md) · [工作计划](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R135/WORK_PLAN.md)
> **目标基准：** `origin/dev` HEAD (`a31f422`)

---

## 目录

1. [方案总览](#1-方案总览)
2. [CLN 清理细则（main.py）](#2-cln-清理细则mainpy)
3. [state.py 变量清理](#3-statepy-变量清理)
4. [跨模块影响分析](#4-跨模块影响分析)
5. [清理后 handle_broadcast 预期代码](#5-清理后-handle_broadcast-预期代码)
6. [验收表](#6-验收表)
7. [不做事项](#7-不做事项)
8. [注意事项与执行顺序](#8-注意事项与执行顺序)

---

## 1. 方案总览

### 1.1 核心目标

将 `handle_broadcast`（当前 L1498-L1925，~420 行）精简为纯 **inbox 投递器**（~110 行），同时清理已废止频道体系在 `state.py`、`__main__.py`、`commands/pipeline.py`、`scenario_matcher.py` 中的残存引用。

### 1.2 执行批次

| 批次 | CLN | 清理内容 | 波及文件 | 估计行 |
|:----:|:---:|:---------|:---------|:------:|
| **Batch 0** | — | 交叉引用预处理（先补齐存活代码所需 import，再删旧版） | `main.py` | 审计 |
| **Batch A** | CLN-1~4 | 独立无依赖：_admin、注册保护、限速、过滤 | `main.py`, `state.py` | ~80 |
| **Batch B** | CLN-5~6 | 权限 & rollcall：需注意交叉引用 | `main.py`, `state.py`, `commands/pipeline.py` | ~100 |
| **Batch C** | CLN-7~10 | 最大批：大厅、注册投递、广播、ACK 统计 | `main.py`, `state.py`, `__main__.py`, `scenario_matcher.py` | ~270 |
| **Batch D** | CLN-12 | message_store.py 精简 | `message_store.py`, `__main__.py` | ~60 |
| **合计** | | | 6 个文件 | **~510** |

### 1.3 CLN-11 状态

workspace.py（`origin/dev`）已是 63 行最小存根 — **CLN-11 无需操作**。  
验证：`git show origin/dev:server/ws_server/workspace.py | wc -l` → 63。

---

## 2. CLN 清理细则（main.py）

> 所有行号引用基于 `git show origin/dev:server/ws_server/main.py`（3,706 行）。

### CLN-1（清理 A）：_admin 频道 intercept

| 项目 | 位置 | 行数 | 说明 |
|:-----|:-----|:----:|:-----|
| `handle_broadcast` 内 | L1596-L1615 | ~20 | 整段删除：`_admin` 频道 intercept + 持久化 + 非 ! 命令提示 |
| `_admin_msg()` | L426-L434 | ~9 | 函数定义整段删除 |
| `_persist_admin_response()` | L437-L449 | ~13 | 函数定义整段删除 |

注意：L1612 中 `if not content.startswith("!"):` 引用 `_persist_admin_response`，删整段即消除。

### CLN-2（清理 B）：未注册 bot 保护

| 项目 | 位置 | 行数 |
|:-----|:-----|:----:|
| `handle_broadcast` 内 | L1528-L1530 | ~3 |

删除后注意 L1526「Fall through to normal inbox handling below」注释调整。

### CLN-3（清理 C）：速率限制

| 项目 | 位置 | 行数 |
|:-----|:-----|:----:|
| `handle_broadcast` 内 | L1532-L1543 | ~12 |
| `_check_rate_limit()` | L1952-L1980 | ~29 |

删除后 L1531 空行收窄。

### CLN-4（清理 D）：全局消息过滤

| 项目 | 位置 | 行数 |
|:-----|:-----|:----:|
| `handle_broadcast` 内 | L1545-L1556 | ~12 |
| `_is_nonsense()` | L1982-L2000 | ~19 |
| `_is_duplicate()` | L2003-L2009 | ~7 |

### CLN-5（清理 E）：用户角色/权限

| 项目 | 位置 | 行数 |
|:-----|:-----|:----:|
| `handle_broadcast` 内 | L1558-L1563 | ~6 |
| `handle_broadcast` 内 | L1583-L1594 | ~12（📢 广播 admin 检查 + @提及解析）|
| `_get_agents_by_role()` | L512-L544 | ~33 |
| `_can_broadcast()` | L2079-L2103 | ~25 |

关键：**L1583-L1594** 的 `📢 broadcast admin-only check` 和 `@mention` 解析也随频道体系废止一并删除。  
注意：`auth.get_users()` 调用同时存在于 L1533 和 L1558，删除 L1558-L1563 后 L1533 是唯一残留——L1533 也随 CLN-3 删除。

### CLN-6（清理 F）：Rollcall + Bot ACK 检测

| 项目 | 位置 | 行数 |
|:-----|:-----|:----:|
| `handle_broadcast` 内 | L1565-L1581 | ~17 |
| `_handle_rollcall_ack()` | L547-L553 | ~7（空函数后接 `_ensure_watchdog`）|
| `_update_step_ack_state()` | L1127-L1157 | ~31 |

注意 L1574 检查 `channel.startswith(p.WORKSPACE_ID_PREFIX) or channel.startswith("ws:")` — 工作区已废止。

### CLN-7（清理 G）：频道解析 fallback / Lobby 暂停 / _can_broadcast / 大厅前缀路由

| 项目 | 位置 | 行数 |
|:-----|:-----|:----:|
| 频道解析 fallback（未知通道→LOBBY） | L1661-L1666 | ~6 |
| `_can_broadcast` 调用 + 权限不足返回 | L1668-L1672 | ~5 |
| Lobby 暂停拦截 + `send_str/send` 双模式 | L1674-L1698 | ~25（含 broadcast JSON 构建）|
| 大厅前缀路由（`_sm.classify_lobby_message`） | L1700-L1768 | ~70 |
| **合计** | | **~106** |

保留部分：L1682-L1698 的 **broadcast JSON 构建** 是 L1700 直接使用的变量——但 L1700+L1682 一起删。  
注意 L1684-L1698 构建 `broadcast` 字典（变量名与 L1778-L1792 冗余）。删前者时保留后者。

### CLN-8（清理 H）：Registration 通道投递

| 项目 | 位置 | 行数 |
|:-----|:-----|:----:|
| `handle_broadcast` 内 | L1770-L1775 | ~6 |

### CLN-9（清理 I）：统一广播 + 离线队列

| 项目 | 位置 | 行数 |
|:-----|:-----|:----:|
| 统一广播构建 + 投递 | L1777-L1811 | ~35 |
| 离线队列处理 | L1828-L1859 | ~32 |
| `_push_offline()` | L386-L399 | ~14 |
| `_flush_offline_push()` | L402-L420 | ~19 |
| **合计** | | **~100** |

保留部分：L1812-L1827（`_delivery_status` 跟踪）— 但这部分也随 CLN-10 删。

### CLN-10（清理 J）：ACK 交付统计

| 项目 | 位置 | 行数 |
|:-----|:-----|:----:|
| ACK delivery stats（lobby 路径） | L1861-L1899 | ~39 |
| 延迟记录 + 日志 | L1901-L1908 | ~8 |
| 📋 roll-call 在线列表 | L1910-L1925 | ~16 |
| `_build_online_list()` | L153-L179 | ~27 |
| `get_delivery_status()` | L132-L133 | ~2 |
| **合计** | | **~92** |

---

## 3. state.py 变量清理

> `git show origin/dev:server/ws_server/state.py` — 当前 130 行。

### 3.1 待删除变量（全部随 CLN 删除）

| 变量名 | 关联 CLN | 当前引用 |
|:-------|:--------:|:---------|
| `_rate_limits` | CLN-3 | `main.py` 仅 |
| `RATE_LIMIT_WINDOW` | CLN-3 | `main.py` 仅 |
| `RATE_LIMIT_SECONDS` | CLN-3 | `main.py` 仅 |
| `_SILENT_PREFIXES` | CLN-4 | `main.py` 仅 |
| `_NONSENSE_PATTERNS` | CLN-4 | `main.py` 仅 |
| `_last_message` | CLN-4 | `main.py` 仅 |
| `_r57_rollcall_events` | CLN-6 | `main.py` 仅 |
| `_channel_ack_state` | CLN-6 | `main.py` 仅 |
| `_step_advance_buffer` | CLN-6 | `main.py` L1127? + `commands/pipeline.py` L104-L107 → **需双删** |
| `_LOBBY_PAUSED` | CLN-7 | `main.py` + `commands/pipeline.py` L1201-L1203 |
| `_LOBBY_PAUSED_ROUND` | CLN-7 | `main.py` + `commands/pipeline.py` L1201-L1203 |
| `_lobby_rate_limits` | CLN-7 | `main.py` 仅 |
| `LOBBY_RATE_WINDOW_P1P2` | CLN-7 | `main.py` 仅 |
| `LOBBY_RATE_WINDOW_P3` | CLN-7 | `main.py` 仅 |
| `LOBBY_RATE_SECONDS` | CLN-7 | `main.py` 仅 |
| `PREFIX_ANNOUNCE` | CLN-7 | `state.py` + `scenario_matcher.py` L741 |
| `PREFIX_CHECKIN` | CLN-7 | `state.py` + `scenario_matcher.py` L743 |
| `PREFIX_HELP` | CLN-7 | `state.py` + `scenario_matcher.py` L746 |
| `_offline_push_queue` | CLN-9 | `main.py` + `__main__.py` L224, L276 |
| `_offline_timers` | CLN-9 | `main.py` + `__main__.py` L224, L286-L288 |
| `_delivery_status` | CLN-10 | `main.py` 仅 |
| `_send_stats` | CLN-10 | `main.py` L39 重复初始化 |
| **合计** | | **24 个变量/常量** |

### 3.2 保留变量（不受影响）

| 变量 | 原因 |
|:-----|:-----|
| `_send_stats` | main.py L39 重复定义，保留 state.py 原始定义 |
| `SYSTEM_AGENT_ID` | 系统消息标识，多处使用 |
| `REGISTRATION_BROADCAST_ENABLED` | 注册广播开关，`main.py` register flow 使用 |
| `SERVER_INBOX_CHANNEL` | `_inbox:server` 核心常量 |
| `_PIPELINE_STATE` / `_PIPELINE_CONFIG` | 管线核心状态 |
| `_pipeline_manager` | PipelineContextManager 实例 |
| `_ROLE_AGENT_MAP` | 管线角色映射 |
| `_step_ack_states` | ACK 状态（依然用于 ## 命令和管线推进）|
| `_GIT_SYNC_TASK` | Git 同步任务 |
| `_TIMEOUT_SCAN_TASK` / `_TIMEOUT_SCAN_STARTED` | 超时扫描 |
| `_watchdog_started` / `_watchdog_task` / `_watchdog_alerts` | 看门狗 |
| `_r72_users` | R72 认证 agent 映射 |
| `_task_ack_timers` | 任务 ACK 定时器 |
| `_cards_loaded_guard` / `_card_watcher` | Agent Card 子系统 |
| `WATCHDOG_SCAN_INTERVAL` / `WATCHDOG_REALERT_INTERVAL` | watchdog 常量 |
| `_STEP_TIMEOUT_DEFAULTS` | 超时默认值 |

---

## 4. 跨模块影响分析

### 4.1 `__main__.py` (`server/ws_server/__main__.py`)

| CLN | 影响位置 | 操作 |
|:---:|:---------|:-----|
| CLN-9 | L224-225: `from .state import _offline_push_queue, _offline_timers` | 删除 import |
| CLN-9 | L276: `_offline_push_queue.setdefault(mid, [])` | 删除 | 
| CLN-9 | L286-288: `_offline_timers[mid]`, `_flush_offline_push(mid)` | 删除 |
| CLN-12 | L17: `search_messages as _search_messages` | 删除 import |
| CLN-12 | L442-L448: `_api_search` handler | 整段删除 |

`__main__.py` 修改范围：**L224-L225 删除**、**L276-L288 约 13 行删除**、**L17 修改**、**L442-L448 删除**。

### 4.2 `commands/pipeline.py` (`server/ws_server/commands/pipeline.py`)

| CLN | 影响位置 | 操作 |
|:---:|:---------|:-----|
| CLN-6 | L104, L107: `_step_advance_buffer.get/set` | 删除（step advance 串行化缓冲已不需要）|
| CLN-7 | L1201-L1203: `state._LOBBY_PAUSED`, `state._LOBBY_PAUSED_ROUND` | 删除（lobby pause set/unset 逻辑已无意义）|

`commands/pipeline.py` 修改范围：**L103-L108** 约 6 行、**L1200-L1203** 约 4 行。

### 4.3 `scenario_matcher.py` (`server/ws_server/scenario_matcher.py`)

| CLN | 影响位置 | 操作 |
|:---:|:---------|:-----|
| CLN-7 | L6: README 注释引 `_classify_lobby_message` | 不影响运行 |
| CLN-7 | L733-L746: `classify_lobby_message` 函数 | 整段删除（含 PREFIX 引用）|

注意：`classify_lobby_message` 在 R126 从 `main.py` 移至 `scenario_matcher.py`。**此函数在清理后仅被 CLN-7 中删除的 L1701 调用。** 确认无其他调用方。

### 4.4 `message_store.py` (`server/ws_server/message_store.py`)

| CLN | 影响 | 行数 | 
|:---:|:-----|:----:|
| CLN-12 | `search_messages()` L126-L156 | ~31 |
| CLN-12 | `get_messages_by_channel_pattern()` L188-L219 | ~32 |
| CLN-12 | `get_messages_by_time_range()` L221-L240 | ~20 |
| CLN-12 | `is_duplicate()` L168-L186 | ~19 |
| | **保留：** `init_db`, `save_message`, `get_messages_since`, `get_messages_by_channel`, `clear_messages_by_channel`, `clean_old_messages` | |

注意：`get_messages_by_channel`（L114-L124）和 `clear_messages_by_channel`（L158-L166）保留。

### 4.5 `pipeline_engine.py` — 无影响

`_persist_broadcast` 作为回调传入（L106），仍保留。`_broadcast_to_channel` 也保留。无影响。

### 4.6 `common/message_store.py` — 无影响

web_ui/viewer.py 引用的是 `server.common.message_store`，完全独立。

---

## 5. 清理后 handle_broadcast 预期代码

```python
async def handle_broadcast(ws, sender_id: str, msg: dict) -> None:
    """Inbox-only message dispatcher.

    - _inbox:server → handled by scenario_matcher, return immediately
    - _inbox:{agent_id} → unicast to inbox owner + ACK
    - All other channels → silently ignored
    """
    # ── A: Lazy-start on first message ──
    _ensure_watchdog()
    await _ensure_engine().restore_pipeline_timers()
    _ensure_engine()._ensure_git_scan()
    _ensure_engine()._ensure_timeout_scanner()
    _ensure_agent_cards_loaded()
    _ensure_card_watcher()

    content = msg.get("content", "")
    channel = msg.get(p.FIELD_CHANNEL, "")

    # ── B: _inbox:server → handled by scenario_matcher ──
    if channel == p.SERVER_INBOX_CHANNEL:
        return

    # ── C: _inbox:{agent_id} → unicast + ACK ──
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
        owner_id = persistence.resolve_inbox_owner(channel)
        if not owner_id:
            await _send(ws, {"type": "error", "error": "❌ 无效的收件箱通道"})
            return
        if sender_id == owner_id:
            await _send(ws, {"type": "error", "error": "❌ 不允许向自己的收件箱发消息"})
            return
        # Unicast to target
        targets = [(aid, conns) for aid, conns in _connections.items() if aid == owner_id]
        if not targets:
            await _send(ws, {"type": "error", "error": "❌ 收件箱主人不在线"})
            return
        # Resolve sender name
        users = auth.get_users()
        sender_name = users.get(sender_id, {}).get("name") or \
                      state._r72_users.get(sender_id, {}).get("name", sender_id)
        # Persist
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent=sender_id, from_name=sender_name,
            content=content, ts=time.time(),
            data_dir=config.DATA_DIR, channel=channel,
        )
        # Build broadcast payload
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
        logger.info("Inbox [%s] %s→%s: %s",
                     channel, sender_name, owner_id[:12], content[:60])
        await _send(ws, {"type": "ack", "channel": channel, "sent": sent, "to": owner_id})
        return

    # ── D: Unknown channel → silently ignore ──
    logger.info("Unknown channel '%s' from %s — silently ignored", channel, sender_id[:12])
```

**预计行数：~80 行**（含空行和注释）。

---

## 6. 验收表

| # | 验收项 | 类型 | 验证方法 |
|:-:|:-------|:----:|:---------|
| CLN-1 | `_admin` 频道 intercept 整段删除，`_admin_msg`/`_persist_admin_response` 无残留 | P0 | `grep -n '_admin_msg\|_persist_admin_response\|ADMIN_CHANNEL' main.py` |
| CLN-2 | 未注册 bot 保护代码删除（L1528-L1530） | P0 | `grep -n 'not auth.is_approved' main.py` |
| CLN-3 | 速率限制代码无残留：`_check_rate_limit` 函数和 state 变量 | P0 | `grep -n '_check_rate_limit\|_rate_limits\|RATE_LIMIT_' main.py state.py` |
| CLN-4 | 全局消息过滤无残留：`_is_nonsense`/`_is_duplicate` 及 state 变量 | P0 | `grep -n '_is_nonsense\|_is_duplicate\|_SILENT_PREFIXES\|_NONSENSE_PATTERNS\|_last_message' main.py state.py` |
| CLN-5 | `_get_agents_by_role`/`_can_broadcast`/角色逻辑无残留 | P0 | `grep -n '_get_agents_by_role\|_can_broadcast\|sender_role\|admin_ids' main.py` |
| CLN-6 | Rollcall/ACK 检测无残留：`_handle_rollcall_ack`/`_update_step_ack_state` 及 state 变量 + pipeline.py 引用 | P0 | `grep -n 'rollcall\|_update_step_ack\|_r57_rollcall\|_channel_ack_state\|_step_advance_buffer' main.py state.py commands/pipeline.py` |
| CLN-7 | 大厅/Lobby 前缀路由 + `classify_lobby_message` 无残留 | P0 | `grep -n 'LOBBY\|classify_lobby\|PREFIX_ANNOUNCE\|PREFIX_CHECKIN\|PREFIX_HELP\|_LOBBY_PAUSED\|_can_broadcast' main.py state.py scenario_matcher.py commands/pipeline.py` |
| CLN-8 | Registration 通道投递无残留 | P0 | `grep -n 'REGISTRATION_CHANNEL' main.py`（仅保留 register flow 中的正常引用）|
| CLN-9 | 统一广播 + 离线队列无残留：`_push_offline`/`_flush_offline_push`/state 变量/`__main__.py` 引用 | P0 | `grep -n '_push_offline\|_flush_offline\|_offline_push_queue\|_offline_timers' main.py state.py __main__.py` |
| CLN-10 | ACK 交付统计无残留：`_build_online_list`/`get_delivery_status`/`_send_stats` 删除确认 | P0 | `grep -n '_build_online_list\|get_delivery_status\|_send_stats' main.py state.py` |
| CLN-12 | `search_messages`/`get_messages_by_channel_pattern`/`get_messages_by_time_range`/`is_duplicate` 删除 | P1 | `grep -n 'def search_messages\|def get_messages_by_channel_pattern\|def get_messages_by_time_range\|def is_duplicate' message_store.py` |
| R135-1 | 清理后 `handle_broadcast` 只剩惰性启动 + inbox 路由 | P0 | 目视检查 |
| R135-2 | `python3 -c "from server.ws_server import main"` 无 ImportError | P0 | 终端执行 |
| R135-3 | `##status##R135` 管线状态查询正常 | P0 | 管线测试 |
| R135-4 | `##start##R135` 管线启动 + 派活正常 | P0 | 管线测试 |
| R135-5 | `_inbox:{agent_id}` 单播投递正常（自刷阻断 + ACK） | P0 | 发送测试消息 |
| R135-6 | `_inbox:server` 规则表路由正常 | P0 | 发送测试消息 |

---

## 7. 不做事项

| 事项 | 原因 | 归属 |
|:-----|:-----|:----:|
| `_broadcast_to_channel()` 删除 | 仍然被 `pipeline.py` (L170) 和 `handle_register` 调用来发送通知 | 保留 |
| `_persist_broadcast()` 删除 | pipeline_engine 作为回调传入 (L106)，watchdog/timout 模块仍使用 | 保留 |
| `_send_to_agent()` 重构 | 纯提取工作 | R136 |
| `##` 命令迁移到 engine | 纯提取工作 | R136 |
| `_connections` 池化 | 纯提取工作 | R136 |
| `send_str`/`send` 二选一模式统一 | 已知重复模式 ~15 处但不在此轮 | R136 |
| workspace.py 清理 | `origin/dev` 已是最小存根（63 行），CLN-11 已完成 | ✅ 已完成 |
| `_api_search` 路由注册补删 | 搜索 API 已不注册路由，但 handler 残留——已含在 CLN-12 | CLN-12 |

---

## 8. 注意事项与执行顺序

### 8.1 执行顺序（按 Batch）

```
Batch A (CLN-1~4) → Batch B (CLN-5~6) → Batch C (CLN-7~10) → Batch D (CLN-12)
```

每完成一个 Batch 立即执行 `python3 -c "from server.ws_server import main"` 验证。

### 8.2 R125 教训：Path import 顺序

删除函数定义前，先检查旧版是否有活跃代码调用该函数但缺少 import。  
**执行顺序：先补齐存活代码所需 import → 再删旧版函数。**

本次不涉及函数移动，但注意：

- `_broadcast_to_channel` (L102) 和 `_persist_broadcast` (L451) 保留。确认其 import 路径无缺失。
- `_send_to_agent` (L2114) 保留。它是 inbox 单播路径的底层函数。

### 8.3 双模块变量清理提醒

以下变量同时存在于 `state.py` 和 `__main__.py`/`commands/pipeline.py`/`scenario_matcher.py`：

- `_step_advance_buffer` → `state.py` + `commands/pipeline.py`
- `_LOBBY_PAUSED` / `_LOBBY_PAUSED_ROUND` → `state.py` + `commands/pipeline.py`
- `PREFIX_ANNOUNCE` / `PREFIX_CHECKIN` / `PREFIX_HELP` → `state.py` + `scenario_matcher.py`
- `_offline_push_queue` / `_offline_timers` / `_flush_offline_push` → `state.py` + `__main__.py`

**必须四个文件全部清理，否则 NameError。**

### 8.4 残留 import 检查清单

删除后全局搜索（`search_files` 跨文件）：

```bash
# state.py 变量
for v in _rate_limits RATE_LIMIT_WINDOW RATE_LIMIT_SECONDS _SILENT_PREFIXES _NONSENSE_PATTERNS _last_message _r57_rollcall_events _channel_ack_state _step_advance_buffer _LOBBY_PAUSED _LOBBY_PAUSED_ROUND _lobby_rate_limits LOBBY_RATE_WINDOW_P1P2 LOBBY_RATE_WINDOW_P3 LOBBY_RATE_SECONDS PREFIX_ANNOUNCE PREFIX_CHECKIN PREFIX_HELP _offline_push_queue _offline_timers _delivery_status _send_stats; do
  echo "=== $v ==="; grep -rl "$v" server/ws_server/ --include="*.py" 2>/dev/null || echo "✅ CLEAN"
done

# main.py 函数
for f in _admin_msg _persist_admin_response _check_rate_limit _check_lobby_rate_limit _is_nonsense _is_duplicate _can_broadcast _get_agents_by_role _handle_rollcall_ack _update_step_ack_state _build_online_list get_delivery_status _push_offline _flush_offline_push; do
  echo "=== $f ==="; grep -rl "$f" server/ws_server/ --include="*.py" 2>/dev/null || echo "✅ CLEAN"
done
```

### 8.5 清理后 `main.py` 删除的 import

当前 `main.py` 无 `from .command_utils import ...`（command_utils.py 已被 R134 删除）。  
`from . import message_store as ms` 保留（inbox 单播仍需 `ms.save_message`）。  
`from . import scenario_matcher as _sm` 仍被 `handle_hash_*` / 规则注册引用 — 保留。  
`from . import workspace as ws_mod` 保留（pipeline 其他函数仍需 `get_workspace`）。

无需删除的 import：任何清理都不应删除 `re`, `json`, `asyncio`, `uuid`, `time` 等标准库 import（hande_broadcast 之外的其他函数仍在使用）。
