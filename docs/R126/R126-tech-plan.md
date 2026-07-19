# R126 技术方案 — 场景匹配规则提取

> **起草人：** 📐 Arch（小开）
> **状态：** 📝 草稿
> **版本：** v1.0
> **基线：** dev `1496add` + R125 commit（R125-tech-plan.md 已合入）

---

## 1. 问题与目标

### 1.1 现状

`main.py` 当前 **5021 行**，承载三类职责。本轮目标是提取其中**场景匹配与路由规则**部分到独立模块。

| 职责 | 行数估算 | 本轮动作 |
|:-----|:--------:|:---------|
| 🔌 WebSocket 连接管理（handler/认证/注册） | ~800 行 | 不动 |
| 📡 **场景匹配 + 路由规则** | **~400 行** | **提取到 `scenario_matcher.py`** |
| 🛠️ 管线状态机 + 业务函数 | ~3800 行 | 不动 |

### 1.2 核心痛点

| 痛点 | 代码位置 | 描述 |
|:-----|:---------|:-----|
| **P1 规则隐藏** | `_handle_server_relay` L3271-L3495（224 行） | 7 条 if/elif 链隐式表达优先级，新规则难加 |
| **P2 双入口副本** | `handler()` L4161 + `ws_handler()` L95/L106 | 同一份 `_handle_server_relay` **调用 3 处**，修改需确保 3 处同步 |
| **P3 规则/路由未分离** | `_handle_hash_cmd` L3672-L3746 | 命令解析与帮助文本耦合 |
| **P4 协议不同步** | inbox-message-protocol.md | 代码有 7 种前缀规则，文档与之需同步 |

---

## 2. 代码审计 — 实际行号与范围

### 2.1 待提取代码

#### 2.1.1 `_handle_server_relay()` — L3271~L3495（224 行）

完整 re 路由链：

| 优先级 | 规则 | 行号范围 | 代码量 |
|:------:|:-----|:--------:|:------:|
| 10 | `test ✅` 回路测试 | L3287-L3303 | ~17 行 |
| 20 | `to_agent` 派活路由 | L3314-L3360 | ~47 行 |
| 30 | `##` 命令 → `_handle_hash_cmd` | L3363-L3365 | ~3 行 |
| 35 | PM 安全守卫 | L3368-L3376 | ~9 行 |
| 40 | `收到 ✅` / `ACK ✅` 转发 PM | L3378-L3391 | ~14 行 |
| 50 | `已完成 ✅` / `✅ 完成` 自动确认 | L3393-L3419 | ~27 行 |
| 60 | `退回 🔄` 驳回回退 | L3421-L3447 | ~27 行 |
| 70 | `失败 ❌` 告警通知 | L3449-L3472 | ~24 行 |
| 80 | `!` 命令透传 | L3474-L3477 | ~4 行 |
| 90 | 无匹配入库留痕 | L3479-L3495 | ~17 行 |
| | *函数头/公共变量* | L3271-L3284 | ~14 行 |
| | **合计** | | **~224 行** |

#### 2.1.2 `_handle_hash_cmd()` — L3672~L3746（74 行）

| 段 | 行号范围 | 说明 |
|:---|:--------:|:-----|
| 函数头 + docstring | L3672-L3680 | 命令列表文档化 |
| 格式错误内联帮助 | L3681-L3698 | 解析失败时显示 |
| 命令分发主逻辑 | L3700-L3720 | start/status/stop/advance/archive/help |
| `##help` 命令回复 | L3721-L3736 | 帮助文本块 |
| 未知命令回退 | L3738-L3746 | 错误提示 |

#### 2.1.3 `_classify_lobby_message()` — L2195~L2213（18 行）

- `📢` → `'announce'`
- `📋` → `'checkin'`
- `🆘` → `'help'`
- `@mention` → `'mention', names`
- 普通文本 → `'plain'`

**本轮不提取大厅前缀的 routing action**（保留在 `handle_broadcast`），只提取分类函数到 `scenario_matcher` 供后续轮次使用。

### 2.2 双入口调用点

