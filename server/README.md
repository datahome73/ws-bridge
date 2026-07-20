# Server — WS Bridge 服务端

> 本目录是 ws-bridge 服务端的全部核心代码。**共 33 个 .py 文件，约 17,100 行。**
>
> 🏗️ **R101+ 双进程架构** — WSS 核心（端口 8765）与 Web 服务（端口 8766）独立运行，
> 通过 Supervisor 管理。Web 界面不依赖 WebSocket 推流，改用 5 秒 HTTP 轮询。
>
> R126/R127 已完成场景匹配规则（scenario_matcher.py）和管线状态机（pipeline_engine.py）
> 的模块化提取，大幅降低了 main.py 的复杂度。
>
> R131 完成 `##query` 命令族全面迁移（6 个 ! 命令规则化为 ## 命令），
> R133 完成 Web 收件箱发件人颜色扩展（支持 系统/经理 颜色 + 收件人颜色显示）。

---

## 一、架构总览

### 1.1 包结构

```
server/
├── common/           ← 双进程共享模块（配置 / 认证 / 持久化 / 消息存储）
├── ws_server/        ← 进程 1：WSS 核心（端口 8765）— WebSocket 服务 + 管线
└── web_ui/           ← 进程 2：Web 服务（端口 8766）— HTTP API + 前端
```

### 1.2 双进程架构

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
│  ws_server/__main__.py  (aiohttp 入口)                          │
│   ├─ /ws                   WebSocket 端点                      │
│   ├─ /api/status           bot 在线状态（读 _connections）      │
│   ├─ /api/health           健康检查                             │
│   └─ /api/workspaces       工作区列表                           │
│         │                                                      │
│         ▼                                                      │
│  ws_server/main.py（核心消息路由）                               │
│   ├─ handler()             WS 会话主循环                       │
│   ├─ handle_broadcast()    消息路由 + 广播（含 ##/! 命令分发） │
│   ├─ _handle_server_relay() inbox 中继（场景匹配规则路由）     │
│   ├─ _handle_server_query() _inbox:server 查询路由             │
│   ├─ handle_auth()         认证入口                            │
│   ├─ handle_register()     bot 注册入口 (R72)                  │
│   └─ _send()               WebSocket 写入                     │
│         │                                                      │
│         ├── scenario_matcher.py  ← 规则表 + 匹配引擎 (R126)    │
│         ├── pipeline_engine.py   ← 管线状态机 (R127)          │
│         └── commands/            ← ##/! 命令注册表 (R100)     │
│               ├── pipeline.py    管线命令 (2085行)             │
│               ├── workspace.py   工作区命令                    │
│               ├── agent_card.py  Agent 卡片命令                │
│               ├── task.py        任务命令                      │
│               └── admin.py       管理命令                      │
└────────────────────────────────────────────────────────────────┘
                         │ HTTP 轮询（10s 后台线程）
                         ▼
┌────────────────────────────────────────────────────────────────┐
│  ═══ 进程 2: Web 服务（端口 8766） ═══                        │
│                                                                │
│  web_ui/main.py (独立 aiohttp 入口)                             │
│   ├─ /                      HTML 页面                          │
│   ├─ /api/chat             聊天历史 API                        │
│   ├─ /api/chat/inbox       收件箱 API                          │
│   ├─ /api/chat/archive     归档历史 API (R76)                  │
│   ├─ /api/chat/search      消息搜索 (R76)                      │
│   ├─ /api/channels         频道列表 API                        │
│   ├─ /api/bot_status       bot 在线状态（内存缓存） ← R102     │
│   ├─ /api/workspaces       工作区列表（代理到 WSS 核心）       │
│   ├─ /api/pipelines        管线状态列表 ← R112                │
│   └─ /api/agent_status     Agent 健康/离线 ← R131             │
│         │                                                      │
│         ├── 后台定时轮询 WSS 核心 /api/status → 内存缓存       │
│         └── 前端 5s 轮询 Web 服务 API（非 WS 推流）           │
└────────────────────────────────────────────────────────────────┘
                         │ HTTP (5s 轮询 / 下拉刷新)
                         ▼
                     ┌────────────────┐
                     │  浏览器 Web UI  │
                     │  纯数据查看器    │
                     │  📬📂🏠📚📊   │
                     └────────────────┘
