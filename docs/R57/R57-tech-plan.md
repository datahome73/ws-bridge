# R57 技术方案 — Step 交接点名发现 + 在线状态预检 + 备用自动换人 + 角色名显示

> **版本：** v1.0
> **状态：** 📝 待编码
> **架构师：** 🏗️ arch-bot
> **日期：** 2026-06-30
> **基于需求文档：** `docs/R57/R57-product-requirements.md` v0.4
> **基于工作计划：** `docs/R57/WORK_PLAN.md` v1.0

---

## 0. 改动范围

| 方向 | 说明 | 文件 | 行数 | 优先级 |
|:----:|:-----|:----|:----:|:------:|
| **A** | `PIPELINE_STEP_MAP` 扩展 `primary`/`backup` + `_cmd_step_complete` 预检+点名换人 | `server/config.py`, `server/handler.py` | ~30 行 | 🔴 P0 |
| **C** | 系统消息角色名替代 agent ID | `server/handler.py` | ~8 行 | 🔴 必修 |

---

## 1. 方向 A（核心）：Step 交接点名发现 + 备用自动换人

### 1.1 PIPELINE_STEP_MAP 扩展

**位置：** `server/config.py` 第 62-70 行

**当前结构：**
```python
PIPELINE_STEP_MAP: dict[str, dict] = {
    "step1": {"role": "admin",   "name": "管线启动",       "timeout_hours": 2.0,  "escalation": "notify_pm"},
    "step2": {"role": "arch",    "name": "技术方案",       "timeout_hours": 6.0,  "escalation": "notify_pm"},
    "step3": {"role": "dev",     "name": "编码",          "timeout_hours": 12.0, "escalation": "notify_pm"},
    "step4": {"role": "review",  "name": "代码审查",       "timeout_hours": 4.0,  "escalation": "notify_pm"},
    "step5": {"role": "qa",      "name": "测试验证",       "timeout_hours": 6.0,  "escalation": "notify_pm"},
    "step6": {"role": "admin",   "name": "合并部署归档",    "timeout_hours": 2.0,  "escalation": "notify_pm"},
}
```

**新增字段：** 每个 Step 增加 `"primary"`（主角角色名）和 `"backup"`（备用角色名）。

**修改后结构（仅修改 step2-step6，step1 不涉及交接无需主备）：**
```python
PIPELINE_STEP_MAP: dict[str, dict] = {
    "step1": {"role": "admin",   "name": "管线启动",       "timeout_hours": 2.0,  "escalation": "notify_pm"},
    "step2": {"role": "arch",    "name": "技术方案",       "timeout_hours": 6.0,  "escalation": "notify_pm",
              "primary": "arch", "backup": "dev"},
    "step3": {"role": "dev",     "name": "编码",          "timeout_hours": 12.0, "escalation": "notify_pm",
              "primary": "dev",  "backup": "arch"},
    "step4": {"role": "review",  "name": "代码审查",       "timeout_hours": 4.0,  "escalation": "notify_pm",
              "primary": "review", "backup": "qa"},
    "step5": {"role": "qa",      "name": "测试验证",       "timeout_hours": 6.0,  "escalation": "notify_pm",
              "primary": "qa",   "backup": "review"},
    "step6": {"role": "admin",   "name": "合并部署归档",    "timeout_hours": 2.0,  "escalation": "notify_pm",
              "primary": "admin", "backup": "arch"},
}
```

**设计说明：**
- `primary` 和 `backup` 都是**角色名**（不是 agent ID），由 `_find_agents_by_role()` 解析到具体 agent
- 通过 agent cards 和 `auth.get_users()` 双重查找（现有逻辑复用，详见 `handler.py` 第 877-882 行 `_find_agents_by_role`）
- 约束「不能自己审自己」由 WORK_PLAN 配置保证，不在代码级硬校验
- step1（管线启动）是自动步骤，不设主备
- `_override_raw` 环境变量覆盖逻辑保持不变（config.py 第 71-78 行）

### 1.2 `_cmd_step_complete` 改造 — 在线预检 + 点名发现 + 换人

**位置：** `server/handler.py` 第 1499-1539 行（「查下一 Step」至「定向通知」段）

