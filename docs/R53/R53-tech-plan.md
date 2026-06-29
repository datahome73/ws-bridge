# R53 技术方案 — ACK 确认制点名与派活

> **版本：** v1.0
> **状态：** 🔶 定稿
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-29
> **基于需求：** [R53-product-requirements.md v1.0 ✅](./R53-product-requirements.md)
> **基于工作计划：** [WORK_PLAN.md v1.0 ✅](./WORK_PLAN.md)

---

## Part A — 方案设计

### 架构图

```
                    ┌───────────────────────┐
                    │     _broadcast_        │
                    │  active_channel(ws_id) │
                    └───────┬───────────────┘
                            │
          ┌─────────────────▼──────────────────┐
          │  1. Persist channel for all members │
          │  2. Send MSG_SET_ACTIVE_CHANNEL     │
          │     (with per-broadcast ack_task_id)│
          │  3. _start_channel_ack_wait(ws_id)  │
          │     → 30s timeout per online member │
          └─────────────────┬──────────────────┘
                            │
              ┌─────────────▼─────────────┐
              │   Member → MSG_ACK        │
              │   { task_id, channel,     │
              │     status: "switched" }  │
              │         +                 │
              │   MSG_CHANNEL_UPDATED     │
              │   (already sent by bot    │
              │    on receiving SET)      │
              └─────────────┬─────────────┘
                            │
          ┌─────────────────▼──────────────────┐
          │  handle_broadcast: MSG_ACK branch  │
          │  1. Match ack_task_id in           │
          │     _channel_ack_state             │
          │  2. Mark member "acknowledged"     │
          │  3. All acked? → Complete          │
          └─────────────────┬──────────────────┘
                            │
              ┌─────────────▼─────────────┐
              │ _notify_rollcall_complete  │
              │ ✅ 全员已切换 / ⚠️ N人未响应│
              └───────────────────────────┘


                    ┌───────────────────────┐
                    │   _cmd_step_complete   │
                    └───────┬───────────────┘
                            │
              ┌─────────────▼─────────────┐
              │ ① Mark current task ✅    │
              │ ② _broadcast_active_      │
              │   channel(ws_id) + ACK    │ ← Direction A + C
              │ ③ _cmd_task_create()      │
              │   → task: submitted       │
              │ ④ Wait MSG_TASK_ACK       │ ← Direction B
              │   → task: working         │
              │ ⑤ _update_pipeline_step() │
              │ ⑥ Return result           │
              └───────────────────────────┘
```

### A-1: 新增 `_channel_ack_state` 全局变量

```python
# 替代 _rollcall_active / _rollcall_confirmed / _rollcall_timers
_channel_ack_state: dict[str, dict] = {}
# ws_id → {
#   "ack_task_id": str,           # per-broadcast unique ID
#   "online_members": set[str],   # members that were online at send time
#   "acked_members": dict[str]    # {agent_id: ack_timestamp}
#   "timer": asyncio.Task | None  # 30s timeout task
#   "callback": callable | None   # called on completion/partial
# }
```

合并替代三个旧全局变量（`_rollcall_active`、`_rollcall_confirmed`、`_rollcall_timers`），统一在同一个 dict 中维护频道切换 ACK 状态。

### A-2: `_broadcast_active_channel()` 增强（带 ACK 等待）

**改动目标：** 现有函数（L2631）增加 ACK 等待逻辑，不仅返回 online_count，还返回 ACK 结果。

```python
async def _broadcast_active_channel(ws_id: str) -> dict:
    """Broadcast MSG_SET_ACTIVE_CHANNEL with ACK waiting.
    Returns: {online_count, acked_members: set[str], timedout_members: set[str]}
    """
```

**关键变更：**

1. 生成一个 `ack_task_id = str(uuid.uuid4())`，附加到 MSG_SET_ACTIVE_CHANNEL 消息中
2. 在线成员发送后记录到 `_channel_ack_state[ws_id].online_members`
3. 启动 30s 定时器任务（`_channel_ack_timeout(ws_id)`）
4. 函数**不阻塞**（asyncio 定时器走后台），返回立即可用的部分结果
5. 完整结果通过 `_notify_rollcall_complete()` 传递

