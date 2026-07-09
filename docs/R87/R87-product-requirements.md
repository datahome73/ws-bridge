# R87 产品需求 — `_inbox:server` 中继架构 🚉

> **版本：** v1.0（初稿，待审核）
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

R86 测试中 PM（小谷）需要：
- 逐一向 5 个 bot 派活
- 逐一确认每个 bot 的完成回复
- 手动分辨哪些是 ACK、哪些是完成、哪些是啰嗦消息

**一次 6 步管线，PM 要处理约 20+ 条消息。** 随着 bot 数量增加，不可扩展。

### 1.3 目标

> **R87 目标：引入 `_inbox:server` 中继架构，将 inbox 通信从「点对点」升级为「hub-and-spoke」，PM 全程只需做 1 件事——派活。**

---

## 2. 方案设计

### 2.1 核心架构

```
PM                                Server                              Bot
│                                  │                                  │
│① 派活 ─────────────────────────→│────────→ _inbox:<bot_id> ──────→│
│   (PM 唯一的上行消息)             │                                  │
│                                  │② ACK ✅ R{轮次} 收到！──────────→│
│←──③ 转发 ACK（进度可知）─────────┤  (_inbox:server)                  │
│                                  │                                  │
│                                  │         [bot 干活中...]         │
│                                  │                                  │
│                                  │④ ✅ 完成，已推 dev: xxx ────────→│
│←──⑤ 转发 完成（最终结果）─────────┤  (_inbox:server)                  │
│                                  │                                  │
│                                  │⑥ ✅ 确认 → _inbox:<bot_id> ────→│
│                                  │  (server 自动发，PM 无需操心)     │
```

### 2.2 PM 视角

| 步骤 | 方向 | 内容 | PM 做什么？ |
|:----|:-----|:-----|:-----------|
| ① 派活 | → server | 任务描述 | **唯一需要做的事情** |
| ③ ACK 通知 | ← server | `"ACK ✅ R87 收到！"` | 看看，知道 bot 已接活 |
| ⑤ 完成通知 | ← server | `"✅ 完成，已推 dev: xxx"` | 看结果，闭环 |
| ⑥ 自动确认 | server→bot | 自动确认 | **不需要做任何事** |

**PM 全程只需发 1 条消息。** 收到 ACK 知道进度，收到完成看结果，确认由 server 自动完成。

### 2.3 Bot 视角

| 步骤 | 方向 | 内容 | Bot 做什么？ |
|:----|:-----|:-----|:------------|
| ① 收活 | ← server | 任务描述 | 收到任务，开始处理 |
| ② ACK ✅ | → `_inbox:server` | `"ACK ✅ R87 收到！"` | **5 秒内回复 ACK** |
| ④ 完成 | → `_inbox:server` | `"✅ 完成，已推 dev: xxx"` | 干完活后回复完成 |
| ⑥ 自动确认 | ← server | `"✅ 确认，已收到你的完成通知"` | **不用回复，直接结束** |

**Bot 核心变化：回复目标从 `_inbox:<PM_id>` 改为 `_inbox:server`**。其他逻辑不变。

### 2.4 Server 视角

Server 新增以下职责：

#### 2.4.1 特殊通道识别

`_inbox:server` 是一个**特殊保留通道**，不绑定任何 agent。任何 bot 发往此通道的消息都由 server 内部处理。

```
收到消息 → channel == "_inbox:server"?
  ├── 是 → 进入中继路由逻辑
  └── 否 → 正常 inbox 路由（现有逻辑不变）
```

#### 2.4.2 前缀匹配转发规则

| 前缀 | 含义 | Server 行为 |
|:-----|:-----|:------------|
| `ACK ✅` | Step 2 确认 | **转发给发送者**（PM），仅通知进度 |
| `✅ 完成` | Step 3 完成 | **转发给发送者**（PM）+ **自动回复确认**（Step 4）给 bot |
| 其他内容 | 非关键消息 | **沉默处理**，不转发、不回复 |

**匹配策略：**
- `str.startswith("ACK ✅")` — 检测 ACK
- `str.startswith("✅ 完成")` — 检测完成
- 如果 bot 用其他变体（如 `"ACK ✅ 测试通过"`），仍按 `startswith("ACK ✅")` 匹配

#### 2.4.3 Step 4 自动确认

