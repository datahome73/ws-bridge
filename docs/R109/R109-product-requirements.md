# R109 — 架构大重构：ws-server / web-ui 彻底分离 🏗️

> **版本：** v2.0
> **日期：** 2026-07-13
> **状态：** 📝 需求文档
> **轮次：** R109
> **优先级：** P0（架构级）
> **前置条件：** R108 已闭环 ✅

---

## 一、背景

### 1.1 当前架构的问题

R101 实现了**进程级解耦**（Supervisor 双进程），但**代码级仍是紧耦合**。

```
ws-bridge/
├── server/                     ← 一个 package 装两个世界
│   ├── __main__.py             WSS 入口（也挂 /api/status 等）
│   ├── web_service.py          Web HTTP 入口（8766，独立进程）
│   ├── main.py                 WSS 核心逻辑（3626 行）
│   ├── web_viewer.py           Web UI 所有 HTTP handler（722 行）
│   ├── templates.py            Web HTML/JS/CSS
│   ├── workspace_api.py        Web HTTP workspaces API
│   ├── workspace.py            workspace 模型（WSS + Web 共用）
│   ├── message_store.py        SQLite 消息存储（共用）
│   ├── persistence.py          JSON 持久化（共用）
│   ├── auth.py                 认证（WSS + Web 混在一起）
│   └── ...
└── data/                       ← SQLite DB
```

**耦合表现：**

| 文件 | import 来源 | 问题 |
|:-----|:------------|:-----|
| `web_service.py` | `from .config`, `from . import web_viewer`, `from . import persistence, message_store, state` | 5 处 `server.` 依赖 |
| `web_viewer.py` | `from . import auth, config, persistence, workspace, message_store, main` | 6 处 `server.` 依赖 |
| `workspace_api.py` | `from . import workspace` | 寄生在 server package |

R109 的目标是让 `web-ui/` **零** `ws-server/` import，两者只在 data 层面打交道。

### 1.2 命名规范

| 名称 | 说明 | 目录 |
|:-----|:------|:-----|
| **WSS 核心** | WebSocket 通信、消息路由、管线编排、命令系统 | `ws-server/` |
| **Web 服务** | HTTP 页面、inbox 查看、GitHub OAuth | `web-ui/` |
| **数据层** | SQLite DB + JSON 文件 | `ws-server/` 拥有，`web-ui/` 只读副本 |

> ⚠️ 两套代码之间没有任何 `import` 依赖，只在 data 目录（`./data/`）层面通过 SQLite/JSON 文件产生关联。

---

## 二、架构目标

### 2.1 架构变化

```
移植前:
  ws-bridge/
  ├── server/                     ← 混合 package
  │   ├── __main__.py             WSS 入口
  │   ├── main.py                 WSS 核心
  │   ├── web_service.py          Web 入口
  │   ├── web_viewer.py           Web handler
  │   ├── templates.py            Web 模板
  │   ├── workspace_api.py        Web API
  │   ├── message_store.py        [共用数据层]
  │   ├── persistence.py          [共用持久化]
  │   ├── auth.py                 [共用认证——逻辑混乱]
  │   ├── config.py               [共用配置]
  │   ├── workspace.py            [共用模型]
  │   ├── state.py                [WSS 专用]
  │   ├── auto_router.py          [WSS 专用]
  │   └── commands/               [WSS 专用]
  ├── gateway-plugin/
  └── clients/

移植后:
  ws-bridge/
  ├── ws-server/                  ← WSS 核心（独立 package）
  │   ├── __init__.py
  │   ├── __main__.py             WSS 入口（端口 8765）
  │   ├── main.py                 WSS 核心路由（精简）
  │   ├── protocol.py             bot-WSS 通信协议
  │   ├── config.py               [WSS 配置]
  │   ├── auth.py                 [WSS 认证 — api_key, agent level]
  │   ├── message_store.py        [数据写入 + 读取]
  │   ├── persistence.py          [JSON 持久化]
  │   ├── workspace.py            [workspace 完整模型]
  │   ├── state.py                共享状态
  │   ├── auto_router.py          管线调度
  │   ├── agent_card.py           Agent Card
  │   ├── command_utils.py        命令路由工具
  │   ├── commands/               命令系统
  │   ├── pipeline_context.py     管线上下文
  │   ├── pipeline_sync.py        Git 同步
  │   ├── task_store.py           任务状态机
  │   ├── timeout_tracker.py      超时管理
  │   └── audit.py                审计日志
  │
  ├── web-ui/                     ← Web 服务（独立 package，零 ws-server import）
  │   ├── __init__.py
  │   ├── __main__.py             Web 入口（端口 8766）
  │   ├── handlers.py             HTTP handler（原 web_viewer.py）
  │   ├── templates.py            HTML 模板（纯数据，不变）
  │   ├── config.py               [Web 配置 — 端口、OAuth]
  │   ├── auth.py                 [Web 认证 — session、GitHub OAuth、bind code]
  │   ├── message_store.py        [只读副本 — 仅 inbox/chat 查询]
  │   └── persistence.py          [Web 专用持久化 — sessions、bind codes]
  │
  ├── gateway-plugin/
  └── clients/
```