```python
# payload 增加 task_id 字段
switch_payload = json.dumps({
    "type": p.MSG_SET_ACTIVE_CHANNEL,
    p.FIELD_CHANNEL: ws_id,
    p.FIELD_TASK_ID: ack_task_id,   # ★ NEW
    "content": f"请将活跃频道切换至 {ws_id} 后回复 ACK",
    "ts": time.time(),
})
```

### A-3: 新增 `_channel_ack_timeout()` 定时器

```python
async def _channel_ack_timeout(ws_id: str) -> None:
    """30s timeout for channel switch ACK.
    On timeout: marks unresponsive members as timeout,
    calls _notify_rollcall_complete() with partial result.
    """
```

**行为：**
- 30s 后检查 `_channel_ack_state[ws_id].acked_members`
- 未 ACK 的在线成员标记为 `timed_out`
- 调用 `_notify_rollcall_complete()` 报告结果
- 清理 `_channel_ack_state[ws_id]`

### A-4: 新增 `MSG_ACK` 消息处理分支

在 `handle_broadcast()` 的 `msg_type` 分发循环中（L3407 附近）新增分支：

```python
# —— R53 A-4: Channel switch ACK ——
elif msg_type == p.MSG_ACK and agent_id:
    ack_task_id = msg.get(p.FIELD_TASK_ID, "")
    status = msg.get(p.FIELD_TASK_STATUS, "switched")  # "switched" | "failed"
    channel = msg.get(p.FIELD_CHANNEL, "")
    
    # Find matching channel_ack_state by ack_task_id
    ws_id = _resolve_ws_by_ack_task_id(ack_task_id)
    if not ws_id or ws_id not in _channel_ack_state:
        continue  # stale ACK or not waiting
    
    state = _channel_ack_state[ws_id]
    if status == "switched":
        state["acked_members"][agent_id] = time.time()
        await _send(ws, {"type": "ack", "status": "ok",
                         "message": "✅ 频道切换已确认"})
        
        # All online members acknowledged?
        if state["acked_members"].keys() >= state["online_members"]:
            state["timer"].cancel()
            asyncio.create_task(_notify_rollcall_complete(ws_id))
    # "failed" → record but don't block
```

**关键设计：** ACK 的匹配不靠 ws_id 字符串（多个 pipeline 可能共用同一频道名），而是靠 `ack_task_id` UUID 做精确追踪。

### A-5: 移除旧的文本确认机制

**移除项：**

| # | 位置 | 行号 | 删除内容 |
|:-:|:-----|:----:|:---------|
| 🗑️ | `_auto_rollcall_notify()` | L329-354 | 整个函数 — 文本「📋 点名报道 + 回复到 + 3分钟超时」 |
| 🗑️ | `_rollcall_timeout()` | L2871-2905 | 整个函数 — 3分钟超时（替换为 30s ACK 超时） |
| 🗑️ | 文本「已切」确认 | L2360-2378 | `content.strip() == "已切"` 处理分支 |
| 🗑️ | `_rollcall_active` | L86 | 全局变量（被 `_channel_ack_state` 替代） |
| 🗑️ | `_rollcall_timers` | L87 | 全局变量 |
| 🗑️ | `_rollcall_confirmed` | L88 | 全局变量 |
| 🗑️ | `_cmd_rollcall_next` 的文本点名消息 | L847 | `"请回复「到」开始"` → 移除（ACK 驱动代替） |

### A-6: `_cmd_rollcall_next()` 改造

当前（L823-866）：发送文本点名消息 + 期待文本「到」回复。

新行为：调用 `_broadcast_active_channel(ws_id)`（已带 ACK 等待），不再发送独立的文本点名消息。

