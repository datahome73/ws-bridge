# R127 需求文档 — 管线状态机提取（Pipeline Engine 模块化）

> **轮次：** R127
> **类型：** 代码重构轮（主模块拆分）
> **版本：** v1.0
> **日期：** 2026-07-19
> **状态：** 📝 草稿待审

---

## §1 背景与问题

### 现状

`main.py` 当前 **5309 行 / 104 个函数**。经过 R126（场景匹配规则提取 → `scenario_matcher.py`）后，main.py 剩余两大职责：

| 职责 | 行数估算 | 函数数 | 说明 |
|:-----|:--------:|:------:|:------|
| 🔌 WebSocket 连接管理 + 消息处理 | ~1000 行 | ~20 | handler/ws_handler/认证/连接生命周期 |
| 🛠️ **管线状态机 + 命令处理** | **~3000 行** | **~45** | **本轮目标 — 提取** |
| 📋 其他工具函数 | ~1300 行 | ~39 | 通知/广播/工作区/成员管理 |

其中 **管线状态机** 是目前 main.py 中最大的逻辑块。R125 之前的架构演进：

```
R77:    PipelineContext 提取 → pipeline_context.py
R110:   PipelineAutoStarter 提取 → pipeline_auto_starter.py
R126:   场景匹配规则提取 → scenario_matcher.py
R127:   管线状态机提取 → pipeline_engine.py  ← 本轮
```

### 痛点

| 痛点 | 描述 | 影响 |
|:-----|:-----|:------|
| **P1** | 管线状态机逻辑（`_try_advance_pipeline`、`_auto_dispatch`、`_notify_pm` 等 45 个函数）与 WS 连接管理混在同一个 5309 行文件里 | 修改状态机逻辑需要先理解整个 WS 消息处理流程，新人上手成本极高 |
| **P2** | 6 个 `_handle_hash_*` 命令处理器（start/stop/status/advance/archive）和对应的业务逻辑（`_archive_pipeline`、`_auto_advance_pipeline`）散落在 main.py 的 3752~4100 行区域中，之间夹杂着其他非管线函数 | 添加新 `##` 命令需要理解整个区域的上下文依赖 |
| **P3** | 3 个后台扫描循环（git sync / timeout scan / restore）的启动和管理逻辑在主入口 (`__main__.py` 的 814~853 行) 和 main.py 之间来回引用 | 启动顺序依赖和维护者容易遗漏 |
| **P4** | `_auto_dispatch`、`_auto_swap_agent`、`_auto_re_notify` 三个自动调度函数耦合了 `WsBridgeClient` 的直接调用和 `pipeline_context.py` 的 CRUD | 自动调度难以单独测试，每次修改都需重启整个服务 |

### 目标

```
当前 main.py (5309 行)
├── WS 连接管理 (~1000 行)
├── 🛠️ 管线状态机 (~3000 行)   →   pipeline_engine.py (~2000 行)
│   ├── 状态推进: _try_advance_pipeline / _auto_advance_pipeline
│   ├── 自动调度: _auto_dispatch / _auto_swap_agent / _auto_re_notify
│   ├── ## 命令: 6 个 hash handler
│   ├── 归档管理: _archive_pipeline / _find_archive
│   ├── 通知: _notify_pm / _enqueue_retry
│   ├── 模板渲染: _render_template / _build_step_summary / _get_step_agent_name
│   ├── 后台扫描: git sync / timeout / restore
│   └── 状态格式化: _format_pipeline_context
├── 其他业务逻辑 (~1300 行)
                               +
                               pipeline_engine.py (~2000 行)
                               ├── PipelineEngine 类（统一入口）
                               ├── 所有管线状态机逻辑
                               ├── 对外接口: dispatch_hash / dispatch_reject / etc.
                               └── main.py 仅保留 ~10 行调用代码
```

---

## §2 核心设计

### 2.1 新文件: `pipeline_engine.py`

在 `server/ws_server/pipeline_engine.py` 新建一个 `PipelineEngine` 类，作为管线状态机的统一入口。

```python
class PipelineEngine:
    """管线状态机引擎 — 统一管理管线全生命周期。

    职责范围：
    - 管线状态推进（_try_advance / _auto_advance）
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

    def __init__(self, pipeline_manager: PipelineContextManager,
                 ws_client_factory: Callable):
        self._manager = pipeline_manager
        self._client_factory = ws_client_factory
        ...

    async def handle_hash_start(self, round_name: str, kv: dict,
                                 agent_id: str, ws) -> bool: ...
    async def handle_hash_status(self, round_name: str,
                                  agent_id: str, ws) -> bool: ...
    async def handle_hash_stop(self, round_name: str,
                                agent_id: str, ws) -> bool: ...
    async def handle_hash_advance(self, round_name: str, kv: dict,
                                   agent_id: str, ws) -> bool: ...
    async def handle_hash_archive(self, round_name: str,
                                   agent_id: str, ws) -> bool: ...
    async def handle_reject(self, content: str,
                             sender_agent_id: str) -> None: ...
    def try_advance(self, content: str,
                    agent_id: str) -> tuple[bool, str]: ...
    async def auto_dispatch(self, round_name: str,
                             step_num: int) -> bool: ...
    async def archive_pipeline(self, round_name: str) -> None: ...
    def format_context(self, round_name: str,
                        verbose: bool = False) -> str: ...
    ...
```

