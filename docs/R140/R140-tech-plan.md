# R140 技术方案 — 管线引擎核心路径修复

> **起草人：** 📐 小开 (Arch)
> **版本：** v1.0
> **日期：** 2026-07-21
> **依据：** `docs/R140/R140-product-requirements.md`、`docs/R140/WORK_PLAN.md`

---

## 1. 问题复述

管线引擎（`pipeline_engine.py`，2201 行）存在 3 条核心路径的 5 个问题：

| # | 路径 | 问题 | 严重度 |
|:-:|:----|:-----|:------:|
| P1 | 启动 (`##start`) | `_auto_dispatch(ctx, 2)` 可能静默失败，无错误反馈 | 🔴 |
| P2 | 启动 (`##start`) | 回复「Step 1 已派活」，实际派的是 Step 2 | 🟡 |
| P3 | 手动推进 (`##advance`) | 权限写死 PM-only，管线协调者（经理）无法使用 | 🔴 |
| P4 | 手动推进 (`##advance`) | 只能顺序推进，无法跨步 | 🔴 |
| P5 | 自动推进 (`已完成 ✅`) | `_auto_dispatch` 失败后无通知机制 | 🟡 |

> P6（`##step##complete` 走旧路径）本轮不做。

---

## 2. 根因链与代码证据

### 2.1 P1+P2：`##start` 静默失败 + 误导消息

**代码位置：** `_handle_hash_start` L1295-L1420

```
L1374-1377:  ctx.current_step = 2
L1380:       await _auto_dispatch(ctx, 2)   ← 返回值被忽略
L1395-1402:  "✅ {round_name} 管线已启动，Step 1 已派活"  ← 硬编码
```

`_auto_dispatch`（L854）在以下场景返回 `False` 但不通知任何人：
- `AUTO_DISPATCH_ENABLED = False` → L862，仅 log
- 模板缺失 → L877-882，仅 log warning
- agent_id 为空 → L887-892，仅 log warning
- card key 无法解析 → L897-909，仅 log warning

### 2.2 P3：`##advance` 权限写死 PM-only

**代码位置：** `_handle_hash_advance` L1147-L1203

```
L1154-1155:  pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
             if pm_agent_id and agent_id != pm_agent_id:
```

没有配置扩展点，也没有 L4 角色检查。

### 2.3 P4：`##advance` 无法跨步

**根因：** `_handle_hash_advance` 构造假完成消息喂给 `_try_advance_pipeline`：

```
L1189:  content = f"已完成 ✅ {round_name} Step {step_num}"
L1190:  ok, reason = _try_advance_pipeline(content, agent_id)
```

而 `_try_advance_pipeline`（L361）要求 `completed_step == current_step`（L393）。如果 `step_num > current_step + 1`，走 L430-434 返回 `"future step"`。

### 2.4 P5：自动推进后派活失败无通知

**代码位置：** `_try_advance_pipeline` L437-L456

```
L452:  asyncio.ensure_future(_auto_dispatch(ctx, next_step))  ← 返回值被忽略
```

推进已成功，但派活失败 → 管线卡在中间状态，无人知。

---

## 3. 修改位置表

| # | 函数 | 行号 | 修改类型 | 说明 |
|:-:|:-----|:----:|:--------:|:-----|
| M1 | `_handle_hash_advance` | L1147 | 重构 | 权限扩展 + 跨步推进逻辑 |
| M2 | `_auto_dispatch` | L854 | 修改签名 | 增加 `notify_ws`/`notify_agent_id` 参数，失败时通知 |
| M3 | `_handle_hash_start` | L1295 | 修改 | 根据 `_auto_dispatch` 返回值回复不同消息 |
| M4 | `_try_advance_pipeline` | L361 | 修改 | `ensure_future` 调用传递通知参数 |
| M5 | `config.py` | L111 后 | 新增 | 可选：`PIPELINE_COORDINATOR_AGENT_ID` |

---

## 4. 详细设计

### 4.1 M1：`##advance` 权限扩展 + 跨步推进 (`_handle_hash_advance`)

#### 4.1.1 权限设计

**方案选型：** 新增 `PIPELINE_COORDINATOR_AGENT_ID` 配置项 + L4 角色兼容。理由：
- 工作计划的角色表中有「经理」角色专门负责管线调度
- `config.py` 已有 AGENT_WHITELIST（L113：`{"小爱", "小谷", "小开", "爱泰", "小周", "泰虾", "经理"}`）

**实现：**

