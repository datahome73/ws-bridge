# R130 需求文档 — Web UI 显示优化

> **轮次：** R130
> **类型：** Web UI 功能优化轮
> **版本：** v1.0
> **日期：** 2026-07-19
> **状态：** 📝 草稿待审

---

## §1 背景与问题

### 现状

Web UI（`server/web_ui/templates.py` + `viewer.py`）经历了 R8→R129 的多轮功能叠加，当前存在若干冗余功能和体验问题：

| # | 问题 | 影响 |
|:-:|:-----|:------|
| P1 | **autorouter bot** 已被禁用（`auto_router.py` 头部已标注 [DISABLED]），但可能仍在 bot 状态栏/列表中显示 | 干扰用户对当前开发团队 bot 状态的判断 |
| P2 | **管理员 Tab**（`_admin` 通道）已长期不使用，但仍在 Tab 栏中占用一个固定位置 | Tab 栏显示冗余，用户有额外切换成本 |
| P3 | **搜索按钮/搜索功能** 从未被实际使用，但占用了 Header 工具栏空间（`toggleSearchBtn` + 搜索栏 DOM + `doSearch` 全流程 JS） | 界面元素冗余，视觉噪声 |
| P4 | **Tab 切换响应延迟** — 点击「管线」Tab 后需要 ~15 秒才显示内容 | 用户体验差，不确定是加载中还是卡死 |

### 目标

```
当前 Web UI（templates.py ~910 行）         →  目标
├── TAB_STATE: 4-tab                          ├── TAB_STATE: 3-tab（移除管理员）
│   ├── 📬 收件箱                             │   ├── 📬 收件箱
│   ├── 🔧 管理员 ❌ 移除                      │   ├── 🗂️ 历史
│   ├── 🗂️ 历史                               │   └── 📊 管线
│   └── 📊 管线                               │
├── Header: 工作室按钮 + 🔍 搜索 ❌ 移除       ├── Header: 工作室按钮 + 状态 + 登出
├── Bot 状态栏: 全量 agent 列表                ├── Bot 状态栏: 仅 7 开发 bot
└── Tab 切换: 依赖轮询刷新                     └── Tab 切换: 立即触发拉取
```

---

## §2 核心设计

### 2.1 改动策略：前端过滤 + 后端配合

所有改动集中在 Web UI 前端（`templates.py` 中的 HTML/CSS/JS）和可能的后端状态 API（`viewer.py` / `__main__.py`）。**不改动倒序显示规则**（`sortNewestFirst` 保留）。

### 2.2 改动详细说明

#### R1: 移除 autorouter bot 显示 — bot 状态栏仅显示 7 开发 bot

| 维度 | 说明 |
|:----|:------|
| **定位** | `_api_status`（WSS 核心 `__main__.py` L657）返回全量 agent 列表；`handle_api_agents_status`（`viewer.py` L494）转发到前端；前端 `pollStatus()`（`templates.py` L782-821）渲染状态栏 |
| **方案 A（推荐）** | 在 `_api_status` 中对 agent 列表做白名单过滤，只输出当前 7 个开发 bot（小爱/小谷/小开/爱泰/小周/泰虾 + PM/ops bot） |
| **方案 B** | 前端 `pollStatus()` 回调中过滤 `data.agents`，只渲染白名单 bot |
| **方案 C** | 清理 `_approved_users.json` / `_api_keys.json` 中 autorouter 的注册记录（一次性数据清理） |

> 推荐方案 A+B 组合：后端做白名单过滤 + 前端做 fallback 渲染保护。

#### R2: 移除管理员 Tab

| 维度 | 说明 |
|:----|:------|
| **定位** | 前端 `TAB_STATE`（`templates.py` L160-165）的 `tab2` 配置 |
| **改动点** | 删除 `tab2` 条目；从 `renderTabBar()` 移除 `admin-tab` 分支判断；从 `selectTab()` 移除 `tab2` 分支（L289-296）；移除 CSS 中 `.admin-tab` 样式（L67-68）；移除 `colorMap` 中可能的冗余条目 |
| **影响** | Tab 栏从 4 个减为 3 个，布局右移。不影响后端 `_admin` 通道的存在 |

#### R3: 移除搜索按钮和搜索功能

