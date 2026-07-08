# R84 产品需求 — 客户端收件箱消息响应 🎯

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-08
> **基线：** `4eb13e6`（R83 fix — 代码库干净基础）
> **本轮改动范围：** `clients/python/ws_client.py`、`scripts/`、新增 inbox daemon 模板
> **参考：** TODO R36-C（待分配）、pitfall #17（bot 不回 inbox 根因分析）、R83 B1 诊断结论

---

## 1. 问题背景

### 1.1 现状：各 bot 收到 inbox 任务但无标准响应机制

当前 ws-bridge 管线中，PM（小谷）通过 `_send_inbox_task()` 向各 bot 的收件箱发送任务分配消息。服务端已验证正确投递（R68 37/37 全绿 ✅），DB 存储正常（R83 B1 诊断：SQL LIKE 正确、代码无 bug）。

但各 bot 收到 inbox 任务后存在三个问题：

| 问题 | 表现 | 根因 |
|:-----|:------|:------|
| **静默忽略** | 任务送达但 bot 无响应，PM 无法确认 bot 是否已收到 | `WsBridgeClient` 的 `on_message` 回调不区分 inbox 消息与普通广播，bot 没有 inbox 感知 |
| **无法回复** | bot 完成任务后不知道往哪里回复 | inbox 消息的 `channel` 包含目标 agent_id，但 bot 没有标准化的「回复到发送者收件箱」机制 |
| **无常驻监听** | PM 发完任务就断开 WS，bot 几秒后回复无人接收（pitfall #17） | 各 bot 的连接模式是「临时连接→发消息→断开」，缺少持久 inbox 监听 |

### 1.2 根因分析

| 层面 | 问题 | 严重度 |
|:-----|:------|:------:|
| **客户端库** | `WsBridgeClient` 的 `on_message` 回调是通用接口，不区分 inbox vs 广播，不解构 inbox 消息中的 sender/任务内容 | 🔴 |
| **回复路径** | 收到 inbox 消息后，bot 不知道该往哪回复。正确路径是 `_inbox:<发送者_agent_id>`，但当前 `send_message()` 方法没有「回复到来源 inbox」的便捷函数 | 🔴 |
| **持久监听** | 无标准 inbox daemon 模板。各 bot 各自实现连接逻辑，没有统一的「持续连接→监听 inbox→处理任务→回复」工作流 | 🟡 |
| **任务识别** | 任务消息的 content 是纯文本格式（前置 `📥 任务分配 — ...`），bot 的 LLM 需要理解这是任务指令并执行，缺乏结构化提示 | 🟢 |

### 1.3 为什么本轮修

R83 完成了 Web 端 inbox 改造（23/23 ALL GREEN），服务端 inbox 通道已完善。但 R77-R83 多轮管线实战反复暴露同一个问题：**bot 能收到 inbox 消息，但不一定能正确响应和回复**。这是拖慢管线效率的核心瓶颈——PM 发任务后只能靠 `git ls-remote` 猜测 bot 是否在干，无法获得直接确认。

此外，项目负责人明确指出 inbox 问题应在 Gateway 层面解决。R84 以客户端库增强为主，为 Gateway 统一消息处理奠定基础——让 `WsBridgeClient` 成为「inbox 感知」的智能客户端，供各 bot 的 Gateway 直接使用。

---

## 2. 功能需求

### 设计原则

> **客户端库先行，Gateway 统一处理预留接口。** R84 专注增强 `WsBridgeClient` 成为 inbox-aware 客户端库，加入 inbox 消息识别、回复、持久监听能力。不引入外挂 daemon，而是让各 bot 的 Gateway 能直接用增强后的客户端库处理 inbox 消息。R84 产出的 inbox Daemon 模板作为参考实现，非强制部署。

> **向后兼容。** 所有增强不改变现有 `on_message` / `send_message` 签名。新增功能通过新方法/新回调/新接口提供，不影响已有代码。

---

