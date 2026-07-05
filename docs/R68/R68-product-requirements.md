# R68 产品需求 — Bot 私有收件箱通道 📥

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-05
> **本轮改动范围：** `shared/protocol.py`、`server/handler.py`、`server/persistence.py`（新增通道类型 + 收件箱路由）
> **参考：** TODO（新增项）、docs/ARCHITECTURE-REQUIREMENTS.md §3.2 工作室/频道系统、R67 Agent Card 系统

---

## 1. 问题背景

### 1.1 现状：工作室广播机制导致上下文污染，Bot 频繁丢活

ws-bridge 目前的**工作室（workspace）**采用广播路由：

| # | 投递方式 | 接收者 | 过滤条件 |
|:-:|:---------|:-------|:---------|
| ① | 成员在工作室内发消息 → **全量广播** | 所有在线成员 + admin | 只有 sender 不接收 |
| ② | Bot 通过 `mention_mode` 控制**是否回复** | 所有在线成员 | `@mention_keyword` 才回复 |
| ③ | Bot 的 LLM 上下文 = 整个工作室对话历史 | Bot 自己的上下文 | **无过滤** — 所有消息都进入上下文 |

结果是：

```
工作室内消息流（真实案例）:

@dev ✅ 配置确认
@QA ✅ 准备就绪
@arch 💬 这个方案我觉得可以
admin 💬 测试通过了
review 💬 好的收到
📋 PM @dev 🦐 R68 Step 3 — 编码实现到你了！   ← 任务消息被噪声淹没
admin 💬 稍等我看下
```

- Bot 的 LLM 上下文窗口被大量「确认」/「收到」/闲聊消息污染
- 真正到派活时，触发词被上下文噪声干扰，bot 意识不到自己被点名
- **根因正是需要频繁 TG 私聊激活 bot 的重要原因**

### 1.2 根因分析

| # | 根因 | 说明 |
|:-:|:-----|:------|
| 1 | **无上下文隔离** | 工作室是「一个大群」，所有消息全量广播，没有按 bot 隔离的会话通道 |
| 2 | **LLM 上下文无边界** | Bot 的上下文是整个工作室消息流，没有「仅任务相关」的干净输入 |
| 3 | **触发机制脆弱** | `mention_mode` 只控制「是否回复」，不控制「是否进入上下文」。bot 能看到所有消息 |
| 4 | **历史依赖** | 多个轮次积累的噪声让 bot 上下文越来越糟，需要人工（TG 私聊）重设上下文来「唤醒」 |

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:-----|:------|
| 🔴 **严重影响管线效率** | 每轮都有 bot 不响应，这是最频繁的卡点 |
| 🔴 **Agent Card 基础设施已就绪** | R67 统一了 Agent Card 存储格式，R68 收件箱可复用「每 agent 一份持久化数据」的模式 |
| 🟡 **改动可控** | 新的 `_inbox` 通道类型是现有频道系统的自然扩展，不破坏现有路由 |
| 🟢 **管线全自动闭环** | 收件箱模式解决后，管线可真正全自动流转，减少人工介入 |

---

## 2. 功能需求

### 设计原则

> **收件箱 = 单向邮件收件箱（PM → Bot），只读。**
> Agent Card = 公开名片（声明能力）；收件箱 = 暗线任务队列（派活）。
> Bot 读到任务后，回复/产出走 `_admin` 频道（现有基础设施），不往收件箱里回。

```
PM → 📥 _inbox:<bot_id>  → Bot 读取任务（只读）
Bot → 🛡️ _admin          → 回复 ACK / 报告产出（PM 统一可见）
```

---

### 方向 A（核心）：私有收件箱通道 `_inbox:<agent_id>` 🔴 P0

#### 概念

每个已注册的 agent 拥有一个**唯一的私有收件箱通道**，类似邮件收件箱：

| 属性 | 值 |
|:-----|:----|
| **通道 ID** | `_inbox:<agent_id>` |
| **可见性** | **仅** admin（发件人）+ 目标 agent（收件人） |
| **方向** | **→ 单向**（PM → Bot），Bot 只读 |
| **存储** | 有时间戳，有日志存查（写聊天日志 `write_chat_log`） |
| **生命周期** | Agent 注册/认证成功后自动创建，长期有效 |
| **Bot 回复** | 统一走 `_admin` 频道，不回写收件箱 |

