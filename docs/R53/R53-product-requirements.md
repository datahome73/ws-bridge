# R53 产品需求 — ACK 确认制点名与派活

> **版本：** v0.1（草稿，待审核）
> **状态：** 📋 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-06-29
> **本轮改动范围：** 仅第①类（服务器代码，`server/handler.py` + `shared/protocol.py`）

---

## 1. 问题背景

当前点名→派活的流程存在两个核心断点：

### 断点 1：点名后频道切换无确认

```
系统发 MSG_SET_ACTIVE_CHANNEL ──→ bot 收到 ──→ ...（没有 ACK）
                                     ↓
                               bot 的活跃频道被持久化
                               但系统不知道 bot 是否真的切了
```

R52 修复了 F-20（`_cmd_pipeline_start` 调用 `_broadcast_active_channel`），但 `_broadcast_active_channel` 是**单向广播**，发完即走。系统不知道 bot 是否真的收到了、是否真的切换了活跃频道。

当前的「回复「到」确认」和「3 分钟超时默认到齐」都是为 Web 端人工观察设计的文本消息机制，不是协议级的确认。体现在：
- 文本「到」被 `handle_broadcast` 当作普通消息处理，不触发系统状态变更
- 3 分钟超时后系统默认「已到齐」，但 bot 的活跃频道可能根本没切

### 断点 2：派活（Task 分配）的 ACK 未集成到管线状态机

`MSG_TASK_ACK` 协议消息和 `_task_ack_timeout` 计时器已在 R12/R37 实现，但**管线状态机不等待 ACK**。`!step_complete` 点名下一角色后，管线状态已推进到下一 Step，Task 却还在 `submitted` 状态，bot 实际未确认接收。

### 根因汇总

| # | 问题 | 代码路径 |
|:-:|:-----|:---------|
| ① | 点名（MSG_SET_ACTIVE_CHANNEL）是单向广播，无 ACK 确认 | `_broadcast_active_channel()`, `_auto_rollcall_notify()` |
| ② | 「回复到」和「3 分钟超时」是文本机制，不走协议确认 | `_auto_rollcall_notify()`, `_notify_rollcall_complete()` |
| ③ | 任务已创建（submitted）但管线不等待 ACK 就推进 | `_cmd_step_complete()` → `_cmd_rollcall_next()` → `_cmd_task_create()` |
| ④ | `_broadcast_active_channel` 发完就完，不验证 bot 的实际频道切换 | `_broadcast_active_channel()` |

---

## 2. 需求描述

### 需求 A：点名（频道切换）走 ACK 确认

**当前行为：**
系统通过 `_broadcast_active_channel(ws_id)` 向工作室所有成员广播 `MSG_SET_ACTIVE_CHANNEL` 协议消息，然后等 3 分钟超时或文本「到」回复，即认为点名完成。

**目标行为：**

```
系统发 MSG_SET_ACTIVE_CHANNEL ──→ bot 收到并切换频道
             │                         │
             │                    bot 回复 MSG_ACK
             │                    { task_id, channel, status: "switched" }
             │                         │
             ◄─────────────────────────┘
             │
     系统确认：成员已就位
     标记点名完成，推进管线
```

**具体改动：**

1. `_broadcast_active_channel(ws_id)` 除了现有行为（持久化频道 + 广播消息），还要为每个在线成员启动一个 ACK 等待定时器（类似 `_task_ack_timeout`，约 30s 超时）
2. bot 收到 `MSG_SET_ACTIVE_CHANNEL` 后，主动回复一条 ACK 消息：`{"type": "msg_ack", "task_id": "...", "channel": "ws:xxx", "status": "switched"}`
3. 服务端 `handle_broadcast` 中增加对 `MSG_ACK` 的处理：匹配等待中的 ACK 定时器，标记该成员「已确认」
4. 全员确认（或超时未确认）后，`_notify_rollcall_complete()` 返回确认结果：✅ 全部已切换 / ⚠️ N 人未响应
5. 全员点名流程中，如果超时未 ACK，直接通知项目管理（admin-bot）介入

**注意：** 原有的「回复“到”」文本机制和「3 分钟超时」完全移除——这些是为 Web 端人工可见性设计的，不适用 bot 协作环境。