| 维度 | 说明 |
|:----|:------|
| **定位** | 前端 Header 中的 `toggleSearchBtn`（L136）、搜索栏 `searchBar` DOM（L144-148）、相关 JS 函数：`exitSearchMode()`（L858-868）、`doSearch()`（L870-892）、`toggleSearchBtn` 事件绑定（L847-856）、`searchInput` 事件绑定（L894-897）、`searchClearBtn` 事件绑定（L898） |
| **改动点** | 删除 `toggleSearchBtn` 按钮元素；删除 `searchBar` DOM 区域；删除 `searchMode` 变量（L169）；删除 `exitSearchMode()`、`doSearch()` 函数；从 `selectTab()` 中移除 `if (searchMode) exitSearchMode();`（L271）；移除相关事件监听 |
| **后端关联** | `/api/chat/search` 路由（`viewer.py` L771）可保留，不影响 |

#### R4: 修复 Tab 切换延迟

| 维度 | 说明 |
|:----|:------|
| **定位** | `selectTab()` 的 `tab4` 分支（L299-303）已调用 `renderPipelineDashboard()`，但可能因后端响应慢或轮询错觉造成延迟 |
| **根因分析** | 可能存在 setTimeout 竞态或 `renderPipelineDashboard` 的 fetch 无超时兜底（`templates.py` L565-592 的 fetch 请求缺少 AbortController/timeout 保护） |
| **改动点** | ① `selectTab(tabId)` 中所有 tab 切换时设置 **显式加载状态** + **fetch 超时（最多 5s）**；② `renderPipelineDashboard()` 的 fetch 增加 AbortController + 5s 超时，超时后显示「加载超时，请重试」而不是空白；③ `loadMessages()` / `loadInboxMessages()` 已有 timeout（L328），保持不变；④ 如发现后端 `/api/pipelines` 响应慢，可在对应 handler（`viewer.py` L712-736）优化查询逻辑 |
| **期望** | 点击管线 Tab → 立即显示「📊 加载中...」→ 5s 内显示内容或超时提示。不再等待轮询周期 |

### 2.3 严守的约束

⚠️ **不得改动消息倒序显示逻辑**：所有消息列表的 `sortNewestFirst()` 排序、`insertBefore(firstChild)` 逻辑（L350-362、L425-429、L462、L710-720）保持原样。

---

## §3 改动范围

| 文件 | 新增行 | 删除行 | 修改行 | 净变化 | 说明 |
|:----|:------:|:------:|:------:|:-----:|:------|
| `server/web_ui/templates.py` | ~5 | ~60 | ~15 | **-70** | 移除管理员 Tab（~10 行）/搜索功能（~40 行）/状态栏过滤（~10 行）/Tab 切换超时保护（~15 行修改） |
| `server/ws_server/__main__.py` | ~5 | 0 | ~5 | **+5** | `_api_status` 增加白名单过滤/HIDDEN_AGENTS 扩展 |
| `server/web_ui/viewer.py` | ~3 | 0 | ~5 | **+3** | `handle_api_agents_status` 可选白名单过滤 |

### 各改动的行级影响

#### R1: Bot 状态栏过滤

| 位置 | 改动 |
|:-----|:------|
| `__main__.py` `_api_status()` L657-707 | 在构建 agents_list 时增加白名单检查，只包含 7 个开发 bot |
| `templates.py` `pollStatus()` L783-820 | 可选：在 `data.agents.forEach` 中过滤 |
| `common/config.py` `HIDDEN_AGENTS` L15-17 | 可选：扩展隐藏列表 |

#### R2: 移除管理员 Tab

| 位置 | 改动 |
|:-----|:------|
| `templates.py` `TAB_STATE` L160-165 | 删除 `tab2` 条目 |
| `templates.py` `renderTabBar()` L246-265 | 移除 `admin-tab` 分支（L255-258） |
| `templates.py` `selectTab()` L288-296 | 移除 `tab2` 分支 |
| `templates.py` CSS L67-68 | 移除 `.tab.admin-tab` / `.tab.admin-tab.active` 样式 |

#### R3: 移除搜索功能

| 位置 | 改动 |
|:-----|:------|
| `templates.py` Header 按钮 L136 | 删除 `toggleSearchBtn` |
| `templates.py` 搜索栏 DOM L144-148 | 删除整段 |
| `templates.py` `searchMode` 变量 L169 | 删除 |
| `templates.py` `selectTab()` L271 | 删除 `if (searchMode) exitSearchMode();` |
| `templates.py` `exitSearchMode()` L858-868 | 删除 |
| `templates.py` `doSearch()` L870-892 | 删除 |
| `templates.py` 事件绑定 L847-856 | 删除 toggle 搜索绑定 |
| `templates.py` 事件绑定 L894-898 | 删除搜索输入/按钮绑定 |

