# R131 需求文档 — !命令规则化改造（Query-as-##）

> **轮次：** R131
> **类型：** 架构重构轮（命令路由统一化）
> **版本：** v1.1
> **日期：** 2026-07-20
> **状态：** 📝 草稿待审

---

## §1 背景与问题

### 现状

工作室机制已移除，**系统仅为纯 inbox 单播架构**。无频道广播、无多播场景。但 `!` 命令仍走 `handle_broadcast()` 老路：

```
Bot ──!command──→ handle_broadcast()
                      │
              ↓ 拦截 ! 前缀（main.py L1597）
              ↓ 查 _ADMIN_COMMANDS 注册表
              ↓ _check_command_permission()
              ↓ 执行 handler
              ↓ 通过 inbox 回复
```

### 痛点

| 痛点 | 描述 | 影响 |
|:----|:------|:------|
| **P1** | `!` 命令的拦截逻辑嵌在 `handle_broadcast()` 中（main.py L1596-1609），而当前已无广播场景 | 广播函数名与实际功能不符，维护者困惑 |
| **P2** | `!` 命令的权限检查（`_check_command_permission`）与 `##` 命令的权限检查**两套独立逻辑** | 权限体系割裂 |
| **P3** | `_handle_server_query`（main.py L2082）仅支持 5 个 `!` 查询命令，硬编码在 main.py 中 | 新增查询命令需要改 main.py，违背「不要碰 main.py」的开发准则 |
| **P4** | `##` 命令（scenario_matcher 规则表）已经有查询能力（`##status`、`##help`），但功能不全 | 用户需要 `!agent_card list` 等查询，但目前只能用 `!` |

### 目标

```
当前                              →  目标
! 命令（分散在 broadcast/query）   ##query 命令统一走 scenario_matcher 规则表
├── broadcast 拦截 ! 前缀          ├── rule 25: ##query
├── _handle_server_query           ├── 子命令路由
└── 两套权限检查                   └── 规则内置 level 检查
```

---

## §2 核心设计

### 2.1 方案：新增 `##query` 规则

在 `scenario_matcher.py` 的规则表中，新增一组 `##query` 子规则（优先级 25，介于 to_agent 20 和 ## 30 之间）：

```
优先级 25: ##query 命令
  25.1 ── ##status [R{N}]       → 管线状态查询（已有 ##status）
  25.2 ── ##agents              → 列出所有注册 bot
  25.3 ── ##agent_info <id>     → 查询单个 bot 详情
  25.4 ── ##whoami              → 查看自己的 agent_id + level
  25.5 ── ##audit [--limit N]   → 审计日志（Level 3+）
  25.6 ── ##help                → 帮助信息（已有）
```

### 2.2 命令详情

| ##query 命令 | 替换 ! 命令 | 功能 | 最低权限 |
|:------------|:------------|:------|:---------|
| `##status [R{N}]` | `!pipeline_status` | 查询管线状态（特定轮次或全部） | L1 |
| `##agents` | `!agent_card list` + `!list_agents` | 列出所有已注册 bot（ID / name / role / online） | L1 |
| `##agent_info <agent_id>` | `!agent_card get` + `!agent_status` | 查询单个 bot 详情（Agent Card + 在线状态 + 级别） | L1 |
| `##whoami` | `!my_id` | 返回自己的 agent_id、display_name、级别 | L1 |
| `##audit [--limit N]` | `!audit_log` | 查看审计日志 | **L3** |
| `##help` | `!help` | 显示可用 ##query 命令列表 | L1 |

### 2.3 权限模型

复用当前级别体系：

| 级别 | 标签 | 可用的 ##query 命令 |
|:----:|:-----|:-------------------|
| **L1** | 普通 bot | `##status`、`##agents`、`##agent_info`、`##whoami`、`##help` |
| **L2** | 已注册 bot | 全部 L1 |
| **L3** | 管理员 | 全部 L1 + `##audit` |
| **L4** | 全局管理员 | 全部 L1~L3 |

### 2.4 规则表集成