**影响范围：** 
- `_broadcast_active_channel()` — 增加 ACK 等待逻辑
- `_auto_rollcall_notify()` — 移除 3 分钟超时文本机制
- 新增 `_wait_for_ack(ws_id)` 或类似——等待全员 ACK
- `handle_broadcast()` — 新增 `MSG_ACK` 消息处理分支
- `_notify_rollcall_complete()` — 基于 ACK 结果发送确认通知

### 需求 B：派活（Task 分配）走 ACK 确认

**当前行为：**
`_cmd_task_create()` 创建 task 并将状态设为 `submitted`，然后 `_broadcast_task_notify()` 广播任务通知。已有 `MSG_TASK_ACK` 协议消息和 `_task_ack_timeout` 定时器（30s），但管线不等待 ACK 就推进。

**目标行为：**

```
!step_complete StepN ──→ 点名下一角色 ──→ 创建 task (submitted)
                                               │
                                         发送任务通知
                                         含 task_id、context
                                               │
                                         等待 bot MSG_TASK_ACK
                                         含 { task_id, status: "accepted" }
                                               │
                                         ◄─────┘
                                               │
                                         标记 task → "working"
                                         管线状态推进
```

**具体改动：**

1. `_cmd_step_complete()` 调用 `_cmd_rollcall_next()` + `_cmd_task_create()` 后，**不立即返回**，而是进入 ACK 等待状态
2. 等待 ACK 的机制复用现有的 `_task_ack_timers` 和 `_task_ack_timeout`（30s 超时），但需要增强：
   - 现有行为：超时后仅通知 admin，不阻塞管线
   - 新行为：超时后 **升级到项目管理**（TG 私聊通知项目负责人），并在 `_admin` 频道标记「⚠️ 任务未被确认」
3. 收到 MSG_TASK_ACK + status="accepted" 后，将 task 状态从 `submitted` 推进到 `working`，然后正常返回
4. 在 `!pipeline_status` 中区分显示：
   - `submitted`（已创建，等待 ACK）
   - `working`（已 ACK，工作中）
   - `completed`（已完成）

**影响范围：**
- `_cmd_step_complete()` — 集成 ACK 等待逻辑
- `_task_ack_timeout()` — 增强超时处理（管线级升级，不仅是通知 admin）
- `!pipeline_status` — 显示 ACK 状态

### 需求 C：点名 + 派活合并为「分配 + ACK」单步操作

**动机：**
当点名（需求 A）和派活（需求 B）都使用 ACK 确认后，两者在本质上是同一种操作——「分配任务并等待确认」。当前的点名（先频道切换）和派活（后创建 task）是分开的两步，因为点名用于解决「bot 在哪个频道」这个前置问题。一旦频道切换也有 ACK，就可以合一。

**目标行为：**

```
分配 Step N：
  ① _broadcast_active_channel(ws_id)      → 切频道（含 ACK 等待）
  ② _cmd_task_create(context, role, name)  → 创建 task（含 ACK 等待）
  ③ 管线显示：Step N → waiting_ack → working
```

不再是：
```
分配 Step N：
  ① _auto_rollcall_notify()  → 「📋 点名报到，回复 到」
  ② 等待 3 分钟超时
  ③ _cmd_rollcall_next(role)  → 点名某某角色
  ④ _cmd_task_create()  → 创建 task (submitted)
  ⑤ 不等 ACK 就推进
```

**被移除的旧机制：**
- `_auto_rollcall_notify()` 中的「📋 点名报到」文本消息
- `_notify_rollcall_complete()` 的文本确认（消息本身保留，基于 ACK 结果）
- `_cmd_rollcall_role()` 的文本点名消息（替换为协议级 ACK 驱动点名）

**保留的全员点名：**
> **重要——保留 `!rollcall` 全员点名命令，用于全队评审和讨论场景。**
> 
> 当需要所有 bot 汇集到同一个工作室进行方案讨论、全员评审时，管理员的 `!rollcall` 命令继续可用。但它也改为 ACK 确认制——全员收到 MSG_SET_ACTIVE_CHANNEL 后逐个回复 ACK，管理员看到 ACK 计数确认全员到位。

---

## 3. 验收标准

### 需求 A — ACK 点名

