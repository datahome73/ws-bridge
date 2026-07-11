# Server — WS Bridge 服务端

> 本目录是 ws-bridge 服务端的全部核心代码。**共 27 个 .py 文件，约 13,000 行。**
>
> 🏗️ **R101+ 双进程架构** — WSS 核心（端口 8765）与 Web 服务（端口 8766）独立运行，
> 通过 Supervisor 管理。Web 界面不再依赖 WebSocket 推流，改用 5 秒 HTTP 轮询。
>
> R102 新增：bot 在线状态缓存 — Web 服务后台定时从 WSS 核心拉取、内存缓存。

---

## 一、架构总览

### 1.1 双进程架构

```
                     ┌────────────────────────────────┐
                     │  Bot / Gateway 客户端            │
                     │  (WebSocket 长连接)              │
                     └──────────┬─────────────────────┘
                                │ WS 消息
                                ▼
┌────────────────────────────────────────────────────────────────┐
│  ═══ 进程 1: WSS 核心（端口 8765） ═══                        │
│                                                                │
│  __main__.py  (aiohttp 入口)                                    │
│   ├─ /ws                   WebSocket 端点                      │
│   ├─ /api/status           bot 在线状态（读 _connections）      │
│   ├─ /api/health           健康检查                             │
│   └─ /api/workspaces       工作区列表                           │
│         │                                                      │
│         ▼                                                      │
│  main.py（核心消息路由）                                        │
│   ├─ handler()             WS 会话主循环                       │
│   ├─ handle_broadcast()    消息路由 + 广播（含 !命令分发）     │
│   ├─ _handle_server_relay() inbox 中继                        │
│   ├─ _handle_server_query() _inbox:server 查询路由            │
│   ├─ handle_auth()         认证入口                            │
│   ├─ handle_register()     bot 注册入口                        │
│   └─ _send()               WebSocket 写入                     │
│         │                                                      │
│         ▼                                                      │
│  领域模块层（与 Web 服务共享）                                  │
└────────────────────────────────────────────────────────────────┘
                         │ HTTP 轮询（10s）
                         ▼
┌────────────────────────────────────────────────────────────────┐
│  ═══ 进程 2: Web 服务（端口 8766） ═══                        │
│                                                                │
│  web_service.py (独立 aiohttp 入口)                             │
│   ├─ /                     HTML 页面                          │
│   ├─ /api/chat             聊天历史 API                        │
│   ├─ /api/chat/inbox       收件箱 API                          │
│   ├─ /api/channels         频道列表 API                        │
│   ├─ /api/bot_status       bot 在线状态（内存缓存） ← R102    │
│   ├─ /api/workspaces       工作区列表（代理到 WSS 核心）       │
│   └─ ... 其他 API 端点                                        │
│         │                                                      │
│         ├── 后台定时轮询 WSS 核心 /api/status → 内存缓存       │
│         └── 前端 5s 轮询 Web 服务 API（非 WS 推流）           │
└────────────────────────────────────────────────────────────────┘
                         │ HTTP (5s 轮询 / 下拉刷新)
                         ▼
                     ┌────────────────┐
                     │  浏览器 Web UI  │
                     │  纯数据查看器    │
                     └────────────────┘
```

### 1.2 核心判断

> **去掉 Web 界面，bot 之间还能正常收发 inbox 消息吗？**
> → 能。Web 界面是纯数据查看器，不影响任何通信逻辑。

| 层 | 去掉后影响 | 判断 |
|:---|:-----------|:----:|
| WSS 核心 + `save_message(DB)` | Inbox 不通，bot 失联 | ✅ 核心 |
| Web HTTP 界面 + 轮询 | Bot 仍正常收发消息 | 🔴 插件 |

### 1.3 共享领域模块

两个进程共享以下模块层（通过同一个 `server/` 包 import）：

```
配置层      config.py
持久化层    persistence.py / message_store.py / task_store.py
工作区      workspace.py / workspace_api.py
认证层      auth.py
Agent 管理  agent_card.py
管线系统    pipeline_context.py / pipeline_sync.py / timeout_tracker.py
Web 视图   web_viewer.py（路由注册 + 会话管理，被两个进程共用）
模板       templates.py（HTML/CSS/JS 内联模板）
```

