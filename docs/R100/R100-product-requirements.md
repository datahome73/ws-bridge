# R100 — 服务端核心重构：handler.py 拆分 🏗️

> **状态**: 需求文档  
> **PM**: —  
> **目标版本**: v3.0  
> **优先级**: P0 (架构级)

---

## 一、背景

### 1.1 当前问题

`server/handler.py` 经过 40+ 轮迭代增长至 **7,024 行**，承载了远超其原始职责的功能：

```
handler.py (7024行)
├── 核心 WS 消息路由 (~500行)     ✓ 该留
├── 入口认证/注册 (~200行)        ✓ 该留
├── !命令路由基础设施 (~150行)    ✓ 重组
├── 30+ 个 _cmd_* 函数 (~2000行)  ✗ 搬走
├── 管线状态全局变量 (~100行)     ✗ 搬走
├── 管线辅助函数 (~500行)         ✗ 搬走
├── 看门狗子系统 (~300行)         ✗ 搬走
├── ACK/超时子系统 (~300行)       ✗ 搬走
└── handler()内 msg_type分支(~2000行) ✗ 搬走
```

**核心矛盾**：handler.py 本该只做消息路由（`handle_broadcast` / `_handle_server_relay` / `_handle_server_query` / `handler()`），但因无架构约束，所有功能都以"加一个 `_cmd_*` 函数"的方式塞入同一个文件，导致：

- 文件过大，难以维护
- 状态散落在文件各处的全局变量
- 无法独立测试命令逻辑
- 新开发者找不到入口
- AutoRouter 等高级功能无法在此结构上构建

### 1.2 分层原则

ws-bridge 的层次关系：

```
┌─────────────────────────────────────┐
│  消息通道（核心）                    │
│  ───────────────────                │
│  bot 们能正常收发 inbox 消息         │
│  去掉这个，inbox 就不通了            │
├─────────────────────────────────────┤
│  附加功能（插件）                    │
│  ───────────────────                │
│  !命令 / 管线 / 看门狗 / Git 同步    │
│  去掉这些，inbox 还能互相通信        │
└─────────────────────────────────────┘
```

**核心测试**：去掉某功能后，bot 之间是否还能通过 _inbox 互相发消息？能 → 插件；不能 → 核心。

---

## 二、目标

### 2.1 R100 范围（Phase 1）

只做 **结构拆分**，不做行为改变：

| 目标 | 衡量标准 |
|---|---|
| handler.py 拆分完成 | handler.py 改名 main.py，从 7024 行降至 ~800 行 |
| !命令全部迁出 | commands/ 目录 5 个文件承载全部 ~30 个 !命令 |
| 共享状态统一管理 | state.py 持有全部共享全局变量 |
| 命令路由工具统一 | command_utils.py 持有全部命令路由辅助函数 |
| 无循环导入 | 依赖链单向：main → commands → state |
| 零行为变更 | 所有现有 !命令行为完全不变 |

### 2.2 非目标（Phase 2+）

- ❌ 不砍 `_PIPELINE_STATE`（Phase 2）
- ❌ 不重写管线状态机（Phase 2）
- ❌ 不重新设计 AutoRouter（Phase 3）
- ❌ 不改 workspace.py / auth.py / agent_card.py 等已有模块
- ❌ 不改 Web 界面

---

## 三、方案

### 3.1 目录结构变更

```
server/                          server/
├── handler.py    (7024行)   →   ├── main.py             (~800行)  改名+精简
                                  ├── state.py            (~200行)  🔺新增
                                  ├── command_utils.py    (~200行)  🔺新增
                                  └── commands/           (~2500行) 🔺新增
                                      ├── __init__.py
                                      ├── workspace.py
                                      ├── pipeline.py
                                      ├── agent_card.py
                                      ├── task.py
                                      └── admin.py
```

### 3.2 文件职责

#### `main.py`（原名 handler.py）— 核心消息路由

只保留：
```
main.py
├── handler()                WS 会话主循环
├── handle_broadcast()       消息路由 + 广播（含 !命令分发）
├── _handle_server_relay()   inbox 中继（转发生成/ACK/完成通知）
├── _handle_server_query()   _inbox:server 查询路由
├── handle_auth()            认证入口
├── handle_register()        bot 注册入口
├── handle_agent_card_register() Agent Card 注册入口
├── _send()                  WebSocket 写入
├── msg_type 分支            handler() 内的各种 type 处理
└── _connections             在线连接集合（仅此一个全局变量保留）
```

> **为什么 `msg_type` 分支不一起搬？** 它们与 handler() 主循环的耦合更紧密（直接操作 ws 对象发送响应），Phase 2 再处理。