### 2.2 集成方式

main.py 中：

```python
# 初始化（在 server 启动时）
from .pipeline_engine import PipelineEngine
engine = PipelineEngine(pipeline_manager, ws_client_factory)

# 替换直接函数调用
# 旧: await _handle_hash_start(round_name, kv, agent_id, ws)
# 新: await engine.handle_hash_start(round_name, kv, agent_id, ws)

# 旧: _try_advance_pipeline(content, agent_id)
# 新: engine.try_advance(content, agent_id)
```

### 2.3 与已提取模块的协作关系

```
main.py
  ├── pipeline_engine.py (本轮提取)
  │     ├── 调用 pipeline_context.py 的 CRUD
  │     └── 通过 WsBridgeClient 发送 WS 消息
  ├── scenario_matcher.py (R126)
  │     └── 调用 pipeline_engine.handle_hash_*()
  ├── pipeline_auto_starter.py (R110)
  │     └── 调用 pipeline_engine.handle_hash_start()
  └── pipeline_context.py (R77)
        └── 纯数据模型，不依赖任何模块
```

---

## §3 集成方案

### 3.1 改动点

| 文件 | 操作 | 说明 |
|:-----|:------|:------|
| `server/ws_server/pipeline_engine.py` | **新建** | PipelineEngine 类 ~2000 行 |
| `server/ws_server/main.py` | 修改 | 移除 45 个管线函数，替换为 PipelineEngine 调用 |
| `server/ws_server/scenario_matcher.py` | 修改 | `_sm_handle_hash`/`_sm_handle_reject` 改为调用 `engine.*` |
| `server/ws_server/__main__.py` | 修改 | 后台扫描循环（git sync/timeout）改为 `engine.start_background_tasks()` |
| `server/ws_server/pipeline_auto_starter.py` | 修改 | 如有直接调用管线函数，改为通过 `engine` |

### 3.2 集成步骤

```
Step 1: PM 审核本需求文档 → 推 dev
Step 2: Arch 编写 pipeline_engine.py 架构骨架（PipelineEngine 类 + 空方法签名）
Step 3: Dev 将 45 个管线函数逐一搬入 PipelineEngine + 编译验证
Step 4: Review 审查代码结构 + 引用完整性
Step 5: QA py_compile + 运行时管线功能全流程测试
Step 6: Ops 合入 main 部署
```

### 3.3 向前兼容保证

| 保证 | 说明 |
|:-----|:------|
| **消息格式零变更** | 所有 `##` 命令的 content 格式不变 |
| **业务逻辑零变更** | 搬移过程中不改任何逻辑，纯提取 |
| **API 零变更** | `scenario_matcher` 和 `pipeline_auto_starter` 对外接口不变 |
| **启动流程零变更** | `__main__.py` 的启动顺序不变，只是后台任务注册改为 `engine.start()` |

### 3.4 风险控制

| 风险 | 等级 | 缓解措施 |
|:-----|:----:|:---------|
| 漏搬某个函数引用导致运行时 ImportError | 🔴 | Step 4 Review 做全量 `grep -n "from.*import.*_handle_hash\|_try_advance\|_auto_dispatch"` 扫描 |
| `__main__.py` 后台任务启动顺序依赖 | 🟡 | 统一由 `PipelineEngine.start_background_tasks()` 管理，`__main__.py` 只调一次 |
| 函数间隐式依赖（全局变量/闭包引用） | 🟡 | 搬移前通读每个函数的全局引用，`self._*` 封装 |
| scenario_matcher 已合入 main, 需同步接新 engine | 🟡 | 同时修改 scenario_matcher 中的 `_sm_handle_*` 引用 |

---

## §4 改动范围估算

### 4.1 管线函数清单（从 main.py 提取）

