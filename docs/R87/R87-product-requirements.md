# R87 产品需求 — `_inbox:server` 中继架构 🚉

> **版本：** v1.1（初稿，待审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-09
> **前置条件：** R86 认证加固已部署 ✅ | Inbox 消息协议已文档化（§8 四步流程）✅

---

## 1. 问题背景

### 1.1 现状

当前 inbox 通信模式（R84 定型，§8 协议）是**点对点直连**：

```
PM ──→ Bot  (_inbox:<bot_id>)    派活
Bot ──→ PM  (_inbox:<PM_id>)     ACK ✅
Bot ──→ PM  (_inbox:<PM_id>)     ✅ 完成
PM  ──→ Bot  (_inbox:<bot_id>)    确认
```

**暴露的问题：**

| # | 问题 | 影响 |
|:-:|:-----|:------|
| 🔴 | **每个 bot 必须知道 PM 的 agent_id** — 派活消息中要嵌入 `SENDER_INBOX` 字段，bot 提取后才能回复 | 加新 bot 要同步通知 PM_id，配置耦合 |
| 🟡 | **PM 收所有 bot 消息** — 包括啰嗦的思考过程、不必要的中间状态 | 消息污染，PM 被信息淹没 |
| 🟡 | **PM 需手动回复 Step 4 确认** — 多 bot 同时干活时，PM 要逐一回复确认 | 操作负担，也是人为延迟环节 |
| 🟢 | **通信层 ACK 与业务层 ACK 混在一起** — 服务端 `send_message` 的回执与 bot 回复的 `ACK ✅` 是两个概念 | 无法利用传输层回执做可靠性保障 |

### 1.2 R86 管线暴露的痛点

R86 测试中 PM 需要：
- 逐一向 5 个 bot 派活
- 逐一确认每个 bot 的完成回复
- 手动分辨哪些是 ACK、哪些是完成、哪些是啰嗦消息

**一次 6 步管线，PM 要处理约 20+ 条消息。** 随着 bot 数量增加，不可扩展。

### 1.3 目标

> **R87 目标：引入 `_inbox:server` 中继通道，让 bot 的回复统一走 server 转发，PM 仅需派活 1 条消息，server 自动筛选关键消息 + 自动确认。**

---

## 2. 方案设计

### 2.1 核心架构

**通道职责严格分离：**

| 通道 | 用途 | 发送方 | 接收方 |
|:-----|:------|:-------|:-------|
| `_inbox:<bot_id>` | 任务派发 + 自动确认 | PM、Server | **Bot** |
| `_inbox:<PM_id>` | 进度/结果转发通知 | Server | **PM** |
| `_inbox:server` | **Bot 回复中继，仅用于此** | **仅限 Bot** | **Server 内部处理** |

⚠️ **重要规则：`_inbox:server` 只接受 bot 发来的消息。PM 和 server 都不应往这个通道发消息。** 这从根本上消除了路由歧义——server 收到 `_inbox:server` 消息时，发送方一定是 bot，不可能来自 PM。

```
PM                                Server                              Bot
│                                  │                                  │
│① 派活 ────────────────────────────────→ _inbox:<bot_id> ──────────→│
│   PM直接发bot收件箱，不走server        │                              │
│                                  │                                  │
│                                  │←── ② ACK ✅ R{轮次} 收到！─────┤
│                                  │     (_inbox:server)              │
│←── ③ 转发 ACK（进度通知）──────────┤                                  │
│                                  │                                  │
│                                  │         [bot 干活中...]         │
│                                  │                                  │
│                                  │←── ④ ✅ 完成，已推 dev: xxx ───┤
│                                  │     (_inbox:server) ← 唯一触发点 │
│←── ⑤ 转发 完成 ──────────────────┤                                  │
│         (通知PM)                  │── ⑥ 自动确认 ──────────────────→│
│                                  │    (回复bot，_inbox:<bot_id>)     │
│                                  │ ⑤+⑥ 同时触发，无先后顺序        │
```

### 2.2 PM 视角

| 步骤 | 动作 | 说明 |
|:----|:------|:-----|
| ① 派活 | **发到 `_inbox:<bot_id>`** | 跟现在一样，直接发到目标 bot 的收件箱 |
| ③ 收 ACK 通知 | **收到 server 转发** | 知道 bot 已接活，看看就行 |
| ④ → ⑤+⑥ | **bot 发 ✅ 完成** | 同时触发两条消息 |
| ⑤ 收完成通知 | **server → PM** | 看结果，闭环 |
| ⑥ 自动确认 | **server → bot** | server 自动完成，PM 不用管 |

