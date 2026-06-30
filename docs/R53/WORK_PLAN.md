# R53 开发计划

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **编制人：** 🧐 PM
> **日期：** 2026-06-29
> **基于需求：** [R53-product-requirements.md v1.0 ✅](./R53-product-requirements.md)

---

## 一、轮次概览

| 维度 | 内容 |
|:----|:------|
| **轮次** | R53 |
| **需求文档** | 🔗 [R53-product-requirements.md v1.0 ✅](./R53-product-requirements.md) |
| **本轮改动范围** | 仅第①类（服务器代码 `server/handler.py` + `shared/protocol.py`） |
| **轮次类型** | 管线基础设施修复轮（Pipeline Infrastructure Fix） |
| **核心目标** | 将点名（频道切换）和派活（Task 分配）从单向文本机制改为双向 ACK 确认制，消除「点名后 bot 未真正切换频道」的管线断点 |

---

## 二、参与角色

| 角色 | bot | 本轮任务 |
|:----|:----|:---------|
| 🧐 PM（需求/调度） | pm-bot | 触发管线、更新状态、通知项目负责人 |
| 🏗️ 架构师（技术方案） | arch-bot | 出 ACK 实现方案（`_broadcast_active_channel` 增加 ACK 等待、`_cmd_step_complete` 集成 ACK、`!pipeline_status` ACK 状态显示） |
| 💻 开发工程师（编码） | dev-bot | 实现需求 A/B/C 的代码改动 |
| 🔍 审查工程师（代码审查） | review-bot | 审查 ACK 状态机逻辑、超时处理、过渡兼容 |
| 🦐 测试工程师（测试验证） | qa-bot | dev 部署 + 全量验收 A-1~C-3 |
| 🦸 管理员（合并部署） | admin-bot | 合并 dev→main + 生产部署 |

---

## 三、管线步骤

| Step | 名称 | 状态 | 责任人 | 产出 | 验收 |
|:----:|:-----|:----:|:------|:-----|:----:|
| 1 | 🔶 管线启动 | ✅ | 服务端自动 | 建工作室 + 点名全员 + 派活 | F-20 |
| 2 | 🏗️ 技术方案 | ✅ | arch-bot | `docs/R53/R53-tech-plan.md` v1.0 `b36e5e4` | — |
| 3 | 💻 编码实现 | ✅ | dev-bot | 方向 A+B+C 编码 `e5606de`（+142/-170，净-28行） | A-1~C-3 |
| 4 | 🔍 代码审查 | ✅ | review-bot | 审查通过 `03a1b7f`（自动驾驶推进） | A-1~C-3 |
| 5 | 🦐 测试验证 | ✅ | qa-bot | 39/39 全绿 `cb8a0d9` | A-1~C-3 |
| 6 | 🦸 合并部署归档 | ✅ | admin-bot | dev→main 合并 + TODO.md v2.20 `7867198` | — |

---

## 四、编码要点（方向 A + B + C）

### 方向 A：ACK 点名

| # | 改动点 | 文件 | 说明 |
|:-:|:-------|:-----|:------|
| A-1 | `_broadcast_active_channel()` 增加 ACK 等待 | `handler.py` | 现有函数末尾增加 ACK 定时器逻辑（类似 `_task_ack_timers`），等待各 bot 回复 MSG_ACK |
| A-2 | 新增 `MSG_ACK` 处理分支 | `handler.py::handle_broadcast()` | 收到 `msg_type == "msg_ack"` → 匹配等待中的 ACK 定时器 → 标记已确认 |
| A-3 | `_auto_rollcall_notify()` 移除文本「回复到」+「3分钟超时」 | `handler.py` | 删除相关文本逻辑，改为等待 ACK 定时器组 |
| A-4 | `_notify_rollcall_complete()` 基于 ACK 结果 | `handler.py` | 全员 ACK → ✅，部分未响应 → ⚠️ 并通知 admin |
| A-5 | `!rollcall` 全员点名命令接入 ACK | `_cmd_rollcall_role()` | 管理员的 `!rollcall` 命令也走 ACK 确认制 |
| A-6 | 超时 fallback | `handler.py` | 30s 未 ACK → 通知 admin，不阻塞（过渡兼容旧 bot） |

### 方向 B：ACK 派活

| # | 改动点 | 文件 | 说明 |
|:-:|:-------|:-----|:------|
| B-1 | `_cmd_step_complete()` 集成 ACK 等待 | `handler.py` | 创建 task 后不立即返回，进入 ACK 等待状态 |
| B-2 | MSG_TASK_ACK 处理增强 | `handler.py` | 收到 accepted → task 从 `submitted` 推进到 `working` |
| B-3 | `_task_ack_timeout()` 增强 | `handler.py` | 超时后管线级升级通知（不仅是 admin 通知），`_admin` 频道显示「⚠️ 任务未被确认」 |
| B-4 | `!pipeline_status` ACK 状态显示 | `handler.py` | 新增 `waiting_ack` 状态显示 |

### 方向 C：合并分配

| # | 改动点 | 文件 | 说明 |
|:-:|:-------|:-----|:------|
| C-1 | `_cmd_step_complete()` 调用流重整 | `handler.py` | 点名切频道 ACK → 创建 task ACK → 管线推进，合并为单步二次 ACK 流程 |
| C-2 | 移除冗余文本广播 | `handler.py` | 确认 `_auto_rollcall_notify` 和 `_cmd_rollcall_role` 中无残留文本点名消息 |

### 协议常量

| # | 改动点 | 文件 | 说明 |
|:-:|:-------|:-----|:------|
| P-1 | 确认 `MSG_TASK_ACK` 常量完整 | `shared/protocol.py` | 现有 MSG_TASK_ACK 是否已定义 FIELD_TASK_ID/FIELD_TASK_STATUS/FIELD_TASK_REASON，如缺少则补充 |

---

## 五、过渡兼容说明

- 旧 bot 不回复 ACK → 30s 超时后 fallback 通过 → 管线推进，通知 admin
- 新 bot 回复 ACK → 立即确认 → 不等超时
- 无需强制 bot 客户端统一更新，服务端先上线，bot 逐步适配

---

## 六、变更日志

| 版本 | 日期 | 说明 |
|:----:|:----|:------|
| v0.1 | 2026-06-29 | 初稿 — ACK 确认制管线基础设施修复轮 |

---

## 七、相关资源

- 需求文档：`docs/R53/R53-product-requirements.md`
- 现有 ACK 基础设施：`handler.py` 中 `_task_ack_timers`、`_task_ack_timeout()`、`_notify_rollcall_complete()`、`MSG_TASK_ACK`
- 管线命令：`!pipeline_start`、`!step_complete`、`!pipeline_status`、`!step_handoff`