```

### 1.3 核心判断

> **去掉 Web 界面，bot 之间还能正常收发 inbox 消息吗？**
> → 能。Web 界面是纯数据查看器，不影响任何通信逻辑。

| 层 | 去掉后影响 | 判断 |
|:---|:-----------|:----:|
| WSS 核心 + save_message(DB) | Inbox 不通，bot 失联 | ✅ 核心 |
| Web HTTP 界面 + 轮询 | Bot 仍正常收发消息 | 🔴 插件 |

### 1.4 共享模块（server/common/）

两个进程共享以下模块层（通过 `server.common.*` import）：

```
配置层      config.py
持久化层    persistence.py
认证层      auth.py
消息存储    message_store.py
```

---

## 二、各文件职责

### 🔵 基础设施（server/common/）

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`config.py`** | 114 | 全部环境变量配置。**其他模块不应自行 os.getenv** |
| **`persistence.py`** | 128 | JSON 文件原子读写。维护：API Keys、授权用户、Web 会话。线程安全 |
| **`auth.py`** | 137 | is_approved() / get_users() / is_workspace_admin() / agent_name 查询 |
| **`message_store.py`** | 140 | 消息存储接口层（ws_server/message_store.py 的封装） |

### 🟢 WSS 核心 — 入口与路由（进程 1）

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`__main__.py`** | 846 | **WSS 核心入口**。aiohttp app 启动/停止，端点注册（`/ws`, `/api/status`, `/api/health`, `/api/workspaces`），后台循环 |
| **`main.py`** | 4,951 | **核心消息路由** — WS 会话主循环 + 消息广播 + inbox 中继/查询 + 认证入口 + 全部 ##/! 命令。**应继续拆分为更多子模块** |
| **`message_store.py`** | 260 | 消息持久化实现（SQLite, 7天 TTL + R129 去重） |
| **`state.py`** | 130 | 共享模块级状态：`_PIPELINE_STATE`、`_PIPELINE_CONFIG`、`_connections`、`SYSTEM_AGENT_ID` 等 |
| **`command_utils.py`** | 205 | 命令路由工具：`_parse_command()`、权限检查、审计、广播 |

### 🟠 场景匹配与管线引擎（R126/R127 提取）

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`scenario_matcher.py`** | 795 | **R126 提取** — 场景匹配规则表。从 main.py 提取为声明式 HandlerRule 列表，含 inbox 中继规则 + 大厅前缀规则 + ## 命令规则 + PM 安全守卫。显式优先级排序 |
| **`pipeline_engine.py`** | 1,282 | **R127 提取** — 管线状态机。`PipelineEngine` 类封装了 start/stop/advance/archive/status/dispatch/retry/notify_pm 等全部管线操作逻辑 |

### 🟠 命令处理（##/! 命令）

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`commands/__init__.py`** | 202 | 构建 `_ADMIN_COMMANDS` 注册表，导入各子模块的命令函数（R131 新增 ##query 规则组） |
| **`commands/pipeline.py`** | 2,085 | 管线命令族：start/stop/status/activate/handoff/reject/force/verify/step/archive/advance/retry/review |
| **`commands/workspace.py`** | 455 | 工作区命令：create/close/list/join/leave/add/remove/list_members |
| **`commands/agent_card.py`** | 258 | Agent 卡片命令：list/get/set/unset/reload/register/auto_register/role_map |
| **`commands/task.py`** | 197 | 任务命令：create/update/query/list |
| **`commands/admin.py`** | 176 | 管理命令：approve_ws_admin/reject_ws_admin/list_pending/audit_log/revoke_api_key |

### 🟡 Web 服务（进程 2）

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`web_ui/main.py`** | 113 | **独立 Web HTTP 入口**。启动 aiohttp 服务（端口 8766），注册 viewer.py 的全部 Web API 路由，后台轮询 WSS 核心 bot 状态。**R101 新增，R102 扩展** |
| **`web_ui/viewer.py`** | 779 | Web HTTP API 处理函数 + 会话管理 + GitHub OAuth。含聊天历史 / 收件箱 / 频道列表 / 搜索 / 归档 / 管线状态 / Agent 状态等全部 API |
| **`web_ui/templates.py`** | 850 | Web 聊天界面 HTML/CSS/JS 内联模板（单文件，无外部依赖）。含 5-Tab 布局（📬收件箱 🏠大厅 📂工作区 📚历史 📊管线）、收件箱发件人8色系统（R133）、管线 Dashboard、工作室面板 |

### 🟡 工作区

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`workspace.py`** | 460 | 工作区 CRUD + 生命周期状态机 + JSON 持久化 + 自动归档 |
| **`workspace_api.py`** | 37 | HTTP API 端点（GET /api/workspaces） |

### 🟠 管线系统

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`pipeline_context.py`** | 692 | PipelineContext dataclass + PipelineContextManager（CRUD + 状态机 + JSON 持久化 + JSONL 历史归档） |
| **`pipeline_sync.py`** | 203 | 管线 Git 同步检测（检查 dev 分支新提交，通过 commit message 匹配推进状态） |
| **`timeout_tracker.py`** | 164 | Step 超时计时器（纯内存，无 async 无依赖） |
| **`auto_router.py`** | 750 | 🚂 管线自动路由服务 — **独立外挂进程，已停用（R129 确认退役）**，保留为独立 CLI 脚本 |

### 🔴 Agent 管理

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`agent_card.py`** | 429 | Agent Card 加载/迁移/注册/热更新/离线检测 |
| **`task_store.py`** | 184 | SQLite 任务存储（R38 任务状态机，与 pipeline 关联） |
| **`audit.py`** | 94 | AuditLogger — 审计日志（##/! 命令执行 → _audit_log.jsonl） |

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
              ├── "register"         → handle_register()          (R72)
              ├── "agent_card_register" → handle_agent_card_register()
              ├── "message"          → handle_broadcast()
              │                        ├─ 解析 ##/! 命令 → commands/注册表
              │                        ├─ _inbox:server → _handle_server_relay()
              │                        │                    └─ scenario_matcher.py 规则表
              │                        │                       ├─ test ✅ 回路测试
              │                        │                       ├─ to_agent 派活路由
              │                        │                       ├─ ## 命令 → pipeline_engine
              │                        │                       ├─ 收到 ✅ / 已完成 ✅
              │                        │                       ├─ 退回 🔄 / 失败 ❌
              │                        │                       └─ ! 命令透传
              │                        ├─ inbox 单播  → 路由到目标 bot
              │                        └─ 频道广播   → 路由到频道成员
              │                                             │
              │                                     save_message(DB)
              │
              └── 其他 msg_type      → 各自 handler
```

