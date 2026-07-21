# ws_server — WSS 核心进程

> **端口 8765** | WebSocket 服务 + 管线引擎 + 命令路由
>
> 双进程架构中的**进程 1**。处理所有 bot 的 WebSocket 长连接、消息路由、
> 场景匹配中继、管线状态机、!命令分发。与进程 2（Web 服务，端口 8766）
> 通过共享数据存储通信，不共享内存。
>
> 共 **18 个 .py 文件，约 11,515 行**（不含 `commands/` 时为 6,842 行）。

---

## 一、文件清单

### 🟢 入口与路由

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`__main__.py`** | 846 | aiohttp 入口。端点注册（`/ws`, `/api/status`, `/api/health`, `/api/workspaces`），WS 握手，后台清理循环 |
| **`main.py`** | 4,664 | **核心消息路由** — `handler()` WS 会话主循环、`handle_broadcast()` 消息广播、`_handle_server_relay()` inbox 中继、`handle_auth()` 认证、`handle_register()` bot 注册、`_send()` WebSocket 写入。**仍有拆分空间** |
| **`state.py`** | 130 | 共享模块级状态容器。`_PIPELINE_STATE`、`_PIPELINE_CONFIG`、`_connections`、`_delivery_status`、`_offline_push_queue`、`SYSTEM_AGENT_ID` 等。零业务逻辑 |
| **`command_utils.py`** | 205 | 命令路由工具：`_parse_command()` 解析、权限检查、审计日志写入、`_broadcast_to_channel()` 频道广播。纯工具函数，不含业务逻辑 |

### 🟠 场景匹配引擎（R126 + R139）

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`scenario_matcher.py`** | 685 | **规则匹配引擎**。`HandlerRule` dataclass、8 种 match 函数（`match_loopback` / `match_to_agent` / `match_hash_cmd` / `match_query` / `match_pm_guard` / `match_ack` / `match_complete` / `match_reject` / `match_fail` / `match_exclamation` / `match_catchall`）、`register_rule()`、`dispatch()` 优先级调度 |
| **`scenario_rules.py`** | 301 | **回调 handler**（R139 EXT）。`_sm_handle_*()` 回调实现 + `register_all_rules()` 注册函数。从 scenario_matcher.py 提取，保持 matcher 引擎层纯净 |

**处理流程：**

```
_inbox:server 消息
        │
        ▼
scenario_matcher.dispatch()
        │
        ├─ 遍历 _RULES（按 priority 升序）
        │    Rule 10:  test ✅ 回路测试
        │    Rule 20:  to_agent 派活路由
        │    Rule 25:  ##query 查询命令 (R131)
        │    Rule 30:  ## 命令 → pipeline_engine
        │    Rule 35:  PM 安全守卫
        │    Rule 40:  收到 ✅ / ACK ✅ → 通知 PM
        │    Rule 50:  已完成 ✅ / ✅ 完成 → 管线推进
        │    Rule 60:  退回 🔄 → pipeline_engine.handle_reject()
        │    Rule 70:  失败 ❌ → 告警通知
        │    Rule 80:  ! 命令透传 → 正常路由
        │    Rule 90:  无匹配 → 入库留痕
        │
        └─ rule.handle() 在 scenario_rules.py 中实现
```

### 🟠 管线系统

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`pipeline_engine.py`** | 1,406 | **管线状态机（R127）**。`PipelineEngine` class：`start()` / `stop()` / `advance()` / `archive()` / `dispatch()` / `handle_reject()` / `try_advance()` 等全部管线操作。从 main.py 提取为独立模块 |
| **`pipeline_context.py`** | 692 | `PipelineContext` dataclass + `PipelineContextManager`（CRUD + 状态机 + JSON 持久化 + JSONL 历史归档） |
| **`pipeline_sync.py`** | 203 | Git 同步检测。检查 dev 分支新提交，通过 commit message 匹配推进管线状态 |
| **`timeout_tracker.py`** | 164 | Step 超时计时器。纯内存实现，无 async 依赖 |

### 🟠 !命令注册表（`commands/`）

**共 6 个文件，3,373 行。**

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`commands/__init__.py`** | 202 | 构建 `_ADMIN_COMMANDS` 注册表，导入各子模块命令函数 |
| **`commands/pipeline.py`** | 2,085 | pipeline 命令体系：start/stop/status/activate/handoff/reject/force/verify/mode/role_override。**最大文件** |
| **`commands/workspace.py`** | 455 | workspace 命令：create/close/list/join/leave/add/remove/list_members/reset |
| **`commands/agent_card.py`** | 258 | agent_card 命令：list/get/set/unset/reload/register/auto_register/role_map/watch |
| **`commands/task.py`** | 197 | task 命令：create/update/query/list + rollcall_role/rollcall_next |
| **`commands/admin.py`** | 176 | admin 命令：approve_ws_admin/reject_ws_admin/list_pending/audit_log/list_agents/agent_status/revoke_api_key |