**与现有通道类型对比：**

| 通道 | 可见性 | 通信方向 | 用途 |
|:-----|:-------|:---------|:-----|
| `lobby` 🏛️ | 全体在线 | 双向 | 日常公告、点名 |
| `_admin` 🛡️ | admin 专属 | 双向 | 管理命令、审计、Bot 回复 |
| `ws:XXX` 💼 | 工作室成员 | 双向 | 管线协作讨论 |
| `_inbox:<id>` 📥 | **agent + admin 仅 2 人** | **单向（PM→Bot）** | **任务派发** |
| `__registration__` 📋 | 未注册 bot | 双向 | 注册审批流程 |

#### A1 — 收件箱注册与持久化

**位置：** `shared/protocol.py` 新增前缀常量 + `server/persistence.py` 新增工具函数

当 agent 注册/认证成功后（`auth.py` 审批通过），自动创建收件箱通道记录：

```python
# shared/protocol.py
INBOX_CHANNEL_PREFIX = "_inbox:"

# server/persistence.py
def get_inbox_channel(agent_id: str) -> str:
    return f"{INBOX_CHANNEL_PREFIX}{agent_id}"

def is_inbox_channel(channel: str) -> bool:
    return channel.startswith(INBOX_CHANNEL_PREFIX)

def resolve_inbox_owner(channel: str) -> Optional[str]:
    if channel.startswith(INBOX_CHANNEL_PREFIX):
        return channel[len(INBOX_CHANNEL_PREFIX):]
    return None
```

**改造对比：**

| 当前 | 改造后 |
|:-----|:--------|
| agent 注册后只有 `_approved_users` 条目 | agent 注册后**自动创建收件箱通道记录** |
| 任务消息走工作室广播（噪声环境） | 任务消息走私有收件箱（干净环境） |
| 无 per-agent 私有通道概念 | 每 agent 一持久化私有通道，随时可查历史任务 |

#### A2 — 收件箱消息路由（单向，PM → Bot）

**位置：** `server/handler.py` 的 `handle_broadcast()` — 新增 `_inbox` 通道拦截

**关键设计：** 收件箱是**只读信箱**。只有 admin 可以**发消息**到收件箱（派活），agent 只能**收/读**。agent 不可向自己的收件箱发消息回复。

```python
# handler.py handle_broadcast() 中新增分支
if channel.startswith(INBOX_CHANNEL_PREFIX):
    owner_id = resolve_inbox_owner(channel)
    if not owner_id:
        await _send(ws, {"type": "error", "error": "❌ 无效的收件箱通道"})
        return

    # 权限：只有 admin 可发消息到收件箱
    if sender_role != "admin":
        await _send(ws, {"type": "error", "error": "❌ 权限不足：仅 admin 可向收件箱发消息"})
        return

    # 仅投递给目标 agent（单播，不广播给其他人）
    targets = [(aid, conns) for aid, conns in _connections.items() if aid == owner_id]
    # ... 消息持久化 write_chat_log(channel=inbox_ch) ...
    # ... 投递逻辑 ...
```

**路由规则矩阵：**

| 操作 ↓ \\ 角色 → | admin | 目标 agent 本人 | 其他 agent |
|:-----------------|:-----:|:---------------:|:----------:|
| 向 `_inbox:<id>` 发消息 | ✅ 派活 | ❌ | ❌ |
| 从 `_inbox:<id>` 收消息 | — | ✅ 读任务 | ❌ |
| 向 `_inbox` 回复 | ❌（回复走 `_admin`） | ❌（回复走 `_admin`） | ❌ |

**消息持久化：** 收件箱消息走 `write_chat_log(channel=inbox_channel)`，有时间戳，可追溯历史任务。

**Bot 侧读取：** Bot 连接 ws-bridge 后，收到 `MSG_SET_ACTIVE_CHANNEL = _inbox:<agent_id>` 即可开始接收收件箱消息。Bot 现有的 Hermes gateway 无需改造 — 收件箱消息对 bot 而言就是一个新的 channel 的消息。

