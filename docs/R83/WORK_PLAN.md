---
pipeline:
  name: "R83 Web 端 Inbox 化改造"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R83/WORK_PLAN.md"

  workspace:
    members:
      architect:
        mention_keyword: "小开;architect;架构师"
        rules: "输出技术方案文档（含 B1 诊断 + 所有改动点）"
      developer:
        mention_keyword: "爱泰;developer;开发"
        rules: "按技术方案编码"
      reviewer:
        mention_keyword: "小周;reviewer;审查"
        rules: "代码审查"
      qa:
        mention_keyword: "泰虾;qa;测试"
        rules: "浏览器验证 + 端到端测试"
      operations:
        mention_keyword: "小爱;operations;运维"
        rules: "合并部署归档"

  steps:
    step2:
      role: architect
      title: 技术方案（含收件箱 B1 诊断）
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R83/R83-product-requirements.md"
      timeout_minutes: 360
    step3:
      role: developer
      title: 编码实现
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R83/R83-product-requirements.md"
      timeout_minutes: 360
    step4:
      role: reviewer
      title: 代码审查
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R83/R83-product-requirements.md"
      timeout_minutes: 180
    step5:
      role: qa
      title: 测试验证
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R83/R83-product-requirements.md"
      timeout_minutes: 180
    step6:
      role: operations
      title: 合并部署归档
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R83/R83-product-requirements.md"
      timeout_minutes: 60
---

# R83 工作计划 — Web 端 Inbox 化改造 🎯

> **版本：** v1.0
> **状态：** 📋 定稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R83/R83-product-requirements.md v1.0 ✅（项目负责人审核通过）

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动极小（~125 行净改），严禁 scope creep：**
- 🔴 不改 `server/handler.py`（R82 已完成服务端重构，本轮不动）
- 🔴 不改 bot 客户端
- 🔴 不改界面视觉风格/颜色
- 🔴 不增加新的 API 端点（只删不改）
- 🟢 本次改动全部集中在 `server/templates.py`（JS）和 `server/web_viewer.py`

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | architect | developer | 先诊断 B1 再出方案 |
| Step 3 | 💻 编码 | developer | architect | 按技术方案编码 |
| Step 4 | 🔍 审查 | reviewer | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | reviewer | 浏览器验证为重点 |
| Step 6 | 🦸 合并部署 | operations | architect | — |

### 0.3 工作区成员管理规则

- **owner（创建者）= 群主**：可踢人、可关工作区
- **群成员**：可拉人加入、可自己加入、可自己退出
- **不可踢出 owner**：owner 不能 `!workspace_leave`，也不能被踢出
- **min_role=2（全员可用）**

---

## 1. 管线总览

### 改动范围

仅 3 个文件，~125 行净改：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A | Tab 架构重写（3-tab：收件箱/管理员/历史） | `server/templates.py` TAB_STATE + renderTabBar + init + selectTab | ~80 行 |
| 2 | B | 收件箱 API 修复（B1 诊断→B2 修复） | `server/web_viewer.py` handle_api_inbox + `server/message_store.py` | ~40+5 行 |
| 3 | C | 删除绑定码 API（3 个路由+函数） | `server/web_viewer.py` + 可能 `auth.py` / `persistence.py` | ~40 行 |

**总估算：** ~125 行净改

---

## 2. 管线步骤

### Step 2 — 技术方案（架构师 🏗️）

**主角：** 架构师（小开）
**备用：** 开发工程师（爱泰）

**任务：**

1. **阅读需求文档** — `docs/R83/R83-product-requirements.md`
2. **B1 诊断** — 确定收件箱 Tab 空白的根因：
   - 在**服务器上实际执行诊断**（非纯代码分析）
   - 浏览器 DevTools → `/api/chat/inbox` 响应检查
   - `sqlite3 data/messages.db` → 检查 DB 中 inbox 消息
   - 测试 `LIKE '_inbox:%'` SQL 查询对 `_inbox:xxx` 的实际匹配效果
   - 检查 `handle_api_inbox()` 的 `/api/chat/inbox` 返回数据格式与前端 `loadInboxMessages()` 的期望是否一致
3. **输出技术方案文档** `docs/R83/R83-tech-plan.md`，包含：
   - B1 诊断结论（根因精确到哪一行代码）
   - A1-A4 每个改动点的精确代码修改（旧→新对比）
   - B2 修复方案（3 个 Scenario 中实际需要哪个）
   - C1 删除项清单（逐个标注文件+行号）
   - 兼容性分析（删除 tab2 后 poll/WS 事件链是否完整）
   - **完成条件：** 推 dev，告知 SHA

---

### Step 3 — 编码（开发工程师 💻）

**主角：** 开发工程师（爱泰）
**备用：** 架构师（小开）

**任务：**

