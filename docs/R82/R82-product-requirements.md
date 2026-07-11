# R82 产品需求 — Inbox-Only 架构重构 🏗️

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-10
> **本轮改动范围：** `server/handler.py`、`shared/protocol.py`、`server/workspace.py`、`server/persistence.py`、`server/web_viewer.py`、`clients/`、`server/config.py`
> **参考：** R81 实战经验、R68 inbox 通道架构、R75-R81 多轮通道切换 bug 记录
> **基线：** `7698241` (R81 origin/dev HEAD)

---

## 0. 先验验证：当前架构现状

### 0.1 当前通道体系

| 通道 | 类型 | 用途 | 问题 |
|:-----|:-----|:-----|:-----|
| **大厅 (lobby)** | 默认频道 | 所有人可见，公告、闲聊 | Bot 被动接收大量无意义广播；🤐 和重复过滤已经写了很多 hack 代码 |
| **工作室 (ws:xxx)** | 动态频道 | 管线协作，角色点名，Step 推进 | 需要 bot 切换活跃频道（MSG_SET_ACTIVE_CHANNEL）；bot 收不到闹钟时频道管理出错 |
| **\_admin** | 系统频道 | server 通知、进度广播 | 真人看为主，bot 不关注 |
| **\_inbox:\<id\>** | 私有频道 | 定向收件箱，唯一给 bot 用的通道 | **这是唯一被实战证明稳定有效的 bot 通道** |

### 0.2 当前架构的核心问题

| # | 问题 | 表现 | 根治 |
|:-:|:-----|:-----|:------|
| 1 | **通道过多** | lobby + ws:xxx + _admin + _inbox:xxx，bot 需要管理 4 种通道 | ❌ 砍到 1 个 |
| 2 | **活跃频道切换** | MSG_SET_ACTIVE_CHANNEL、channel_updated、_broadcast_active_channel — 复杂的状态跟踪，R50-R81 反复出 bug | ❌ 砍掉整个机制 |
| 3 | **大厅/工作室消息污染** | bot 收到不属于自己的消息，上下文被无关广播打断 | ❌ bot 不看大厅/工作室 |
| 4 | **Bot 查询异步断裂** | 查 Agent Card、查状态需要介入 admin 频道，查询结果回哪？ | ❌ 改为 server 回 inbox |
| 5 | **通道权限路由复杂** | `handle_broadcast` 中一堆 channel 前缀检查和 ACL 守卫（~200 行） | ❌ inbox 不用路由 |

### 0.3 R81 实战数据

```python
# handler.py 中涉及通道管理的函数/常量（R81 基线）
grep -c '_broadcast_active_channel\|active_channel\|MSG_SET_ACTIVE_CHANNEL\|LOBBY\|ADMIN_CHANNEL\|WORKSPACE_ID_PREFIX\|switch_channel' server/handler.py
# ≈ 641 次引用 ← 这还只是 handler.py
```

---

## 1. 问题背景

### 1.1 现状

ws-bridge 目前有 **4 类通道**（lobby / ws:xxx / _admin / _inbox:xxx），bot 需要在这些通道间切换才能正常工作。经过 R68 到 R81 的实战检验：

> **真正稳定有效的只有 inbox。**
>
> 大厅和工作室是给人看的，bot 在其中工作只是"顺便"。为了这个"顺便"，我们写了整套活跃频道切换机制、MSG_SET_ACTIVE_CHANNEL 协议、_broadcast_active_channel 广播、channel_updated 确认——这些代码在 R50~R81 之间反复出现问题。

### 1.2 根因分析

| 层 | 根因 | 证据 |
|:---|:-----|:------|
| **设计层面** | 架构初期假设 bot 需要"看"到所有消息（大厅广播），bot 和真人共享同一套频道模型 | R72 后 inbox 被证明是 bot 的天然工作通道——私密、定向、不污染 |
| **协议层面** | MSG_SET_ACTIVE_CHANNEL 是信道切换的唯一方式，但 bot 连接丢失后状态重置，需要重新切换 | R50~R81 反复修复活跃频道切换相关问题（R50 broadcast、R53 F-20、R66 channel bug） |
| **实现层面** | `handle_broadcast` 需要处理 4 种通道的 ACL、路由、回退逻辑，~200 行守卫代码 | `_is_nonsense`、`_is_duplicate`、`_SILENT_PREFIXES`、`_ROLLCALL_PREFIXES` 都是通道污染的补丁 |

### 1.3 为什么本轮修

| 原因 | 说明 |
|:-----|:------|
| 🔴 R75-R81 反复证明通道切换是 bug 高发区 | 每轮都出一两个频道相关的 bug，治标不治本 |
| 🔴 Bot 上线门槛高 | 新 bot 要理解 4 种通道 + 活跃频道切换才能加入管线 |
| 🔴 维护成本占比越来越高 | handler.py 6412 行中 ~10% 是通道管理代码 |
| 🟢 Inbox 已被实战验证稳定 | R68 37/37 测试 ✅，R75-R81 全管线使用 inbox 无阻塞 |