#### A3 — 管线派活走收件箱 + 工作室轻量通知

**位置：** `server/handler.py` — `_cmd_step_complete()` / `_cmd_step_handoff()` 中的 Step 交接定点逻辑

当前流程（纯广播）：

```
Step N → !step_complete → 广播点名到工作室 → 所有 bot 收到噪声消息
                          → 目标 bot 从噪声中解析任务
                          → 上下文已污染 → 可能不触发
```

改造后流程（收件箱 + 工作室通知 + Admin 回复）：

```
Step N → !step_complete
  ├─ 📥 向 _inbox:<next_bot> → 完整任务消息（安静投递，干净上下文）
  └─ 🏠 向 workspace        → @bot_name 🔔 Step N 已派活，请查收收件箱
      └─ Bot 读取收件箱 → 回复到 _admin → ✅ ACK（或开始干活）
```

**改造前后对比：**

| 维度 | 当前（广播） | 改造后（收件箱） |
|:-----|:------------|:-----------------|
| 工作室消息量 | 全员收到每一条消息 | 工作室仅**轻量进展通知** |
| Bot 上下文 | 全量历史含噪声 | **仅收件箱消息**，干净可控 |
| 任务触发 | 依赖 @mention 从噪声中识别 | 收件箱就是任务队列 |
| Bot 回复路径 | 回复到工作室（又被广播） | 回复到 `_admin`（不打扰工作室） |
| 任务历史追溯 | 混在工作室历史中 | 收件箱独立日志 |
| TG 激活频率 | **高** — 经常需要 | **低** — 收件箱可靠 |

**收件箱消息内容模板（关键）：**

```
📥 任务分配 — R{ N } Step { step }

背景上下文：
{ 前序 Step 的产出摘要 / 上下文注入 }

任务描述：
{ 按 WORK_PLAN 对应 Step 的任务描述 }

参考文档：
📄 需求：{ url }
📋 WORK_PLAN：{ url }
🏗️ 技术方案：{ url }
🔗 上一步产出：{ sha }

验收要求：
{ 从 WORK_PLAN 复制对应 Step 的验收清单 }

完成后：
1. git push dev
2. 在 _admin 频道回复 ✅ Step 完成 + commit SHA
```

#### A4 — Bot 收信后的 ACK 回复到 _admin（可选增强）

Bot 收到收件箱消息后，可选择向 `_admin` 频道发送 ACK 确认，让 PM 和管理员一目了然：

```
📥 PM → _inbox:<bot_id>: 完整任务消息...
     Bot 读取收件箱
     Bot → _admin: ✅ [R68] 已收到 Step 3 任务，开始执行
```

超时未 ACK（30s）→ `_admin` 自动告警：`⚠️ <bot_name> 未确认收件箱任务`

**为什么要回 `_admin` 而非收件箱或工作室？**

| 路径 | 问题 |
|:-----|:------|
| 回复到工作室 ❌ | 工作室又变回噪声环境 |
| 回复到收件箱 ❌ | 收件箱只读，且收件箱是 1:1 通道 |
| 回复到 `_admin` ✅ | PM/admin 统一监控，不打扰工作室 |

---

### 方向 B（兼容）：收件箱 API 与 Web 端管理视图 🟡 P1

- Web 端 admin 查看所有 agent 的收件箱消息（按时间倒序，类邮件列表）
- admin 可通过 Web 端直接向指定 bot 收件箱发送消息（手动派活兜底）
- 侧边栏 bot 列表展示「📥 N」未读收件箱消息数（可选）

---

## 3. 验收标准

