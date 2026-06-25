# Hermes Kanban 调研报告

> **时间：** 2026-06-25
> **目的：** 调查 Hermes Agent 内置 Kanban 看板系统（多 Agent 协作工作队列），分析其对 ws-bridge 的可借鉴点

---

## 目录

1. [调研背景](#1-调研背景)
2. [Hermes Kanban 概述](#2-hermes-kanban-概述)
3. [核心设计详解](#3-核心设计详解)
   - [3.1 Board 看板模型](#31-board-看板模型)
   - [3.2 Task 任务生命周期](#32-task-任务生命周期)
   - [3.3 Worker Lane 工人流水线](#33-worker-lane-工人流水线)
   - [3.4 Dispatcher 调度器](#34-dispatcher-调度器)
   - [3.5 Dashboard 仪表盘](#35-dashboard-仪表盘)
4. [ws-bridge 现有能力对照](#4-ws-bridge-现有能力对照)
5. [可借鉴点分析](#5-可借鉴点分析)
   - [5.1 有参考价值的模式](#51-有参考价值的模式)
   - [5.2 ws-bridge 已覆盖的能力](#52-ws-bridge-已覆盖的能力)
   - [5.3 不匹配的场景](#53-不匹配的场景)
6. [建议下一步](#6-建议下一步)

---

## 1. 调研背景

ws-bridge 本质上是**运行在消息平台上的 Agent-to-Agent 消息总线**，通过 Telegram/Feishu 实现多角色协作。R38 已实现并上线了：
- **流水线任务状态机**（TaskState: submitted/working/completed/failed/canceled/input_required）
- **Web 端进度 Tab**（📊 进度表格视图）
- **角色元数据（Agent Card）**（config/agent_cards.json）

Hermes Agent 是 Nous Research 开发的开源 AI Agent 框架，其内置的 Kanban 系统提供了一套完整的多 Agent 工作队列管理方案。本次调研分析 Hermes Kanban 的设计，作为 ws-bridge 后续演进方向的参考。

---

## 2. Hermes Kanban 概述

> **官网：** https://hermes-agent.nousresearch.com
> **开源：** https://github.com/NousResearch/hermes-agent
> **状态：** 内置功能，随 Hermes Agent 发布

Hermes Kanban 是一个**持久化任务看板系统**，存储在 SQLite 中，为多个 Hermes Agent profile 提供协作工作队列。

### 三个交互表面

| 表面 | 使用者 | 交互方式 |
|:----|:------|:---------|
| 🖥️ **Dashboard 仪表盘** | 人类（你） | `hermes dashboard` → http://127.0.0.1:9119 |
| 💻 **CLI 命令行** | 人类（你） | `hermes kanban create/list/show/complete/...` |
| 🤖 **kanban_* 工具集** | Agent Worker | 9 个专用函数（show、list、complete、block、heartbeat、comment、create、link、unblock） |

三个表面共享同一数据源（`~/.hermes/kanban.db`），保证一致性。

---

## 3. 核心设计详解

### 3.1 Board 看板模型

| 概念 | 说明 |
|:----|:------|
| **Board（看板）** | 隔离的工作队列，默认为 `default`，可创建多个 |
| **多 Board 隔离** | 每个 project/repo/domain 可以有一个独立 Board，Worker 看不到其他 Board 的任务 |
| **存储** | default → `~/.hermes/kanban.db`，其他 → `~/.hermes/kanban/boards/<slug>/kanban.db` |

**与 ws-bridge 对照：** ws-bridge 的工作室（workspace）本质上也起到了隔离作用——每个 R{n} 轮次有自己的工作室频道。但工作室是通信层隔离，不是数据层隔离。

### 3.2 Task 任务生命周期

```
ready → running → blocked / done → archived
```

| 状态 | 含义 |
|:----|:------|
| **ready** | 待认领，dispatcher 匹配 assignee 后 spawn worker |
| **running** | 正在执行中 |
| **blocked** | 阻塞（外部依赖，等待 unblock） |
| **done** | 完成 |
| **archived** | 归档 |

**Task 字段：** title, description, assignee, priority, status, tags, lane, comments, links（支持文档/PR 关联）

**对比 ws-bridge 的 TaskState：**

| ws-bridge TaskState (R38) | Hermes Kanban | 差异 |
|:-------------------------|:--------------|:-----|
| `submitted` | `ready` | 语义等价 |
| `working` | `running` | 名称不同 |
| `completed` | `done` | → `archived` 两步完成 |
| `failed` | `blocked` | ws-bridge 的 fail 是终极态，kanban 的 block 可恢复 |
| `canceled` | — | Kanban 无取消态 |
| `input_required` | `blocked` | Kanban 用 block+comment 表达等待反馈 |

> **关键差异：** ws-bridge 的状态机更贴近「流水线」场景（提交→执行→完成/失败/取消/退回），而 Kanban 更通用（就绪→执行→阻塞/完成→归档）。

### 3.3 Worker Lane 工人流水线

Worker Lane 是 Kanban 的**核心抽象**——一个可路由任务到执行者的通道。

**层级：**

```
Hermes Kanban = 正式任务生命周期 + 审计追踪
Worker Lane   = 一张任务卡的执行者
Reviewer      = 人类/代理人，gate "done"
GitHub PR     = 可合入的产出物（对于代码类 Lane 可选）
```

**三种 Lane 类型：**

| 类型 | 说明 | 适用场景 |
|:----|:------|:---------|
| **Hermes Profile Lane** | 由 Hermes Agent profile 执行任务 | 默认模式，dispatcher spawn Hermes 进程 |
| **外部 CLI Lane** | 封装第三方 CLI（Codex、Claude Code） | 对接其他 AI 工具 |
| **API Worker Lane** | 非 Hermes 服务通过 API 拉取/完成任务 | 任意语言实现的外部 worker |

**注册 Lane 需要提供三要素：**
1. **Assignee 标识字符串** — dispatcher 匹配任务
2. **Spawn 机制** — 如何启动 worker
3. **Contract** — worker 启动后对任务的承诺行为

**与 ws-bridge 对照：**

ws-bridge 的**角色（PM、admin-bot、arch-bot、dev-bot、review-bot、QA-bot）**与 Kanban 的 **Lane** 有概念对应。

| 维度 | Hermes Kanban Lane | ws-bridge 角色 |
|:----|:-------------------|:---------------|
| 身份 | assignee 字符串 | agent_id + paires pairing |
| 启动方式 | Dispatcher 自动 spawn Hermes 进程 | 手动 @mention 唤醒 |
| 生命周期 | 由 Kanban kernel 管理 | 由 WORKFLOW.md 文档规范管理 |
| 任务接收 | Dispatcher 匹配 assignee | 通过大厅/工作室消息路由 |

### 3.4 Dispatcher 调度器

Dispatcher 是 Kanban 的**核心调度引擎**，运行在 Hermes Gateway 内部。

| 特性 | 说明 |
|:----|:------|
| **调度频率** | 默认每 60 秒 tick 一次（可配置） |
| **任务认领** | 自动 claim 所有 `ready` 状态的待执行任务 |
| **Worker 仲裁** | 每个 worker 同时只能 claim 一个任务 |
| **熔断机制** | 连续失败 `failure_limit` 次（默认 2），自动 block 任务 |
| **自动重试** | 可配置 max_retries（覆盖全局 failure_limit） |
| **超时兜底** | 回收 stale 的 claim（worker 心跳中断），重新 mark 为 ready |

**与 ws-bridge 对照：**

ws-bridge 当前没有统一的调度器。Step 交接靠**角色 @mention 人工触发**。R38 的 `!task_create`/`!task_update`/`!task_query`/`!task_list` 命令提供了任务 CRUD，但没有自动调度下一棒。

### 3.5 Dashboard 仪表盘

`hermes dashboard` 启动一个本地 Web 服务器（默认 :9119），提供：
- Kanban Board 可视化（各列状态、任务卡片详情）
- 多种用户故事场景（solo dev、fleet farming、role pipeline）

**与 ws-bridge 对照：**

ws-bridge Web 端已有 **📊 进度 Tab**（R38 实现），基于 `!task_query` 轮询 + 表格渲染，提供任务状态可视化。差异点：

| 维度 | Hermes Kanban Dashboard | ws-bridge 进度 Tab |
|:----|:----------------------|:-----------------|
| 定位 | 全局看板视图 | 以轮次为单位的任务状态表 |
| 交互 | 查看、点击、拖拽 | 只读表格 |
| 数据源 | SQLite DB | WebSocket task_query |
| 更新方式 | 自动 | 30s 轮询 |
| 是否需要 Hermes | ✅ 是 | ❌ 否，独立运行 |

---

## 4. ws-bridge 现有能力对照

ws-bridge 的以下能力已经在 R38 中实现，**覆盖了 Kanban 的部分核心功能**：

### ✅ 任务状态机（R38 已上线）

```python
class TaskState(str, Enum):
    SUBMITTED = "submitted"        # 已排入流水线
    WORKING = "working"            # 正在处理
    COMPLETED = "completed"        # 完成
    FAILED = "failed"              # 锁定失败
    CANCELED = "canceled"          # 已取消
    INPUT_REQUIRED = "input_required"  # 退回修复
```

### ✅ 任务命令体系（R38 已上线）

| 命令 | 功能 |
|:----|:------|
| `!task_create` | 创建任务 |
| `!task_update` | 更新状态（含质量门校验） |
| `!task_query` | 查询任务详情 |
| `!task_list` | 列出轮次任务 |

### ✅ Web 端进度 Tab（R38 已上线，R40 有显示 BUG）

Web 端已有 5 栏 Tab 布局，包含 `📊 进度` Tab：
- 渲染任务状态表格（Step、环节、责任人、状态）
- 30s 定时自动刷新
- Tab 排序：活跃→大厅→管理员→📊进度→历史

### ✅ Agent Card（R38 已上线）

`config/agent_cards.json` 定义了机器可读的角色元数据。

### ✅ Workspace 频道隔离

每个 R{n} 轮次使用独立的工作室频道进行讨论，相当于任务级别的上下文隔离。

---

## 5. 可借鉴点分析

### 5.1 有参考价值的模式

| 模式 | Kanban 实现 | ws-bridge 借鉴价值 |
|:----|:-----------|:-----------------|
| **🔗 Task 链式依赖（Link）** | `kanban_link` 工具可将任务链接，形成前驱/后继关系 | 当前 Step 1→7 的顺序依赖是隐式的（靠 WORK_PLAN 的列表顺序），可以引入显式的前驱/后继字段 |
| **⏱️ 心跳 + 超时回收（Heartbeat）** | Worker 运行中定期 heartbeat，超时后 dispatcher 回收 claim 并重启 | 当前 ws-bridge 没有 worker 存活性检测。点名超时（3分钟）只有基础实现。可以借鉴 heartbeat 机制 |
| **🚦 熔断（Circuit Breaker）** | 连续失败自动 block，避免死循环 | ws-bridge 当前没有重试次数限制。一个任务可能无限次退回修复 |
| **⚙️ 多 Board 隔离** | 每个 project 用独立 Board | ws-bridge 已有工作室隔离，概念等效 |
| **🤖 Worker Lane 可扩展性** | Hermes profile / 外部 CLI / API Worker 三种 Lane | ws-bridge 角色扩展（加新 bot）目前需要手动配置配对、注册权限。可以定义更规范的角色注册流程 |
| **📋 Review Gate** | Reviewer 审批通过才允许 done | ws-bridge 的代码审查（Step 5）已经是 gate，但 `completed` 状态没有被 review gate 保护 |

### 5.2 ws-bridge 已覆盖的能力

| Kanban 功能 | ws-bridge 等价物 | 覆盖度 |
|:-----------|:-----------------|:------:|
| Board（看板） | Workspace + contextId | 🟢 工作室内等价 |
| Task 创建/更新 | `!task_create` / `!task_update` | 🟢 已实现 |
| 状态枚举 | TaskState | 🟢 已实现 |
| 可视化 | Web 📊 进度 Tab | 🟢 已实现（有 BUG 待修复） |
| 角色元数据 | Agent Card (config/agent_cards.json) | 🟢 已实现 |
| 消息路由 | 大厅 + 工作室路由 | 🟢 更丰富（权限 P0-P4 分级） |
| 实时讨论 | Workspace 频道 | 🟢 ws-bridge 独有优势 |

### 5.3 不匹配的场景

| Kanban 特性 | 与 ws-bridge 不匹配的原因 |
|:------------|:------------------------|
| **Dispatcher 自动 spawn worker** | Kanban dispatcher 依赖 Hermes Gateway 运行。ws-bridge 独立运行在 VPS 上，bot 是长期连线的 Telegram/Feishu 实例，不是按需启动的进程 |
| **Hermes Profile 依赖** | worker lane 默认需要独立的 Hermes Agent profile。ws-bridge 的 agent 是 Python bot 进程，无此架构约束 |
| **Dashboard 全局视图** | ws-bridge Web 端已有进度 Tab，且不依赖 Hermes。如果需要更丰富的看板功能，在现有 Web 端扩展比引入 Hermes Dashboard 更直接 |
| **放弃已有基础设施** | ws-bridge 的 workspace 频道隔离、权限体系、WebSocket 协议已运行稳定，不应为移植 Kanban 而重构 |

---

## 6. 建议下一步

### 短期（可参考的设计改进）

1. **🔗 任务链式依赖** — 在 TaskStore 中增加 `depends_on` / `predecessors` 字段，让 Step 1→7 的依赖关系显式化、可查询
2. **⏱️ 超时 + 熔断** — 给任务增加 `max_retries` 字段，在超过重试次数后自动 fail。当前点名超时逻辑可扩展为通用的超时机制
3. **📊 进度 Tab BUG 修复** — R40 进度 Tab 显示空白（F-10）是当前痛点，修复后 ws-bridge 的 Web 端可视化能力即可恢复

### 中期（可选探索）

4. **Worker 心跳** — bot 定期向 TaskStore 报告状态 `alive`，超时未汇报则自动标记任务为 blocked
5. **Link 关系可视化** — Web 进度 Tab 增加依赖箭头，显示哪个任务等哪个任务

### 长期（保留参考）

6. 如果未来 ws-bridge 需要对接跨实例/跨团队的 Agent 协作，Hermes Kanban 或 Google A2A 可以作为**标准化任务交换协议**的蓝本

---

> **结论：** Hermes Kanban 的核心设计（SQLite-backed 任务看板、Lane 抽象、Dispatcher 调度、Heartbeat/Retry/CircuitBreaker 机制）对 ws-bridge 的后续演进有参考价值。但 ws-bridge 的独立架构（VPS 运行、自定义 WebSocket 协议、消息平台路由）决定了**直接迁移 Kanban 的收益有限**，更务实的路径是**提取其中 Task 链式依赖、超时熔断、心跳监控等设计模式**，在 ws-bridge 现有架构中渐进式实现。R38 已完成的 **TaskState 状态机 + Web 进度 Tab + Agent Card** 是正确方向，修复现有 BUG 和补全缺失模块的优先级高于引入新框架。
