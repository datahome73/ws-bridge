# R49 技术方案 — 管线路由重构 + 角色持久化 + 超时告警闭环

> **版本：** v1.0
> **状态：** 📝 初稿
> **编制人：** 🏗️ 架构师（小开）
> **日期：** 2026-06-28
> **基于需求：** [R49-product-requirements.md v0.2 ✅](./R49-product-requirements.md)
> **基于计划：** [WORK_PLAN.md v0.1](./WORK_PLAN.md)
> **改动范围：** 仅 `server/handler.py` + `server/config.py` + `data/` 持久化层（零改动 web_viewer / auth / templates）

---

## 目录

1. [方向 A — `!` 命令全频道路由](#方向-a---命令全频道路由)
2. [方向 B — Agent Card 角色持久化](#方向-b---agent-card-角色持久化)
3. [方向 C — 超时告警闭环 + 重启恢复](#方向-c---超时告警闭环--重启恢复)
4. [改动清单](#改动清单)
5. [向后兼容性分析](#向后兼容性分析)
6. [风险与注意事项](#风险与注意事项)

---

## 方向 A — `!` 命令全频道路由

### A.1 当前问题

`handle_broadcast()` 中 `!` 命令解析锁定在 `_admin` 频道独占分支：

```
handler.py:1610  # ── R35: _admin channel intercept ──
handler.py:1611  if channel == p.ADMIN_CHANNEL:
                     ...
handler.py:1629      cmd_name, params = _parse_command(content)
handler.py:1650  # ── Channel resolution (lobby/channel/workspace) ──
```

工作频道（workspace）中发的 `!step_complete`、`!pipeline_status` 等被当作普通广播消息，经 1650 行后的广播逻辑直接路由给成员，服务端不解析、不执行 — 管线状态机永远无法在工作室环境中自动推进。

### A.2 设计方案

将 `!` 前缀检测从 `_admin` 分支提到 `handle_broadcast` 函数入口级通用路由。改动位于 handler.py 约 1610 行前，加通用检测分支：

```
handle_broadcast() 入口
  ├─ rate limiting / nonsense filter / silent filter (不变)
  ├─ 📢 admin-only check (不变)
  ├─ mention parse (不变)
  │
  ├── [NEW] 全频道 ! 路由 (handler.py ≈行 1609a)
  │     if content.startswith("!"):
  │       cmd_name, params = _parse_command(content)
  │       if cmd_name and cmd_name in _ADMIN_COMMANDS:
  │         allowed, reason = _check_command_permission(...)
  │         if allowed:
  │           result = await cmd["handler"](sender_id, params)
  │           # 结果发回来源频道（工作室发回工作室，_admin 发回 _admin）
  │           await _send_to_source_channel(ws, sender_id, channel, result)
  │         else:
  │           await _send_to_source_channel(ws, sender_id, channel, f"❌ {reason}")
  │       else:
  │         await _send_to_source_channel(ws, sender_id, channel, f"❌ 未知命令")
  │       return  # ! 命令处理完毕，不再走后续广播
  │
  ├── [EXISTING] _admin channel intercept (handler.py:1610)
  │   → 保留完整原逻辑，仅移除 ! 解析部分（因已被通用分支提前处理）
  │   → _admin 频道非 ! 消息仍按原逻辑拦截并提示
  │
  └── Channel resolution → workspace/lobby/registration (不变)
```

**关键设计：**

1. **通用路由在 `_admin` 分支之前** — `!` 开头的消息在到达 `_admin` 分支前就被通用路由截获并返回
2. **`_admin` 频道向后兼容** — `_admin` 频道的 `!` 命令同样走通用路由（因为通配 `content.startswith("!")`），但执行结果发回 `_admin` 频道
3. **`_admin` 频道非 `!` 消息** — 仍被 `_admin` 分支拦截并提示「ℹ️ 管理频道仅支持 ! 命令」（不变）
4. **结果写回来源频道** — 工作室中执行 `!step_complete` 后，结果发回工作室（通过 `ws_mod.broadcast_to_workspace()` 或等效机制），不污染 `_admin`

### A.3 结果回发机制

```python
async def _send_to_source_channel(ws, sender_id: str, channel: str, text: str) -> None:
    """Send command result back to the source channel."""
    if channel == p.ADMIN_CHANNEL:
        # Use existing _persist_admin_response (unchanged)
        await _persist_admin_response(ws, sender_id, "系统", text)
    elif channel.startswith("ws:"):
        # Workspace channel → broadcast to members
        ws_obj = ws_mod.get_workspace(channel)
        if ws_obj:
            payload = json.dumps({
                "type": "broadcast",
                "channel": channel,
                "from_name": "系统",
                "from": "系统",
                "content": text,
                "ts": time.time(),
            })
            for agent_id in ws_obj.members:
                for conn in list(_connections.get(agent_id, set())):
                    try:
                        await conn.send_str(payload) if hasattr(conn, "send_str") else await conn.send(payload)
                    except Exception:
                        pass
            # Also persist for web viewer
            write_chat_log("系统", text, channel=channel)
    else:
        # Lobby or other — send back to sender only
        await _send(ws, {"type": "broadcast", "channel": channel, "from_name": "系统", "content": text, "ts": time.time()})
```

### A.4 涉及代码行

| 位置 | 操作 | 说明 |
|:----|:----|:------|
| `handler.py` ≈行 1609 | **新增** 全频道 `!` 路由分支 | 约 25 行 |
| `handler.py` ≈行 1611 | **调整** `_admin` 分支 | 移除分支内 `!` 解析逻辑（约-10 行），保留非 `!` 消息拦截 |
| `handler.py` ≈行 1693 | **新增** `_send_to_source_channel` | 约 20 行 |
| **合计** | | **净 +35 行**（新增 45 - 删除 10） |

### A.5 验收覆盖

A-1 ~ A-8（全 8 项）

---

## 方向 B — Agent Card 角色持久化

### B.1 当前问题

`_cmd_step_complete` 点名下一角色时：

```python
# handler.py:1296-1300
next_role_names = [
    users.get(aid, {}).get("name", aid[:12])
    for aid in ws_obj.members
    if users.get(aid, {}).get("role", "member") == next_role  # ← 全 member，永远不匹配
]
```

所有 agent 在 `auth.json` 中的 role 均为默认 `member`（或少数为 `admin`），管线角色（arch/dev/review/qa）在 `PIPELINE_STEP_MAP` 中定义但无法匹配工作区成员。点名时 `next_role_names` 始终为空列表，点名失败。

### B.2 设计方案：轻量 Agent Card

受 A2A Agent Card 模式启发，不在代码层硬编码角色映射，而是在容器持久化层维护 `data/agent_cards.json`，每个 agent 持有一份轻量卡片（不进 git 跟踪）。

**文件格式：** `data/agent_cards.json`（注意：非 `docs/` 下、非 `server/` 下、非 git 跟踪）

```json
{
  "version": 1,
  "cards": {
    "<agent_id_1>": {
      "name": "arch-bot",
      "display_name": "小开",
      "pipeline_roles": ["arch"],
      "skills": ["architecture", "planning", "code-review"],
      "status": "online",
      "updated_at": 1719500000.0
    },
    "<agent_id_2>": {
      "name": "dev-bot",
      "display_name": "爱泰",
      "pipeline_roles": ["dev"],
      "skills": ["coding", "testing"],
      "status": "online",
      "updated_at": 1719500000.0
    },
    "<agent_id_3>": {
      "name": "review-bot",
      "display_name": "小周",
      "pipeline_roles": ["review"],
      "skills": ["code-review", "testing"],
      "status": "online",
      "updated_at": 1719500000.0
    },
    "<agent_id_4>": {
      "name": "qa-bot",
      "display_name": "泰虾",
      "pipeline_roles": ["qa"],
      "skills": ["testing", "deployment"],
      "status": "online",
      "updated_at": 1719500000.0
    },
    "<agent_id_5>": {
      "name": "admin-bot",
      "display_name": "小爱",
      "pipeline_roles": ["admin"],
      "skills": ["management", "deployment"],
      "status": "online",
      "updated_at": 1719500000.0
    }
  }
}
```

**核心能力：**

| 场景 | 当前行为（role=member 全面不匹配） | R49 行为（Agent Card 匹配） |
|:----|:-----------------------------------|:--------------------------|
| `!pipeline_start R49` 创建工作室 | 所有成员 role=member，无分类 | 从 `agent_cards.json` 读取 `pipeline_roles`，将对应 agent 加入工作区 |
| `!step_complete StepN` 点名下一角色 | `users.get(aid, {}).get("role") == "arch"` → 永不匹配 | `_get_agent_card_roles(aid)` → 检查 `pipeline_roles` 是否包含 `next_role` |
| 映射表不存在 | — | 完全回退到现有 `auth.get_users()` `role` 字段匹配（向后兼容） |

### B.3 新增函数

```python
# handler.py ≈行 877（_load_step_config 旁）
AGENT_CARDS_PATH: str = "data/agent_cards.json"  # config.DATA_DIR 下

def _load_agent_cards() -> dict:
    """Load agent card mapping from persistent file.
    Returns dict: {agent_id -> {name, display_name, pipeline_roles[], skills[], status}}
    Falls back to empty dict if file missing.
    """
    import os, json
    path = os.path.join(config.DATA_DIR, "data", "agent_cards.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        data = json.load(f)
    return data.get("cards", {})

def _save_agent_cards(cards: dict) -> bool:
    """Save agent card mapping to persistent file."""
    import os, json
    path = os.path.join(config.DATA_DIR, "data", "agent_cards.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"version": 1, "cards": cards}, f, indent=2)
    return True

def _get_agent_card_roles(agent_id: str, cards: dict) -> list[str]:
    """Get pipeline roles for an agent from cards. Returns [] if not found."""
    card = cards.get(agent_id, {})
    return card.get("pipeline_roles", [])

def _find_agents_by_role(role: str, member_ids: list[str], cards: dict) -> list[str]:
    """Find workspace members whose agent card has the given pipeline role."""
    return [
        aid for aid in member_ids
        if role in _get_agent_card_roles(aid, cards)
    ]
```

### B.4 管线集成点

**`_cmd_pipeline_start` 修改（≈行 1081）：**

```
当前：ws_obj = ws_mod.create_workspace(name, members=[...])
    成员列表来自 auth.get_users() 的 admin 列表

R49: cards = _load_agent_cards()
     # 如果卡片存在 → 从卡片收集所有 pipeline_roles 中出现的 agent
     if cards:
       for card_agent_id, card in cards.items():
         if card.get("pipeline_roles"):
           members.append(card_agent_id)
     # 如果卡片不存在 → 回退到 auth.get_users()
     else:
       members = [aid for aid, u in auth.get_users().items() if ...]
```

**`_cmd_step_complete` 修改（≈行 1294-1300）：**

```
当前：next_role_names = [
        users.get(aid, {}).get("name", aid[:12])
        for aid in ws_obj.members
        if users.get(aid, {}).get("role", "member") == next_role
      ]

R49: cards = _load_agent_cards()
     if cards:
       matched = _find_agents_by_role(next_role, ws_obj.members, cards)
       next_role_names = [
         users.get(aid, {}).get("name", aid[:12])
         for aid in matched
       ]
     else:
       # Fallback to old behavior
       next_role_names = [
         users.get(aid, {}).get("name", aid[:12])
         for aid in ws_obj.members
         if users.get(aid, {}).get("role", "member") == next_role
       ]
```

### B.5 管理命令：`!agent_card`

注册到 `_ADMIN_COMMANDS`（`min_role: 3` — 工作室管理员/全局管理员）：

| 命令 | 功能 | 实现 |
|:-----|:-----|:-----|
| `!agent_card list` | 显示当前所有 Agent Card | `_cmd_agent_card_list` |
| `!agent_card get <agent_id>` | 查看指定 agent 的卡片 | `_cmd_agent_card_get` |
| `!agent_card set <agent_id> --role <r1,r2> [--name <n>]` | 设置/更新卡片 | `_cmd_agent_card_set` |
| `!agent_card unset <agent_id>` | 删除卡片 | `_cmd_agent_card_unset` |
| `!agent_card reload` | 不重启重新加载持久化文件 | `_cmd_agent_card_reload` |

**`!agent_card set` 参数：**
- `--role`：管线角色列表，逗号分隔（如 `arch`、`dev`、`review,qa`）
- `--name`：可选，agent 显示名
- `--skills`：可选，技能列表，逗号分隔

**示例：**
```
!agent_card set abc123 --role arch --name 小开
!agent_card set def456 --role dev,qa --name 爱泰
!agent_card list
```

### B.6 `.gitignore` 更新

在 `.gitignore` 中加入：
```
data/agent_cards.json
```

### B.7 涉及代码行

| # | 位置 | 操作 | 预估行数 |
|:-:|:-----|:-----|:--------:|
| 1 | `handler.py` | 新增 `_load_agent_cards` / `_save_agent_cards` / `_get_agent_card_roles` / `_find_agents_by_role` | ~30 |
| 2 | `handler.py` `_cmd_pipeline_start` | 改造成员收集逻辑：优先从卡片读取 | ~10 |
| 3 | `handler.py` `_cmd_step_complete` | 改造点名匹配逻辑：优先从卡片匹配 | ~10 |
| 4 | `handler.py` | 新增 `_cmd_agent_card_list/get/set/unset/reload` 5 个 handler | ~60 |
| 5 | `handler.py` `_ADMIN_COMMANDS` | 注册 5 条新命令 | ~20 |
| 6 | `.gitignore` | 新增忽略规则 | 1 |
| | | **合计** | **~+131** |

### B.8 验收覆盖

B-1 ~ B-9（全 9 项）

---

## 方向 C — 超时告警闭环 + 重启恢复

### C.1 当前问题

R43 已有完整的 watchdog 轮询实现，但存在三个明显短板：

**短板 1：告警只发 `_admin`，不发工作室**
```python
# handler.py:1057 — 告警仅 persist 到 _admin 频道，不广播到工作室
_persist_broadcast(p.ADMIN_CHANNEL, "系统", msg)
```
工作室内成员看不到超时通知，不知道需要被催促的是哪一个 Step。

**短板 2：超时后不触发点名/催办**
超时只是发一条通知消息，不触发 `_rollcall_next` 或二次点名。没有主动催办 Step 负责人的机制。

**短板 3：服务端重启后计时器丢失**
`_PIPELINE_STATE` 只在内存中，重启后所有计时器归零。如果活跃管线在重启前已经接近超时阈值，重启后计时器从零开始重新算，相当于超时机制完全复位。

### C.2 设计方案

#### C.2.1 告警发到工作室（修复最短路径）

在 `_send_watchdog_alert()` 中增加工作室广播逻辑：

```python
# handler.py:1057 行改造
async def _send_watchdog_alert(round_name, step_name, elapsed_hours, timeout_hours, alert_type):
    # ...（现有消息构建不变）...

    # [EXISTING] 发到 _admin 频道
    _persist_broadcast(p.ADMIN_CHANNEL, "系统", msg)

    # [NEW] 如果有活跃管线的工作室 → 也发到工作室
    pstate = _PIPELINE_STATE.get(round_name, {})
    ws_id = pstate.get("ws_id", "")
    if ws_id:
        ws_obj = ws_mod.get_workspace(ws_id)
        if ws_obj:
            alert_msg = (
                f"⏰ {round_name} 管线超时提醒\n"
                f"  Step: {step_display}（{step_name}）\n"
                f"  责任人: {role}\n"
                f"  已挂起: {_elapsed_hours_display(elapsed_hours)}（超时阈值: {timeout_hours}h）\n"
                f"  请 @{role} 尽快处理或私聊项目负责人协调！"
            )
            # Broadcast to workspace members
            payload = json.dumps({
                "type": "broadcast", "channel": ws_id,
                "from_name": "系统", "from": "系统",
                "content": alert_msg, "ts": time.time(),
            })
            for agent_id in ws_obj.members:
                for conn in list(_connections.get(agent_id, set())):
                    try:
                        await conn.send_str(payload) if hasattr(conn, "send_str") else await conn.send(payload)
                    except Exception:
                        pass
            write_chat_log("系统", alert_msg, channel=ws_id)
```

#### C.2.2 超时后触发点名催办（增量）

新增 `_watchdog_rerollcall()` 函数，在超时告警首次触发后尝试再次点名当前 Step 负责人：

```python
async def _watchdog_rerollcall(round_name: str, step_name: str) -> None:
    """After timeout, try to rerollcall the current step owner."""
    pstate = _PIPELINE_STATE.get(round_name, {})
    ws_id = pstate.get("ws_id", "")
    if not ws_id:
        return
    step_config = _load_step_config()
    step_info = step_config.get(step_name, {})
    role = step_info.get("role", "?")
    # 尝试再次点名当前角色
    await _cmd_rollcall_role("系统", {
        "_positional": [role],
        "context": f"{round_name} {step_name} 超时催办",
    })
```

在 `_check_watchdog_alert()` 返回 `"first"` 时调用。

#### C.2.3 重启后恢复计时器（增量）

`_PIPELINE_STATE` 仅在内存中，重启后丢失。但工作室信息和管线元数据部分可从持久化介质恢复：

1. **`started_at` 恢复**：遍历 `_PIPELINE_STATE` 初始化逻辑，检查工作区信息
2. **已创建的任务**：从 `task_store`（SQLite）中查询活跃 round 的未完成 task
3. **Workaround**：如果 `started_at` 无法恢复，则从当前时间开始计时（即重启前的挂起时间不计入）

```python
def _restore_pipeline_timers() -> None:
    """On server start, recover pipeline timeout timers from task store.
    
    Scans active task rounds from task_store, reconstructs:
    - round_name → {active, current_step, ws_id, started_at}
    
    Falls back gracefully: if started_at cannot be recovered,
    starts from current time (lost-time scenario).
    """
    ...
```

在主启动逻辑中调用：`_restore_pipeline_timers()`（在 `handler.py` 模块加载时，或在 `_ensure_watchdog` 中触发）。

#### C.2.4 超时时间可配置

在 `config.py` 已支持 `PIPELINE_STEP_MAP` 中配置 `timeout_hours`。R49 确认：

- 无需新增独立配置项 — 已支持（`config.py` 行 51-56 每 step 有 `timeout_hours` 字段）
- 当前默认值：step1=2h, step2=6h, step3=12h, step4=4h, step5=6h, step6=2h
- 可通过 `PIPELINE_STEP_MAP_OVERRIDE` 环境变量运行时覆盖

### C.3 涉及代码行

| # | 位置 | 操作 | 预估行数 |
|:-:|:-----|:-----|:--------:|
| 1 | `handler.py` `_send_watchdog_alert` | 新增工作室广播逻辑 | ~15 |
| 2 | `handler.py` | 新增 `_watchdog_rerollcall` | ~15 |
| 3 | `handler.py` `_check_watchdog_alert` | 首次超时时调用 rerollcall | ~3 |
| 4 | `handler.py` | 新增 `_restore_pipeline_timers` | ~20 |
| 5 | `handler.py` 模块级 | 调用 `_restore_pipeline_timers` | ~2 |
| | | **合计** | **~+55** |

### C.4 验收覆盖

C-1 ~ C-7（全 7 项）

---

## 改动清单

| # | 文件 | 方向 | 位置 | 改动类型 | 预估行数 |
|:-:|:----|:----:|:-----|:---------|:--------:|
| 1 | `handler.py` | A | ≈行 1609 前 | 新增全频道 `!` 路由分支 | ~+25 |
| 2 | `handler.py` | A | ≈行 1611-1648 | 调整 `_admin` 分支（移除非 ! 解析） | ~-10 |
| 3 | `handler.py` | A | ≈行 1693 | 新增 `_send_to_source_channel` | ~+20 |
| 4 | `handler.py` | B | ≈行 877 旁 | 新增 `_load_agent_cards` 等 4 个函数 | ~+30 |
| 5 | `handler.py` | B | `_cmd_pipeline_start` | 改造成员收集逻辑 | ~+10 |
| 6 | `handler.py` | B | `_cmd_step_complete` | 改造点名匹配逻辑 | ~+10 |
| 7 | `handler.py` | B | 新增 | 新增 5 个 `!agent_card` 命令 handler | ~+60 |
| 8 | `handler.py` | B | ≈行 1395 `_ADMIN_COMMANDS` | 注册 5 条新命令 | ~+20 |
| 9 | `handler.py` | C | `_send_watchdog_alert` | 新增工作室广播 | ~+15 |
| 10 | `handler.py` | C | 新增 | 新增 `_watchdog_rerollcall` | ~+15 |
| 11 | `handler.py` | C | `_check_watchdog_alert` | 首次超时触发 rerollcall | ~+3 |
| 12 | `handler.py` | C | 新增 | 新增 `_restore_pipeline_timers` | ~+20 |
| 13 | `handler.py` | C | 模块级 | 启动时调用恢复 | ~+2 |
| 14 | `.gitignore` | B | 尾部 | 新增忽略规则 | ~+1 |
| | | | | **合计** | **~+221 行** |

**零删除（除 `_admin` 分支中移除的 ~10 行 ! 解析逻辑外），零新增文件（`agent_cards.json` 是运行时数据文件，非代码文件），零新增依赖。**

---

## 向后兼容性分析

| 场景 | R48 行为 | R49 行为 | 兼容？ |
|:-----|:---------|:---------|:------:|
| `_admin` 频道发 `!step_complete StepN` | 执行 handler，`_persist_admin_response` | 同样执行（走通用路由），结果回 `_admin` | ✅ 完全一致 |
| `_admin` 频道发非 `!` 消息 | 拦截并提示「仅支持 ! 命令」 | 同左 | ✅ 完全一致 |
| 工作室发普通消息 | 广播给成员 + admin | 同左（非 `!` 前缀不受影响） | ✅ 完全一致 |
| 工作室发 `!step_complete` | 当作广播消息，无效果 | 执行 handler，结果回工作室 | ✅ 新功能 |
| `!pipeline_start R49`（无 `agent_cards.json`） | 从 `auth.get_users()` 收集 admin | 同左（回退逻辑） | ✅ 完全一致 |
| `!step_complete StepN`（无 `agent_cards.json`） | `role` 字段匹配 → 永远不匹配 | 同左（回退到 `role` 字段） | ✅ 完全一致 |
| 超时告警（无活跃管线） | 发 `_admin` 频道 | 发 `_admin` 频道（无 ws_id → 跳过工作室分支） | ✅ 完全一致 |
| 超时告警（有活跃管线） | 仅发 `_admin` 频道 | 发 `_admin` + 工作室 | ✅ 增强 |
| 服务端重启、无管线 | 无声 | 同左（`_restore_pipeline_timers` 无数据 → 无操作） | ✅ 完全一致 |
| `config.py` 不改动 | — | — | ✅ 零改动 |

**结论：** 所有场景向后兼容。三个方向均为纯增量增强。`agent_cards.json` 不存在时三个方向的行为与 R48 基线完全一致。

---

## 风险与注意事项

### R1. 通用路由先于 `_admin` 分支 → `_admin` 行为验证

全频道路由必须在 `_admin` 分支之前截获 `!` 消息。验证点：`_admin` 频道发 `!step_complete` → 通用路由截获 → 执行 handler → `_send_to_source_channel(channel=ADMIN_CHANNEL)` → 结果 `_persist_admin_response`。`_admin` 分支中移除 `!` 处理后，保留非 `!` 消息拦截逻辑。

### R2. `!` 误解析风险

如果普通消息恰好以 `!` 开头（如 `!注意 xxx`），会被通用路由截获并尝试解析。**缓解措施：** `_parse_command` 要求 `!` 后紧跟命令名（字母开头），`!注意` 不会匹配 `_ADMIN_COMMANDS` 中任何命令，会返回 `❌ 未知命令`。这种误触发的成本极低（一条错误提示），但用户体验略差。可考虑在通用路由中增加一个快速检查：`!` 后首个单词是否在 `_ADMIN_COMMANDS` 中，不再由 `_parse_command` 承担。

### R3. Agent Card 初始配置成本

首次部署后需要管理员逐条执行 `!agent_card set` 注册各 agent 卡片。提供两个降低初始成本的选项：
- **批量 import**：管理员可直接在容器卷中写入 `data/agent_cards.json`（JSON 格式），然后执行 `!agent_card reload` 加载
- **容器初始化脚本**：在首次启动部署时由 admin-bot 自动执行一组 `!agent_card set` 命令

### R4. Agent Card 脱敏义务

`data/agent_cards.json` 包含真实 `agent_id`（类似 `auth.json`），**绝不进 git 跟踪**、绝不进代码仓库。`.gitignore` 显式忽略该路径。

### R5. 超时重启恢复的精度限制

`_restore_pipeline_timers` 从 `task_store`（SQLite）恢复 `started_at`。但 task_store 的 task 的 `created_at` 字段可能不是精确的 Step 开始时间（因为 Step 点名后需要等待「到」确认才会真正开始）。**降级策略：** 如果无法精确恢复 `started_at`，使用当前时间（即重启前的挂起时间不计入超时）。这对用户来说意味着重启可能"重置"超时计时，但总比没有超时检测好。

### R6. 三方向无代码冲突

方向 A（通用路由）、方向 B（Agent Card 持久化）、方向 C（超时告警闭环）在 `handler.py` 中影响不同的函数模块，无代码冲突，可平行开发、平行编码。

### R7. TG 协调链路无代码改动

方向 C 的「超时后工作室活跃 bot 主动 TG 私聊项目负责人」是人工行为，服务端只负责发超时通知到工作室。谁发现异常，谁主动联系项目负责人协调。这与需求文档一致（§3.3 升级通知链路）。

---

## 参考

- `server/handler.py` `handle_broadcast` 行 1548-1693（R48 基线）
- `server/handler.py` `_cmd_pipeline_start` 行 1081-1177（R48 基线）
- `server/handler.py` `_cmd_step_complete` 行 1199-1349（R48 基线）
- `server/handler.py` `_load_step_config` 行 877-880
- `server/handler.py` `_send_watchdog_alert` 行 1030-1058（R43 基线）
- `server/handler.py` `_watchdog_scan` 行 945-982（R43 基线）
- `server/handler.py` `_ADMIN_COMMANDS` 行 1395-1503
- `server/config.py` `PIPELINE_STEP_MAP` 行 50-57
- `docs/A2A-Protocols-Research-Report.md` §4.1 Agent Card 设计模式
- `docs/R49/R49-product-requirements.md` v0.2 ✅

---

> **审核记录：**
> - v1.0 提交方向审查：2026-06-28
> - 方向审查结论：⏳ 待审查
