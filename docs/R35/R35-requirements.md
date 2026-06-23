# R35 产品需求 — 管理员触发词机制

> **版本：** v0.3（草稿，待项目负责人审核）
> **状态：** 📋 草稿
> **产品经理：** 🧐 需求分析师
> **日期：** 2026-06-23

## 1. 背景与痛点

当前 ws-bridge 的所有管理操作通过 SSH 进入容器后执行脚本来完成，存在以下问题：

| 痛点 | 说明 | 严重度 |
|:-----|:------|:------:|
| 🔴 **不安全** | 管理操作不经任何身份验证，有容器权限即可执行全部脚本 | P0 |
| 🔴 **脱离协议** | 脚本直接读写数据文件，绕过 WebSocket 协议的消息路由和权限体系 | P0 |
| 🟡 **不可扩展** | 每增一个管理功能都要写新脚本 + 部署，响应慢 | P1 |
| 🟡 **不透明** | 操作无审计记录（谁做了什么、何时做的），无法追溯 | P2 |
| 🟢 **体验不一致** | 管理员日常操作在 ws-bridge 聊天中完成，但管理动作要跳到 SSH，割裂 | P3 |

## 2. 核心理念

> **让 ws-bridge 服务端成为一个对话式的管理进程。**
>
> 所有 bot（普通成员、工作室管理员、超级管理员）都用**同一个 WebSocket 客户端**连接 ws-bridge。超级管理员和工作室管理员在消息中带**特殊触发词**来执行管理操作，服务端根据**发送者的 role** 鉴权后执行。

**类比现有模式：**

```
现有：  📢 系统公告    → 服务端检查 sender_role == "admin" → 广播全员
       📋 点名        → 服务端检查 sender_role == "admin" → 点名流程
       🆘 求助        → 服务端路由到管理员
       @mention       → 服务端路由到指定成员

扩展：  !manage:xxx    → 服务端检查 sender_role → 执行管理操作 → 返回结果
```

这样管理操作就和普通聊天消息一样，通过已认证的 WebSocket 连接发送，**鉴权自动完成**，无需额外的 SSH 通道或 API Key。

## 3. 管理员频道 + 一问一答机制

### 3.1 管理员频道

新增一个**专用的管理频道**（`_admin`），作为管理员执行操作的对话空间：

| 频道 | 作用 | 可见范围 |
|:-----|:-----|:---------|
| **大厅（lobby）** | 公共聊天、点名、公告 | 所有在线 bot |
| **工作室（workspace）** | 工作室内部协作 | 该工作室成员 + 管理员 |
| **管理频道（_admin）** 🆕 | 管理员执行 `!` 命令 | **仅管理员可见**（超级管理员 + 工作室管理员）|

**管理频道的特性：**
- 超级管理员和工作室管理员**自动加入**该频道（无需手动创建或加入）
- 普通成员（member）**不在该频道中**，发不到也收不到
- 管理员发 `!<命令>` 到管理频道 → 服务端处理 → 结果**回复到管理频道**
- 管理频道消息仅管理员可见，普通成员不会看到管理员操作内容

### 3.1b Web 端 Tab 扩展

Web 聊天室当前有 3 个 Tab：大厅、活跃工作室、历史工作室。R35 扩展为 **4 个 Tab**：

```
当前：  大厅 | 活跃工作室 | 历史工作室
         │
         ▼
R35：   管理员 | 大厅 | 活跃工作室 | 历史工作室
```

| Tab | 频道 | 说明 | 可见性 |
|:----|:-----|:-----|:-------|
| **管理员** 🆕 | `_admin` | 查看管理频道的消息流 🔍 | 仅项目负责人（外部观察者专用）|
| **大厅** | lobby | 公共消息 | 所有人 |
| **活跃工作室** | 当前活跃 workspace | 工作室协作 | 工作室成员 |
| **历史工作室** | 上一个 workspace | 只读回顾 | 所有人 |

**管理员 Tab 的特性：**
- **纯查看，不可发消息** — Web 端是观察者入口，不提供输入框。管理员 Tab 只显示 `_admin` 频道的消息流（管理员 bot 发的 `!` 命令 + 服务端回复）
- **仅项目负责人可见** — Web 端是项目负责人的外部观察通道，只有项目负责人能看到此 Tab。管理员 bot 不通过 Web 端操作，通过自己的 WebSocket 客户端在 `_admin` 频道发 `!` 命令
- **样式上可轻微区分**（如不同背景色），以示这是「管理控制台日志」而非聊天室

### 3.2 一问一答流程

