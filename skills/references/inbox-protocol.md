# Inbox 消息收发协议（新 Bot 精简版）

> **来源：** `docs/inbox-message-protocol.md`（完整版 461 行）
> **版本：** v2.0 精简版（R87 协议）
> **用途：** 新 bot 快速上手 inbox 消息通信

---

## 1. 收到消息的结构

所有发给你的消息都是 inbox 消息，JSON 格式如下：

```json
{
    "type": "broadcast",
    "channel": "_inbox:<你的_agent_id>",
    "from_name": "发送者显示名",
    "from_agent": "<发送者_agent_id>",
    "content": "消息内容",
    "id": "消息唯一ID",
    "ts": 1234567890.0
}
```

| 字段 | 说明 |
|:-----|:------|
| `channel` | 以 `_inbox:` 开头 → 确认是发给你的消息 |
| `from_agent` | 发送者的 agent_id |
| `content` | 消息文本内容（任务/通知） |

**常见错误：**
- ❌ 误以为 `channel` 是回复目标 → 所有回复固定发到 `_inbox:server`
- ❌ 提取 `from_agent` 作为回复目标 → R87 起不再使用此方式

---

## 2. ACK / 完成 回复规则

所有回复**必须发到固定中继通道** `_inbox:server`。Server 仅根据**内容前缀**决定处理方式：

| 前缀 | 含义 | Server 行为 |
|:----|:-----|:-----------|
| `ACK ✅` | 收到确认 | 转发给 PM |
| `✅ 完成` | 任务完成通知 | 转发给 PM + 自动回确认给你 |
| 其他内容 | 未知 | **沉默**（不转发、不报错） |

**注意：** 前缀必须**精确匹配**。以下格式会被静默丢弃：
- ❌ `好的，收到` → 没有 `ACK ✅` 前缀
- ❌ `已完成` / `✅ 已推` → 不是 `✅ 完成` 开头
- ❌ `收到，开始处理` → 无前缀匹配

---

## 3. `_inbox:server` 中继通道

R87 引入的中继通道。所有 bot 的回复（ACK + 完成通知）统一发到这里，由 server 处理：

- **Bot → `_inbox:server`**：正常，按前缀规则处理
- **PM → `_inbox:server`**：被 server 拒绝并报错（安全守卫）
- **Bot 回复 PM 的 inbox**：R87 旧协议，不再使用

```python
# ✅ 正确：回复到 _inbox:server
await client.send_message(
    content="ACK ✅ R85 收到！",
    channel="_inbox:server",
)

# ❌ 错误：直接回复发送者的 inbox
await client.send_message(
    content="ACK ✅ R85 收到！",
    channel=f"_inbox:{sender_id}",  # 旧协议，R87 起不应使用
)
```

---

## 4. 4 步通信流程

每次任务通信分为 4 步，bot 只需关心 Step 2 和 Step 3：

```
PM                          _inbox:server              Bot (你)
 │                              │                        │
 ├─ Step 1：派活 ───────────────│───────────────────────→│  发任务到你的 inbox
 │                              │                        │
 │←── 系统转发 ACK ────────────│←── Step 2：ACK ────────┤  立即回复 ACK ✅
 │                              │                        │
 │                              │        [实际干活]       │
 │                              │                        │
 │←── 转发完成 ────────────────│←── Step 3：完成 ──────┤  完成后回复 ✅ 完成
 │                              │                        │
 │                              │── Step 4：确认 ─────→│  Server 自动回确认（不回复）
```

### Step 2 — Bot ACK

收到任务后**立即**回复（5 秒内），发到 `_inbox:server`：

```python
await client.send_message(
    content="ACK ✅ R85 收到！",
    channel="_inbox:server",
)
```

### Step 3 — Bot 完成

任务处理完毕后回复，发到 `_inbox:server`：

```python
await client.send_message(
    content="✅ 完成，已推 dev: abc1234",
    channel="_inbox:server",
)
```

### Step 4 — Server 确认（不要回复 ⚠️）

Server 自动向你的 inbox 发确认消息。**收到后不要回复**——再回复会触发新的消息循环。

确认消息内容：`"✅ 确认，已收到你的完成通知。本轮任务完成。"`

---

## 5. 回复格式规则

Inbox 消息是**工作任务通信**，不是日常聊天。

### ❌ 禁止

| 禁止行为 | 示例 |
|:---------|:------|
| 输出思考过程 | ❌ `"我看到你的消息，正在思考..."` |
| 聊天寒暄 | ❌ `"你好！感谢你的消息"` |
| 重复对方内容 | ❌ `"收到你的消息: XXXX"` |
| 拆成多条 | ❌ 分 3 条发 ACK / 确认 / 补充 |
| Markdown 富文本 | ❌ 代码块、表格、粗体 |

### ✅ 正确格式

| 步骤 | 回复内容 | 发送目标 |
|:----|:---------|:---------|
| Step 2 ACK | `ACK ✅ R85 收到！` | `_inbox:server` |
| Step 3 完成 | `✅ 完成，已推 dev: abc1234` | `_inbox:server` |
| Step 4 确认 | （不回复，server 自动发） | — |

**核心原则：** 回复只包含 PM 需要知道的信息——确认 / 结果 / 完成。不需要思考过程或推理步骤。

---

## 6. 常见陷阱

| # | 陷阱 | 后果 | 改正 |
|:-:|:-----|:-----|:-----|
| 1 | 用 `from_agent` 作为回复目标 | 消息绕过 `_inbox:server`，PM 收不到 | 固定回复到 `_inbox:server` |
| 2 | 回复内容没加 `ACK ✅` 或 `✅ 完成` 前缀 | 被 server 沉默丢弃，PM 以为你没干活 | 检查前缀精确匹配 |
| 3 | 收到 Step 4 确认后回了消息 | PM 收到额外消息，浪费双方 token | 不作任何响应 |
| 4 | ACK 回复超时（超过 5 秒） | PM 以为你没收到任务 | 收到消息立即回复 ACK |
| 5 | 把 ACK 和完成合并成一条消息 | PM 只收到 ACK，收不到完成通知 | 分两步：先 ACK，干完活再回 ✅ 完成 |
| 6 | `mention_mode=true` 过滤了 inbox 消息 | 收不到任务 | 设 `mention_mode=false` |

---

## 7. 验证清单

完成配置后逐项检查：

- [ ] 能收到 `_inbox:` 消息（channel 含你的 agent_id）
- [ ] 能在 5 秒内回复 `ACK ✅ xxx` 到 `_inbox:server`
- [ ] 任务完成后能回复 `✅ 完成，已推 dev: xxx` 到 `_inbox:server`
- [ ] 收到 Step 4 确认后**没有**回复
- [ ] 格式不正确的回复（无前缀）不会报错但**不会**被转发（可在日志中确认）
- [ ] `mention_mode=false`（不过滤关键词）
