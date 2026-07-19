# R130 技术方案 — Web UI 显示优化

> **起草人：** 📐 Arch（小开）
> **版本：** v1.0
> **基线：** dev `5038dab`（R130 需求 + WORK_PLAN 已合入）

---

## 1. 问题概述

纯前端显示优化轮。4 项修复：

| # | 问题 | 影响 | 方案 |
|:-:|:-----|:------|:-----|
| R1 | autorouter bot 在状态栏显示 | 干扰团队 bot 状态判断 | 白名单过滤，仅显示 7 开发 bot |
| R2 | 管理员 Tab 长期不用 | Tab 栏冗余 | 删除 `tab2` 配置 + admin-tab CSS |
| R3 | 搜索按钮/功能从未使用 | 界面噪声 | 删除搜索 DOM/JS 全链路 |
| R4 | Tab 切换 ~15 秒延迟 | 体验差 | fetch 加 AbortController + 5s 超时 |

---

## 2. 代码审计 — 精确行号

### 2.1 受影响文件

| 文件 | 总行数 | 待改行数 | 类型 |
|:-----|:------:|:--------:|:-----|
| `server/web_ui/templates.py` | 910 | ~80 | HTML + JS |
| `server/ws_server/__main__.py` | 878 | ~10 | Python |
| `server/web_ui/viewer.py` | 780 | — | 不动 |
| `server/common/config.py` | — | ~3 | 可选 |

### 2.2 R2：移除管理员 Tab — 行级定位

| # | 位置 | 行号 | 当前内容 | 操作 |
|:-:|:-----|:----:|:---------|:-----|
| 2a | CSS `.tab.admin-tab` | L67-L68 | 橙色高亮样式 | ❌ 删除 2 行 |
| 2b | TAB_STATE | L159 | 注释「3-tab (inbox \| admin \| history)」 | 改为 `(inbox \| history \| pipeline)` |
| 2c | TAB_STATE tab2 条目 | L162 | `tab2: { id: 'tab2', channel: '_admin', ... }` | ❌ 删除 L162 |
| 2d | renderTabBar admin 分支 | L255-L258 | `if (id === 'tab2') { html += '<div class="tab admin-tab"...' }` | ❌ 删除 L255-L258 |
| 2e | selectTab tab2 分支 | L288-L296 | `if (tabId === 'tab2') { ... return; }` | ❌ 删除 L288-L296 |

### 2.3 R3：移除搜索功能 — 行级定位

| # | 位置 | 行号 | 当前内容 | 操作 |
|:-:|:-----|:----:|:---------|:-----|
| 3a | 搜索按钮 DOM | L136 | `<button id="toggleSearchBtn" ...>🔍</button>` | ❌ 删除 L136 |
| 3b | 搜索栏 DOM | L144-L148 | `<div class="search-bar" id="searchBar">...` 含 input + searchBtn + clearBtn | ❌ 删除 L144-L148 |
| 3c | searchMode 变量 | L169 | `let searchMode = false;` | ❌ 删除 L169 |
| 3d | selectTab 退出搜索 | L271 | `if (searchMode) exitSearchMode();` | ❌ 删除 L271 |
| 3e | toggleSearchBtn 事件绑定 | L847-L856 | `document.getElementById('toggleSearchBtn').addEventListener(...)` | ❌ 删除 L847-L856 |
| 3f | exitSearchMode() 函数 | L858-L868 | `function exitSearchMode() { ... }` | ❌ 删除 L858-L868 |
| 3g | doSearch() 函数 | L870-L892 | `async function doSearch() { ... }` | ❌ 删除 L870-L892 |
| 3h | 搜索事件绑定 | L894-L898 | searchInput keydown + searchBtn click + searchClearBtn click | ❌ 删除 L894-L898 |

### 2.4 R1：Bot 状态栏白名单 — 数据流

```
__main__.py:_api_status()            __main__.py                    web_ui/main.py                 templates.py
L657-707                              │                            │                               │
                                     ↓                            ↓                               ↓
从 _connections 收集全量 agent     _fetch_bot_status() →        _api_status() 缓存             pollStatus()
→ 构建 agents_list                  _api_status HTTP 请求         L100 注册 /api/bot_status      L785 fetch /api/bot_status
→ 返回 JSON {agents: [...]}                                        → data.agents → bar.innerHTML
```

**过滤方案：** 两段式白名单（推荐方案 A + B）