### 3.2 Web 界面数据流

```
  浏览器                              Web 服务 (8766)                  WSS 核心 (8765)
   │                                      │                              │
   ├─ 首次加载 GET / ──────────────────→  templates.py                  │
   │                                      │                              │
   ├─ 每 5s → GET /api/chat?since=... ──→  viewer.py        ──读 DB──→ message_store
   ├─ 每 5s → GET /api/chat/inbox ──────→  viewer.py        ──读 DB──→ message_store
   ├─ 每 10s → GET /api/bot_status ────→  web_ui/main (缓存)            │
   │                                      │        ↑                    │
   │                                      │  后台线程每 10s              │
   │                                      │  GET /api/status ──────────→  _connections
   ├─ 下拉刷新 → 同 5s 轮询              │                              │
   ├─ 每 Ns → GET /api/pipelines ──────→  viewer.py       ──读 JSON──→ pipeline_contexts.json
   ├─ 每 15s → GET /api/workspaces ────→  workspace_api   ──读 JSON──→ workspace.py
   └─ 每 15s → GET /api/agent_status ──→  viewer.py       ──读 JSON──→ agent_card.py
```

> **R101 关键变更：** 23 处 `write_chat_log()` 全部从 WSS 核心移除。消息持久化仅靠
> `save_message(DB)`。Web 端不再走 WS 推流，改用 5 秒 fetch 轮询。
>
> **R102 关键变更：** Web 服务增加后台轮询 + 内存缓存，暴露 `/api/bot_status` 给前端。
>
> **R112 关键变更：** 新增 Pipeline Dashboard，Web UI 通过 `/api/pipelines` 展示管线状态。
>
> **R126/R127 关键变更：** 场景匹配规则（scenario_matcher.py）和管线状态机（pipeline_engine.py）
> 从 main.py 提取为独立模块。
>
> **R131 关键变更：** 6 个 `!` 查询命令规则化为 `##query` 命令族。
>
> **R133 关键变更：** Web 收件箱颜色系统扩展为 8 色（+系统蓝 + 经理紫），收件人使用 bot 颜色。

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
│  data/pipeline_contexts.json    ← pipeline_context.py（活跃管线）
│  data/pipeline_contexts_history.jsonl ← pipeline_context.py（归档流水）
│  data/pipeline_archive.json     ← pipeline_engine.py（已归档管线）
│  data/_approved_users.json      ← persistence.py
│  data/_web_sessions.json        ← persistence.py
│  data/_api_keys.json            ← persistence.py
│  data/_archive_state.json       ← viewer.py（Web 归档状态）
│  data/_audit_log.jsonl          ← audit.py
├───────────────────────┤
│ SQLite                 │
│  data/messages.db      ← message_store.py (原始消息，7天滚动)
│  data/tasks.db         ← task_store.py (任务状态)
└───────────────────────┘
```

> **R101 后不再活跃写入：** `data/chat_logs/` 目录下的 JSONL 日志文件是旧 `write_chat_log()`
> 的历史遗留产物。R101 已移除所有 `write_chat_log()` 调用，但已有日志文件在 volumes 中保留。
> `data/pairing_codes/` 目录为更早期的 Web 登录方式，已不再主动写入。

---

## 四、管线系统详解

### 4.1 历史 & 现状

| 阶段 | 引入 | 机制 | 当前状态 |
|:-----|:-----|:------|:---------|
| **R42-R74** | 旧管线 | `_PIPELINE_STATE`（内存 dict）+ `_PIPELINE_CONFIG`（WORK_PLAN frontmatter） | 逐步迁移中 |
| **R77-R97** | PipelineContext | `PipelineContextManager` (dataclass + JSON 持久化 + 状态机) | 当前主力 |
| **R97** | AutoRouter | 独立外挂进程 | **已停用（R129 确认退役）** |
| **R126** | ScenarioMatcher | 场景匹配规则表，从 main.py 提取 | ✅ 活跃 |
| **R127** | PipelineEngine | 管线状态机模块化，从 main.py 提取为独立 class | ✅ 活跃 |

### 4.2 当前管线工作流

```
① PM 编写需求文档 + WORK_PLAN → 推 dev
② 经理/用户发 ##start##R{N} 到 _inbox:server 启动管线
③ 管线自动派活 Step 1 → PM 推 dev
④ 完成后 bot 回复 ✅ 完成到 _inbox:server
⑤ 场景匹配器检测 → 推进到下一步 → 自动派活
⑥ 重复直到 Step 6（合并部署）→ 手动 ##archive##R{N} 归档
```

> 推进不依赖 AutoRouter。所有推进通过 `scenario_matcher.py` 规则引擎自动检测完成消息，
> 调用 `pipeline_engine.py` 推进状态机。

### 4.3 场景匹配规则优先级

| 优先级 | 规则 | 说明 |
|:------:|:-----|:------|
| 10 | `test ✅` 回路测试 | 健康检查回路 |
| 20 | `to_agent` 派活路由 | 定向派活流程 |
| 30 | `##` 命令 | 转 commands/ 或 pipeline_engine |
| 35 | PM 安全守卫 | 拒绝 PM 本人发 `_inbox:server` |
| 40 | `收到 ✅` / `ACK ✅` PM 通知 | 进度通知 |
| 50 | `已完成 ✅` / `✅ 完成` 自动确认 | **触发管线推进** |
| 60 | `退回 🔄` 驳回回退 | 回退重做 |
| 70 | `失败 ❌` 告警通知 | 异常告警 |
| 80 | `!` 命令透传 | 旧格式兼容 |
| 90 | 无匹配 → 入库留痕 | 默认兜底 |

