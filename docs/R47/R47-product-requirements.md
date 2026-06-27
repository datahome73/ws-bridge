# R47 产品需求 — 进度 Tab 数据管线修复

> **版本：** v0.1（初稿，待项目负责人审核）
> **状态：** 📋 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-06-27
> **本轮改动范围：** 仅第①类（服务器代码 `server/handler.py` + 前端模板 `server/templates.py`）

---

## 1. 问题背景

### 1.1 📊 进度 Tab 长期空白

Web 端「📊 进度」Tab 自 R38 引入以来，在后续轮次中几乎没有显示过有效数据。当前数据链：

```
!task_create / !step_complete / 管线启动
  ↓
ts.create_task() / ts.update_state() → task_store DB 写入
  ↓
_task_notify_workspace() → broadcast msg_type="task_notify" 到工作区成员
  ↓
  write_chat_log("系统", "📊 R46 step2: SUBMITTED → WORKING", channel=_admin)
  ↓
前端 renderProgressTab() → GET /api/chat?channel=_admin → filter 📊 → 渲染
```

**实际运行中这条链断裂了两次：**

| 断点 | 现象 | 根因 |
|:-----|:------|:------|
| **① `!step_complete` 调用 `get_tasks_by_context` 不存在** | step 无法完成、无进度更新（F-14） | task_store 中函数名是 `list_tasks_by_context` 不是 `get_tasks_by_context` |
| **② pipepline_start / step_complete 不触发 `_task_notify_workspace`** | task 在 DB 中但进度 Tab 无显示 | 命令逻辑中没调进度通知函数 |

### 1.2 已有基础

| 已有能力 | 状态 | 说明 |
|:---------|:----:|:------|
| `task_store` 模块 | ✅ | 完整 CRUD：create_task / update_state / list_tasks_by_context |
| `_task_notify_workspace()` | ✅ | 写入 `_admin` 频道的 📊 消息 + 推送到 Web 端 WS |
| `renderProgressTab()` | ✅ | 前端解析 `📊 {context} {name}: {transition}` 格式 |
| MSG_TASK_NOTIFY 协议 | ✅ | 双入口（handler.py + __main__.py）均处理 |

---

## 2. 预期体验

### 2.1 改进后

```
管线流程                          进度 Tab 显示
───────                          ────────────
!pipeline_start R47              📊 R47 — 管线已启动
                                   step2 (arch): SUBMITTED

!step_complete Step2              📊 R47 — 管线进行中
                                   step2 (arch): SUBMITTED → COMPLETED 🟢
                                   step3 (dev): SUBMITTED 🆕

!close_workspace                  📊 R47 — 管线已结束
                                   全部 Step: 已完成
```

---

## 3. 需求详述

### 方向 A — 修复数据链断裂 🟡 P2

| # | 需求 | 优先级 |
|:-:|:-----|:------:|
| A-1 | 修复 `handler.py` 中两处 `ts.get_tasks_by_context()` → 改为 `ts.list_tasks_by_context()`（F-14 修复）| 🔴 P1 |
| A-2 | `_cmd_pipeline_start()` 中 task 创建后调用 `_task_notify_workspace()` 写入 📊 消息 | 🟡 P2 |
| A-3 | `_cmd_step_complete()` 中完成旧 task + 创建新 task 时触发 `_task_notify_workspace()` | 🟡 P2 |

### 方向 B — 关闭写结束消息 🟢 P3

| # | 需求 | 优先级 |
|:-:|:-----|:------:|
| B-1 | `!close_workspace` 时如果该 workspace 是活跃管线工作室，写一条 `📊 {round}: 管线已结束` | 🟢 P3 |

---

## 4. 验收标准

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| A-1 | `!step_complete Step2 --output xxx` 不再报错，正常完成 Step | 🔴 P1 |
| A-2 | `!pipeline_status` 不再报错，返回管线状态 | 🔴 P1 |
| A-3 | `!pipeline_start R47` 后 `/api/chat?channel=_admin` 中出现 `📊` 开头的消息 | 🟡 P2 |
| A-4 | `!step_complete` 后 `/api/chat?channel=_admin` 中新增 `📊` 状态更新消息 | 🟡 P2 |
| A-5 | Web 端进度 Tab 打开后显示管线 Step 列表 | 🟡 P2 |
| B-1 | 关闭管线工作室后出现 `📊 R47: 管线已结束` 消息 | 🟢 P3 |

---

## 5. 不纳入本轮需求

| 事项 | 原因 |
|:-----|:------|
| Agent Card 角色声明（F-16）| 独立调研+开发轮 |
| F-3 P3 角色体系 | 独立功能轮 |

---

## 6. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v0.1 | 2026-06-27 | 初稿 — 修复进度 Tab 数据链（F-14）+ 关闭写结束消息 |