| 层 | 方案 | 位置 | 操作 |
|:---|:-----|:------|:------|
| A（后端） | `__main__.py:_api_status()` | L657-707 | 填充 agents_list 前过滤，仅保留白名单 agent |
| B（前端） | `templates.py:pollStatus()` | L790 | `data.agents.forEach` 中按 `a.name` 过滤 |

**白名单定义：** 在 `common/config.py` 新增 `AGENT_WHITELIST` 配置变量。

| Agent | 状态栏显示名 |
|:------|:------------|
| 小爱 (ops) | 小爱 |
| 小谷 (PM) | 小谷 |
| 小开 (arch) | 小开 |
| 爱泰 (dev) | 爱泰 |
| 小周 (review) | 小周 |
| 泰虾 (qa) | 泰虾 |
| ws-bridge-server | ws-bridge-server |

### 2.5 R4：Tab 切换延迟修复

| 位置 | 行号 | 当前问题 | 改动 |
|:-----|:----:|:---------|:------|
| `renderPipelineDashboard()` fetch | L569 | `await fetch('/api/pipelines?...')` — 无超时 | 增加 `AbortController` + 5s 超时 |
| `selectTab()` tab4 分支 | L298-L302 | 直接调用 `renderPipelineDashboard()` | 确保前序 tab 已清空 + 加载状态显示 |

```javascript
// 修改后（L569 附近）：
async function renderPipelineDashboard() {
  const list = document.getElementById('msgList');
  list.innerHTML = '<div class="pipeline-empty">📊 加载中...</div>';
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const resp = await fetch('/api/pipelines?token=' + encodeURIComponent(TOKEN), { signal: controller.signal });
    clearTimeout(timeout);
    // ... 后续保持不变
  } catch(e) {
    clearTimeout(timeout);
    if (e.name === 'AbortError') {
      list.innerHTML = '<div class="pipeline-empty">⏱ 加载超时，请重试</div>';
    } else {
      list.innerHTML = '<div class="pipeline-empty">❌ 加载失败: ' + escapeHtml(e.message || '') + '</div>';
    }
  }
}
```

---

## 3. 改动清单

### 3.1 `server/ws_server/__main__.py`（+~10 行修改，0 删）

| 操作 | 位置 | 代码 |
|:-----|:------|:------|
| 导入白名单 | L657-660 | `from server.common.config import AGENT_WHITELIST` |
| 过滤 agents_list | L667+ | 在 `for agent_id, conns in list(_connections.items()):` 中增加白名单检查 |
| 过滤离线 users | L689+ | 同上 |
| 过滤 R73 离线 keys | L698+ | 同上 |

```python
# 过滤逻辑示例（在 L667 前加）：
WHITELIST_MODE = True  # 或检查 AGENT_WHITELIST 是否非空
if WHITELIST_MODE:
    name = users.get(agent_id, {}).get("name") or api_keys.get(agent_id, {}).get("display_name", "")
    if name not in AGENT_WHITELIST and agent_id not in AGENT_WHITELIST:
        continue  # 跳过非白名单 agent
```

### 3.2 `server/web_ui/templates.py`（净 -~70 行）

| 操作 | 区域 | 行数 |
|:-----|:------|:----:|
| ❌ 删除 CSS admin-tab | L67-L68 | -2 行 |
| ❌ 删除搜索按钮 DOM | L136 | -1 行 |
| ❌ 删除搜索栏 DOM | L144-L148 | -5 行 |
| ❌ 删除 searchMode 变量 | L169 | -1 行 |
| ❌ 删除 selectTab 搜索退出 | L271 | -1 行 |
| ❌ 删除 selectTab tab2 分支 | L288-L296 | -9 行 |
| ❌ 删除 renderTabBar admin 分支 | L255-L258 | -4 行 |
| ❌ 删除 TAB_STATE tab2 | L162 | -1 行 |
| ❌ 删除搜索事件绑定 | L847-L856 | -10 行 |
| ❌ 删除 exitSearchMode() | L858-L868 | -11 行 |
| ❌ 删除 doSearch() | L870-L892 | -23 行 |
| ❌ 删除搜索事件绑定 | L894-L898 | -5 行 |
| ✅ 更新 TAB_STATE 注释 | L159 | 修改文本 |
| ✅ 修改 renderPipelineDashboard | L565-L592 | ~+10 行修改 |
| ✅ pollStatus 白名单过滤 | L790 | ~+5 行修改 |

### 3.3 `server/common/config.py`（+~5 行）

