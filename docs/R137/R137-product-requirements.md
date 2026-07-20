# R137 产品需求 — 引擎分拆轮：main.py 管线逻辑迁入 engine2.py

> **起草人：** 🧐 PM
> **状态：** ⬜ 待审核
> **版本：** v1.0
> **日期：** 2026-07-20
> **依据文档：** `server/ws_server/README.md` §9 重构清单

---

## 0. R137 定位

```
R135（已上线）— 死代码清理：handle_broadcast + 频道体系精简 (-600行)
R136（已上线）— 纯提取轮：连接管理/看门狗/ACK状态机/Git调度/超时扫描 独立成模块
R137（本轮）  — 引擎分拆轮：main.py 管线逻辑迁入 engine2.py，两套引擎并行
R138（下轮）  — 两引擎对齐/合并
```

R137 是**零语义改动轮**——只搬文件，不改逻辑。提取后生产行为不变。

---

## 1. 背景与目标

### 1.1 现状

R136 之后 `main.py` 从 3,092 行降至 **2,180 行**。虽然 R136 提取了 5 个模块，但管线核心逻辑（~1,200 行）仍然嵌在 main.py 中：

| 功能区 | 行数 | 说明 |
|:-------|:----:|:-----|
| ## 命令处理（start/stop/status/advance/archive） | ~360 | 5 个 `_handle_hash_*` 函数 |
| 自动调度（dispatch/re-notify/retry） | ~190 | `_auto_dispatch` + `_auto_re_notify` + `_retry_loop` |
| 管线推进（try_advance/auto_advance） | ~230 | 两套 advance 逻辑 |
| 通知/驳回（notify_pm/handle_reject） | ~150 | PM 队列通知 + 驳回回退 |
| 模板渲染/摘要（render/summary/rich_templates） | ~120 | 派活消息模板 + Step 摘要 |
| 工具函数（verify_sha/archive/extract_kv/name_resolve） | ~150 | 各类辅助函数 |
| **合计管线逻辑** | **~1,200** | |

### 1.2 深层问题：两套分叉实现

`pipeline_engine.py`（R127 提取）和 main.py 的管线逻辑是**两套分叉的实现**：

| 函数 | main.py 版本 | pipeline_engine.py 版本 | 状态 |
|:-----|:-------------|:------------------------|:-----|
| `##start` | 成熟版（~120 行） | 精简版（~80 行） | 🚨 不同 |
| `##status` | 带硬编码 step_names | 用 `format_context()` | 🚨 不同 |
| `##advance` | 构造完成消息+调 `_try_advance` | 直接 `ctx.current_step = target` | 🚨 不同 |
| `##archive` | 完整归档 | 独立归档逻辑 | 🚨 不同 |
| `auto_dispatch` | 完整版（模板+摘要+card→WS 桥接） | 精简版 | 🚨 不同 |
| `try_advance` | R115+R123+R124 完整版 | 基本版 | 🚨 不同 |

### 1.3 目标

**本轮不做合并，只做分拆。**

```
main.py ─────────────────────── pipeline_engine.py ──── engine2.py（新建）
  │  WS 通信协议                    精简版实现            从 main.py 搬来的
  │  ~800 行                        ~1300 行             成熟管线逻辑
  │                                                      ~1200 行
  │
  └── scenario_matcher ──→ engine2（改路由）
```

分拆后两套引擎并行运行，各做各的：
- `pipeline_engine.py` — R127 提取的精简版（暂时不动）
- `engine2.py` — 从 main.py 搬来的**真实生产代码**（命名临时，后续合并改回）

等两套都稳定、差异消除后，R138 合并为一套 `pipeline_engine.py`。

### 1.4 范围界定

| 范围 | 包含 | 不包含 |
|:-----|:-----|:-------|
| engine2 提取 | main.py 中全部 ~1,200 行管线逻辑 → engine2.py | 非管线逻辑（通信协议/初始化/规则桥接） |
| 路由切换 | scenario_matcher `##` 命令 → engine2 | pipeline_engine.py 的修改 |
| main.py 精简 | 删除已移动的管线代码，保留通信协议 | 非管线代码的改动 |

---

## 2. 功能需求

### EXT-A：创建 engine2.py

新建 `engine2.py`，包含 main.py 中以下管线逻辑（完整列表见 §3 迁移清单）：