### 方向 A（核心）：WsBridgeClient 收件箱感知能力 📥 🔴 P0

增强 `WsBridgeClient` 使其能识别 inbox 消息并提供标准化回复机制。

#### A1 — 收件箱消息识别

**位置：** `clients/python/ws_client.py` — `_handle_message()` 方法

当前 `_handle_message()` 对所有 `broadcast`/`message` 类型消息统一走 `self.on_message(msg)`。需要新增 inbox 消息的感知：

```python
# 当前：全量消息走 on_message
if msg_type in ("broadcast", "message"):
    # ...去重 + 自过滤...
    self.on_message(msg)
    return

# → 改造后：区分 inbox 消息与普通广播
_INBOX_PREFIX = "_inbox:"

if msg_type in ("broadcast", "message"):
    channel = msg.get("channel", "")
    sender_id = msg.get("agent_id") or msg.get("from_agent") or ""
    
    # 是 inbox 消息
    if channel.startswith(_INBOX_PREFIX):
        # 提取收件箱 owner
        inbox_owner = channel[len(_INBOX_PREFIX):]
        # 过滤自己的 self-message
        if sender_id == self._agent_id:
            return
        # 调用 inbox 专用回调
        self.on_inbox_message(msg)
        return
    
    # 普通广播消息（原有逻辑不变）
    # ...去重 + 自过滤...
    self.on_message(msg)
    return
```

**新增回调：** `on_inbox_message(msg)` — 默认实现为调用 `on_message(msg)` 保持向后兼容，但 bot 可覆盖此回调专门处理 inbox 消息。

#### A2 — 标准化回复功能

**位置：** `clients/python/ws_client.py` — 新增方法

当前 `send_message()` 发送到 lobby 或指定 channel。需要新增「回复到 inbox」的方法：

```python
async def reply_to_inbox(self, msg: dict, content: str) -> str:
    """Reply to the sender of an inbox message.
    
    Extracts the sender's agent_id from the inbox message and
    sends the reply to ``_inbox:<sender_agent_id>``.
    
    Returns the message ID on success, or ``""`` on failure.
    """
    # Extract sender info from the original inbox message
    sender_id = msg.get("agent_id") or msg.get("from_agent") or ""
    sender_name = msg.get("from_name") or sender_id[:12]
    
    if not sender_id:
        logger.warning("reply_to_inbox: no sender agent_id in message")
        return ""
    
    # Route reply to sender's inbox
    inbox_ch = f"_inbox:{sender_id}"
    reply_msg_id = str(uuid.uuid4())
    
    payload = {
        "type": "message",
        "channel": inbox_ch,
        "content": content,
        "from_name": self.name,
        "agent_id": self._agent_id or "",
        "id": reply_msg_id,
        "ts": time.time(),
    }
    
    # Register pending ACK
    event = asyncio.Event()
    self._pending_acks[reply_msg_id] = event
    
    async with self._ws_lock:
        if not self._ws or not self._authed:
            self._pending_acks.pop(reply_msg_id, None)
            return ""
        try:
            await self._ws.send(json.dumps(payload))
            logger.info(">> [inbox-reply → %s] %s (id=%s)", 
                        sender_name, content[:80], reply_msg_id[:8])
        except Exception as exc:
            logger.error("reply_to_inbox send error: %s", exc)
            self._pending_acks.pop(reply_msg_id, None)
            return ""
    
    # Wait for ACK
    try:
        await asyncio.wait_for(event.wait(), timeout=ACK_TIMEOUT)
        self._pending_acks.pop(reply_msg_id, None)
        return reply_msg_id
    except asyncio.TimeoutError:
        logger.warning("No ACK for inbox reply (id=%s)", reply_msg_id[:8])
        self._pending_acks.pop(reply_msg_id, None)
        return ""
```

**关键特征：**
- 从原 inbox 消息中提取 `agent_id`/`from_agent` 作为目标
- 自动构建 `_inbox:<sender_id>` 目标频道
- 复用现有 ACK 等待机制
- 日志区分普通消息与 inbox 回复

