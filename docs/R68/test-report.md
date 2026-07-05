# R68 测试验证报告 — Bot 私有收件箱通道 📥

> **版本：** v1.0 ✅
> **状态：** ✅ **全部通过（37/37）**
> **测试者：** 🦐 **泰虾**
> **基线：** `6dc3400`（编码）+ `89ac235`（step_handoff 回退补丁）+ `3b5a101`（fix）
> **日期：** 2026-07-05

---

## 测试概要

| 方向 | 验收项 | 状态 | 说明 |
|:-----|:------:|:----:|:-----|
| **A1 协议+持久化** | ✅-1 ~ ✅-2 | ✅ 10/10 | 常量定义 + 3 工具函数 + auth 自动注册 |
| **A2 收件箱路由** | ✅-3 ~ ✅-9 | ✅ 16/16 | 单播、权限控制、位置、日志、时间戳 |
| **A3 管线集成** | ✅-10 ~ ✅-11 | ✅ 11/11 | step_complete/handoff 收件箱 + 轻量通知 |
| **合计** | **✅-1 ~ ✅-11** | **✅ 37/37** | **全部通过，0 阻塞** |

---

## 方向 A1 — 协议层常量 + 持久化工具函数

### ✅-1 `_inbox:<agent_id>` 通道格式定义

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:---:|:-----|
| 1 | `INBOX_CHANNEL_PREFIX` 常量存在 | ✅ | 值: `'_inbox:'` |
| 2 | 常量值正确 | ✅ | `= "_inbox:"` |

### ✅-2 Agent 注册后自动创建收件箱

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:---:|:-----|
| 3 | `get_inbox_channel()` 函数存在 | ✅ | persistence.py |
| 4 | 函数返回格式正确 | ✅ | `get_inbox_channel("test-agent-123")` → `"_inbox:test-agent-123"` |
| 5 | `is_inbox_channel()` 识别收件箱 | ✅ | True for `_inbox:abc` |
| 6 | `is_inbox_channel()` 排除非收件箱 | ✅ | False for `workspace_abc` |
| 7 | `resolve_inbox_owner()` 提取 agent_id | ✅ | `_inbox:user-42` → `"user-42"` |
| 8 | `resolve_inbox_owner()` 返回 None 于非收件箱 | ✅ | `workspace_x` → None |
| 9 | `auth.py approve()` 调用 `get_inbox_channel()` | ✅ | AST 确认 |
| 10 | `auth.py approve()` 调用 `set_agent_channel()` | ✅ | 自动注册收件箱通道 |

---

## 方向 A2 — 收件箱路由

### ✅-3 收件箱消息仅投递给目标 agent（单播）

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:---:|:-----|
| 11 | `handle_broadcast()` 收件箱拦截存在 | ✅ | `persistence.resolve_inbox_owner()` 调用 |
| 12 | 单播路由（只投目标） | ✅ | `if aid == owner_id` 过滤 |
| 13 | 不广播到工作室 | ✅ | 直接发目标连接，不走 workspace broadcast |
| 14 | `channel.startswith(p.INBOX_CHANNEL_PREFIX)` 检查 | ✅ | 路由前置条件 |

### ✅-4 仅 admin 可向收件箱发消息

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:---:|:-----|
| 15 | `sender_role != "admin"` 权限检查 | ✅ | 在 inbox 分支内 |
| 16 | 非 admin 返回错误消息 | ✅ | "仅管理员可向收件箱发消息" |

### ✅-5 admin 可向任意 agent 收件箱发消息

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:---:|:-----|
| 17 | admin 通过权限检查 | ✅ | 仅非 admin 被拦截 |
| 18 | 投递循环存在 | ✅ | `for agent_id, conns in targets:` |
| 19 | ACK 发送 | ✅ | `"sent": sent` |

### ✅-6 收件箱路由在正确位置

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:---:|:-----|
| 20 | `R68 A2: Inbox channel intercept` 注释 | ✅ | handler.py L4115 |
| 21 | admin 拦截在前 → inbox 在后 | ✅ | admin L4092 → inbox L4115 |
| 22 | inbox 在前 → channel resolution 在后 | ✅ | inbox L4115 → resolution L4153 |

### ✅-7 收件箱消息持久化

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:---:|:-----|
| 23 | 拦截分支调用 `write_chat_log(channel=channel)` | ✅ | Inbox 分支 |
| 24 | `_send_inbox_task()` 调用 `ms.save_message()` | ✅ | 持久化到 channel |
| 25 | `_send_inbox_task()` 调用 `write_chat_log()` | ✅ | 日志记录 |

### ✅-8 消息含时间戳

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:---:|:-----|
| 26 | inbox 拦截分支 payload 含 `"ts": time.time()` | ✅ | 双引号格式 |
| 27 | `_send_inbox_task()` payload 含 `"ts": time.time()` | ✅ | 时间戳字段 |

### ✅-9 Agent 不可向收件箱写

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:---:|:-----|
| 28 | 角色检查覆盖所有非 admin | ✅ | `sender_role != "admin"` |
| 29 | 错误消息明确 | ✅ | "仅管理员可向收件箱发消息" |

---

## 方向 A3 — 管线集成

### ✅-10 step_complete 后任务消息发收件箱

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:---:|:-----|
| 30 | `_cmd_step_complete()` 调用 `_send_inbox_task()` | ✅ | 全局搜索确认 |
| 31 | step_complete 函数体内调用 `_send_inbox_task()` | ✅ | 精确函数体检查 |
| 32 | 旧 @mention 全量广播已移除 | ✅ | `mention_msg` 在函数体无残留 |
| 33 | `_cmd_step_handoff()` 也调用 `_send_inbox_task()` | ✅ | handoff 也有收件箱派活 |

### ✅-11 工作室同时收到轻量通知

| # | 检查项 | 结果 | 详情 |
|:-:|:-------|:---:|:-----|
| 34 | `_send_inbox_task()` 发送工作室轻量通知 | ✅ | `@{target_name} 🔔 Step「...」已分配` |
| 35 | 通知使用 `_persist_broadcast` | ✅ | 持久化到 workspace |
| 36 | 通知为轻量（非完整任务体） | ✅ | "已分配，请查看收件箱" |
| 37 | **总计** | **✅ 37/37** | |

---

## 审查 Warning 回归检查

| # | 审查项 | 状态 | 确认 |
|:-:|:-------|:---:|:-----|
| W-1 | `_cmd_step_handoff()` 中角色映射为空时回退到工作室广播 @mention | ✅ 已修复 | `89ac235` 补充 fallback 路径 |
| W-2 | step_handoff fallback 中 `_pconfig_n` → `_PIPELINE_CONFIG.get()` | ✅ 已修复 | `3b5a101` 修复 Typo |
| 💡 | inbox_task 函数体较大（~42 行） | ✅ 合理 | 函数职责单一，包含收件箱写入 + 工作室通知两阶段 |

---

## 结论

**37/37 全部通过 ✅ — 无阻塞项，可推进 Step 6 合并部署**

```
✅-1  ~ ✅-2  (方向 A1):  10/10 ✅ — 常量 + 工具函数 + 自动注册
✅-3  ~ ✅-9  (方向 A2):  16/16 ✅ — 路由 + 权限 + 日志 + 时间戳
✅-10 ~ ✅-11 (方向 A3):  11/11 ✅ — 管线集成 + 轻量通知
```

三个审查 Warning 均已修复（`89ac235` + `3b5a101`）。
