---
pipeline:
  steps:
    - step: 2
      role: architect
      task: 技术方案
    - step: 3
      role: developer
      task: 编码实现
    - step: 4
      role: reviewer
      task: 代码审查
    - step: 5
      role: qa
      task: 测试验证
    - step: 6
      role: admin
      task: 合并部署
  timeout_minutes: 30
workspace:
  name: R76-dev
  members:
    - name: 架构师
      role: architect
    - name: 开发工程师
      role: developer
    - name: 审查工程师
      role: reviewer
    - name: 测试工程师
      role: qa
    - name: 项目管理
      role: admin
---
# R76 工作计划 — Inbox 可视化 + 时间切片归档 📬

> **版本：** v1.0（初稿）
> **状态：** 📝 待审核
> **项目协调人：** 🧐 PM
> **基于需求文档：** [docs/R76/R76-product-requirements.md](https://raw.githubusercontent.com/datahome73/ws-bridge/ca8979a/docs/R76/R76-product-requirements.md) v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**后端 ~135 行净增 + 前端 ~120 行净增，严禁 scope creep**

| 本轮做 | 本轮不做 |
|:-------|:---------|
| Inbox 聚合 API（`/api/chat/inbox`） | Inbox 发送功能（只读） |
| Inbox Tab 前端展示（混合只读） | inbox 按 bot 分类筛选 |
| 时间切片归档全局状态 | 物理删除数据库消息 |
| `since` 参数 API 扩展 | 归档文件下载/导出 |
| 归档全 channel 历史查看 API | 修改现有消息路由逻辑 |

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | 架构师 | 开发工程师 | — |
| Step 3 | 💻 编码 | 开发工程师 | 架构师 | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | 审查工程师 | 测试工程师 | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | 测试工程师 | 审查工程师 | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | 项目管理 | 架构师 | — |

---

## 1. 管线总览

### 核心架构

R76 涉及两个独立功能，改动文件高度重叠（均修改 `web_viewer.py` + `templates.py`），建议按 A→B 顺序编码：

```
功能 A: Inbox Tab ────  后端: web_viewer.py (handle_api_inbox)
                     └── 前端: templates.py (tab5 + 渲染格式 + WS)

功能 B: 时间切片归档 ──  后端: web_viewer.py (handle_api_archive + 全局状态 + since)
                     └── 后端: handler.py (close_workspace 触发)
                     └── 前端: templates.py (since 过滤 + 历史查看器增强)
```

### 改动范围

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:-----|:----:|
| 1 | A | 新增 `GET /api/chat/inbox` — 聚合所有 `_inbox:*` 消息并反查接收人名 | `server/web_viewer.py` | ~30 行 |
| 2 | A | Web 端 inbox Tab 渲染 + WS 实时推送 + 未读红点 | `server/templates.py`（CHAT_TEMPLATE） | ~60 行 |
| 3 | B | `last_archive_ts` 全局状态读写 + persistence | `server/web_viewer.py` | ~30 行 |
| 4 | B | `!close_workspace` 触发归档标记写入 | `server/handler.py` | ~10 行 |
| 5 | B | `GET /api/chat?channel=X&since=T` since 参数扩展 | `server/web_viewer.py` | ~10 行 |
| 6 | B | 新增 `GET /api/chat/archive?workspace_id=X` — 全 channel 消息 | `server/web_viewer.py` | ~25 行 |
| 7 | B | 历史查看器增强（归档全 channel 展示 + channel 来源标签） | `server/templates.py`（CHAT_TEMPLATE） | ~40 行 |
| 8 | B | 无活跃工作室时各 Tab 自动 since 过滤 | `server/templates.py`（CHAT_TEMPLATE） | ~30 行 |
| 9 | 辅助 | 新增 agent_id→显示名解析函数（供 inbox 收件人反查） | `server/auth.py` 或 `persistence.py` | ~10 行 |

**总估算：** ~245 行净增

---

## 2. 管线步骤

### Step 1：需求审核通过 ✅ → 编写 WORK_PLAN（PM — 本轮）

- 需求文档审核通过 ✅
- WORK_PLAN 编写中
- 状态：📋 当前（PM 推进中）

---

### Step 2：技术方案（Arch — 主角：架构师，备用：开发工程师）

**核心设计问题需要架构师决定：**

#### 2.1 全局状态存储位置

存档状态 `_archive_state.json` 的读写方式：

| 方案 | 做法 | 复杂度 |
|:-----|:------|:------:|
| **方案 A（推荐）** | `config.DATA_DIR/_archive_state.json`，用 `persistence` 模块的 `_load_json`/`_save_json` 模式 | ⭐ 低 |
| 方案 B | 追加到 `workspace.py` 的 workspace metadata 中 | ⭐⭐ 中（侵入现有数据结构） |

建议方案 A，与现有 persist 模式一致。

#### 2.2 结果获取 `_r72_users` 的反查

Inbox 收件人反查需要 `agent_id → name` 映射：

```python
def get_agent_name(agent_id: str) -> str:
    """Return display name for an agent_id, or truncated id as fallback."""
    users = get_users()
    name = users.get(agent_id, {}).get("name")
    if name:
        return name
    # R72 agents registered via api_key live in handler._r72_users
    from . import handler as _handler
    r72 = getattr(_handler, "_r72_users", {})
    return r72.get(agent_id, {}).get("name", agent_id[:12])
```

**确认点：** 建议将此函数放在 `auth.py` 中（已有 `get_users()` 依赖）。

#### 2.3 `handle_api_inbox` 的查询实现

```sql
SELECT * FROM messages WHERE channel LIKE '_inbox:%'
ORDER BY ts DESC LIMIT ?
```

对每条消息，从 `channel = '_inbox:{agent_id}'` 中提取 agent_id → 调用 `get_agent_name()` 获得 `to_name`。

#### 2.4 `handle_api_archive` 的时间窗口查询

```sql
SELECT * FROM messages
WHERE ts >= ? AND ts <= ?
ORDER BY ts ASC
```

不限制 channel，返回所有频道消息。

#### 2.5 前端架构 — 状态机

```
┌─ 有活跃工作室 ─────────────────────────────┐
│  TAB_STATE.archiveMode = false              │
│  各 Tab 加载: since 参数 = null              │
│  历史查看器: 仅 workspace channel 消息        │
└─────────────────────────────────────────────┘
                     ↓  !close_workspace (last one)
┌─ 无活跃工作室 ─────────────────────────────┐
│  TAB_STATE.archiveMode = true                │
│  TAB_STATE.lastArchiveTs = T                 │
│  各 Tab 加载: since = lastArchiveTs          │
│  历史查看器: 全 channel 消息 (archive API)    │
└─────────────────────────────────────────────┘
                     ↓  新 workspace 创建
┌─ 有活跃工作室 ─────────────────────────────┐
│  TAB_STATE.archiveMode = false               │
│  (重置回正常模式)                             │
└─────────────────────────────────────────────┘
```

#### 注意事项

- `handle_api_chat` 的 `since` 参数：当前已有 `limit` 参数，`since` 作为可选 float 参数，注意类型转换（query string 传进来是字符串）
- `handle_api_inbox` 的分页：默认 limit=50，可以加 `offset` 参数
- `write_chat_log` 的 inbox 消息中的 `content` 可能包含较长文本，前端注意截断显示

---

### Step 3：编码（Dev — 主角：开发工程师，备用：架构师）

**精确改动点：**

#### 3.1 `server/auth.py` — 新增 `get_agent_name()`（~10 行）

```python
def get_agent_name(agent_id: str, default: str | None = None) -> str:
    """Return display name for agent_id, or truncated id as fallback."""
    users = get_users()
    name = users.get(agent_id, {}).get("name")
    if name:
        return name
    try:
        from . import handler as _handler
        r72 = getattr(_handler, "_r72_users", {})
        return r72.get(agent_id, {}).get("name", default or agent_id[:12])
    except Exception:
        return default or agent_id[:12]
```

#### 3.2 `server/web_viewer.py` — 后端 API 改动

**① 新增 `handle_api_inbox()`（~30 行）**

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
    
    # 解析接收人
    for m in db_msgs:
        owner_id = persistence.resolve_inbox_owner(m["channel"])
        m["to_name"] = auth.get_agent_name(owner_id) if owner_id else owner_id or "?"
        m["to_agent"] = owner_id or ""
        # 前端用 from_name（已有）
    
    return web.json_response({"messages": db_msgs})
```

**② 新增 `get_messages_by_channel_pattern()` 到 `message_store.py`（~15 行）**

需要在 `message_store.py` 中新增对 `channel LIKE 'pattern'` 的支持：

```python
def get_messages_by_channel_pattern(
    pattern: str, data_dir: Path, limit: int = 50, since: float | None = None
) -> list[dict]:
    db_path = str(data_dir / DEFAULT_DB_NAME)
    conn = _get_conn(db_path)
    query = "SELECT msg_id, msg_type, from_agent, from_name, content, ts, channel FROM messages WHERE channel LIKE ?"
    params = [pattern]
    if since is not None:
        query += " AND ts > ?"
        params.append(since)
    query += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]