### 2.2 减法原则 — 两边都做减法

#### Web 减法

Web 定位回归本质：
- 📋 **只读 inbox 查看器** — 展示 bot 间收件箱消息
- 💬 **聊天历史查看** — 按频道查看历史消息
- 🔑 **GitHub OAuth 登录** — 身份验证

**去掉：**
- ❌ **admin 频道** — 自动化管线后无意义
- ❌ **📊 进度 Tab** — 管线状态已通过 bot 回复呈现
- ❌ **Workspace 管理** — Web 端不再展示/管理工作区
- ❌ **绑定码体系** — 纯 GitHub OAuth 取代
- ❌ **大厅** — 不再需要

#### WSS 减法

WSS 配置回归精简，去掉历史残留：
- ❌ **`ADMIN_AGENTS`** — 没有 admin_bot 了
- ❌ **`APP_ID`** — 不再需要
- ❌ **`CHAT_LOG_DIR`** — write_chat_log 已移除（R101）
- ❌ **GitHub OAuth 配置** — 属于 Web，不放在 WSS
- ❌ **`PIPELINE_ARCH_FROM_NAME`** — 自动化管线不需要特殊触发名
- ❌ **`DISPATCH_SENDER_ID` / `PIPELINE_PM_AGENT_ID`** — 合并为 `PM_AGENT_ID`

#### 数据层修复：管线消息入库

自动派活后 inbox 消息没有落库，Web 端收件箱看不到管线消息。根因是 `_auto_dispatch()` 和 `_handle_server_relay()` 的 to_agent 转发路径直接调 `_send_to_agent()`，缺了 `save_message()`。

**修复点：**

| 位置 | 文件 | 行号区间 | 修复 |
|:-----|:------|:---------|:------|
| `_auto_dispatch()` | `main.py` | 2511-2520 | payload 构造后、`_send_to_agent()` 前，调 `ms.save_message(channel=f"_inbox:{target_agent_id}")` |
| `_handle_server_relay()` to_agent 分支 | `main.py` | 2588-2596 | `relay_payload` 发送前，调 `ms.save_message(channel=f"_inbox:{to_agent}")` |

### 2.3 目标清单

| # | 目标 | 衡量标准 |
|:-:|:-----|:---------|
| 1 | `ws-server/` 独立 — 从 `server/` 重命名，纯 WSS 核心 | `ws-server/` 无任何 web 相关文件 |
| 2 | `web-ui/` 独立 — 零 `ws-server` import | `grep -rn "from ws-server\|import ws-server" web-ui/` → 0 |
| 3 | `web-ui/` 零 `server` import | `grep -rn "from server\|import server" web-ui/` → 0 |
| 4 | `ws-server/` 零 `web-ui` import | `grep -rn "from web-ui\|import web-ui" ws-server/` → 0 |
| 5 | `auth.py` 一分为二 | `ws-server/auth.py` 只做 api_key 认证；`web-ui/auth.py` 只做 session/OAuth |
| 6 | `message_store.py` 两份 | `ws-server/message_store.py`（读写），`web-ui/message_store.py`（只读） |
| 7 | `persistence.py` 分开 | `ws-server/persistence.py`（全量），`web-ui/persistence.py`（仅 sessions/bind codes） |
| 8 | Web 做减法 — 无 admin 频道、无 workspace 管理、无绑定码 | 前端页面不再展示这些功能 |
| 9 | Docker & Supervisor 正常 | 双进程正常启动 |
| 10 | 全链路回归 | bot 通信正常、Web 页面可访问 |

