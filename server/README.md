# Server — WS Bridge 服务端

> 本目录是 ws-bridge 服务端的全部核心代码。**共 17 个 .py 文件，12,858 行。**
>
> 📋 **R100 重构中** — 正在将 `handler.py` 拆分为 `main.py`（核心）+ `state.py` + `command_utils.py` + `commands/` 包。
> 执行中请参考 `docs/R100/R100-product-requirements.md`。

---

## 一、架构总览

```
                     ┌─────────────────────────────┐
                     │   Bot / Gateway 客户端       │
                     │   (WebSocket 连接)            │
                     └──────────┬──────────────────┘
                                │ WS 消息
                                ▼
┌───────────────────────────────────────────────────────────────┐
│                  __main__.py  (服务入口)                        │
│  • aiohttp app 启动 (HTTP + WS)                                │
│  • 启动后台循环: 自动归档 / 定时清理                           │
│  • 端点注册: /ws, /api/*, Web 界面                             │
└────────────────────────┬──────────────────────────────────────┘
                         │ 路由到
                         ▼
┌───────────────────────────────────────────────────────────────┐
│  main.py（原名 handler.py — 核心消息路由）                     │
│                                                               │
│  WebSocket 消息处理（[[核心]] — 只做消息流转）                  │
│  ├── handler()              WS 会话主循环                     │
│  ├── handle_broadcast()     消息路由 + 广播（含 !命令分发）   │
│  ├── _handle_server_relay() inbox 中继                        │
│  ├── _handle_server_query() _inbox:server 查询路由            │
│  ├── handle_auth()          认证入口                          │
│  ├── handle_register()      bot 注册入口                      │
│  └── _send()                WebSocket 写入                    │
│                                                               │
│  [[插件]] — 通过 commands/ 注册表路由                         │
│  ├── !命令 → _parse_command → _ADMIN_COMMANDS → _cmd_*()     │
│  └── msg_type 分支 → 各 handler 函数                          │
└──────────┬────────────────────────────────────────────────────┘
           │ 调用
           ▼
┌──────────┴────────────────────────────────────────────────────┐
│  领域模块层                                                    │
│                                                                │
│  state.py          共享状态（管线、连接、全局变量）             │
│  command_utils.py  命令路由工具（解析/权限/审计/广播）         │
│  commands/         全部 !命令处理（按领域分文件）               │
│  ├── __init__.py   构建 _ADMIN_COMMANDS 注册表                 │
│  ├── workspace.py  工作区命令                                  │
│  ├── pipeline.py   管线命令                                    │
│  ├── agent_card.py Agent Card 命令                             │
│  ├── task.py       任务命令                                    │
│  └── admin.py      管理命令                                    │
│                                                                │
│  workspace.py      工作区 CRUD + 状态机 + 自动归档             │
│  auth.py           认证 & 权限检查                             │
│  agent_card.py     Agent Card 加载/注册/热更新                 │
│  audit.py          审计日志 (JSONL)                            │
│  persistence.py    JSON 持久化（用户/会话/API Keys）           │
│  message_store.py  SQLite 消息存储（7天滚动）                  │
│  task_store.py     SQLite 任务存储（R38 任务状态机）            │
│  pipeline_context.py PipelineContext 数据类 + 管理器 + 持久化  │
│  pipeline_sync.py  管线 Git 同步检测                           │
│  timeout_tracker.py Step 超时计时器（纯内存）                  │
│  config.py         配置（环境变量）                             │
│  templates.py      Web 界面 HTML/CSS/JS 模板                   │
│  web_viewer.py     Web 聊天界面后端（HTTP + WS 端点）          │
│  workspace_api.py  Workspace HTTP API                          │
│  auto_router.py    🚂 管线自动路由（已停用）                   │
└───────────────────────────────────────────────────────────────┘
```

---

## 二、各文件职责

### 🔵 基础设施

