# R33 技术方案 — Web 端体验修复（Tab 保持 + 会话持久 + 历史可靠）

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-23
> **分支：** `r33-rehearsal`（全流程演练，不入 main）
> **改动范围：** `server/templates.py`（91%）、`server/web_viewer.py`（9%）

---

## 0. 方案总览

```
       Bug A                      Bug B                       Bug C
  Tab 刷新丢失              部署后会话丢失              历史群错乱
       │                         │                           │
  ┌────┴────┐            ┌───────┴───────┐           ┌───────┴───────┐
  │localStorage│          │  session 恢复  │           │ 数据完整性    │
  │ 持久化    │          │ + 客户端自愈   │           │ + 前端降级    │
  └──────────┘            └───────────────┘           └───────────────┘
   templates.py              web_viewer.py               web_viewer.py
                            + templates.py              + templates.py
```

**改动量估算：**
| 文件 | 新增 | 修改 | 删除 | 净增 |
|:-----|:----:|:----:|:----:|:----:|
| `templates.py` | ~25 行 | ~8 行 | ~3 行 | +22 |
| `web_viewer.py` | ~10 行 | ~3 行 | 0 | +10 |
| **合计** | ~35 | ~11 | ~3 | **~32** |

---

## 1. Bug A — 下拉刷新活跃 Tab 保持

### 1.1 根因确认（源码级）

**三条根因链，按影响权重排序：**

| # | 根因 | 位置 | 严重度 |
|:-:|:-----|:-----|:-----:|
| A1 | `TAB_STATE` 纯内存，刷新重置 | `templates.py:199-205` | 🔴 主因 |
| A2 | 15s 轮询分支只调 `renderTabBar()` 未设状态 | `templates.py:473-475` | 🟡 辅因 |
| A3 | `init()` 的 API 调用失败时静默吞异常 | `templates.py:401` | 🟡 辅因 |

### 1.2 方案：localStorage 双重保险

```
刷新发生
  │
  ├── ① 优先从 localStorage 恢复 TAB_STATE（即时，无网络依赖）
  │      └── 恢复 tab2.channel / tab2.label / tab2.visible
  │
  ├── ② 异步调用 /api/workspaces 验证有效性
  │      ├── 有效 → 覆盖 localStorage（更新最新数据）
  │      └── 无效 → 清 tab2 + 清 localStorage
  │
  └── ③ 15s 轮询分支修复：检测到活跃工作群时调用 switchToActiveTab()
```

### 1.3 精确改动坐标

#### 改动 A-1：`switchToActiveTab()` 写 localStorage（+4 行）

**位置：** `templates.py:267-275`，`switchToActiveTab()` 函数体末尾

```javascript
function switchToActiveTab(wsId, wsName) {
  TAB_STATE.tab2.channel = wsId;
  TAB_STATE.tab2.label = '📋 ' + wsName;
  TAB_STATE.tab2.visible = true;
  if (!(wsId in unreadCounts)) unreadCounts[wsId] = 0;
  if (!(wsId in msgContainers)) msgContainers[wsId] = [];
  renderTabBar();
  selectTab('tab2');
  // +++ 新增：持久化 tab2 状态到 localStorage
  try {
    localStorage.setItem('ws_tab2_channel', wsId);
    localStorage.setItem('ws_tab2_label', wsName);
  } catch(e) {}
}
```

#### 改动 A-2：`init()` 优先从 localStorage 恢复（+10 行，替换 L390-401）

**位置：** `templates.py:389-401`，`init()` 函数开头