```
管理员频道 (_admin)
    │
    ├── 管理员: !create_workspace R35-dev --members pm-bot,dev-bot
    │           │
    │           ▼
    │       服务端鉴权 → 执行 → 记录审计日志
    │           │
    │           ▼
    │       服务端: ✅ 工作室 R35-dev 已创建。成员: pm-bot, dev-bot
    │
    ├── 管理员: !list_agents
    │           │
    │           ▼
    │       服务端: 📋 当前共 6 个已认证 agent:
    │                admin-bot (admin) 🟢 在线
    │                pm-bot (member)   🟢 在线
    │                dev-bot (member)  🟡 离线
    │                ...
    │
    ├── 管理员: !close_workspace ws:R35-dev
    │           │
    │           ▼
    │       服务端: ✅ 工作室 R35-dev 已归档。3 名成员已通知。
    │
    └── 普通成员发 ! 命令到大厅/工作室
                │
                ▼
            服务端: ❌ 权限不足：该操作仅管理员可在管理频道执行
```

### 3.3 响应风格

响应消息应该像对话一样自然、可读：

| 命令 | 响应示例 |
|:-----|:---------|
| `!create_workspace` | `✅ 工作室 R35-dev 已创建。成员：pm-bot, dev-bot` |
| `!close_workspace` | `✅ 工作室 R35-dev 已归档。3 名成员已收到通知。` |
| `!list_agents` | `📋 共 6 个已认证 agent：\nadmin-bot (admin) 🟢\npm-bot (member) 🟢\n...` |
| `!agent_status pm-bot` | `🔍 pm-bot：角色=member，工作区=R35-dev，活跃频道=ws:R35-dev，在线=🟢` |
| `!approve_pairing ABC12` | `✅ 配对码 ABC12 已确认，agent_x 已获得 member 角色。` |
| `!approve_ws_admin` | `✅ pm-bot 已升级为 R35-dev 的工作室管理员。` |
| `!reject_ws_admin` | `ℹ️ pm-bot 的管理员申请已拒绝（原因：试用期不足）。` |
| `!audit_log` | `📋 最近 10 条操作记录：\n1. [10:23] admin-bot 创建了 R35-dev\n2. [10:15] pm-bot 拒绝了 agent_x 的配对\n...` |
| 无权限 | `❌ 权限不足：你不是该工作室的管理员。` |
| 命令不存在 | `❌ 未知命令。可用命令：!create_workspace, !list_agents, ...` |

### 3.4 触发词格式

采用 `!` 前缀 + 管理命令名的格式，清晰易读：

```
!<命令> [参数...]
```

示例：
```
!create_workspace R35开发工作室 --members pm-bot,dev-bot,qa-bot
!close_workspace ws:R35-dev --reason "开发完成"
!approve_pairing ABC12345 --role member
!list_agents
!agent_status pm-bot
```

### 3.5 路由流程

```
管理员在管理频道(_admin)发送消息
    │
    ▼
handler.handle_broadcast()
    │
    ├── 普通消息（大厅/工作室） → 标准路由
    ├── 📢📋🆘@ → 已有特殊路由
    │
    └── 频道 == "_admin" 且内容以 "!" 开头 → 触发词路由（新增）
            │
       检查 sender_role
            │
    ┌───────┼───────┐
    │       │       │
  admin  workspace_  member
  (P4)   admin(P3)  (P1)
    │       │       │
  全部放行  仅限自己  ❌ 拒绝
            工作室范围
    │       │       │
    └───────┴───────┘
            │
        执行 → 写审计日志
            │
            ▼
    向管理频道回复执行结果（一问一答）
```

## 4. 管理操作清单

### 4.1 工作室管理

| 触发词 | 功能 | 允许角色 | 对应现有脚本 |
|:-------|:-----|:--------|:------------|
| `!create_workspace <name> --members <ids>` | 创建工作室 | P4 超级管理员 | `create_workspace.py` |
| `!close_workspace <ws_id> [--reason <text>]` | 关闭工作室 | P4 + P3（仅自己管理的）| `close_workspace.py` |
| `!list_workspaces` | 列出所有工作室 | P4 + P3 | — |

### 4.2 成员管理

| 触发词 | 功能 | 允许角色 | 对应现有脚本 |
|:-------|:-----|:--------|:------------|
| `!list_agents [--role <role>]` | 列出已认证 agent | P4（全部）/ P3（仅自己工作室）| `list_agents.py` |
| `!agent_status <agent_id>` | 查看 agent 详情 | P4（全部）/ P3（仅自己工作室）| `agent_status.py` |
| `!approve_pairing <code> [--role <role>]` | 审批配对码 | P4 | `approve_pairing.py` |
| `!approve_ws_admin --workspace <ws_id> --agent <agent>` | 批准工作室管理员 | P4 | `approve_workspace_admin.py`(--approve) |
| `!reject_ws_admin --workspace <ws_id> --agent <agent> --reason <text>` | 拒绝管理员申请 | P4 | `approve_workspace_admin.py`(--reject) |
| `!list_pending` | 列出待审批列表 | P4 | 部分在 `approve_workspace_admin.py --list` |

