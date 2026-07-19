# R127 技术方案 — 管线状态机提取（PipelineEngine 类）

> **轮次：** R127
> **类型：** 迁移/重构（Genre A — 模块提取）
> **版本：** v1.0
> **日期：** 2026-07-19
> **角色：** 📐 架构师（小开）
> **状态：** ✅ 待审核

---

## §1 概述

将 `server/ws_server/main.py`（当前 4889 行）中的管线状态机逻辑（估 ~2000 行 / 28 个函数 / 5 个数据区域）提取到 `server/ws_server/pipeline_engine.py` 的 `PipelineEngine` 类中。

### 1.1 目标

| 指标 | 提取前 | 提取后 |
|:-----|:------:|:------:|
| `main.py` 行数 | 4889 行 | ~2900 行 |
| `pipeline_engine.py` | — | ~2000 行 |
| 管线函数集中度 | 散落 main.py 39~4795 行 | 全部集中在 `PipelineEngine` 类 |
| 新增 ## 命令 | 需定位 main.py 散落区域 | `PipelineEngine` 加一个方法 |
| 后台任务管理 | 3 处独立启动（__main__.py） | `engine.start()` 统一入口 |
| 单测可行性 | ❌ 依赖全局变量 | ✅ 可构造实例测试 |

### 1.2 设计原则

```
纯搬移，零逻辑改动
├── 不改业务逻辑         → _try_advance / _auto_dispatch 原样搬入
├── 不改 PipelineContext   → 数据模型不动
├── 不改 scenario_matcher  → 只改调用目标
├── 不改命令格式           → ## 命令消息格式零变更
└── 不改 API 接口          → 对外集成面零变更
```

---

## §2 代码侦察结果

### 2.1 main.py 当前结构

```
main.py (4889 行)
┌──────────────────────────────────────────────────────┐
│  1~38     imports                                     │
│  39~465   WS 连接管理 / 认证 / 注册 / 工具            │
│  470~477  _ensure_watchdog()                          │
│  484~492  _ensure_git_scan()                          │
│  494~528  _start_git_sync_loop / _pipeline_git_sync   │  ← F
│  530~546  _ensure_timeout_scanner()                   │
│  549~657  _start_timeout_scan / _pipeline_timeout /   │  ← F
│            _auto_advance_pipeline                     │  ← B
│  658~878  WS handler (handler) 主体 / 广播/通知       │
│  1278~1348 _format_pipeline_context                   │  ← A
│  1351~1412 _restore_pipeline_timers / _dispatches     │  ← F
│  1416~2290 其他业务逻辑（广播/成员/速率限制/看门狗）   │
│  2487~2519 _send_to_agent ★ 关键 WS send 桥接         │
│  2555~2669 _try_advance_pipeline                      │  ← B
│  2673~2747 _notify_pm                                 │  ← E
│  2751~2800 _pending_retries / _retry_loop / _enqueue   │  ← E
│  2806~2895 _render_template / _get_step_agent_name /   │  ← A
│            _build_step_summary                         │
│  2929~2945 _find_archive                              │  ← A
│  2999~3037 _auto_re_notify                            │  ← D
│  3041~3153 _auto_dispatch                             │  ← D
│  3158~3285 _handle_reject                             │  ← E
│  3333~3475 _handle_hash_advance / _archive / _handle   │  ← C
│            _hash_start / _hash_status / _hash_stop     │
│  3478~3585 _handle_hash_start ↕                        │  ← C
│  3602~3710 _handle_hash_status / _handle_hash_stop     │  ← C
│  3712~4610 WS handler 主体 / 路由                      │
│  4619~4795 _sm_handle_* (9 个 scenario matcher handler)│  ← G
│  4798~4889 Rule 注册表                                 │
└──────────────────────────────────────────────────────┘
```

**批次标记：** A=纯数据工具 B=状态推进 C=##命令 D=自动调度 E=通知 F=后台扫描 G=sm_handle

### 2.2 待搬移函数清单（28 个核心 + 7 个 sm_handle 包装器）