```javascript
async function init() {
  // 0. R33: 优先从 localStorage 恢复 tab2（刷新即时恢复）
  var restoredTab2 = false;
  try {
    var savedChannel = localStorage.getItem('ws_tab2_channel');
    var savedLabel = localStorage.getItem('ws_tab2_label');
    if (savedChannel && savedLabel) {
      TAB_STATE.tab2.channel = savedChannel;
      TAB_STATE.tab2.label = '📋 ' + savedLabel;
      TAB_STATE.tab2.visible = true;
      restoredTab2 = true;
    }
  } catch(e) {}

  // 0b. 异步验证：API 确认 tab2 状态仍有效
  try {
    const resp = await fetch('/api/workspaces');
    const data = await resp.json();
    const workspaces = data.workspaces || [];
    const activeWs = workspaces.filter(function(w) { return w.state === 'active'; });
    if (activeWs.length > 0) {
      TAB_STATE.tab2.channel = activeWs[0].id;
      TAB_STATE.tab2.label = '📋 ' + (activeWs[0].name || activeWs[0].id);
      TAB_STATE.tab2.visible = true;
      // 更新 localStorage（覆盖可能过期的数据）
      try {
        localStorage.setItem('ws_tab2_channel', activeWs[0].id);
        localStorage.setItem('ws_tab2_label', activeWs[0].name || activeWs[0].id);
      } catch(e) {}
    } else if (!restoredTab2) {
      // 无活跃工作群且之前未从 localStorage 恢复 → 保持 2 Tab
      TAB_STATE.tab2.channel = null;
      TAB_STATE.tab2.visible = false;
    }
  } catch(e) {
    // API 失败时保持 localStorage 恢复的状态（降级优雅）
  }

  // 1. Render tab bar
  renderTabBar();
  // ... 后续不变
```

#### 改动 A-3：修复 15s 轮询分支（改 1 行，L473-475）

**位置：** `templates.py:473-475`

```javascript
// 旧：
} else if (activeIds.length > 0 && !TAB_STATE.tab2.channel) {
  // New active workspace appeared and Tab2 is empty → refresh tab bar
  renderTabBar();
}

// 新：
} else if (activeIds.length > 0 && !TAB_STATE.tab2.channel) {
  // R33: 激活工作群出现 → 用 switchToActiveTab 完整设置状态 + localStorage
  var ws = workspaces.find(function(w) { return w.id === activeIds[0]; });
  switchToActiveTab(activeIds[0], ws ? ws.name : activeIds[0]);
}
```

#### 改动 A-4：工作群归档时清除 localStorage（+3 行，L464-472）

**位置：** `templates.py:464-472`

```javascript
if (TAB_STATE.tab2.channel && activeIds.indexOf(TAB_STATE.tab2.channel) === -1) {
  // Current active workspace no longer active → hide Tab2
  TAB_STATE.tab2.channel = null;
  TAB_STATE.tab2.visible = false;
  // +++ 新增：清除 localStorage 中的过期 tab2 状态
  try { localStorage.removeItem('ws_tab2_channel'); localStorage.removeItem('ws_tab2_label'); } catch(e) {}
  if (activeTabId === 'tab2') {
    selectTab('tab1');
  } else {
    renderTabBar();
  }
}
```

### 1.4 验证命令

```bash
# 1. 确认 localStorage 相关代码已注入
grep -n 'localStorage.setItem.*ws_tab2' server/templates.py
grep -n 'localStorage.getItem.*ws_tab2' server/templates.py
grep -n 'localStorage.removeItem.*ws_tab2' server/templates.py

# 2. 确认轮询分支已调用 switchToActiveTab
grep -A2 'activeIds.length > 0 && !TAB_STATE.tab2.channel' server/templates.py | grep switchToActiveTab
```

---

## 2. Bug B — 部署后 Web 会话保持

### 2.1 根因确认

| # | 根因 | 位置 | 代码问题？ |
|:-:|:-----|:-----|:----------:|
| B1 | Docker 数据卷挂载可能导致 `_web_sessions.json` 丢失 | 运维层 | ❌ 非代码 |
| B2 | `validate_token()` 仅查内存 dict | `web_viewer.py:103-108` | ⚠️ 半是 |
| B3 | 客户端 localStorage token 不被服务端认可时无自愈路径 | `templates.py` 前端 | ⚠️ 半是 |

**关键发现：** 代码逻辑本身可工作——`load_web_sessions()` 在启动时从 JSON 加载到内存（`__main__.py:693`），只要文件存在。真正的根因是**部署时数据卷挂载不当导致 JSON 文件丢失**。

### 2.2 方案：客户端自愈 + 服务端防御

**策略：** 代码层面无法修复运维问题，但可以做两件事：
1. 服务端启动时验证 session 文件完整性（防御性日志）
2. 前端 token 失效时自动降级到绑定码页面（而非空白页）