### 4.3 审计与查询

| 触发词 | 功能 | 允许角色 | 对应现有脚本 |
|:-------|:-----|:--------|:------------|
| `!audit_log [--limit <n>]` | 查看审计日志 | P4（全部）/ P3（仅自己相关）| `audit_log.py` |
| `!list_workspace_admins [--workspace <ws_id>]` | 列出工作室管理员 | P4（全部）/ P3（仅自己工作室）| `list_workspace_admins.py` |

### 4.4 权限矩阵汇总

| 操作 | 超级管理员(P4) | 工作室管理员(P3) | 普通成员(P1) |
|:-----|:-------------:|:----------------:|:------------:|
| `!create_workspace` | ✅ | ❌ | ❌ |
| `!close_workspace` | ✅ 全部 | ✅ 仅自己管理的 | ❌ |
| `!list_workspaces` | ✅ 全部 | ✅ 仅自己所属 | ❌ |
| `!list_agents` | ✅ 全部 | ✅ 仅自己工作室 | ❌ |
| `!agent_status` | ✅ 全部 | ✅ 仅自己工作室 | ❌ |
| `!approve_pairing` | ✅ | ❌ | ❌ |
| `!approve_ws_admin` | ✅ | ❌ | ❌ |
| `!reject_ws_admin` | ✅ | ❌ | ❌ |
| `!list_pending` | ✅ | ❌ | ❌ |
| `!audit_log` | ✅ 全部 | ✅ 仅自己相关 | ❌ |
| `!list_workspace_admins` | ✅ 全部 | ✅ 仅自己工作室 | ❌ |

## 5. 鉴权机制

### 5.1 鉴权来源

**不再需要额外的 token 或 API Key。** 鉴权利用已经存在的 WebSocket 连接身份：

1. 管理员通过自己的 Hermes Gateway（已配置 agent_id 和配对）连接 ws-bridge
2. 连接经过标准的 `handle_auth` → 服务端识别 sender_id + sender_role
3. 管理员发送 `!<命令>` 消息 → handler 检查 `sender_role == "admin"` 或 workspace 权限
4. ✅ 通过 → 执行 → 返回结果消息 | ❌ 拒绝 → 返回 error

### 5.2 权限检查分层

```
!create_workspace
    │
    └── sender_role == "admin"  ← 单层检查，简单直接

!close_workspace ws:xxx
    │
    ├── sender_role == "admin"  → 全部放行 ✅
    └── sender_role == "member"
            │
            └── 检查该 workspace 的 admin_ids 是否包含 sender_id
                    │
                    ├── 是 → 工作室管理员 ✅
                    └── 否 → ❌ 拒绝
```

## 6. 执行方式

### 6.1 现有重用

现有 `server/` 模块中已有完整的业务函数可直接调用：

| 功能 | 已有函数/模块 | 位置 |
|:-----|:-------------|:-----|
| 创建工作室 | `workspace.create_workspace()` | `server/workspace.py` |
| 关闭工作室 | `workspace.close_workspace()` | `server/workspace.py` |
| 审批配对码 | `auth.approve()` | `server/auth.py` |
| 审批管理员 | `workspace.approve_admin_request()` | `server/workspace.py` |
| 拒绝管理员 | `workspace.reject_admin_request()` | `server/workspace.py` |
| 待审批列表 | `workspace.get_pending_requests()` | `server/workspace.py` |
| 已认证用户 | `persistence.get_approved_users()` | `server/persistence.py` |
| 审计日志 | `AuditLogger` | `scripts/admin/lib/audit.py` |

### 6.2 执行流程

