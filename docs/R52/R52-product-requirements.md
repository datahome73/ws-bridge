# R52 产品需求 — 去掉 Web 端 📊 进度 Tab

> **版本：** v0.1（草稿，待审核）
> **状态：** 📋 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-06-29
> **本轮改动范围：** 仅第④类（Web 端，`server/templates.py`）

---

## 1. 问题背景

R41 修复了 F-10（进度 Tab 空白：`_broadcast_task_notify()` 写入 `_admin` 频道的 chat log），Web 端进度 Tab 开始能显示管线进度数据。

但自 R49 起，`!pipeline_status` 已能在工作室中自然输出管线进度卡片——包含 Step 名称、状态、产出链接等信息，且随管线流转实时更新。`📊` 进度 Tab 提供了相同的功能，但数据来源是 `_admin` 频道的 task_notify 协议消息，不直观且需等待 30s 轮询刷新。

**核心判断：** `!pipeline_status` 已在工作室中完整覆盖了进度展示需求，进度 Tab 成为**多余功能**。保留它增加了前端代码复杂度（200+ 行 JS + 30s 轮询 + WebSocket 事件处理），且无人使用。

---

## 2. 需要移除的内容

进度 Tab 的实现完全在 `server/templates.py` 的单页面 HTML/JS 中，无独立后端 API。需要移除的代码块：

| # | 位置（行号） | 内容 | 说明 |
|:-:|:------------|:-----|:-----|
| ① | TAB_STATE 定义 (~L174) | `tab5: { id: 'tab5', channel: '_progress', label: '📊 进度', permanent: true, visible: true }` | 移除 tab5 定义，相邻 tab 的 ID 不变 |
| ② | `renderTabBar()` (~L259-261) | 渲染「📊 进度」Tab 按钮的 HTML 代码块 | 移除进度 Tab 按钮，其余 Tab 排序不变 |
| ③ | `selectTab()` (~L287-289) | `else if (tabId === 'tab5') { renderProgressTab(); }` 分支 | 移除对 tab5 的特殊处理 |
| ④ | `renderProgressTab()` 函数 (~L454-525) | 完整的函数定义，包含：获取 `_admin` 频道数据 → 过滤 `📊` 前缀 → 分组渲染表格 → 30s 自动刷新提示 | 整个函数删除 |
| ⑤ | WebSocket `onmessage` (~L589-593) | `data.type === 'task_notify'` 时刷新进度 Tab 的代码 | 移除该分支 |
| ⑥ | 30s 轮询 (~L630-635) | `setInterval` 每 30s 调用 `renderProgressTab()` 的代码块 | 移除该轮询 |

### 向后兼容说明

- ⚠️ tab5 的定义虽然整体删除，但**相邻 tab 的 `tab3`/`tab4` ID 保持不变**，避免 localStorage 中可能存储的导航状态错乱
- `!pipeline_status` 在工作室中正常工作，不受任何影响
- `_broadcast_task_notify()` 在 `handler.py` 中继续正常运行（移除前端不会影响后端协议消息），保持向后兼容性

---

## 3. 用户体验变化

| 状态 | 变化 |
|:----|:-----|
| **移除前** | Web 端顶部 Tab 栏共 5 个 Tab（有活跃工作室时）：📋 活跃 / 🌐 大厅 / 🔧 管理员 / 📊 进度 / 🗂️ 历史查看器 |
| **移除后** | Web 端顶部 Tab 栏变为 4 个 Tab（有活跃工作室时）：📋 活跃 → 🌐 大厅 → 🔧 管理员 → 🗂️ 历史查看器 |
| **功能替代** | 用户如需查看管线进度，在工作室（Tab 2）中使用 `!pipeline_status` 命令获取即时进度卡片 |
| **数据完整性** | `_admin` 频道的 `📊` 前缀消息仍正常写入和存储，Web `/api/chat?channel=_admin` 仍可查询到，仅前端不再渲染独立进度 Tab |

---

## 4. 验收标准

| # | 验收标准 | 验证方法 |
|:-:|:---------|:---------|
| V-1 | Web 端顶部 Tab 栏不再显示「📊 进度」Tab | 刷新 Web 页面，确认 Tab 栏只有 4 个 Tab |
| V-2 | 其余 4 个 Tab（大厅/活跃/管理员/历史查看器）功能正常 | 逐一点击各 Tab，确认消息加载正确 |
| V-3 | 切换 Tab 时控制台无 JavaScript 错误 | 打开浏览器开发者工具 Console，切换各 Tab 检查无异常 |
| V-4 | `!pipeline_status` 在工作室中正常输出进度卡片（不受影响） | 在工作室内执行 `!pipeline_status`，确认返回 📊 进度表格 |
| V-5 | JS 控制台无 `renderProgressTab is not defined` 等残留引用报错 | 刷新页面后等待 30s+，确认无进度 Tab 相关的 JS 错误 |
| V-6 | Tab 栏排序正确（无活跃工作室时：🌐 大厅 → 🔧 管理员 → 🗂️ 历史查看器；有活跃工作室时：📋 活跃 → 🌐 大厅 → 🔧 管理员 → 🗂️ 历史查看器） | 确认视觉顺序正确 |

---

## 5. 不纳入本次需求

- ❌ 不修改 `handler.py` 中的 `_broadcast_task_notify()` 逻辑（后端继续正常工作）
- ❌ 不修改 Web 端其他 Tab 的布局或功能
- ❌ 不做性能优化（如消除 30s 轮询的残留）
- ❌ 不调整 Tab 的 `permanent`/`visible` 属性体系

---

> **技术方案（具体方式）由架构师决定。**
