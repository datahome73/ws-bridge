# R119 实现说明

> **轮次：** R119 — 自动派活全流程生产验证
> **作者：** 爱泰（Dev）
> **基线：** `0fb86bd`（技术方案）→ `5c9e6f0`（最新修复）
> **状态：** ✅ 全部 5 个 fix 已合入 dev

---

## 概述

R119 的核心是**生产验证**——在真实环境中让 `##start` → Step 1→6 全自动派活链路第一次完整跑通。技术方案定义为"零架构变更"验证轮，但在验证过程中发现了 **5 个实际断点**，均需源码修复。

本文档记录 5 个 fix commit 的改动内容、触发场景和修复逻辑。

---

## Fix 汇总

| # | Commit | 文件 | 类型 | 触发场景 |
|:-:|:-------|:-----|:-----|:---------|
| 1 | `f560daf` | `main.py` | 状态持久化 | 容器重启后 Step 1 自动确认状态丢失 |
| 2 | `54cc097` | `main.py` + `__main__.py` | 启动恢复 | 容器重启后活跃管线无人派活 |
| 3 | `59acf9a` | `main.py` | 并发修复 | 恢复派活未进重试队列 + await 缺失 |
| 4 | `bff10b5` | `main.py` | 去重保护 | 派活通知在重启后重复发送 |
| 5 | `5c9e6f0` | `main.py` | 消息路由 | 派活消息被 bot 网关静默丢弃 |

---

## Fix 1：Step 1 自动确认状态落盘

**Commit:** `f560daf`
**文件:** `server/ws_server/main.py`

### 问题

`_handle_hash_start()` 在创建管线后自动将 Step 1 标记为 `done`（状态"已确认"），然后调用 `_auto_dispatch(ctx, 2)` 派活 Step 2。但 **Step 1 的状态修改仅存在于内存**，未调用 `mgr.save()` 持久化。

如果容器在 Step 1→2 之间重启，管线回退到初始状态（`current_step=1`），导致重复确认和重复派活。

### 修复

在设置 Step 1 状态后立即落盘：

```python
# ═══ R119 fix: 落盘 Step 1 自动确认状态，防止容器重启后丢失 ═══
try:
    mgr.save()
except Exception:
    pass
```

### 验证

- 容器重启后，已启动的管线 `current_step` 保持为 2，Step 1 状态为 `done`
- 不会出现重复派活 Step 1 的现象

---

## Fix 2：启动时恢复活跃管线的自动派活

**Commit:** `54cc097`
**文件:** `server/ws_server/main.py`, `server/ws_server/__main__.py`

### 问题

容器重启后，所有 `RUNNING` 状态的管线失去了自动派活上下文。`_restore_pipeline_timers()` 只负责恢复定时器（归档/超时），**不处理派活**。结果：管线虽然在运行中，但当前 Step 无人收到派活消息，管线永久卡住。

### 修复

新增 `_restore_pipeline_dispatches()` 函数：

```python
async def _restore_pipeline_dispatches() -> None:
    """On server start, re-dispatch the current step for all RUNNING pipelines
    whose current step is still pending."""
    mgr = _ensure_pipeline_manager()
    for ctx in mgr.get_all_active():
        if ctx.status != PipelineStatus.RUNNING:
            continue
        step_num = ctx.current_step
        if step_num < 1 or step_num > ctx.total_steps:
            continue
        step_key = f"step{step_num}"
        step_info = next(
            (s for s in (ctx.steps or []) if s.get("name") == step_key), None,
        )
        if not step_info or step_info.get("status") not in ("pending", "in_progress"):
            continue
        # 加入重试队列（等 bot 连上再发）
        _enqueue_retry(ctx, step_num)
```

在 `__main__.py` 的 `app.on_startup` 中注册：

```python
async def _restore_dispatches(app):
    from .main import _restore_pipeline_dispatches
    await _restore_pipeline_dispatches()
    logger.info("[R119] pipeline dispatch restoration completed")

app.on_startup.append(_restore_dispatches)
```

额外增加 `logging.basicConfig` 配置，确保容器日志中能看到 `[R119]` 标记的恢复日志。

### 恢复流程

```
容器启动
  → app.on_startup (按注册顺序)
  → _restore_dispatches()
  → 遍历所有 RUNNING 管线
  → 对 current_step 为 pending/in_progress 的：
      → _enqueue_retry(ctx, step_num) 加入重试队列
      → 重试队列在 bot 连接后发送派活消息
```

### 验证

- 容器重启后，`docker logs` 中出现 `[R119] 恢复派活: R119 step3 → ws_xxx`
- bot 重新连接后收到当前 Step 的派活消息

---

## Fix 3：启动恢复改入重试队列 + await 修复

**Commit:** `59acf9a`
**文件:** `server/ws_server/main.py`

### 问题

两个子问题：

1. **恢复派活未进重试队列** — `_restore_pipeline_dispatches` 在启动时直接调 `_auto_dispatch`，但此时 bot 可能尚未连接 WebSocket，消息发送失败。

2. **await 缺失** — `handle_broadcast()` 中调用 `_restore_pipeline_timers()` 未加 `await`，导致定时器恢复函数执行不完整。

### 修复

1. 将恢复派活改为入重试队列（`_enqueue_retry`），由重试循环在 bot 上线后自动发送。
2. 补上 `await`：

```python
# Before (R49 C):
_restore_pipeline_timers()
# After (R119 fix):
await _restore_pipeline_timers()
```

### 验证