#### `state.py` — 共享状态

从 handler.py 搬出全部共享全局变量：

| 变量 | 用途 |
|---|---|
| `_PIPELINE_STATE` | R42 管线运行时状态 |
| `_PIPELINE_CONFIG` | R62 管线只读配置 |
| `_step_ack_states` | R53 频道切换 ACK 状态 |
| `_LOBBY_PAUSED` / `_LOBBY_PAUSED_ROUND` | R42 大厅暂停状态 |
| `_r72_users` | R72 注册 agent 用户名映射 |
| `_offline_push_queue` / `_offline_timers` | 离线消息推送队列 |
| `_delivery_status` | 消息投递状态追踪 |
| `_task_ack_timers` | 任务 ACK 超时计时器 |
| `_r57_rollcall_events` | R57 rollcall ACK 事件 |
| `_channel_ack_state` | 频道切换 ACK 状态 |
| `SYSTEM_AGENT_ID` | 系统 agent 常量 |
| `SERVER_INBOX_CHANNEL` | server inbox 通道常量 |
| `_role_agent_map` | R63 角色→agent 映射 |
| `_GIT_SYNC_TASK` | R65 Git 同步 task 引用 |
| `_watchdog_task` | 看门狗 task 引用 |
| `_card_watcher_running` | Agent Card 热更新状态 |
| 其他 handler.py 顶层的模块级变量 | |

#### `command_utils.py` — 命令路由工具

| 函数 | 用途 |
|---|---|
| `_parse_command(content)` | 解析 !命令字符串 → (cmd_name, params) |
| `_check_command_permission(sender_id, cmd_name, cmd, params)` | 权限检查 |
| `_send_cmd_response(ws, sender_id, from_name, content, channel)` | 发送命令响应 |
| `_log_audit(...)` | 审计日志记录 |
| `_broadcast_to_channel(channel, payload)` | 向频道广播消息 |
| `_resolve_workspace(sender_id, params)` | 解析工作区 ID |

#### `commands/` — 全部 !命令

每个文件对应一个领域，导出命令处理函数：

| 模块 | 命令 | 行数预估 |
|---|---|---|
| `workspace.py` | create_workspace, close_workspace, list_workspaces, workspace_join, workspace_leave, workspace_add, workspace_remove, workspace_list_members, workspace_reset | ~500 |
| `pipeline.py` | pipeline_start, pipeline_stop, pipeline_status, pipeline_activate, pipeline_context, pipeline_mode, pipeline_role_override, step_handoff, step_complete, step_reject, step_force, step_verify + 全部管线辅助函数 | ~1200 |
| `agent_card.py` | agent_card, agent_card_list, agent_card_get, agent_card_set, agent_card_unset, agent_card_reload, agent_card_register, agent_card_auto_register, agent_role_map | ~300 |
| `task.py` | task_create, task_update, task_query, task_list, rollcall_role, rollcall_next | ~400 |
| `admin.py` | approve_ws_admin, reject_ws_admin, list_pending, audit_log, list_workspace_admins, revoke_api_key + list_agents, agent_status | ~200 |

`commands/__init__.py` 导入所有模块并构建 `_ADMIN_COMMANDS` 注册表（从 handler.py 原样搬出）。

### 3.3 依赖关系

```
__main__.py
  └── main.py
        ├── state.py          （纯数据，无反向依赖）
        ├── command_utils.py  （调用 state，无反向依赖）
        ├── commands/__init__.py  （导入 _ADMIN_COMMANDS）
        │     ├── state.py
        │     ├── command_utils.py
        │     └── workspace / auth / agent_card / ...
        ├── (其他 server 模块)
        └── shared.protocol
```

**无循环导入**：`state.py` 和 `command_utils.py` 不依赖 main.py 或 commands/ 中的任何内容。

### 3.4 与旧文件的兼容

| 旧符号 | 新位置 | 兼容方式 |
|---|---|---|
| `handler.handle_auth` | `main.handle_auth` | __main__.py 改 import |
| `handler.handle_broadcast` | `main.handle_broadcast` | __main__.py 改 import |
| `handler._connections` | `main._connections` | 保留在 main.py |
| `_PIPELINE_STATE` | `state._PIPELINE_STATE` | 所有引用处改 import |
| `_cmd_create_workspace` | `commands.workspace._cmd_create_workspace` | 通过 `_ADMIN_COMMANDS` 路由 |

---

## 四、执行计划

### Step 1: 创建 state.py

- 从 handler.py 复制全部模块级全局变量到 state.py
- 保持名称不变，方便后续搜索替换
- 验证：state.py 无任何 import 依赖

