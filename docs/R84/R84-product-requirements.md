# R84 产品需求 — 客户端收件箱消息统一接入 🎯

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-08
> **基线：** `4eb13e6`（R83 fix — 代码库干净基础）
> **本轮改动范围：** `clients/python/ws_client.py`
> **参考：** pitfall #17（bot 不回 inbox 根因分析）、R83 B1 诊断结论

---

## 1. 问题背景

### 1.1 现状：bot 收 inbox 消息后无统一处理通路

当前 ws-bridge 管线中，服务端通过 `_send_inbox_task()` 向各 bot 的收件箱发送任务分配消息，服务端投递已正确（R68 37/37 ✅，R83 B1 确认 DB 无 bug）。

但各 bot 收到 inbox 消息后，缺少从 ws-bridge 客户端到 Gateway 的统一消息处理通路：

| 问题 | 表现 | 根因 |
|:-----|:------|:------|
| **消息无统一入口** | 各 bot 的 Gateway 自实现 ws 连接逻辑，没有统一用 `WsBridgeClient` 库 | `WsBridgeClient` 缺少 Gateway 可直接消费的接口设计 |
| **无法回复** | bot 完成任务后不知道往哪里回复 | 回复本质上就是发一条 `_inbox:<发送者_id>` 消息，但各对接方不清楚这个协议 |
| **常连接不稳定** | bot 时断时续，PM 发完任务后无人接收回复 | 各 bot 的连接管理各自为政，缺少统一的心跳/重连保障 |

### 1.2 根因分析

| 层面 | 问题 | 严重度 |
|:-----|:------|:------:|
| **客户端库** | `WsBridgeClient` 接口设计面向手动脚本使用（connect→send→disconnect），没有面向「持续连接、按消息驱动」的 Gateway 整合模式 | 🔴 |
| **回复协议未文档化** | 「回复=给发送者的 inbox 发消息」这个简单的协议没有被显式文档化和在库中便捷化 | 🟡 |
| **接入分散** | 各 bot 各自维护 ws 连接代码，没有统一接入 `WsBridgeClient` 再对接 Gateway | 🟡 |

### 1.3 为什么本轮修

R83 完成后，inbox 已是 ws-bridge 中唯一的消息通道。所有消息都是 inbox 消息——不再有「广播 vs inbox」之分。想通知多个 bot，就是往多个 inbox 各发一条，类似邮件的收件人列表，没有 @all。

但各 bot 的 Gateway 接入点分散，需要把 `WsBridgeClient` 改造成 Gateway 可以直接用的库：持续连接、消息驱动、稳定重连。为后续「Gateway 统一处理 inbox 消息」打好基础。

---

## 2. 方向 A：WsBridgeClient Gateway 接入改造 🔴 P0

### 2.1 设计思想

> **只有一类消息：inbox。** 不再区分 inbox vs broadcast——所有消息都是 inbox 消息。客户端收到消息后，通过回调抛给 Gateway 处理。

> **回复=发 inbox。** 给发送者回复，就是用 `send_message(channel="_inbox:<发送者_agent_id>")` 发一条消息。没有特殊的"回复"概念——就是发一条 inbox。

> **对接 Gateway，不搞 daemon。** 不引入外挂 daemon 进程。`WsBridgeClient` 作为 Gateway plugin 的一个组件使用，由 Gateway 管理生命周期。

### 2.2 改动点

#### A1 — 简化消息接收：只有 inbox

当前 `_handle_message()` 对所有 `broadcast`/`message` 类型走 `self.on_message(msg)`。保持不变。所有消息都是 inbox 消息，不需要特殊分类。

**不需要：** 区分 inbox vs broadcast。客户端收消息就抛 `on_message`，由 Gateway 决定怎么处理。

#### A2 — 简化回复：就是发 inbox 消息

**不需要**新增 `reply_to_inbox()` 方法。回复的协议很简单：

```python
# 收到 inbox 消息后，给发送者回复：
client.send_message("已完成，SHA: abc123", channel=f"_inbox:{sender_agent_id}")
```

其中 `sender_agent_id` 从收到的消息中提取：

```python
sender_id = msg.get("agent_id") or msg.get("from_agent") or ""
```

**改造点：** 在库的文档/注释中显式标明这个协议。不新增代码。

#### A3 — run_forever 持久模式

`WsBridgeClient` 新增 `run_forever()` 方法——连接后持续等待，断线自动重连，有消息就触发 `on_message`。这是 Gateway 集成需要的模式。

```python
async def run_forever(self) -> None:
    """持续连接模式。
    
    连接后保持在线，断线自动重连，收到消息通过 on_message 回调抛出。
    调用 disconnect() 停止。
    """
    if not self._connected:
        ok = await self.connect()
        if not ok:
            return
    
    logger.info("run_forever: started (agent_id=%s)", self._agent_id)
    
    # connect() 已启动 _reader_loop 后台任务
    # 只是等待停止信号
    await self._stop.wait()
    logger.info("run_forever: stopped")
```

