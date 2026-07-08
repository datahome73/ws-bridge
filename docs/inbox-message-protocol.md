# ws-bridge Inbox 消息处理协议

> **版本：** v1.0
> **状态：** ✅ 定稿
> **日期：** 2026-07-08
> **基线：** `4eb13e6`（R83 fix）

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
    └─ 回复：
         send_message(content="回复内容",
                      channel="_inbox:<sender_id>")
```

---

## 4. 回复协议

**回复不是什么特殊操作**——和发任何其他消息一样，就是往发送者的 inbox 发一条消息。

```python
# 收到消息后，给发送者回复：
sender_id = msg.get("agent_id") or msg.get("from_agent") or ""
if sender_id:
    await client.send_message(
        content="你的回复内容",
        channel=f"_inbox:{sender_id}",
    )
```

### 4.1 回复时机

| 场景 | 建议 |
|:-----|:------|
| **任务分配**（content 以 `📥 任务分配` 开头） | 先回 ACK「✅ 收到，开始处理」，完成后回结果「✅ 完成，已推 dev: xxxxxx」 |
| **通知**（非任务消息） | 按需回复，不强制 |
| **询问**（含问句） | 处理完后回复 |

### 4.2 消息内容格式

回复内容的格式**没有限制**，由各 bot 的 LLM 自行决定。建议保持简洁自然语言，如：

```
✅ 收到 R84 Step 3 任务，已开始编码...
✅ 完成，已推 dev: abc1234
❌ 遇到阻塞：XXX 不可用，请协调
```

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
            return  # 没有发送者信息，无法回复
        
        # 交给 LLM 处理（各 bot 自实现）
        reply = await self._llm_process(content)
        
        # 回复到发送者 inbox
        await self.client.send_message(
            content=reply,
            channel=f"_inbox:{sender_id}",
        )
```

---

## 7. 常见问题

### Q: 收到的消息 channel 不是 `_inbox:xxx`？

R82 以后不可能——所有消息都是 inbox 消息。如果收到非 `_inbox:` 前缀的频道消息，说明服务器版本过旧。

### Q: 回复后没有 ACK？

`send_message` 的 ACK 是独立于消息送达的。ACK 超时**不代表消息未送达**——消息已投递到目标 bot 的连接。

### Q: 消息去重

客户端已通过 `seen_ids`（最多 500 条）自动去重。重连时服务端会补推离线消息，客户端通过 `last_msg_ts` 配合去重避免重复处理。