```python
async def _cmd_rollcall_next(sender_id: str, params: dict) -> str:
    """点名下一角色 — 使用 ACK 确认制代替文本「到」。
    
    不再发送「请回复到开始」文本消息。
    改为通过 _broadcast_active_channel(ws_id) 启动 ACK 等待。
    """
    # ... 现有角色匹配逻辑保留（L827-846）...
    
    # 发送 ACK 驱动的频道切换
    ack_result = await _broadcast_active_channel(ws_id)
    
    # 返回包含 ACK 计数结果
    return f"✅ 已点名 {names_str}（{ack_result['online_count']} 人在线），等待 ACK 确认..."
```

### A-7: `!rollcall` 命令（文本 `📋` 触发）改造

当前 L2599-2625：发送在线列表 → 广播 MSG_SET_ACTIVE_CHANNEL → 启动 3min 超时。

新行为：发送在线列表 → 广播 MSG_SET_ACTIVE_CHANNEL（带 ACK） → 启动 30s 超时。等待 ACK 计数，管理员看到 `✅ N/M 已确认`。

代码位置：L2594-2625 的 `if ... content.startswith("📋"):` 分支。
- 删除 `_rollcall_active[target_ch] = True`、`_rollcall_confirmed[target_ch] = set()`、`_rollcall_timers` 三行
- 直接调 `_broadcast_active_channel(target_ch)`（内部已启动 ACK 等待）

### B-1: `_cmd_step_complete()` 集成 ACK 等待

当前（L1393-1551）：标记 task 完成 → rollcall next → task create → 返回。

新行为——在 `_cmd_step_create` 之后插入 ACK 等待：

```python
# 创建下一步的 Task（L1513-1518，现有）
next_task_result = await _cmd_task_create(sender_id, {
    "context": round_name,
    "name": next_step,
    "role": next_role,
})

# ★ R53 B-1: 等待 MSG_TASK_ACK before returning
# task 当前状态为 "submitted"
# 不阻塞整个 event loop — 在后台等 ACK
# 返回值中包含"等待确认"标记

# 更新管线状态（L1521，现有）
_update_pipeline_step(round_name, next_step)
```

**关键设计：** 不阻塞 `_cmd_step_complete` 的返回（asyncio 中 await 一个 30s 的 asyncio.Event 会阻塞这条连接的全部其他消息处理）。改为：

1. 在 `_channel_ack_state` 中注册一个 `"pending_task_ack": set()` 映射
2. `_cmd_step_complete` 返回时带 `⏳ 等待 {role} ACK 确认任务...`
3. MSG_TASK_ACK 到达后，通过 `_on_task_ack(task_id)` 回调触发 `_notify_task_ack_complete()`
4. `_notify_task_ack_complete()` 将 task 状态从 `submitted` 推进到 `working`

### B-2: MSG_TASK_ACK 处理增强

当前处理（L3408-3444）：接收 MSG_TASK_ACK → 取消 timer → 通知 admin → 不改变 task 状态。

增强行为：

```python
elif msg_type == p.MSG_TASK_ACK and agent_id:
    task_id = msg.get(p.FIELD_TASK_ID, "")
    status = msg.get(p.FIELD_TASK_STATUS, "accepted")
    reason = msg.get(p.FIELD_TASK_REASON, "")
    
    timer = _task_ack_timers.pop(task_id, None)
    if timer:
        timer.cancel()
    
    if status == "accepted":
        # ★ NEW: 将 task 从 submitted → working
        task = ts.get_task(task_id, config.DATA_DIR)
        if task and task.get("state") == p.TaskState.SUBMITTED.value:
            ts.update_task(task_id, state=p.TaskState.WORKING.value, data_dir=config.DATA_DIR)
        # ... 现有 admin 通知逻辑保留 ...
```

### B-3: `_task_ack_timeout()` 增强

当前（L2810-2823）：30s 超时 → 通知 admin。

增强：超时后在 `_admin` 频道写升级通知：