| # | 函数 | 行号 | 行数 | 批次 | 依赖 |
|:-:|:-----|:----:|:----:|:----:|:-----|
| 1 | `_start_git_sync_loop` | 494 | 10 | F | — |
| 2 | `_pipeline_git_sync_scan` | 504 | 25 | F | pipeline_context + _auto_advance_pipeline |
| 3 | `_ensure_timeout_scanner` | 530 | 17 | F | config, state |
| 4 | `_start_timeout_scan_loop` | 549 | 10 | F | — |
| 5 | `_pipeline_timeout_scan` | 559 | 98 | F | pipeline_context, _send_to_agent |
| 6 | `_auto_advance_pipeline` | 657 | 122 | B | pipeline_context, _auto_dispatch |
| 7 | `_ensure_pipeline_manager` | 39 | 5 | — | 保留在 main.py（惰性初始化） |
| 8 | `_format_pipeline_context` | 1278 | 70 | A | PipelineContext |
| 9 | `_restore_pipeline_timers` | 1351 | 33 | F | pipeline_context |
| 10 | `_restore_pipeline_dispatches` | 1384 | 28 | F | pipeline_context, _send_to_agent, _enqueue_retry |
| 11 | `_try_advance_pipeline` | 2555 | 115 | B | pipeline_context, _auto_dispatch, _notify_pm, _archive_pipeline, _extract_artifact_kv |
| 12 | `_notify_pm` | 2673 | 75 | E | _send_to_agent, _get_step_agent_name |
| 13 | `_retry_loop` | 2753 | 38 | E | _auto_dispatch, _notify_pm |
| 14 | `_enqueue_retry` | 2788 | 18 | E | _pending_retries |
| 15 | `_render_template` | 2806 | 70 | A | — |
| 16 | `_get_step_agent_name` | 2876 | 19 | A | PipelineContext |
| 17 | `_build_step_summary` | 2895 | 34 | A | PipelineContext |
| 18 | `_find_archive` | 2929 | 16 | A | persistence |
| 19 | `_auto_re_notify` | 2999 | 38 | D | _render_template, _send_to_agent |
| 20 | `_auto_dispatch` | 3041 | 113 | D | _render_template, _get_step_agent_name, _build_step_summary, _send_to_agent, _notify_pm, _enqueue_retry |
| 21 | `_handle_reject` | 3158 | 128 | E | pipeline_context, _notify_pm |
| 22 | `_handle_hash_advance` | 3333 | 57 | C | pipeline_context, _try_advance_pipeline |
| 23 | `_handle_hash_archive` | 3390 | 33 | C | _archive_pipeline |
| 24 | `_archive_pipeline` | 3423 | 55 | C | pipeline_context, _notify_pm |
| 25 | `_handle_hash_start` | 3478 | 124 | C | pipeline_context, _auto_dispatch |
| 26 | `_handle_hash_status` | 3602 | 79 | C | pipeline_context, _find_archive |
| 27 | `_handle_hash_stop` | 3681 | 30 | C | pipeline_context |
| 28 | `_broadcast_workspace_archived` | 4583 | 35 | C | _send |
| 29~35 | `_sm_handle_*` (hash/reject/complete/ack/loopback/to_agent/fail/exclamation/catchall) | 4619~4795 | ~180 | G | 各 handler 转发 |

**小计：28 个核心 + 7 个 sm_handle 包装器 = 35 个函数 → ~2000 行**

### 2.3 关键外部依赖