#### A3 — 持久化任务监听模式

**位置：** `clients/python/ws_client.py` — 新增 `run_forever()` 方法

当前 `WsBridgeClient` 的使用模式是「connect → send → disconnect」。需要支持持久化监听模式，让 bot 持续连接到 WS，自动处理 inbox 消息：

```python
async def run_forever(self) -> None:
    """Run the client persistently, processing inbox messages.
    
    The client stays connected with auto-reconnect, and calls
    ``on_inbox_message()`` for each inbox message received.
    
    This is the recommended mode for bots that need to respond
    to inbox task assignments.
    
    Call ``disconnect()`` to stop.
    """
    if not self._connected:
        ok = await self.connect()
        if not ok:
            logger.error("run_forever: connect failed")
            return
    
    logger.info("run_forever: started (agent_id=%s)", self._agent_id)
    
    # The reader loop is already running from connect()
    # Just wait until stop is set
    await self._stop.wait()
    logger.info("run_forever: stopped")
```

**配合使用模式：**

```python
# Bot 的主循环
client = WsBridgeClient(name="小谷", on_inbox_message=my_handler)
await client.run_forever()  # 持续连接，自动处理 inbox 消息

# 哪里调用 disconnect()
# await client.disconnect()
```

**注意：** `run_forever()` 依赖 `connect()` 启动的 `_reader_loop` 后台任务。`_reader_loop` 已具备自动重连能力（通过 `_reconnect_with_backoff`）。新增 `on_inbox_message` 回调后，bot 只需实现此回调即可处理所有 inbox 消息。

#### A4 — 任务消息解析工具函数

**位置：** `clients/python/ws_client.py` — 新增静态工具函数

任务消息的 content 有固定格式（`📥 任务分配 — R{N} Step「{title}」\n━━━\n...`）。提供工具函数帮 bot 解析关键信息：

```python
@staticmethod
def parse_inbox_task(msg: dict) -> dict:
    """Parse an inbox task assignment message.
    
    Returns a dict with:
      - round_name (str): e.g. "R84"
      - step_name (str): e.g. "step3"
      - step_title (str): e.g. "编码实现"
      - requirements_url (str or None)
      - work_plan_url (str or None)
      - sender_name (str)
      - sender_id (str)
      - full_content (str): original message content
    """
    content = msg.get("content", "")
    sender_name = msg.get("from_name", "?")
    sender_id = msg.get("agent_id") or msg.get("from_agent") or ""
    channel = msg.get("channel", "")
    
    result = {
        "sender_name": sender_name,
        "sender_id": sender_id,
        "full_content": content,
        "round_name": "",
        "step_name": "",
        "step_title": "",
        "requirements_url": "",
        "work_plan_url": "",
    }
    
    # Extract round: "📥 任务分配 — R{数字} Step..."
    import re
    m = re.search(r'R(\d+)', content)
    if m:
        result["round_name"] = f"R{m.group(1)}"
    
    # Extract step: "Step「...」" 
    m = re.search(r'Step「(.+?)」', content)
    if m:
        result["step_title"] = m.group(1)
    
    # Extract URLs
    for line in content.split('\n'):
        if '需求' in line and 'http' in line:
            m = re.search(r'https?://\S+', line)
            if m:
                result["requirements_url"] = m.group(0)
        if 'WORK_PLAN' in line and 'http' in line:
            m = re.search(r'https?://\S+', line)
            if m:
                result["work_plan_url"] = m.group(0)
    
    return result
```

---

### 方向 B（辅助）：Inbox Daemon 参考模板 🔷 🟡 P1

提供一个可运行的 Python inbox daemon 脚本，作为各 bot 实现持久 inbox 监听的参考实现。

#### B1 — 标准 inbox daemon 模板

**位置：** `scripts/inbox-daemon-template.py`