#### 1.2.1 当前代码逻辑（已精简）

```python
# handler.py:1499 当前代码
next_step = step_keys[current_idx + 1]
next_role = step_config[next_step]["role"]

# ... resolve display names ...
users = auth.get_users()
cards = _load_agent_cards()
# ... find agents matching next_role ...
target_agents = _find_agents_by_role(next_role, member_ids, cards)  # 或 fallback

# Notify ALL matching agents
for agent_id in target_agents:
    await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
```

当前行为：找到下一 Step 的角色 → 通知**所有**匹配该角色的 agent → 完成。

#### 1.2.2 改造后逻辑流程图

```
!step_complete stepN --output <sha>
  ↓
① 标记 Step N 完成（现有代码，保持不动，handler.py:1436-1451）
  ↓
② 查下一 Step = stepN+1（现有代码，handler.py:1499）
  ↓
③ 从 step_config 读取 next_step 的 primary / backup 角色名
   （新增读取：step_config[next_step].get("primary"), .get("backup")）
  ↓
④ 通过 _find_agents_by_role() 解析 primary_role → 候选 agent_id 列表
   （若无 backup 配置 → 跳过，回退到原有全通知逻辑 = 行为不变 A-9）
  ↓
┌─ primary_agents 为空（无匹配 agent）───── 回退旧逻辑 ────┐
│    通知所有匹配 role 的 agent（当前行为）                  │
│    标记：no_primary_fallback                              │
└──────────────────────────────────────────────────────────┘
  ↓（primary_agents 非空）
⑤ 取 primary_agents[0] 作为主角 agent_id
   查 _connections[primary_agent_id]
  ↓
┌─ _connections 为空（主角离线）─── 0s 等待 ──────┬─ _connections 非空（主角在线）┐
│    ↓                                            │    ↓                          │
│  ⚠️ 系统广播到工作室：                            │  ⑦ 点名主角：                  │
│   「⚠️ 主角离线，{next_step} 由备用接替」           │   定向发送                    │
│    ↓                                            │   「@{agent} Step N+1 到你了,│
│  ⑥ 查 backup_agent（_find_agents_by_role 解析）   │    请回复确认」               │
│    ↓                                            │    ↓                          │
│  ├─ backup 在线 → 定向通知备用带上下文              │  启动 30 秒定时器             │
│  ├─ backup 离线 → 工作室广播                      │    ↓                          │
│  │   「🔴 主角和备用均不在线，等待协调」              │  ├─ 主角回复 ✅ → 正常交接    │
│  └─ 无 backup 配置 → 通知全 role（A-9 兼容）        │  │  （不换人，当前逻辑）        │
└──────────────────────────────────────────────────┤  ├─ 30s 无响应 → 切备用      │
                                                   │  │  ↓ 同 ⑥                   │
                                                   └──────────────────────────────┘
  ↓
⑧ 创建下一步 Task、更新管线状态（复用现有代码 handler.py:1541-1549）
  ↓
⑨ 返回结果消息（含备用接替标记）
```

#### 1.2.3 精确代码改动

**改动 A：`_cmd_step_complete` 内，替换当前「定向通知」段（约 handler.py 第 1499-1539 行）**

替换前（当前代码的主要结构，line 1499 ~ 1539 — 注意不是精确逐行替换，而是逻辑段落的替换）：

```python
# 第 1499 行：找到下一 Step
next_step = step_keys[current_idx + 1]
next_role = step_config[next_step]["role"]

# 第 1502-1518 行：解析角色显示名（现有代码保留）
# ...

# 第 1527-1539 行：定向通知
member_ids = list(ws_obj.members)
if cards:
    target_agents = _find_agents_by_role(next_role, member_ids, cards)
else:
    target_agents = [ ... ]
for agent_id in target_agents:
    await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
rollcall_result = f"📨 已通知 {next_role_display}（{len(target_agents)} 人）接管 {next_step}"
```

替换为：

