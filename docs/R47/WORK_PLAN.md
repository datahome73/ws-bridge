# R47 工作计划 — 进度 Tab 数据管线修复

> **版本：** v1.0（初稿，待项目负责人审核）
> **状态：** 📋 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-06-27

---

## 角色分工

| 角色 | 职责 |
|:-----|:------|
| 🧐 PM | 需求文档 + 工作计划 + 协调 |
| 🏗️ arch-bot | 技术方案 |
| 💻 dev-bot | 编码实现 |
| 🔍 review-bot | 代码审查 |
| 🦐 qa-bot | 测试验证 |

---

## 流水线步骤

| Step | 名称 | 负责人 | 产出 | 状态 |
|:----:|:-----|:------|:-----|:----:|
| 🔶 A | **需求文档** | 🧐 PM | `docs/R47/R47-product-requirements.md` v0.1 | 🆕 待审核 |
| 🔶 B | **工作计划** | 🧐 PM | 本文档 v1.0 | 🆕 待审核 |
| 🟢 1 | **管线启动** | 🧐 PM | `!pipeline_start R47` | ⏳ |
| 🟢 2 | **技术方案** | 🏗️ arch-bot | `docs/R47/R47-tech-plan.md` | ⏳ |
| 🟢 3 | **编码** | 💻 dev-bot | `handler.py` ~20 行改动 | ⏳ |
| 🟢 4 | **代码审查** | 🔍 review-bot | `docs/R47/R47-code-review.md` | ⏳ |
| 🟢 5 | **测试** | 🦐 qa-bot | `docs/R47/R47-test-report.md` | ⏳ |
| 🟢 6 | **合并部署归档** | 🦸 admin-bot | 合并 dev→main，更新 TODO.md F-14 | ⏳ |

---

## 详细说明

### Step 2 — 技术方案

1. `handler.py` 中两处 `ts.get_tasks_by_context` → `ts.list_tasks_by_context`（F-14 修复）
2. `_cmd_pipeline_start()` 中 task 创建后调用 `_task_notify_workspace()`
3. `_cmd_step_complete()` 中状态变更时触发通知
4. `_cmd_close_workspace()` 检查管线状态，写结束消息

### Step 5 — 测试

- A-1/A-2: `!pipeline_status` + `!step_complete` 不再报错
- A-3/A-4: `/api/chat?channel=_admin` 出现 📊 消息
- B-1: 关闭后出现结束消息

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-06-27 | 初稿 — 修复进度 Tab 数据链（F-14） |