| # | 函数 | 行数 | 依赖 | 说明 |
|:-:|:-----|:----:|:-----|:-----|
| 1 | `_ensure_pipeline_manager` | ~10 | pipeline_context | 已提取，保留调用 |
| 2 | `_pipeline_git_sync_scan` | ~45 | pipeline_context | 搬入 engine |
| 3 | `_start_git_sync_loop` | ~10 | — | 搬入 engine |
| 4 | `_pipeline_timeout_scan` | ~55 | pipeline_context + WS send | 搬入 engine |
| 5 | `_start_timeout_scan_loop` | ~10 | — | 搬入 engine |
| 6 | `_auto_swap_agent` | ~65 | pipeline_context + WS client | 搬入 engine |
| 7 | `_auto_advance_pipeline` | ~110 | pipeline_context + WS client | 搬入 engine |
| 8 | `_format_pipeline_context` | ~230 | pipeline_context | 搬入 engine |
| 9 | `_restore_pipeline_timers` | ~30 | pipeline_context | 搬入 engine |
| 10 | `_restore_pipeline_dispatches` | ~30 | pipeline_context + WS client | 搬入 engine |
| 11 | `_try_advance_pipeline` | ~130 | pipeline_context | 搬入 engine |
| 12 | `_notify_pm` | ~115 | WS client | 搬入 engine |
| 13 | `_enqueue_retry` | ~15 | pipeline_context | 搬入 engine |
| 14 | `_render_template` | ~80 | — | 搬入 engine |
| 15 | `_get_step_agent_name` | ~15 | pipeline_context | 搬入 engine |
| 16 | `_build_step_summary` | ~35 | pipeline_context | 搬入 engine |
| 17 | `_find_archive` | ~110 | — | 搬入 engine |
| 18 | `_auto_re_notify` | ~35 | WS client | 搬入 engine |
| 19 | `_auto_dispatch` | ~115 | pipeline_context + WS client | 搬入 engine |
| 20 | `_handle_reject` | ~180 | pipeline_context + WS client | 搬入 engine |
| 21 | `_handle_hash_advance` | ~55 | pipeline_context + WS client | 搬入 engine |
| 22 | `_handle_hash_archive` | ~30 | pipeline_context + WS | 搬入 engine |
| 23 | `_archive_pipeline` | ~55 | pipeline_context | 搬入 engine |
| 24 | `_handle_hash_start` | ~125 | pipeline_context + WS | 搬入 engine |
| 25 | `_handle_hash_status` | ~80 | pipeline_context + WS | 搬入 engine |
| 26 | `_handle_hash_stop` | ~75 | pipeline_context | 搬入 engine |
| 27 | `_broadcast_workspace_archived` | ~65 | — | 搬入 engine |
| 28~32 | `_sm_handle_*` (hash/reject/loopback/to_agent/...) | ~150 | 各 handler | 搬入 engine（或留 scenario_matcher） |

### 4.2 文件变更汇总

| 文件 | 新增 | 删除 | 修改 | 净变化 |
|:-----|:----:|:----:|:----:|:------:|
| `pipeline_engine.py` | ~2000 行 | — | — | **+2000** |
| `main.py` | 调用 ~30 行 | ~2000 行管线代码 | ~20 行 import/init | **-1990** |
| `scenario_matcher.py` | — | — | ~30 行改引用 | ~0 |
| `__main__.py` | — | — | ~20 行改启动 | ~0 |
| `pipeline_auto_starter.py` | — | — | ~10 行改引用 | ~0 |
| **合计** | **~2000** | **~2000** | **~80** | **~+0 净增** |

> 净增 ≈ 0 — 纯搬移，不新增业务逻辑。~2000 行从 main.py 搬到 pipeline_engine.py。

---

## §5 验收标准

### PE-N: Pipeline Engine 提取（P0）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| PE-1 | `pipeline_engine.py` 存在且可导入，`from ..pipeline_engine import PipelineEngine` 无错误 | 功能 | P0 |
| PE-2 | `PipelineEngine` 类所有 28+ 个方法签名与旧函数签名一致 | 功能 | P0 |
| PE-3 | `main.py` 中所有管线函数引用替换为 `self._engine.*` 调用 | 功能 | P0 |
| PE-4 | `##start##R127-test##task=...` 创建管线并返回成功 | 功能 | P0 |
| PE-5 | `##status##R127-test` 返回管线状态 | 功能 | P0 |
| PE-6 | `##stop##R127-test` 停止管线 | 功能 | P0 |
| PE-7 | `##advance##R127-test##step=2` 推进 step | 功能 | P0 |
| PE-8 | `##archive##R127-test` 归档管线 | 功能 | P0 |
| PE-9 | `_try_advance_pipeline`（现 `engine.try_advance()`）正确处理 `✅ 完成` 完成信号 | 功能 | P0 |
| PE-10 | `_auto_dispatch`（现 `engine.auto_dispatch()`）正确发送派活消息到目标 agent | 功能 | P0 |
| PE-11 | `_notify_pm`（现 `engine.notify_pm()`）正确发送 PM 通知 | 功能 | P0 |