| 入口 | 文件 | 行号 | 代码 |
|:-----|:-----|:----:|:-----|
| `handler()` | `main.py` | L4161 | `if await _handle_server_relay(ws, agent_id, msg):` |
| `ws_handler()` | `__main__.py` | L95 | `if await _handle_server_relay(ws, agent_id, data):` |
| `ws_handler()` R102 | `__main__.py` | L106 | `if await _handle_server_relay(ws, agent_id, data):` |

**统一后：** 3 处全部改为 `if await scenario_matcher.dispatch(ws, agent_id, msg):`

### 2.3 保留在 main.py 的业务函数（不动）

| 函数 | 行号 | 说明 |
|:-----|:----:|:-----|
| `_handle_reject()` | L3499 | 驳回状态回退逻辑 |
| `_handle_hash_start()` | L3891 | 创建管线 |
| `_handle_hash_status()` | L3558 | 查询管线 |
| `_handle_hash_stop()` | L3618 | 停止管线 |
| `_handle_hash_advance()` | L3749 | 手动推进 |
| `_handle_hash_archive()` | L3806 | 手动归档 |
| `_archive_pipeline()` | L3839 | 归档执行 |
| `_try_advance_pipeline()` | — | 管线推进引擎 |
| `handle_broadcast()` | L1466 | 广播路由核心 |

---

## 3. 核心设计 — HandlerRule 规则表

### 3.1 `HandlerRule` Schema

```python
@dataclass
class HandlerRule:
    \"\"\"一条场景匹配规则。\"
    match: Callable[[str, dict, str], bool]  # match(content, msg, agent_id) → matched
    handle: Callable[[Any, str, dict, Any], Awaitable[bool]]  # handle(ws, agent_id, msg, matched_info)
    priority: int           # 数字越小越优先
    name: str               # 规则名称（日志/调试）
    protocol_ref: str = ""  # 指向 docs/inbox-message-protocol.md §章节
```

### 3.2 `Dispatch` 引擎

```python
async def dispatch(ws, agent_id: str, msg: dict) -> bool:
    \"\"\"按 priority 升序遍历规则表，命中即执行。\"
    channel = msg.get("channel", "")
    if channel != state.SERVER_INBOX_CHANNEL:
        return False  # 非中继消息放行
    content = (msg.get("content") or "").strip()
    for rule in _RULES:
        matched = rule.match(content, msg, agent_id)
        if matched is not False and matched is not None:
            return await rule.handle(ws, agent_id, msg, matched)
    return False  # 无规则匹配
```

### 3.3 规则表（7 条 inbox 中继规则 + R102 兼容）

规则按 `priority` 升序注册到 `_RULES: list[HandlerRule]`。

每条规则的 `match` 函数放在 `scenario_matcher.py` 中，`handle` 回调由 `main.py` 注册（通过 `register_rule()` 或直接传回调）。

#### 架构决策：避免循环依赖

`scenario_matcher.py` 不能导入 `main.py`（否则 `main.py` → `scenario_matcher.py` → `main.py` 循环）。解决方案：

```
# scenario_matcher.py 定义：
_RULES: list[HandlerRule] = []

async def dispatch(ws, agent_id, msg) -> bool: ...

def register_rule(rule: HandlerRule) -> None:
    _RULES.append(rule)
    _RULES.sort(key=lambda r: r.priority)

# main.py 在模块初始化时注册规则：
from . import scenario_matcher as sm

sm.register_rule(sm.HandlerRule(
    match=sm.match_ack,           # 纯函数，在 sm 中定义
    handle=handle_ack_to_pm,      # 回调函数，在 main.py 中定义
    priority=40, name="ACK 转发",
))
```

#### 各规则的 match/handle 分布

