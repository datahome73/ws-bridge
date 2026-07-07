> **状态：** 🏁 已归档
> **备注：** 历史轮次，代码已合并入 main。保留供参考。

# R38 开发计划 — 流水线任务状态机 + Agent 协作体系

> **版本：** v1.0
> **状态：** ✅ Step 3 完成 — 技术方案 `156ac2d`，进入全员评审 → Step 4
> **日期：** 2026-06-24
> **需求文档：** [R38-product-requirements.md](R38-product-requirements.md)
> **参考：** [A2A 协议调研报告](../A2A-Protocols-Research-Report.md)

---

## 角色分工

| 角色 | 成员 |
|:----:|:----:|
| 🦸 项目管理 | admin-bot |
| 🧐 需求分析师 | pm-bot |
| 🏗️ 架构师 | arch-bot |
| 💻 开发工程师 | dev-bot |
| 🔍 审查工程师 | review-bot |
| 🦐 测试工程师 | qa-bot |

---

## 开发步骤

### 🔶 前置决策区（全部通过）

#### Step A — 需求文档 🧐 pm-bot ✅
- **v1.0 ✅（项目负责人审核通过）**
- 方向：A2A Task 状态机 + Agent Card + Web 端进度 Tab + Tab 排序/刷新规则
- 产出：`docs/R38/R38-product-requirements.md`
- 20 条验收标准（S-1~S-15 服务端 + W-1~W-7 Web 端）

#### Step B — 工作计划 🦸 admin-bot
- ⬜ 待审核
- 产出：本文件

---

### 🟢 自动化管线

#### ⬜ Step 1 — 创建工作室 🦸 admin-bot

| 事项 | 说明 |
|:-----|:------|
| 工作室 | R38 开发工作室 |
| 目标 | 全员加入，准备点名 |
| 前置 | Step A + Step B 全部 ✅ |

#### ⬜ Step 2 — 点名 🦐 qa-bot

| 事项 | 说明 |
|:-----|:------|
| 点名主持 | qa-bot |
| 关键操作 | MSG_SET_ACTIVE_CHANNEL → ws:R38开发工作室 |
| 全员回复 | 「已切」确认后点名完成 |

#### ✅ Step 3 — 技术方案 🏗️ arch-bot (156ac2d)

- **产出：** `docs/R38/R38-tech-plan.md`（674 行）— `156ac2d`
- 9 大主题全覆盖：TaskStore SQLite、_ADMIN_COMMANDS 4 条新命令、Agent Card 配置、Web 进度 Tab、Tab 排序/刷新规则、双入口同步
- 20 条验收标准全覆盖映射表（§3）

**PM 评审：** 方案提交后在工作室群内全员讨论，评审意见记录在方案文档中（不再出独立方向审查文档）

#### ⬜ Step 4 — 编码 💻 dev-bot

**编码任务分组：**

| 优先级 | 任务 | 验收标准 | 预估 |
|:------:|:-----|:--------|:----:|
| P0 | ① 协议层：TaskState 枚举 + 消息类型常量 | S-1, S-2 | 中 |
| P0 | ② 服务端：Task 数据模型 + SQLite 持久化 | S-3, S-10 | 大 |
| P0 | ③ 服务端：_ADMIN_COMMANDS 注册 + 4 条 Task 命令 | S-4~S-9, S-12 | 大 |
| P1 | ④ 服务端：MSG_TASK_NOTIFY 推送 | S-11 | 小 |
| P1 | ⑤ Agent Card 配置/持久化表 | S-14, S-15 | 中 |
| P0 | ⑥ Web 端：进度 Tab 表格 | W-1~W-5 | 大 |
| P0 | ⑦ Web 端：Tab 排序规则（活跃→大厅→管理员→进度→历史） | W-6 | 中 |
| P0 | ⑧ Web 端：下拉刷新回第一个 Tab | W-7 | 小 |
| P0 | ⑨ 双入口同步 | S-13 | 小 |

**提交规范：** `feat(R38): <描述>` — 代码推 dev 分支

#### ⬜ Step 5 — 代码审查 🔍 review-bot

| 事项 | 说明 |
|:-----|:------|
| 初审 | review-bot 出审查报告 |
| 退回机制 | 🔴 驳回 → dev-bot 修复 → 二审 |
| 二审 | 逐项确认闭合 → ✅ 通过 或 ❌ FAILED 锁定 |
| 产出 | `docs/R38/R38-code-review.md` |

#### ⬜ Step 6 — 测试验证 🦐 qa-bot

| 事项 | 说明 |
|:-----|:------|
| Dev 部署 | qa-bot 部署 dev 容器 + health check |
| 测试范围 | 20 条验收标准全部验证 |
| 产出 | `docs/R38/R38-test-report.md` |

#### ⬜ Step 7 — 合并部署 & 归档 🦸 admin-bot

| 事项 | 说明 |
|:-----|:------|
| 合并 dev → main | admin-bot 执行合并 |
| 部署正式容器 | 更新生产环境 |
| 归档 | 关闭工作室，标记 |

---

## 编码注意事项

1. **双入口同步（🔴 关键）** — `handler.py::handler()` 和 `__main__.py::ws_handler()` 都要支持新消息类型。`__main__.py` 的 import 同步检查（`write_chat_log`, `uuid`, `persistence` 等）。
2. **SQLite 新增表** — 新建 `task_store` 表，不修改 `message_store` 现有结构。
3. **Web 端 Tab 排序（W-6）** — 有活跃工作室时顺序：活跃→大厅→管理员→📊 进度→历史。无活跃工作室时不显示「活跃」Tab，大厅为第一个。
4. **下拉刷新规则（W-7）** — 刷新时回到第一个 Tab（有活跃→活跃，无活跃→大厅）。这是 F-7 的修复方向。
5. **Agent Card** — 配置级定义，不硬编码角色列表到 handler.py 中。配置文件中定义各角色 ID、display_name、skills、state。
6. **Task 状态转换校验** — 在服务端做纯规则校验（走 _ADMIN_COMMANDS 路径），不做 LLM 判断。
7. **Reject 计数上限** — `INPUT_REQUIRED → WORKING` 最多 2 次，第 3 次自动锁定 FAILED。
8. **`_persist_admin_response()`** — 复用现有基础设施，Task 命令响应走 `_admin` 频道。

---

## 需求-验收对照图

```
需求文档 §2           → 验收标准
─────────────────────────────────────────
Task 状态机            → S-1, S-2
_admin 命令扩展         → S-4~S-9, S-12
MSG_TASK_NOTIFY        → S-11
SQLite 持久化           → S-10
双入口同步              → S-13
Agent Card 元数据       → S-14, S-15
Web 进度 Tab           → W-1~W-5
Tab 排序规则            → W-6
下拉刷新规则            → W-7
```
