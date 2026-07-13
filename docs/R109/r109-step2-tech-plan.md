# R109 Step 2 — 技术方案：server/ 包分割（web-ui ↔ ws-server）

## 概览

将当前单体 `server/` 包拆分为两个独立进程 + 共享层：

```
server/              ← 当前（Step 1 后，R100 已拆 handler）
├── common/          ← 新建：双进程共享层
│   ├── __init__.py
│   ├── config.py    ← 精简后的公共配置（~40 行）
│   ├── persistence.py  ← JSON 文件持久化（加锁 + 双进程安全）
│   ├── auth.py      ← 认证逻辑（WSS + Web 共用）
│   └── message_store.py  ← SQLite 只读查询接口（Web 端用）
├── web-ui/          ← 新建：纯 HTTP 服务包
│   ├── __init__.py
│   ├── main.py      ← R101 web_service.py 迁入
│   ├── viewer.py    ← R100 web_viewer.py 迁入
│   └── templates.py ← R100 templates.py 迁入
├── ws-server/       ← 新建：WebSocket 服务包
│   ├── __init__.py
│   ├── __main__.py  ← server/__main__.py 迁入
│   ├── main.py      ← server/main.py 迁入
│   ├── state.py     ← server/state.py 迁入
│   ├── commands/    ← server/commands/ 迁入
│   ├── command_utils.py
│   ├── workspace.py / workspace_api.py
│   ├── agent_card.py / pipeline_context.py / pipeline_sync.py
│   ├── auto_router.py / timeout_tracker.py
│   ├── task_store.py / audit.py
│   └── ...其余 WS 专有模块
└── __init__.py      ← 过渡期占位，最终删除
```

**迁移顺序：** ① 建 `common/` → ② 抽 `web-ui/` → ③ 抽 `ws-server/` → ④ 删除 `server/`

---

## 1. 整体迁移策略（三阶段）

### 阶段 A：创建 `server/common/` 共享层

**不动任何业务逻辑，只复制 + 精简。** 共享层模块直接拷贝当前文件，WS 端继续从 `server/` 导入，Web 端改为从 `server.common.*` 导入。

| 模块 | 内容 | 目标行数 | 说明 |
|------|------|----------|------|
| config.py | 仅保留双进程必需的 env 读取 | ~40 行 | 见 §5 |
| persistence.py | JSON 文件 CRUD + 线程锁 | ~80 行 | 见 §4 |
| auth.py | 纯认证函数（无 WS 依赖） | ~100 行 | 见 §2 |
| message_store.py | 只读查询子集 | ~60 行 | 见 §3 |

### 阶段 B：抽离 `server/web-ui/`

1. 将 `server/web_service.py` → `server/web-ui/main.py`
2. 将 `server/web_viewer.py` → `server/web-ui/viewer.py`
3. 将 `server/templates.py` → `server/web-ui/templates.py`
4. **所有 `from .xxx` 导入改为：**
   - `from server.common import config, persistence, auth, message_store as ms`
   - `from . import viewer, templates`（自身包内）
5. 删除 web-ui 中对 WS 专有模块的引用（workspace.py 直接读 → 改为 HTTP poll）
6. web-ui 独立可运行：`python3 -m server.web-ui.main`

### 阶段 C：抽离 `server/ws-server/`

1. 将剩余 `server/` 文件全部复制到 `server/ws-server/`
2. 将涉及 `server.common.*` 的导入改为 `from server.common import ...`
3. 将 `server/__main__.py` → `server/ws-server/__main__.py`
4. ws-server 独立可运行：`python3 -m server.ws-server.__main__`

### 阶段 D：删除 `server/` 根包

1. 验证 web-ui 和 ws-server 均正常工作
2. 将 `server/` 根包所有非 `common/`/`web-ui/`/`ws-server/` 文件删除
3. 更新所有外部引用（Dockerfile、supervisor、entrypoint.py、测试脚本等）

---

## 2. auth.py 拆分边界

当前 `server/auth.py`（156 行）按功能划分如下：

### ✅ 进入 common/auth.py（约 100 行）