```

**③ 新增归档全局状态读写（~30 行）**

```python
_ARCHIVE_STATE_FILE = "_archive_state.json"

def _load_archive_state() -> dict:
    path = config.DATA_DIR / _ARCHIVE_STATE_FILE
    if not path.exists():
        return {"last_archive_ts": 0, "archived_workspaces": []}
    return json.loads(path.read_text(encoding="utf-8"))

def _save_archive_state(state: dict) -> None:
    path = config.DATA_DIR / _ARCHIVE_STATE_FILE
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
```

**④ `handle_api_chat()` 扩展 `since` 参数（~10 行）**

```python
since = request.query.get("since", None)
if since:
    try:
        since = float(since)
    except (ValueError, TypeError):
        since = None
```

然后传给 `get_messages_by_channel()`（需扩展该函数支持 `since` 参数）。

或者直接调用 `get_messages_since()`（已有该函数）。

**⑤ 新增 `handle_api_archive()`（~25 行）**

```python
async def handle_api_archive(request: web.Request) -> web.Response:
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
    
    # 解析 inbox 收件人
    for m in all_msgs:
        if m.get("channel", "").startswith("_inbox:"):
            owner_id = persistence.resolve_inbox_owner(m["channel"])
            m["to_name"] = auth.get_agent_name(owner_id) if owner_id else "?"
            m["to_agent"] = owner_id or ""
        # channel 标签
        ch = m.get("channel", "")
        if ch == "lobby":
            m["_channel_label"] = "大厅"
        elif ch == "_admin":
            m["_channel_label"] = "管理员"
        elif ch.startswith("_inbox:"):
            owner_id = persistence.resolve_inbox_owner(ch)
            name = auth.get_agent_name(owner_id) if owner_id else "?"
            m["_channel_label"] = f"收件箱（{name}）"
        else:
            m["_channel_label"] = ch
    
    return web.json_response({
        "workspace": ws_info["name"],
        "period": ws_info["archive_window"],
        "messages": all_msgs,
        "total": len(all_msgs),
    })
