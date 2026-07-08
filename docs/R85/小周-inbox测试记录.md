# 小周 Inbox 通信测试记录

> **日期：** 2026-07-08
> **测试人：** 小周
> **基线：** `4eb13e6`（R83 fix）

---

## 一、阅读 `docs/inbox-message-protocol.md` 的体会

### 1.1 核心变化

R82 之后，ws-bridge 的所有消息统一为 inbox 消息。不再有"广播"和"收件箱"的区分——只有一类消息：发给某个接收者的 inbox 消息。

**关键设计：**

- 频道格式固定为 `_inbox:<接收者_agent_id>`
- 每条消息都携带发送者的 `agent_id` / `from_agent`，回复时用它构造目标频道
- 服务端自动将消息投递到目标 bot 当前连接，多 bot 通知用循环发送代替 @all

### 1.2 协议层次

这是一个"应用层协议"——它定义的是消息路由和通信流程的规则，不改变底层 WebSocket 传输。server 端只负责投递，bot 端负责按流程回复。

### 1.3 设计优势

- 消除了"广播 vs 收件箱"的歧义，路由逻辑统一
- 回复路径是显式的（`_inbox:<sender_id>`），不存在歧义
- 多 bot 通知通过循环分别发送，各自独立，互不干扰
- 去掉了 `set_active_channel` / `channel_updated` 等冗余消息类型

---

## 二、4 步通信流程的理解

### 全景图

```
时间    小谷（PM）                     Bot
 │        │                            │
 │        ├─ Step 1：派活 ─────────────→│  向 bot 收件箱发任务（含 SENDER_INBOX）
 │        │                            │
 ├─ 2s ─┤←── Step 2：ACK ───────────────┤  Bot 秒回 ACK 确认
 │        │                            │
 │        │                     [执行任务: git push dev]
 │        │                            │
 ├─ Ns ─┤←── Step 3：完成回复 ──────────┤  Bot git push 后回复完成
 │        │                            │
 │        ├── Step 4：确认回复 ─────────→│  PM 回确认，闭环完成
 │        │                            │
 v        v                            v
```

### 各步骤详解

#### Step 1: PM 派活
- PM 向 bot 的收件箱 `_inbox:<bot_agent_id>` 发送消息
- 内容包含任务描述 + `SENDER_INBOX` 字段（告诉 bot 回复到哪里）

#### Step 2: Bot ACK
- Bot 收到任务后 **5 秒内**回复 ACK
- 回复目标：`_inbox:<发件人的 agent_id>`
- 内容简短：`ACK ✅ R{轮次} 任务收到！`

#### Step 3: Bot 完成回复
- 任务执行完毕后（git push dev 后），回复完成消息
- 回复目标：同上（`_inbox:<发件人的 agent_id>`）
- 内容：`✅ 完成，已推 dev: xxx`

#### Step 4: PM 确认
- PM 收到完成回复后，向 bot 回确认
- **Bot 收到此确认后不得再回复**——这是整轮通信的终点

### 关键规则

| 规则 | 说明 |
|:-----|:------|
| 回复目标 | 永远是 `_inbox:<sender_id>`，**不是**自己的收件箱 |
| 回复时机 | ACK 5s 内，完成后立即回 |
| 禁止循环 | Step 4 后 bot 不得再回复 |
| 不回复自己 | server 会拒绝向自己收件箱发消息 |

---

## 三、回复格式规则的总结

### 规则含义

inbox 消息是**工作任务通信**，不是日常聊天。回复必须简洁、直接、不含冗余信息。

### ❌ 禁止行为

| 行为 | 原因 |
|:-----|:------|
| 输出思考过程 | "我正在分析..."/"让我看看..." 消耗双方 token |
| 聊天/寒暄/闲聊 | 每一条消息都有成本 |
| 重复对方内容 | "收到你的消息: XXXX" 无意义 |
| Markdown 富文本 | 不需要格式（ACK 用纯文本） |
| 拆成多条 | 一次说完 |

### ✅ 正确格式

| 步骤 | 回复 | 说明 |
|:-----|:------|:------|
| Step 2 ACK | `ACK ✅ R85 任务收到！` | 一句话确认 |
| Step 3 完成 | `✅ 完成，已推 dev: abc1234` | 只说结果 |
| Step 4 确认 | `✅ 已收到你的完成通知。` | 简短闭环 |

### 核心原则

> 回复只包含 PM 需要知道的信息：确认 / 结果 / 完成。不需要 PM 听你的思考过程或推理步骤。

---

## 四、Gateway 适配总结

### 对 Gateway 插件的修改

将 ws-bridge Gateway 插件（`__init__.py`）从广播模式适配为 inbox 协议：

| 修改 | 说明 |
|:-----|:------|
| `_determine_channel` | 不再忽略 `context_channel`，inbox 消息回复到 `_inbox:<sender_id>` |
| `_process_inbound_message` | inbox 消息不覆盖 `_active_channel` |
| `_handle_ws_message` | inbox 消息绕过 `mention_mode` 过滤 |
| `chat_id` 映射 | 用发送者收件箱代替自己收件箱作为会话 chat_id |
| `user_id` / `user_name` | 使用发送者真实身份，替代硬编码 `ws_bridge_user` |
| `authorization_is_upstream` | 添加 adapter property，绕过 Gateway 授权检查 |

### Bot 侧 Checklist

| # | 要求 | 实现 |
|:-:|:-----|:-----|
| 1 | 收到 `_inbox:` 消息必须处理 | ✅ |
| 2 | 提取 `sender_id` | ✅ |
| 3 | 5 秒内回复 ACK | ✅ |
| 4 | 处理任务 | ⚠️ 需在 ACK 后继续执行 |
| 5 | 回复完成消息 | ✅ 传输层已通 |
| 6 | 不回复自己 | ✅ server 拒绝 + 代码过滤 |
| 7 | `mention_mode=false` | ✅ |
| 8 | `compression.enabled=true` | ✅ |

---

## 五、测试结论

| 项目 | 状态 |
|:-----|:-----|
| 消息接收 | ✅ 小谷消息正常到达 |
| chat_id 映射 | ✅ 映射到发送者收件箱 |
| ACK 回复 | ✅ 成功发送，无报错 |
| 授权通过 | ✅ `authorization_is_upstream` 生效 |
| 任务执行 | ⚠️ ACK 后需继续执行任务 |
| Step 3 完成回复 | ⚠️ 待完善 |
| 通信闭环 | ⚠️ 待完整测试 |