| 函数 | 原因 | 依赖 |
|------|------|------|
| `is_approved()` | 双进程读 `persistence` | `persistence.get_approved_users()` / `get_api_keys()` |
| `get_users()` | 同上 | `persistence.get_approved_users()` |
| `is_workspace_admin()` | 可独立导入 workspace 模型 | `workspace`（⚠ 见下） |
| `is_global_admin()` | 纯 `get_users` 查询 | — |
| `can_manage_workspace()` | 组合上述 | — |
| `set_workspace_admin()` | admin 操作 | `workspace` |
| `generate_agent_id()` | 纯加密函数 | `secrets` |
| `create_api_key()` | 同上 | `hashlib + secrets` |
| `validate_api_key()` | 双进程认证 | `persistence.get_api_keys()` |
| `revoke_api_key()` | admin 操作 | `persistence` |
| `get_level()` / `set_level()` | 双进程等级查询 | `persistence.get_api_key_record()` |
| `get_agent_name()` | 双进程名称解析 | ⚠ 需改造，见下方 |

### ⚠ `get_agent_name()` 改造

当前 `get_agent_name()` 引用了 `server.state._r72_users`（WS 运行时状态）：

```python
try:
    from . import state as _state
    r72 = _state._r72_users
    return r72.get(agent_id, {}).get("name", default or agent_id[:12])
except ImportError:
    return default or agent_id[:12]
```

**改造方案：** 将 `_r72_users` 的职责转移到 `persistence`：

1. 在 `persistence.py` 中维护 `_r72_users` 全局字典（与 `_api_keys` 同步）
2. 每次 `save_api_keys()` 时自动从 `_api_keys` 重建 `_r72_users_map`（agent_id → display_name）
3. `get_agent_name()` 纯用 `persistence` 查询，不再引用 `state`

```python
# 改造后
def get_agent_name(agent_id: str, default: str | None = None) -> str:
    users = get_users()
    name = users.get(agent_id, {}).get("name")
    if name:
        return name
    # 从 api_keys 获取 display_name
    record = get_api_key_record(agent_id)
    if record:
        return record.get("display_name", default or agent_id[:12])
    return default or agent_id[:12]
```

### ❌ 不进入 common（保留在 ws-server）

无。auth.py 当前所有函数均可在 common 层实现，只需将 `workspace` 依赖改为惰性导入并留 fallback。

> **`is_workspace_admin()` 和 `set_workspace_admin()`** 在 Web 端也需要（API 路径 `/api/chat/inbox` 和频道解析用到）。故 workspace 模块需在 common 层提供只读接口或 HTTP poll。

---

## 3. message_store.py 只读副本

### 现状

- `server/message_store.py`（245 行）：SQLite 完整 CRUD
- Web UI 仅使用查询接口：`get_messages_since()`、`get_messages_by_channel()`、`search_messages()`、`get_messages_by_channel_pattern()`、`get_messages_by_time_range()`
- 写接口 (`save_message()`, `clear_messages_by_channel()`, `clean_old_messages()`) 仅有 WS 进程调用

### 方案：server/common/message_store.py

创建只读副本，仅暴露查询函数：

```python
"""只读 SQLite 查询接口（web-ui 用）。仅暴露查询方法，无写操作。"""

import sqlite3
import threading
from pathlib import Path

_local = threading.local()

def _get_conn(db_path: str) -> sqlite3.Connection:
    """Thread-local connection, WAL mode, read-only pragma."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return _local.conn

def get_messages_since(ts, data_dir, limit=500, channel=None) -> list[dict]:
    ...

def get_messages_by_channel(channel, data_dir, limit=100) -> list[dict]:
    ...

def search_messages(query, data_dir, limit=50, channel=None, sender=None) -> list[dict]:
    ...

def get_messages_by_channel_pattern(pattern, data_dir, limit=50, since=None) -> list[dict]:
    ...

def get_messages_by_time_range(start_ts, end_ts, data_dir) -> list[dict]:
    ...
```

### 关键设计

| 项目 | 选择 | 理由 |
|------|------|------|
| 只读模式 | `mode=ro` (URI) | 彻底消除写操作，SQLite 层面保证 |
| WAL 模式 | 由 WS 进程设置 | Web 进程的 `mode=ro` 继承 WAL 的读不受限特性 |
| 共享 DATA_DIR | 同一路径 | 两个进程指向同一 SQLite 文件 |
| 线程安全 | `threading.local()` | 与 WS 端一致，aiohttp 多线程安全 |

> **不需 `init_db()`：** 只读副本假设 DB 已由 WS 进程创建并初始化。启动时检测文件存在，不存在则日志 WARN。

### 后续优化方向（非本步）

