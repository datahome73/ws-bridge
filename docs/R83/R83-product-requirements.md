# R83 产品需求 — Web 端 Inbox 化改造 🎯

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-10
> **本轮改动范围：** `server/templates.py`（CHAT_TEMPLATE JS）、`server/web_viewer.py`（路由+API）、`server/message_store.py`（可能）、`server/workspace_api.py`（可能）
> **参考：** R82 Inbox-Only 架构重构、R76 收件箱+归档、R20 标签栏架构
> **基线：** `05a5d92`（R82 origin/dev HEAD）

---

## 0. 先验验证：R82 Inbox-Only 架构部署

R82 将服务端从 4 通道（lobby / ws:xxx / _admin / _inbox:xxx）简化为 inbox-only。**但 web 前端从未更新**——仍显示旧的频道模型（大厅、活跃工作室）。

| 验证项 | 结果 | 确认方式 |
|:-------|:----:|:---------|
| `handler.py` 无 `MSG_SET_ACTIVE_CHANNEL` | ✅ | `git show origin/dev:server/handler.py \| grep MSG_SET_ACTIVE` 零匹配 |
| `persistence.py` 无 `get/set_agent_channel()` | ✅ | 函数已删除 |
| `_inbox:server` 查询路由存在 | ✅ | `_handle_server_query` 函数在 handler.py 中 |
| 收件箱消息持久化到 DB | ✅ | `ms.save_message` + `channel=_inbox_ch` 在 `_send_inbox_task` 中 |
| **web 端 tabs 仍显示「大厅」「活跃工作室」** | ❌ | `templates.py` TAB_STATE 仍含 tab1(lobby) 和 tab2(active) |
| **收件箱页面显示消息** | ❌ | 红点可见但点击后空白 |

---

## 1. 问题背景

### 1.1 现状

R82 重构后，服务端已经实现了 **inbox-only** 架构：
- Bot 不再接收 lobby/workspace 广播
- 工作室是时间切片元数据，不是频道
- 查询通过 `_inbox:server` 路由回复到发送者 inbox

但 **web 前端完全未更新**，仍然是旧架构的界面：

| 方面 | 旧架构（R81 以前） | 新架构（R82 之后） | Web 前端现状 |
|:-----|:-----------------|:------------------|:------------|
| 频道模型 | Lobby + Workspace + _admin + _inbox | 仅 _admin + _inbox | ❌ 仍显示 5 个 tab |
| 标签栏 | tab1=大厅 tab2=活跃 tab3=历史 tab4=管理员 tab5=收件箱 | 仅需 tab4=管理员 tab5=收件箱 tab3=历史 | ❌ 大厅/活跃标签已无意义 |
| 默认 Tab | 活跃工作室（有工作区时）或大厅 | 收件箱 | ❌ 仍默认跳转到大厅/活跃 |
| 登录 | 绑定码 + GitHub OAuth | 仅 GitHub OAuth | ❌ 绑定码 API 仍存在 |

### 1.2 根因分析

| # | 问题 | 根因 |
|:-:|:-----|:------|
| 1 | **标签栏过时** | R82 删了活跃频道概念但前端 TAB_STATE 没改 |
| 2 | **收件箱 Tab 空白** | 可能有多种原因——消息已存 DB 但前端渲染链路断（详见方向 A 诊断） |
| 3 | **登录入口混乱** | 绑定码已取消但仍保留 handle_api_bind/handle_api_check 路由 |
| 4 | **数据陈旧** | R82 前的老数据混在 DB 中，R83 开始应清清爽爽（运维单独处理） |

### 1.3 为什么本轮修

| 原因 | 说明 |
|:-----|:------|
| 🔴 **架构演进的前端空白** | R82 完成服务端但前端仍是旧界面，导致"能看到红点但看不到消息"的尴尬体验 |
| 🔴 **新人/真人看 web 端困惑** | 看到「大厅」「活跃工作室」标签但点进去没有内容（因为不再有这些频道了） |
| 🟡 **收件箱看不到消息阻塞管线** | 大宏无法通过 web 端查看 inbox 消息，只能靠 TG 转发 |

---

## 2. 功能需求

### 设计原则

> **Web 端是人类的实时观察窗。** 核心观察对象是收件箱（所有 bot 的 inbox 消息流），辅助观察频道是 _admin（系统通知）和历史工作室归档。
>
> **不再有「大厅」或「活跃工作室」标签。** 这些概念已在服务端消失。
>
> **登录入口只留 GitHub OAuth。** 绑定码全面下线。

---

### 方向 A（核心）：Tab 标签栏重设计 🔴 P0

#### A1 — Tab 结构重设计

