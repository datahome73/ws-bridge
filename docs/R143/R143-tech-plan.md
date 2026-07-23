# R143 技术方案 — 跨步状态同步修复轮

> **轮次：** R143
> **类型：** 🛠️ 跨步状态同步修复轮
> **角色：** 🏗️ 架构师 小开
> **日期：** 2026-07-23
> **基于：** `5f27161`（R142 Step 2 技术方案已推）
> **状态：** ✅ 定稿

---

## §0 本轮定位与范围

### 0.1 一句话目标

修复 `##advance` 跨步推进时 **仅跳过 `pending` 状态步、遗漏 `in_progress` 中间步** 导致超时假报警的 bug。

### 0.2 依赖文档

| 文档 | 位置 | 状态 |
|:-----|:-----|:----:|
| 需求文档 | `docs/R143/R143-product-requirements.md` | ✅ |
| 工作计划 | `docs/R143/WORK_PLAN.md` | ✅ |

### 0.3 范围声明

| 包含 | 不包含 |
|:-----|:-------|
| ✅ `##advance` 跨步条件修复（1 行条件 + 2 行清理） | ❌ B-5 重复派活（P3，bot 静默忽略，仅 Web 端视觉问题） |
| ✅ `dispatched_at` 清除（防止超时扫描误判） | ❌ R-1 超时去噪（根因即本 bug，修复后自然消失） |
| ✅ 增强日志（记录原状态名以便排查） | ❌ 测试/审查/部署流程（由对应角色推进） |

---

## §1 问题分析

### 1.1 根因定位（行号级审计）

**函数：** `server/ws_server/pipeline_engine.py` → `_handle_hash_advance()`

```python
# L1296 — 跨步循环条件（当前代码）
if step_num_i < step_num and s.get("status") in ("pending",):
```

**问题：** 条件仅匹配 `"pending"` 一种状态。当 `step.get("status")` 为以下值时均不命中：

| 状态 | 是否被跳过 | 结果 |
|:-----|:----------:|:-----|
| `"pending"` | ✅ 是 | 正常 |
| `"in_progress"` | ❌ **否 — bug 根因** | 遗留为 in_progress，触发超时假报警 |
| `"failed"` | ❌ 否 | 遗留为 failed（低风险，`failed` 步不会触发超时） |
| `"done"` | ✅ 否（正确） | 已完成的步不应降级 |
| `"skipped"` | ❌ 否 | 已跳过的步保持不动（无影响） |
| `"timeout"` | ❌ 否 | 超时步保持不动（无影响） |

### 1.2 触发链路

```
##advance##R143##step=4
  → _handle_hash_advance()
  → L1296: step_num_i=2 < step_num=4, but s["status"]="in_progress" not in ("pending",)
  → Step 2 状态不变（仍 in_progress）
  → _try_advance_pipeline() 推进管线到 Step 4
  → 30分钟后 _pipeline_timeout_scan()
  → L2219: step.get("status") == "in_progress" → YES
  → L2221: dispatched_at != None → YES
  → L2233: elapsed >= 30min → YES
  → ⏰ 发超时告警「Step 2 已超时 30 分钟」— 假报警！
    （实际管线已在 Step 4 正常运行）
```

### 1.3 超时扫描器逻辑（L2207-2247）

```python
# L2219: 第一筛条件
if step.get("status") != "in_progress":
    continue
# L2221-2223: 第二筛条件
dispatched_at = step.get("dispatched_at")
if not dispatched_at:
    continue
```

**结论：** 想让超时扫描器跳过已推进的步，需同时满足：
1. `status != "in_progress"` — 即改为 `"skipped"`
2. 清除 `dispatched_at` 字段（消除第二筛入口）

两个条件缺一不可。仅改 status 不删 `dispatched_at`，扫描器在 `timeout_alerted` 为 False 的情况下仍可能在不同 tick 中触发。

---

## §2 方案设计

### 2.1 改动 F-1：跨步条件修复

**文件：** `server/ws_server/pipeline_engine.py` _handle_hash_advance L1296-L1302

**改动前：**

