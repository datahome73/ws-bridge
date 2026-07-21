# R139 技术方案 — main.py 规则回调+注册提取

> **起草人：** 小开 (Arch)
> **版本：** v1.0
> **日期：** 2026-07-21
> **依据：** [R139 产品需求](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R139/R139-product-requirements.md) | [WORK_PLAN](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R139/WORK_PLAN.md)

---

## 1. 可行性结论

**✅ 可行。** 创建 `server/ws_server/scenario_rules.py` 独立模块，将 main.py L469-L735（8 个 `_sm_handle_*()` 回调 + 10 条规则注册）逐字迁移。循环依赖可以通过函数体内 lazy import 避免（scenario_matcher.py 已有先例：L297 `from .main import _connections`）。

| 维度 | 结论 | 依据 |
|:-----|:-----|:------|
| 依赖分析 | ✅ 无循环依赖 | 全部回调依赖可拆分为：顶部直接 import + 函数体内 lazy import |
| 行数 | ✅ 净增 ~5 行 | -266 + 270 + 1 ≈ +5 行（纯提取，零行为变更） |
| 行为等价 | ✅ 逐字迁移 | 函数体、注册顺序、模块接口全不变 |
| 兼容性 | ✅ 无公共 API 变动 | `_sm_handle_*()` 不是外部接口，全部在注册链内部使用 |

---

## 2. 依赖分析

### 2.1 scenario_rules.py 的 import 策略

所有依赖按来源分组，明确每个的引入方式：

| 依赖 | 来源模块 | 引入方式 | 说明 |
|:-----|:---------|:---------|:------|
| `uuid`, `time`, `logging`, `asyncio` | stdlib | 顶部 `import` | 标准库，无循环风险 |
| `_send` | `connection_manager` | 顶部 `from .connection_manager import _send` | 无依赖 main，安全 |
| `_send_to_agent` | `connection_manager` | 顶部 `from .connection_manager import _send_to_agent` | 同上 |
| `_is_valid_agent_id` | `connection_manager` | 顶部 `from .connection_manager import _is_valid_agent_id` | 同上 |
| `ms.save_message` | `message_store` | 顶部 `from . import message_store as ms` | 无依赖 main |
| `state.SYSTEM_AGENT_ID`, `state._r72_users` | `state` | 顶部 `from . import state` | 纯数据层 |
| `config.DISPATCH_SENDER_ID`, `config.PIPELINE_PM_AGENT_ID`, `config.DATA_DIR` | `server.common.config` | 顶部 `from server.common import config` | 公共配置 |
| `_ensure_engine()`, `_ensure_pipeline_manager()` | `main` | 函数体内 `from .main import _ensure_engine, _ensure_pipeline_manager` | ⚠️ **lazy import** — 避免循环依赖 |
| `_sm.match_*`, `_sm.register_rule()`, `_sm.HandlerRule` | `scenario_matcher` | 函数体内 `from . import scenario_matcher as _sm` | ⚠️ **lazy import** — 在 `register_all_rules()` 内部 |

### 2.2 循环依赖分析

```
main.py  ──from .scenario_rules import register_all_rules──▶  scenario_rules.py
   ▲                                                            │
   │                                                            │ function体内:
   │                     from .main import _ensure_engine       │
   └────────────────────────────────────────────────────────────┘
```

**结论：无循环风险。** `register_all_rules()` 被 main.py 在 **module level** 调用（import 完成之后），而 `_ensure_engine` 仅在回调函数体内 lazy import。Python 在函数体执行前不会解析该 import，此时 main 模块已完全加载。

执行时序：
1. Python 加载 `main.py` → 执行顶部 import → 遇到 `from .scenario_rules import register_all_rules` → 加载 `scenario_rules.py`
2. `scenario_rules.py` 执行顶部 import（stdlib + connection_manager + message_store + state + config — 全部无 main 依赖）
3. `scenario_rules.py` 定义回调函数（包含函数体内的 `from .main import _ensure_engine` — **此时仅定义，不执行**）
4. 控制权回到 `main.py` → 调用 `register_all_rules()` → 此时 main 已完全加载 → 函数体内的 `from .main import _ensure_engine` 安全执行

### 2.3 现有先例验证

scenario_matcher.py 已有 3 处函数体内 `from .main import ...`：

| 位置 | 代码 | 状态 |
|:----|:-----|:----:|
| L297 | `from .main import _connections` | ✅ 运行中 |
| L327 | `from .main import _connections` | ✅ 运行中 |
| _format_pipeline_status | `main_mod._ensure_pipeline_manager()` | 🔴 L515 传参 `_main` 未定义（待修复）|

