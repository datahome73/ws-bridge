# R100 WORK_PLAN — 服务端核心重构：handler.py 拆分

> **PM**: — | **目标版本**: v3.0
> **仓库**: datahome73/ws-bridge | **分支**: dev

---

## 一、概述

将 `server/handler.py`（7024 行）按"核心消息路由 vs 插件命令"分层原则拆分为 8 个新文件。**只做结构拆分，零行为变更**。

### 核心原则

```
消息通道（核心）— 去掉则 inbox 不通
   ├── main.py  (~800行)  改名+精简
   └── handler() + handle_broadcast + relay + query
   
插件（附加）— 去掉 inbox 仍通
   ├── state.py          共享状态
   ├── command_utils.py  命令路由工具
   └── commands/         !命令处理（5领域）
```

---

## 二、Step 拆解

### Step 1: 创建 `server/state.py`

**目标**：从 handler.py 搬出全部模块级共享变量

操作：
```
1. 在 server/ 下新建 state.py
2. 从 handler.py 复制以下全局变量：
   - _PIPELINE_STATE, _PIPELINE_CONFIG
   - _step_ack_states, _ROLE_AGENT_MAP
   - _LOBBY_PAUSED, _LOBBY_PAUSED_ROUND
   - _r72_users
   - _offline_push_queue, _offline_timers
   - _delivery_status, _task_ack_timers
   - _r57_rollcall_events, _channel_ack_state
   - _GIT_SYNC_TASK, _watchdog_task, _card_watcher_running
   - SYSTEM_AGENT_ID, SERVER_INBOX_CHANNEL
   - 其他 handler.py 顶层的模块级变量
3. 保持名称不变
4. 验证：state.py 无任何 import 依赖，纯数据
```

**产出**: `server/state.py` ~200 行

---

### Step 2: 创建 `server/command_utils.py`

**目标**：从 handler.py 搬出命令路由工具函数

操作：
```
1. 在 server/ 下新建 command_utils.py
2. 从 handler.py 复制以下函数：
   - _parse_command(content) → (cmd_name, params)
   - _check_command_permission(sender_id, cmd_name, cmd, params) → (allowed, reason)
   - _send_cmd_response(ws, sender_id, from_name, content, channel)
   - _log_audit(...)
   - _broadcast_to_channel(channel, payload) → int
   - _resolve_workspace(sender_id, params) → (ws_id, error)
   - _admin_msg(content) → dict
   - _persist_admin_response(...)
3. 将引用 state.py 变量的部分改为 state.X
4. 验证：command_utils.py 只依赖 state.py + Python 标准库 + 已有 server 模块
```

**产出**: `server/command_utils.py` ~200 行

---

### Step 3: 创建 `server/commands/` 包

**目标**：从 handler.py 搬出全部 _cmd_* 函数 + _ADMIN_COMMANDS 注册表

操作：
```
3a. 创建 server/commands/ 目录 + __init__.py
    从 handler.py 复制 _ADMIN_COMMANDS dict
    导入各子模块并构建注册表

3b. server/commands/workspace.py
    _cmd_create_workspace, _cmd_close_workspace
    _cmd_list_workspaces, _cmd_workspace_join
    _cmd_workspace_leave, _cmd_workspace_add
    _cmd_workspace_remove, _cmd_workspace_list_members
    _cmd_workspace_reset

3c. server/commands/pipeline.py
    _cmd_pipeline_start, _cmd_pipeline_stop
    _cmd_pipeline_status, _cmd_pipeline_activate
    _cmd_pipeline_context, _cmd_pipeline_mode
    _cmd_pipeline_role_override
    _cmd_step_handoff, _cmd_step_complete
    _cmd_step_reject, _cmd_step_force, _cmd_step_verify
    + 全部管线辅助函数:
    _parse_frontmatter, _build_pipeline_config
    _build_fallback_config, _load_step_config
    _get_step_config, _step_sort_key
    _infer_artifact_url, _render_context
    _find_template_refs
    _set_pipeline_state, _update_pipeline_step
    _clear_pipeline_state, pipeline_is_active, pipeline_exists
    _ensure_pipeline_manager, _refresh_role_agent_map
    _ensure_agent_cards_loaded, _ensure_card_watcher
    _get_agents_by_role
    _send_inbox_task, _auto_advance_pipeline
    _verify_git_commit, _ensure_watchdog
    _ensure_git_scan, _start_git_sync_loop
    _pipeline_git_sync_scan
    _watchdog_loop, _watchdog_scan
    _get_step_timeout, _trigger_timeout_escalation
    _ack_timeout_task, _send_ack_timeout_info
    _trigger_ack_escalation, _update_step_ack_state
    _format_ack_status, _check_watchdog_alert
    _send_watchdog_alert, _watchdog_rerollcall
    _send_clear_alert
    _restore_pipeline_timers
    _broadcast_task_notify
    _cmd_step_force → _run_validation_hook
    _r57_switch_to_backup, _r57_wait_for_ack
    _r59_auto_fallback_monitor
    + 相关全局状态的引用改为 state.X
    + _broadcast_to_channel 等改为 command_utils.X

3d. server/commands/agent_card.py
    _cmd_agent_card_list, _cmd_agent_card_get
    _cmd_agent_card_set, _cmd_agent_card_unset
    _cmd_agent_card_reload, _cmd_agent_card_watch
    _cmd_agent_card_register, _cmd_agent_card_auto_register
    _cmd_agent_role_map
    + _get_agent_display, _get_agent_card_roles
    + _find_agents_by_role

3e. server/commands/task.py
    _cmd_task_create, _cmd_task_update
    _cmd_task_query, _cmd_task_list
    _cmd_rollcall_role, _cmd_rollcall_next
    + _handle_rollcall_ack
    + _task_ack_timeout, _notify_rollcall_complete
    + _channel_ack_timeout, _broadcast_workspace_ready
    + _broadcast_stage_completed

3f. server/commands/admin.py
    _cmd_approve_ws_admin, _cmd_reject_ws_admin
    _cmd_list_pending, _cmd_audit_log
    _cmd_list_workspace_admins, _cmd_list_agents
    _cmd_agent_status, _cmd_revoke_api_key
```

