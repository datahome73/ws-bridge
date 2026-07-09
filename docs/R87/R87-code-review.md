# R87 代码审查报告 — `_inbox:server` 中继架构 🚉

> **版本：** v2.0（合并审查）
> **状态：** 🟡 条件通过
> **审查者：** 🔍 小周（Review）
> **日期：** 2026-07-09
> **审查基准：** `f05b769` (feat(R87): _inbox:server 中继架构)
> **前置文档：** [产品需求](./R87-product-requirements.md) · [技术方案](./R87-tech-plan.md)

---

## 1. 审查结论

| 维度 | 评分 |
|:-----|:----:|
| 核心功能实现（3 规则 + 入口集成） | 🟢 **优秀** — 与技术方案完全一致 |
| PM 安全守卫 | 🟢 **优秀** — 位置正确，行为合理 |
| 路由安全 | 🟢 **完善** — 守卫矩阵全覆盖 |
| 向后兼容 | 🟢 **完全兼容** — 旧 bot 不受影响 |
| 代码质量 | 🟢 **优秀** — 函数职责单一，结构清晰 |
| **! 指令透传** | 🟡 **W1** — `_handle_server_query` 被拦截 |
| **Scope 控制** | ❌ **不合格** — 8 个非审查文件改动 |

### 处理决定

**核心 3 文件（config.py / handler.py / __main__.py）通过审查。W1 已修复（`20139c2`）。Scope creep 文件需分离处理。**

---

## 2. 逐文件审查

### 2.1 `server/config.py` ✅ 通过

| 检查项 | 结果 | 说明 |
|:-------|:----:|:------|
| 新增位置 | ✅ | 紧接 `PIPELINE_PM_AGENT_ID` (L169+) |
| 常量名 | ✅ | `SERVER_INBOX_CHANNEL = "_inbox:server"` |
| 类型注解 | ✅ | `: str` |
| Docstring | ✅ | 有简要说明 |
| Scope creep | ✅ | 仅此 1 处新增，无多余改动 |

```python
# ── R87: _inbox:server 中继通道 ────────────────────────────
SERVER_INBOX_CHANNEL: str = "_inbox:server"
"""Bot 回复中继通道。bot 将 ACK/完成回复发至此通道，由 server 筛选转发。"""
```

✅ 与技术方案一致。

---

### 2.2 `server/handler.py` ✅ 核心逻辑通过

#### 2.2.1 `is_server_inbox()` — ✅

| 检查项 | 结果 |
|:-------|:----:|
| 位置 | ✅ 模块级常量区 |
| 判断逻辑 | ✅ `channel == SERVER_INBOX_CHANNEL` 精确相等 |
| 返回类型 | ✅ `bool` |

#### 2.2.2 `_handle_server_relay()` — ✅ 3 条规则

**规则 1: `ACK ✅` → 转发 PM**

| 检查项 | 结果 |
|:-------|:----:|
| 前缀匹配 | ✅ `content.startswith("ACK ✅")` — 精确 |
| 转发目标 | ✅ `_broadcast_to_channel(f"_inbox:{pm_agent_id}", ...)` |
| PM_AGENT_ID 为空保护 | ✅ `if pm_agent_id:` 守卫 |
| 消息格式 | ✅ `📬 {sender_name} 已接活:\n{content}` |
| 匹配后 `return` | ✅ `return True`，不继续匹配 |
| 日志 | ✅ `logger.info("[Relay] ACK: %s → PM", sender_name)` |

**规则 2: `✅ 完成` → ⑤ 转发 PM + ⑥ 自动确认 bot**

| 检查项 | 结果 |
|:-------|:----:|
| 前缀匹配 | ✅ `content.startswith("✅ 完成")` — 精确 |
| ⑤ 转发目标 | ✅ `_broadcast_to_channel(f"_inbox:{pm_agent_id}", ...)` |
| ⑤ PM 空保护 | ✅ `if pm_agent_id:` 守卫 |
| ⑤ 消息格式 | ✅ `✅ {sender_name} 任务完成:\n{content}` |
| ⑥ 自动确认目标 | ✅ `_broadcast_to_channel(f"_inbox:{agent_id}", ...)` — bot 自己的 inbox |
| ⑥ 确认内容 | ✅ `"✅ 确认，已收到你的完成通知。本轮任务完成。"` |
| ⑥ 不走 `_inbox:server` | ✅ 确认发到 `_inbox:<bot_id>` |
| ⑤+⑥ 同时触发 | ✅ 两个 `await` 顺序执行，`_broadcast_to_channel` 内部 `try/except`，一个失败不影响另一个 |
| 匹配后 `return` | ✅ `return True` |