---

## 3. 详细改动

### 3.1 新增 `server/ws_server/scenario_rules.py`（~270 行）

**文件结构：**

```python
# -*- coding: utf-8 -*-
"""R139 EXT: Scenario rules — extracted from main.py L469-L735.

Contains _sm_handle_*() callbacks for scenario_matcher rules
plus register_all_rules() to register them.
"""
import asyncio
import logging
import time
import uuid

from .connection_manager import _send, _send_to_agent, _is_valid_agent_id
from . import message_store as ms
from . import state
from server.common import config

logger = logging.getLogger("ws-bridge")

# ── 8 个回调函数（逐字迁移自 main.py L469-L735）──

async def _sm_handle_loopback(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 10: test ✅ loopback."""
    # ...逐字复制自 main.py L469-L484...

async def _sm_handle_to_agent(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 20: to_agent dispatch routing."""
    # ...逐字复制自 main.py L487-L520...

async def _sm_handle_hash(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 30: ## commands → scenario_matcher.handle_hash_cmd."""
    from . import scenario_matcher as _sm
    return await _sm.handle_hash_cmd(ws, agent_id, msg, matched)

async def _sm_handle_query(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 25: ##query commands → scenario_matcher.handle_query."""
    from . import scenario_matcher as _sm
    return await _sm.handle_query(ws, agent_id, msg, matched)

async def _sm_handle_step(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 28: ##step commands → scenario_matcher.handle_step."""
    from . import scenario_matcher as _sm
    return await _sm.handle_step(ws, agent_id, msg, matched)

async def _sm_handle_ack(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 40: 收到 ✅ / ACK ✅ → forward to PM."""
    # ...逐字复制自 main.py L538-L553...

async def _sm_handle_complete(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 50: 已完成 ✅ / ✅ 完成 → forward PM + auto-confirm + advance."""
    from .main import _ensure_engine  # 函数体内 lazy import
    # ...逐字复制自 main.py L556-L582...

async def _sm_handle_reject(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 60: 退回 🔄 → forward PM + auto-confirm + rollback."""
    from .main import _ensure_engine  # 函数体内 lazy import
    # ...逐字复制自 main.py L585-L609...

async def _sm_handle_fail(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 70: 失败 ❌ → forward PM + auto-confirm."""
    # ...逐字复制自 main.py L612-L635...

async def _sm_handle_catchall(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 90: no match → store silently."""
    # ...逐字复制自 main.py L638-L657...


# ── 规则注册函数（封装原本 main.py L660-L735 的 module-level 注册代码）──

def register_all_rules() -> None:
    """Register all scenario rules with lazy import of scenario_matcher."""
    from . import scenario_matcher as _sm  # 函数体内 import，防循环

    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_loopback, handle=_sm_handle_loopback,
        priority=10, name="回路测试", protocol_ref="§7.1",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_to_agent, handle=_sm_handle_to_agent,
        priority=20, name="to_agent派活路由", protocol_ref="§7.2",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_query, handle=_sm_handle_query,
        priority=25, name="##query命令", protocol_ref="§R131",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_step, handle=_sm_handle_step,
        priority=28, name="##step命令", protocol_ref="§R132",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_hash_cmd, handle=_sm_handle_hash,
        priority=30, name="##命令路由", protocol_ref="§7.3",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_ack, handle=_sm_handle_ack,
        priority=40, name="ACK转发", protocol_ref="§7.5",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_complete, handle=_sm_handle_complete,
        priority=50, name="完成确认", protocol_ref="§7.6",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_reject, handle=_sm_handle_reject,
        priority=60, name="退回回退", protocol_ref="§7.7",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_fail, handle=_sm_handle_fail,
        priority=70, name="失败告警", protocol_ref="§7.8",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_catchall, handle=_sm_handle_catchall,
        priority=90, name="入库留痕", protocol_ref="§7.10",
    ))
```

### 3.2 main.py 修改：删除 L469-L735 + 追加 2 行

**删除内容：**
- `_sm_handle_loopback` (L469-L484)
- `_sm_handle_to_agent` (L487-L520)
- `_sm_handle_hash` (L523-L525)
- `_sm_handle_query` (L528-L530)
- `_sm_handle_step` (L533-L535)
- `_sm_handle_ack` (L538-L553)
- `_sm_handle_complete` (L556-L582)
- `_sm_handle_reject` (L585-L609)
- `_sm_handle_fail` (L612-L635)
- `_sm_handle_catchall` (L638-L657)
- `from . import scenario_matcher as _sm` (L662 — 因为 handler() 已使用 `_sm.dispatch()` 但通过 L428 引用)
- 全部 10 条 `_sm.register_rule(...)` 调用 (L664-L735)

