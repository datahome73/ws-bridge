# R33 产品需求 — Web 端体验修复（Tab 丢失 + 部署登出 + 历史错乱）

> **版本：** v0.2（草稿，待项目负责人审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-06-23
> **本轮改动范围：** 仅 Web 端（第④类，`server/templates.py`、`server/web_viewer.py`）

---

## 1. 背景与痛点

### 1.1 Bug A — 下拉刷新活跃 Tab 丢失

Web 聊天室在进入工作群（workspace）后，正常显示 3 个 Tab：

| Tab | 内容 |
|:---|:-----|
| 🌐 大厅 | 公共频道（常驻） |
| 📋 活跃 | 当前活跃的工作群（动态） |
| 🗂️ 历史查看器 | 归档工作组查阅（常驻） |

用户执行**下拉刷新（或 F5 页面刷新）**后，📋 活跃 Tab 消失，页面回退到仅 2 个 Tab（大厅 + 历史查看器）。需要用户手动在右侧工作群面板中点击活跃工作群才能恢复。

**用户旅程：**
```
初始条件：Web 端已进入工作群（有活跃 workspace），显示 3 Tab

① 用户下拉刷新页面
② ❌ Tab 栏回退到 2 Tab（活跃工作群 Tab 丢失）
③ 用户需要手动找到右侧工作群面板 → 点击活跃工作群 → Tab 恢复
④ ✅ 期望：刷新只刷新消息内容，Tab 状态保持

复现条件：任何有活跃工作群的环境
```

### 1.2 Bug B — 上线部署后 Web 端登出

每次服务端上线部署（容器重建/重启）后，Web 聊天室回退到绑定码页面，用户需要：

1. 重新生成绑定码
2. 等待管理员审批
3. 重新登录才能看到聊天界面

**用户旅程：**
```
初始条件：用户已登录 Web 聊天室，正常使用

① 服务端部署新版本（docker-compose build + up -d）
② ❌ Web 端显示绑定码页面，原先的聊天界面丢失
③ 用户需重新绑定 → 管理员审批 → 重新登录
④ ✅ 期望：部署后 Web 会话保持有效，无需重新绑定

复现条件：每次部署/容器重启
```

### 1.3 Bug C — 重新登录后历史工作群错乱

即使重新绑定成功进入聊天室，「🗂️ 历史查看器」Tab 有时显示异常：

- 某些已归档工作群在列表中不显示
- 点开历史工作群后消息列表为空（看不到历史聊天记录）
- 偶发性工作群列表与实际情况不一致

**用户旅程：**
```
初始条件：部署后用户重新绑定登录成功

① 用户点击「🗂️ 历史查看器」Tab
② ❌ 部分归档工作群没有显示在列表中
③ 用户手动在右侧面板点击历史工作群
④ ❌ 消息列表显示为空（"暂无消息"）
⑤ ✅ 期望：所有已归档工作群可见，历史消息可正常加载

复现条件：部署后重新绑定，偶发
```

### 1.4 影响范围

- **Web 端所有用户** — 三个 Bug 影响所有使用 Web 聊天室的成员
- **部署流程** — Bug B 使每次部署都需要人工介入恢复 Web 会话
- **工作群历史查阅** — Bug C 导致无法回溯已完成的工作群讨论记录

---

## 2. 当前代码逻辑分析

### 2.1 Bug A — Tab 状态模型（`server/templates.py`）

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

#### 2.1.1 初始化流程（`init()` ~line 389）

```
init()
  ├── 0. fetch('/api/workspaces')      ← 异步获取工作群列表
  │     └── 有活跃工作群 → 设置 tab2.channel + visible = true
  ├── 1. renderTabBar()                ← 渲染 Tab 栏
  ├── 2. loadMessages('lobby')         ← 加载大厅消息
  ├── 3. connectWS()                   ← 建立 WebSocket
  ├── 4-7. 定时轮询（polling fallback、工作群变更、成员状态）
```

#### 2.1.2 根因

**问题 A1：初始化工作群 API 调用可能失败**

`init()` 中 `fetch('/api/workspaces')` 被 `try/catch` 包裹，失败时静默吞异常。若 API 请求失败或返回空列表（部署重置/时序竞争），tab2 保持 `{channel: null, visible: false}`，后续无重试机制将 tab2 激活。

**问题 A2：15s 轮询检测到活跃工作群但不设置 tab2 状态**

line 473-475 的判读分支：

```javascript
} else if (activeIds.length > 0 && !TAB_STATE.tab2.channel) {
  // New active workspace appeared and Tab2 is empty → refresh tab bar
  renderTabBar();
}
```

此分支检测到「存在活跃工作群，但 tab2 无 channel」，却**只调用 `renderTabBar()` 未设置 `TAB_STATE.tab2` 的实际状态**。由于 tab2 的 channel 仍为 `null`、visible 仍为 `false`，`renderTabBar()` 渲染结果依然是 2 个 Tab。