| 符号 | 类型 | 来源 | 在 engine 中如何访问 |
|:-----|:-----|:-----|:-------------------|
| `state._pipeline_manager` | 模块全局 | `state.py` | 通过 `_ctx_mgr` 属性（初始化时传入） |
| `_connections` | 模块全局 dict | `main.py` | 通过 `send_to_agent` 回调间接访问 |
| `_pending_retries` | 模块全局 dict | `main.py` | 提取为 `self._pending_retries` |
| `_GIT_SYNC_TASK` | 模块全局 Task | `state.py` | 提取为 `self._git_sync_task` |
| `_TIMEOUT_SCAN_TASK` | 模块全局 Task | `state.py` | 提取为 `self._timeout_scan_task` |
| `_TIMEOUT_SCAN_STARTED` | 模块全局 bool | `state.py` | 提取为 `self._timeout_scan_started` |
| `_send_to_agent` | 顶层函数 | `main.py` | 通过构造函数回调传入 |
| `_send` | 顶层函数 | `main.py` | 通过构造函数回调传入 |
| `_extract_artifact_kv` | 顶层函数 | `main.py` | 保持原位（非管线逻辑） |
| `_resolve_card_key_to_ws_id` | 顶层函数 | `main.py` | 通过回调传入 |

---

## §3 PipelineEngine 类 API 设计

### 3.1 类骨架

```python
class PipelineEngine:
    """管线状态机引擎 — 统一管理管线全生命周期。

    职责范围：
    - 管线状态推进（try_advance / auto_advance）
    - 自动调度（dispatch / swap / re_notify）
    - ## 命令处理（start / stop / status / advance / archive）
    - 归档管理（archive / find）
    - PM 通知（notify / retry）
    - 模板渲染（render / summary / agent_name）
    - 后台扫描循环（git sync / timeout / restore）
    - 状态格式化（format_context）

    不包含：
    - WebSocket 连接管理（仍在 main.py）
    - 场景匹配规则（已在 scenario_matcher.py）
    - Git 管线自动启动器（已在 pipeline_auto_starter.py）
    - 管线数据模型（已在 pipeline_context.py）
    """

    def __init__(
        self,
        context_mgr: PipelineContextManager,
        send_to_agent: Callable[[str, dict], Awaitable[int]],
        send_ws: Callable[[Any, dict], Awaitable[None]],
        resolve_card_key: Callable[[str], str | None] = None,
    ):
        ...
```

### 3.2 完整方法签名

#### 🅰️ 数据/工具函数

| 方法 | 签名 | 行数估 | 旧函数 |
|:-----|:-----|:------:|:-------|
| `format_context(ctx, verbose)` | `def format_context(ctx: PipelineContext, verbose: bool = False) -> str` | ~70 | `_format_pipeline_context` |
| `render_template(template, ctx, step_num)` | `def render_template(template: str, ctx: PipelineContext, step_num: int) -> str` | ~70 | `_render_template` |
| `get_step_agent_name(ctx, step_num)` | `def get_step_agent_name(ctx: PipelineContext, step_num: int) -> str` | ~19 | `_get_step_agent_name` |
| `build_step_summary(ctx, step_num)` | `def build_step_summary(ctx: PipelineContext, step_num: int) -> str` | ~34 | `_build_step_summary` |
| `find_archive(round_name)` | `def find_archive(round_name: str) -> dict \| None` | ~16 | `_find_archive` |

#### 🅱️ 状态推进

| 方法 | 签名 | 行数估 | 旧函数 |
|:-----|:-----|:------:|:-------|
| `try_advance(content, agent_id)` | `def try_advance(content: str, agent_id: str) -> tuple[bool, str]` | ~115 | `_try_advance_pipeline` |
| `auto_advance(round_name, result)` | `async def auto_advance(round_name: str, result: dict) -> str` | ~122 | `_auto_advance_pipeline` |

#### 🅲 ## 命令

| 方法 | 签名 | 行数估 | 旧函数 |
|:-----|:-----|:------:|:-------|
| `handle_hash_start(round_name, kv, agent_id, ws)` | `async def handle_hash_start(round_name: str, kv: dict, agent_id: str, ws) -> bool` | ~124 | `_handle_hash_start` |
| `handle_hash_status(round_name, agent_id, ws)` | `async def handle_hash_status(round_name: str, agent_id: str, ws) -> bool` | ~79 | `_handle_hash_status` |
| `handle_hash_stop(round_name, agent_id, ws)` | `async def handle_hash_stop(round_name: str, agent_id: str, ws) -> bool` | ~30 | `_handle_hash_stop` |
| `handle_hash_advance(round_name, kv, agent_id, ws)` | `async def handle_hash_advance(round_name: str, kv: dict, agent_id: str, ws) -> bool` | ~57 | `_handle_hash_advance` |
| `handle_hash_archive(round_name, agent_id, ws)` | `async def handle_hash_archive(round_name: str, agent_id: str, ws) -> bool` | ~33 | `_handle_hash_archive` |

