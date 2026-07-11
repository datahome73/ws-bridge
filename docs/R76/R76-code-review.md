# R76 代码审查报告 — Inbox Tab + 时间切片归档 📬

> **审查人：** 🔍 审查工程师
> **审查对象：** `3db77b0` feat(R76): Inbox Tab + 时间切片归档 — 后端+前端全量实现
> **审查日期：** 2026-07-08
> **改动统计：** 5 文件, +411/-15 行
> **技术方案：** `docs/R76/R76-tech-plan.md` v1.0

---

## 0. 审查结论

> 🟡 **条件通过 — 1 项 🔴 + 1 项 🟡 + 1 项 💡 — 建议编码修复后进入 QA**
>
> | 级别 | 数量 | 说明 |
> |:----:|:----:|:------|
> | 🔴 阻塞 | 1 | B-1: `handle_api_inbox` 的 `since=float(since)` 未保护 |
> | 🟡 W 级 | 1 | W-1: handler.py 中 `_time.time()` 应为 `time.time()` |
> | 💡 建议 | 1 | S-1: `_save_archive_state()` 建议加本层异常处理 |
>
> **建议：** 修复 B-1 和 W-1（共 3 行修改）后进入 QA，不展开退回。

---

## 1. 需求→方案→代码追溯矩阵

| # | 验收项 | 方案位置 | 实现位置 | 状态 |
|:-:|:-------|:---------|:---------|:----:|
| A1 | Inbox 聚合 API | §1.1-A1 | `web_viewer.py:handle_api_inbox()` | ✅ |
| A1 | LIKE `_inbox:%` 查询 | §1.3 | `message_store.py:get_messages_by_channel_pattern()` | ✅ |
| A1 | `idx_messages_channel` 索引命中 | §1.3 | SQL `WHERE channel LIKE ?` 前缀模式 → 范围扫描 | ✅ |
| A2 | Tab5 收件箱 Tab | §2.1 | `templates.py:TAB_STATE.tab5` | ✅ |
| A2 | Tab 顺序 tab2→tab1→tab4→tab5→tab3 | §2.2 | `renderTabBar()` 渲染顺序 | ✅ |
| A2 | 收件箱 Tab 无输入框 | §2.3 | `selectTab('tab5')` → `inputArea.style.display = 'none'` | ✅ |
| A3 | 消息渲染「发送人 → 接收人」 | §3.2 | `createInboxMessageEl()` | ✅ |
| A4 | WS 推送 inbox 消息 → 未读红点 | §4.1-4.2 | `ws.onmessage` + `unreadCounts['__inbox__']` | ✅ |
| B1 | 归档状态 JSON 文件存储 | §1.1-1.3 | `web_viewer.py:_load_archive_state/_save_archive_state` | ✅ |
| B2 | 关闭工作室触发归档 | §2.1 | `handler.py:_cmd_close_workspace()` 末尾 | ⚠️ W-1 |
| B3 | `since` 参数 | §3.1 | `handle_api_chat()` + `handle_api_inbox()` | 🔴 B-1 |
| B3 | `handle_api_archive()` | §3.2 | `web_viewer.py:handle_api_archive()` | ✅ |
| B3 | `get_messages_by_time_range()` | §3.3 | `message_store.py:get_messages_by_time_range()` | ✅ |
| B3 | `handle_api_channels()` 附加 archive_state | §3.5 | `web_viewer.py:handle_api_channels()` | ✅ |
| B4 | 前端 archiveMode + lastArchiveTs | §4.1-4.5 | `templates.py:archiveMode/lastArchiveTs` + `selectTab()` | ✅ |
| B4 | workspace_created → archiveMode=false | §4.5 | `ws.onmessage` handler | ✅ |
| §3 | `get_agent_name()` 辅助函数 | §3.1-3.3 | `auth.py:get_agent_name()` | ✅ |
| — | Scope 合规 | §4.2 | 仅改 5 文件（auth/handler/message_store/templates/web_viewer） | ✅ |

---

## 2. 改动统计