### 2.2 Bug B — Web 会话与持久化机制（`server/persistence.py` + `server/web_viewer.py`）

#### 2.2.1 当前会话模型

Web 端认证流程：

```
用户访问 /chat
  ├── URL 有 token 参数？ → 验证 token → ✅ 显示聊天 / ❌ 显示绑定码
  └── Cookie 有 ws_im_session？ → 用 cookie 值验证 → 同上

绑定流程：
  ① 用户点击「生成绑定码」→ POST /api/bind → 显示 WB-XXXXXX
  ② 管理员审批 → POST /api/approve_web → 创建 session
  ③ 客户端轮询检测到 approved → 存 token 到 localStorage + cookie
```

**会话持久化机制：**

| 存储 | 位置 | 存活期 |
|:----|:-----|:-------|
| `_web_sessions`（内存） | 服务端 `persistence.py` | 进程生命周期 |
| `_web_sessions.json`（磁盘） | `DATA_DIR` 目录 | 持久化（Docker volume） |
| `ws_bridge_token`（浏览器） | `localStorage` | 手动清除前 |
| `ws_im_session`（浏览器） | Cookie，`max_age=7天` | 7 天 |

服务端启动时（`__main__.py:692-693`）从 JSON 文件加载已有 session 到内存。

#### 2.2.2 根因

**问题 B1：Docker 部署时 DATA_DIR 卷挂载可能导致 session 文件丢失**

如果部署流程重建容器时未正确挂载数据卷，`_web_sessions.json` 文件丢失，所有已批准的 session 全部失效。客户端虽然有 localStorage token，但服务端不认识，回退到绑定码页面。

**问题 B2：验证入口 `/api/chat?token=XXX` 的 `validate_token` 仅检查内存 dict**

`web_viewer.py:103-108`：
```python
def validate_token(token: str) -> str | None:
    sessions = persistence.get_web_sessions()
    entry = sessions.get(token)
    if entry:
        return entry.get("name")
    return None
```

如果内存中的 `_web_sessions` 为空（JSON 文件不存在或加载失败），所有 token 都被视为无效。

**问题 B3：WebSocket 连接 `/ws/chat` 的 token 验证路径独立**

WebSocket 连接使用独立的 `/ws/chat?token=XXX` 路径（`web_viewer.py` 中的 WebSocket handler），其 token 验证逻辑与 HTTP API 路径可能不同步。若 WS 连接失败，前端可能显示空白页而非降级为绑定码页面。

### 2.3 Bug C — 历史工作群消息加载机制

#### 2.3.1 当前模型

历史消息通过以下路径加载：

```
点击工作群 → switchHistoryTab(wsId, wsName)
  ├── 设置 TAB_STATE.tab3.channel = wsId
  ├── renderTabBar()
  └── selectTab('tab3')
       └── loadMessages(channel) → GET /api/chat?channel=XXX
```

同时 5s 轮询（`init()` 中的 interval）定期调用 `/api/chat?channel=current` 检查新消息。

#### 2.3.2 根因

**问题 C1：工作群列表 API（`/api/workspaces`）可能返回不完整数据**

部署后服务端重新加载 workspace 数据。若 workspace 的持久化文件（`workspaces.json`）有残留或数据目录挂载问题，已归档工作群的列表可能不完整。

**问题 C2：SQLite 消息数据库被重建**

`init_db(DATA_DIR)`（line 697）创建/打开 SQLite 数据库。如果部署时数据卷挂载不当导致数据库文件丢失或重建，所有历史消息消失，工作群显示为"暂无消息"。

**问题 C3：前端消息缓存 `msgContainers` 为空时未触发 API 重加载**

前端用 `msgContainers[channel]` 做消息去重（line 442-443）。如果是全新登录（非刷新），此缓存为空，但 `loadMessages()` 会正常调用 API 加载。但如果 `appendMessage()` 先于 `loadMessages()` 触发（WebSocket 推消息快于 API 拉取），可能导致时序问题。

---

## 3. 需求详述

### 需求 A — 下拉刷新 Tab 保持

**目标：** 页面刷新后 📋 活跃 Tab 保持显示，不需要手动恢复。

**改动范围：** `server/templates.py`（前端 JS）

<!-- 实现方向见 §4 -->

### 需求 B — 部署后 Web 会话保持

**目标：** 服务端部署/重启后，用户 Web 会话保持有效，不需要重新绑定审批。

**改动范围：** `server/web_viewer.py`（token 验证 + 会话恢复）+ `server/templates.py`

**关键校验点：**
- 用户浏览器 localStorage 中保存的 token 在部署后仍被服务端认可
- 或部署后能自动重新建立有效会话（无需人工审批）

### 需求 C — 历史工作群消息可靠加载

**目标：** 部署后重新登录进入聊天室，所有已归档工作群可见，历史消息可正常加载。