如需彻底消除读竞争，可引入 WAL 模式的 `db_path?mode=ro` 只在第一次执行，或引入 SQLite 连接池重连。

---

## 4. persistence.py 拆分 + JSON 竞争

### 现状：server/persistence.py（135 行）

| 数据 | 读方 | 写方 |
|------|------|------|
| `_approved_users` | Web 端认证 | Web 端 approve |
| `_web_sessions` | Web 端 | Web 端 |
| `_api_keys` | 双进程 | 主要是 WS（注册/吊销） |

### 拆分策略

#### 进入 `server/common/persistence.py`（约 80 行）：只保留 `_api_keys`

```python
_api_keys: dict = {}
_lock = threading.Lock()

def _load_json(path) -> dict:
    ...

def _save_json_atomic(path, data) -> None:
    # 原子写入：tmp 文件 → rename
    ...

def load_api_keys(data_dir) -> None: ...
def save_api_keys(data_dir) -> None: ...
def get_api_keys() -> dict: ...
def set_api_keys(keys) -> None: ...
def get_api_key_record(agent_id) -> dict | None: ...

# 通用 helper（双进程都需要）
def get_inbox_channel(agent_id) -> str: ...
def is_inbox_channel(channel) -> bool: ...
def resolve_inbox_owner(channel) -> str | None:  ...
```

#### 留在 `server/ws-server/` 或 `server/web-ui/`（各进程独有）

| 函数 | 归属 | 原因 |
|------|------|------|
| `_approved_users` 全家桶 | Web 端独有 | 仅 web viewer 审批用 |
| `_web_sessions` 全家桶 | Web 端独有 | 仅 web viewer 会话用 |
| `workspace_store()` | WS 端独有 | 引用 workspace 模块 |

Web 端独有这些的功能保持原有写法，直接放在 `web-ui/` 包内或独立文件。

### JSON 竞争条件分析

`_api_keys.json` 是唯一的双进程写共享文件。竞争模型：

```
┌─────────────┐         ┌─────────────┐
│   WS 进程   │         │  Web 进程   │
│ 注册/吊销   │         │  仅读不写   │
│ api_keys    │         │  api_keys   │
└──────┬──────┘         └──────┬──────┘
       │  write                │  read (5s poll)
       ▼                       ▼
    ┌─────────────────────────────┐
    │     _api_keys.json          │
    │     (原子写入)              │
    └─────────────────────────────┘
```

**现状分析：** Web 端当前不写 `_api_keys`，因此不存在双进程写竞争。未来若 Web 端需要写 `_api_keys`（例如 Web 控制台吊销 key），解决方案：

1. **首选：** Web 端只通过 WS 端 API 写（HTTP 请求 `127.0.0.1:8765/api/revoke_key`）
2. **备选：** 引入文件锁（`fcntl.flock` 或 `portalocker`），但增加复杂度
3. **不推荐：** 双进程直接写同一文件（即使原子写入，也会丢失另一方的修改）

**当前结论：** 无需额外锁机制。Web 端只读，WS 端独占写。

### Web sessions 竞争

`_web_sessions.json` 仅 Web 端读写，无竞争。`_approved_users.json` 同理。

---

## 5. config.py 减法（181→~40 行）

### 当前 server/config.py（176 行）删除清单

进入 common 的变量用 ✅ 标出，删除（移入 ws-server）的用 ❌：

