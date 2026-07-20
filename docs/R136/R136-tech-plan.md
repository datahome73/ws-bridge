# R136 技术方案 — 纯提取轮：连接管理 + 看门狗 + ACK 状态机 + 超时扫描 + Git 调度

> **版本：** v1.0
> **日期：** 2026-07-20
> **依据：** [R136 产品需求](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R136/R136-product-requirements.md) · [工作计划](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R136/WORK_PLAN.md)
> **目标基准：** `origin/dev` HEAD（`2965131`，R135 已完成，main.py 3,092 行）

---

## 目录

1. [方案总览](#1-方案总览)
2. [EXT-5：Git 同步调度 → `git_sync_scheduler.py`](#2-ext-5git-同步调度--git_sync_schedulerpy)
3. [EXT-4：超时扫描 → `pipeline_timeout.py`](#3-ext-4超时扫描--pipeline_timeoutpy)
4. [EXT-3：ACK 状态机 → `ack_machine.py`](#4-ext-3ack-状态机--ack_machinepy)
5. [EXT-2：看门狗 → `watchdog.py`](#5-ext-2看门狗--watchdogpy)
6. [EXT-1：连接管理 → `connection_manager.py`](#6-ext-1连接管理--connection_managerpy)
7. [main.py 清理后预期结构](#7-mainpy-清理后预期结构)
8. [跨模块 import 调整](#8-跨模块-import-调整)
9. [验收表](#9-验收表)
10. [不做事项](#10-不做事项)
11. [执行顺序与注意事项](#11-执行顺序与注意事项)

---

## 1. 方案总览

### 1.1 提取原则

```
原位置 main.py:
  def _some_function(...):
      ...

提取后 git_sync_scheduler.py:
  def _some_function(...):
      ...  # 完全相同的代码

原位置 main.py:
  from .git_sync_scheduler import _some_function
```

- **不重命名、不改签名、不合并函数**
- **不改变 `state._*` 全局变量引用方式**
- 提取后 `main.py` import 回原名 → 所有已有引用者（`__main__.py`、`scenario_matcher.py`、`pipeline_engine.py`）**无需修改**（除 `_connections` 和 `__main__.py` 顶部 import）
- 仅 `_connections` 和 `engine` 两个模块级变量需要保留引用关系

### 1.2 提取顺序（风险从低到高）

```
EXT-5 Git 调度 (~30行)  →  EXT-4 超时扫描 (~100行)  →  EXT-3 ACK (~50行)
  →  EXT-2 看门狗 (~300行)  →  EXT-1 连接管理 (~200行)
```

### 1.3 最终目标

| 文件 | 删除行 | 新增行 | 提取后大小 |
|:-----|:------:|:------:|:----------:|
| `main.py` | ~640 | ~20 (import) | **~2,470 行** |
| `git_sync_scheduler.py` | 0 | ~30 | ~30 行 |
| `pipeline_timeout.py` | 0 | ~100 | ~100 行 |
| `ack_machine.py` | 0 | ~50 | ~50 行 |
| `watchdog.py` | 0 | ~300 | ~300 行 |
| `connection_manager.py` | 0 | ~200 | ~200 行 |

---

## 2. EXT-5：Git 同步调度 → `git_sync_scheduler.py`

### 2.1 精确范围

```
main.py L440-L487
```

### 2.2 提取内容

| 函数 | 行号范围 | 行数 |
|:-----|:--------:|:----:|
| `_ensure_git_scan()` | L443-L451 | ~9 |
| `_start_git_sync_loop()` | L453-L461 | ~9 |
| `_pipeline_git_sync_scan()` | L463-L484 | ~22 |

### 2.3 函数体和注释（带行号标记）

```python
# ── R65 A2: Git sync lifecycle ──

def _ensure_git_scan() -> None:
    """在 handler 初始化时调用一次.启动 git sync 定时循环."""
    if not config.ENABLE_GIT_SYNC:
        logger.info("[R65] Git sync 已禁用（ENABLE_GIT_SYNC=false）")
        return
    if state._GIT_SYNC_TASK is None or state._GIT_SYNC_TASK.done():
        state._GIT_SYNC_TASK = asyncio.create_task(_start_git_sync_loop())
        logger.info("[R65] Git sync watchdog 已启动（interval=%ds）", config.GIT_SYNC_INTERVAL)


async def _start_git_sync_loop():
    """独立的 git 同步定时循环，每 GIT_SYNC_INTERVAL 秒执行一次."""
    while True:
        await asyncio.sleep(config.GIT_SYNC_INTERVAL)
        try:
            await _pipeline_git_sync_scan()
        except Exception as e:
            logger.warning("[R65] git_sync_scan error: %s", e)


async def _pipeline_git_sync_scan():
    """遍历所有活跃管线，检查 git 同步."""
    for pid, pstate in list(state._PIPELINE_STATE.items()):
        if not pstate.get("active"):
            continue
        if not config.ENABLE_GIT_SYNC:
            continue
        pconfig = state._PIPELINE_CONFIG.get(pid, {})
        sync_config = {
            "branch": pconfig.get("git_sync_branch", config.GIT_SYNC_BRANCH),
            "repo_path": pconfig.get("repo_path", config.REPO_PATH),
            "last_sha": pstate.get("last_output_sha", ""),
            "fallback_enabled": config.GIT_SYNC_FALLBACK,
        }
        syncer = pps.PipelineGitSync(pid, sync_config)
        result = await syncer.sync()
        if result and result.get("synced"):
            await _auto_advance_pipeline(pid, result)
            pstate["_last_git_sync_ts"] = time.time()
```

### 2.4 依赖

| 外部引用 | 用途 |
|:---------|:-----|
| `state._PIPELINE_STATE` | 遍历活跃管线 |
| `state._PIPELINE_CONFIG` | 读取管线配置 |
| `state._GIT_SYNC_TASK` | 任务引用管理 |
| `config.ENABLE_GIT_SYNC` | 开关 |
| `config.GIT_SYNC_INTERVAL` | 扫描间隔 |
| `config.GIT_SYNC_BRANCH` / `config.GIT_SYNC_FALLBACK` / `config.REPO_PATH` | 同步参数 |
| `pps.PipelineGitSync` | 实际同步引擎 |
| `_auto_advance_pipeline()` (保留在 main.py) | 推进回调 |
| `logger` (main.py 模块级) | 日志 |

注意：`_pipeline_git_sync_scan()` 调用 `_auto_advance_pipeline()`，后者保留在 main.py。这是唯一需要从模块外回调的函数。

### 2.5 提取后的 `main.py` 替换

```python
# ── R65 A2: Git sync lifecycle ──
from .git_sync_scheduler import (
    _ensure_git_scan,
    _start_git_sync_loop,
    _pipeline_git_sync_scan,
)
```

---

## 3. EXT-4：超时扫描 → `pipeline_timeout.py`

### 3.1 精确范围

```
main.py L489-L614
```

### 3.2 提取内容

| 函数 | 行号范围 | 行数 |
|:-----|:--------:|:----:|
| `_ensure_timeout_scanner()` | L489-L505 | ~17 |
| `_start_timeout_scan_loop()` | L508-L515 | ~8 |
| `_pipeline_timeout_scan()` | L518-L614 | ~97 |

### 3.3 函数体和注释（带行号标记）

```python
# ═══ R122: 管线超时告警扫描 ════

def _ensure_timeout_scanner() -> None:
    """在 handler 初始化时调用一次。启动超时扫描定时循环。"""
    timeout_min = config.PIPELINE_TIMEOUT_ALERT_MINUTES
    scan_interval = config.PIPELINE_TIMEOUT_SCAN_INTERVAL
    if timeout_min <= 0:
        logger.info("[R122] 管线超时告警已禁用（PIPELINE_TIMEOUT_ALERT_MINUTES=%d）", timeout_min)
        return
    if state._TIMEOUT_SCAN_STARTED:
        return
    state._TIMEOUT_SCAN_TASK = asyncio.create_task(
        _start_timeout_scan_loop(timeout_min, scan_interval)
    )
    state._TIMEOUT_SCAN_STARTED = True
    logger.info(
        "[R122] 管线超时扫描已启动（timeout=%dmin, interval=%ds）",
        timeout_min, scan_interval,
    )


async def _start_timeout_scan_loop(timeout_min: int, scan_interval: int) -> None:
    """独立的超时扫描定时循环，每 scan_interval 秒执行一次。"""
    while True:
        await asyncio.sleep(scan_interval)
        try:
            await _pipeline_timeout_scan(timeout_min)
        except Exception as e:
            logger.warning("[R122] 超时扫描错误: %s", e)


async def _pipeline_timeout_scan(timeout_min: int) -> None:
    """遍历所有 RUNNING 管线，检查 in_progress step 是否超时。"""
    from .pipeline_context import PipelineStatus as PS
    now = time.time()
    threshold = timeout_min * 60.0
    mgr = _ensure_pipeline_manager()
    alerted = 0
    # ... (full body unchanged)
```

**完整函数体需从 `origin/dev` 的 L518-L614（共 97 行）逐字复制。**

### 3.4 依赖

| 外部引用 | 用途 |
|:---------|:-----|
| `config.PIPELINE_TIMEOUT_ALERT_MINUTES` | 超时阈值 |
| `config.PIPELINE_TIMEOUT_SCAN_INTERVAL` | 扫描间隔 |
| `config.PIPELINE_TIMEOUT_RETRY_MINUTES` | 重发派活阈值 |
| `config.PIPELINE_TIMEOUT_MARK_MINUTES` | timeout 标记阈值 |
| `config.PIPELINE_PM_AGENT_ID` | PM agent ID |
| `state._TIMEOUT_SCAN_TASK` / `state._TIMEOUT_SCAN_STARTED` | 状态 |
| `_ensure_pipeline_manager()` | 获取 mgr |
| `_send_to_agent()` | 告警发送 |
| `_auto_re_notify()` | 重发派活回调 |
| `logger` | 日志 |

### 3.5 提取后的 `main.py` 替换

```python
# ═══ R122: 管线超时告警扫描 ════
from .pipeline_timeout import (
    _ensure_timeout_scanner,
    _start_timeout_scan_loop,
    _pipeline_timeout_scan,
)
```

---

## 4. EXT-3：ACK 状态机 → `ack_machine.py`

### 4.1 精确范围

```
main.py L880-L1006（ACK 状态机段落）
main.py L1429-L1493（task/channel ack 超时函数）
```

### 4.2 提取内容

| 函数 | 行号范围 | 行数 |
|:-----|:--------:|:----:|
| `_ack_timeout_task()` | L883-L900 | ~18 |
| `_send_ack_timeout_info()` | L903-L944 | ~42 |
| `_trigger_ack_escalation()` | L947-L998 | ~52 |
| `_format_ack_status()` | L1008-L1032 | ~25 |
| `_task_ack_timeout()` | L1429-L1442 | ~14 |
| `_channel_ack_timeout()` | L1444-L1481 | ~38 |
| `_resolve_ws_by_ack_task_id()` | L1484-L1489 | ~6 |

**注意：** 以下函数因依赖 ACK 模块函数，但本身属于 ACK 模块，一并提取：
- ACK_TIMEOUT_SEC 常量（L880）

### 4.3 依赖

| 外部引用 | 用途 |
|:---------|:-----|
| `state._step_ack_states` | ACK 状态容器 |
| `state._channel_ack_state` | 频道 ACK 状态 |
| `state._PIPELINE_STATE` | 管线遍历 |
| `state._task_ack_timers` | 任务 ACK 定时器 |
| `_send()` (保留在 main.py) | admin_ws 发送 |
| `_persist_broadcast()` (保留在 main.py) | 持久化告警 |
| `_get_agent_display()` (保留在 main.py) | 名称格式化 |
| `ws_mod.get_workspace()` | 工作区查询 |
| `_connections` | 连接查询 |
| `auth.get_users()` | 用户名查询 |
| `_notify_rollcall_complete()` (保留在 main.py) | 回调 |

### 4.4 提取后的 `main.py` 替换

```python
# ── R63 Phase 4: ACK state machine ──
from .ack_machine import (
    _ack_timeout_task,
    _send_ack_timeout_info,
    _trigger_ack_escalation,
    _format_ack_status,
    _task_ack_timeout,
    _channel_ack_timeout,
    _resolve_ws_by_ack_task_id,
)
```

---

## 5. EXT-2：看门狗 → `watchdog.py`

### 5.1 精确范围

```
main.py L429-L437（_ensure_watchdog — 看门狗启动入口）
main.py L739-L824（看门狗循环 + 超时判断）
main.py L1038-L1131（告警相关：_check/_clear/_elapsed/_send/_watchdog_rerollcall/_send_clear）
```

### 5.2 提取内容

| 函数 | 行号范围 | 行数 |
|:-----|:--------:|:----:|
| `_ensure_watchdog()` | L429-L437 | ~9 |
| `_watchdog_loop()` | L739-L747 | ~9 |
| `_watchdog_scan()` | L749-L814 | ~66 |
| `_get_step_timeout()` | L817-L823 | ~7 |
| `_trigger_timeout_escalation()` | L829-L874 | ~46 |
| `_check_watchdog_alert()` | L1038-L1055 | ~18 |
| `_clear_watchdog_alert()` | L1058-L1064 | ~7 |
| `_elapsed_hours_display()` | L1067-L1071 | ~5 |
| `_send_watchdog_alert()` | L1074-L1129 | ~56 |
| `_watchdog_rerollcall()` | L1134-L1149 | ~16 |
| `_send_clear_alert()` | L1152-L1164 | ~13 |

### 5.3 看门狗函数内部使用的交叉引用（保留在 main.py）

| 被调用函数 | 位置 | 处理方式 |
|:-----------|:-----|:---------|
| `_get_step_config()` | main.py（通过 import） | 看门狗函数引用→通过 import 解决 |
| `_persist_broadcast()` | main.py 保留 | → import 解决 |
| `_cmd_rollcall_role()` | commands/pipeline.py | → import 解决 |
| `ac_mod.mark_stale_offline()` | agent_card.py | → import agent_card 解决 |
| `state._PIPELINE_STATE` | — | → 引用 state 模块 |
| `state._watchdog_alerts` | — | → 引用 state 模块 |

### 5.4 提取后的 `main.py` 替换

```python
# ── R43: Watchdog ──
from .watchdog import (
    _ensure_watchdog,
    _watchdog_loop,
    _watchdog_scan,
    _get_step_timeout,
    _trigger_timeout_escalation,
    _check_watchdog_alert,
    _clear_watchdog_alert,
    _elapsed_hours_display,
    _send_watchdog_alert,
    _watchdog_rerollcall,
    _send_clear_alert,
)
```

---

## 6. EXT-1：连接管理 → `connection_manager.py`

### 6.1 精确范围

```
main.py L35-L39（_connections / engine 声明 — 保留在 main.py，connection_manager 通过 import 引用）
main.py L68-L69（get_connections — 读接口）
main.py L130-L138（_force_disconnect_revoked_agent — 前一个 def，会被覆盖）
main.py L140-L148（_send — 统一发送器）
main.py L149-L158（_force_disconnect_revoked_agent — 后一个 def，实际有效）
main.py L160-L185（handle_auth — api_key 认证）
main.py L189-L198（_update_agent_online_status）
main.py L204-L209（_find_agent_by_name）
main.py L212-L264（handle_register — 新 bot 注册，不含 _build_* helpers）
main.py L270-L283（_build_registration_welcome — 注册辅助函数 1）
main.py L286-L297（_build_admin_notification — 注册辅助函数 2）
main.py L300-L303（_should_notify_admins — 注册辅助函数 3）
main.py L306-L362（handle_agent_card_register — Agent Card 注册）

main.py L1495-L1497（_is_valid_agent_id）
main.py L1500-L1538（_send_to_agent — 单播网关）
```

**注意：** `_connections` 变量定义在 L35 保留在 `main.py`，但 `connection_manager.py` 需要引用它。处理方法见 §6.4。

### 6.2 提取内容（精确行号）

| 函数 | 行号范围 | 行数 |
|:-----|:--------:|:----:|
| `get_connections()` | L68-L69 | ~2 |
| `_force_disconnect_revoked_agent()`（有效） | L149-L158 | ~10 |
| `_send()` | L140-L148 | ~9 |
| `handle_auth()` | L160-L186 | ~27 |
| `_update_agent_online_status()` | L189-L198 | ~10 |
| `_find_agent_by_name()` | L204-L209 | ~6 |
| `handle_register()` | L212-L264 | ~53 |
| `_build_registration_welcome()` | L270-L283 | ~14 |
| `_build_admin_notification()` | L286-L297 | ~12 |
| `_should_notify_admins()` | L300-L303 | ~4 |
| `handle_agent_card_register()` | L306-L362 | ~57 |
| `_is_valid_agent_id()` | L1495-L1497 | ~3 |
| `_send_to_agent()` | L1500-L1538 | ~39 |

### 6.4 关键设计：`_connections` 引用

**问题：** `_connections` 在 `main.py` L35 定义，被 `__main__.py` 直接 import。  
`connection_manager.py` 中的函数需要读写 `_connections`。

**方案：** `_connections` 留在 `main.py` L35。`connection_manager.py` 在函数内通过 `_get_connections()` 延迟引用：

```python
# connection_manager.py
def _get_connections():
    from .main import _connections
    return _connections
```

或者更直接：`connection_manager.py` 中的函数通过 `from .main import _connections` 模块级引用。  
但由于存在循环依赖风险（`main.py → connection_manager.py → main.py`），推荐在函数体内延迟 import：

```python
async def handle_auth(ws, msg: dict) -> str | None:
    from .main import _connections
    ...
    _connections.setdefault(agent_id, set()).add(ws)
```

但这样每调用一次函数都重复 import。更优方案：在 `connection_manager.py` 顶部：

```python
# connection_manager.py — 函数内部引用 _connections
# _connections 定义在 main.py L35，__main__.py 也直接 import
# 避免模块级循环 import，函数内部通过 from .main import _connections 延迟引用
```

或者更简单：`_connections` 定义在 `connection_manager.py` 中，`main.py` 和 `__main__.py` 都改为从 `connection_manager.py` import `_connections`。

**推荐方案：**  
将 `_connections` 定义移到 `connection_manager.py`，`main.py` 和 `__main__.py` 通过 import 共享：

```python
# connection_manager.py
_connections: dict[str, set] = {}  # 原 main.py L35

# main.py
from .connection_manager import _connections, _send, ...

# __main__.py（已有 from .main import handle_auth, handle_broadcast, handle_register, _connections）
# 改为：
from .connection_manager import _connections
from .main import handle_auth, handle_broadcast, handle_register
```

**注意：** `engine: Optional[PipelineEngine] = None`（L39）保留在 main.py，不移动。

### 6.5 其他函数交叉引用关系

| 函数 | 引用的 main.py 内部函数 | 处理方式 |
|:-----|:------------------------|:---------|
| `handle_register` | `_send`, `_find_agent_by_name`, `_update_agent_online_status` | 同在 connection_manager |
| `handle_agent_card_register` | `_send`, `_build_registration_welcome`, `_build_admin_notification`, `_should_notify_admins`, `_broadcast_to_channel` | `_broadcast_to_channel` 保留在 main.py |
| `handle_auth` | `_send`, `_update_agent_online_status`, `state._r72_users` | 同在 connection_manager |
| `_send_to_agent` | `ms.is_duplicate`, `ms.save_message`, `state.SYSTEM_AGENT_ID`, `config.DATA_DIR`, `_connections` | `ms`/`state`/`config` 可从模块级 import |

### 6.6 提取后的 `main.py` 替换

```python
# ── R72: Connection management ──
from .connection_manager import (
    get_connections,
    _force_disconnect_revoked_agent,
    _send,
    _send_to_agent,
    handle_auth,
    _update_agent_online_status,
    _find_agent_by_name,
    handle_register,
    _build_registration_welcome,
    _build_admin_notification,
    _should_notify_admins,
    handle_agent_card_register,
    _is_valid_agent_id,
)
```

---

## 7. main.py 清理后预期结构

```
main.py 清理后（~2,470 行）
├── docstring + imports (~30 行)
│   ├── 标准库
│   ├── 内部模块（agent_card, auth, config, state, message_store, ...）
│   └── 提取模块的 import（5 组）
├── 模块级变量（~5 行）
│   ├── _connections              # 从 connection_manager import
│   ├── engine: PipelineEngine    # 保留
│   └── _audit_logger              # 保留
├── _ensure_engine() / _ensure_pipeline_manager()     # ~25 行 保留
├── _refresh_role_agent_map()                          # ~25 行 保留
├── _broadcast_to_channel()                            # ~30 行 保留
├── _persist_broadcast()                               # ~20 行 保留  
├── _get_agent_display()                               # ~15 行 保留
├── _ensure_agent_cards_loaded() / _ensure_card_watcher()  # ~25 行 保留
├── 5 组 from .xxx import ...                          # ~5 行 新增
├── _auto_advance_pipeline() / ...                     # 管线功能 (~1000行)
│     （_verify_git_commit, _format_pipeline_context, _restore_*,
│       _extract_artifact_kv, _try_advance, _notify_pm, ...）
├── handle_broadcast()                                 # ~120 行 保留
└── 底部 ~30 行（scenario_matcher 规则注册）
```

---

## 8. 跨模块 import 调整

### 8.1 `__main__.py` (`server/ws_server/__main__.py`)

**当前：** L15: `from .main import handle_auth, handle_broadcast, handle_register, _connections`

**改为：**
```python
from .connection_manager import _connections
from .main import handle_auth, handle_broadcast, handle_register
```

**原因：** `_connections` 定义移到 `connection_manager.py`。`handle_auth`、`handle_broadcast`、`handle_register` 仍可通过 `main.py` import（main.py 会 re-export）。

### 8.2 `scenario_matcher.py` — 无影响

`_send_to_agent` / `_send` 通过 engine 注入或场景规则回调传递，不是通过模块名引用。

确认：`grep -n "_send_to_agent\|_send" server/ws_server/scenario_matcher.py`

### 8.3 `pipeline_engine.py` — 无影响

`_send_to_agent` 通过构造注入（`PipelineEngine.__init__`的 `send_to_agent` 参数），不直接引用模块名。

确认：`grep -n "_send_to_agent\|_send" server/ws_server/pipeline_engine.py`

### 8.4 `commands/pipeline.py` — 无影响

`_broadcast_to_channel`、`_persist_broadcast` 仍保留在 main.py，可通过 main.py import。

### 8.5 `web_ui/viewer.py` — 无影响

引用 `server.common.message_store`，不与 `ws_server.message_store` 关联。

---

## 9. 验收表

| # | 验收项 | 类型 | 验证方法 |
|:-:|:-------|:----:|:---------|
| EXT-5 | `git_sync_scheduler.py` 创建，`main.py` import 正常 | P0 | `python3 -c "from server.ws_server import main"` |
| EXT-5 | `_ensure_git_scan` 导入后可调用（签名一致）| P0 | 检查函数签名 + 引用 |
| EXT-4 | `pipeline_timeout.py` 创建，`main.py` import 正常 | P0 | `python3 -c "from server.ws_server import main"` |
| EXT-4 | `_pipeline_timeout_scan()` 内部引用 `_send_to_agent` 正常 | P0 | 检查未用函数体延迟 import |
| EXT-3 | `ack_machine.py` 创建，ImportError 无 | P0 | `python3 -c "from server.ws_server import main"` |
| EXT-3 | `_format_ack_status()` 读 `state._step_ack_states` 正常 | P0 | 检查 state 引用路径 |
| EXT-2 | `watchdog.py` 创建，ImportError 无 | P0 | `python3 -c "from server.ws_server import main"` |
| EXT-2 | `_watchdog_scan()` 引用 `_get_step_config` 正常 | P0 | 检查 import 路径 |
| EXT-1 | `connection_manager.py` 创建，ImportError 无 | P0 | `python3 -c "from server.ws_server import main"` |
| EXT-1 | `_connections` 在 `connection_manager.py` 中定义 → `__main__.py` 和 `main.py` 共享同一 dict 实例 | P0 | `python3 -c "from server.ws_server.connection_manager import _connections; from server.ws_server.main import _connections; print(_connections is _connections)"` 应为 True |
| EXT-1 | `__main__.py` 导入 `_connections` 路径正确 | P0 | `python3 -c "from server.ws_server.__main__ import ..."` 无 ImportError |
| R136-1 | `python3 -c "from server.ws_server import main"` 无 ImportError | P0 | 终端执行 |
| R136-2 | `##status` 查询管线状态正常 | P0 | 管线测试 |
| R136-3 | `##start##R136` 管线启动 + 派活正常 | P0 | 管线测试 |
| R136-4 | 看门狗首次消息后启动 | P0 | 日志检查 |
| R136-5 | Git sync 扫描正常启动 | P1 | 日志检查 |
| R136-6 | 超时扫描正常启动 | P1 | 日志检查 |
| R136-7 | `_inbox:{agent_id}` 单播投递正常 | P0 | 发送测试消息 |
| R136-8 | `_inbox:server` 规则表路由正常 | P0 | 发送测试消息 |

### 9.1 每提取后的验证脚本

```bash
# 每批提取后执行
echo "=== EXT-X import check ==="
python3 -c "from server.ws_server import main; print('main OK')"
python3 -c "from server.ws_server.connection_manager import _send; print('connection_manager OK')" 2>/dev/null \
  || python3 -c "from server.ws_server.watchdog import _ensure_watchdog; print('watchdog OK')" 2>/dev/null \
  || python3 -c "from server.ws_server.ack_machine import _format_ack_status; print('ack_machine OK')" 2>/dev/null \
  || python3 -c "from server.ws_server.pipeline_timeout import _ensure_timeout_scanner; print('pipeline_timeout OK')" 2>/dev/null \
  || python3 -c "from server.ws_server.git_sync_scheduler import _ensure_git_scan; print('git_sync_scheduler OK')" 2>/dev/null
```

---

## 10. 不做事项

| 事项 | 原因 | 归属 |
|:-----|:-----|:----:|
| `##` 命令迁移到 engine | 纯提取不包含行为重构 | R137 |
| `_connections` 池化（dict→class）| 纯提取不包含重构 | R138 |
| `_send_to_agent` 统一网关 | 纯提取不包含重构 | R138 |
| `send_str`/`send` 二选一模式统一 | 已知重复 ~15 处但不在此轮 | R138 |
| 规则注册回调统一 | 纯提取 | R137 |
| `_broadcast_to_channel` 重组 | 仍被 pipeline 和 register 正常使用 | 保留 |
| `_persist_broadcast` 移动 | 仍被 pipeline_engine callback 使用 | 保留 |
| `_ensure_engine()` 移动 | 需要访问 `_send_to_agent` 等刚被抽出函数，留在 main.py 作为 hub | 保留 |
| `_ensure_pipeline_manager()` 移动 | 同上 | 保留 |
| workspace.py / message_store.py / state.py 调整 | 非本轮范围 | — |

---

## 11. 执行顺序与注意事项

### 11.1 推荐执行顺序

```
Step 1: EXT-5 git_sync_scheduler.py   → 验证: python3 -c "from server.ws_server import main"
Step 2: EXT-4 pipeline_timeout.py     → 验证: python3 -c "from server.ws_server import main"
Step 3: EXT-3 ack_machine.py          → 验证: python3 -c "from server.ws_server import main"
Step 4: EXT-2 watchdog.py             → 验证: python3 -c "from server.ws_server import main"
Step 5: EXT-1 connection_manager.py   → 验证: python3 -c "from server.ws_server import main"
                                        python3 -c "from server.ws_server.connection_manager import _connections"
Step 6: 更新 __main__.py import        → 验证: python3 -m server.ws_server (dry run)
```

### 11.2 注意事项

1. **`_connections` 共享实例：** 确保 `main.py` 和 `connection_manager.py` 共享同一个 `_connections` dict 实例。方案：唯一定义在 `connection_manager.py`，`main.py` 通过 `from .connection_manager import _connections` 引用。

2. **`engine` 变量（L39）保留在 main.py：** `_ensure_engine()` 保留在 main.py，不需要提取。`PipelineEngine` 构造时通过参数注入 `_send_to_agent`、`_send` 等函数引用，不需要模块级 import。

3. **看门狗中的延迟 import：** `_watchdog_scan` 中调用 `_cmd_rollcall_role()`（来自 `commands/pipeline.py`），在文件顶部 import 即可解决。

4. **`_pipeline_timeout_scan` 中的延迟 import：** L524 有 `from .pipeline_context import PipelineStatus as PS`，保持原样。

5. **`_get_step_config` 引用：** 看门狗中 `_get_step_config("")` 在 `_watchdog_scan` L761 和 `_get_step_timeout` L819 使用。此函数在 `commands/pipeline.py` 中定义。提取时确保 watchdog.py 顶部 import 正确。

6. **`handle_agent_card_register` 中的 `REGISTRATION_BROADCAST_ENABLED`：** L348 引用的这个变量在 `state.py` 中定义。提取到 `connection_manager.py` 后仍需访问 `state.REGISTRATION_BROADCAST_ENABLED`。

7. **`_broadcast_to_channel` 在 `handle_agent_card_register` 中被调用：** L336, L351。此函数保留在 main.py。提取到 connection_manager.py 后通过 `from .main import _broadcast_to_channel` 解决。
