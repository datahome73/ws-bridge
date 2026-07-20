# R134 技术方案 — 代码精简轮：! 命令体系 + Workspace + AutoRouter 清理

| 字段 | 内容 |
|:-----|:------|
| **版本** | v1.0 |
| **作者** | Hermes Agent |
| **轮次** | R134 |
| **类型** | 代码清理轮（纯删除 + 精简） |
| **净预估** | **~-3,870 行**（含 audit 修正） |

---

## 1. 问题与目标

R131（##query）+ R132（##step）完成后，`!` 命令体系已被 `##` 命令全面替代。旧 `!` 命令代码 + 已废弃的 Workspace 子系统 + 已退役的 AutoRouter 保留大量死代码。本轮将其**一次清理**。

---

## 2. 代码审计 — 实际行号 + 依赖分析

### 2.1 待删除文件

| 文件 | 行数 | 外部引用 | 风险 |
|:-----|:----:|:---------|:----:|
| `commands/__init__.py` | 202 | `main.py L1599: from .commands import _ADMIN_COMMANDS` | 🟢 仅 ! 路由使用，同轮删除 |
| `commands/workspace.py` | 455 | `commands/__init__.py`（同轮删除） | 🟢 无独立外部引用 |
| `commands/admin.py` | 176 | `commands/__init__.py`（同轮删除） | 🟢 无独立外部引用 |
| `commands/agent_card.py` | 258 | `commands/__init__.py`（同轮删除） | 🟢 无独立外部引用 |
| `commands/task.py` | 197 | `main.py L52: from .commands.task import _cmd_task_update` | 🔶 需先迁移 `_cmd_task_update` |
| `command_utils.py` | 205 | `main.py L22/L30`, `main.py L2482`, `scenario_matcher.py L592` | 🔶 `_refresh_role_agent_map` + `_broadcast_to_channel` 被 main.py 使用 |
| `workspace.py` | 460 | `auth.py L30/L54`（懒导入）, `__main__.py` 全文件引用, `main.py L3872-4470` | 🔴 **auth.py 依赖需清理** |
| `workspace_api.py` | 37 | `viewer.py` HTTP poll | 🟢 viewer.py 同轮清理 |
| `auto_router.py` | 750 | **无任何 import 引用**（仅 CLI 入口） | 🟢 安全删除 |

### 2.2 `command_utils.py` 引用审计

| 符号 | 使用者 | 操作 |
|:-----|:-------|:-----|
| `_parse_command()` | `main.py L1596-1618`（! route，同轮删除） | 🗑️ 可删 |
| `_check_command_permission()` | `main.py L1606`（! route） | 🗑️ 可删 |
| `_log_audit()` | `commands/*.py` 全部同轮删除 | 🗑️ 可删 |
| `_resolve_workspace()` | `commands/*.py` + `command_utils.py` 内部 | 🗑️ 可删 |
| `_broadcast_to_channel()` | `main.py L30` 导入，被多处引用 | 🔶 **需保留或迁移** |
| `_send_cmd_response()` | `commands/*.py`（同轮删除） | 🗑️ 可删 |
| `_refresh_role_agent_map()` | `main.py L30` 导入，`main.py L67` 使用 | 🔶 **需保留或迁移** |
| `_is_any_workspace_admin()` | `main.py L2482`（`_can_broadcast`） | 🗑️ workspace 删除后移除 |

**结论：** `command_utils.py` 不能整体删除，其 2 个函数（`_broadcast_to_channel`、`_refresh_role_agent_map`）有活跃引用。应拆解：删除死函数，保留活跃函数到 `state.py` 或简化到 `main.py`。

### 2.3 `auth.py` workspace 依赖（需求文档未提及）

`server/common/auth.py` 有 3 个 workspace 相关函数：

| 函数 | L | 实现 | 调用者 |
|:-----|:-:|:-----|:-------|
| `is_workspace_admin(ws_id, agent_id)` | L25-36 | 懒导入 `workspace` 模块 | `can_manage_workspace()` |
| `can_manage_workspace(ws_id, agent_id)` | L45-47 | 调用 `is_workspace_admin` | `main.py L3885/3908/4442` |
| `set_workspace_admin(ws_id, agent_id, by_agent)` | L50-58 | 懒导入 `workspace` 模块 | `main.py L3930/4350` |