**PM 全程只需做 1 件事：派活。** 和现在操作方式一样，只是收件箱更干净了。

### 2.3 Bot 视角

| 步骤 | 动作 | 说明 |
|:----|:------|:-----|
| ① 收活 | 从 `_inbox:<bot_id>` 收到 | **和现在一样** |
| ② ACK ✅ | **回复到 `_inbox:server`** | 核心变化：不再是 PM 的 inbox |
| ④ 完成 | **回复到 `_inbox:server`** | 核心变化：不再是 PM 的 inbox |
| ⑥ 收自动确认 | 从 `_inbox:<bot_id>` 收到 | 与 ⑤ 同时被 ④ 触发，**不回复** |

**Bot 唯一要改的：回复目标从 `_inbox:<PM_id>` 改为 `_inbox:server`。**

### 2.4 Server 视角

Server 新增以下职责：

#### 2.4.1 特殊通道识别

`_inbox:server` 是一个**特殊保留通道**，不绑定任何 agent。**仅接受 bot 发来的消息**（即 `agent_id` 不为空的已认证连接）。

```
收到消息 → channel == "_inbox:server"?
  ├── 是 → 进入中继路由逻辑
  └── 否 → 正常 inbox 路由（现有逻辑不变）
```

**安全守卫：如果 PM 也发了 `_inbox:server`（误操作），server 仍正常转发？**
→ 放在 §3.1.2 实现细节中：检查发送者角色，非 bot 直接拒绝。

#### 2.4.2 前缀匹配转发规则

| 前缀 | 含义 | Server 行为 | 转发到 |
|:-----|:-----|:------------|:-------|
| `ACK ✅` | Step 2 确认 | **转发给 PM**，作为进度通知 | `_inbox:<PM_id>` |
| `✅ 完成` | Step 3 完成 | **同时触发两条消息**：⑤ 转发PM + ⑥ 自动确认bot | PM + `_inbox:<bot_id>` |
| 其他内容 | 非关键消息 | **沉默处理**，不转发、不回复 | — |

**匹配策略：**
- `str.startswith("ACK ✅")` — 检测 ACK，匹配后 `return`，不继续匹配下一条规则
- `str.startswith("✅ 完成")` — 检测完成，匹配后触发转发 + 自动确认
- 两条规则互斥——一条消息只触发一条

**关于 `✅ 完成` 的转发方向：**
- 转发给 PM → 使用 `_inbox:<PM_id>`（PM 的收件箱）
- 自动确认给 bot → 使用 `_inbox:<bot_id>`（bot 的收件箱）
- **两者都不走 `_inbox:server`**，避免潜在路由歧义

#### 2.4.3 Step 4 自动确认

当 server 收到 `✅ 完成` 前缀的消息后（唯一触发点）：

```
收到 bot 的 ✅ 完成 → _inbox:server  ← 唯一触发
  │
  ├── ⑤ 转发给 PM（同步）
  │     send_message(content=f"✅ {bot_name} 任务完成:\n{原始内容}",
  │                  channel="_inbox:<PM_id>")
  │
  └── ⑥ 自动确认给 bot（同步）
        send_message(content="✅ 确认，已收到你的完成通知。本轮任务完成。",
                     channel="_inbox:<bot_id>")
        # ⑤ 与 ⑥ 无先后顺序，同时发出
```

**确认消息的语言可配置**（通过 server 配置项 `server_relay.completion_ack_template`）。

#### 2.4.4 路由安全守卫（防误操作）

以下是针对可能的路由混淆场景的安全设计：

| # | 场景 | 风险 | 防护措施 |
|:-:|:-----|:-----|:---------|
| ❶ | PM 误发消息到 `_inbox:server` | Server 可能转发给 PM 自己，形成空转 | 检查发送者身份：`_handle_server_relay` 入口处验证 `sender_id` 是否属于已注册 bot，非 bot 消息直接拒绝+返回错误 |
| ❷ | Bot 回复 Step 4 自动确认（无意义循环） | Bot 收到确认后又一言不发回 `_inbox:server` | 回复内容大概率不匹配 ACK ✅ / ✅ 完成，会被沉默处理 |
| ❸ | Bot 用 `ACK ✅ 确认收到` 回复 Step 4 | 触发 ACK 转发规则，污染 PM | 概率极低——Step 4 确认不需要 bot 回复，且 bot 协议明确「不用回复」 |
| ❹ | Bot 意外断连重连后，`_inbox:server` 消息被重放 | 重复转发/重复确认 | B1 检查 + 消息去重（现有 `seen_ids` 机制覆盖） |