```python
# ── 保留在 common（双进程共用）──
HOST                   ✅  Web 端也需要绑定地址
PORT                   ✅  WS 端口（web 端需要知道以 poll /api/status）
HTTP_PORT              ✅  Web 端自己端口
APP_ID                 ✅  双进程共用标识
DATA_DIR               ✅  双进程共享目录
ADMIN_AGENTS           ✅  Web 端需要过滤管理员显示
HIDDEN_AGENTS          ✅  Web 端需要在 agent 列表隐藏
SERVER_INBOX_CHANNEL   ✅  R87 中继通道（双进程发送/解析）
DISPATCH_SENDER_ID     ✅  R102 通知目标（双进程）
WS_ENV / IS_PRODUCTION ✅  双进程需要知道运行环境

# ── 移入 ws-server 专有 config（约 130 行）──
CHAT_LOG_DIR           ❌  Web 端改用 DB 查询，不再写日志文件
GITHUB_OAUTH_CLIENT_ID      ❌  → 移入 web-ui（仅 web 端 OAuth）
GITHUB_OAUTH_CLIENT_SECRET  ❌  → 同上
GITHUB_OAUTH_REDIRECT_URI   ❌  → 同上
OAUTH_NAME_MAP              ❌  → 同上
_oauth_file / 文件读取      ❌  → 同上
GIT_REMOTE_URL              ❌  WS 管线验证用
WORK_PLAN_REPO_URL          ❌  WS 管线用
PIPELINE_PM_NAME            ❌  WS 管线用
PIPELINE_STEP_MAP           ❌  WS 管线用
PIPELINE_ARCH_FROM_NAME     ❌  WS 管线用
PIPELINE_ROLE_OVERRIDES     ❌  WS 管线用
ENABLE_GIT_SYNC             ❌  WS 管线用
GIT_SYNC_INTERVAL/BRANCH/FALLBACK/REPO_PATH  ❌  WS 管线用
ENABLE_VALIDATION_HOOK      ❌  WS 管线用
VALIDATION_DEFAULT_SCRIPT   ❌  WS 管线用
VALIDATION_DEFAULT_TIMEOUT  ❌  WS 管线用
PIPELINE_PM_AGENT_ID        ❌  WS 管线用
```

### 精简后 common/config.py 约 40 行

```python
"""双进程共享配置 — 仅 env 读取，无逻辑。"""
import os
from pathlib import Path

HOST = os.environ.get("WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_PORT") or os.environ.get("PORT", "8765"))
HTTP_PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8765"))
APP_ID = os.environ.get("WS_APP_ID", "hermes-ws")
DATA_DIR = Path(os.environ.get("WS_DATA_DIR", "./data"))

ADMIN_AGENTS: set[str] = set(
    filter(None, os.environ.get("WS_ADMIN_AGENTS", "").split(","))
)
HIDDEN_AGENTS: set[str] = set(
    filter(None, os.environ.get("WS_HIDDEN_AGENTS", "bot-hermes").split(","))
)

WS_ENV = os.environ.get("WS_ENV", "dev")
IS_PRODUCTION = WS_ENV == "production"

SERVER_INBOX_CHANNEL = "_inbox:server"
DISPATCH_SENDER_ID: str = os.environ.get(
    "DISPATCH_SENDER_ID",
    os.environ.get("WS_PM_AGENT_ID", ""),
)
```

---

## 6. Bot 状态文件传递（时序与竞争条件）

### 现状：R101 内存缓存

`web_service.py` 通过后台协程每 10 秒轮询 WS 进程的 `/api/status` 获取在线 bot 列表：

```python
_BOT_STATUS_CACHE: dict = {"agents": [], "_last_update": 0}

async def _fetch_bot_status() -> dict:
    url = f"http://127.0.0.1:{WSS_PORT}/api/status"
    # ... GET 请求，5s 超时
```

### 时序

```
Web 进程                        WS 进程
  │                               │
  │  ── HTTP GET /api/status ──►  │
  │  ◄── {"agents": [...]} ────  │
  │                               │
  │  (缓存 10s, 下次轮询)         │
  │                               │
  │  ── HTTP GET /api/status ──►  │
  │  ◄── {"agents": [...]} ────  │
```

### 竞争条件

| 场景 | 影响 | 严重度 |
|------|------|--------|
| 轮询间隙 bot 上线 | Web UI 最多滞后 10 秒显示 | 低（可接受） |
| 轮询间隙 bot 离线 | 同上 | 低 |
| WS 进程崩溃重启 | 轮询返回空列表，缓存更新为无 agent | 中（重启后恢复） |
| Web 先于 WS 启动 | 第一次轮询失败，缓存为空 | 低（10s 后恢复） |

### 本阶段方案：保持现状，只做路径调整

1. 将 `_poll_bot_status_loop` 从 `server/web_service.py` 移到 `server/web-ui/main.py`
2. 轮询 URL 从 `127.0.0.1:{PORT}` 改为 `127.0.0.1:{WSS_PORT}`（固定 WS 进程端口）
3. 添加启动重试（Web 启动时最多等 30 秒让 WS 就绪）

```python
async def _wait_for_wss_ready(max_wait=30):
    """启动时等待 WS 进程的 /api/status 就绪。"""
    url = f"http://127.0.0.1:{WSS_PORT}/api/status"
    for i in range(max_wait):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=2) as resp:
                    if resp.status == 200:
                        return True
        except Exception:
            pass
        await asyncio.sleep(1)
    logger.warning("WSS not ready after %ds — bot status cache will start empty", max_wait)
    return False
```

