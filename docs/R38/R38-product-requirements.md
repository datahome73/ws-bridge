# R38 产品需求 — A2A 协议适配：引入流水线任务状态机

> **版本：** v0.1（草稿，预沟通讨论稿）
> **状态：** 📋 草稿（待审核）
> **产品经理：** 🧐 PM
> **日期：** 2026-06-24
> **参考：** [A2A 协议调研报告](../A2A-Protocols-Research-Report.md)

---

## 0. 权限分级体系（总纲）

R38 的需求涉及 Agent 协作流程的基础设施改进，不涉及用户权限分级调整。现有 P0-P4 体系不变。

---

## 1. 背景与问题

### 1.1 调研背景

本团队对现有 A2A（Agent-to-Agent）开源协议做了全面调研，覆盖 Google A2A Protocol、Anthropic MCP、OpenAI Agents SDK、FIPA-ACL、AutoGen 等主流协议。调研报告详见 [A2A 协议调研报告](../A2A-Protocols-Research-Report.md)。

核心发现：ws-bridge 本质上已是一个 **Agent-to-Agent 消息总线**，但缺少标准化的**任务生命周期管理**和**自描述 Agent 元数据**。Google A2A Protocol（v1.0，Apache 2.0）中的 Task 状态机设计模式与 ws-bridge 流水线高度吻合，可借鉴落地。

### 1.2 当前痛点

| # | 痛点 | 说明 |
|:-:|:-----|:------|
| ① | **流水线步骤状态不明确** | 当前 Step 1→6 是线性前进的，没有状态枚举。一个步骤是「待启动」「进行中」「已驳回」「已取消」——这些都靠人脑跟踪，不写入系统 |
| ② | **审查驳回无状态挂起** | 代码审查驳回后，被驳回的步骤处于「既不算完成也不算失败」的中间态。当前靠 WORK_PLAN 的 🟡 退回标记，但这是文档级的，不是系统级的 |
| ③ | **跨步骤上下文无统一 ID** | 当前有 R{N} 轮次 ID 但缺少统一的 context 概念。一个轮次的多个步骤、多轮消息之间没有绑定关系，各步骤的产出（文档、代码、报告）没有结构化关联 |
| ④ | **Agent 能力不可编程查询** | 当前各角色的能力（谁可以审查、谁可以编码、谁可以测试）只写在 WORKSPACE_RULES.md 里供人读，没有机器可读的元数据供路由逻辑引用 |

### 1.3 本轮改动范围

> **本轮改动范围：** 兼顾第①类（服务器代码 `server/`）和第④类（Web 端 `server/web_viewer.py`, `server/templates.py`）

**原因：** 任务状态机需要在服务端（消息路由、任务分发）和 Web 端（状态可视化）两端同时落地，缺一端则状态机不可观测。属于同一层语义概念的跨端联动，不是独立的多种改动。

---

## 2. 方向呈现

本报告提出 2 个候选方向供决策。方向 A 为核心需求，方向 B 为可选扩展。

### 🔷 方向 A：Task 生命周期状态机（核心）

借鉴 Google A2A 的 Task 状态机模型，为 ws-bridge 的流水线步骤引入系统级状态管理。

#### 2.1 A2A Task 状态机参考

```
               ┌──────────┐
               │SUBMITTED │
               └────┬─────┘
                    │
               ┌────▼─────┐
               │  WORKING  │
               └────┬─────┘
                    │
       ┌────────────┼────────────┐
       │            │            │
┌──────▼────┐ ┌─────▼─────┐ ┌───▼────┐
│ COMPLETED │ │  FAILED   │ │CANCELED │
└───────────┘ └───────────┘ └────────┘
       │            │
       │     ┌──────▼────────┐
       │     │INPUT_REQUIRED │←── 审查驳回（关键状态）
       │     └──────┬────────┘
       │            │（重新提交）
       │     ┌──────▼────────┐
       │     │   WORKING     │
       │     └──────┬────────┘
       │            │
       └────(最终态)─┘

新增状态（与 ws-bridge 映射）：
- SUBMITTED    → 步骤已创建（待启动）
- WORKING      → 步骤进行中
- COMPLETED    → 步骤完成 ✅
- FAILED       → 步骤执行失败 ❌
- CANCELED     → 步骤主动取消 ⛔
- INPUT_REQUIRED → 审查驳回等待修复 🟡
```

