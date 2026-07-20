# ws_server — WSS 核心进程

> WSS 进程是 ws-bridge 的 WebSocket 服务核心。**共 18 个源文件（含 commands/），~9,000 行。**
>
> `main.py` 占 4,951 行，是该包最大的文件，也是后续重构的主要目标。

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
├── main.py               # 【核心路由器】— 4,951 行，需重构
│   ├── WebSocket 连接管理（_connections / auth / register）
│   ├── handle_broadcast() — 消息路由中枢
│   ├── _handle_server_query() — _inbox:server 查询路由
│   ├── 场景匹配规则注册 + 回调 handler 桥接
│   ├── 管道推进 / watchdog / 超时告警
│   ├── ACK 状态机 / 消息去重 / 速率限制
│   └── 已提取函数的入口（惰性初始化 engine/pipeline_manager 等）
│
├── state.py              # 共享状态容器（模块级全局变量，零业务逻辑）
│
├── scenario_matcher.py   # R126: 声明式规则表（HandlerRule）— _inbox:server 中继路由
│
├── command_utils.py      # !命令解析、权限检查、频道广播、审计日志工具
│
├── agent_card.py         # Agent Card CRUD + 文件变更监控 + R67 迁移
│
├── workspace.py           # 工作区 CRUD + 状态机 + 管理员审批
├── workspace_api.py       # 工作区 HTTP API（/api/workspaces）
│
├── message_store.py       # SQLite 消息持久化（7天 TTL，10 万行上限）
├── task_store.py          # SQLite 任务持久化（R38 任务状态机）
├── audit.py               # JSON Lines 审计日志
│
├── timeout_tracker.py     # 步骤级倒计时（纯内存）
│
├── pipeline_context.py    # PipelineContext 数据模型 + PipelineContextManager + 枚举
├── pipeline_engine.py     # PipelineEngine 状态机（R127 提取 ~2,000 行）
├── pipeline_sync.py       # R65: Git 同步检测器
│
├── auto_router.py         # 【已禁用】独立外挂 AutoRouter
│
└── commands/              # !命令处理器目录
    ├── __init__.py        # _ADMIN_COMMANDS 注册表
    ├── admin.py           # 管理员命令（list_agents / agent_status / audit_log…）
    ├── pipeline.py        # 管线命令（start / stop / status / handoff…）
    ├── task.py            # 任务命令（create / update / query / rollcall…）
    ├── workspace.py       # 工作区命令（create / close / join / list…）
    └── agent_card.py      # Agent Card 命令（list / get / set / register…）
```

---

## 二、架构分层

WS 消息从入站到出站穿越 **6 层**：

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
│  · 权限检查                                            │
│  · 频道解析（lobby / workspace / inbox / _admin）      │
│  · 广播 + ACK + 离线队列                               │
└──────┬───────────────────────┬─────────────────────────┘
       │ _inbox:server 通道     │ 其他通道（lobby/workspace/inbox）
       ▼                       ▼
┌────────────────────┐  ┌────────────────────────────────┐
│ L3 场景匹配层       │  │ L4 命令域 / L5 管线域          │
│ scenario_matcher   │  │ commands/ / pipeline_engine.py │
│ 规则表路由          │  │ !命令 / ##命令 / 管线推进       │
└────────┬───────────┘  └──────────────┬─────────────────┘
         │ 匹配规则                     │
         ▼                             ▼
  ┌────────────────┐          ┌────────────────────┐
  │ 回调 handler    │          │ 广播 / 回复 / 派活  │
  │ (在 main.py 底  │          └────────────────────┘
  │ 部注册)         │
  └────────────────┘
```

### 各层详情

| 层 | 文件 | 职责 | 关键函数 |
|---|---|---|---|
| **L1 传输** | `__main__.py` | WS 握手、会话管理、msg_type 一级分发 | `ws_handler()` |
| **L2 路由** | `main.py` | `handle_broadcast()` 消息路由中枢 | 速率限制、去重、频道解析、权限检查、广播 |
| **L3 场景匹配** | `scenario_matcher.py` | `_inbox:server` 中继路由（规则表） | `dispatch()` → 规则链 |
| **L4 命令域** | `commands/` | `!命令` 处理器 | `_ADMIN_COMMANDS` 注册表 |
| **L5 管线域** | `pipeline_engine.py` | 管线状态机、自动派发、模板渲染 | `try_advance()`, `auto_dispatch()` |
| **L6 数据层** | `message_store.py` / `task_store.py` / `audit.py` | 持久化存储 | SQLite CRUD |

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
  │                        │   50 已完成 ✅ → 转发 PM + 自动推进
  │                        │   60 退回 🔄 → 转发 PM + 回退
  │                        │   70 失败 ❌ → 转发 PM + 告警
  │                        │   80 ! 命令 → 透传 L2 正常路由
  │                        │   90 兜底入库（静默留痕）
  │                        │
  │                        └─ 未匹配 → handle_broadcast() L2 路由
  │
  ├─ type="agent_card_register"  → handle_agent_card_register()
  │
  ├─ type="workspace_*"          → 行内 WS handler（还在 __main__.py）
  │
  ├─ type="ping"                 → "pong"
  │
  └─ type="admin_request*"       → 行内 WS handler（还在 __main__.py）