> **web_viewer.py** 在 R101 解耦后变为纯函数库：它不再持有 WebSocket 连接池（`_ws_clients` 已移除），
> 不再写入聊天日志文件（`write_chat_log` 从 WSS 核心移除）。它只负责注册 HTTP 路由和会话管理，
> 被 `__main__.py`（WSS 核心）和 `web_service.py`（独立 Web 服务）共同调用。

---

## 二、各文件职责

### 🔵 基础设施

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`config.py`** | 166 | 全部环境变量配置。**其他模块不应自行 os.getenv** |
| **`persistence.py`** | 135 | JSON 文件原子读写。维护: 授权用户、Web 会话、API Keys。线程安全 |
| **`auth.py`** | 156 | is_approved() / get_users() / is_workspace_admin() |
| **`audit.py`** | 94 | AuditLogger — 审计日志（!命令执行 → _audit_log.jsonl） |
| **`__init__.py`** | 1 | 包声明 |

### 🟢 WSS 核心（进程 1）

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`__main__.py`** | 806 | **WSS 核心入口**。aiohttp app 启动/停止，端点注册（`/ws`, `/api/status`, `/api/health`, `/api/workspaces`），后台循环 |
| **`main.py`** | 3,427 | **核心消息路由** — WS 会话主循环 + 消息广播 + inbox 中继/查询 + 认证入口 + 全部 !命令。**应继续拆分为 commands/ 子模块** |
| **`message_store.py`** | 245 | 消息持久化 (SQLite, 7天 TTL) |
| **`state.py`** | 126 | 共享模块级状态：`_PIPELINE_STATE`、`_PIPELINE_CONFIG`、常量等 |
| **`command_utils.py`** | 204 | 命令路由工具：`_parse_command()`、权限检查、审计、广播 |

### 🟠 !命令处理

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`commands/__init__.py`** | 202 | 构建 `_ADMIN_COMMANDS` 注册表，导入各子模块的命令函数 |
| **`commands/workspace.py`** | 454 | workspace: create/close/list/join/leave/add/remove/list_members |
| **`commands/pipeline.py`** | 2,019 | pipeline: start/stop/status/activate/handoff/reject/force/verify/... |
| **`commands/agent_card.py`** | 257 | agent_card: list/get/set/unset/reload/register/auto_register/role_map |
| **`commands/task.py`** | 196 | task: create/update/query/list |
| **`commands/admin.py`** | 175 | admin: approve_ws_admin/reject_ws_admin/list_pending/audit_log/revoke_api_key |

### 🟡 Web 服务（进程 2）

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`web_service.py`** | 84 | **独立 Web HTTP 入口**。启动 aiohttp，注册 `web_viewer.setup_routes()` 全部 Web API，后台轮询 WSS 核心 bot 状态。**R101 新增，R102 扩展** |
| **`templates.py`** | 755 | Web 聊天界面 HTML/CSS/JS 内联模板（单文件，无外部依赖） |
| **`web_viewer.py`** | 680 | Web 界面路由注册 + 会话管理 + API 处理函数（聊天历史、收件箱、频道列表、搜索、归档、GitHub OAuth）。被两个进程共用 |

### 🟡 工作区

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`workspace.py`** | 460 | 工作区 CRUD + 生命周期状态机 + JSON 持久化 + 自动归档 |
| **`workspace_api.py`** | 35 | HTTP API 端点 (GET /api/workspaces) |

### 🟠 管线系统

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`pipeline_context.py`** | 556 | PipelineContext dataclass + PipelineContextManager（CRUD + 状态机 + JSON 持久化 + JSONL 历史归档） |
| **`pipeline_sync.py`** | 203 | 管线 Git 同步检测（检查 dev 分支新提交，通过 commit message 匹配推进状态） |
| **`timeout_tracker.py`** | 164 | Step 超时计时器（纯内存，无 async 无依赖） |
| **`auto_router.py`** | 750 | 🚂 管线自动路由服务 — **独立外挂进程，已停用** |

