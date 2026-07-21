# R140 产品需求 — 管线引擎核心路径修复

> **起草人：** 🧐 PM
> **版本：** v1.0
> **日期：** 2026-07-21
> **依据文档：** `server/ws_server/pipeline_engine.py` 代码调查

---

## 1. 背景与目标

### 1.1 现状

管线引擎（pipeline_engine.py, 2,201 行）是 ws-bridge 的核心调度模块，包含管线创建、自动派活、状态推进、手动推进等全部操作。经代码调查发现以下关键问题：

| # | 领域 | 问题 | 严重度 |
|:-:|:----|:-----|:------:|
| P1 | 启动 | `_auto_dispatch(ctx, 2)` 可能静默失败（模板缺失/agent_id为空），无错误反馈 | 🔴 |
| P2 | 启动 | 回复消息说「Step 1 已派活」，实际派的是 Step 2，误导性用语 | 🟡 |
| P3 | 手动推进 | `##advance` **权限写死 PM-only**，管线协调者（经理）无法使用 | 🔴 |
| P4 | 手动推进 | `##advance` 只能按顺序推进（`completed_step == current_step`），**无法跨步** | 🔴 |
| P5 | 手动推进 | `_auto_dispatch` 失败后无重试/通知机制 | 🟡 |
| P6 | 手动推进 | `##step##complete` 走的是旧 `state._PIPELINE_STATE` 路径，与 pipeline_engine 脱节 | 🟡 |

### 1.2 三条核心路径与问题

#### 路径 A：管线启动（`##start##R{N}##k=v`）

```
##start → handle_hash_start → 创建 PipelineContext
  → current_step=2 (Step 1 自动 ✅)
  → _auto_dispatch(ctx, 2)     ← ❌ 可能静默失败
  → "Step 1 已派活" 回复       ← ❌ 误导性消息
```

**失败场景：**
| 失败原因 | 代码位置 | 表现 |
|:---------|:---------|:-----|
| `AUTO_DISPATCH_ENABLED = False` | L856 | 仅打印日志，不发送 |
| Step 2 模板不存在 | L877-L882 | log warning，不通知任何人 |
| Step 2 agent_id 为空 | L887-L892 | log warning，不通知任何人 |
| agent_id 不是 ws_ 开头且无法 fallback | L897-L909 | log warning，不通知任何人 |

**后果：** 管线已创建，current_step=2，但没有任何 bot 收到派活消息。发起者看到的却是「✅ 已启动」。

#### 路径 B：自动推进（`已完成 ✅` → `try_advance`）

```
已完成 ✅ R{N} Step {N} → _try_advance_pipeline
  → 正则匹配 "已完成 ✅ R(\\d+) Step (\\d+)"
  → 检查 completed_step == current_step
  → 记录 artifacts + 标记 done
  → advance_step() 推进 current_step
  → _auto_dispatch(ctx, next)   ← ❌ 同上，可能静默失败
```

**问题：**
- `_auto_dispatch` 失败后推进已完成（current_step 已前进），但无派活 → 卡死在中间状态
- 最后一步完成后自动归档（L456），没有给协调者审核的机会

#### 路径 C：手动推进（`##advance##R{N}##step=N`）

```
##advance → handle_hash_advance
  → ❌ 权限检查：agent_id != pm_agent_id → 拒绝
  → 构造 "已完成 ✅" 消息
  → 调用 _try_advance_pipeline  ← 同一条路径
```

**🔴 核心 bug：** `##advance` 的权限写死 PM-only（L1155：`if pm_agent_id and agent_id != pm_agent_id`）。管线协调者（经理 bot）**无法使用** `##advance`。

**🔴 核心限制：** 即使能用，`_try_advance_pipeline` 要求 `completed_step == current_step`，所以只能一步一步推进，不能跨步（如从 Step 2 直接跳到 Step 5）。

### 1.3 目标

| # | 目标 | 对应问题 |
|:-:|:-----|:---------|
| G1 | **修复 `##advance` 权限** — 管线协调者也可使用 | P3 |
| G2 | **支持跨步推进** — `##advance##R{N}##step=N` 直接跳到指定步 | P4 |
| G3 | **`_auto_dispatch` 失败通知** — 派活失败时通知发起者，不静默 | P1 |
| G4 | **`##start` 反馈修复** — 回复真实状态，而非误导性消息 | P2 |
| G5 | **重试/通知机制** — 自动派活失败后有补救手段 | P5 |

> P6（`##step##complete` 走旧路径）不在本轮修复范围，留待后续统一。

---

## 2. 功能需求

### 2.1 A-1：`##advance` 权限扩展

**当前：** `##advance` 仅 PM 可用（L1155 写死白名单）。

**目标：** 管线协调者（经理 bot）也可以使用 `##advance`。

**方案：**
```python
# 当前（L1154-L1155）：
pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
if pm_agent_id and agent_id != pm_agent_id:

# 改为：允许 PM 或 协调者（经理）
ALLOWED_ADVANCE_AGENTS = {
    config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID,
    config.PIPELINE_COORDINATOR_AGENT_ID,  # 新增配置项
}
# 去掉 None
ALLOWED_ADVANCE_AGENTS.discard(None)
if ALLOWED_ADVANCE_AGENTS and agent_id not in ALLOWED_ADVANCE_AGENTS:
```

**或者更简单的实现：** L4 权限即可使用 `##advance`（与 `##step` 一致）。