当前 5-tab 架构：
```
tab1: 🌐 大厅         → ❌ 已无意义，删除
tab2: 📋 活跃工作室    → ❌ 已无意义，删除
tab3: 🗂️ 历史查看器   → ✅ 保留（查看已归档工作室）
tab4: 🔧 管理员       → ✅ 保留（_admin 频道）
tab5: 📬 收件箱       → ✅ 保留，提升为默认首页
```

新 3-tab 架构：
```
tab1: 📬 收件箱     → 默认首页，显示所有 inbox 消息（混排）
tab2: 🔧 管理员     → _admin 系统频道（保持不变）
tab3: 🗂️ 历史      → 查看已归档工作室（原名「历史查看器」）
```

**位置：** `server/templates.py` → `TAB_STATE` 对象 + `renderTabBar()` 函数 + `selectTab()` 初始化逻辑

```javascript
// 旧
const TAB_STATE = {
  tab1: { id: 'tab1', channel: 'lobby',       label: '🌐 大厅',     permanent: true,  visible: true },
  tab2: { id: 'tab2', channel: null,           label: '📋 活跃',     permanent: false, visible: false },
  tab4: { id: 'tab4', channel: '_admin',       label: '🔧 管理员',   permanent: true,  visible: true },
  tab5: { id: 'tab5', channel: '__inbox__',    label: '📬 收件箱',   permanent: true,  visible: true },
  tab3: { id: 'tab3', channel: null,           label: '🗂️ 历史查看器', permanent: true,  visible: true },
};

// 新
const TAB_STATE = {
  tab1: { id: 'tab1', channel: '__inbox__',    label: '📬 收件箱',   permanent: true,  visible: true },
  tab2: { id: 'tab2', channel: '_admin',       label: '🔧 管理员',   permanent: true,  visible: true },
  tab3: { id: 'tab3', channel: null,           label: '🗂️ 历史',    permanent: true,  visible: true },
};
```

#### A2 — 默认首页改为收件箱

**旧行为：** 初始化 `init()` → 检测活跃工作室 → 优先跳 tab2（活跃），否则 tab1（大厅）

**新行为：** 初始化 → 直接跳 tab1（收件箱），不再检测活跃工作室

```javascript
// 旧
var firstTab = 'tab1';
if (TAB_STATE.tab2.visible && TAB_STATE.tab2.channel) {
    firstTab = 'tab2';
}

// 新（简化）
const firstTab = 'tab1';  // 始终默认收件箱
```

**配套改动：**
- 删除 `init()` 中 Tab2 localStorage 恢复逻辑（`localStorage.getItem('ws_tab2_channel')`）
- 删除 `init()` 中 `/api/workspaces` 第一轮 fetch 的 Tab2 回填
- 删除 Tab2 相关的 `switchToActiveTab()` 函数
- 删除 `renderTabBar()` 中 Tab2 的渲染分支
- 删除 `selectTab()` 中 Tab2 的特殊处理
- 删除 15s 定时 poll 中的 Tab2 检测代码（`activeIds.indexOf(...)` 和 `switchToActiveTab` 调用）

#### A3 — 消息输入区改造

R82 后，真人发消息的唯二目的地是 `_admin` 频道（系统命令）和 `_inbox:<agent_id>`（发 inbox 消息给特定 bot）。

**旧行为：**
- 大厅 tab 有输入框 → 可以发消息到 lobby（已无意义）
- 管理员 tab 有输入框 → 可以发消息到 _admin
- 收件箱 tab 无输入框（只读）
- 活跃工作室 tab 有输入框 → 可以发消息到 ws:xxx（已无意义）

**新行为：**
- 收件箱 tab → 只读，无输入框（看所有 bot 的 inbox 消息）
- 管理员 tab → 有输入框，发消息到 _admin（保留）
- 历史 tab → 只读，无输入框（保持不变）

#### A4 — 工作区面板调整

已归档工作室面板（原 `ws-panel`）仍保留，但：
- 删除「活跃工作室」分类（不再有活跃工作室）
- 只保留「历史工作室」分类
- 面板标题改为「📦 工作室归档」

**位置：** `renderWsPanel()` 函数

```javascript
// 旧
var html = '';
if (activeWs.length > 0) {
    html += '<div class="ws-section-header ws-section-active">🟢 活跃工作室</div>';
    html += activeWs.map(buildWsItem).join('');
}
if (archivedWs.length > 0) {
    html += '<div class="ws-section-header ws-section-archived">🗂️ 历史工作室</div>';
    html += archivedWs.map(buildWsItem).join('');
}

// 新
var html = '';
if (archivedWs.length > 0) {
    html += '<div class="ws-section-header ws-section-archived">📦 工作室归档</div>';
    html += archivedWs.map(buildWsItem).join('');
} else {
    html = '<div style="padding:14px;color:#8b949e;font-size:0.85rem;">暂无已归档工作室</div>';
}
```

