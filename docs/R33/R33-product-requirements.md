# R33 产品需求 — Web 端下拉刷新 Tab 丢失修复

> **版本：** v0.1（草稿，待项目负责人审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-06-23
> **本轮改动范围：** 仅 Web 端（第④类，`server/templates.py`）

---

## 1. 背景与痛点

### 1.1 问题描述

Web 聊天室在进入工作群（workspace）后，正常显示 3 个 Tab：

| Tab | 内容 |
|:---|:-----|
| 🌐 大厅 | 公共频道（常驻） |
| 📋 活跃 | 当前活跃的工作群（动态） |
| 🗂️ 历史查看器 | 归档工作组查阅（常驻） |

用户执行**下拉刷新（或 F5 页面刷新）**后，📋 活跃 Tab 消失，页面回退到仅 2 个 Tab（大厅 + 历史查看器）。需要用户手动在右侧工作群面板中点击活跃工作群才能恢复。

### 1.2 用户旅程

```
初始条件：Web 端已进入工作群（有活跃 workspace），显示 3 Tab

① 用户下拉刷新页面
② ❌ Tab 栏回退到 2 Tab（活跃工作群 Tab 丢失）
③ 用户需要手动找到右侧工作群面板 → 点击活跃工作群 → Tab 恢复
④ ✅ 期望：刷新只刷新消息内容，Tab 状态保持

复现条件：任何有活跃工作群的环境
```

### 1.3 影响范围

- **所有使用 Web 聊天室的成员** — 下拉刷新/页面重载后均受影响
- **工作群频繁切换的场景** — 每次进入新工作群后刷新都丢失

---

## 2. 当前代码逻辑分析

### 2.1 Tab 状态模型（`server/templates.py`）

Web 端使用固定 3-slot 架构：

```javascript
const TAB_STATE = {
  tab1: { id: 'tab1', channel: 'lobby',       label: '🌐 大厅',     permanent: true,  visible: true },
  tab2: { id: 'tab2', channel: null,           label: '📋 活跃',     permanent: false, visible: false },
  tab3: { id: 'tab3', channel: null,           label: '🗂️ 历史查看器', permanent: true,  visible: true },
};
let activeTabId = 'tab1';
```

Tab 状态完全由内存中的 `TAB_STATE` 对象管理，**无持久化存储**。页面刷新后全部重置为默认值。

### 2.2 初始化流程（`init()` ~line 389）

```
init()
  ├── 0. fetch('/api/workspaces')      ← 异步获取工作群列表
  │     └── 有活跃工作群 → 设置 tab2.channel + visible = true
  ├── 1. renderTabBar()                ← 渲染 Tab 栏
  ├── 2. loadMessages('lobby')         ← 加载大厅消息
  ├── 3. connectWS()                   ← 建立 WebSocket
  ├── 4-7. 定时轮询（polling fallback、工作群变更、成员状态）
```

### 2.3 根因分析

**问题 A：初始化工作群 API 调用可能失败**

`init()` 中 `fetch('/api/workspaces')` 被 `try/catch` 包裹，失败时静默吞异常。若 API 请求失败或返回空列表（部署重置/时序竞争），tab2 保持 `{channel: null, visible: false}`，后续无重试机制将 tab2 激活。

**问题 B：15s 轮询检测到活跃工作群但不设置 tab2 状态**

line 473-475 的判读分支：

```javascript
} else if (activeIds.length > 0 && !TAB_STATE.tab2.channel) {
  // New active workspace appeared and Tab2 is empty → refresh tab bar
  renderTabBar();
}
```

此分支检测到「存在活跃工作群，但 tab2 无 channel」，却**只调用 `renderTabBar()` 未设置 `TAB_STATE.tab2` 的实际状态**。由于 tab2 的 channel 仍为 `null`、visible 仍为 `false`，`renderTabBar()` 渲染结果依然是 2 个 Tab。

**问题的实质**：Tab 状态是内存对象，页面刷新丢失。而恢复机制的 2 条路径（`init()` 的 API 获取 + 15s 轮询）都存在缺陷，导致恢复失败。

---

## 3. 验收标准

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| A-1 | 有活跃工作群时，页面刷新后 📋 活跃 Tab 保持显示，无需手动恢复 | P0 |
| A-2 | 刷新后活跃 Tab 的消息内容正确加载（显示该工作群最新消息） | P0 |
| A-3 | 无活跃工作群时，页面刷新后仍为 2 Tab（大厅 + 历史查看器），不出现空白 Tab | P0 |
| A-4 | 工作群归档后，📋 活跃 Tab 自动隐藏（不影响现有归档逻辑） | P0 |
| A-5 | 同时存在多个活跃工作群时，行为正确（仅显示第一个或保持刷新前的那个） | P1 |
| A-6 | 离线/API 异常场景下降级正常（刷新后 Tab 不显示，但不阻塞页面加载） | P2 |

---

## 4. 修复方向建议

> **说明：** 以下为推荐实现方向，具体方案由架构师在技术方案中确定。

**方案 A：localStorage 持久化（推荐）**

- 在 `switchToActiveTab()` 中将 tab2 状态（channel + label）写入 `localStorage`
- 在 `init()` 中优先从 `localStorage` 恢复 tab2，再通过 API 刷新验证
- 在工作群归档/切换时同步更新 `localStorage`

**优势：** 页面刷新后即时恢复（不依赖 API），初始化即可显示 3 Tab

**方案 B：修复轮询分支**

- 将 line 473-475 的 `renderTabBar()` 改为调用 `switchToActiveTab(activeWs[0].id, activeWs[0].name)`
- 同时修复 `init()` 中 API 失败的降级

**优势：** 改动量小，不增加持久化逻辑

**方案 C：组合方案**

- localStorage 持久化 tab2 状态 + 轮询保底恢复
- 最健壮，覆盖所有场景（API 正常/失败/时序竞争）

---

## 5. 不改的内容

| 事项 | 原因 |
|:----|:-----|
| 其他 Tab（tab1 大厅、tab3 历史）的持久化 | 大厅和历史查看器无动态状态丢失问题 |
| Web 端其他功能增强 | 仅修复 Tab 丢失 Bug |
| 服务端代码改动 | 问题纯在 Web 前端 JS 逻辑中，无需改 handler/API |
| Web 端 CSS/样式调整 | 不属本轮范围 |

---

## 6. 开放问题

| # | 问题 | 建议 | 决策者 |
|:-:|:-----|:-----|:------|
| 1 | 多个活跃工作群时，刷新后恢复哪个？ | 恢复刷新前所在的那个（localStorage 存 activeTabId） | 项目负责人 |
| 2 | localStorage 是否需清理过期数据？ | `tab2.channel` 在 API 验证时确认有效，无效则清 | 项目负责人 |

---

## 7. 验收检查表

| # | 验收项 | 类型 | 状态 |
|:-:|:------|:----:|:----:|
| A-1 | 刷新后活跃 Tab 保持显示 | P0 | ⬜ |
| A-2 | 刷新后活跃 Tab 消息正确加载 | P0 | ⬜ |
| A-3 | 无活跃工作群时仍为 2 Tab | P0 | ⬜ |
| A-4 | 工作群归档后 Tab 自动隐藏 | P0 | ⬜ |
| A-5 | 多活跃工作群场景行为正确 | P1 | ⬜ |
| A-6 | API 异常时降级正常 | P2 | ⬜ |

---

> **审核记录：**
> - v0.1 提交审核：2026-06-23
> - 项目负责人审核意见：
> - 结论：