| 分组 | 函数 | 行数 | 说明 |
|:-----|:-----|:----:|:-----|
| A1 | ## 命令 | ~360 | `_handle_hash_start`, `_handle_hash_status`, `_handle_hash_stop`, `_handle_hash_advance`, `_handle_hash_archive` |
| A2 | 自动调度 | ~190 | `_auto_dispatch`, `_auto_re_notify`, `_retry_loop`, `_enqueue_retry`, `_pending_retries` |
| A3 | 管线推进 | ~230 | `_try_advance_pipeline`, `_auto_advance_pipeline`, `_verify_sha_remote` |
| A4 | 通知/驳回 | ~150 | `_notify_pm`, `_handle_reject`, `_build_names` |
| A5 | 模板/展示 | ~120 | `_render_template`, `_build_step_summary`, `_build_rich_templates`, `_get_step_agent_name` |
| A6 | 工具函数 | ~150 | `_extract_artifact_kv`, `_find_archive`, `_archive_pipeline`, `_restore_pipeline_timers`, `_restore_pipeline_dispatches`, `_resolve_card_key_to_ws_id`, `_build_name_to_ws_map`, `_fmt_ts` |
| A7 | 模块级常/全局变量 | ~10 | `_pending_retries`, `_ROLE_EMOJIS`, `_ROLE_NAMES`, `_URL_FIELDS` |

**engine2.py 提取原则：**

```
原位置 main.py:
  def _handle_hash_start(round_name, kv, agent_id, ws) -> bool:
      ...  # 完整代码

提取后 engine2.py:
  def _handle_hash_start(round_name, kv, agent_id, ws) -> bool:
      ...  # 完全相同代码（零改动）

原位置 main.py:
  删除该函数定义
  # 其他模块通过 from . import engine2 引用
```

- **不重命名、不改签名、不合并函数**
- module-level lazy import 解决循环依赖（`from .main import _ensure_pipeline_manager` 在函数体内）
- `_ensure_pipeline_manager()` 本身保留在 main.py 中，engine2.py 通过 lazy import 引用

### EXT-B：改 scenario_matcher 路由

当前场景匹配器路由：

```
scenario_matcher.handle_hash_cmd()
  ├── from . import main as _main
  ├── await _main._handle_hash_start(...)
  ├── await _main._handle_hash_status(...)
  ├── await _main._handle_hash_stop(...)
  ├── await _main._handle_hash_advance(...)
  └── await _main._handle_hash_archive(...)
```

改为：

```
scenario_matcher.handle_hash_cmd()
  ├── from . import engine2 as _e2
  ├── await _e2._handle_hash_start(...)
  ├── await _e2._handle_hash_status(...)
  ├── await _e2._handle_hash_stop(...)
  ├── await _e2._handle_hash_advance(...)
  └── await _e2._handle_hash_archive(...)
```

同样，`scenario_matcher` 中查询管线状态的 `_format_pipeline_status()` 等函数也改引用 engine2。

**改动点：**
1. `scenario_matcher.py` L407+ — `from . import main as _main` → `from . import engine2 as _e2`（或在最新代码中对应位置）
2. 所有 `_main._handle_hash_*` → `_e2._handle_hash_*`
3. 所有 `_main._ensure_engine()` → `_e2._ensure_engine()`（engine2 需要导出 `_ensure_engine()`）
4. 所有 `_main._ensure_pipeline_manager()` → `_e2._ensure_pipeline_manager()`（engine2 需要导出或包装这个）

### EXT-C：精简 main.py

删除已移至 engine2.py 的全部 ~1,200 行管线代码。main.py 保留：

| 保留区域 | 行数 | 内容 |
|:---------|:----:|:-----|
| docstring + imports | ~30 | |
| 模块级变量（_connections, engine） | ~10 | |
| Agent Card 初始化 | ~50 | `_refresh_role_agent_map`, `_ensure_agent_cards_loaded`, `_ensure_card_watcher` |
| 广播/工具 | ~80 | `_broadcast_to_channel`, `_persist_broadcast`, `_get_agent_display` |
| WebSocket 协议 | ~280 | `handle_broadcast`, `handler()` |
| 规则桥接（`_sm_handle_*`） | ~200 | rule 10/20/30/40/50/60/70/90 回调 |
| 规则注册 | ~80 | 8 条规则的 register_rule 调用 |
| 已提取模块的 import | ~20 | connection_manager, watchdog, ack_machine, etc. |
| **合计** | **~800** | |

### EXT-D：engine2 的 `_ensure_engine()` 和 `_ensure_pipeline_manager()`

engine2.py 中的管线函数大量调用 `_ensure_pipeline_manager()` 和 `_ensure_engine()`。
当前这两个函数定义在 main.py 中（L41-L67）。

两种方案：

**方案 A（推荐）：lazy import**

engine2.py 在每个需要调用 `_ensure_pipeline_manager()` 的函数体内：
```python
def _try_advance_pipeline(content, agent_id):
    from .main import _ensure_pipeline_manager
    mgr = _ensure_pipeline_manager()
    ...
```

**方案 B：engine2 自包含**

engine2.py 定义自己的 `_ensure_pipeline_manager()`（与 main.py 版本相同）：
```python
def _ensure_pipeline_manager() -> PipelineContextManager:
    if state._pipeline_manager is None:
        state._pipeline_manager = PipelineContextManager(data_dir=config.DATA_DIR)
    return state._pipeline_manager
```