### 🔴 Agent 管理

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`agent_card.py`** | 429 | Agent Card 加载/迁移/注册/热更新/离线检测 |
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
              │                                             │
              │                                     save_message(DB)
              │                                       （不再写 chat_log）
              │
              ├── "agent_card_register" → handle_agent_card_register()
              └── 其他 msg_type      → 各自 handler
```

### 3.2 Web 界面数据流

```
  浏览器                              Web 服务 (8766)                  WSS 核心 (8765)
   │                                      │                              │
   ├─ 首次加载 GET / ──────────────────→  templates.py                  │
   │                                      │                              │
   ├─ 每 5s → GET /api/chat?since=... ──→  web_viewer        ──读 DB──→ message_store
   ├─ 每 5s → GET /api/chat/inbox ──────→  web_viewer        ──读 DB──→ message_store
   ├─ 每 10s → GET /api/bot_status ────→  web_service (缓存)            │
   │                                      │        ↑                    │
   │                                      │  后台线程每 10s              │
   │                                      │  GET /api/status ──────────→  _connections
   ├─ 下拉刷新 → 同 5s 轮询              │                              │
   └─ 工作区列表 15s → /api/workspaces ─→  workspace_api  ──读 JSON──→ workspace.py
```

> **R101 关键变更：** 23 处 `write_chat_log()` 全部从 WSS 核心移除。消息持久化仅靠
> `save_message(DB)`。Web 端不再走 WS 推流，桌面端 5 秒 fetch 轮询，手机端下拉刷新。
>
> **R102 关键变更：** Web 服务增加后台轮询 + 内存缓存，暴露 `/api/bot_status` 给前端。

### 3.3 数据持久化层次

```
┌───────────────────────┐
│ 内存 (不落盘)          │
│  state._PIPELINE_STATE │  ← 仅存活跃管线运行时状态
│  state._PIPELINE_CONFIG│  ← 只读配置，从 WORK_PLAN 解析
│  state._connections    │  ← 在线连接集合（WSS 核心进程）
│  timeout_tracker       │  ← 超时计时器
│  _BOT_STATUS_CACHE    │  ← bot 在线状态（Web 服务进程，R102）
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
├───────────────────────┤
│ SQLite                 │
│  data/messages.db      ← message_store.py (原始消息，7天滚动)
│  data/tasks.db         ← task_store.py (任务状态)
└───────────────────────┘
```

> **R101 后不再活跃写入：** `data/chat_logs/` 目录下的 JSONL 日志文件是旧 `write_chat_log()`
> 的历史遗留产物。R101 已移除所有 `write_chat_log()` 调用，但已有日志文件在 volumes 中保留
> 可读。`data/pairing_codes/` 目录为更早期的 Web 登录方式，已不再主动写入。

---

## 四、管线系统详解

### 4.1 历史 & 现状

管线系统经历了三个阶段：

| 阶段 | 引入 | 机制 | 当前状态 |
|:-----|:-----|:------|:---------|
| **R42-R74** | 旧管线 | `_PIPELINE_STATE` (内存 dict) + `_PIPELINE_CONFIG` (WORK_PLAN frontmatter) | **仍在使用** |
| **R77-R97** | PipelineContext | `PipelineContextManager` (dataclass + JSON 持久化 + 状态机) | **部分使用** |
| **R97** | AutoRouter | 独立外挂进程 | **已停用** |

### 4.2 当前管线工作流（R101+ inbox-handoff）

```
PM 编写需求 → 推 dev → 发 inbox 给 arch → arch 技术方案 → 推 dev
  → PM 通知 dev → dev 编码 → 推 dev → dev 回复 PM inbox
  → PM 通知 review → review 审查 → 回复 inbox → ...
