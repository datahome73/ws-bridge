# R135 产品需求 — handle_broadcast 死代码清理 + 频道体系精简

> **起草人：** 🧐 PM
> **状态：** 📝 草稿
> **版本：** v1.0
> **日期：** 2026-07-20
> **依据文档：** `server/ws_server/README.md` §4（已定稿）

---

## 0. R135 定位

```
R134（已上线）— 代码精简轮：!命令体系 + Workspace + AutoRouter 清理
R135（本轮）    — handle_broadcast 死代码清理 + 频道体系精简 (-306行)
R136（下轮）    — 纯提取：连接管理/离线队列/看门狗/ACK状态机/定时器分离
```

---

## 1. 背景与目标

### 1.1 现状问题

`handle_broadcast` 是 `main.py` 的消息路由中枢（L1498-L1918），当前约 **420 行**。
R134 虽然移除了 `!` 命令路由段（-1,245 行），但以下频道体系已全部废止：

| 已废止的概念 | 原因 | 影响代码 |
|---|---|---|
| `LOBBY`（大厅） | 所有通信走 `_inbox:*` | L1661-L1768 |
| `REGISTRATION_CHANNEL` | 注册自动完成 | L1528-L1530, L1770-L1775 |
| `_admin` 频道 | 无 admin 角色 | L1596-L1615 |
| `WORKSPACE`（工作区） | R134 已清理 | L1565-L1581, L1668-L1680, L1910-L1918 |
| `sender_role`（admin/member） | 全自动注册，无分级 | L1558-L1563 |

### 1.2 目标

清理 `handle_broadcast` 中 **~306 行死代码**，将其从 420 行精简到 **~110 行**，
使其退化为纯粹的 **inbox 投递器**。同时清理因频道体系变更而失效的相关辅助函数和状态变量。

### 1.3 范围界定

| 范围 | 包含 | 不包含 |
|---|---|---|
| `main.py` | `handle_broadcast` 死代码删除 | `##` 命令处理（`_handle_hash_*`） |
| `state.py` | 已废止的状态变量清理 | 管线相关状态变量 |
| `workspace.py` | 不再需要 `init()` 及重复的权限函数 | 核心数据模型 |
| `message_store.py` | 不再需要的全局 broadcast 查询 | 消息存储核心 |
| 其他模块 | 因清理引发的 import 调整 | 纯提取工作（留 R136） |

---

## 2. 功能需求

### CLN-1（清理 A）：`_admin` 频道 intercept

- **位置：** `main.py` L1596-L1615
- **行为：** 整段删除。`_admin` 频道已废止，无 bot 再发消息到此频道。
- **附带清理：**
  - `_admin_msg()` 函数（L426-L435）
  - `_persist_admin_response()` 函数（L437-L449）
  - `p.ADMIN_CHANNEL` 引用（如仍存在）

### CLN-2（清理 B）：未注册 bot 保护

- **位置：** `main.py` L1528-L1530
- **行为：** 删除。注册全自动，无需强制跳转 REGISTRATION_CHANNEL。

### CLN-3（清理 C）：速率限制

- **位置：** `main.py` L1532-L1543
- **行为：** 删除。所有通信走 `_inbox:*` 点对点通道，无需全局限速。
- **附带清理：**
  - `_check_rate_limit()` 函数
  - `_check_lobby_rate_limit()` 函数
  - `state._rate_limits` 及相关常量
  - `state._lobby_rate_limits` 及相关常量

### CLN-4（清理 D）：全局消息过滤

- **位置：** `main.py` L1545-L1556
- **行为：** 删除。inbox 是点对点，无需全局去重/噪音过滤。
- **附带清理：**
  - `_is_nonsense()` 函数
  - `_is_duplicate()` 函数
  - `state._SILENT_PREFIXES`
  - `state._NONSENSE_PATTERNS`
  - `state._last_message` 及相关状态

### CLN-5（清理 E）：用户角色/权限信息

- **位置：** `main.py` L1558-L1563
- **行为：** 删除。无 admin/member 分级。
- **附带清理：**
  - `_can_broadcast()` 函数（L2079-L2108）
  - `_get_agents_by_role()` 函数（L512-L544）
  - 所有 `sender_role` 分支逻辑

### CLN-6（清理 F）：Rollcall + Bot ACK 检测

- **位置：** `main.py` L1565-L1581
- **行为：** 删除。无大厅/工作区，无 rollcall。
- **附带清理：**
  - `_handle_rollcall_ack()` 函数
  - `_update_step_ack_state()` 函数
  - `state._r57_rollcall_events`
  - `state._channel_ack_state`
  - `state._step_advance_buffer`

### CLN-7（清理 G）：频道解析 fallback/Lobby 暂停/`_can_broadcast`/大厅前缀路由

- **位置：** `main.py` L1661-L1768
- **行为：** 整段（~95 行）删除。
- **附带清理：**
  - `_sm.classify_lobby_message()` 引用
  - `_check_lobby_rate_limit()`（已包含在 CLN-3）
  - `state._LOBBY_PAUSED`
  - `state._LOBBY_PAUSED_ROUND`
  - `state.PREFIX_ANNOUNCE/CHECKIN/HELP` 常量

### CLN-8（清理 H）：Registration 通道投递

- **位置：** `main.py` L1770-L1775
- **行为：** 删除。无 registration 通道。

### CLN-9（清理 I）：统一广播 + 离线队列

- **位置：** `main.py` L1777-L1859
- **行为：** 删除。无广播目标（只剩 `_inbox:*` 单播路径）。
- **附带清理：**
  - `_push_offline()` 函数（L386-L400）
  - `_flush_offline_push()` 函数（L402-L421）
  - `state._offline_push_queue`
  - `state._offline_timers`
  - `state._delivery_status`
  - `state._send_stats`