### 2.4 非目标

- ❌ 不改动消息存储格式（`messages.db` schema 不变）
- ❌ 不改动 bot 通信协议（`protocol.py` 不变）
- ❌ 不改动 WSS 核心消息路由逻辑（`main.py` 逻辑不变）
- ❌ 不改动管线/命令系统
- ❌ 不引入新的外部依赖
- ❌ 不重写 Web 前端 UI（仅删减功能）

---

## 三、方案

### 3.1 文件迁移矩阵

#### WSS 核心 → `ws-server/`

| 原路径 | 新路径 | 变更内容 |
|:-------|:-------|:---------|
| `server/__main__.py` | `ws-server/__main__.py` | git mv + 更新 import |
| `server/main.py` | `ws-server/main.py` | git mv + import 改绝对路径 |
| `server/config.py` | `ws-server/config.py` | git mv，保留 WSS 配置项 |
| `server/auth.py` | `ws-server/auth.py` | git mv + **只保留 WSS 认证逻辑**（api_key、agent level、用户管理） |
| `server/message_store.py` | `ws-server/message_store.py` | git mv，全量（读写） |
| `server/persistence.py` | `ws-server/persistence.py` | git mv，全量 JSON 持久化 |
| `server/workspace.py` | `ws-server/workspace.py` | git mv，完整 workspace 模型 |
| `server/state.py` | `ws-server/state.py` | git mv |
| `server/auto_router.py` | `ws-server/auto_router.py` | git mv |
| `server/agent_card.py` | `ws-server/agent_card.py` | git mv |
| `server/command_utils.py` | `ws-server/command_utils.py` | git mv |
| `server/commands/` | `ws-server/commands/` | git mv |
| `server/pipeline_context.py` | `ws-server/pipeline_context.py` | git mv |
| `server/pipeline_sync.py` | `ws-server/pipeline_sync.py` | git mv |
| `server/task_store.py` | `ws-server/task_store.py` | git mv |
| `server/timeout_tracker.py` | `ws-server/timeout_tracker.py` | git mv |
| `server/audit.py` | `ws-server/audit.py` | git mv |

#### Web 服务 → `web-ui/`

| 原路径 | 新路径 | 变更内容 |
|:-------|:-------|:---------|
| `server/web_service.py` | `web-ui/__main__.py` | 重命名 + 提取 Web 配置 + 简化启动 |
| `server/web_viewer.py` | `web-ui/handlers.py` | 重命名 + **减法：去掉 admin 频道、workspace 管理** |
| `server/templates.py` | `web-ui/templates.py` | 重命名 + 前端减法 |
| `server/workspace_api.py` | 合并到 `web-ui/handlers.py` | 仅保留 `/api/workspaces` 端点（只读）；或直接去掉 |
| — | `web-ui/auth.py` | **新建** — 从原 auth.py 提取 Web 认证逻辑（sessions、GitHub OAuth、bind codes） |
| — | `web-ui/message_store.py` | **新建** — 只读副本（仅 `get_messages_since`、`get_messages_by_channel`、`search_messages` 等读函数） |
| — | `web-ui/persistence.py` | **新建** — Web 专用（`get_web_sessions`、`set_web_sessions`、`save_web_sessions`、`get_web_bind_codes`、`save_web_bind_codes`） |
| — | `web-ui/config.py` | **新建** — Web 配置（端口 8766、OAuth 配置、`DATA_DIR`） |

#### 删除

| 文件 | 原因 |
|:-----|:------|
| `server/`（整个目录） | 已拆分为 ws-server/ + web-ui/ |
| `entrypoint.py` | Railway 已不再使用，不需要 |
| `server/templates.py.bak` | 备份文件 |
| `server/web_service.py` | 变成 `web-ui/__main__.py` |
| `server/web_viewer.py` | 变成 `web-ui/handlers.py` |

### 3.2 依赖关系变化