| 文件 | 行数 | 职责 |
|---|---|---|
| **`config.py`** | 166 | 全部环境变量配置。**其他模块不应自行 os.getenv** |
| **`persistence.py`** | 128 | JSON 文件原子读写。维护: 授权用户、Web 会话、API Keys。线程安全 |
| **`auth.py`** | 117 | is_approved() / get_users() / is_workspace_admin() |
| **`audit.py`** | 94 | AuditLogger — 审计日志（!命令执行 → _audit_log.jsonl） |
| **`__init__.py`** | 1 | 包声明 |

### 🟢 WebSocket 通信（核心职责）

| 文件 | 行数 | 职责 |
|---|---|---|
| **`__main__.py`** | 844 | **服务入口**。aiohttp app 启动/停止，端点注册，后台循环 |
| **`main.py`** | ~800 | **核心消息路由** — WS 会话主循环 + 消息广播 + inbox 中继/查询 + 认证入口。**不要在此文件加业务逻辑** |
| **`message_store.py`** | 245 | 消息持久化 (SQLite, 7天TTL) |
| **`templates.py`** | 762 | Web 聊天界面 HTML/CSS/JS 内联模板 |
| **`web_viewer.py`** | 725 | Web 界面后端（路由、聊天缓冲、ChatLog 写入） |

### 🟡 共享层（R100 新增）

| 文件 | 行数 | 职责 |
|---|---|---|
| **`state.py`** | ~200 | 共享模块级状态：`_PIPELINE_STATE`、`_PIPELINE_CONFIG`、`_step_ack_states`、`_LOBBY_PAUSED`、`_r72_users`、常量等 |
| **`command_utils.py`** | ~200 | 命令路由工具：`_parse_command()`、`_check_command_permission()`、`_send_cmd_response()`、`_log_audit()`、`_broadcast_to_channel()` |

### 🟠 !命令处理（R100 新增）

| 文件 | 行数 | 职责 |
|---|---|---|
| **`commands/__init__.py`** | ~100 | 构建 `_ADMIN_COMMANDS` 注册表，导入各子模块的命令函数 |
| **`commands/workspace.py`** | ~500 | workspace: create/close/list/join/leave/add/remove/list_members |
| **`commands/pipeline.py`** | ~1200 | pipeline: start/stop/status/activate/handoff/reject/force/verify/... |
| **`commands/agent_card.py`** | ~300 | agent_card: list/get/set/unset/reload/register/auto_register/role_map |
| **`commands/task.py`** | ~400 | task: create/update/query/list + rollcall_role/rollcall_next |
| **`commands/admin.py`** | ~200 | admin: approve_ws_admin/reject_ws_admin/list_pending/audit_log/revoke_api_key |

### 🟡 工作区

| 文件 | 行数 | 职责 |
|---|---|---|
| **`workspace.py`** | 460 | 工作区 CRUD + 生命周期状态机 + JSON 持久化 + 自动归档 |
| **`workspace_api.py`** | 35 | HTTP API 端点 (GET /api/workspaces) |

### 🟠 管线系统

| 文件 | 行数 | 职责 |
|---|---|---|
| **`pipeline_context.py`** | 556 | PipelineContext dataclass + PipelineContextManager（CRUD + 状态机 + JSON 持久化 + JSONL 历史归档） |
| **`pipeline_sync.py`** | 203 | 管线 Git 同步检测（检查 dev 分支新提交，通过 commit message 匹配推进状态） |
| **`timeout_tracker.py`** | 164 | Step 超时计时器（纯内存，无 async 无依赖） |
| **`auto_router.py`** | 752 | 🚂 管线自动路由服务 — **独立外挂进程，已停用** |

### 🔴 Agent 管理

| 文件 | 行数 | 职责 |
|---|---|---|
| **`agent_card.py`** | 415 | Agent Card 加载/迁移/注册/热更新/离线检测 |
| **`task_store.py`** | 184 | SQLite 任务存储（R38 任务状态机，与 pipeline 关联） |

---

## 三、消息数据流

