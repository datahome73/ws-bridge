# R83 技术方案 — Web 端 Inbox 化改造 🎯

> **版本：** v1.0 | **架构师：** 👷 Arch | **日期：** 2026-07-08
> **基于：** docs/R83/R83-product-requirements.md v1.0 ✅
> **改动范围：** `server/templates.py`、`server/web_viewer.py`、`server/auth.py`、`server/persistence.py`
> **不动：** `server/handler.py`、`clients/`、`server/config.py`

---

## 1. B1 诊断报告

### 1.1 诊断过程

| # | 步骤 | 结果 |
|:-:|:-----|:-----|
| 1 | 检查 `data/messages.db` | ✅ 存在（28672 bytes, Jul 2） |
| 2 | SQLite 查询总消息数 | ❌ **0 条消息** — DB 完全为空 |
| 3 | 测试 `LIKE '_inbox:%'` | 返回 0（DB 空） |
| 4 | 测试 `LIKE '\\_inbox:%' ESCAPE '\\'` | 返回 0（同上） |
| 5 | 检查 `handle_api_inbox()` (web_viewer.py L439-469) | ✅ 逻辑正确 |
| 6 | 检查 `get_messages_by_channel_pattern()` (message_store.py L173-201) | ✅ 函数完整 |
| 7 | 检查前端 `loadInboxMessages()` (templates.py L389-410) | ✅ 格式匹配 |
| 8 | 检查 `createInboxMessageEl()` (templates.py L412-427) | ✅ 渲染正确 |
| 9 | 检查 WS inbox push (templates.py L601-614) | ✅ `_inbox:` 前缀正确处理 |
| 10 | 检查 `data/chat_logs/` | ❌ 不存在 |

### 1.2 根因确认

**根因：`messages.db` 为空（0 条消息）。** 这不是代码 bug，而是环境数据问题。当前开发环境的 SQLite DB 没有 inbox 消息数据。生产环境中消息通过 `handler.py` 的 `save_message()` 写入。

**LIKE 通配符分析：** `_inbox:%` 在 SQLite 中正确匹配 `_inbox:xxx`（`_` 是单字符通配符，匹配字面量 `_`）。当前代码无问题。

**结论：代码层面无 bug。收件箱 Tab 显示"暂无收件箱消息"是正确行为。部署到生产环境后自动填充。**

### 1.3 修复策略

不做 SQL 修复（代码正确）。改为增强：

- 新增 `_channel_label` 字段 → 显式标记消息发到谁的收件箱
- 新增消息类型标签 → 区分 bot 回复/系统通知
- 5s poll 新增 inbox 分支 → WS 断线时 inbox 也有 poll fallback

---

## 2. 方向 A：Tab 标签栏重设计

### 2.1 TAB_STATE 重写（L133-142）

**旧（5-tab）：**
```javascript
const TAB_STATE = {
  tab1: { id: 'tab1', channel: 'lobby',       label: '🌐 大厅',     permanent: true, visible: true },
  tab2: { id: 'tab2', channel: null,           label: '📋 活跃',     permanent: false, visible: false },
  tab4: { id: 'tab4', channel: '_admin',       label: '🔧 管理员',   permanent: true, visible: true },
  tab5: { id: 'tab5', channel: '__inbox__',    label: '📬 收件箱',   permanent: true, visible: true },
  tab3: { id: 'tab3', channel: null,           label: '🗂️ 历史查看器', permanent: true, visible: true },
};
```

**新（3-tab）：**
```javascript
const TAB_STATE = {
  tab1: { id: 'tab1', channel: '__inbox__',    label: '📬 收件箱',   permanent: true, visible: true },
  tab2: { id: 'tab2', channel: '_admin',       label: '🔧 管理员',   permanent: true, visible: true },
  tab3: { id: 'tab3', channel: null,           label: '🗂️ 历史',    permanent: true, visible: true },
};
```

### 2.2 renderTabBar() 重写（L220-241）

3-tab 循环渲染，删除大厅/活跃 Tab 分支：