```python
"""
ws-bridge Inbox Daemon — 参考实现

用途：持续连接 WS Bridge，监听收件箱，处理任务分配消息。
各 bot 可复制此模板并实现自己的 ``on_inbox_message()`` 函数。

使用方式：
  1. 确保 ``~/.ws-bridge/{bot_name}.json`` 已存在（已 register）
  2. 修改下方的 BOT_NAME
  3. uv run python3 inbox-daemon-template.py
"""

import asyncio
import json
import logging
import os
import sys

# 根据 bot 类型调整
BOT_NAME = os.environ.get("WS_BRIDGE_BOT_NAME", "小谷")
WS_URL = os.environ.get("WS_BRIDGE_URL", "wss://wsim.datahome73.cloud/ws")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("inbox-daemon")


# ── Bot 需要实现的逻辑 ──────────────────────────────────────────

async def handle_inbox_task(parsed: dict, client) -> None:
    """收到收件箱任务后如何处理。"""
    logger.info("📥 收到收件箱任务：%s %s", 
                parsed.get("round_name"), parsed.get("step_title"))
    
    # Step 1: 确认收到
    ack_msg = f"✅ 收到 {parsed['round_name']} {parsed.get('step_title', '任务')}，开始处理..."
    await client.reply_to_inbox(parsed.get("_raw_msg", {}), ack_msg)
    
    # Step 2: 执行实际工作（各 bot 实现）
    # ...
    
    # Step 3: 完成汇报
    # result_msg = f"✅ 完成 {parsed['round_name']} {parsed.get('step_title')}，已推 dev"
    # await client.reply_to_inbox(parsed.get("_raw_msg", {}), result_msg)


# ── Inbox 消息处理 ──────────────────────────────────────────────

def make_on_inbox(client):
    """创建 on_inbox_message 回调"""
    async def on_inbox_message(msg):
        parsed = WsBridgeClient.parse_inbox_task(msg)
        parsed["_raw_msg"] = msg
        
        if not parsed.get("round_name") or not parsed.get("step_title"):
            logger.info("📩 收件箱消息（非任务）: %s", msg.get("content", "")[:120])
            return
        
        asyncio.create_task(handle_inbox_task(parsed, client))
    
    return on_inbox_message


# ── 启动 ──────────────────────────────────────────────────────

async def main():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "clients", "python"))
    from ws_client import WsBridgeClient
    
    client = WsBridgeClient(
        name=BOT_NAME,
        ws_url=WS_URL,
        auto_reconnect=True,
    )
    
    client.on_inbox_message = make_on_inbox(client)
    
    logger.info("🚀 Inbox daemon 启动（bot=%s url=%s）", BOT_NAME, WS_URL)
    
    try:
        await client.run_forever()
    except asyncio.CancelledError:
        pass
    finally:
        await client.disconnect()
        logger.info("👋 Inbox daemon 退出")


if __name__ == "__main__":
    asyncio.run(main())
```

#### B2 — 任务消息格式标准化

**位置：** `server/handler.py` — `_send_inbox_task()` 中的 message 内容

当前 inbox 任务消息的内容格式为自由文本，建议增加结构化的元数据标记，方便客户端程序化解析：

```python
# 当前格式（纯文本）
inbox_msg = f"""📥 任务分配 — {round_name} Step「{_step_title}」
━━━━━━━━━━━━━━━━━━━━━━━━━━━
{_prev_section}

📄 参考资料:
  📄 需求：{req_url}
  📋 WORK_PLAN：{plan_url}

🎯 你的任务: 请按技术方案完成 {next_step}
━━━━━━━━━━━━━━━━━━━━━━━━━━━
完成后: git push dev → !step_complete {next_step} --output <sha>"""

# 建议增加的元数据区块（机器可读，bot 可忽略）
inbox_msg = f"""📥 任务分配 — {round_name} Step「{_step_title}」
━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 ROUND: {round_name}
📋 STEP: {next_step}
📋 TITLE: {_step_title}
📋 REQ_URL: {req_url}
📋 PLAN_URL: {plan_url}
📋 SENDER_INBOX: _inbox:{pm_agent_id}
━━━━━━━━━━━━━━━━━━━━━━━━━━━
{_prev_section}

📄 参考资料:
  📄 需求：{req_url}
  📋 WORK_PLAN：{plan_url}

🎯 你的任务: 请按技术方案完成 {next_step}
━━━━━━━━━━━━━━━━━━━━━━━━━━━
完成后: git push dev → !step_complete {next_step} --output <sha>
完成后请回复 _inbox:{pm_agent_id} 告知 SHA。"""
```

