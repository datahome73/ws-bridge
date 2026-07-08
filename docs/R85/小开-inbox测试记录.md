# 小开 Inbox 通信协议学习记录

> **作者：** 小开（架构师）
> **日期：** 2026-07-08
> **参考：** docs/inbox-message-protocol.md v1.0

---

## 一、阅读体会

### 1.1 协议的核心思想

读完 `docs/inbox-message-protocol.md`，最深的体会是：**简洁就是力量。**

R82 之前，ws-bridge 有 4 种通道（lobby、ws:xxx、_admin、_inbox:xxx），bot 需要管理活跃频道切换、监听多个频道、区分广播 vs 收件箱。R82 一刀砍掉 3 个，只剩下一种——inbox。

这种做减法的思路和我参与过的 R82 技术方案设计一致：所有被实战验证没用的复杂性，直接删。

### 1.2 印象深刻的设计点

1. **「回复 = 发消息」**——回复不是特殊操作，就是普通的 `send_message(channel=f"_inbox:{sender_id}")`。这个统一模型让 bot 逻辑简单了：收到消息 → 提取 sender_id → 处理 → 发回。

2. **去中心化通知**——通知多个 bot 不用 @all，而是依次给每个 inbox 发消息。虽然多几行代码，但每一条消息都有明确的目标，不会出现「广播风暴」的问题。

3. **ACK 超时时消息可能已送达**——第 7 节 FAQ 说 ACK 超时不代表消息未送达，这个说明很实用，防止 bot 开发者误判连接状态。

### 1.3 协议文档的质量评价

| 维度 | 评价 |
|:-----|:-----|
| 清晰度 | ✅ 语言简洁，4 步流程一目了然 |
| 完整性 | ✅ 消息格式、处理流程、回复协议、多 bot 通知、Gateway 整合、FAQ 全覆盖 |
| 实用性 | ✅ 有可直接复制粘贴的代码示例，降低对接门槛 |
| 准确性 | ✅ 与 R82 实际代码行为一致 |

---

## 二、4 步通信流程的理解

协议文档第 3 节定义了 4 步流程：

### Step 1：确认 channel

```
收到消息 → channel 以 "_inbox:" 开头 → 这是给你的消息
```

**理解：** 这是第一道门。R82 后所有消息都是 inbox 消息，所以理论上这一步永远是 yes。但做这个检查是个好习惯——既防旧协议残留，也让代码意图清晰。

### Step 2：提取 sender_id

```
sender_id = msg.get("agent_id") or msg.get("from_agent")
```

**理解：** 这是最关键的步骤。`agent_id` 和 `from_agent` 是新老字段名的兼容写法。提取不到 sender_id 就无法回复——文档建议此时直接 return。

### Step 3：处理内容

```
用 LLM 处理 content（各 bot 自实现）
```

**理解：** 这一步是各 bot 的核心差异所在。架构师的任务是保证 Step 2→Step 4 的管道畅通，具体处理逻辑交给各 bot 自己。

### Step 4：回复

```
send_message(content="回复内容", channel=f"_inbox:{sender_id}")
```

**理解：** 回复就是发消息。没有特制的 `reply()` 方法，没有隐藏的频道上下文。统一接口降低了学习成本。

### 我的流程图理解

```
on_message(msg)
  │
  ├─ msg.channel.startswith("_inbox:") ?
  │    └─ ❌ → 忽略（旧协议残留）
  │
  ├─ sender_id = msg.agent_id or msg.from_agent
  │    └─ 空 → 无法回复，return
  │
  ├─ result = await llm_process(msg.content)
  │
  └─ await client.send_message(result, f"_inbox:{sender_id}")
```

---

## 三、回复格式规则总结

### 3.1 核心规则

| # | 规则 | 说明 |
|:-:|:-----|:------|
| 1 | **回复地址固定** | 目标 channel 永远是 `f"_inbox:{sender_id}"` |
| 2 | **内容格式不限** | 自然语言即可，无固定模板 |
| 3 | **回复不是特殊 API** | 用 `send_message()` 即可，无独立 `reply()` 方法 |
| 4 | **回复时机按场景定** | 任务必有 ACK + 完成通知；通知按需回复 |

### 3.2 不同场景的回复格式

**任务分配场景**（如本轮 R85 测试）：
```
① ACK: ✅ 收到 R85 学习记录任务，开始执行...
② 完成: ✅ 完成，已推 dev: <SHA>
```

**通知场景**：
```
可选回复或不回复。如需确认，简洁回复：
✅ 已收到通知
```

**询问场景**：
```
按 LLM 处理结果回复，无需固定格式
```

### 3.3 注意事项

1. **不依赖 ACK**——`send_message` 的 ACK 超时**不代表消息未送达**
2. **去重**——客户端用 `seen_ids` 自动去重
3. **限速**——多 bot 通知时，每发一条间隔 1s
4. **别发给自己**——server 拒绝向自己的 inbox 发消息

---

## 四、总结

inbox 协议的精髓可以用一句话概括：

> **所有消息都是 inbox 消息。回复就是给发送者的 inbox 再发一条消息。**

这个简单模型让 ws-bridge 的 bot 通信变成了一个纯函数调用：
- 输入：`{content, agent_id, channel}`
- 处理：`llm_process(content)`
- 输出：`send_message(result, f"_inbox:{sender_id}")`

没有状态、没有频道切换、没有广播路由。这就是 R82 做减法的成果。

---

*记录完毕。* ✅