```python
# ── R130: Web UI bot status white list ──
AGENT_WHITELIST: set[str] = set(
    filter(None, os.environ.get("WS_AGENT_WHITELIST", "小爱,小谷,小开,爱泰,小周,泰虾,ws-bridge-server").split(","))
)
```

---

## 4. 侧效应分析

| 变动 | 侧效应 | 风险 |
|:-----|:-------|:----:|
| 删除管理员 Tab | 用户无法通过 UI 看到 `_admin` 通道消息（后端通道仍存在） | 🟢 `_admin` 已长期不使用 |
| 删除搜索功能 | 用户无法在前端搜索消息（后端 `/api/chat/search` 路由保留） | 🟢 搜索从未被使用 |
| 白名单过滤 | 未在白名单中的 agent 不在状态栏显示 | 🟢 仅隐藏显示，不影响 agent 功能 |
| fetch AbortController | 超时后显示「加载超时」，不再显示空白/无限等待 | 🟢 体验改善 |
| 倒序显示逻辑 | 未修改 `sortNewestFirst()`, `insertBefore(firstChild)` | 🟢 零影响 |

**倒序保护确认（不变）：**

| 函数 | 行号 | 现状 | 操作 |
|:-----|:----:|:------|:-----|
| `sortNewestFirst()` | — | 消息排序 | ✅ 不动 |
| `loadMessages()` | L324-371 | AbortController 10s 超时已有 | ✅ 不动 |
| `loadInboxMessages()` | L410-433 | 已有 fetch 超时 | ✅ 不动 |
| `createPipelineCard()` | L594+ | 倒序渲染 | ✅ 不动 |

---

## 5. 不做事项

| # | 事项 | 理由 |
|:-:|:-----|:------|
| ❌ | 删除后端 `/api/chat/search` 路由 | 路由不显示在 UI，移除无收益 |
| ❌ | 删除 `auto_router.py` | 已在 R129 保留，不在本轮范围 |
| ❌ | 重新设计 Web UI 布局 | 本轮仅做减法 + 延迟修复 |
| ❌ | 修改消息发送/输入区域 | 不在本轮范围 |
| ❌ | 优化后端管线 API 响应速度 | 前端超时保护已够用 |

---

## 6. 验收检查表（11 项）

| # | 验收项 | 验证方法 | 优先级 |
|:-:|:-------|:---------|:------:|
| F1 | bot 状态栏仅显示 7 开发 bot | 打开 Web UI → 右上角状态栏 agent 列表 | 🟢 P0 |
| F2 | Tab 栏仅 3 个：收件箱 / 历史 / 管线 | 检查 Tab 栏（无「🔧 管理员」） | 🟢 P0 |
| F3 | 按钮区域无搜索按钮 🔍 | 检查 Header 工具栏 | 🟢 P0 |
| F4 | 点击管线 Tab 后 5s 内显示内容或超时提示 | 手动切换 Tab → 观察 | 🟢 P0 |
| F5 | 倒序显示不变 | 收件箱/历史/管线消息最新在上 | 🟢 P0 |
| R1 | 收件箱 Tab 正常加载、实时轮询 | 切到收件箱 → 新消息自动出现 | 🟢 P0 |
| R2 | 历史 Tab 正常加载、工作室面板正常 | 点击「历史工作室」→ 切工作室 | 🟢 P0 |
| R3 | 管线 Tab 数据正确、排序正确 | 切到管线 → 最新管线在最上 | 🟢 P0 |
| R4 | 登出按钮正常 | 点击登出 → 回到登录页 | 🟢 P0 |
| R5 | Bot 状态栏在线/离线指示正确 | 等待 15s 轮询 → 状态图标变化 | 🟢 P0 |
| R6 | 移动端响应式布局不受影响 | 缩窄浏览器窗口 → Tab/消息自适应 | 🟡 P1 |

---

## 7. 执行顺序

| 步骤 | 操作 | 依赖 |
|:----:|:-----|:-----|
| 1 | `config.py` 新增 `AGENT_WHITELIST` 变量 | — |
| 2 | `__main__.py:_api_status()` 增加白名单过滤 | 1 |
| 3 | `templates.py` 删除管理员 Tab（CSS / TAB_STATE / renderTabBar / selectTab） | — |
| 4 | `templates.py` 删除搜索功能全链路（DOM / 变量 / 函数 / 事件绑定） | 3 |
| 5 | `templates.py` pollStatus 前端白名单过滤 | 1 |
| 6 | `templates.py` renderPipelineDashboard 增加 AbortController + 5s 超时 | — |
| 7 | 全量回归验证（11 项验收表） | 1-6 |