### 未来扩展（非本步）

如需实时性，可添加 Unix socket 事件通知（WS 进程在 bot 上线/离线时向 Web 发信号），但鉴于现有 10 秒轮询已满足需求，当前不做。

---

## 7. Dockerfile + supervisor 更新

### 当前 Dockerfile

```dockerfile
FROM python:3.11-slim
COPY server/ server/        # ← 整个 server/ 包
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/ws-bridge.conf"]
```

### 当前 supervisord.conf

```ini
[program:wss]
command=python3 -u -m server.__main__

[program:web]
command=python3 -u -m server.web_service
```

### 迁移后版本

#### Dockerfile

```dockerfile
FROM python:3.11-slim
# ... (不变)
COPY server/ server/     # ← 不变，server/common/ 和 server/web-ui/ 都在包内
# 最终阶段删除 server/ 后改为：
# COPY server/common/ server/common/
# COPY server/web-ui/   server/web-ui/
# COPY server/ws-server/ server/ws-server/
```

#### supervisord.conf

```ini
[program:wss]
command=python3 -u -m server.ws-server.__main__
directory=/app
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
stopwaitsecs=10

[program:web]
command=python3 -u -m server.web-ui.main
directory=/app
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
stopwaitsecs=5

# 启动顺序：wss 先启动，web 依赖其 /api/status 就绪
# supervisor 不直接支持依赖顺序，web 端通过 _wait_for_wss_ready 自愈
```

### 启动顺序保障

- supervisor 同时启动两个 program
- web-ui 的 `main()` 会等待 WS 就绪（最多 30 秒）
- 若 WS 在 web 之后启动，web 的轮询会在 10 秒内自动发现 WS 就绪
- 任一进程崩溃后 supervisor 自动重启，不影响另一进程

---

## 8. import 迁移清单

### 8.1 web-ui 各文件导入变更

#### `server/web-ui/main.py`（原 `server/web_service.py`）

```
当前导入                          →  目标导入
───────────────────────────────     ──────────────────────────
from .config import DATA_DIR, ...   from server.common.config import DATA_DIR, HOST, PORT as WSS_PORT
from . import web_viewer            from . import viewer  (文件重命名)
from . import persistence           from server.common import persistence
from . import message_store as ms   from server.common import message_store as ms
from . import state as _state       删除（仅 seed _r72_users，改为 persistence 方法）
```

#### `server/web-ui/viewer.py`（原 `server/web_viewer.py`）

```
当前导入                          →  目标导入
───────────────────────────────     ──────────────────────────
from . import auth                  from server.common import auth
from . import config                from server.common import config
from . import persistence           from server.common import persistence
from . import workspace as ws_mod   删除（改为 HTTP poll 获取频道列表）
from . import message_store as ms   from server.common import message_store as ms
from .templates import ...          from .templates import ...
from .main import get_connections   删除（改为 poll _BOT_STATUS_CACHE）
```

> **workspace 依赖替代方案：** `handle_api_channels()` 和 `handle_api_archive()` 原本直接读 workspace 内存。将改为向 WS 进程的 `/api/workspaces` 发 HTTP 请求获取。

#### `server/web-ui/templates.py`（原 `server/templates.py`）

纯 HTML/CSS/JS 模板，无 server 内部导入。直接复制，无变更。

### 8.2 ws-server 各文件导入变更

#### `server/ws-server/__main__.py`（原 `server/__main__.py`）

```
当前导入                          →  目标导入
───────────────────────────────     ──────────────────────────
from .config import HOST, ...       from server.common.config import HOST, PORT, DATA_DIR
from .main import handle_auth, ...  from .main import handle_auth, ...
from .message_store import init_db  from server.common import message_store as ms
    (完整版需 init_db，但 common 层只有只读接口)
    → 改为从 ws-server 自有模块导入完整 message_store 或内联 init_db
from .persistence import ...        from .persistence import ...  (ws-server 版的)
                                    + from server.common import persistence as common_persistence
```

> **关键决策：** `__main__.py` 需要完整版的 `message_store`（含 `init_db`, `save_message` 等）。将：
> 1. 完整版 `message_store.py` 保留在 `ws-server/` 下
> 2. common 层只保留只读子集
> 3. `__main__.py` 中的 `from .message_store import init_db` 改为 `from server.ws-server.message_store import init_db`（包内相对导入）