```python
# ── 第 1499 行开始：找到下一 Step（保持不动）
next_step = step_keys[current_idx + 1]
next_role = step_config[next_step]["role"]

# ── 第 1502-1518 行：解析角色显示名（保持不动，现有代码照旧）

# ── R57 A: Online pre-check + rollcall with backup fallback ──
member_ids = list(ws_obj.members)
users = auth.get_users()                       # 已有定义
cards = _load_agent_cards()                    # 已有定义

# 读取 primary/backup 配置
primary_role = step_config[next_step].get("primary")
backup_role = step_config[next_step].get("backup")

# 解析 primary agent
primary_agents = []
if cards and primary_role:
    primary_agents = _find_agents_by_role(primary_role, member_ids, cards)
if not primary_agents:
    # 无 primary 配置 → 回退到原有全通知行为（A-9 兼容）
    if cards:
        target_agents = _find_agents_by_role(next_role, member_ids, cards)
    else:
        target_agents = [aid for aid in member_ids
                         if users.get(aid, {}).get("role", "member") == next_role]
    for agent_id in target_agents:
        await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
    rollcall_result = f"📨 已通知 {next_role_display}（{len(target_agents)} 人）接管 {next_step}"
else:
    primary_agent = primary_agents[0]
    primary_name = users.get(primary_agent, {}).get("name", primary_agent[:12])
    conns = _connections.get(primary_agent, set())

    if not conns:
        # ── 主角离线 ── 直接切备用，0秒等待 ──
        rollcall_result = await _r57_switch_to_backup(
            round_name, next_step, next_role,
            backup_role, member_ids, cards, users,
            ws_obj, sender_ch, targeted_notify, primary_name,
            reason="primary_offline"
        )
    else:
        # ── 主角在线 ── 点名确认，30秒超时 ──
        rollcall_msg = f"@**{primary_name}** Step「{next_step}」轮到你了，请在 30 秒内回复确认"
        await _persist_broadcast(sender_ch, "系统", rollcall_msg)
        for conn in conns:
            try:
                await _send(conn, {"type": "broadcast", "channel": sender_ch,
                                    "from_name": "系统", "content": rollcall_msg, "ts": time.time()})
            except Exception:
                pass

        # 启动 30 秒点名定时器
        ack_received = await _r57_wait_for_ack(primary_agent, timeout=30)

        if ack_received:
            # 主角回复 ✅ 正常交接
            if cards:
                target_agents = _find_agents_by_role(next_role, member_ids, cards)
            else:
                target_agents = [aid for aid in member_ids
                                 if users.get(aid, {}).get("role", "member") == next_role]
            for agent_id in target_agents:
                await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
            rollcall_result = f"✅ 主角 {primary_name} 已确认，正常交接 {next_step}"
        else:
            # 主角 30 秒无响应 → 切备用
            rollcall_result = await _r57_switch_to_backup(
                round_name, next_step, next_role,
                backup_role, member_ids, cards, users,
                ws_obj, sender_ch, targeted_notify, primary_name,
                reason="primary_timeout"
            )
```

#### 1.2.4 新增辅助函数

**`_r57_switch_to_backup` — 备用接替处理**