### 3.1 WebSocket 消息生命周期

```
  Bot ──WS──→ __main__.py (aiohttp /ws 端点)
                      │
                      ▼
              main.handler(ws)       ← 最顶层协程，管理整个 WS 会话
                      │
              解析 MSG type
              ├── "auth"             → handle_auth()
              ├── "register"         → handle_register()
              ├── "message"          → handle_broadcast()
              │                        ├─ 解析 !command → commands/注册表
              │                        ├─ _inbox:server → _handle_server_query()
              │                        ├─ inbox 单播  → 路由到目标 bot
              │                        └─ 频道广播   → 路由到频道成员
              ├── "agent_card_register" → handle_agent_card_register()
              └── 其他 msg_type      → 各自 handler（未来拆入 commands/）
```

### 3.2 数据持久化层次

```
┌───────────────────────┐
│ 内存 (不落盘)          │
│  state._PIPELINE_STATE │  ← R42 旧系统，仅存活跃管线运行时状态
│  state._PIPELINE_CONFIG│  ← R62 只读配置，从 WORK_PLAN 解析
│  state._connections    │  ← 在线连接集合
│  state._step_ack_states│  ← R53 频道切换 ACK
│  timeout_tracker       │  ← 超时计时器
│  watchdog 状态          │
├───────────────────────┤
│ JSON 文件              │
│  data/workspaces.json           ← workspace.py
│  data/pipeline_contexts.json    ← pipeline_context.py
│  data/pipeline_contexts_history.jsonl ← pipeline_context.py (归档)
│  data/approved_users.json       ← persistence.py
│  data/web_sessions.json         ← persistence.py
│  data/api_keys.json             ← persistence.py
│  data/oauth_config.json         ← config.py
│  data/_audit_log.jsonl          ← audit.py
│  data/chat_logs/               ← web_viewer.py
├───────────────────────┤
│ SQLite                 │
│  data/messages.db      ← message_store.py (原始消息)
│  data/tasks.db         ← task_store.py (任务状态)
└───────────────────────┘
```

---

## 四、管线系统详解

### 4.1 历史 & 现状

管线系统经历了三个阶段的演进：

| 阶段 | 引入 | 机制 | 当前状态 |
|---|---|---|---|
| **R42-R74** | 旧管线 | `_PIPELINE_STATE` (内存 dict) + `_PIPELINE_CONFIG` (WORK_PLAN frontmatter) | **仍在使用**，!pipeline_status 等依赖 |
| **R77-R97** | PipelineContext | `PipelineContextManager` (dataclass + JSON 持久化 + 状态机) | **部分使用**，!pipeline_start 写入，!pipeline_stop 读取 |
| **R97** | AutoRouter | 独立外挂进程，dict 格式 PipelineContext，文件共享 | **已停用**（`531c601`） |

### 4.2 已知问题

| 问题 | 说明 |
|---|---|
| **handler.py 7007行** | 包揽了 WebSocket 处理、命令路由、管线状态机、看门狗、Git 同步、ACK、超时、角色映射等数十项职责 |
| **三套管线状态并存** | `_PIPELINE_STATE`(内存) + `PipelineContextManager`(dataclass+JSON) + AutoRouter 自维护(dict+JSON)，数据流向混乱 |
| **pipeline_contexts.json 双格式混写** | dataclass 和 dict 格式写同一个文件，结构不同 |
| **AutoRouter 停用=管线断链** | `!pipeline_start` 仍说"AutoRouter 将自动派活"，但无人接管 |
| **状态依赖交叉** | handler.py 里 20+ 个 `_cmd_*` 函数直接读写全局变量，难以单体测试 |

---

## 五、依赖关系

