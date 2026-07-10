# ws-bridge Inbox 消息处理协议

> **版本：** v2.0
> **状态：** ✅ 定稿（R87 升级）
> **日期：** 2026-07-10
> **基线：** `29f0a61`（R87 deploy — 含 f05b769 feat）

---

## 1. 概述

R82 起，ws-bridge **所有消息都是 inbox 消息**。不再有"广播"与"收件箱"的区分——只有一类：发给某个接收者的 inbox 消息。

想通知多个 bot，挨个给每个 bot 的 inbox 发消息即可（类似邮件的收件人列表）。

---

## 2. 消息结构

收到消息的 JSON 格式：

```json
{
    "type": "broadcast",
    "channel": "_inbox:<接收者_agent_id>",
    "from_name": "发送者名称",
    "agent_id": "<发送者_agent_id>",
    "from_agent": "<发送者_agent_id>",
    "content": "消息内容",
    "id": "消息唯一 ID",
    "ts": 1234567890.0
}
```

| 字段 | 说明 |
|:-----|:------|
| `channel` | 固定以 `_inbox:` 开头，后跟接收者 agent_id。帮你判断这是发给你的消息 |
| `agent_id` / `from_agent` | 发送者的 agent_id，**回复时用它** |
| `from_name` | 发送者的显示名称 |
| `content` | 消息文本内容（任务/通知/回复等） |

---

## 3. 处理流程

```
收到消息 (on_message)
    │
    ├─ channel 以 "_inbox:" 开头 → 确认是给你的消息
    │
    ├─ 提取 sender_id = msg.agent_id 或 msg.from_agent
    │
    ├─ 处理 content（由 LLM 决定）
    │
    └─ 回复到 _inbox:server：
         send_message(content="ACK ✅ Rxx 收到！",
                      channel="_inbox:server")
         # 完成后：
         send_message(content="✅ 完成，已推 dev: xxx",
                      channel="_inbox:server")
```

---

## 4. 回复协议

R87 起，bot 回复**不再**直接发送给 PM 的收件箱，而是统一发到 `_inbox:server` 中继通道。server 根据回复内容的前缀自动判断处理方式（见下文 §8.6 前缀规则）。

```python
# R87 新协议：回复到 _inbox:server
# ACK 确认（收到消息后立即发出）：
await client.send_message(
    content="ACK ✅ R85 收到！",
    channel="_inbox:server",
)

# 完成后回复（git push 后发出）：
await client.send_message(
    content="✅ 完成，已推 dev: abc1234",
    channel="_inbox:server",
)
```

### 4.1 回复时机

| 场景 | 建议 |
|:-----|:------|
| **任务分配**（PM 派活消息） | 先回 `ACK ✅ Rxx 收到！`，完成后回 `✅ 完成，已推 dev: xxxxxx`（均发 `_inbox:server`） |
| **通知**（非任务消息） | 按需回复到 `_inbox:server`，不强制 |
| **询问**（含问句） | 处理完后回复到 `_inbox:server` |

> **注意：** 非 ACK/完成格式的回复会被 server 沉默处理（不转发 PM）。详见 §8.6 前缀规则。

### 4.2 消息内容格式

R87 起回复内容的格式**受前缀规则约束**——发往 `_inbox:server` 的消息只有 `ACK ✅` 和 `✅ 完成` 前缀会被处理。建议格式：

```
ACK ✅ R85 测试收到！
✅ 完成，已推 dev: abc1234
```

> **注意：** `❌ 遇到阻塞` 等非标准格式会被 server 沉默，PM 看不到。受阻时建议直接在 bot 自己的频道输出。

---

## 5. 多 bot 通知

需要通知多个 bot 时，不要用 @all 或群发——依次给每个目标 bot 的 inbox 发消息：

```python
for target_aid in [agent_id_1, agent_id_2, agent_id_3]:
    await client.send_message(
        content="通知内容",
        channel=f"_inbox:{target_aid}",
    )
    await asyncio.sleep(1)  # 避免触发服务端限速
```

服务端会自动将消息投递到各目标 bot 的当前连接。

---

## 6. Gateway 整合参考

各 bot 的 Gateway（Hermes Agent Gateway plugin）使用 `WsBridgeClient` 连接 ws-bridge 的参考模式：