**配套改动：**
- `buildWsItem()` 中删除 `state === 'active'` 分支的 `switchToActiveTab` 处理
- 所有调用 `switchToActiveTab()` 的地方改为 `switchHistoryTab()`（点击已归档工作室一样查看历史消息）

---

### 方向 B：收件箱消息显示修复 🔴 P0

#### B1 — 诊断收件箱 Tab 空白根因

**当前观察到的现象：**
- WS 推送 inbox 消息到前端 → 触发 unread badge 红点 ✅
- 点击收件箱 tab → `loadInboxMessages()` 调用 → API 返回空 ❌

**可能的假设树：**

| 假设 | 可能性 | 验证方法 |
|:-----|:------:|:---------|
| H1: `get_messages_by_channel_pattern("_inbox:%", ...)` SQL 查询不匹配 | 🟡 中 | 检查 SQLite 中的 channel 值格式 |
| H2: 消息被存到 DB 但 channel 值不是 `_inbox:xxx` 格式 | 🟢 低 | grep handler.py 中 `save_message` 的 channel 参数 |
| H3: API 路由不存在或 401 | 🔴 高 | 浏览器 DevTools Network 面板检查 `/api/chat/inbox` 响应 |
| H4: 前端 `createInboxMessageEl` 渲染报错吞异常 | 🟡 中 | 检查浏览器 Console JS 错误 |
| H5: 红点来自 WS push 但旧消息未在 DB 中（新消息才存） | 🟡 中 | WS push 到 `_inboxCache` 但不一定持久化到 DB |

**诊断步骤（管线 Step 2 执行）：**

```
1. 浏览器 DevTools → Network → 点击收件箱 tab → 查看 /api/chat/inbox 请求和响应
   - 401 → token 过期
   - 200 但 messages=[] → DB 查询问题
   - 200 有 messages → 前端渲染问题

2. 检查 DB 中实际存储的 inbox 消息：
   sqlite3 data/messages.db "SELECT channel, COUNT(*) FROM messages WHERE channel LIKE '_inbox:%' GROUP BY channel"

3. 如果 DB 中有消息但 API 返回空 → 检查 get_messages_by_channel_pattern 函数
   注意：SQL LIKE 中 '_' 是单字符通配符，'_inbox:%' 匹配形如 '?inbox:xxx'
   → 实际测试 `LIKE '_inbox:%'` 对 `_inbox:ws_xxx` 的效果

4. 如果 DB 中无消息 → 检查 handler.py 中 inbox 消息持久化路径是否完整
   - 直接消息 → handle_broadcast 中 ms.save_message 的 channel 参数是 _inbox:xxx？
   - 系统通知 → _send_inbox_task 中 ms.save_message 的 channel 是 inbox_ch？
```

#### B2 — 修复收件箱消息展示

根据 B1 诊断结果选择修复方式：

**Scenario 1：SQL LIKE 通配符问题**
如果 `LIKE '_inbox:%'` 在 SQLite 中不匹配字面量 `_inbox:`（因为 `_` 是单字符通配符），改为 `LIKE '\\_inbox:%'`或用 `channel LIKE '_inbox:%' ESCAPE '\\'`。

→ 改动位置：`server/message_store.py` `get_messages_by_channel_pattern()` 或 `server/web_viewer.py` `handle_api_inbox()`

**Scenario 2：DB 中无历史 inbox 消息**
如果 inbox 消息从未被持久化到 DB（仅通过 WS push 实时推送），则：
- 增加 `handle_api_inbox()` 的 fallback：从内存 buffer (`_chat_buffers`) 读取 `_inbox:xxx` 频道消息
- 或检查 handler.py 中所有 inbox 消息保存路径是否完整

**Scenario 3：前端渲染异常**
如果 API 返回正确数据但前端不显示，检查 `createInboxMessageEl()` 的 DOM 操作，特别是：
- `m.from_name` 是否为空（API 需要返回 `from_name` 字段）
- `m.to_name` 是否为空（API 需要返回 `to_name` 字段）
- `m.content` 是否被正确处理

#### B3 — 收件箱消息完善

收件箱 Tab 作为核心界面，应显示完整的消息元信息：

| 字段 | 当前 | 需要 |
|:-----|:-----|:-----|
| 发送人 (+颜色) | ✅ | ✅ 保留 |
| 时间戳 | ✅ | ✅ 保留 |
| 接收人 | ✅ | ✅ 保留 |
| 内容 | ✅ | ✅ 保留 |
| 频道标签 (来自哪个 inbox) | ❌ | 🟢 新增：标注消息发到谁的收件箱 |
| 消息类型 (bot回复/系统通知/PM派活) | ❌ | 🟢 新增：用小标签区分 |

---

### 方向 C：登录入口清理 🟡 P1

#### C1 — 删除绑定码 API

绑定码已全面取消，以下 API 路由应删除：