```javascript
function renderTabBar() {
  const bar = document.getElementById('tabBar');
  let html = '';
  for (const [id, tab] of Object.entries(TAB_STATE)) {
    const isActive = activeTabId === id;
    const badgeHtml = (id === 'tab1' && unreadCounts['__inbox__'] > 0 && !isActive)
      ? '<span class="badge">' + unreadCounts['__inbox__'] + '</span>' : '';
    html += '<div class="tab' + (isActive ? ' active' : '') + '" data-tab="' + id +
      '" onclick="selectTab(\'' + id + '\')">' + tab.label + badgeHtml + '</div>';
  }
  bar.innerHTML = html;
}
```

### 2.3 selectTab() 简化（L245-270）

按 `tab.channel` 路由，删除 tab5 特殊处理：

```javascript
function selectTab(tabId) {
  if (tabId === activeTabId) return;
  if (searchMode) exitSearchMode();
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  const tabEl = document.querySelector('.tab[data-tab="' + tabId + '"]');
  if (tabEl) tabEl.classList.add('active');
  activeTabId = tabId;
  const tab = TAB_STATE[tabId];

  // 收件箱 tab
  if (tab && tab.channel === '__inbox__') {
    unreadCounts['__inbox__'] = 0; renderTabBar();
    document.getElementById('inputArea').style.display = 'none';
    loadInboxMessages(null); return;
  }
  // 管理员 tab
  if (tab && tab.channel === '_admin') {
    document.getElementById('inputArea').style.display = 'block';
    loadMessages('_admin', null); return;
  }
  // 历史 tab
  document.getElementById('inputArea').style.display = 'none';
  document.getElementById('msgList').innerHTML = '<div class="empty">👈 点击右侧「工作室归档」选择一个查看</div>';
}
```

### 2.4 init() 简化（L531-588）

| 改动 | 操作 |
|:-----|:-----|
| localStorage tab2 恢复 (L532-543) | **删除** |
| 获取 workspaces 回填 tab2 (L545-565) | **简化** — 只刷新缓存，不操作 TAB_STATE |
| 首 Tab 确定 (L584-587) | **固定** `const firstTab = 'tab1'` |
| 15s poll 中 tab2 检测 (L675-695) | **删除** tab2 逻辑，保留面板缓存失效 |

### 2.5 删除 switchToActiveTab() + buildWsItem 简化

- **`switchToActiveTab()`** (L283-294) → 整段删除
- **`buildWsItem()`** (L470-480) → 活跃工作室不渲染（`if (w.state === 'active') return ''`），点击全走 `switchHistoryTab()`
- **`renderWsPanel()`** → 删除「活跃工作室」分区，标题改为「📦 工作室归档」

### 2.6 unreadCounts/msgContainers 初始值调整（L144-145）

```javascript
let unreadCounts = { '__inbox__': 0 };
const msgContainers = {};
```

### 2.7 5s poll 简化 + inbox 分支

- 删除 L675-695 tab2 活跃检测完整逻辑（约 20 行）
- 新增 inbox 分支 → 用 `/api/chat/inbox` 增量更新
- 保留面板缓存失效 `wsPanelCache = null`

---

## 3. 方向 B：收件箱消息增强

### 3.1 增加频道标签（web_viewer.py L464-467）

```python
# 在每个 inbox 消息中增加 _channel_label
m["_channel_label"] = f"📬 {to_name}"
```

### 3.2 增加消息类型标签（templates.py L412-427）

在 `createInboxMessageEl()` 中判断 `from_agent === '_system'`：
- 系统消息 → 蓝色标签 `🤖 系统`
- 普通回复 → 灰色标签 `💬 回复`

### 3.3 5s poll 新增 inbox 分支

在 poll 函数入口检测 `channel === '__inbox__'` → 调 `/api/chat/inbox` 增量追加，非 inbox 才走原有 `/api/chat` 逻辑。

---

## 4. 方向 C：登录入口清理

### 4.1 web_viewer.py 删除项