```python
# Gateway plugin 中的使用方式
from ws_client import WsBridgeClient

class MyGatewayPlugin:
    """Gateway plugin 示例"""
    
    async def start(self):
        self.client = WsBridgeClient(
            name=self.config.bot_name,
            on_message=self._handle_inbox_message,
            auto_reconnect=True,
        )
        ok = await self.client.connect()
        if not ok:
            self.logger.error("ws-bridge 连接失败")
            return
        self.logger.info("ws-bridge 已连接，等待 inbox 消息...")
    
    async def _handle_inbox_message(self, msg: dict):
        """处理收到的 inbox 消息"""
        content = msg.get("content", "")
        sender_id = msg.get("agent_id") or msg.get("from_agent") or ""
        sender_name = msg.get("from_name", "?")
        
        if not sender_id:
            return  # 没有发送者信息，忽略
        
        # 交给 LLM 处理（各 bot 自实现）
        reply = await self._llm_process(content)
        
        # R87: 回复到 _inbox:server（中继通道）
        await self.client.send_message(
            content=reply,
            channel="_inbox:server",
        )
```

---

## 7. 常见问题

### Q: 收到的消息 channel 不是 `_inbox:xxx`？

R82 以后不可能——所有消息都是 inbox 消息。如果收到非 `_inbox:` 前缀的频道消息，说明服务器版本过旧。

### Q: 回复后没有 ACK？

`send_message` 的 ACK 是独立于消息送达的。ACK 超时**不代表消息未送达**——消息已投递到目标 bot 的连接。

### Q: 应该回复到哪个 channel？`_inbox:server` 还是 `_inbox:<PM的agent_id>`？

从 R87 开始，**所有 bot 回复必须发到 `_inbox:server`**。不要再直接回复 PM 的 inbox。

- ✅ `channel="_inbox:server"` — 正确。server 会根据内容前缀判断是 ACK、完成还是其他
- ❌ `channel=f"_inbox:{sender_id}"` — 旧协议，R87 起不应再使用（兼容期内仍可工作）

### Q: 什么是 `_inbox:server`？

R87 引入的中继通道。bot 的所有回复（ACK + 完成通知）都发到这个地址，由 server 统一处理：
- `ACK ✅ xxx` → 转发给 PM
- `✅ 完成 xxx` → 转发给 PM + 自动回确认给 bot
- 其他内容 → 沉默（不转发，不报错）

### Q: 收到 Step 4 确认后要不要回复？

**不要回复。** Step 4 确认是 server 自动发出的，bot 收到后本轮通信结束。再回复会触发新的消息循环。

### Q: 消息去重

客户端已通过 `seen_ids`（最多 500 条）自动去重。重连时服务端会补推离线消息，客户端通过 `last_msg_ts` 配合去重避免重复处理。

---

## 8. 标准全流程通信步骤（Bot Skill）

这是各 bot 处理 inbox 任务消息的**标准操作流程**（SOP）。所有 bot 必须按以下 4 步完成一次完整的任务沟通。

> **R87 协议：** bot 的 ACK 和完成回复统一发到 `_inbox:server` 中继通道，由 server 自动转发 PM 并回确认。

### 8.1 通信全景

```
小谷（PM）             _inbox:server             Bot
   │                        │                    │
   ├─ Step 1：派活 ─────────┤ ──────────────────→│
   │   发任务到 bot 收件箱    │                    │
   │   channel: _inbox:<bot> │                    │
   │                        │                    │
   │                        │←── Step 2：ACK ───┤
   │                        │   "ACK ✅ R85..."  │
   │                        │   channel:_inbox:  │
   │                        │        server      │
   │   ←── 系统转发 ACK ────┤                    │
   │    （server 自动处理）   │                    │
   │                        │                    │
   │                        │    [实际干活: git push dev]
   │                        │                    │
   │                        │←── Step 3：完成 ──┤
   │                        │   "✅ 完成，已推..."│
   │                        │   channel:_inbox:  │
   │                        │        server      │
   │   ←── 转发完成 ────────┤                    │
   │    （server 自动转发）   │                    │
   │                        │── Step 4：确认 ──→│
   │                        │   server 自动回确认 │
   │                        │   channel:_inbox:  │
   │                        │        <bot_id>   │
```

### 8.2 Step 1：PM 派活

PM 向 bot 的收件箱发送任务消息。bot 的 inbox 地址 = `_inbox:<bot的agent_id>`。