```
当前:
  server/web_service.py
    ├── from .config import DATA_DIR, HOST, PORT     → server package
    ├── from . import web_viewer                     → server package
    ├── from . import persistence                    → server package
    ├── from . import message_store                  → server package
    └── from . import state                          → server package（仅 _r72_users）

移植后:
  web-ui/__main__.py
    ├── from .config import ...         → 本 package
    ├── from . import handlers          → 本 package
    ├── from . import persistence       → 本 package（Web 专用）
    ├── from . import message_store     → 本 package（只读副本）
    └── (无任何 ws-server import)       → ✅ 独立

  web-ui/handlers.py
    ├── from . import auth              → 本 package（Web 认证）
    ├── from .config import ...         → 本 package
    ├── from . import persistence       → 本 package
    ├── from . import message_store     → 本 package
    └── ws-server 的 /api/status（HTTP 轮询）→ ✅ 协议层，非 import
```

### 3.3 auth.py 拆分明细

#### `ws-server/auth.py`（WSS 认证）

保留原 `auth.py` 中与 WSS 相关的逻辑：

| 函数/数据 | 说明 |
|:----------|:------|
| `API_KEY_PREFIX`, `WEB_CODE_PREFIX` | 常量（api key 部分保留，bind code 部分移到 web-ui） |
| `generate_api_key()` | 生成新的 api_key |
| `verify_api_key(api_key)` | 验证 api_key 有效性 |
| `get_users()` | 获取所有用户 |
| `get_level(agent_id)` | 获取 agent 等级（L0-L4） |
| `set_level(agent_id, level)` | 设置 agent 等级 |
| `get_agent_name(agent_id)` | 获取 agent 显示名 |
| `get_role(agent_id)` | 获取 agent 角色 |
| `set_role(agent_id, role)` | 设置 agent 角色 |
| `set_workspace_admin()` | workspace 管理员管理 |
| `get_approved_users()` | 获取批准用户列表 |

#### `web-ui/auth.py`（Web 认证）

从原 `auth.py` 提取 Web 相关逻辑，并简化：

| 函数/数据 | 说明 |
|:----------|:------|
| `WEB_CODE_PREFIX` | 绑定码前缀（简化——如需要） |
| `generate_web_bind_code()` | 生成绑定码（简化——备选方案） |
| `create_web_bind_code(code)` | 创建绑定码 |
| `approve_web_bind_code(code, name)` | 审批绑定码 |
| `validate_token(token)` | 验证 Web session token |
| `get_web_sessions()` | 获取所有 Web session |

> 🔑 **GitHub OAuth** 认证逻辑保留在 `web-ui/handlers.py` 中（`handle_github_login` / `handle_github_callback`），因为它是 Web 独有且与 handler 逻辑紧密关联，不需要单独提取到 auth.py。

### 3.4 message_store.py 拆分明细

#### `ws-server/message_store.py`（全量）

保留现有全部函数：
- `init_db(data_dir)` — 初始化 DB
- `save_message(data_dir, message)` — 保存消息
- `get_messages_since(data_dir, since, limit, channel)` — 时间查询
- `get_messages_by_channel(data_dir, channel, limit)` — 频道查询
- `get_messages_by_channel_pattern(data_dir, pattern, limit)` — 模式查询
- `search_messages(query, data_dir, ...)` — 搜索
- `get_messages_since_by_agent(data_dir, agent_id, since)` — 按 agent 查询
- `get_message_count(data_dir)` — 计数

#### `web-ui/message_store.py`（只读副本）

仅保留读函数：

```python
"""Read-only message store — queries the same SQLite DB."""
import sqlite3
import time
from pathlib import Path

def init_db(data_dir: Path) -> None:
    """Ensure DB exists (no-op if already exists)."""
    ...

def get_messages_since(data_dir, since, limit=50, channel=None):
    """Return messages after timestamp (用于 5s 轮询)."""
    ...

def get_messages_by_channel(data_dir, channel, limit=50):
    """Return latest messages in a channel."""
    ...

def get_messages_by_channel_pattern(data_dir, pattern, limit=50):
    """Return messages by channel LIKE pattern."""
    ...

def search_messages(query, data_dir, limit=50, channel=None, sender=None):
    """Full-text search."""
    ...

def get_messages_since_by_agent(data_dir, agent_id, since):
    """Return messages for a specific agent."""
    ...
```

### 3.5 persistence.py 拆分明细

#### `ws-server/persistence.py`（全量）

保留全部函数：
- `load/save_*` — approved_users, web_sessions, api_keys, web_bind_codes, agents_channels
- `resolve_inbox_owner()` — inbox 渠道解析
- 所有 workspace 相关的持久化

#### `web-ui/persistence.py`（Web 专用）

仅保留 Web 需要用到的函数：