### 4.4 Bot 权限等级（R99/R131）

| 等级 | 能力 |
|:----:|:------|
| **L1** | 测试 + `##whoami` |
| **L3** | 查询、收消息（不能主动发消息给其他 bot） |
| **L4** | 完整读写：发消息 + 管线操作 + 管理命令（含 `##start`/`##step`/`##task`） |

> 权限检查函数 `_check_level(channel, sender_id, min_level)` 定义在 main.py。
> `##query` 命令族（R131）使用 `_QUERY_LEVEL_MAP` 表按子命令细分权限级别。

---

## 五、依赖关系

```
━━━ 进程 1: WSS 核心 ━━━
ws_server/__main__.py
  ├── ws_server/main.py（核心消息路由）
  │     ├── ws_server/state.py
  │     ├── ws_server/command_utils.py
  │     ├── ws_server/scenario_matcher.py（场景匹配规则表）
  │     ├── ws_server/pipeline_engine.py（管线状态机）
  │     │     └── ws_server/pipeline_context.py
  │     ├── ws_server/commands/
  │     │     ├── pipeline.py
  │     │     ├── workspace.py
  │     │     ├── agent_card.py
  │     │     ├── task.py
  │     │     └── admin.py
  │     ├── ws_server/agent_card.py
  │     ├── ws_server/workspace.py / workspace_api.py
  │     ├── ws_server/audit.py
  │     ├── ws_server/message_store.py
  │     ├── ws_server/task_store.py
  │     ├── ws_server/pipeline_sync.py
  │     ├── ws_server/timeout_tracker.py
  │     ├── server/common/auth.py
  │     ├── server/common/persistence.py
  │     └── server/common/config.py
  └── (内联路由注册 + HTTP 端点)

━━━ 进程 2: Web 服务 ━━━
web_ui/main.py
  ├── web_ui/viewer.py（路由注册 + API 处理）
  │     ├── server/common/auth.py
  │     ├── server/common/persistence.py
  │     ├── server/common/config.py
  │     ├── server/common/message_store.py
  │     └── ws_server/pipeline_context.py（只读 PipelineContextManager）
  ├── web_ui/templates.py（HTML/CSS/JS）
  └── [后台线程] ──HTTP──→ ws_server/__main__.py:/api/status（WSS 核心）
```

