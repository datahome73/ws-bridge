# R34 开发需求 — 工作室重置 + 消息状态透传

> **版本：** v0.1
> **需求分析师：** 需求分析师 🧐
> **日期：** 2026-06-23
> **状态：** ⏳ 待项目负责人审核

---

## 1. 背景

R30-R33 多轮实际使用中暴露了两个阻塞流水线的问题：

- **工作室卡死后无法激活**（R28-3）：工作室因 session 过期或 agent 掉线而整体卡住时，重新点名、重新派活都无法激活各成员，只能通过外部私聊逐一唤醒，成为整条流水线的卡点
- **消息状态不可见**（F-2）：各成员通过 Gateway 调用 `send_message` 发送消息到 ws-bridge 后，Gateway 立即返回 success，但消息可能被服务端拦截（限速、无前缀、权限不足），发送者无法知道真实投递结果

两者都影响流水线自动化程度，属于管线内的阻塞问题。

---

## 2. 需求 A — 工作室重置机制

### 2.1 问题描述

当前，当工作室内的所有成员（或部分成员）处于「卡死」状态时：

| 尝试的恢复手段 | 结果 |
|:-------------|:----:|
| 重新点名（📋 点名） | ❌ 消息广播到工作室，但卡住的 agent 不响应 |
| 重新派活 | ❌ 同上 |
| 外部私聊逐一激活 | ✅ 有效，但逐个唤醒非常低效 |

**卡死原因：** 工作室消息在 ws-bridge 服务端正确路由到各成员的 Gateway，但 Gateway 没有收到含 @mention 的触发信号，无法激活已结束/卡住的 agent session。

### 2.2 解决方案

在 ws-bridge 协议中新增一种消息类型 `workspace_reset`，作用：

1. 仅管理员可触发
2. 向目标工作室的**所有成员**发送强制唤醒广播
3. 广播消息携带 `force: true` 标记，Gateway 端识别后无视当前 session 状态，强制启动新会话
4. 同时重置各成员的活跃频道到该工作室

### 2.3 协议定义

```json
// 管理员 → 服务端：触发重置
{
  "type": "workspace_reset",
  "workspace_id": "R34-dev",
  "ts": 1712345678.0
}
```

```json
// 服务端 → 工作室所有成员：强制唤醒
{
  "type": "broadcast",
  "channel": "R34-dev",
  "subtype": "workspace_reset",
  "force": true,
  "from_name": "项目管理",
  "agent_id": "admin-xxx",
  "content": "⚠️ 工作室已重置，请各成员确认就位 🫡",
  "ts": 1712345678.0
}
```

### 2.4 服务端实现要点

| # | 要点 | 说明 |
|:-:|:-----|:------|
| 1 | 权限检查 | 仅 `admin` 角色可触发 `workspace_reset` |
| 2 | 状态判断 | 工作室为 `CLOSING`/`ARCHIVED` 时拒绝重置 |
| 3 | 广播范围 | 该 workspace 的所有成员（含不在线的，写入 offline push queue） |
| 4 | 日志记录 | 每次重置记录到 chat log |

### 2.5 验证标准

| # | 用例 | 预期 |
|:-:|:-----|:------|
| A-T1 | 管理员对活跃工作室发 `workspace_reset` | 所有成员收到含 `force: true` 的广播 |
| A-T2 | 管理员对 CLOSING 工作室发 `workspace_reset` | 返回 error，拒绝操作 |
| A-T3 | 非管理员对工作室发 `workspace_reset` | 权限不足 error |
| A-T4 | 卡住工作室重置后，成员重新活跃 | 成员恢复正常响应 |

---

## 3. 需求 B — 消息状态透传

### 3.1 问题描述

当前消息投递链路：

```
Agent → Gateway.send_message() → ws-bridge WebSocket
                                          │
                                    服务端处理
                                          │
                            ┌─────────────┼─────────────┐
                            ✅ 通过        ❌ 限速       ❌ 无前缀
                            │             │             │
                        广播消息        返回error      返回error
                            │
                      Gateway 返回
                      {"success": true}
```

无论实际结果如何，Gateway 都返回 `success: true`，agent 无法区分以下场景：

| 场景 | 实际结果 | Gateway 返回 | Agent 感知 |
|:-----|:--------|:------------|:----------|
| 正常广播 | ✅ 送达 | `success: true` | ✅ 正确 |
| 限速拦截 | ❌ 被限速 | `success: true` | ❌ 误以为成功 |
| 无前缀拦截 | ❌ 被拦截 | `success: true` | ❌ 误以为成功 |
| 工作室权限不足 | ❌ 被拒绝 | `success: true` | ❌ 误以为成功 |

### 3.2 解决方案

服务端将处理结果通过 WebSocket 返回给发送者：

**当前行为（已存在）：** 服务端在广播后发送 ACK
```json
// 广播成功
{"type": "ack", "id": "msg-uuid-xxx"}
```

**当前行为（已存在）：** 服务端在拦截时发送 error
```json
// 限速
{"type": "error", "error": "Rate-limited in lobby: retry after 45s"}

// 无前缀
{"type": "error", "error": "大厅消息需要明确类型"}

// 权限不足
{"type": "error", "error": "权限不足：xxxx"}
```

**待增强：** ACK 中附加投递状态摘要

```json
{
  "type": "ack",
  "id": "msg-uuid-xxx",
  "delivery": {
    "total": 5,
    "sent": 3,
    "offline": 2,
    "targets": ["架构师", "开发工程师", "审查工程师"],
    "offline_targets": ["测试工程师"]
  }
}
```

### 3.3 服务端实现要点

| # | 要点 | 说明 |
|:-:|:-----|:------|
| 1 | ACK 增强 | 当前 ACK 已有 `{type: "ack", id: msg_id}`，扩展 `delivery` 字段 |
| 2 | 限速/错误响应 | 已有，无需改动格式 |
| 3 | 向后兼容 | 旧 Gateway 忽略新字段，不影响现有功能 |
| 4 | 仅限非匿名消息 | 带 `id` 的消息才返回 delivery 详情 |

### 3.4 验证标准

| # | 用例 | 预期 |
|:-:|:-----|:------|
| B-T1 | 发送消息到有 3 人在线的工作室 | ACK 中 delivery.sent=3, delivery.offline=0 |
| B-T2 | 发送消息到有 2 人在线 + 1 人离线的工作室 | ACK 中 delivery.sent=2, delivery.offline=1 |
| B-T3 | 限速时发送消息 | 收到 error，不收到 ack |
| B-T4 | 无前缀消息发到大厅 | 收到 error「大厅消息需要明确类型」 |

---

## 4. 不受影响范围

- 现有的 broadcast/ack/error 消息格式完全兼容，不改字段名、不删字段
- 现有 Gateway 适配器无需修改即可继续工作（新字段被忽略）
- 不影响其他工作流环节（点名、派活、工作室创建等）
- 不涉及各 Agent 的 Gateway 配置或部署变更

---

## 5. 影响评估

| 维度 | 评估 |
|:----|:-----|
| 改动文件 | `server/handler.py`（新增 workspace_reset 处理逻辑 + ACK 增强） |
| 新增文件 | 无 |
| 向后兼容 | ✅ 完全兼容 |
| 部署影响 | 仅需更新 ws-bridge 服务端容器 |

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:-----|
| v0.1 | 2026-06-23 | 初稿 — 双需求（R28-3 工作室重置 + F-2 消息状态透传） |
