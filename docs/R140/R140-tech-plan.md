# R140 技术方案 — 管线引擎核心路径修复

> **起草人：** 小开 (Arch)
> **版本：** v1.0
> **日期：** 2026-07-21
> **依据：** [R140 产品需求](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R140/R140-product-requirements.md) | [WORK_PLAN](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R140/WORK_PLAN.md)

---

## 1. 现状分析

`server/ws_server/pipeline_engine.py`（~2,201 行）包含模块级函数 + `PipelineEngine` class 两层结构，class 方法通过薄包装器调用模块级函数。

| 组件 | 行号 | 职责 | 关键问题 |
|:-----|:----:|:-----|:---------|
| `_handle_hash_advance()` | L1146 | 手动推进 | 🔴 权限写死 PM-only；只能逐步推进 |
| `_handle_hash_start()` | L1295 | 启动管线 | 🟡 回复"Step 1 已开始"但实际派活 Step 1 |
| `_try_advance_pipeline()` | L361 | 自动推进 | 🟡 `_auto_dispatch` 失败后无法回滚 |
| `_auto_dispatch()` | L854 | 自动派活 | 🔴 失败仅 log warning，无任何通知 |
| `PipelineEngine.auto_dispatch()` | L1805 | 薄包装器 | 与模块级 `_auto_dispatch` 不同实现（含默认模板回退） |

### 问题 1：`##advance` 权限与跨步

```python
# P3: L1154-1155 权限校验
pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
if pm_agent_id and agent_id != pm_agent_id:  # 🔴 仅 PM
    ...

# P4: 只能逐步推进（构造假完成消息 → 走 _try_advance_pipeline）
# _try_advance_pipeline 要求 completed_step == current_step 才推进
# 无法 ##advance##R140##step=5 跨步跳到 Step 5
```

### 问题 2：`_auto_dispatch` 静默失败

```python
# P1: L874-L882 模板缺失时仅 log warning，不通知任何人
if not next_template:
    logger.warning("...缺少 step%d 模板，跳过自动派活")
    return False  # ❌ 不通知发起者

# P1: L888-L895 agent_id 为空时同样静默
if not next_step_info or not next_step_info.get("agent_id"):
    logger.warning("...无 agent_id，跳过自动派活")
    return False  # ❌ 不通知发起者
```

### 问题 3：`##start` 消息

L1308 创建管线后回复 `"Step 1 已开始"` 并 `auto_dispatch(ctx, 1)`。但需求文档指出应说"Step 2 已派活给 xxx"——这取决于管线启动后是否立即自动完成 Step 1。

---

## 2. 设计方案

### 2.1 A-1：`##advance` 权限扩展（P3）

**改动位置：** `_handle_hash_advance()` L1152-L1161

**方案：** 将 PM-only 校验改为 L4+ 白名单。与 `##step` 权限一致（scenario_matcher.py L571 `if level < 4:`）。

```python
# 原有（L1152-L1161）：
pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
if pm_agent_id and agent_id != pm_agent_id:
    await _send(ws, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": "❌ 无权限: ##advance 仅 PM 可用",
        "ts": time.time(),
    })
    return True

# 改为：
# 方案 A（推荐）：L4+ 万能权限，与 ##step 一致
from .scenario_matcher import _get_agent_level
if _get_agent_level(agent_id) < 4:
    await _send(ws, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": "❌ 无权限: ##advance 需要 L4 或以上级别",
        "ts": time.time(),
    })
    return True
```

**备选方案 B：** 如果希望保留 PM+协调者白名单，新增 `config.PIPELINE_COORDINATOR_AGENT_ID`。

**推荐方案 A（L4+）的原因：** 与 `##step` 命令权限一致（scenario_matcher 已有 `_get_agent_level` 函数），无需新增配置项，与现有权限体系对接。

### 2.2 A-2：`##advance` 跨步推进（P4）

**改动位置：** `_handle_hash_advance()` L1175-L1195

**当前实现的问题：** 构造假完成消息 → `_try_advance_pipeline()` → 只允许 `completed_step == current_step`。无法跨步。

**方案：** 新增 `_advance_pipeline_direct()` 函数，不走 `_try_advance_pipeline` 的完成消息解析路径，直接操作 PipelineContext。