```python
# 替代 L1154-L1155 的硬编码 PM-only 检查
ALLOWED_ADVANCE_AGENTS = set()
if config.DISPATCH_SENDER_ID:
    ALLOWED_ADVANCE_AGENTS.add(config.DISPATCH_SENDER_ID)
if config.PIPELINE_PM_AGENT_ID:
    ALLOWED_ADVANCE_AGENTS.add(config.PIPELINE_PM_AGENT_ID)
if getattr(config, 'PIPELINE_COORDINATOR_AGENT_ID', None):
    ALLOWED_ADVANCE_AGENTS.add(config.PIPELINE_COORDINATOR_AGENT_ID)

if ALLOWED_ADVANCE_AGENTS and agent_id not in ALLOWED_ADVANCE_AGENTS:
    await _send(ws, { "content": "❌ 无权限: ##advance 仅 PM 或管线协调者可用" })
    return True
```

**降级策略：** 如果 `PIPELINE_COORDINATOR_AGENT_ID` 未配置，`ALLOWED_ADVANCE_AGENTS` 退化为原 PM-only 行为，零影响。

#### 4.1.2 跨步推进逻辑

**不再构造假 `已完成 ✅` 消息调用 `_try_advance_pipeline`**，而是直接操作 PipelineContext：

```python
async def _handle_hash_advance(round_name, kv, agent_id, ws) -> bool:
    # ... 权限检查同上 ...

    step_str = kv.get("step", "")
    if not step_str.isdigit():
        await _send(ws, {"content": "❌ 参数错误: 缺少 `step=N` 参数"})
        return True
    target_step = int(step_str)

    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        await _send(ws, {"content": f"❌ 管线 {round_name} 不存在"})
        return True

    # 边界检查
    if target_step < 1 or target_step > ctx.total_steps:
        await _send(ws, {"content": f"❌ Step {target_step} 超出范围 (1-{ctx.total_steps})"})
        return True

    old_step = ctx.current_step

    # A) 跨步推进：跳过中间未完成步骤，标记为 skipped
    for i in range(old_step, target_step):
        if i < len(ctx.steps):
            step_info = ctx.steps[i]
            if step_info.get("status") in ("pending",):
                step_info["status"] = "skipped"
                step_info["result_msg"] = f"跨步推进（从 Step {old_step} 跳过）"

    # B) 设置新 current_step
    ctx.current_step = target_step
    # 目标步标记为 active（或 pending）
    target_idx = target_step - 1
    if target_idx < len(ctx.steps):
        ctx.steps[target_idx]["status"] = "active"

    try:
        mgr.save()
    except Exception:
        pass

    # C) 派活目标步
    dispatch_ok = await _auto_dispatch(ctx, target_step, notify_ws=ws, notify_agent_id=agent_id)

    # D) 回复
    msg = f"✅ **{round_name}** 跨步推进: Step {old_step} → **Step {target_step}**"
    if not dispatch_ok:
        msg += "\n⚠️ 自动派活失败，原因见上方通知"
    await _send(ws, {"content": msg, ...})
    return True
```

**关键设计决策：**
- 中间步骤标记为 `"skipped"`，保留历史记录
- 目标步标记为 `"active"`，与 `_auto_dispatch` 中 `next_step_info["status"] = "in_progress"` 一致
- 从 `old_step` 到 `target_step` 的连续跳过，不是从 step=1 开始

### 4.2 M2：`_auto_dispatch` 增加失败通知 (`_auto_dispatch`)

**签名变更：**

```python
# 原
async def _auto_dispatch(ctx: PipelineContext, step_num: int) -> bool:

# 新
async def _auto_dispatch(
    ctx: PipelineContext,
    step_num: int,
    notify_ws=None,          # WS 连接，发给发起者
    notify_agent_id=None,    # Agent ID，发给发起者
) -> bool:
```

**通知逻辑（在每个静默失败点增加）：**

```python
async def _auto_dispatch(ctx, step_num, notify_ws=None, notify_agent_id=None):
    if not config.AUTO_DISPATCH_ENABLED:
        # 保持原有 log，增加通知
        _notify_failure(ctx, step_num, "自动派活已关闭 (AUTO_DISPATCH_ENABLED=False)",
                        notify_ws, notify_agent_id)
        return False

    next_step_key = f"step{step_num}"
    next_template = ctx.message_templates.get(next_step_key)
    if not next_template:
        _notify_failure(ctx, step_num, "模板缺失 (message_templates 中无此 step)",
                        notify_ws, notify_agent_id)
        return False

    next_step_info = next(...)
    if not next_step_info or not next_step_info.get("agent_id"):
        _notify_failure(ctx, step_num, "无 agent_id (步骤角色未分配)",
                        notify_ws, notify_agent_id)
        return False

    target_agent_id = next_step_info["agent_id"]
    if not target_agent_id.startswith("ws_"):
        _fallback_id = _resolve_card_key_to_ws_id(target_agent_id)
        if not _fallback_id:
            _notify_failure(ctx, step_num,
                            f"无法解析 agent_id {target_agent_id} 为 WS 连接",
                            notify_ws, notify_agent_id)
            return False
        target_agent_id = _fallback_id
    # ... 后续正常派活 ...
```

