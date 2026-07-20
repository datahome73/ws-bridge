# ws_server — WSS 核心进程

> WSS 进程是 ws-bridge 的 WebSocket 服务核心。**共 15 个源文件，约 5,000 行。**
>
> `main.py` 占 3,706 行，是该包最大的文件，也是后续重构的主要目标。
>
> R134 已清理 8 个废止文件。R135 将继续清理 `handle_broadcast` 中的死代码，
> 包括 `_admin` 频道、大厅前缀路由、工作区相关逻辑。

---

## 目录

- [一、包结构与模块职责](#一包结构与模块职责)
- [二、架构分层](#二架构分层)
- [三、消息路由总览](#三消息路由总览)
- [四、广播路由分析（`handle_broadcast`）](#四广播路由分析handle_broadcast)
- [五、模块关联图](#五模块关联图)
- [六、数据层](#六数据层)
- [七、管线领域](#七管线领域)
- [八、命令体系](#八命令体系)
- [九、`main.py` 重构清单](#九mainpy-重构清单)
- [十、启动流程](#十启动流程)

---

## 一、包结构与模块职责

```
ws_server/
├── __init__.py           # 包声明（一行）
├── __main__.py           # aiohttp 入口：WebSocket 会话生命周期 + HTTP API 端点
│
├── main.py               # 【核心路由器】— 3,706 行，需重构
│   ├── WebSocket 连接管理（_connections / auth / register）
│   ├── handle_broadcast() — 消息路由中枢（含大量死代码需清理）
│   ├── 场景匹配规则注册 + 回调 handler 桥接
│   ├── ## 命令处理（start/stop/status/advance/archive）
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
├── workspace.py          # 工作区 CRUD + 状态机 + 管理员审批（R135 后将精简）
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
                       │ msg_type="message"
                       ▼
┌────────────────────────────────────────────────────────┐
│  L2 消息路由层  Routing Layer                           │
│  main.py handle_broadcast()                            │
│  · 惰性启动 (watchdog/git/agent cards)                  │
│  · _inbox:server 快速返回（交 scenario_matcher 处理）  │
│  · 消息过滤（速率限制/去重/噪音）                        │
│  · inbox 通道 → 单播给目标 agent                       │
│  · 通用广播 → 投递所有在线连接                         │
│  · 离线队列 + ACK 交付统计                             │
└──────────────┬─────────────────────────────────────────┘
               │ _inbox:server 通道
               ▼
┌────────────────────────────────────────────────────────┐
│  L3 场景匹配层  Scenario Matching                      │
│  scenario_matcher.py dispatch()                        │
│  · 规则表: loopback → to_agent → ##query → ##step →   │
│    ##cmd → PM guard → ACK → complete → reject → fail  │
│  · 未匹配 → handle_broadcast() 正常路由                │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│  L4 管线域  Pipeline Domain                            │
│  pipeline_engine.py + main.py (## 命令)                │
│  · PipelineEngine 状态机                               │
│  · auto_dispatch / auto_advance / try_advance          │
│  · ##start/stop/status/advance/archive                 │
│  · watchdag / timeout scanner / git sync               │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│  L5 数据层  Data Layer                                 │
│  message_store.py / task_store.py / audit.py           │
│  pipeline_context.py (JSON) / agent_card.py (JSON)     │
│  workspace.py (JSON)                                   │
└────────────────────────────────────────────────────────┘
```

### 各层详情

| 层 | 文件 | 职责 | 关键函数 |
|---|---|---|---|
| **L1 传输** | `__main__.py` | WS 握手、会话管理、msg_type 一级分发 | `ws_handler()` |
| **L2 路由** | `main.py` | `handle_broadcast()` 消息路由 | 惰性启动 / 过滤 / inbox 单播 / 广播 / ACK |
| **L3 场景匹配** | `scenario_matcher.py` | `_inbox:server` 中继路由（规则表） | `dispatch()` → 规则链 |
| **L4 管线域** | `pipeline_engine.py` + `main.py` | 管线状态机、`##` 命令处理、自动派发 | `try_advance()`, `auto_dispatch()`, `handle_hash_*()` |
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
  └─ type="ping"                 → "pong"
```

### 关键说明

- **`_inbox:server` 通道** — 所有消息直接交 `scenario_matcher.dispatch()` 规则表处理，不经过 `handle_broadcast`
- **`_inbox:{agent_id}` 通道** — 由 `handle_broadcast` 路由，单播给收件箱主人
- **其他通道** — 统一走广播路径（当前仅剩 `LOBBY` 和 `REGISTRATION` 两个频道）

---

## 四、广播路由分析（`handle_broadcast`）

`handle_broadcast` 是 `main.py` 的消息路由中枢（L1498-L1918），当前约 420 行。
R134 移除了 `!` 命令路由段，但大量大厅/工作区相关死代码仍在。

### 4.1 现状（R134 之后）

```
handle_broadcast(ws, sender_id, msg)
  │
  ├─ 🟢 A. 惰性启动
  │      _ensure_watchdog() / engine._ensure_git_scan() / _ensure_agent_cards()
  │
  ├─ 🟢 B. _inbox:server 快速返回
  │      channel == _inbox:server → 已由 scenario_matcher 处理，直接 return
  │
  ├─ 🟢 C. 未注册 bot 保护
  │      非 approved → channel 强制改为 REGISTRATION_CHANNEL
  │
  ├─ 🟢 D. 速率限制 + 消息过滤
  │      _check_rate_limit() / _is_nonsense() / _is_duplicate() / 静音前缀
  │
  ├─ 🟢 E. 用户信息解析
  │      users / sender_name / sender_role / admin_ids
  │
  ├─ 🟢 F. Rollcall ACK 钩子 + Bot ACK 检测
  │      _r57_rollcall_events / _update_step_ack_state()
  │
  ├─ ⚡ G. _admin 频道 intercept  ←── 已废止，待删除
  │      L1596-L1615 — 仅持久化消息，然后 return
  │      实际无任何 bot 再发消息到 _admin
  │
  ├─ 🟢 H. Inbox 通道（_inbox:{agent_id}）
  │      L1617-L1659 — 单播给收件箱主人 → ACK
  │
  ├─ ⚡ I. 频道解析  ←── 已废止，待删除
  │      L1661-L1666 — channel != LOBBY ⇒ channel = LOBBY
  │      整段只做了 fallback，无实际频道解析
  │
  ├─ ⚡ J. Lobby 暂停 + _can_broadcast  ←── 已废止，待删除
  │      L1668-L1680 — 权限检查和暂停检测
  │      原始设计依赖工作区状态，现在 `resolved_workspace` 恒为 None
  │
  ├─ ⚡ K. 大厅前缀路由  ←── 已废止，待删除
  │      L1700-L1768 — 📢 公告 / 📋 点名 / 🆘 求助 / @ 提及的路由选择
  │      近 70 行，当前所有消息直接走统一广播路径即可
  │
  ├─ 🟢 L. Registration 通道
  │      L1770-L1775 — 仅投递到 admin 连接
  │
  ├─ 🟢 M. 统一广播
  │      L1777-L1859 — 构建 payload → 遍历 targets → 发送 → 离线队列
  │
  └─ 🟢 N. ACK 交付统计
        L1861-L1918 — 发送 delivery_status / 延迟统计
```

### 4.2 待清理的死代码汇总

| 段落 | 行范围 | 行数 | 说明 |
|---|---|---|---|
| G `_admin` 频道 | L1596-L1615 | ~20 | 无实际流量，全 return |
| I 频道解析 | L1661-L1666 | ~6 | 只剩 `channel = LOBBY` |
| J 暂停+权限 | L1668-L1680 | ~13 | `_can_broadcast`/`_LOBBY_PAUSED` 已无关 |
| K 大厅前缀路由 | L1700-L1768 | ~70 | 📢/📋/🆘/@ 路由选择，全 return |
| 尾段 workspace admin roll-call | L1910-L1918 | ~10 | `resolved_workspace` 恒为 None |
| **合计** | | **~120** | |

此外，`handle_broadcast` 中的可重构段：

| 段落 | 行范围 | 行数 | 问题 |
|---|---|---|---|
| D 速率限制+过滤 | L1532-L1556 | ~25 | 可提取到独立 `_preprocess_message()` |
| F Rollcall+ACK | L1565-L1581 | ~17 | 可提取到 `_handle_bot_signals()` |
| M 统一广播 | L1777-L1859 | ~83 | `send_str`/`send` 二选一模式重复 4+ 次 |
| N ACK 统计 | L1861-L1918 | ~58 | 大厅专用 ACK + admin 交付状态 |

### 4.3 清理后预期（R135 后）

移除 ⚡ 段落后，`handle_broadcast` 降为约 **200 行**：

```
handle_broadcast(ws, sender_id, msg)
  │
  ├─ A. 惰性启动
  ├─ B. _inbox:server 快速返回
  ├─ C. 未注册 bot 保护
  ├─ D. 速率限制 + 消息过滤（可提取 _preprocess_message）
  ├─ E. Rollcall + Bot ACK 检测（可提取 _handle_bot_signals）
  ├─ F. Inbox 通道 → 单播给收件箱主人
  ├─ G. Registration 通道 → 投递 admin
  └─ H. 广播 + 离线队列 + ACK 统计
```

**简化后的消息路由流程：**

```
入站 message
  │
  ├─ _inbox:server → scenario_matcher 规则表处理 → 结束
  │
  ├─ _inbox:{agent_id} → 单播 + ACK
  │
  ├─ registration → 仅投 admin
  │
  └─ 其他 (实际仅 LOBBY) → 统一广播全部在线连接 + 离线队列
```

没有大厅前缀分类，没有工作区权限，没有 `_admin` 频道。`handle_broadcast`
退化为纯粹的 **投递路由器**：判断通道类型 → 选择投递策略 → 发送 + ACK。

---

## 五、模块关联图

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
│  _handle_hash_start/stop/status/advance/archive   │
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

## 六、数据层

| 文件 | 存储方式 | 数据 | 文件位置 | 生命周期 |
|---|---|---|---|---|
| `message_store.py` | SQLite (WAL) | `messages.db` — 所有广播消息 | `config.DATA_DIR/messages.db` | 7 天 TTL / 10 万行上限 |
| `task_store.py` | SQLite (WAL) | `tasks.db` — R38 任务状态 | `config.DATA_DIR/tasks.db` | 永久（直到管线归档） |
| `audit.py` | JSON Lines | `_audit_log.jsonl` — 操作审计 | `config.DATA_DIR/_audit_log.jsonl` | 追加写入 |
| `pipeline_context.py` | JSON | `pipeline_contexts.json` — 活跃管线 | `config.DATA_DIR/pipeline_contexts.json` | 内存 + 磁盘同步 |
| `agent_card.py` | JSON | `config/agent_cards.json` — Bot 元数据 | `server/config/agent_cards.json` | 文件变更监控刷新 |
| `workspace.py` | JSON | `workspaces.json` / `admin_requests.json` | `config.DATA_DIR/workspaces.json` | 内存 + 磁盘同步 |

---

## 七、管线领域

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

## 八、命令体系

### `##` 命令（主要入口 — scenario_matcher.py + main.py）

管线操作统一走 `##` 命令族：

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

`_inbox:server` 通道的消息自动匹配以下前缀：

| 前缀 | 规则 | 动作 |
|---|---|---|
| `test ✅` | 10 loopback | 双向通信测试 |
| `收到 ✅` / `ACK ✅` | 40 ACK 转发 | 转发 PM + 标记接活 |
| `已完成 ✅` / `✅ 完成` | 50 完成确认 | 转发 PM + auto_advance 管线 |
| `退回 🔄` | 60 退回回退 | 转发 PM + rollback |
| `失败 ❌` | 70 失败告警 | 转发 PM + 告警 |
| 其他未匹配 | 90 入库留痕 | 静默持久化 |

### `!` 命令（R134 已整体移除）

`commands/pipeline.py` 保留 `step_complete` / `step_verify` / `step_force` 等工序操作。

---

## 九、`main.py` 重构清单

`main.py` 当前 3,706 行。R134 已清理 ~1,245 行（`!` 命令路由、`_handle_server_query`、工作区 handlers）。

### 第一刀（R135）：`handle_broadcast` 死代码清除

| 清除目标 | 行范围 | 说明 |
|---|---|---|
| `_admin` 频道 intercept | L1596-L1615 | 已废止，整段删除 |
| 频道解析 fallback | L1661-L1666 | 仅 `channel = LOBBY`，可精简到一行变量默认值 |
| Lobby 暂停 + `_can_broadcast` | L1668-L1680 | 模块已废止 |
| 大厅前缀路由（📢/📋/🆘/@） | L1682-L1768 | 近 90 行，全部删除 |
| 大厅 delivery ACK 统计中的 workspace admin 分支 | L1910-L1918+ | `resolved_workspace` 恒为 None |

**清理后 `handle_broadcast` 从 ~420 行降至约 200 行。**

### 优先级 2 — 纯提取（零语义改动）

| 提取目标 | 行范围（估值） | 目标文件 | 原因 |
|---|---|---|---|
| 连接管理 | L37-L210 | `connection_manager.py` | `_connections`/`_send`/`handle_auth`/`handle_register` |
| 离线队列推送 | L386-L421 | `offline_queue.py` | `_push_offline`/`_flush_offline_push` |
| 看门狗 | L865-L942 | `watchdog.py` | R43 看门狗循环 + 告警 |
| ACK 状态机 | L1009-L1198 | `ack_machine.py` | R63 Phase 4 ACK 检测 |
| Git 同步生命周期 | L569-L613 | `git_sync_lifecycle.py` | 与 pipeline_sync.py 分离的调度层 |

### 优先级 3 — 行为拆分（需设计接口）

| 提取目标 | 行范围（估值） | 目标文件 | 原因 |
|---|---|---|---|
| `_handle_hash_*` (## 命令) | L2966-L3410 | (已有 pipeline_engine.py) | `start/stop/advance/archive/status` 可全部迁入 engine |
| 消息过滤 | L1982-L2014 | `message_filter.py` | `_is_nonsense`/`_is_duplicate` |

### 优先级 4 — 重构设计

- **`_connections` → connection pool class**：当前 `dict[str, set[ws]]`，缺并发安全、缺连接元数据
- **`_send_to_agent` → 统一发送网关**：现有多处 `send_str`/`send` 二选一（至少 15 处重复），应提取单播+广播统一发送器
- **规则注册回调统一**：底部 ~280 行的 `_sm_handle_*()` + 规则注册可统一到一个注册表文件

---

## 十、启动流程

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