```python
async def _advance_pipeline_direct(
    round_name: str, target_step: int, ws, agent_id: str
) -> bool:
    """直接推进管线到指定步骤（跳过完成消息解析）。"""
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        await _send(ws, {... "content": f"❌ 未找到活跃管线 `{round_name}`"})
        return False

    if target_step < 1 or target_step > ctx.total_steps:
        await _send(ws, {... "content": f"❌ 无效 step: {target_step}（范围: 1-{ctx.total_steps}）"})
        return False

    old_step = ctx.current_step
    # 标记中间未完成步骤为 skipped
    for i, s in enumerate(ctx.steps):
        step_num = i + 1
        if step_num > old_step and step_num < target_step:
            if s.get("status") in ("pending", None):
                s["status"] = "skipped"
                s["output"] = {"skipped_reason": "手动跨步跳过"}
                s["result_msg"] = f"##advance 跳转到 Step {target_step}"

    # 推进到目标步
    ctx.current_step = target_step
    try:
        mgr.save()
    except Exception:
        pass

    # 派活目标步
    asyncio.ensure_future(_auto_dispatch(ctx, target_step))

    await _send(ws, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": f"✅ **{round_name}** 已从 Step {old_step} 直接推进到 **Step {target_step}**，已派活",
        "ts": time.time(),
    })
    return True
```

**`_handle_hash_advance` 改动：** 在权限校验后，判断 `target_step` 是否跨步：

```python
# 在权限校验后、推进逻辑前
target_step = int(step_str)

# 检查是否需要跨步
ctx = _ensure_pipeline_manager().get(round_name)
if ctx and target_step != ctx.current_step:
    # 跨步推进——直接操作 PipelineContext
    return await _advance_pipeline_direct(round_name, target_step, ws, agent_id)

# 单步推进——走原有完成消息路径（兼容）
content = f"已完成 ✅ {round_name} Step {target_step}"
ok, reason = _try_advance_pipeline(content, agent_id)
```

### 2.3 A-3：`_auto_dispatch` 失败通知（P1）

**改动位置：** `_auto_dispatch()`（模块级，L854）和 `PipelineEngine.auto_dispatch()`（L1805）

**方案：** 新增 `notify_agent_id: str = ""` 可选参数。当 `_auto_dispatch` 因模板缺失/agent_id 为空失败时，通知发起者。

```python
async def _auto_dispatch(
    ctx: PipelineContext, step_num: int,
    notify_agent_id: str = "",   # 新增
    notify_ws=None,              # 新增
) -> bool:
    ...
    if not next_template:
        msg = f"⚠️ {ctx.round_name} Step {step_num} 派活失败：缺少消息模板，"
        msg += "请检查 ##start 参数中的 ref 配置"
        if notify_agent_id:
            await _send_to_agent(notify_agent_id, _build_notify_payload(msg))
        elif notify_ws and notify_agent_id:
            await _send(notify_ws, {... "content": msg})
        return False

    if not next_step_info or not next_step_info.get("agent_id"):
        msg = f"⚠️ {ctx.round_name} Step {step_num} 派活失败：无法确定负责人（agent_id 为空）"
        if notify_agent_id:
            await _send_to_agent(notify_agent_id, _build_notify_payload(msg))
        elif notify_ws and notify_agent_id:
            await _send(notify_ws, {... "content": msg})
        return False
    ...
```

**辅助函数：**

```python
def _build_notify_payload(msg: str, to_agent: str = "") -> dict:
    return {
        "type": "broadcast",
        "channel": f"_inbox:{to_agent}" if to_agent else "",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": msg,
        "ts": time.time(),
    }
```

### 2.4 A-4：`##start` 回复修正（P2）

**改动位置：** `_handle_hash_start()` L1308-L1327（回复消息部分）

**方案：** 将 `auto_dispatch` 改为同步调用（等待结果），根据派活结果决定回复内容。

```python
# 原有：
await _send(ws, {... "content": f"✅ 管线 {round_name} 已创建并启动\n  Step 1 已开始"})
asyncio.ensure_future(self.auto_dispatch(ctx, 1))

# 改为：
dispatch_success = await _auto_dispatch(ctx, 1, notify_agent_id=agent_id, notify_ws=ws)
if dispatch_success:
    agent_name = _get_step_agent_name(ctx, 1)
    reply_text = (
        f"✅ 管线 {round_name} 已创建并启动\n"
        f"  Step 1 已派活给「{agent_name}」"
    )
else:
    reply_text = (
        f"✅ 管线 {round_name} 已创建，但自动派活失败\n"
        f"  请检查角色配置后使用 ##advance##{round_name}##step=N 手动推进"
    )
await _send(ws, {
    "type": "broadcast", "channel": f"_inbox:{agent_id}",
    "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
    "content": reply_text, "ts": time.time(),
})
```

**⚠️ 注意：** 当前 _handle_hash_start 是 _auto_dispatch 的薄包装，需要 _ensure_pipeline_manager() 引用。注意不要引入循环依赖。

### 2.5 A-5：`_try_advance_pipeline` 派活失败通知（P5）

**改动位置：** `_try_advance_pipeline()` L444（`asyncio.ensure_future(_auto_dispatch(ctx, next_step))` 处）