**规则 3: 其他 → 沉默**

| 检查项 | 结果 |
|:-------|:----:|
| 沉默处理 | ✅ 仅 `logger.info`，不转发不回复 |
| 返回 | ✅ `return True` |
| 日志截断 | ✅ `content[:60]` 防日志暴涨 |

#### 2.2.3 PM 安全守卫 — ✅

| 检查项 | 结果 |
|:-------|:----:|
| 检查时机 | ✅ 入口处，`is_server_inbox()` 之后，前缀匹配之前 |
| 判断条件 | ✅ `pm_agent_id and agent_id == pm_agent_id` |
| 返回 error | ✅ `await _send(ws, {"type": "error", "error": "..."})` |
| 日志警告 | ✅ `logger.warning("[Relay] 拒绝: PM %s 试图发消息到 _inbox:server", agent_id[:12])` |
| 返回 True | ✅ **关键设计** — 返回 True 表示已处理，调用方 `continue`，消息不被路由到任何地方 |

#### 2.2.4 入口集成位置 — ✅

```python
# handler() 中（L6332-6336）
# ═══ R87: _inbox:server 中继拦截 ═══
if await _handle_server_relay(ws, agent_id, msg):
    continue
# ════════════════════════════════════════
await handle_broadcast(ws, agent_id, msg)
```

| 检查项 | 结果 |
|:-------|:----:|
| 在 `handle_broadcast` 之前 | ✅ — 100% 拦截 `_inbox:server` 消息 |
| 在 B1 key 检查之后 | ✅ — 只有已认证 bot 才能进入中继 |
| `continue` 语义 | ✅ — 已处理消息不走后续路由 |
| 不修改现有逻辑 | ✅ — `handle_broadcast` 调用不变 |

---

### 2.3 `server/__main__.py` ✅ 通过

| 检查项 | 结果 |
|:-------|:----:|
| 导入 `_handle_server_relay` | ✅ L13 追加，与现有导入并列 |
| 入口集成 | ✅ 同 handler.py，B1 后 + handle_broadcast 前 |
| B1 检查 | ✅ 局部 `from . import persistence` + 检查 |
| `continue` 语义 | ✅ |
| 作用域 | ✅ 与 handler 入口完全对称 |

```python
from .handler import handle_auth, handle_broadcast, handle_register, _connections, _handle_server_relay  # R87
```

---

## 3. 审查清单逐项

### 3.1 核心功能检查

| # | 检查项 | 结果 | 证据 |
|:-:|:-------|:----:|:-----|
| ✅-1 | `_handle_server_relay()` 3 条规则正确 | ✅ | §2.2.2 — ACK / 完成 / 沉默 三条规则完整实现 |
| ✅-2 | `_inbox:server` 拦截在 `handle_broadcast` 前 | ✅ | §2.2.4 — `if await _handle_server_relay(): continue` 在 `handle_broadcast` 之前 |
| ✅-3 | Step ⑤+⑥ 同时触发 | ✅ | 两个 `await _broadcast_to_channel()` 顺序执行，各自 `try/except` 隔离 |
| ✅-4 | Step ⑥ 确认发 `_inbox:<bot_id>`（不是 `_inbox:server`） | ✅ | `_broadcast_to_channel(f"_inbox:{agent_id}", ...)` |
| ✅-5 | PM 安全守卫：`agent_id==PM_AGENT_ID` 拒绝+error | ✅ | §2.2.3 |
| ❌-6 | **零 scope creep** | ❌ | **§5.1** — 8 个非审查文件改动 |
| ✅-7 | 旧 bot 用 `_inbox:<PM_id>` 回复不受影响 | ✅ | `is_server_inbox()` 只拦截 `_inbox:server` |
| ❌-8 | **! 命令到 `_inbox:server` 正常处理** | ❌ | **§4** — W1: `_handle_server_query` 被拦截 |

