# R119 实现说明

> **作者：** 爱泰（Dev）
> **日期：** 2026-07-15
> **对应需求：** `R119-product-requirements.md`
> **对应的 dev 提交：** `f560daf` ~ `5c9e6f0`

---

## 概述

R119 是**生产验证轮**——在真实环境中让 `##start` → Step 1→6 全自动派活链路第一次完整跑通。R119 本身不引入新功能，而是在跑全流程过程中**发现 bug 即源码修复**，不手动绕行。

共 5 个修复 commit，改动集中在 `server/ws_server/main.py` 和 `server/ws_server/__main__.py`（+36/-12 行）。

---

## 修复 1：Step 1 自动确认状态落盘

**Commit:** `f560daf`  
**文件:** `server/ws_server/main.py`  
**变动:** +5 行

### 问题

`##start##R{N}` 创建管线后，Step 1 自动标记为 `done` 并推进到 Step 2。但这一状态变更仅存在于内存中的 `PipelineContext` 对象，未调用 `mgr.save()` 持久化。如果容器在 Step 2 执行前重启，管线回退到 `current_step=1`，恢复后重复派活 Step 2。

### 修复

在 `_handle_hash_start()` 的 Step 1 确认逻辑后增加 `mgr.save()`：

```python
# ═══ R119 fix: 落盘 Step 1 自动确认状态，防止容器重启后丢失 ═══
try:
    mgr.save()
except Exception:
    pass
```

---

## 修复 2：启动时恢复活跃管线的自动派活

**Commit:** `54cc097`  
**文件:** `server/ws_server/main.py` +31 行, `server/ws_server/__main__.py` +8 行  
**变动:** +39 行

### 问题

容器重启后，原自动派活消息随 WebSocket 连接断开丢失。如果重启前某 step 已推进但派活消息未送达，该 step 会永久卡在 `pending`。

### 修复

新增 `_restore_pipeline_dispatches()` 函数，在 `__main__.py` 的 `on_startup` 中调用：

```python
async def _restore_pipeline_dispatches() -> None:
    """On server start, re-dispatch the current step for all RUNNING pipelines
    whose current step is still pending."""
    try:
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
            if not step_info or step_info.get("status") != "pending":
                continue
            # ... re-dispatch
    except Exception:
        pass
```

在 `__main__.py` 注册为 `on_startup` 回调：

```python
app.on_startup.append(_restore_dispatches)
```

#### 设计考量

- 仅处理 `RUNNING` 状态管线，不干扰已完成的管线
- 仅处理 `pending` step，不重复派活已在执行中的 step
- 顶层 `try/except` 确保启动过程不被单个恢复异常阻断

---

## 修复 3：启动恢复派活改入重试队列 + await 修复

**Commit:** `59acf9a`  
**文件:** `server/ws_server/main.py`  
**变动:** 2 行修改

### 问题 3a：启动时派活竞争条件

`_restore_pipeline_dispatches()` 在 `on_startup` 阶段调用 `asyncio.ensure_future(_auto_dispatch(...))`。但此时 bot 的 WebSocket 连接尚未建立（`on_startup` 早于 `on_connection`），`_send_to_agent()` 立即返回 `sent=0`，派活失败。且直接派活不走重试队列，失败后不会重试。

### 修复 3a

将直接派活改为入重试队列：

```python
# Before:
asyncio.ensure_future(_auto_dispatch(ctx, step_num))

# After:
_enqueue_retry(ctx, step_num)
```

重试队列每 60s 重试一次（最多 5 次），等 bot 连上后自然派活成功。

### 问题 3b：协程未 await

`handle_broadcast()` 第 1347 行调用 `_restore_pipeline_timers()` 时缺少 `await`，这是个 `async` 函数但从未被等待，实质上静默失效。

### 修复 3b

```python
# Before:
_restore_pipeline_timers()

# After:
await _restore_pipeline_timers()
```

---

## 修复 4：自动派活成功后标记 step in_progress

**Commit:** `bff10b5`  
**文件:** `server/ws_server/main.py`  
**变动:** +7 行

### 问题

`_auto_dispatch()` 派活成功后未将 step 状态从 `pending` 更新为 `in_progress`。当 `_restore_pipeline_dispatches()` 在容器重启后遍历时，仍看到 `pending` 状态，再次派活同一 step，导致重复派活刷屏。

### 修复

在派活成功（`sent > 0`）后，立即标记 step 为 `in_progress` 并持久化：