### RV-N: 回归验证（P0）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| RV-1 | `py_compile` 全量零错误 | 编译 | P0 |
| RV-2 | 启动后所有后台扫描循环（git sync / timeout / restore）正常运行 | 功能 | P0 |
| RV-3 | `scenario_matcher.dispatch()` 调用 `engine.handle_hash_*` 正常工作 | 集成 | P0 |
| RV-4 | `pipeline_auto_starter.PipelineAutoStarter` 调用 `engine.handle_hash_start` 正常工作 | 集成 | P0 |
| RV-5 | R126 已提取的 `scenario_matcher` 不受本轮回影响 | 回归 | P0 |

### DO-N: 文档同步（P1）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| DO-1 | `pipeline_engine.py` 模块 docstring 含职责说明 + 协作关系图 | 文档 | P1 |
| DO-2 | `inbox-message-protocol.md` 更新 `##` 命令的 handler 路径 | 文档 | P1 |

---

## §6 不做事项

| # | 事项 | 理由 |
|:-:|:-----|:------|
| ❌ | **不改变任何业务逻辑** | 纯搬移。`_try_advance_pipeline` 怎么处理 `✅ 完成` 信号，搬过去后也一样处理 |
| ❌ | **不改 PipelineContext 数据模型** | 数据模型已在 `pipeline_context.py` 稳定运行多轮，不动 |
| ❌ | **不改 PipelineAutoStarter** | 只改它调用 engine 的引用方式，不改自动启动逻辑 |
| ❌ | **不改 scenario_matcher 的规则定义** | 只改 `_sm_handle_*` 的调用目标，不改规则匹配逻辑 |
| ❌ | **不优化/重构管线业务逻辑** | 虽然 3000 行管线代码中有优化空间，但本轮**只搬不移**，确保零回归风险 |
| ❌ | **不提取其他非管线函数** | main.py 中的广播/通知/成员管理/工作区等函数留待后续轮次 |
| ❌ | **不加新功能** | 不新增 `##resume` / `##skip` 等命令，不改变协议文档 |

---

## §7 验收检查表（汇总）

### 提取前 → 提取后对比

| 维度 | 提取前 | 提取后 |
|:-----|:-------|:-------|
| `main.py` 行数 | 5309 行 | ~3300 行（-2000 管线代码） |
| 管线函数位置 | main.py 散落在 39~5215 行 | 集中在 `pipeline_engine.py` 的 `PipelineEngine` 类中 |
| 新增 `##` 命令 | 需在 main.py 中找位置 + 理解上下文依赖 | 在 `PipelineEngine` 中加一个方法即可 |
| 后台管理 | 3 个扫描循环在 `__main__.py` 中分别启动 | `engine.start()` 统一管理 |
| 单测可行性 | 不可测（依赖 main.py 全局变量） | 可构造 `PipelineEngine` 实例测试 |

### 文件改动清单

| 操作 | 文件 | 估算行数 |
|:-----|:-----|:--------:|
| ✅ 新建 | `server/ws_server/pipeline_engine.py` | ~2000 行 |
| ✅ 修改 | `server/ws_server/main.py` | ~50 行（替换调用 + 清理） |
| ✅ 修改 | `server/ws_server/scenario_matcher.py` | ~30 行（改引用） |
| ✅ 修改 | `server/ws_server/__main__.py` | ~20 行（改启动） |
| ✅ 修改 | `server/ws_server/pipeline_auto_starter.py` | ~10 行（改引用） |
| ❌ 不碰 | `server/ws_server/pipeline_context.py` | — |
| ❌ 不碰 | `server/ws_server/task_card.py` | — |

### 验收计数

| 分组 | P0 项 | P1 项 | 合计 |
|:-----|:-----:|:-----:|:----:|
| PE Pipeline Engine 提取 | 11 | 0 | 11 |
| RV 回归验证 | 5 | 0 | 5 |
| DO 文档同步 | 0 | 2 | 2 |
| **合计** | **16** | **2** | **18** |

---

## §8 与 R126 的关系

R126（场景匹配规则提取）和 R127（管线状态机提取）是 main.py 拆分的两个阶段：

```
main.py (5309 行)
  │
  ├─ R126 → scenario_matcher.py (~400 行)   ← 已合入 main ✅
  │     规则表 + 调度引擎
  │
  ├─ R127 → pipeline_engine.py (~2000 行)   ← 本轮
  │     管线状态机 + ## 命令 + 归档 + 通知
  │
  └─ 剩余 → main.py (~3300 行)               ← 后续轮次
        WS 连接 + 广播 + 成员管理 + 工具函数
```

两者正交。R126 不依赖 R127，R127 也不依赖 R126。可独立合入 main，无冲突。