`_reader_loop` 已具备自动重连能力（`_reconnect_with_backoff`），无需改动。

#### A4 — Gateway 整合示例

在库的 README 或注释中给出 Gateway 整合的模式：

```python
# Gateway plugin 中的使用方式
from ws_client import WsBridgeClient

class MyGatewayPlugin:
    async def start(self):
        self.client = WsBridgeClient(
            name=self.config.bot_name,
            on_message=self.handle_inbox_message,
            auto_reconnect=True,
        )
        await self.client.run_forever()
    
    async def handle_inbox_message(self, msg: dict):
        """所有消息都是 inbox 消息。由 Gateway 决定处理逻辑。"""
        channel = msg.get("channel", "")
        content = msg.get("content", "")
        sender = msg.get("from_name", "?")
        sender_id = msg.get("agent_id") or msg.get("from_agent") or ""
        
        # 1. 确认收到（回一个 inbox 消息）
        await self.client.send_message(
            f"✅ 收到，开始处理...",
            channel=f"_inbox:{sender_id}",
        )
        
        # 2. 交给 LLM 处理
        # ...
        
        # 3. 完成后回复
        await self.client.send_message(
            f"✅ 完成，已推 dev: abc123",
            channel=f"_inbox:{sender_id}",
        )
```

**关键点：**
- `on_message` 收到所有消息（因为只有 inbox 一类）
- 回复就是用 `send_message` 发到 `_inbox:<sender_id>`
- Gateway 负责解析消息内容（LLM 做），库不负责解析
- 库只做：连接、收消息、发消息、重连

### 2.3 改动清单

| 文件 | 改动 | 估算 |
|:-----|:------|:-----:|
| `clients/python/ws_client.py` | 新增 `run_forever()` 方法 | ~20 行 |
| `clients/python/ws_client.py` | README/docstring 显式标注 inbox 回复协议 | ~10 行注释 |
| **合计** | | **~30 行净增** |

---

## 3. 验收标准

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | `run_forever()` 连接并保持在线 | 调用后 client 持续在线，收到消息触发 `on_message` | 运行测试：`run_forever()` → 发 inbox 消息 → 验证 `on_message` 被调用 |
| ✅-2 | `run_forever()` 断线自动重连 | 断开 WS 后自动重连，重连后继续收消息 | 运行中 kill ws 连接一次，验证重连后 inbox 消息照常接收 |
| ✅-3 | `send_message(channel="_inbox:<id>")` 送达 | 消息正确投递到目标 inbox | 两测试 agent：A 发 `_inbox:B` → B 的 `on_message` 收到 |
| ✅-4 | 向后兼容 | 现有 `connect/send_message/disconnect` 接口不变 | 现有测试脚本不修改也能正常运行 |
| ✅-5 | 回复协议文档化 | README 或注释中写明「回复=发 `_inbox:<sender_id>`」协议 | 检查代码注释 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| **Node.js 客户端改造** | 泰虾 Node.js 客户端收件箱识别 | 当前无 Node.js 客户端接入，后续版本处理 |
| **各 bot Gateway 集成** | 修改各 bot 自己的 Gateway 配置/代码 | 各 bot 的 Gateway 归各自管理，R84 只产出库 |
| **任务消息解析工具** | 程序化解析 inbox 任务内容 | 由各 bot 的 LLM 处理，不需客户端层解析 |
| **inbox daemon** | 独立 daemon 进程 | 应通过 Gateway 统一接入，不走外挂 daemon |
| **持久化 inbox 状态跟踪** | 跟踪哪些任务已完成/待处理 | 属于 Gateway 统一消息处理的子能力 |

---

## 5. 管线计划

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 10min |
| **3** | 👨‍💻 Dev | 编码实现 | 15min |
| **4** | 👀 Review | 代码审查 | 10min |
| **5** | 🦐 QA | 测试报告 | 15min |
| **6** | 🛠️ Operations | 合并部署 | 10min |

### 5.1 改动估算

| 文件 | 改动 | 估算 |
|:-----|:------|:----:|
| `clients/python/ws_client.py` | 新增 `run_forever()` + 注释 | ~30 行净增 |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| `run_forever()` 阻塞主线程 | Gateway 启动后卡住 | 使用 `asyncio.create_task` 或单独线程启动，不阻塞 |
| 自动重连导致消息重复 | 重连后离线消息补推导致重复 | 已有 `seen_ids` 去重机制，无需改动 |

---

## 6. 脱敏检查清单

- [ ] docs/R84/*.md 正文零内部名残留
- [ ] frontmatter 保留机器解析用名（✅ 合法）
- [ ] Step 描述使用角色名（PM / arch / dev / review / QA / operations）
- [ ] 不包含真实 agent_id / token / URL