当 server 收到 `✅ 完成` 前缀的消息后：

```
收到 bot 的 ✅ 完成 → _inbox:server
  │
  ├── ① 转发该消息给原始发送者（PM）
  │
  └── ② 自动发确认给 bot：
       send_message(
           content="✅ 确认，已收到你的完成通知。本轮任务完成。",
           channel="_inbox:<bot_id>"
       ）
```

**确认消息的语言可配置**（通过 server 配置项 `server_relay.completion_ack_template`）。

### 2.5 关键优势对比

| 维度 | 当前点对点模式 | `_inbox:server` 中继模式 |
|:-----|:---------------|:------------------------|
| 🎯 回复地址 | 每个 bot 要查 PM 的 agent_id | 所有 bot 统一 `_inbox:server` |
| 🧹 消息筛选 | PM 收所有 bot 消息 | server 只转关键消息，其余沉默 |
| 🔢 PM 消息量 | 派活 + N 个确认（N 个 bot） | 派活 1 条，N 条转发通知 |
| 🔧 扩展性 | 加新 bot 要同步 PM_id | 零配置，统一协议 |
| 📬 传输层 ACK | bot 直发 PM，无传输回执 | server 收消息即有回执 |
| 🤖 啰嗦容忍度 | 低（PM 全收） | 高（server 过滤） |

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

#### 3.1.2 中继路由逻辑（`handle_broadcast` 或新增函数）

```python
async def _handle_server_relay(ws, agent_id: str, msg: dict):
    """处理发往 _inbox:server 的消息"""
    channel = msg.get("channel", "")
    content = msg.get("content", "").strip()
    sender_id = agent_id       # 发送此消息的 bot 的 agent_id
    sender_name = msg.get("from_name", "?")
    original_channel = msg.get("_original_channel")  # 可选：原始派活来源跟踪

    if not channel.startswith("_inbox:server"):
        return False  # 不是中继消息

    TASK_ORIGINATOR = _get_task_originator(sender_id)
    """根据上下文查找此消息应该转发给谁（PM）"""

    # 规则 1: Step 2 ACK
    if content.startswith("ACK ✅"):
        await _send_to_agent(
            target_id=TASK_ORIGINATOR,
            content=f"📬 {sender_name} 已接活:\n{content}",
            from_name="系统(中继)",
            msg_type="relay_ack",
        )
        return True

    # 规则 2: Step 3 完成
    if content.startswith("✅ 完成"):
        # 转发给 PM
        await _send_to_agent(
            target_id=TASK_ORIGINATOR,
            content=f"✅ {sender_name} 任务完成:\n{content}",
            from_name="系统(中继)",
            msg_type="relay_complete",
        )
        # 自动回复确认给 bot（Step 4）
        await _send_to_agent(
            target_id=sender_id,
            content="✅ 确认，已收到你的完成通知。本轮任务完成。",
            from_name="系统(中继)",
            msg_type="relay_ack",
        )
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
    
    # 新增：_inbox:server 中继检查
    if is_server_inbox(msg.get("channel", "")):
        await _handle_server_relay(ws, agent_id, msg)
        continue  # 已由中继处理，不走后续路由
    
    await handle_broadcast(ws, agent_id, msg)
```

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

#### 3.2.3 Bot 不再接收 Step 4

当前模式中，bot 收到 PM 的 Step 4 确认后要**停止回复**（协议规定）。新模式下 **bot 仍然会收到 Step 4 确认**（由 server 发出），但 bot 收到后仍然遵循「不用回复」规则——和当前行为一致。

### 3.3 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **新增** — `_handle_server_relay()` 中继函数 + `_inbox:server` 判断 + 消息入口集成 | ~40 行 |
| `server/__main__.py` | **修改** — ws_handler() 消息入口加中继路由 | ~10 行 |
| `server/config.py` | **新增** — `SERVER_INBOX_CHANNEL` 常量 + `completion_ack_template` 配置 | ~5 行 |
| `clients/ws_client.py` | **可选新增** — `send_to_server()` 辅助方法 | ~5 行 |
| **合计** | | **~60 行净增** |

---

## 4. 验收标准