```python
if step_num_i < step_num and s.get("status") in ("pending",):
    s["status"] = "skipped"
    logger.info("[R140] %s step%d skipped（##advance 跨步）",
                round_name, step_num_i)
```

**改动后：**

```python
if step_num_i < step_num and s.get("status") not in ("done",):
    s["status"] = "skipped"
    s.pop("dispatched_at", None)  # R143: 清除时间戳，防止超时扫描误判
    logger.info("[R143] %s step%d → skipped（##advance 跨步，原状态=%s）",
                round_name, step_num_i, s.get("status"))
```

### 2.2 语义变化矩阵

| 原状态 | 旧条件 `in ("pending",)` | 新条件 `not in ("done",)` | 语义正确性 |
|:-------|:------------------------:|:-------------------------:|:----------:|
| pending | → skipped ✅ | → skipped ✅ | ✅ 一致 |
| **in_progress** | → **不动 ❌** | → **skipped ✅** | ✅ 修复 |
| failed | → 不动 | → skipped | ✅ 合理（失败步不应阻塞跨步） |
| done | → 不动 | → 不动 | ✅ not in ("done",) 不命中 |
| skipped | → 不动 | → 不动（保持 skipped） | ✅ 幂等 |
| timeout | → 不动 | → skipped | ✅ 超时步被跳过合理 |

### 2.3 日志增强说明

旧日志：`"[R140] %s step%d skipped（##advance 跨步）"`
新日志：`"[R143] %s step%d → skipped（##advance 跨步，原状态=%s）"`

**改动原因：** 跨步现在覆盖更多原状态，记录原状态名有助于排查跳步后的异常行为。`s.get("status")` 在 L1296 之后已被设为 `"skipped"`，但原状态值已在 L1296 的条件判断中被读取（因为条件 `not in ("done",)` 已检查过它），所以 logger 中 `s.get("status")` 实际上返回的是 `"skipped"`。需在修改前保存原状态。

**修正实现：**

```python
if step_num_i < step_num and s.get("status") not in ("done",):
    old_status = s.get("status", "unknown")  # 在修改前保存
    s["status"] = "skipped"
    s.pop("dispatched_at", None)
    logger.info("[R143] %s step%d → skipped（##advance 跨步，原状态=%s）",
                round_name, step_num_i, old_status)
```

> ⚠️ **设计注意点：** `old_status` 必须在 `s["status"] = "skipped"` 之前读取，否则日志会误记为 `"skipped"`。

---

## §3 依赖与执行顺序分析

### 3.1 代码依赖关系

| 依赖项 | 类型 | 是否受影响 | 说明 |
|:-------|:-----|:----------:|:-----|
| `_pipeline_timeout_scan` | 运行时依赖 | ✅ 受益 | 跳步后 in_progress → skipped + dispatched_at 清除，直接消除假报警 |
| `_try_advance_pipeline` | 顺序依赖 | ❌ 不相关 | 推进逻辑不变，仅前置状态标记修正 |
| `_auto_dispatch` | 顺序依赖 | ❌ 不相关 | 派活逻辑不变，仅接收已修正的 step 状态 |
| `state.SYSTEM_AGENT_ID` | import 依赖 | ❌ 不相关 | 已存在，不新增引用 |
| scenario_matcher | lazy import | ❌ 不相关 | 不变 |

### 3.2 执行顺序

```
_handle_hash_advance() 被调用
  ├─ L1262: 权限检查（不变）
  ├─ L1275-1286: 参数解析（不变）
  ├─ L1292-1302: ⭐ 跨步循环（本轮改动点）
  │    └── 条件从 in ("pending",) → not in ("done",)
  │    └── 新增 s.pop("dispatched_at", None)
  │    └── 日志增强（记录原状态名）
  ├─ L1304-1306: 构造完成消息（不变）
  ├─ L1306: _try_advance_pipeline()（不变）
  └─ L1318: _auto_dispatch()（不变）
```

### 3.3 风险——原状态日志取值顺序

**问题：** 如 §2.3 所述，`s.get("status")` 在 `s["status"] = "skipped"` 之后读取会返回 `"skipped"` 而非原始状态。