#### 🅳 自动调度

| 方法 | 签名 | 行数估 | 旧函数 |
|:-----|:-----|:------:|:-------|
| `auto_dispatch(ctx, step_num)` | `async def auto_dispatch(ctx: PipelineContext, step_num: int) -> bool` | ~113 | `_auto_dispatch` |
| `auto_re_notify(ctx, step_key, step_num)` | `async def auto_re_notify(ctx, step_key: str, step_num: int) -> None` | ~38 | `_auto_re_notify` |

#### 🅴 通知/排队

| 方法 | 签名 | 行数估 | 旧函数 |
|:-----|:-----|:------:|:-------|
| `notify_pm(ctx, step_num, status, detail)` | `async def notify_pm(ctx: PipelineContext, step_num: int, status: str, detail: str = "") -> None` | ~75 | `_notify_pm` |
| `handle_reject(content, sender_agent_id)` | `async def handle_reject(content: str, sender_agent_id: str) -> None` | ~128 | `_handle_reject` |
| `enqueue_retry(ctx, step_num)` | `def enqueue_retry(ctx: PipelineContext, step_num: int) -> None` | ~18 | `_enqueue_retry` |
| `_retry_loop` | `async def _retry_loop() -> None` | ~38 | `_retry_loop` |

#### 🅵 后台扫描 + 生命周期

| 方法 | 签名 | 行数估 | 旧函数 |
|:-----|:-----|:------:|:-------|
| `start()` | `def start() -> None` | ~30 | 新建（聚合启动） |
| `stop()` | `def stop() -> None` | ~10 | 新建 |
| `pipeline_git_sync_scan()` | `async def _pipeline_git_sync_scan() -> None` | ~25 | `_pipeline_git_sync_scan` |
| `pipeline_timeout_scan(timeout_min)` | `async def _pipeline_timeout_scan(timeout_min: int) -> None` | ~98 | `_pipeline_timeout_scan` |
| `restore_pipeline_timers()` | `async def restore_pipeline_timers() -> None` | ~33 | `_restore_pipeline_timers` |
| `restore_pipeline_dispatches()` | `async def restore_pipeline_dispatches() -> None` | ~28 | `_restore_pipeline_dispatches` |
| `broadcast_workspace_archived(ws_id, ...)` | `async def broadcast_workspace_archived(ws_id: str, ...) -> None` | ~35 | `_broadcast_workspace_archived` |

---

## §4 集成方案

### 4.1 数据流图

```
┌───────────────────────────┐
│      __main__.py          │
│                           │
│  engine = PipelineEngine( │
│    context_mgr,           │
│    send_to_agent,         │ ← _send_to_agent (传引用)
│    send_ws,               │ ← _send (传引用)
│  )                        │
│  engine.start()           │ ← 统一启动后台扫描
│                           │
│  # 之前：                  │
│  # _restore_pipeline_...  │ → engine.restore_...()
│  # _retry_loop()          │ → engine._retry_loop()
└──────────┬────────────────┘
           │
           ▼
┌───────────────────────────┐
│   pipeline_engine.py      │
│   (PipelineEngine)        │
│                           │
│  ┌─ auto_dispatch ──────┐ │
│  │ send_to_agent(...)   │─┼─→ main.py 维护的 WS 连接池
│  │ notify_pm(...)       │ │
│  └──────────────────────┘ │
│                           │
│  ┌─ handle_hash_* ──────┐ │
│  │ send_ws(...)          │─┼─→ 直接回复 WS 消息
│  └──────────────────────┘ │
│                           │
│  ┌─ state ──────────────┐ │
│  │ _pending_retries     │ │  ← 内部状态，不暴露 main.py
│  │ _git_sync_task       │ │
│  │ _timeout_scan_task   │ │
│  └──────────────────────┘ │
└───────────────────────────┘
           │
           ▼
┌───────────────────────────┐
│    scenario_matcher.py    │
│                           │
│  handle_hash_cmd() ──────┼─→ engine.handle_hash_*(...)
│  _sm_handle_reject ──────┼─→ engine.handle_reject(...)
│  _sm_handle_complete ────┼─→ engine.try_advance(...)
│                           │
│  # 之前:                  │
│  # from .main import      │
│  #   _handle_hash_start   │ → engine 实例
└───────────────────────────┘
           │
           ▼
┌───────────────────────────┐
│  pipeline_auto_starter.py │
│                           │
│  _auto_start_pipeline()   │
│    └─ engine.auto_dispatch│ ← 替换直接调用 _auto_dispatch
└───────────────────────────┘
```