```python
"""Web-specific persistence — sessions + bind codes only."""
import json
import threading
from pathlib import Path

_lock = threading.Lock()
_web_sessions: dict = {}
_web_bind_codes: dict = {}
_BIND_CODES_FILE = "web_bind_codes.json"
_SESSIONS_FILE = "web_sessions.json"

def load_web_sessions(data_dir: Path) -> None: ...
def save_web_sessions(data_dir: Path) -> None: ...
def get_web_sessions() -> dict: ...
def set_web_sessions(sessions: dict) -> None: ...
def load_web_bind_codes(data_dir: Path) -> None: ...
def save_web_bind_codes(data_dir: Path) -> None: ...
def get_web_bind_codes() -> dict: ...
```

### 3.6 config.py 拆分明细

#### `ws-server/config.py` → 做减法

保留 WSS 核心配置，**去掉所有不需要的项**：

```python
"""WSS server config — minimal, no web config leak."""
import os
from pathlib import Path

# ── 基础 ──
HOST = os.environ.get("WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_PORT", "8765"))
DATA_DIR = Path(os.environ.get("WS_DATA_DIR", "./data"))

# 隐藏的系统 agent（不在 /api/status 中暴露）
HIDDEN_AGENTS: set[str] = set(
    filter(None, os.environ.get("WS_HIDDEN_AGENTS", "bot-hermes").split(","))
)

# ── PM inbox 地址（唯一需要的地址）──
# Server 将 ACK/完成/退回/失败通知转发至此收件箱
PM_AGENT_ID: str = os.environ.get("WS_PM_AGENT_ID", "")

# ── 中继通道 ──
SERVER_INBOX_CHANNEL: str = "_inbox:server"

# ── 自动派活 ──
AUTO_DISPATCH_ENABLED: bool = True

# ── 管线配置 ──
PIPELINE_STEP_MAP: dict[str, dict] = {
    "step1": {"role": "operations", "name": "管线启动",       "timeout_hours": 2.0},
    "step2": {"role": "arch",       "name": "技术方案",       "timeout_hours": 6.0},
    "step3": {"role": "dev",        "name": "编码",           "timeout_hours": 12.0},
    "step4": {"role": "review",     "name": "代码审查",       "timeout_hours": 4.0},
    "step5": {"role": "qa",         "name": "测试验证",       "timeout_hours": 6.0},
    "step6": {"role": "operations", "name": "合并部署归档",   "timeout_hours": 2.0},
}
GIT_REMOTE_URL: str = os.environ.get("WS_BRIDGE_GIT_REMOTE", "https://github.com/datahome73/ws-bridge.git")
ENABLE_GIT_SYNC: bool = os.environ.get("R65_ENABLE_GIT_SYNC", "1") == "1"
REPO_PATH: str = os.environ.get("R65_REPO_PATH", "/opt/data/ws-bridge")
```

**删除的配置项及原因：**

| 配置项 | 原因 |
|:-------|:------|
| `HTTP_PORT` | Web 的配置，移到 `web-ui/config.py` |
| `APP_ID` | 不再需要 |
| `CHAT_LOG_DIR` | write_chat_log 已移除（R101） |
| `ADMIN_AGENTS` | 没有 admin_bot 了 |
| GitHub OAuth 全部（6 项） | Web 的认证，移到 `web-ui/config.py` |
| `WS_ENV` / `IS_PRODUCTION` | Web 的环境标识 |
| `PIPELINE_ARCH_FROM_NAME` | 自动化管线，不再需要特殊触发名 |
| `PIPELINE_ROLE_OVERRIDES` | 自动化管线固定角色映射 |
| `PIPELINE_PM_NAME` | 自动化后 PM 名固定 |
| `DISPATCH_SENDER_ID` | 与 `PIPELINE_PM_AGENT_ID` 合并为 `PM_AGENT_ID` |
| `PIPELINE_PM_AGENT_ID` | 重命名为 `PM_AGENT_ID` |
| `WORK_PLAN_REPO_URL` | 自动化管线不再通过 URL 拉取 WORK_PLAN |
| `ENABLE_VALIDATION_HOOK` 等（3 项） | 验证钩子未实际投入使用 |
| `GIT_SYNC_INTERVAL` / `GIT_SYNC_BRANCH` / `GIT_SYNC_FALLBACK` | 保留默认值，去掉可配性

