# R76 技术方案 — Inbox 可视化 + 时间切片归档 📬

> **版本：** v1.0
> **状态：** ✅ 技术方案
> **架构师：** 👷 架构师
> **日期：** 2026-07-08
> **基于需求：** docs/R76/R76-product-requirements.md v1.0
> **基线：** `892c5c77`（main）
> **改动范围：** `server/web_viewer.py` `server/templates.py` `server/handler.py` `server/message_store.py` `server/auth.py`

---

## 目录

1. [方向 A：Inbox Tab 混合展示](#1-方向-ainbox-tab-混合展示)
   - [A1 — 后端：Inbox 聚合 API](#a1--后端inbox-聚合-api)
   - [A2 — 前端：Inbox Tab](#a2--前端inbox-tab)
   - [A3 — 消息渲染格式](#a3--消息渲染格式)
   - [A4 — WebSocket 实时推送 + 未读红点](#a4--websocket-实时推送--未读红点)
2. [方向 B：时间切片归档](#2-方向-b时间切片归档)
   - [B1 — 归档全局状态存储](#b1--归档全局状态存储)
   - [B2 — 关闭工作室触发归档标记](#b2--关闭工作室触发归档标记)
   - [B3 — API 查询扩展（since 参数 + 归档 API）](#b3--api-查询扩展since-参数--归档-api)
   - [B4 — 前端状态机](#b4--前端状态机)
3. [辅助函数：get_agent_name()](#3-辅助函数get_agent_name)
4. [改动汇总](#4-改动汇总)
5. [兼容性分析](#5-兼容性分析)
6. [风险与缓解](#6-风险与缓解)

---

## 1. 方向 A：Inbox Tab 混合展示

### A1 — 后端：Inbox 聚合 API

#### 1.1 API 契约

```
GET /api/chat/inbox?token={token}&limit={n}&since={ts}

Response 200:
{
  "messages": [
    {
      "ts": 1749200000.0,
      "from_name": "需求分析师",
      "to_name": "架构师",
      "to_agent": "ws_xxxxxxxxxxxx",
      "channel": "_inbox:ws_xxxxxxxxxxxx",
      "content": "R76技术方案请评估一下"
    }
  ]
}

Response 401 (无 token 或 token 无效):
{ "error": "unauthorized" }
```

#### 1.2 实现 —— `handle_api_inbox()`

**位置：** `server/web_viewer.py`，新增函数，按现有 `handle_api_chat` 模式实现。

```python
async def handle_api_inbox(request: web.Request) -> web.Response:
    """Return aggregated inbox messages with resolved recipient names."""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)

    limit = int(request.query.get("limit", "50"))
    since = request.query.get("since", None)
    since = float(since) if since else None

    try:
        db_msgs = ms.get_messages_by_channel_pattern(
            "_inbox:%", config.DATA_DIR, limit=limit, since=since
        )
    except Exception:
        db_msgs = []

    # 解析接收人：从 channel 名提取 agent_id → 反查显示名
    for m in db_msgs:
        owner_id = persistence.resolve_inbox_owner(m.get("channel", ""))
        m["to_name"] = auth.get_agent_name(owner_id) if owner_id else (owner_id or "?")
        m["to_agent"] = owner_id or ""

    return web.json_response({"messages": db_msgs})
```

#### 1.3 新增 DB 查询 —— `get_messages_by_channel_pattern()`

**位置：** `server/message_store.py`，新增函数。已有 `get_messages_by_channel()`（精确匹配）和 `get_messages_since()`（时间范围），缺 LIkE 模式匹配。

```python
def get_messages_by_channel_pattern(
    pattern: str, data_dir: Path, limit: int = 50, since: float | None = None
) -> list[dict]:
    """Retrieve messages from channels matching a SQL LIKE pattern.
    
    Pattern uses '%' as wildcard (e.g. '_inbox:%' matches all inbox channels).
    Since the `channel` column has an index (idx_messages_channel), 
    a LIKE query with a prefix pattern ('_inbox:%') still hits the index.
    """
    db_path = str(data_dir / DEFAULT_DB_NAME)
    if not Path(db_path).exists():
        return []
    conn = _get_conn(db_path)
    try:
        query = (
            "SELECT msg_id, msg_type, from_agent, from_name, content, ts, channel "
            "FROM messages WHERE channel LIKE ?"
        )
        params: list = [pattern]
        if since is not None:
            query += " AND ts > ?"
            params.append(since)
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()
```

**索引分析：** `channel` 字段已有索引 `idx_messages_channel`。LIKE 模式 `_inbox:%` 以 `_inbox:` 作为前缀——对 SQLite 而言，LIKE 模式如果以固定前缀开头（不含前导通配符），仍可利用 B-tree 索引进行范围扫描。性能与精确匹配接近。

#### 1.4 路由注册

```python
# 在 setup_routes() 中追加：
app.router.add_get("/api/chat/inbox", handle_api_inbox)
```

插入位置：L534 (`/api/chat`) 之后。

---

### A2 — 前端：Inbox Tab

#### 2.1 Tab 定义

在 `CHAT_TEMPLATE` 的 `TAB_STATE` 中新增第 5 个固定 Tab：

```javascript
// 当前 4-TAB_STATE:
//   tab1: 大厅, tab2: 活跃工作室, tab4: 管理员, tab3: 历史查看器
//
// R76: 新增 tab5（收件箱），置于 tab4 和 tab3 之间
const TAB_STATE = {
  tab1: { id: 'tab1', channel: 'lobby',       label: '🌐 大厅',     permanent: true,  visible: true },
  tab2: { id: 'tab2', channel: null,           label: '📋 活跃',     permanent: false, visible: false },
  tab4: { id: 'tab4', channel: '_admin',       label: '🔧 管理员',   permanent: true,  visible: true },
  tab5: { id: 'tab5', channel: '__inbox__',    label: '📬 收件箱',   permanent: true,  visible: true },
  tab3: { id: 'tab3', channel: null,           label: '🗂️ 历史查看器', permanent: true,  visible: true },
};
```

#### 2.2 Tab 渲染顺序

当前 `renderTabBar()` 顺序：tab2 → tab1 → tab4 → tab3

新顺序：**tab2（活跃）→ tab1（大厅）→ tab4（管理员）→ tab5（收件箱）→ tab3（历史查看器）**

```javascript
function renderTabBar() {
  const bar = document.getElementById('tabBar');
  var html = '';
  // Tab 2: 活跃工作室（最常用，排第一）
  if (TAB_STATE.tab2.visible && TAB_STATE.tab2.channel) { ... }
  // Tab 1: 大厅（始终可见）
  html += '<div class="tab' + (...tab1...) + '">🌐 大厅</div>';
  // Tab 4: 管理员（始终可见）
  html += '<div class="tab admin-tab' + (...tab4...) + '">🔧 管理员</div>';
  // R76: Tab 5: 收件箱（始终可见）+ 未读红点
  const inboxUnread = unreadCounts['__inbox__'] || 0;
  html += '<div class="tab' + (activeTabId === 'tab5' ? ' active' : '') + '" data-tab="tab5" onclick="selectTab(\'tab5\')">📬 收件箱' +
    (inboxUnread > 0 ? '<span class="badge">' + inboxUnread + '</span>' : '') + '</div>';
  // Tab 3: 历史查看器
  html += '<div class="tab' + (...tab3...) + '">🗂️ 历史查看器</div>';
  bar.innerHTML = html;
}
```

#### 2.3 收件箱 Tab 无输入框

`selectTab('tab5')` 时隐藏输入区域：

```javascript
function selectTab(tabId) {
  // ... 现有逻辑 ...
  if (tabId === 'tab5') {
    // Inbox Tab：只读，无输入
    document.getElementById('inputArea').style.display = 'none';
    loadInboxMessages();
  } else {
    document.getElementById('inputArea').style.display = '';
    // ... 现有加载逻辑 ...
  }
}
```

---

### A3 — 消息渲染格式

#### 3.1 `loadInboxMessages()` 函数

```javascript
async function loadInboxMessages(since) {
  const list = document.getElementById('msgList');
  list.innerHTML = '<div class="empty">加载中...</div>';
  let url = '/api/chat/inbox?limit=50&token=' + encodeURIComponent(TOKEN);
  if (since) url += '&since=' + since;
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error('fetch failed');
    const data = await resp.json();
    const msgs = data.messages || [];
    list.innerHTML = '';
    if (msgs.length === 0) {
      list.innerHTML = '<div class="empty">暂无收件箱消息</div>';
      return;
    }
    // 最新消息在上（API 已按 ts DESC 排序）
    for (const m of msgs) {
      list.appendChild(createInboxMessageEl(m));
    }
  } catch(e) {
    list.innerHTML = '<div class="empty">加载失败</div>';
  }
}
```

#### 3.2 `createInboxMessageEl()` — 带收发人的消息渲染

```javascript
function createInboxMessageEl(m) {
  const div = document.createElement('div');
  div.className = 'msg bot';
  const sender = m.from_name || '';
  const receiver = m.to_name || '';
  const cls = colorMap[sender] || 'unknown';
  div.innerHTML =
    '<div class="meta">' +
      '<span class="ts">' + formatTime(m.ts) + '</span>' +
      '<span class="sender s-' + cls + '">' + escapeHtml(sender) + '</span>' +
      '<span style="color:#8b949e;margin:0 4px;">→</span>' +
      '<span style="color:#8b949e;font-size:0.85rem;">' + escapeHtml(receiver) + '</span>' +
    '</div>' +
    '<div class="content">' + escapeHtml(m.content || '') + '</div>';
  return div;
}
```

**渲染效果：**
```
[14:23] 需求分析师 → 架构师
R76的技术方案请评估一下
```

---

### A4 — WebSocket 实时推送 + 未读红点

#### 4.1 WS 消息处理

当前 `ws.onmessage` 处理 `chat_message` 类型的广播。R76 扩展：

```javascript
ws.onmessage = function(e) {
  let data;
  try { data = JSON.parse(e.data); } catch(e) { return; }

  if (data.type === 'chat_message') {
    const ch = data.channel || 'lobby';
    const msg = data.message || data;

    if (ch.startsWith('_inbox:')) {
      // inbox 消息 → 追加到 inbox 内部缓存
      if (!window._inboxCache) window._inboxCache = [];
      window._inboxCache.push(msg);

      if (activeTabId !== 'tab5') {
        // 不在 inbox Tab → 显示未读红点
        unreadCounts['__inbox__'] = (unreadCounts['__inbox__'] || 0) + 1;
        renderTabBar();
      } else {
        // 当前在 inbox Tab → 直接追加渲染
        const list = document.getElementById('msgList');
        list.insertBefore(createInboxMessageEl(msg), list.firstChild);
      }
    } else {
      // 非 inbox 消息 → 现有处理逻辑
      appendMessage(ch, msg);
    }
  }
};
```

#### 4.2 未读红点清除

切换至 inbox Tab 时清除未读计数：

```javascript
function selectTab(tabId) {
  if (tabId === 'tab5') {
    unreadCounts['__inbox__'] = 0;
    renderTabBar();
    // ... loadInboxMessages() ...
  }
}
```

---

## 2. 方向 B：时间切片归档

### B1 — 归档全局状态存储

#### 1.1 设计决策确认 ✅

| 决策项 | 方案 | 依据 |
|:-------|:-----|:------|
| **存储位置** | `config.DATA_DIR / "_archive_state.json"` | 与现有 `_pairing_codes.json`、`_api_keys.json` 等 persistence 文件同目录 |
| **读写模式** | `json.loads` / `json.dumps` 直接文件 I/O | 每次调用即时加载，不缓存——服务器重启不影响 |
| **锁定** | 单文件写入，无需锁（`!close_workspace` 单线程执行） | 确保写入操作的原子性 |

#### 1.2 数据结构

```python
# _archive_state.json
{
  "last_archive_ts": 1749286400.0,
  "archived_workspaces": [
    {
      "id": "ws:xxx-R76-dev",
      "name": "R76-dev",
      "created_at": 1749200000.0,
      "closed_at": 1749286400.0,
      "archive_window": {
        "start": 1749200000.0,
        "end": 1749286400.0
      }
    }
  ]
}
```

#### 1.3 读写函数

**位置：** `server/web_viewer.py`，新增模块级函数。

```python
import json
from pathlib import Path

_ARCHIVE_STATE_FILE = "_archive_state.json"

def _load_archive_state() -> dict:
    """Load archive state from disk. Returns default if file missing."""
    path = config.DATA_DIR / _ARCHIVE_STATE_FILE
    if not path.exists():
        return {"last_archive_ts": 0, "archived_workspaces": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"last_archive_ts": 0, "archived_workspaces": []}

def _save_archive_state(state: dict) -> None:
    """Persist archive state to disk."""
    path = config.DATA_DIR / _ARCHIVE_STATE_FILE
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def set_archive_state(ws_id: str, ws_name: str, start_ts: float) -> None:
    """Record archive entry for a workspace. Called when last workspace closes."""
    now = time.time()
    state = _load_archive_state()
    state["last_archive_ts"] = now
    state["archived_workspaces"].append({
        "id": ws_id,
        "name": ws_name,
        "created_at": start_ts,
        "closed_at": now,
        "archive_window": {"start": start_ts, "end": now},
    })
    _save_archive_state(state)
```

---

### B2 — 关闭工作室触发归档标记

#### 2.1 触发点确认 ✅

**位置：** `server/handler.py`，`_cmd_close_workspace()` 函数末尾。

当前 `!close_workspace` 流程（约 L2630-2690）：验证权限 → 关闭指定 workspace → 广播通知 → 返回成功。

R76 在「关闭成功后」追加：

```python
# R76 B2: 检查是否已无活跃 workspace → 触发归档标记
try:
    from . import workspace as ws_mod
    from . import web_viewer as wv
    active = [w for w in ws_mod.get_all_workspaces()
              if w.state == ws_mod.WorkspaceState.ACTIVE]
    if not active:
        # 所有 workspace 已关闭 → 记录归档状态
        wv.set_archive_state(
            ws_id=closed_ws.id,
            ws_name=closed_ws.name,
            start_ts=closed_ws.created_at.timestamp() if hasattr(closed_ws.created_at, 'timestamp') else time.time(),
        )
        logger.info("R76: Archive triggered — last workspace '%s' closed", closed_ws.name)
except Exception as e:
    logger.warning("R76: Archive state write failed (non-fatal): %s", e)
```

> **注意：** `closed_ws` 是刚关闭的 workspace 对象。此归档写入仅影响「最后一次关闭」——若一次只关一个 workspace，它就是最后一个；若一次关多个，最后执行到这里的 workspace 的时间戳作为归档边界。

#### 2.2 `ws.created_at` 兼容性

`workspace` 对象的 `created_at` 可能是 `datetime` 对象或 float。需要兼容处理：

```python
if hasattr(closed_ws, 'created_at') and closed_ws.created_at:
    if isinstance(closed_ws.created_at, (int, float)):
        start_ts = float(closed_ws.created_at)
    elif hasattr(closed_ws.created_at, 'timestamp'):
        start_ts = closed_ws.created_at.timestamp()
    else:
        start_ts = time.time()
else:
    start_ts = time.time()
```

---

### B3 — API 查询扩展（since 参数 + 归档 API）

#### 3.1 `handle_api_chat()` 扩展 since 参数

**位置：** `server/web_viewer.py`，`handle_api_chat()` L211-247。

当前实现：
```python
channel = request.query.get("channel", "lobby")
limit = int(request.query.get("limit", "50"))
```

R76 扩展：
```python
channel = request.query.get("channel", "lobby")
limit = int(request.query.get("limit", "50"))
# R76 B3: 可选 since 参数 — 只返回该时间戳之后的消息
since = request.query.get("since", None)
if since:
    try:
        since = float(since)
    except (ValueError, TypeError):
        since = None
```

然后传递给 `get_messages_by_channel()`。当前 `get_messages_by_channel()` 不支持 `since`，需要改造：

**方案 A（推荐）：** 若 `since` 有值，调用 `get_messages_since(channel=channel, ts=since)` 替代 `get_messages_by_channel()`。`get_messages_since()` 已支持 channel 过滤。

```python
if since is not None:
    # 支持 since 的查询复用 get_messages_since
    from .message_store import get_messages_since
    db_msgs = get_messages_since(since, config.DATA_DIR, limit=limit, channel=channel)
else:
    db_msgs = ms.get_messages_by_channel(channel, config.DATA_DIR, limit=limit)
```

#### 3.2 新增 `handle_api_archive()` — 全 channel 归档查询

```python
async def handle_api_archive(request: web.Request) -> web.Response:
    """Return all messages from a workspace's archive window, across all channels.
    
    GET /api/chat/archive?workspace_id={id}&token={token}
    """
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)

    ws_id = request.query.get("workspace_id", "")
    if not ws_id:
        return web.json_response({"error": "missing workspace_id"}, status=400)

    state = _load_archive_state()
    ws_info = None
    for ws in state.get("archived_workspaces", []):
        if ws["id"] == ws_id:
            ws_info = ws
            break
    if not ws_info:
        return web.json_response({"error": "workspace not found"}, status=404)

    start = ws_info["archive_window"]["start"]
    end = ws_info["archive_window"]["end"]

    all_msgs = ms.get_messages_by_time_range(start, end, config.DATA_DIR)

    # 为每条消息添加 channel 来源标签 + inbox 收件人解析
    for m in all_msgs:
        ch = m.get("channel", "")
        if ch == "lobby":
            m["_channel_label"] = "大厅"
        elif ch == "_admin":
            m["_channel_label"] = "管理员"
        elif ch.startswith("_inbox:"):
            owner_id = persistence.resolve_inbox_owner(ch)
            to_name = auth.get_agent_name(owner_id) if owner_id else "?"
            m["to_name"] = to_name
            m["to_agent"] = owner_id or ""
            m["_channel_label"] = f"收件箱（{to_name}）"
        else:
            m["_channel_label"] = ch

    return web.json_response({
        "workspace": ws_info["name"],
        "period": ws_info["archive_window"],
        "messages": all_msgs,
        "total": len(all_msgs),
    })
```

#### 3.3 新增 `get_messages_by_time_range()`

**位置：** `server/message_store.py`

```python
def get_messages_by_time_range(
    start_ts: float, end_ts: float, data_dir: Path
) -> list[dict]:
    """Retrieve all messages within a time range, ordered by timestamp ascending."""
    db_path = str(data_dir / DEFAULT_DB_NAME)
    if not Path(db_path).exists():
        return []
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT msg_id, msg_type, from_agent, from_name, content, ts, channel "
            "FROM messages WHERE ts >= ? AND ts <= ? ORDER BY ts ASC",
            (start_ts, end_ts),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()
```

#### 3.4 路由注册

```python
app.router.add_get("/api/chat/inbox", handle_api_inbox)    # 方向 A
app.router.add_get("/api/chat/archive", handle_api_archive) # 方向 B
```

#### 3.5 `handle_api_channels()` 扩展归档状态

Web 前端需要知道当前是否有活跃 workspace，以决定是否启用 `since` 过滤。在 `handle_api_channels()` 的返回值中附加 `archive_state`：

```python
async def handle_api_channels(request: web.Request) -> web.Response:
    """... existing docstring ..."""
    # ... 现有 workspaces 列表构建逻辑不变 ...
    
    # R76 B3: 附加归档状态
    try:
        from . import workspace as ws_mod
        active_ws = [w for w in ws_mod.get_all_workspaces()
                     if w.state == ws_mod.WorkspaceState.ACTIVE]
        state = _load_archive_state()
        archive_state = {
            "active": len(active_ws) > 0,
            "last_archive_ts": state.get("last_archive_ts", 0),
        }
    except Exception:
        archive_state = {"active": True, "last_archive_ts": 0}

    return web.json_response({
        "channels": channels,
        "archive_state": archive_state,
    })
```

---

### B4 — 前端状态机

#### 4.1 状态定义

```javascript
// R76 B4: 归档状态
// 通过 /api/channels 返回的 archive_state 初始化
let archiveMode = false;       // true = 无活跃工作室
let lastArchiveTs = 0;        // 归档时间戳
```

#### 4.2 初始化流程

`init()` 函数中增强：

```javascript
async function init() {
  // ... 现有 channel 加载逻辑 ...
  try {
    const channelsResp = await fetch('/api/channels?token=' + encodeURIComponent(TOKEN));
    if (channelsResp.ok) {
      const channelsData = await channelsResp.json();
      
      // R76: 读取归档状态
      if (channelsData.archive_state) {
        archiveMode = !channelsData.archive_state.active;
        lastArchiveTs = channelsData.archive_state.last_archive_ts || 0;
      }
      
      // ... 现有的 workspace 列表渲染逻辑 ...
      renderTabBar();
    }
  } catch(e) { ... }
}
```

#### 4.3 状态转换

```
创建新 workspace → archiveMode = false, lastArchiveTs 不变（但不影响 since 过滤）
关闭最后活跃 workspace → archiveMode = true, 触发 set_archive_state() 写入
刷新页面 → 从 /api/channels 重新读取 archive_state
```

#### 4.4 各 Tab 加载时的 since 参数

```javascript
function selectTab(tabId) {
  // ... Tab 切换逻辑 ...
  
  if (tabId === 'tab5') {
    // 收件箱 Tab
    unreadCounts['__inbox__'] = 0;
    loadInboxMessages(archiveMode ? lastArchiveTs : null);
  } else if (tab && tab.channel && tab.channel !== '__inbox__') {
    // 普通 Tab（大厅/管理员）
    loadMessages(tab.channel, archiveMode ? lastArchiveTs : null);
  }
}

// loadMessages 扩展 since 参数
async function loadMessages(channel, since) {
  let url = '/api/chat?channel=' + encodeURIComponent(channel)
          + '&limit=50&token=' + encodeURIComponent(TOKEN);
  if (since) url += '&since=' + since;
  // ... 现有 fetch + 渲染逻辑 ...
}
```

#### 4.5 新工作室创建后的恢复

当用户创建新 workspace 时，WebSocket 会收到广播。前端在收到新 workspace 创建的广播时恢复 archiveMode：

```javascript
// 在 ws.onmessage 收到新 workspace 创建时
if (data.type === 'workspace_created') {
  archiveMode = false;
  renderTabBar();
  // 重设各 Tab 加载（取消 since 过滤）
}
```

---

## 3. 辅助函数：get_agent_name()

### 3.1 设计决策 ✅

| 决策项 | 方案 | 依据 |
|:-------|:-----|:------|
| **放置位置** | `server/auth.py` | 已有 `get_users()`、`role_level()`、`is_global_admin()` 等用户查询函数；`persistence.py` 是纯数据层不包含业务逻辑 |
| **查询优先级** | ① `get_users()` → ② `_r72_users` → ③ 截断 agent_id | 与 `handle_broadcast()` 中 sender_name 的解析逻辑一致 |
| **函数签名** | `get_agent_name(agent_id: str, default: str \| None = None) -> str` | 默认截断 agent_id 前 12 位 |

### 3.2 实现

```python
# server/auth.py — 新增函数
def get_agent_name(agent_id: str, default: str | None = None) -> str:
    """Return display name for an agent_id.
    
    Priority:
    1. Traditional users (pre-R72)
    2. R72 users (registered via api_key, stored in handler._r72_users)
    3. Truncated agent_id as fallback (e.g. 'ws_xxxxxxxxxxxx')
    """
    users = get_users()
    name = users.get(agent_id, {}).get("name")
    if name:
        return name
    try:
        from . import handler as _handler
        r72 = getattr(_handler, "_r72_users", {})
        return r72.get(agent_id, {}).get("name", default or agent_id[:12])
    except ImportError:
        return default or agent_id[:12]
```

### 3.3 引用位置

`get_agent_name()` 被以下函数调用：
- `handle_api_inbox()` — 解析 inbox 消息接收人显示名
- `handle_api_archive()` — 归档消息中的 inbox 收件人解析
- 未来可复用

---

## 4. 改动汇总

### 4.1 文件清单

| 文件 | 改动类型 | 行数估算 | 说明 |
|:-----|:---------|:--------:|:-----|
| `server/web_viewer.py` | **新增** `handle_api_inbox()` | ~25 | Inbox 聚合 API |
| `server/web_viewer.py` | **新增** `handle_api_archive()` | ~35 | 归档全 channel 查询 |
| `server/web_viewer.py` | **新增** `_load_archive_state()` | ~12 | 归档状态读取 |
| `server/web_viewer.py` | **新增** `_save_archive_state()` | ~6 | 归档状态写入 |
| `server/web_viewer.py` | **新增** `set_archive_state()` | ~10 | 归档触发写入 |
| `server/web_viewer.py` | **修改** `handle_api_chat()` | ~5 | since 参数扩展 |
| `server/web_viewer.py` | **修改** `handle_api_channels()` | ~10 | 附加 archive_state |
| `server/web_viewer.py` | **修改** `setup_routes()` | ~2 | 新增 2 条路由 |
| `server/templates.py` | **修改** `TAB_STATE` | ~1 | 新增 tab5 |
| `server/templates.py` | **修改** `renderTabBar()` | ~10 | 收件箱 Tab + 未读红点 |
| `server/templates.py` | **修改** `selectTab()` | ~10 | 收件箱路由 + 无输入框 |
| `server/templates.py` | **修改** `loadMessages()` | ~3 | since 参数 |
| `server/templates.py` | **新增** `loadInboxMessages()` | ~20 | 收件箱加载 |
| `server/templates.py` | **新增** `createInboxMessageEl()` | ~12 | 收件箱消息渲染 |
| `server/templates.py` | **修改** WS handler | ~12 | inbox 消息 + 未读红点 |
| `server/templates.py` | **新增** archive 相关 JS | ~40 | 归档模式状态机 |
| `server/handler.py` | **修改** `!close_workspace` | ~15 | 归档触发 |
| `server/message_store.py` | **新增** `get_messages_by_channel_pattern()` | ~20 | LIKE 模式查询 |
| `server/message_store.py` | **新增** `get_messages_by_time_range()` | ~15 | 时间范围查询 |
| `server/auth.py` | **新增** `get_agent_name()` | ~12 | 收件人反查 |
| **合计** | | **~275 行净增** | |

### 4.2 无改动项

| 文件 | 原因 |
|:-----|:------|
| `server/shared/` `server/config.py` | 不改全局配置 |
| `server/persistence.py` | `resolve_inbox_owner()` 已在；归档状态存 web_viewer 自己的文件 |
| `gateway-plugin/` | 网关无需变更 |
| `docs/` 其他文件 | 不在本轮 scope |

### 4.3 操作顺序

```
1. auth.py:    新增 get_agent_name()
2. message_store.py: 新增 get_messages_by_channel_pattern() + get_messages_by_time_range()
3. web_viewer.py:    归档状态函数 + handle_api_inbox + handle_api_archive + since 参数 + 路由
4. handler.py:       close_workspace 归档触发
5. templates.py:     Tab5 收件箱 + 前端状态机 + WS 处理
6. 验证:             curl 测试 API + 浏览器验证 UI
7. commit + push
```

---

## 5. 兼容性分析

### 5.1 旧轮次管线

| 场景 | 当前行为 | 改造后行为 | 兼容性 |
|:-----|:---------|:-----------|:-------|
| 已有活跃 workspace | handle_api_channels 返回 channels | 附加 `"archive_state": {"active": true}` | ✅ 向下兼容（新字段，旧前端忽略） |
| 前端未更新（旧 HTML 缓存） | 无 tab5 | tab5 不存在不影响 | ✅ |
| 无 workspace 时各 Tab 加载 | LOAD 全量消息 | with since=last_archive_ts | ⚠️ 注意：前端 JS 变化需要刷新页面 |

### 5.2 API 向后兼容

| API | 改造 | 兼容性 |
|:----|:------|:-------|
| `GET /api/chat?channel=X&limit=N` | 新增可选 `since` 参数 | ✅ 完全向后兼容（不带 since = 原行为） |
| `GET /api/channels` | 新增 `archive_state` 字段 | ✅ 向下兼容（新字段不影响旧消费者） |
| `GET /api/chat/inbox` | 全新 endpoint | ✅ 新增 |
| `GET /api/chat/archive` | 全新 endpoint | ✅ 新增 |

### 5.3 前端页面加载

HTML 模板通过 `CHAT_TEMPLATE` 在服务器启动时渲染。用户刷新浏览器即获取新模板。无缓存版本问题。

---

## 6. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:-----|:---------|
| `get_messages_by_channel_pattern` 的 LIKE `_inbox:%` 未命中索引 | 低 | 查询慢（inbox 消息量小） | `_inbox:` 前缀是固定值，SQLite 可走 idx_messages_channel 范围扫描。若需优化可加 `channel LIKE '_inbox:%'` 的覆盖索引 |
| `close_workspace` 同时关闭多个 workspace 时竞争条件 | 低 | `last_archive_ts` 只记录最后一个 | `!close_workspace` 在单线程中顺序执行（asyncio）。若需极致安全可加锁 |
| 前端 archiveMode 切换后未及时反映 | 中 | 用户看到错误的消息视图 | 创建/关闭 workspace 后通过 WebSocket 广播状态变化，前端监听实时更新 |
| `ws.created_at` 为 None 或 datetime 对象 | 低 | 归档时间窗口 start 不正确 | 已设计兼容处理 — 优先 `created_at.timestamp()`，回退 `time.time()` |
| `since` 参数在 DB 查询中与现有 `LIMIT` 组合 | 低 | 返回的消息数可能少于 limit | 预期行为 — 时间范围内不足 limit 则返回实际条数 |
| `_archive_state.json` 文件被多个连接同时读取 | 低 | 读竞争 | 写成 `web_viewer.py` 模块级函数，每次调用即时加载。后续如需优化可加 `threading.Lock` |

---

## 7. 脱敏检查清单

- [x] 本文件（R76-tech-plan.md）零内部角色名残留
- [x] 使用通用角色名（需求分析师 / 架构师 / 开发工程师 / 审查工程师 / 测试工程师 / 项目管理 / 项目负责人）
- [x] 不包含真实 agent_id / token
- [x] URL 为公开 GitHub raw URL，不含认证信息
- [x] 代码示例中 `ws_xxxxxxxxxxxx` 为通用占位符
- [x] `colorMap` 中的键名为通用英文（xiaogu/xiaokai 等，非内部名）

---

## 8. 设计决策确认清单

| # | 决策项 | 决策 | 状态 |
|:-:|:-------|:-----|:----:|
| 1 | 归档全局状态存储位置 | `config.DATA_DIR/_archive_state.json`（`_load_json`/`_save_json` 模式） | ✅ 确认 |
| 2 | `get_agent_name()` 放置位置 | `server/auth.py`（已有 get_users 等查询函数） | ✅ 确认 |
| 3 | Inbox 聚合查询方式 | `LIKE '_inbox:%'`（命中 `idx_messages_channel` 索引） | ✅ 确认 |
| 4 | 归档消息查询方式 | `get_messages_by_time_range()`（基于 ts >= start AND ts <= end） | ✅ 确认 |
| 5 | 前端状态机 | `archiveMode` + `lastArchiveTs`，selectTab 时传递 since 参数 | ✅ 确认 |
| 6 | 归档触发点 | `_cmd_close_workspace()` 末尾，检测无活跃 workspace 时调用 `set_archive_state()` | ✅ 确认 |

---

## 9. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-08 | 初稿 — R76 技术方案：方向 A Inbox Tab 后端+前端+WS 推送 + 方向 B 时间切片归档状态机+API+触发点 |
