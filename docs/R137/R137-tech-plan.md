# R137 技术方案 — 引擎分拆轮：main.py 管线逻辑迁入 engine2.py

> **版本：** v1.0
> **日期：** 2026-07-20
> **依据：** [R137 产品需求](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R137/R137-product-requirements.md) · [工作计划](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R137/WORK_PLAN.md)
> **目标基准：** `origin/dev` HEAD（`f53f028`，R136 已完成，main.py 2,180 行）

---

## 目录

1. [方案总览](#1-方案总览)
2. [EXT-A：engine2.py 创建与迁移清单](#2-ext-aengine2py-创建与迁移清单)
3. [EXT-B：scenario_matcher 路由切换](#3-ext-bscenario_matcher-路由切换)
4. [EXT-C：main.py 精简](#4-ext-cmainpy-精简)
5. [循环依赖规避方案](#5-循环依赖规避方案)
6. [engine2.py 完整导出接口](#6-engine2py-完整导出接口)
7. [main.py 清理后预期结构](#7-mainpy-清理后预期结构)
8. [验收表](#8-验收表)
9. [不做事项](#9-不做事项)
10. [执行顺序与注意事项](#10-执行顺序与注意事项)

---

## 1. 方案总览

### 1.1 核心目标

将 main.py 中全部 ~1,200 行管线逻辑迁入新建的 `engine2.py`，`scenario_matcher.py` 路由改指向 `engine2`，main.py 精简至 ~800 行。

### 1.2 迁移原则

```
原位置 main.py:
  def _some_function(...):
      ...  # 完整代码

迁移后 engine2.py:
  def _some_function(...):
      ...  # 完全相同代码（零改动）

原位置 main.py:
  删除该函数定义
```

- **不重命名、不改签名、不合并函数**
- **不改 `state._*` 全局变量引用方式**
- `_ensure_pipeline_manager()` 和 `_ensure_engine()` 保留在 main.py，engine2 用 **函数体内 lazy import** 引用
- `pipeline_engine.py` 本轮不动（两套并行）

### 1.3 迁移步骤

```
Step 1: 创建 engine2.py，逐组搬入 A1~A7 (~1,200行)
Step 2: scenario_matcher 路由切换（from .main → from .engine2）
Step 3: main.py 删除管线代码 + 补 import
每步验证: python3 -c "from server.ws_server import main" + "from server.ws_server import engine2"
```

---

## 2. EXT-A：engine2.py 创建与迁移清单

### 2.1 A1：## 命令处理（6 个函数，~360 行）

| 函数 | 行号范围 | 行数 | 签名 |
|:-----|:--------:|:----:|:-----|
| `_handle_hash_start` | L1602-L1723 | ~122 | `(round_name, kv, agent_id, ws) -> bool` |
| `_handle_hash_status` | L1726-L1802 | ~77 | `(round_name, agent_id, ws) -> bool` |
| `_handle_hash_stop` | L1805-L1830 | ~26 | `(round_name, agent_id, ws) -> bool` |
| `_handle_hash_advance` | L1457-L1510 | ~54 | `(round_name, kv, agent_id, ws) -> bool` |
| `_handle_hash_archive` | L1514-L1542 | ~29 | `(round_name, agent_id, ws) -> bool` |
| `_archive_pipeline` | L1547-L1599 | ~53 | `(round_name) -> None` |

### 2.2 A2：自动调度（4 个函数 + 1 个模块变量，~190 行）

| 对象 | 行号范围 | 行数 | 说明 |
|:-----|:--------:|:----:|:-----|
| `_pending_retries` (dict 声明) | L875 | ~1 | 模块级变量 |
| `_retry_loop` | L877-L909 | ~33 | 后台重试循环 |
| `_enqueue_retry` | L912-L924 | ~13 | 入重试队列 |
| `_auto_dispatch` | L1165-L1277 | ~113 | 自动派活（模板+摘要+card→WS 桥接）|
| `_auto_re_notify` | L1123-L1161 | ~39 | 超时重发派活 |

### 2.3 A3：管线推进（3 个函数，~230 行）

| 函数 | 行号范围 | 行数 | 签名 |
|:-----|:--------:|:----:|:-----|
| `_auto_advance_pipeline` | L221-L341 | ~121 | `(round_name, result) -> str` |
| `_try_advance_pipeline` | L679-L791 | ~113 | `(content, agent_id) -> tuple[bool, str]` |
| `_verify_sha_remote` | L1080-L1120 | ~41 | `(round_name, step_num, sha) -> None` |

### 2.4 A4：通知/驳回（2 个函数，~150 行）

| 函数 | 行号范围 | 行数 | 说明 |
|:-----|:--------:|:----:|:-----|
| `_notify_pm` | L797-L870 | ~74 | PM 队列通知 |
| `_handle_reject` | L1282-L1356 | ~75 | 驳回回退 |

### 2.5 A5：模板/展示（4 个函数 + 3 组常量，~120 行）

| 对象 | 行号范围 | 行数 | 说明 |
|:-----|:--------:|:----:|:-----|
| `_render_template` | L930-L997 | ~68 | 消息模板渲染 |
| `_ROLE_EMOJIS` / `_ROLE_NAMES` / `_URL_FIELDS` | L1010-L1016 | ~7 | 展示常量 |
| `_build_step_summary` | L1019-L1047 | ~29 | Step 前置摘要 |
| `_get_step_agent_name` | L1000-L1006 | ~7 | Agent 名称解析 |
| `_build_rich_templates` | L1411-L1452 | ~42 | 富模板构建 |

### 2.6 A6：工具函数（7 个函数，~150 行）

| 函数 | 行号范围 | 行数 | 说明 |
|:-----|:--------:|:----:|:-----|
| `_extract_artifact_kv` | L651-L673 | ~23 | ##key=value 提取 |
| `_find_archive` | L1053-L1066 | ~14 | 查找已归档轮次 |
| `_fmt_ts` | L1069-L1074 | ~6 | 时间戳格式化 |
| `_build_name_to_ws_map` | L1364-L1371 | ~8 | 名称→WS ID 映射 |
| `_resolve_card_key_to_ws_id` | L1374-L1408 | ~35 | Card Key→WS ID 解析 |
| `_restore_pipeline_timers` | L487-L514 | ~28 | 启动时恢复 timer |
| `_restore_pipeline_dispatches` | L520-L544 | ~25 | 启动时恢复派活 |

### 2.7 A7：engine2.py 顶部 imports

engine2.py 需要以下模块级 imports：

```python
"""R137: Pipeline engine — extracted from main.py.

Contains all pipeline logic: ## commands, auto-dispatch, pipeline advancement,
PM notifications, template rendering, and utility functions.
"""
import asyncio
import json
import logging
import re
import time
import uuid
from typing import Optional

from server.common import auth, config, persistence
from . import state
from . import message_store as ms
from . import task_store as ts
from . import workspace as ws_mod
from . import timeout_tracker
from . import pipeline_sync as pps
from . import agent_card as ac_mod
from .pipeline_context import (
    PipelineContext, PipelineContextManager,
    PipelineStatus, PipelineTaskKind,
)
from .connection_manager import _connections, _send, _send_to_agent
from .pipeline_engine import PipelineEngine
```

注意：`PipelineEngine` 只在 `_ensure_engine()` 中使用（该函数保留在 main.py）。engine2 不需要它——但部分函数读 engine 实例通过 `_ensure_engine()` lazy import 获取。

---

## 3. EXT-B：scenario_matcher 路由切换

### 3.1 当前引用

`scenario_matcher.py` 有 3 处 `from . import main as _main`：

| 位置 | 行号 | 代码 |
|:-----|:----:|:-----|
| `_format_pipeline_status()` | L215 | `from . import main as _main` |
| `_format_pipeline_status()` 内部 | L269, L272, L274, L284 | `_main._ensure_pipeline_manager()`, `_main._ensure_engine()` |
| `handle_hash_cmd()` | L407 | `from . import main as _main` |
| `handle_hash_cmd()` 内部 | L410-L418 | `_main._handle_hash_start(...)`, `_main._handle_hash_status(...)`, etc. |

### 3.2 改为

| 位置 | 行号 | 改后代码 |
|:-----|:----:|:---------|
| `_format_pipeline_status()` | L215 | `from . import engine2 as _e2` |
| L269 | `mgr = _e2._ensure_pipeline_manager()` |
| L272 | `return _e2._ensure_engine().format_context(ctx)` |
| L274 | `archive = _e2._ensure_engine().find_archive(...)` |
| L284 | `mgr = _e2._ensure_pipeline_manager()` |
| `handle_hash_cmd()` | L407 | `from . import engine2 as _e2` |
| L410-L418 | 全部 `_main._handle_hash_*` → `_e2._handle_hash_*` |

**注意：** `_e2._ensure_engine()` 和 `_e2._ensure_pipeline_manager()` 需要 engine2.py 导出（或通过 lazy import 转发）。方案：

```python
# engine2.py
def _ensure_engine():
    from .main import _ensure_engine
    return _ensure_engine()

def _ensure_pipeline_manager():
    from .main import _ensure_pipeline_manager
    return _ensure_pipeline_manager()
```

这样 `scenario_matcher.py` 无需理解哪个函数来自哪个模块——直接 `_e2._ensure_engine()` 即可。

### 3.3 `format_pipeline_context` 的调用链

`_format_pipeline_context`（main.py L414）被 `_format_pipeline_status`（scenario_matcher）引用。  
但这个函数不是 `_handle_hash_*` 管线函数——它是展示格式函数，在 scenario_matcher 的多条规则中用到。

查看 origin/dev：

```
main.py L414-L483: _format_pipeline_context(ctx) → str
```

此函数被 `scenario_matcher.py` 中 `_format_pipeline_status()` 间接调用。  
若 engine2.py 需要它，搬过去。若 main.py 保留它，scenario_matcher 继续通过 `_e2` 引用——但 `_format_pipeline_context` 不是纯管线函数，它输出展示格式，与 `_build_step_summary` 同类。

**决定：** `_format_pipeline_context` 迁入 engine2.py，因为它被 `_handle_hash_status` 调用，是管线查询的一部分。  
需确认：`_format_pipeline_context` 是否只被管线逻辑调用？快速 grep：

```
grep -rn "_format_pipeline_context" server/ws_server/
```

它在 scenario_matcher 中通过 `_main._ensure_engine().format_context()` 调用，而非直接引用函数名。  
所以 engine2.py 需要导出 `_ensure_engine()` 方法供 scenario_matcher 调用 `_e2._ensure_engine().format_context()`。

实际 `format_context()` 是 `PipelineEngine` 类的方法——不需要将 `_format_pipeline_context` 搬到 engine2。  
`_format_pipeline_context`（main.py L414）是一个独立的模块级函数，但我不确定它被谁调用。让我检查：

实际上，它的定义是：
```python
def _format_pipeline_context(ctx: PipelineContext) -> str:
```

如果它被 `_handle_hash_status` 调用（多数情况），搬入 engine2。如果被其他规则回调调用，保留在 main.py 并通过 import 解决。

让开发在实践中确认——技术方案只标注：

> `_format_pipeline_context`（L414-L483，~70 行）— 优先迁入 engine2（与 _handle_hash_status 同级）。  
> 如被 `scenario_matcher.py` 或规则回调直接引用，main.py 保留并通过 `from .engine2 import _format_pipeline_context` 导入。

---

## 4. EXT-C：main.py 精简

### 4.1 删除范围

删除 A1~A6 全部函数（~1,200 行），删除后 main.py 从 L1602-L1805 号段落全部消失。

具体删除区域：

| 区域 | 删除行 | 行数 |
|:-----|:------:|:----:|
| `_auto_advance_pipeline` | L221-L341 | ~121 |
| `_restore_pipeline_timers` | L487-L514 | ~28 |
| `_restore_pipeline_dispatches` | L520-L544 | ~25 |
| `_extract_artifact_kv` | L651-L673 | ~23 |
| `_try_advance_pipeline` | L679-L791 | ~113 |
| `_notify_pm` | L797-L870 | ~74 |
| `_pending_retries` + `_retry_loop` + `_enqueue_retry` | L875-L924 | ~50 |
| `_render_template` + nested `_resolve_step_var` | L930-L997 | ~68 |
| `_get_step_agent_name` | L1000-L1006 | ~7 |
| `_ROLE_EMOJIS`/`_ROLE_NAMES`/`_URL_FIELDS` | L1010-L1016 | ~7 |
| `_build_step_summary` | L1019-L1047 | ~29 |
| `_find_archive` | L1053-L1066 | ~14 |
| `_fmt_ts` | L1069-L1074 | ~6 |
| `_verify_sha_remote` | L1080-L1120 | ~41 |
| `_auto_re_notify` | L1123-L1161 | ~39 |
| `_auto_dispatch` | L1165-L1277 | ~113 |
| `_handle_reject` | L1282-L1356 | ~75 |
| `_build_name_to_ws_map` | L1364-L1371 | ~8 |
| `_resolve_card_key_to_ws_id` | L1374-L1408 | ~35 |
| `_build_rich_templates` | L1411-L1452 | ~42 |
| `_handle_hash_advance` | L1457-L1510 | ~54 |
| `_handle_hash_archive` | L1514-L1542 | ~29 |
| `_archive_pipeline` | L1547-L1599 | ~53 |
| `_handle_hash_start` | L1602-L1723 | ~122 |
| `_handle_hash_status` | L1726-L1802 | ~77 |
| `_handle_hash_stop` | L1805-L1830 | ~26 |
| `_format_pipeline_context` | L414-L483 | ~70 |
| **合计** | | **~1,320** |

### 4.2 保留区域

| 保留区域 | 行号范围 | 行数 | 说明 |
|:---------|:--------:|:----:|:-----|
| docstring + imports | L1-L40 | ~40 | 含 R136 模块 import |
| `_ensure_engine` | L41-L62 | ~22 | **保留** — 用于注入 engine 到 scenario_matcher |
| `_ensure_pipeline_manager` | L63-L67 | ~5 | **保留** — engine2 lazy import |
| `_refresh_role_agent_map` | L74-L96 | ~23 | 保留 |
| `_broadcast_to_channel` | L99-L140 | ~42 | 保留 |
| `_persist_broadcast` | L143-L163 | ~21 | 保留 |
| `_get_agent_display` | L166-L177 | ~12 | 保留 |
| `_ensure_agent_cards_loaded` | L180-L189 | ~10 | 保留 |
| `_ensure_card_watcher` | L192-L206 | ~15 | 保留 |
| `handle_broadcast` | L549-L648 | ~100 | **核心路由 — 保留** |
| `handler()` | L1836-L1910 | ~75 | WS 连接处理 |
| `_sm_handle_*` 回调 | L1913-L2084 | ~172 | 8 个规则回调 |
| 规则注册底部 | L2085-L2180 | ~96 | 8 条 register_rule |
| 新增 import 行 | — | ~20 | `from .engine2 import ...` |
| **合计** | | **~800** | |

### 4.3 main.py 新增 imports

删除管线函数后，main.py 需要从 engine2 重新导入被保留区域调用的函数：

```python
# main.py — 新增 import（放在 R136 模块 import 之后）
from .engine2 import (
    _restore_pipeline_timers,      # handle_broadcast L559 调用
    _restore_pipeline_dispatches,  # handle_broadcast L559 调用
    _format_pipeline_context,      # _sm_handle_query / _sm_handle_step 规则回调引用
    _extract_artifact_kv,          # _ensure_engine L57 注入
    _resolve_card_key_to_ws_id,    # _ensure_engine L52 注入
)
```

**注意：** `_handle_reject` 在 `_sm_handle_reject`（L2029-L2055）中被调用，该回调保留在 main.py：

```python
async def _sm_handle_reject(ws, agent_id, msg, matched) -> bool:
    from . import engine2 as _e2
    return await _e2._handle_reject(msg.get("content", ""), agent_id)
```

但更好的做法：`_sm_handle_reject` 已经在 main.py 中定义为：

```python
async def _sm_handle_reject(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 60: 退回 🔄 → 转发 PM + 回退"""
    return await _handle_reject(msg.get("content", ""), agent_id)
```

删除管线函数后，`_handle_reject` 在 engine2.py 中。所以 main.py 对应改为：

```python
async def _sm_handle_reject(ws, agent_id: str, msg: dict, matched) -> bool:
    from . import engine2 as _e2
    return await _e2._handle_reject(msg.get("content", ""), agent_id)
```

同理检查其他 `_sm_handle_*` 回调中对 engine2 函数的引用。

---

## 5. 循环依赖规避方案

### 5.1 核心风险

```
main.py  →  engine2.py  (模块级: from .engine2 import _restore_pipeline_timers)
engine2.py  →  main.py  (如模块级: from .main import _ensure_pipeline_manager)
                            → 循环依赖: main -> engine2 -> main ❌
```

### 5.2 方案：函数体内 lazy import

engine2.py 中所有涉及 `_ensure_pipeline_manager()` 或 `_ensure_engine()` 调用的函数，**在函数体内延迟 import**：

```python
# engine2.py — 正确做法
def _try_advance_pipeline(content: str, agent_id: str) -> tuple[bool, str]:
    from .main import _ensure_pipeline_manager
    mgr = _ensure_pipeline_manager()
    ...

async def _auto_dispatch(ctx: PipelineContext, step_num: int) -> bool:
    from .main import _ensure_pipeline_manager
    mgr = _ensure_pipeline_manager()
    ...
```

同理，engine2.py 中需要 `_send_to_agent` 或 `_connections` 的地方——这些在 `connection_manager.py` 中，engine2.py 可以直接模块级 import：

```python
# engine2.py 模块级（安全）：
from .connection_manager import _connections, _send, _send_to_agent
# → main.py 不引用 connection_manager，所以 main -> engine2 -> connection_manager 无环
```

### 5.3 哪些函数需要 lazy import？

在执行迁移时，搜索 engine2.py 中所有对 `_ensure_pipeline_manager` 和 `_ensure_engine` 的引用，改为函数体内 lazy import。

参考函数列表（从 origin/dev 确认）：

| engine2 函数 | 调用 `_ensure_pipeline_manager` | 调用 `_ensure_engine` |
|:-------------|:-------------------------------:|:---------------------:|
| `_handle_hash_start` | ✅ | ✅ |
| `_handle_hash_status` | ✅ | ✅ |
| `_handle_hash_stop` | ✅ | |
| `_handle_hash_advance` | ✅ | |
| `_handle_hash_archive` | ✅ | |
| `_auto_dispatch` | ✅ | |
| `_auto_re_notify` | ✅ | |
| `_auto_advance_pipeline` | ✅ | |
| `_try_advance_pipeline` | ✅ | |
| `_verify_sha_remote` | ✅ | |
| `_notify_pm` | ✅ | |
| `_handle_reject` | ✅ | |
| `_verify_git_commit` | | ✅ |
| `_restore_pipeline_timers` | | |
| `_restore_pipeline_dispatches` | ✅ | |
| **_合计** | **14 个函数** | **2 个函数** |

### 5.4 `_ensure_engine()` 转发

scenario_matcher.py 中 `_format_pipeline_status()` 调用 `_main._ensure_engine()`。  
路由切换后调用 `_e2._ensure_engine()`。但 `_ensure_engine()` 在 main.py 中。

engine2.py 定义转发函数：

```python
# engine2.py
def _ensure_engine():
    from .main import _ensure_engine
    return _ensure_engine()

def _ensure_pipeline_manager():
    from .main import _ensure_pipeline_manager
    return _ensure_pipeline_manager()
```

这两个转发函数使用函数体内 lazy import，安全引用 main.py 的原始定义。

---

## 6. engine2.py 完整导出接口

engine2.py 不设 `__all__`，所有迁入函数保持 `_` 前缀。  
模块顶部 imports + 所有函数定义（按 A1~A6 分组）。

### 6.1 scenario_matcher.py 需要的接口

```python
from . import engine2 as _e2

# 被 scenario_matcher.handle_hash_cmd() 调用：
_e2._handle_hash_start(round_name, kv, agent_id, ws)
_e2._handle_hash_status(round_name, agent_id, ws)
_e2._handle_hash_stop(round_name, agent_id, ws)
_e2._handle_hash_advance(round_name, kv, agent_id, ws)
_e2._handle_hash_archive(round_name, agent_id, ws)

# 被 scenario_matcher._format_pipeline_status() 调用：
_e2._ensure_pipeline_manager()
_e2._ensure_engine().format_context(ctx)
_e2._ensure_engine().find_archive(round_name)
```

### 6.2 main.py 需要的接口

```python
from .engine2 import (
    _restore_pipeline_timers,
    _restore_pipeline_dispatches,
    _format_pipeline_context,
    _extract_artifact_kv,
    _resolve_card_key_to_ws_id,
)
```

### 6.3 commands/pipeline.py 需要的接口

`commands/pipeline.py` 直接 import main.py 的函数（`_auto_dispatch`, `_enqueue_retry`, `_handle_reject`, `_notify_pm`, `_auto_advance_pipeline`, `_auto_re_notify`, `_ensure_engine`, `_ensure_pipeline_manager` 等）。  
搬迁后需改为从 engine2 import：

```python
# commands/pipeline.py — 当前从 .main 的 import（需改为 .engine2）
```

需确认 pipeline.py 的所有 import 行。快速 grep：

```bash
grep -n "from \.main import\|from main import" server/ws_server/commands/pipeline.py
```

---

## 7. main.py 清理后预期结构

```
main.py（~800 行）
├── docstring + imports (~40 行)
│   ├── 标准库
│   ├── 内部模块（agent_card, auth, config, state, ...）
│   ├── R136 模块（connection_manager, watchdog, ack_machine, ...）
│   └── R137 engine2 import（_restore_pipeline_timers, ...）
├── 模块级变量（~5 行）
├── _ensure_engine() / _ensure_pipeline_manager()  # ~25 行
├── _refresh_role_agent_map()                       # ~25 行
├── _broadcast_to_channel()                         # ~40 行
├── _persist_broadcast()                            # ~20 行
├── _get_agent_display() / _ensure_agent_cards*()   # ~30 行
├── handle_broadcast()                              # ~100 行
├── handler() (legacy ws handler)                   # ~70 行
├── _sm_handle_* 规则回调（8 个）                     # ~170 行
│   ├── _sm_handle_loopback    → 发回 loopback
│   ├── _sm_handle_to_agent    → 调用 engine2 派活
│   ├── _sm_handle_hash        → scenario_matcher.handle_hash_cmd()
│   ├── _sm_handle_query       → scenario_matcher.handle_query()
│   ├── _sm_handle_step        → scenario_matcher.handle_step()
│   ├── _sm_handle_ack         → 转发 PM
│   ├── _sm_handle_complete    → 转发 PM + auto_advance
│   ├── _sm_handle_reject      → engine2._handle_reject()
│   ├── _sm_handle_fail        → 转发 PM + 告警
│   └── _sm_handle_catchall    → 入库留痕
└── 规则注册（~80 行，8 条 HandlerRule）
```

---

## 8. 验收表

| # | 验收项 | 类型 | 验证方法 |
|:-:|:-------|:----:|:---------|
| EXT-A | `engine2.py` 创建，从 main.py 迁移 ~1,200 行管线逻辑 | P0 | `git diff --stat` |
| EXT-A | `python3 -c "from server.ws_server import engine2"` 无 ImportError | P0 | 终端执行 |
| EXT-B | scenario_matcher `##` 命令路由改指向 engine2 | P0 | 检查 `handle_hash_cmd` 中 `from . import engine2` |
| EXT-B | `_format_pipeline_status()` 改引用 engine2 的 `_ensure_engine()` | P0 | 检查 L215+L269+L272+L274+L284 全部改为 `_e2` |
| EXT-C | main.py 精简至 ~800 行（删除 ~1,200 行管线代码） | P0 | `wc -l main.py` |
| EXT-C | `python3 -c "from server.ws_server import main"` 无 ImportError | P0 | 终端执行 |
| EXT-D | 循环依赖：`main → engine2 → main` 不存在模块级反引 | P0 | 模块加载无 RecursionError |
| T1 | `##start##R137-test##task=dev##steps=2` 正常启动 | P0 | 管线测试 |
| T2 | `##status##R137-test` 正常查询 | P0 | 管线测试 |
| T3 | `##stop##R137-test` 正常停止 | P0 | 管线测试 |
| T4 | 自动派活消息正常送到目标 agent | P0 | 派活测试 |
| T5 | 已完成 ✅ 自动推进正常 | P0 | 完成消息测试 |
| T6 | 退回 🔄 驳回回退正常 | P0 | 驳回测试 |
| T7 | PM 通知正常送达 | P0 | 通知测试 |
| T8 | `handle_broadcast` 非管线消息路由正常 | P0 | 发送测试 |
| T9 | `_inbox:server` 规则 10/20/25/28/30/40/50/60/70/90 路由正常 | P0 | 规则测试 |
| T10 | ACK 状态机正常（pipeline_engine 不受影响） | P1 | ACK 测试 |

---

## 9. 不做事项

| 事项 | 原因 | 归属 |
|:-----|:-----|:----:|
| pipeline_engine.py 的修改 | 两套并行，本轮不动 | R138 |
| 函数重命名 / 参数签名变更 | 零语义改动 | — |
| 合并分叉的 `##start`/`##status`/etc. 实现 | 纯搬迁，不改行为 | R138 |
| 代码优化 / bug 修复 | 零语义改动 | 后续 |
| `_connections` 池化 | 独立工作 | R138 |
| `send_str`/`send` 二选一模式统一 | 已知重复模式 | R138 |

---

## 10. 执行顺序与注意事项

### 10.1 推荐执行步骤

```
Step 1: 创建 engine2.py 文件，写入顶部 imports + 所有 ~1,200 行函数
        → 验证: python3 -c "from server.ws_server import engine2" ✅

Step 2: 修改 scenario_matcher.py
        - L215: from . import main → from . import engine2 as _e2
        - L407: from . import main → from . import engine2 as _e2
        - 所有 _main._handle_hash_* → _e2._handle_hash_*
        - 所有 _main._ensure_engine() → _e2._ensure_engine()
        → 验证: python3 -c "from server.ws_server import scenario_matcher" ✅

Step 3: 修改 main.py
        - 删除 A1~A6 全部 ~1,200 行管线函数
        - 添加 from .engine2 import 需要的函数
        - 检查 _sm_handle_* 回调中 require engine2 的引用
        → 验证: python3 -c "from server.ws_server import main" ✅

Step 4: 检查 commands/pipeline.py 的 import
        - 确认 from .main import 改为 from .engine2 import
        → 验证: python3 -c "from server.ws_server.commands import pipeline" ✅
```

### 10.2 注意事项

1. **`_ensure_engine()` 的 `_send_to_agent` 参数：** `PipelineEngine` 构造函数接收 `send_to_agent=_send_to_agent`（L50）。`_send_to_agent` 现在在 `connection_manager.py` 中，不是 engine2 的一部分。确保 `_ensure_engine()` 保留在 main.py 中时，import 路径仍然是：

```python
# main.py 的 _ensure_engine 中：
from .connection_manager import _send_to_agent, _send
```

2. **`_extract_artifact_kv` 被 `_ensure_engine` 注入：** 若 `_extract_artifact_kv` 搬到 engine2，`_ensure_engine` 中需要 `from .engine2 import _extract_artifact_kv`。注意不要循环依赖。

3. **`commands/pipeline.py` 的 import 变更：** pipeline.py 多处 `from .main import _auto_dispatch, _enqueue_retry, ...`，搬迁后需改为 `from .engine2 import ...`。逐个检查：

```python
# 需检查的 import 组：
from .main import _handle_reject, _notify_pm, _enqueue_retry, _auto_dispatch
from .main import _auto_re_notify, _auto_advance_pipeline, _ensure_pipeline_manager
from .main import _get_step_config, _step_sort_key, _set_pipeline_state
```

4. **`send_str` 在 `handle_broadcast` 中：** L599 附近有 `conn.send_str(broadcast)`，L550-648 保留在 main.py——需确保这段代码完整保留。

5. **`_verify_git_commit`（L375-L411）：** 这个函数可能被管线推进逻辑调用，也可能被其他部分调用。检查 origin/dev 中谁调用了它：

```bash
grep -n "_verify_git_commit" server/ws_server/main.py
```

如仅被 `_auto_advance_pipeline` 调用，迁入 engine2。如需通过 grep 确认，**由开发在实际操作中确认**。

6. **`_format_pipeline_context`（L414-L483）：** 迁入 engine2。被 `_handle_hash_status` 和 scenario_matcher 中的格式化函数调用。main.py 通过 `from .engine2 import _format_pipeline_context` 引用。