```

**⑥ `message_store.py` 新增 `get_messages_by_time_range()`（~15 行）**

```python
def get_messages_by_time_range(
    start_ts: float, end_ts: float, data_dir: Path
) -> list[dict]:
    db_path = str(data_dir / DEFAULT_DB_NAME)
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT msg_id, msg_type, from_agent, from_name, content, ts, channel "
        "FROM messages WHERE ts >= ? AND ts <= ? ORDER BY ts ASC",
        (start_ts, end_ts),
    ).fetchall()
    return [dict(r) for r in rows]
```

**⑦ 路由注册（~5 行）**

```python
app.router.add_get("/api/chat/inbox", handle_api_inbox)
app.router.add_get("/api/chat/archive", handle_api_archive)
```

#### 3.3 `server/handler.py` — 关闭工作室时触发归档

在 `!close_workspace` 的处理逻辑中，关闭工作室后增加归档检测：

```python
# 在 close_workspace 成功后：
# 检查是否所有 workspace 都已关闭
from . import workspace as ws_mod
active_ws = [w for w in ws_mod.get_all_workspaces() if w.state == ws_mod.WorkspaceState.ACTIVE]
if not active_ws:
    # 所有 workspace 已关闭 → 设置归档标记
    from . import web_viewer as wv
    wv.set_archive_state(ws_mod)  # 写入 last_archive_ts + 刚关闭的 workspace 信息
