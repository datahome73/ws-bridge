# R84 技术方案 — Inbox 消息处理协议文档化 📄

> **版本：** v1.0 | **架构师：** 👷 Arch | **日期：** 2026-07-08
> **基于：** docs/R84/R84-product-requirements.md v1.0 ✅
> **改动范围：** `docs/inbox-message-protocol.md`（新增）+ `clients/python/ws_client.py`（注释）
> **不动：** `server/`、`clients/node/`、其他任何 .py 逻辑

---

## 1. 工作量评估

| 交付物 | 类型 | 估算 |
|:-------|:-----|:----:|
| `docs/inbox-message-protocol.md` | 新增文档 | ~60 行 |
| `clients/python/ws_client.py` 注释 | 追加 docstring | ~10 行 |
| `docs/R84/R84-tech-plan.md` | 本方案文件 | 本文件 |
| **合计** | | **~70 行（纯文字）** |

零代码逻辑改动。纯文档+注释。

---

## 2. 协议文档内容确认

协议文档 `docs/inbox-message-protocol.md` 应包含以下 6 节：

### 2.1 协议概述
> R82 起所有消息都是 inbox 消息。不再有「广播」与「收件箱」的区分。

### 2.2 消息结构
inbox 消息 JSON 字段说明：`type`、`channel`（格式 `_inbox:<receiver_id>`）、`from_name`、`agent_id`/`from_agent`、`content`、`id`、`ts`。

### 2.3 处理流程
1. 收到消息 → `channel` 以 `_inbox:` 开头 → 这是给你的消息
2. 提取 `sender_id` = `msg.agent_id` 或 `msg.from_agent`
3. LLM 处理内容
4. 回复 → `send_message(content=result, channel=f"_inbox:{sender_id}")`

### 2.4 回复协议
回复不是什么特殊操作——就是给发送者发一条 inbox 消息。

### 2.5 多 bot 通知
```python
for agent_id in target_agents:
    await client.send_message(content, channel=f"_inbox:{agent_id}")
```

### 2.6 Gateway 整合示例
完整的 `WsBridgeClient` 使用代码示例。

---

## 3. WsBridgeClient 注释确认

追加在现有 docstring 底部（L13 之后）：

```
Inbox 消息协议（R82+）：
所有收到的消息都是 inbox 消息。
回复 = send_message(content, channel=f"_inbox:{sender_agent_id}")
sender_agent_id 从 msg.agent_id 或 msg.from_agent 获取。
详见 docs/inbox-message-protocol.md
```

---

## 4. 脱敏检查

- [x] 正文使用角色名（架构师/开发工程师/审查工程师）
- [x] frontmatter 区保留 bot 名（机器解析需要）
- [x] 不含真实 agent_id/token/URL
- [x] 协议示例中使用填空式变量名（如 `bot_name`、`sender_id`）

---

## 5. 风险

| 风险 | 缓解 |
|:-----|:------|
| 文档与实际行为不一致 | 技术方案审阅时确认每一步与实际代码一致 |
| 各 bot 按文档实现出错 | 文档给出完整可复制粘贴的代码示例 |