### 4.2 改动点一览

| 文件 | 操作 | 变化 | 行数估 |
|:-----|:------|:-----|:------:|
| `pipeline_engine.py` | **新建** | PipelineEngine 类，含所有管线函数 | **+2000** |
| `main.py` | 修改 | 移除 28 个函数 + 7 个 sm_handle 包装器 | **-2000** |
| `main.py` | 修改 | 新增 `engine: PipelineEngine` 属性 + 初始化代码 | **+50** |
| `main.py` | 修改 | 移除 `_pending_retries` / `_GIT_SYNC_TASK` / `_TIMEOUT_*` 等模块级状态 | **-5** |
| `scenario_matcher.py` | 修改 | `handle_hash_cmd` 中 `from .main import _handle_hash_*` → `engine.*` | **~30** |
| `__main__.py` | 修改 | 后台启动改为 `engine.start()` + `engine.restore_*()` | **~30** |
| `pipeline_auto_starter.py` | 修改 | `from .main import _auto_dispatch` → `engine.auto_dispatch` | **~10** |
| **合计净增** | | | **~0** |

### 4.3 import 迁移清单

#### main.py 中移除的 import（因函数搬走不再需要）

| 当前 import | 用途 | 去向 |
|:------------|:-----|:-----|
| `from .pipeline_context import PipelineContextManager, PipelineStatus, PipelineTaskKind, PipelineContext` | 保留（仍需 `_ensure_pipeline_manager`） | 不移除 |
| `from . import pipeline_sync as pps` | `_pipeline_git_sync_scan` 中调用 | → `pipeline_engine.py` |
| `from . import message_store as ms` | `_auto_dispatch` 中 `ms.save_message` | → `pipeline_engine.py` |
| `from . import state` | 全局变量访问 | → `pipeline_engine.py`（self 管理） |
| `from server.common import config` | 配置读取 | 保留（main 和 engine 都需要） |

#### pipeline_engine.py 新增 import

```python
import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from server.common import config, persistence
from . import message_store as ms
from . import pipeline_sync as pps
from .pipeline_context import PipelineContext, PipelineContextManager, PipelineStatus

logger = logging.getLogger("ws-bridge.pipeline_engine")
```

### 4.4 传参方式选择

**方案 A（推荐）：构造函数传回调**

```python
class PipelineEngine:
    def __init__(self, context_mgr, send_to_agent, send_ws, resolve_card_key=None):
        self._ctx_mgr = context_mgr
        self._send_to_agent = send_to_agent  # async (target_id, payload) → int
        self._send_ws = send_ws              # async (ws, data) → None
        self._resolve_card_key = resolve_card_key  # (key) → str | None
```

理由：
- 零循环 import 依赖（main.py 传函数引用，engine 不 import main.py）
- 易于单测（mock 回调即可）
- 与 scenario_matcher 的 `HandlerRule` 模式一致

**方案 B（否决）：engine import main.py**

```python
# pipeline_engine.py
from . import main as _main  # ❌ 导致循环 import
```

否决理由：`main.py` 将 import `pipeline_engine`，导致循环依赖。

### 4.5 __main__.py 改造

