# R47 产品需求文档 — 进度 Tab 内容修复

| 字段 | 值 |
|:-----|:----|
| 轮次 | R47 |
| 状态 | v0.1 — 已批准 |
| 类型 | Bug 修复（数据链断裂）+ 补全通知逻辑 |
| 目标 | 让「进度 Tab」在管线运行期间正确展示各 Step 状态，Step 完成时更新，工作室关闭时收回 |

---

## 1. 背景与问题

1. **进度 Tab 存在但无数据**：往轮开发的 `📊` 进度消息机制存在 `_admin` 频道，但前几轮从未观察到数据。`!pipeline_status` 和 `!step_complete` 也无实际输出。
2. **原因：** `handler.py` 中多处调用了 `task_store.get_tasks_by_context()`，但实际方法名为 `list_tasks_by_context()` — 函数名不匹配导致调用静默失败（`AttributeError` 被吞没或未触发）。这是 **F-14** 的根因。
3. **缺少通知串联**：`pipeline_start` 和 `step_complete` 未主动调用 `_task_notify_workspace()`，因此即使 task_store 能查询，也没有触发写入 `📊` 消息的入口。

## 2. 需求范围

本轮聚焦修复**数据链**和**通知链**的断裂点，不做 UI 重构或新功能。

### 2.1 修复 F-14：函数名不匹配

- 将 `handler.py` 中所有 `task_store.get_tasks_by_context(...)` 调用修正为 `task_store.list_tasks_by_context(...)`。
- 涉及位置（基于 v0.4.0 基线）：约 2 处（`pipeline_status` 和 `step_complete` 回调）。
- **验证：** 修正后 `!pipeline_status` 应返回当前 Step 任务清单（含 `task_id` / `title` / `status`）。

### 2.2 串通知链：pipeline_start + step_complete 调用 `_task_notify_workspace`

- `_cmd_pipeline_start()` 在创建管线频道后调用 `_task_notify_workspace()`，向 `_admin` 发出初始 `📊` 进度消息。
- `_cmd_step_complete()` 在标记 Step 完成后调用 `_task_notify_workspace()` 更新同一 `📊` 消息。
- **验证：** 管线运行期间 `_admin` 频道可见 `📊` 消息，内容从 Step 1 开始逐步更新。

### 2.3 管线结束时自动清理进度数据

- `_cmd_workspace_close()` 或 `step_complete(step=N final)` 后，自动关闭进度 Tab（删除或标记完结）。
- 与 `_admin` 频道的 `📊` 消息生命周期对齐：工作室关闭 → 进度消息收回。

### 2.4 非需求

- 不改 UI 模板、不新增 Web API、不重构 task_store。
- 不改 step_complete 的外部触发逻辑（仅在现有 `!step_complete` 流程内追加通知调用）。

## 3. 技术方案

### 3.1 数据流

```
pipeline_start
  └→ _task_notify_workspace() → task_store.list_tasks_by_context()
     └→ 发送 📊 初始进度消息到 _admin

step_complete
  ├→ task_store.list_tasks_by_context() (F-14 修复后正常返回)
  └→ _task_notify_workspace() → 编辑同一 📊 消息 → 更新进度

workspace_close / final step
  └→ 删除/关闭 📊 进度消息
```

### 3.2 改动量预估

- **handler.py:** ~20 行新增/修改（2 处函数名修正 + 3 处通知调用插入 + 1 处关闭清理）
- **无** config.py / task_store.py / 前端改动

## 4. 验收标准

| 编号 | 内容 | 验证方式 |
|:-----|:-----|:---------|
| A1 | F-14 修正后 `!pipeline_status` 能正确返回当前 Step 的任务 | 生产环境人工验证 |
| A2 | `!pipeline_start` 后 `_admin` 频道有 `📊` 初始进度消息 | 生产环境观察 |
| A3 | `!step_complete` 后进度消息更新（状态变化） | 生产环境观察 |
| A4 | 工作室关闭后进度消息自动收回 | 生产环境观察 |

## 5. 风险

- 低风险：纯方法名修正 + 通知追加，不涉及状态机重构。
- 如果 `list_tasks_by_context` 本身有 bug（返回空/报错），则本轮无法修复——列入 TODO 下轮解决。