| 文件 | 行数 | 改动类型 |
|:-----|:----:|:---------|
| `server/auth.py` | +23 | 新增 `get_agent_name()` — 3 级 fallback |
| `server/handler.py` | +17 | `_cmd_close_workspace()` 归档触发 |
| `server/message_store.py` | +59 | `get_messages_by_channel_pattern()` + `get_messages_by_time_range()` |
| `server/templates.py` | +148/-15 | Tab5 + 前端状态机 + WS 处理 + 归档加载 |
| `server/web_viewer.py` | +179/-15 | `handle_api_inbox/archive` + 归档状态 + since + 路由 |
| **合计** | **+411/-15** | |

---

## 3. 逐项审查

### ✅ 3.1 `handle_api_inbox` — LIKE `_inbox:%` 索引命中

```python
# message_store.py:get_messages_by_channel_pattern()
query = "SELECT ... FROM messages WHERE channel LIKE ?"
# pattern = "_inbox:%"  — 固定前缀，SQLite 可走 idx_messages_channel 范围扫描
```

**验证：**
- channel 列已定义索引 `idx_messages_channel`
- `LIKE '_inbox:%'` 以固定前缀开头（无前导通配符 `%`），SQLite 可进行 B-tree 前缀扫描
- 性能与精确匹配接近 ✅

### 🔴 3.2 `since` 参数类型安全

**`handle_api_chat()` — 正确：**
```python
since = request.query.get("since", None)
if since:
    try:
        since = float(since)
    except (ValueError, TypeError):
        since = None          # ← 安全降级
```

**🔴 B-1: `handle_api_inbox()` — 未保护：**
```python
since = request.query.get("since", None)
since = float(since) if since else None
# 若 since="abc" → ValueError: could not convert string to float: 'abc'
# 此异常不在 try 块内，会穿透到 aiohttp 返回 500
```

**风险：** 客户端传 `since=abc` 或 `since=%20` 等垃圾输入时，返回 500 页面而非安全降级。

**修复：** 参照 `handle_api_chat()` 的写法，加 try/except：
```python
since = request.query.get("since", None)
if since:
    try:
        since = float(since)
    except (ValueError, TypeError):
        since = None
```

### ✅ 3.3 `get_agent_name()` — `_r72_users` fallback 路径

```python
# auth.py
def get_agent_name(agent_id, default=None):
    users = get_users()
    name = users.get(agent_id, {}).get("name")    # ① 传统用户
    if name:
        return name
    try:
        from . import handler as _handler
        r72 = getattr(_handler, "_r72_users", {})
        return r72.get(agent_id, {}).get("name", default or agent_id[:12])  # ② R72 用户
    except ImportError:
        return default or agent_id[:12]            # ③ 截断 fallback
```

**验证：**
- 三级 fallback 完全匹配技术方案 ✅
- 局部 `from . import handler` 避免循环导入 ✅
- `getattr` 加默认值避免 AttributeError ✅
- `ImportError` 捕获处理 ✅

**调用点：**
- `handle_api_inbox()` 解析收件人 → ✅
- `handle_api_archive()` 归档消息收件人解析 → ✅

### ✅ 3.4 归档状态持久化 — JSON 文件读写

**`_load_archive_state()` — 异常处理完善：**
```python
if not path.exists():
    return {"last_archive_ts": 0, "archived_workspaces": []}   # 文件缺失
try:
    return json.loads(path.read_text(encoding="utf-8"))
except (json.JSONDecodeError, OSError):
    return {"last_archive_ts": 0, "archived_workspaces": []}   # 损坏/IO 错误
```

**`_save_archive_state()` — 💡 S-1: 建议加本层保护：**
```python
def _save_archive_state(state):
    path = config.DATA_DIR / _ARCHIVE_STATE_FILE
    path.write_text(json.dumps(state, ...))   # ← 无异常处理
```

当前依赖外部调用者的 `try/except`（`_cmd_close_workspace()` 包裹了异常），但从函数设计角度，IO 写入函数自身应有防护。建议：
```python
def _save_archive_state(state):
    try:
        path = config.DATA_DIR / _ARCHIVE_STATE_FILE
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # 写入失败由更上层决定是否告警
```

**`handle_api_archive()` 中 `_load_archive_state()` 的调用无异常保护** — 但损坏的文件会返回空状态导致 404，属可接受降级。

### ✅ 3.5 WS 推送 inbox → 前端未读红点

