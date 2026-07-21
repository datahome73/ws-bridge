# ws_server — WSS 核心进程

> **端口 8765** | WebSocket 服务 + 管线引擎 + 命令路由
>
> 双进程架构中的**进程 1**。处理所有 bot 的 WebSocket 长连接、消息路由、
> 场景匹配中继、管线状态机、!命令分发。与进程 2（Web 服务，端口 8766）
> 通过共享数据存储通信，不共享内存。
>
> 当前版本：**R140**（权限修复 / 跨步推进 / 失败通知）。共 **18 个 .py 文件，约 11,515 行**。

---

## 一、文件清单

### 🟢 入口与路由

| 文件 | 行数 | 职责 |
|:------|:----:|:--------|
| **`__main__.py`** | 846 | aiohttp 入口。端点注册（`/ws`, `/api/status`, `/api/health`, `/api/workspaces`），WS 握手，后台清理循环 |
| **`main.py`** | 4,664 | **核心消息路由** — `handler()` WS 会话主循环、`handle_broadcast()` 消息广播、`_handle_server_relay()` inbox 中继、`handle_auth()` 认证、`handle_register()` bot 注册、`_send()` WebSocket 写入。**R138/R140 吸收了 ack_machine / connection_manager / watchdog 等模块逻辑** |
| **`state.py`** | 130 | 共享模块级状态容器。`_PIPELINE_STATE`、`_PIPELINE_CONFIG`、`_connections`、`_delivery_status`、`_offline_push_queue`、`SYSTEM_AGENT_ID` 等。零业务逻辑 |
| **`command_utils.py`** | 205 | 命令路由工具：`_parse_command()` 解析、权限检查、审计日志写入、`_broadcast_to_channel()` 频道广播 |

### 🟠 场景匹配引擎（R126 + R139）

| 文件 | 行数 | 职责 |
|:------|:----:|:--------|
| **`scenario_matcher.py`** | 685 | **规则匹配引擎**。`HandlerRule` dataclass、11 种 match 函数（loopback / to_agent / hash_cmd / query / pm_guard / ack / complete / reject / fail / exclamation / catchall）、`register_rule()`、`dispatch()` 优先级调度 |
| **`scenario_rules.py`** | 301 | **回调 handler**（R139 EXT）。`_sm_handle_*()` 回调实现 + `register_all_rules()` 注册函数 |

**处理流程：**

```
_inbox:server 消息 → scenario_matcher.dispatch()
  ├─ Rule 10 (p=10)  test ✅ 回路测试
  ├─ Rule 20 (p=20)  to_agent 派活路由
  ├─ Rule 25 (p=25)  ##query 查询命令（R131）
  ├─ Rule 30 (p=30)  ## 命令 → pipeline_engine.handle_hash_*()
  ├─ Rule 35 (p=35)  PM 安全守卫 — 拒绝 PM 本人发 _inbox:server
  ├─ Rule 40 (p=40)  收到 ✅ / ACK ✅ → 通知 PM
  ├─ Rule 50 (p=50)  已完成 ✅ / ✅ 完成 → pipeline_engine.try_advance()
  ├─ Rule 60 (p=60)  退回 🔄 → pipeline_engine.handle_reject()
  ├─ Rule 70 (p=70)  失败 ❌ → 告警通知
  ├─ Rule 80 (p=80)  ! 命令透传 → 正常路由
  └─ Rule 90 (p=90)  无匹配 → 入库留痕
```

### 🟠 管线系统

| 文件 | 行数 | 职责 |
|:------|:----:|:--------|
| **`pipeline_engine.py`** | 1,406 | **管线状态机（R127 + R140）**。`PipelineEngine` class 封装全部管线操作。R140 新增：##advance L4+ 权限 / 跨步推进 / 失败通知发起者 / 自动确认 Step 1 并派活 Step 2 |
| **`pipeline_context.py`** | 692 | `PipelineContext` dataclass + `PipelineContextManager`（CRUD + 状态机 + JSON 持久化 + JSONL 历史归档） |
| **`pipeline_sync.py`** | 203 | Git 同步检测。检查 dev 分支新提交，通过 commit message 匹配推进管线状态 |
| **`timeout_tracker.py`** | 164 | Step 超时计时器。纯内存实现，无 async 依赖 |

### 🟠 !命令注册表（`commands/`）

**共 6 个文件，3,373 行。**