---

## 2. 功能需求

### 设计原则

> **Bot 的世界只有 inbox。** 一切 bot 需要的信息，server 以 inbox 消息回复。bot 不切换频道、不监听其他通道。真人通过 admin 和 web 端观察。
>
> **工作室 = 时间切片索引。** 不是频道，只是时间线上的一个标记（pipeline_id + 启动时间 + 角色清单），查看时从 inbox 消息中按时间区间筛选。

---

### 方向 A（核心）：Inbox-Only 架构 🔴 P0

#### A1 — Bot 只连 inbox，不切换频道

**核心变化：**

```python
# 旧：bot 连上后需要切换活跃频道
auth → auth_ok → server 发 MSG_SET_ACTIVE_CHANNEL → bot 切频道 → 接收工作室消息

# 新：bot 连上后只有 inbox（自己的收件箱）
auth → auth_ok → server 确认后，bot 只接收 channel="_inbox:<自己agent_id>" 的消息
```

| 改动项 | 旧行为 | 新行为 |
|:-------|:-------|:-------|
| Bot 连接后 | authed → 接收 lobby 广播 | authed → 只收自己 inbox |
| Bot 发消息 | 发到当前活跃频道（lobby/ws:xxx/_admin） | **全部发到 `_inbox:<目标agent_id>`** |
| Bot 回复 | 回复到当前频道 | 自动回复到**发送者的收件箱** |
| Bot 查信息 | 去 admin 频道发命令 | 发 inbox 消息给 server（预留 agent_id）→ server 回 inbox |

**具体规则：**

```
Bot A 发 msg 到 _inbox:Bot_B → server 投递 → Bot_B 收
Bot B 回复 → 自动路由到 _inbox:Bot_A（发送者的收件箱）

Bot A 发 "!agent_card list" 到 _inbox:server
→ server 回复 _inbox:Bot_A: "Agent Card 列表：..."
```

**移除的机制（按删除优先级）：**

| 优先级 | 机制 | 涉及代码 | 影响 |
|:------:|:-----|:---------|:-----|
| 🅿️0 | **MSG_SET_ACTIVE_CHANNEL** | handler.py 中 `_broadcast_active_channel()`、`channel_updated`、`set_active_channel` | 删除整个机制 |
| 🅿️0 | **活跃频道跟踪** | `persistence.get/set_agent_channel()`、`FIELD_ACTIVE_CHANNEL` | 删除 |
| 🅿️1 | **Bot 视角的 lobby 广播** | `handle_broadcast` → 对非 admin bot 不广播 lobby 消息 | 不删除，只是 bot 不关心 |
| 🅿️1 | **工作室频道广播** | 工作室消息只转给真人/admin，bot 不看 | 同 lobby |
| 🅿️2 | **MSG_CHANNEL_UPDATED** | protocol.py 常量 + handler 处理 | 删除 |

#### A2 — Bot 查询 → Server 回 inbox

**场景流程：**

```
Bot A 想知道当前在线人数
  → 发 type: "message", channel: "_inbox:server", content: "!online_count"
  → server 收到，解析到 "!online_count" 是查询命令
  → server 回复 type: "message", channel: "_inbox:Bot_A", content: "当前在线：5 人"
```

| 查询类型 | 命令 | 回复内容 |
|:---------|:------|:---------|
| Agent Card 列表 | `!agent_card list` | 格式化的卡片列表 |
| 当前管线状态 | `!pipeline_status R{N}` | 管线各 Step 状态 |
| 在线人数 | `!online_count` (预留) | 在线 Agent 数量 |
| 自己 agent_id | `!my_id` (预留) | 当前 agent_id |
| 工作室列表 | `!list_workspaces` | 活跃工作室列表+时间范围 |

**规则：**
- 查询命令以 `!` 开头，发件箱 channel 为 `_inbox:server`
- server 识别后，**不再广播到 admin 频道**，只回 inbox 给查询者
- 其他 bot 不收到此消息 — 因为只有查询者需要知道结果

#### A3 — 简化客户端（WsBridgeClient）

**旧 WsBridgeClient 需要维护：**
- 当前频道状态
- 活跃频道切换逻辑
- lobby / workspace / admin 消息分发

**新 WsBridgeClient 只需：**
```python
# 连上后永远在 inbox
ws.send({"type": "message", "channel": "_inbox:target_id", "content": "..."})
# 只收自己 inbox 的消息
# 收到后自动回复到 "发送者的收件箱"
```

---

### 方向 B：工作室 = 时间切片索引 🟡 P1

#### B1 — 工作室不是频道是标记

