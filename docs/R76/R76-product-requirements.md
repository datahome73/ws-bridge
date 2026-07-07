# R76 产品需求 — Inbox 可视化 + 时间切片归档 📬

> **版本：** v1.0（初稿）
> **状态：** 📝 待审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-08
> **基线：** `892c5c77`（main 最新 — R75 合并部署）
> **本轮改动范围：** `server/web_viewer.py` `server/handler.py` `server/templates.py`
> **参考：** TODO.md

---

## 0. 先验验证：已就绪的基础设施

| 验证项 | 结果 | 确认方式 |
|:-------|:----:|:---------|
| R74/R75 管线稳定运行 | ✅ | R75 合并部署 main `93264e3`，ws-bridge:r75 镜像 |
| inbox 全线双向通 | ✅ | D1 权限修复 + 3651d70，5 bot 回复确认 |
| Web Viewer 基础架构 | ✅ | 4-Tab 架构（大厅/活跃/管理员/历史），WebSocket 实时推送 |
| 消息持久化（message_store） | ✅ | SQLite `messages` 表，含 channel 字段索引 |
| **小结** | ✅ | **基础设施稳固，可以进行前端可视化增强** |

---

## 1. 问题背景

### 1.1 现状

经过 R68→R75 的迭代，收件箱（inbox）通道已实现 bot 之间的点对点私密通信。但在实际开发中发现：

| 问题 | 具体表现 | 严重度 |
|:-----|:---------|:------:|
| **Inbox 消息 Web 端不可见** | 项目负责人只能通过 bot 汇报间接了解 inbox 通信内容，无法直观查阅 | 🔴 P0 |
| **无集中 inbox 查阅入口** | 每个 bot 有独立 `_inbox:{agent_id}` 通道，但 Web UI 没有聚合展示 | 🔴 P0 |
| **开发轮次消息归档不完整** | 关闭工作室后，大厅/管理员/inbox 消息仍堆积在视图中，无时间切片归档机制 | 🟡 P1 |
| **消息时间线分散** | 同一轮次的沟通分散在大厅、管理员、各 inbox 通道中，无法一站式复盘 | 🟡 P1 |

### 1.2 根因分析

| # | 根因 | 说明 |
|:-:|:-----|:------|
| 1 | inbox 设计初始为 bot 通信通道，未考虑可视化 | R68 A2 实现了 inbox 消息的持久化和路由，但前端从未展示 |
| 2 | 无工作轮次概念 | 消息都按频道存储，没有「从创建到关闭」的时间窗口概念 |
| 3 | 无归档/清理状态 | 关闭工作室只标记状态，不触发任何视图清理逻辑 |

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:-----|:------|
| 🔴 **P0 — Inbox 透明化** | 项目负责人要求 inbox 消息在 Web 端可见（需求明确：「把黑盒子揭开」） |
| 🟡 **P1 — 复盘效率** | 按轮次归档后，项目负责人可在历史查看器中一站式查看该轮完整通讯 |
| 🟢 **基础设施就绪** | message_store 已含所有 channel 消息，WebSocket 推送已含 channel 字段，只需前端展示 |

---

## 2. 功能需求

### 设计原则

> **Inbox 可视化：** 所有 bot 的 inbox 消息混合展示，只读查阅，不改变现有收发逻辑。
>
> **时间切片归档：** 视觉层面的过滤——不改数据库，只影响 Web 端显示范围。

---

### 方向 A（核心 — P0）：Inbox Tab 混合展示

#### A1 — 后端：Inbox 聚合 API

新增 `GET /api/chat/inbox` 接口（需 token 验证）：

- 查询 `messages` 表中所有 `channel LIKE '_inbox:%'` 的消息
- 按 `ts` 降序排列返回最新 N 条（默认 50）
- 对每条消息，解析 `_inbox:{agent_id}` 反查出接收人显示名
- 返回格式：

```json
{
  "messages": [
    {
      "ts": 1749200000.0,
      "from_name": "需求分析师",
      "to_name": "架构师",
      "to_agent": "ws_xxxxxxxxxxxx",
      "content": "R76的技术方案请评估一下"
    }
  ]
}
```

实现位置：`server/web_viewer.py` — 新增 `handle_api_inbox()` 处理函数 + 注册路由

#### A2 — 前端：Inbox Tab

在 `CHAT_TEMPLATE` 的 Tab bar 中新增第 5 个固定 Tab：

| 属性 | 值 |
|:-----|:----|
| Tab ID | `tab5` |
| 图标+标签 | **「📬 收件箱」** |
| 排序 | 置于「🔧 管理员」和「🗂️ 历史查看器」之间 |
| 行为 | 选择时调用 `GET /api/chat/inbox` 加载消息 |
| 只读 | 无输入框，纯展示 |
| 未读提示 | WebSocket 收到 `_inbox:*` 频道消息 → 收件箱 Tab 显示未读红点计数 |

#### A3 — 消息渲染格式

Inbox 消息的显示格式与普通消息不同——需要同时显示发送人和接收人：

