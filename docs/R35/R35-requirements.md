# R35 产品需求 — 管理员 API 授权机制

> **版本：** v0.1（草稿，待项目负责人审核）
> **状态：** 📋 草稿
> **产品经理：** 🧐 需求分析师
> **日期：** 2026-06-23

## 1. 背景与痛点

当前 ws-bridge 的所有管理操作通过 SSH 进入容器后执行脚本来完成，存在以下问题：

| 痛点 | 说明 | 严重度 |
|:-----|:------|:------:|
| 🔴 **不安全** | 管理操作不经过任何身份验证，有容器权限即可执行 | P0 |
| 🟡 **不可扩展** | 每次新增管理功能都需要写新脚本、部署，无法快速响应 | P1 |
| 🟡 **脱离协议** | 脚本直接读写数据文件，绕过 WebSocket 协议的消息路由和权限检查 | P1 |
| 🟡 **不透明** | 操作无审计记录（谁做了什么、何时做的），无法追溯 | P2 |
| 🟢 **API 断层** | Web 端已有部分 API（/api/agents/status），但管理操作无 API 暴露，上层工具无法集成 | P3 |

## 2. 现状分析

### 2.1 现有管理脚本

当前 `scripts/admin/` 目录下共 **12 个管理脚本**，全部通过 SSH 执行：

| 脚本 | 功能 | 权限要求（当前） |
|:-----|:-----|:----------------|
| `create_workspace.py` | 创建工作区 | 容器访问 |
| `close_workspace.py` | 关闭工作区 | 容器访问 |
| `approve_pairing.py` | 审批配对码 | 容器访问 |
| `approve_bind.py` | 审批 Web 绑定 | 容器访问 |
| `approve_workspace_admin.py` | 审批工作室管理员申请 | 容器访问 |
| `request_workspace_admin.py` | 申请成为工作室管理员 | 容器访问 |
| `list_agents.py` | 列出所有已认证 agent | 容器访问 |
| `list_workspace_admins.py` | 列出工作室管理员 | 容器访问 |
| `agent_status.py` | 查看 agent 详细信息 | 容器访问 |
| `audit_log.py` | 查看审计日志 | 容器访问 |

### 2.2 现有 API & 授权基础

- **已有角色体系：** `admin`（超级管理员）/ `member`（普通成员）/ `unregistered`（未注册）
- **已有 WebSocket 协议：** handler.py 中有 auth_ok、broadcast、ack 等消息路由
- **已有 HTTP API：** `__main__.py` 中已有 `/api/agents/status`、`/api/channels`、`/api/approve_web` 等端点
- **已有审核列表：** workspace 模块有 `_admin_requests`、`get_pending_requests()`、`approve_admin_request()` 等
- **已有审计日志：** scripts/admin/lib/audit.py 中的 AuditLogger

### 2.3 角色权限定义

| 角色 | 级别 | 可执行的操作 |
|:-----|:----:|:------------|
| 🦸 **超级管理员** (admin) | P4 | 全部管理操作：创建/关闭工作室、审批所有请求、管理成员角色、查看所有数据 |
| 🔧 **工作室管理员** (workspace_admin) | P3 | 仅操作所属工作室：管理工作室成员、查看工作室状态 |
| 🧑 **普通成员** (member) | P1 | 无管理权限，仅参与工作室协作 |

## 3. 需求方案

### 3.1 设计原则

1. **不走 SSH** — 所有管理操作通过 WebSocket 协议消息或 HTTP API 完成
2. **每次调用都鉴权** — 每步操作检查调用者的 role，非 admin 拒绝
3. **超级管理员 vs 工作室管理员分层** — 超级管理员全权限，工作室管理员仅管理自己所属工作室
4. **现有 WebSocket handler 优先** — 可复用的走 WebSocket 协议消息（如 create_workspace 可通过协议消息触发），不适合的走 HTTP API
5. **审计日志** — 每次管理操作记录操作者、操作时间、操作内容

### 3.2 管理操作分类

#### A 类：可直接通过 WebSocket 协议消息实现（已有基础）

这些操作已有 WebSocket handler 或路由机制，可直接复用：

| 操作 | 实现方式 | 当前状态 |
|:-----|:---------|:---------|
| 📋 点名 | 已有协议消息 | ✅ 已有 |
| 🆘 求助 | 已有协议消息 | ✅ 已有 |
| 📢 公告广播 | 已有前缀过滤 | ✅ 已有 |
| 🔄 工作室重置 | workspace_reset（R34） | ✅ 已有 |

#### B 类：需新增 WebSocket 协议消息

| 操作 | 建议消息类型 | 说明 |
|:-----|:------------|:------|
| 🏗️ 创建工作室 | `admin_create_workspace` | 超级管理员通过协议消息创建工作室 |
| 🚪 关闭工作室 | `admin_close_workspace` | 超级管理员/工作室管理员关闭工作室（带权限检查） |
| ✅ 审批配对码 | `admin_approve_pairing` | 超级管理员在 WebSocket 中审批配对请求 |
| 👥 审批工作室管理员 | `admin_approve_ws_admin` | 超级管理员审批/拒绝工作室管理员申请 |
| 📋 列出 agent | `admin_list_agents` | 返回 agent 列表 |
| 🔍 查看 agent 状态 | `admin_agent_status` | 返回指定 agent 详情 |