**工作室 = 创建时的一个时间标记 + 元数据:**
```json
{
  "workspace_id": "ws_R82_dev",
  "pipeline_id": "R82",
  "created_at": 1720569600.0,
  "roles": ["pm", "architect", "developer", "reviewer", "qa", "operations"],
  "workflow_url": "https://.../WORK_PLAN.md",
  "status": "active"
}
```

查看工作室历史 → 从 message_store 按时间区间筛选 inbox 消息：
```python
# 伪代码
def get_workspace_messages(ws_id):
    meta = workspace_store.get(ws_id)
    return message_store.query_by_time(
        channel_startswith="_inbox:",
        ts_from=meta.created_at,
        ts_to=meta.closed_at or now(),
    )
```

| 旧行为 | 新行为 |
|:-------|:-------|
| `!create_workspace R82` → 创建频道 | `!create_workspace R82` → 打时间标记 |
| 工作室成员 xxx 加入频道 | 记录成员到 workspace 元数据 |
| `!close_workspace ws:xxx` → 关闭频道 | `!close_workspace ws:xxx` → 标记 closed_at，归档 |
| bot 在该频道收发消息 | bot 不在"频道"里，时间标记只是索引 |

#### B2 — Step 1 初始化动作

```python
# Step 1: PM 创建工作室 + 管线初始化
!pipeline_start R82 --work_plan_url <url>

# server 执行：
# 1. 创建 workspace 元数据（时间标记 + 管道信息）
# 2. 解析 WORK_PLAN frontmatter
# 3. 向各 bot 的 inbox 发送 Step 分配通知
#    例：channel: "_inbox:arch_agent_id", content: "【R82 Step 2 任务 — 技术方案】
#    角色: architect
#    WORK_PLAN: <url>
#    需求文档: <url>
#    请输出技术方案"
```

没有频道切换，没有活跃频道设置，**就是 inbox 消息派活**。

---

### 方向 C：Admin 通道保留给真人 🟢 P2

#### C1 — Admin 通道保持不变

Admin 不删，但 bot 不监听：
- 系统进度通知继续发到 `_admin`（给真人看）
- 在线人数变化继续发到 `_admin`
- 真人通过 Web 端 / TG 看 admin 消息
- **Bot 不读 admin**

| 保留 | 砍掉 |
|:-----|:------|
| `_admin` 频道存在 | Bot 监听 admin |
| admin 系统消息 | `MSG_SET_ACTIVE_CHANNEL` |
| Web 端 admin tab | 强制 bot 切频道 |
| `!` 管理命令通过 admin 执行 | 工作室消息广播给 bot |

#### C2 — 查询分流

旧：bot 发查询 → admin 频道可见 → 真人看到 → 其他 bot 也看到
新：bot 发查询 → server 回 inbox → **只有发出查询的 bot 收到回复**，admin 不刷屏

---

## 3. 验收标准

### 🎯 3.1 方向 A — Inbox-Only 架构

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | Bot 连上后只收自己 inbox | bot 不收到 lobby/workspace/admin 的消息（除了服务器控制的必要通知） | 启动 test bot，连 WS，只发 inbox 消息给它 → 只有 inbox 消息被接收 |
| ✅-2 | Bot 发消息到他人 inbox | 目标 bot 正确收到，其他 bot 不收 | Bot A 发消息到 Bot B inbox → Bot B 收、Bot C 不收 |
| ✅-3 | Bot 回复自动路由到发送者收件箱 | 无需指定 channel，server 自动回发给发送者 inbox | Bot B 回复 Bot A 的消息 → Bot A 的 inbox 收到回复 |
| ✅-4 | Bot 发送 `!agent_card list` 到 `_inbox:server` | Server 回复格式化卡片列表到该 bot 的 inbox | Test bot 发查询 → 自己 inbox 收回复 |
| ✅-5 | Bot 发送 `!pipeline_status R82` 到 `_inbox:server` | Server 回复管线状态到该 bot 的 inbox | 同上 |
| ✅-6 | 查询结果不广播到 admin | admin 频道无该查询/回复消息 | 观察 admin 频道，无干扰消息 |
| ✅-7 | 删除 MSG_SET_ACTIVE_CHANNEL | 协议中无此消息类型，handler 中无处理代码 | grep 零匹配 |
| ✅-8 | 删除 `_broadcast_active_channel()` | handler 中无此函数 | grep 零匹配 |
| ✅-9 | 删除 `persistence.get/set_agent_channel()` | persistence 中无此函数 | grep 零匹配 |
| ✅-10 | Bot 客户端无频道切换代码 | WsBridgeClient 无 `switch_channel`、`current_channel` 等方法 | 检查 clients/ 代码 |
| ✅-11 | 旧 bot 无需改 apikey/注册流程 | 兼容现有 bot，不破坏 auth | 现有 bot 连上后行为正常 |
| ✅-12 | Bot 发消息到 inbox 不经过 nonsense/duplicate 过滤 | inbox 消息直达，不误拦截 | 发多条相同 inbox 消息 → 全部送达，不丢 |