```python
async def _r57_switch_to_backup(
    round_name: str, next_step: str, next_role: str,
    backup_role: str | None, member_ids: list[str],
    cards: dict, users: dict, ws_obj, sender_ch: str,
    targeted_notify: str, primary_name: str,
    reason: str,
) -> str:
    """R57: 主角离线或无响应时，切换备用接替。

    reason: "primary_offline" | "primary_timeout"
    返回 rollcall_result 字符串。
    """
    # 广播换人公告到工作室
    if reason == "primary_offline":
        swap_msg = f"⚠️ 主角 {primary_name} 离线，{next_step} 由备用接替"
    else:
        swap_msg = f"⚠️ 主角 {primary_name} 未响应，{next_step} 由备用接替"
    _persist_broadcast(sender_ch, "系统", swap_msg)

    backup_assigned = False

    # 查找备用 agent
    backup_agents = []
    if cards and backup_role:
        backup_agents = _find_agents_by_role(backup_role, member_ids, cards)
    if not backup_agents:
        # 无 backup 配置 → 通知全 role（A-9 兼容）
        if cards:
            backup_agents = _find_agents_by_role(next_role, member_ids, cards)
        else:
            backup_agents = [aid for aid in member_ids
                             if users.get(aid, {}).get("role", "member") == next_role]

    for backup_agent in backup_agents:
        backup_conns = _connections.get(backup_agent, set())
        backup_name = users.get(backup_agent, {}).get("name", backup_agent[:12])
        if backup_conns:
            # 备用在线 → 定向通知带完整上下文
            backup_notify = targeted_notify + "\n（🔧 您作为备用接替此 Step）"
            await _send_to_agent(backup_agent, backup_notify, ws_id=sender_ch)
            backup_assigned = True

    if not backup_assigned:
        # 备用也离线 → 系统广播到工作室
        critical_msg = f"🔴 {next_step} 主角和备用均不在线，等待协调"
        _persist_broadcast(sender_ch, "系统", critical_msg)
        # _admin 频道日志
        try:
            admin_channel = p.ADMIN_CHANNEL
            admin_msg = f"📋 {round_name} | {next_step} | 主角+备用均离线，需人工介入"
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=admin_msg, ts=time.time(),
                data_dir=config.DATA_DIR, channel=admin_channel,
            )
            write_chat_log("系统", admin_msg, channel=admin_channel)
        except Exception:
            pass

    # _admin 频道记录换人日志
    try:
        admin_channel = p.ADMIN_CHANNEL
        log_msg = f"📋 {round_name} | {next_step} | {reason.replace('_', ' ')} → 备用接替"
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent="系统", from_name="系统",
            content=log_msg, ts=time.time(),
            data_dir=config.DATA_DIR, channel=admin_channel,
        )
        write_chat_log("系统", log_msg, channel=admin_channel)
    except Exception:
        pass

    return f"🔄 {next_step} — 由备用接替（{reason.replace('_', ' ')})"
```

**`_r57_wait_for_ack` — 30 秒点名等待**

```python
async def _r57_wait_for_ack(agent_id: str, timeout: int = 30) -> bool:
    """等待 agent 在 timeout 秒内回复 ACK。返回是否收到确认。

    实现方式：在 _task_ack_timers 或类似机制中注册一次性监听。
    简单实现：asyncio.sleep(timeout) 并用 _r57_ack_received 标志位。

    编码者选择方案（以下二选一）：
    方案 1：用 asyncio.Event
        event = _r57_rollcall_events.get(agent_id)
        if not event:
            event = asyncio.Event()
            _r57_rollcall_events[agent_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            _r57_rollcall_events.pop(agent_id, None)

    方案 2：用已存在的 _task_ack_timers 机制扩展
        在收到 agent_id 的 MSG_ACK 时设置标志位
    """
    # 编码时根据现有 ACK 机制选择具体实现
    pass  # 待编码实现
```

**全局变量新增（handler.py 顶部附近）：**
```python
# ── R57 A: Rollcall ACK events ──
_r57_rollcall_events: dict[str, asyncio.Event] = {}
```

**ACK 监听（在 handle_broadcast 或 handle_ack 中钩入）：**

在 `handle_broadcast` 或相应消息处理函数中，当收到 agent 回复与点名相关的消息时，触发 event set。编码时需确定适当的钩入点（现有 `_task_ack_timers` 或新增监听路径）。

### 1.3 `!pipeline_status` 备用接替标记

**位置：** `server/handler.py` 第 1976-1977 行

**改动：** 当前 Step 的行尾追加 `(备用接替)` 标记。

**当前代码：**
```python
current = " ◀ 当前" if step_key == pstate.get("current_step") else ""
lines.append(f"  {task_state} {step_key} — {role}{current}")
```

**修改后：**
```python
current = " ◀ 当前" if step_key == pstate.get("current_step") else ""
# ── R57 A-6: Backup takeover marker ──
backup_suffix = ""
pipeline_backup = pstate.get("backup_active", {})
if step_key == pipeline_backup.get("step"):
    backup_suffix = "（备用接替）"
lines.append(f"  {task_state} {step_key} — {role}{current}{backup_suffix}")
```

**配套：** 在 `_r57_switch_to_backup` 中设置 `pstate["backup_active"] = {"step": next_step, "role": backup_role}`，在 Step 正常完成时清空。

### 1.4 主角回归待命（A-7）

**实现位置：** `_cmd_step_complete` 返回前 / `_r57_switch_to_backup` 末尾