### CLN-10（清理 J）：ACK 交付统计

- **位置：** `main.py` L1861-L1918
- **行为：** 删除。无广播，无需交付统计。
- **附带清理：**
  - `_build_online_list()` 函数（L153-L180）
  - `get_delivery_status()` 函数（L132-L133）
  - `_broadcast_task_notify()` 函数（L1498-残存）

### CLN-11（清理 K）：`workspace.py` 精简

- **原因：** 工作区概念已废止，但 workspace.py 仍保留完整 CRUD 和审批功能。
- **保留：** `get_workspace()` / `Workspace` 数据模型（其他模块仍有引用）
- **删除：**
  - `start_closing()` / `force_close()` / `check_idle()`
  - `submit_admin_request()` / `approve_admin_request()` / `reject_admin_request()`
  - `AdminRequest` dataclass 及相关 I/O
  - `list_workspace_admins()` / `get_pending_requests()`
  - `cleanup_archived()` / `build_workspace_ready()`

### CLN-12（清理 L）：`message_store.py` 精简

- **原因：** 无广播，消息持久化仅 inbox 通道需要。
- **保留：** `save_message()` / `get_messages_since()` / `init_db()` / `clean_old_messages()`
- **删除：**
  - `search_messages()` — 全局搜索已不需要
  - `get_messages_by_channel_pattern()` — 通道模式匹配不再使用
  - `get_messages_by_time_range()` — 时间范围查询不再使用
  - `is_duplicate()` — 去重逻辑随 CLN-4 移除

---

## 3. 清理后架构预期

### `handle_broadcast` 清理后

```
handle_broadcast(ws, sender_id, msg)
  ├─ A. 惰性启动（watchdog / git sync / timeout / agent cards）
  ├─ B. _inbox:server → 直接 return（scenario_matcher 已处理）
  └─ C. _inbox:{agent_id} → 验证 → 单播 → ACK
       其他 channel → 静默忽略
```

清理后约 **~110 行**，退化为纯 inbox 投递器。

### 消息路由流程

```
入站 message
  ├─ channel == _inbox:server
  │     → scenario_matcher.dispatch() 规则表
  │     → loopback / to_agent / ##命令 / ACK / 完成确认 / 退回 / 失败 / 兜底
  │
  └─ channel == _inbox:{agent_id}
        → 验证收件箱存在
        → 验证 sender != owner（防自刷）
        → 单播给 owner
        → ACK 回复发送者
```

---

## 4. 验收标准

| # | 验收项 | 类型 | 状态 |
|:-:|:-------|:----:|:----:|
| CLN-1 | `_admin` 频道 intercept 整段删除，无残留 import | P0 | ⬜ |
| CLN-2 | 未注册 bot 保护代码删除 | P0 | ⬜ |
| CLN-3 | 速率限制代码及 state 变量全部删除 | P0 | ⬜ |
| CLN-4 | 全局消息过滤代码及 state 变量全部删除 | P0 | ⬜ |
| CLN-5 | 用户角色/权限代码及 `_can_broadcast` 删除 | P0 | ⬜ |
| CLN-6 | Rollcall/ACK 检测及 state 变量删除 | P0 | ⬜ |
| CLN-7 | Lobby 暂停 + 大厅前缀路由 + 频道解析整段删除 | P0 | ⬜ |
| CLN-8 | Registration 通道投递删除 | P0 | ⬜ |
| CLN-9 | 统一广播 + 离线队列及其 state 变量删除 | P0 | ⬜ |
| CLN-10 | ACK 交付统计及辅助函数删除 | P0 | ⬜ |
| CLN-11 | workspace.py 精简：仅保留 `get_workspace()` + 数据模型 | P1 | ⬜ |
| CLN-12 | message_store.py 精简：删除 3 个全局查询函数 | P1 | ⬜ |
| R135-1 | 清理后 `handle_broadcast` 无死代码，仅剩惰性启动 + inbox 路由 | P0 | ⬜ |
| R135-2 | `python3 -c "from server.ws_server import main"` 无 ImportError | P0 | ⬜ |
| R135-3 | `##status##R135` 管线状态查询正常 | P0 | ⬜ |
| R135-4 | `##start##R135` 管线启动 + 派活正常 | P0 | ⬜ |
| R135-5 | `_inbox:{agent_id}` 单播投递正常（自刷阻断 + ACK） | P0 | ⬜ |
| R135-6 | `_inbox:server` 规则表路由正常（loopback / ACK / 完成确认） | P0 | ⬜ |

---

## 5. 方向决定

| 决定事项 | 选择 | 说明 |
|:--------|:----|:-----|
| 实现范围 | 仅服务端 | `server/ws_server/` 代码，不含客户端 |
| 不做事项 | `##` 命令迁移到 engine | 留 R136: **纯提取轮** |
| 不做事项 | `_connections` 池化 | 留 R136 |
| 不做事项 | `_send_to_agent` 统一网关 | 留 R136 |
| 不做事项 | scenario_matcher 规则注册统一 | 留 R136 |

---

## 6. 开放问题

| # | 问题 | 建议方向 | 决策者 |
|:-:|:-----|:--------|:------|
| 1 | `workspace.py` 是否整体删除？ | 保留数据模型和 `get_workspace()`，其他函数删除。因 `__main__.py` 和 `main.py` 仍有 `workspace` import | 项目负责人 |

---

> **审核记录：**
> - v1.0 提交审核：[@2026-07-20]
> - 项目负责人审核意见：
> - 结论：⬜ 待审核