#### 2.2 具体需求

**A-1：在 server/handler.py 中实现 TaskState 枚举**

为每个流水线任务引入序列化的状态机，支持状态转换和持久化。

```python
# 示意
@unique
class TaskState(Enum):
    SUBMITTED = "pending"       # 待启动
    WORKING = "in_progress"     # 进行中
    COMPLETED = "completed"     # 已完成
    FAILED = "failed"           # 失败
    CANCELED = "canceled"       # 已取消
    INPUT_REQUIRED = "blocked"  # 驳回等待（审查退回/需要输入）
```

**状态转换规则：**
- ✅ 允许：`SUBMITTED → WORKING`
- ✅ 允许：`WORKING → COMPLETED`
- ✅ 允许：`WORKING → FAILED`
- ✅ 允许：`WORKING → INPUT_REQUIRED`
- ✅ 允许：`INPUT_REQUIRED → WORKING`（修复后重提）
- ✅ 允许：任何状态 → `CANCELED`
- ❌ 禁止：`SUBMITTED → COMPLETED`（跳过执行）
- ❌ 禁止：`COMPLETED → WORKING`（已完成不能再激活）

**A-2：Task 实例管理与持久化**

- 每个 Task 实例应包含：`task_id`, `context_id`, `name`, `state`, `assigned_role`, `created_at`, `updated_at`, `output_refs[]`
- Task 持久化到 SQLite（复用 message_store 或新建 task_store 表）
- `contextId`：对应一个轮次（R{N}），分组一组相关 Task
- `taskId`：全局唯一的 UUID，用于跨消息引用

**A-3：新增消息类型用于任务操作**

在 `shared/protocol.py` 中新增消息类型：

| 消息类型 | 方向 | 用途 |
|:---------|:-----|:------|
| `MSG_TASK_CREATE` | Agent → 服务端 | 创建新 Task（如「启动 Step 4 编码」） |
| `MSG_TASK_UPDATE` | Agent → 服务端 | 更新 Task 状态（如「编码完成 → COMPLETED」） |
| `MSG_TASK_QUERY` | Agent → 服务端 | 查询 Task 列表或单个状态 |
| `MSG_TASK_NOTIFY` | 服务端 → Agent | Task 状态变更推送通知 |

**A-4：Web 端 Task 状态可视化**

在 Web 聊天室中增加任务状态视图：

- Tab 新增「任务面板」或集成到现有 Tab 布局
- 以轮次（contextId）为分组，显示每个步骤的实时状态
- 状态变更时自动刷新（轮询或 SSE 推送）
- 状态用颜色标记（🟢已完成/🟡阻塞中/🟢 进行中/⏸️ 待启动）

**A-5：审查驳回 → INPUT_REQUIRED 自动流转**

- 审查工程师发送审查报告（含驳回结论）时，自动将该步骤的 Task state 切换为 `INPUT_REQUIRED`
- 开发修复后重推代码时，手动触发 `MSG_TASK_UPDATE → WORKING`，开始第二轮审查周期
- 两轮仍不通过时状态锁定为 `FAILED`（不再允许 `INPUT_REQUIRED → WORKING`）

### 🔷 方向 B：Agent Card 轻量元数据（可选扩展）

为每个角色定义机器可读的能力清单，用于消息路由和状态管理。

#### 2.3 需求描述

**B-1：Agent Card 定义**

在配置或规则文件中定义每个角色的 Skill Card：

```json
{
  "agent_id": "pm-bot",
  "display_name": "PM",
  "skills": [
    {"id": "write-requirements", "description": "撰写需求文档"},
    {"id": "review-requirements", "description": "评审需求"},
    {"id": "schedule-work", "description": "编排工作计划"}
  ],
  "triggers": ["!pm", "!需求"],
  "state": "online",
  "channels": ["lobby", "workspace"]
}
```

**B-2：基于 Agent Card 的动态路由**

