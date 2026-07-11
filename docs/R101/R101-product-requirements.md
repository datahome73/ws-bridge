# R101 — WSS/Web 解耦：Web 界面独立为服务 🧹

> **状态**: 需求草稿
> **PM**: 小谷
> **目标版本**: v3.0
> **优先级**: P0 (架构级)

---

## 一、背景

### 1.1 当前问题

经过 R100 的 handler.py→main.py 拆分后，服务端的**核心/插件**边界已经清晰。但还有一个更大的架构问题：**Web HTTP 服务与 WSS 核心在同一进程内紧密耦合**。

当前 `__main__.py` 创建一个 `aiohttp.web.Application` 同时承载：

```
__main__.py (aiohttp app)
├── /ws                      WSS 核心（bot 通信）
├── /, /chat                 HTTP — Web 页面
├── /api/chat                  HTTP — 聊天 API
├── /api/channels              HTTP — 频道列表 API
├── /api/inbox                 HTTP — 收件箱 API
├── /api/bind, /api/check      HTTP — 绑定码
├── /api/agents/status         HTTP — 在线状态
├── /auth/github/*             HTTP — GitHub OAuth 登录
├── /api/logout, /api/auth/me  HTTP — 会话管理
├── /api/archive               HTTP — 归档
├── /ws/chat                   HTTP — Web 端 WS 推流
└── ...                        
```

**耦合的具体表现：**

| 耦合点 | 文件 | 行数 |
|:-------|:-----|:-----|
| `write_chat_log()` 23 处调用 | main.py / command_utils.py / commands/pipeline.py / commands/workspace.py / __main__.py | 每次消息广播都触发 |
| `_ws_clients` 引用 | main.py:1269, __main__.py:25,609-610 | Web 端 WS 推流 |
| `setup_routes()` 调用 | __main__.py:797,813 | 注册全部 HTTP 路由 |
| `from .web_viewer import ...` | 6 个文件 | 代码级耦合 |
| `web_viewer.py` 共享模块状态 | _chat_buffers, _ws_clients, write_chat_log | 同一进程内共享内存 |

### 1.2 核心判断

> **去掉 Web 界面，bot 之间还能正常收发 inbox 消息吗？**

**能。** Bot 通信走 WSS，消息持久化走 `message_store.save_message()`（SQLite DB）。Web 界面只看已有数据，不参与通信逻辑。

**Web 界面本质上是一个只读的数据查看器。** 有和没有，不影响 bot 之间的任何沟通交流。

### 1.3 不设实时推送

David 明确：Web 端**不需要 WebSocket 实时推送**。

| 端 | 获取新数据方式 | 延迟容忍 |
|:---|:--------------|:---------|
| 桌面浏览器 | 每 5 秒 fetch() 轮询 `/api/chat?since=xxx` | 5 秒 |
| 手机浏览器 | 下拉刷新 | 用户手势触发 |

Bot 间的聊天消息不需要及时反映到网页端，有延迟完全不影响。

---

## 二、目标

### 2.1 R101 范围

| # | 目标 | 衡量标准 |
|:-:|:-----|:---------|
| 1 | WSS 核心不再 import `web_viewer` | 全部 6 处 `from .web_viewer import ...` 从 WSS 代码中移除 |
| 2 | `write_chat_log()` 从 WSS 核心移除 | 0 处 `write_chat_log` 调用在 `server/main.py`/`command_utils.py`/`commands/` 中 |
| 3 | `_ws_clients` 从 WSS 核心移除 | 0 处 `_ws_clients` 引用在 `server/main.py`/`server/__main__.py` 中 |
| 4 | `setup_routes()` 从 `__main__.py` 移除 | `__main__.py` 只注册 `/ws` 路由 |
| 5 | Web 服务独立启动 | 独立的入口文件/目录，独立的端口 |
| 6 | Web 服务通过 DB 轮询获取数据 | 5 秒轮询 + 下拉刷新正常工作 |

### 2.2 非目标

- ❌ 不改动消息存储层（`message_store.py` 不变）
- ❌ 不改动 WSS 核心的消息路由逻辑（`main.py` 核心保留）
- ❌ 不改动 bot 通信协议（`protocol.py` 不变）
- ❌ 不重写 Web 前端（HTML/JS 模板尽可能复用）
- ❌ 不改动管线命令系统

---

## 三、方案

### 3.1 架构变化