> **进程隔离：** 两个进程不共享内存状态。WSS 核心的 `_connections` 不暴露给 Web 服务。
> Web 服务通过 HTTP 调用 WSS 核心的 `/api/status` 获取 bot 在线状态（R102）。
> 管线上下文通过 JSON 文件共享（Web 服务进程从 `pipeline_contexts.json` 读取）。

---

## 六、开发准则

### 6.1 文件职责边界

| 文件 | 职责 |
|:-----|:------|
| **`main.py`** | 只做 WebSocket 消息路由、消息广播、命令路由分发。所有 `##/!` 命令处理逻辑 → 拆到 `commands/*.py` |
| **`scenario_matcher.py`** | 场景匹配规则表 — 声明式规则，显式优先级。不涉及 WS 通信 |
| **`pipeline_engine.py`** | 管线状态机 — start/stop/advance/archive/dispatch 全部管线操作。不涉及 WS 通信 |
| **`commands/*.py`** | 只处理 `##/!` 命令的业务逻辑。不能直接操作 WebSocket 连接，只能返回字符串响应 |
| **`state.py`** | 持有共享状态，不包含业务逻辑 |
| **`command_utils.py`** | 命令路由的纯工具函数，不包含业务逻辑 |
| **`pipeline_*.py`** | 只关心管线数据模型、状态机、持久化。不涉及 WS 通信 |
| **`web_ui/main.py`** | 只做 Web 服务启动和路由注册。不处理 WS 连接 |
| **`web_ui/viewer.py`** | HTTP API 处理函数 + 会话管理。被两个进程共用，不持 WebSocket 连接 |

