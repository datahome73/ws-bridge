# Server — WS Bridge 服务端

> 本目录是 ws-bridge 服务端的全部核心代码。**共 17 个 .py 文件，12,858 行。**

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
│  handler.py  ← ← ←  7,007 行 — 请勿再往此文件加逻辑          │
│                                                               │
│  WebSocket 消息处理（消息入口）                                │
│  ├── handle_auth()          认证                               │
│  ├── handle_register()      bot 注册                           │
│  ├── handle_broadcast()     消息广播（核心）                    │
│  ├── _handle_server_relay() inbox 中继                         │
│  ├── _handle_server_query() _inbox:server 查询路由             │
│  └── handler()              WS 会话主循环                      │
│                                                               │
│  !命令路由 & 处理                                             │
│  ├── 工作区命令  workspace: create/close/list/join/leave       │
│  ├── 管线命令    pipeline: start/stop/status/activate/handoff  │
│  ├── 任务命令    task: create/update/query/list                │
│  ├── Agent Card  card: list/get/set/reload/register            │
│  └── 管理命令    admin: approve/reject/audit/revoke            │
│                                                               │
│  ⚠️ 还塞了: 管线状态机 / 看门狗 / Git 同步 / ACK / 超时       │
│            角色映射 / Step 验证 / 备用接管/...                 │
└──────────┬────────────────────────────────────────────────────┘
           │ 调用
           ▼
┌──────────┴────────────────────────────────────────────────────┐
│  领域模块层                                                    │
│                                                                │
│  workspace.py       工作区 CRUD + 状态机 + 自动归档            │
│  auth.py            认证 & 权限检查                            │
│  agent_card.py      Agent Card 加载/注册/热更新                │
│  audit.py           审计日志 (JSONL)                           │
│  persistence.py     JSON 持久化（用户/会话/API Keys）          │
│  message_store.py   SQLite 消息存储（7天滚动）                 │
│  task_store.py      SQLite 任务存储（R38 任务状态机）          │
│  pipeline_context.py PipelineContext 数据类 + 管理器 + 持久化  │
│  pipeline_sync.py   管线 Git 同步检测                          │
│  timeout_tracker.py Step 超时计时器（纯内存）                  │
│  config.py          配置（环境变量）                            │
│  templates.py       Web 界面 HTML/CSS/JS 模板                  │
│  web_viewer.py      Web 聊天界面后端（HTTP + WS 端点）         │
│  workspace_api.py   Workspace HTTP API                         │
│  auto_router.py     🚂 管线自动路由（已停用）                  │
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
| **`handler.py`** | 7007 | ⚠️ **WebSocket 消息处理 + 全部 !命令 — 当前过载，需要拆分** |
| **`message_store.py`** | 245 | 消息持久化 (SQLite, 7天TTL) |
| **`templates.py`** | 762 | Web 聊天界面 HTML/CSS/JS 内联模板 |
| **`web_viewer.py`** | 725 | Web 界面后端（路由、聊天缓冲、ChatLog 写入） |

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
              handler(ws)       ← 最顶层协程，管理整个 WS 会话
                      │
              解析 MSG type
              ├── "auth"       →  handle_auth()
              ├── "register"   →  handle_register()
              ├── "message"    →  handle_broadcast()
              │                    ├─ 解析 !command → 路由到 _cmd_*()
              │                    └─ 广播到频道成员
              ├── "agent_card_register" → handle_agent_card_register()
              └── 其他
```

### 3.2 数据持久化层次

```
┌───────────────────────┐
│ 内存 (不落盘)          │
│  _PIPELINE_STATE      │  ← R42 旧系统，仅存活跃管线运行时状态
│  _PIPELINE_CONFIG     │  ← R62 只读配置，从 WORK_PLAN 解析
│  _connections         │  ← 在线连接集合
│  _step_ack_states     │  ← R53 频道切换 ACK（逐步迁移中）
│  timeout_tracker      │  ← 超时计时器
│  watchdog 状态         │
├───────────────────────┤
│ JSON 文件              │
│  data/workspaces.json           ← workspace.py
│  data/pipeline_contexts.json    ← pipeline_context.py + auto_router.py
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
│  data/im.db            ← ? (可能存在)
└───────────────────────┘
```

---

## 四、管线系统详解

### 4.1 历史 & 现状

管线系统经历了三个阶段的演进，但遗留了大量中间状态：

| 阶段 | 引入 | 机制 | 当前状态 |
|---|---|---|---|
| **R42-R74** | 旧管线 | `_PIPELINE_STATE` (内存 dict) + `_PIPELINE_CONFIG` (WORK_PLAN frontmatter) | **仍在使用**，!pipeline_status 等大量命令依赖 |
| **R77-R97** | PipelineContext | `PipelineContextManager` (dataclass + JSON 持久化 + 状态机) | **部分使用**，!pipeline_start 写入，!pipeline_stop 读取 |
| **R97** | AutoRouter | 独立外挂进程，dict 格式 PipelineContext，文件共享 | **已停用**（`531c601`） |

### 4.2 当前管线流转

```
!pipeline_start R97
  → 写入 pipeline_contexts.json（dict 格式）
  → 更新 _PIPELINE_STATE（内存）
  → 广播 _admin 「R97 管线已启动」