**操作：** 删除这 3 个函数。调用者（main.py workspace msg_type handlers）同轮删除。

### 2.4 `__main__.py` workspace 引用（远超 80 行估算）

| 区间(L) | 内容 | 行数 |
|:--------|:-----|:----:|
| L19 | `from . import workspace as ws_mod` | 1 |
| L124-210 | workspace_create / create_approved / close / add_member / remove_member handler | ~86 |
| L229-246 | admin_request handler（导入 workspace） | ~17 |
| L275-295 | approve_admin_request handler（导入 workspace） | ~20 |
| L321 | resolved_ws = workspace 查询 | 1 |
| L343-363 | reject_admin_request handler（导入 workspace） | ~20 |
| L396-447 | workspace 相关 msg_type 路由 + approve/reject | ~51 |
| L489-496 | workspace state 检查 | ~7 |
| L610-644 | workspace module 多处引用 | ~34 |
| L797 | `ws_mod.init()` | 1 |
| **合计** | | **~238 行** |

### 2.5 `main.py` workspace 引用（远超 20 行估算）

| 区间(L) | 内容 | 行数 |
|:--------|:-----|:----:|
| L24 | `from . import workspace as ws_mod` | 1 |
| L2177-2198 | `_notify_member_changed()` | ~22 |
| L2405-2463 | `_broadcast_workspace_ready()` / stage_completed | ~58 |
| L2482 | `_is_any_workspace_admin` 在 `_can_broadcast` | 1 |
| L2495-2506 | workspace channel 权限检查（`get_workspace_members`, `can_send_in_token_mode`） | ~12 |
| L3811-3920 | MSG_WORKSPACE_CREATE / CLOSE / ADD_MEMBER / REMOVE_MEMBER handlers | ~110 |
| L4041-4050 | MSG_WORKSPACE_RESET handler | ~10 |
| L4464-4470 | MSG_WORKSPACE_ACK_CLOSE handler | ~7 |
| L4570-4650 | `_broadcast_workspace_closing()`, `_broadcast_workspace_archived()` | ~80 |
| **合计** | | **~300 行** |

### 2.6 ! 命令路由引用（main.py）

| 区间(L) | 内容 | 行数 |
|:--------|:-----|:----:|
| L22 | `from . import command_utils` | 1 |
| L30 | `from .command_utils import _refresh_role_agent_map, _broadcast_to_channel` | 1 |
| L1522 | `await _handle_server_query(ws, sender_id, content)` | 1 |
| L1545 | `if not content.startswith("!"):` → 检查 | 1 |
| L1594-1618 | `is_task = ... or content.startswith("!")` + ! 命令路由段 | ~25 |
| L1637 | `if not content.startswith("!"):` | 1 |
| L2082-2175 | `_handle_server_query()` 函数 | ~94 |
| L4834-4838 | `_sm_handle_exclamation()` | ~5 |
| L4938-4943 | `match_exclamation` 规则注册 | ~6 |
| **合计** | | **~135 行** |

### 2.7 `scenario_matcher.py` ! 命令引用

| 区间(L) | 内容 | 行数 |
|:--------|:-----|:----:|
| L155-158 | `match_exclamation()` 函数 | ~4 |
| L167 | `handle_hash_cmd` — 不受影响 | — |
| L592 | `from .commands.pipeline import (...) ` — 保留 | — |

### 2.8 Web UI workspace 引用

| 文件 | 区间 | 内容 | 行数 |
|:-----|:-----|:-----|:----:|
| `templates.py` | L508-550 | workspace Tab HTML/JS 渲染 | ~42 |
| `templates.py` | L733-748 | workspace poll + history tab 检测 | ~15 |
| `viewer.py` | L235-245 | `fetch_workspaces()` HTTP poll 函数 | ~10 |
| `viewer.py` | L329-335 | `get_available_channels()` workspace 解析 | ~6 |
| `viewer.py` | L447-487 | archive API workspace 查询 | ~40 |
| **合计** | | | **~113 行** |

> ⚠️ `viewer.py` L447-487 的 archive API 使用 `workspace_id` 作为查询参数，但这是**归档查询**功能（显示历史记录），并非 workspace 管理。删除 workspace 后，archive 逻辑需改用 `channel_id` 或 `round_name` 查询。需确认 archive API 是否与 workspace 强耦合。

---

## 3. 清理方案

### 3.1 分批执行顺序