```
当前（同一进程）:
  __main__.py
  ├── /ws (WSS)
  ├── /api/chat (HTTP) 
  ├── /, /chat (HTML)
  └── ...

R101（拆为两个独立服务）:
  WSS 核心 (端口 8765)
  └── __main__.py
        ├── /ws                ← 只注册 WS 路由
        ├── /api/status
        ├── /api/health
        └── /api/workspaces
  
  Web 服务 (端口 8766)
  └── web_app.py (或 web_service/ 目录)
        ├── /, /chat           ← HTML 页面
        ├── /api/chat          ← 从 DB 读数据
        ├── /api/channels
        ├── /api/inbox
        ├── /api/bind, /api/check
        ├── /api/agents/status
        ├── /auth/github/*
        ├── /api/logout, /api/auth/me
        ├── /api/archive
        └── ...
```

### 3.2 数据流

```
Bot A ──WSS──→ handle_broadcast() ──→ save_message(DB) ──→ SQLite DB
                                           │
                                           └── [不再调用 write_chat_log]
                                                
Web 前端 ──fetch──→ handle_api_chat() ──→ get_messages_since(DB) ←── SQLite DB
                    (每 5 秒轮询)
```

**关键变化：** WSS 核心不再写日志文件、不再维护 `_chat_buffers`、不再维护 `_ws_clients`。Web 服务直接从 DB 读数据。

### 3.3 目录结构变更

```
server/                          server/
├── __main__.py   (832行)   →   ├── __main__.py          (~50行)  只 WSS
├── main.py                    ├── main.py               (去掉 write_chat_log)
├── web_viewer.py  (725行)  →   ├── web_viewer.py        保留（Web 服务共享）
├── command_utils.py           ├── command_utils.py      (去掉 write_chat_log)
├── commands/                  ├── commands/
│   ├── pipeline.py            │   ├── pipeline.py       (去掉 write_chat_log)
│   └── workspace.py           │   └── workspace.py      (去掉 wv 引用)
└── ...                        └── ...

新增:
  web_service/
  ├── __main__.py              ← HTTP 服务入口
  └── app.py (可选)            ← 或直接引用 server.web_viewer + server 模块
```

### 3.4 Web 服务如何工作

Web 服务是一个**纯 HTTP 服务**，不建立任何 WebSocket 连接。它：

1. **共享 server 模块** — 读同一份 SQLite DB (`messages.db`)
2. **使用已有的 API** — `message_store.get_messages_since()`, `get_messages_by_channel()`, `get_messages_by_channel_pattern()`
3. **复用 `web_viewer.py`** — `handle_api_chat`, `handle_api_inbox`, `handle_api_channels` 等 handler 函数逻辑不变，只是入口改成独立 aiohttp app
4. **读取聊天日志文件** — 对历史的日志文件（DB 为空时的 fallback），**不需要再写新的**
5. **前端轮询** — JS 中每 5 秒 `fetch(/api/chat?channel=X&since=latest_ts)` 获取新消息

### 3.5 端口分配

| 服务 | 环境变量 | 默认端口 |
|:-----|:---------|:---------|
| WSS 核心 | `WS_PORT` | 8765 |
| Web 服务 | `WS_HTTP_PORT` | 8766 |

`config.py` 中已有 `HTTP_PORT` 配置项，可复用。

---

## 四、执行计划

### Step 1: 清理 WSS 核心对 web_viewer 的依赖

**移除全部 `write_chat_log()` 调用：**

| 文件 | 调用数 | 替换方式 |
|:-----|:------:|:---------|
| `main.py` | 13 | 全部删除 — 日志文件 + WS 推送不再需要 |
| `command_utils.py` | 2 | 全部删除 |
| `commands/pipeline.py` | 4 | 全部删除 |
| `commands/workspace.py` | 1 | 全部删除 |
| `__main__.py` | 3 | 全部删除 |

> **确认：** `save_message()` 已经在 `handle_broadcast()` 中调用，消息已被持久化到 DB。删除 `write_chat_log` 不影响任何 bot 通信。

**移除 `_ws_clients` 引用：**

- `main.py:1269` — `from .web_viewer import _ws_clients as _web_clients` → 删除
- `__main__.py:609-610` — `_ws_clients.discard(ws)` → 删除（这是 web WS 客户端断开时的清理，WSS 核心不再管）

**移除 `setup_routes()` 调用：**