**改动范围：** `server/web_viewer.py` + `server/templates.py`

**关键校验点：**
- `/api/workspaces` 返回完整的已归档工作群列表
- 点击归档工作群后 `/api/chat?channel=XXX` 返回历史消息
- 数据卷重建不影响历史数据

---

## 4. 修复方向建议

> **说明：** 以下为推荐实现方向，具体方案由架构师在技术方案中确定。

### 需求 A 方向 — Tab 持久化

**方案 A1：localStorage 持久化（推荐）**

- 在 `switchToActiveTab()` 中将 tab2 状态（channel + label）写入 `localStorage`
- 在 `init()` 中优先从 `localStorage` 恢复 tab2，再通过 API 刷新验证
- 在工作群归档/切换时同步更新 `localStorage`
- 优势：页面刷新后即时恢复（不依赖 API）

**方案 A2：修复轮询分支**

- 将 line 473-475 的 `renderTabBar()` 改为调用 `switchToActiveTab()`
- 同时修复 `init()` 中 API 失败的降级
- 优势：改动量小

### 需求 B 方向 — 会话持久性

**方向 B1：确保 session 文件在部署中不丢失（运维层面）**

- 确认 Docker volume 挂载路径正确：`_web_sessions.json` 在数据目录中
- 部署后自动恢复内存 session（已实现 `load_web_sessions()`，验证是否生效）

**方向 B2：客户端 token 续期机制（代码层面）**

- 前端检测到 `/api/chat?token=XXX` 返回 401 时，自动尝试用 cookie + 新的 bind 码续期
- 或增加 `/api/session/refresh` 端点，客户端 token 过期时自动轮换

**方向 B3：WebSocket 连接异常时浏览器自动重试**

- 当前 `connectWS()` 已有 3 秒重连（line 428）
- 如果 WS 因 token 无效断开，前端应自动回退到 HTTP polling 模式

### 需求 C 方向 — 历史消息可靠性

**方向 C1：确认数据卷持久化**

- 在部署步骤中增加 `DATA_DIR` 卷存在性验证
- SQLite 数据库文件（`messages.db`）必须在 volume 中

**方向 C2：前端消息加载降级路径**

- 当 `loadMessages(channel)` 返回空列表时，应显示明确的提示（如"无历史消息" vs "加载失败"）
- 5s 轮询不应覆盖用户手动切换工作群的操作

---

## 5. 不改的内容

| 事项 | 原因 |
|:----|:-----|
| 其他 Tab（tab1 大厅）的持久化 | 大厅无动态状态丢失问题 |
| Web 端 UI 重构/样式调整 | 仅修复功能性 Bug |
| 服务端 handler.py 改造 | 问题集中在 Web 端前端代码和 session 管理层 |
| Gateway 插件 | 不属本轮范围 |
| Docker Compose 配置 | 基础设施问题不在代码修复范围 |

---

## 6. 开放问题

| # | 问题 | 建议 | 决策者 |
|:-:|:-----|:-----|:------|
| 1 | 多个活跃工作群时，刷新后恢复哪个？ | 恢复刷新前所在的那个（localStorage 存 activeTabId） | 项目负责人 |
| 2 | localStorage 是否需要清理过期数据？ | `tab2.channel` 在 API 验证时确认有效，无效则清 | 项目负责人 |
| 3 | 部署后 session 丢失是代码问题还是卷挂载问题？ | 需确认 Docker volume `DATA_DIR` 是否在部署后残留 | 项目负责人 |
| 4 | 历史消息空 vs 加载失败是否需要前端区分显示？ | 建议区分：「暂无消息」vs「加载失败，重试」 | 项目负责人 |

---

## 7. 验收检查表

| # | 验收项 | 类型 | 状态 |
|:-:|:------|:----:|:----:|
| A-1 | 刷新后活跃 Tab 保持显示 | P0 | ⬜ |
| A-2 | 刷新后活跃 Tab 消息正确加载 | P0 | ⬜ |
| A-3 | 无活跃工作群时仍为 2 Tab | P0 | ⬜ |
| A-4 | 工作群归档后 Tab 自动隐藏 | P0 | ⬜ |
| B-1 | 部署/重启后 Web 端不显示绑定码页面，保持登录状态 | P0 | ⬜ |
| B-2 | 部署后 WebSocket 自动重连成功，聊天功能正常 | P0 | ⬜ |
| C-1 | 重新登录后历史工作群列表完整 | P1 | ⬜ |
| C-2 | 历史工作群消息列表可正常加载 | P1 | ⬜ |
| C-3 | 历史消息加载失败时显示明确提示 | P2 | ⬜ |

---

> **审核记录：**
> - v0.1 提交审核：2026-06-23
> - v0.2 追加 Bug B（部署登出） + Bug C（历史错乱）：2026-06-23
> - 项目负责人审核意见：
> - 结论：