**设计：** 不抢占逻辑在现有架构中已天然满足 — 每个 `!step_complete` 只推进一步，如果主角在备用工作中重新上线，下一轮 `!step_complete` 再检测时，会切换到该 Step 的主备配置。无需额外代码。主角回归自然在下一 Step 的轮次中生效。

**唯一需要的存储：** 在管线 state 中记录当前执行者角色（是主角还是备用），供 `!pipeline_status` 展示。新增 `pstate["current_actor"] = "primary" | "backup"`。

### 1.5 验收标准映射

| # | 验收标准 | 技术实现对应点 |
|:-:|:---------|:--------------|
| A-1 | 主角在线→点名 30s→回复→正常交接 | `_connections` 非空 → `_cmd_rollcall_next` 正常路径 |
| A-2 | 主角 `_connections` 为空→直接切备用，0s 等待 | `_r57_switch_to_backup(reason="primary_offline")` |
| A-3 | 主角在线但不回复→30s 超时→切备用 | `_r57_wait_for_ack` 超时 → `_r57_switch_to_backup(reason="primary_timeout")` |
| A-4 | 备用接替→工作室收换人公告 | `_persist_broadcast` 发 swap_msg 到工作室 |
| A-5 | `_admin` 频道记录换人日志 | `ms.save_message` + `write_chat_log` 到 ADMIN_CHANNEL |
| A-6 | `!pipeline_status` 标注「备用接替」 | `pstate["backup_active"]` + 行内标记 |
| A-7 | 主角中途上线→不抢占，自动待命 | 天然满足（每 Step 只推进一次，不主动干扰） |
| A-8 | 主角+备用同时离线→系统广播 | `not backup_assigned` 分支 → critical_msg |
| A-9 | 无 backup 配置→行为不变 | `if not primary_agents:` 回退到 `_find_agents_by_role(next_role)` 全通知 |

---

## 2. 方向 C（捎带）：系统消息角色名替代 agent ID

### 2.1 `_cmd_create_workspace` 成员列表（影响 `!pipeline_start` 系统消息）

**位置：** `server/handler.py` 第 444 行

**当前代码：**
```python
member_list = ", ".join(member_ids) if member_ids else "无"
```

**修改后：**
```python
# ── R57 C-1: Use role/name instead of raw agent ID ──
users_for_display = auth.get_users()
member_names = []
for mid in member_ids:
    # Try agent card display_name first, then auth name, then role, then truncated ID
    name = users_for_display.get(mid, {}).get("name", "")
    if not name:
        role = users_for_display.get(mid, {}).get("role", "")
        name = role if role else mid[:12]
    member_names.append(name)
member_list = ", ".join(member_names) if member_names else "无"
```

**说明：** `users` 已在 `_cmd_create_workspace` 第 431 行定义为 `users = auth.get_users()`，可直接复用。

### 2.2 `_cmd_pipeline_status` 角色显示（C-2）

**位置：** `server/handler.py` 第 1977 行

**当前代码：**
```python
lines.append(f"  {task_state} {step_key} — {role}{current}")
```

`role` 已经是角色名（arch/dev/review/qa/admin），不属于 agent ID。但当前 Step 行右侧没有显示具体执行者的名字。需求说「成员列表」，所以应该在工作区成员概览处展示。

查看 `_cmd_pipeline_status` 输出：当前只有 Step 进度表，没有独立的工作区成员列。如果要展示「当前有哪些人在工作室 + 各自角色」，应在管线状态头部追加一行。

**修改方案（在管线状态头部追加成员信息）：**
```python
# ── R57 C-2: Display member names instead of agent IDs ──
if ws_obj:
    member_info = []
    for mid in ws_obj.members:
        name = users.get(mid, {}).get("name", "")
        role = users.get(mid, {}).get("role", "")
        label = name if name else (role if role else mid[:12])
        online = "🟢" if mid in _connections and _connections[mid] else "🔴"
        member_info.append(f"{online}{label}")
    if member_info:
        lines.append(f"  成员: {' · '.join(member_info)}")
```

### 2.3 name 缺失时 role 回退（C-3）

上面两处修改均已处理该逻辑：先查 name，空则回退到 role，再空则截断 ID。

