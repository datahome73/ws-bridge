# R87 技术方案 — `_inbox:server` 中继架构 🚉

> **版本：** v1.0
> **状态：** ✅ 终稿
> **作者：** 🏗️ 架构师（小开）
> **日期：** 2026-07-09
> **基于需求文档：** `docs/R87/R87-product-requirements.md` v1.2
> **涉及文件：** `server/handler.py` · `server/__main__.py` · `server/config.py`

---

## 目录

1. [改动总览](#1-改动总览)
2. [新增常量](#2-新增常量)
3. [核心中继函数 `_handle_server_relay()`](#3-核心中继函数-_handle_server_relay)
4. [入口集成](#4-入口集成)
5. [安全守卫](#5-安全守卫)
6. [兼容性分析](#6-兼容性分析)
7. [风险与回退](#7-风险与回退)

---

## 1. 改动总览

| # | 文件 | 位置 | 说明 | 行数 |
|:-:|:----|:-----|:-----|:----:|
| 1 | `server/config.py` | 模块级 L168 已有 `PIPELINE_PM_AGENT_ID` | **无需新增** — 直接复用现有常量 | 0 |
| 2 | `server/config.py` | 模块级（建议 L169 后） | 新增 `SERVER_INBOX_CHANNEL` 常量 | ~2 行 |
| 3 | `server/handler.py` | 模块级（建议 L54 附近，常量区） | 新增 `is_server_inbox()` 判断函数 | ~5 行 |
| 4 | `server/handler.py` | 模块级（建议放在 `handler()` 之前） | 新增 `_handle_server_relay()` 中继函数 | ~40 行 |
| 5 | `server/handler.py` | `handler()` L6165 | 入口集成：`msg_type == "message"` 分支新增拦截 | ~5 行 |
| 6 | `server/__main__.py` | `ws_handler()` L104 | 入口集成：同上 | ~5 行 |

**净增量：** ~60 行，3 文件改动。

---

## 2. 新增常量

### 2.1 `config.py` 现有常量（复用，无需新增）

```python
# 已存在 L168-169
PIPELINE_PM_AGENT_ID: str = os.environ.get("WS_PM_AGENT_ID", "")
```

✅ **直接复用 `config.PIPELINE_PM_AGENT_ID`** 作为 PM 的 agent_id，不新增重复常量。

### 2.2 `config.py` 新增

**插入位置：** 紧接 `PIPELINE_PM_AGENT_ID` 之后（L169 后）

```python
# ── R87: _inbox:server 中继通道 ────────────────────────────
SERVER_INBOX_CHANNEL: str = "_inbox:server"
"""Bot 回复中继通道。bot 将 ACK/完成回复发至此通道，由 server 筛选转发。"""
```

### 2.3 `handler.py` 新增判断函数

**插入位置：** 模块级常量区（建议放在 L54 附近 `_SILENT_PREFIXES` 之后）

```python
# ── R87: _inbox:server 中继通道 ──────────────────────────
SERVER_INBOX_CHANNEL = "_inbox:server"


def is_server_inbox(channel: str) -> bool:
    """判断 channel 是否为 server 中继通道。"""
    return channel == SERVER_INBOX_CHANNEL
```

---

## 3. 核心中继函数 `_handle_server_relay()`

### 3.1 位置

`server/handler.py` 模块级，建议放在 `handler()` 函数之前（L6139 之前），与 `handle_auth()`、`handle_register()` 等入口处理函数自然相邻。

### 3.2 函数签名

```python
async def _handle_server_relay(ws, agent_id: str, msg: dict) -> bool:
    """处理发往 _inbox:server 的消息（仅接受 bot 消息）。

    Args:
        ws: WebSocket 连接
        agent_id: 发送消息的 bot 的 agent_id（已认证）
        msg: 消息 dict（必须含 channel/content 字段）

    Returns:
        True  — 消息已由中继处理（调用方应 continue，不继续路由）
        False — 不是 _inbox:server 消息（调用方继续正常路由）
    """
```

### 3.3 完整实现

```python
# ── R87: _inbox:server 中继通道 ──────────────────────────
SERVER_INBOX_CHANNEL = "_inbox:server"


def is_server_inbox(channel: str) -> bool:
    return channel == SERVER_INBOX_CHANNEL


async def _handle_server_relay(ws, agent_id: str, msg: dict) -> bool:
    """R87: 处理发往 _inbox:server 的 bot 回复中继。"""
    channel = msg.get("channel", "")
    content = (msg.get("content") or "").strip()

    # 非中继消息 → 走正常路由
    if not is_server_inbox(channel):
        return False

    # ── 获取发送者信息 ──
    sender_name = _r72_users.get(agent_id, {}).get("name", agent_id[:12])
    pm_agent_id = config.PIPELINE_PM_AGENT_ID

    # ═══ 安全守卫: PM 误发 _inbox:server ═══
    if pm_agent_id and agent_id == pm_agent_id:
        await _send(ws, {
            "type": "error",
            "error": "_inbox:server 仅接受 bot 消息，PM 请直接发 bot 收件箱。",
        })
        logger.warning("[Relay] 拒绝: PM %s 试图发消息到 _inbox:server", agent_id[:12])
        return True

    # ═══ 规则 1: ACK ✅ → 转发 PM（进度通知）═══
    if content.startswith("ACK ✅"):
        if pm_agent_id:
            await _broadcast_to_channel(
                f"_inbox:{pm_agent_id}",
                {
                    "type": "broadcast",
                    "channel": f"_inbox:{pm_agent_id}",
                    "from_name": "系统(中继)",
                    "from_agent": "system",
                    "content": f"📬 {sender_name} 已接活:\n{content}",
                    "ts": time.time(),
                },
            )
        logger.info("[Relay] ACK: %s → PM", sender_name)
        return True

    # ═══ 规则 2: ✅ 完成 → 转发PM + 自动确认bot（同时触发）═══
    if content.startswith("✅ 完成"):
        # ⑤ 转发给 PM
        if pm_agent_id:
            await _broadcast_to_channel(
                f"_inbox:{pm_agent_id}",
                {
                    "type": "broadcast",
                    "channel": f"_inbox:{pm_agent_id}",
                    "from_name": "系统(中继)",
                    "from_agent": "system",
                    "content": f"✅ {sender_name} 任务完成:\n{content}",
                    "ts": time.time(),
                },
            )
        # ⑥ 自动确认给 bot（发到 bot 的 inbox，不走 _inbox:server）
        await _broadcast_to_channel(
            f"_inbox:{agent_id}",
            {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统(中继)",
                "from_agent": "system",
                "content": "✅ 确认，已收到你的完成通知。本轮任务完成。",
                "ts": time.time(),
            },
        )
        logger.info("[Relay] 完成: %s → PM + 自动确认", sender_name)
        return True

    # ═══ 规则 3: 其他内容 → 沉默 ═══
    logger.info("[Relay] 沉默: %s 内容=%s...", sender_name, content[:60])
    return True
```

### 3.4 三条转发规则

| 规则 | 前缀 | 触发行为 | 转发目标 |
|:----:|:-----|:---------|:---------|
| 1 | `ACK ✅` | 转发给 PM（进度通知） | `_inbox:<PM_id>` |
| 2 | `✅ 完成` | ⑤ 转发PM + ⑥ 自动确认bot（**同时触发**） | PM: `_inbox:<PM_id>` · Bot: `_inbox:<bot_id>` |
| 3 | 其他 | **沉默** — 不转发、不回复 | — |

### 3.5 Step ⑤+⑥ 同时触发策略

两条 `_broadcast_to_channel()` 调用**在同一个 async 函数内顺序执行**，语义上同时触发：

```
收到 ✅ 完成
  ├─ await _broadcast_to_channel("_inbox:<PM_id>", ...)    ← ⑤
  └─ await _broadcast_to_channel("_inbox:<bot_id>", ...)    ← ⑥
```

- **无锁竞争：** `_broadcast_to_channel` 只读 `_connections` 并追加 `ms.save_message()`，内部无共享状态修改冲突
- **无先后依赖：** ⑤ 和 ⑥ 独立，交换顺序不影响结果
- **失败隔离：** 每个 `_broadcast_to_channel` 内部有 try/except，一个失败不影响另一个

### 3.6 `_broadcast_to_channel` 复用说明

使用现有的 `_broadcast_to_channel(channel, payload)` 函数（`handler.py` L313）：

| 能力 | 说明 |
|:-----|:------|
| ✅ 在线推送 | 向 channel 内所有在线连接广播 |
| ✅ 离线持久化 | 通过 `ms.save_message()` 写入消息存储，离线后恢复可见 |
| ✅ 聊天日志 | `write_chat_log()` 写入日志 |
| ✅ 兼容性 | 已在 PM 通知场景中验证（L3144 `_broadcast_to_channel(f"_inbox:{pm_agent_id}", ...)`） |

---

## 4. 入口集成

### 4.1 设计原则

1. **在 `handle_broadcast` 之前拦截** — `_inbox:server` 消息不经过 `handle_broadcast` 的 inbox fast path
2. **在 B1 key 检查之后** — 确保只有已认证的 bot 才能发消息到 `_inbox:server`
3. **使用 `continue`** — 已处理的消息不继续路由

### 4.2 `handler()` — `server/handler.py` L6165-6166

#### 改造前

```python
            elif msg_type == "message" and agent_id:
                await handle_broadcast(ws, agent_id, msg)
```

#### 改造后

```python
            elif msg_type == "message" and agent_id:
                # ═══ R86 B1: key 活性检查（已存在的 R86 代码）═══
                _keys = persistence.get_api_keys()
                _rec = _keys.get(agent_id)
                if _rec and _rec.get("status") == "revoked":
                    await _send(ws, {"type": "error", "error": "API key revoked"})
                    continue
                # ═══════════════════════════════════════════════════

                # ═══ R87: _inbox:server 中继拦截 ═══
                if await _handle_server_relay(ws, agent_id, msg):
                    continue
                # ════════════════════════════════════════

                await handle_broadcast(ws, agent_id, msg)
```

### 4.3 `ws_handler()` — `server/__main__.py` L104-105

#### 改造前

```python
        elif msg_type == "message" and agent_id:
            await handle_broadcast(ws, agent_id, data)
```

#### 改造后

```python
        elif msg_type == "message" and agent_id:
            # ═══ R86 B1: key 活性检查（已存在的 R86 代码）═══
            from . import persistence as _persistence
            _keys = _persistence.get_api_keys()
            _rec = _keys.get(agent_id)
            if _rec and _rec.get("status") == "revoked":
                await ws.send_json({"type": "error", "error": "API key revoked"})
                continue
            # ════════════════════════════════════════════════════════

            # ═══ R87: _inbox:server 中继拦截 ═══
            from .handler import _handle_server_relay
            if await _handle_server_relay(ws, agent_id, data):
                continue
            # ════════════════════════════════════════════

            await handle_broadcast(ws, agent_id, data)
```

### 4.4 导入说明

| 文件 | 需要导入 | 方式 |
|:----|:---------|:-----|
| `handler.py` | 无需额外 import | `_handle_server_relay` 在同一文件 |
| `__main__.py` | `_handle_server_relay` | `from .handler import _handle_server_relay`（局部导入在 L13 处追加，或函数内导入） |

推荐在 `__main__.py` L13 处追加导入，与现有 `from .handler import handle_auth, handle_broadcast, handle_register, _connections` 并列：

```python
from .handler import handle_auth, handle_broadcast, handle_register, _connections, _handle_server_relay  # R87
```

---

## 5. 安全守卫

### 5.1 守卫矩阵

| # | 场景 | 检测 | 响应 | 连接是否中断 |
|:-:|:-----|:-----|:-----|:-----------:|
| ❶ | PM 误发消息到 `_inbox:server` | `agent_id == config.PIPELINE_PM_AGENT_ID` | 返回 error + 日志警告 | ❌ 不断 |
| ❷ | 未认证连接发 `_inbox:server` | 外层 `if agent_id` 条件不满足 → 不进此分支 | 自动落到 `else` 分支 | ❌ 不断 |
| ❸ | Bot 回复 Step 6 确认消息（无意义循环） | 内容不匹配 `ACK ✅` / `✅ 完成` → 规则 3 沉默 | 只写日志，不转发不回 | — |
| ❹ | `ACK✅`（无空格）→ 不触发转发 | `startswith("ACK ✅")` 不匹配 | 规则 3 沉默 | — |
| ❺ | `✅完成`（无空格）→ 不触发完成转发 | `startswith("✅ 完成")` 不匹配 | 规则 3 沉默 | — |

### 5.2 PM 守卫实现细节

```
_handle_server_relay 入口
  │
  ├─ is_server_inbox(channel)? → No → return False（正常路由）
  │
  ├─ agent_id == PM_AGENT_ID? → Yes → send error + return True（拒绝）
  │
  ├─ content.startswith("ACK ✅")? → Yes → 转发PM
  │
  ├─ content.startswith("✅ 完成")? → Yes → ⑤转发PM + ⑥自动确认
  │
  └─ else → 沉默（return True）
```

**关键设计：** PM 守卫**返回 True**（标记已处理），所以调用方会 **`continue`**，不继续路由。这意味着 PM 的违规消息不会被转发到任何地方，包括不会被 error 回显之外路由到大厅。

---

## 6. 兼容性分析

### 6.1 旧 bot 向后兼容

| 场景 | 旧行为 | R87 后行为 | 兼容性 |
|:-----|:-------|:-----------|:------:|
| 旧 bot 回复 `_inbox:<PM_id>` | 消息正常路由到 PM inbox | **不变** — `_inbox:<PM_id>` 不是 `_inbox:server`，`is_server_inbox()` 返回 False，走正常路由 | ✅ 完全兼容 |
| 旧 bot 不知 `_inbox:server` | N/A | 无影响，消息仍走原路径 | ✅ |
| 新旧 bot 混合部署 | — | 新 bot 用 `_inbox:server`，旧 bot 用 `_inbox:<PM_id>`，互不影响 | ✅ |

**关键：** `_handle_server_relay()` 只拦截 `channel == "_inbox:server"` 的消息。`_inbox:<PM_id>` 和其他任何通道都不受影响。

### 6.2 功能矩阵

| 检查项 | 预期 | 依据 |
|:-------|:-----|:------|
| 非 `_inbox:server` 消息不受影响 | ✅ | 函数入口 `is_server_inbox()` 返回 False → return False |
| PM 收到 ACK 转发通知 | ✅ | `_broadcast_to_channel("_inbox:<PM_id>", ...)` — 复用已在 R80 验证的路径 |
| Bot 收到 ✅ 完成自动确认 | ✅ | `_broadcast_to_channel("_inbox:<bot_id>", ...)` — 同上 |
| Bot 发非关键内容 → 沉默 | ✅ | 规则 3 不触发任何转发 |
| PM 误发 `_inbox:server` → 拒绝 | ✅ | 安全守卫：send error + return True |
| 多个 bot 同时发 → 独立处理 | ✅ | 每个 `_handle_server_relay` 调用独立，`_broadcast_to_channel` 内部互斥操作单次消息 |
| 未 auth 的连接无法发到 `_inbox:server` | ✅ | 外层 `msg_type == "message" and agent_id` 已过滤未认证连接 |

### 6.3 scope 边界

| 不改 | 原因 |
|:-----|:------|
| 客户端库 `ws_client.py` | 协议层无变动，bot 修改回复目标即可 |
| Web 端、Agent Card、管线状态机、workspace | 不相关模块 |
| 现有 `inbox-message-protocol.md` | 部署后由 ops 统一更新（不在此次编码范围） |
| `handle_broadcast()` 现有逻辑 | 不修改 |

---

## 7. 风险与回退

### 7.1 风险评估

| # | 风险 | 等级 | 缓解措施 |
|:-:|:-----|:----:|:---------|
| 1 | PM_AGENT_ID 为空（`WS_PM_AGENT_ID` 未设置） | 🟡 中 | `_handle_server_relay` 中检查 `pm_agent_id`，为空时跳过 PM 转发，仅做沉默/自动确认。日志 warning 提醒 |
| 2 | `_broadcast_to_channel` 双调用性能 | 🟢 低 | 两个连续 await 无锁争用，~微秒级操作 |
| 3 | PM 误发 `_inbox:server` 后 error 消息未送达 | 🟢 低 | `_send(ws, error)` 直接发回 sender 连接，无需路由 |
| 4 | Bot 收到 Step 6 确认后再次回复 | 🟢 低 | 回复内容大概率不匹配前缀，被规则 3 沉默 |

### 7.2 回退方案

1. 入口回退：移除 `handler()` + `ws_handler()` 中的 `if await _handle_server_relay(...): continue` 块
2. 函数回退：注释 `_handle_server_relay()` 函数体，保留空壳返回 False
3. 最简回退：`git revert <commit-sha>` + `git push origin dev`

---

## 附录：完整改动对照表

| 文件 | 行号（当前） | 操作 | 代码摘要 |
|:----|:-----------|:----|:---------|
| `server/config.py` | L169 之后 | ➕ 新增 1 行 | `SERVER_INBOX_CHANNEL = "_inbox:server"` |
| `server/handler.py` | L54 附近 | ➕ 新增 ~8 行 | `SERVER_INBOX_CHANNEL` + `is_server_inbox()` |
| `server/handler.py` | L6139 之前 | ➕ 新增 ~40 行 | `_handle_server_relay()` 完整实现 |
| `server/handler.py` | L6165-6166 | ➕ 插入 ~3 行 | `if await _handle_server_relay(ws, agent_id, msg): continue` |
| `server/__main__.py` | L13 | ➕ 追加导入 | `_handle_server_relay` |
| `server/__main__.py` | L104-105 | ➕ 插入 ~3 行 | 同上中继拦截 |

---

*本文档由 🏗️ 架构师（小开）编写，待 Step 3 💻 编码实现。*