在 `scenario_matcher.py` 中新增 `match_query` 匹配函数和 `handle_query` 处理函数：

```python
# 规则 25: ##query 命令
register_rule(HandlerRule(
    match=match_query,      # content.startswith("##query")
    handle=handle_query,    # 解析子命令 → 权限检查 → 执行 → 回复 inbox
    priority=25,
    name="##query 命令",
    protocol_ref="§R131",
))
```

`handle_query` 内部流程：

```
handle_query(ws, agent_id, msg, matched)
  │
  ├─ 解析: "##query##status##R130" → cmd="status", params="R130"
  │
  ├─ 查级别: get_agent_level(agent_id)
  │     └─ 级别不足 → 回复「权限不足」到 inbox
  │
  ├─ 执行查询: 调用对应的数据获取函数
  │
  └─ 回复: _send_reply(ws, agent_id, result)
        └─ 只发到发送者的 inbox
```

### 2.5 回复机制

使用 scenario_matcher 已有的 `_send_reply` 函数（已在 handle_hash_cmd 中使用）：

```python
async def _send_reply(ws, agent_id: str, content: str) -> None:
    """回复消息到指定 agent 的 inbox（仅发送者可见）。"""
    reply_ch = persistence.get_inbox_channel(agent_id)
    if not reply_ch:
        return
    await _broadcast_to_channel(reply_ch, {
        "type": "broadcast", "channel": reply_ch,
        "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
        "content": content, "ts": time.time(),
    })
```

### 2.6 使用示例

| 场景 | 发送内容 | 回复（仅发送者 inbox 可见） |
|:-----|:---------|:---------------------------|
| 查自己 | `##whoami` | 🆔 agent_id: ws_xxx | 名称: 小开 | 级别: L3 |
| 查管线 | `##status` | 活跃管线: R130 running step=6/6 |
| 查管线 | `##status##R130` | 📊 R130: Step 6/6, 小爱(ops) 执行中 |
| 查 bot | `##agents` | 📇 Agents (7): 小爱🟢 小谷🟢 小开🟢 爱泰🟢 小周🟢 泰虾🟢 经理🟢 |
| 查审计 | `##audit` | 📋 最近 20 条审计日志（仅 L3+） |

---

## §3 改动范围

### 3.1 涉及文件

| 文件 | 操作 | 说明 |
|:-----|:------|:------|
| `server/ws_server/scenario_matcher.py` | **修改** | 新增 match_query + handle_query 规则 + 子命令路由 + 权限检查 |
| `server/ws_server/main.py` | **修改** | 注册 `##query` 的 handle 回调到 scenario_matcher（参考 L4653+ 的注册模式） |
| `server/ws_server/state.py` | 可选 | 新增 get_agent_level() 工具函数（如需） |

### 3.2 不改动

| 文件 | 理由 |
|:-----|:------|
| `server/ws_server/commands/__init__.py` | ##query 是新增路径，不会删除旧 `!` 路由 |
| `server/ws_server/commands/*.py` | handler 函数可能被 ##query 内部复用 |
| `server/ws_server/pipeline_engine.py` | 不涉及管线状态机改动 |
| `server/web_ui/*` | 纯后端改动 |

---

## §4 验收标准

### 4.1 功能验收

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| F1 | 向 `_inbox:server` 发 `##whoami`，收到自己 agent_id + 级别回复 | 发送 `##whoami` → 检查 inbox 回复 |
| F2 | 向 `_inbox:server` 发 `##agents`，收到所有注册 bot 列表 | 发送 `##agents` → 检查回复内容 |
| F3 | 向 `_inbox:server` 发 `##status`，收到活跃管线列表 | 发送 `##status` → 检查回复 |
| F4 | 向 `_inbox:server` 发 `##status##R{N}`，收到指定管线详情 | 发送 `##status##R130` → 检查 |
| F5 | 向 `_inbox:server` 发 `##agent_info ws_xxx`，收到 bot 详情 | 发送 `##agent_info ws_f26e585f6479` → 检查 |
| F6 | 向 `_inbox:server` 发 `##audit`，L3+ 收到审计日志，L1 收到权限拒绝 | 用不同级别 bot 测试 |