按技术方案执行以下编码：

#### 方向 A — Tab 标签栏重设计

1. **TAB_STATE 重写**：5-tab → 3-tab（收件箱/管理员/历史）
2. **renderTabBar() 重写**：只渲染 3 个 tab，删大厅/活跃分支
3. **selectTab() 默认首页改为收件箱**：删 tab2 判断逻辑
4. **init() 简化**：删 localStorage tab2 恢复 + 删 `/api/workspaces` tab2 回填
5. **删除 `switchToActiveTab()` 函数**
6. **15s poll 中删 tab2 检测**：删 `activeIds.indexOf(...)` 和 `switchToActiveTab` 调用
7. **`renderWsPanel()` 简化**：删活跃工作室分类，只保留已归档工作室

#### 方向 B — 收件箱消息显示修复

按技术方案诊断结果修复。可能涉及：
- `server/message_store.py` — SQL LIKE 查询转义
- `server/web_viewer.py` — `handle_api_inbox()` 增加 fallback 或修复响应格式
- `server/templates.py` — 前端渲染修复（如 `createInboxMessageEl`）

#### 方向 C — 登录入口清理

- 删 `web_viewer.py` 中 `handle_api_bind` / `handle_api_check` / `handle_api_approve_web` 函数
- 删 `setup_routes()` 中对应的 3 条路由注册
- 删 `auth.py` 中 `generate_web_bind_code` / `create_web_bind_code` / `approve_web_bind_code`（如不再被引用）
- 删 `persistence.py` 中 `get/set/save_web_bind_codes`（如不再被引用）

**完成条件：** 推 dev，告知 SHA

---

### Step 4 — 代码审查（审查工程师 🔍）

**主角：** 审查工程师（小周）
**备用：** 测试工程师（泰虾）

**审查重点：**

1. **Scope 合规** — 没有改动 `server/handler.py` 或 bot 客户端（< 审查发现越界直接打回）
2. **`TAB_STATE` 所有引用点检查** — 确认 `TAB_STATE.tab1`/`tab2`/`tab3` 在 3-tab 架构中全部被正确处理
3. **`switchToActiveTab()` 和 tab2 相关代码已删干净** — `grep -n 'tab2\|switchToActiveTab' server/templates.py` 零匹配
4. **WS inbox 事件链正确** — `onmessage` 处理 inbox 消息→触发 unread badge→点击 tab5 显示
5. **绑定码函数已删** — `grep -n 'bind_code\|api/bind\|api/check\|api/approve' server/web_viewer.py` 零匹配
6. **删除的连接影响** — 确认 `setup_routes()` 中 3 条路由已移除，无残留引用
7. **JavaScript 语法正确** — 无逗号/括号/引号语法错误（手动检查或浏览器预览）

**完成条件：** 输出审查报告 `docs/R83/R83-code-review.md` 推 dev，告知 SHA

---

### Step 5 — 测试（测试工程师 🦐）

**主角：** 测试工程师（泰虾）
**备用：** 审查工程师（小周）

**测试方法：** 浏览器验证 + 静态代码检查

#### 方向 A 测试（✅-1 ~ ✅-12）

| # | 方法 | 通过条件 |
|:-:|:-----|:---------|
| ✅-1 | 打开 /chat | 默认 Tab 显示收件箱（非大厅/活跃） |
| ✅-2 | 检查标签栏 | 只有 3 个 tab：收件箱 · 管理员 · 历史 |
| ✅-3 | `grep templates.py` | 无「大厅」字面量 |
| ✅-4 | `grep templates.py` | 无「活跃」字面量 |
| ✅-5 | 切管理员 Tab | 显示输入框 |
| ✅-6 | 切收件箱 Tab | 无输入框 |
| ✅-7 | 切历史 Tab | 无输入框 |
| ✅-8 | 点击📋按钮 | 面板只显示已归档工作室 |
| ✅-9 | 面板内容 | 无「活跃工作室」字样 |
| ✅-10 | 点击归档工作室 | 切历史 Tab + 加载消息 |
| ✅-11 | 浏览器 Console | 无 JS 错误 |
| ✅-12 | `grep templates.py` | 无 `localStorage.*tab2` |

#### 方向 B 测试（✅-13 ~ ✅-18）

| # | 方法 | 通过条件 |
|:-:|:-----|:---------|
| ✅-13 | 打开收件箱 Tab | 显示消息列表，非「暂无收件箱消息」 |
| ✅-14 | 后台发 inbox 消息 | 实时出现在顶部 |
| ✅-15 | 切管理员 Tab 后收消息 | 收件箱显示红点 |
| ✅-16 | 点收件箱 Tab | 红点消失 |
| ✅-17 | 查看消息 | 发送人+接收人+时间+内容 完整显示 |
| ✅-18 | 发送人颜色 | 与名字对应 |