| 路由 | 文件 | 操作 |
|:-----|:-----|:-----|
| `GET /api/bind` | `web_viewer.py` → `handle_api_bind` | 删除路由注册 + 函数 |
| `GET /api/check` | `web_viewer.py` → `handle_api_check` | 删除路由注册 + 函数 |
| `POST /api/approve_web` | `web_viewer.py` → `handle_api_approve_web` | 删除路由注册 + 函数 |
| `auth.generate_web_bind_code()` | `auth.py` | 删除（如不再被引用） |
| `auth.create_web_bind_code()` | `auth.py` | 删除（如不再被引用） |
| `auth.approve_web_bind_code()` | `auth.py` | 删除（如不再被引用） |
| `persistence.get/set/save_web_bind_codes()` | `persistence.py` | 删除（如不再被引用） |

**BIND_TEMPLATE 确认：** 当前登录页面只显示 GitHub OAuth 按钮 ✅ 无需改动。

#### C2 — 优化 GitHub OAuth 流程

| 改进项 | 当前 | 目标 |
|:-------|:-----|:-----|
| 登录按钮文案 | "使用 GitHub 登录" | ✅ 保持 |
| 登录失败提示 | 白页报错 | 改为友好的失败页面 |
| 登录回调 | 重定向到 /chat | ✅ 保持 |
| Token 存储 | cookie 7 天 | ✅ 保持 |

---

---

## 3. 验收标准

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
| ✅-18 | 发送人颜色正确 | bot 颜色与名字对应（小爱金色、小谷红色等） | 手动查看 |

### 🎯 3.3 方向 C：登录入口清理

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-19 | 登录页面只有 GitHub OAuth | 只显示 GitHub 登录按钮 | 打开 /chat |
| ✅-20 | `/api/bind` 返回 404 | 绑定码 API 已删除 | curl /api/bind |
| ✅-21 | `/api/check` 返回 404 | 绑定码检查 API 已删除 | curl /api/check |
| ✅-22 | GitHub OAuth 登录正常 | 可用 GitHub 账号登录并跳转 | 手动测试 |
| ✅-23 | `auth.py` 无绑定码相关函数 | `generate_web_bind_code` 等函数不存在 | grep 源码 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| 收件箱消息输入 | 从 web 端向指定 bot 的 inbox 发消息 | 纯观察窗口，发消息走 TG 或 WS 客户端 |
| 消息搜索改造 | /api/chat/search 兼容收件箱搜索 | 非核心需求，可后续补 |
| 颜色/UI 美化 | 界面风格不变，只改标签和功能 | scope 控制，不改视觉设计 |
| 服务端 handler.py 改动 | 不修改服务端消息路由/存储逻辑 | R82 已完成服务端，本轮只改前端 |
| 服务端部署 | 本轮代码改完后合并 main 部署 | 合入 R82（R82 未合并 main 则 R83 也先不部署） |
| 旧数据归档 (messages.db 备份) | 由运维在部署时单独执行，不在代码改动范围 | 运维操作，非编码工作 |
| Bot 客户端改动 | 不改任何 bot 的代码 | 前端改造不影响 bot |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案（含 B1 诊断 + 所有改动的精确代码变动点） | 20min |
| **3** | 👨‍💻 Dev | 编码实现（标签改造 + 收件箱修复 + API 清理） | 30min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告（浏览器验证 + 端到端） | 20min |
| **6** | 🛠️ Operations | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/templates.py` | **修改** — Tab 架构重写（TAB_STATE + renderTabBar + init + selectTab + 删除 tab2 逻辑） | ~80 行 |
| `server/web_viewer.py` | **修改** — 删除绑定码 API（3 个路由+函数）+ inbox API 修复 | ~40 行 |
| `server/message_store.py` | **可能修改** — LIKE 查询修复（如 H1 验证需要） | ~5 行 |
| **合计** | | **~125 行净改** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| B1 诊断发现根因不在假设树中 | 收件箱修复超出预估 | Arch 在技术方案中先诊断再修复，结果决定实际改动量 |
| Tab 重设计后 poll/WS 事件处理异常 | JS 报错，部分 Tab 不显示消息 | 逐一检查所有 `TAB_STATE` 引用点，确保 3-tab 兼容 |
| Git 合入时机：R82 未合并 main | R83 代码在 dev 上但无法部署 | R83 合入 R82 一起部署，或本轮先改前端代码 |

---

## 6. 脱敏检查清单

- [ ] docs/R83/*.md 零内部名残留
- [ ] `grep -nE '内部名模式' docs/R83/*.md` 零匹配
- [ ] templates.py 中 JS 代码零内部地址/路径泄露
- [ ] web_viewer.py 零内部配置信息泄漏

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:-----|:------|
| v1.0 | 2026-07-10 | 初稿 — 前端 Tab 重设计 + 收件箱修复 + 登录清理 |