**注意**：每个命令函数中：
- 所有 `_PIPELINE_STATE` → `state._PIPELINE_STATE`
- 所有 `_broadcast_to_channel()` → `command_utils._broadcast_to_channel()`
- 所有 `_send_cmd_response()` → `command_utils._send_cmd_response()`
- 所有 `_log_audit()` → `command_utils._log_audit()`
- 所有 `_connections` / `_r72_users` → `state._connections` / `state._r72_users`
- 所有 `config.DATA_DIR` → 保持 `from ..config import DATA_DIR`（或从 `state` 导入）
- 所有 `ws_mod` → 保持 `from .. import workspace as ws_mod`
- 所有 `auth` → 保持 `from .. import auth`
- 所有 `ac_mod` → 保持 `from .. import agent_card as ac_mod`

**产出**:
- `server/commands/__init__.py` ~100 行
- `server/commands/workspace.py` ~500 行
- `server/commands/pipeline.py` ~1200 行
- `server/commands/agent_card.py` ~300 行
- `server/commands/task.py` ~400 行
- `server/commands/admin.py` ~200 行

---

### Step 4: handler.py → main.py

**目标**：改名并精简为核心消息路由

操作：
```
1. git mv server/handler.py server/main.py
2. 删除已搬出到 state.py 的全局变量
3. 删除已搬出到 command_utils.py 的函数
4. 删除已搬出到 commands/ 的全部 _cmd_* 函数
5. 保留：
   - handler()  WS 会话主循环
   - handle_broadcast()  消息路由 + 广播
   - _handle_server_relay()  inbox 中继
   - _handle_server_query()  _inbox:server 查询路由
   - handle_auth()  认证入口
   - handle_register()  bot 注册入口
   - handle_agent_card_register()  Agent Card 注册入口
   - _send()  WebSocket 写入
   - _connections  在线连接集合（唯一保留的全局变量）
   - msg_type 分支（handler() 内的各种 elif type 处理）
6. 添加导入：
   - from .state import ...
   - from .command_utils import ...
   - from .commands import _ADMIN_COMMANDS
7. handler() 内引用已搬变量的地方改为 state.X
8. handle_broadcast() 内 !命令路由改为 from .commands import _ADMIN_COMMANDS
```

**产出**: `server/main.py` ~800 行

---

### Step 5: 更新 `server/__main__.py`

操作：
```
1. 改 import：from .main import ... 替代 from .handler import ...
2. 检查所有用到 handler 的函数调用是否仍有效
```

**产出**: `server/__main__.py` 修改 ~5 行

---

### Step 6: 验证 + 部署

操作：
```
1. 本地启动测试
   cd /opt/data/ws-bridge
   python -m server.__main__
2. 确认服务启动无 ImportError
3. 手工通路测试
   - Bot A 连接 → 认证成功
   - Bot A → Bot B _inbox 消息
   - Bot B 回复 Bot A
   - _inbox:server 中继（ACK ✅ / ✅ 完成）
4. !命令功能抽样测试
5. 推 dev 分支
6. 通知运维部署到生产
7. 生产验证 inbox 双向通信
```

---

## 三、命令职责映射

