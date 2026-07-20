# R134 需求文档 — 代码精简轮：! 命令体系 + Workspace 清理

| 字段 | 内容 |
|:-----|:------|
| **版本** | v1.0 |
| **作者** | 小谷 (PM) |
| **状态** | 📝 草稿待审 |
| **类型** | 代码清理轮 |
| **前置轮次** | R131 (##query 迁移)、R132 (##step 迁移) |

---

## §1 背景与目标

### 1.1 现状

经过 R131（##query 命令族，6 个 ! 命令规则化）和 R132（##step 规则组，步骤操作迁移）两轮后，`!` 命令体系已被 `##` 命令全面替代。但旧 `!` 命令的代码仍然保留，形成双倍维护负担：

| 体系 | 路由方式 | 状态 |
|:-----|:---------|:-----|
| `##` 命令 (##query / ##step / ##start 等) | `scenario_matcher.py` 规则表 → `handle_query` / `handle_step` / `pipeline_engine` | ✅ 当前活跃 |
| `!` 命令 (旧 47 个命令) | `main.py` 硬编码路由 → `commands/_ADMIN_COMMANDS` 注册表 → 各 handler | ❌ **已废弃，代码残留** |

同时，Workspace（工作区）子系统作为早期 bot 协作的频道模型，已被 Inbox 通道体系完全替代。目前所有消息收发走 `_inbox:` 前缀通道，workspace 相关的 CRUD、生命周期、持久化、HTTP API 和 Web UI Tab 全是死代码。

### 1.2 本轮目标

> **清理已经废弃的 `!` 命令完整路由链路和 Workspace 子系统，减掉维护负担。**

### 1.3 清理范围总览

| 子系统 | 涉及文件 | 估算删除/精简行数 |
|:-------|:---------|:-----------------:|
| 🗑️ ! 命令路由链路 | `main.py` (~90行)、`command_utils.py` (205行)、`commands/__init__.py` (202行) | **~500 行** |
| 🗑️ ! 命令 handler: workspace | `commands/workspace.py` (455行) | **455 行** |
| 🗑️ ! 命令 handler: admin | `commands/admin.py` (176行) | **176 行** |
| 🗑️ ! 命令 handler: agent_card | `commands/agent_card.py` (258行) | **258 行** |
| 🔧 ! 命令 handler: pipeline (精简) | `commands/pipeline.py` (2085→~1200行) | **~-885 行** |
| 🔧 ! 命令 handler: task (精简) | `commands/task.py` (197→~30行) | **~-167 行** |
| 🗑️ Workspace 核心 | `workspace.py` (460行) + `workspace_api.py` (37行) | **497 行** |
| 🗑️ Workspace 路由 | `__main__.py` 消息类型 handler (~80行) | **80 行** |
| 🔧 Workspace 引用清理 | `main.py`、`web_ui/templates.py`、`web_ui/viewer.py` | **~-60 行** |
| 🗑️ ! 命令规则 + handler | `scenario_matcher.py` 中 `match_exclamation` + 注册 | **~15 行** |
| | **合计** | **~-3,000 行** |

> 清理后 server 目录从当前 **33 文件 / ~17,100 行** 降至 **~27 文件 / ~14,100 行**，减负约 17%。

---

## §2 清理方案

### 2.1 ! 命令体系链路清理

**当前 ! 命令消息的完整路径：**
```
用户发 "!agent_card list"
  ↓
main.py L1596: handle_broadcast 检测 content.startswith("!")
  ↓
main.py L1599: 导入 commands._ADMIN_COMMANDS 注册表
  ↓
command_utils._parse_command() 解析命令名和参数
command_utils._check_command_permission() 检查权限
  ↓
commands/agent_card.py → _cmd_agent_card_list() 执行
  ↓
command_utils._log_audit() 记日志
  ↓
回复到发送者的 inbox 通道
```

**! 命令还有第二条路径**（通过 `_inbox:server` 发到 server）：
```
scenario_matcher.py: match_exclamation (Rule 80) 匹配 "!" 开头
  ↓
main.py: _sm_handle_exclamation → return False（透传到 handle_broadcast 正常路由）
  ↓
main.py L1596: handle_broadcast 的 ! 命令路由（同上）
  ↓
main.py L2070: _handle_server_query() 处理部分 ! 命令
```

**移除方案（P0）：**

| 文件 | 操作 | 说明 |
|:-----|:----:|:------|
| `commands/__init__.py` | ❌ 删除 | 整个 `_ADMIN_COMMANDS` 注册表是死代码 |
| `commands/workspace.py` | ❌ 删除 | 所有 `!workspace` 命令 handler |
| `commands/admin.py` | ❌ 删除 | 所有 `!admin` 命令 handler |
| `commands/agent_card.py` | ❌ 删除 | 所有 `!agent_card` 命令 handler |
| `command_utils.py` | ❌ 删除 | 仅被 ! 命令系统使用的工具函数 (`_parse_command`, `_check_command_permission`, `_log_audit`, `_resolve_workspace`, `_broadcast_to_channel`, `_send_cmd_response`, `_refresh_role_agent_map`, `_is_any_workspace_admin`) |
| `commands/pipeline.py` | 🔧 精简 | 保留 `_cmd_step_complete` / `_cmd_step_reject` / `_cmd_step_force` / `_cmd_step_handoff`（被 scenario_matcher 使用）+ `_get_step_config` / `_find_agents_by_role` / `_set_pipeline_state` / `_step_sort_key`（被 main.py PipelineEngine 使用）；删除 `!pipeline_start` / `!pipeline_stop` / `!pipeline_status` / `!pipeline_activate` / `!pipeline_mode` / `!pipeline_role_override` / `!step_verify` 等 handler |
| `commands/task.py` | 🔧 精简 | 保留 `_cmd_task_update`（被 main.py PipelineEngine 使用）；删除 `!task_create` / `!task_query` / `!task_list` / `!rollcall_role` / `!rollcall_next` |
| `main.py` | 🔧 清理 | 删除 `!` 命令路由段（L1596-1618）、`_handle_server_query` 函数（L2070-2170）、`_sm_handle_exclamation` 函数（L4834-4838）、`!` 命令规则注册（L4937-4943） |
| `scenario_matcher.py` | 🔧 清理 | 删除 `match_exclamation` 函数（L155-158） |

### 2.2 Workspace 子系统清理

Workspace（工作区）是早期 bot 协作的频道模型。当前消息路由已完全走 Inbox 通道体系（`_inbox:` 前缀），workspace 概念已废弃。

**清理范围（P0）：**

| 文件 | 操作 | 行数 | 说明 |
|:-----|:----:|:----:|:------|
| `workspace.py` | ❌ 删除 | 460 | 整个 Workspace 数据模型 + CRUD + 生命周期 + JSON 持久化 + 自动归档 |
| `workspace_api.py` | ❌ 删除 | 37 | HTTP API 端点 GET /api/workspaces |
| `__main__.py` | 🔧 清理 | ~-80 | 删除 workspace_create / workspace_create_approved / workspace_close / workspace_ack_close / workspace_add_member / workspace_remove_member 消息类型 handler |
| `main.py` | 🔧 清理 | ~-20 | 删除 `ws_mod` 导入 (L24) 和活跃引用（`!list_workspaces` handler 等） |
| `web_ui/templates.py` | 🔧 清理 | ~-20 | 删除 📂 工作区 Tab（HTML/CSS/JS） |
| `web_ui/viewer.py` | 🔧 清理 | ~-20 | 删除 `/api/workspaces` 代理路由和相关函数 |
| `data/workspaces.json` | 🧹 可删除 | — | 持久化文件，部署时清空 |
| `ws_server/commands/workspace.py` | ❌ 已在 2.1 删除 | 455 | 同上 |

### 2.3 保留（本轮不碰）

| 文件 | 行数 | 保留理由 |
|:-----|:----:|:---------|
| `audit.py` | 94 | `##query##audit` 命令仍使用 `AuditLogger` 查询审计日志 |
| `auto_router.py` | 750 | 独立 CLI 脚本，不阻塞 — 已有 R129 确认保留 |
| `task_store.py` | 184 | `_cmd_task_update` 可能还用到 (待 Arch 确认) |
| `agent_card.py` (ws_server/) | 429 | Agent Card 被 ##query##agent_info / pipeline_engine 使用 |

---

## §3 架构决策

### 3.1 精简后的 `commands/` 目录结构

```diff
 commands/
-├── __init__.py         (202行，! 命令注册表)
-├── admin.py            (176行，废弃 !admin)
-├── agent_card.py       (258行，废弃 !agent_card)
-├── pipeline.py         (2085→~1200行，保留 step ops + 工具函数)
-├── task.py             (197→~30行，保留 _cmd_task_update)
-└── workspace.py        (455行，废弃 !workspace)
+└── pipeline.py         (~1200行，精简后)
+└── task.py             (~30行，精简后)
```

> 若精简后 `commands/` 目录只有 2 个文件，可考虑将 `pipeline.py` 重命名为 `step_ops.py` 并移到 `commands/` 目录外。

### 3.2 main.py 清理

清理后 main.py 从 ~4,951 行降至 ~4,850 行。核心变化：

| 删除段 | 行数 | 说明 |
|:-------|:----:|:------|
| `!` 命令路由 (`if content.startswith("!"):`) | ~25 行 | L1596-1619 |
| `_handle_server_query()` 函数 | ~80 行 | L2070-2170 |
| `_sm_handle_exclamation()` | ~5 行 | L4834-4838 |
| `match_exclamation` 规则注册 | ~6 行 | L4937-4943 |
| `ws_mod` 导入（如果不再被使用） | ~1 行 | L24 |

### 3.3 Workspace 拆除影响

删除 workspace.py 后需处理：
1. `__main__.py` 中 `from . import workspace as ws_mod` + 6 个 ws msg_type handler
2. `commands/__init__.py` 中 workspace 命令导入（该文件已整体删除）
3. `viewer.py` 中 workspace poll API
4. `templates.py` 中 📂 工作区 Tab（包括 HTML 标签、JS 切换逻辑、CSS 样式）
5. `main.py` 中 `ws_mod.` 调用（`!list_workspaces` handler 等）

> ⚠️ 注意事项：`main.py` 中 `ws_mod.get_workspace()` 在多个函数中被用于 **频道解析**（判断一个 channel 是否为 workspace）。Arch 需确认这些用途是否可移除或替换为 `_inbox:` 前缀检查。

---

## §4 验收标准

### CLN: ! 命令清理（P0）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| CLN-1 | `commands/__init__.py` 已删除 | 代码 | P0 |
| CLN-2 | `commands/workspace.py` 已删除 | 代码 | P0 |
| CLN-3 | `commands/admin.py` 已删除 | 代码 | P0 |
| CLN-4 | `commands/agent_card.py` 已删除 | 代码 | P0 |
| CLN-5 | `command_utils.py` 已删除 | 代码 | P0 |
| CLN-6 | `commands/pipeline.py` 中 `!_cmd_pipeline_*` 命令 handler 已删除，保留 step ops + 工具函数 | 代码 | P0 |
| CLN-7 | `commands/task.py` 中 `!task_*` / `!rollcall_*` handler 已删除，保留 `_cmd_task_update` | 代码 | P0 |
| CLN-8 | `main.py` 中 `!` 命令路由段 (L1596-1618) 已删除 | 代码 | P0 |
| CLN-9 | `main.py` 中 `_handle_server_query` 函数已删除 | 代码 | P0 |
| CLN-10 | `main.py` 中 `_sm_handle_exclamation` 函数已删除 | 代码 | P0 |
| CLN-11 | `scenario_matcher.py` 中 `match_exclamation` + 规则注册已删除 | 代码 | P0 |

### WKS: Workspace 清理（P0）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| WKS-1 | `workspace.py` 已删除 | 代码 | P0 |
| WKS-2 | `workspace_api.py` 已删除 | 代码 | P0 |
| WKS-3 | `__main__.py` 中 workspace msg_type handler 已删除 | 代码 | P0 |
| WKS-4 | `main.py` 中 `ws_mod` 导入和关联调用已删除 | 代码 | P0 |
| WKS-5 | `web_ui/templates.py` 中 📂 工作区 Tab 已删除 | 代码 | P0 |
| WKS-6 | `web_ui/viewer.py` 中 workspace API 路由已删除 | 代码 | P0 |

### RV: 回归验证（P0）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| RV-1 | `##query##whoami` / `##query##status` / `##query##help` 正常工作 | 功能 | P0 |
| RV-2 | `##step##complete##R133` 推进步骤正常 | 功能 | P0 |
| RV-3 | `##start##R134` 创建管线正常 | 功能 | P0 |
| RV-4 | `_inbox:server` 收消息/派活正常（to_agent）+ ✅ 完成推进 | 功能 | P0 |
| RV-5 | `py_compile` 所有 .py 文件零错误 | 校验 | P0 |
| RV-6 | `python3 -c "from server.ws_server import main"` 启动导入无 ImportError | 校验 | P0 |
| RV-7 | `__main__.py` 启动路由无缺失端点的 RuntimeError | 校验 | P0 |
| RV-8 | Web UI 加载正常（📬 收件箱 / 📊 管线 Tab 可见，其余不受影响） | 功能 | P0 |

---

## §5 不做事项

| # | 事项 | 理由 |
|:-:|:-----|:------|
| ❌ | **不删 `auto_router.py`** | R129 已确认保留为独立 CLI 脚本，不影响 server 启动 |
| ❌ | **不删 `audit.py`** | `##query##audit` 命令仍使用 `AuditLogger` |
| ❌ | **不删 `task_store.py`** | `_cmd_task_update` 调用 task_store，需 Arch 确认是否可移除 |
| ❌ | **不改 `##` 命令逻辑** | 只删 ! 命令死代码，不碰 ## 命令的功能代码 |
| ❌ | **不改 Inbox 协议文档** | 本轮纯代码清理，不涉及协议文档修改 |
| ❌ | **不改 server/README.md** | 架构文档在清理验证通过后单独更新 |
| ❌ | **不重构 main.py** | 只删死代码行，不做提取/重构 — 留待后续轮次 |

---

## §6 验收检查表（汇总）

### 文件改动清单

| 操作 | 文件 | 行数 |
|:-----|:-----|:----:|
| ❌ 删除 | `server/ws_server/commands/__init__.py` | 202 |
| ❌ 删除 | `server/ws_server/commands/workspace.py` | 455 |
| ❌ 删除 | `server/ws_server/commands/admin.py` | 176 |
| ❌ 删除 | `server/ws_server/commands/agent_card.py` | 258 |
| ❌ 删除 | `server/ws_server/command_utils.py` | 205 |
| ❌ 删除 | `server/ws_server/workspace.py` | 460 |
| ❌ 删除 | `server/ws_server/workspace_api.py` | 37 |
| 🔧 精简 | `server/ws_server/commands/pipeline.py` | 2085→~1200 |
| 🔧 精简 | `server/ws_server/commands/task.py` | 197→~30 |
| 🔧 修改 | `server/ws_server/main.py` | 4951→~4860 |
| 🔧 修改 | `server/ws_server/__main__.py` | 846→~770 |
| 🔧 修改 | `server/ws_server/scenario_matcher.py` | 795→~780 |
| 🔧 修改 | `server/web_ui/templates.py` | 850→~830 |
| 🔧 修改 | `server/web_ui/viewer.py` | 779→~760 |
| 🧹 可清理 | `data/workspaces.json` | — |

### 验收计数

| 分组 | P0 项 | 合计 |
|:-----|:-----:|:----:|
| CLN ! 命令清理 | 11 | 11 |
| WKS Workspace 清理 | 6 | 6 |
| RV 回归验证 | 8 | 8 |
| **合计** | **25** | **25** |

---

> **审核记录：**
> - v1.0 提交审核：[@date]
> - 项目负责人审核意见：
> - 结论：⬜ 待审核