```
┌──────────────────────────────────────────────┐
│ [14:23] 需求分析师 → 架构师                   │
│ R76的技术方案请评估一下                        │
├──────────────────────────────────────────────┤
│ [14:25] 架构师 → 需求分析师                   │
│ 已评估，详见docs/R76/R76-tech-plan.md         │
└──────────────────────────────────────────────┘
```

- 发送人颜色沿用当前 `colorMap` 规则
- 接收人显示在 `→` 之后，使用不同样式（灰色或下划线）以示区分
- 仅 inbox Tab 内的消息使用此格式；其他 Tab 不变

#### A4 — WebSocket 实时推送

现有 `write_chat_log()` 和 WS 推送逻辑不变。前端新增处理：

- WS 消息 `channel` 以 `_inbox:` 开头时 → 追加到 inbox 消息缓冲区
- 当前 Tab 是 inbox → 直接渲染
- 当前 Tab 不是 inbox → inbox Tab 显示未读红点

---

### 方向 B（P1 — 核心）：时间切片归档

#### B1 — 归档标记

新增全局状态 `last_archive_ts`：

- 当最后一个活跃工作室被关闭（`!close_workspace`）时触发
- 记录该时刻的时间戳 `last_archive_ts = now()`
- 写入全局持久化存储（可存放在 `config.DATA_DIR/_archive_state.json`）

状态数据结构：

```json
{
  "last_archive_ts": 1749286400.0,
  "archived_workspaces": [
    {
      "id": "ws_xxx-R76-dev",
      "name": "R76-dev",
      "created_at": 1749200000.0,
      "closed_at": 1749286400.0,
      "archive_window": {
        "start": 1749200000.0,
        "end": 1749286400.0
      }
    }
  ]
}
```

#### B2 — 活跃工作室存在时的显示

**有活跃工作室时，各 Tab 显示行为不变：**

| Tab | 行为 | 说明 |
|:----|:-----|:------|
| 🌐 大厅 | `GET /api/chat?channel=lobby` | 显示全部（无 since 过滤） |
| 📋 活跃 | workspace channel 消息 | 现有行为 |
| 🔧 管理员 | 显示全部 | 无 since 过滤 |
| 📬 收件箱 | 显示全部 inbox 消息 | 混合展示，无时间过滤 |
| 🗂️ 历史查看器 | 只显示点选的 workspace channel 消息 | 现有行为 |

#### B3 — 无活跃工作室时的显示

**所有活跃工作室关闭后，各 Tab 行为变为：**

| Tab | 行为 | 说明 |
|:----|:-----|:------|
| 🌐 大厅 | `GET /api/chat?channel=lobby&since=last_archive_ts` | 只显示归档后的新消息 |
| 🔧 管理员 | `GET /api/chat?channel=_admin&since=last_archive_ts` | 只显示归档后的新消息 |
| 📬 收件箱 | `GET /api/chat/inbox&since=last_archive_ts` | 只显示归档后的新消息 |
| 🗂️ 历史查看器 | 点击已归档 workspace → 调用新 API 获取 **该时间窗口内所有 channel** 的消息 | 全量查看 |

**视觉效果：** 各 Tab 清空为「暂无消息」状态→等待新的工作室消息产生。

#### B4 — 历史查看器增强

新增 `GET /api/chat/archive?workspace_id=xxx` 接口：

- 查询 `_archive_state.json` 中对应 workspace 的 `archive_window`
- 返回该时间窗口内 `[start, end]` 的所有 channel 消息
- 消息按 ts 排序，每条消息携带 `channel` 来源标记

返回格式：

```json
{
  "workspace": "R76-dev",
  "period": { "start": 1749200000.0, "end": 1749286400.0 },
  "messages": [
    {
      "ts": 1749200100.0,
      "from_name": "需求分析师",
      "content": "R76正式启动",
      "channel": "lobby",
      "_channel_label": "大厅"
    },
    {
      "ts": 1749201000.0,
      "from_name": "需求分析师",
      "to_name": "架构师",
      "content": "技术方案开始",
      "channel": "_inbox:ws_xxxxxxxxxxxx",
      "_channel_label": "收件箱（架构师）"
    }
  ],
  "total": 342
}
```

前端历史查看器渲染时，每个消息旁显示 `_channel_label` 标签（如「大厅」「管理员」「收件箱（架构师）」），方便项目负责人追踪消息来源。

#### B5 — 新工作室创建后

当有新的活跃工作室被创建时：

- `last_archive_ts` 全局状态重置（或保持不变但不影响——since 参数始终有效）
- 各 Tab 恢复到「有活跃工作室」的显示模式
- 新的消息在干净的视图中开始积累

#### B6 — 不纳入范围

| 事项 | 说明 |
|:-----|:------|
| 物理删除数据库消息 | 不改 message_store 表的 DELETE 逻辑 |
| 归档文件导出下载 | 本轮不实现归档文件的下载/导出功能 |
| inbox 的发送功能 | inbox Tab 只读，不发消息 |
| inbox 按 bot 筛选 | 需求明确「混在一起就好，不需要按 bot 分类」 |