方案 A 改动最小（只改 import），推荐。方案 B 有代码重复但无循环依赖风险。

注意：`_ensure_engine()` 构造 PipelineEngine 时依赖 `commands/pipeline.py` 的函数和 `_send` 等回调，这些函数部分会随 pipeline 逻辑进入 engine2。需确认 engine2 是否能独立完成 engine 初始化。如果不行，`_ensure_engine()` 保留在 main.py，engine2 通过 lazy import 获取 engine 实例。

---

## 3. 迁移清单（精确范围）

### 3.1 从 main.py → engine2.py 的函数

**A1：## 命令处理（~360 行）**

| 函数 | main.py 行号 | 行数 |
|:-----|:------------:|:----:|
| `_handle_hash_start` | L1602-L1723 | ~122 |
| `_handle_hash_status` | L1726-L1802 | ~77 |
| `_handle_hash_stop` | L1805-L1830 | ~26 |
| `_handle_hash_advance` | L1457-L1510 | ~54 |
| `_handle_hash_archive` | L1514-L1542 | ~29 |
| `_archive_pipeline` | L1547-L1599 | ~53 |

**A2：自动调度（~190 行）**

| 函数 | main.py 行号 | 行数 |
|:-----|:------------:|:----:|
| `_pending_retries`（dict 声明） | L875 | ~1 |
| `_retry_loop` | L877-L909 | ~33 |
| `_enqueue_retry` | L912-L924 | ~13 |
| `_auto_dispatch` | L1165-L1277 | ~113 |
| `_auto_re_notify` | L1123-L1161 | ~39 |

**A3：管线推进（~230 行）**

| 函数 | main.py 行号 | 行数 |
|:-----|:------------:|:----:|
| `_auto_advance_pipeline` | L221-L341 | ~121 |
| `_try_advance_pipeline` | L679-L791 | ~113 |
| `_verify_sha_remote` | L1080-L1120 | ~41 |

**A4：通知/驳回（~150 行）**

| 函数 | main.py 行号 | 行数 |
|:-----|:------------:|:----:|
| `_notify_pm` | L797-L870 | ~74 |
| `_handle_reject` | L1282-L1356 | ~75 |

**A5：模板/展示（~120 行）**

| 函数 | main.py 行号 | 行数 |
|:-----|:------------:|:----:|
| `_render_template` | L930-L997 | ~68 |
| `_ROLE_EMOJIS` / `_ROLE_NAMES` / `_URL_FIELDS`（常量） | L1010-L1016 | ~7 |
| `_build_step_summary` | L1019-L1047 | ~29 |
| `_get_step_agent_name` | L1000-L1006 | ~7 |
| `_build_rich_templates` | L1411-L1452 | ~42 |

**A6：工具函数（~150 行）**

| 函数 | main.py 行号 | 行数 |
|:-----|:------------:|:----:|
| `_extract_artifact_kv` | L651-L673 | ~23 |
| `_find_archive` | L1053-L1066 | ~14 |
| `_fmt_ts` | L1069-L1074 | ~6 |
| `_build_name_to_ws_map` | L1364-L1371 | ~8 |
| `_resolve_card_key_to_ws_id` | L1374-L1408 | ~35 |
| `_restore_pipeline_timers` | L487-L514 | ~28 |
| `_restore_pipeline_dispatches` | L520-L544 | ~25 |

### 3.2 需要 engine2 额外导入/引用的外部模块

| 引用源 | 引用项 | 方式 |
|:-------|:-------|:-----|
| `main.py` | `_ensure_pipeline_manager()` | lazy import `from .main import _ensure_pipeline_manager` |
| `connection_manager.py` | `_send`, `_send_to_agent`, `_connections` | 直接 import |
| `state` | `_PIPELINE_STATE`, `_ROLE_AGENT_MAP`, `SYSTEM_AGENT_ID` | 直接 import |
| `config` | `PIPELINE_PM_AGENT_ID`, `AUTO_DISPATCH_ENABLED`, `DATA_DIR` | 直接 import |
| `agent_card` | `get_all_cards`, `get_agent_card` | 直接 import |
| `pipeline_context` | `PipelineContext`, `PipelineContextManager`, `PipelineStatus` | 直接 import |
| `task_store` | `list_tasks_by_context`, `get_task`, etc. | 直接 import |
| `message_store` | `save_message` | 直接 import |
| `timeout_tracker` | `start_timer` | 直接 import |
| `workspace` | `get_workspace` | 直接 import |
| `auth` | `get_users` | 直接 import |
| `commands/pipeline.py` | `_get_step_config`, `_step_sort_key`, `_set_pipeline_state` | 直接 import（已在函数体内） |