```python
# 当前（提取前）
from .main import _restore_pipeline_dispatches, _retry_loop

app.on_startup.append(lambda _: asyncio.create_task(_retry_loop()))
app.on_startup.append(lambda _: _restore_pipeline_dispatches())

# 提取后
engine = PipelineEngine(
    context_mgr=_ensure_pipeline_manager(),
    send_to_agent=_send_to_agent,
    send_ws=_send,
)
engine.start()  # 统一启动后台扫描 + 恢复

app.on_startup.append(lambda _: asyncio.create_task(engine._retry_loop()))
app.on_startup.append(lambda _: engine.restore_pipeline_dispatches())
```

### 4.6 scenario_matcher.py 改造

当前 `handle_hash_cmd` 通过 `from .main import _handle_hash_*` 动态引用（运行时 import）。

改造后，scenario_matcher 需要通过 main.py 传入 engine 引用：

```python
# main.py — 注入 engine
_sm.engine = engine

# scenario_matcher.py — 使用 engine
async def handle_hash_cmd(ws, agent_id, msg, matched):
    ...
    return await engine.handle_hash_start(round_name, kv, agent_id, ws)
```

或使用回调注册模式给 scenario_matcher 注入 engine。

---

## §5 搬移步骤

### Step 1: 创建 pipeline_engine.py 骨架

```python
class PipelineEngine:
    def __init__(self, context_mgr, send_to_agent, send_ws, resolve_card_key=None):
        ...

    # —— 以下每个方法是空方法体 + 原函数 docstring，交给 Dev 填充 ——
    def format_context(self, ctx, verbose=False): ...
    def render_template(self, template, ctx, step_num): ...
    def get_step_agent_name(self, ctx, step_num): ...
    def build_step_summary(self, ctx, step_num): ...
    def find_archive(self, round_name): ...
    def try_advance(self, content, agent_id): ...
    async def auto_advance(self, round_name, result): ...
    async def handle_hash_start(self, round_name, kv, agent_id, ws): ...
    async def handle_hash_status(self, round_name, agent_id, ws): ...
    async def handle_hash_stop(self, round_name, agent_id, ws): ...
    async def handle_hash_advance(self, round_name, kv, agent_id, ws): ...
    async def handle_hash_archive(self, round_name, agent_id, ws): ...
    async def auto_dispatch(self, ctx, step_num): ...
    async def auto_re_notify(self, ctx, step_key, step_num): ...
    async def notify_pm(self, ctx, step_num, status, detail=""): ...
    async def handle_reject(self, content, sender_agent_id): ...
    def enqueue_retry(self, ctx, step_num): ...
    async def _retry_loop(self): ...
    async def _pipeline_git_sync_scan(self): ...
    async def _pipeline_timeout_scan(self, timeout_min): ...
    async def restore_pipeline_timers(self): ...
    async def restore_pipeline_dispatches(self): ...
    async def broadcast_workspace_archived(self, ws_id, ...): ...
    def start(self): ...
    def stop(self): ...
```

### Step 2-5: 按优先级分批搬移

| 批次 | 函数 | 数量 | 验证 | 搬移后 main.py 需改 |
|:----:|:-----|:----:|:-----|:-------------------|
| A | 纯数据工具（format/render/agent/summary/find） | 5 | py_compile | 替换调用 + 移除函数 |
| B | 状态推进（try_advance/auto_advance） | 2 | py_compile + 运行时 | 替换调用 |
| C | ## 命令（5 个 handler + archive + broadcast） | 7 | 运行时 | 替换调用 |
| D | 自动调度（dispatch/re_notify） | 2 | 运行时 | 替换调用 |
| E | 通知/重试（notify/reject/enqueue/retry_loop） | 4 | 运行时 | 替换调用 + 移除 _pending_retries |
| F | 后台扫描（git_sync/timeout/restore*） | 5 | 启动验证 | 替换调用 |
| G | sm_handle 包装器（7 个）+ __main__.py 改造 | 9 | py_compile + 启动 | 移除包装器 + 改 __main__ |

---

## §6 副作用分析

### 6.1 已知依赖链

