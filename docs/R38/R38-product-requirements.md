# R38 产品需求 — 流水线任务状态机 + Agent 协作体系

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-06-24
> **参考：** [A2A 协议调研报告](../A2A-Protocols-Research-Report.md)

---

## 0. 改动范围

> **本轮改动范围：** 第①类（服务器代码 `server/`）+ 第④类（Web 端 `server/web_viewer.py`, `server/templates.py`），连带协议常量和配置。

**原因：** 任务状态机需要在服务端（消息路由 + 命令分发）和 Web 端（状态可视化）两端同时落地，缺一端则状态机不可观测。Agent Card 元数据与状态机共用数据模型，一起做互相关联，代码量大但能快速解决问题。

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

### 1.3 核心设计原则

> **自己完成本环节的任务后，把好自己的质量关，合格就推进到下一环节，不合格就退回。**

> **纯规则化的部分（不涉及 AI 智能判断）都放到服务端系统级别处理，不占用 token。**

这条原则决定了架构分层——Task 状态转换是纯规则（状态迁移矩阵、权限检查），执行在服务端 `handler.py` 的 admin 命令基础设施中，不走 LLM。AI Agent 只负责**完成工作内容**和**做出质量判断**（合格/退回），状态记录由服务端自动处理。

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

**状态与 WORK_PLAN 标记映射：**

| Task 状态 | 标记 | 含义 |
|:----------|:----:|:-----|
| `SUBMITTED` | ⬜ | Step 已排入流水线，等待分配执行者 |
| `WORKING` | ▶ | 执行者正在处理该 Step |
| `COMPLETED` | ✅ | 执行者/审查者确认合格，本 Step 完成 |
| `FAILED` | ❌ | 二次退回后仍不合格，锁定终止 |
| `CANCELED` | ⛔ | 任务主动取消（如轮次范围变更） |
| `INPUT_REQUIRED` | 🟡 | 审查者判定不合格，退回修复 |

**状态转换规则（纯规则 — 服务端执行）：**

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

### 2.2 实现方式 — 扩展 Admin 命令基础设施

Task 状态机作为 **现有 `_ADMIN_COMMANDS` 注册表**的扩展实现。不新建独立服务，不引入新基础设施。

**当前已有的 admin 命令模式（R35 已实现）：**

```
_ADMIN_COMMANDS: dict[str, dict] = {
    "create_workspace": { handler, min_role, usage },
    "close_workspace":  { handler, min_role, usage },
    "list_workspaces":  { handler, min_role, usage },
    "approve_pairing":  { handler, min_role, usage },
    ...
}
```

**新增 Task 相关命令：**

| 命令 | 最低角色 | 说明 |
|:-----|:--------:|:------|
| `!task_create --context R38 --step 3 --name "编码" --role dev-bot` | P3（工作室管理员） | 创建新 Task，状态初始为 SUBMITTED |
| `!task_update --task-id <uuid> --state COMPLETED [--output <ref>]` | P1（任务执行者） | 更新 Task 状态，校验合法转换 |
| `!task_query --context R38` | P1（所有成员） | 查询指定轮次的所有 Task 和状态 |
| `!task_list [--context <id>] [--state <state>]` | P1 | 列出 Task，支持过滤 |

**执行流程（复用现有基础设施）：**

```
Agent → _admin channel → !task_update --task-id X --state COMPLETED
                    │
                    ▼
   handler.py — _ADMIN_COMMANDS dispatch
                    │
                    ▼
   _parse_command → 解析参数
                    │
                    ▼
   _check_command_permission → 权限校验
                    │
                    ▼
   TaskState 转换校验 → 允许/拒绝
                    │
                    ▼
   SQLite 持久化 (task_store)
                    │
                    ▼
   MSG_TASK_NOTIFY → 推送状态变更给所有相关 Agent
                    │
                    ▼
   _persist_admin_response → 返回结果给发送者
```

**全链路全部在服务端纯规则执行，零 LLM 调用，零 token 消耗。**

### 2.3 Task 实例数据模型