```

**或者更精确：** 在 `_cmd_close_workspace` 函数末尾添加调用。

#### 3.4 `server/templates.py` — 前端改动

**① Tab bar 新增第 5 个 Tab「📬 收件箱」（~5 行）**

```javascript
// 在 TAB_STATE 中新增
tab5: { id: 'tab5', channel: '__inbox__', label: '📬 收件箱', permanent: true, visible: true },
```

**② Tab 渲染顺序（renderTabBar 函数）**

```
顺序: [tab2 活跃 → tab1 大厅 → tab4 管理员 → tab5 收件箱 → tab3 历史查看器]
```

**③ inbox Tab 渲染逻辑（~20 行）**

```javascript
function selectTab(tabId) {
  // ...
  const tab = TAB_STATE[tabId];
  if (tab && tab.channel) {
    if (tabId === 'tab5') {
      loadInboxMessages();
    } else {
      loadMessages(tab.channel);
    }
  }
}
```

**④ `loadInboxMessages()` 函数（~15 行）**

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
    for (const m of msgs) {
      const el = createInboxMessageEl(m);
      list.appendChild(el);
    }
  } catch(e) {
    list.innerHTML = '<div class="empty">加载失败</div>';
  }
}
```

**⑤ `createInboxMessageEl()`（~10 行）**

```javascript
function createInboxMessageEl(m) {
  const div = document.createElement('div');
  div.className = 'msg bot';
  const sender = m.from_name || '';
  const receiver = m.to_name || '';
  const cls = colorMap[sender] || 'unknown';
  div.innerHTML = '<div class="meta"><span class="ts">' + formatTime(m.ts) + '</span>' +
    '<span class="sender s-' + cls + '">' + escapeHtml(sender) + '</span>' +
    '<span style="color:#8b949e;margin:0 4px;">→</span>' +
    '<span style="color:#8b949e;font-size:0.85rem;">' + escapeHtml(receiver) + '</span>' +
    '</div><div class="content">' + escapeHtml(m.content || '') + '</div>';
  return div;
}
```

**⑥ WS 推送处理（~5 行）**

```javascript
// 在 ws.onmessage 中：
if (data.type === 'chat_message') {
  const ch = data.channel || 'lobby';
  if (ch.startsWith('_inbox:')) {
    // inbox 消息 → 追加到 inbox 缓冲区
    appendInboxMessage(data.message || data);
    if (activeTabId !== 'tab5') {
      unreadCounts['__inbox__'] = (unreadCounts['__inbox__'] || 0) + 1;
      renderTabBar();
    }
  } else {
    appendMessage(ch, data.message || data);
  }
}
```

**⑦ 无活跃工作室时 since 过滤（~20 行）**

```javascript
// 从 /api/workspaces 返回数据中获取 archive 状态
// 假设 workspaces API 返回：{workspaces: [...], archive_state: {active: true/false, last_archive_ts: N}}

function getLoadUrl(channel) {
  let url = '/api/chat?channel=' + encodeURIComponent(channel) + '&limit=50&token=' + encodeURIComponent(TOKEN);
  if (TAB_STATE.archiveMode && TAB_STATE.lastArchiveTs) {
    url += '&since=' + TAB_STATE.lastArchiveTs;
  }
  return url;
}

// 或者在 selectTab 时判断
function selectTab(tabId) {
  // ...
  if (tabId === 'tab5') {
    loadInboxMessages(TAB_STATE.archiveMode ? TAB_STATE.lastArchiveTs : null);
  } else if (tab && tab.channel) {
    loadMessages(tab.channel, TAB_STATE.archiveMode ? TAB_STATE.lastArchiveTs : null);
  }
}
```