**解决方案：** 用 `old_status` 变量保存原始值，在修改 `s["status"]` 之前读取。已体现在实现代码中。

---

## §4 验收表

| 编号 | 描述 | 测试场景 | 预期 | 优先级 |
|:----|:-----|:---------|:-----|:------:|
| AS-1 | `##advance` 跳步后 `in_progress` 中间步 → `skipped` | Step 2 in_progress, `##advance##R{N}##step=4` | Step 2 status == "skipped" | 🔴 P1 |
| AS-2 | `##advance` 跳步后 `done` 中间步保持 `done` | Step 2 done, `##advance##R{N}##step=4` | Step 2 status 保持 "done" | 🔴 P1 |
| AS-3 | 被跳过 step 清除 `dispatched_at` | 跳步后检查被跳过步 | 无 `dispatched_at` 字段 | 🔴 P1 |
| AS-4 | 目标 step 保持 `in_progress` | `##advance##R{N}##step=4` | Step 4 status == "in_progress" | 🔴 P1 |
| AS-5 | `pending` 中间步正常跳过（回归） | Step 1 pending, 跳步到 Step 4 | Step 1 → skipped | 🔴 P1 |
| AS-6 | 修复后不触发超时扫描 | 跳步后检查被跳过步 | 超时扫描器跳过该步 | 🔴 P1 |

---

## §5 侧效应分析

| # | 侧效应 | 影响 | 严重度 | 缓解措施 |
|:-:|:-------|:-----|:------:|:---------|
| 1 | `failed` 状态步被跳过 | 手工 `##advance` 跨步时 failed 步不会阻塞，恢复到 failed 步需要重新处理 | 🟡 P2 | 手工推进的目的是跳过当前路径，failed 步确实不应阻塞跨步；如果要重做 failed 步，需手动回退 |
| 2 | `timeout` 状态步被跳过 | 同上逻辑，timeout 步不再阻止跨步 | 🟢 P3 | 同 failed 步，跨步推进语义本身是「跳过中间所有未完成步」 |
| 3 | 跨步时所有 `pending` 步同时被跳过 | 如果同时有 Step 1 pending + Step 3 pending，跳步到 Step 4 时两者都变 skipped | 🟢 P3 | 这是已有行为（R140 A-2 设计），本轮未改变 |

---

## §6 不做事项清单

| # | 事项 | 原因 |
|:-:|:-----|:-----|
| 1 | ❌ `_try_advance_pipeline` 增加跨步校验 | 超时要的是推进后状态正确，而不是阻拦推进 |
| 2 | ❌ 超时扫描器增加「跳过已跳步管线」逻辑 | 超时扫描器职责只在检测真超时，跨步状态修正由 advance 自己负责 |
| 3 | ❌ B-5 重复派活修复 | 非功能性 bug，bot 端静默忽略，不占本轮 |
| 4 | ❌ R-1 超时去噪 | 根因已修复（本 bug），修复后自然消失 |
| 5 | ❌ 修改 `pipeline_context.py` 的数据结构 | 本轮不涉及 context 层面改动 |
| 6 | ❌ 新增单元测试文件 | 改动极小（+4/-1 行），代码审查即可覆盖全部验收标准 |

---

## §7 改动概要

| 维度 | 值 |
|:-----|:----|
| **目标文件** | `server/ws_server/pipeline_engine.py` |
| **目标函数** | `_handle_hash_advance()` — L1296 |
| **改动模式** | 1 行条件修改 + 2 行清理 + 1 行日志增强 |
| **行数统计** | **+4/-1**（净增 3 行） |
| **风险等级** | 🟢 低——仅改变跨步时的状态标记逻辑，不影响正常推进路径 |
| **回归风险** | 无——done 步保护在 `not in ("done",)` 中，不会降级已完成的步 |

---

## §8 变更记录

| 日期 | 版本 | 变更 |
|:----|:----:|:-----|
| 2026-07-23 | v1.0 | 初版 — 跨步状态同步修复技术方案 |