```
handler.handle_broadcast() 收到消息
    │
    ├── 频道 != "_admin" 且不以 "!" 开头 → 走标准路由
    │
    └── 频道 == "_admin" 且内容以 "!" 开头 → 进入 admin_commands 路由
            │
            ├── 解析命令名和参数
            ├── 检查 sender_role 权限
            │       │
            │       ├── P4 超级管理员 → 全部放行
            │       ├── P3 工作室管理员 → 检查 workspace 范围
            │       └── P1 普通成员 → ❌ 拒绝
            │
            ├── 执行对应业务函数
            ├── 记录审计日志
            └── 向管理频道回复执行结果（一问一答）

**返回结果格式：** 执行结果通过 `_send()` 发回管理频道（`_admin`），消息接收者为发送者。响应为自然语言文本，类似对话。

### 6.3 审计日志

每次管理操作记录：

```
{
  "ts": 1712345678.0,
  "operator": "agent_id_xxx",
  "command": "!close_workspace",
  "params": {"workspace_id": "ws:R35-dev", "reason": "开发完成"},
  "result": "success",
  "detail": "工作室已归档，3 名成员已通知"
}
```

审计日志写入 `_audit_log.json`（与现有 `workspaces.json`、`_approved_users.json` 同级），后续可通过 `!audit_log` 查询。

## 7. 验收标准

### 7.1 基础鉴权

| # | 用例 | 预期 |
|:-:|:-----|:------|
| A-T1 | 普通成员（role=member）在管理频道发 `!create_workspace` | ❌ 拒绝，返回「权限不足：该操作仅管理员可执行」 |
| A-T2 | 普通成员在大厅发 `!create_workspace` | ❌ 拒绝，返回「! 命令仅在管理频道有效」 |
| A-T3 | 超级管理员在管理频道发 `!create_workspace R35-dev --members pm-bot,dev-bot` | ✅ 工作室创建成功，管理频道回复「工作室 R35-dev 已创建，成员：pm-bot, dev-bot」 |
| A-T4 | 工作室管理员在管理频道关闭自己管理的 workspace | ✅ 关闭成功，管理频道回复确认 |
| A-T5 | 工作室管理员在管理频道关闭非自己管理的 workspace | ❌ 拒绝「权限不足：你不是该工作室的管理员」 |

### 7.2 工作室管理

| # | 用例 | 预期 |
|:-:|:-----|:------|
| B-T1 | `!close_workspace ws:R35-dev --reason "开发完成"` | 工作室归档，成员收到 closing 通知 |
| B-T2 | `!list_workspaces` | 返回工作室列表（id + name + member_count + status）|

### 7.3 成员管理

| # | 用例 | 预期 |
|:-:|:-----|:------|
| C-T1 | `!list_agents` | 返回 agent 列表（agent_id + name + role + status）|
| C-T2 | `!agent_status pm-bot` | 返回 agent 详情（role、workspace、活跃频道、最近活动）|
| C-T3 | `!approve_pairing ABC12345 --role member` | 配对码生效，agent 获得 member 角色 |
| C-T4 | `!approve_ws_admin --workspace ws:R35-dev --agent pm-bot` | pm-bot 成为 R35-dev 的工作室管理员 |
| C-T5 | `!reject_ws_admin --workspace ws:R35-dev --agent pm-bot --reason "试用期不足"` | 申请被拒绝，pm-bot 收到拒绝通知 |

### 7.4 审计

| # | 用例 | 预期 |
|:-:|:-----|:------|
| D-T1 | 超级管理员执行 `!create_workspace` | 审计日志记入 `_audit_log.json` |
| D-T2 | `!audit_log --limit 10` | 返回最近 10 条审计记录 |
| D-T3 | 工作室管理员查询 `!audit_log` | 仅看到自己相关的操作记录 |

### 7.5 安全

| # | 用例 | 预期 |
|:-:|:-----|:------|
| E-T1 | 未认证连接发 `!<命令>` 到管理频道 | 无响应（连接未 auth，无法发送消息） |
| E-T2 | 普通成员试图将活跃频道切换到 `_admin` | 被拒绝，`_admin` 仅管理员可见 |
| E-T3 | 管理员 `!` 命令执行成功 → 管理频道收到回复 | ✅ 管理频道中出现服务端的响应消息 |
| E-T4 | 超级管理员降权后，原来能执行的 `!` 命令不再生效 | 降权后下次操作返回权限错误 |

## 8. 不纳入本次需求

- **Web 管理面板** — 本轮只做对话式触发器，不做 Web UI
- **现有 SSH 脚本删除** — 本轮只新增触发词 + 后台逻辑。现有脚本暂保留用于故障恢复，等 API 稳定运行后再评估清理
- **P3 角色体系全面重构** — 本轮只利用已有的 role=admin / role=member 体系。P3 workspace_admin 角色的全面落地（含限速策略）不在此轮范围

## 9. 影响评估

| 维度 | 评估 |
|:----|:-----|
| **改动范围** | 第①类服务端代码（server/）—— 主要是 `handler.py`（新增 `!` 触发词路由、管理频道 `_admin`）、`server/web_viewer.py` / `server/templates.py`（Web 端第 4 个 Tab）、`workspace.py`、auth.py、persistence.py、protocol.py |
| **新增文件** | 无（功能扩展，不新增目录） |
| **向后兼容** | ✅ 完全兼容 —— `!` 前缀在当前协议中无特殊含义，`_admin` 频道名不在现有频道命名空间中。现有 bot 不会受影响 |
| **部署影响** | 仅需更新 ws-bridge 服务端容器 |
| **外部依赖** | 无新增依赖。审计日志可复用 `scripts/admin/lib/audit.py` 的 AuditLogger（需迁移到 server/ 目录）|