#### `web-ui/config.py`

新建，仅 Web 配置：

```python
HOST = os.environ.get("WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8766"))
DATA_DIR = Path(os.environ.get("WS_DATA_DIR", "./data"))  # 与 ws-server 相同路径
GITHUB_OAUTH_CLIENT_ID = ...
GITHUB_OAUTH_CLIENT_SECRET = ...
GITHUB_OAUTH_REDIRECT_URI = ...
OAUTH_NAME_MAP: dict[str, str] = ...
WS_ENV = os.environ.get("WS_ENV", "dev")
```

### 3.7 Bot 在线状态传递

**不用 HTTP 轮询，用文件传递。**

ws-server 定时（每 10 秒）将当前在线 bot 状态写入 `data/_bot_status.json`，web-ui 每次刷新页面时读取该文件。两者只在 data 目录层面产生关联。

```json
// data/_bot_status.json（由 ws-server 定时写入）
{
  "agents": [
    {"id": "ws_xxx", "name": "小谷", "online": true, "uptime_secs": 3600},
    {"id": "ws_yyy", "name": "爱泰", "online": false}
  ],
  "_last_update": 1712345678.0
}
```

```python
# web-ui/handlers.py — 读取文件（原 web_service.py 中的 _fetch_bot_status 改为读文件）
import json
from .config import DATA_DIR

def _get_bot_status() -> dict:
    path = DATA_DIR / "_bot_status.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"agents": []}
```

**变更点：**
- **`ws-server/`**：新增一个轻量定时任务，每 10 秒将 `_connections` 状态写入 `data/_bot_status.json`
- **`web-ui/`**：删除 HTTP 轮询 `_fetch_bot_status()`，改为读本地文件
- 两者零网络依赖，只在 data 目录关联

### 3.8 Web 前端减法

#### 当前状态确认

经过前面轮次的简化，Web 当前已是简洁状态：
- ✅ **无绑定码** — `BIND_TEMPLATE` 是残留代码（`web_viewer.py` 的 `handle_chat()` 已直接返回 `CHAT_TEMPLATE`），实际界面不再使用
- ✅ **纯 GitHub OAuth 登录** — 是唯一认证方式
- ✅ **收件箱 Tab** — 已实现

当前 Tab 结构（`server/templates.py`）：

```
📬 收件箱  |  🔧 管理员  |  🗂️ 历史
```

#### R109 减法目标

| 去掉 | 原因 | 所在文件 |
|:-----|:------|:---------|
| ❌ `🔧 管理员` Tab | 自动化管线后无意义 | `templates.py:137` — `tab2` |
| ❌ 📋 工作室列表按钮/面板 | Web 不再管理 workspace | `templates.py:110` — `wsListBtn` |
| ❌ 活跃工作室视图 | 只留历史归档查看 | `templates.py:504` — `activeWs` 相关渲染 |
| ❌ 大厅引用 | 已不再需要 | `templates.py:276` — 清理 |
| ❌ `BIND_TEMPLATE` | 残留代码，不再使用 | `templates.py:4` — 删除整个常量 |
| ❌ `handle_api_bind` / `handle_api_check` | 残留路由 | `web_viewer.py:206,213` |
| ❌ `handle_api_approve_web` | 残留 | `web_viewer.py:327` |

#### 减法后的 Web 结构

```
首页 (/) → GitHub OAuth 登录按钮 → 跳转至聊天页

聊天页 (/chat)
  ├── 📬 收件箱       ← 默认 Tab，显示 inbox 消息
  ├── 🗂️ 历史        ← 选择已归档工作室查看历史
  ├── 搜索框          ← 搜索当前频道消息
  └── 登出按钮
```

```javascript
// 减法后的 TAB_STATE
const TAB_STATE = {
  tab1: { id: 'tab1', channel: '__inbox__', label: '📬 收件箱', permanent: true },
  tab3: { id: 'tab3', channel: null,         label: '🗂️ 历史',  permanent: true },
};
```

```python
# 减法后的路由（web-ui/handlers.py 将精简为）
setup_routes(app):
    GET  /                 → GitHub 登录页
    GET  /chat             → 聊天页面
    GET  /api/chat         → 消息查询（只读）
    GET  /api/channels     → 频道列表
    GET  /api/chat/inbox   → 收件箱聚合
    GET  /api/chat/archive → 归档历史查询
    GET  /api/chat/search  → 消息搜索
    GET  /api/version      → 版本号
    GET  /auth/github/login    → GitHub OAuth
    GET  /auth/github/callback → OAuth 回调
    GET  /api/auth/me     → 当前用户状态
    POST /api/logout       → 登出
```