**⑧ 历史查看器归档全 channel 展示（~20 行）**

```javascript
async function loadArchiveMessages(wsId) {
  const list = document.getElementById('msgList');
  list.innerHTML = '<div class="empty">加载中...</div>';
  const resp = await fetch('/api/chat/archive?workspace_id=' + encodeURIComponent(wsId) + '&token=' + encodeURIComponent(TOKEN));
  if (!resp.ok) { list.innerHTML = '<div class="empty">加载失败</div>'; return; }
  const data = await resp.json();
  const msgs = data.messages || [];
  list.innerHTML = '';
  // 顶部显示统计
  const header = document.createElement('div');
  header.style.cssText = 'padding:8px 12px;margin-bottom:8px;border-radius:8px;background:#161b22;border:1px solid #30363d;font-size:0.8rem;color:#8b949e;';
  header.textContent = '📦 ' + data.workspace + ' · ' + msgs.length + ' 条消息 · ' + new Date(data.period.start * 1000).toLocaleString() + ' → ' + new Date(data.period.end * 1000).toLocaleString();
  list.appendChild(header);
  for (const m of msgs) {
    const el = createArchiveMessageEl(m);
    list.appendChild(el);
  }
}

function createArchiveMessageEl(m) {
  const div = document.createElement('div');
  div.className = 'msg bot';
  const sender = m.from_name || '';
  const label = m._channel_label || m.channel || '';
  const cls = colorMap[sender] || 'unknown';
  let inner = '<div class="meta"><span class="ts">' + formatTime(m.ts) + '</span>' +
    '<span class="sender s-' + cls + '">' + escapeHtml(sender) + '</span>';
  if (m.to_name) {
    inner += '<span style="color:#8b949e;margin:0 4px;">→</span>' +
      '<span style="color:#8b949e;font-size:0.85rem;">' + escapeHtml(m.to_name) + '</span>';
  }
  inner += '<span style="margin-left:auto;font-size:0.7rem;color:#8b949e;border:1px solid #30363d;border-radius:3px;padding:1px 4px;">' + escapeHtml(label) + '</span>';
  inner += '</div><div class="content">' + escapeHtml(m.content || '') + '</div>';
  div.innerHTML = inner;
  return div;
}
```

**⑨ workspaces API 扩展**

在 `handle_api_channels` 或 `handle_api_workspaces` 中返回归档状态信息：

```python
# 在 workspaces 列表返回时附加：
state = _load_archive_state()
return web.json_response({
    "workspaces": workspaces,
    "archive_state": {
        "active": len(active_ws) > 0,
        "last_archive_ts": state.get("last_archive_ts", 0),
    },
})
```

---

### Step 4：审查（Review — 主角：审查工程师，备用：测试工程师）

**审查重点：**

| # | 审查项 | 预期 |
|:-:|:-------|:-----|
| 1 | `handle_api_inbox` 查询性能 — LIKE '\_inbox:%' 是否命中索引？ | `channel` 字段已建索引（idx_messages_channel），但 LIKE 前缀通配不影响 |
| 2 | `since` 参数类型安全 — 字符串能正确转换为 float？ | 用 `float(since)` + try/except 保护 |
| 3 | inbox 消息解析接收人 — `resolve_inbox_owner` 兼容实际播发格式？ | 确认 `persistence.resolve_inbox_owner()` 输入参数为完整 channel 名 |
| 4 | 归档状态持久化 — 服务器重启后 `_archive_state.json` 重新加载？ | 每次读取时即时加载文件，非内存缓存（重启不影响） |
| 5 | WS 推送 inbox 消息时前端未读红点计数正确 | 仅在非 inbox Tab 时计数 |
| 6 | 前端 archiveMode 切换 — 从 archive → 正常模式时状态重置 | 创建 workspace 时清除 |
| 7 | 无 scope creep — 只改了上述指定文件 | git diff 确认 |