**辅助函数（在 `_auto_dispatch` 前新增或 inline）：**

```python
async def _notify_dispatch_failure(
    ctx: PipelineContext,
    step_num: int,
    reason: str,
    notify_ws=None,
    notify_agent_id=None,
) -> None:
    """派活失败时通知发起者（不抛出异常）"""
    msg = f"⚠️ {ctx.round_name} Step {step_num} 自动派活失败：{reason}"
    logger.warning("[R140] %s", msg)
    if notify_ws:
        try:
            await _send(notify_ws, {
                "type": "broadcast",
                "channel": f"_inbox:{notify_agent_id or 'unknown'}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": msg,
                "ts": time.time(),
            })
        except Exception:
            pass
    elif notify_agent_id:
        try:
            await _send_to_agent(notify_agent_id, {
                "type": "broadcast",
                "channel": f"_inbox:{notify_agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": msg,
                "ts": time.time(),
            })
        except Exception:
            pass
```

### 4.3 M3：`##start` 回复消息修正 (`_handle_hash_start`)

**当前（L1380 + L1395-1402）：**

```python
await _auto_dispatch(ctx, 2)                                   # L1380 — 返回值丢弃
# ...
"content": f"✅ {round_name} 管线已启动，Step 1 已派活",       # L1400
```

**改为：**

```python
dispatch_ok = await _auto_dispatch(ctx, 2, notify_ws=ws, notify_agent_id=agent_id)

# 获取 Step 2 的 agent name
step2_name = _get_step_agent_name(ctx, 2)

if dispatch_ok:
    content = f"✅ {round_name} 管线已启动，Step 2（{_get_step_title(ctx, 2)}）已派活给 {step2_name}"
else:
    content = (
        f"✅ {round_name} 管线已创建（Step 1 自动确认），\n"
        "⚠️ 但 Step 2 自动派活失败，原因见系统通知。\n"
        f"请使用 `##advance##{round_name}##step=N` 手动推进"
    )

await _send(ws, {
    "type": "broadcast",
    "channel": f"_inbox:{agent_id}",
    "from_name": "系统",
    "from_agent": state.SYSTEM_AGENT_ID,
    "content": content,
    "ts": time.time(),
})
```

**辅助函数（需要在文件中新增或使用已有）：**
- `_get_step_agent_name(ctx, step_num)` — 已有（L682）
- Step title 可通过 `ctx.steps[1].get("title", "技术方案")` 获取

### 4.4 M4：`_try_advance_pipeline` 派活失败通知

**当前（L450-L454）：**

```python
next_step = old_step + 1
if next_step <= ctx.total_steps:
    asyncio.ensure_future(_auto_dispatch(ctx, next_step))
```

**改为：**

```python
next_step = old_step + 1
if next_step <= ctx.total_steps:
    asyncio.ensure_future(
        _auto_dispatch(ctx, next_step, notify_ws=None, notify_agent_id=agent_id)
    )
```

**设计说明：** `_try_advance_pipeline` 是同步函数（非 `async`），通过 `asyncio.ensure_future` 异步执行 `_auto_dispatch`。传入 `notify_agent_id=agent_id`（完成消息的发送者），使 `_auto_dispatch` 失败时能通知到该发送者。

---

## 5. 数据流图

```
##start → _handle_hash_start
  → ctx.current_step = 2, steps[0].status = "done"
  → _auto_dispatch(ctx, 2, notify_ws=ws, notify_agent_id=agent_id)
    → 成功: 回复 "Step 2 已派活给 {name}"
    → 失败: 回复 "创建完成但派活失败: {reason}"

已完成 ✅ → _try_advance_pipeline(content, agent_id)
  → 正则匹配 → completed_step == current_step?
  → 记录 artifacts + status=done
  → advance_step() → current_step += 1
  → _auto_dispatch(ctx, next_step, notify_agent_id=agent_id)
    → 成功: 静默（已发 _notify_pm）
    → 失败: 通知 agent_id（完成消息发送者）