---

## 四、执行计划

### Step 1 — 新建 web-ui/ 目录

1. 创建 `web-ui/` 目录 + `__init__.py`
2. 从原 `server/` 复制并改造：
   - `web-ui/__main__.py`（从 `web_service.py` 改造，去除对 server package 的依赖）
   - `web-ui/handlers.py`（从 `web_viewer.py` 改造，做减法）
   - `web-ui/templates.py`（从 `templates.py` 复制，前端减法）
   - `web-ui/config.py`（新建，仅 Web 配置）
   - `web-ui/auth.py`（新建，Web 认证）
   - `web-ui/message_store.py`（新建，只读副本）
   - `web-ui/persistence.py`（新建，Web 专用持久化）
3. 验证：`python3 -m web-ui` → `WEB READY: http://0.0.0.0:8766/`

### Step 2 — 拆分 auth.py

1. `git mv server/auth.py ws-server/auth.py`
2. 从 `ws-server/auth.py` 中删除 Web 专用逻辑（bind code 相关、session 相关）
3. 创建 `web-ui/auth.py`，放入 Web 认证逻辑
4. 验证：两边 auth 无交叉 import

### Step 3 — 拆分 message_store.py

1. `git mv server/message_store.py ws-server/message_store.py`
2. 创建 `web-ui/message_store.py`，仅保留只读函数
3. 验证：web-ui 能正常查询 messages.db

### Step 4 — 拆分 persistence.py

1. `git mv server/persistence.py ws-server/persistence.py`
2. 创建 `web-ui/persistence.py`，仅保留 sessions + bind codes
3. 验证：web-ui 能正常读写 sessions

### Step 5 — 拆分 config.py

1. `git mv server/config.py ws-server/config.py`
2. 从 `ws-server/config.py` 中删除 Web 配置项（HTTP_PORT、GITHUB_OAUTH_*、OAUTH_NAME_MAP、WS_ENV）
3. 创建 `web-ui/config.py`

### Step 6 — 新建 ws-server/ 目录

1. `git mv server/ ws-server/` 剩余的 WSS 文件
2. 更新所有 `from .xxx` 相对 import 为 `from ws-server.xxx`（或保持相对 import，在 ws-server/ 内部用 `.` 没问题）
3. 注意：`absolute import` vs `relative import` — ws-server 内部文件之间用 `.` 相对 import 不变；ws-server 模块之间用绝对路径？

> **关于 import 风格**：ws-server 内部用相对 import（`from . import xxx`）不变。web-ui 内部也用相对 import。两者无交叉。

### Step 7 — 更新部署配置

```dockerfile
# Dockerfile
COPY ws-server/ ws-server/        # 含 protocol.py
COPY web-ui/ web-ui/
COPY gateway-plugin/ gateway-plugin/  # 如需要
```

```ini
# supervisord.conf
[program:wss]
command=python3 -u -m ws-server.__main__

[program:web]
command=python3 -u -m web-ui
```

### Step 8 — 删除 server/ 和 entrypoint.py

1. `rm -rf server/`
2. `rm entrypoint.py`
3. 更新 `README.md` 中过时的路径引用

### Step 9 — 验证

- WSS 核心正常：bot auth → inbox 路由 → 消息持久化
- Web 服务正常：首页 → 聊天页 → 频道列表 → 消息轮询
- 解耦验证：停 Web → bot 正常；停 WSS → Web 显示历史
- 前端减法验证：无 admin 频道、无 workspace 管理、无绑定码

---

## 五、验收标准

### 5.1 代码结构

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 1 | `server/` 目录不存在 | `ls server/` → 无此目录 |
| 2 | `ws-server/` 纯 WSS 核心 | `ls ws-server/` 不含任何 web 相关文件 |
| 3 | `web-ui/` 纯 Web 服务 | `grep -rn 'ws-server\|from ws' web-ui/'` → 0 |
| 4 | `ws-server/auth.py` 无 Web 认证逻辑 | `grep -c 'bind_code\|web_session' ws-server/auth.py` → 0 |
| 5 | `web-ui/auth.py` 无 WSS 认证逻辑 | `grep -c 'api_key\|get_level\|set_role' web-ui/auth.py` → 0 |
| 6 | 双进程语法正确 | `python3 -m py_compile ws-server/__main__.py && python3 -m py_compile web-ui/__main__.py` → ✅ |
| 7 | `protocol.py` 在 ws-server 中 | `ls ws-server/protocol.py` → 存在 |