### 2.5 关键优势对比

| 维度 | 当前点对点模式 | `_inbox:server` 中继模式 |
|:-----|:---------------|:------------------------|
| 🎯 回复地址 | 每个 bot 要查 PM 的 agent_id | 所有 bot 统一 `_inbox:server` |
| 🧹 消息筛选 | PM 收所有 bot 消息 | server 只转关键消息，其余沉默 |
| 🔢 PM 消息负担 | 派活 + 确认 N 条（N 个 bot） | 派活 1 条 + 收到 N 条转发通知 |
| 🔧 扩展性 | 加新 bot 要同步 PM_id | 零配置，统一协议 |
| 📬 传输层 ACK | bot 直发 PM，无传输回执 | server 收消息即有回执 |
| 🤖 啰嗦容忍度 | 低（PM 全收） | 高（server 过滤） |
| 🛡️ **路由安全** | PM 直发 bot inbox，天然清晰 | **`_inbox:server` 严格限 bot 使用，PM/Server 均不走** |

---

## 3. 实现方案

### 3.1 Server 端改动

#### 3.1.1 新增 `_inbox:server` 常量和判断

```python
# 在 handler.py 或 config.py 中
SERVER_INBOX_CHANNEL = "_inbox:server"

def is_server_inbox(channel: str) -> bool:
    """判断是否为 server 中继通道"""
    return channel == SERVER_INBOX_CHANNEL
```

#### 3.1.2 中继路由逻辑（新增函数）

```python
# PM 的 agent_id，用于转发通知
PM_AGENT_ID = config.PM_AGENT_ID  # 从配置中读取 PM 身份

async def _handle_server_relay(ws, agent_id: str, msg: dict):
    """处理发往 _inbox:server 的消息（仅接受 bot 发来的消息）"""
    channel = msg.get("channel", "")
    content = msg.get("content", "").strip()
    sender_id = agent_id       # 发送此消息的 bot 的 agent_id
    sender_name = msg.get("from_name", "?")

    if not is_server_inbox(channel):
        return False

    # 安全守卫：检查发送者是否为已注册 bot
    # 如果发送者是 PM 或未注册连接，直接拒绝
    if sender_id == PM_AGENT_ID:
        await _send(ws, {
            "type": "error",
            "error": "_inbox:server 仅接受 bot 消息，PM 请直接发 bot 收件箱。",
        })
        logger.warning(f"[Relay] 拒绝: PM 试图发消息到 _inbox:server")
        return True

    # 规则 1: Step 2 ACK → 转发 PM（进度通知）
    if content.startswith("ACK ✅"):
        await _send_to_agent(
            target_id=PM_AGENT_ID,
            content=f"📬 {sender_name} 已接活:\n{content}",
            from_name="系统(中继)",
        )
        logger.info(f"[Relay] ACK: {sender_name} → PM")
        return True

    # 规则 2: Step 3 完成 → 转发 PM + 自动确认 bot
    if content.startswith("✅ 完成"):
        # 转发给 PM
        await _send_to_agent(
            target_id=PM_AGENT_ID,
            content=f"✅ {sender_name} 任务完成:\n{content}",
            from_name="系统(中继)",
        )
        # 自动回复确认给 bot（发到 bot 的 inbox，不走 _inbox:server）
        await _send_to_agent(
            target_id=sender_id,
            content="✅ 确认，已收到你的完成通知。本轮任务完成。",
            from_name="系统(中继)",
        )
        logger.info(f"[Relay] 完成: {sender_name} → PM + 自动确认 → {sender_name}")
        return True

    # 规则 3: 其他内容 → 沉默
    logger.info(f"[Relay] 沉默: {sender_name} → {content[:50]}...")
    return True
```

#### 3.1.3 集成到消息入口

```python
# handler() / ws_handler() 中
if msg_type == "message" and agent_id:
    # ... 现有 key 验证 ...
    
    # 新增：_inbox:server 中继检查（在 handle_broadcast 之前拦截）
    if is_server_inbox(msg.get("channel", "")):
        await _handle_server_relay(ws, agent_id, msg)
        continue  # 已由中继处理，不走后续路由
    
    await handle_broadcast(ws, agent_id, msg)
```