**WS 消息处理：**
```javascript
if (ch.startsWith('_inbox:')) {
    _inboxCache.push(msg);
    if (activeTabId === 'tab5') {
        list.insertBefore(createInboxMessageEl(msg), list.firstChild);  // 当前 Tab → 直接渲染
    } else {
        unreadCounts['__inbox__'] = (unreadCounts['__inbox__'] || 0) + 1;  // 其他 Tab → 红点 +1
        renderTabBar();
    }
}
```

**Tab 切换时清除红点：**
```javascript
if (tabId === 'tab5') {
    unreadCounts['__inbox__'] = 0;
    renderTabBar();
    ...
}
```

**验证：**
- 类型区分：`ch.startsWith('_inbox:')` 正确匹配所有 inbox 通道 ✅
- 红点计数：仅不在 inbox Tab 时递增，切换时清零 ✅
- Tab Bar 渲染：`<span class="badge">N</span>` 条件渲染 ✅
- 消息缓存：`_inboxCache` 累积 WS 推送但不自动显示（符合「加载+增量」设计）✅

### ✅ 3.6 `archiveMode` 状态切换

**初始化：**
```javascript
archiveMode = !chData.archive_state.active;   // 无活跃工作室 → 归档模式
lastArchiveTs = chData.archive_state.last_archive_ts || 0;
```

**各 Tab 加载：**
- tab5: `loadInboxMessages(archiveMode ? lastArchiveTs : null);` — ✅ since 过滤
- tab1/tab2/tab4: `loadMessages(tab.channel, archiveMode ? lastArchiveTs : null);` — ✅ since 过滤
- tab3 (历史): `loadArchiveMessages(wsId)` — 不传 since（由 workspace_id 从归档窗口查询）— ✅

**状态转换：**
| 事件 | archiveMode 变化 | 正确性 |
|:-----|:----------------|:-------|
| 页面初始化（无活跃工作室） | true (archiveMode) | ✅ |
| 页面初始化（有活跃工作室） | false | ✅ |
| workspace_created WS 事件 | false | ✅ |
| close_workspace（最后一个关闭） | 不变（需刷新页面重新 init） | ✅ 页面刷新后重查 channels API |

### 🟡 3.7 Scope 合规

```
Changed files: 5  —  auth.py, handler.py, message_store.py, templates.py, web_viewer.py
```

完全匹配技术方案 §4.1 文件清单，零 scope creep ✅。

### 🟡 3.8 `!close_workspace` 归档触发点

**位置：** `handler.py` 第 527 行后，`_cmd_close_workspace()` 末尾

**逻辑：** 关闭后检测是否无活跃 workspace → 调用 `web_viewer.set_archive_state()`

**🟡 W-1: `_time.time()` → 应为 `time.time()`**
```python
# handler.py:537 — BUG
start_ts = ws.created_at if isinstance(ws.created_at, (int, float)) else _time.time()
                                                # ^^^^^^ NameError: name '_time' is not defined
# handler.py 使用 `import time`（非 `import time as _time`）
```

**分析：**
- `workspace.created_at` 的类型为 `float`（workspace.py:188 `created_at: float = 0.0`），始终为 float
- 因此 `isinstance(ws.created_at, (int, float))` 恒为 True，`_time.time()` 分支永远不会执行
- **运行时不会触发**（死代码路径），但代码是错误的

**修复：** 无需使用 `_time.time()` 分支。`ws.created_at` 始终为 float，直接使用即可：
```python
start_ts = ws.created_at  # 恒为 float
```

或改为 `time.time()`：
```python
start_ts = ws.created_at if isinstance(ws.created_at, (int, float)) else time.time()
```

---

## 4. 代码质量审查

### 4.1 架构与设计

| 检查项 | 结论 |
|:-------|:-----|
| 函数单一职责 | ✅ 每个新增函数职责明确 |
| 模块间依赖清晰 | ✅ auth.get_agent_name → handler._r72_users（局部导入避循环） |
| API 设计 | ✅ 符合现有 /api/chat/ 命名风格 |
| 前端状态管理 | ✅ archiveMode + lastArchiveTs 双变量，selectTab 时传递 |
| WS 推送分流 | ✅ inbox vs 非 inbox 在 ws.onmessage 层分流，不走 appendMessage |

### 4.2 边界情况分析