```

### 广播路由（handle_broadcast 内部）

```
handle_broadcast(ws, sender_id, msg)
  │
  ├─ 1. 惰性启动 watchdog / git sync / timeout scanner / agent card watcher
  │
  ├─ 2. inbox 快速通道（_inbox:hoge）→ 单播给目标 agent
  │
  ├─ 3. 未注册 bot → 路由到 registration channel
  │
  ├─ 4. 速率限制 / 去重 / 静音前缀过滤
  │
  ├─ 5. ! 命令 → 解析 → 权限检查 → 执行 handler → 响应
  │
  ├─ 6. _admin 频道 → 持久化 + 仅 ! 命令模式
  │
  ├─ 7. inbox 通道 → 单播给收件箱主人（_inbox:{owner_id}）
  │
  ├─ 8. 频道解析 → ws_mod.get_workspace(channel)
  │      ├─ 未知频道 → 尝试自动路由到 sender 的唯一活跃工作区
  │      └─ 仍未知 → fallback lobby
  │
  ├─ 9. 权限检查 _can_broadcast()
  │
  ├─ 10. 大厅暂停检查（管线运行时大厅静默）
  │
  ├─ 11. 工作区广播 → 成员 + 管理员（排除发送者）
  │
  ├─ 12. 大厅广播 → 按消息类型（📢/📋/🆘/@）选择性路由
  │       ├─ 📢 → 全员（仅管理员）
  │       ├─ 📋 → 点名目标
  │       ├─ 🆘 → 管理员
  │       ├─ @  → 目标 + 管理员
  │       └─ 纯文本 → 拒绝（大厅需前缀）
  │
  └─ 13. ACK 交付统计 → 发送者 + 离线队列
```

---

## 四、模块关联图

```
                         ┌─────────────┐
                         │  __main__.py │  ← aiohttp 入口
                         └──────┬──────┘
                                │ ws_handler()
                                ▼
┌────────────────────── main.py ──────────────────────┐
│                                                      │
│  handle_auth() / handle_register() / _send_to_agent()│
│  handle_broadcast() — 消息路由中枢                    │
│  _handle_server_query() — _inbox:server 查询          │
│                                                      │
│  规则注册 (底部 30 行)                                 │
│  _sm_handle_*() 回调                                 │
│                                                      │
│  _ensure_engine() → PipelineEngine                   │
│  _ensure_pipeline_manager() → PipelineContextManager │
│  _ensure_card_watcher() → CardFileWatcher            │
└────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬───┘
     │    │    │    │    │    │    │    │    │    │
     ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼
  ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌────┐
  │S │ │C │ │st│ │ag │ │cm│ │ws│ │ms│ │ts│ │au│ │p.e │
  │M │ │om│ │at│ │ent│ │d.│ │..│ │..│ │..│ │d.│ │ng..│
  │  │ │..│ │e │ │crd│ │ut│ │py│ │py│ │py│ │py│ │.py │
  │  │ │ut│ │py│ │.py│ │il│ │  │ │  │ │  │ │  │ │  │
  │  │ │il│ │  │ │   │ │s.│ │  │ │  │ │  │ │  │ │  │
  │  │ │s.│ │  │ │   │ │py│ │  │ │  │ │  │ │  │ │  │
  └┬─┘ └┬─┘ └┬─┘ └┬──┘ └┬─┘ └┬─┘ └┬─┘ └┬─┘ └┬─┘ └┬──┘
   │    │    │    │     │    │    │    │    │    │
   │    │    │    │     │    │    │    │    │    └── pipeline_engine.py
   │    │    │    │     │    │    │    │    │       (依赖 pipeline_context.py,
   │    │    │    │     │    │    │    │    │        pipeline_sync.py, 回调)
   │    │    │    │     │    │    │    │    │
   │    │    │    │     │    └────┼────┘    │
   ▼    ▼    ▼    ▼     ▼         ▼         ▼
  ┌─────────────────────────────────────────────┐
  │               state.py                       │
  │  模块级全局变量（_connections / _PIPELINE_*）  │
  │  / _ROLE_AGENT_MAP / _delivery_status / …    │
  └─────────────────────────────────────────────┘