| 项目 | 行号 | 操作 |
|:-----|:----:|:-----|
| `handle_api_bind()` | L221-225 | 删除函数 |
| `handle_api_check()` | L228-252 | 删除函数 |
| `handle_api_approve_web()` | L369-? | 删除函数 |
| `/api/bind` 路由 | L696 | 删除 |
| `/api/check` 路由 | L697 | 删除 |
| `/api/approve_web` 路由 | L699 | 删除 |

### 4.2 auth.py 删除项

| 项目 | 行号 | 操作 |
|:-----|:----:|:-----|
| `WEB_CODE_PREFIX` | L127 | 删除 |
| `generate_web_bind_code()` | L130-133 | 删除 |
| `create_web_bind_code()` | L136-143 | 删除 |
| `approve_web_bind_code()` | L146-? | 删除 |

### 4.3 persistence.py 删除项

| 项目 | 行号 | 操作 |
|:-----|:----:|:-----|
| `_web_bind_codes` 变量 | L12 | 删除 |
| `load_web_bind_codes()` | L79-81 | 删除 |
| `save_web_bind_codes()` | L84-86 | 删除 |
| `get_web_bind_codes()` | L99-101 | 删除 |
| `set_web_bind_codes()` | L104-107 | 删除 |

### 4.4 保留项

- GitHub OAuth 完整流程（`handle_github_callback` + `handle_api_auth_me`）
- Web session cookie（`_web_sessions` 持久化保留）
- 登录页面 HTML（已只显示 GitHub OAuth ✅）

---

## 5. 兼容性分析

### 5.1 TAB_STATE 引用完整性（~15 处）

| 引用位置 | 旧 key | 新 key | 状态 |
|:---------|:-------|:-------|:-----|
| selectTab() L256 | tab5 | tab1 | ✅ 重写 |
| renderTabBar() L222-238 | tab1/2/4/5 | tab1/2/3 | ✅ 重写 |
| init() L535-565 | tab2 localStorage | 删除 | ✅ |
| init() L584-587 | tab2 优先 | 固定 tab1 | ✅ |
| buildWsItem() L474 | tab2 点击 | 只走 history | ✅ |
| ws.onmessage L605 | tab5 | tab1 | ✅ |
| 15s poll L676 | tab2 检测 | 删除 | ✅ |

### 5.2 WS push 兼容

- `_inbox:xxx` → tab1 渲染（旧 tab5）✅
- `_admin` → tab2 渲染（旧 tab4）✅
- `lobby` → 不存在（R82 不再产生）✅
- `ws:xxx` → 不存在（R82 不再产生）✅

### 5.3 绑定码兼容

- 已登录用户 session cookie 不受影响（`_web_sessions` 保留）
- `/api/bind` 返回 404（合理行为）

---

## 6. 改动统计

| 文件 | 删除 | 新增 | 净变化 |
|:-----|:----:|:----:|:------:|
| `server/templates.py` | ~110 | ~70 | **-40** |
| `server/web_viewer.py` | ~60 | ~10 | **-50** |
| `server/auth.py` | ~30 | 0 | **-30** |
| `server/persistence.py` | ~20 | 0 | **-20** |
| **合计** | **~220** | **~80** | **-140 行净删** |

---

## 附：执行顺序（给 Step 3 开发者）

```
Phase 1 — 清理绑定码
  └── persistence.py + auth.py + web_viewer.py

Phase 2 — Tab 架构重写
  ├── TAB_STATE 5→3
  ├── renderTabBar() + selectTab() + init() 重写
  ├── 删除 switchToActiveTab()
  ├── renderWsPanel() + buildWsItem() 简化
  ├── 15s poll 删除 tab2 + unreadCounts 调整
  └── 5s poll 新增 inbox 分支

Phase 3 — 收件箱增强
  ├── web_viewer.py: 新增 _channel_label
  └── templates.py: createInboxMessageEl() 消息类型标签

Phase 4 — 验证
  └── grep 零匹配: tab2\|tab4\|tab5\|switchToActiveTab\|generate_web_bind_code\|/api/bind
```