依赖顺序：`command_utils.py` 需在 `commands/*.py` 删除前拆解。`commands/task.py` 需先迁移 `_cmd_task_update`。

#### Batch A: 命令工具函数拆解（command_utils.py）

| # | 操作 | 细节 |
|:-:|:-----|:------|
| A1 | 🔧 解绑 | 将 `_broadcast_to_channel()` 从 command_utils.py 移至 `state.py` 或 `main.py` |
| A2 | 🔧 解绑 | 将 `_refresh_role_agent_map()` 从 command_utils.py 移至 `state.py` 或 `main.py` |
| A3 | 🔧 清理 | `main.py L30` 改为从新位置导入 |
| A4 | ❌ 删除 | `command_utils.py` 整体删除（剩余函数全是 ! 命令专用死代码） |

#### Batch B: 文件直接删除（无依赖）

| # | 操作 | 文件 |
|:-:|:-----|:------|
| B1 | ❌ 删除 | `commands/__init__.py` |
| B2 | ❌ 删除 | `commands/workspace.py` |
| B3 | ❌ 删除 | `commands/admin.py` |
| B4 | ❌ 删除 | `commands/agent_card.py` |
| B5 | ❌ 删除 | `workspace_api.py` |
| B6 | ❌ 删除 | `auto_router.py` |

#### Batch C: task.py 删除 + `_cmd_task_update` 迁移

| # | 操作 | 文件 | 细节 |
|:-:|:-----|:-----|:------|
| C1 | 🔧 迁移 | `pipeline_engine.py` | 将 `_cmd_task_update` 逻辑（含 task_store 操作）作为 `PipelineEngine` 内部方法 |
| C2 | 🔧 更新 | `main.py L52` | 删除 `from .commands.task import _cmd_task_update` |
| C3 | 🔧 更新 | `main.py L61` | 删除 `cmd_task_update=_cmd_task_update` 参数 |
| C4 | ❌ 删除 | `commands/task.py` | |

#### Batch D: scenario_matcher.py 清理

| # | 操作 | 文件 | 细节 |
|:-:|:-----|:-----|:------|
| D1 | ❌ 删除 | `scenario_matcher.py L155-158` | `match_exclamation()` 函数 |

#### Batch E: main.py ! 命令清理

| # | 操作 | 细节 |
|:-:|:-----|:------|
| E1 | ❌ 删除 L22 | `from . import command_utils` 导入 |
| E2 | ❌ 删除 L30 | `from .command_utils import _refresh_role_agent_map, _broadcast_to_channel`（改从新位置导入） |
| E3 | ❌ 删除 L1522 | `await _handle_server_query(ws, sender_id, content)` 调用 |
| E4 | 🔧 修改 L1545 | `if not content.startswith("!")` 检查移除 |
| E5 | ❌ 删除 L1594-1618 | ! 命令路由段（`is_task = bool(mention_names) or content.startswith("!")` → `is_task = bool(mention_names)`） |
| E6 | 🔧 修改 L1637 | `if not content.startswith("!")` 检查移除 |
| E7 | ❌ 删除 L2082-2175 | `_handle_server_query()` 完整函数 |
| E8 | ❌ 删除 L4834-4838 | `_sm_handle_exclamation()` |
| E9 | ❌ 删除 L4938-4943 | `match_exclamation` 规则注册 |

#### Batch F: main.py workspace 清理

| # | 操作 | 细节 |
|:-:|:-----|:------|
| F1 | ❌ 删除 L24 | `from . import workspace as ws_mod` |
| F2 | ❌ 删除 L2177-2198 | `_notify_member_changed()` |
| F3 | ❌ 删除 L2405-2463 | `_broadcast_workspace_ready()` |
| F4 | 🔧 修改 L2482 | 删除 `_is_any_workspace_admin` 检查行 |
| F5 | ❌ 删除 L2495-2506 | workspace channel 权限检查块 |
| F6 | ❌ 删除 L3811-3920 | 5 个 workspace msg_type handlers |
| F7 | ❌ 删除 L4041-4050 | MSG_WORKSPACE_RESET handler |
| F8 | ❌ 删除 L4464-4470 | MSG_WORKSPACE_ACK_CLOSE handler |
| F9 | ❌ 删除 L4570-4650 | `_broadcast_workspace_closing()` + `_broadcast_workspace_archived()` |

