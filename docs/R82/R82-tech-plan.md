# R82 技术方案 — Inbox-Only 架构重构 🏗️

> **版本：** v1.0
> **状态：** ✅ 已审核通过
> **架构师：** 👷 Architect
> **日期：** 2026-07-08
> **基于需求文档：** docs/R82/R82-product-requirements.md v1.0 ✅
> **基线：** `7698241` (R81 origin/dev HEAD)
> **改动范围：** `server/handler.py`、`shared/protocol.py`、`server/workspace.py`、`server/persistence.py`、`server/config.py`
> **不动：** `clients/`、`server/web_viewer.py`、`server/auth.py`、`server/agent_card.py`

---

## 目录

1. [精确改动点](#1-精确改动点)
2. [删除路径 / 保留路径决策树](#2-删除路径--保留路径决策树)
3. [工作室时间切片模型](#3-工作室时间切片模型)
4. [兼容性分析](#4-兼容性分析)
5. [风险与缓解](#5-风险与缓解)
6. [改动统计](#6-改动统计)

---

## 1. 精确改动点

### 1.1 handler.py — 改动点汇总

#### 🅿️0-1: 删除 `_broadcast_active_channel()` 函数
- **位置：** `server/handler.py` L5725-5778（~53 行）
- **描述：** 整个函数删除。该函数向工作室所有成员发送 `MSG_SET_ACTIVE_CHANNEL` 报文，等待 ACK 超时。inbox-only 架构下不再需要 bot 切换频道。
- **连带删除：**
  - `_channel_ack_state` 字典（L138, ~20 行引用）
  - `_channel_ack_timeout()` 函数（L5984-6021, ~37 行）
  - `_resolve_ws_by_ack_task_id()` 函数（L6024-6028, ~5 行）

#### 🅿️0-2: 删除 `_broadcast_active_channel()` 的 8 个调用点

| # | 行号 | 所在函数 | 当前用途 | 删除方式 |
|:-:|:----:|:---------|:---------|:---------|
| 1 | **L696** | `_cmd_create_workspace` | 创建工作室后广播频道切换 | **删除** — 创建工作室后不再频道切换 |
| 2 | **L1100** | `_cmd_rollcall`（点名） | 点名后广播频道切换 | **删除** — 点名通过 inbox 通知，不再切换频道 |
| 3 | **L1134** | `_cmd_rollcall`（下一环节） | 下一环节广播 | **删除** — 同上 |
| 4 | **L2701** | `_cmd_pipeline_start` / F-20 修复 | 管线启动广播 | **删除** — 改用 inbox 派活 |
| 5 | **L2858** | pipeline_start 后续 | 同上 | **删除** |
| 6 | **L3989** | `_cmd_close_workspace` | 关闭后 lobby 广播 | **删除** — 不需要广播频道切换 |
| 7 | **L4170** | 重置/恢复 | 频道恢复广播 | **删除** |
| 8 | **L5719** | `_resolve_ws_routing` | 频道解析回退 | **删除** |

#### 🅿️0-3: 简化 `handle_broadcast()` — Inbox-only 路由

- **位置：** `server/handler.py` L5141-5600（~460 行 → 精简至 ~250 行）

**改动 3a — 删除 channel 回退到 `get_agent_channel`（L5159）：**
```python
# 旧
channel = msg.get(p.FIELD_CHANNEL) or persistence.get_agent_channel(sender_id) or p.LOBBY
# 新
channel = msg.get(p.FIELD_CHANNEL) or p.LOBBY
```
- 不再需要 `get_agent_channel()` 回退 — bot 不维护活跃频道

**改动 3b — 保留 📢/📋/@ 大厅路由（L5482-5551），但 bot 不接收：**
- 大厅路由**保留给真人**，改动点：移除 admin 之外的 bot 从大厅接收消息
- 在 L5505-5546 的 `targets` 构建中，排除非 admin bot（使用 `_connections` 但只路由给 admin/真人）
- `_classify_lobby_message()` 函数保留不动

**改动 3c — 工作室（workspace）频道路由（L5363-5481）简化：**
- 当前：L5363-5481 路由到工作室 members + admin
- 改为：工作室消息只路由给**真人**（即 `_connections` 中 role=admin 或非 bot 的 agent_id）
- Bot 不再接收工作室频道广播
- 工作室频道本身保留（真人仍需在里面聊天）

**改动 3d — Inbox 通道 intercept 保持不变（L5277-5313）：**
- `_inbox:xxx` 的完整路由逻辑**保留不动**
- 这是 inbox-only 架构的核心通道 — 0 改动
- 仅补充：移除对 `get_agent_channel` 的依赖（inbox 路由已不依赖）

**改动 3e — 删除或简化 `_is_nonsense` / `_is_duplicate` 在 inbox 路径上的判断：**
- 当前：L5179-5185 对所有非 `!` 消息进行 nonsense/duplicate 过滤
- 改为：inbox 通道消息跳过 nonsense/duplicate 过滤（L5277 inbox 分支已 return，不受影响 ✅）
- 非 inbox 消息仍保留过滤（给真人用）

**改动 3f — 删除 R63 Phase 3 的 workspace channel rollcall ACK（L5208-5212）：**
- `if channel.startswith(p.WORKSPACE_ID_PREFIX) or channel.startswith("ws:")` 的分支
- 该分支依赖 workspace 频道模型，inbox-only 后不再触发
- **直接删除** L5206-5212 的 `_handle_rollcall_ack` 调用

**改动 3g — 删除 silent/noise 过滤（L5188-5190）：**
- `_SILENT_PREFIXES` 过滤是频道污染补丁
- 删除 L5188-5190 的整个过滤块
- `_SILENT_PREFIXES` 元组（L32-40）保留（被 Admin 频道 `_persist_broadcast` 等外部路径引用）

#### 🅿️1-1: 删除 `set_active_channel` admin 命令

- **位置：** `server/__main__.py` L390-404
- **描述：** 管理员通过 WebSocket 协议设置 agent 活跃频道的功能。inbox-only 后废弃。
- **删除方式：** 删除 L390-404 整个 elif 分支。
- **注意：** 不影响 `MSG_ADMIN_REQUEST`（L406+）和其他消息类型处理。

#### 🅿️1-2: 删除注册流程中的活跃频道设置

- **位置：** `server/handler.py` L391-396（`handle_agent_card_register` 内）
- **当前代码：**
  ```python
  persistence.set_agent_channel(agent_id, p.LOBBY)
  await _send(ws, {
      "type": p.MSG_SET_ACTIVE_CHANNEL,
      p.FIELD_CHANNEL: p.LOBBY,
  })
  ```
- **删除方式：** 删除 L391-396 整个代码块。注册后 bot 不再被切换到 lobby 频道。

#### 🅿️1-3: 删除 `_cmd_create_workspace` 中的活跃频道绑定

- **位置：** `server/handler.py` L682-684
- **当前代码：**
  ```python
  persistence.set_agent_channel(sender_id, ws_id)
  persistence.save_agent_channels(config.DATA_DIR)
  ```
- **删除方式：** 删除 L682-684，创建工作室不再自动切换发送者的活跃频道。

#### 🅿️1-4: 删除欢迎消息中的活跃频道查询

- **位置：** `server/handler.py` L368
- **当前代码：**
  ```python
  target_ch = persistence.get_agent_channel(agent_id) or p.LOBBY
  ```
- **改为：** 直接使用 `p.LOBBY` 而非查询活跃频道。欢迎消息始终发到大厅（给真人看）。

---

### 1.2 persistence.py — 改动点

#### 🅿️0-4: 删除活跃频道相关代码

| # | 行号 | 函数/变量 | 删除方式 |
|:-:|:----:|:----------|:---------|
| 1 | **L126** | `_agent_active_channels: dict[str, str]` | 删除整个字典 |
| 2 | **L129-131** | `load_agent_channels()` | 删除整个函数 |
| 3 | **L134-136** | `save_agent_channels()` | 删除整个函数 |
| 4 | **L139-141** | `set_agent_channel()` | 删除整个函数 |
| 5 | **L144-146** | `get_agent_channel()` | 删除整个函数 |
| 6 | **L149-151** | `reset_agent_channel()` | 删除整个函数 |

- **连带删除引用：**
  - `server/handler.py` 中所有 `persistence.get_agent_channel()` 调用（L205, L368, L5159, L640 等）
  - `server/handler.py` 中所有 `persistence.set_agent_channel()` 调用（L393, L683, L5749 等）
  - `server/handler.py` 中所有 `persistence.save_agent_channels()` 调用（L394, L684, L5760 等）
  - `server/__main__.py` L397-399 引用

#### 🅿️1-5: 新增工作室元数据持久化（R82-B）

- **位置：** `server/persistence.py` — 新增 `workspace_store.py` 或追加到现有函数

新增函数：
```python
# 工作室元数据存储（时间切片模型）
_workspace_meta: dict[str, dict] = {}

def save_workspace_meta(data_dir: Path, meta: dict) -> None:
    """持久化工作室元数据。"""
    ...

def load_workspace_meta(data_dir: Path) -> dict:
    """加载所有工作室元数据。"""
    ...

def get_workspace_meta(ws_id: str) -> dict | None:
    """获取单个工作室元数据。"""
    ...
```

---

### 1.3 protocol.py — 改动点

#### 🅿️0-5: 删除频道切换消息常量

| # | 行号 | 常量 | 删除方式 |
|:-:|:----:|:-----|:---------|
| 1 | **L82-84** | `MSG_SET_ACTIVE_CHANNEL` | 删除 L82-84 整行 |
| 2 | **L84** | `MSG_CHANNEL_UPDATED` | 删除该行 |
| 3 | **L150** | `FIELD_ACTIVE_CHANNEL` | 删除该行 |

- **删除后清理：**
  - 检查 handler.py 和 __main__.py 中 `p.MSG_SET_ACTIVE_CHANNEL` 的所有引用（~10 处）并删除对应代码
  - 检查 `p.FIELD_ACTIVE_CHANNEL` 的所有引用（L205, L264, L395 等）并删除对应代码

---

### 1.4 workspace.py — 改动点

#### 🅿️1-6: 保留 Workspace 模型但标记部分字段 deprecated

- **位置：** `server/workspace.py` L178-191
- **当前模型：** Workspace 是频道模型（有 members, state, 活跃频道状态机）
- **本轮改动：** 保留 Workspace 模型作为**元数据容器**。不删除 `Workspace` dataclass — 它仍然管理成员、管理员、生命周期状态。
- **新增字段：** 为时间切片索引模型增加元数据字段

```python
@dataclass
class Workspace:
    id: str
    name: str
    owner_id: str
    owner_name: str
    
    # ── 生命周期（保留） ──
    state: WorkspaceState = WorkspaceState.ACTIVE
    created_at: float = 0.0
    closed_at: float | None = None
    
    # ── 成员管理（保留） ──
    members: set[str] = field(default_factory=set)
    admin_ids: set[str] = field(default_factory=set)
    
    # ── R82 新增：时间切片索引元数据 ──
    pipeline_id: str = ""                    # 关联管线 ID（如 "R82"）
    roles: list[str] = field(default_factory=list)  # 角色清单
    workflow_url: str = ""                   # WORK_PLAN URL
    inbox_message_count: int = 0             # 该工作室内 inbox 消息总数（缓存）
    
    # ── Deprecated（保留字段但不再使用于频道切换） ──
    token_ring: TokenRing = field(default_factory=TokenRing)  # 保留，历史兼容
    last_active_at: float = 0.0              # 保留，用于闲置归档
    closing_acks: set[str] = field(default_factory=set)  # 保留，关闭流程
```

- **`create_workspace()` 行为变更：**
  - 旧：创建频道（实际上 workspace 一直是元数据 + 消息路由标识）
  - 新：创建时间切片标记 — 只记录元数据，不再关联频道路由
  - 现有 `ws_mod.create_workspace()` 函数签名保持不变（只新增参数）

#### 🅿️1-7: 新增 `!workspace view` 查询路由

- **位置：** `server/handler.py` — 在 `_ADMIN_COMMANDS` 中新增或扩展现有命令
- 工作室查看改为从 `message_store` 按时间区间 + inbox 通道前缀查询

---

### 1.5 config.py — 改动点

#### 🅿️2-1: 清理通道配置项

- **位置：** `server/config.py`
- **当前：** 无明确的"默认频道"配置项（系统默认使用 p.LOBBY）
- **本轮：** 确认无需要删除的配置项。`BROADCAST_ADMINS`、`ADMIN_AGENTS` 保留不变。在注释中标注通道相关配置仅影响真人侧。
- **净改动：** 0 行（只加注释）

---

## 2. 删除路径 / 保留路径决策树

### 2.1 广播路由决策树

```
收到消息 → handle_broadcast()
│
├─ channel == REGISTRATION_CHANNEL?
│   └─ ✅ 保留 — 新 bot 注册流程
│
├─ channel == _admin?
│   ├─ ✅ 保留 — admin 继续接收 ! 命令（真人侧）
│   └─ ❌ 删除 — bot 不再接收 _admin 消息
│
├─ channel startswith '_inbox:' ?
│   └─ ✅ 保留核心逻辑 — INBOX-ONLY 主通道（L5277-5313 不动）
│
├─ channel startswith 'ws:' / WORKSPACE_ID_PREFIX?
│   ├─ 发送者角色 == admin？
│   │   └─ ✅ 保留 — admin 可在工作室发消息
│   ├─ 发送者角色 == member（真人）？
│   │   └─ ✅ 保留 — 真人可在工作室频道聊天
│   └─ 发送者 == bot？
│       └─ ❌ 删除广播 — bot 不应在工作室频道发消息
│
├─ channel == LOBBY?
│   ├─ 大厅路由分类 📢/📋/@ 保留
│   ├─ ✅ 保留 — 真人 admin 的公告/点名
│   ├─ ✅ 保留 — @真人 的消息路由
│   └─ ❌ 删除 — bot 不被路由到 lobby 消息（非 bot 通道）
│
└─ 未知频道回退？
    └─ ❌ 删除 — 不再自动路由到活跃工作区
```

### 2.2 函数级别决策树

| 函数 | 决策 | 理由 |
|:-----|:----|:------|
| `_broadcast_active_channel()` | **删除** 🅿️0 | inbox-only 不需要频道切换 |
| `_channel_ack_timeout()` | **删除** 🅿️0 | 同上 |
| `_resolve_ws_by_ack_task_id()` | **删除** 🅿️0 | 同上 |
| `handle_broadcast()` | **简化** 🅿️0 | 删除bot路由分支，保留真人路由 |
| `_cmd_create_workspace()` | **简化** 🅿️1 | 删除频道切换代码，保留创建逻辑 |
| `_cmd_close_workspace()` | **保留** ✅ | 保留关闭流程，删除频道切换广播 |
| `_cmd_rollcall()` | **简化** 🅿️1 | 删除 `_broadcast_active_channel` 调用 |
| `_cmd_pipeline_start()` | **简化** 🅿️1 | 删除频道切换，改用 inbox 派活 |
| `handle_agent_card_register()` | **简化** 🅿️1 | 删除注册后频道切换 |
| `_broadcast_to_channel()` | **保留** ✅ | 用于 _admin 频道系统消息，不删除 |
| `_is_nonsense()` | **保留** ✅ | 仅用于非-inbox 消息过滤 |
| `_is_duplicate()` | **保留** ✅ | 同上 |
| `_classify_lobby_message()` | **保留** ✅ | 大厅路由逻辑保留给真人 |
| `set_agent_channel()` (persistence) | **删除** 🅿️0 | 不再需要活跃频道持久化 |
| `get_agent_channel()` (persistence) | **删除** 🅿️0 | 同上 |
| `save_agent_channels()` (persistence) | **删除** 🅿️0 | 同上 |
| `load_agent_channels()` (persistence) | **删除** 🅿️0 | 同上 |
| `reset_agent_channel()` (persistence) | **删除** 🅿️0 | 同上 |

### 2.3 协议级别决策树

| 协议常量 | 决策 | 理由 |
|:---------|:----|:------|
| `MSG_SET_ACTIVE_CHANNEL` | **删除** 🅿️0 | inbox-only 不需要 |
| `MSG_CHANNEL_UPDATED` | **删除** 🅿️0 | 同上 |
| `FIELD_ACTIVE_CHANNEL` | **删除** 🅿️0 | 同上 |
| `FIELD_CHANNEL` | **保留** ✅ | 仍然用于标识消息目标通道 |
| `MSG_MEMBER_CHANGED` | **保留** ✅ | 工作室成员变更通知保留 |
| `MSG_TASK_ASSIGNMENT` | **保留** ✅ | 任务分配通过 inbox 进行 |
| `MSG_TASK_ACK` | **保留** ✅ | 任务确认通过 inbox 进行 |
| `MSG_BROADCAST` | **保留** ✅ | 通用广播类型保留 |

---

## 3. 工作室时间切片模型

### 3.1 数据结构

```python
# workspace.py — Workspace dataclass 新增字段
@dataclass
class Workspace:
    # ... 现有字段 ...
    
    # ── R82 B: 时间切片索引元数据 ──
    pipeline_id: str = ""                    # 管线 ID（如 "R82"）
    roles: list[str] = field(default_factory=list)  # ["pm","architect","developer","reviewer","qa"]
    workflow_url: str = ""                   # WORK_PLAN.md URL
    inbox_message_count: int = 0             # 缓存的消息计数
```

### 3.2 创建流程

```
!create_workspace R82 --members xxx
  → _cmd_create_workspace()
  → ws_mod.create_workspace()        # 保留原函数签名
  → 补充元数据: workspace.pipeline_id = "R82"
  → 不再调用 _broadcast_active_channel()  ❌
  → 不再调用 persistence.set_agent_channel() ❌
  → 返回: "✅ 工作室 R82 已创建（时间标记: <ts>）"
```

### 3.3 查看流程

```
!workspace view ws:xxx
  → 从 workspace 元数据获取 created_at / closed_at
  → 从 message_store 按时间区间查询:
    ms.query_by_time(channel_startswith="_inbox:", ts_from=created_at, ts_to=closed_at)
  → 返回: 该工作室时间段内的 inbox 消息列表
```

### 3.4 工作室 = 索引而非频道

- 旧：`ws:xxx` 是 bot 切换到的**频道**
- 新：`ws:xxx` 是时间段**索引**，bot 不"进入"工作室
- 创建时只需要 `!pipeline_start R82` 或 `!create_workspace` → 记录元数据
- 管线 Step 任务通过 **inbox 消息派发**，不触发任何频道切换

---

## 4. 兼容性分析

### 4.1 对现有 bot 连接的影响

| bot | 旧行为 | 新行为 | 是否兼容 |
|:---|:-------|:-------|:--------|
| **inbox 收消息** | 通过 `_inbox:xxx` 收 | 不变 | ✅ 完全兼容 |
| **inbox 发消息** | 发到 `_inbox:xxx` | 不变 | ✅ 完全兼容 |
| **lobby 收消息** | 收到大厅广播 | **不再收到** | ✅ 不破坏收发 inbox 消息 |
| **workspace 收消息** | 收到工作室频道广播 | **不再收到** | ✅ 不破坏收发 inbox 消息 |
| **admin 收消息** | 收到系统通知 | **不再收到** | ✅ 不破坏收发 inbox 消息 |
| **查询命令** | 发到 admin 频道 | 发到 `_inbox:server` | ✅ 新方式工作，旧方式仍可用（admin 命令路由保留） |
| **活跃频道** | 维护 active_channel | 不再维护 | ✅ 客户端忽略 set_active_channel 消息即可 |

### 4.2 对旧客户端协议的影响

| 协议消息 | 旧客户端 | 新客户端 |
|:---------|:---------|:---------|
| `MSG_SET_ACTIVE_CHANNEL` | 需要处理频道切换 | **不再收到** — 删除该消息 |
| `MSG_CHANNEL_UPDATED` | 需要返回确认 | **不再需要** — 删除该消息 |
| `type: "broadcast"` — lobby 消息 | 收到大厅广播 | **不再收到** — 但客户端兼容 |
| `type: "broadcast"` — inbox 消息 | 正常收 | **正常收** ✅ |

### 4.3 对客户端代码的影响

- **本轮不改 `clients/`** — 但注明 Step 3 可能需要的最小改动：
  - 删除 `switch_channel()` 方法（如有）
  - 删除 `current_channel` 属性（如有）
  - 新增 `query(command)` 方法：发消息到 `_inbox:server` 并等待回复

### 4.4 对 admin 频道的影响

- 系统进度通知**继续发到 `_admin`**（L381-385 保留 ✅）
- Bot 不读 `_admin`（bot 不再收到 `_admin` 消息 ✅）
- Web 端 admin tab **正常工作** ✅

### 4.5 对 message_store 的影响

- inbox 消息继续写入 `message_store`（L5292, L5403-5414 保留 ✅）
- 工作室时间切片查询从 message_store 按时间区间筛选（R76 已实现）

### 4.6 对认证层的影响

- **完全不动** — `auth.py`、`api_key` 体系不受影响 ✅
- 现有 bot 无需改 apikey/注册流程 ✅

---

## 5. 风险与缓解

| # | 风险 | 等级 | 影响 | 缓解措施 |
|:-:|:-----|:----|:-----|:---------|
| 1 | **Bot 连接兼容** — 旧 bot（小开/爱泰/泰虾/小爱）部署后收不到原本的 lobby/workspace 广播 | 🔴 | 低 — 这些广播不是必要功能 | 部署后验证 inbox 收发正常；旧 bot 忽略不工作正常的频道也不影响核心功能 |
| 2 | **Pipeline 状态机依赖活跃频道** — `pipeline_start` 中调用了 `_broadcast_active_channel`，删除后可能漏掉角色通知 | 🔴 | 中 — 管线 Step 启动可能失效 | 改为通过 inbox 派活：`_send_to_inbox(agent_id, "【R82 Step N 任务】...")`，不需要频道切换 |
| 3 | **`!` 命令入口变化** — 旧 bot 通过 admin 频道执行 `!` 命令，新 bot 通过 `_inbox:server` | 🟡 | 低 — 两条路由均可用 | Admin 频道 `!` 命令路由**保留**（L5253-5274 保留），`_inbox:server` 新增查询路由仅为补充 |
| 4 | **删除 `FIELD_ACTIVE_CHANNEL` 影响 auth_ok 报文** — L205 在 auth 成功响应中包含了 `active_channel` | 🟡 | 低 | 从 auth_ok 报文中删除 `active_channel` 字段；旧客户端不使用该字段也可正常工作 |
| 5 | **`_broadcast_active_channel` 在 R57 rollcall 中被依赖** — L1100/L1134 被点名流程调用 | 🟡 | 中 | 点名用 inbox 通知替代——`_send_to_inbox(member_id, "📋 {sender_name} 点名xxx")` |
| 6 | **Web 端查看工作区历史** — Web 端看工作室消息改为从 inbox 筛选 | 🟡 | 低 | R76 已实现时间切片查询 |
| 7 | **Workspace 删除时清理** — `_cmd_close_workspace` L5979 清理 `_channel_ack_state` | 🟢 | 低 | 删除关联代码即可 |
| 8 | **`connections` 中非 bot 判定** — handler 中没有明确的"是否是 bot"标志 | 🟡 | 低 | 通过 role != admin + 不在 _r72_users 判断 |

---

## 6. 改动统计

| 文件 | 删除行 | 新增行 | 净变化 |
|:-----|:------:|:------:|:------:|
| `server/handler.py` | ~160 行 | ~20 行 | **-140 行** |
| `shared/protocol.py` | ~5 行 | 0 | **-5 行** |
| `server/persistence.py` | ~30 行 | ~15 行 | **-15 行** |
| `server/workspace.py` | ~10 行 | ~30 行 | **+20 行** |
| `server/__main__.py` | ~15 行 | 0 | **-15 行** |
| `server/config.py` | 0 | 注释 | **0 行** |
| **合计** | **~220 行** | **~65 行** | **-155 行净删** |

---

## 附：术语对照

| 旧术语 | 新术语 | 说明 |
|:-------|:-------|:------|
| 活跃频道 (active_channel) | （废弃） | Bot 不再维护频道概念 |
| 频道切换 (channel switch) | （废弃） | 不再需要切换 |
| 工作室 = 频道 | 工作室 = 时间切片索引 | 仅是元数据 + 时间区间 |
| inbox 消息 + admin 消息 | inbox 消息 | Bot 只看 inbox |
| `MSG_SET_ACTIVE_CHANNEL` | （删除） | 不再需要 |
| bot 收到大厅消息 | bot 只在 inbox | 其他人发 inbox 才收 |

---

## 附：改动执行顺序（给 Step 3 开发者）

**建议的执行顺序（按依赖关系）：**

```
Phase 1 — 协议层清理（无运行时影响）
  └── 1. protocol.py: 删除 MSG_SET_ACTIVE_CHANNEL / MSG_CHANNEL_UPDATED / FIELD_ACTIVE_CHANNEL

Phase 2 — 持久化层清理 + 新增
  └── 2. persistence.py: 删除活跃频道函数，新增 workspace 元数据函数

Phase 3 — 核心路由重写（handle_broadcast 逻辑更改）
  ├── 3. handler.py: 删除 _broadcast_active_channel() + 关联函数
  ├── 4. handler.py: 删除 handle_broadcast 中 bot 的路由分支
  ├── 5. handler.py: 删除 8 个 _broadcast_active_channel 调用点
  └── 6. handler.py: 删除注册/创建中的频道切换代码

Phase 4 — 边缘清理
  ├── 7. __main__.py: 删除 set_active_channel handler
  └── 8. workspace.py: 新增时间切片字段

Phase 5 — 验证
  └── 9. grep 零匹配验证：
       grep -rn 'MSG_SET_ACTIVE_CHANNEL\|_broadcast_active_channel\|get_agent_channel\b\|set_agent_channel\b' server/ shared/ | grep -v '^Binary'
```