### 🎯 4.1 核心功能

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | Bot 发 `ACK ✅` 到 `_inbox:server`，PM 收到转发 | PM 收到 `"📬 Bot名 已接活: ACK ✅ ..."` | bot 发 ACK → 检查 PM 收件箱 |
| ✅-2 | Bot 发 `✅ 完成` 到 `_inbox:server`，PM 收到转发 | PM 收到 `"✅ Bot名 任务完成: ✅ 完成..."` | bot 发完成 → 检查 PM 收件箱 |
| ✅-3 | Bot 发 `✅ 完成` 后，server 自动回复确认 | bot 收到 `"✅ 确认，已收到你的完成通知"` | 检查 bot 收件箱 |
| ✅-4 | Bot 发非关键内容（如 `"正在思考..."`）→ 沉默 | PM 不收到此消息，bot 也不收回复 | bot 发杂音 → 检查 PM 收件箱无此消息 |
| ✅-5 | 非 `_inbox:server` 的消息不受影响 | 普通 inbox 消息正常路由（向后兼容） | 正常发消息 → 检查现有路由不变 |

### 🎯 4.2 边界场景

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-6 | `ACK✅`（无空格）→ 不触发转发 | PM 不收到 ACK 通知 | 发送测试 |
| ✅-7 | `✅完成`（无空格）→ 不触发完成转发 | PM 不收到完成通知 | 发送测试 |
| ✅-8 | 多个 bot 同时发消息到 `_inbox:server` | 各自独立转发，互不影响 | 同时发 10 条 |
| ✅-9 | Bot 未注册就发到 `_inbox:server` | 按现有 key 验证逻辑拒绝（不会进入中继） | 未 auth 的连接发消息 |
| ✅-10 | Step 4 确认后 bot 再回复 → 走正常消息路径 | bot 回复到 `_inbox:server`，按前缀匹配处理（可能沉默） | bot 回 Step 4 确认的消息 |

### 🎯 4.3 文档更新

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-11 | inbox-message-protocol.md §8 更新 | 全流程改为 `_inbox:server` 中继模型，附通信图、前缀规则、Bot Checklist 更新 |
| ✅-12 | TODO.md Phase 2 更新 | 已同步本次架构设计 |

---

## 5. 不纳入范围

| 事项 | 原因 |
|:-----|:------|
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
| **2** | 👷 Arch | 技术方案（含伪代码、入口修改点） | 10min |
| **3** | 👨‍💻 Dev | 编码实现（~60 行净增） | 15min |
| **4** | 👀 Review | 代码审查 | 10min |
| **5** | 🦐 QA | 测试报告（12 项验收） | 10min |
| **6** | 🛠️ Operations | 合并部署 + 更新 inbox-message-protocol.md | 10min |

### 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| 部署后 bot 未更新回复地址 | PM 收不到 ACK/完成通知 | 旧 bot 仍可用 `_inbox:<PM_id>` 回复，新模式下不强制立即迁移 |
| `_inbox:server` 被非预期 bot 滥用 | 杂音污染 | 现有 key 验证机制已经拦截未注册 bot |
| ACK 前缀误匹配（bot 写了 `ACK ✅ 已完成` 同时触发两条） | 一条消息同时匹配 ACK 和完成 | 先匹配 ACK，匹配后 `return` 不继续——一条消息只触发一条规则 |
| 自动确认发到错误 bot | bot 收到别人的确认 | Step 4 使用 `sender_id`（发送原始完成消息的 bot），不会串 |

---

## 7. 部署后文档更新

### 7.1 更新 `inbox-message-protocol.md`

实现并部署后，必须更新 §8 全流程通信步骤：

- 替换通信全景 ASCII 图
- 更新 Step 2/Step 3 回复目标（`_inbox:server`）
- 新增 `_inbox:server` 说明小节
- 更新 Bot Checklist（回复地址检查项）
- 移除 SENDER_INBOX 字段概念

### 7.2 更新 Bot 端文档

各 bot 的 Gateway 配置说明中：
- 回复目标改为 `_inbox:server`
- 强调前缀格式要求（`ACK ✅` / `✅ 完成`）
- 说明「非关键消息被沉默」的行为

---

## 8. 脱敏检查清单

- [ ] docs/R87/*.md 零内部名残留（frontmatter 除外）
- [ ] 使用通用角色名（PM / arch / dev / review / QA / operations）
- [ ] 不包含真实 agent_id / token / URL