#### Batch G: auth.py workspace 函数清理

| # | 操作 | 细节 |
|:-:|:-----|:------|
| G1 | ❌ 删除 L25-36 | `is_workspace_admin()` 函数 |
| G2 | ❌ 删除 L45-47 | `can_manage_workspace()` 函数 |
| G3 | ❌ 删除 L50-58 | `set_workspace_admin()` 函数 |

#### Batch H: __main__.py workspace 清理

| # | 操作 | 细节 |
|:-:|:-----|:------|
| H1 | ❌ 删除 L19 | `from . import workspace as ws_mod` |
| H2 | ❌ 删除 L124-210 | workspace_create / close / add_member / remove_member handler |
| H3 | ❌ 删除 L229-296 | admin_request / approve_admin_request handler |
| H4 | ❌ 删除 L321 | resolved_ws workspace 查询 |
| H5 | ❌ 删除 L343-447 | reject_admin_request + workspace msg_type 路由 |
| H6 | ❌ 删除 L489-496 | workspace state 检查 |
| H7 | ❌ 删除 L610-644 | workspace module 多处引用 |
| H8 | ❌ 删除 L797 | `ws_mod.init()` |

#### Batch I: Web UI workspace 清理

| # | 操作 | 文件 | 细节 |
|:-:|:-----|:-----|:------|
| I1 | ❌ 删除 L508-550 | `templates.py` — workspace Tab HTML/JS |
| I2 | ❌ 删除 L733-748 | `templates.py` — workspace poll |
| I3 | ❌ 修改 L222 | `templates.py` — `m._workspace_event` 检查（删除） |
| I4 | ❌ 删除 L235-245 | `viewer.py` — `fetch_workspaces()` |
| I5 | ❌ 删除 L329-335 | `viewer.py` — `get_available_channels()` workspace 解析 |
| I6 | 🔧 修改 L447-487 | `viewer.py` — archive API workspace_id 改为 channel_id 查询 |
| I7 | ❌ 删除 L127-131 | `viewer.py` — `record_workspace_archive()` |

#### Batch J: pipeline.py 精简

保留的函数（活跃引用，被 `scenario_matcher` / `main` 使用）：

| 函数 | 使用者 |
|:-----|:--------|
| `_cmd_step_complete` | `scenario_matcher.handle_step` |
| `_cmd_step_reject` | `scenario_matcher.handle_step` |
| `_cmd_step_force` | `scenario_matcher.handle_step` |
| `_cmd_step_handoff` | `scenario_matcher.handle_step` |
| `_get_step_config` | `main._ensure_engine` |
| `_find_agents_by_role` | `main._ensure_engine` |
| `_set_pipeline_state` | `main._ensure_engine` |
| `_step_sort_key` | `main._ensure_engine` |

删除的 handler（已被 `##` 命令替代，~885 行）：

| 删除函数 | 估算行数 |
|:---------|:--------:|
| `_handle_pipeline_command` | ~144 |
| `_cmd_pipeline_start` | ~139 |
| `_cmd_pipeline_activate` | ~45 |
| `_cmd_pipeline_stop` | ~66 |
| `_cmd_pipeline_status` | ~155 |
| `_cmd_pipeline_mode` | ~27 |
| `_cmd_pipeline_role_override` | ~38 |
| `_cmd_step_verify` | ~59 |
| `_send_inbox_task` | ~111 |
| `_check_pm_or_admin` | ~16 |
| `_run_validation_hook` | ~46 |
| `pipeline_is_active`, `pipeline_exists`, `set_lobby_paused` | ~18 |
| 相关 import + 辅助引用 | ~20 |

---

## 4. 执行顺序总表

依赖关系：A → B/D/E → C → F → G → H → I → J

```
A  拆解 command_utils（移活跃函数）
↓
B  删除 6 个独立文件（无依赖）
D  清理 scenario_matcher（match_exclamation）
E  清理 main.py ! 命令代码段
↓
C  迁移 _cmd_task_update → pipeline_engine + 删除 task.py
↓
F  清理 main.py workspace 代码段（ws_mod, handlers, broadcast）
G  清理 auth.py workspace 函数
↓
H  清理 __main__.py workspace handler
↓
I  清理 Web UI workspace 引用
↓
J  精简 pipeline.py（删除 ! handler，保留 step ops + tools）
```

---

## 5. 侧效应分析