```

> 管线不依赖 AutoRouter。所有推进通过 inbox 手动协调，详见 `docs/inbox-message-protocol.md`。

---

## 五、依赖关系

```
━━━ 进程 1: WSS 核心 ━━━
__main__.py
  ├── main.py（核心消息路由）
  │     ├── state.py
  │     ├── command_utils.py
  │     ├── commands/
  │     │     ├── workspace.py
  │     │     ├── pipeline.py
  │     │     ├── agent_card.py
  │     │     ├── task.py
  │     │     └── admin.py
  │     ├── auth.py
  │     ├── workspace.py / workspace_api.py
  │     ├── agent_card.py
  │     ├── pipeline_context.py
  │     ├── pipeline_sync.py
  │     ├── timeout_tracker.py
  │     ├── task_store.py
  │     ├── persistence.py
  │     ├── message_store.py
  │     └── shared.protocol
  └── web_viewer.py（路由注册 + 会话管理）

━━━ 进程 2: Web 服务 ━━━
web_service.py
  ├── web_viewer.py（路由注册 + API 处理）
  ├── templates.py（HTML/CSS/JS）
  ├── persistence.py
  ├── message_store.py
  └── config.py

  └── [后台线程] ──HTTP──→ __main__:/api/status（WSS 核心）
```

> **进程隔离：** 两个进程不共享内存状态。WSS 核心的 `_connections` 不暴露给 Web 服务。
> Web 服务通过 HTTP 调用 WSS 核心的 `/api/status` 获取 bot 在线状态（R102）。

---

## 六、开发准则

### 6.1 文件职责边界

| 文件 | 职责 |
|:-----|:------|
| **`main.py`** | 只做 WebSocket 消息路由、消息广播、命令路由分发。所有 !命令处理逻辑 → 拆到 `commands/*.py` |
| **`commands/*.py`** | 只处理 !命令的业务逻辑。不能直接操作 WebSocket 连接，只能返回字符串响应 |
| **`state.py`** | 持有共享状态，不包含业务逻辑 |
| **`command_utils.py`** | 命令路由的纯工具函数，不包含业务逻辑 |
| **`pipeline_*.py`** | 只关心管线数据模型、状态机、持久化。不涉及 WS 通信 |
| **`web_service.py`** | 只做 Web 服务启动和路由注册。不处理 WS 连接 |
| **`web_viewer.py`** | HTTP API 处理函数 + 会话管理。被两个进程共用，不持 WebSocket 连接 |

### 6.2 新增功能的约定

1. **新增 !命令** → 在 `commands/` 下对应领域文件加函数，`commands/__init__.py` 注册，**不要碰 main.py**
2. **新增 Web API** → 在 `web_viewer.py` 加 handler + `setup_routes()` 注册，**不要碰 `__main__.py`**
3. **新增后台循环** → 判断属于哪个进程：WSS 核心在 `__main__.py` 的 `on_startup` 启动；Web 服务在 `web_service.py` 的 `on_startup` 启动
4. **WS 连接状态** → 留在 `main.py` 的 `_connections` 里
5. **跨进程数据** → 不能直接 import 对方的内存状态，通过 HTTP API（如 `/api/status`）或共享 DB/文件通信
6. **管线逻辑** → 永远不要写进 main.py，去 `commands/pipeline.py` 或 `pipeline_*.py`

### 6.3 重构路线图

```
Phase 1 ✅ (R100)  📋 拆 handler.py — 结构拆分
  → main.py            改名，保留核心 WS 路由
  → state.py           共享状态提取
  → command_utils.py   命令路由工具提取
  → commands/          全部 !命令处理（6 个领域文件）

Phase 1a ✅ (R101)  📋 WSS/Web 解耦
  → web_service.py     独立 Web 服务进程（端口 8766）
  → 移除 23 处 write_chat_log()
  → 移除 _ws_clients（Web 端不再走 WS 推流）
  → 前端改用 5 秒 HTTP 轮询

Phase 1b ✅ (R102)  📋 Bot 在线状态
  → Web 服务后台轮询 WSS 核心 /api/status
  → 内存缓存 → /api/bot_status

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
├── messages.db                 SQLite 消息存储（7 天滚动）
├── tasks.db                    SQLite 任务存储
├── chat_logs/                  聊天日志文件（历史遗留，R101 后不再写入）
└── pairing_codes/              配对码（旧版 Web 登录，不再主动写入）
```