```python
if sent > 0:
    # 标记 step 为进行中，防止重复派活
    next_step_info["status"] = "in_progress"
    try:
        mgr = _ensure_pipeline_manager()
        mgr.save()
    except Exception:
        pass
    asyncio.ensure_future(_notify_pm(ctx, step_num, "dispatched"))
```

配合修复 5 中 `_restore_pipeline_dispatches` 也处理 `in_progress` 状态，确保重启后能恢复卡在 `in_progress` 的 step。

---

## 修复 5：auto_dispatch 消息类型/频道修复

**Commit:** `5c9e6f0`  
**文件:** `server/ws_server/main.py` + `server/ws_server/__main__.py`  
**变动:** 2 文件，+12/-4 行

### 根因（最关键的 bug）

`_auto_dispatch()` 构造的 payload 使用 `type: "message"` + `channel: "_inbox:server"`，但 bot 的 gateway-plugin 只处理 `type: "broadcast"` 的消息，且期望 channel 是 `_inbox:<bot_id>` 格式。

断链流程：

```
_auto_dispatch → payload {type: "message", channel: "_inbox:server"}
    ↓
_send_to_agent → WebSocket send → sent=1 ✅（TCP 层投递成功）
    ↓ 但 bot 侧：
_handle_ws_message → msg_type == "message" ≠ "broadcast" → ❌ 静默丢弃
    ↓
_auto_dispatch 看到 sent=1 → step 标记 in_progress → 重试队列清除
    ↓
管线卡死，bot 从未收到派活消息
```

### 修复

```python
# Before:
payload = {
    "type": "message",
    "channel": "_inbox:server",
    ...
}

# After:
payload = {
    "type": "broadcast",
    "channel": f"_inbox:{target_agent_id}",
    ...
}
```

**关键点：** `_send_to_agent()` 返回 `sent=1` 只表示 WebSocket 写入成功（TCP 层），不代表 bot 应用层已接收处理。bot 网关的身份验证和消息路由要到最后一步 `_handle_ws_message()` 中才按 `type` 字段分发。`type: "message"` 在 bot 端被 `handle_broadcast` → `on_message` 链路跳过，静默丢弃。

### 附带修复

在 `_restore_pipeline_dispatches()` 的条件判断中增加 `in_progress` 覆盖：

```python
# Before:
if not step_info or step_info.get("status") != "pending":
    continue

# After:
if not step_info or step_info.get("status") not in ("pending", "in_progress"):
    continue
```

确保容器重启后，因上述 bug 卡在 `in_progress` 的 step 也能被恢复。

### 其他：`__main__.py` 日志配置

增加 `logging.basicConfig(level=logging.INFO, ...)`，让 INFO 级别的日志（如 `[R119] 恢复派活: ...`）在容器 `docker logs` 中可见。

---

## 改动总览

| # | Commit | 文件 | 改动 | 行数 |
|:-:|:-------|:-----|:-----|:----:|
| 1 | `f560daf` | `main.py:3238-3242` | Step 1 自动确认后 mgr.save() | +5 |
| 2 | `54cc097` | `main.py:1250-1280`, `__main__.py:841-848` | `_restore_pipeline_dispatches` 框架 | +39 |
| 3 | `59acf9a` | `main.py:1274, 1344` | 恢复派活入重试队列 + await 修复 | +2/-2 |
| 4 | `bff10b5` | `main.py:2755-2761` | 派活成功后 mark in_progress | +7 |
| 5 | `5c9e6f0` | `main.py:1269,2727-2728`, `__main__.py:29-36` | type/channel 修复 + logging | +12/-4 |
| | **合计** | **2 文件** | **5 项修复** | **+36/-12** |

---

## 验证要点

部署后通过以下场景验证：

1. **正常派活链路：** `##start##R119` → Step 1 自动确认 ✅ → Step 2 自动派活给小开 ✅
2. **容器重启恢复：** 重启容器后，`_restore_pipeline_dispatches` 遍历所有 RUNNING 管线，`in_progress` 或 `pending` 的 step 入重试队列
3. **离线重试：** 目标 bot 不在线时，60s 后重试（最多 5 次），bot 连上后自动送达
4. **日志可见：** `docker logs` 输出 `[R119]` 和 `[INFO]` 级别日志
5. **PM 通知：** 派活成功后小谷（PM）收到通知

---

## 未解决的问题

- `_enqueue_retry()` 的重试间隔固定 60s，不可配置
- `_restore_pipeline_dispatches()` 不处理 `COMPLETED`/`FAILED`/`CANCELLED` 状态的管线（设计意图）
- `__main__.py` 的 `on_startup` 回调顺序依赖 append 顺序（`_start_retry_loop` 先行）