| # | 规则名 | match（scenario_matcher） | handle（main.py） |
|:-:|:-------|:-------------------------|:------------------|
| 10 | 回路测试 | `content.startswith("test ✅")` | `_send(ws, {回路确认})` |
| 20 | to_agent 路由 | `msg.get("to_agent")` 或 content 解析 | `_send_to_agent()` + 落库 |
| 30 | ## 命令 | `content.startswith("##")` | `_handle_hash_cmd()` 存根→调用子规则 |
| 35 | PM 守卫 | `agent_id == pm_agent_id` | `_send(ws, {拒绝错误})` |
| 40 | ACK 转发 | `startswith("收到 ✅" or "ACK ✅")` | `_send_to_agent(pm_id, {转发})` |
| 50 | 完成确认 | `startswith("已完成 ✅" or "✅ 完成")` | `_send_to_agent(pm_id, ...) + _send_to_agent(bot, 确认) + _try_advance_pipeline()` |
| 60 | 退回回退 | `startswith("退回 🔄")` | `_send_to_agent(pm_id, ...) + _send_to_agent(bot, 确认) + ensure_future(_handle_reject())` |
| 70 | 失败告警 | `startswith("失败 ❌")` | `_send_to_agent(pm_id, ...) + _send_to_agent(bot, 确认)` |
| 80 | ! 透传 | `content.startswith("!")` | `return False` |
| 90 | 入库留痕 | `True`（兜底） | `ms.save_message(...)` 沉默记录 |

### 3.4 `##` 子规则（在 `##` 规则内部继续路由）

保持现有 `_handle_hash_cmd()` 结构不变，只将其从 `main.py` 搬入 `scenario_matcher.py` 的 `##` 规则 handler：

```python
async def handle_hash_cmd(ws, agent_id, msg, matched):
    content = (msg.get("content") or "").strip()
    parts = content.split("##")
    # ... 现有 _handle_hash_cmd 逻辑完全搬入 ...
    # 6 个子路由：start/status/stop/advance/archive/help
    # 每个子路由调用 main.py 的 _handle_hash_xxx() 回调
```

**存根调用：** `_handle_hash_cmd` 搬入 `scenario_matcher.py`，它通过注册的回调调用 `_handle_hash_start()` 等业务函数。

### 3.5 R102 兼容处理

当前 `__main__.py` 的 `ws_handler()` 中有 R102 逻辑（L97-L107）：

```python
# 非 _inbox:server 通道的消息，匹配前缀则强制走中继
if _r102_channel != f"{p.INBOX_CHANNEL_PREFIX}server":
    _r102_prefixes = ("收到 ✅", "已完成 ✅", "退回 🔄", "失败 ❌", "ACK ✅", "✅ 完成", "✅ ")
    if _r102_content.startswith(_r102_prefixes):
        data["channel"] = f"{p.INBOX_CHANNEL_PREFIX}server"
        if await _handle_server_relay(ws, agent_id, data):
            continue
```

**提取方案：** R102 的 `channel` 修正逻辑改为在 `dispatch()` 入口处完成——如果 `channel != SERVER_INBOX_CHANNEL` 但 content 匹配中继前缀，自动修正 channel 为 `SERVER_INBOX_CHANNEL` 再继续。这样 `__main__.py` 中的 R102 代码块可以大幅简化。

---

## 4. 改动清单

### 4.1 新建文件

**`server/ws_server/scenario_matcher.py`**（~400 行）

| 组件 | 行数估算 |
|:-----|:--------:|
| HandlerRule dataclass + imports | ~30 行 |
| dispatch() 引擎 | ~40 行 |
| register_rule() / 初始化 | ~20 行 |
| 10 条 match 函数 | ~80 行 |
| `_handle_hash_cmd` 搬入（含子路由 6 条 + 2 帮助块） | ~80 行 |
| R102 channel 修正钩子 | ~15 行 |
| 规则表注册（回调占位） | ~30 行 |
| 模块 docstring + 协议指引 | ~10 行 |
| 大厅前缀分类（`_classify_lobby_message` 搬入） | ~20 行 |
| **合计** | **~400** |

### 4.2 修改文件

**`server/ws_server/main.py`**（净 -~190 行）

| 操作 | 内容 | 行数 |
|:-----|:------|:----:|
| 删除 | `_handle_server_relay()` | **-224 行**（L3271-L3495） |
| 删除 | `_handle_hash_cmd()` | **-74 行**（L3672-L3746） |
| 删除 | `_classify_lobby_message()` | **-18 行**（L2195-L2213） |
| 替换 | `handler()` 中的 relay 调用 + import | ~+5 行 |
| **净减** | | **~-311 行** |