**关键确认：** L662 的 `from . import scenario_matcher as _sm` 也在删除范围内，但需要确认 handler() 函数中 `_sm.dispatch()` 的引用。查看 L428：

```python
if await _sm.dispatch(ws, agent_id, msg):
```

`_sm` 在 L662 的 `from . import scenario_matcher as _sm` 中定义。删除 L662 后，需要在 main.py 顶部（或其他位置）添加替代 import。最佳位置：**追加在 L21 `from . import state` 之后** — 作为顶部模块级 import。

> ⚠️ 重要：删除 L662 的 `from . import scenario_matcher as _sm` 后，需要在 main.py 顶部添加 `from . import scenario_matcher as _sm`（追加在 L22 `from . import state` 之后），否则 handler() L428 的 `_sm.dispatch()` 会 NameError。**这是需求文档未提及的关键隐式依赖。**

**追加内容（main.py 文件末尾）：**

```python
from .scenario_rules import register_all_rules
register_all_rules()
```

**净效果：** 736 → 736 - 267(删除) + 1(顶部_sm import) + 2(底部注册) = **~472 行**

### 3.3 scenario_matcher.py 修复：L515 `_main` bug

```python
# 当前（bug ❌）：
elif sub_cmd == "status":
    reply = await _format_pipeline_status(params, _main)
    await _send_reply(ws, agent_id, reply)

# 修复后（✅）：
elif sub_cmd == "status":
    from . import main as _main_lazy
    reply = await _format_pipeline_status(params, _main_lazy)
    await _send_reply(ws, agent_id, reply)
```

| 修复项 | 当前 | 修复后 | 触发路径 |
|:-------|:-----|:-------|:---------|
| L515 `_main` 未定义 | `_main` 从未定义 | `from . import main as _main_lazy` | `##status` or `##query##status` 命令 |

### 3.4 README.md 更新

**§1 模块清单：** 新增 `scenario_rules.py` 行，更新 `main.py` 行数 2,197→472：

```diff
 ws_server/                                      行数  说明
 ├── __init__.py                                    1  包声明
 ├── __main__.py                                  417  aiohttp 入口 + HTTP API 端点
-├── main.py                                    2,197  消息路由 + ## 命令 + 模板渲染
+├── main.py                                      472  消息路由核心（纯净路由层）
+├── scenario_rules.py                            270  规则回调 + 注册（R139 提取）
```

**§4 模块关联图：** 更新 main.py 模块块描述，`scenario_rules.py` 作为独立框出现在 main.py 下方：

```
┌─────────────────── main.py ──────────────────────┐
│  handle_broadcast() — inbox 投递器 (~78 行)       │
│  handler() — WS 消息分发                          │
│  (不再包含规则回调和注册代码)                       │
│  import: connection_manager / scenario_rules      │
└─────────────────────┬─────────────────────────────┘
                      │ register_all_rules()
                      ▼
┌───────────── scenario_rules.py ───────────────────┐
│  _sm_handle_*() 回调 × 8                          │
│  register_all_rules() — 注册 10 条 HandlerRule     │
│  import: connection_manager / state / message_store│
│  lazy import: main / scenario_matcher              │
└───────────────────────────────────────────────────┘
```

**§9 main.py 重构进度：** 更新 `_sm_handle_*()` 回调 + 规则注册状态为 ✅ 完成：

| 阶段 | 状态 | 说明 |
|:----:|:----:|:------|
| ... | ... | ... |
| `_sm_handle_*()` 回调 + 规则注册统一 | ✅ R139 完成 | 提取到 `scenario_rules.py` |

---

## 4. 执行计划（分步操作）

### Step 3 (Dev — 爱泰)

| # | 操作 | 文件 | 行数变化 |
|:-:|:-----|:-----|:--------:|
| 1 | 创建 `scenario_rules.py` | 🆕 `server/ws_server/scenario_rules.py` | +270 |
| 2 | main.py 删除 L469-L735（含 `from . import scenario_matcher as _sm` at L662）| ✂️ `main.py` | -267 |
| 3 | main.py 顶部 L21 之后追加 `from . import scenario_matcher as _sm` | 📝 `main.py` | +1 |
| 4 | main.py 底部追加 `from .scenario_rules import register_all_rules; register_all_rules()` | 📝 `main.py` | +2 |
| 5 | scenario_matcher.py L515 修复 `_main` → lazy import | 🔧 `scenario_matcher.py` | +1(物理)，~0(净) |
| 6 | README.md 更新模块清单 + §9 重构进度 | 📝 `README.md` | ~±5 |