### 6.2 新增功能的约定

1. **新增 `##/!` 命令** → 在 `commands/` 下对应领域文件加函数，`commands/__init__.py` 注册，**不要碰 main.py**
2. **新增 Web API** → 在 `web_ui/viewer.py` 加 handler + `setup_routes()` 注册，**不要碰 `__main__.py`**
3. **新增后台循环** → 判断属于哪个进程：WSS 核心在 `__main__.py` 的 `on_startup` 启动；Web 服务在 `web_ui/main.py` 的 `on_startup` 启动
4. **WS 连接状态** → 留在 `main.py` 的 `_connections` 里
5. **跨进程数据** → 不能直接 import 对方的内存状态，通过 HTTP API（如 `/api/status`）或共享 DB/JSON 文件通信
6. **管线逻辑** → 永远不要写进 main.py，去 `pipeline_engine.py` 或 `commands/pipeline.py`
7. **场景匹配规则** → 永远不要写进 main.py，去 `scenario_matcher.py` 的规则表

### 6.3 已完成的重构

```
Phase 1 ✅ (R100)    📋 命令模块化 — 结构拆分
  → main.py            保留核心 WS 路由
  → state.py           共享状态提取
  → command_utils.py   命令路由工具提取
  → commands/          全部 !命令处理（6 个领域文件）

Phase 1a ✅ (R101)   📋 WSS/Web 解耦
  → web_ui/main.py     独立 Web 服务进程（端口 8766）
  → 移除 23 处 write_chat_log()
  → 移除 _ws_clients（Web 端不再走 WS 推流）
  → 前端改用 5 秒 HTTP 轮询

Phase 1b ✅ (R102)   📋 Bot 在线状态
  → Web 服务后台轮询 WSS 核心 /api/status
  → 内存缓存 → /api/bot_status

Phase 2 ✅ (R126)    📋 场景匹配规则提取
  → scenario_matcher.py 从 main.py 提取
  → HandlerRule 声明式规则表（显式优先级排序）

Phase 3 ✅ (R127)    📋 管线状态机提取
  → pipeline_engine.py 从 main.py 提取
  → PipelineEngine class 封装所有管线操作
```

### 6.4 待办重构

```
Phase 4  📋 统一管线状态
  → 砍掉 _PIPELINE_STATE（内存），全部走 PipelineContextManager
  → 统一 pipeline_contexts.json 写入格式
  → 管线相关辅助函数从 commands/pipeline.py 进一步拆分

Phase 5  📋 main.py 进一步拆分
  → main.py 当前仍有 4,951 行，继续拆分认证、广播、中继等模块
```

---

## 七、数据文件位置

```
data/                                   ← WS_DATA_DIR（默认 ./data）
├── _approved_users.json         前端授权用户
├── _web_sessions.json           Web 登录会话
├── _api_keys.json               API Keys (R72)
├── _archive_state.json          Web 归档状态（R76）
├── workspaces.json              工作区
├── pipeline_contexts.json       管线上下文（活跃）
├── pipeline_contexts_history.jsonl  管线上下文（历史归档流水）
├── pipeline_archive.json        管线归档记录
├── _audit_log.jsonl             审计日志
├── messages.db                  SQLite 消息存储（7 天滚动）
├── tasks.db                     SQLite 任务存储
├── chat_logs/                  聊天日志文件（历史遗留，R101 后不再写入）
└── pairing_codes/              配对码（旧版 Web 登录，不再主动写入）
```