**`server/ws_server/__main__.py`**（净 -~10 行）

| 操作 | 内容 | 行数 |
|:-----|:------|:----:|
| 替换 | import `_handle_server_relay` → `scenario_matcher` | ~+1 行 |
| 替换 | L95 调用 `_handle_server_relay` → `scenario_matcher.dispatch()` | ~+0 行 |
| 简化 | L97-L107 R102 逻辑（dispatch 内部自动处理） | **-~15 行** |

**`docs/inbox-message-protocol.md`**（~+30 行）

| 章节 | 改动 |
|:-----|:------|
| §7 前缀规则 | 新增优先级映射表（10 条规则） |
| §7 新增子节 | 每条规则链接到 `scenario_matcher.py` 的对应 HandlerRule |

### 4.3 汇总

| 文件 | 新增 | 删除 | 净变化 |
|:-----|:----:|:----:|:------:|
| `scenario_matcher.py` | +400 行 | — | **+400** |
| `main.py` | +5 行（import + dispatch 调用） | -316 行 | **-311** |
| `__main__.py` | +1 行 | -15 行 | **-14** |
| `inbox-message-protocol.md` | +30 行 | — | **+30** |
| **合计** | **+436** | **-331** | **+105** |

---

## 5. 导入依赖清单

### 5.1 `scenario_matcher.py` 所需导入

```python
import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import state
from . import message_store as ms
from server.common.config import DATA_DIR, DISPATCH_SENDER_ID, PIPELINE_PM_AGENT_ID
```

### 5.2 `main.py` 新增

```python
from . import scenario_matcher  # 替换 _handle_server_relay
```

### 5.3 `__main__.py` 变更

```python
# 删除:
from .main import ..., _handle_server_relay
# 改为:
from . import scenario_matcher
```

---

## 6. 规则表注册方案

规则注册在 `main.py` 模块加载时执行。有两种方案：

### 方案 A：`main.py` 末尾显式注册（推荐）

```
┌─────────────────────────────┐
│  main.py 模块加载              │
│      │                       │
│      ├─ 定义 handler 回调函数   │
│      ├─ import scenario_matcher │
│      ├─ register_rule() × 10  │
│      └─ ✓ 规则表就绪           │
└─────────────────────────────┘
```

优点：调用方显式注入，无隐式依赖。`__main__.py` 可安全使用。

### 方案 B：`scenario_matcher.py` 内部延迟初始化

在首次 `dispatch()` 调用时通过 module-level 函数填充规则表。调用方只需 `from . import scenario_matcher` 即可使用。

**选择方案 A**，避免隐式初始化带来的意外顺序问题。

---

## 7. 侧效应分析

| 变动 | 侧效应 | 风险 |
|:-----|:-------|:----:|
| 删除 `_handle_server_relay()` | `handler()` L4161 和 `ws_handler()` L95/L106 调用目标需改为 `scenario_matcher.dispatch()` | 🟢 3 处同步替换即可 |
| 删除 `_handle_hash_cmd()` | `##` 命令逻辑全部搬入 scenario_matcher，签名不变 | 🟢 输入输出不变 |
| 删除 `_classify_lobby_message()` | 仅在 `handle_broadcast` 中被调用 1 处（L1796 附近），需改为 `sm.classify_lobby_message()` | 🟢 纯函数 |
| R102 逻辑移入 dispatch | `__main__.py` 中 R102 channel 修正代码可大幅简化 | 🟢 dispatch 入口统一处理 |
| `scenario_matcher` 导入 | 无循环依赖。main.py→sm→state/config/ms，均为纯数据模块 | 🟢 低 |
| **notify_on_complete** | handler 和 ws_handler 的 relay 返回语义不变（True=已处理） | 🟢 零行为变更 |

---

## 8. 不做事项