### 2.2 A-2：`##advance` 支持跨步推进

**当前：** `_try_advance_pipeline` 要求 `completed_step == current_step`，只能一步一步推进。

**目标：** `##advance##R{N}##step=N` 可以跳过中间步骤，直接推进到指定步。

**方案：**
```python
# _handle_hash_advance 中，不再构造假完成消息，
# 而是直接操作 PipelineContext：
ctx.current_step = step_num
# 标记 step_num 之前所有未完成的步骤为 skipped
for i, s in enumerate(ctx.steps):
    if i < step_num - 1 and s["status"] == "pending":
        s["status"] = "skipped"
ctx.steps[step_num - 1]["status"] = "active"  # 或 pending
mgr.save()
# 然后派活指定步
await _auto_dispatch(ctx, step_num)
```

### 2.3 A-3：`_auto_dispatch` 失败通知

**当前：** `_auto_dispatch` 静默失败（仅 log warning），发起者不知情。

**目标：** 派活失败时，通知发起者原因。

**方案：**
```python
# _auto_dispatch 新增 notify_ws / notify_agent_id 参数
async def _auto_dispatch(ctx, step_num, notify_ws=None, notify_agent_id=None):
    ...
    if not next_template:
        if notify_agent_id:
            await _send_to_agent(notify_agent_id, {
                "type": "broadcast",
                "channel": f"_inbox:{notify_agent_id}",
                "from_name": "系统",
                "content": f"⚠️ {ctx.round_name} Step {step_num} 派活失败：模板缺失",
            })
        return False
    if not next_step_info or not next_step_info.get("agent_id"):
        # 类似的通知
        ...
```

### 2.4 A-4：`##start` 回复消息修正

**当前：**
```python
"content": f"✅ {round_name} 管线已启动，Step 1 已派活",
```

**目标：** 根据实际派活结果回复不同消息：

```python
if 派活成功:
    "✅ {round_name} 管线已启动，Step 2（技术方案）已派活给 {agent_name}"
else:
    "✅ {round_name} 管线已创建，但 Step 2 自动派活失败：{原因}"
    "请使用 ##advance##{round_name}##step=N 手动推进"
```

### 2.5 A-5：`_try_advance_pipeline` 派活失败后通知

**当前（L437-L456）：** `_try_advance_pipeline` 推进成功后，`asyncio.ensure_future(_auto_dispatch(ctx, next_step))` — 也静默处理。

**目标：** 推进成功后，`_auto_dispatch` 如果失败，通过原 WS 连接通知发起者。

---

## 3. 改动范围

| 文件 | 变更 | 行数变化 |
|:-----|:------|:--------:|
| `pipeline_engine.py` | `_handle_hash_advance` 权限+跨步逻辑 | +~50 行 |
| `pipeline_engine.py` | `_auto_dispatch` 增加通知参数 | +~30 行 |
| `pipeline_engine.py` | `_handle_hash_start` 回复消息修正 | +~10 行 |
| `pipeline_engine.py` | `_try_advance_pipeline` 派活失败通知 | +~10 行 |
| `server/common/config.py` | 可选：新增 `PIPELINE_COORDINATOR_AGENT_ID` 配置 | +~3 行 |

---

## 4. 验收标准

| # | 验收项 | 类型 |
|:-:|:-------|:----:|
| A-1 | 经理（非 PM 的 L4 bot）能用 `##advance##R{N}##step=N` | P0 |
| A-2 | `##advance##R{N}##step=5` 从 Step 2 直接跳到 Step 5（中间步标记 skipped） | P0 |
| A-3 | `##advance` 跨步后正确派活指定步 | P0 |
| A-4 | `_auto_dispatch` 模板缺失时，通知发起者而非静默 | P0 |
| A-5 | `_auto_dispatch` agent_id 为空时，通知发起者 | P0 |
| A-6 | `##start` 回复显示"Step 2 已派活给 {name}"（而非"Step 1 已派活"） | P1 |
| A-7 | `##start` 派活失败时，回复显示失败原因 | P0 |
| A-8 | `已完成 ✅` 推进后若派活失败，通知完成消息发送者 | P1 |
| R1 | `##start` 正常创建管线 + 派活 | P0 |
| R2 | `已完成 ✅ Step N` 正常推进（不破坏现有流程） | P0 |
| R3 | `##stop` 正常停止 | P0 |
| R4 | 编译无错误：`python3 -c "from server.ws_server import pipeline_engine"` | P0 |

---

## 5. 不做事项

| ❌ 不做 | 原因 |
|:--------|:-----|
| 重写 `_auto_dispatch` 为同步可靠方式 | 增量修复，不改整体架构 |
| 统一 `##step##complete` 与 `##advance` | 旧 `!` 命令路径不在本轮范围 |
| PipelineContext 数据模型改造 | 非本轮目标 |
| `_try_advance_pipeline` 正则匹配改造 | 可用，不改 |
| 自动归档拿掉或改为可选 | 非本轮目标 |

---

## 6. 验收检查表总览

| 分组 | 检查项数 | P0 | P1 |
|:----|:--------:|:--:|:--:|
| 功能验收 A-1~A-8 | 8 | 6 | 2 |
| 回归验收 R1~R4 | 4 | 4 | — |
| **合计** | **12** | **10** | **2** |

---

> **审核记录：**
> - v1.0 提交审核
> - 结论：⬜ 待审核
