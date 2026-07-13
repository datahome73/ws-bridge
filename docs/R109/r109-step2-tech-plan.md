# R109 Step 2 — 架构大重构：ws-server / web-ui 彻底分离 技术方案

> **轮次：** R109 · **角色：** 架构师（小开）
> **日期：** 2026-07-13
> **状态：** 📝 技术方案
> **前置：** [需求文档](./R109-product-requirements.md) ✅
> **关联：** [WORK_PLAN](./WORK_PLAN.md)

---

## 目录

1. [整体迁移策略](#1-整体迁移策略)
2. [auth.py 拆分](#2-authpy-拆分)
3. [message_store.py 只读副本](#3-message_storepy-只读副本)
4. [persistence.py 拆分与读写锁](#4-persistencepy-拆分与读写锁)
5. [config.py 减法](#5-configpy-减法)
6. [Bot 状态文件传递](#6-bot-状态文件传递)
7. [Dockerfile + Supervisor 更新](#7-dockerfile--supervisor-更新)
8. [import 迁移清单](#8-import-迁移清单)
9. [执行计划与验证](#9-执行计划与验证)
10. [回滚方案](#10-回滚方案)

---

## 1. 整体迁移策略

### 1.1 策略核心：分步迁移，避免大爆炸

不采用一次性 `git mv server/ ws-server/` 再创建 `web-ui/` 的"大爆炸"方式，而是 **分 6 个子步骤**，每一步都可独立验证、可回滚。

```
Step A: 新建 web-ui/ 包（复制+改造 web 文件）
Step B: 拆分 auth.py（WSS 与 Web 分离）
Step C: 拆分 message_store.py（只读副本）
Step D: 拆分 persistence.py（Web 专用副本）
Step E: 拆分 config.py（WSS 精简 + Web 新建）
Step F: 创建 ws-server/（git mv server/ 剩余文件）+ 更新 import
Step G: 更新 Docker + Supervisor
Step H: 删除 server/ + cleanup
```

### 1.2 过渡期策略

在 Steps A-E 期间，`server/` 目录仍然存在且功能完整。新建的 `web-ui/` 独立运行，两者共存：

```
过渡期（Step A~E）:
  ws-bridge/
  ├── server/          ← 仍然完整，Supervisor 双进程继续从 server/ 启动
  ├── web-ui/          ← 新建，独立可运行，与 server/ 零 import
  ├── data/            ← 共享数据目录
  └── ...              ← 其他不变

最终（Step F~H）:
  ws-bridge/
  ├── ws-server/       ← git mv from server/（WSS 核心）
  ├── web-ui/          ← 独立 Web 包（已建好）
  ├── data/
  └── ...
```

**关键原则：** 每一步结束后 `python3 -m server.__main__` 和 `python3 -m web-ui` 都必须正常运行。

### 1.3 文件生命周期

| 步骤 | 创建 | 保留 | 删除 |
|:-----|:-----|:-----|:-----|
| A | `web-ui/__main__.py`, `web-ui/handlers.py`, `web-ui/templates.py`, `web-ui/config.py`, `web-ui/__init__.py` | `server/web_service.py`, `server/web_viewer.py`, `server/templates.py`, `server/config.py` | — |
| B | `web-ui/auth.py` | `server/auth.py`（删除 Web 逻辑） | — |
| C | `web-ui/message_store.py` | `server/message_store.py`（全量） | — |
| D | `web-ui/persistence.py` | `server/persistence.py`（全量） | — |
| E | — | `server/config.py`（→ `ws-server/config.py`，减法） | — |
| F | — | `ws-server/`（从 server/ git mv） | — |
| G | — | — | 更新 Dockerfile + supervisor |
| H | — | — | `server/`, `entrypoint.py`, 备份文件 |

---

## 2. auth.py 拆分

### 2.1 当前状态

`server/auth.py`（156 行）混合了 WSS 和 Web 认证逻辑：

| 函数 | 域 | 目标 |
|:-----|:---|:-----|
| `is_approved()` | WSS | → `ws-server/auth.py` |
| `get_users()` | WSS | → `ws-server/auth.py` |
| `is_workspace_admin()` | WSS | → `ws-server/auth.py` |
| `is_global_admin()` | WSS | → `ws-server/auth.py` |
| `can_manage_workspace()` | WSS | → `ws-server/auth.py` |
| `set_workspace_admin()` | WSS | → `ws-server/auth.py` |
| `generate_agent_id()` | WSS | → `ws-server/auth.py` |
| `create_api_key()` | WSS | → `ws-server/auth.py` |
| `validate_api_key()` | WSS | → `ws-server/auth.py` |
| `revoke_api_key()` | WSS | → `ws-server/auth.py` |
| `get_level()` | WSS | → `ws-server/auth.py` |
| `set_level()` | WSS | → `ws-server/auth.py` |
| `get_agent_name()` | WSS | → `ws-server/auth.py` |
| — | — | — |
| bind code 相关 | Web | → 迁移至 `web-ui/auth.py` |
| web session 管理 | Web | → 由 `web-ui/persistence.py` 接管 |
| GitHub OAuth callback | Web | → 保留在 `web-ui/handlers.py`（与 handler 耦合） |

### 2.2 WSS 侧：`ws-server/auth.py`

**保留所有 WSS 函数不变**（从原 server/auth.py 直接 git mv），仅删除以下 Web 专用代码：

1. `WEB_CODE_PREFIX` 绑定码常量 → 移到 web-ui
2. `generate_web_bind_code()` / `approve_web_bind_code()` → 移到 web-ui
3. `create_web_bind_code()` → 移到 web-ui
4. Web session token 验证 → 移到 web-ui

**验证条件：** `grep -c 'bind_code\|web_session\|WEB_CODE' ws-server/auth.py` → 0

### 2.3 Web 侧：`web-ui/auth.py`

新建文件，包含：

```python
"""Web authentication — sessions + bind codes + GitHub OAuth helpers."""

import json
import secrets
import time
from pathlib import Path

from .config import DATA_DIR
from .persistence import get_web_bind_codes, save_web_bind_codes

# ── Bind codes ──────────────────────────────────────────
WEB_CODE_PREFIX = "wc_"

def generate_web_bind_code() -> str:
    """Generate a new web bind code."""
    code = WEB_CODE_PREFIX + secrets.token_hex(16)
    codes = get_web_bind_codes()
    codes[code] = {"created": time.time(), "approved": False, "approved_name": None}
    save_web_bind_codes(codes)
    return code

def approve_web_bind_code(code: str, name: str) -> bool:
    """Approve a bind code for a named user."""
    codes = get_web_bind_codes()
    if code not in codes:
        return False
    codes[code]["approved"] = True
    codes[code]["approved_name"] = name
    codes[code]["approved_at"] = time.time()
    save_web_bind_codes(codes)
    return True

def is_bind_code_approved(code: str) -> tuple[bool, str]:
    """Check if bind code is approved, return (ok, name)."""
    codes = get_web_bind_codes()
    rec = codes.get(code)
    if not rec:
        return False, ""
    if rec.get("approved"):
        return True, rec.get("approved_name", "")
    return False, ""
```

**GitHub OAuth 逻辑**（`handle_github_login` / `handle_github_callback`）**保留在 `web-ui/handlers.py`** 中，因为它们与 HTTP handler 紧密耦合，提取到 auth.py 反而增加复杂度。

---

## 3. message_store.py 只读副本

### 3.1 当前状态

`server/message_store.py`（245 行）有 8 个公开函数：

| 函数 | 读写 | web-ui 需要？ |
|:-----|:----|:-------------|
| `init_db()` | 初始化 | ✅ 需要（确保 DB 存在） |
| `save_message()` | 写入 | ❌ web-ui 只读 |
| `get_messages_since()` | 读 | ✅ - 5s 轮询 |
| `get_messages_by_channel()` | 读 | ✅ - 频道查看 |
| `search_messages()` | 读 | ✅ - 搜索 |
| `clear_messages_by_channel()` | 写入 | ❌ Web 不清理消息 |
| `get_messages_by_channel_pattern()` | 读 | ✅ - inbox 聚合 |
| `get_messages_by_time_range()` | 读 | ✅ - 历史归档 |
| `clean_old_messages()` | 写入 | ❌ WSS 专用 |

### 3.2 只读副本设计

`web-ui/message_store.py` — 仅保留读函数（~70 行，是原版的 1/3）：

```python
"""Read-only message store — queries the same SQLite DB shared with ws-server."""

import sqlite3
import time
from pathlib import Path

# 复用原 server/message_store.py 的 DB 路径逻辑
_DB_FILENAME = "messages.db"

def _get_db_path(data_dir: Path) -> str:
    return str(data_dir / _DB_FILENAME)

def init_db(data_dir: Path) -> None:
    """Ensure DB exists (no-op if already exists)."""
    db_path = _get_db_path(data_dir)
    if Path(db_path).exists():
        return
    # 只建表，不走 migration——由 ws-server 全权管理 schema
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            channel TEXT NOT NULL,
            content TEXT,
            sender TEXT,
            ts REAL NOT NULL,
            metadata TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_channel ON messages(channel)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON messages(ts)")
    conn.commit()
    conn.close()

def get_messages_since(data_dir: Path, since: float, limit: int = 50, channel: str | None = None) -> list[dict]:
    """Return messages after timestamp (用于 5s 轮询)."""
    # ...（简化为 SQL 查询）

def get_messages_by_channel(data_dir: Path, channel: str, limit: int = 100) -> list[dict]:
    """Return latest messages in a channel."""
    # ...

def get_messages_by_channel_pattern(data_dir: Path, pattern: str, limit: int = 50) -> list[dict]:
    """Return messages by channel LIKE pattern (inbox 聚合)."""
    # ...

def search_messages(data_dir: Path, query: str, limit: int = 50) -> list[dict]:
    """Full-text search across all channels."""
    # ...

def get_messages_by_time_range(data_dir: Path, start: float, end: float, channel: str | None = None) -> list[dict]:
    """Return messages within a time range (历史归档)."""
    # ...
```

### 3.3 数据竞争风险

`web-ui/message_store.py` 和 `ws-server/message_store.py` 同时读写同一个 SQLite 文件。SQLite 本身支持多进程读，写入会加锁（WAL 模式），所以：

- **同时读（web-ui）+ 同时写（ws-server）→ 安全** ✅（SQLite WAL 模式支持并发读写）
- **同时写 + 同时写** → 由 ws-server 独占，web-ui 不调用 `save_message()` ✅
- **web-ui 只读函数不持有长时间事务** → 不阻塞 ws-server 写入 ✅

**无需额外同步机制。** 只需确保 `data/messages.db` 以 WAL 模式运行（`PRAGMA journal_mode=WAL`），此设置由 ws-server 的 `init_db()` 负责。

---

## 4. persistence.py 拆分与读写锁

### 4.1 当前状态

`server/persistence.py`（135 行）管理 5 组 JSON 文件：

| 数据 | 文件 | 写入者 | web-ui 需要？ |
|:-----|:-----|:-------|:-------------|
| `approved_users` | `approved_users.json` | WSS | ❌ |
| `web_sessions` | `web_sessions.json` | Web | ✅ |
| `api_keys` | `api_keys.json` | WSS | ❌ |
| `web_bind_codes` | `web_bind_codes.json` | Web | ✅ |
| workspace 数据 | 通过 workspace_store() | WSS | ❌ |

### 4.2 Web 专用副本

`web-ui/persistence.py` — 仅保留 Web 相关内容（~50 行）：

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
```

### 4.3 JSON 文件竞争问题（读写锁）

**问题：** web-ui 和 ws-server 可能同时读写同一个 JSON 文件（`web_sessions.json` 由 web-ui 写，ws-server 不碰；`web_bind_codes.json` 由 web-ui 写，ws-server 不碰；`api_keys.json` 由 ws-server 写，web-ui 不碰）。

**结论：不存在竞争** ✅，因为：

| JSON 文件 | 写入方 | 读取方 | 竞争？ |
|:----------|:-------|:-------|:------|
| `web_sessions.json` | web-ui | web-ui | ❌ 无（独占） |
| `web_bind_codes.json` | web-ui | web-ui | ❌ 无（独占） |
| `api_keys.json` | ws-server | ws-server | ❌ 无（独占） |
| `approved_users.json` | ws-server | ws-server | ❌ 无（独占） |

**但为防止未来误用，两边 persistence 都使用 `_save_json_atomic()` 模式**（写临时文件 → rename 覆盖），确保即使在极端情况下也不会产生半写文件。

```python
def _save_json_atomic(path: Path, data: dict) -> None:
    """Atomic write: temp file → rename."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.rename(path)
```

---

## 5. config.py 减法

### 5.1 当前状态

`server/config.py` — **176 行**，混合了 WSS 配置、Web 配置、OAuth 配置、管线配置。

### 5.2 WSS 配置：`ws-server/config.py`（~45 行）

```python
"""WSS server config — minimal, no web config leak."""
import os
from pathlib import Path

# ── 基础 ──
HOST = os.environ.get("WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_PORT") or os.environ.get("PORT", "8765"))
DATA_DIR = Path(os.environ.get("WS_DATA_DIR", "./data"))

# 隐藏的系统 agent（不在 /api/status 中暴露）
HIDDEN_AGENTS: set[str] = set(
    filter(None, os.environ.get("WS_HIDDEN_AGENTS", "bot-hermes").split(","))
)

# ── PM inbox 地址（唯一需要的地址）──
PM_AGENT_ID: str = os.environ.get("WS_PM_AGENT_ID", "")

# ── 中继通道 ──
SERVER_INBOX_CHANNEL: str = "_inbox:server"

# ── 自动派活（R102+）──
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

### 5.3 删除的配置项及原因（共 21 项 → ~45 行）

| 配置项 | 行数 | 原因 | 迁移目标 |
|:-------|:----:|:-----|:---------|
| `HTTP_PORT` | 2 | Web 配置 | `web-ui/config.py` |
| `APP_ID` | 1 | 不再需要 | 🗑️ 删除 |
| `CHAT_LOG_DIR` | 1 | write_chat_log 已移除（R101） | 🗑️ 删除 |
| `ADMIN_AGENTS` | 3 | 没有 admin_bot 了 | 🗑️ 删除 |
| GitHub OAuth 全部（6 项 + 解析逻辑 ~30 行） | ~30 | Web 认证 | `web-ui/config.py` |
| `WS_ENV` / `IS_PRODUCTION` | 2 | Web 环境标识 | `web-ui/config.py` |
| `WORK_PLAN_REPO_URL` | 3 | 自动化管线不再通过 URL 拉取 | 🗑️ 删除 |
| `PIPELINE_PM_NAME` | 3 | 自动化后固定 | 🗑️ 删除（硬编码 "PM"） |
| `PIPELINE_ARCH_FROM_NAME` | 4 | 自动化管线不再需要 | 🗑️ 删除 |
| `PIPELINE_ROLE_OVERRIDES` | 10 | 自动化管线固定角色映射 | 🗑️ 删除 |
| `DISPATCH_SENDER_ID` | 5 | 与 `PIPELINE_PM_AGENT_ID` 合并 | `PM_AGENT_ID` |
| `PIPELINE_PM_AGENT_ID` | 4 | 重命名 | `PM_AGENT_ID` |
| `GIT_SYNC_INTERVAL` | 2 | 保留默认值，去掉可配性 | 🗑️ 删除 |
| `GIT_SYNC_BRANCH` | 2 | 保留默认值（dev） | 🗑️ 删除 |
| `GIT_SYNC_FALLBACK` | 2 | 保留默认值 | 🗑️ 删除 |
| `ENABLE_VALIDATION_HOOK` | 4 | 未投入使用 | 🗑️ 删除 |
| `VALIDATION_DEFAULT_SCRIPT` | 3 | 未投入使用 | 🗑️ 删除 |
| `VALIDATION_DEFAULT_TIMEOUT` | 2 | 未投入使用 | 🗑️ 删除 |

### 5.4 Web 配置：`web-ui/config.py`（~25 行）

```python
"""Web UI config — port, OAuth, data dir."""
import os
from pathlib import Path

HOST = os.environ.get("WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8766"))
DATA_DIR = Path(os.environ.get("WS_DATA_DIR", "./data"))

# ── GitHub OAuth ──
GITHUB_OAUTH_CLIENT_ID = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "")
GITHUB_OAUTH_CLIENT_SECRET = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "")
GITHUB_OAUTH_REDIRECT_URI = os.environ.get(
    "GITHUB_OAUTH_REDIRECT_URI",
    os.environ.get("WS_PUBLIC_URL", "http://0.0.0.0:8766") + "/auth/github/callback",
)
OAUTH_NAME_MAP: dict[str, str] = {}
_raw = os.environ.get("OAUTH_NAME_MAP", "")
if _raw.strip():
    import json as _json
    try:
        OAUTH_NAME_MAP.update(_json.loads(_raw))
    except _json.JSONDecodeError:
        pass

# ── 环境标识 ──
WS_ENV = os.environ.get("WS_ENV", "dev")
IS_PRODUCTION = WS_ENV == "production"
```

---

## 6. Bot 状态文件传递

### 6.1 架构

```
ws-server（定时 10s 写入）           web-ui（页面刷新/首次加载时读取）
     │                                      │
     │  write: data/_bot_status.json         │  read: data/_bot_status.json
     └────────────────── data/ ──────────────┘
```

### 6.2 WSS 侧：定时写入

在 `ws-server/main.py` 中新增一个轻量 asyncio 定时任务：

```python
import json, time, asyncio
from pathlib import Path

async def _write_bot_status_loop():
    """每 10s 将当前在线 bot 状态写入 data/_bot_status.json"""
    status_path = Path(config.DATA_DIR) / "_bot_status.json"
    while True:
        try:
            agents = []
            for agent_id, conn in _connections.items():
                agents.append({
                    "id": agent_id,
                    "name": getattr(conn, "display_name", agent_id[:8]),
                    "online": True,
                    "uptime_secs": int(time.time() - conn.connected_at) if hasattr(conn, "connected_at") else 0,
                })
            data = {"agents": agents, "_last_update": time.time()}
            tmp = status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.rename(status_path)
        except Exception:
            pass  # 静默失败，不阻塞主循环
        await asyncio.sleep(10)
```

**启动时机：** 在 `main()` 的 `asyncio.gather()` 中添加此协程。

**回退方案：** 如果 bot 状态写入出错（如 data/ 目录不可写），静默跳过，Web 端显示空的 agent 列表。

### 6.3 Web 侧：读取文件

替换原 `web_service.py` 中的 `_fetch_bot_status()`（HTTP 轮询 `/api/status`）：

```python
# web-ui/handlers.py
import json
from pathlib import Path
from .config import DATA_DIR

def _get_bot_status() -> dict:
    """读取 ws-server 写入的 bot 状态文件。"""
    path = Path(DATA_DIR) / "_bot_status.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"agents": []}
```

### 6.4 时序与竞争条件

| 场景 | 影响 | 处理 |
|:-----|:-----|:-----|
| Web 在 WSS 写入中间读取 | 可能读到旧数据或 .tmp 文件 | ✅ 使用 atomic write（.tmp → rename），rename 是原子操作 |
| WSS 还没写入，Web 先启动 | `_bot_status.json` 不存在 | ✅ 返回 `{"agents": []}`，Web 显示空列表 |
| WSS 挂了，Web 还在运行 | 状态文件是最后写入的内容 | ✅ Web 显示"最后一次在线"状态，合理 |
| 并发读取频繁 | JSON 文件读取无锁问题 | ✅ Python `read_text()` 是原子读操作 |

---

## 7. Dockerfile + Supervisor 更新

### 7.1 Dockerfile

```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y supervisor && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# R109: server/ 替换为 ws-server/ + web-ui/
COPY ws-server/ ws-server/
COPY web-ui/ web-ui/
COPY gateway-plugin/ gateway-plugin/
COPY clients/ clients/
COPY scripts/ scripts/
COPY config/ config/
COPY docs/ docs/
COPY shared/ shared/

COPY supervisord.conf /etc/supervisor/conf.d/ws-bridge.conf

EXPOSE 8765 8766

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/ws-bridge.conf"]
```

**变更：** `COPY server/ server/` → `COPY ws-server/ ws-server/` + `COPY web-ui/ web-ui/`，去掉 `COPY entrypoint.py .`

### 7.2 supervisord.conf

```ini
[supervisord]
nodaemon=true
logfile=/dev/null
logfile_maxbytes=0
user=root

[program:wss]
command=python3 -u -m ws-server.__main__
directory=/app
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
stopwaitsecs=10

[program:web]
command=python3 -u -m web-ui
directory=/app
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
stopwaitsecs=5
```

**变更：** `-m server.__main__` → `-m ws-server.__main__`，`-m server.web_service` → `-m web-ui`

---

## 8. import 迁移清单

### 8.1 ws-server 内部 import（不变）

`ws-server/` 内部所有文件继续使用相对 import（`from . import xxx`）：

```python
# ws-server/main.py — 不变
from . import config, auth, message_store as ms, persistence, ...
from .commands import pipeline, ...
```

✅ 注意：Python 包重命名（`server/` → `ws-server/`）后，`from .xxx` 相对 import 自然指向新包。不需要修改任何相对 import。

### 8.2 web-ui import（全部改为本 package 绝对路径）

#### `web-ui/__main__.py`（从 `server/web_service.py` 改造）

```python
# 原（server/web_service.py）：
from .config import DATA_DIR, HOST, PORT as WSS_PORT
from . import web_viewer
from . import persistence
from . import message_store as ms

# 新（web-ui/__main__.py）：
from .config import HOST, PORT
from . import handlers           # 重命名 web_viewer → handlers
from . import persistence        # Web 专用
from . import message_store as ms # 只读副本
```

#### `web-ui/handlers.py`（从 `server/web_viewer.py` 改造）

```python
# 原（server/web_viewer.py）：
from . import auth, config, persistence, workspace as ws_mod
from . import message_store as ms
from .templates import BIND_TEMPLATE, CHAT_TEMPLATE

# 新（web-ui/handlers.py）：
from . import auth               # Web 认证（新建）
from . import config             # Web 配置（新建）
from . import persistence        # Web 专用持久化
from . import message_store as ms # 只读副本
from .templates import CHAT_TEMPLATE  # BIND_TEMPLATE 已删除
```

### 8.3 删除的 import

| 原 import | 原因 |
|:----------|:------|
| `from . import workspace as ws_mod` | web-ui 不再管理 workspace |
| `from .templates import BIND_TEMPLATE` | 前端减法：删除绑定码界面 |
| `from .config import CHAT_LOG_DIR` | write_chat_log 已移除 |
| `from .config import APP_ID` | 不再需要 |
| `from .config import ADMIN_AGENTS` | 无 admin_bot |

### 8.4 完整 import 迁移对照表

| 文件 | 旧 import（from server.） | 新 import |
|:-----|:-------------------------|:----------|
| `web-ui/__main__.py` | `.config`, `.web_viewer`, `.persistence`, `.message_store` | `.config`, `.handlers`, `.persistence`, `.message_store` |
| `web-ui/handlers.py` | `.auth`, `.config`, `.persistence`, `.workspace`, `.message_store`, `.templates`（×2） | `.auth`, `.config`, `.persistence`, `.message_store`, `.templates`（×1，去掉 BIND） |
| `web-ui/workspace_api.py` | `.workspace` | 🗑️ 删除文件，合并到 handlers.py（可选） |
| `ws-server/*.py` | `.xxx`（相对 import） | **不变**（Python 包重命名后相对 import 自动跟随） |

---

## 9. 执行计划与验证

### Step A：新建 web-ui/ 包

**命令序列：**

```bash
# 1. 创建目录结构
mkdir -p web-ui

# 2. 创建 __init__.py
touch web-ui/__init__.py

# 3. web-ui/config.py（新建 ~25 行 Web 配置）
# 4. web-ui/__main__.py（从 server/web_service.py 改造，替换 import）
# 5. web-ui/handlers.py（从 server/web_viewer.py 改造，减法+替换 import）
# 6. web-ui/templates.py（从 server/templates.py 复制，前端减法）
# 7. web-ui/message_store.py（新建只读副本 ~70 行）
# 8. web-ui/persistence.py（新建 Web 专用 ~50 行）
# 9. web-ui/auth.py（新建 Web 认证 ~50 行）

# 验证
python3 -m web-ui
# → 输出：WEB READY: http://0.0.0.0:8766/
```

**验收：** `python3 -m web-ui` → 正常启动，首页显示 GitHub 登录页 ✅

### Step B-D：拆分 auth / message_store / persistence

> 这些"拆分"步骤在 Step A 中已通过"新建"实现——`web-ui/auth.py`、`web-ui/message_store.py`、`web-ui/persistence.py` 已在 Step A 创建。本步只需：从 `server/auth.py` 中删除 Web 专用逻辑（bind code / web session 相关函数）。

### Step E：拆分 config.py

```bash
# 1. 从 server/config.py 中剥离 Web 配置项 → 移到 web-ui/config.py（Step A 已建）
# 2. 从 server/config.py 中删除 21 项 → 精简至 ~45 行
# 3. 注意：Step F（git mv）前 server/config.py 仍然在使用
```

**验收：** `python3 -m server.__main__` → 正常启动（功能不变）✅

### Step F：创建 ws-server/

```bash
# 1. git mv server/ ws-server/ （全部 WSS 文件）
# 2. 验证：所有相对 import 自动跟随
# 3. 验证：python3 -m ws-server.__main__ → 正常启动

# 临时文件检查
# ws-server 不应包含任何 web-* 文件
ls ws-server/web_*  # → 不应存在
```

**验收：** `python3 -m ws-server.__main__` → `READY: http://0.0.0.0:8765/` ✅

### Step G：更新部署配置

```bash
# 1. 更新 Dockerfile：COPY server/ → COPY ws-server/ + COPY web-ui/
# 2. 更新 supervisord.conf：server.__main__ → ws-server.__main__，server.web_service → web-ui
```

### Step H：清理

```bash
# 1. 确认两个新包都正常运行后
# 2. git rm -r server/（或其他包重命名后的残留）
# 3. git rm entrypoint.py（如存在）
# 4. 删除备份文件 server/templates.py.bak
```

### 全量验收清单（对照需求文档 §5）

| # | 验收项 | 方法 |
|:-:|:-------|:------|
| V-1 | `server/` 不存在 | `ls server/` → 无此目录 |
| V-2 | `ws-server/` 无 web 文件 | `ls ws-server/web_*` → 无匹配 |
| V-3 | `web-ui/` 零 ws-server import | `grep -rn 'from ws-server\|import ws-server\|from server\|import server' web-ui/` → 0 |
| V-4 | `ws-server/auth.py` 无 Web 逻辑 | `grep -c 'bind_code\|web_session\|WEB_CODE' ws-server/auth.py` → 0 |
| V-5 | `web-ui/auth.py` 无 WSS 逻辑 | `grep -c 'api_key\|get_level\|set_role' web-ui/auth.py` → 0 |
| V-6 | 双进程语法正确 | `python3 -m py_compile ws-server/__main__.py && python3 -m py_compile web-ui/__main__.py` |
| R-7 | WSS 核心正常启动 | `python3 -m ws-server.__main__` → `READY` |
| R-8 | Web 服务正常启动 | `python3 -m web-ui` → `WEB READY` |
| R-9 | Bot auth 正常 | WSS auth → `auth_ok` |
| R-10 | Bot inbox 路由正常 | Bot A → `_inbox:bot_b` → Bot B 收到 |
| S-11 | 前端只有两个 Tab | 页面 Tab 区域无 `🔧 管理员`、`🌐 大厅` |
| S-12 | `BIND_TEMPLATE` 已删除 | `grep 'BIND_TEMPLATE' web-ui/` → 0 |
| S-13 | config.py ≤ 50 行 | `wc -l ws-server/config.py` |
| S-14 | Web 停 → bot 正常 | `kill web-ui` → bot 收发 inbox 正常 |
| S-15 | Docker 构建 | `docker build -t ws-bridge:r109 .` → 无错误 |

---

## 10. 回滚方案

### 10.1 如果 web-ui 无法启动

```bash
# 过渡期：保留 server/ 不变，回退 Supervisor
# supervisord.conf 恢复为：
# [program:web] command=python3 -u -m server.web_service
```

### 10.2 如果 ws-server 无法启动（Step F 后）

```bash
# git revert Step F 提交
git revert HEAD
# 恢复 server/ 目录
git checkout HEAD~1 -- server/
```

### 10.3 数据损坏

整个迁移不涉及 schema 变更或数据迁移，数据文件（`data/messages.db`、`data/*.json`）保持不变。任何步骤回退后，数据文件可被旧代码正常读取。无数据回滚风险。

---

> **技术方案版本：** v1.0
> **审核状态：** ⏳ 待 Step 4 代码审查
> **前置依赖：** R108 已闭环 ✅
