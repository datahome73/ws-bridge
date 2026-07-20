# R138 技术方案 — 引擎合并轮：engine2.py 吞并 pipeline_engine.py

> **版本：** v1.0
> **日期：** 2026-07-20
> **依据：** [R138 产品需求](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R138/R138-product-requirements.md) · [工作计划](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R138/WORK_PLAN.md)
> **目标基准：** `origin/dev` HEAD（`2ba0856`，R137 已完成）

---

## 目录

1. [现状分析](#1-现状分析)
2. [合并策略](#2-合并策略)
3. [MERGE-A：以 engine2.py 为主体重写 pipeline_engine.py](#3-merge-a以-engine2py-为主体重写-pipeline_enginepy)
4. [MERGE-B：吸收旧 pipeline_engine.py 的有用功能](#4-merge-b吸收旧-pipeline_enginepy-的有用功能)
5. [MERGE-C：B-5 修复确认](#5-merge-cb-5-修复确认)
6. [MERGE-D：删除 engine2.py](#6-merge-d删除-engine2py)
7. [import 变更清单](#7-import-变更清单)
8. [新 pipeline_engine.py 预期结构](#8-新-pipeline_enginepy-预期结构)
9. [验收表](#9-验收表)
10. [不做事项](#10-不做事项)
11. [执行顺序与注意事项](#11-执行顺序与注意事项)

---

## 1. 现状分析

### 1.1 三个文件的角色

| 文件 | 行数 | 角色 |
|:-----|:----:|:-----|
| `main.py` | 736 | WS 通信协议 + `_ensure_engine()` 注入 |
| `engine2.py` | 1,544 | 已验证的管线模块级函数（31 函数 + 2 转发器 + 4 常量） |
| `pipeline_engine.py` | 1,319 | PipelineEngine class（30+ 方法，精简版实现） |

### 1.2 函数对照表

| 功能组 | engine2.py 函数 | pipeline_engine.py 方法 | 选择 |
|:-------|:----------------|:-------------------------|:-----|
| 自动推进 | `_auto_advance_pipeline()` | `auto_advance()` | 用 **engine2**（已验证） |
| 步骤推进 | `_try_advance_pipeline()` | `try_advance()` | 🚨 **不同实现** → 见 §4.2 |
| 自动调度 | `_auto_dispatch()` | `auto_dispatch()` | 🚨 **不同实现** → 见 §4.3 |
| 重发派活 | `_auto_re_notify()` | `auto_re_notify()` | 🚨 **不同实现** → 见 §4.4 |
| 驳回 | `_handle_reject()` | `handle_reject()` | 🚨 **不同实现** → 见 §4.5 |
| ## start | `_handle_hash_start()` | `handle_hash_start()` | 用 **engine2** |
| ## status | `_handle_hash_status()` | `handle_hash_status()` | 用 **engine2** |
| ## stop | `_handle_hash_stop()` | `handle_hash_stop()` | 用 **engine2** |
| ## advance | `_handle_hash_advance()` | `handle_hash_advance()` | 用 **engine2** |
| ## archive | `_handle_hash_archive()` / `_archive_pipeline()` | `handle_hash_archive()` / `archive_pipeline()` | 用 **engine2** |
| 模板渲染 | `_render_template()` | `render_template()` | 🚨 不同实现 → engine2 有 `_resolve_step_var` 嵌套 |
| Step 摘要 | `_build_step_summary()` | `build_step_summary()` | 🚨 不同实现 |
| Agent 名 | `_get_step_agent_name()` | `get_step_agent_name()` | 相同 |
| 归档查找 | `_find_archive()` | `find_archive()` | 相同 |
| PM 通知 | `_notify_pm()` | `notify_pm()` | 🚨 不同实现 |
| 重试队列 | `_retry_loop()` / `_enqueue_retry()` | `_retry_loop()` / `enqueue_retry()` | 用 **engine2** |
| context 格式 | `_format_pipeline_context()` | `format_context()` | 🚨 不同实现 → 见 §4.6 |
| 提取 kv | `_extract_artifact_kv()` | 无（通过构造注入） | 用 engine2 |
| Card→WS ID | `_resolve_card_key_to_ws_id()` | 无（通过构造注入 `resolve_card_key`）| 用 engine2 |
| 后台 git 扫描 | 无 | `_ensure_git_scan()` + `_start_git_sync_loop()` + `_pipeline_git_sync_scan()` | ✅ 保留旧版（注入 class） |
| 后台超时扫描 | 无 | `_ensure_timeout_scanner()` + `_start_timeout_scan_loop()` + `_pipeline_timeout_scan()` | ✅ 保留旧版（注入 class） |
| 启动恢复 | 无 | `restore_pipeline_timers()` + `restore_pipeline_dispatches()` | ✅ 保留旧版（注入 class） |
| 任务状态更新 | 无 | `_cmd_task_update()` | ✅ 保留（被 auto_advance 使用） |
| 工作区归档广播 | 无 | `broadcast_workspace_archived()` | ✅ 保留（被 archive 使用） |
| 转发器 | `_ensure_engine()` / `_ensure_pipeline_manager()` | 无 | ✅ 保留为 class 方法或模块函数 |

### 1.3 关键差异：状态引用方式

| 维度 | engine2.py | pipeline_engine.py |
|:-----|:-----------|:-------------------|
| 函数签名 | `def _auto_dispatch(ctx, step_num)` — ctx 参数传入 | `def auto_dispatch(self, ctx, step_num)` — self + ctx |
| state 引用 | 直接 `state._PIPELINE_STATE` | 通过 `self._ctx_mgr` |
| 派活消息模板 | `ctx.message_templates.get(next_step_key)` — **需要模板** | `self.render_template(template, ctx, step_num)` — **有默认回退** |
| _pending_retries | 模块级全局 `_pending_retries: dict` | 实例属性 `self._pending_retries` |

---

## 2. 合并策略

### 2.1 核心原则

1. **PipelineEngine class 必须保留** — `main.py`、`scenario_matcher.py`、`__main__.py` 都通过 `_ensure_engine()` 获取 `PipelineEngine` 实例调用方法
2. **以 engine2.py 的已验证代码为主** — 逻辑差异选择以 engine2 版本为准（已验证通过 60/60 测试）
3. **吸收旧版有用功能** — 旧版中 engine2 没有的功能（`format_context`、`_cmd_task_update`、`broadcast_workspace_archived`、`start()/stop()`、后台扫描循环引用）整合进新 class
4. **不重命名、不改签名** — `_ensure_engine()` 仍返回 PipelineEngine 实例，外部调用不变
5. **消除 B-5 PM fallback** — 以确保选中 engine2 版本的 auto_dispatch

### 2.2 函数保留决策矩阵

| 功能 | engine2 版本 | pipeline_engine 版本 | 最终采用 |
|:-----|:------------|:---------------------|:---------|
| auto_advance_pipeline | ✅ 已验证 | 有差异 | **engine2** |
| try_advance | ✅ 已验证（旧版不同） | 有 `_extract_artifact_kv` 回调、output 构建 | **engine2 为主，吸收旧版的 output 构建** |
| auto_dispatch | ✅ 已验证（需模板） | 有默认模板回退 | **engine2 为主，吸收默认模板回退** |
| auto_re_notify | ✅ 已验证 | 相似 | **engine2** |
| handle_reject | ✅ 已验证 | 相似 | **engine2** |
| render_template | ✅ 有 `_resolve_step_var` | 简化版 | **engine2** |
| build_step_summary | ✅ 有 `_URL_FIELDS` | 有 | **engine2** |
| format_context | — | `format_context()` 方法 | **保留旧版 class 方法** |
| _cmd_task_update | — | 旧版唯一 | **保留旧版** |
| broadcast_workspace_archived | — | 旧版唯一 | **保留旧版** |
| git/超时扫描 | 无（git_sync_scheduler + pipeline_timeout 模块） | class 方法 | **保留旧版 class 方法**（调用 git_sync_scheduler 等模块） |
| restore_pipeline_timers/dispatches | `_restore_pipeline_timers()` / `_restore_pipeline_dispatches()`（模块函数）| `restore_pipeline_timers()` / `restore_pipeline_dispatches()`（class 方法，调用 git_sync_scheduler）| **旧版 class 方法 + engine2 模块级函数共存**（class 方法包装模块函数） |

---

## 3. MERGE-A：以 engine2.py 为主体重写 pipeline_engine.py

### 3.1 操作步骤

```
1. git checkout -b r138-merge origin/dev
2. 将 engine2.py 全部内容复制为 pipeline_engine.py（临时覆盖）
3. 在 pipeline_engine.py 中嵌入 PipelineEngine class
4. 将 engine2 的模块级函数包装为 class 方法（或 class 直接引用模块函数）
5. 加入旧版有用功能
6. 删除 engine2.py
7. 更新 import
```

### 3.2 PipelineEngine class 集成方式

新 `pipeline_engine.py` 的结构：

```python
"""R138: Unified pipeline engine — merged from engine2.py + pipeline_engine.py."""
import asyncio
import json
import logging
import re
import time
import uuid
from typing import Optional, Callable, Awaitable, Any
from dataclasses import dataclass

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

logger = logging.getLogger("ws-bridge.pipeline_engine")

# ── 模块级常量 ──
_ROLE_EMOJIS = {1: "📋", 2: "📐", 3: "💻", 4: "👁", 5: "🧪", 6: "🚢"}
_ROLE_NAMES = {1: "PM", 2: "Arch", 3: "Dev", 4: "Review", 5: "QA", 6: "Ops"}
_URL_FIELDS = {
    "tech_plan_url": "技术方案", "review_url": "审查报告",
    "test_report_url": "测试报告", "test_summary": "测试结果",
    "requirements_url": "需求文档", "work_plan_url": "工作计划",
}
_pending_retries: dict[str, dict] = {}
# ── 转发器（供 scenario_matcher 调用） ──
def _ensure_engine():
    from .main import _ensure_engine
    return _ensure_engine()
def _ensure_pipeline_manager():
    from .main import _ensure_pipeline_manager
    return _ensure_pipeline_manager()


class PipelineEngine:
    """统一管线引擎 — engine2.py 的函数 + PipelineEngine 生命周期。"""

    def __init__(self, ...):
        ...  # 保留旧版 __init__ 签名

    def start(self) -> None:
        self._ensure_git_scan()
        self._ensure_timeout_scanner()

    def stop(self) -> None:
        ...  # 取消后台任务

    # ── 模块函数包装为方法 ──
    async def auto_advance(self, round_name, result):
        return await _auto_advance_pipeline(round_name, result)

    def try_advance(self, content, agent_id):
        return _try_advance_pipeline(content, agent_id)

    async def auto_dispatch(self, ctx, step_num):
        return await _auto_dispatch(ctx, step_num)
    ...
```

### 3.3 包装模式 vs 函数搬入

两种方式：

**方案 A（推荐）：直接引用模块函数** — class 方法是一行包装器

```python
class PipelineEngine:
    async def auto_dispatch(self, ctx, step_num):
        return await _auto_dispatch(ctx, step_num)
    
    def try_advance(self, content, agent_id):
        return _try_advance_pipeline(content, agent_id)
```

优点：engine2 代码不需修改函数签名，import 自动指向同模块函数  
缺点：self 中的回调（`self._send_to_agent`, `self._ctx_mgr`）不能被模块函数使用

**方案 B：把 engine2 函数搬进 class 并改用 self 访问** — 修改函数体

```python
class PipelineEngine:
    async def _auto_dispatch(self, ctx, step_num):
        # 改为 self._send_to_agent 而不是全局 _send_to_agent
        ...
```

优点：class 完全自包含  
缺点：需要修改已验证的函数体，增加回归风险

**推荐：方案 A（包装器模式）** — 模块函数保持不变，class 为薄包装层。  
对于需要 `self._ctx_mgr` 或 `self._send_to_agent` 的函数（如 `_auto_dispatch`、`_try_advance`），需要在包装时处理：

```python
# 模块级函数（从 engine2 原样保留）：
def _try_advance_pipeline(content: str, agent_id: str) -> tuple[bool, str]:
    from .main import _ensure_pipeline_manager
    mgr = _ensure_pipeline_manager()
    ...  # 使用 mgr 操作，不依赖 self

# class 方法包装：
class PipelineEngine:
    def try_advance(self, content, agent_id):
        return _try_advance_pipeline(content, agent_id)
```

这里的关键是 engine2 函数用 `lazy import _ensure_pipeline_manager()` 替代 `self._ctx_mgr`，所以即使包装后也能正常工作。

---

## 4. MERGE-B：吸收旧 pipeline_engine.py 的有用功能

### 4.1 保留的功能

| 功能 | 方法名 | 行号 | 说明 |
|:-----|:-------|:----:|:-----|
| 生命周期 | `start() / stop()` | L120-L138 | 统一启动/停止后台扫描 |
| 任务状态更新 | `_cmd_task_update()` | L139-L169 | `_auto_advance_pipeline` 中使用 |
| 上下文格式化 | `format_context()` | L170-L239 | 管线状态展示 |
| 默认模板回退 | `auto_dispatch()` 中 | L882-L886 | engine2 版本缺失这点 |
| 工作区归档广播 | `broadcast_workspace_archived()` | L819-L839 | `_archive_pipeline` 中使用 |
| 后台 git 扫描 | `_ensure_git_scan()` / `_start_git_sync_loop()` / `_pipeline_git_sync_scan()` | L1109-L1145 | 被 `handle_broadcast` 和 `start()` 调用 |
| 后台超时扫描 | `_ensure_timeout_scanner()` / `_start_timeout_scan_loop()` / `_pipeline_timeout_scan()` | L1146-L1265 | 被 `handle_broadcast` 和 `start()` 调用 |

### 4.2 `try_advance` 差异处理

engine2 的 `_try_advance_pipeline()`（L363-L478，~116 行）和旧版 `PipelineEngine.try_advance()`（L338-L404，~67 行）的主要差异：

| 方面 | engine2 版本 | pipeline_engine 版本 |
|:-----|:------------|:---------------------|
| 正则匹配 | `r"已完成 ✅ R(\d+) Step (\d+)"` | `r"(?:已完成\|完成)\s*[✅✔️]\s*R(\d+)\s*[Ss]tep\s*(\d+)"` |
| artifact 提取 | 手动 `re.finditer(r"##(\w+)=([^#]+)", content)` | 通过 `self._extract_artifact_kv()` 回调 |
| output 构建 | 简单赋值 | 完整的 output dict（含 sha, tech_plan_url 等字段） |
| advance | 推进 + `_auto_dispatch` | 推进 + `self.auto_dispatch` |

**采用 engine2 版本为主，吸收旧版的优点：**
- 使用旧版的宽松正则（容错 `✅`/`✔️`、已完成/完成）
- 保留旧版的完整 output 构建逻辑（通过 `_extract_artifact_kv` 回调 → engine2 模块函数）
- 保留旧版的 `Step Info` 更新逻辑（output / result_msg / status = done）

### 4.3 `auto_dispatch` 差异处理 → B-5 修复

engine2 的 `_auto_dispatch()`（L856-L972，~117 行）和旧版 `PipelineEngine.auto_dispatch()`（L845-L911，~67 行）的主要差异：

| 方面 | engine2 版本 | pipeline_engine 版本 |
|:-----|:------------|:---------------------|
| AUTO_DISPATCH_ENABLED=0 时 | 打印模拟日志 + 返回 False | 直接返回 False（无日志） |
| 模板查找 | `ctx.message_templates.get(next_step_key)` — 找不到返回 False | `ctx.message_templates.get()` — 找不到用默认模板 fallback |
| 消息风格 | 仅渲染模板 | 模板回退到 "💻 **R{N} Step {N}** — {name}\n\n{summary}\n\n请完成..." |
| target_agent_id | 从 step_info 取 `agent_id` | 同上 |
| 自刷检查 | **有**（不允许向自己的收件箱发消息） | **无** |
| sender_name | 构建 sender_name | 直接 `from_name=pm_name` |
| 离线连接 | 直接返回 False（sent=0） | enqueue_retry + 返回 False |
| PM 通知派活 | 调用 `_notify_pm` | 调用 `self.notify_pm()` |

**采用 engine2 版本，吸收旧版的默认模板回退：**

```python
# 新 pipeline_engine.py 的 _auto_dispatch():
# 核心使用 engine2 版本（已验证）
# 差异点：当 ctx.message_templates 无匹配时，使用旧版的默认模板 fallback
rendered = _render_template(next_template, ctx, step_num) if next_template else (
    f"💻 **{round_name} Step {step_num}** — {agent_name}\\n\\n"
    f"{summary}\\n\\n"
    f"请完成当前步骤后回复：已完成 ✅ {round_name} Step {step_num}"
)
```

### 4.4 `auto_re_notify` 差异

两版基本一致，用 engine2 版。

### 4.5 `handle_reject` 差异

两版基本同（正则略有不同），用 engine2 版（已验证）。

### 4.6 `format_context` 差异

engine2 的 `_format_pipeline_context()`（L200-L274，~75 行）和旧版 `PipelineEngine.format_context()`（L170-L239，~70 行）。

主要差异是 `format_context` 是 PipelineEngine 的方法，通过 `self._ctx_mgr.get()` 访问。而 engine2 的 `_format_pipeline_context` 是模块函数，通过 `_ensure_pipeline_manager()` 访问。

保留旧版 `format_context()` 作为 class 方法（被 `_handle_hash_status` 和 `scenario_matcher._format_pipeline_status()` 调用）。  
同时保留 `_format_pipeline_context()` 模块函数（通过 lazy import 供其他模块用）。

### 4.7 后台扫描的调用链

当前调用链：

```
handle_broadcast → engine._ensure_git_scan()  → 旧 PipelineEngine._ensure_git_scan()
                 → engine._ensure_timeout_scanner()  → 旧 PipelineEngine._ensure_timeout_scanner()
                 → engine.restore_pipeline_timers()  → 旧 PipelineEngine.restore_pipeline_timers()

__main__.py → engine._retry_loop()  → 旧 PipelineEngine._retry_loop()
            → engine.restore_pipeline_dispatches()  → 旧 PipelineEngine.restore_pipeline_dispatches()
```

**合并后：** class 的 `_ensure_git_scan` / `_ensure_timeout_scanner` / `restore_pipeline_timers` 等继续作为 class 方法，内部实现可以调用已提取的模块（`git_sync_scheduler.py` / `pipeline_timeout.py`）或保持原样。

注意：旧版 `PipelineEngine` 的 `_ensure_git_scan()` 和 R136 的 `git_sync_scheduler._ensure_git_scan()` 功能重叠。合并时确认 class 方法调用正确的实现。

---

## 5. MERGE-C：B-5 修复确认

### 5.1 B-5 根因追溯

需求文档描述的 B-5 bug：

```python
# 旧 pipeline_engine.py L826-L833:
if not target_agent_id:
    if self._resolve_card_key:
        target_agent_id = self._resolve_card_key(config.PIPELINE_PM_AGENT_ID or "")
    if not target_agent_id:
        target_agent_id = config.PIPELINE_PM_AGENT_ID
```

**但当前 origin/dev 的 `pipeline_engine.auto_dispatch()`（L864-L874）已无此代码**——它只有 `return False`。

可能原因：
1. 需求文档描述的 bug 位于旧版 `auto_dispatch` 的不同代码路径（已通过补丁修复）
2. bug 位于另一个函数（如 `handle_reject` 或 `try_advance` 中的 PM fallback）

### 5.2 确认要点

| 检查点 | 现状 | 确认 |
|:-------|:-----|:-----|
| `auto_dispatch()` 无 PM fallback | ✅ 已 `return False` | 已确认 |
| `auto_dispatch()` 没有 `self._resolve_card_key` 用于 agent_id 回退 | ✅ 未使用 | 已确认 |
| `_try_advance()` 无 PM fallback | ✅ 无 | 已确认 |
| `_handle_reject()` 无 PM fallback | ✅ 无 | 已确认 |
| `handle_hash_start()` 无 PM fallback | ✅ 无 | 已确认 |

### 5.3 合并后的 B-5 防护

采用 engine2 版的 `_auto_dispatch()` 自动确保 B-5 不再出现。在 `auto_dispatch` 包装器中补充日志：

```python
class PipelineEngine:
    async def auto_dispatch(self, ctx, step_num):
        result = await _auto_dispatch(ctx, step_num)
        if not result:
            logger.info("[B-5 fix] auto_dispatch 返回 False — 无 PM fallback 风险")
        return result
```

---

## 6. MERGE-D：删除 engine2.py

### 6.1 删除操作

```bash
git rm server/ws_server/engine2.py
```

### 6.2 engine2.py 被引用的位置（需全部更新）

所有引用 engine2.py 的文件和行号：

| 文件 | 位置 | 当前代码 | 改为 |
|:-----|:-----|:---------|:-----|
| `main.py` | L48 | `from .engine2 import _resolve_card_key_to_ws_id, _extract_artifact_kv` | `from .pipeline_engine import _resolve_card_key_to_ws_id, _extract_artifact_kv` |
| `scenario_matcher.py` | L215 | `from . import engine2 as _e2` | `from . import pipeline_engine as _e2` |
| `scenario_matcher.py` | L266 | `from . import engine2 as _e2` | `from . import pipeline_engine as _e2` |
| `scenario_matcher.py` | L407 | `from . import engine2 as _e2` | `from . import pipeline_engine as _e2` |
| `scenario_matcher.py` | L503 | `from . import engine2 as _e2` | `from . import pipeline_engine as _e2` |

### 6.3 删除后验证

```bash
# 应成功
python3 -c "from server.ws_server import main"
python3 -c "from server.ws_server import pipeline_engine"
python3 -c "from server.ws_server import scenario_matcher"
python3 -c "from server.ws_server import commands.pipeline"

# 应报 ImportError（确认删除）
python3 -c "from server.ws_server import engine2"
# ModuleNotFoundError: No module named 'server.ws_server.engine2'
```

---

## 7. import 变更清单

### 7.1 `main.py` 变更

**当前：**
```python
# L31:
from .pipeline_engine import PipelineEngine
# L48（在 _ensure_engine 函数体内）:
from .engine2 import _resolve_card_key_to_ws_id, _extract_artifact_kv
```

**改为：**
```python
# L31: 不变
from .pipeline_engine import PipelineEngine
# L48: engine2 → pipeline_engine（路径不变，因为 engine2 代码迁入 pipeline_engine）
from .pipeline_engine import _resolve_card_key_to_ws_id, _extract_artifact_kv
```

不需要额外改动，因为 `pipeline_engine.py` 将包含 engine2 的全量函数。

### 7.2 `scenario_matcher.py` 变更

**当前（4 处）：**
```python
from . import engine2 as _e2
```

**改为：**
```python
from . import pipeline_engine as _e2
```

只需替换 4 行 import 语句。所有 `_e2._handle_hash_*`, `_e2._ensure_engine()`, `_e2._ensure_pipeline_manager()` 调用保持不变——因为新 pipeline_engine.py 会导出这些函数和转发器。

### 7.3 `__main__.py` — 无变更

当前 `__main__.py` 引用：
```python
from .main import _ensure_engine
engine = _ensure_engine()
await engine._retry_loop()
await engine.restore_pipeline_dispatches()
```

不直接引用 engine2。`_ensure_engine()` 在 main.py 中不变，所以无变更。

### 7.4 `commands/pipeline.py` — 无变更

当前通过 lazy import 引用 `..main`：
```python
from ..main import _ensure_pipeline_manager
```

不直接引用 engine2。`_ensure_pipeline_manager()` 保留在 main.py，所以无变更。

### 7.5 `engine2.py` 自身的 `from .pipeline_engine import PipelineEngine`（L36）

engine2.py 的模块级 import `from .pipeline_engine import PipelineEngine` 在新 pipeline_engine.py 中必须删除（文件不能 import 自身）。

新 pipeline_engine.py 中，`PipelineEngine` class 是本文件定义的——不需要 import。将 class 定义和模块函数放在同一个文件中即可。

---

## 8. 新 pipeline_engine.py 预期结构

```
pipeline_engine.py（~1,600 行）
├── docstring + imports（~40 行）
│   ├── 标准库
│   ├── 内部模块（state, config, agent_card, ...）
│   └── connection_manager（_connections, _send, _send_to_agent）
├── 模块级常量（~10 行）
│   ├── _ROLE_EMOJIS / _ROLE_NAMES / _URL_FIELDS
│   └── _pending_retries
├── 转发器（~10 行）
│   ├── _ensure_engine()
│   └── _ensure_pipeline_manager()
├── ═══ engine2 模块级函数 ═══（~1,100 行，从 engine2.py 原样保留）
│   ├── _auto_advance_pipeline()
│   ├── _verify_git_commit()
│   ├── _format_pipeline_context()
│   ├── _restore_pipeline_timers()
│   ├── _restore_pipeline_dispatches()
│   ├── _extract_artifact_kv()
│   ├── _try_advance_pipeline()
│   ├── _notify_pm()
│   ├── _retry_loop() / _enqueue_retry()
│   ├── _render_template() + _resolve_step_var()
│   ├── _get_step_agent_name() / _build_step_summary()
│   ├── _find_archive() / _fmt_ts()
│   ├── _verify_sha_remote()
│   ├── _auto_re_notify() / _auto_dispatch()
│   ├── _handle_reject()
│   ├── _build_name_to_ws_map() / _resolve_card_key_to_ws_id()
│   ├── _build_rich_templates()
│   ├── _handle_hash_advance / _handle_hash_archive / _archive_pipeline
│   ├── _handle_hash_start / _handle_hash_status / _handle_hash_stop
│   └──（共 31 个模块函数）
├── ═══ PipelineEngine class ═══（~400 行）
│   ├── __init__(...)           # 保留旧版签名（construct注入）
│   ├── start() / stop()        # 生命周期
│   ├── _cmd_task_update()      # 任务状态更新
│   ├── format_context()        # 上下文格式化（class 方法）
│   ├── render_template()       # 包装 _render_template
│   ├── get_step_agent_name()   # 包装 _get_step_agent_name
│   ├── build_step_summary()    # 包装 _build_step_summary
│   ├── find_archive()          # 包装 _find_archive
│   ├── try_advance()           # 包装 _try_advance_pipeline（含旧版 output 构建增强）
│   ├── auto_advance()          # 包装 _auto_advance_pipeline
│   ├── handle_hash_start/status/stop/advance/archive  # 包装
│   ├── archive_pipeline()      # 包装 _archive_pipeline
│   ├── broadcast_workspace_archived()  # 保留旧版
│   ├── auto_dispatch()         # 包装 _auto_dispatch（含默认模板回退增强）
│   ├── auto_re_notify()        # 包装 _auto_re_notify
│   ├── notify_pm()             # 包装 _notify_pm
│   ├── handle_reject()         # 包装 _handle_reject
│   ├── enqueue_retry()         # 包装 _enqueue_retry
│   ├── _retry_loop()           # 包装 _retry_loop
│   ├── _ensure_git_scan() / _start_git_sync_loop() / _pipeline_git_sync_scan()  # 保留旧版
│   ├── _ensure_timeout_scanner() / _start_timeout_scan_loop() / _pipeline_timeout_scan()  # 保留旧版
│   ├── restore_pipeline_timers()    # 包装 _restore_pipeline_timers
│   └── restore_pipeline_dispatches()  # 包装 _restore_pipeline_dispatches
└── 底部（engine2 原有的 from .pipeline_engine import PipelineEngine 不在此文件）
```

---

## 9. 验收表

| # | 验收项 | 类型 | 验证方法 |
|:-:|:-------|:----:|:---------|
| MERGE-A | `pipeline_engine.py` 包含 engine2.py 全部 31 个函数 | P0 | `diff <(grep '^def \|^async def' old_engine2.py) <(grep '^def \|^async def' new_pipeline_engine.py)` |
| MERGE-B | 旧 pipeline_engine 的有用功能已合并（`format_context`, `_cmd_task_update`, `broadcast_workspace_archived`, `start/stop`, 后台扫描） | P0 | 检查 5 个方法存在 |
| MERGE-C | B-5 不再存在：`auto_dispatch` 无 PM fallback 到 `PIPELINE_PM_AGENT_ID` | P0 | `grep -n "PIPELINE_PM_AGENT" new_pipeline_engine.py \| grep auto_dispatch` → 无匹配 |
| MERGE-D | `engine2.py` 已删除 | P0 | `python3 -c "from server.ws_server import engine2"` → ModuleNotFoundError |
| U1 | `python3 -c "from server.ws_server import main"` 无 ImportError | P0 | 终端执行 |
| U2 | `python3 -c "from server.ws_server import pipeline_engine"` 无 ImportError | P0 | 终端执行 |
| U3 | `python3 -c "from server.ws_server import scenario_matcher"` 无 ImportError | P0 | 终端执行 |
| U4 | `python3 -c "from server.ws_server import commands.pipeline"` 无 ImportError | P0 | 终端执行 |
| U5 | `python3 -c "from server.ws_server.connection_manager import _send"` 正常 | P0 | 终端执行 |
| T1 | `##start##R138-test##task=dev##steps=2` 正常启动 + 派活 Step 1 | P0 | 管线测试 |
| T2 | `##status##R138-test` 正常查询 | P0 | 管线测试 |
| T3 | `##stop##R138-test` 正常停止 | P0 | 管线测试 |
| T4 | `已完成 ✅` 自动推进正常（不走 PM fallback） | P0 | 完成消息测试 |
| T5 | 退回 🔄 驳回回退正常 | P0 | 驳回测试 |
| T6 | PM 通知正常送达 | P0 | 通知测试 |
| T7 | `handle_broadcast` 非管线消息路由正常 | P0 | 发送测试 |
| T8 | 规则路由 10/20/25/28/30/40/50/60/70/90 正常 | P0 | 规则测试 |
| T9 | Git sync / Timeout scanner 正常启动 | P1 | 日志检查 |
| T10 | `_retry_loop()` 启动正常 | P1 | 日志检查 |

### 9.1 验证脚本

```bash
echo "=== 无残留 engine2 ==="
python3 -c "from server.ws_server import engine2" 2>&1 && echo "FAIL: engine2 still exists" || echo "PASS: engine2 removed"

echo "=== 模块加载 ==="
python3 -c "from server.ws_server import main; print('main OK')"
python3 -c "from server.ws_server import pipeline_engine; print('pipeline_engine OK')"
python3 -c "from server.ws_server import scenario_matcher; print('scenario_matcher OK')"

echo "=== 实例化 PipelineEngine ==="
# _ensure_engine 需要完整注入环境，但在 __main__.py 启动时才会创建
# 此处仅验证 import + class 定义
python3 -c "from server.ws_server.pipeline_engine import PipelineEngine; print('PipelineEngine class OK')"

echo "=== 检查 engine2 残留引用 ==="
grep -rn "from \.engine2\|import engine2" server/ws_server/ --include="*.py"
```

---

## 10. 不做事项

| 事项 | 原因 |
|:-----|:-----|
| 函数重命名或参数签名变更 | 外部依赖不变 |
| `_connections` 池化（dict→class） | 独立工作 |
| `send_str`/`send` 二选一模式统一 | 已知重复 ~15 处 |
| `_format_pipeline_context` 和 `format_context` 代码合并 | 一个模块函数一个 class 方法，保留现状 |
| 移除 `_pending_retries` 模块变量（改为 class 属性） | 保持 engine2 代码不变 |
| 修复 `_auto_dispatch` 中 `config.PIPELINE_PM_AGENT_ID` 的日志引用（L895） | 仅日志，无行为影响 |

---

## 11. 执行顺序与注意事项

### 11.1 推荐执行步骤

```
Step 1: 备份当前 pipeline_engine.py 为 pipeline_engine.py.bak
        → cp server/ws_server/pipeline_engine.py server/ws_server/pipeline_engine.py.bak

Step 2: 复制 engine2.py 为 pipeline_engine.py
        → cp server/ws_server/engine2.py server/ws_server/pipeline_engine.py
        → 删除 module docstring 中的 "extracted from main.py" 字样
        → 删除模块级 `from .pipeline_engine import PipelineEngine`（本文件不能 import 自身）
        → 验证: python3 -c "from server.ws_server.pipeline_engine import _auto_dispatch" ✅

Step 3: 向 pipeline_engine.py 添加 PipelineEngine class
        → 使用旧版 pipeline_engine.py.bak 的 class 框架
        → 所有方法改为包装器调用模块函数
        → 添加 `_cmd_task_update`、`broadcast_workspace_archived`（从 .bak 复制）
        → 添加 `format_context`、`start/stop`（从 .bak 复制）
        → 注意：避免循环依赖（不能 import pipeline_engine 自身）
        → 验证: python3 -c "from server.ws_server.pipeline_engine import PipelineEngine" ✅

Step 4: 更新 main.py import（L48）
        → from .engine2 → from .pipeline_engine

Step 5: 更新 scenario_matcher.py import（4 处）
        → from . import engine2 → from . import pipeline_engine

Step 6: 删除 engine2.py
        → git rm server/ws_server/engine2.py

Step 7: 全量验证
        → python3 -c "from server.ws_server import main"
        → python3 -c "from server.ws_server import pipeline_engine"
        → python3 -c "from server.ws_server import scenario_matcher"
        → python3 -c "from server.ws_server import commands.pipeline"
        → grep -rn "engine2" server/ws_server/ --include="*.py"  # 应无结果
```

### 11.2 注意事项

1. **engine2 模块级 `from .pipeline_engine import PipelineEngine` 必须删除：** L36 行在新文件中不能存在。PipelineEngine class 定义在本文件中，不需要 import。

2. **`_ensure_engine()` 转发器：** engine2 底部（L1536-L1544）的 `_ensure_engine()` 和 `_ensure_pipeline_manager()` 转发器需保留在 pipeline_engine.py 中。它们使用函数体内 lazy import `from .main import _ensure_engine`，不会造成循环依赖。

3. **`_send_to_agent` 和 `_connections` 在 engine2 函数中：** engine2 的模块函数已经使用 `from .connection_manager import _send_to_agent, _connections`。新 pipeline_engine.py 保留这些 import。

4. **`_auto_dispatch` 的模板回退增强：** 按 §4.3 的 diff 修改，使 engine2 的 `_auto_dispatch` 在无模板时使用默认消息回退（旧版行为），而不是直接返回 False。

5. **`_try_advance` 的 output 构建增强：** 按 §4.2 的 diff 修改，吸收旧版完整的 output dict 构建和 artifact 提取逻辑。

6. **`git_sync_scheduler.py` 和 `pipeline_timeout.py` 与 class 方法的共存：** R136 提取了 `git_sync_scheduler._ensure_git_scan()` 和 `pipeline_timeout._ensure_timeout_scanner()` 作为模块函数。旧版 PipelineEngine class 有自己的 `_ensure_git_scan()` 方法。合并时保留 class 方法——它们可以在内部调用模块级函数，或保持独立实现（推荐保持独立实现，因为 class 版本管理自己的 task 状态）。

7. **`logger` 名称：** engine2.py 使用 `logger = logging.getLogger("ws-bridge.engine2")`。合并到 pipeline_engine.py 后改为 `logging.getLogger("ws-bridge.pipeline_engine")` 或保留原有 logger 名以保持日志一致。推荐改为 `ws-bridge.pipeline_engine`。