| 影响 | 分析 | 风险 |
|:-----|:-----|:----:|
| `_can_broadcast()` 缺少 workspace 通道 | L2495-2506 删除后，workspace 通道消息不再有成员检查。但 workspace 已废弃，无实际影响 | 🟢 |
| `auth.py` 导出接口减少 | `can_manage_workspace` / `set_workspace_admin` 所有调用者同轮删除 | 🟢 |
| `_broadcast_to_channel` 位置变化 | 移入 state.py 或 main.py，导入路径更新即可 | 🟢 |
| `_refresh_role_agent_map` 位置变化 | 同上 | 🟢 |
| `viewer.py` archive API workspace_id → channel_id | 需确认 archive 功能独立于 workspace。当前 archive 按 workspace_id 分组，删除 workspace 后需改用 `channel` 字段 | 🔶 |
| `templates.py` L222 `m._workspace_event` | workspace 事件标记，删除后 archive 事件可能不再被标记 | 🔶 需检查 |
| `data/workspaces.json` | 持久化文件，不删除代码。部署时清理 | 🟢 |
| `##query##whoami` / `##step##complete` | 完全不受影响（走 scenario_matcher 规则表） | 🟢 |
| `##start##R134` | 不受影响（走 pipeline_engine） | 🟢 |
| `to_agent` 派活 | 不受影响（走 rule 20） | 🟢 |

---

## 6. 验证验收标准

### CLN 组 — ! 命令清理（12 项）

| # | 验收项 |
|:-:|:-------|
| CLN-1 | `commands/__init__.py` 已删除 |
| CLN-2 | `commands/workspace.py` 已删除 |
| CLN-3 | `commands/admin.py` 已删除 |
| CLN-4 | `commands/agent_card.py` 已删除 |
| CLN-5 | `command_utils.py` 已删除 |
| CLN-6 | `commands/pipeline.py` 已精简，无 ! handler 残留 |
| CLN-7 | `commands/task.py` 已删除，`_cmd_task_update` 已迁移 |
| CLN-8 | `main.py` `!` 命令路由段（L1594-1618）已删除 |
| CLN-9 | `main.py` `_handle_server_query()` 已删除 |
| CLN-10 | `main.py` `_sm_handle_exclamation()` 已删除 |
| CLN-11 | `scenario_matcher.py` `match_exclamation` 已删除 |
| CLN-12 | `auto_router.py` 已删除 |

### WKS 组 — Workspace 清理（6 项）

| # | 验收项 |
|:-:|:-------|
| WKS-1 | `workspace.py` 已删除 |
| WKS-2 | `workspace_api.py` 已删除 |
| WKS-3 | `__main__.py` workspace handler 已删除 |
| WKS-4 | `main.py` ws_mod 导入 + 调用已删除 |
| WKS-5 | `templates.py` 工作区 Tab 已删除 |
| WKS-6 | `viewer.py` workspace API 已删除 |

### RV 组 — 回归验证（8 项）

| # | 验收项 |
|:-:|:-------|
| RV-1 | `##query##whoami` / `##query##status` / `##query##help` 正常 |
| RV-2 | `##step##complete##R133` 推进正常 |
| RV-3 | `##start##R134` 创建管线正常 |
| RV-4 | `_inbox:server` 收消息 + to_agent 派活 + ✅ 完成推进正常 |
| RV-5 | py_compile 所有 .py 文件零错误 |
| RV-6 | `from server.ws_server import main` 无 ImportError |
| RV-7 | `__main__.py` 启动路由无缺失端点 |
| RV-8 | Web UI 加载正常（📬 收件箱 + 📊 管线 Tab 可见） |

---

## 7. 不做事项

| 事项 | 理由 |
|:-----|:------|
| 不删 `audit.py` | `##query##audit` 仍使用 AuditLogger |
| 不删 `task_store.py` | PipelineEngine list_tasks_by_context 仍使用 |
| 不改 `##` 命令逻辑 | 只删 ! 死代码，不动活跃 ## 功能 |
| 不改 inbox-message-protocol.md | 纯代码清理，不涉及协议 |
| 不改 server/README.md | 清理验证通过后单独更新 |
| 不重构 main.py | 只删死代码行，不做提取/重构 |
| 不修改 pipeline_engine.py 核心逻辑 | 仅迁入 `_cmd_task_update` |

---

*技术方案结束*
