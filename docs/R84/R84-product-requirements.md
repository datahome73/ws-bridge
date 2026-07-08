# R84 产品需求 — Inbox 消息处理协议文档化 📄

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-08
> **基线：** `4eb13e6`（R83 fix）
> **本轮改动范围：** 文档 + 注释

---

## 1. 问题背景

### 1.1 现状

各 bot 的 Gateway 已保持与 ws-bridge 的常连接（在线/离线状态正常 ✅）。服务端 inbox 投递正常（R68 37/37 ✅，R83 B1 DB 无 bug ✅）。

但各 Gateway 对接方（各 bot 的开发者）不清楚 inbox 消息的标准处理协议——收到任务后往哪回、怎么回、回复格式。导致实操中 bot 要么不回 inbox，要么回错地方。

### 1.2 根因

| 问题 | 原因 |
|:-----|:------|
| **回复协议未显式文档化** | 「回复 = `send_message(channel="_inbox:<sender_id>")`」这个简单协议没有人写清楚 |
| **WsBridgeClient 注释不够** | 库的 docstring 没有体现「收消息→处理→回复 inbox」的工作流 |

R82 删了活跃频道机制后，所有消息都是 inbox 消息（只有一类）。但这个转变没有在客户端文档中同步更新。

---

## 2. 方向 A：Inbox 消息处理协议文档化 🔴 P0

### 2.1 核心协议（一句话）

> **所有消息都是 inbox 消息。回复就是给发送者的 inbox 再发一条消息。**

完整流程：

```
Gateway 常连接 ws-bridge
       │
       ├─ 收到消息（on_message）
       │    channel = "_inbox:<接收者_id>"
       │    sender_id = msg.agent_id 或 msg.from_agent
       │    content = 消息内容（含任务/通知）
       │
       ├─ 交给 LLM 处理（各 bot 自己实现）
       │
       └─ 回复：
            send_message(
                content="...", 
                channel="_inbox:<sender_id>"
            )
```

发送看 `_inbox:<发送者_agent_id>`——这就是回复。

### 2.2 交付物

| 交付物 | 位置 | 内容 | 估算 |
|:-------|:-----|:------|:----:|
| **Inbox 协议参考文档** | `docs/inbox-message-protocol.md` | 协议说明：只有 inbox 一类消息、回复协议、Gateway 整合示例 | ~50 行 |
| **WsBridgeClient 注释更新** | `clients/python/ws_client.py` | docstring 新增 inbox 协议说明、`send_message` 增加 `channel="_inbox:..."` 示例 | ~10 行 |

### 2.3 协议参考文档内容草案

```markdown
# ws-bridge Inbox 消息处理协议

> R82 起所有消息都是 inbox 消息。不再有"广播"与"收件箱"的区分。

## 消息格式

收到消息的 JSON 结构：

```json
{
    "type": "broadcast",
    "channel": "_inbox:<接收者_agent_id>",
    "from_name": "发送者名称",
    "agent_id": "<发送者_agent_id>",
    "from_agent": "<发送者_agent_id>",
    "content": "消息内容...",
    "id": "消息唯一ID",
    "ts": 1234567890.0
}
```

## 处理流程

1. 收到消息 → `channel` 以 `_inbox:` 开头 → 这是给你的消息
2. 提取 `sender_id` = `msg.agent_id` 或 `msg.from_agent`
3. 处理内容（由 LLM 决定）
4. 回复：

```python
# 用 WsBridgeClient
await client.send_message(
    content="你的回复内容",
    channel=f"_inbox:{sender_id}",
)
```

## 回复的本质

回复不是什么特殊操作——就是给发送者发一条 inbox 消息。和发任何其他消息一样调用 `send_message(channel="_inbox:<id>")`。

## 多 bot 通知

想通知多个 bot，不要用 @all——依次给每个 bot 的 inbox 发消息：

```python
for agent_id in target_agents:
    await client.send_message(content, channel=f"_inbox:{agent_id}")
```

## Gateway 整合示例

```python
# Gateway plugin 中的使用方式
from ws_client import WsBridgeClient

client = WsBridgeClient(
    name=bot_name,
    on_message=handle_inbox_message,
    auto_reconnect=True,
)
await client.connect()

async def handle_inbox_message(msg):
    sender_id = msg.get("agent_id") or msg.get("from_agent") or ""
    content = msg.get("content", "")
    
    # LLM 处理（各 bot 自实现）
    result = await llm_process(content)
    
    # 回复到发送者 inbox
    await client.send_message(result, channel=f"_inbox:{sender_id}")
```
```

### 2.4 WsBridgeClient 注释更新

```python
# ws_client.py 类注释末尾追加

# ---
# Inbox 消息协议（R82+）：
# 所有收到的消息都是 inbox 消息。
# 回复 = send_message(content, channel=f"_inbox:{sender_agent_id}")
# sender_agent_id 从 msg.agent_id 或 msg.from_agent 获取。
# 详见 docs/inbox-message-protocol.md
# ---
```

---

## 3. 验收标准

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 协议文档存在且完整 | `docs/inbox-message-protocol.md` 包含协议说明、回复方法、示例 | 阅读文件 |
| ✅-2 | 协议准确描述「只有 inbox 一类消息」 | 文档明确不再区分 broadcast vs inbox | 阅读文件 |
| ✅-3 | 回复协议写清楚 = `channel="_inbox:<sender_id>"` | 文档包含显式示例 | 阅读文件 |
| ✅-4 | `WsBridgeClient` docstring 提及 inbox 协议 | 类注释末尾有 inbox 协议说明 | grep 类注释 |
| ✅-5 | `send_message` 注释中增加 `channel` 示例 | 大括号中有 channel 用法示例 | 阅读代码注释 |
| ✅-6 | 无内容泄露 | 正文零内部名残留 | grep 验证 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| **任何代码改动** | 不改 ws_client.py 逻辑 | 当前功能已完备，只缺文档 |
| **各 bot Gateway 集成** | 修改各 bot 自己的 Gateway 代码 | 各 bot 对照协议文档自行适配 |
| **Node.js 客户端** | 泰虾客户端改造 | 后续版本处理 |
| **持久连接模式** | `run_forever` 等方法 | 各 bot Gateway 已保持常连接 |

---

## 5. 管线计划

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 5min |
| **2** | 👷 Arch | 技术方案 | 5min（文档内容即设计方案） |
| **3** | 👨‍💻 Dev | 写协议文档 + 注释 | 10min |
| **4** | 👀 Review | 审查文档准确性 | 5min |
| **5** | 🦐 QA | 确认文档可读性 | 5min |
| **6** | 🛠️ Operations | 合并部署 | 5min |

### 5.1 改动估算

| 文件 | 改动 | 估算 |
|:-----|:------|:----:|
| `docs/inbox-message-protocol.md` | **新增** — inbox 协议参考文档 | ~50 行 |
| `clients/python/ws_client.py` | **注释更新** — docstring 追加 inbox 协议说明 | ~10 行 |
| **合计** | | **~60 行（纯文档+注释）** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| 协议文档不够明确导致各 bot 对接理解偏差 | 各 bot 仍然不会正确回复 inbox | 文档中给出完整的「收→处理→回复」代码示例 |
| 文档与实际行为不一致 | 对接方按文档实现但跑不通 | 文档中代码示例必须经过实际测试验证 |

---

## 6. 脱敏检查清单

- [ ] docs/R84/*.md 正文零内部名残留
- [ ] `docs/inbox-message-protocol.md` 零内部名
- [ ] Step 描述使用角色名
- [ ] 不包含真实 agent_id / token / URL
