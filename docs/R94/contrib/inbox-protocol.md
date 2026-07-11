# Inbox 消息协议（新 Bot 精简版）

> **版本：** v1.0（从 `docs/inbox-message-protocol.md` 精简）  
> **用途：** 新 bot 快速上手 inbox 消息收发  
> **归属：** `ws-bridge-registration` skill → `references/inbox-protocol.md`

---

## 1. 概述

ws-bridge 所有消息都是 **inbox 消息**——每条消息明确发给特定接收者。新 bot 只需要知道三件事：

1. **怎么识别是给我的消息** → 看 `channel` 字段是否以 `_inbox:` 开头
2. **怎么回复** → 发到 `_inbox:server` 中继通道
3. **回复格式** → 严格按前缀规则（否则 PM 看不到）

---

## 2. 消息格式

收到消息的 JSON 结构：

```json
{
    "type": "broadcast",
    "channel": "_inbox:<你的agent_id>",   // ← 是你的消息
    "from_name": "小谷",
    "from_agent": "<发送者agent_id>",
    "content": "消息内容",
    "id": "消息唯一ID",
    "ts": 1234567890.0
}
```

| 字段 | 说明 |
|:-----|:------|
| `channel` | 以 `_inbox:` 开头就是发给你的。`_inbox:<你的agent_id>` 就是你的收件箱 |
| `from_agent` | 发送者的 agent_id，用来识别谁发的（但不作为回复目标） |
| `content` | 消息文本内容 |

---

## 3. 标准 4 步通信

inbox 通信严格按 4 步走，bot 只需参与 Step 2 和 Step 3。

```
小谷(PM)              _inbox:server              Bot
  │                        │                      │
  ├─ Step 1: 派活 ────────│────────────────────→ │  任务到 bot 收件箱
  │                        │                      │
  │←── 转发 ACK ─────────│←── Step 2: ACK ───── │  立即回复 ACK ✅
  │                        │                      │
  │                        │        [实际干活]    │
  │                        │                      │
  │←── 转发完成 ─────────│←── Step 3: 完成 ──── │  完成后回复 ✅ 完成
  │                        │                      │
  │                        │── Step 4: 确认 ──→ │  server 自动回确认
  │                        │                      │  (bot 收到后终止)
```

### Step 1：收到消息

PM 发到 `_inbox:<你的agent_id>`。判断方法：

```python
if msg.get("channel", "").startswith("_inbox:"):
    # 这是给你的消息，必须处理
    pass  # 不因 mention_mode 过滤
```

### Step 2：立即 ACK（5 秒内）

收到任务后**立即**回复确认。必须发到 `_inbox:server`。

```python
await client.send_message(
    content="ACK ✅ R85 收到！",
    channel="_inbox:server",    # ← 固定值，不要改
)
```

- **回复目标：** `_inbox:server`（固定值）
- **回复内容：** 必须以 `ACK ✅` 开头
- **时效：** 收到消息后 5 秒内

### Step 3：完成后回复

任务处理完后（如 git push），回复完成通知。

```python
await client.send_message(
    content="✅ 完成，已推 dev: abc1234",
    channel="_inbox:server",    # ← 固定值
)
```

- **回复目标：** `_inbox:server`（固定值）
- **回复内容：** 必须以 `✅ 完成` 开头

### Step 4：收到确认后终止

server 收到你的 `✅ 完成` 后，自动向你发确认：

```
"✅ 确认，已收到你的完成通知。本轮任务完成。"
```

**⚠️ 收到此消息后不要回复。** 这是通信终点，再回复会开启无效循环。

---

## 4. 前缀规则（必须遵守）

发往 `_inbox:server` 的消息，server **仅根据内容前缀**决定行为：

| 前缀 | 含义 | Server 行为 |
|:----|:-----|:-----------|
| `ACK ✅` | ACK 确认 | 转发给 PM：`📬 {bot名称} 已接活` |
| `✅ 完成` | 完成通知 | 转发给 PM + 自动回确认给 bot |
| 其他任何内容 | 未知 | **沉默**（不转发、不报错） |

**格式必须精确：** `好的，收到` / `已完成` / `✅ 已推` 等非标准格式会被静默丢弃，PM 看不到。

---

## 5. 回复格式规则

inbox 是**工作任务通信**，不是聊天。回复必须遵守：

| 规则 | 说明 |
|:-----|:------|
| ❌ 禁止思考过程 | 不要 `"让我分析一下..."` / `"根据我的理解..."` |
| ❌ 禁止闲聊 | 不要问候、寒暄、重复对方内容 |
| ❌ 不要拆成多条 | 一次说完 |
| ❌ 不要用富文本 | 不需代码块、表格、Markdown |
| ✅ Step 2 | `ACK ✅ Rxx 收到！` |
| ✅ Step 3 | `✅ 完成，已推 dev: xxxxxx` |

---

## 6. Bot Checklist

| # | 行为 | 要求 |
|:-:|:-----|:------|
| 1 | 收到 `_inbox:` 消息 | 必须处理，不因 `mention_mode` 过滤 |
| 2 | 提取 sender_id | 从 `msg.from_agent` 获取（仅识别，不用于回复目标） |
| 3 | Step 2 ACK | 5 秒内回复 `_inbox:server`，以 `ACK ✅` 开头 |
| 4 | 处理任务 | LLM 正常处理 |
| 5 | Step 3 完成 | 完成后回复 `_inbox:server`，以 `✅ 完成` 开头 |
| 6 | 不回复 Step 4 | 收到确认后停止 |
| 7 | `mention_mode` | `false`，不过滤关键词 |
| 8 | `compression.enabled` | `true`（防止上下文溢出） |

---

## 7. FAQ

### 回复发错目标了？
- ✅ `_inbox:server` — 正确。R87 起所有回复走中继通道
- ❌ `_inbox:<sender_id>` — 旧协议，不要再用了

### `_inbox:server` 是什么？
中继通道。bot 的所有回复（ACK + 完成通知）发到这里，由 server 统一处理转发。

### 回复后没有 ACK 返回？
ACK 超时**不代表消息未送达**——消息已投递到目标连接。`send_message` 的 ACK 是独立机制。

### Step 4 确认要不要回复？
**不要回复。** 这是通信终点。再回复会触发新循环。
