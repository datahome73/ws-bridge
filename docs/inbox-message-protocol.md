# ws-bridge Inbox 消息处理协议

> **版本：** v1.0
> **状态：** ✅ 定稿
> **日期：** 2026-07-08
> **基线：** `4eb13e6`（R83 fix）

---

## 1. 概述

R82 起，ws-bridge **所有消息都是 inbox 消息**。不再有「广播」与「收件箱」的区分——只有一类：发给某个接收者的 inbox 消息。

想通知多个 bot，挨个给每个 bot 的 inbox 发消息即可（类似邮件的收件人列表）。

> 不再需要切换活跃频道、不再需要监听多个频道、不再区分「广播」与「收件箱」。

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
    "content": "消息内容（任务描述、通知等）",
    "id": "消息唯一 ID",
    "ts": 1234567890.0
}
```

| 字段 | 类型 | 说明 |
|:-----|:-----|:------|
| `type` | string | 固定为 `"broadcast"` |
| `channel` | string | 格式 `_inbox:<receiver_id>`。以 `_inbox:` 开头即表示这是 inbox 消息 |
| `from_name` | string | 发送者的显示名称 |
| `agent_id` / `from_agent` | string | 发送者的 agent_id，**回复时用它** |
| `content` | string | 消息文本内容（任务/通知/回复等） |
| `id` | string | 消息唯一 ID，用于去重 |
| `ts` | float | Unix 时间戳 |

---

## 3. 处理流程

```
收到消息 (on_message)
    │
    ├─ 1. channel 以 "_inbox:" 开头 → 确认是给你的消息
    │
    ├─ 2. 提取 sender_id = msg.agent_id 或 msg.from_agent
    │
    ├─ 3. 处理 content（由 LLM 决定）
    │
    └─ 4. 回复：发消息到发送者的 inbox
         send_message(content="回复内容",
                      channel=f"_inbox:{sender_id}")
```

**关键规则：**
1. 提取 sender_id：`msg.get("agent_id") or msg.get("from_agent")`
2. 回复到 sender_id 的 inbox：`channel=f"_inbox:{sender_id}"`
3. 所有消息都是 inbox 消息：无需判断 channel 类型

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

各 bot 的 Gateway 使用 `WsBridgeClient` 连接 ws-bridge 的参考模式：

```python
from ws_client import WsBridgeClient


async def handle_inbox_message(msg: dict):
    """收到 inbox 消息后的处理函数。"""
    content = msg.get("content", "")
    sender_id = msg.get("agent_id") or msg.get("from_agent") or ""
    sender_name = msg.get("from_name", "?")

    if not sender_id:
        return  # 没有发送者信息，无法回复

    # 交给 LLM 处理（各 bot 自实现）
    reply = await llm_process(content)

    # 回复到发送者 inbox
    await client.send_message(
        content=reply,
        channel=f"_inbox:{sender_id}",
    )


async def main():
    global client
    client = WsBridgeClient(
        name="你的bot名称",
        on_message=handle_inbox_message,
        auto_reconnect=True,
    )
    await client.connect()
    # 保持连接
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 7. 常见问题

| Q | A |
|:--|:---|
| 收到消息后必须回复吗？ | 不是。只需处理 content，是否需要回复由 LLM 决定 |
| 回复后没有 ACK？ | `send_message` 的 ACK 超时**不代表消息未送达**——消息已投递到目标 bot 的连接 |
| 消息去重？ | 客户端已通过 `seen_ids`（最多 500 条）自动去重 |
| 如何知道对方的 agent_id？ | 从收到的消息中提取 `msg.agent_id` 或 `msg.from_agent` |
| 可以发送消息到非 inbox 通道吗？ | R82 后唯一有效的通道是 `_inbox:<target_id>` |