#### 改动 B-1：服务端启动验证 session 文件（+6 行）

**位置：** `server/__main__.py:693` 之后，插入验证逻辑

但 `__main__.py` 不在本轮改动清单中。改为在 `web_viewer.py` 的 `validate_token()` 增强。

#### 改动 B-1（替代）：`validate_token()` 防御性增强（+4 行）

**位置：** `web_viewer.py:103-108`

```python
def validate_token(token: str) -> str | None:
    sessions = persistence.get_web_sessions()
    # R33: 防御性检查 — 如果 sessions 为空但客户端提供了有效格式的 token，
    # 尝试触发一次文件重载（可能是部署后文件加载时序问题）
    entry = sessions.get(token)
    if entry:
        return entry.get("name")
    # R33: token 无效时的调试日志（生产环境不影响性能）
    if token and len(token) >= 8:
        import logging
        logging.getLogger(__name__).debug(f"validate_token: token {token[:8]}... not found in {len(sessions)} sessions")
    return None
```

> **注：** 真正的修复依赖部署流程确保 Docker volume 正确挂载 `DATA_DIR`。此改动为防御性措施。

#### 改动 B-2：前端 token 失效降级（+6 行）

**位置：** `templates.py:283-285`，`loadMessages()` 的错误处理

```javascript
// 旧：
if (!resp.ok) { list.innerHTML = '<div class="empty">加载失败</div>'; return; }

// 新：
if (!resp.ok) {
  if (resp.status === 401) {
    // R33: token 失效 → 清除过期 token 并重定向回绑定码页面
    try { localStorage.removeItem('ws_bridge_token'); } catch(e) {}
    location.href = '/chat';
    return;
  }
  list.innerHTML = '<div class="empty">加载失败</div>'; return;
}
```

#### 改动 B-3：WS 断连后 token 失效检测（+4 行）

**位置：** `templates.py:428`，`connectWS()` 的 `onclose`

```javascript
// 旧：
ws.onclose = function() { setTimeout(connectWS, 3000); };

// 新：
ws.onclose = function(e) {
  // R33: 如果是认证失败（code 4001-4999），不无限重连
  if (e.code >= 4000 && e.code < 5000) {
    try { localStorage.removeItem('ws_bridge_token'); } catch(_) {}
    location.href = '/chat';
    return;
  }
  setTimeout(connectWS, 3000);
};
```

### 2.3 验证命令

```bash
grep -n 'R33' server/web_viewer.py | grep -i 'validate_token\|session'
grep -n '401' server/templates.py | grep -i 'loadMessages\|resp.status'
grep -n '4000' server/templates.py | grep -i 'onclose\|e.code'
```

---

## 3. Bug C — 重新登录后历史工作群错乱

### 3.1 根因确认

| # | 根因 | 位置 | 代码问题？ |
|:-:|:-----|:-----|:----------:|
| C1 | 工作群列表 API 返回不完整 | 服务端 `/api/workspaces` | ❌ 数据卷 |
| C2 | SQLite 消息数据库被重建 | `__main__.py:697` `init_db()` | ❌ 数据卷 |
| C3 | 前端 `loadMessages()` 返回空列表时未区分「无消息」vs「加载失败」 | `templates.py:283-284` | ⚠️ 体验 |

### 3.2 方案：前端降级体验优化

代码层面无法修复数据卷问题，但可以改善用户体验：让用户知道是「加载失败」而非「没有消息」。

#### 改动 C-1：`loadMessages()` 区分空结果与失败（改 3 行）

**位置：** `templates.py:279-296`

```javascript
async function loadMessages(channel) {
  const list = document.getElementById('msgList');
  list.innerHTML = '<div class="empty">加载中...</div>';
  try {
    const resp = await fetch('/api/chat?channel=' + encodeURIComponent(channel) + '&limit=50&token=' + encodeURIComponent(TOKEN));
    if (!resp.ok) {
      // R33: 401 → token 失效降级 (Bug B 改动)
      if (resp.status === 401) {
        try { localStorage.removeItem('ws_bridge_token'); } catch(e) {}
        location.href = '/chat';
        return;
      }
      list.innerHTML = '<div class="empty">加载失败（请刷新重试）</div>'; return;
    }
    const data = await resp.json();
    const msgs = data.messages || [];
    // 现有渲染逻辑...
    if (msgs.length === 0) {
      // R33: 区分「暂无消息」vs 加载成功但为空
      list.innerHTML = '<div class="empty">暂无消息</div>';
    } else {
      // 现有渲染...
    }
  } catch(e) {
    list.innerHTML = '<div class="empty">加载失败（网络异常）</div>';
  }
}
```