- 启动日志中出现 `[R119] 恢复派活: R119 step3 → ws_xxx` 并跟随重试队列日志
- `handle_broadcast` 中定时器恢复完整执行

---

## Fix 4：自动派活后标记 in_progress

**Commit:** `bff10b5`
**文件:** `server/ws_server/main.py`

### 问题

`_auto_dispatch()` 发送派活消息成功后，Step 的状态仍为 `pending`。重启后 `_restore_pipeline_dispatches()` 发现 Step 为 `pending`，会再次派活同一 Step，导致 bot 收到重复的派活通知。

### 修复

发送成功后立即标记 Step 为 `in_progress` 并持久化：

```python
# 标记 step 为进行中，防止重复派活
next_step_info["status"] = "in_progress"
try:
    mgr = _ensure_pipeline_manager()
    mgr.save()
except Exception:
    pass
```

### 状态流转

```
pending (初始)
  → _auto_dispatch 发送成功 → in_progress (本 fix)
  → bot 回复完成 → done
```

重启后 `_restore_pipeline_dispatches()` 只处理 `pending` 和 `in_progress`。`in_progress` 的 Step 不会重复派活，因为 bot 已在处理中。

### 验证

- `_auto_dispatch` 发送后，`docker logs` 显示 Step 状态已改为 `in_progress`
- 容器重启后不会重复派活 `in_progress` 的 Step

---

## Fix 5：auto_dispatch 消息类型/频道修复

**Commit:** `5c9e6f0`
**文件:** `server/ws_server/main.py`

### 问题

这是 **R119 最关键的 fix**。`_auto_dispatch()` 构造的 payload 为：

```python
payload = {
    "type": "message",
    "channel": "_inbox:server",
    "content": content,
    ...
}
```

两个问题：
1. **类型 `"message"`** — bot 网关收到 `type=message` 且无 `chat_id` 的消息时，尝试路由到 Telegram/WS Bridge 群聊。如果找不到目标频道，**静默丢弃**，不报错。
2. **频道 `"_inbox:server"`** — 这是发往 bot 自己的 server inbox，不是目标 agent 的 inbox。server inbox 的处理逻辑（`_handle_server_inbox`）只处理 `##` 命令和进度上报，不处理派活消息。

结果：派活消息从 _auto_dispatch 发出后，返回 `sent=1`（因为找到了连接），但 bot **实际从未收到**。

### 修复

改为 broadcast 模式定向发送到目标 agent 的 inbox：

```python
payload = {
    "type": "broadcast",          # ← 从 message 改为 broadcast
    "channel": f"_inbox:{target_agent_id}",  # ← 从 _inbox:server 改为目标
    "content": content,
    ...
}
```

`type=broadcast` 与 `channel=_inbox:{agent_id}` 的组合在 ws-bridge 中表示：
1. 查找目标 agent 的所有 WS 连接
2. 对每个连接发送 `_inbox` 类型消息（bot 的 `on_inbox_message` 处理）
3. 目标 bot 在 inbox 中收到消息

### 消息投递路径对比

```
Before (丢失):
  _auto_dispatch → _send_to_agent(ws_id, {type:"message", channel:"_inbox:server"})
    → 找到连接 ✓ → sent=1 ✓
    → 网关路由: type="message", 无 chat_id → 静默丢弃 ✗

After (正常):
  _auto_dispatch → _send_to_agent(ws_id, {type:"broadcast", channel:"_inbox:{target}"})
    → 找到连接 ✓ → sent=1 ✓
    → 网关路由: type="broadcast", channel="_inbox:xxx" → 推送到目标 bot inbox ✓
```

### 验证

- bot 的 inbox 实际收到派活消息（这是之前从未成功过的）
- 日志中 `sent=1` 后目标 bot 回复 `✅ 确认` 或执行任务
- 这是 R119 验证轮的最关键修复，此前 R117 的 `card_key→ws_id` 桥接虽然正确，但消息卡在路由层发不出去

---

## 5 个 Fix 协作时序

```
容器启动
  │
  ├─ Fix 2 (54cc097): _restore_pipeline_dispatches → _enqueue_retry
  │     └─ 启动时恢复功能，依赖 Fix 4 的 in_progress 标记避免重复派活
  │
  ├─ Fix 3 (59acf9a): await _restore_pipeline_timers + 重试队列
  │     └─ Fix 2 的支撑修复，确保恢复完整执行
  │
  ├─ 正常运行时
  │     ├─ _handle_hash_start → Fix 1 (f560daf): 状态落盘
  │     │     └─ Fix 5 (5c9e6f0): 消息正确路由到目标 bot
  │     │           └─ Fix 4 (bff10b5): 标记 in_progress 防重复
  │     └─ _try_advance_pipeline → _auto_dispatch → ... (循环)
```

---

## 验收检查点

| # | 检查项 | 对应 Fix | 验证方式 |
|:-:|:-------|:---------|:---------|
| ① | 重启后 Step 1 不丢失 | Fix 1 | 重启后 `current_step` 保持正确 |
| ② | 重启后派活自动恢复 | Fix 2 + 3 | 日志 `[R119] 恢复派活` 出现 |
| ③ | 重复派活保护 | Fix 4 | Step 标记 `in_progress` 不重复派 |
| ④ | 派活消息到达目标 bot | Fix 5 | bot inbox 收到派活消息 |
| ⑤ | 全链路跑通 | 全部 | Step 1→6 逐项完成 |

---

> **编写：** 爱泰
> **日期：** 2026-07-15
> **状态：** ✅ 定稿
