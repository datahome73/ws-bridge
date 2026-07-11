# 爱泰 Inbox 通信协议测试记录

> **日期：** 2026-07-08
> **测试人：** 爱泰（ws_0bb747d3ea2a）

---

## 1. 阅读 docs/inbox-message-protocol.md 的体会

### 核心变化

R82 起，ws-bridge 所有消息都是 inbox 消息，不再区分"广播"和"收件箱"。每条消息通过 `channel: "_inbox:<接收者_agent_id>"` 定向投递。

### 消息结构

```json
{
    "type": "broadcast",
    "channel": "_inbox:<接收者_agent_id>",
    "from_name": "小谷",
    "agent_id": "<发送者_agent_id>",
    "from_agent": "<发送者_agent_id>",
    "content": "消息内容",
    "id": "消息唯一 ID",
    "ts": 1234567890.0
}
```

关键字段：
- `channel` — 固定 `_inbox:` 前缀 + 接收者 agent_id
- `agent_id` / `from_agent` — 发送者的 agent_id，回复时用它
- `from_name` — 发送者的显示名称

### Gateway Handler 改动要点

1. **inbox 路由**：收到 `_inbox:` 消息后，`chat_id` 必须改为 `_inbox:<sender_id>`，否则回复会发到自己的 inbox（server 拒绝）
2. **mention_mode 绕过**：inbox 消息是直接发给我的，不应按 mention 关键词过滤
3. **agent_id 回退**：消息中 `agent_id` 和 `from_agent` 两个字段都可能存在，需 `from_agent = msg.get("from_agent") or msg.get("agent_id")`
4. **_active_channel 保护**：收到 `_inbox:` 消息时不更新 `_active_channel`，保持为 lobby，避免后续发送误用

### 实际遇到的坑

| 问题 | 现象 | 根因 |
|:-----|:------|:------|
| 回复被拒 | `Server error: ❌ 不允许向自己的收件箱发消息` | `_active_channel` 被 inbox 消息覆盖成 `_inbox:<own_agent_id>`，回复发送错误 |
| mention 误过滤 | inbox 消息被丢弃 | mention_mode 检查时未跳过 `_inbox:` 消息 |
| 字段缺失 | `from_agent` 为空导致路由失败 | 只读 `from_agent` 字段，未回退到 `agent_id` |

---

## 2. 4 步通信流程的理解

```
小谷（PM）                     爱泰（Bot）
   │                             │
   ├─ Step 1：派活 ─────────────→│  发任务到 bot 收件箱
   │    channel: _inbox:<bot_id>  │  content 含 SENDER_INBOX
   │                             │
   │←──── Step 2：ACK ──────────┤  5 秒内回复确认
   │    "ACK ✅ R85 收到！"       │  回复到 SENDER_INBOX
   │                             │
   │←── Step 3：完成回复 ────────┤  git push 后回复完成
   │    "✅ 完成，已推 dev: xxx"  │  回复到 SENDER_INBOX
   │                             │
   ├─ Step 4：确认 ─────────────→│  PM 确认闭环
   │    "✅ 已收到完成通知。"     │  收到后 bot 不再回复
```

### 回复目标规则

回复目标必须是 **发送者的 inbox**（`_inbox:<sender_id>`），不是收到的 channel（那是自己的 inbox）。

```python
# ✅ 正确
sender_id = msg.get("agent_id") or msg.get("from_agent")
await client.send(content="ACK ✅", channel=f"_inbox:{sender_id}")

# ❌ 错误 — server 拒绝
await client.send(content="ACK ✅", channel=msg.get("channel"))
```

### 回复时机

| 场景 | 行为 |
|:-----|:------|
| 任务分配（`📥` 开头） | Step 2 ACK → 执行 → Step 3 完成 |
| 通知 | 按需回复 |
| 询问（含问句） | 处理后回复 |

---

## 3. 回复格式规则总结

### ❌ 禁止行为

| 禁止项 | 说明 |
|:-------|:------|
| 思考过程 | 不要输出推理步骤、分析 |
| 闲聊寒暄 | 不问候、不重复对方内容 |
| 富文本 | 不要用代码块、表格、Markdown |
| 拆条发 | 一次说完，不分多条 |

### ✅ 正确格式

| 步骤 | 回复 | 说明 |
|:----|:-----|:------|
| Step 2 ACK | `ACK ✅ R85 收到！` | 一句话确认 |
| Step 3 完成 | `✅ 完成，已推 dev: abc1234` | 只说结果 |
| Step 4 确认 | `✅ 已收到你的完成通知。` | 简短确认 |

### 核心原则

> 回复只包含 PM 需要知道的信息：确认 / 结果 / 完成。不需要 PM 听思考过程。
>
> 每条消息都消耗 bot 和 PM 双方的 token，保持简洁。

---

## 4. 测试结论

| 测试项 | 状态 | 说明 |
|:-------|:-----|:------|
| 消息接收 | ✅ | inbox 消息正常投递 |
| ACK 回复 | ✅ | 修复后 ACK 成功送达 |
| 任务执行 | ✅ | 本记录已提交 |
| 4 步闭环 | ⏳ | 等待 PM（小谷）Step 4 确认 |
| mention 过滤 | ✅ | inbox 消息已跳过 keyword 检查 |
| 抗重连 | ✅ | 网关重启后仍能收到离线期间的消息 |

---

*爱泰 — 2026-07-08*
