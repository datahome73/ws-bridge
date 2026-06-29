# R52 技术方案 — 去掉 Web 端 📊 进度 Tab

> **版本：** v1.0
> **状态：** ⏳ 待方向审查
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-29
> **基于需求：** [R52-product-requirements.md v1.0 ✅](./R52-product-requirements.md)

---

## Part A — 方案设计

### 架构图

本轮改动仅在 `server/templates.py` 的单页面 HTML/JS 中进行，无后端 API 变更，无 handler.py 变更。

```
templates.py (CHAT_TEMPLATE)
│
├── JS 变量区
│   ├── TAB_STATE          → ① 删除 tab5 条目
│   └── STATE_ICONS        → ⭐ 顺便删除（仅被 renderProgressTab 引用）
│
├── renderTabBar()         → ② 删除 tab5 按钮渲染
│
├── selectTab()            → ③ 删除 tab5 分支
│
├── renderProgressTab()    → ④ 删除整个函数 + STATE_ICONS
│
├── init()
│   └── connectWS()
│       └── onmessage      → ⑤ 删除 task_notify 分支
│   └── 30s 轮询           → ⑥ 删除 setInterval 块
│
└── 注释更新               → 调整 renderTabBar 头部注释 (5-tab→4-tab)
```

### ① — TAB_STATE 删除 tab5（L173-L174）

**位置：** `server/templates.py:173-174`

**操作：** 删除以下 2 行

```js
  // R38: task progress tab
  tab5: { id: 'tab5', channel: '_progress',    label: '📊 进度',     permanent: true,  visible: true },
```

**影响：** 删除后 `TAB_STATE` 只有 `tab1/tab2/tab4/tab3` 四个条目。`tab3`（历史查看器）的 `tab3` 键名保持不变。

**⭐ 顺便清理：** 删除 `STATE_ICONS` 对象（L449-452），该常量仅被 `renderProgressTab()` 引用（L510），删除函数后即为死代码。

```js
const STATE_ICONS = {
  'submitted': '⬜', 'working': '▶', 'completed': '✅',
  'failed': '❌', 'canceled': '⛔', 'input_required': '🟡',
};
```

### ② — renderTabBar() 删除 tab5 按钮（L259-261）

**位置：** `server/templates.py:259-261`

**操作：** 删除以下 3 行

```js
  // R38: Tab 5 — 📊 进度 (always) — W-6: fourth
  html += '<div class="tab' + (activeTabId === 'tab5' ? ' active' : '') + '" data-tab="tab5" onclick="selectTab(\\'tab5\\')">' +
    '📊 进度</div>';
```

**影响：** 删除后剩下的 Tab 按 L251-257（大厅→管理员）→ L263-266（历史查看器）的顺序排列。历史查看器（tab3）的注释 `W-6: last` 仍然准确。

**同时更新 renderTabBar 头部注释：** L239 从 `5-tab` 改为 `4-tab`

```js
// ── R20/R35/R38: Fixed 4-tab rendering (active | lobby | admin | history) ──
```

### ③ — selectTab() 删除 tab5 分支（L287-289）

**位置：** `server/templates.py:287-289`

**操作：** 删除以下 3 行

```js
  } else if (tabId === 'tab5') {
    renderProgressTab();
  }
```

**影响：** `selectTab()` 中的 if/else 链变为：
- 有 `tab.channel` → `loadMessages()`（tab1/tab2/tab4）
- `tabId === 'tab3'` → 历史查看器占位
- 无其他分支（tab5 不复存在）

**注意：** `tabId === 'tab3'` 的 else-if 后面没有 else 分支是安全的 — 所有剩余的 `tabId` 要么有 channel（走第一个 if），要么是 `tab3`。不需要额外的兜底处理。

### ④ — renderProgressTab() 函数删除（L454-525）

**位置：** `server/templates.py:454-525`

**操作：** 删除整个函数（L454-525），包含：

- 函数声明 `async function renderProgressTab() {`
- 获取 `_admin` 频道消息（`fetch('/api/chat?channel=_admin')`）
- 过滤 `📊` 前缀消息
- 按 context_id 分组 + 去重
- 渲染 HTML 表格 + 自动刷新提示
- 错误处理

共约 72 行。

### ⑤ — WebSocket onmessage 删除 task_notify 分支（L589-594）

**位置：** `server/templates.py:589-594`

**操作：** 删除以下 6 行

```js
        // R38: MSG_TASK_NOTIFY — refresh progress tab if visible
        if (data.type === 'task_notify') {
          if (activeTabId === 'tab5') {
            renderProgressTab();
          }
        }
```

**影响：** WebSocket 收到 `task_notify` 消息后不再触发前端刷新。后端 `_broadcast_task_notify()` 继续发送该消息 — 仅 Web 端不再消费它。

### ⑥ — 30s 轮询删除（L630-635）

**位置：** `server/templates.py:630-635`

**操作：** 删除以下 6 行

```js
  // R38: Poll progress tab every 30s (W-4)
  setInterval(async function() {
    if (activeTabId === 'tab5') {
      try { renderProgressTab(); } catch(_) {}
    }
  }, 30000);
```

**影响：** 移除了唯一一个每 30 秒触发 `renderProgressTab()` 的定时器。其他轮询（5s 消息轮询 L614-628、15s 工作室轮询 L638+）不受影响。

---

### 涉及文件、改动行号汇总

