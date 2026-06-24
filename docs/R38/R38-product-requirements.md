# R38 产品需求 — 流水线任务状态机 + Agent 协作体系

> **版本：** v0.2（草稿，基于项目负责人问答收敛）
> **状态：** 📋 草稿（待审核）
> **产品经理：** 🧐 PM
> **日期：** 2026-06-24
> **参考：** [A2A 协议调研报告](../A2A-Protocols-Research-Report.md)

---

## 0. 改动范围

> **本轮改动范围：** 第①类（服务器代码 `server/`）+ 第④类（Web 端 `server/web_viewer.py`, `server/templates.py`），连带文档和协议常量。

**原因：** 任务状态机需要在服务端（消息路由、任务分发）和 Web 端（状态可视化）两端同时落地，缺一端则状态机不可观测。Agent Card 元数据与状态机共用数据模型，一起做互相关联，代码量大但能快速解决问题。

---

## 1. 背景与问题

### 1.1 调研背景

本团队对现有 A2A（Agent-to-Agent）开源协议做了全面调研，覆盖 Google A2A Protocol、Anthropic MCP、OpenAI Agents SDK、FIPA-ACL、AutoGen 等主流协议。调研报告详见 [A2A 协议调研报告](../A2A-Protocols-Research-Report.md)。

核心发现：ws-bridge 本质上已是一个 **Agent-to-Agent 消息总线**，但缺少标准化的**任务生命周期管理**和**自描述 Agent 元数据**。Google A2A Protocol（v1.0，Apache 2.0）中的 Task 状态机设计模式与 ws-bridge 流水线高度吻合，可借鉴落地。

### 1.2 当前痛点

| # | 痛点 | 说明 |
|:-:|:-----|:------|
| ① | **流水线步骤状态不明确** | 每个 Step 是「待启动」「进行中」「已完成」「已驳回」——全靠人脑跟踪 WORK_PLAN 表格，系统不记录 |
| ② | **审查驳回无系统级挂起** | 代码审查驳回后步骤停在中间态，文档里的 🟡 退回标记不是系统状态，无法编程判断 |
| ③ | **跨步骤上下文无统一 ID** | 一个轮次的多个步骤、多轮消息之间没有绑定关系，各步骤产出没有结构化关联 |
| ④ | **Agent 能力不可编程查询** | 各角色能力只写在 WORKSPACE_RULES.md 里供人读，没有机器可读的元数据供路由引用 |
| ⑤ | **进度不可实时查看** | 当前进度靠 WORK_PLAN.md 文档手动更新，Web 端看不到任何任务状态 |

### 1.3 核心原则（本设计遵照执行）

> **自己完成本环节的任务后，把好自己的质量关，合格就推进到下一环节，不合格就退回。**

这条原则贯穿整个设计——每个 Agent 完成自己的 Step 后，由执行者/审查者决定流转方向，系统执行状态转换。

---

## 2. 需求设计

### 2.1 Task 状态机 — 以 Step 为粒度

借鉴 Google A2A 的 Task 状态机模型，**每个 Step 对应一个 Task 实例**。Step 即之前需求文档中定义的「短任务」——每个 Agent 自己环节完成的独立任务单元。

```
               ┌──────────┐
               │SUBMITTED │  （Step 已创建，待启动）
               └────┬─────┘
                    │
               ┌────▼─────┐
               │  WORKING  │  （Step 进行中）
               └────┬─────┘
                    │
       ┌────────────┼────────────┐
       │            │            │
┌──────▼────┐ ┌─────▼─────┐ ┌───▼────┐
│ COMPLETED │ │  FAILED   │ │CANCELED │
└───────────┘ └───────────┘ └────────┘
       │            │
       │     ┌──────▼────────┐
       │     │INPUT_REQUIRED │←── 审查驳回/需要输入
       │     └──────┬────────┘
       │            │（修复后重提）
       │     ┌──────▼────────┐
       │     │   WORKING     │
       │     └──────┬────────┘
       │            │
       └────(最终态)─┘
```

**状态与 ws-bridge 映射：**

