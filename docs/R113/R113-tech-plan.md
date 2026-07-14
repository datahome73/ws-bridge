# R113 Step 2 — 管线自动派活修复技术方案

> **轮次：** R113
> **版本：** v1.0
> **日期：** 2026-07-14
> **审核：** R113 需求文档 §2.2、WORK_PLAN
>
> **设计角色：** 小开（架构师）
> **实现角色：** 爱泰（开发工程师）

---

## 一、概述

R113 是管线自动派活修复轮，改动极小（2 文件 ~8 行）。对 R111 `##start` 落地后暴露的 4 处边缘问题进行定点修复，不引入新功能。

### 改动范围

| 文件 | 改动类型 | 行数 |
|:-----|:---------|:-----|
| `server/ws_server/pipeline_context.py` | ✅ 修改 | ~7 行 |
| `server/ws_server/main.py` | ✅ 修改 | ~2 行 |

| 文件 | 不动原因 |
|:-----|:---------|
| `commands/pipeline.py` | 自有 from_dict 不共用这 5 个索引 |
| `pipeline_sync.py` | 无关联逻辑 |

---

## 二、4 处修复详情

### 2.1 状态转换 → 允许 INIT → RUNNING（1 行）

**问题：** `##start` 最终调用 `mgr.transition_to(..., RUNNING)`，但 INIT 状态的合法转换只有 `{PLANNING, CANCELLED}`，不含 `RUNNING`，导致转换静默失败（`transition_to` 返回 False）。

**修复：** `pipeline_context.py:65` 在 INIT 的合法转换集中增加 `RUNNING`。

```python
# 修复前
PipelineStatus.INIT: {PipelineStatus.PLANNING, PipelineStatus.CANCELLED},

# 修复后
PipelineStatus.INIT: {PipelineStatus.PLANNING, PipelineStatus.RUNNING, PipelineStatus.CANCELLED},
```

**方案选择：** 采用方案 A（1 行加 RUNNING），因为 `##start` 从 INIT 直接到 RUNNING 是业务意图，无需中间 PLANNING 态。

---

### 2.2 5 处硬索引改 .get() + 后备值（5 行）

**问题：** `from_dict()` 中 5 个字段使用 `d["key"]` 直接索引，上游 JSON 缺失对应 key 时抛 `KeyError` 导致整条管线不可恢复。

**修复：** 全部改为 `.get(key, default)`，后备值见需求文档 §2.2。

| 行号 | 字段 | 修复前 | 修复后 |
|:----:|:-----|:-------|:-------|
| 223 | `task_kind` | `PipelineTaskKind(d["task_kind"])` | `PipelineTaskKind(d.get("task_kind", "dev"))` |
| 224 | `workspace_dir` | `Path(d["workspace_dir"])` | `Path(d.get("workspace_dir", ""))` |
| 225 | `task_dir` | `Path(d["task_dir"])` | `Path(d.get("task_dir", ""))` |
| 226 | `workspace_id` | `d["workspace_id"]` | `d.get("workspace_id", "")` |
| 228 | `status` | `PipelineStatus(d["status"])` | `PipelineStatus(d.get("status", "init"))` |

> L222 `round_name` 保留 `d["round_name"]`（必填字段，缺失是调用方 bug）。
> L227/L229 已使用 `.get()`，不重复改。

---

### 2.3 `_load()` 增加 KeyError/ValueError 兜底（1 行）

**问题：** `PipelineContextManager._load()` 的 except 子句仅捕获 `(OSError, json.JSONDecodeError)`，`from_dict()` 抛出的 `KeyError`（字段缺失）或 `ValueError`（枚举值非法）会穿透导致整个 `__init__` 失败，服务无法启动。

**修复：** `pipeline_context.py:714` 增加 `KeyError, ValueError`。

```python
# 修复前
except (OSError, json.JSONDecodeError) as e:

# 修复后
except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
```

> 方案：精确加 KeyError + ValueError，不做 Exception 全覆盖——其他异常（如 OSError）已在 714 由显式分支处理，全覆盖会掩盖真正的 bug。

---

### 2.4 step 搜索匹配 step_key 而非 name（2 行）

**问题：** `_auto_dispatch()` 中搜索 steps 列表时用 `s.get("name") == next_step_key`（即 `"step1"`），但 `StepInfo` 数据结构使用 `step_key` 字段存储 `"step1"`～`"step6"`，`name` 字段存储的是步骤标题（如 `"技术方案"`）。不匹配导致搜索结果永远为 None，派活失败。

**修复：** `main.py:2499` 优先匹配 `step_key`，`step_key` 不存在时降级到 `name`（向后兼容旧 JSON）。

```python
# 修复前
next_step_info = next(
    (s for s in ctx.steps if s.get("name") == next_step_key), None,
)

# 修复后
next_step_info = next(
    (s for s in ctx.steps if s.get("step_key", s.get("name")) == next_step_key), None,
)
```

> `s.get("step_key", s.get("name"))` === `s.get("step_key") or s.get("name")`，确保新数据匹配 step_key、旧数据（仅有 name）降级匹配 name。

---

## 三、验证方法

```bash
# 2.1 状态转换
grep -n 'INIT:' server/ws_server/pipeline_context.py  # 应含 RUNNING

# 2.2 硬索引
sed -n '223,228p' server/ws_server/pipeline_context.py  # 5 行全 .get

# 2.3 异常兜底
grep -n 'except.*KeyError.*ValueError' server/ws_server/pipeline_context.py

# 2.4 step_key 匹配
grep -n 'step_key' server/ws_server/main.py | head -3

# 全部改动行数
git diff dev --stat
```

---

## 四、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-07-14 | 初稿 — 确认 4 方案并推 dev |