**方案：** 传递 agent_id（完成消息的发送者）作为 `notify_agent_id` 参数。

```python
# 原有（L444）：
asyncio.ensure_future(_auto_dispatch(ctx, next_step))

# 改为：
asyncio.ensure_future(_auto_dispatch(
    ctx, next_step,
    notify_agent_id=agent_id,
))
```

**⚠️ 注意：** `_try_advance_pipeline` 已经接收 `agent_id` 参数（L362），可以直接传递。

---

## 3. 改动范围

| 文件 | 函数 | 改动内容 | 行数估值 |
|:-----|:-----|:---------|:--------:|
| `pipeline_engine.py` | `_handle_hash_advance()` | A-1: L4+ 权限校验替换 PM-only | ±3 行 |
| `pipeline_engine.py` | `_advance_pipeline_direct()` | A-2: **新增函数** — 跨步推进 | +45 行 |
| `pipeline_engine.py` | `_handle_hash_advance()` | A-2: 跨步/单步分支路由 | +5 行 |
| `pipeline_engine.py` | `_auto_dispatch()` | A-3: 增加 `notify_agent_id`/`notify_ws` 参数 + 失败通知 | +20 行 |
| `pipeline_engine.py` | `_handle_hash_start()` | A-4: 回复消息动态化（成功/失败两种模板） | +10 行 |
| `pipeline_engine.py` | `_try_advance_pipeline()` | A-5: 传递 `agent_id` 给 `_auto_dispatch` | +1 行 |
| `pipeline_engine.py` | `_build_notify_payload()` | 辅助函数，封装通知消息构建 | +8 行 |

**合计：** ~+92 行（主要在新增 `_advance_pipeline_direct`）

---

## 4. 执行顺序

```
Step 3 (Dev — 爱泰)：
  ① _handle_hash_advance L4+ 权限替换 (A-1)     — 最简单，先做
  ② _auto_dispatch notify_agent_id 参数 (A-3)    — 被 A-4/A-5 依赖
  ③ _advance_pipeline_direct 新增 + 路由 (A-2)   — 核心新增
  ④ _handle_hash_start 回复修正 (A-4)            — 依赖 A-3
  ⑤ _try_advance_pipeline 传递 agent_id (A-5)   — 依赖 A-3
  ⑥ 编译验证 C1-C3
```

---

## 5. 验收检查表

| # | 验收项 | 验证方法 | 类型 |
|:-:|:-------|:---------|:----:|
| A-1 | L4+ bot 能用 `##advance##R{N}##step=N` | L3 拒绝，L4 通过 | P0 |
| A-2 | `##advance##R140##step=5` 从 Step 2 跳到 Step 5 | 中间步标记 skipped，Step 5 派活 | P0 |
| A-3 | `_auto_dispatch` 模板缺失时通知发起者 | 置空模板 → 收到失败通知 | P0 |
| A-4 | `_auto_dispatch` agent_id 为空时通知发起者 | 置空 agent_id → 收到失败通知 | P0 |
| A-5 | `##start` 派活成功时回复含 agent name | `##start##R{N}` → "派活给 xxx" | P1 |
| A-6 | `##start` 派活失败时回复含失败提示 | 模拟失败 → 看到"请手动推进" | P0 |
| A-7 | `已完成 ✅` 推进后继派活失败通知发送者 | 让下一步派活失败 → 完成者收到通知 | P1 |
| R1 | `##start##R{N}` 正常创建+派活 | 管线创建，Step 1 派活 | P0 |
| R2 | `已完成 ✅ R{N} Step N` 正常推进 | Step 标记 done，下一步派活 | P0 |
| R3 | `##stop##R{N}` 正常停止 | 管线停止 | P0 |
| R4 | `##archive##R{N}` PM 归档正常 | 管线归档 | P0 |
| C1 | `from server.ws_server import pipeline_engine` 无错 | python -c import | P0 |
| C2 | `##advance` 单步推进兼容原行为 | `##advance##R{N}##step=N` 正常推进 | P0 |

---

## 6. 不做事项

| ❌ 不做 | 原因 |
|:--------|:-----|
| 重写 `_auto_dispatch` 同步可靠 | 增量修复，不改架构 |
| 统一 `##step##complete` 与 `##advance` | P6 不在本轮范围 |
| PipelineContext 数据模型改造 | 非本轮目标 |
| `_try_advance_pipeline` 正则匹配改造 | 够用，不改 |
| 自动归档时机调整 | 非本轮目标 |
| 新增 `config.PIPELINE_COORDINATOR_AGENT_ID` | 推荐 L4+ 方案，不新增配置 |

---

> **审核记录：**
> - v1.0 提交审核
> - 关键决策：A-1 采用 L4+ 权限（与 `##step` 一致），不新增配置项
> - 结论：⬜ 待审核