### 3.3 engine2.py 导出接口

engine2.py 作为模块级文件导出所有 `_handle_hash_*` 函数 + 工具函数，供 `scenario_matcher.py` 调用。

```python
# engine2.py — 最后一行不需要显式 __all__
# 所有函数保持 _ 前缀（仍是私有约定），scenario_matcher 通过 module 引用来调用
```

---

## 4. 提取原则

### 4.1 提取方式

```
原位置 main.py:
  def _some_function(...):
      ...   # 完整代码

提取后 engine2.py:
  def _some_function(...):
      ...   # 完全相同的代码

原位置 main.py:
  删除该函数定义
  工程约束：确认无其他模块直接引用该函数名
```

### 4.2 不做的

| 事项 | 原因 |
|:-----|:-----|
| 函数重命名 | 保持 `_` 前缀和原名，减少 diff |
| 参数签名变更 | 零语义改动 |
| 合并同类函数 | 纯搬运，不做重构 |
| pipeline_engine.py 的修改 | 两套并行，不改现有 engine |
| 代码优化 / bug 修复 | R137 只搬不改，优化留给后续轮次 |

### 4.3 验证方法

```bash
# 无 ImportError
python3 -c "from server.ws_server import main"
python3 -c "from server.ws_server import engine2"

# 功能测试
##start##R137-test##task=dev##steps=3    # 管线启动正常
##status##R137-test                        # 查询正常
##stop##R137-test                          # 停止正常
##step##complete##...                      # 步骤完成正常
```

---

## 5. 验收标准

| # | 验收项 | 类型 | 状态 |
|:-:|:-------|:----:|:----:|
| EXT-A | `engine2.py` 创建，从 main.py 迁移 ~1,200 行管线逻辑 | P0 | ⬜ |
| EXT-B | scenario_matcher `##` 命令路由指向 engine2，非 main | P0 | ⬜ |
| EXT-C | main.py 精简至 ~800 行，管线代码已删除 | P0 | ⬜ |
| EXT-D | `python3 -c "from server.ws_server import engine2"` 无 ImportError | P0 | ⬜ |
| EXT-D | `python3 -c "from server.ws_server import main"` 无 ImportError（无循环依赖） | P0 | ⬜ |
| T1 | `##start##R137-test##task=dev##steps=2` 正常启动 | P0 | ⬜ |
| T2 | `##status##R137-test` 正常查询 | P0 | ⬜ |
| T3 | `##stop##R137-test` 正常停止 | P0 | ⬜ |
| T4 | 自动派活消息正常送到目标 agent | P0 | ⬜ |
| T5 | 已完成 ✅ 自动推进正常 | P0 | ⬜ |
| T6 | 退回 🔄 驳回回退正常 | P0 | ⬜ |
| T7 | PM 通知正常送达 | P0 | ⬜ |
| T8 | `handle_broadcast` 非管线消息路由正常 | P0 | ⬜ |
| T9 | 规则 10/20/30/40/50/60/70/90 路由正常 | P0 | ⬜ |
| T10 | ACK 状态机正常（pipeline_engine 不受影响） | P1 | ⬜ |

---

## 6. 方向决定

| 决定事项 | 选择 | 说明 |
|:---------|:-----|:------|
| 实现范围 | 仅服务端 | `server/ws_server/` |
| engine2 形式 | 模块级函数文件（非 class） | 维持 main.py 现有风格，方便纯搬 |
| `_ensure_pipeline_manager()` 处理 | lazy import `from .main import ...` | 避免循环依赖 |
| `_ensure_engine()` 处理 | 保留在 main.py，engine2 lazy import | engine 构造依赖多个外部回调 |
| `pipeline_engine.py` | 本轮不动 | 两套并行，R138 再合并 |
| 不做的 | 函数重命名/参数变更/逻辑优化 | 零语义改动 |

---

## 7. 开放问题

| # | 问题 | 建议方向 | 决策者 |
|:-:|:-----|:--------|:------|
| 1 | `_ensure_engine()` 是否可迁入 engine2？当前依赖 `commands/pipeline.py` 函数 + `_send` 回调 | 保留在 main.py，engine2 lazy import | 🧐 PM |
| 2 | `_connections` 在 engine2 中被若干工具函数读取，是否需要通过 `connection_manager` 统一引用？ | 直接 `from .connection_manager import _connections`（已有 R136 提取） | 项目负责人 |
| 3 | `_restore_pipeline_timers` 和 `_restore_pipeline_dispatches` 被 `handle_broadcast` 调用（L559），搬迁后 main.py 如何引用？ | engine2 导出，main 从 engine2 import | 🧐 PM |

---

> **审核记录：**
> - v1.0 提交审核：[@2026-07-20]
> - 项目负责人审核意见：
> - 结论：⬜ 待审核