| 文件 | 行数 | 职责 |
|:------|:----:|:--------|
| **`commands/__init__.py`** | 202 | 构建 `_ADMIN_COMMANDS` 注册表 |
| **`commands/pipeline.py`** | 2,085 | pipeline 命令：start/stop/status/activate/handoff/reject/force/verify/mode/role_override |
| **`commands/workspace.py`** | 455 | workspace 命令：create/close/list/join/leave/add/remove/list_members/reset |
| **`commands/agent_card.py`** | 258 | agent_card 命令：list/get/set/unset/reload/register/auto_register/role_map/watch |
| **`commands/task.py`** | 197 | task 命令：create/update/query/list + rollcall_role/rollcall_next |
| **`commands/admin.py`** | 176 | admin 命令：approve_ws_admin/reject_ws_admin/list_pending/audit_log/list_agents/agent_status/revoke_api_key |

### 🔴 Agent 管理 & 工作区

| 文件 | 行数 | 职责 |
|:------|:----:|:--------|
| **`agent_card.py`** | 429 | Agent Card 加载/迁移/注册/热更新/离线检测 |
| **`task_store.py`** | 184 | SQLite 任务存储。R38 任务状态机，与 Pipeline 关联 |
| **`audit.py`** | 94 | AuditLogger — !命令执行 → `_audit_log.jsonl` |
| **`workspace.py`** | 460 | 工作区 CRUD + 生命周期状态机 + JSON 持久化 + 自动归档 |
| **`workspace_api.py`** | 37 | HTTP API 端点（GET /api/workspaces） |

### 🟡 持久化

| 文件 | 行数 | 职责 |
|:------|:----:|:--------|
| **`message_store.py`** | 264 | SQLite 消息存储实现。7 天 TTL 滚动 |

### 🟡 退役模块

| 文件 | 行数 | 状态 |
|:------|:----:|:------|
| **`auto_router.py`** | 750 | 🚂 管线自动路由 — **已停用（R129 确认退役）**，保留代码 |

> **R138/R140 已删除的模块：**
> - `ack_machine.py` — ACK 处理 → 逻辑并入 main.py
> - `connection_manager.py` — 连接管理 → 逻辑并入 main.py
> - `git_sync_scheduler.py` — Git 同步调度 → 逻辑并入 pipeline_engine.py
> - `pipeline_timeout.py` — 超时管理 → 逻辑并入 pipeline_engine.py
> - `watchdog.py` — 看门狗 → 逻辑并入 main.py
> - `engine2.py` — 实验性引擎 → 合并回 pipeline_engine.py（R138）

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

## 三、管线系统详解

### 3.1 PipelineEngine 核心方法

```
PipelineEngine
├── 生命周期
│   ├── start()     → 启动后台扫描（git sync + timeout scanner）
│   └── stop()      → 停止所有后台扫描
│
├── 状态推进
│   ├── try_advance(content, agent_id)     → 检测完成消息，自动推进
│   ├── auto_advance(context)              → 无条件推进到下一步
│   ├── handle_advance(sender_role, args)  → ##advance（R140: L4+权限+跨步）
│   └── handle_reject(content, agent_id)   →  退回回退
│
├── 自动调度
│   ├── auto_dispatch(context, step_idx)   → 派活到指定步骤
│   ├── auto_re_notify(context, step_idx)  → 重新通知重试
│   └── _dispatch_with_notify()            → R140: 派活失败通知发起者
│
├── ## 命令
│   ├── handle_hash_cmd(ws, agent_id, msg, matched) → 统一 ##* 入口
│   ├── handle_start()   →  ##start (R140 A-6: 自动确认Step 1 + 派活Step 2)
│   ├── handle_stop()    →  ##stop
│   ├── handle_status()  →  ##status
│   ├── handle_advance() →  ##advance (R140 A-1: L4+权限 / A-2:跨步)
│   └── handle_archive() →  ##archive
│
├── 归档管理
│   ├── archive(context) → 归档管线
│   └── find(...)        → 搜索归档管线
│
├── 通知
│   ├── notify_pm(agent_id, msg)    → 通知 PM
│   └── notify_ws(ws, msg)          → 直接通知 WS 连接（R140 A-4/A-5）
│
├── 后台扫描
│   ├── _git_sync_loop()            → 定期检查 git 新提交
│   └── _timeout_scanner()          → 检查 step 超时
│
├── 模板渲染
│   ├── render_context(context)     → 渲染状态摘要
│   ├── summary(contexts)           → 多管线概览
│   └── agent_name(agent_id)        → agent 名称解析
│
└── 状态格式化
    └── format_context(context)     → 格式化单管线状态
```

### 3.2 R140 核心变更