### 4.2 回归验证

| # | 回归项 | 验证方法 |
|:-:|:-------|:---------|
| R1 | 原有 `##start`/`##stop`/`##advance`/`##archive` 等命令不受影响 | 发送 `##status##R130` → 正常返回 |
| R2 | 原有 `!` 命令仍可用（不删除） | 发 `!agent_card list` 到 _inbox:server → 正常回复 |
| R3 | `_inbox:server` 的 `_handle_server_query` 仍可用 | 发 `!pipeline_status` → 正常回复 |
| R4 | to_agent 派活不受影响 | 发送带 to_agent 的消息 → 正常路由 |
| R5 | 回复**仅发送到发送者 inbox**，不广播 | 发 `##whoami` + 检查其他 bot 是否收到 |

---

## §5 废除路线图

### 5.1 本轮（R131）— ##query 先行

新增 6 个 `##query` 命令覆盖最常用的查询需求。**旧 `!` 命令保持兼容，不删除。**

### 5.2 下轮（R132+）— 逐步迁移

| 批次 | 命令 | 新 ## 模式 | 说明 |
|:----:|:------|:-----------|:------|
| **1** | `!step_complete` / `!step_reject` / `!step_handoff` / `!step_force` / `!step_verify` | `##complete` / `##reject` / `##handoff` / `##force` / `##verify` | 行动类 |
| **2** | `!pipeline_start` / `!pipeline_stop` / `!pipeline_activate` / `!pipeline_mode` / `!pipeline_role_override` | `##start` / `##stop`（已有）/ `##activate` 等 | 管线管理类 |
| **3** | `!agent_card set` / `!agent_card unset` / `!agent_card reload` / `!agent_card register` / `!agent_role_map` / `!approve_ws_admin` / `!reject_ws_admin` / `!revoke_api_key` / `!list_pending` | `##admin##set_card` / `##admin##approve` 等 | 管理类 |
| **4** | `!task_create` / `!task_update` / `!task_query` / `!task_list` / `!rollcall_role` / `!rollcall_next` | `##task##create` / `##rollcall##` 等 | 任务类 |

### 5.3 最终状态

```
当前                                    →  最终
! 命令（两套路由）                      ## 命令（统一走 scenario_matcher）
├── pipeline 类（!pipeline_start...）     ├── ##start##（已有）
├── step 类（!step_complete...）          ├── ##complete / ##reject...
├── agent_card 类                         ├── ##agents / ##agent_info（本轮）
├── task 类（!task_create...）            ├── ##task##create...
├── rollcall 类（!rollcall_role...）       ├── ##rollcall##...
├── admin 类（!approve_ws_admin...）      ├── ##admin##approve...
├── audit 类（!audit_log...）             ├── ##audit（本轮）
└── 查询类（!my_id/!help...）            └── ##whoami / ##help（本轮）
```

每迁移一批，旧 `!` 命令对应的 handler 标记 `@deprecated`，记录到 TODO.md，下轮可安全删除。

---

## §6 验收检查表

### 文件改动清单

| # | 文件 | 改动说明 | 状态 |
|:-:|:-----|:---------|:----:|
| 1 | `scenario_matcher.py` | 新增 `match_query` 匹配函数 | ⬜ |
| 2 | `scenario_matcher.py` | 新增 `handle_query` 处理函数 + 子命令路由 | ⬜ |
| 3 | `scenario_matcher.py` | 新增 `get_agent_level()` 权限检查 | ⬜ |
| 4 | `scenario_matcher.py` | 注册 rule 25（priority=25） | ⬜ |
| 5 | `main.py` | 注册 `##query` 的 handle 回调（参考 L4653+） | ⬜ |

### 验收计数

| 分组 | 总数 | 🟢 通过 | 🔴 失败 |
|:----|:----:|:-------:|:-------:|
| 功能验收（F1-F6） | 6 | 0 | 0 |
| 回归验证（R1-R5） | 5 | 0 | 0 |
| **合计** | **11** | **0** | **0** |