| Task 状态 | WORK_PLAN 标记 | 含义 |
|:----------|:--------------:|:-----|
| `SUBMITTED` | ⬜ 待启动 | Step 已排入流水线，等待分配执行者 |
| `WORKING` | ▶ 进行中 | 执行者正在处理该 Step |
| `COMPLETED` | ✅ 已完成 | 执行者/审查者确认合格，本 Step 完成 |
| `FAILED` | ❌ 失败 | 二次退回后仍不合格，锁定终止 |
| `CANCELED` | ⛔ 已取消 | 任务主动取消（如轮次范围变更） |
| `INPUT_REQUIRED` | 🟡 驳回待修 | 审查者判定不合格，退回修复 |

**状态转换规则：**

```
SUBMITTED ──→ WORKING        ✅ 任务启动
WORKING   ──→ COMPLETED      ✅ 执行者自评通过（或审查者判通过）
WORKING   ──→ INPUT_REQUIRED ✅ 审查者判不合格退回
WORKING   ──→ FAILED         ✅ 执行异常/不可恢复错误
WORKING   ──→ CANCELED       ✅ 主动取消
INPUT_REQUIRED ──→ WORKING   ✅ 修复后重提，回到进行中
INPUT_REQUIRED ──→ FAILED    ✅ 第二次仍不合格，锁定（不可再重提）
SUBMITTED ──→ COMPLETED      ❌ 禁止跳过执行
COMPLETED ──→ WORKING        ❌ 禁止重新激活
```

### 2.2 Task 实例数据模型

每个 Task 实例包含：

| 字段 | 类型 | 说明 |
|:-----|:-----|:------|
| `task_id` | UUID | 全局唯一 Task 标识 |
| `context_id` | string | 轮次 ID（如 `R38`），分组一组相关 Task |
| `step` | int | Step 编号（如 1, 2, 3…） |
| `name` | string | Step 名称（如「编码」「代码审查」） |
| `state` | TaskState | 当前任务状态 |
| `assigned_role` | string | 当前执行者角色 ID（如 `dev-bot`） |
| `created_at` | timestamp | 创建时间 |
| `updated_at` | timestamp | 最后更新时间 |
| `output_refs` | string[] | 产出引用列表（commit SHA / 文件路径 / 报告链接） |

**持久化：** Task 实例存入 SQLite（复用 `message_store` 或新建 `task_store` 表），服务重启后状态不丢失。

### 2.3 流程流转规则（自质量门）

> 每个 Agent 完成自己环节的任务后，把好自己的质量关，合格就下一环节，不合格就退回。

**一般 Step（非审查 Step）：**

```
执行者完成工作 ──→ 执行者自评质量：
    合格    ──→ MSG_TASK_UPDATE(state=COMPLETED) ──→ 下一步 SUBMITTED
    不合格  ──→ MSG_TASK_UPDATE(state=INPUT_REQUIRED) ──→ 自己返工
```

**审查 Step（代码审查/方案审查）：**

```
审查者评估产出：
    合格    ──→ MSG_TASK_UPDATE(state=COMPLETED) ──→ 下一步 SUBMITTED
    不合格  ──→ MSG_TASK_UPDATE(state=INPUT_REQUIRED) ──→ 通知开发修复
```

**关键约束：**
- **谁完成谁负责决策流转方向** — 执行者/审查者自己决定是 COMPLETED 还是 INPUT_REQUIRED
- 系统只记录状态、执行合法转换校验，不做自动化判定
- 两次 `INPUT_REQUIRED → WORKING` 后达到上限 → 自动锁定为 `FAILED`

### 2.4 新增消息类型

在 `shared/protocol.py` 中新增：

| 消息类型 | 方向 | 用途 |
|:---------|:-----|:------|
| `MSG_TASK_CREATE` | Agent → 服务端 | 创建新 Task（如排入一个新 Step） |
| `MSG_TASK_UPDATE` | Agent → 服务端 | 更新 Task 状态（执行者/审查者操作） |
| `MSG_TASK_QUERY` | Agent/Web → 服务端 | 查询 Task 列表（按 contextId/按状态） |
| `MSG_TASK_NOTIFY` | 服务端 → Agent | Task 状态变更主动推送通知 |

### 2.5 Agent Card（角色元数据）