| 变更 | 说明 |
|:-----|:------|
| **A-1 ##advance 权限** | L4 及以上等级即可使用（不限于 PM） |
| **A-2 跨步推进** | 自动跳过中间步骤，标记跳过的步骤状态 |
| **A-4/A-5 失败通知** | 派活失败时通过 `notify_ws` 或 `notify_agent_id` 通知发起者 |
| **A-6/A-7 自动起始** | ##start 后自动确认 Step 1 完成 + 尝试派活 Step 2 |
| **A-8 派活反馈** | 通知完成消息发送者派活结果，显示 agent 名称 |

### 3.3 数据持久化层次

```
内存 (不落盘)
  state._PIPELINE_STATE    ← 仅存活跃管线运行时状态
  state._PIPELINE_CONFIG   ← 只读配置，从 WORK_PLAN 解析
  state._connections       ← 在线连接集合
  timeout_tracker          ← 超时计时器
  engine._pending_retries  ← 待重试派活

JSON 文件
  data/pipeline_contexts.json        ← pipeline_context.py（活跃管线）
  data/pipeline_contexts_history.jsonl ← pipeline_context.py（归档流水）
  data/pipeline_archive.json         ← pipeline_engine.py（已归档管线）
  data/workspaces.json               ← workspace.py
  data/_audit_log.jsonl              ← audit.py
  data/_approved_users.json          ← persistence.py
  data/_web_sessions.json            ← persistence.py
  data/_api_keys.json                ← persistence.py

SQLite
  data/messages.db      ← message_store.py (原始消息，7天滚动)
  data/tasks.db         ← task_store.py (任务状态)
```

---

## 四、开发准则

### 4.1 文件职责边界

| 文件 | 应做 | 不应做 |
|:------|:------|:--------|
| **main.py** | WS 消息路由 / 广播分发 / 命令路由 | ❌ 写 !命令业务逻辑 → commands/*.py |
| **scenario_matcher.py** | 规则引擎（HandlerRule / match 函数 / dispatch） | ❌ 写回调 handler → scenario_rules.py |
| **scenario_rules.py** | 回调 handler + register_all_rules() | ❌ 修改 match 函数或 dispatch 逻辑 |
| **pipeline_engine.py** | 管线状态机逻辑 | ❌ 直接操作 WS 连接 |
| **commands/*.py** | !命令业务逻辑 | ❌ 直接操作 WS 连接（返回字符串） |
| **state.py** | 共享状态容器 | ❌ 任何业务逻辑或函数定义 |
| **command_utils.py** | 纯工具函数 | ❌ 命令业务逻辑 |
| **pipeline_*.py** | 管线数据模型 / 状态机 / 持久化 | ❌ 任何 WS 通信 |

### 4.2 新增功能的约定

1. **新增 !命令** → `commands/` 下加函数，`commands/__init__.py` 注册，**不要碰 main.py**
2. **新增场景匹配规则** → match 函数在 `scenario_matcher.py`，handle 回调在 `scenario_rules.py`，`register_all_rules()` 注册
3. **管线逻辑** → 永远不进 main.py，去 `pipeline_engine.py` 或 `commands/pipeline.py`
4. **跨进程数据** → 通过共享文件（JSON/SQLite）或 HTTP API（如 `/api/status`），不能 import 对方内存

### 4.3 已完成的重构

```
Phase 1 ✅ (R100)    📋 命令模块化
  → state.py / command_utils.py / commands/ 从 main.py 提取

Phase 1a ✅ (R101)   📋 WSS/Web 解耦
  → web_ui/main.py 独立进程; 移除 write_chat_log() 和 WS 推流

Phase 1b ✅ (R102)   📋 Bot 在线状态
  → Web 服务后台轮询 + 内存缓存

Phase 2 ✅ (R126)    📋 场景匹配规则提取
  → scenario_matcher.py: HandlerRule + match 函数 + dispatch

Phase 3 ✅ (R127)    📋 管线状态机提取
  → pipeline_engine.py: PipelineEngine class

Phase 3a ✅ (R139)   📋 场景回调拆分
  → scenario_rules.py: 回调 handler 独立文件

Phase 3b ✅ (R138)   📋 引擎合并
  → engine2 → pipeline_engine.py 合并; ack_machine / connection_manager
    / git_sync_scheduler / pipeline_timeout / watchdog 逻辑吸收入主模块
```

### 4.4 待办重构

```
Phase 4  📋 统一管线状态
  → 砍掉 _PIPELINE_STATE（内存），全部走 PipelineContextManager
  → 统一 pipeline_contexts.json 写入格式

Phase 5  📋 main.py 继续拆分
  → main.py 当前 4,664 行，拆分认证/广播/中继模块（R138/R140 合并了
    多个小模块进来，实际行数没有下降）
```