| 字段 | 类型 | 说明 |
|:-----|:-----|:------|
| `task_id` | UUID | 全局唯一 Task 标识 |
| `context_id` | string | 轮次 ID（如 `R38`），分组一组相关 Task |
| `step` | int | Step 编号（如 1, 2, 3…） |
| `name` | string | Step 名称（如「编码」「代码审查」） |
| `state` | TaskState | 当前任务状态 |
| `assigned_role` | string | 当前执行者角色 ID（如 `dev-bot`） |
| `created_at` | float (timestamp) | 创建时间 |
| `updated_at` | float (timestamp) | 最后更新时间 |
| `output_refs` | text (JSON array) | 产出引用列表（commit SHA / 文件路径 / 报告链接） |
| `reject_count` | int | 退回次数（达到 2 次自动锁定 FAILED） |

**持久化：** 新增 `task_store` 表（SQLite），与 `message_store` 同级。服务重启后状态不丢失。

### 2.4 流程流转规则（自质量门）

> 每个 Agent 完成自己环节的任务后，把好自己的质量关，合格就推进到下一环节，不合格就退回。
> 状态记录由服务端系统自动处理，Agent 通过 ! 命令触发状态变更。

**一般 Step（非审查 Step）：**

```
执行者完成工作
    ├── 自评合格
    │   → 发 !task_update --task-id X --state COMPLETED
    │   → 服务端校验 → 记录状态 → 推下一步 SUBMITTED
    │   → 通知下一步执行者
    └── 自评不合格
        → 发 !task_update --task-id X --state INPUT_REQUIRED
        → 服务端校验 → 记录状态 → 自己返工
```

**审查 Step（代码审查/方案审查）：**

```
审查者评估产出
    ├── 合格
    │   → 发 !task_update --task-id X --state COMPLETED
    │   → 服务端校验 → 记录状态 → 推下一步 SUBMITTED
    └── 不合格
        → 发 !task_update --task-id X --state INPUT_REQUIRED
        → 服务端校验 → reject_count+1 → 通知开发修复
        → 修复后 !task_update --state WORKING
        → 第二轮审查仍不合格 → reject_count=2 → 自动锁定 FAILED
```

### 2.5 新增协议常量（ `shared/protocol.py` ）

| 常量 | 值 | 说明 |
|:-----|:----|:------|
| `MSG_TASK_CREATE` | `"task_create"` | 创建 Task 的消息类型 |
| `MSG_TASK_UPDATE` | `"task_update"` | 更新 Task 状态的消息类型 |
| `MSG_TASK_QUERY` | `"task_query"` | 查询 Task 的消息类型 |
| `MSG_TASK_NOTIFY` | `"task_notify"` | Task 状态变更推送通知的消息类型 |
| `FIELD_CONTEXT_ID` | `"context_id"` | 轮次 ID 字段名 |
| `FIELD_TASK_ID` | `"task_id"` | Task ID 字段名 |
| `FIELD_TASK_STATE` | `"state"` | 状态字段名 |

### 2.6 Agent Card（角色元数据）

为每个 Agent 定义机器可读的能力清单。与 Task 状态机共用数据模型——Task 的 `assigned_role` 字段引用 Agent Card 中的角色 ID。

**Agent Card 定义（配置文件或持久化表）：**

```json
{
  "agent_id": "pm-bot",
  "display_name": "PM Bot",
  "roles": ["product-manager"],
  "skills": [
    {"id": "write-requirements", "description": "撰写需求文档"},
    {"id": "review-requirements", "description": "评审需求"}
  ],
  "triggers": ["!pm", "!需求"],
  "state": "online"
}
```

**当前角色映射（配置级，不硬编码）：**

| 角色 ID | 涉及 Step | 能力 |
|:--------|:---------|:------|
| `admin-bot` | 0.5, 9 | 全平台管理、工作室创建、合并部署 |
| `pm-bot` | 1 | 需求文档、方向决策 |
| `arch-bot` | 2 | 技术方案、架构设计 |
| `dev-bot` | 3 | 编码实现 |
| `review-bot` | 4 | 代码审查 |
| `qa-bot` | 5 | 测试验证 |

