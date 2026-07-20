# ws_server — WSS 核心进程

> WSS 进程是 ws-bridge 的 WebSocket 服务核心。**共 15 个源文件，约 5,000 行。**
>
> `main.py` 占 3,706 行，是该包最大的文件，也是后续重构的主要目标。
>
> R134 已清理 8 个废止文件：`auto_router.py`、`command_utils.py`、`workspace_api.py`、
> `commands/__init__.py`、`commands/admin.py`、`commands/agent_card.py`、
> `commands/task.py`、`commands/workspace.py`。`!` 命令体系整体移除，
> 管线操作已统一到 `##` 命令族（scenario_matcher）和 PipelineEngine。

---

## 目录

- [一、包结构与模块职责](#一包结构与模块职责)
- [二、架构分层](#二架构分层)
- [三、消息路由总览](#三消息路由总览)
- [四、模块关联图](#四模块关联图)
- [五、数据层](#五数据层)
- [六、管线领域](#六管线领域)
- [七、命令体系](#七命令体系)
- [八、`main.py` 重构清单](#八mainpy-重构清单)
- [九、启动流程](#九启动流程)

---

## 一、包结构与模块职责

```
ws_server/
├── __init__.py           # 包声明（一行）
├── __main__.py           # aiohttp 入口：WebSocket 会话生命周期 + HTTP API 端点
│
├── main.py               # 【核心路由器】— 3,706 行，需重构
│   ├── WebSocket 连接管理（_connections / auth / register）
│   ├── handle_broadcast() — 消息路由中枢
│   ├── 场景匹配规则注册 + 回调 handler 桥接
│   ├── 管道推进 / watchdog / 超时告警
│   ├── ACK 状态机 / 消息去重 / 速率限制
│   └── 已提取函数的入口（惰性初始化 engine/pipeline_manager 等）
│
├── state.py              # 共享状态容器（模块级全局变量，零业务逻辑）
│
├── scenario_matcher.py   # R126: 声明式规则表（HandlerRule）— _inbox:server 中继路由
│
├── agent_card.py         # Agent Card CRUD + 文件变更监控 + R67 迁移
│
├── workspace.py          # 工作区 CRUD + 状态机 + 管理员审批
│
├── message_store.py      # SQLite 消息持久化（7天 TTL，10 万行上限）
├── task_store.py         # SQLite 任务持久化（R38 任务状态机）
├── audit.py              # JSON Lines 审计日志
│
├── timeout_tracker.py    # 步骤级倒计时（纯内存）
│
├── pipeline_context.py   # PipelineContext 数据模型 + PipelineContextManager + 枚举
├── pipeline_engine.py    # PipelineEngine 状态机（R127 提取 ~2,000 行）
├── pipeline_sync.py      # R65: Git 同步检测器
│
└── commands/
    └── pipeline.py       # 唯一保留的 ! 命令文件（step_complete/verify等管线操作）
```

### 已清理（R134 删除）

| 文件 | 行数 | 原因 |
|---|---|---|
| `auto_router.py` | 750 | 独立外挂 AutoRouter，已禁用多轮 |
| `command_utils.py` | 205 | `!` 命令解析/权限/广播工具 — 命令体系已整体移除 |
| `workspace_api.py` | 37 | HTTP API，重构后无需独立文件 |
| `commands/__init__.py` | 202 | `_ADMIN_COMMANDS` 注册表 — 命令体系移除 |
| `commands/admin.py` | 176 | 管理员 `!` 命令 |
| `commands/agent_card.py` | 258 | Agent Card `!` 命令 |
| `commands/task.py` | 197 | 任务 `!` 命令 |
| `commands/workspace.py` | 455 | 工作区 `!` 命令 |

---

## 二、架构分层

WS 消息从入站到出站穿越 **5 层**：

```
┌────────────────────────────────────────────────────────┐
│  L1 传输层  Transport Layer                            │
│  __main__.py ws_handler()                              │
│  · aiohttp WS 会话生命周期                              │
│  · JSON 解析 + msg_type 一级分发                        │
└──────────────────────┬─────────────────────────────────┘
                       │ msg_type="broadcast"
                       ▼
┌────────────────────────────────────────────────────────┐
│  L2 消息路由层  Routing Layer                           │
│  main.py handle_broadcast()                            │
│  · 速率限制 / 去重 / 静默前缀过滤                        │
│  · 频道解析（lobby / workspace / inbox / _admin）      │
│  · 广播 + ACK + 离线队列                               │
└──────┬───────────────────────┬─────────────────────────┘
       │ _inbox:server 通道     │ 其他通道（lobby/workspace/inbox）
       ▼                       ▼
┌────────────────────┐  ┌──────────────────────────────┐
│ L3 场景匹配层       │  │ L4 管线域 + 命令域            │
│ scenario_matcher   │  │ pipeline_engine.py            │
│ 规则表路由          │  │ ##命令 / 状态机 / 自动派发    │
│ ##query / ##step   │  │ (还有少量 inline 在 main.py) │
│ ##start/stop/...   │  └──────────────┬───────────────┘
└────────┬───────────┘                 │
         │                              ▼
         ▼                    ┌────────────────────┐
  ┌────────────────┐          │ 广播 / 回复 / 派活  │
  │ 回调 handler    │          └────────────────────┘
  │ (在 main.py 底  │
  │ 部注册)         │
  └────────────────┘
```

### 各层详情

| 层 | 文件 | 职责 | 关键函数 |
|---|---|---|---|
| **L1 传输** | `__main__.py` | WS 握手、会话管理、msg_type 一级分发 | `ws_handler()` |
| **L2 路由** | `main.py` | `handle_broadcast()` 消息路由中枢 | 速率限制、去重、频道解析、权限检查、广播 |
| **L3 场景匹配** | `scenario_matcher.py` | `_inbox:server` 中继路由（规则表） | `dispatch()` → 规则链 |
| **L4 管线域** | `pipeline_engine.py` | 管线状态机、`##` 命令处理、自动派发、模板渲染 | `try_advance()`, `auto_dispatch()`, `handle_hash_*()` |
| **L5 数据层** | `message_store.py` / `task_store.py` / `audit.py` | 持久化存储 | SQLite CRUD |

---

## 三、消息路由总览

```
WebSocket 入站 JSON
  │
  ├─ type="auth"          → handle_auth()         → auth_ok + _connections 记录
  ├─ type="register"      → handle_register()     → 生成 api_key + _connections
  │
  ├─ type="message"       → 密钥活性检查 → scenario_matcher.dispatch()
  │                        │
  │                        ├─ 匹配规则 (Priority 10~90):
  │                        │   10 test ✅ 回路测试（loopback）
  │                        │   20 to_agent 派活路由
  │                        │   25 ##query 命令（query / whoami / agents…）
  │                        │   28 ##step 命令
  │                        │   30 ##start/status/stop/advance/archive
  │                        │   35 PM 安全守卫（禁止 PM 发给 _inbox:server）
  │                        │   40 收到 ✅ / ACK ✅ → 转发 PM
  │                        │   50 已完成 ✅ → 转发 PM + 自动推进管线
  │                        │   60 退回 🔄 → 转发 PM + 回退
  │                        │   70 失败 ❌ → 转发 PM + 告警
  │                        │   90 兜底入库（静默留痕）
  │                        │
  │                        └─ 未匹配 → handle_broadcast() L2 路由
  │
  ├─ type="agent_card_register"  → handle_agent_card_register()
  ├─ type="ping"                 → "pong"
  │
  └─ type="admin_request*"       → 行内 WS handler（在 __main__.py）
```

### 广播路由（handle_broadcast 内部）

```
handle_broadcast(ws, sender_id, msg)
  │
  ├─ 1. 惰性启动 watchdog / git sync / timeout scanner / agent card watcher
  │
  ├─ 2. inbox 快速通道（_inbox:*）→ _inbox:server 由 scenario_matcher 处理
  │
  ├─ 3. 未注册 bot → 路由到 registration channel
  │
  ├─ 4. 速率限制 / 去重 / 静音前缀过滤
  │
  ├─ 5. _admin 频道 → 持久化 + 仅 ! 命令模式（实际管线操作已迁到 ## 命令）
  │
  ├─ 6. inbox 通道 → 单播给收件箱主人（_inbox:{owner_id}）
  │
  ├─ 7. 频道解析 → ws_mod.get_workspace(channel)
  │      ├─ 未知频道 → 尝试自动路由到 sender 的唯一活跃工作区
  │      └─ 仍未知 → fallback lobby
  │
  ├─ 8. 权限检查 _can_broadcast()
  │
  ├─ 9. 大厅暂停检查（管线运行时大厅静默）
  │
  ├─ 10. 工作区广播 → 成员 + 管理员（排除发送者）
  │
  ├─ 11. 大厅广播 → 按消息类型（📢/📋/🆘/@）选择性路由
  │       ├─ 📢 → 全员（仅管理员）
  │       ├─ 📋 → 点名目标
  │       ├─ 🆘 → 管理员
  │       ├─ @  → 目标 + 管理员
  │       └─ 纯文本 → 拒绝（大厅需前缀）
  │
  └─ 12. ACK 交付统计 → 发送者 + 离线队列
```

---

## 四、模块关联图

```
                         ┌─────────────┐
                         │  __main__.py │  ← aiohttp 入口
                         └──────┬──────┘
                                │ ws_handler()
                                ▼
┌─────────────────── main.py ─────────────────────┐
│                                                   │
│  handle_auth() / handle_register() / _send()      │
│  handle_broadcast() — 消息路由中枢                 │
│  _send_to_agent() — 单播                          │
│                                                   │
│  规则注册 (底部 ~30 行)                            │
│  _sm_handle_*() 回调                              │
│                                                   │
│  _ensure_engine() → PipelineEngine                │
│  _ensure_pipeline_manager() → PipelineContextMgr  │
│  _ensure_card_watcher() → CardFileWatcher         │
└────┬────┬────┬────┬────┬────┬────┬────┬────┬──────┘
     │    │    │    │    │    │    │    │    │
     ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼
  ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌─────────┐
  │S │ │ag │ │ms│ │ts│ │au│ │ws│ │to│ │pl│ │p.engine │
  │M │ │ent│ │..│ │..│ │d.│ │..│ │..│ │..│ │         │
  │  │ │crd│ │py│ │py│ │py│ │py│ │py│ │py│ │pipeline │
  │  │ │.py│ │  │ │  │ │  │ │  │ │  │ │  │ │_engine  │
  │  │ │   │ │  │ │  │ │  │ │  │ │  │ │  │ │_context │
  │  │ │   │ │  │ │  │ │  │ │  │ │  │ │  │ │_sync    │
  └┬─┘ └┬──┘ └┬─┘ └┬─┘ └┬─┘ └┬─┘ └┬─┘ └┬─┘ └─────────┘
   │    │     │    │    │    │    │    │         │
   │    │     └────┴────┴────┼────┘    │         │
   ▼    ▼                    ▼         ▼         ▼
  ┌─────────────────────────────────────────────┐
  │               state.py                       │
  │  模块级全局变量（_connections / _PIPELINE_*）  │
  │  / _ROLE_AGENT_MAP / _delivery_status / …    │
  └─────────────────────────────────────────────┘
```

**缩写：** SM=scenario_matcher | ms=message_store | ts=task_store | au=audit | ws=workspace | to=timeout_tracker | pl=pipeline_sync

**模块依赖方向：** `main.py` → 所有子模块（通过`_ensure_*()`惰性初始化）。`state.py` 是纯数据层，零反向依赖。

---

## 五、数据层

| 文件 | 存储方式 | 数据 | 文件位置 | 生命周期 |
|---|---|---|---|---|
| `message_store.py` | SQLite (WAL) | `messages.db` — 所有广播消息 | `config.DATA_DIR/messages.db` | 7 天 TTL / 10 万行上限 |
| `task_store.py` | SQLite (WAL) | `tasks.db` — R38 任务状态 | `config.DATA_DIR/tasks.db` | 永久（直到管线归档） |
| `audit.py` | JSON Lines | `_audit_log.jsonl` — 操作审计 | `config.DATA_DIR/_audit_log.jsonl` | 追加写入 |
| `pipeline_context.py` | JSON | `pipeline_contexts.json` — 活跃管线 | `config.DATA_DIR/pipeline_contexts.json` | 内存 + 磁盘同步 |
| `agent_card.py` | JSON | `config/agent_cards.json` — Bot 元数据 | `server/config/agent_cards.json` | 文件变更监控刷新 |
| `workspace.py` | JSON | `workspaces.json` / `admin_requests.json` | `config.DATA_DIR/workspaces.json` | 内存 + 磁盘同步 |

---

## 六、管线领域

```
pipeline_context.py         pipeline_engine.py          pipeline_sync.py
  PipelineContext               PipelineEngine             PipelineGitSync
  PipelineContextManager        生命周期管理                 Git 提交检测
  PipelineStatus                状态推进                    4 种匹配规则
  PipelineTaskKind              ##命令处理                  消息 / 文件 / 作者 / 兜底
  状态机转换矩阵                自动派发 (auto_dispatch)
  序列化/反序列化               模板渲染
                                超时扫描
                                重试队列
```

### 状态机（PipelineStatus）

```
INIT ──→ PLANNING ──→ RUNNING ──→ COMPLETED
  │                    │  │  │
  └──→ CANCELLED       │  │  └──→ STOPPED
                       │  └────→ BLOCKED → RUNNING
                       └───────→ CANCELLED / STOPPED
```

6 步标准管线:

| Step | 角色 | 产出 |
|---|---|---|
| Step 1 | PM | WORK_PLAN 审核 |
| Step 2 | 架构师 (Arch) | 技术方案 |
| Step 3 | 开发 (Dev) | 代码 + 推 dev |
| Step 4 | 审查 (Review) | Code Review |
| Step 5 | 测试 (QA) | 测试报告 |
| Step 6 | 运维 (Ops) | 合 main + 部署 |

---

## 七、命令体系

### `##` 命令（主要入口 — scenario_matcher.py）

R134 之后，所有管线操作统一走 `##` 命令族，由 scenario_matcher 规则表路由：

| 命令 | 处理位置 | 说明 |
|---|---|---|
| `##start##R{N}##k=v` | `main.py` → `_handle_hash_start()` | 创建管线 + 派活 Step 1 |
| `##status##R{N}` | `main.py` → `_handle_hash_status()` | 查询管线状态 |
| `##stop##R{N}` | `main.py` → `_handle_hash_stop()` | 停止管线 |
| `##advance##R{N}##step=N` | `main.py` → `_handle_hash_advance()` | 手动推进（PM 使用） |
| `##archive##R{N}` | `main.py` → `_handle_hash_archive()` | 归档管线（PM 使用） |
| `##query##whoami` | `scenario_matcher.py` | 查看自己信息 (L1+) |
| `##query##agents` | `scenario_matcher.py` | 列出所有 bot (L3+) |
| `##query##status [R{N}]` | `scenario_matcher.py` | 查询管线 (L3+) |
| `##query##agent_info <id>` | `scenario_matcher.py` | 查询 bot 详情 (L3+) |
| `##query##audit` | `scenario_matcher.py` | 审计日志 (L4+) |
| `##step` | `scenario_matcher.py` | 步骤管理 (R132) |

### 自动中继（规则表，无需手动输入）

`_inbox:server` 通道的消息自动匹配以下前缀，触发中继逻辑：

| 前缀 | 规则 | 动作 |
|---|---|---|
| `test ✅` | 10 loopback | 双向通信测试 |
| `收到 ✅` / `ACK ✅` | 40 ACK 转发 | 转发 PM + 标记接活 |
| `已完成 ✅` / `✅ 完成` | 50 完成确认 | 转发 PM + 自动推进管线 |
| `退回 🔄` | 60 退回回退 | 转发 PM + rollback |
| `失败 ❌` | 70 失败告警 | 转发 PM + 告警 |
| 其他未匹配 | 90 入库留痕 | 静默持久化 |

### `!` 命令（R134 已移除）

R134 之前，`!` 命令通过 `command_utils._parse_command()` + `commands.__init__._ADMIN_COMMANDS` 注册表路由。
R134 清理了这 40+ 个 `!` 命令和全部 5 个命令域文件。仅保留 `commands/pipeline.py` 中的
`step_complete` / `step_verify` / `step_force` 等工序操作（仍可通过 `_admin` 频道直接调用）。

---

## 八、`main.py` 重构清单

`main.py` 目前 3,706 行，是 ws_server 的内聚度瓶颈。R134 已清理 ~1,245 行
（移除 `!` 命令路由、`_handle_server_query`、工作区 handlers、`_broadcast_task_notify`等）。
以下是后续推荐提取方案：

### 优先级 1 — 纯提取（零语义改动，可安全合并）

| 提取目标 | 行范围（估值） | 目标文件 | 原因 |
|---|---|---|---|
| 连接管理 | L37-L210 | `connection_manager.py` | `_connections`/`_send`/`handle_auth`/`handle_register` |
| 离线队列推送 | L386-L421 | `offline_queue.py` | `_push_offline`/`_flush_offline_push` |
| 看门狗 | L865-L942 | `watchdog.py` | R43 看门狗循环 + 告警 |
| 管道超时扫描 | L615-L740 | (已有 pipeline_engine.py) | R122/R124 超时扫描逻辑 |
| ACK 状态机 | L1009-L1198 | `ack_machine.py` | R63 Phase 4 ACK 检测 |
| Git 同步生命周期 | L569-L613 | `git_sync_lifecycle.py` | 与 pipeline_sync.py 分离的调度层 |

### 优先级 2 — 行为拆分（需设计接口）

| 提取目标 | 行范围（估值） | 目标文件 | 原因 |
|---|---|---|---|
| 管线手动推进 (`_handle_hash_*`) | L2966-L3410 | (已有 pipeline_engine.py) | `_handle_hash_start/stop/advance/archive/status` 可迁入 engine |
| 消息过滤 | L1982-L2014 | `message_filter.py` | `_is_nonsense`/`_is_duplicate` |
| `_can_broadcast` | L2079-L2108 | `permission.py` | 广播权限检查独立 |

### 优先级 3 — 重构设计

- **`_connections` → connection pool class**：当前是 `dict[str, set[ws]]`，缺并发安全、缺连接元数据
- **`handle_broadcast` 分拆**：按消息通道拆为独立函数 — `_handle_workspace_broadcast`, `_handle_lobby_broadcast`, `_handle_inbox_broadcast`
- **规则注册回调统一**：底部 ~280 行的 `_sm_handle_*()` + 规则注册可统一到一个注册表文件中
- **`_send_to_agent` → 统一网关**：现多处有 `send_str`/`send` 二选一模式（至少 15 处重复），应提取到单播网关

---

## 九、启动流程

```
__main__.py 启动
  │
  ├─ 1. 加载配置（server.common.config）
  ├─ 2. 初始化 SQLite DB（message_store.init_db / task_store.init_db）
  ├─ 3. 加载持久化数据（workspace._load / auth.load / persistence.load）
  ├─ 4. 创建 aiohttp Application
  │      ├─ /ws          → ws_handler()          — WebSocket 端点
  │      ├─ /api/status  → bot 在线状态           — 读取 _connections
  │      └─ /api/health  → 健康检查               — 返回 {"ok": true}
  ├─ 5. 注册 scenario_matcher 规则（_sm.register_rule × 9）
  ├─ 6. 首次消息触发惰性启动
  │      ├─ _ensure_watchdog()              — R43 watchdog 循环
  │      ├─ _ensure_engine()._ensure_git_scan()  — R65 git sync
  │      ├─ _ensure_engine()._ensure_timeout_scanner() — R122 超时扫描
  │      ├─ _ensure_agent_cards_loaded()    — 加载 Agent Card
  │      ├─ _ensure_card_watcher()          — 卡片热更新
  │      └─ _restore_pipeline_dispatches()  — R119 恢复派活
  │
  └─ 7. 进入 asyncio 事件循环
```