```

**模块依赖方向：** `main.py` → 所有子模块（通过`_ensure_*()`惰性初始化）。`state.py` 是纯数据层，零反向依赖。

---

## 五、数据层

| 文件 | 存储方式 | 数据 | 文件位置 | 生命周期 |
|---|---|---|---|---|
| `message_store.py` | SQLite (WAL) | `messages.db` — 所有广播消息 | `config.DATA_DIR/messages.db` | 7 天 TTL / 10 万行上限 |
| `task_store.py` | SQLite (WAL) | `tasks.db` — R38 任务状态 | `config.DATA_DIR/tasks.db` | 永久（直到管线归档） |
| `audit.py` | JSON Lines | `_audit_log.jsonl` — !命令审计 | `config.DATA_DIR/_audit_log.jsonl` | 追加写入 |
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
  PipelineTaskKind              自动派发                    消息 / 文件 / 作者 / 兜底
  状态机转换矩阵                 ##命令处理
  序列化/反序列化               模板渲染
                                超时扫描
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

### `!` 命令（commands/ 注册表）

- 由 `command_utils._parse_command()` 解析
- 所有 `!<cmd>` 由 `handle_broadcast()` 内透传到 `commands.__init__._ADMIN_COMMANDS` 注册表
- 权限分级 L1~L4
- 审计日志自动写入

**当前 5 个命令域:**

| 命令目录 | 文件 | 命令数 | 示例 |
|---|---|---|---|
| 管理员 | `commands/admin.py` | 7 | `!list_agents`, `!audit_log`, `!revoke_api_key` |
| 管线 | `commands/pipeline.py` | ~12 | `!pipeline_start`, `!step_complete`, `!pipeline_mode` |
| 工作区 | `commands/workspace.py` | ~8 | `!create_workspace`, `!workspace_reset` |
| 任务 | `commands/task.py` | ~6 | `!task_create`, `!rollcall_role` |
| Agent Card | `commands/agent_card.py` | ~8 | `!agent_card list`, `!agent_card set` |

### `##` 命令（scenario_matcher.py）

- `##start##R{N}##k=v` — 创建管线 + 派活 Step 1
- `##status##R{N}` — 查询管线状态
- `##stop##R{N}` — 停止管线
- `##advance##R{N}##step=N` — 手动推进
- `##query##whoami` / `##query##agents` — 查询命令 (L1~L4)

---

## 八、`main.py` 重构清单

`main.py` 目前 4,951 行，是 ws_server 的内聚度瓶颈。以下是推荐提取方案：

### 优先级 1 — 纯提取（零语义改动，可安全合并）

| 提取目标 | 行范围（估算） | 目标文件 | 原因 |
|---|---|---|---|
| 连接管理 | L37-L88 | `connection_manager.py` | `_connections`/`_send`/`handle_auth`/`handle_register` |
| 离线队列推送 | L331-L366 | `offline_queue.py` | `_push_offline`/`_flush_offline_push` |
| 广播 ACK 状态 | L77-L78, L1787-L1800 | `delivery_tracker.py` | `_delivery_status`/ACK 交付统计 |
| 管道超时扫描 | L558-L685 | `pipeline_timeout.py` | R122/R124 超时扫描逻辑 |
| 看门狗 | L810-L946 | `watchdog.py` | R43 看门狗循环 + 告警 |
| ACK 状态机 | L949-L1129 | `ack_machine.py` | R63 Phase 4 ACK 检测 |
| Git 同步生命周期 | L511-L556 | `git_sync_lifecycle.py` | 与 pipeline_sync.py 分离的调度层 |

### 优先级 2 — 行为拆分（需设计接口）

| 提取目标 | 行范围（估算） | 目标文件 | 原因 |
|---|---|---|---|
| `_handle_server_query` | L2082-L2170 | `server_query_handler.py` | 近 100 行行内 if/elif 链 |
| 工作区 admin request handlers | __main__.py L228-L451 | `workspace_admin_handler.py` | 四个重复的 admin_request 处理 |
| 管道手动推进 | L687-L807 | (已有 pipeline_engine.py) | `_auto_advance` 已搬移，其余补充 |
| 消息过滤（去重/静音） | L1546-L1556 | `message_filter.py` | `_is_nonsense`/`_is_duplicate` |

### 优先 3 — 重构设计

- **`_connections` → connection pool class**：当前是 `dict[str, set[ws]]`，缺并发安全、缺连接元数据
- **`handle_broadcast` 分拆**：按消息通道拆分为独立函数 — `_handle_workspace_broadcast`, `_handle_lobby_broadcast`, `_handle_inbox_broadcast`
- **规则注册回调统一**：底部 300 行的 `_sm_handle_*()` + 规则注册可统一到一个注册表文件中

---

## 九、启动流程

```
__main__.py 启动
  │
  ├─ 1. 加载配置（server.common.config）
  ├─ 2. 初始化 SQLite DB（message_store.init_db / task_store.init_db）
  ├─ 3. 加载持久化数据（workspace.init / auth.load / persistence.load）
  ├─ 4. 创建 aiohttp Application
  │      ├─ /ws          → ws_handler()          — WebSocket 端点
  │      ├─ /api/status  → bot 在线状态           — 读取 _connections
  │      ├─ /api/health  → 健康检查               — 返回 {"ok": true}
  │      └─ /api/workspaces → workspace_api       — 工作区列表
  ├─ 5. 注册 scenario_matcher 规则（_sm.register_rule × 10）
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