### Step 2: 创建 command_utils.py

- 从 handler.py 复制命令路由工具函数
- 将引用 state.py 变量的部分改为 `state.X` 形式
- 验证：command_utils.py 只依赖 state.py + Python 标准库

### Step 3: 创建 commands/ 包

- 逐个创建 5 个命令文件
- 每个文件从 handler.py 复制对应 _cmd_* 函数
- 将所有 `_PIPELINE_STATE` 等引用改为 `state._PIPELINE_STATE`
- 将所有 `_broadcast_to_channel()` 等工具函数改为 `command_utils._broadcast_to_channel()`
- commands/__init__.py 构建 _ADMIN_COMMANDS

### Step 4: 改名 handler.py → main.py

- git mv handler.py main.py
- 删除已搬出的函数和变量
- 保留核心 WS 路由函数 + _connections + handler() 主循环
- 导入 commands._ADMIN_COMMANDS 用于 !命令分发
- 导入 state/command_utils 用于其他引用

### Step 5: 更新 __main__.py

- 改 import 路径: `from .main import ...` 替代 `from .handler import ...`

### Step 6: 验证 + 部署

- 启动服务，确认无 import 错误
- 手工 inbox 双向通信测试（bot ↔ server）
- 常用 !命令功能测试
- 推 dev → 通知运维部署 → 生产验证

---

## 五、验收标准

### 5.1 核心通路验证

```
1. Bot A 连接 → 认证成功
2. Bot A 向 Bot B 发 _inbox 消息 → Bot B 收到
3. Bot B 回复 Bot A 的 _inbox → Bot A 收到
4. _inbox:server 中继功能正常（ACK ✅ / ✅ 完成 路由到 PM）
5. 大厅 lobby 消息广播正常
```

### 5.2 命令功能验证

```
6. !list_workspaces → 返回工作区列表
7. !pipeline_status → 返回管线状态（无错误）
8. !agent_card list → 返回 Agent Card 列表
9. !task_list → 返回任务列表
10. !audit_log → 返回审计日志
```

### 5.3 代码质量验证

```
11. handler.py → main.py, 从 7024 ↓ ~800 行
12. commands/ 目录存在，包含 __init__.py + 5 个模块
13. state.py 存在，包含全部共享变量
14. command_utils.py 存在，包含全部工具函数
15. 无循环导入：服务启动无 ImportError
```

---

## 六、风险与缓解

| 风险 | 缓解 |
|---|---|
| 循环导入导致服务无法启动 | 单向依赖链设计 + 启动前本地测试 |
| 搬漏函数引用导致运行时 NameError | 逐文件构建 + 搜索确保所有 _cmd_* 已迁移 |
| handler() 内 msg_type 分支引用已搬变量 | 统一改为 `state.X` 引用 |
| _connections 被 commands 函数引用 | _connections 保留在 main.py，通过参数或 state.py 中转 |
| 部署后 inbox 不通 | Step 6 先在小爱测试环境验证 |

---

## 七、文件清单

### 新增文件

| 文件 | 内容来源 | 行数预估 |
|---|---|---|
| `server/state.py` | handler.py 全局变量 | ~200 |
| `server/command_utils.py` | handler.py 工具函数 | ~200 |
| `server/commands/__init__.py` | handler.py _ADMIN_COMMANDS | ~100 |
| `server/commands/workspace.py` | handler.py workspace 命令 | ~500 |
| `server/commands/pipeline.py` | handler.py pipeline 命令 + 辅助函数 | ~1200 |
| `server/commands/agent_card.py` | handler.py agent_card 命令 | ~300 |
| `server/commands/task.py` | handler.py task + rollcall 命令 | ~400 |
| `server/commands/admin.py` | handler.py admin 命令 | ~200 |

### 修改文件

| 文件 | 变更内容 |
|---|---|
| `server/handler.py` → `server/main.py` | 改名，删除已搬出的函数和变量，保留核心 ~800 行 |
| `server/__main__.py` | import 路径: handler → main |
| `server/README.md` | 更新架构图、文件职责表、依赖关系 |

### 删除文件

| 文件 | 原因 |
|---|---|
| `server/workspace.py` 移除？ | 经讨论保留，架构师决定 |
| `server/task_store.py` 移除？ | 保留，与管线关联，Phase 2 再讨论 |

---

## 八、Reference

- [server/README.md](../server/README.md) — 完整架构文档
- [handler.py 现状分析](../server/README.md#四管线系统详解) — 问题说明
- [重构路线图](../server/README.md#63-重构路线图) — Phase 1/2/3 规划