**用途：**
- `!task_create --role dev-bot` 时通过 Agent Card 自动路由通知到对应 Agent
- Web 端「工作人」列从 Agent Card 获取 `display_name`
- 新 Agent 加入时只需注册 Agent Card，路由和任务分配自动生效

### 2.7 Web 端任务进度 Tab

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

**表格列（与现有 WORK_PLAN 对齐）：**

| 列 | 数据来源 | 说明 |
|:---|:---------|:-----|
| **Step** | Task.step | Step 编号 |
| **环节名称** | Task.name | 如「需求文档」「技术方案」「编码」 |
| **工作人** | Task.assigned_role → Agent Card.display_name | 从 Agent Card 查角色显示名 |
| **状态** | Task.state → 🟢 ✅ ▶ ⬜ 🟡 ❌ ⛔ | WORK_PLAN 标准标记 |

**数据来源：** Web 端通过 `!task_query --context R{N}` 接口（HTTP API 或 WebSocket 消息）获取数据，前端格式化展示。

**刷新机制：**
- 页面加载时发 `MSG_TASK_QUERY` 获取当前轮次所有 Task
- 定时轮询（每 30s）或 SSE 推送 `MSG_TASK_NOTIFY`
- 状态变更时 Tab 标题显示未读标记

---

## 3. 验收标准

### 服务端（server/ + shared/）

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| **S-1** | `shared/protocol.py` 中有 `TaskState` 枚举，6 种状态定义完整，转换规则按 §2.1 矩阵执行 | P0 |
| **S-2** | `shared/protocol.py` 中新增 4 种消息类型常量（MSG_TASK_CREATE/UPDATE/QUERY/NOTIFY）及 FIELD_ 常量 | P0 |
| **S-3** | Task 实例数据模型包含全部字段（task_id, context_id, step, name, state, assigned_role, reject_count 等）| P0 |
| **S-4** | `_ADMIN_COMMANDS` 注册表中新增 `task_create` / `task_update` / `task_query` / `task_list` 命令 | P0 |
| **S-5** | `!task_create --context <id> --step <n> --name <s> --role <r>` 创建 Task，返回 task_id，状态 SUBMITTED | P0 |
| **S-6** | `!task_update --task-id <id> --state <new>` 合法转换通过，非法转换返回错误 | P0 |
| **S-7** | `INPUT_REQUIRED → WORKING` 转换时 `reject_count` 递增；`reject_count ≥ 2` 时自动锁定 FAILED | P1 |
| **S-8** | `!task_query --context <id>` 返回该轮次所有 Task，按 step 排序 | P0 |
| **S-9** | `!task_list [--state <s>]` 返回匹配指定状态的 Task 列表 | P1 |
| **S-10** | Task 持久化到 SQLite（新建 `task_store` 表），服务重启后所有状态不丢失 | P1 |
| **S-11** | Task 状态变更时服务端推 `MSG_TASK_NOTIFY` 给所有关联 Agent | P1 |
| **S-12** | `!task_update` 的 `--state COMPLETED` 可附带 `--output <ref>` 记录产出（commit SHA / 报告路径）| P1 |
| **S-13** | 双入口同步：`handler.py::handler()` 和 `__main__.py::ws_handler()` 均支持以上所有消息类型和命令 | P0 |
| **S-14** | 有一份 Agent Card 配置文件或持久化表，定义所有角色 ID、display_name、skills、triggers、当前状态 | P1 |
| **S-15** | `!task_create` 的 `--role` 参数从 Agent Card 验证角色是否存在，不存在时返回错误 | P1 |

### Web 端（server/web_viewer.py + server/templates.py）

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| **W-1** | Web 端新增任务进度 Tab，与大厅/工作室/历史并列 | P0 |
| **W-2** | 表格列完整：Step、环节名称、工作人、状态 4 列 | P0 |
| **W-3** | 按 contextId（轮次）分组，显示最近 3 个轮次进度 | P1 |
| **W-4** | 定时刷新（轮询 30s 或 SSE），状态变更 ≤5s 内可见 | P1 |
| **W-5** | 状态用彩色标记对应 WORK_PLAN 标准（🟢 ✅ ▶ ⬜ 🟡 ❌ ⛔）| P1 |