### 3.2 路由安全

| # | 检查项 | 结果 |
|:-:|:-------|:----:|
| ✅-6 | PM 误发 `_inbox:server` → 拒绝+error | ✅ |
| ✅-7 | Step ⑥ 确认发 `_inbox:<bot_id>`（不走 `_inbox:server`） | ✅ |
| ✅-8 | `ACK✅`（无空格）→ 不触发转发 | ✅ |
| ✅-9 | `✅完成`（无空格）→ 不触发完成转发 | ✅ |
| ✅-10 | 多个 bot 同时发 → 独立处理 | ✅ |
| ✅-11 | 未认证 bot → 不进中继 | ✅ |
| ✅-12 | Step ⑥ 确认后 bot 再回复 → 中继沉默 | ✅ |

---

## 4. 🟡 发现的问题

### W1: `!` 指令到 `_inbox:server` 被沉默

**严重度:** 🟡 中

**发现者：** 🔍 小周（审查工程师）

**现象：**
现有 `_handle_server_query()` (handler.py L5763) 处理发给 `_inbox:server` 的 `!` 命令（如 `!agent_card list`、`!pipeline_status`、`!list_workspaces`），通过 `handle_broadcast` L5193 的 inbox fast path 调用。

但新的 `_handle_server_relay()` 在 **`handle_broadcast` 之前** 拦截所有 `_inbox:server` 消息。`!` 命令不匹配规则 1/2，落入规则 3 沉默处理，永远不会到达 `_handle_server_query()`。

**影响链路：**
```
_inbox:server 消息
  │
  ├─ R82: _handle_server_query (L5193)   ← 原有入口，被拦截
  │    └─ !agent_card list → ✅ 正常（原行为）
  │
  └─ R87: _handle_server_relay (L6336)   ← 新拦截，先执行
       ├─ ACK ✅ → 转发 PM ✅
       ├─ ✅ 完成 → 转发+确认 ✅
       └─ !agent_card list → ❌ 沉默！（应为正常处理）
```

**根因：** `_handle_server_relay` 缺少对 `!` 前缀的透传逻辑。

**修复建议：**
在 `_handle_server_relay` 规则 3 前增加 `!` 透传：

```python
    # ═══ 规则 0: ! 命令 → 透传到 normal routing（兼容 _handle_server_query）═══
    if content.startswith("!"):
        logger.info("[Relay] 透传: %s 发送 ! 命令到 _inbox:server", sender_name)
        return False
```

这样 `!` 命令 `return False`，调用方不 `continue`，继续走到 `handle_broadcast` → `_handle_server_query`。

---

## 5. 🔴 发现的问题

### 🔴 5.1 Scope Creep（严重）

**发现者：** 🏗️ 小开（架构师）

提交包含 **8 个非审查范围文件的改动（~125 行）**，是 3 个审查文件改动量的 2 倍+。

| 文件 | 变动 | 行数 | 是否在审查范围 |
|:-----|:-----|:----:|:------------:|
| `server/config.py` | ✅ 审查文件 | +5 | ✅ 是 |
| `server/handler.py` | ✅ 审查文件 | +99 | ✅ 是 |
| `server/__main__.py` | ✅ 审查文件 | +6 | ✅ 是 |
| **`gateway-plugin/__init__.py`** | R82+ inbox 路由改进 | **~40** | **❌ 否** |
| **`join_ws.py`** | **新文件** — 调试脚本 | **+41** | **❌ 否** |
| **`query_pipeline.py`** | **新文件** — 调试脚本 | **+38** | **❌ 否** |
| **`clients/node/ws_bridge_state_default.json`** | **新文件** — 节点状态 | **+7** | **❌ 否** |
| **`clients/node/.ws-bridge-pid`** | PID 文件 | **+1** | **❌ 否** |
| **`clients/node/.ws-bridge-write`** | 删除文件 | **-11** | **❌ 否** |
| **`clients/node/ws-bridge-err.log`** | 日志清理 | **-14** | **❌ 否** |
| **`clients/node/ws-bridge-out.log`** | 日志清理 | **-32** | **❌ 否** |
| **合计** | | **235±** | **仅 ~47% 在审查范围** |

