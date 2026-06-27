# R44 开发计划 — 管线入口直达

> **版本：** v1.0 ✅（已审批）
> **状态：** ✅ 已审核
> **日期：** 2026-06-27
> **需求文档：** [R44-product-requirements.md](R44-product-requirements.md)

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

#### ✅ Step A — 需求文档 🧐 pm-bot ✅
- **v0.2 ✅（项目负责人审核通过）**
- 仅方向 A — 管线入口直达：PM 在 TG DM 发 `!pipeline_start R{N}` 一次触发管线，取消三段式中转
- 三个实现方向留白给架构师：Gateway 侧路由 / 服务端侧代理 / 权限降级
- 改动范围：第①类服务器代码（`server/handler.py` + Gateway adapter）

#### ✅ Step B — 工作计划 🧐 pm-bot ✅
- ✅ v1.0 已审核通过（本文件）

---

### 🟢 自动化管线（6 步管线）

#### Step 1 — `!pipeline_start R44` 🤖 服务器

| 事项 | 状态 |
|:-----|:----:|
| 触发方式 | (桥接轮次) PM 通过 code 块经项目负责人转发给 admin-bot 执行 `!pipeline_start R44 --from step2` |
| 自动操作 | ⏳ 验证前置决策 → 创建工作室 R44-dev → 点名全员 → 点名架构师出技术方案 |

> **桥接轮次说明：** R44 要修复的正是管线入口问题本身，所以本轮的 Step 1 仍需用「旧流程」（code 块 + 项目负责人转发）触发。这正是设计模式中的「桥接轮次」——R44 用旧流程修新入口，R45 起新入口生效。

#### Step 2 — 技术方案 🏗️ arch-bot

| 事项 | 状态 |
|:-----|:----:|
| 产出文件 | ⏳ `docs/R44/R44-tech-plan.md` |
| 关键问题 | 三种路由方案选型 + Gateway 侧 vs 服务端侧边界划分 |
| 完成标志 | `!step_complete step2 --output <commit-sha>` |

**方案选项：**

| 方案 | 改动范围 | 复杂度 | 风险 |
|:-----|:--------:|:------:|:----:|
| **方案 1：Gateway 侧路由** | `ws_bridge_adapter.py`（~30 行） | 低 | 低 — 仅识别人命令转发，不改服务端逻辑 |
| **方案 2：服务端侧代理** | `handler.py` `_ADMIN_COMMANDS`（~20 行） | 低 | 中 — 需处理 member→P4 角色代理的认证边界 |
| **方案 3：权限降级** | `handler.py` `_check_command_permission`（~5 行） | 最低 | 中 — 降级单个命令的权限检查，可能影响整体安全感知 |

> 架构师推荐方案 1（Gateway 侧路由）作为首选，理由：不改服务端认证体系，Gateway 侧识别 `!pipeline_start` 后以 admin-bot 身份发到 `_admin` 频道，完全透明。具体推荐在技术方案中论证。

#### Step 3 — 编码实现 💻 dev-bot

| 方向 | 预期改动量 | 说明 |
|:----:|:----------:|:-----|
| A 管线入口直达 | ~20–50 行 | 取决于方案选择：方案 1（adapter 路由）约 30 行，方案 2（服务端代理）约 20 行，方案 3（权限降级）约 5 行 |

**涉及文件：**

| 文件 | 操作 | 说明 |
|:-----|:----|:------|
| `ws_bridge_adapter.py`（Gateway 插件目录） | 🔄 新增/修改 | 方案 1：识别 `!pipeline_start` 命令路由到 `_admin` |
| `server/handler.py` | 🔄 新增/修改 | 方案 2：`_ADMIN_COMMANDS` 增加代理转发；方案 3：`_check_command_permission` 增加例外 |
| `shared/protocol.py` | ℹ️ 无需改动 | 无新消息类型增加 |

#### Step 4 — 代码审查 🔍 review-bot

**审查重点：**
- 路由是否仅限 `!pipeline_start` 管线命令，避免将其他 `!` 命令错误路由到 `_admin` 频道
- 执行权限是否始终由 admin-bot（P4）持有，不降低 `!` 命令系统的整体权限
- 旧入口（`_admin` 频道直接发命令）是否继续可用
- 命令执行结果回传 PM 的链路是否完整
- **向后兼容：** 非管线命令行为不变

#### Step 5 — 测试验证 🦐 qa-bot

> **产出要求：** `docs/R44/R44-test-report.md`

| 序号 | 测试项 | 对应需求 |
|:----:|:-------|:--------:|
| T-A1 | PM 从 TG DM 发 `!pipeline_start R44`，管线 <5 秒自动启动 | A-1 |
| T-A2 | 命令始终由 admin-bot（P4）权限执行，PM 不直接获得 `!` 权限 | A-2 |
| T-A3 | 非管线命令（`!task_create`、`!create_workspace`）不被错误路由 | A-3 |
| T-A4 | 缺轮次参数的 `!pipeline_start` 返回用法提示，不创建工作室 | A-4 |
| T-A5 | 执行结果通过 TG DM 回传给 PM | A-5 |

**测试方法：**
- T-A1: PM 在 TG DM 发 `!pipeline_start R44`，观察工作室是否创建、点名是否执行
- T-A2: 检查 handler 日志确认命令执行者 agent_id 为 admin-bot（非 pm-bot）
- T-A3: PM 在 TG DM 发 `!task_create ...`，确认消息按普通文本发送到大厅（非 `_admin`）
- T-A4: 发 `!pipeline_start` 无参数，确认返回格式化的用法提示
- T-A5: 发 `!pipeline_start R44` 后，检查 TG DM 是否收到管线启动结果

#### Step 6 — 合并部署 + 归档 🦸 admin-bot

- `git checkout main && git merge dev` — main 对齐 dev
- TODO.md 更新：F-12 标记为 🟢 已完成
- 工作室关闭，回归大厅

---

## 关键约束

1. **只改第①类服务器代码** — `server/handler.py` + Gateway adapter，不涉及 Web 端、脚本
2. **不改权限体系** — PM 触发的命令仍由 admin-bot（P4）权限执行，不修改 `_check_command_permission` 的权限阈值
3. **向后兼容** — `!pipeline_start` 在 `_admin` 频道直接执行继续可用，旧流程保持不变
4. **限路由范围** — 路由仅限 `!pipeline_start` 管线命令，不扩大其他 `!` 命令的可达性
5. **桥接轮次** — R44 用旧流程（code 块转发）启动管线修新入口，R45 起新入口生效
6. **仅方向 A** — 工作区成员填充（F-13）和上下文增强不纳入本轮