### 🎯 3.1 方向 A（核心）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | `_inbox:<agent_id>` 通道格式定义 | 前缀常量 `INBOX_CHANNEL_PREFIX` 在 `protocol.py` 中定义 | grep 检查常量定义 |
| ✅-2 | Agent 注册后自动创建收件箱 | 新 agent 审批通过后，`get_inbox_channel(agent_id)` 返回合法 ID | 注册新 agent → 检查收件箱通道 |
| ✅-3 | 收件箱消息仅投递给目标 agent | 发到 `_inbox:<agent_id>` 的消息仅该 agent 收到 | 模拟 2 个在线 agent → 向 A 收件箱发消息 → B 不收到 |
| ✅-4 | 权限：仅 admin 可向收件箱发消息 | member 角色向任何 `_inbox` 发消息 → 被拒绝 ❌ | member → 收件箱 → error |
| ✅-5 | admin 可向任何 agent 收件箱发消息 | admin 向 `_inbox:<agent_id>` 发消息 → 成功投递 | admin → 任意收件箱 → ✅ |
| ✅-6 | `handle_broadcast` 新增收件箱路由 | `_inbox` 前缀拦截在 `_admin` / `registration` 通道拦截之后 | grep handler.py 含收件箱路由 |
| ✅-7 | 收件箱消息持久化到聊天日志 | `write_chat_log(channel=inbox_ch)` 写入日志文件 | 发消息 → 检查 chat_logs/ |
| ✅-8 | 收件箱消息有时间戳 | 消息记录含 `ts` 字段 | 检查消息 JSON 格式 |
| ✅-9 | Agent 不能向收件箱回复写 | agent 向 `_inbox:<self>` 发消息 → 被拒绝 | agent → 自己收件箱 → error ❌ |

### 🎯 3.2 方向 B（辅助）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-10 | `!step_complete` 后任务消息发到收件箱 | Step 完成后，下一 bot 的收件箱收到完整任务消息 | 启动管线 → Step 交接 → 检查收件箱 |
| ✅-11 | 工作室同时收到轻量进展通知 | 工作室出现 `@bot_name 🔔 Step N 已分配` | 验证工作室消息 |
| ✅-12 | Bot 收信后向 `_admin` 回复 ACK | bot 读取收件箱后 → `_admin` 出现 `✅ [R{N}] 已收到任务` | 模拟 bot 写 `_admin` |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| Bot 端收件箱客户端改造 | 收件箱是服务端路由能力，bot 端通过现有 `MSG_SET_ACTIVE_CHANNEL` 接收消息 | 服务端先建路由，bot 自行适配 |
| 收件箱消息过期/TTL | 保留同现有工作室策略 | 简化实现 |
| Bot 上下文管理逻辑 | 不定义 bot 如何刷新上下文窗口 | bot 端自行实现 |
| 收件箱加密 | 不新增消息加密 | 超出 scope |
| Hermes `send_message` 适配 `_inbox` | 当前 PM 通过 WebSocket 直连发送到收件箱 | 后续轮次适配 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 15min |
| **3** | 👨‍💻 Dev | 编码实现 | 20min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 15min |
| **6** | 🛠️ Admin | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `shared/protocol.py` | **新增** `INBOX_CHANNEL_PREFIX` 常量 | ~2 行 |
| `server/persistence.py` | **新增** 3 个工具函数（get/is/resolve） | ~15 行 |
| `server/handler.py` | **修改** handle_broadcast 新增收件箱路由分支；pipenline handoff 改收件箱派活 | ~60 行 |
| `server/auth.py` | **修改** agent 审批通过后自动注册收件箱 | ~5 行 |
| **合计** | | **~82 行净增** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| Bot 当前不监听 `_inbox` 频道 | Bot 收不到收件箱消息 | 服务端按现有 `MSG_SET_ACTIVE_CHANNEL` 机制投递，bot 收到 channel 消息自动处理。Hermes gateway 已有通用 channel 支持 |
| 现有 bot 被配置为回复到工作室而非 `_admin` | Bot 回复仍发到工作室 | 本轮不强制改 bot 回复路径，只建收件箱路由。方向 A 只做「收件箱可收到任务消息」，bot 端下轮适配 |
| `_inbox` 通道被大量任务消息填满 | 收件箱消息过多 | 消息持久化同现有策略，bot 只需读最新 N 条 |

---

## 6. 脱敏检查清单

- [ ] docs/R68/*.md 零内部名残留
- [ ] `grep -nE 'bot名|内部名|真实ID' docs/R68/*.md` 零匹配
- [ ] handler.py 代码零内部 URL/端口泄露
- [ ] 使用角色名/通用名（admin/PM/dev/arch/review/QA）替代具体 bot 名