| # | 事项 | 理由 |
|:-:|:-----|:------|
| ❌ | **不搬业务逻辑函数**（`_handle_hash_start` 等） | 保持 main.py 中的业务逻辑不变 |
| ❌ | **不引入插件/热加载机制** | 规则表静态构建即可 |
| ❌ | **不重构大厅路由** | `handle_broadcast` 中大厅前缀 routing 依赖局部变量，提取收益低 |
| ❌ | **不新增规则** | 只搬现有 10 条规则 |
| ❌ | **不改 protocol 文档的协议定义** | 只加规则优先级映射表 |
| ❌ | **不改动 `_handle_server_query`（!命令）** | `_handle_server_relay` 中仅做 `return False` 透传 |

---

## 9. 验收检查表（22 项）

| # | 验收项 | 验证方式 | 优先级 |
|:-:|:-------|:---------|:------:|
| SC-1 | `scenario_matcher.py` 可导入 | `from . import scenario_matcher` 无 ImportError | 🟢 P0 |
| SC-2 | `_RULES` 按 priority 升序 | `for r in _RULES: assert r.priority >= prev` | 🟢 P0 |
| SC-3 | `test ✅` 回路测试 | 发 `test ✅` → 收回路确认 | 🟢 P0 |
| SC-4 | `to_agent` 派活 | 带 `to_agent` 消息 → 目标 agent 收到 | 🟢 P0 |
| SC-5 | `##status##R125` | 返回管线状态 | 🟢 P0 |
| SC-6 | `##start##R126##task=xxx` | 创建管线 + 派活 | 🟢 P0 |
| SC-7 | `##archive##R125` | 归档已完成管线 | 🟢 P0 |
| SC-8 | `收到 ✅` 转发 PM | PM 收到转发 | 🟢 P0 |
| SC-9 | `已完成 ✅` 推进管线 | Step 自动推进 | 🟢 P0 |
| SC-10 | `退回 🔄` 状态回退 | 触发回退 | 🟢 P0 |
| SC-11 | `失败 ❌` 转发 PM | PM 收到失败通知 | 🟢 P0 |
| LO-1~LO-5 | 大厅前缀分类 | 5 种 `_classify` 返回值正确 | 🟢 P0 |
| RV-1 | 双入口统一 | `handler()` + `ws_handler()` 均调 `sm.dispatch()` | 🟢 P0 |
| RV-2 | 返回语义不变 | `True`=已处理, `False`=未匹配, `!` 透传正常 | 🟢 P0 |
| RV-3 | PM 守卫 | PM 本人发 `_inbox:server` 被拒 | 🟢 P0 |
| DO-1 | 协议文档规则表 | §7 新增优先级映射表 | 🟡 P1 |
| DO-2 | `protocol_ref` 字段 | 每条规则指向协议文档对应章节 | 🟡 P1 |
| DO-3 | 模块 docstring | 含「协议文档见 docs/inbox-message-protocol.md」 | 🟡 P1 |

---

## 10. 执行顺序

| 步骤 | 操作 | 依赖 |
|:----:|:-----|:-----|
| 1 | 创建 `scenario_matcher.py`：HandlerRule + dispatch + register_rule | — |
| 2 | 搬入 `_handle_hash_cmd` → `scenario_matcher.py`（含 2 个帮助块 + 6 条子路由） | 1 |
| 3 | 搬入 `_classify_lobby_message` → `scenario_matcher.py` | 1 |
| 4 | 在 `scenario_matcher.py` 定义 10 条 match 函数 | 1-3 |
| 5 | 在 `main.py` 注册规则表（10 条 HandlerRule，handle 回调指向 main.py 现有函数） | 4 |
| 6 | 替换 `handler()` 中 `_handle_server_relay` 调用为 `sm.dispatch()` | 5 |
| 7 | 删除 `_handle_server_relay()` / `_handle_hash_cmd()` | 6（确认调用已全部替换） |
| 8 | 修改 `__main__.py`：替换 import + 调用 + 简化 R102 | 6 |
| 9 | 更新 `docs/inbox-message-protocol.md` 规则表 | 5 |
| 10 | 全量回归验证（22 项验收表） | 1-9 |