| 场景 | 预期 | 实现 | 状态 |
|:-----|:-----|:-----|:----:|
| 无 inbox 消息 | 显示「暂无收件箱消息」 | ✅ `loadInboxMessages` → empty | ✅ |
| inbox 消息量 > 50 | 分页（暂未实现，limit=50） | ⚠️ 无分页，但符合 doc 设计 | ✅ |
| 恶意 `since=abc` | 安全降级，不报 500 | ❌ **B-1** | 🔴 |
| `_archive_state.json` 损坏 | 返回空状态 | ✅ try/except | ✅ |
| `_archive_state.json` 不存在 | 返回空状态 | ✅ path.exists() 检查 | ✅ |
| 同时关多个 workspace | 最后关闭的 ws 触发归档 | ✅ `if not active_ws` | ✅ |
| `ws.created_at` 为 0.0 | 归档窗口 start=0，包含全部消息 | ✅ `isinstance(..., (int, float))` 通过 | ✅ |
| WS 推送 inbox 但前端刚刷新 | 从 API 拉取全量 | ✅ `loadInboxMessages(null)` 拉全部 | ✅ |
| `_inboxCache` 不被主动渲染 | 切换 tab 时重新 API 拉取 | ✅ 每次 switch to tab5 都调用 loadInboxMessages | ✅ |

### 4.3 潜在改进建议

| # | 建议 | 位置 | 非阻塞 |
|:-:|:-----|:-----|:------:|
| S-1 | `_save_archive_state()` 加 try/except OSError | web_viewer.py | 💡 |
| S-2 | `loadInboxMessages` 可复用 `_inboxCache` 减少网络请求（优化项） | templates.py | 💡 |

---

## 5. 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:----:|
| token 验证 | ✅ 所有新 API 端点均有 `validate_token()` |
| XSS 防护 | ✅ 使用 `escapeHtml()` 处理用户输入 |
| 硬编码敏感信息 | ✅ 无 |
| 调试日志/print 残留 | ✅ 无 |
| TODO/FIXME 残留 | ✅ 无 |
| 旧的 R 标签残留 | ✅ 无（R34/R35/R38 注释为预存在的合法引用） |

---

## 6. 问题清单

| 级别 | 编号 | 描述 | 位置 | 修复方式 |
|:----:|:----:|:-----|:-----|:---------|
| 🔴 | B-1 | `handle_api_inbox()` 的 `since=float(since)` 未受 try/except 保护，传非法字符串返回 500 | `web_viewer.py` L446-447 | 参照 `handle_api_chat()` 加 try/except |
| 🟡 | W-1 | handler.py 中 `_time.time()` → 应为 `time.time()`（但 type hint 保证 `ws.created_at` 为 float，死路径不会执行） | `handler.py` L537 | 改 `_time.time()` → `time.time()`，或直接用 `ws.created_at` |
| 💡 | S-1 | `_save_archive_state()` 无异常处理，IO 错误穿透至调用方 | `web_viewer.py` | 加 try/except OSError |

---

## 7. 总结

### 🟡 待修复项（3 行修改）

```diff
--- a/server/web_viewer.py
+++ b/server/web_viewer.py
-    since = float(since) if since else None
+    since = None
+    if since:
+        try:
+            since = float(since)
+        except (ValueError, TypeError):
+            since = None

--- a/server/handler.py
-        start_ts = ws.created_at if isinstance(ws.created_at, (int, float)) else _time.time()
+        start_ts = ws.created_at if isinstance(ws.created_at, (int, float)) else time.time()
```

### ✅ 通过项

- ✅ Inbox 聚合 API — LIKE `_inbox:%` 命中索引
- ✅ `since` 参数类型安全（`handle_api_chat` 正确；`handle_api_inbox` 需修复 B-1）
- ✅ `get_agent_name()` 三级 fallback 完整
- ✅ 归档状态持久化 — JSON 文件读写，存活重启，异常降级
- ✅ WS 推送 inbox → 前端未读红点计数 + Tab 切换清零
- ✅ `archiveMode` 状态切换 — 初始化/WS 事件/Tab 加载
- ✅ Scope 合规 — 仅改指定 5 文件
- ✅ `!close_workspace` 归档触发点 — 位置正确，无活跃 workspace 时触发

---

> **总体：🟡 条件通过 — 修复 B-1 + W-1（3 行）后进入 Step 5 QA**
>
> 审查完毕：2026-07-08 🔍 审查工程师