##advance##R{N}##step=N → _handle_hash_advance
  → 权限检查（PM + 协调者）
  → 跨步跳过中间 pending steps → skipped
  → ctx.current_step = N
  → _auto_dispatch(ctx, N, notify_ws=ws, notify_agent_id=agent_id)
  → 回复 "跨步推进: Step {old} → Step {N}"
```

---

## 6. 验收标准追溯

| # | 验收项 | P0/P1 | 对应修改位置 | 验证方式 |
|:-:|:-------|:-----:|:------------|:---------|
| A-1 | 经理能用 `##advance` | P0 | M1: L1154-1155 | 非 PM 的 L4 bot 执行 `##advance` |
| A-2 | 跨步跳到 Step 5 | P0 | M1: 新增跨步逻辑 | `##advance##R{N}##step=5` |
| A-3 | 跨步后正确派活 | P0 | M1 → M2 联动 | 检查目标步的派活消息 |
| A-4 | 模板缺失时通知 | P0 | M2: L877-882 通知分支 | 构造无模板的 ctx |
| A-5 | agent_id 为空时通知 | P0 | M2: L887-892 通知分支 | 构造无 agent_id 的 ctx |
| A-6 | `##start` 说「Step 2 已派活」 | P1 | M3: L1400 | `##start` 后看回复 |
| A-7 | `##start` 派活失败有原因 | P0 | M3: `dispatch_ok` 分支 | 关 AUTO_DISPATCH_ENABLED |
| A-8 | 推进后派活失败通知发送者 | P1 | M4: L452 | `已完成 ✅` 后模拟派活失败 |
| R1 | `##start` 正常创建 | P0 | 回归 | 现有测试 |
| R2 | `已完成 ✅` 正常推进 | P0 | 回归 | 现有测试 |
| R3 | `##stop` 正常停止 | P0 | 回归 | 现有测试 |
| R4 | 编译无错误 | P0 | `python3 -c "from server.ws_server import pipeline_engine"` | CI |

---

## 7. 侧效应分析

| 侧效应 | 可能性 | 影响 | 缓解措施 |
|:-------|:------:|:----|:---------|
| `_auto_dispatch` 新增参数被旧调用者遗漏 | 中 | 通知功能降级，不致命 | 签名增加默认值 `notify_ws=None, notify_agent_id=None`，旧调用者自动兼容 |
| `_handle_hash_advance` 重构后 `_try_advance_pipeline` 不再被调用 | 低 | `##advance` 不走 artifact 提取路径 | 跨步推进不需要 artifact 提取（没有「完成」一个未执行的步骤），符合预期 |
| 跨步推进标记 skipped 导致 `_try_advance_pipeline` 后续拦截 | 低 | 后续 `已完成 ✅` 匹配 `old_step` 已为 target_step，无冲突 | 已验证：中间步 skipped 不影响后续 |
| `notify_agent_id` 在 `_try_advance_pipeline` 中为空 | 中 | 推进后派活失败退化为静默 | 只有 `已完成 ✅` 消息的发送者会被传入，正常流程都有 sender |
| `PIPELINE_COORDINATOR_AGENT_ID` 未配置时 behavior | 低 | 退化为原 PM-only | 与 `set.discard(None)` 配合，零影响 |

---

## 8. 不做事项

| ❌ 不做 | 原因 |
|:--------|:-----|
| 重写 `_auto_dispatch` 为同步可靠方式 | 增量修复，不改整体架构 |
| 统一 `##step##complete` 与 `##advance` | 旧 `!` 命令路径不在本轮范围 |
| PipelineContext 数据模型改造（添加 `skipped` 枚举值） | 直接复用 `"pending" → "skipped"` 字符串，不新增枚举 |
| `_try_advance_pipeline` 正则匹配改造 | 现有逻辑可用，不改 |
| 自动归档拿掉或改为可选 | 非本轮目标 |

---

## 9. 改动预估

| 文件 | 变更 | 行数变化 | 预估耗时 |
|:-----|:------|:--------:|:--------:|
| `server/ws_server/pipeline_engine.py` | M1：`_handle_hash_advance` 权限+跨步 | +~55 行 | 30min |
| `server/ws_server/pipeline_engine.py` | M2：`_auto_dispatch` 通知参数 | +~35 行 | 20min |
| `server/ws_server/pipeline_engine.py` | M3：`##start` 回复消息 | +~15 行 | 10min |
| `server/ws_server/pipeline_engine.py` | M4：`_try_advance_pipeline` 传递 agent_id | +~5 行 | 5min |
| `server/common/config.py` | 可选：`PIPELINE_COORDINATOR_AGENT_ID` | +~3 行 | 2min |

> 技术方案审核人：小周
> 审核结论：⬜ 待审核