```python
async def _task_ack_timeout(admin_ws, task_id: str, target_name: str, round_name: str = "", next_step: str = "") -> None:
    await asyncio.sleep(30)
    _task_ack_timers.pop(task_id, None)
    
    # 原有 admin 通知
    try:
        await _send(admin_ws, {
            "type": "delivery_status",
            "task_id": task_id,
            "status": "timeout",
            "message": f"⚠️ {target_name} 30 秒内未确认任务，建议检查",
        })
    except Exception:
        pass
    
    # ★ NEW: 写入 _admin 频道升级通知
    if round_name:
        try:
            escalation_msg = f"⚠️ {round_name} {next_step} 任务未被 {target_name} 确认（30s 超时），请通知项目负责人介入"
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=escalation_msg, ts=time.time(),
                data_dir=config.DATA_DIR, channel=p.ADMIN_CHANNEL,
            )
            write_chat_log("系统", escalation_msg, channel=p.ADMIN_CHANNEL)
        except Exception:
            pass
```

`_cmd_step_complete()` 创建 `_task_ack_timers[task_id]` 时需传入 round_name 和 next_step 给 `_task_ack_timeout`。

### B-4: `!pipeline_status` ACK 状态显示

当前（L1700-1739）：显示 task 状态：⬜ (submitted) / 🟢 (working) / ✅ (completed)。

新增 `waiting_ack` 显示状态：

```python
# 在 task_state 判断中增加
if ts_state == p.TaskState.SUBMITTED.value:
    # 检查是否有活跃的 ACK 计时器
    if task["id"] in _task_ack_timers:
        task_state = "⏳"  # waiting_ack
    else:
        task_state = "⬜"  # submitted, no pending ack
```

**注意：** 不增加新的 `TaskState` 枚举值（不修改 `shared/protocol.py` 的 TaskState 枚举）。`waiting_ack` 仅在显示层通过检查 `_task_ack_timers` 是否存在 active timer 来判断。

### C-1: `_cmd_step_complete()` 调用流重整

当前流：
```
mark current task ✅ → rollcall_next (text) → task_create (submitted) → advance pipeline
```

新流：
```
mark current task ✅ → broadcast_active_channel (ACK wait) → task_create (submitted) → 
wait MSG_TASK_ACK → task: submitted → working → advance pipeline
```

具体改动——`_cmd_step_complete()` 的 L1506-1521 段：

```python
# ★ R53 C-1: Reorder — channel ACK first, then task with ACK

# ① 广播 MSG_SET_ACTIVE_CHANNEL（带 ACK 等待）
ack_result = await _broadcast_active_channel(ws_id)

# ② 创建下一步的 Task（submitted）
next_task_result = await _cmd_task_create(sender_id, {...})

# ③ 注册 task ACK 等待（timer 由 _cmd_task_create 内部的
#    _broadcast_task_notify 中已启动）
#    无需额外操作 — _broadcast_task_notify 已经在 L3231 启动
#    _task_ack_timers[task_id] 定时器

# ④ 更新管线状态
_update_pipeline_step(round_name, next_step)
```

### C-2: 移除冗余文本广播

验证以下位置无残留文本点名消息：

| 位置 | 行号 | 检查项 |
|:-----|:----:|:-------|
| `_auto_rollcall_notify()` | L337-341 | `📋 点名报道 请回复「到」` → 已移除（A-5） |
| `_cmd_rollcall_next()` | L847 | `请回复「到」开始` → 改为 ACK 消息 |
| `_cmd_rollcall_role()` | L798 | `请回复「到」确认在线` → 改为 ACK 消息 |
| `_broadcast_active_channel()` | L2645 | `回复「已切」确认` → 改为 ACK 协议 |

---

## Part B — 向后兼容分析