**改动量：** 在 `_send_inbox_task()` 中新增元数据区块，约 +5 行。

---

### 方向 C（兼容）：Node.js 客户端收件箱感知 🟢 P2

当前 Node.js 客户端（`ws-bridge-client.js`，用于泰虾）使用旧认证（`app_id + agent_id`），尚未迁移到 R72 api_key 认证。暂不改变认证方式，仅增加 inbox 消息的响应能力。

#### C1 — Node.js inbox 消息识别

**位置：** `clients/node/ws-bridge-client.js` — `processBroadcast()` 函数

在 `processBroadcast()` 中，当前所有广播/消息统一 `console.log` 输出。新增 inbox 消息识别：

```javascript
// 在 processBroadcast() 开头新增
const channel = msg.channel || "";
const fromAgent = msg.from || msg.from_agent || "";
const fromName = msg.from_name || (fromAgent ? fromAgent.slice(0, 20) : "unknown");

// 识别 inbox 消息
if (channel.startsWith("_inbox:")) {
  const inboxOwner = channel.slice("_inbox:".length);
  if (fromAgent === CONFIG.agentId) return; // 自过滤
  
  log(`📥 [INBOX] from=${fromName} content=${(msg.content || "").slice(0, 200)}`);
  
  // 回复到发送者的 inbox
  const inboxMeta = JSON.stringify({
    type: "inbox",
    sender_id: fromAgent,
    sender_name: fromName,
    inbox_owner: inboxOwner,
  });
  const b64 = Buffer.from(msg.content || "", "utf-8").toString("base64");
  console.log(`[MSG]system|system|${b64}|${inboxMeta}`);
  return;
}
```

---

## 3. 验收标准

### 🎯 3.1 方向 A — WsBridgeClient 收件箱感知

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-A1 | `on_inbox_message` 回调存在且可覆盖 | 设置自定义回调后，inbox 消息触发该回调而非 `on_message` | 编写测试脚本：发 inbox 消息给测试 agent，验证自定义回调被调用 |
| ✅-A2 | 普通广播消息不走 `on_inbox_message` | 非 inbox 频道消息仍只走 `on_message` | 发 lobby 广播消息，验证 `on_inbox_message` 不触发 |
| ✅-A3 | `reply_to_inbox()` 正确路由到发送者 inbox | 回复内容送达发送者的 `_inbox:<sender_id>` 频道 | 用两个测试 agent：A 发 inbox 给 B → B 调用 reply_to_inbox → A 的 inbox 收到回复 |
| ✅-A4 | `reply_to_inbox()` ACK 超时回退 | 无 ACK 时返回 `""` 而非抛出异常 | 断开 WS 后调用，验证优雅降级 |
| ✅-A5 | `parse_inbox_task()` 正确解析任务消息 | round_name/step_title/URLs 均正确提取 | 用真实 `_send_inbox_task` 产出的消息调用解析函数，验证输出字段 |
| ✅-A6 | `run_forever()` 持久模式存活 | 连接后持续在线，收到消息触发回调，断线自动重连 | 运行测试脚本 60s，期间 kill WS 连接 1 次，验证自动重连且消息不丢 |
| ✅-A7 | 向后兼容：不设 `on_inbox_message` 时 inbox 消息走 `on_message` | 不覆盖 `on_inbox_message` 时，inbox 消息仍通过 `on_message` 回调 | 用旧版 `on_message` 回调运行，验证 inbox 消息照常接收 |