**影响分析：**
- `gateway-plugin/__init__.py` 的改动（mention 模式 bypass、inbox 路由 redirect、platform_hint 重写）是**需要独立 Review 的逻辑变更**，不应混入 R87 审查
- `join_ws.py` 和 `query_pipeline.py` 是调试工具，不应合入 dev 分支
- 日志/PID 文件操作会影响后续排查

**处理建议：** 将 scope creep 文件从该 commit 分离。`gateway-plugin/__init__.py` 的改动应归入独立 PR/commit 并经过独立的 Review 流程。

### 🟡 5.2 `query_pipeline.py` 凭据泄露（中等）

**文件：** `query_pipeline.py`（新文件，38 行）

```
WS_URL = "wss://wsim.datahome73.cloud/ws"
API_KEY = "sk_ws_...d000"
AGENT_ID = "ws_0bb747d3ea2a"
```

- 包含**生产环境** WebSocket URL 和 API Key
- 无论 key 是否已吊销，硬编码凭据不应出现在 repo 中

**处理建议：** 从 commit 中移除该文件，并轮换泄露的 API Key。

---

## 6. 兼容性分析

| 场景 | 旧行为 | R87 后 | 结论 |
|:-----|:-------|:--------|:----:|
| 旧 bot 用 `_inbox:<PM_id>` 回复 | 正常路由到 PM inbox | **不变** — `_inbox:<PM_id>` 不走中继 | ✅ 完全兼容 |
| 旧 bot 不知 `_inbox:server` | N/A | 无影响 | ✅ |
| 新旧 bot 混合部署 | — | 新 bot `_inbox:server`，旧 bot `_inbox:<PM_id>` | ✅ |
| 非 `_inbox:server` 的消息 | 正常路由 | **不变** — `is_server_inbox()` 返回 False → 走 `handle_broadcast` | ✅ |

---

## 7. 风险与建议

### 7.1 风险

| # | 风险 | 等级 | 评估 |
|:-:|:-----|:----:|:-----|
| 1 | `PM_AGENT_ID` 为空时 ACK/完成不转发 | 🟢 低 | 代码已处理，仅自动确认 bot |
| 2 | `_broadcast_to_channel` ⑤ 失败不影响 ⑥ | 🟢 低 | 内部 `try/except` 已做隔离 |
| 3 | Scope creep 文件合入后影响 | 🟡 中 | `gateway-plugin/__init__.py` 的 inbox 路由改动未经 Review |

### 7.2 建议

| # | 建议 | 优先级 |
|:-:|:-----|:------:|
| 1 | **修复 W1：在 `_handle_server_relay` 增加 `!` 透传** | 🔴 高 |
| 2 | **将 scope creep 文件从 dev 分离** — 创建独立 commit 处理 `gateway-plugin/__init__.py` | 🔴 高 |
| 3 | **删除 `join_ws.py` 和 `query_pipeline.py`** — 调试工具不应合入 dev | 🟡 中 |
| 4 | **轮换 `query_pipeline.py` 中泄露的 API Key** | 🟡 中 |

---

## 8. 最终结论

| 维度 | 评分 | 说明 |
|:-----|:----:|:------|
| 核心功能实现（3 规则 + 入口集成） | 🟢 优秀 | 与技术方案完全一致 |
| PM 安全守卫 | 🟢 优秀 | 位置正确，行为合理 |
| 路由安全 | 🟢 完善 | 守卫矩阵全覆盖 |
| 向后兼容 | 🟢 完全兼容 | 旧 bot 不受影响 |
| **! 指令透传** | 🟡 W1 | `_handle_server_query` 被拦截 |
| **Scope 控制** | 🔴 不合格 | 8 个非审查文件改动 |

**核心 3 文件（config.py / handler.py / __main__.py）通过审查。W1 已修复（`20139c2`）。Scope creep 文件需分离处理。**

---

*本文档由 🔍 审查工程师（小周）编写，待 Step 5 🦐 QA 测试验证。*