之后全靠手动:
!step_handoff R97 step2 → 构建任务消息 → 发送到 bot inbox
Bot 完成任务 → 回复 _inbox:server 「✅ 完成...」
  → handler.py 解析完成通知
  → PM 手动触发下一棒
```

### 4.3 已知问题

| 问题 | 说明 |
|---|---|
| **handler.py 7007行** | 包揽了 WebSocket 处理、命令路由、管线状态机、看门狗、Git 同步、ACK、超时、角色映射等数十项职责 |
| **三套管线状态并存** | `_PIPELINE_STATE`(内存) + `PipelineContextManager`(dataclass+JSON) + AutoRouter 自维护(dict+JSON)，数据流向混乱 |
| **pipeline_contexts.json 双格式混写** | PipelineContextManager(dataclass→dict A) 和 AutoRouter(dict B) 写同一个文件，结构不同 |
| **AutoRouter 停用=管线断链** | `!pipeline_start` 仍说"AutoRouter 将自动派活"，但无人接管 |
| **状态依赖交叉** | handler.py 里 20+ 个 `_cmd_*` 函数直接读写全局变量，难以单体测试 |
| **配置散落** | 部分配置在 `config.py`，部分在 `handler.py` 顶层，部分在 `_PIPELINE_CONFIG` 动态构造 |

---

## 五、依赖关系

```
__main__.py
  ├── handler.py    (直接导入 _connections, handle_auth, handle_broadcast...)
  │     ├── auth.py
  │     ├── audit.py
  │     ├── agent_card.py (load_cards, get_all_cards)
  │     ├── workspace.py  (get_workspace, get_active_workspaces...)
  │     ├── pipeline_context.py  (PipelineContextManager...)
  │     ├── pipeline_sync.py (pipeline_git_sync_scan)
  │     ├── timeout_tracker.py
  │     ├── task_store.py
  │     ├── persistence.py
  │     ├── message_store.py
  │     ├── web_viewer.py  (write_chat_log)
  │     └── shared.protocol
  ├── message_store.py
  ├── persistence.py
  ├── workspace.py
  ├── web_viewer.py
  │     ├── auth.py
  │     ├── templates.py
  │     └── message_store.py
  └── workspace_api.py
        └── workspace.py
```

> **`handler.py` 的扇入和扇出都是最高的** —— 所有模块都直接或间接依赖它，而它又几乎依赖所有其他模块。这是重构需要解决的核心耦合点。

---

## 六、开发准则

### 6.1 文件职责边界

```
handler.py     → 只做 WebSocket 消息路由、消息广播、命令路由分发。
                 所有 !命令处理逻辑 → 拆到独立的 *_cmd.py 模块。
                 管线状态机 → 拆到 pipeline_state.py。
                 看门狗 → 拆到 watchdog.py。
                 验证钩子 → 拆到 validation.py。

pipeline_*.py → 只关心管线数据模型、状态机、持久化。
                 不涉及 WS 通信、消息解析、!命令处理。

workspace.py  → 已较好解耦，保持即可。

agent_card.py  → 已较好解耦，保持即可。
```

### 6.2 新增功能的约定

1. **新增 !命令** → 不要在 handler.py 里加 `_cmd_*`，新建 `commands/xxx.py`，在 `__main__.py` 注册路由
2. **新增状态** → 不要加新的全局 dict，用 `PipelineContextManager` 或专门的 Manager 类
3. **新增后台循环** → 在 `__main__.py` 的 `on_startup` 中启动，不要在 handler.py 里起 task
4. **WS 连接状态** → 留在 `handler.py` 的 `_connections` 里（这是它该管的）
5. **管线逻辑** → 永远不要写进 handler.py，去 `pipeline_*.py`

### 6.3 重构路线图（建议）

```
Phase 1  📋 拆 handler.py（7007 行 → 可管理的模块）
  → commands/           !命令处理（~30 个 _cmd_*）
  → pipeline_state.py   管线状态管理（从 handler 剥离）
  → watchdog.py         看门狗逻辑
  → validation.py       Step 验证钩子

Phase 2  📋 统一管线状态
  → 砍掉 _PIPELINE_STATE（内存），全部走 PipelineContextManager
  → 统一 pipeline_contexts.json 写入格式

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
