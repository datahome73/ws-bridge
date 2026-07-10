# R95 技术方案 — Pipeline Stop 命令 🛑

> **版本：** v1.0
> **状态：** 📝 初稿
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-10
> **基于需求文档：** `docs/R95/R95-product-requirements.md` v2.0
> **基于工作计划：** `docs/R95/WORK_PLAN.md` v1.0
> **改动文件：** `server/handler.py`（~+50 行） · `server/auto_router.py`（~+15 行）

---

## 目录

1. [改动总览](#1-改动总览)
2. [状态机设计](#2-状态机设计)
3. [状态流转图](#3-状态流转图)
4. [🅰️ `_cmd_pipeline_stop` handler 实现](#️-cmd_pipeline_stop-handler-实现)
5. [🅱️ AutoRouter 停止信号处理](#️-autorouter-停止信号处理)
6. [🅲 `pipeline_status` 扩展](#️-pipeline_status-扩展)
7. [改动对照表](#7-改动对照表)
8. [兼容性分析](#8-兼容性分析)
9. [风险与缓解](#9-风险与缓解)
10. [验收清单](#10-验收清单)

---

## 1. 改动总览

### 1.1 改动文件

| 文件 | 改动 | 净增行 |
|:-----|:------|:------:|
| `server/handler.py` | 新增 `_cmd_pipeline_stop` + 注册命令 + `pipeline_is_stopped` 工具 + status 显示 | ~+50 |
| `server/auto_router.py` | `_handle_message` 增加 stop 信号检测 + `_stop_pipeline` 清理逻辑 | ~+15 |
| **合计** | **2 文件** | **~+65 行** |

### 1.2 改动点全景

```
server/handler.py
│
├── 模块级工具 L1561                  ← 🅰️ optional: pipeline_is_stopped()
│     def pipeline_is_stopped(round_name):
│         state = _PIPELINE_STATE.get(round_name)
│         return bool(state and state.get("active") == "stopped")
│
├── _cmd_pipeline_stop()   (🆕)     ← 🅰️ 核心 handler
│     async def _cmd_pipeline_stop(sender_id, params) -> str:
│         # ① 参数解析
│         # ② 权限校验（仅发起者可 stop）
│         # ③ 状态校验（仅 running 可 stop）
│         # ④ 设置状态 stopped
│         # ⑤ 广播通知
│         # ⑥ 返回结果
│
├── _cmd_pipeline_status() L4219     ← 🅲 显示 stopped
│     # 增加 stopped 状态显示
│
├── _ADMIN_COMMANDS L4790            ← 🅰️ 注册 pipeline_stop 命令
│     "pipeline_stop": {
│         "handler": _cmd_pipeline_stop,
│         "min_role": 3,
│         "workspace_scope": False,
│         "usage": "!pipeline_stop <R{N}>",
│     },
│
└── _cmd_pipeline_start() L2749      ← 🅰️ 记录 triggerer_id
      _set_pipeline_state(round_name, {
          "active": True,
          ...
          "triggerer_id": sender_id,   # ← 已存在
      })

server/auto_router.py
│
├── _handle_message() L194           ← 🅱️ 增加 stop 信号检测
│     if f"🛑 {round_name} 管线已停止" in content:
│         await self._on_pipeline_stop(round_name)
│
└── _on_pipeline_stop()   (🆕)      ← 🅱️ 停止管线清理
      async def _on_pipeline_stop(round_name):
          # 清理 _round_progress
          # 清理 _step_dispatch_times
          # 清理 _step_timeout_notified
```

---

## 2. 状态机设计

### 2.1 新增状态

| 状态 | 含义 | `_PIPELINE_STATE["active"]` 值 |
|:-----|:-----|:-------------------------------|
| `running` | 管线正在自动推进 | `True`（bool） |
| `stopped` | 用户主动停止 | `"stopped"`（str） |
| `idle` | 未启动 / 已清理 | 不在 `_PIPELINE_STATE` 中 |

### 2.2 当前状态检测

```python
# 现有代码（handler.py L1575）
def pipeline_is_active(round_name: str) -> bool:
    state = _PIPELINE_STATE.get(round_name)
    return bool(state and state.get("active"))
```

对于 `active="stopped"`，`bool("stopped")` 为 `True`，所以 `pipeline_is_active("R95")` 返回 `True`。这可能导致 `!pipeline_start R95` 再次启动时被拒绝（"管线已活跃"）。

**解决方案：** `pipeline_is_active` 保持不变（下位兼容），新增专门的 `pipeline_is_stopped` 和修改 `!pipeline_start` 的检查逻辑。

### 2.3 `_set_pipeline_state` 调用点（_cmd_pipeline_start）

```python
# handler.py L2749 — 已有的 start 状态
_set_pipeline_state(round_name, {
    "active": True,                     # ← bool True
    "current_step": start_step,
    "ws_id": ws_id,
    "started_at": time.time(),
    "work_plan_url": work_plan_url or None,
    "triggerer_id": sender_id,
    "mode": mode,
})
```

### 2.4 新增状态设置（_cmd_pipeline_stop）

```python
# 新建：handler.py _cmd_pipeline_stop
_PIPELINE_STATE[round_name]["active"] = "stopped"   # ← str "stopped"
_PIPELINE_STATE[round_name]["stopped_at"] = time.time()
_PIPELINE_STATE[round_name]["stopped_by"] = sender_id
```

---

## 3. 状态流转图

```
                          !pipeline_stop
                         ┌──────────────┐
                         │              │
                         ▼              │
  ┌─────────┐    !pipeline_start    ┌──────┴────┐    !pipeline_stop    ┌──────────┐
  │  idle   │ ──────────────────→   │  running  │ ──────────────────→  │ stopped  │
  │         │                       │  (active)  │                     │          │
  │(不在     │ ←─────── ────────────│ =True)     │                     │ (active  │
  │_STATE)  │   !pipeline_start     └───────────┘                     │  ="stopp │
  └─────────┘   (再次 start)                                          │  ed")    │
                                                                      └──────────┘
        │                           │                                      │
        │                           │  step 完成自动                      │
        │                           │  ───────────                        │ 手工 inbox
        │                           ▼   6 step 闭环                      │ PM 派活续跑
        │                     ┌──────────┐                                │
        │                     │ success  │ (active 被清除)                ▼
        │                     └──────────┘                       继续自动推进直到闭环
        │
        └───── !pipeline_stop ────→ ❌ 拒绝 "不在运行状态"
        └───── 重复 stop ─────────→ ✅ 幂等 "已停止（无需操作）"
```

### 3.1 状态约束

| 当前状态 | 允许 `!pipeline_stop` | 允许 `!pipeline_start` |
|:---------|:---------------------:|:----------------------:|
| idle（不存在） | ❌ 拒绝 | ✅ 正常启动 |
| running | ✅ 执行 stop | ❌ 拒绝（已活跃） |
| stopped | ✅ 幂等返回 | ❌ 拒绝（已存在） |
| success（active 清除） | ❌ 拒绝 | ✅ 可重启 |

---

## 4. 🅰️ `_cmd_pipeline_stop` handler 实现

### 4.1 完整伪代码

```python
async def _cmd_pipeline_stop(sender_id: str, params: dict) -> str:
    """R95: 停止自动推进的管线。

    用法：!pipeline_stop <R{N}>
    权限：仅发起者（!pipeline_start 的 triggerer）
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!pipeline_stop <R{N}>"

    round_name = positional[0].upper()

    # ── ① 管线是否存在 ──
    state = _PIPELINE_STATE.get(round_name)
    if not state:
        return f"❌ Pipeline {round_name} 不存在，请先执行 !pipeline_start {round_name}"

    # ── ② 状态校验：仅 running 可 stop ──
    current_active = state.get("active")
    if current_active == "stopped":
        return f"✅ Pipeline {round_name} 已停止（无需操作）"
    if not current_active:
        return f"❌ Pipeline {round_name} 不在运行状态（active=False）"
    if current_active is not True:
        return f"❌ Pipeline {round_name} 不在运行状态（active={current_active!r}）"

    # ── ③ 权限校验：仅发起者可 stop ──
    triggerer = state.get("triggerer_id", "")
    if triggerer and sender_id != triggerer:
        return f"❌ 只有发起者可以 stop 此管线"
    # 如果 triggerer_id 未记录（旧版兼容），allow admin fallback
    if not triggerer:
        # 无发起者信息时，谁都可以 stop（旧版管线）
        pass

    # ── ④ 设置 stopped 状态 ──
    _PIPELINE_STATE[round_name].update({
        "active": "stopped",
        "stopped_at": time.time(),
        "stopped_by": sender_id,
    })

    # ── ⑤ 广播通知 _admin（让 AutoRouter 也收到） ──
    try:
        await _broadcast_to_channel(p.ADMIN_CHANNEL, {
            "type": "broadcast",
            "channel": p.ADMIN_CHANNEL,
            "from_name": "系统",
            "from_agent": SYSTEM_AGENT_ID,
            "content": f"🛑 {round_name} 管线已停止（发起者: {sender_id[:12]}）",
            "ts": time.time(),
        })
    except Exception as e:
        logger.warning("R95: _admin 广播失败: %s", e)

    logger.info("R95: Pipeline %s stopped by %s", round_name, sender_id[:12])

    return (
        f"🛑 Pipeline {round_name} 已停止\n"
        f"  发起者: {sender_id[:12]}\n"
        f"  当前 step: {state.get('current_step', '?')}\n"
        f"  AutoRouter 已停止推进，正在执行的 bot 不受影响"
    )
```

### 4.2 命令注册

```python
# handler.py _ADMIN_COMMANDS 字典（L4790 附近，紧邻 pipeline_start）
"pipeline_stop": {
    "handler": _cmd_pipeline_stop,
    "min_role": 3,
    "workspace_scope": False,
    "usage": "!pipeline_stop <R{N}>",
},
```

### 4.3 权限校验细节

| 场景 | `triggerer_id` 状态 | 行为 |
|:-----|:-------------------|:------|
| 发起者本人执行 stop | 匹配 | ✅ 允许 |
| 非发起者执行 stop | 不匹配 | ❌ 拒绝 |
| `triggerer_id` 为空（旧版管线） | 无校验 | ✅ 允许（降级） |
| 重复 stop | 状态已为 `stopped` | ✅ 幂等 |
| 对 idle（不存在）管线 stop | 无 state | ❌ 拒绝 |

### 4.4 幂等处理

```python
# 重复 stop：active == "stopped" → 直接返回幂等提示
if current_active == "stopped":
    return f"✅ Pipeline {round_name} 已停止（无需操作）"
```

### 4.5 对 idle/failed/success 管线 stop 的处理

| 管线状态 | `active` 值 | stop 行为 |
|:---------|:-----------|:----------|
| idle（未启动） | 不在 `_PIPELINE_STATE` 中 | ❌ 拒绝 `Pipeline R<N> 不存在` |
| running | `True` | ✅ 正常停止 |
| stopped | `"stopped"` | ✅ 幂等 `无需操作` |
| failed | `False` 或不存在 | ❌ 拒绝 `不在运行状态` |
| success（自然完成） | active 被清除 | ❌ 拒绝 `Pipeline R<N> 不存在` |

### 4.6 广播通知

与 R92 相同模式 — 通过 `_broadcast_to_channel(p.ADMIN_CHANNEL, ...)` 让 AutoRouter 收到信号：

```
content: "🛑 R95 管线已停止（发起者: ws_abc1...）"
```

---

## 5. 🅱️ AutoRouter 停止信号处理

### 5.1 `_handle_message` 扩展

```python
# auto_router.py _handle_message() — 在 _admin 频道专有处理区增加

# _admin 专有
if is_admin:
    # ═══ R95: 管线停止信号 ═══
    round_name = self._extract_round(content)
    if round_name and f"🛑 {round_name} 管线已停止" in content:
        await self._on_pipeline_stop(round_name)
        return
    return  # 其他 _admin 消息忽略
```

### 5.2 `_on_pipeline_stop` 实现

```python
async def _on_pipeline_stop(self, round_name: str) -> None:
    """R95: 收到管线停止信号 → 清理 AutoRouter 内部状态。

    停止管线意味着：
    1. 不再派发新的 step（清理 _round_progress）
    2. 取消超时检测（清理 _step_dispatch_times）
    3. 已发出的 inbox 消息不再等待
    """
    logger.info("[AR] ⏹️ [%s] 收到停止信号，正在清理...", round_name)

    # ① 清理进度追踪（阻止 _dispatch_step 继续派活）
    self._round_progress.pop(round_name, None)

    # ② 清理超时计时器
    self._step_dispatch_times.pop(round_name, None)
    self._step_timeout_notified.pop(round_name, None)

    await self._send_to_pm(
        f"🛑 AutoRouter: {round_name} 管线已停止调度\n"
        f"  已在执行的 bot 不受影响\n"
        f"  待发送任务已清空"
    )
    logger.info("[AR] ✅ [%s] 管线已停止调度", round_name)
```

### 5.3 停止后 AutoRouter 行为矩阵

| 场景 | AutoRouter 行为 |
|:-----|:----------------|
| 收到已停止管线的完成消息 `✅ 完成` | ❌ 忽略 — `_round_progress` 中无该管线记录 → `_on_step_complete` 找不到 progress → 日志 DEBUG + return |
| 收到已停止管线的停止信号 | ✅ 幂等 — `_round_progress.pop()` 第二次返回 None |
| 断线重连后，管线已 stopped | AutoRouter 启动时 `_restore_pipeline_state` 不恢复（v1 限制）。新的 `_admin` 广播 message 被 `_mark_seen` 去重用？— 需看 msg_id 是否一致。如果不一致（通常 id 不同），则可能重复处理 → 幂等 |
| 停止后 PM 手工派活 inbox | ✅ 正常 — AutoRouter 收到完成消息后检查 `_round_progress` 不存在 → 忽略。不会推进下一 step |

### 5.4 关于「已发出 inbox 消息不再等待」

需求文档要求：已发出的 inbox 消息不再处理，视为 bot 离线、消息被吞。

AutoRouter 当前架构**天然支持**这一行为：

```python
# 收到 ✅ 完成 → _on_step_complete
def _on_step_complete(self, content):
    progress = self._round_progress.get(round_name)  # ← 已被 pop
    if not progress:
        logger.debug("[AR] [%s] 无进度记录，跳过", round_name)
        return  # ← 直接忽略
```

停用管线后，`_round_progress` 被 pop，任何后续完成通知都不会触发派活。**无需额外的「吞消息」逻辑。**

---

## 6. 🅲 `pipeline_status` 扩展

### 6.1 改动位置

**文件：** `server/handler.py`
**函数：** `_cmd_pipeline_status`（L4219+）
**函数：** `_format_pipeline_state`（L1816+，如果存在）

### 6.2 现有状态格式化

查看 `_cmd_pipeline_status` 的实现，找到状态显示区域：

```python
# handler.py — 在 _cmd_pipeline_status 或 cycle_pipeline_tasks 中
# 当前显示 active: True → "🟢 活跃"
# 需要扩展为：
#   active: True      → "🟢 活跃 (running)"
#   active: "stopped" → "🟡 已停止 (stopped)"
```

### 6.3 实际改动

```python
# 在 pipeline_status 显示函数中，修改状态显示逻辑

# Before:
if state.get("active"):
    status_icon = "🟢 活跃"
else:
    status_icon = "⚫ 非活跃"

# After (R95 🅲):
active_val = state.get("active")
if active_val == "stopped":
    status_icon = "🟡 已停止"
elif active_val:
    status_icon = "🟢 运行中"
else:
    status_icon = "⚫ 非活跃"
```

---

## 7. 改动对照表

### 7.1 handler.py 改动

| # | 位置 | 操作 | 说明 |
|:-:|:-----|:----|:------|
| 1 | 模块级（L1561 附近） | ➕ 新增 `pipeline_is_stopped()` | 工具函数，约 4 行 |
| 2 | `_ADMIN_COMMANDS`（L4790） | ➕ 新增 `pipeline_stop` 注册条目 | 6 行 |
| 3 | `_cmd_pipeline_stop()`（🆕） | ➕ 新增完整 handler | ~+35 行 |
| 4 | `_cmd_pipeline_start()`（L2573） | ✏️ 可选修改 `pipeline_is_active` → 加 `stopped` 检测 | 1–3 行 |
| 5 | `_cmd_pipeline_status()` / 状态格式化 | ✏️ 增加 `stopped` 状态显示 | ~+5 行 |
| **合计** | | | **~+50 行净增** |

### 7.2 auto_router.py 改动

| # | 位置 | 操作 | 说明 |
|:-:|:-----|:----|:------|
| 6 | `_handle_message()` L226-229 | ✏️ 增加 `🛑 {round_name} 管线已停止` 信号捕获 | ~+5 行 |
| 7 | `_on_pipeline_stop()`（🆕） | ➕ 新增停止清理方法 | ~+10 行 |
| **合计** | | | **~+15 行净增** |

---

## 8. 兼容性分析

### 8.1 向后兼容矩阵

| 场景 | 旧行为 | R95 后行为 | 兼容性 |
|:-----|:-------|:-----------|:------:|
| `!pipeline_start R{N}` | 正常启动 | **不变** | ✅ |
| `!pipeline_status` | 显示 active True/False | 额外显示 stopped 状态 | ✅ 仅增加 |
| 旧版 `_PIPELINE_STATE` 中的 `active=True` | `pipeline_is_active` 返回 True | **不变** — `"stopped"` 是字符串，`True` 仍是 bool | ✅ |
| 旧版管线（无 `triggerer_id`）| N/A | `_cmd_pipeline_stop` 降级允许 | ✅ |
| 非发起者调用 stop | N/A | ❌ 拒绝 | ✅ 预期行为 |
| 其他管线正常运行 | 不受影响 | **不变** — stop 只操作指定 round_name | ✅ |
| AutoRouter 中旧版管线 | 正常推进 | **不变** — 除非收到 stop 广播 | ✅ |

### 8.2 `pipeline_is_active` 的兼容性

`pipeline_is_active` 当前逻辑是 `bool(state and state.get("active"))`。由于 `"stopped"` 是 truthy 字符串，`bool("stopped") == True`，**现有调用方行为不变**：

| 调用方 | 对 stopped 管线行为 | 是否需修改 |
|:-------|:-------------------|:----------:|
| `_cmd_pipeline_start` 的"已活跃"检查 | 阻止重复 start | ✅ 期望行为（start 应拒绝 stopped 管线） |
| `set_lobby_paused` | 大厅继续暂停 | ✅ 期望行为 |
| `_cmd_step_handoff` | 允许 handoff | ✅ 期望行为（停止后仍可手工操作） |

**结论：`pipeline_is_active` 不需要修改。** `active=True` 和 `active="stopped"` 都被视为「活跃」，这正是需求所期望的：stop 后的管线不能被再次 start，但可以手工操作。

### 8.3 不再受影响的功能

| 功能 | 说明 |
|:-----|:------|
| `!pipeline_start` | 行为不变，对 stopped 管线返回「已活跃」 |
| `!pipeline_status` | 扩展显示 stopped |
| `!list_workspaces` | 不受影响 |
| `!close_workspace` | 不受影响 |
| AutoRouter 自动推进 | 其他管线不受影响 |
| 多管线并发 | stop 只影响指定管线 |

---

## 9. 风险与缓解

| # | 风险 | 等级 | 缓解措施 |
|:-:|:-----|:----:|:---------|
| R1 | `_cmd_pipeline_stop` 未在 `_ADMIN_COMMANDS` 注册 → 命令不可用 | 🟢 低 | 注册条目是 6 行硬逻辑，代码审查可发现 |
| R2 | `active="stopped"` 被 `bool()` 误判 | 🟢 低 | `bool("stopped") == True`，与 `active=True` 行为一致，无需改动 |
| R3 | AutoRouter 重连后重发 stop 信号 | 🟢 低 | `_on_pipeline_stop` 幂等 — `_round_progress.pop()` 再次返回 None |
| R4 | stop 后 PM 手工派活但 AutoRouter 不推进 | 🟡 中 | **预期行为**：AutoRouter 不再推进 stopped 管线的 step。PM 需手动派完全流程，或向 `_admin` 发 `!pipeline_start` 重建管线 |
| R5 | `triggerer_id` 在旧有管线中缺失 | 🟢 低 | `_cmd_pipeline_stop` 检测到 `triggerer_id` 为空时降级允许任意用户 stop |
| R6 | 超时检测 task 仍在轮询 stopped 管线的 dispatch_time | 🟢 低 | `_on_pipeline_stop` 中调用 `_step_dispatch_times.pop(round_name)` 清除计时器 |
| R7 | 未启动的管线 stop 时报错信息不够明确 | 🟢 低 | 返回 `Pipeline R<N> 不存在，请先执行 !pipeline_start` — 清晰 |

### 9.1 回退方案

| 级别 | 操作 | 复杂度 |
|:----:|:-----|:------:|
| 🟢 浅回退 | 从 `_ADMIN_COMMANDS` 移除 `pipeline_stop` 条目 | 6 行 |
| 🟢 中回退 | 恢复 `pipeline_status` 中的 stopped 显示 | ~5 行 |
| 🟡 中回退 | 移除 AutoRouter 中 `_on_pipeline_stop` | ~15 行 |
| 🔴 全回退 | `git revert <commit-sha>` | 1 命令 |

---

## 10. 验收清单

### 🅰️ `!pipeline_stop` 命令（7 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🅰️-1 | 对 running 管线执行 stop | `_PIPELINE_STATE[round]["active"]` | 变 `"stopped"` |
| 🅰️-2 | 权限校验：非发起者 | 另一用户执行 `!pipeline_stop` | ❌ `只有发起者可以 stop` |
| 🅰️-3 | 幂等：重复 stop | 对已 stop 管线再执行 | ✅ `已停止（无需操作）` |
| 🅰️-4 | idle 管线 stop | 对未启动管线执行 | ❌ `不存在` |
| 🅰️-5 | 命令注册 | `_ADMIN_COMMANDS` 中有 `pipeline_stop` | ✅ 存在 |
| 🅰️-6 | 广播通知 `_admin` | stop 后检查 `_admin` 频道 | `🛑 R{N} 管线已停止` |
| 🅰️-7 | stop 后正在执行的 bot 不受影响 | 检查 bot 日志 | bot 正常输出 |

### 🅱️ AutoRouter 停止处理（4 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🅱️-1 | AutoRouter 收到停止信号后清理 `_round_progress` | `_handle_message` 日志 | `[AR] ⏹️ [R{N}] 收到停止信号` |
| 🅱️-2 | stop 后 AutoRouter 不再派活 | 模拟完成消息 | `_round_progress` 为空 → 忽略 |
| 🅱️-3 | stop 后 `_step_dispatch_times` 被清理 | 检查 dict | 该 round 已 pop |
| 🅱️-4 | stop 后 PM 收件箱收到确认 | 检查 PM inbox | `🛑 AutoRouter: R{N} 已停止调度` |

### 🅲 `pipeline_status` 显示（2 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🅲-1 | `!pipeline_status` 显示 stopped 管线 | stop 后查询 | `🟡 已停止` |
| 🅲-2 | running 管线仍显示 `🟢 运行中` | 正常管线查询 | `🟢 运行中` |

---

## 附录：断点续跑流程

```
管线 R95 在 Step 2 (architect) 卡死
        │
        ▼
① PM 发 !pipeline_stop R95
        │
        ▼
   AutoRouter 清理内部状态
   工作区仍存在，bot 产出保留
        │
        ▼
② PM 查看 !pipeline_status R95 → Step 2 (architect) 卡死
   跳过已完成 step，直接从 Step 3 (developer) 开始
        │
        ▼
③ PM 发 inbox 给 developer bot
   "R95 Step 3: 请编码实现 xxx"
        │
        ▼
④ Developer bot 完成任务 → 回复 ✅ 完成 (inbox:server)
        │
        ▼
⑤ AutoRouter 收到 ✅ 完成通知
   → 检查 _round_progress: 空（stopped 时已清理）
   → 忽略，不推进 Step 4
        │
        ▼
   说明：stopped 管线的完成消息被 AutoRouter 忽略。
   PM 需要 ① 手动派完全流程，或 ② 发 !pipeline_start R95 重建管线。
```

---

*本文档由 🏗️ 架构师编写，待 Step 3 👨‍💻 编码实现。*