**为什么放在 `handle_broadcast` 之前？**
- 放在最前面可以确保 `_inbox:server` 消息被 100% 拦截，不会漏到普通路由
- `handle_broadcast` 对 `_inbox:` 前缀有特殊处理（R82 inbox fast path），提前拦截避免影响现有逻辑

### 3.2 Bot 端改动

#### 3.2.1 回复地址变更

```python
# 当前代码（回复到 PM 的 inbox）：
sender_id = msg.get("agent_id") or msg.get("from_agent") or ""
await client.send_message(
    content="ACK ✅ R87 收到！",
    channel=f"_inbox:{sender_id}",
)

# 改为（回复到 server）：
await client.send_message(
    content="ACK ✅ R87 收到！",
    channel="_inbox:server",        # ← 统一回复到这里
)
```

#### 3.2.2 格式要求

| 消息 | 回复内容 | 必须前缀 |
|:-----|:---------|:---------|
| Step 2 ACK | `ACK ✅ R{轮次} 收到！` | 必须以 `ACK ✅` 开头 |
| Step 3 完成 | `✅ 完成，已推 dev: abc1234` | 必须以 `✅ 完成` 开头 |

**注意：** 前缀必须完全匹配。`ACK✅`（无空格）不会触发转发。

#### 3.2.3 Bot 收到自动确认后

Bot 仍然会收到 Step 4 确认（由 server 发出到 `_inbox:<bot_id>`），和当前协议一致——**不用回复**。

### 3.3 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **新增** — `_handle_server_relay()` 中继函数 + `_inbox:server` 判断 + 消息入口集成（含安全守卫） | ~50 行 |
| `server/__main__.py` | **修改** — ws_handler() 消息入口加中继路由 | ~10 行 |
| `server/config.py` | **新增** — `SERVER_INBOX_CHANNEL` 常量 + `PM_AGENT_ID` 配置 + `completion_ack_template` | ~5 行 |
| `clients/ws_client.py` | **可选新增** — `send_to_server()` 辅助方法 | ~5 行 |
| **合计** | | **~70 行净增** |

---

## 4. 验收标准

### 🎯 4.1 核心功能

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | Bot 发 `ACK ✅` 到 `_inbox:server`，PM 收到转发 | PM 收到 `"📬 Bot名 已接活: ACK ✅ ..."` | bot 发 ACK → 检查 PM 收件箱 |
| ✅-2 | Bot 发 `✅ 完成` 到 `_inbox:server`，PM 收到转发 | PM 收到 `"✅ Bot名 任务完成: ✅ 完成..."` | bot 发完成 → 检查 PM 收件箱 |
| ✅-3 | Bot 发 `✅ 完成` 后，server 自动回复确认到 bot inbox | bot 收到 `"✅ 确认，已收到你的完成通知"`（发到 `_inbox:<bot_id>`） | 检查 bot 收件箱 |
| ✅-4 | Bot 发非关键内容（如 `"正在思考..."`）→ 沉默 | PM 不收到此消息，bot 也不收回复 | bot 发杂音 → 检查 PM 收件箱无此消息 |
| ✅-5 | 非 `_inbox:server` 的消息不受影响 | 普通 inbox 消息正常路由（向后兼容） | 正常发消息 → 检查现有路由不变 |

### 🎯 4.2 路由安全

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-6 | PM 误发消息到 `_inbox:server` | Server 拒绝，返回 error `"_inbox:server 仅接受 bot 消息"` | PM 发 `_inbox:server` → 看响应 |
| ✅-7 | Step 4 确认发到 `_inbox:<bot_id>`（不走 `_inbox:server`） | 检查 server 发确认时 channel 为 `_inbox:<bot_id>` | 日志 grep channel 确认 |
| ✅-8 | `ACK✅`（无空格）→ 不触发转发 | PM 不收到 ACK 通知 | 发送测试 |
| ✅-9 | `✅完成`（无空格）→ 不触发完成转发 | PM 不收到完成通知 | 发送测试 |
| ✅-10 | 多个 bot 同时发消息到 `_inbox:server` | 各自独立转发，互不影响 | 同时发 10 条 |
| ✅-11 | Bot 未注册就发到 `_inbox:server` | 按现有 key 验证逻辑拒绝（不会进入中继） | 未 auth 的连接发消息 |
| ✅-12 | Step 4 确认后 bot 再回复 → 走正常中继路径 | bot 回复到 `_inbox:server`，按前缀匹配处理（大概率沉默） | bot 回 Step 4 确认的消息 |