| 搬移函数 | 依赖的 main.py 符号 | 处理方式 |
|:---------|:-------------------|:---------|
| `_auto_dispatch` | `_send_to_agent`, `_render_template`, `_get_step_agent_name`, `_build_step_summary`, `_notify_pm`, `_enqueue_retry`, `_resolve_card_key_to_ws_id` | 全部搬入 engine → 内部 self.xxx 调用 |
| `_try_advance_pipeline` | `_ensure_pipeline_manager`, `_extract_artifact_kv`, `_auto_dispatch`, `_notify_pm`, `_archive_pipeline` | `_ensure_pipeline_manager` → `self._ctx_mgr`；`_extract_artifact_kv` 保持原位（不是管线函数） |
| `_notify_pm` | `_send_to_agent`, `_get_step_agent_name` | 全部搬入 engine |
| `_auto_advance_pipeline` | `_auto_dispatch` | 全部搬入 engine |
| `_pipeline_timeout_scan` | `_send_to_agent`, `_ensure_pipeline_manager` | `_send_to_agent` 通过回调；`_ctx_mgr` 为属性 |

### 6.2 不能搬入 engine 的函数

| 函数 | 行号 | 理由 |
|:-----|:----:|:-----|
| `_ensure_pipeline_manager` | 39 | 被 main.py 中 WS 连接管理部分也使用；保留为惰性初始化 |
| `_send_to_agent` | 2487 | 依赖 `_connections` 全局 dict（WS 连接管理） |
| `_send` | 59 | 底层 WS send 工具，被大量非管线代码使用 |
| `_extract_artifact_kv` | 2527 | 通用工具函数，与管线无关 |
| `_resolve_card_key_to_ws_id` | 3250 | 与 WS 连接管理耦合 |
| `_ensure_git_scan` | 484 | 在 handler 初始化时调用，不搬入 |
| `_ensure_watchdog` | 470 | 看门狗逻辑，不属于管线状态机 |

### 6.3 状态隔离

| 当前模块状态 | 新位置 | 说明 |
|:------------|:-------|:-----|
| `state._pipeline_manager` | `self._ctx_mgr` | 构造函数传入，engine 不管理生命周期 |
| `state._GIT_SYNC_TASK` | `self._git_sync_task` | engine 内部管理 |
| `state._TIMEOUT_SCAN_TASK` | `self._timeout_scan_task` | engine 内部管理 |
| `state._TIMEOUT_SCAN_STARTED` | `self._timeout_scan_started` | engine 内部管理 |
| `_pending_retries` (module-level) | `self._pending_retries` | engine 内部管理 |

### 6.4 零变更保证

| 保证项 | 验证方式 |
|:-------|:---------|
| 消息格式零变更 | 所有 `##` 命令的 content 格式不变 |
| 业务逻辑零变更 | 搬移过程中不改任何 if/else 条件、正则、计算 |
| API 零变更 | scenario_matcher / pipeline_auto_starter 对外接口不变 |
| config 零变更 | `ENABLE_GIT_SYNC` / `AUTO_DISPATCH_ENABLED` 等配置项不变 |
| PipelineContext 零变更 | 数据模型字段不变，序列化格式不变 |

---

## §7 验收标准

### PE-N: Pipeline Engine 提取（P0 × 11 | P1 × 0）

| 编号 | 描述 | 验证方式 |
|:----|:-----|:---------|
| PE-1 | `pipeline_engine.py` 存在且可 import `from ..pipeline_engine import PipelineEngine` | `py_compile` |
| PE-2 | `PipelineEngine` 所有方法签名与旧函数签名一致 | 手动对照 + grep |
| PE-3 | `main.py` 中所有管线函数引用替换为 `self._engine.*` | `grep -c "_handle_hash\|_try_advance\|_auto_dispatch\|_notify_pm" main.py` = 0 |
| PE-4 | `##start##R127-test##task=...` 创建管线并返回成功 | 运行时测试 |
| PE-5 | `##status##R127-test` 返回管线状态 | 运行时测试 |
| PE-6 | `##stop##R127-test` 停止管线 | 运行时测试 |
| PE-7 | `##advance##R127-test##step=2` 推进 step | 运行时测试 |
| PE-8 | `##archive##R127-test` 归档管线 | 运行时测试 |
| PE-9 | `engine.try_advance()` 正确处理 `✅ 完成` 信号 | 运行时测试 |
| PE-10 | `engine.auto_dispatch()` 正确发送派活消息 | 运行时测试 |
| PE-11 | `engine.notify_pm()` 正确发送 PM 通知 | 运行时测试 |