- `__main__.py:797` — `from .web_viewer import setup_routes as _setup_routes` → 删除
- `__main__.py:813` — `setup_routes(app)` → 删除

### Step 2: 清理 import

| 文件 | 删除的 import |
|:-----|:--------------|
| `main.py:25` | `from .web_viewer import write_chat_log` |
| `command_utils.py:14` | `from .web_viewer import write_chat_log` |
| `commands/pipeline.py:17` | `from ..web_viewer import write_chat_log` |
| `commands/workspace.py:136` | `from . import web_viewer as wv`（对应使用 wv 的地方也删） |
| `__main__.py:25` | `from .web_viewer import setup_routes, _ws_clients, write_chat_log`（+ 删除行 797） |

### Step 3: 简化 `__main__.py`

只保留：

```python
# server/__main__.py — 只做 WSS

async def ws_handler(request): ...
async def _api_status(request): ...
async def _api_health(request): ...
async def _auth_callback(request): ...

async def _broadcast_workspace_closing_aiohttp(ws_id): ...

def main():
    app = web.Application()
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/status", _api_status)
    app.router.add_get("/api/health", _api_health)
    app.router.add_get("/auth-callback", _auth_callback)
    app.router.add_get("/api/workspaces", _ws_api.api_workspaces)
    web.run_app(app, host=HOST, port=PORT)
```

从 ~832 行降至 ~50 行。

### Step 4: 创建 Web 服务入口

**方案 A（推荐）：在 `server/web_service.py` 中创建独立入口**

```python
# server/web_service.py — Web HTTP 服务入口
import os
from aiohttp import web
from .config import DATA_DIR
from . import web_viewer
from . import persistence
from . import message_store as ms

HOST = os.environ.get("WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8766"))

def main():
    persistence.load_web_sessions(DATA_DIR)
    ms.init_db(DATA_DIR)
    
    app = web.Application()
    web_viewer.setup_routes(app)
    
    print(f"WEB READY: http://{HOST}:{PORT}/", flush=True)
    web.run_app(app, host=HOST, port=PORT)

if __name__ == "__main__":
    main()
```

可单独运行：
```bash
cd /opt/data/ws-bridge && uv run python3 -m server.web_service
```

**方案 B：新建 `web_service/` 目录**（目录层级分离更干净）

```
web_service/
├── __main__.py     ← 入口
└── app.py          ← aiohttp app 构建
```

两种方案均可复现 `__main__.py` 被剥离的 web 路由。**推荐方案 A**（改动最小，共享 server 模块无需复制）。

### Step 5: 更新前端轮询

在 `templates.py` 的 HTML/JS 中，原来用 WebSocket 接收实时消息的部分改为：

```javascript
// 删除 WebSocket 连接代码
// 改为每 5 秒轮询

let lastTs = Date.now() / 1000;

async function pollMessages() {
    const resp = await fetch(`/api/chat?channel=${currentChannel}&since=${lastTs}&token=${token}`);
    const data = await resp.json();
    if (data.messages && data.messages.length > 0) {
        for (const msg of data.messages) {
            appendMessage(msg);
            if (msg.ts > lastTs) lastTs = msg.ts;
        }
    }
}

// 初始加载 + 每 5 秒轮询
pollMessages();
setInterval(pollMessages, 5000);

// 手机下拉刷新
// 用 touch 事件检测下拉手势 → pollMessages()
```

### Step 6: 部署 + 验证

1. 推 dev → 部署到 dev 环境
2. 验证 WSS 核心：bot A 发 inbox 消息到 bot B → bot B 收到
3. 验证 Web 服务：打开 `http://host:8766/` → 能看到聊天历史
4. 验证轮询：发一条新消息 → 5 秒内 Web 端显示
5. 验证独立：停掉 Web 服务 → bot 通信不受影响
6. 验证独立：停掉 WSS 核心 → Web 端显示历史数据（无实时更新）

---

## 五、验收标准

### 5.1 核心通路

| # | 验证项 | 方法 |
|:-:|:------|:-----|
| 1 | Bot inbox 通畅 | Bot A 发 `_inbox:bot_b` → Bot B 收到并回复 |
| 2 | WSS 核心无 web_viewer import | `grep -rn 'web_viewer' server/main.py server/__main__.py server/command_utils.py server/commands/` → 0 |
| 3 | WSS 核心无 `write_chat_log` 调用 | `grep -rn 'write_chat_log' server/main.py server/__main__.py server/command_utils.py server/commands/` → 0 |
| 4 | WSS 核心无 `_ws_clients` 引用 | `grep -rn '_ws_clients' server/main.py server/__main__.py` → 0 |

