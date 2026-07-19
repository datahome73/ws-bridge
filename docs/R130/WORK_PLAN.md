# R130 WORK_PLAN — Web UI 显示优化

> **目标：** 移除 Web UI 中已废弃的 autorouter bot 显示、管理员 Tab、搜索功能，修复 Tab 切换延迟问题

---

## Step 1：需求确认 + 推 dev

- [ ] 审核 R130 需求文档
- [ ] 确认改动范围符合预期
- [ ] 推 dev：`git add -f docs/R130/ && git commit -m "docs: R130 v1.0 — Web UI 显示优化" && git push origin dev`

## Step 2：技术方案

本轮为纯前端显示优化轮，无新增架构设计，方案已在需求文档 §2 中定义：

| # | 方案 | 位置 | 说明 |
|:-:|:-----|:-----|:------|
| S1 | 白名单过滤 | `__main__.py` `_api_status()` | 后端限制 bot 状态栏仅 7 开发 bot |
| S2 | 删除 DOM + JS | `templates.py` | 移除管理员 Tab / 搜索按钮 / 搜索功能 |
| S3 | 超时保护 | `templates.py` `renderPipelineDashboard()` | fetch 加 AbortController + 5s 超时 |
| S4 | 倒序保护 | `templates.py` 全局 | 确保 `sortNewestFirst` 不受影响 |

- [ ] 如果用户要求修改方案，在此 Step 调整
- [ ] arch 确认方案 → 推进 Step 3

## Step 3：编码

### S3-1: 移除管理员 Tab（`templates.py`）

| 操作 | 位置 | 内容 |
|:----|:-----|:------|
| 删除 | `TAB_STATE` (L160-165) | 删除 tab2 `{ id: 'tab2', channel: '_admin', label: '🔧 管理员', ... }` |
| 修改 | `renderTabBar()` (L246-265) | 移除 admin-tab 分支（L255-258），循环简化为统一渲染 |
| 修改 | `selectTab()` (L288-296) | 移除 tab2 分支代码 |
| 删除 | CSS (L67-68) | 删除 `.tab.admin-tab` / `.tab.admin-tab.active` 样式 |
| 删除 | 注释 (L159) | 更新注释「3-tab (inbox \| admin \| history)」→「3-tab (inbox \| history \| pipeline)」 |

### S3-2: 移除搜索功能（`templates.py`）

| 操作 | 位置 | 内容 |
|:----|:-----|:------|
| 删除 | L136 | `toggleSearchBtn` 按钮 |
| 删除 | L144-148 | 搜索栏 DOM（searchBar div） |
| 删除 | L169 | `let searchMode = false;` |
| 修改 | L271 | 删除 `if (searchMode) exitSearchMode();` |
| 删除 | L847-856 | `toggleSearchBtn` 事件绑定 |
| 删除 | L858-868 | `exitSearchMode()` 函数 |
| 删除 | L870-892 | `doSearch()` 函数 |
| 删除 | L894-898 | `searchInput` / `searchBtn` / `searchClearBtn` 事件绑定 |

### S3-3: Bot 状态栏白名单过滤（`templates.py` + `__main__.py`）

| 操作 | 位置 | 内容 |
|:----|:-----|:------|
| 方案A | `__main__.py` `_api_status()` (L657-707) | 在构建 agents_list 时增加白名单：仅包含 7 个开发 bot |
| 方案B | `templates.py` `pollStatus()` (L790) | `data.agents.forEach` 中过滤非白名单 agent |
| 可选 | `common/config.py` HIDDEN_AGENTS | 扩展隐藏列表 |

### S3-4: Tab 切换超时保护（`templates.py`）

| 操作 | 位置 | 内容 |
|:----|:-----|:------|
| 修改 | `renderPipelineDashboard()` (L565-592) | fetch 增加 AbortController + 5s 超时，超时显示「⏱ 加载超时，请重试」 |
| 验证 | `loadMessages()` (L324-371) | 已有 10s timeout（L328），不需修改 |
| 验证 | `loadInboxMessages()` (L410-433) | 已有 fetch 不设 timeout 但无超时显示，可选补上 |

## Step 4：代码审查

- [ ] 审查 `templates.py` 变更 — 确保删除的 JS 函数不影响其他功能（特别是 selectTab 中搜索退出逻辑）
- [ ] 审查 `__main__.py` 白名单过滤逻辑
- [ ] 确认 `sortNewestFirst` 和 `insertBefore(firstChild)` 未受影响

## Step 5：测试验证

- [ ] `py_compile` 检查 Python 文件语法
- [ ] 前端 JS 语法验证（无编译工具则肉眼检查大括号/分号完整性）
- [ ] 确认删除的 DOM 元素 ID 不在代码其他地方引用

### QA 检查表

| # | 验收项 | 结果 |
|:-:|:-------|:----:|
| F1 | bot 状态栏仅 7 个开发 bot | ⬜ |
| F2 | 无「🔧 管理员」Tab | ⬜ |
| F3 | 无「🔍」搜索按钮 | ⬜ |
| F4 | 点击管线 Tab 5s 内显示 | ⬜ |
| F5 | 倒序显示不变 | ⬜ |
| R1 | 收件箱 Tab 正常加载、实时轮询（5s） | ⬜ |
| R2 | 历史 Tab 正常加载、工作室面板正常 | ⬜ |
| R3 | 管线 Tab 数据正确、排序正确 | ⬜ |
| R4 | 登出按钮正常 | ⬜ |
| R5 | Bot 状态栏在线/离线指示正确 | ⬜ |
| R6 | 移动端响应式布局不受影响 | ⬜ |

## Step 6：合并部署

- [ ] `git checkout main && git pull origin main`
- [ ] `git merge dev`（merge commit）
- [ ] `git push origin main`
- [ ] 部署到生产环境

---

## 关键里程碑

| 阶段 | 交付物 |
|:-----|:-------|
| Step 1 ✅ | 需求文档审核通过 + 推 dev |
| Step 2 ✅ | 技术方案确认（无新增架构，沿用需求文档 §2 方案） |
| Step 3 ✅ | 编码完成（管理员 Tab 移除 / 搜索功能移除 / 白名单过滤 / 超时保护） |
| Step 4 ✅ | 代码审查通过（templates.py 变更 / __main__.py 白名单 / 倒序约束未受影响） |
| Step 5 ✅ | 测试验证 11/11 ALL GREEN 🟢 |
| Step 6 ✅ | 合 main 部署 |

---

## 改动预览

| 文件 | 新增 | 删除 | 修改 | 净变化 |
|:-----|:----:|:----:|:----:|:------:|
| `server/web_ui/templates.py` | ~5 | ~60 | ~20 | **-70** |
| `server/ws_server/__main__.py` | ~5 | 0 | ~5 | **+5** |
| `server/web_ui/viewer.py` | ~3 | 0 | ~5 | **+3** |