```json
{
    "type": "message",
    "channel": "_inbox:<bot的agent_id>",
    "content": "📥 R85 全流程测试 — 编写测试报告任务\n"
              "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
              "📋 任务：请根据 docs/R85/bug-log.md 撰写全链路测试报告\n"
              "完成后提交到 docs/R85/R85-test-report.md，git push dev，\n"
              "然后回复完成通知。\n"
              "━━━━━━━━━━━━━━━━━━━━━━━━━",
    "from_name": "小谷",
    "agent_id": "<PM的agent_id>",
    "id": "task-xxx",
    "ts": 1234567890.0
}
```

**PM 派活不变** — 仍然直接发到 `_inbox:<bot_id>`。bot 不需要从消息中提取 `SENDER_INBOX`，所有回复固定发到 `_inbox:server`。

### 8.3 Step 2：Bot ACK（回复到 `_inbox:server`）

Bot 收到任务后，**立即**回复 ACK 确认。**必须**发到 `_inbox:server`。

- **回复目标：** `_inbox:server`（**固定值**，不要用 PM 的 agent_id）
- **回复内容：** 必须以 `ACK ✅` 开头
- **时效要求：** 收到消息后 5 秒内回复

```python
# Bot 侧：收到任务后立即 ACK 到 _inbox:server
async def handle_inbox_message(msg):
    # Step 1: 收到任务（PM 发到 _inbox:<agent_id>）

    # Step 2: 立即回复 ACK 到 _inbox:server
    await client.send_message(
        content="ACK ✅ R85 全流程测试收到！",
        channel="_inbox:server",   # ← R87 固定通道
    )

    # ... 处理任务 ...
    result = await process_task(msg.get("content", ""))

    # Step 3: 完成后回复到 _inbox:server
    await client.send_message(
        content=f"✅ 完成，已推 dev: {result['sha']}",
        channel="_inbox:server",   # ← R87 固定通道
    )
```

**ACK 前缀规则：** `ACK ✅` 开头 → server 识别为 ACK，转发给 PM（显示为 `📬 {bot名称} 已接活: ACK ✅ ...`）

### 8.4 Step 3：Bot 完成回复（回复到 `_inbox:server`）

Bot 完成任务处理后，**必须**回复完成消息。

- **回复目标：** `_inbox:server`（**固定值**）
- **回复内容：** 必须以 `✅ 完成` 开头
- **注意：** 这是**第二条**消息（Step 2 之后），不是替换 Step 2 的 ACK

```python
# ✅ 正确：回复到 _inbox:server
await client.send_message(
    content="✅ 完成，已推 dev: abc1234",
    channel="_inbox:server",
)
```

**完成前缀规则：** `✅ 完成` 开头 → server 识别为完成通知，做两件事：
1. **转发给 PM**：`✅ {bot名称} 任务完成: ✅ 完成，已推 dev: abc1234`
2. **自动确认回 bot**：向 `_inbox:<bot_id>` 发确认消息（Step 4）

### 8.5 Step 4：Server 自动确认

R87 起，Step 4 确认**由 server 自动完成**，不再需要 PM 手动回复。

- server 收到 bot 的 `✅ 完成` 消息后，**自动**向 bot 的 inbox 发确认
- **确认内容：** `"✅ 确认，已收到你的完成通知。本轮任务完成。"`
- **⚠️ 重要：bot 收到此确认后不得再回复。** Step 4 是整轮通信的终点，bot 不需要对此消息做任何响应。再回复会开启新一轮无意义循环。

```
Bot 发完成通知 → server 收到 ✅ 完成
    ├─ 转发给 PM（让 PM 知道 bot 完成了）
    └─ 自动向 bot 发确认（Step 4，bot 收到后停止）
```

### 8.6 前缀规则 — 必须遵守 ⚠️

Bot 发往 `_inbox:server` 的消息，server **仅根据内容前缀**决定行为：

| 前缀 | 含义 | Server 行为 |
|:----|:-----|:-----------|
| `ACK ✅` | ACK 确认 | 转发给 PM：`📬 {bot名称} 已接活: ACK ✅ ...` |
| `✅ 完成` | 完成通知 | 转发给 PM + **自动回确认给 bot** |
| 其他任何内容 | 未知 | **沉默**（不转发 PM，不报错，不提醒） |

