# R102 — Server 转发体系技术方案 🚉

> **版本**: v1.0
> **作者**: 小开 (Architect)
> **状态**: 📝 草稿
> **目标版本**: v2.71
> **前置条件**: R101 (WSS/Web 解耦) 已部署 ✅ | R87 `_inbox:server` 中继已就绪 ✅

---

## 目录

1. [现有架构分析](#一现有架构分析)
2. [扩展点分析](#二扩展点分析)
3. [消息处理流程](#三消息处理流程)
4. [DISPATCH_SENDER_ID 配置](#四dispatch_sender_id-配置)
5. [前缀规则更新对照](#五前缀规则更新对照)
6. [文件修改清单](#六文件修改清单)
7. [安全考虑](#七安全考虑)
8. [注意事项与陷阱](#八注意事项与陷阱)

---

## 一、现有架构分析

### 1.1 调用链全景

```
客户端 → WS → type:"message"
                  │
                  ▼
         handler() / ws_handler()
                  │
                  ▼
         授权检查 + key活性检查
                  │
                  ▼
      ┌─ _handle_server_relay()  ← R87 拦截 _inbox:server 消息
      │  返回 True  → 消息已处理，continue
      │  返回 False → 继续下行
      │
      ▼  (False 时)
   权限检查 (R99)
      │
      ▼
  handle_broadcast()
      │
      ├─ channel == "_inbox:server" → _handle_server_query()  # R82 ! 命令
      ├─ channel.startswith("_inbox:") → 正常 inbox 路由
      └─ 其他 → 普通广播
```

### 1.2 R87 现有路由（`_handle_server_relay`）

| 优先级 | 规则 | 前缀 | 行为 |
|:------:|:-----|:-----|:-----|
| 0 (R96) | 回路测试 | `test ✅` | 回声回复到 bot 收件箱 |
| 1 (安全) | PM 误发 | — | agent_id == PM → 拒绝 (返回 True) |
| 2 (R87) | ACK | `ACK ✅` | 转发通知到 PM |
| 3 (R87) | 完成 | `✅ 完成` | 转发 PM + 自动确认 bot |
| 4 (R82) | 查询 | `!` | 透传 → `_handle_server_query` |
| 5 (R87) | 沉默 | 其他 | 仅日志，返回 True |

### 1.3 重复代码问题 ⚠️

`_handle_server_relay` 在同一文件中有**两份完全相同的实现**：

| 副本 | 行号 | 说明 |
|:----:|:-----|:------|
| **A** | L2313–L2419 | 被 `handler()` 的 `handler()` 调用 |
| **B** | L2422–L2528 | 被 `handler()` 的 `handler()` 调用 |

两份代码逻辑完全一致，这可能是合并过程中产生的重复。**R102 仅修改副本 A（L2313–L2419）**，副本 B 保持不动以减少风险。建议后续 R103 清理重复。

### 1.4 调用入口分布

| 入口 | 文件 | 行号 | 备注 |
|:-----|:-----|:-----|:------|
| `handler()` (websockets 库) | `server/main.py` | L2567 | 旧版入口，维护兼容 |
| `ws_handler()` (aiohttp) | `server/__main__.py` | L84 | 新版入口（supervisor 使用） |

两个入口均调用 `_handle_server_relay`，R102 修改后两个入口都受益。

---

## 二、扩展点分析

### 2.1 新增：`to_agent` 派活分支

**插入位置**: `_handle_server_relay`（副本 A, L2313）中，紧跟在 `test ✅` 回路测试之后、`PM 安全守卫` 之前。

**优先级**: 1（最高 — 派活紧急性最高）

**原因**: PM 发 `to_agent` 消息必须先于安全守卫（安全守卫目前拒绝所有 PM→`_inbox:server` 的消息）。新逻辑应允许 PM 消息中**含 `to_agent` 字段**的通过。

**新优先级表**:

| 优先级 | 标签 | 触发条件 | 位置 | 行为 |
|:------:|:-----|:---------|:-----|:------|
| 0 | 🔄 回路测试 | `content.startswith("test ✅")` | L2329 | 保持不动 |
| **1** | **📤 派活** | **`msg.get("to_agent")` 非空** | **L2347 插入** | **R102 新增** |
| 2 | 🛡️ PM 守卫 | `agent_id == pm_agent_id` | L2357 | **修改** — 排除含 to_agent 的消息 |
| 3 | 📬 ACK | `收到 ✅` | L2366 | **修改** — 前缀变更 |
| 4 | ✅ 完成 | `已完成 ✅` | L2383 | **修改** — 前缀变更 |
| 5 | 🔄 退回 | `退回 🔄` | L2392 插入 | **新增** |
| 6 | ❌ 失败 | `失败 ❌` | L2397 插入 | **新增** |
| 7 | ❓ 查询 | `content.startswith("!")` | L2413 | 保持不动 |
| 8 | 🤫 沉默 | 其他 | L2418 | 保持不动 |

### 2.2 新增函数拆分建议

可选方案 — 可将 Bot 回复前缀匹配逻辑拆出独立函数：

```python
async def _handle_bot_reply(ws, agent_id: str, msg: dict) -> bool:
    """处理 bot 回复到 _inbox:server 的前缀匹配逻辑.
    
    Args:
        ws: WebSocket 连接
        agent_id: 发送消息的 bot 的 agent_id
        msg: 原始消息 dict
    
    Returns:
        True — 消息已处理（ACK/完成/退回/失败/沉默）
        False — 需要继续路由（透传 ! 命令）
    """
```

**建议放在 `_handle_server_relay` 内部作为内联逻辑**，不拆出独立函数，保持与现有 R87 代码风格一致。后续 R103 如果逻辑膨胀再拆。

---

## 三、消息处理流程

### 3.1 派活流程（PM → Server → Bot）

```
PM (小谷) ──→ _inbox:server (to_agent: ws_xxx, content: "任务")

  _handle_server_relay() 入口:

  ① 检测 to_agent 字段
     if msg.get("to_agent"):
         target = msg["to_agent"].strip()
  
  ② 校验目标合法性
     if not target or not target.startswith("ws_"):
         await _send(ws, {"type": "error", "error": ...})
         return True  # 已处理（拒绝）
  
  ③ 隐藏发件人
     relay_payload = {
         "type": "broadcast",
         "channel": f"_inbox:{target}",
         "from_name": "系统",
         "from_agent": state.SYSTEM_AGENT_ID,
         "content": msg.get("content", "").strip(),
         "ts": time.time(),
     }
  
  ④ 广播到目标 Bot 的 inbox
     await _broadcast_to_channel(f"_inbox:{target}", relay_payload)
  
  ⑤ 记录日志
     logger.info("[Dispatch] %s → %s: %s...", sender_id[:12], target[:16], content[:60])

  Bot 收到 ── inbox 中看到 from_name: "系统", from_agent: "server"
```

### 3.2 Bot 回复流程（Bot → Server → PM）

```
Bot ──→ _inbox:server (content: "收到 ✅ R102 技术方案")

  _handle_server_relay() 入口:

  ① 检查 channel == _inbox:server
  
  ② 前缀匹配（startswith）
  
  ┌─ "收到 ✅"  →  ③ ACK 记录
  │                 ④ 构造通知: f"📬 {sender_name} 已接活:\n{content}"
  │                 ⑤ _broadcast_to_channel(f"_inbox:{DISPATCH_SENDER_ID}", payload)
  │                 ⑥ return True
  │
  ├─ "已完成 ✅" →  ③ 完成标记
  │                 ④ 通知 PM: f"✅ {sender_name} 任务完成:\n{content}"
  │                 ⑤ 自动确认 Bot: "✅ 确认，已收到你的完成通知。"
  │                 ⑥ 两路 _broadcast_to_channel
  │                 ⑦ return True
  │
  ├─ "退回 🔄"  →  ③ 退回标记
  │                 ④ 通知 PM: f"🔄 {sender_name} 退回:\n{content}"
  │                 ⑤ 自动确认 Bot: "🔄 已记录退回。"
  │                 ⑥ 两路 _broadcast_to_channel
  │                 ⑦ return True
  │
  ├─ "失败 ❌"  →  ③ 失败标记
  │                 ④ 通知 PM: f"⚠️ {sender_name} 失败:\n{content}"
  │                 ⑤ 自动确认 Bot: "⚠️ 已记录失败。"
  │                 ⑥ 两路 _broadcast_to_channel
  │                 ⑦ return True
  │
  ├─ "!"       →  ③ 透传到 handle_broadcast → _handle_server_query
  │                 ④ return False
  │
  └─ 其他       →  ③ 沉默（仅日志，无转发）
                    ④ 可考虑写入 DB（见 §7.3）
                    ⑤ return True
```

### 3.3 PM 通知流程（示意 payload）

```python
await _broadcast_to_channel(f"_inbox:{dispatch_sender_id}", {
    "type": "broadcast",
    "channel": f"_inbox:{dispatch_sender_id}",
    "from_name": "系统",
    "from_agent": state.SYSTEM_AGENT_ID,
    "content": f"📬 {sender_name} 已接活:\n{content}",
    "ts": time.time(),
})
```

PM (`dispatch_sender_id = ws_f26e585f6479`) 收到后看到 `from_name: "系统"`，内容中 `sender_name` 是 Bot 的显示名（如"小开"），PM 据此知晓进度。

---

## 四、DISPATCH_SENDER_ID 配置

### 4.1 配置项定义

在 `server/config.py` 末尾追加：

```python
# ── R102: Dispatch notification target ──────────────────────────
# PM 的 inbox agent_id，Server 将 ACK/完成/退回/失败通知转发至此收件箱。
# 环境变量: DISPATCH_SENDER_ID
# 未设置时回退到已有配置 WS_PM_AGENT_ID（用于 R87 原有通知）
DISPATCH_SENDER_ID: str = os.environ.get(
    "DISPATCH_SENDER_ID",
    os.environ.get("WS_PM_AGENT_ID", ""),
)
```

### 4.2 设计理由

| 考量 | 说明 |
|:-----|:------|
| **独立环境变量** | `DISPATCH_SENDER_ID` 与 `WS_PM_AGENT_ID` 语义不同：前者专指"进度通知收件人"，后者是"PM 身份标识"。分开配置更清晰 |
| **回退策略** | 未设 `DISPATCH_SENDER_ID` 时自动回退到 `WS_PM_AGENT_ID`，实现零配置向后兼容 |
| **部署值** | 小谷的 agent_id = `ws_f26e585f6479` |

### 4.3 在 _handle_server_relay 中的使用

```python
pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
if pm_agent_id:
    await _broadcast_to_channel(f"_inbox:{pm_agent_id}", notify_payload)
```

---

## 五、前缀规则更新对照

| 现有 (R87) | → | 新 (R102) | 说明 |
|:-----------|:--|:----------|:------|
| `ACK ✅` | → | `收到 ✅` | 更自然的语义，与 Bot 实际回复一致 |
| `✅ 完成` | → | `已完成 ✅` | 与需求文档对齐 |
| — | → | `退回 🔄` | 新增，支持退回重做流程 |
| — | → | `失败 ❌` | 新增，支持失败通知流程 |
| `test ✅` | 保持 | `test ✅` | 回路测试，不受影响 |
| `!` | 保持 | `!` | 查询命令，不受影响 |

### 5.1 向后兼容策略

为避免部署瞬间 Bot 旧前缀失效，建议**双前缀兼容**两周：

```python
# R102: 新前缀 (primary)
if content.startswith("收到 ✅") or content.startswith("ACK ✅"):
    ...

if content.startswith("已完成 ✅") or content.startswith("✅ 完成"):
    ...
```

部署两周后（R103 发布时）移除旧前缀支持。

---

## 六、文件修改清单

### 6.1 `server/main.py` — 修改 _handle_server_relay（副本 A，L2313–L2419）

| 行号 | 操作 | 内容 |
|:----:|:-----|:------|
| L2328 | 修改 | 调整注释标记，增加 R102 字头 |
| **L2347 后** | **插入 ~25 行** | **`to_agent` 派活分支**（见 §6.1.1） |
| L2357 | 修改 | PM 安全守卫排除含 `to_agent` 字段的消息 |
| L2365 | 修改 | `ACK ✅` → `收到 ✅`（双前缀兼容） |
| L2382 | 修改 | `✅ 完成` → `已完成 ✅`（双前缀兼容） |
| L2392 后 | 插入 ~25 行 | `退回 🔄` 分支 |
| L2392 后 | 插入 ~25 行 | `失败 ❌` 分支 |
| — | ~+100 行 | 合计净增 |

#### 6.1.1 `to_agent` 派活分支 伪代码

```python
    # ═══ R102: to_agent 派活路由 ═══
    to_agent = (msg.get("to_agent") or "").strip()
    if to_agent:
        # 校验: 必须是合法 agent_id 格式
        if not _is_valid_agent_id(to_agent):
            logger.warning("[Dispatch] 拒绝: 非法 to_agent=%s", to_agent)
            return True
        # 隐藏发件人，构造转发 payload
        relay_payload = {
            "type": "broadcast",
            "channel": f"_inbox:{to_agent}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": msg.get("content", "").strip(),
            "ts": time.time(),
        }
        await _broadcast_to_channel(f"_inbox:{to_agent}", relay_payload)
        logger.info("[Dispatch] %s → %s: %s...",
                     agent_id[:12], to_agent[:16],
                     (msg.get("content") or "")[:60])
        return True
    # ═══════════════════════════════════════════
```

#### 6.1.2 PM 安全守卫修改

```python
    # ═══ 安全守卫: PM 误发 _inbox:server ═══
    # 排除带 to_agent 的派活消息
    if pm_agent_id and agent_id == pm_agent_id and not msg.get("to_agent"):
        ...
```

#### 6.1.3 前缀规则更新（R87 → R102）

```python
    # ═══ 规则 1: 收到 ✅ / ACK ✅ → 转发 PM ═══
    if content.startswith("收到 ✅") or content.startswith("ACK ✅"):
        ...

    # ═══ 规则 2: 已完成 ✅ / ✅ 完成 → 转发 PM + 自动确认 ═══
    if content.startswith("已完成 ✅") or content.startswith("✅ 完成"):
        ...

    # ═══ 规则 3: 退回 🔄 ═══
    if content.startswith("退回 🔄"):
        ...

    # ═══ 规则 4: 失败 ❌ ═══
    if content.startswith("失败 ❌"):
        ...
```

### 6.2 `server/config.py` — 新增配置项

| 行号 | 操作 | 内容 |
|:----:|:-----|:------|
| 末尾 (~L167) | 插入 ~10 行 | `DISPATCH_SENDER_ID` 配置（见 §4.1） |

### 6.3 无改动文件 ✅

| 文件 | 理由 |
|:-----|:------|
| `server/__main__.py` | 已复用 `_handle_server_relay`，自动受益 |
| `server/protocol.py` | 无需新增消息类型 |
| `server/command_utils.py` | `_broadcast_to_channel` 已有，无需修改 |
| 客户端 | 零改动 |

---

## 七、安全考虑

### 7.1 `to_agent` 字段校验

| 校验项 | 实现 | 拒绝条件 |
|:-------|:-----|:---------|
| 非空 | `if not to_agent:` | 空/空白 → return True |
| 格式 | `_is_valid_agent_id(to_agent)` — 检查 `startswith("ws_")` + 长度 | 格式非法 → return True |
| 存在性 | 可选的：检查目标是否已注册（通过 `_connections`） | 不强制 — 允许离线投递 |

建议辅助函数：

```python
def _is_valid_agent_id(aid: str) -> bool:
    """粗校验：格式 must be ws_xxx."""
    return bool(aid and aid.startswith("ws_") and len(aid) > 10)
```

### 7.2 隐藏发件人

| 风险 | 缓解 |
|:-----|:------|
| Bot 从 payload 逆推 PM 身份 | `from_agent` 硬赋值为 `state.SYSTEM_AGENT_ID`（`"server"`），`from_name` 硬赋值为 `"系统"`。原始 `from_agent`/`from_name` 完全被覆盖 |
| PM 在消息 content 中自曝身份 | 这是 PM 操作层面的问题，Server 无法过滤消息正文中的文本提及。需在工作规范中约定 |
| 日志泄露 | `logger.info("[Dispatch] %s → ...", agent_id[:12], ...)` 只记录截断的 sender_id，不记录显示名 |

### 7.3 无关消息入库

需求要求「不匹配任何前缀的消息仅写入 DB，不转发不回复」。

当前 `_handle_server_relay` 对无关消息只做 `return True`（沉默），**并未写入 DB**。

R102 可在沉默分支添加：

```python
# ═══ 规则 5: 无匹配 → 入库沉默 ═══
logger.info("[Relay] 沉默: %s 内容=%s...", sender_name, content[:60])
# 入库留痕（可选，如 message_store 有 save_message 接口）
try:
    ms.save_message(channel, msg)  # 通用的消息入库
except Exception:
    pass  # 入库失败不阻塞主流程
return True
```

> ⚠️ **注意**：`ms.save_message()` 是否存在需确认。如无此函数，可降级为仅日志。R102 不强制实现入库，**优先级低于核心派活路由**。

### 7.4 `_handle_server_query`（R82 `!` 命令）不受影响

当前处理流程：

```
handler()/ws_handler()
  → _handle_server_relay()   # 检查 ! 前缀 → return False（透传）
  → handle_broadcast()       # channel==_inbox:server → _handle_server_query()
```

R102 `to_agent` 分支插入在回路测试之后、PM 守卫之前。`!` 命令的透传逻辑不变。

`test ✅` 回路测试同样不受影响 — 它在 `to_agent` 分支之前检查并 return True。

---

## 八、注意事项与陷阱

| # | 陷阱 | 说明 | 缓解 |
|:-:|:-----|:------|:------|
| 1 | **重复代码** | `_handle_server_relay` 有两份（L2313 + L2422） | 只改副本 A。通知爱泰编码时注意 |
| 2 | **PM 守卫拦截** | PM 带 `to_agent` 的消息会被现有守卫拒绝 | 修改守卫排除 `to_agent` |
| 3 | **兼容前缀** | Bot 可能继续发旧前缀 | 双前缀兼容两周 |
| 4 | **`_broadcast_to_channel` 目标不存在** | 如果 `to_agent` 指向离线 Bot | `_broadcast_to_channel` 内部已有容错 |
| 5 | **循环风险** | Bot 回复到 `_inbox:server` 触发前缀匹配，不会形成循环 | 不可能循环 — `_handle_server_relay` 只接收 `type:"message"`，不产生新 inbound 消息 |

---

## 附录 A：完整消息流对照

### 🅰️ 派活流程（PM → _inbox:server → Server → Bot）

```
[PM] 发送到 _inbox:server:
  { type: "message", channel: "_inbox:server",
    to_agent: "ws_0bb747d3ea2a",
    content: "R102 编码",
    from_name: "小谷", from_agent: "ws_f26e585f6479" }

        │
        ▼
_handle_server_relay():
  ① to_agent = "ws_0bb747d3ea2a"  ✓
  ② 校验通过  ✓
  ③ 构造 payload (from_name="系统", from_agent="server")
  ④ _broadcast_to_channel("_inbox:ws_0bb747d3ea2a", payload)
  ⑤ return True

        │
        ▼
[Bot 爱泰] inbox 收到:
  { type: "broadcast", channel: "_inbox:ws_0bb747d3ea2a",
    from_name: "系统", from_agent: "server",
    content: "R102 编码" }
```

### 🅱️ 回复流程（Bot → _inbox:server → Server → PM）

```
[Bot 爱泰] 回复到 _inbox:server:
  { type: "message", channel: "_inbox:server",
    content: "收到 ✅ R102 开始编码",
    from_name: "爱泰", from_agent: "ws_0bb747d3ea2a" }

        │
        ▼
_handle_server_relay():
  ① channel == "_inbox:server"  ✓
  ② content.startswith("收到 ✅")  ✓
  ③ sender_name = "爱泰"
  ④ 通知 PM: f"📬 爱泰 已接活:\n收到 ✅ R102 开始编码"
  ⑤ _broadcast_to_channel("_inbox:ws_f26e585f6479", notify_payload)
  ⑥ return True

        │
        ▼
[PM 小谷] inbox 收到:
  { type: "broadcast", channel: "_inbox:ws_f26e585f6479",
    from_name: "系统", from_agent: "server",
    content: "📬 爱泰 已接活:\n收到 ✅ R102 开始编码" }
```

---

## 附录 C：附带修复 — Web 端消息顺序 Bug 🐛

### 问题

3 处 `.reverse()` 误用导致 Web 端最新消息显示在最下面：

| # | 文件:行号 | 修复 |
|:-:|:----------|:-----|
| ① | `web_viewer.py:271` | 删除 `db_msgs.reverse()` — DB 已返回 DESC（最新在前） |
| ② | `web_viewer.py:291` | 删除 `messages.reverse()` — `sort(reverse=True)` 已排好 |
| ③ | `web_viewer.py:465` 后 | 追加 `all_msgs.reverse()` — `get_messages_by_time_range` 返回 ASC（最旧在前） |

### 修复后语义统一

```
DB / 日志 → 统一为 [最新, ..., 最旧]
            ↓
前端 appendChild 按顺序追加到 DOM
            ↓
显示: 最新在最上面 ✅
```

变更量：改 3 行，零逻辑风险。爱泰在 Step 3 顺手修掉。

---

## 附录 B：关键函数引用的行号速查

| 函数/变量 | 文件 | 行号 |
|:----------|:-----|:-----|
| `_handle_server_relay` (副本 A) | `server/main.py` | L2313 |
| `_handle_server_relay` (副本 B) | `server/main.py` | L2422 |
| `_handle_server_query` | `server/main.py` | L1860 |
| `handle_broadcast` | `server/main.py` | L1276 |
| `handler()` (websockets) | `server/main.py` | L2531 |
| `ws_handler()` (aiohttp) | `server/__main__.py` | L40 |
| `_broadcast_to_channel` | `server/command_utils.py` | L16 |
| `PIPELINE_PM_AGENT_ID` | `server/config.py` | L160 |
| `state.SYSTEM_AGENT_ID` | `server/state.py` | — |
| `state.SERVER_INBOX_CHANNEL` | `server/config.py` | L165 |