### 🎯 3.2 方向 B — Inbox Daemon 参考模板

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-B1 | daemon 模板可独立运行 | `uv run python3 scripts/inbox-daemon-template.py` 正常连接 WS | 从 `ws-bridge/` 目录运行脚本，验证连接成功且开始监听 |
| ✅-B2 | daemon 收到 inbox 任务后回复 ACK | 向 daemon 的 inbox 发任务消息，daemon 自动回复「✅ 收到」 | 用另一个 agent 给 daemon 的 agent_id 发 inbox 消息，观察回复 |
| ✅-B3 | daemon 断线自动重连 | 断开 WS 后 daemon 自动重连并继续监听 | 重启 ws-bridge 服务，验证 daemon 重连后 inbox 消息正常接收 |

### 🎯 3.3 方向 C — Node.js inbox 识别

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-C1 | Node.js 客户端输出 `[INBOX]` 标记 | inbox 消息在 log 中以 `📥 [INBOX]` 前缀输出 | 用测试 agent 给 Node.js 客户端发 inbox 消息，验证 log 格式 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| **Gateway 统一消息处理** | 各 bot 的 Gateway（Hermes Agent Gateway plugin）层面统一处理 inbox 消息 | 项目负责人指定的长期方向，R84 先完善客户端库能力，Gateway 集成留待后续 |
| **Node.js 客户端迁移到 R72 认证** | 泰虾的 Node.js 客户端仍用旧 `app_id + agent_id` 认证 | 架构升级需要协调泰虾侧改动，非本轮目标 |
| **`_send_inbox_task` 消息格式大幅重构** | 改变当前纯文本格式为 JSON 结构体 | 当前格式对 LLM 友好，增加机器元数据块即可 |
| **持久化 inbox 状态跟踪** | 跟踪哪些 inbox 任务已完成/待处理 | 属于 Gateway 统一消息处理的子能力，留待后续 |
| **各 bot Gateway 集成** | 修改各 bot 自己的 Gateway 配置/代码来使用增强的客户端库 | 各 bot 的 Gateway 归各自管理，R84 只产出库和模板 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 15min |
| **3** | 👨‍💻 Dev | 编码实现 | 30min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 20min |
| **6** | 🛠️ Operations | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `clients/python/ws_client.py` | **新增** — on_inbox_message/reply_to_inbox/parse_inbox_task/run_forever | ~120 行 |
| `server/handler.py` | **微调** — `_send_inbox_task()` 消息增加元数据区块 | ~5 行 |
| `scripts/inbox-daemon-template.py` | **新增** — inbox daemon 参考模板 | ~100 行 |
| `clients/node/ws-bridge-client.js` | **微调** — processBroadcast 增加 inbox 识别 | ~15 行 |
| **合计** | | **~240 行净增** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| `on_inbox_message` 默认回退到 `on_message` 导致双重回调 | 用户设了 `on_message` 又设了 `on_inbox_message` 时 inbox 消息触发两次 | 默认实现中，`on_inbox_message` 不调用 `on_message`——回调互斥 |
| `reply_to_inbox` 发送者的 agent_id 在消息中不存在 | 无法回复 | 降级为 `send_message()` 到 `_admin` 频道并 log warning |
| 泰虾 Node.js 客户端非 R72 认证，`[INBOX]` 标记可能不被上层解析 | 节点端识别但无实际响应 | 标记不影响现有功能，泰虾可后续升级 |

---

## 6. 脱敏检查清单

- [ ] docs/R84/*.md 零内部名残留
- [ ] `grep -nE '内部名模式' docs/R84/*.md` 零匹配
- [ ] 使用通用角色名（PM / arch / dev / review / QA / operations）
- [ ] 不包含真实 agent_id / token / URL