### 🎯 4.3 文档更新

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-13 | inbox-message-protocol.md §8 更新 | 全流程改为 `_inbox:server` 中继模型，附通道职责表、前缀规则、Bot Checklist 更新 |
| ✅-14 | TODO.md Phase 2 更新 | 已同步本次架构设计 |

---

## 5. 不纳入范围

| 事项 | 原因 |
|:-----|:------|
| **PM 也走 `_inbox:server` 派活** | R87 不做。当前 PM 直接发 bot inbox 足够清晰。以后如需统一入口再说 |
| **Step 4 消息内容可配置** | 初版用固定模板即可，后续加配置项 |
| **`_inbox:server` 消息持久化** | 中继消息不需要单独持久化——转发给 PM 的消息自然存到 PM 的 inbox 记录中 |
| **前缀匹配的国际化** | 当前只支持中文 `ACK ✅` / `✅ 完成`，后续可按需扩展 |
| **Bot 端自动适配** | Bot 需要手动改回复地址——这不是服务端能自动完成的 |
| **历史兼容** | 旧 bot 继续使用 `_inbox:<PM_id>` 回复也可工作（只要 PM 的 inbox 能收到）— 但不享受筛选和自动确认的好处 |

---

## 6. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 5min |
| **2** | 👷 Arch | 技术方案（含伪代码、入口修改点、路由安全分析） | 10min |
| **3** | 👨‍💻 Dev | 编码实现（~70 行净增） | 15min |
| **4** | 👀 Review | 代码审查（重点关注路由安全守卫） | 10min |
| **5** | 🦐 QA | 测试报告（14 项验收） | 10min |
| **6** | 🛠️ Operations | 合并部署 + 更新 inbox-message-protocol.md | 10min |

### 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| **① Step 1 派活路由** | PM 发到 `_inbox:server` 会被拒 | PM 直接发 `_inbox:<bot_id>`，和现在一样——无需担心 |
| **② Step ⑤+⑥ 同时触发** | 误解为先 ⑤ 后 ⑥ | 源码中两个 `_send_to_agent` 是顺序 await，但语义上是同时触发——无先后依赖关系 |
| **③ Step 6 确认路由** | 自动确认走错通道导致循环 | 确认发到 `_inbox:<bot_id>` 不走 `_inbox:server`，且 bot 协议要求不回复确认 |
| 部署后 bot 未更新回复地址 | PM 收不到 ACK/完成通知 | 旧 bot 仍可用 `_inbox:<PM_id>` 回复，新模式下不强制立即迁移 |
| `_inbox:server` 被非预期 bot 滥用 | 杂音污染 | 现有 key 验证机制已经拦截未注册 bot + 安全守卫 PM 检查 |
| ACK 前缀误匹配（bot 写了 `ACK ✅ 已完成` 同时触发两条） | 一条消息同时匹配 ACK 和完成 | 先匹配 ACK，匹配后 `return` 不继续——一条消息只触发一条规则 |
| 自动确认发到错误 bot | bot 收到别人的确认 | 自动确认使用 `sender_id`（发送原始完成消息的 bot），不会串 |

---

## 7. 部署后文档更新

### 7.1 更新 `inbox-message-protocol.md`

实现并部署后，必须更新 §8 全流程通信步骤：

- 替换通信全景 ASCII 图（PM 直接派活 + bot 回复 `_inbox:server`）
- 新增通道职责表（说明 `_inbox:server` / `_inbox:<bot_id>` / `_inbox:<PM_id>` 的区别）
- 更新 Step 2/Step 3 回复目标（`_inbox:server`）
- 新增 `_inbox:server` 说明小节（仅 bot 使用，PM/Server 均不走）
- 更新 Bot Checklist（回复地址检查项）
- 移除 SENDER_INBOX 字段概念

### 7.2 更新 Bot 端文档

各 bot 的 Gateway 配置说明中：

- 回复目标改为 `_inbox:server`
- 强调前缀格式要求（`ACK ✅` / `✅ 完成`）
- 说明「非关键消息被沉默」的行为
- 强调「收到 Step 4 自动确认后不要回复」

---

## 8. 脱敏检查清单

- [ ] docs/R87/*.md 零内部名残留（frontmatter 除外）
- [ ] 使用通用角色名（PM / arch / dev / review / QA / operations）
- [ ] 不包含真实 agent_id / token / URL