```
__main__.py
  ├── main.py    (原 handler.py — 核心消息路由)
  │     ├── state.py         （无反向依赖）
  │     ├── command_utils.py （调用 state，无反向依赖）
  │     ├── commands/
  │     │     ├───→ state.py
  │     │     ├───→ command_utils.py
  │     │     └───→ workspace / auth / agent_card / pipeline_context / ...
  │     ├── auth.py
  │     ├── workspace.py
  │     ├── agent_card.py
  │     ├── pipeline_context.py
  │     ├── pipeline_sync.py
  │     ├── timeout_tracker.py
  │     ├── task_store.py
  │     ├── persistence.py
  │     ├── message_store.py
  │     ├── web_viewer.py
  │     └── shared.protocol
  └── ... (其他启动模块)
```

> **无循环导入** — 单向依赖链：`__main__ → main → commands → state/command_utils`
>
> `state.py` 和 `command_utils.py` 是纯工具层，不依赖 main.py 或 commands/。

---

## 六、开发准则

### 6.1 文件职责边界

```
main.py          → 只做 WebSocket 消息路由、消息广播、命令路由分发。
                   所有 !命令处理逻辑 → 拆到 commands/*.py。
                   管线状态机 → 拆到 pipeline_state.py（Phase 2）。
                   看门狗 → 拆到 watchdog.py（Phase 2）。
                   验证钩子 → 拆到 validation.py（Phase 2）。

commands/*.py   → 只处理 !命令的业务逻辑。
                   每个文件对应一个领域（workspace/pipeline/agent_card/task/admin）。
                   不能直接操作 WebSocket 连接，只能返回字符串响应。

state.py        → 持有共享状态，不包含业务逻辑。
command_utils.py→ 命令路由的纯工具函数，不包含业务逻辑。

pipeline_*.py   → 只关心管线数据模型、状态机、持久化。
                   不涉及 WS 通信、消息解析、!命令处理。

workspace.py    → 已较好解耦，保持即可。
agent_card.py   → 已较好解耦，保持即可。
```

### 6.2 新增功能的约定

1. **新增 !命令** → 在 `commands/` 下对应领域文件加函数，`commands/__init__.py` 注册，**不要碰 main.py**
2. **新增状态** → 不要加新的全局 dict，用 `state.py` 或专门的 Manager 类
3. **新增后台循环** → 在 `__main__.py` 的 `on_startup` 中启动，不要在 main.py 里起 task
4. **WS 连接状态** → 留在 `main.py` 的 `_connections` 里（这是它该管的）
5. **管线逻辑** → 永远不要写进 main.py，去 `commands/pipeline.py` 或 `pipeline_*.py`

### 6.3 重构路线图

```
Phase 1 (R100)  📋 拆 handler.py — 结构拆分
  → main.py            改名，保留核心 WS 路由
  → state.py           共享状态提取
  → command_utils.py   命令路由工具提取
  → commands/          全部 !命令处理（5 个领域文件）
  → 验证：手工 inbox 双向通信正常

Phase 2  📋 统一管线状态
  → 砍掉 _PIPELINE_STATE（内存），全部走 PipelineContextManager
  → 统一 pipeline_contexts.json 写入格式
  → 管线相关辅助函数从 commands/pipeline.py 进一步拆分

Phase 3  📋 重新设计 auto 机制
  → 选择方向：handler 内嵌 vs 独立 Gateway 层 vs 混合
```

---

## 七、数据文件位置

```
data/                                   ← WS_DATA_DIR（默认 ./data）
├── approved_users.json         前端授权用户
├── web_sessions.json           Web 登录会话
├── api_keys.json               API Keys (R72)
├── oauth_config.json           GitHub OAuth 配置
├── workspaces.json             工作区
├── pipeline_contexts.json      管线上下文（活跃）
├── pipeline_contexts_history.jsonl  管线上下文（历史归档）
├── _audit_log.jsonl            审计日志
├── messages.db                 SQLite 消息存储
├── tasks.db                    SQLite 任务存储
├── chat_logs/                  聊天日志文件
│   ├── lobby.jsonl
│   ├── _admin.jsonl
│   └── ws_*.jsonl
└── pairing_codes/              配对码（Web 登录用）
```