为每个 Agent 定义机器可读的能力清单。与 Task 状态机共用数据模型——Task 的 `assigned_role` 字段引用 Agent Card 中的角色 ID。

**Agent Card 定义示例（配置文件中）：**

```json
{
  "agent_id": "pm-bot",
  "display_name": "PM Bot",
  "roles": ["product-manager"],
  "skills": [
    {"id": "write-requirements", "description": "撰写需求文档"},
    {"id": "review-requirements", "description": "评审需求"},
    {"id": "schedule-work", "description": "编排工作计划"}
  ],
  "triggers": ["!pm", "!需求"],
  "state": "online"
}
```

**当前角色映射（配置级，不硬编码）：**

| 角色 ID | 职责 | 涉及的 Step |
|:--------|:-----|:-----------|
| `admin-bot` | 全平台管理、工作室创建、合并部署 | Step 0.5, Step 9 |
| `pm-bot` | 需求文档、方向决策 | Step 1 |
| `arch-bot` | 技术方案、架构设计 | Step 2 |
| `dev-bot` | 编码实现 | Step 3 |
| `review-bot` | 代码审查 | Step 4 |
| `qa-bot` | 测试验证 | Step 5 |

**用途：**
- `MSG_TASK_CREATE` 时通过 `assigned_role` 自动路由通知到对应 Agent
- Web 端任务面板显示「工作人」列时从 Agent Card 获取 `display_name`
- 新 Agent 加入时只需注册 Agent Card，路由和任务分配自动生效

### 2.6 Web 端任务进度 Tab

在 Web 聊天室中新增一个**任务进度 Tab**，内容即当前 WORK_PLAN 表格的格式化展示。

**Tab 布局（新增一个 Tab，与大厅/工作室/历史并列）：**

```
┌──────────────────────────────────────────────┐
│ [大厅] [工作室] [历史] [📊 进度]           │
├──────────────────────────────────────────────┤
│                                              │
│  ┌─ R38 ─────────────────────────────────┐  │
│  │ Step │ 环节名称     │ 工作人   │ 状态 │  │
│  │ :--- | :----------- | :------- | :---  │  │
│  │  1   │ 需求文档     │ PM Bot   │ ✅   │  │
│  │  2   │ 技术方案     │ Arch Bot │ ▶    │  │
│  │  3   │ 编码         │ Dev Bot  │ ⬜   │  │
│  │  4   │ 代码审查     │ Rev Bot  │ ⬜   │  │
│  │  5   │ 测试         │ QA Bot   │ ⬜   │  │
│  │  6   │ 合并部署     │ Admin    │ ⬜   │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌─ R37 ─────────────────────────────────┐  │
│  │ Step │ 环节名称     │ 工作人   │ 状态 │  │
│  │ ...                                    │  │
│  └────────────────────────────────────────┘  │
│                                              │
└──────────────────────────────────────────────┘
```

**表格列：**
| 列 | 数据来源 | 说明 |
|:---|:---------|:-----|
| **Step** | Task.step | Step 编号 |
| **环节名称** | Task.name | 如「需求文档」「技术方案」「编码」 |
| **工作人** | Task.assigned_role → Agent Card.display_name | 从 Agent Card 查角色显示名 |
| **状态** | Task.state | ✅ ▶ ⬜ 🟡 ❌ ⛔ 对应 TaskState |

**刷新机制：**
- 页面加载时调用 `MSG_TASK_QUERY(context_id=R{N})` 获取当前轮次所有 Task
- 定时轮询（每 30s）或 SSE 推送 `MSG_TASK_NOTIFY`
- 状态变更时 Tab 标题显示未读 dot（如 `📊 进度●`）

---