| # | 验收标准 | 验证方法 | 优先级 |
|:-:|:---------|:---------|:------:|
| A-1 | `!pipeline_start` 全员点名后，在线 bot 收到 MSG_SET_ACTIVE_CHANNEL 并回复 ACK，系统标记「✅ 已确认」 | 直连 WS 触发管线，观察 bot 是否回复 MSG_ACK，系统是否确认 | P0 |
| A-2 | 收到 ACK 后 bot 的活跃频道已持久化到新工作室 | `!agent_status <agent_id>` 检查 `active_channel` | P0 |
| A-3 | 超时（30s）未 ACK 的 bot 被标记为「⚠️ 未响应」，系统通知项目管理 | 观察 30s 后 `_admin` 频道的超时通知 | P0 |
| A-4 | 原有的「回复「到」」文本确认和「3 分钟超时」机制完全移除 | 确认 `_auto_rollcall_notify()` 中无相关文本逻辑 | P1 |
| A-5 | `!rollcall` 全员点名命令改用 ACK 确认，管理员看到 ACK 计数确认全员到位 | 执行 `!rollcall`，观察 ACK 计数 | P0 |

### 需求 B — ACK 派活

| # | 验收标准 | 验证方法 | 优先级 |
|:-:|:---------|:---------|:------:|
| B-1 | `!step_complete` 调用后，创建 task (submitted) 并等待 bot MSG_TASK_ACK | 直连 WS 观察，创建 task 后不立即返回「✅」 | P0 |
| B-2 | bot 回复 MSG_TASK_ACK + status="accepted" 后，task 标记为 working | `!pipeline_status` 查看 task 状态 | P0 |
| B-3 | 30s 超时未收到 ACK，`_admin` 频道显示「⚠️ 任务未被确认」升级通知 | 等待 30s，观察超时消息 | P1 |
| B-4 | bot 离线时任务进入离线队列，上线后补发并走 ACK | 断线 bot 重新上线后观察 | P1 |
| B-5 | `!pipeline_status` 显示 ACK 状态（submitted / waiting_ack / working / completed） | 执行 `!pipeline_status` 查看状态显示 | P0 |

### 需求 C — 合并分配

| # | 验收标准 | 验证方法 | 优先级 |
|:-:|:---------|:---------|:------:|
| C-1 | 一次 `!step_complete` 调用完成：切频道 ACK + 创建 task ACK，中间无需人工干预 | 触发完整管线 Step，观察自动流转 | P0 |
| C-2 | 原有文本「📋 点名报到」消息不再发送 | 观察工作室频道，无该消息 | P1 |
| C-3 | 保留 `!rollcall` 全员点名命令，规则同需求 A-5 | 执行 `!rollcall` 验证 | P1 |

---

## 4. 过渡期方案

鉴于以下现实约束：
- ⚠️ R52 F-20 修复刚部署，`_broadcast_active_channel` 在 `_cmd_pipeline_start` 中的调用只上线了一次轮次
- ⚠️ 所有 bot 客户端需要支持 `MSG_ACK` 协议消息（当前仅服务端有 ACK 处理能力）
- ⚠️ 如果本轮开发周期长，中间需要保底机制让管线能继续运转

**建议：采用双轨并行开发**

| 方向 | 内容 | 依赖 | 优先级 |
|:----:|:-----|:-----|:------:|
| **A（主方向）** | 服务端 ACK 点名 + ACK 派活完整实现。改动 `handler.py` + `protocol.py` | 无外部依赖 | 🔴 P0 |
| **B（过渡保底）** | 当前文本点名机制降级为兜底：如果 ACK 超时（30s），fallback 到当前行为（超时默认通过 + 通知 admin），不阻塞管线 | 方向 A 完成后再做 | 🟡 P2 |

**不纳入本轮：**
- ❌ 不在 Gateway 侧或 bot 客户端侧做 MSG_ACK 支持——本轮只改 ws-bridge 服务端（第①类）
- ❌ 不在 Web 端增加 ACK 状态显示
- ❌ 不重写 `_task_ack_timeout` 之外的 ACK 定时器机制

> **技术方案（具体实现方式）由架构师决定。**

---

## 5. 不纳入本轮

- 📦 bot 客户端的 MSG_ACK 协议适配（各 bot 自行实现）
- 🖥️ Web 端 ACK 状态可视化
- 🔄 `!step_handoff` / `!pipeline_activate` 等过渡命令的 ACK 改造
- 📋 历史 Step 的 ACK 数据追溯