| 文件 | 改动 | 预计 +/- |
|:-----|:-----|:--------:|
| `server/templates.py` | 删除 6 处代码块 + 1 处死代码清理 + 1 处注释更新 | −92 / +1 |

---

### 不涉及的组件

| 组件 | 原因 |
|:-----|:------|
| `handler.py` | PRD §5 明确不修改后端逻辑 |
| `__main__.py` | 仅前端改动 |
| `shared/protocol.py` | `_progress` 频道只是 JS 中的一个字符串常量，不是 protocol 常量 |
| `config.py` | 无配置变更 |
| CSS 样式 | 进度 Tab 使用通用 `.tab` 类，无专用 CSS 选择器 |

---

## Part B — 向后兼容分析

| 已有功能 | 影响 | 说明 |
|:---------|:----|:------|
| `!pipeline_status` 工作室命令 | ✅ 不受影响 | 完全在 handler.py 中处理，前端不参与 |
| `_broadcast_task_notify()` | ✅ 不受影响 | 后端继续发送，仅 Web 不再渲染 | 
| 其他 4 个 Tab（大厅/活跃/管理员/历史查看器） | ✅ 不受影响 | TAB_STATE 中 tab1/tab2/tab4/tab3 均未改动 |
| Tab 导航 localStorage 状态 | ✅ 兼容 | tab3/tab4 ID 保持不变；用户如果之前选中 tab5，localStorage 存的是 `tab5`，刷新后 selectTab('tab5') 会因 TAB_STATE 中无 tab5 而无效——这会在 init() 的默认 Tab 选择逻辑中被 `selectTab(firstTab)` 覆盖，不会报错 |
| 历史查看器（tab3） | ✅ 不受影响 | `switchHistoryTab()` 始终用 `selectTab('tab3')`，无 tab5 引用 |

### localStorage `activeTabId: 'tab5'` 历史遗留处理

用户之前选中过进度 Tab，其 `activeTabId` 可能以某种形式缓存在 localStorage 中。但当前代码中 **init() 始终使用 `selectTab(firstTab)`**（L574）覆盖启动时的 Tab 状态，因此即使有历史 localStorage 值，也不会因为 tab5 不存在而出错。不需要额外的向前兼容代码。

---

## Part C — 验收标准映射

| # | 验收标准 | 覆盖位置 | 验证方式 | 优先级 |
|:-:|:---------|:---------|:---------|:------:|
| V-1 | Web 顶部 Tab 栏不再显示「📊 进度」Tab | ② renderTabBar() tab5 删除 | 刷新 Web 页面，Tab 栏只有 4 个 | P0 |
| V-2 | 其余 4 个 Tab 功能正常 | ① TAB_STATE 保留条目 + 无其他改动 | 逐一点击各 Tab，消息加载正常 | P0 |
| V-3 | 切换 Tab 控制台无 JS 错误 | ③ selectTab() 分支删除 + ④/⑤/⑥ 无残留引用 | 浏览器 Console 检查 | P0 |
| V-4 | `!pipeline_status` 在工作室正常输出 | 不涉及（后端无改动） | 工作室内执行 `!pipeline_status` | P0 |
| V-5 | JS 控制台无 `renderProgressTab is not defined` 等残留引用报错 | ④ 函数 + ⑤ onmessage + ⑥ 轮询全部删除 | 刷新后等 30s+，Console 无进度 Tab 相关错误 | P0 |
| V-6 | Tab 栏排序正确（无活跃时：大厅→管理员→历史；有活跃时：活跃→大厅→管理员→历史） | ② 删除后顺序由 L246-266 现有逻辑保证 | 视觉确认顺序 | P1 |

---

## 附录

### A. 代码变更汇总

| 文件 | # | 位置 | 类型 | 说明 |
|:-----|:-:|:----|:----|:------|
| `templates.py` | ① | L173-174 | 删除 | TAB_STATE tab5 条目 + 注释 |
| `templates.py` | ①⭐ | L449-452 | 删除 | STATE_ICONS 常量（死代码） |
| `templates.py` | ② | L259-261 | 删除 | renderTabBar() tab5 按钮 |
| `templates.py` | ② | L239 | 修改 | 注释 5-tab→4-tab |
| `templates.py` | ③ | L287-289 | 删除 | selectTab() tab5 分支 |
| `templates.py` | ④ | L454-525 | 删除 | renderProgressTab() 完整函数 |
| `templates.py` | ⑤ | L589-594 | 删除 | onmessage task_notify 分支 |
| `templates.py` | ⑥ | L630-635 | 删除 | 30s 轮询 setInterval |

**合计：** 删除约 92 行，修改 1 行注释，零新增行。

### B. 双入口同步检查

| 入口 | 需要同步？ | 理由 |
|:-----|:----------|:------|
| `handler.py::handler()` | ❌ 不需要 | 纯前端 JS 删除，无后端消息处理逻辑变更 |
| `__main__.py::ws_handler()` | ❌ 不需要 | 同上 |

### C. 脱敏检查

| 检查项 | 结果 |
|:-------|:-----|
| 内部角色姓名 | ✅ 已使用角色名（架构师/需求分析师/开发工程师/审查工程师/测试工程师/管理员/项目负责人）替代内部姓名 |
| 代码中的角色引用 | ✅ 删除点和注释只使用角色名和 emoji |

> **本技术方案交付后，待 🧐 需求分析师方向审查确认后由 💻 开发工程师编码实现。**