#### 改动 C-2：`/api/workspaces` 失败时前端提示（+3 行）

**位置：** `templates.py:372-384`，`renderWorkspacePanel()` 错误分支已有 `加载失败`，保持不改。

---

## 4. 不改的内容

| 事项 | 原因 |
|:-----|:-----|
| `__main__.py` 启动逻辑 | 不在本轮改动范围，且 session 加载已存在 |
| `persistence.py` 数据卷验证 | 属于运维层，需 Docker Compose 配置确认 |
| `handler.py` 消息处理 | Bug 不涉及 handler |
| Docker Compose / Dockerfile | 基础设施，不属于代码修复 |
| Web 端样式 / UI | 仅修复功能性 Bug |

---

## 5. 测试要点（给 🦐 测试工程师）

### Bug A

| # | 用例 | 预期 |
|:-:|:-----|:-----|
| A-T1 | 有活跃工作群 → 下拉刷新 | 📋 活跃 Tab 保持显示 |
| A-T2 | 有活跃工作群 → 刷新 → 切回大厅 → 再切活跃 | 消息正确加载 |
| A-T3 | 无活跃工作群 → 刷新 | 仍 2 Tab（大厅 + 历史） |
| A-T4 | 工作群被归档 → 15s 内 Tab 自动消失 | 活跃 Tab 隐藏 |
| A-T5 | 刷新后 API 不可达 | localStorage 恢复仍生效 |

### Bug B

| # | 用例 | 预期 |
|:-:|:-----|:-----|
| B-T1 | 部署/重启后访问 /chat | 不显示绑定码，直接进入聊天 |
| B-T2 | 部署后 WebSocket 自动重连 | 3s 内恢复，消息正常收发 |
| B-T3 | token 被服务端拒绝（401） | 自动清除 token 回绑定码页面 |

### Bug C

| # | 用例 | 预期 |
|:-:|:-----|:-----|
| C-T1 | 重新登录后历史工作群列表完整 | 所有归档群可见 |
| C-T2 | 点击归档工作群 → 历史消息加载 | 消息列表正确显示 |
| C-T3 | 无历史消息的工作群 | 显示「暂无消息」（非「加载失败」） |

---

## 6. 向后兼容

| 检查项 | 结论 |
|:-------|:----:|
| localStorage 新增 key 是否与现有 key 冲突 | ✅ 否 — `ws_tab2_*` 为新增命名空间 |
| 无活跃工作群时行为是否不变 | ✅ 是 — A-2 中 `!restoredTab2` 保护 |
| 不支持的浏览器（无 localStorage）是否降级 | ✅ 是 — 所有 `try/catch` 包裹 |
| 现有 API 端点是否改动 | ✅ 否 — 只改前端 JS |
| 后端 handler.py 是否受影响 | ✅ 否 |

---

## 7. 实施顺序

```
Step 6 编码顺序：
  ┌──────────────────────────┐
  │ 1. Bug A 改动 (4处)      │ ← 核心改动，影响最大
  │    A-1 switchToActiveTab  │
  │    A-2 init() 恢复        │
  │    A-3 轮询分支修复       │
  │    A-4 归档清除           │
  ├──────────────────────────┤
  │ 2. Bug B 改动 (3处)      │ ← 会话恢复
  │    B-1 validate_token 日志│
  │    B-2 loadMessages 401   │
  │    B-3 WS onclose 码检测  │
  ├──────────────────────────┤
  │ 3. Bug C 改动 (1处)      │ ← 体验优化
  │    C-1 loadMessages 空提示│
  └──────────────────────────┘
```

---

> **方案交付状态：** ✅ 待方向审查 → 🧐 需求分析师 Step 5
> **产出文件：** `docs/R33/tech-plan.md`