### 2.4 agent ID 在服务端日志中保留（C-4）

本方向 C 改动仅影响系统消息文本渲染，服务端日志 `logger.info` 和 `write_chat_log` 的参数保持不变。方向 C 不改动任何日志调用。

---

## 3. 依赖与开关

### 3.1 方向间依赖

```
方向 A（在线预检+点名换人）← 独立，不依赖 C
方向 C（角色名显示）      ← 独立，正交修改
```

两个方向代码改动不重叠，可同时编码、分别审查。

### 3.2 向后兼容

- 无 `primary`/`backup` 的旧配置：`step_config[next_step].get("primary")` 返回 `None` → 回退到以 `role` 字段全通知（A-9 兼容）
- 无 agent card 的环境：`_find_agents_by_role` fallback 到 `auth.get_users()` 的 `role` 字段
- 方向 C：纯展示层改动，不影响任何功能逻辑

### 3.3 配置开关

无运行时开关。`PIPELINE_STEP_MAP` 的主备字段是配置层决定，部署时通过 git 提交 config.py 变更或 `PIPELINE_STEP_MAP_OVERRIDE` 环境变量控制。不需要启用/禁用本功能的 runtime flag。

---

## 4. 编码注意事项

### 4.1 `_send` 与 `_send_to_agent` 的区别

| 函数 | 用途 | 注意 |
|:-----|:-----|:-----|
| `_send(ws, payload)` | 直接发送到单个 WS 连接（handler.py 内部） | payload 是 dict，自动 JSON |
| `_send_to_agent(agent_id, text, ws_id)` | 定向通知 + 离线回退 | text 是字符串，内部构造 broadcast payload |

在点名换人广播公告时，使用 `_persist_broadcast` + 现有写入机制，不要直接调用 `_send` 以避免绕过程序化持久化。

### 4.2 并发安全

- `asyncio.Event` 是线程安全的协程原语
- `_connections` 是全局 dict，在协程中迭代时使用 `list()` 复制（现有惯性已妥善处理）
- 30 秒定时器用 `asyncio.wait_for` 而非 `time.sleep`，避免阻塞事件循环

### 4.3 日志记录

- 换人事件必须写入 `_admin` 频道（`ms.save_message` + `write_chat_log`）
- 日志格式统一：`📋 {round_name} | {step_name} | {reason} → {action}`
- 调试日志用 `logger.info` 而非 `print`

### 4.4 边界情况

| 场景 | 处理 |
|:-----|:-----|
| 主角有多个 WS 连接 | 使用 `list(_connections.get(agent_id, set()))` 遍历所有连接发消息 |
| 某个 WS 连接已断开但仍在 `_connections` 中 | `_send` 抛出异常 → except 静默跳过（现有模式） |
| 备用是主角自己 | 不应发生（主备配置约束），但代码安全处理：只调用 `_send_to_agent` |
| `!step_complete` 并发调用 | 2 秒序列化缓冲已存在（handler.py:1426-1431） |
| 主角先离线又在上线瞬间 | `_connections` 在 `ws_handler finally` 中清理（`__main__.py:636-639`），无竞争 |

---

## 5. 测试要点

### 5.1 单元测试注入（如存在测试框架）

| 测试 | 注入方式 |
|:-----|:---------|
| 主角离线换人 | 设置 `_connections[agent_id] = set()` |
| 主角在线点名 | 设置 `_connections[agent_id] = {mock_ws}` |
| 30 秒超时 | 用 `asyncio.Event` + 不 set 模拟超时 |
| 备用也离线 | `_connections[backup_id] = set()` |
| 无 backup 配置 | 从 config 中删除 `backup` key |

### 5.2 手工验证步骤

1. 部署容器后，主角和备用各开一个 bot 进入工作室
2. `!step_complete Step2 --output <sha>`
3. 观察：主角应收到点名通知
4. 主角不回复 → 30 秒后备用收到通知
5. 断开主角连接 → 再次 Step 交接 → 直接切备用
6. 两个 bot 都断开 → 工作室收到「均不在线」广播

---

## 6. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:-----|
| v1.0 | 2026-06-30 | 初始版本 — 方向 A（在线预检+点名换人）+ 方向 C（角色名显示）完整方案 |