## 3. 验收标准

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| **P-1** | `shared/protocol.py` 中有 `TaskState` 枚举，6 种状态定义完整，转换规则按 §2.1 执行 | P0 |
| **P-2** | `server/` 中有 Task 实例数据模型（task_id, context_id, step, name, state, assigned_role 等字段）| P0 |
| **P-3** | Task 可通过 `MSG_TASK_CREATE` 创建，服务端返回 `task_id` 和初始 `SUBMITTED` 状态 | P0 |
| **P-4** | Task 状态可通过 `MSG_TASK_UPDATE` 推进，合法转换允许、非法转换（如 COMPLETED→WORKING）返回错误 | P0 |
| **P-5** | Task 持久化到 SQLite，服务重启后所有状态不丢失 | P1 |
| **P-6** | `MSG_TASK_QUERY` 按 contextId 返回该轮次所有 Task 及其当前状态，按 step 排序 | P0 |
| **P-7** | `MSG_TASK_NOTIFY` 在 Task 状态变更时推送通知给所有关联 Agent | P1 |
| **P-8** | 审查者可通过 `MSG_TASK_UPDATE` 将审查 Step 设为 COMPLETED（通过）或 INPUT_REQUIRED（驳回）| P0 |
| **P-9** | INPUT_REQUIRED 状态下修复后可再次 `MSG_TASK_UPDATE → WORKING`，第二次仍不合格自动锁定 FAILED | P1 |
| **P-10** | `shared/protocol.py` 中新增 4 种消息类型常量（MSG_TASK_CREATE/UPDATE/QUERY/NOTIFY）| P0 |
| **P-11** | 有一份 Agent Card 配置文件（或持久化表），定义所有角色的 ID、名称、技能、触发词、当前状态 | P1 |
| **P-12** | MSG_TASK_CREATE 的 `assigned_role` 引用 Agent Card 角色 ID，路由通知到对应 Agent | P1 |
| **P-13** | Web 端新增任务进度 Tab，表格展示：Step、环节名称、工作人、状态 4 列 | P0 |
| **P-14** | 任务进度 Tab 按 contextId（轮次）分组，显示最近 3 个轮次进度 | P1 |
| **P-15** | 任务进度 Tab 定时刷新（轮询 30s 或 SSE），状态变更 ≤5s 内可见 | P1 |
| **P-16** | 双入口同步：`handler.py::handler()` 和 `__main__.py::ws_handler()` 均支持以上所有消息类型 | P0 |

---

## 4. 不纳入本次需求

| 不纳入项 | 说明 |
|:---------|:------|
| Google A2A 全协议兼容 | 仅借鉴 Task 状态机模式，不实现 HTTP/gRPC 传输层或 Agent Card JWT 签名 |
| Agent 动态发现注册 | 暂不实现 `/.well-known/agent.json` 或注册表广播，配置级定义即可 |
| Streaming/Push 双模式 | 长时间任务流式推送暂不纳入 |
| Part 容器（多模态消息） | A2A Part 设计是较深的消息模型改造，单独论一轮 |
| 独立任务管理页面 | 仅 Tab 面板展示，不做 Full Screen HUD |
| Agent Card 签名认证 | 内部环境暂不需要 JWT/证书级身份验证 |

---

## 5. 决策记录（Q&A 收敛）

以下是对 v0.1 开放问题的项目负责人决策，已对应体现在 §2 需求设计中：

| # | 问题 | 决策 | 体现 |
|:-:|:-----|:-----|:-----|
| Q1 | 方向 A + 方向 B 合并还是分两轮？ | **一起做** — 互相关联，代码量大但能快速解决问题 | §2.5 Agent Card 合并入此轮 |
| Q2 | 状态机绑轮次还是绑 Step？ | **绑 Step** — 每个 Agent 自己环节完成的任务，即之前说的短任务 | §2.1 每个 Step 一个 Task |
| Q3 | Web 端任务面板怎么做？ | **新增进度 Tab** — 把 WORK_PLAN 表格格式化展示，4 列：Step、环节名称、工作人、状态 | §2.6 |
| Q4 | 审查驳回自动还是手动？ | **审查者决定** — 自己完成本环节任务后，把好质量关，合格下一环节，不合格退回 | §2.3 流转规则 |

---

## 6. 参考文档

- [A2A 协议调研报告](../A2A-Protocols-Research-Report.md) — 完整协议对比分析
- [docs/WORKFLOW.md](../WORKFLOW.md) — 当前流水线步骤定义
- [docs/WORKSPACE_RULES.md](../WORKSPACE_RULES.md) — 角色职责与路由规则
- [docs/TODO.md](../TODO.md) — §三 研究参考 — A2A 引用
- [Google A2A Protocol v1.0](https://github.com/a2aproject/A2A) — 官方规范