| 已有命令/机制 | 影响 | 说明 |
|:-------------|:----:|:-----|
| `!pipeline_start` | ✅ 无影响 | 已调 `_broadcast_active_channel()`（L1300），该函数升级为 ACK 版后自动兼容 |
| `!step_complete` | ✅ 返回值变化 | 返回 `⏳ 等待 ACK` 而非 `✅ 已点名`。管线推进逻辑不变 |
| `!step_handoff` | ✅ 无影响 | 同调 `_broadcast_active_channel()`（L1667），自动兼容 |
| `!rollcall`（📋 文本触发） | ✅ 行为升级 | 仍发在线列表 + MSG_SET_ACTIVE_CHANNEL，改为 30s ACK 代替 3min 文本 |
| `!pipeline_status` | ✅ 增强 | 新增 ⏳ waiting_ack 显示，旧状态不变 |
| `!task_create` | ⚠️ 返回值不变 | task 仍创建为 submitted。仅 `_cmd_step_complete` 中创建的 task 会等 ACK |
| `_cmd_rollcall_next()` | ✅ 行为升级 | 参数不变，内部改为 ACK 等待 |
| `_cmd_rollcall_role()` | ✅ 行为升级 | 参数不变，消息文本改为 ACK 协议 |
| `MSG_TASK_ACK` 旧 bot | ✅ 过渡兼容 | 不回复 ACK → 30s 超时 → fallback 通过 + 通知 admin |
| `MSG_SET_ACTIVE_CHANNEL` 旧 bot | ✅ 过渡兼容 | 不回复 MSG_ACK → 30s 超时 → fallback 通过 |
| 旧 `_rollcall_*` 全局变量 | ⚠️ 需重写引用 | 所有引用 `_rollcall_active`/`_rollcall_timers`/`_rollcall_confirmed` 的地方改为 `_channel_ack_state` |

### 旧 bot 不回复 ACK 场景

```
R53 服务端 → MSG_SET_ACTIVE_CHANNEL（含 ack_task_id）
         │   bot(A) 回复 MSG_ACK ✓ → 立即确认
         │   bot(B) 无响应 → 30s 超时 → fallback: 通知 admin
         │                     → 管线推进（不阻塞）
```

旧 bot 不需要客户端更新——超时 fallback 保证管线不卡死。新 bot 可通过回复 ACK 获得即时确认。

### 需要 grep 确认的引用

```bash
grep -rn '_rollcall_active\|_rollcall_timers\|_rollcall_confirmed' server/ --include='*.py'
```

预期命中：
- 变量定义（L86-88）：删除
- `_auto_rollcall_notify`（L353）：函数整体删除
- `_rollcall_timeout`（L2871-2905）：函数整体删除
- `_cmd_pipeline_start` 间接引用无（通过 `_broadcast_active_channel` 调用）
- `!rollcall` 文本 `📋` handler（L2616-2617，L2619-2623）：改为 `_channel_ack_state`
- 文本「已切」确认（L2363-2364）：删除

---

## Part C — 验收标准映射

### 需求 A — ACK 点名

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------:|
| A-1 | `!pipeline_start` 全员点名后，在线 bot 收到 MSG_SET_ACTIVE_CHANNEL 并回复 ACK，系统标记「✅ 已确认」 | 直连 WS 触发管线，观察 bot 是否回复 MSG_ACK（含 ack_task_id），系统是否在 `_channel_ack_state` 中确认 | P0 |
| A-2 | 收到 ACK 后 bot 的活跃频道已持久化到新工作室 | 确认 `persistence.set_agent_channel` 仍被 `_broadcast_active_channel()` 调用（L2651） | P0 |
| A-3 | 超时（30s）未 ACK 的 bot 被标记为「⚠️ 未响应」，系统通知项目管理 | 观察 30s 后 `_admin` 频道的超时通知 | P0 |
| A-4 | 原有的文本「到 / 已切」确认和「3 分钟超时」机制完全移除 | grep 确认 `_rollcall_active` 等变量 + `content == "已切"` 分支 + `_rollcall_timeout` 函数已删除 | P1 |
| A-5 | `!rollcall` 全员点名命令改用 ACK 确认，管理员看到 ACK 计数 | 执行 `!rollcall`，观察在线列表 + MSG_SET_ACTIVE_CHANNEL 发送时附带 ack_task_id | P0 |