---

### Step 5：测试（QA — 主角：测试工程师，备用：审查工程师）

**验收标准测试（从需求文档 §4 复制）：**

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 新增 `/api/chat/inbox` 返回 inbox 聚合消息 | 含 `from_name` `to_name` `content` `ts`，按 ts 降序 | curl 验证 |
| ✅-2 | 无 token 访问返回 401 | `{"error": "unauthorized"}` | curl 无 token |
| ✅-3 | Web 端显示 📬 收件箱 Tab | Tab bar 可见第 5 个 Tab | 浏览器查看 |
| ✅-4 | 点击 inbox Tab 加载消息 | 显示各 bot inbox 混合消息，含发送人→接收人 | 浏览器操作 |
| ✅-5 | Inbox 消息格式正确 | `[时间] 发送人 → 接收人: 内容` | 浏览器验证 |
| ✅-6 | WS 推送 inbox 消息时显示未读红点 | inbox Tab 显示红色数字 | 两标签页测试 |
| ✅-7 | Inbox Tab 无输入框 | 页面底部无输入区域 | 浏览器验证 |
| ✅-8 | 关闭最后活跃工作室后各 Tab 干净 | 各 Tab 显示「暂无消息」 | 关闭工作室后刷新 Web |
| ✅-9 | 新增 `/api/chat/archive?workspace_id=X` | 返回该时间窗口内所有 channel 消息 | curl 验证 |
| ✅-10 | 历史查看器点击已归档 workspace | 显示全 channel 消息，每条带来源标签 | 浏览器操作 |
| ✅-11 | 创建新工作室后各 Tab 恢复正常 | Tab 开始显示新消息 | 创建工作室后刷新 |
| ✅-12 | `since` 参数按预期过滤 | `GET /api/chat?channel=lobby&since=T` 只返回 T 之后的消息 | curl 验证 |

**测试工具：** 使用 `curl` 测试 API endpoints + 浏览器查看 Web UI

---

### Step 6：合并部署 + 通知（Admin — 主角：项目管理，备用：架构师）

**操作顺序：**

```bash
# 1. 合并 dev → main
git checkout main
git merge dev
git push origin main

# 2. 远程服务器 pull + rebuild + 重启
# 在 VPS 上执行：
cd /opt/data/ws-bridge
git pull origin main
docker build -t ws-bridge:r76 .
docker stop ws-bridge && docker rm ws-bridge
docker run -d --name ws-bridge ... ws-bridge:r76

# 3. 验证部署
# curl http://localhost:{PORT}/api/chat/inbox?token={TOKEN}

# 4. 通知项目负责人
# 「R76 已部署，Web 端可见 📬 收件箱 Tab」
```

---

## 3. 验收清单

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | `/api/chat/inbox` 返回 inbox 聚合消息 | ⏳ |
| ✅-2 | 无 token 返回 401 | ⏳ |
| ✅-3 | 📬 收件箱 Tab 可见 | ⏳ |
| ✅-4 | 点击加载混合消息（发送人→接收人） | ⏳ |
| ✅-5 | 消息格式正确 | ⏳ |
| ✅-6 | WS 推送时未读红点 | ⏳ |
| ✅-7 | 无输入框 | ⏳ |
| ✅-8 | 关闭最后活跃工作室后各 Tab 干净 | ⏳ |
| ✅-9 | `/api/chat/archive` 返回全 channel 消息 | ⏳ |
| ✅-10 | 历史查看器显示全 channel 消息+来源标签 | ⏳ |
| ✅-11 | 新工作室创建后恢复正常 | ⏳ |
| ✅-12 | `since` 参数过滤有效 | ⏳ |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-08 | 初稿 — R76 WORK_PLAN 定稿（审核通过后） |