### 🔴 Agent 管理

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`agent_card.py`** | 429 | Agent Card 加载/迁移/注册/热更新/离线检测 |
| **`task_store.py`** | 184 | SQLite 任务存储。R38 任务状态机，与 Pipeline 关联 |
| **`audit.py`** | 94 | AuditLogger。!命令执行记录 → `_audit_log.jsonl` |
| **`workspace.py`** | 460 | 工作区 CRUD + 生命周期状态机 + JSON 持久化 + 自动归档 |
| **`workspace_api.py`** | 37 | HTTP API 端点（GET /api/workspaces） |

### 🟡 持久化

| 文件 | 行数 | 职责 |
|:-----|:----:|:------|
| **`message_store.py`** | 264 | SQLite 消息存储实现。7 天 TTL 滚动 |

### 🟡 退役模块

| 文件 | 行数 | 状态 |
|:-----|:----:|:-----|
| **`auto_router.py`** | 750 | 🚂 管线自动路由 — **已停用（R129 确认退役）** |

---

## 二、消息数据流

### 2.1 WebSocket 消息生命周期

```
  Bot ──WS──→ __main__.py (aiohttp /ws 端点)
                      │
                      ▼
              main.handler(ws)       ← 管理整个 WS 会话
                      │
              解析 MSG type
              ├── "auth"             → handle_auth()
              ├── "register"         → handle_register()
              ├── "message"          → handle_broadcast()
              │                        ├─ !command    → commands/注册表
              │                        ├─ _inbox:server → scenario_matcher.dispatch()
              │                        │                   └─ scenario_rules 回调
              │                        ├─ inbox 单播 → 路由到目标 bot
              │                        └─ 频道广播  → 频道成员
              │
              ├── "agent_card_register" → handle_agent_card_register()
              └── 其他 msg_type      → 各自 handler
```

### 2.2 连接状态

```
state._connections: dict[str, set]
  key   = agent_id
  value = set of (ws, handshake_done, ...)  ← 同一 agent 可多连接
```

所有路由查找通过 `_connections` 完成。Web 服务进程不持有此数据，
通过 HTTP `/api/status` 轮询获取 bot 在线快照。

---

## 三、开发准则

### 3.1 文件职责边界

| 文件 | 应做 | 不应做 |
|:-----|:-----|:-------|
| **main.py** | WS 消息路由 / 广播分发 / 命令路由 | ❌ 写 !命令业务逻辑 → commands/*.py |
| **scenario_matcher.py** | 规则引擎（HandlerRule / match 函数 / dispatch） | ❌ 写回调 handler → scenario_rules.py |
| **scenario_rules.py** | 回调 handler + register_all_rules() | ❌ 修改 match 函数或 dispatch 逻辑 |
| **pipeline_engine.py** | 管线状态机逻辑 | ❌ 直接操作 WS 连接 |
| **commands/*.py** | !命令业务逻辑 | ❌ 直接操作 WS 连接（返回字符串） |
| **state.py** | 共享状态容器 | ❌ 任何业务逻辑或函数定义 |
| **command_utils.py** | 纯工具函数 | ❌ 命令业务逻辑 |
| **pipeline_*.py** | 管线数据模型 / 状态机 / 持久化 | ❌ 任何 WS 通信 |

### 3.2 新增功能的约定

1. **新增 !命令** → `commands/` 下加函数，`commands/__init__.py` 注册，**不要碰 main.py**
2. **新增场景匹配规则** → match 函数在 `scenario_matcher.py`，handle 回调在 `scenario_rules.py`，`register_all_rules()` 注册
3. **管线逻辑** → 永远不进 main.py，去 `pipeline_engine.py` 或 `commands/pipeline.py`
4. **跨进程数据** → 通过共享文件（JSON/SQLite）或 HTTP API（如 `/api/status`），不能 import 对方内存

### 3.3 已完成的重构

```
Phase 1 ✅ (R100)    命令模块化
  → state.py / command_utils.py / commands/ 从 main.py 提取

Phase 2 ✅ (R126)    场景匹配规则提取
  → scenario_matcher.py: HandlerRule + match 函数 + dispatch

Phase 3 ✅ (R127)    管线状态机提取
  → pipeline_engine.py: PipelineEngine class

Phase 3a ✅ (R139)   场景回调拆分
  → scenario_rules.py: 回调 handler 独立文件
```

### 3.4 待办重构

```
Phase 4  统一管线状态 — 砍掉 _PIPELINE_STATE（内存），全部走 PipelineContextManager
Phase 5  main.py 继续拆分 — 当前 4,664 行，拆分认证/广播/中继模块
```

---

## 四、数据文件

```
data/                                   ← WS_DATA_DIR（默认 ./data）
├── pipeline_contexts.json       管线上下文（活跃） — pipeline_context.py
├── pipeline_contexts_history.jsonl  管线上下文（归档流水）
├── pipeline_archive.json        管线归档记录 — pipeline_engine.py
├── workspaces.json              工作区 — workspace.py
├── _audit_log.jsonl             审计日志 — audit.py
├── messages.db                  SQLite 消息存储（7 天滚动） — message_store.py
├── tasks.db                     SQLite 任务存储 — task_store.py
├── _approved_users.json         前端授权用户 — persistence.py
├── _web_sessions.json           Web 登录会话 — persistence.py
├── _api_keys.json               API Keys（R72） — persistence.py
├── chat_logs/                  日志文件（R101 后不再写入）
└── pairing_codes/              配对码（旧版登录，不再主动写入）
```