### 需求 B — ACK 派活

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------:|
| B-1 | `!step_complete` 调用后，创建 task (submitted) 并等待 bot MSG_TASK_ACK | 观察 task 创建后 `_task_ack_timers` 中注册了 timer，返回消息含「⏳ 等待确认」 | P0 |
| B-2 | bot 回复 MSG_TASK_ACK + status="accepted" 后，task 标记为 working | `ts.get_task()` 查看 task state；`!pipeline_status` 显示 🟢 working | P0 |
| B-3 | 30s 超时未收到 ACK，`_admin` 频道显示「⚠️ 任务未被确认」升级通知 | 等待 30s，观察 `_admin` 频道消息 | P1 |
| B-4 | bot 离线时任务进入离线队列，上线后补发并走 ACK | 下线 bot 重连后观察 `_offline_push_queue` 触发 `_broadcast_task_notify` | P1 |
| B-5 | `!pipeline_status` 显示 ACK 状态（显示 ⏳ 等待 ACK / 🟢 working） | 执行 `!pipeline_status` 查看 task 状态列 | P0 |

### 需求 C — 合并分配

| # | 验收标准 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:------:|
| C-1 | 一次 `!step_complete` 调用完成：切频道 ACK + 创建 task ACK，中间无需人工干预 | 触发完整管线 Step，观察 `_broadcast_active_channel` → `_cmd_task_create` → 等待 ACK 自动流转 | P0 |
| C-2 | 原有文本「📋 点名报到」消息不再发送 | 观察工作室频道，无该消息 | P1 |
| C-3 | 保留 `!rollcall` 全员点名命令，规则同需求 A-5 | 执行 `!rollcall` 验证 ACK 计数 | P1 |

---

## Part D — 协议常量确认

### `shared/protocol.py` 检查

```python
# MSG_ACK = "ack"  — 已定义（L21）✅
# FIELD_TASK_ID = "task_id"  — 已定义（L103）✅
# FIELD_TASK_STATUS = "status"  — 已定义（L98）✅ 值: "accepted" | "rejected"
```

**本轮需要在 protocol.py 中增加的：**

| 常量名 | 值 | 用途 |
|:-------|:---|:-----|
| `MSG_ACK_SWITCHED` | `"switched"` | ACK 状态值：频道切换完成 |
| `MSG_ACK_FAILED` | `"failed"` | ACK 状态值：切换失败（日志用） |

或者不使用新常量，直接使用字符串 `"switched"` 和 `"failed"`（现有模式 `FIELD_TASK_STATUS` 的值 `"accepted"`/`"rejected"` 已经是字符串字面量）。推荐直接字符串，与现有模式一致。

---

## 附录

### 代码变更汇总

| 方向 | 文件 | 改动 | 估计行数 |
|:----:|:-----|:-----|:--------:|
| A | `server/handler.py` | 新增 `_channel_ack_state` 全局变量 (~3行) | +3 |
| A | `server/handler.py` | `_broadcast_active_channel()` 增强：增加 MSG_ACK 等待、ack_task_id 生成、定时器启动 | ~+30 |
| A | `server/handler.py` | 新增 `_channel_ack_timeout()` 函数 | ~+25 |
| A | `server/handler.py` | `handle_broadcast()` 新增 MSG_ACK 处理分支 | ~+25 |
| A | `server/handler.py` | 删除 `_auto_rollcall_notify()` | −35 |
| A | `server/handler.py` | 删除 `_rollcall_timeout()` | −35 |
| A | `server/handler.py` | 删除 R37 文本「已切」确认分支 | −18 |
| A | `server/handler.py` | 删除 `_rollcall_active`/`_rollcall_timers`/`_rollcall_confirmed` | −3 |
| A | `server/handler.py` | `_cmd_rollcall_next()` 改造：去除文本点名，调用 ACK | ~+10 |
| A | `server/handler.py` | `!rollcall` (`📋` handler) 改用 ACK | ~+5 |
| A | `server/handler.py` | `_cmd_rollcall_role()` 文本点名 → ACK 协议 | ~+5 |
| B | `server/handler.py` | `_cmd_step_complete()` 集成 ACK 等待 | ~+15 |
| B | `server/handler.py` | MSG_TASK_ACK 处理增强（task state → working） | ~+5 |
| B | `server/handler.py` | `_task_ack_timeout()` 增强（_admin 频道升级通知） | ~+15 |
| B | `server/handler.py` | `!pipeline_status` ACK 状态显示 | ~+8 |
| C | `server/handler.py` | `_cmd_step_complete()` 调用流重整 | ~+5 |
| C | `server/handler.py` | 移除冗余文本广播（`_cmd_rollcall_role`） | ~-5 |
| - | `shared/protocol.py` | 无改动（已有 MSG_ACK、FIELD_TASK_ID、FIELD_TASK_STATUS） | 0 |