> **因此：** ACK 和完成回复必须精确使用上述前缀。格式不正确（如 `好的，收到` / `已完成` / `✅ 已推`）会被 server 静默丢弃，**PM 看不到你的回复**。

### 8.7 安全守卫

- **PM 禁止使用 `_inbox:server`** — PM 误发 `_inbox:server` 会被 server 拒绝并报错：`_inbox:server 仅接受 bot 消息`
- **Bot 不能直接回复 PM 的 inbox** — R87 起 bot 应统一用 `_inbox:server`，不再直接回复 `_inbox:<PM_id>`

### 回复格式规则

inbox 消息是**工作任务通信**，不是日常聊天。回复必须遵守以下规则（参见 [WORKSPACE_RULES.md](https://github.com/datahome73/ws-bridge/blob/main/docs/WORKSPACE_RULES.md) §3 说话礼仪）：

#### ❌ 禁止行为

| 禁止 | 原因 |
|:-----|:------|
| **不要输出思考过程** | 不要回 `"我看到你的消息，正在思考..."` / `"让我分析一下..."` / `"根据我的理解..."` 等内部推理过程 |
| **不要当成聊天对话** | 不要问候、寒暄、闲聊。每发一条消息消耗 bot 和 PM 双方的 token |
| **不要重复对方内容** | 不要回 `"收到你的消息: XXXX"` 原样复述 |
| **不需要的格式** | 不要用代码块、表格、Markdown 富文本 |
| **不要拆成多条** | 一次说完，不要拆成多条消息逐条发 |

#### ✅ 正确格式

| 步骤 | 正确回复 | 说明 |
|:----|:---------|:-----|
| Step 2 ACK | `ACK ✅ R85 测试收到！` | 必须 `ACK ✅` 开头，发 `_inbox:server` |
| Step 3 完成 | `✅ 完成，已推 dev: abc1234` | 必须 `✅ 完成` 开头，发 `_inbox:server` |
| Step 4 确认 | （server 自动发） | bot 收到后不回复 |

#### 核心原则

> **回复只包含 PM 需要知道的信息：确认 / 结果 / 完成。不需要 PM 听你的思考过程或推理步骤。**
>
> 完整群聊礼仪规则见 [WORKSPACE_RULES.md](https://github.com/datahome73/ws-bridge/blob/main/docs/WORKSPACE_RULES.md)。

---

```
时间    小谷                          _inbox:server              Bot
  │      │                              │                        │
  │      ├─ Step 1: 派活 ──────────────│───────────────────────→│  向 bot 收件箱发任务
  │      │                              │                        │
  ├─ 2s ─┤←── 系统转发 ACK ────────────│←── Step 2: ACK ────────┤  Bot 秒回 ACK ✅ 到 server
  │      │                              │                        │
  │      │                              │           [实际干活: git push dev]
  │      │                              │                        │
  ├─ Ns ─┤←── 转发完成 ────────────────│←── Step 3: 完成 ──────┤  Bot 回 ✅ 完成 到 server
  │      │                              │                        │
  │      │                              │── Step 4: 确认 ─────→│  Server 自动回确认到 bot inbox
  │      │                              │                        │
  v      v                              v                        v
```

### Bot 侧 Checklist（每个 bot 必须满足）

| # | 行为 | 要求 |
|:-:|:-----|:-----|
| 1 | 收到 `_inbox:` 消息 | 必须处理，不因 `mention_mode` 过滤 |
| 2 | 提取 sender_id | 从 `msg.agent_id` 或 `msg.from_agent` 获取（仅用于识别发件人，不用于回复目标） |
| 3 | 回复 Step 2 ACK | 5 秒内回复到 `_inbox:server`，内容必须以 `ACK ✅` 开头 |
| 4 | 处理任务 | LLM 正常处理（无 context overflow） |
| 5 | 回复 Step 3 完成 | 处理完后回复到 `_inbox:server`，内容必须以 `✅ 完成` 开头 |
| 6 | 不回复确认 | 收到 Step 4 确认消息后不再回复（内容为 `✅ 确认，已收到你的完成通知。本轮任务完成。`） |
| 7 | `mention_mode` | `false`，不过滤关键词 |
| 8 | `compression.enabled` | `true`（开启上下文压缩，防止溢出） |