#### C 类：通过 HTTP API 暴露（适合查询类操作）

这些操作适合走 HTTP API（当前已有 `/api/` 端点模式）：

| 操作 | 建议 API 端点 | 当前状态 |
|:-----|:--------------|:---------|
| 查看所有 agent | `GET /api/admin/agents` | 已有 `/api/agents/status`（未鉴权）|
| 查看 audit 日志 | `GET /api/admin/audit` | 新加 |
| 查看待审批列表 | `GET /api/admin/pending` | 新加 |

### 3.3 鉴权机制

**通用鉴权流程：**

```
管理员 → WebSocket 发送协议消息 { type: "admin_xxx", ..., token: "<auth_token>" }
                                  │
                            服务端验证
                                  │
                    ┌─────────────┼─────────────┐
                    │ admin       │ workspace_   │ non-admin
                    │ (super)     │ admin        │
                    ▼             ▼             ▼
              全部放行    仅限自己管理     ❌ 拒绝
                          的工作室范围
```

**鉴权方式（待项目负责人确认方向）：**

| 方案 | 描述 | 优 | 劣 |
|:----|:-----|:---|:---|
| **A — 基于已认证 WebSocket 连接** | 管理员通过已认证的 WebSocket 连接发消息，服务端从连接 session 中获取 sender_role 和 agent_id | 无需额外 token，复用现有连接鉴权 | 管理操作必须走 WebSocket 通道 |
| **B — 基于 API Key / Token** | 管理员在 HTTP API 请求头中带 API Key，服务端验证 key 对应的角色 | 支持 HTTP API 调用，不依赖 WebSocket 连接 | 需新增 token 管理和分发机制 |
| **C — A+B 混合** | WebSocket 操作复用现有连接鉴权（方案 A）；HTTP API 操作用 API Key（方案 B） | 各取所长 | 维护两套鉴权 |

### 3.4 权限矩阵

| 操作 | 超级管理员 (P4) | 工作室管理员 (P3) | 说明 |
|:-----|:---------------:|:-----------------:|:-----|
| 创建工作室 | ✅ | ❌ | 新建 workspace |
| 关闭工作室 | ✅ | ✅（仅自己管理的工作室）| 归档 workspace |
| 审批配对码 | ✅ | ❌ | 通过/拒绝配对申请 |
| 审批工作室管理员 | ✅ | ❌ | 通过/拒绝管理员申请 |
| 工作室重置 | ✅ | ✅（仅自己管理的工作室）| 已有 R34 workspace_reset |
| 列出 agent | ✅ | ✅（仅自己工作室成员）| 查看成员 |
| 查看 agent 状态 | ✅ | ✅（仅自己工作室成员）| 查看详情 |
| 任命工作室管理员 | ✅ | ❌ | 直接指定某人为管理员 |
| 查看审计日志 | ✅ | ✅（仅自己相关操作）| Audit trail |

## 4. 验收标准

### 4.1 基础鉴权

| # | 用例 | 预期 |
|:-:|:-----|:------|
| A-T1 | 普通成员发送 admin_create_workspace 消息 | 被拒绝，返回 error {type: "error", error: "权限不足"} |
| A-T2 | 超级管理员发送 admin_create_workspace 消息 | 工作室创建成功 |
| A-T3 | 工作室管理员关闭自己管理的工作室 | 关闭成功 |
| A-T4 | 工作室管理员关闭非自己管理的工作室 | 被拒绝 |

### 4.2 管理操作

| # | 用例 | 预期 |
|:-:|:-----|:------|
| B-T1 | 管理员通过协议消息创建工作室 | 工作室创建成功，所有成员收到通知 |
| B-T2 | 管理员通过协议消息关闭工作室 | 工作室归档，成员收到 closing 通知 |
| B-T3 | 管理员审批配对码 | 配对码生效，agent 获得对应角色 |
| B-T4 | 管理员列出所有在线 agent | 返回 agent 列表（id + name + role + status）|
| B-T5 | 管理员查看 agent 状态详情 | 返回完整信息（workspace、channel、在线状态）|

### 4.3 安全

| # | 用例 | 预期 |
|:-:|:-----|:------|
| C-T1 | 未认证连接发送 admin_* 消息 | 无响应（连接未 auth）|
| C-T2 | 每次管理操作记录到审计日志 | 审计日志包含 timestamp + operator + operation + result |
| C-T3 | 超级管理员降权普通成员后，该成员不能再执行管理操作 | 后续管理操作被拒绝 |

## 5. 不纳入本次需求

- **Web 管理面板 UI** — 本轮只做 API/协议层，不做前端页面
- **P3 角色体系全面完善** — 本轮只解决 P4↔P3 的管理 API，不涉及 P0~P2 角色体系重构
- **脚本删除** — 现有 SSH 脚本暂不删除，API 上线稳定后再清理

## 6. 影响评估

| 维度 | 评估 |
|:----|:-----|
| **改动范围** | 第①类服务端代码（server/）—— handler.py + __main__.py + protocol.py + persistence.py |
| **新增文件** | 无（功能扩展，不新增目录） |
| **向后兼容** | ✅ 向后兼容 —— 现有 WebSocket 连接行为和消息格式不变，仅新增 admin_* 消息类型 |
| **部署影响** | 仅需更新 ws-bridge 服务端容器 |
| **外部依赖** | 无新增依赖 |