- 消息前缀（📢📋 !code !qa 等）不再硬编码在 handler.py 的路由逻辑中
- 改为查询 Agent Card 的 triggers 字段决定消息投递目标
- 新 Agent 加入时只需注册自己的 Agent Card，路由自动生效

---

## 3. 验收标准

### 方向 A：Task 状态机

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| A-1 | `server/handler.py` 中有 `TaskState` 枚举，6 种状态定义完整，转换规则按「2.2 A-1」执行 | P0 |
| A-2 | Task 实例可通过 `MSG_TASK_CREATE` 创建，服务端返回 `task_id` 和初始 `SUBMITTED` 状态 | P0 |
| A-3 | Task 状态可通过 `MSG_TASK_UPDATE` 推进，非法转换（如 COMPLETED→WORKING）返回错误 | P0 |
| A-4 | 审查消息（review 报告）附 `review: "rejected"` 时，关联 Task 自动进入 `INPUT_REQUIRED` | P1 |
| A-5 | `INPUT_REQUIRED` 状态卡在第二轮时自动锁定为 `FAILED`，不可继续推进 | P1 |
| A-6 | Task 持久化到 SQLite，服务重启后状态不丢失 | P1 |
| A-7 | `MSG_TASK_QUERY` 按 contextId 返回该轮次所有 Task 及其当前状态 | P0 |
| A-8 | Web 端新增任务面板，显示各轮次 Task 状态，状态变更后 ≤5s 内更新 | P1 |
| A-9 | 双入口同步：`handler.py::handler()` 和 `__main__.py::ws_handler()` 均支持以上消息类型 | P0 |

### 方向 B：Agent Card（如选定）

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| B-1 | 有一份 Agent Card 配置文件或持久化表，定义所有角色的能力/触发词/状态 | P2 |
| B-2 | 消息路由可基于 Agent Card triggers 字段投递，不依赖硬编码前缀 | P2 |
| B-3 | Agent 上线时可通过消息注册自己的 Agent Card，路由自动生效 | P3 |

---

## 4. 不纳入本次需求

| 不纳入项 | 说明 |
|:---------|:------|
| Google A2A 全协议兼容 | 仅借鉴 Task 状态机模式，不实现 HTTP/gRPC 传输层或 Agent Card JWT 签名 |
| Agent 动态发现机制 | 暂不实现 `/.well-known/agent.json` 或注册表广播，留在后续轮次 |
| Streaming/Push 双模式 | 长时间任务流式推送暂不纳入，留在后续轮次 |
| Part 容器（多模态消息） | A2A Part 设计是较深的消息模型改造，单独论一轮 | 
| Full Screen HUD | 暂不做独立的任务管理 Web 页面，仅 Tab 面板展示 |
| Agent Card 签名认证 | 内部环境暂不需要 JWT/证书级身份验证 |

---

## 5. 开放问题

| # | 问题 | 决策状态 |
|:-:|:-----|:--------:|
| Q1 | 方向 A（Task 状态机）+ 方向 B（Agent Card）合并成一轮，还是分两轮？方向 B 是否纳入？ | ⏳ 待决策 |
| Q2 | Task 状态机绑定到「轮次」层面（每个 R{N} 一个 contextId）还是「单个步骤」层面（每个 Step 一个 Task）？ | ⏳ 待决策 |
| Q3 | Web 端任务面板是做独立 Tab（Tab 4）还是集成到已有 Tab 中将状态标注在消息旁？ | ⏳ 待决策 |
| Q4 | 审查驳回 → INPUT_REQUIRED 是手动触发（审查者发指令）还是自动识别（解析审查报告文本中的结论）？ | ⏳ 待决策 |

---

## 6. 参考文档

- [A2A 协议调研报告](../A2A-Protocols-Research-Report.md) — 完整协议对比分析
- [docs/WORKFLOW.md](../WORKFLOW.md) — 当前流水线步骤定义
- [docs/WORKSPACE_RULES.md](../WORKSPACE_RULES.md) — 角色职责与路由规则
- [Google A2A Protocol v1.0](https://github.com/a2aproject/A2A) — 官方规范