### RV-N: 回归验证（P0 × 5 | P1 × 0）

| 编号 | 描述 | 验证方式 |
|:----|:-----|:---------|
| RV-1 | `py_compile` 全量零错误 | `python -m py_compile server/ws_server/*.py` |
| RV-2 | 启动后所有后台扫描循环正常 | 日志确认 |
| RV-3 | `scenario_matcher.dispatch()` 调用 `engine.handle_hash_*` 正常工作 | 运行时 |
| RV-4 | `PipelineAutoStarter` 调用 `engine.auto_dispatch` 正常工作 | 运行时 |
| RV-5 | R126 已提取的 `scenario_matcher` 不受影响 | 回归测试 |

### 验收计数

| 分组 | P0 | P1 |
|:-----|:--:|:--:|
| PE Pipeline Engine | 11 | 0 |
| RV 回归验证 | 5 | 0 |
| **合计** | **16** | **0** |

---

## §8 不做事项

| # | 事项 | 理由 |
|:-:|:-----|:------|
| ❌ | 不改任何业务逻辑 | 纯搬移，零逻辑改动 |
| ❌ | 不改 PipelineContext 数据模型 | 已在 pipeline_context.py 稳定运行多轮 |
| ❌ | 不改 PipelineAutoStarter | 只改 dispatch_fn 的传参方式 |
| ❌ | 不改 scenario_matcher 规则定义 | 只改 handle callback 的调用目标 |
| ❌ | 不优化/重构管线业务逻辑 | 虽然 3000 行中有优化空间，但本轮只搬不移 |
| ❌ | 不提取非管线函数 | 广播/通知/成员管理/工作区等留待后续 |
| ❌ | 不加新功能 | 不新增 ##resume / ##skip 等命令 |
| ❌ | 不提取 _ensure_git_scan / _ensure_watchdog | 与 WS 初始化流程耦合 |

---

## §9 文件改动清单

| 操作 | 文件 | 估算 |
|:----|:-----|:----:|
| ✅ 新建 | `server/ws_server/pipeline_engine.py` | ~2000 行 |
| ✅ 修改 | `server/ws_server/main.py` | -1990 净删（移除 28+7 函数，加 50 行 init） |
| ✅ 修改 | `server/ws_server/scenario_matcher.py` | ~30 行（改调用目标） |
| ✅ 修改 | `server/ws_server/__main__.py` | ~30 行（改启动方式） |
| ✅ 修改 | `server/ws_server/pipeline_auto_starter.py` | ~10 行（改 dispatch_fn 传参） |
| ❌ 不碰 | `server/ws_server/pipeline_context.py` | — |
| ❌ 不碰 | `server/ws_server/task_card.py` | — |
| ❌ 不碰 | `server/ws_server/state.py` | — |

---

## §10 与 R126 的关系

```
main.py (4889 行)
  │
  ├─ R126 → scenario_matcher.py (260 行)    ← 已合入 main ✅
  │     规则表 + 调度引擎 + match_* 纯函数
  │
  ├─ R127 → pipeline_engine.py (~2000 行)   ← 本轮
  │     PipelineEngine + 35 个管线函数
  │
  └─ 剩余 → main.py (~2900 行)              ← 后续轮次
        WS 连接 + 广播 + 成员管理 + 工具函数
```

R126 与 R127 正交。R126 的 `handle_hash_cmd` 目前通过 `from .main import _handle_hash_*` 调用旧函数，R127 提取后改为 `engine.handle_hash_*`。两者合入顺序无关，最终形态即如上图。

---

*文档结束 — 技术方案版本 v1.0*
