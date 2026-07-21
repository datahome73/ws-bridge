# ws_server — WSS 核心进程

> **端口 8765** | WSS 核心进程是 ws-bridge 的 WebSocket 服务核心。
> **共 21 个源文件（含 commands/ 及 README），约 8,700 行。**
>
> 历经多轮重构：R134+R135 清理了 8 个废止文件和 ~1,800 行死代码；
> R136 提取 5 个独立模块；R137 拆分 engine2；R138 合并回 pipeline_engine；
> R139 提取 scenario_rules；R140 修复 ##advance 权限/跨步推进/失败通知。
> **`main.py` 从峰值 ~6,400 行 → 559 行。**

---

## 目录

- [一、模块清单](#一模块清单)
- [二、架构分层](#二架构分层)
- [三、消息路由总览](#三消息路由总览)
- [四、模块关联图](#四模块关联图)
- [五、数据层](#五数据层)
- [六、管线领域](#六管线领域)
- [七、命令体系](#七命令体系)
- [八、启动流程](#八启动流程)
- [九、`main.py` 重构进度](#九mainpy-重构进度)

---

## 一、模块清单

```
ws_server/                                      行数  说明
├── __init__.py                                    1  包声明
├── __main__.py                                  415  aiohttp 入口 + HTTP API 端点
├── main.py                                      559  消息路由 + 惰性启动 + 规则注册
│
├── connection_manager.py                        302  连接生命周期（auth/register/_send/单播）
├── ack_machine.py                               241  ACK 状态机（30秒超时/通道超时）
├── watchdog.py                                  308  看门狗循环 + 超时告警
├── pipeline_timeout.py                          148  管线超时扫描（R122）
├── git_sync_scheduler.py                         65  Git 同步调度循环
│
├── scenario_matcher.py                          780  声明式规则表（_inbox:server 中继路由）
├── scenario_rules.py                            301  规则回调 handler（R139 提取）
├── pipeline_engine.py                         2,305  管线状态机 + 自动派发 + ## 命令
├── pipeline_context.py                          692  PipelineContext + PipelineContextManager
├── pipeline_sync.py                             203  Git 提交检测器
│
├── agent_card.py                                429  Agent Card CRUD + 文件监控
├── workspace.py                                  63  工作区（精简后仅剩数据模型）
│
├── state.py                                      68  共享状态容器（全局变量，零业务逻辑）
├── message_store.py                             172  SQLite 消息持久化
├── task_store.py                                 184  SQLite 任务持久化
├── audit.py                                      94  JSON Lines 审计日志
├── timeout_tracker.py                           164  步骤级倒计时
│
├── commands/
│   └── pipeline.py                            1,201  ! 命令（step_complete/verify/force）
│
└── README.md                                     —  本文档
│
└── README.md                                     —  本文档
```

### 已清理历史

| 轮次 | 删除文件 | 行数 | 说明 |
|:----:|:---------|:----:|:------|
| R134 | `auto_router.py` | 750 | 独立外挂 AutoRouter |
| R134 | `command_utils.py` | 205 | `!` 命令解析工具 |
| R134 | `workspace_api.py` | 37 | HTTP API |
| R134 | `commands/__init__.py` | 202 | `_ADMIN_COMMANDS` 注册表 |
| R134 | `commands/admin.py` | 176 | 管理员 `!` 命令 |
| R134 | `commands/agent_card.py` | 258 | Agent Card `!` 命令 |
| R134 | `commands/task.py` | 197 | 任务 `!` 命令 |
| R134 | `commands/workspace.py` | 455 | 工作区 `!` 命令 |
| R135 | `handle_broadcast` 死代码 | ~600 | 大厅/registration/_admin/广播/离线队列/过滤 |

### R136 提取记录

| 目标文件 | 来源 (main.py) | 行数 |
|:---------|:---------------|:----:|
| `connection_manager.py` | auth/register/`_send`/`_send_to_agent` | ~200 |
| `ack_machine.py` | ACK 超时检测 + 状态格式化 | ~50 |
| `watchdog.py` | 看门狗循环 + 告警 + escalation | ~300 |
| `pipeline_timeout.py` | 超时扫描定时器 | ~60 |
| `git_sync_scheduler.py` | Git 同步调度层 | ~30 |

### R137 引擎分拆

| 目标文件 | 来源 (main.py) | 说明 |
|:---------|:---------------|:------|
| `engine2.py` | `##` 命令 / 自动派发 / 模板渲染 | 临时分拆（~885 行），R138 合并回 pipeline_engine |

### R139 提取记录

| 目标文件 | 来源 (scenario_matcher.py) | 行数  |
|:---------|:---------------------------|:-----:|
| `scenario_rules.py` | `_sm_handle_*()` 回调 + `register_all_rules()` | ~300 |

---

## 二、架构分层

```
┌────────────────────────────────────────────────────────┐
│  L1 传输层  Transport Layer                            │
│  __main__.py ws_handler()                              │
│  · aiohttp WS 会话生命周期                              │
│  · JSON 解析 + msg_type 一级分发                        │
└──────────────────────┬─────────────────────────────────┘
                       │ msg_type="message"
                       ▼
┌────────────────────────────────────────────────────────┐
│  L2 消息路由层  Routing Layer                           │
│  main.py handle_broadcast()  (~78 行)                  │
│  · 惰性启动 (watchdog / git / timeout / agent cards)   │
│  · _inbox:server → scenario_matcher.dispatch()         │
│  · _inbox:{agent_id} → 单播给收件箱主人 + ACK          │
└──────────────┬─────────────────────────────────────────┘
               │ _inbox:server 通道
               ▼
┌────────────────────────────────────────────────────────┐
│  L3 场景匹配层  Scenario Matching                      │
│  scenario_matcher.py dispatch()                        │
│  · 规则表: loopback → to_agent → ##query → ##step →   │
│    ##cmd → ACK → complete → reject → fail            │
│  · 未匹配 → handle_broadcast() L2 路由                │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│  L4 管线域  Pipeline Domain                            │
│  pipeline_engine.py  (管线引擎 + ## 命令)              │
│  pipeline_context.py  (数据模型 + 管理器)              │
│  pipeline_sync.py     (Git 提交检测)                   │
│  watchdog.py          (超时看门狗 + 告警)              │
│  pipeline_timeout.py  (R122 超时扫描)                  │
│  git_sync_scheduler.py(同步调度循环)                   │
│  ack_machine.py       (ACK 状态机)                    │
│  timeout_tracker.py   (步骤倒计时)                    │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│  L5 数据层  Data Layer                                 │
│  message_store.py / task_store.py / audit.py           │
│  agent_card.py (JSON) / workspace.py (JSON)            │
│  pipeline_context.py (JSON -> pipeline_contexts.json)  │
└────────────────────────────────────────────────────────┘
```

### 各层详情

| 层 | 文件 | 职责 | 关键函数 |
|---|---|---|---|
| **L1 传输** | `__main__.py` | WS 握手、会话管理、msg_type 一级分发 | `ws_handler()` |
| **L2 路由** | `main.py` | `handle_broadcast()` — 惰性启动 + inbox 单播 | 仅 ~78 行 |
| **L3 场景匹配** | `scenario_matcher.py` | `_inbox:server` 中继（规则表） | `dispatch()` |
| **L4 管线域** | `pipeline_engine.py` + 6 个子模块 | 状态机、自动派发、超时、看门狗、ACK 跟踪 | `try_advance()`, `auto_dispatch()` |
| **L5 数据层** | `message_store.py` / `task_store.py` / `audit.py` | SQLite + JSON 持久化 | CRUD |

---

## 三、消息路由总览

```
WebSocket 入站 JSON
  │
  ├─ type="auth"          → connection_manager.handle_auth()
  ├─ type="register"      → connection_manager.handle_register()
  │
  ├─ type="message"       → scenario_matcher.dispatch()
  │                        │
  │                        ├─ 匹配规则 (Priority 10~90):
  │                        │   10 test ✅ 回路测试
  │                        │   20 to_agent 派活路由
  │                        │   25 ##query 命令
  │                        │   28 ##step 命令
  │                        │   30 ##start/status/stop/advance/archive
  │                        │   40 收到 ✅ / ACK ✅ → 转发协调者
  │                        │   50 已完成 ✅ → 转发协调者 + try_advance
  │                        │   60 退回 🔄 → 转发协调者 + rollback
  │                        │   70 失败 ❌ → 转发协调者 + 告警
  │                        │   90 兜底入库（静默留痕）
  │                        │
  │                        └─ 未匹配 → handle_broadcast()
  │
  ├─ type="agent_card_register"  → handle_agent_card_register()
  └─ type="ping"                 → "pong"
```

### 关键说明

- **`_inbox:server`** — 所有消息直接交 scenario_matcher 规则表处理，不经过 handle_broadcast
- **`_inbox:{agent_id}`** — 由 handle_broadcast 单播给收件箱主人（防自刷 + ACK）
- **其他频道已全部废止** — LOBBY、REGISTRATION、_admin、WORKSPACE 均不再存在。`handle_broadcast` 仅约 78 行。

---

## 四、模块关联图

```
                         ┌─────────────┐
                         │  __main__.py │  ← aiohttp 入口
                         └──────┬──────┘
                                │ ws_handler()
                                ▼
┌─────────────────── main.py ──────────────────────┐
│                                                    │
│  handle_broadcast() — inbox 投递器 (~78 行)       │
│  _try_advance_pipeline() — 管线推进                │
│  _handle_hash_start/stop/status/advance/archive   │
│                                                    │
│  规则注册 (底部 ~200 行)                           │
│  _sm_handle_*() 回调                              │
│                                                    │
│  import: connection_manager / ack_machine          │
│          watchdog / pipeline_timeout               │
│          git_sync_scheduler                        │
└─────┬──────┬──────┬──────┬──────┬──────┬────┬─────┘
      │      │      │      │      │      │    │
      ▼      ▼      ▼      ▼      ▼      ▼    ▼
  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌───────┐
  │conn│ │ack │ │wdog│ │ptim│ │gits│ │ SM │ │p.eng  │
  │mgr │ │mach│ │.py │ │eout│ │ync │ │.py │ │       │
  │.py │ │.py │ │    │ │.py │ │.py │ │    │ │pipelin│
  └─┬──┘ └─┬──┘ └─┬──┘ └─┬──┘ └─┬──┘ └─┬──┘ │_ctx   │
    │      │      │      │      │      │    │_sync   │
    │      │      │      │      │      │    │_timeout│
    ▼      ▼      ▼      ▼      ▼      ▼    └───────┘
  ┌─────────────────────────────────────────────┐
  │               state.py                       │
  │  模块级全局变量（_connections / _PIPELINE_*）  │
  │  / _ROLE_AGENT_MAP / 常量                    │
  └─────────────────────────────────────────────┘
```

**缩写：** connmgr=connection_manager | ack=ack_machine | wdog=watchdog | ptimeout=pipeline_timeout | gitsync=git_sync_scheduler | SM=scenario_matcher

---

## 五、数据层

| 文件 | 存储方式 | 数据 | 文件位置 | 生命周期 |
|---|---|---|---|---|
| `message_store.py` | SQLite (WAL) | `messages.db` — 所有广播消息 | `config.DATA_DIR/messages.db` | 7 天 TTL / 10 万行上限 |
| `task_store.py` | SQLite (WAL) | `tasks.db` — R38 任务状态 | `config.DATA_DIR/tasks.db` | 永久（直到管线归档） |
| `audit.py` | JSON Lines | `_audit_log.jsonl` — 操作审计 | `config.DATA_DIR/_audit_log.jsonl` | 追加写入 |
| `pipeline_context.py` | JSON | `pipeline_contexts.json` — 活跃管线 | `config.DATA_DIR/pipeline_contexts.json` | 内存 + 磁盘同步 |
| `agent_card.py` | JSON | `config/agent_cards.json` — Bot 元数据 | `server/config/agent_cards.json` | 文件变更监控刷新 |
| `workspace.py` | JSON | `workspaces.json` — 工作区存活状态 | `config.DATA_DIR/workspaces.json` | 仅 get_workspace 使用 |

---

## 六、管线领域

### 管线引擎架构

```
  ┌──────────────────────────────────────────────────┐
  │               PipelineEngine                     │
  │  p.s.py ─── pipeline_engine.py ──── p.c.py      │
  │  GitSync    状态机 + ## 命令     PipelineContext │
  │             自动派发 + 推进      PipelineContext │
  │             模板渲染 + 重试       Manager        │
  ├──────────────────────────────────────────────────┤
  │  配套模块:                                        │
  │  watchdog.py         — 看门狗超时告警            │
  │  pipeline_timeout.py — R122 步骤超时扫描         │
  │  git_sync_scheduler.py — 调度同步循环             │
  │  ack_machine.py      — ACK 30秒超时检测          │
  │  timeout_tracker.py  — 步骤倒计时                │
  └──────────────────────────────────────────────────┘
```

### 状态机（PipelineStatus）

```
INIT ──→ PLANNING ──→ RUNNING ──→ COMPLETED
  │                    │  │  │
  └──→ CANCELLED       │  │  └──→ STOPPED
                       │  └────→ BLOCKED → RUNNING
                       └───────→ CANCELLED / STOPPED
```

### 6 步标准管线

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

### `##` 命令

| 命令 | 处理位置 | 说明 |
|---|---|---|
| `##start##R{N}##k=v` | `pipeline_engine.handle_hash_start()` | 创建管线 + 填充 ctx.steps + 派活 Step 1 |
| `##status##R{N}` | `pipeline_engine.handle_hash_status()` | 查询管线状态 |
| `##stop##R{N}` | `pipeline_engine.handle_hash_stop()` | 停止管线 |
| `##advance##R{N}##step=N` | `pipeline_engine.handle_hash_advance()` | 手动推进 |
| `##archive##R{N}` | `pipeline_engine.handle_hash_archive()` | 归档管线 |
| `##query##whoami` | `scenario_matcher` | 查看自己信息 (L1+) |
| `##query##agents` | `scenario_matcher` | 列出所有 bot (L3+) |
| `##query##status [R{N}]` | `scenario_matcher` | 查询管线 (L3+) |
| `##query##agent_info <id>` | `scenario_matcher` | 查询 bot 详情 (L3+) |
| `##query##audit` | `scenario_matcher` | 审计日志 (L4+) |
| `##step` | `scenario_matcher` | 步骤管理 (R132) |

### 规则表中继

| 前缀 | 规则 | 动作 |
|---|---|---|
| `test ✅` | 10 loopback | 双向通信测试 |
| `收到 ✅` / `ACK ✅` | 40 ACK 转发 | 转发协调者 + 标记接活 |
| `已完成 ✅` / `✅ 完成` | 50 完成确认 | 转发协调者 + try_advance |
| `退回 🔄` | 60 退回回退 | 转发协调者 + rollback |
| `失败 ❌` | 70 失败告警 | 转发协调者 + 告警 |
| 其他 | 90 入库留痕 | 静默持久化 |

### `!` 命令

仅 `commands/pipeline.py` 保留 `step_complete` / `step_verify` / `step_force` 等工序操作。

---

## 八、启动流程

```
__main__.py 启动
  │
  ├─ 1. 加载配置（server.common.config）
  ├─ 2. 初始化 SQLite DB（message_store.init_db / task_store.init_db）
  ├─ 3. 加载持久化数据（auth.load / persistence.load）
  ├─ 4. 创建 aiohttp Application
  │      ├─ /ws          → ws_handler()
  │      └─ /api/status  → bot 在线状态（connection_manager.get_connections）
  ├─ 5. 注册 scenario_matcher 规则（_sm.register_rule × 9）
  ├─ 6. 首次消息触发惰性启动
  │      ├─ _ensure_watchdog()                  — watchdog.py
  │      ├─ _ensure_git_scan()                  — git_sync_scheduler.py
  │      ├─ _ensure_timeout_scanner()           — pipeline_timeout.py
  │      ├─ _ensure_agent_cards_loaded()        — agent_card.py
  │      ├─ _ensure_card_watcher()              — agent_card.py
  │      └─ _restore_pipeline_dispatches()      — main.py
  │
  └─ 7. 进入 asyncio 事件循环
```

---

## 九、`main.py` 重构进度

| 阶段 | 状态 | 说明 |
|:----:|:----:|:------|
| R134 删除 `!` 命令路由 + workspace handlers | ✅ 完成 | -1,245 行 |
| R135 删除 handle_broadcast 死代码（大厅/广播/过滤/离线队列）| ✅ 完成 | -600 行 |
| R136 提取 5 模块（connection_manager/ack/watchdog/timeout/git） | ✅ 完成 | -895 行 |
| R137 引擎分拆（engine2.py → ##命令/自动派发/模板渲染） | ✅ 完成 | -885 行，临时分拆 |
| R138 引擎合并（engine2→pipeline_engine 合并为一套） | ✅ 完成 | +885 行回 pipeline_engine |
| R139 规则回调提取（scenario_rules.py） | ✅ 完成 | -300 行 |
| R140 管线核心路径修复（##advance 权限/跨步推进/失败通知） | ✅ 完成 | 逻辑修正，无损行数 |