---

## 3. 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/web_viewer.py` | 新增 `handle_api_inbox()` + `handle_api_archive()` + 路由注册 | ~60 行 |
| `server/web_viewer.py` | 修改 `!close_workspace` 触发处写入归档状态 | ~15 行 |
| `server/web_viewer.py` | `handle_api_chat()` 扩展 `since` 参数支持 | ~10 行 |
| `server/web_viewer.py` | 新增 `_archive_state` 读写函数 | ~30 行 |
| `server/handler.py` | 关闭工作室时通知前端触发归档标记 | ~10 行 |
| `server/templates.py` | 新增 inbox Tab + 收件箱渲染逻辑 + WS 处理 | ~80 行 |
| `server/templates.py` | 历史查看器增强（归档全 channel 展示） | ~40 行 |
| `server/auth.py` 或 `persistence.py` | 新增 agent_id → 显示名映射查询函数（收件人解析用） | ~10 行 |
| **合计** | | **~255 行净增** |

---

## 4. 验收标准

### 🎯 方向 A — Inbox Tab

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 新增 `/api/chat/inbox` 返回 inbox 聚合消息 | 含 `from_name` `to_name` `content` `ts` 字段，按 ts 降序 | curl 验证 |
| ✅-2 | 无 token 访问返回 401 | `{"error": "unauthorized"}` | curl 无 token |
| ✅-3 | Web 端显示 📬 收件箱 Tab | Tab bar 可见第 5 个 Tab | 浏览器查看 |
| ✅-4 | 点击 inbox Tab 加载消息 | 显示来自各 bot inbox 的混合消息列表，含发送人→接收人 | 浏览器操作 |
| ✅-5 | Inbox 消息格式正确 | `[时间] 发送人 → 接收人: 内容` | 浏览器验证 |
| ✅-6 | WS 推送 inbox 消息时显示未读红点 | inbox Tab 显示红色数字 | 在两标签页下测试 |
| ✅-7 | Inbox Tab 无输入框 | 页面底部无输入区域 | 浏览器验证 |

### 🎯 方向 B — 时间切片归档

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-8 | 关闭最后活跃工作室后，大厅/管理员/inbox 变干净 | 各 Tab 显示「暂无消息」 | 关闭工作室后刷新 Web |
| ✅-9 | 新增 `/api/chat/archive?workspace_id=xxx` | 返回该时间窗口内所有 channel 消息 | curl 验证 |
| ✅-10 | 历史查看器点击已归档 workspace | 显示该轮次全部消息（大厅+管理员+inbox+工作室），每条带 channel 来源标签 | 浏览器操作 |
| ✅-11 | 创建新工作室后各 Tab 恢复正常 | Tab 开始显示新消息 | 创建工作室后刷新 |
| ✅-12 | `since` 参数按预期过滤 | `GET /api/chat?channel=lobby&since=T` 只返回 T 之后的消息 | curl 验证 |

---

## 5. 管线计划（6 步接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | ☕ PM | WORK_PLAN.md | 10min |
| **2** | 👷 架构师 | 技术方案 — 代码改动设计 + 状态机 | 20min |
| **3** | 👨‍💻 开发工程师 | 编码实现 — 后端 + 前端改动 | 40min |
| **4** | 👀 审查工程师 | 审查 — 代码质量 + 安全性 | 15min |
| **5** | 🦐 测试工程师 | 测试 — 功能验收全场景 | 15min |
| **6** | 🛠️ 项目管理 | 合并部署 + TODO.md 更新 | 10min |

---

## 6. 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| Inbox 消息反查接收人名时 agent_id 不在 auth 表中 | 接收人显示为 agent_id（`ws_xxx`） | 回退到 `_r72_users` 查询；最坏情况显示 agent_id 前 12 位 |
| 大量 inbox 消息导致 API 响应慢 | 前端加载缓慢 | 默认 limit=50，支持分页（`offset` 参数） |
| 归档时间窗口跨多轮次 | 消息可能重复出现在多个归档中 | 每个 workspace 独立时间窗口，不重叠 |
| 同时关闭多个工作室时竞争条件 | `last_archive_ts` 可能只记录最后一个 | 写操作加锁，顺序执行 |

---

## 7. 脱敏检查清单

- [ ] 本文件（R76-product-requirements.md）零内部角色名残留
- [ ] 使用通用角色名（需求分析师 / 架构师 / 开发工程师 / 审查工程师 / 测试工程师 / 项目管理 / 项目负责人）
- [ ] 无内部域名/IP/SSH 信息
- [ ] 无 agent_id 原始值残留
- [ ] `grep -nE '(小[谷爱开周]|爱泰|泰虾|大宏)' docs/R76/` → exit=1

---

## 8. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-08 | 初稿 — R76 Inbox 可视化 + 时间切片归档。方向 A Inbox Tab 混合展示（P0）+ 方向 B 时间切片归档（P1） |