**净行数变化：** +270 - 267 + 1 + 2 + 1 ≈ **+7 行**（含 import 和注释）

### 代码执行顺序（防止 NameError）

1. **先做第 2 步之前：** main.py L428 使用 `_sm.dispatch()`，L662 删了后必须在顶部补 import
2. 因此 **Step 3-4（顶补 import + 底加注册）** 需要在 **Step 2（删除）同一批提交中**完成
3. scenario_matcher.py 修复（Step 5）和 README.md（Step 6）独立，不依赖其他变更

### 推荐提交顺序

```
commit 1: 创建 scenario_rules.py
   └─ server/ws_server/scenario_rules.py (new)

commit 2: main.py 修改 + scenario_matcher.py 修复
   ├─ server/ws_server/main.py (删除 + 顶部补import + 底部注册)
   └─ server/ws_server/scenario_matcher.py (L515 _main → lazy import)

commit 3: README.md 更新
   └─ server/ws_server/README.md
```

---

## 5. 验收检查表

| # | 验收项 | 验证方法 | 类型 | 依赖 |
|:-:|:-------|:---------|:----:|:----:|
| C1 | `from server.ws_server import main` 无 ImportError | `python3 -c "from server.ws_server import main"` | P0 | commit 1-2 |
| C2 | `from server.ws_server import scenario_rules` 无 ImportError | `python3 -c "from server.ws_server import scenario_rules"` | P0 | commit 1 |
| C3 | `from server.ws_server import scenario_matcher` 无 ImportError | `python3 -c "from server.ws_server import scenario_matcher"` | P0 | commit 2 |
| C4 | `from server.ws_server import *` 全部模块无错误 | 16 模块 `import` | P0 | commit 1-2 |
| T1 | `test ✅` 回路测试正常 | 发 test ✅ → 收到回路回复 | P0 | commit 2 |
| T4 | `##query##status` 不再报 NameError | `##status##R{N}` → 正常显示 | P0 | commit 2 |
| R1 | scenario_rules.py 回调与 main.py 原版逐字一致 | diff 审查 | P0 | commit 1 |
| R2 | main.py 顶部 import 无循环依赖 | python -c import | P0 | commit 2 |
| R3 | 规则注册顺序与原版完全一致 | 10→20→25→28→30→40→50→60→70→90 | P0 | commit 1 |

---

## 6. 不做事项

| ❌ 不做 | 原因 |
|:--------|:-----|
| 重命名 `_sm_handle_*()` 函数 | 保持接口不变，零行为变更 |
| 修改 match 函数签名（`_sm.match_*`） | 不影响匹配逻辑 |
| 统一/优化 ACK/完成/退回的重复 PM 通知代码 | 纯提取轮，不重构不优化 |
| 修改 scenario_matcher.dispatch() 逻辑 | 规则表路由不变 |
| 修改 handle_broadcast() 路由逻辑 | 不变 |
| 修改 handler() WS 消息分发 | 不变 |
| 修改 `_sm` 变量名（main.py 和 scenario_matcher.py 均用 `_sm`）| 保持命名一致 |

---

## 7. 侧效应分析

| 侧效应 | 概率 | 影响 | 应急预案 |
|:-------|:----:|:-----|:---------|
| `_sm` 在 L662 删除后 handler() L428 NameError | **高** | P0 阻断 | **已在 4. 执行计划中预置修复**：顶部补 import |
| callback 函数体内 `from .main import _ensure_engine` 执行时 main 未完全加载 | 低 | 运行时 ImportError | 确认 register_all_rules() 在 main 最后被调用 |
| scenario_rules.py 内部 `_sm` 变量与 main.py 的 `_sm` 冲突 | 无 | — | 两个模块作用域独立，无冲突 |
| main.py 原 L662 `_sm = scenario_matcher` 引用在其他模块 | 无 | — | `_sm` 仅在 main.py 内部使用 |

---

> **审核记录：**
> - v1.0 提交审核
> - ⚠️ 关键发现：需求文档未提及 main.py L662 的 `from . import scenario_matcher as _sm` 是 handler() L428 `_sm.dispatch()` 的依赖，删除后必须在顶部补 import
> - 结论：⬜ 待审核