#### `server/ws-server/main.py`（原 `server/main.py`）

```
当前导入                          →  目标导入
───────────────────────────────     ──────────────────────────
from . import auth                  from server.common import auth
from . import config                from server.common import config
from . import persistence           from . import persistence  (ws-server 拥有的扩展版)
from . import state                 from . import state
from . import message_store as ms   from . import message_store as ms (完整版)
from . import workspace as ws_mod   from . import workspace as ws_mod
... 无变更项                         其余不变
```

#### `server/ws-server/state.py`（原 `server/state.py`）

无 server 内部导入（纯数据容器），直接复制。注意删除或注释掉 `from .pipeline_context import PipelineContextManager` → 改为延迟导入。

#### 其他 ws-server 文件

| 文件 | 涉及 common 的导入 |
|------|-------------------|
| `workspace.py` | 使用 `server.config.DATA_DIR` → `server.common.config.DATA_DIR` |
| `agent_card.py` | 使用 `server.auth` → `server.common.auth` |
| `pipeline_context.py` | 使用 `server.config` → `server.common.config`（仅 DATA_DIR） |
| `pipeline_sync.py` | 使用 `server.config` → `server.common.config` |
| `auto_router.py` | 使用 `server.auth` → `server.common.auth` |
| `commands/` 系列 | 使用 `server.auth`, `server.config`, `server.persistence` 等 |
| `audit.py` | 使用 `server.config.DATA_DIR` → `server.common.config.DATA_DIR` |
| `task_store.py` | 使用 `server.config.DATA_DIR` → `server.common.config.DATA_DIR` + `shared.protocol`（不变） |
| `command_utils.py` | 使用 `server.auth`, `server.config`, `server.state` |

### 8.3 外部文件的导入变更

| 文件 | 当前导入 | 目标导入 |
|------|----------|----------|
| `entrypoint.py` | `from server.persistence import ...`<br>`from server.web_viewer import ...`<br>`from server.__main__ import ...` | 删除（不再使用单体入口） |
| 测试文件 (tests/) | `from server.xxx import ...` | 分情况：<br>• 测试 Web → `from server.web-ui import ...`<br>• 测试 WS → `from server.ws-server import ...`<br>• 测试 shared → `from server.common import ...` |

---

## 附录：文件结构对照

### 迁移前

```
server/
├── __init__.py                   1 行
├── __main__.py                 806 行  ← WS 主入口
├── main.py                    3648 行  ← WS 核心逻辑
├── state.py                    126 行
├── config.py                   176 行
├── persistence.py              135 行
├── auth.py                     156 行
├── message_store.py            245 行
├── web_service.py              105 行  ← Web 入口
├── web_viewer.py               677 行  ← Web UI 逻辑
├── templates.py                767 行  ← HTML 模板
├── workspace.py                460 行
├── workspace_api.py             35 行
├── agent_card.py               429 行
├── audit.py                     94 行
├── task_store.py               184 行
├── pipeline_context.py          ? 行
├── pipeline_sync.py             ? 行
├── auto_router.py               ? 行
├── timeout_tracker.py           ? 行
├── command_utils.py             ? 行
└── commands/
    ├── __init__.py
    ├── admin.py
    ├── agent_card.py
    ├── task.py
    ├── pipeline.py
    └── workspace.py
```

### 迁移后

```
server/
├── __init__.py         ← 过渡期仅含 __version__
├── common/             ← 共享层
│   ├── __init__.py
│   ├── config.py       ~40 行
│   ├── persistence.py  ~80 行
│   ├── auth.py        ~100 行
│   └── message_store.py ~60 行
├── web-ui/             ← Web HTTP 服务
│   ├── __init__.py
│   ├── main.py         搬运 + 改造
│   ├── viewer.py       搬运 + 改造
│   └── templates.py    搬运（不变）
└── ws-server/           ← WebSocket 服务
    ├── __init__.py
    ├── __main__.py
    ├── main.py
    ├── state.py
    ├── message_store.py  (完整版)
    ├── persistence.py    (扩展版，含 web sessions 等)
    ├── workspace.py
    ├── workspace_api.py
    ├── agent_card.py
    ├── ...
    ├── command_utils.py
    └── commands/
```

---

## 版本标签

- **文档版本：** v1.0
- **架构师：** 小开
- **预计工时：** 1.5 — 2 人天
- **风险等级：** 🟡 中（import 路径变更较多，需回归测试）