**总计：** 估计 +146 / −96 行（净增 ~50 行）

### 双入口同步检查

| 改动点 | handler.py | __main__.py | 说明 |
|:-------|:----------:|:-----------:|:-----|
| `_broadcast_active_channel()` | ✅ L2631 | N/A | 共享函数，__main__.py 未调用 |
| `_channel_ack_timeout()` | ✅ 新建 | N/A | 共享函数 |
| MSG_ACK 处理 | ✅ L2360 入口分支 | ⚠️ 需要确认 | 检查 `__main__.py::ws_handler()` 是否有 `msg_type == MSG_ACK` 分支 |
| MSG_TASK_ACK 处理增强 | ✅ L3408 | ⚠️ 需要确认 | 检查 `ws_handler()` 是否也有 MSG_TASK_ACK 分支 |
| `_auto_rollcall_notify()` 删除 | ✅ N/A 删除 | N/A | — |
| `_rollcall_timeout()` 删除 | ✅ N/A 删除 | N/A | — |
| `_cmd_step_complete()` | ✅ L1393 | N/A | `_ADMIN_COMMANDS` 注册，无双入口 |

**需要验证 `__main__.py` 中的二分发：**

```bash
grep -n 'MSG_ACK\|MSG_TASK_ACK\|_broadcast_active_channel\|rollcall' server/__main__.py
```

如果 `ws_handler()` 中没有 MSG_ACK 分支，则无需同步（旧 bot 的 MSG_ACK 由 handler.py 处理）。如果 `ws_handler()` 有自己的 dispatch 循环接收 MSG_ACK，则需要同步。

### 向后的 `_rollcall_*` → `_channel_ack_state` 迁移

| 旧变量 | 新结构 | 访问方式 |
|:-------|:-------|:---------|
| `_rollcall_active[ws_id]` | `ws_id in _channel_ack_state` | key existence |
| `_rollcall_confirmed[ws_id]` | `_channel_ack_state[ws_id]["acked_members"].keys()` | set of acked |
| `_rollcall_timers[ws_id]` | `_channel_ack_state[ws_id]["timer"]` | Task or None |

其他引用 `_rollcall_*` 的位置（需 grep）：

```bash
grep -rn '_rollcall_active\|_rollcall_timers\|_rollcall_confirmed' server/
```

### 注意事项

1. **`_task_ack_timers` 的 key 是 task_id，不是 agent_id。** 一个 bot 在同一时间只能有一个活跃 task。多个 bot 的 ACK 互不冲突。
2. **R37 的 `_rollcall_*` 删除后，`_rollcall_timeout` 中的 `_rollcall_active` 检查（L2875）也随之消失。** 全量删除前确认无其他引用。
3. **`_broadcast_active_channel` 的返回类型从 `int` 变为 `dict`。** 调用方 `_cmd_pipeline_start`（L1300）和 `_cmd_step_handoff`（L1667）以及 `!rollcall` 📋 handler（L2625）都接受 `await` 返回值但不解构——返回类型变更不影响已有调用方，但返回的 `online_count` 信息需要通过新返回值提供。
4. **过渡兼容期日志分级：** bot 不回复 ACK → logger.warning（预期行为，不 panic）。bot 回复 ACK → logger.info。ACK 超时 → logger.warning + _admin 频道通知。

---