#### R4: Tab 切换延迟修复

| 位置 | 改动 |
|:-----|:------|
| `templates.py` `renderPipelineDashboard()` L565-592 | Fetch 增加 AbortController + 5s 超时 |
| `templates.py` `selectTab()` tab4 分支 L299-303 | 确保调用前清空旧状态 + 超时保护 |

---

## §4 验收标准

### 4.1 功能验收

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| F1 | bot 状态栏仅显示 7 个开发 bot，autorouter 不在其中 | 打开 Web UI → 检查 top-right 状态栏 agent 列表 |
| F2 | Tab 栏只有 3 个 Tab：收件箱 / 历史 / 管线 | 检查页面 Tab 栏（无「🔧 管理员」） |
| F3 | 按钮区域无搜索按钮（🔍） | 检查 Header 工具栏 |
| F4 | 点击管线 Tab 后 5s 内显示管线内容 | 手动切换 Tab → 观察显示时间 |
| F5 | **倒序显示不变** — 消息最新在上、最旧在下 | 检查收件箱/历史/管线的消息列表顺序 |

### 4.2 回归验证

| # | 回归项 | 验证方法 |
|:-:|:-------|:---------|
| R1 | 收件箱 Tab 正常加载、实时轮询（5s） | 切到收件箱 → 观察新消息自动出现 |
| R2 | 历史 Tab 正常加载、工作室面板正常 | 点击「历史工作室」→ 选择工作室 → 消息正常显示 |
| R3 | 管线 Tab 数据正确、排序正确 | 切到管线 → 最新管线在最上 |
| R4 | 登出按钮正常 | 点击登出 → 回到登录页 |
| R5 | Bot 状态栏在线/离线指示正确 | 等待 15s 轮询 → 确认状态图标变化 |
| R6 | 移动端响应式布局不受影响 | 缩窄浏览器窗口 → Tab 栏/消息列表自适应 |

---

## §5 不做事项

| # | 事项 | 理由 |
|:-:|:-----|:------|
| ❌ | 删除 `auto_router.py` 文件 | `auto_router.py` 是独立 CLI 脚本（非后台服务），已在 R129 保留。完全移除不属于本轮范围（除非用户要求） |
| ❌ | 删除后端 `/api/chat/search` 路由 | 后端路由不显示在 UI 中，移除没有收益，且保留不影响 |
| ❌ | 重新设计 Web UI 整体布局 | 本轮仅做减法（删除冗余元素）+ 修复延迟问题，不做重设计 |
| ❌ | 修改消息发送/输入区域 | 不在此轮范围 |
| ❌ | 优化管线后端 `/api/pipelines` 响应速度 | 如果延迟问题仅在前端 fetch 超时保护层面解决，后端优化可视情况延后到独立轮次 |

---

## §6 验收检查表

### 文件改动清单

| # | 文件 | 改动说明 | 状态 |
|:-:|:-----|:---------|:----:|
| 1 | `server/web_ui/templates.py` | 移除管理员 Tab（TAB_STATE/render/select/CSS） | ⬜ 待改 |
| 2 | `server/web_ui/templates.py` | 移除搜索按钮/搜索栏/搜索函数/事件绑定 | ⬜ 待改 |
| 3 | `server/web_ui/templates.py` | bot 状态栏白名单过滤（pollStatus 回调） | ⬜ 待改 |
| 4 | `server/web_ui/templates.py` | renderPipelineDashboard fetch 增加超时保护 | ⬜ 待改 |
| 5 | `server/ws_server/__main__.py` | _api_status 白名单过滤或 HIDDEN_AGENTS 扩展 | ⬜ 待改 |
| 6 | `server/web_ui/viewer.py` | handle_api_agents_status 可选白名单过滤 | ⬜ 待改 |

### 验收计数

| 分组 | 总数 | 🟢 通过 | 🔴 失败 |
|:----|:----:|:-------:|:-------:|
| 功能验收（F1-F5） | 5 | 0 | 0 |
| 回归验证（R1-R6） | 6 | 0 | 0 |
| **合计** | **11** | **0** | **0** |