| !命令 | 所属文件 | 搬出前所在行（handler.py） |
|---|---|---|
| `!create_workspace` | commands/workspace.py | ~645 |
| `!close_workspace` | commands/workspace.py | ~707 |
| `!list_workspaces` | commands/workspace.py | ~789 |
| `!list_agents` | commands/admin.py | ~824 |
| `!agent_status` | commands/admin.py | ~840 |
| `!approve_ws_admin` | commands/admin.py | ~866 |
| `!reject_ws_admin` | commands/admin.py | ~881 |
| `!list_pending` | commands/admin.py | ~894 |
| `!audit_log` | commands/admin.py | ~907 |
| `!list_workspace_admins` | commands/admin.py | ~932 |
| `!task_create` | commands/task.py | ~960 |
| `!task_update` | commands/task.py | ~982 |
| `!task_query` | commands/task.py | ~1031 |
| `!task_list` | commands/task.py | ~1062 |
| `!rollcall_role` | commands/task.py | ~1076 |
| `!rollcall_next` | commands/task.py | ~1107 |
| `!pipeline` | commands/pipeline.py | ~2344 |
| `!pipeline_start` | commands/pipeline.py | ~2486 |
| `!pipeline_activate` | commands/pipeline.py | ~2570 |
| `!pipeline_stop` | commands/pipeline.py | ~2614 |
| `!step_handoff` | commands/pipeline.py | ~3802 |
| `!step_complete` | commands/pipeline.py | ~2850 |
| `!step_reject` | commands/pipeline.py | ~3641 |
| `!step_force` | commands/pipeline.py | ~3309 |
| `!step_verify` | commands/pipeline.py | ~3344 |
| `!pipeline_status` | commands/pipeline.py | ~4002 |
| `!pipeline_mode` | commands/pipeline.py | ~4156 |
| `!pipeline_role_override` | commands/pipeline.py | ~4182 |
| `!agent_card` | commands/agent_card.py | ~4219 |
| `!agent_card_list` | commands/agent_card.py | ~4258 |
| `!agent_card_get` | commands/agent_card.py | ~4285 |
| `!agent_card_set` | commands/agent_card.py | ~4316 |
| `!agent_card_unset` | commands/agent_card.py | ~4330 |
| `!agent_card_reload` | commands/agent_card.py | ~4338 |
| `!agent_role_map` | commands/agent_card.py | ~4370 |
| `!agent_card_register` | commands/agent_card.py | ~4407 |
| `!agent_card_auto_register` | commands/agent_card.py | ~4436 |
| `!workspace_join` | commands/workspace.py | ~4632 |
| `!workspace_leave` | commands/workspace.py | ~4665 |
| `!workspace_add` | commands/workspace.py | ~4700 |
| `!workspace_remove` | commands/workspace.py | ~4739 |
| `!workspace_list_members` | commands/workspace.py | ~4782 |
| `!workspace_reset` | commands/workspace.py | ~3781 |
| `!revoke_api_key` | commands/admin.py | ~4822 |

---

## 四、开发约束

### 4.1 每步验证

每完成一个 Step，必须：
```
1. git commit（小粒度提交，方便回退）
2. 运行: python -c "from server.xxx import ..."
3. 确认无 ImportError / NameError
```

### 4.2 不改行为

- ❌ 不重构 _cmd_* 函数内部逻辑
- ❌ 不改函数签名
- ❌ 不修 bug（除非是搬移引入的 import 错误）
- ✅ 只改 import 路径和变量引用方式（state.X）
- ✅ 函数体内容一字不改

### 4.3 特别注意

| 注意点 | 原因 |
|---|---|
| `_connections` 留在 main.py | 它是 WS 会话核心状态，commands 通过 `state._connections` 引用 |
| `_ADMIN_COMMANDS` 在 commands/__init__.py 构建 | main.py 导入它用于 !命令分发 |
| `_send()` 函数留在 main.py | 它操作 ws 对象，是核心通信能力 |
| handler() 内的 msg_type 分支 | 暂不搬移，仅改变量引用为 state.X |

---

## 五、预期产出

### 5.1 文件行数变化

```
                 当前              重构后
handler.py      7,024 行    →    main.py  ~800 行
                              +   state.py  ~200 行
                              +   command_utils.py  ~200 行
                              +   commands/  ~2700 行
                              ──────────────────────
                                 总计  ～3900 行（-44% handler.py 体积）
```

### 5.2 目录结构

```
server/
├── __init__.py
├── __main__.py         ← 改 import 路径
├── main.py             ← 原名 handler.py，精简后 ~800 行
├── state.py            ← 🔺 新增：共享状态
├── command_utils.py    ← 🔺 新增：命令路由工具
├── commands/           ← 🔺 新增：全部 !命令
│   ├── __init__.py
│   ├── workspace.py
│   ├── pipeline.py
│   ├── agent_card.py
│   ├── task.py
│   └── admin.py
├── config.py           ← 不变
├── auth.py             ← 不变
├── audit.py            ← 不变
├── persistence.py      ← 不变
├── workspace.py        ← 不变
├── agent_card.py       ← 不变
├── pipeline_context.py ← 不变
├── pipeline_sync.py    ← 不变
├── timeout_tracker.py  ← 不变
├── message_store.py    ← 不变
├── task_store.py       ← 不变
├── templates.py        ← 不变
├── web_viewer.py       ← 不变
├── workspace_api.py    ← 不变
├── auto_router.py      ← 不变
└── README.md           ← 已更新
```