#### 方向 C 测试（✅-19 ~ ✅-23）

| # | 方法 | 通过条件 |
|:-:|:-----|:---------|
| ✅-19 | 打开 /chat（未登录） | 只显示 GitHub 登录按钮 |
| ✅-20 | `curl /api/bind` | 404 |
| ✅-21 | `curl /api/check` | 404 |
| ✅-22 | GitHub OAuth 登录 | 正常跳转（灰度测试） |
| ✅-23 | `grep auth.py` | 无 `generate_web_bind_code` |

**完成条件：** 输出测试报告 `docs/R83/R83-test-report.md` 推 dev，告知 SHA

---

### Step 6 — 合并部署归档（运维 🦸）

**主角：** 运维（小爱）
**备用：** 架构师（小开）

**操作：**

1. `git checkout main && git merge dev`
2. `git push origin main`
3. `docker build -t ws-bridge:r83 .`
4. 部署生产容器
5. 运维单独执行**旧数据归档**（非编码工作）：
   - `mv data/messages.db data/messages.db.r82-backup`
   - `rm -f data/_archive_state.json`
   - 重启服务后新 DB 自动创建
6. `!pipeline_status` 确认服务健康
7. `TODO.md` 更新版本号

**完成条件：** 合并部署完成，TODO 更新

---

## 3. 验收清单（从需求文档复制）

### 🎯 3.1 方向 A：Tab 标签栏重设计

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 登录后默认 Tab 是收件箱 | 浏览器打开 /chat 后直接显示收件箱消息列表 | 打开 web 端观察默认 Tab |
| ✅-2 | 标签栏只有 3 个 Tab | 收件箱 📬 · 管理员 🔧 · 历史 🗂️ | 检查标签栏 |
| ✅-3 | 无「大厅」标签 | 标签栏中不出现「大厅」字样 | grep templates.py '大厅' 零匹配 |
| ✅-4 | 无「活跃工作室」标签 | 标签栏不出现「活跃」字样 | grep templates.py '活跃' 零匹配 |
| ✅-5 | 管理员 Tab 有输入框 | 切换到管理员 Tab 后显示输入框 | 手动切换查看 |
| ✅-6 | 收件箱 Tab 无输入框 | 切换到收件箱 Tab 后输入框隐藏 | 手动切换查看 |
| ✅-7 | 历史 Tab 无输入框 | 切换到历史 Tab 后输入框隐藏 | 手动切换查看 |
| ✅-8 | 工作区面板只有「工作室归档」 | 点击「📋」按钮，面板只显示已归档工作室 | 打开面板查看 |
| ✅-9 | 工作区面板无「活跃工作室」分类 | 面板中无绿色「活跃工作室」区块 | 打开面板查看 |
| ✅-10 | 点击已归档工作室正确查看历史消息 | 点击后切换到历史 Tab 并加载消息 | 点击验证 |
| ✅-11 | 15s 定时 poll 不报错 | 无 JavaScript 错误 | 浏览器 Console 检查 |
| ✅-12 | 无 `localStorage` 残留 key | `ws_tab2_channel` 等旧 key 不再写入 | grep js 中 `localStorage.setItem` 无 `tab2` |

### 🎯 3.2 方向 B：收件箱消息显示修复

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-13 | 收件箱 Tab 显示消息 | 点开展示消息列表面非「暂无收件箱消息」 | 手动查看 |
| ✅-14 | 新消息实时推送到收件箱 | 收件箱打开时，新消息自动出现在列表顶部 | 发一条 inbox 消息验证 |
| ✅-15 | 收件箱不在前台时显示未读红点 | 切换到管理员 Tab 后，收件箱收到新消息显示 badge | 后台发 inbox 消息 |
| ✅-16 | 点击收件箱 Tab 清除红点 | 切换到收件箱后红点消失 | 手动验证 |
| ✅-17 | 消息显示发送人+接收人+时间+内容 | 每条消息完整显示四要素 | 手动查看 |
| ✅-18 | 发送人颜色正确 | bot 颜色与名字对应 | 手动查看 |

### 🎯 3.3 方向 C：登录入口清理

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-19 | 登录页面只有 GitHub OAuth | 只显示 GitHub 登录按钮 | 打开 /chat |
| ✅-20 | `/api/bind` 返回 404 | 绑定码 API 已删除 | curl /api/bind |
| ✅-21 | `/api/check` 返回 404 | 绑定码检查 API 已删除 | curl /api/check |
| ✅-22 | GitHub OAuth 登录正常 | 可用 GitHub 账号登录并跳转 | 手动测试 |
| ✅-23 | `auth.py` 无绑定码相关函数 | `generate_web_bind_code` 等函数不存在 | grep 源码 |