### 5.2 Web 服务

| # | 验证项 | 方法 |
|:-:|:------|:-----|
| 5 | Web 服务独立启动 | `python3 -m server.web_service` → `READY: http://0.0.0.0:8766/` |
| 6 | 聊天页面可访问 | 浏览器打开 `http://host:8766/` → 显示绑定码/聊天页面 |
| 7 | 聊天历史可读 | 进入聊天页 → 能看到消息列表 |
| 8 | 轮询更新 | 发一条新消息 → 5 秒内 Web 端自动出现 |
| 9 | 手机下拉刷新 | 浏览器模拟手机 → 下拉手势 → 加载新消息 |

### 5.3 解耦验证

| # | 验证项 | 方法 |
|:-:|:------|:-----|
| 10 | 停 Web 服务→bot 通信正常 | `kill web_service` → bot 收发 inbox 确认正常 |
| 11 | 停 WSS 服务→Web 显示历史 | `kill ws_core` → Web 端显示已有数据 |
| 12 | 只有一个端口/进程时不影响 | 任一服务独立运行，不依赖另一个 |

---

## 六、风险与缓解

| 风险 | 缓解 |
|:-----|:------|
| 删除 `write_chat_log` 后日志文件停止更新，历史 fallback 失效 | 已有数据在 DB 中完整保存。日志文件只作为 DB 为空的回退，不影响 |
| 现有机器人/脚本依赖日志文件 | 检查是否有外部进程读取 `data/chat_logs/` 目录。如有需同步迁移 |
| `_ws_clients` 原用于 Web 端实时推送，移除后 Web 端不再实时 | David 已确认 5 秒轮询方案，可接受 |
| 前端 HTML 模板中仍有 WebSocket 代码 | Step 5 替换为 fetch + setInterval 轮询 |
| `_broadcast_workspace_closing_aiohttp()` 中用到 `_ws_clients` 判断 | 该函数的 web 推送部分改为由 Web 服务处理，或在关闭工作室时通知仅通过 inbox 发送 |

---

## 七、文件清单

### 新增文件

| 文件 | 内容 | 行数 |
|:-----|:------|:-----|
| `server/web_service.py` | Web 服务独立入口 | ~30 |
| 或 `web_service/__main__.py` | 新目录独立入口 | ~40 |

### 修改文件

| 文件 | 变更内容 |
|:-----|:---------|
| `server/__main__.py` | 删除 web_viewer import / setup_routes / write_chat_log / _ws_clients，从 832 → ~50 行 |
| `server/main.py` | 删除 13 处 write_chat_log 调用 + _ws_clients import |
| `server/command_utils.py` | 删除 2 处 write_chat_log 调用 + import |
| `server/commands/pipeline.py` | 删除 4 处 write_chat_log 调用 + import |
| `server/commands/workspace.py` | 删除 wv import + 1 处 write_chat_log 调用 |
| `server/web_viewer.py` | 删除 handle_ws_chat（Web 端不再需要 WS）、清理 _ws_clients 推送逻辑 |
| `server/templates.py` | HTML/JS 中 WS 连接代码 → fetch 轮询代码 |
| `server/config.py` | 确认 HTTP_PORT 配置项，视情况调整默认值 |

### 删除/无需改动

| 文件 | 说明 |
|:-----|:------|
| `server/message_store.py` | ✅ 不变——WSS 核心和 Web 服务都依赖它 |
| `server/auth.py` | ✅ 不变——Web 服务共享 |
| `server/persistence.py` | ✅ 不变 |
| `server/workspace.py` | ✅ 不变 |
| `server/protocol.py` | ✅ 不变 |
| `server/agent_card.py` | ✅ 不变 |
| `server/task_store.py` | ✅ 不变 |
| `data/chat_logs/` 目录 | ✅ 已有历史日志文件继续存在，Web 服务可读取作为 fallback |

---

## 八、参考

- [server/README.md](../server/README.md) — 架构文档
- [web_viewer.py 当前路由](../server/web_viewer.py) — `setup_routes()` 中全部路由注册
- [message_store.py API](../server/message_store.py) — `get_messages_since()` 等查询接口
- [R100 拆分经验](../R100/R100-product-requirements.md) — 类似的核心/插件分离模式