### 🎯 3.2 方向 B — 工作室时间切片

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-13 | `!create_workspace` 不创建频道，只打时间标记 | websocket 无 MSG_SET_ACTIVE_CHANNEL 广播，persistence 记录元数据 | 创建后检查 persistence 中有记录，无频道广播 |
| ✅-14 | 查看工作室 = 按时间区间筛选 inbox 消息 | `!workspace view ws:xxx` 返回该时间段内的所有 inbox 消息 | 在时间内发多条 inbox 消息 → view 正确显示 |
| ✅-15 | 工作室关闭 = 标记 closed_at | workspace 元数据 status=archived、closed_at 有值 | close 后检查元数据 |
| ✅-16 | `!pipeline_start` 不触发频道切换 | 只有 Step 任务以 inbox 消息派发 | 启动管线后检查 inbox 消息送达，无频道切换广播 |

### 🎯 3.3 方向 C — Admin 保留

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-17 | admin 频道管线进度通知正常 | admin 可以看到 Step 完成通知和进度消息 | `!step_complete` 后 admin 频道收到通知 |
| ✅-18 | bot 不接收 admin 消息 | bot 的 inbox 无任何 admin 频道的消息投递 | 检查 bot 连接的 recv 输出，无 admin 消息 |
| ✅-19 | Web 端 admin tab 正常 | admin 频道在 Web 端可正常查看 | 打开 Web → admin tab → 有消息渲染 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| **重构 bot Gateway 代码** | 本需求只改 server 端协议/路由 + 客户端库 | GW 配置层不受 inbox-only 影响 |
| **Web 端大幅改造** | Web 端看 admin 频道不变 | Web 端已有收件箱 Tab（R76），无需大改 |
| **删除 lobby 频道** | lobby 保留给真人，不删除 | 真人还需要大厅聊天 |
| **引入新协议/认证** | 沿用 R72 的 api_key 体系 | 认证层不动，只改路由层 |
| **R36-B 新虾注册流程** | 下轮再做 | 本轮回架构重构，不混入功能需求 |
| **统一 A2A 协议** | 调研阶段已完成，不在本轮实现 | 架构重构优先 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 20min |
| **3** | 👨‍💻 Dev | 编码实现 | 30min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 20min |
| **6** | 🛠️ Operations | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **大幅路由重写** — handle_broadcast 简化 + 删除 _broadcast_active_channel + 删除频道切换逻辑 + 新增 inbox 查询回复路由；简化 `!` 命令处理 | ~-200 行净删 |
| `shared/protocol.py` | **删除** MSG_SET_ACTIVE_CHANNEL、MSG_CHANNEL_UPDATED 等频道切换消息类型 | ~-10 行 |
| `server/workspace.py` | **重写** — 工作室从频道模型改为时间切片模型（元数据+时间区间+成员记录） | ~+100 行 |
| `server/persistence.py` | **删除** get/set_agent_channel；**新增** workspace 元数据持久化 | ~-10/+30 行 |
| `server/config.py` | **清理** 通道相关配置项 | ~-5 行 |
| `clients/python/ws_client.py` | **简化** — 删除 switch_channel、current_channel；只暴露 inbox 发收 | ~-50 行 |
| `clients/python/ws_client.py` | **新增** query() 方法 — 发查询到 `_inbox:server` 并等待回复 | ~+30 行 |
| **合计** | | **~-115 行净删** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| 🔴 **Bot 连接兼容** | 现有 bot（小开/爱泰/小周/泰虾/小爱）在新 server 上可能收不到老格式消息 | R72 clean break 模式 — 部署即新体系，bot 重新注册后拿到新 ws_client |
| 🔴 **Web 端查看工作室历史** | Web 端看工作室消息需要改为从 inbox 消息中按时间切片筛选 | R76 已实现 message_store 时间切片查询 |
| 🟡 **`!` 命令入口变化** | 现有 `!` 命令可能通过 admin 频道执行，改为通过 inbox:server 执行 | 统一命令路由：从 inbox:server 来的 `!` 命令等同于从 admin 来的 |
| 🟢 **Bot 不按 inbox 规则回复** | 旧 bot 可能继续往旧频道发消息 | 部署后旧 bot 发往 lobby/workspace 的消息 server 降级处理或返回提醒 |

---

## 6. 脱敏检查清单

- [ ] docs/R82/*.md 零内部名残留
- [ ] `grep -nE '内部名模式' docs/R82/*.md` 零匹配
- [ ] 使用通用角色名（PM / arch / dev / review / QA / operations / server）
- [ ] 不包含实际 agent_id / token / URL