### 5.2 功能回归

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 8 | WSS 核心正常启动 | `python3 -m ws-server.__main__` → `READY: http://0.0.0.0:8765/` |
| 9 | Web 服务正常启动 | `python3 -m web-ui` → `WEB READY: http://0.0.0.0:8766/` |
| 10 | Bot auth 正常 | WSS auth → `auth_ok` |
| 11 | Bot inbox 路由正常 | Bot A → `_inbox:bot_b` → Bot B 收到 |
| 12 | Web 首页 | `GET http://localhost:8766/` → 200（GitHub 登录页） |
| 13 | Web 聊天历史 | `GET /chat` → HTML |
| 14 | Web 消息轮询 | `GET /api/chat?channel=lobby&since=X` → JSON |
| 15 | Web 收件箱 | `GET /api/chat/inbox` → JSON |

### 5.3 Web 减法验证

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 16 | 前端只有两个 Tab：收件箱 + 历史 | 页面 Tab 区域无 `🔧 管理员`、无 `🌐 大厅` |
| 17 | 前端无绑定码 | 首页仅 GitHub 登录按钮，无绑定码输入框 |
| 18 | 前端无工作室列表按钮/面板 | 页面右上角无 📋 按钮，无活跃/历史工作室列表 |
| 19 | `BIND_TEMPLATE` 已删除 | `grep 'BIND_TEMPLATE' web-ui/` → 0 |
| 20 | `handle_api_bind` / `handle_api_check` 已删除 | 路由列表无 `/api/bind` `/api/check` |

### 5.4 解耦验证

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 21 | 停 Web → bot 正常 | `kill web-ui` → bot 收发 inbox 正常 |
| 22 | 停 WSS → Web 显示历史 | `kill ws-server` → Web 端显示已有数据 |
| 23 | Supervisor 双进程 | `supervisorctl status` → wss RUNNING, web RUNNING |
| 24 | Docker 构建 | `docker build -t ws-bridge:r109 .` → 无错误 |

### 5.5 数据层验收

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| 25 | `_auto_dispatch` 派活消息落库 | 派活后查 DB：`SELECT * FROM messages WHERE channel LIKE '_inbox:%'` → 有数据 |
| 26 | `_handle_server_relay` 转发消息落库 | Bot 回复 `_inbox:server` → 查 DB：该条消息在 `_inbox:<target>` 下有记录 |
| 27 | Web inbox Tab 可见管线消息 | 打开 Web 收件箱 Tab → 显示管线派活/完成通知 |

---

## 六、风险与缓解

| 风险 | 缓解 |
|:-----|:------|
| `message_store.py` 两份有代码重复 | 只读副本仅 ~60 行（5 个读函数），维护成本可控。如果后续读逻辑变化，两边同步改。只读函数几乎不变 |
| `persistence.py` 两份导致数据不一致 | Web 只读 sessions/bind codes（sssions 由 Web 写入，WSS 不碰），不冲突。剩余的 workspace/agent 数据由 ws-server 管理 |
| `web_viewer.py` 中的 `get_connections` 惰性 import 指向 `main.py` | 已改为 HTTP 轮询 `/api/status` — web-ui 中已有 `_fetch_bot_status()` 函数 |
| git blame 历史丢失 | 使用 `git mv` 而非 `cp + rm`，Git 能追踪重命名 |
| 前端减法漏改 | 在 templates.py 中 grep `_admin`、`workspace`、`bind` 等关键词确保清理干净 |

---

## 七、参考

- [R101 需求文档](../R101/R101-product-requirements.md) — 第一次 WSS/Web 解耦（进程级）
- [R101 测试报告](../R101/R101-test-report.md) — 解耦验证方法
- `server/web_viewer.py:722` 行 `setup_routes()` — 全部 Web HTTP 路由
- `Dockerfile` — 镜像构建配置
- `supervisord.conf` — 双进程管理