---

## 4. 架构原则

### 4.1 分层边界

```
┌────────────────────────────────────────┐
│         AI Agent 层（LLM 决策）          │
│                                        │
│  做什么：完成工作内容 + 质量判断         │
│  示例：「编码完成，自评合格」→ 发命令     │
│  示例：「审查发现 3 个 Bug」→ 发命令退回  │
│  消耗：token                            │
└──────────────┬─────────────────────────┘
               │ !task_update --state ...
               ▼
┌────────────────────────────────────────┐
│      服务端系统层（纯规则，零 token）       │
│                                        │
│  做什么：状态转换校验、持久化、推送通知     │
│  示例：COMPLETED→WORKING ❌ 拒绝         │
│  示例：COMPLETED 记录 → 通知下一步 Agent  │
│  实现：_ADMIN_COMMANDS 注册表扩展         │
│  消耗：零 token、毫秒级响应               │
└────────────────────────────────────────┘
```

### 4.2 与现有基础设施的关系

| 现有模块 | R38 扩展方式 |
|:---------|:-------------|
| `_ADMIN_COMMANDS` 注册表 | 新增 4 条 Task 命令（task_create/update/query/list） |
| `_parse_command()` | 直接复用，参数格式兼容 `--key <value>` |
| `_check_command_permission()` | 直接复用，Task 命令按 P3/P1 分级 |
| `_persist_admin_response()` | 直接复用，Task 命令响应走 `_admin` 频道 |
| `_log_audit()` | 直接复用，Task 操作记入审计日志 |
| `message_store` (SQLite) | 扩展：新建 `task_store` 表，不修改现有表结构 |
| `shared/protocol.py` | 新增常量（TaskState enum + 消息类型） |

---

## 5. 不纳入本次需求

| 不纳入项 | 说明 |
|:---------|:------|
| Google A2A 全协议兼容 | 仅借鉴 Task 状态机模式，不实现 HTTP/gRPC 传输层或 Agent Card JWT 签名 |
| Agent 动态发现注册 | 暂不实现 `/.well-known/agent.json` 或注册表广播，配置级定义即可 |
| Streaming/Push 双模式 | 长时间任务流式推送暂不纳入 |
| Part 容器（多模态消息） | A2A Part 设计是较深的消息模型改造，单独论一轮 |
| 独立任务管理页面 | 仅 Tab 面板展示，不做 Full Screen HUD |
| Agent Card 签名认证 | 内部环境暂不需要 JWT/证书级身份验证 |

---

## 6. 决策记录

| # | 问题 | 决策 | 体现 |
|:-:|:-----|:-----|:-----|
| Q1 | 方向 A + B 合并还是分轮？ | **一起做** | Agent Card 作为 assigned_role 的数据来源 |
| Q2 | 状态机绑轮次还是绑 Step？ | **绑 Step** | 每个 Step = 一个 Task 实例 |
| Q3 | Web 端任务面板怎么做？ | **新增进度 Tab** | WORK_PLAN 格式化表格：Step/环节名称/工作人/状态 |
| Q4 | 审查驳回自动还是手动？ | **审查者决定** | !task_update --state INPUT_REQUIRED 手动触发 |
| Q5 | 纯规则逻辑放哪？ | **服务端系统层** | 扩展现有 _ADMIN_COMMANDS 基础设施，零 token |

---

## 7. 参考文档

- [A2A 协议调研报告](../A2A-Protocols-Research-Report.md) — 完整协议对比分析
- [docs/WORKFLOW.md](../WORKFLOW.md) — 当前流水线步骤定义
- [docs/WORKSPACE_RULES.md](../WORKSPACE_RULES.md) — 角色职责与路由规则
- [docs/TODO.md](../TODO.md) — §三 研究参考 — A2A 引用
- `server/handler.py` §R35: Admin command infrastructure — 现有 `!_ADMIN_COMMANDS` 注册表模式
- `shared/protocol.py` — 协议常量定义
