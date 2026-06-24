# R39 技术验证方案

> **版本：** v1.0
> **状态：** ✅ 待评审
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-24
> **需求文档：** [R39-product-requirements.md](R39-product-requirements.md)
> **工作计划：** [WORK_PLAN.md](WORK_PLAN.md)

---

## 0. 方案概述

本轮为「先验证再决定修不修」的纯 Bug 修复 + 回归验证轮。验证范围覆盖：

| 区块 | 内容 | 验证项 |
|:-----|:-----|:------:|
| **Part A** | Bug 验证 + R38 回归 | V-1 ~ V-12 |
| **Part B** | 不通过时的修复方案 | FIX-A ~ FIX-D |

### 执行顺序

```
V-1 (F-8 消息重复) → 如 ❌ → FIX-A
V-2 (F-7 下拉刷新) → 如 ❌ → FIX-B
V-3~V-6 (Task 状态机)
V-7 (Agent Card)
V-8~V-10 (Web Tab)
V-11 (F-9 消息分流) → 如 ❌ → FIX-C
V-12 (F-10 进度空白) → 如 ❌ → FIX-D
```

---

## Part A — 验证/回归方案

---

### V-1 — Bug A (F-8)：Web 端消息重复验证 🔴 P0

**目标：** 确认 d1d4bb0 修复后 Web 端不再每条消息显示两遍

**前置条件：**
- Dev 容器已拉取 `origin/dev` 最新（含 `d1d4bb0`）

**验证步骤：**

1. 打开 Web 端，登录进入聊天界面
2. 在任意 Tab（大厅/活跃/管理员）发送几条消息
3. 观察消息列表，确认每条消息只出现一次
4. 切换到不同 Tab 再切回来，确认消息数量不变（`loadMessages()` 轮询不产生重复）
5. 发一条 WS push 消息（由其他 agent 发送），确认 `appendMessage()` 正确去重

**期望结果：**
- 每条消息内容在列表中仅出现一次
- Tab 切换后消息不翻倍
- WS 实时推送不产生重复条目

**验收标准：** A-1 满足

**实现追踪：**

| 位置 | 修复 |
|:-----|:-----|
| `templates.py:323-327` | `loadMessages()` — ts+sender+content hash 去重 |
| `templates.py:342-351` | `appendMessage()` — 同上 hash + 500 key prune |

**如不通过 → FIX-A**

---

### V-2 — Bug B (F-7)：Web 端下拉刷新 🟡 P2

**目标：** 确认下拉刷新回到正确的 Tab

**验证步骤：**

1. **场景 A：有活跃工作室**
   - 确保有活跃工作室（至少一只虾已切到工作室频道）
   - 在 Web 端下拉刷新
   - 确认回到第一个 Tab（活跃工作室 Tab），不是大厅

2. **场景 B：无活跃工作室**
   - 确保无活跃工作室
   - 下拉刷新
   - 确认回到大厅 Tab（第一个可见 Tab）

**期望结果：**
- 有活跃工作室 → 刷新后处于活跃 Tab
- 无活跃工作室 → 刷新后处于大厅 Tab

**验收标准：** A-2 满足

**实现追踪：**

| 位置 | 检查点 |
|:-----|:-------|
| `templates.py` 刷新锚点 | 确认 W-7 规则已实现 |

**如不通过 → FIX-B**

---

### V-3 — Task 状态机：四命令全流程 🟡 P1

**目标：** `!task_create / update / query / list` 四条命令在 dev 环境全部可用

**验证步骤：**

1. 由 qa-bot 或 admin-bot 在 `_admin` 频道执行：
   ```
   !task_create --context R39-test --name 验证 --role qa-bot
   ```
   确认返回 task_id 和 SUBMITTED 状态

2. 更新任务状态：
   ```
   !task_update <task_id> --state WORKING
   ```
   确认返回 `WORKING`

3. 查询单个任务：
   ```
   !task_query <task_id>
   ```
   确认返回完整任务信息（State / Context / Assigned / Rejects / Updated）

4. 查询上下文列表：
   ```
   !task_query --context R39-test
   ```
   确认返回 R39-test 下所有任务

5. 列出全部任务：
   ```
   !task_list
   ```
   确认返回全部上下文的任务汇总

**期望结果：** 四条命令均正常响应，无报错，返回格式完整

**验收标准：** A-3 满足

**关键路径：**

| 命令 | handler.py 函数 | 行号 |
|:-----|:----------------|:-----|
| `!task_create` | `_cmd_task_create()` | L593 |
| `!task_update` | `_cmd_task_update()` | L613 |
| `!task_query` | `_cmd_task_query()` | L659 |
| `!task_list` | `_cmd_task_list()` | L690 |

---

### V-4 — Task 状态转换合法性 🟡 P1

**目标：** 合法转换通过，非法转换拒绝

**验证步骤：**

1. **合法转换序列（走一轮完整管线）：**
   ```
   SUBMITTED → WORKING  ✅ 允许
   WORKING → COMPLETED  ✅ 允许
   ```
   在 `_admin` 频道执行 `!task_update <id> --state WORKING` 等

2. **非法转换：**
   ```
   COMPLETED → WORKING  ❌ 拒绝
   ```
   确认返回 `❌ 不允许的转换：completed → working`

3. **状态枚举验证：**
   - 确认 TaskState 6 态完整：`submitted / working / input_required / completed / failed / canceled`

**期望结果：**
- 合法转换返回 `✅ Task 已更新`
- 非法转换返回 `❌ 不允许的转换`

**验收标准：** A-4 满足

**关键数据：**

| 位置 | 定义 |
|:-----|:-----|
| `shared/protocol.py` | `TASK_VALID_TRANSITIONS` 转移矩阵 |
| `handler.py:631-639` | 状态合法性校验 |

---

### V-5 — INPUT_REQUIRED 回落与锁定 🟡 P1

**目标：** 审查驳回流程 + reject_count ≥ 2 锁定

**验证步骤：**

1. 创建一个测试任务，转换到 WORKING
2. 审查驳回 → `!task_update <id> --state INPUT_REQUIRED`
   - 确认返回包含 `reject_count: 1`
3. 修复后重提 → `!task_update <id> --state WORKING`
   - 确认允许
4. 再次驳回 → `!task_update <id> --state INPUT_REQUIRED`
   - 确认 `reject_count: 2`
5. 第三次重提 → `!task_update <id> --state WORKING`
   - 确认 `❌ 审查已达上限 (2次)，已锁定 FAILED`

**期望结果：**
- 第 1、2 次驳回可重提
- 第 3 次锁定 FAILED，不可再转

**验收标准：** A-5 满足

**关键路径：**

| 位置 | 逻辑 |
|:-----|:-----|
| `handler.py:640-648` | `reject_count >= TASK_REJECT_CEILING` → FAILED |
| `shared/protocol.py` | `TASK_REJECT_CEILING = 2` |

---

### V-6 — SQLite 持久化 🟡 P1

**目标：** 服务重启后 Task 状态不丢失

**验证步骤：**

1. 创建任务并设置到 WORKING 状态
2. 记录 task_id 和当前 state
3. 重启 dev 容器（由 🦸 项目管理 执行 Railway restart）
4. 重启后查询 `!task_query <task_id>`
5. 确认状态仍为 WORKING，无数据丢失

**期望结果：** 重启后任务状态完整保留

**验收标准：** A-6 满足

**关键路径：**

| 位置 | 逻辑 |
|:-----|:-----|
| `server/task_store.py` | SQLite `tasks` 表 |
| `server/__main__.py:809` | `init_task_store(DATA_DIR)` |
| `entrypoint.py:45-46` | Docker 入口同样初始化（a3f0829 已修复） |

---

### V-7 — Agent Card 加载 🟡 P2

**目标：** Agent Card 配置文件加载成功，角色映射正确

**验证步骤：**

1. 确认 `config/agent_cards.json` 存在且格式正确
2. 创建任务时指定存在角色：`!task_create --context R39-test --name 验证 --role qa-bot`
   - 确认成功创建
3. 创建任务时指定不存在角色：`!task_create --context R39-test --name 验证 --role no-exist`
   - 确认返回错误（如果校验已实现）
4. 确认 `!task_query` 返回的 `Assigned` 字段显示正确角色名

**期望结果：** Agent Card 正常加载，role 校验生效

**验收标准：** A-7 满足

**关键路径：**

| 位置 | 逻辑 |
|:-----|:-----|
| `server/agent_card.py` | `load_cards()` 加载配置 |
| `server/__main__.py:810-811` | init 中调用 `load_cards()` |
| `entrypoint.py:47-48` | Docker 入口 init（a3f0829 已修复） |

---

### V-8 — Web 端进度 Tab 渲染 🟡 P1

**目标：** Tab 可见，表格框架正常

**验证步骤：**

1. 打开 Web 端
2. 检查 Tab 栏是否包含「📊 进度」
3. 点击「📊 进度」Tab
4. 确认表格框架加载（4 列：Step / 环节 / 状态，或显示「暂无任务进度数据」）

**期望结果：**
- Tab 存在且可点击
- 表格框架正确渲染（即使数据为空也显示占位提示）

**验收标准：** A-8（部分 — 框架）

**关键路径：**

| 位置 | 逻辑 |
|:-----|:-----|
| `templates.py:158` | tab5 定义（`channel: '_progress'`） |
| `templates.py:438-503` | `renderProgressTab()` 完整逻辑 |
| `templates.py:449` | `📊` 前缀过滤 |

---

### V-9 — Tab 排序 (W-6) 🔴 P0

**目标：** 有活跃工作室时 Tab 顺序为：活跃 → 大厅 → 管理员 → 📊 进度 → 历史

**验证步骤：**

1. **场景 A：有活跃工作室**
   - 确保至少一只 agent 已切到工作室频道
   - 打开 Web 端
   - 确认 Tab 从左到右为：活跃工作室、大厅、管理员、📊 进度、历史

2. **场景 B：无活跃工作室**
   - 确保无 agent 在工作室频道
   - 刷新 Web 端
   - 确认主动画 Tab 消失（或不显示）

**期望结果：** Tab 顺序严格符合 W-6 规范

**验收标准：** A-9 满足

**关键路径：**

| 位置 | 逻辑 |
|:-----|:-----|
| `templates.py:158` | `permanent: true` 标记 |
| `templates.py:243-245` | Tab 5 渲染 |

---

### V-10 — 刷新规则 (W-7) 🔴 P0

**目标：** 下拉刷新回到第一个 Tab

**验证步骤：**

> 此项与 V-2 联动，V-2 验证内容即为 W-7 的下拉刷新行为。

1. 有活跃工作室时下拉刷新 → 回到活跃 Tab（第一个）
2. 无活跃工作室时下拉刷新 → 回到大厅 Tab（第一个）

**期望结果：** 与 V-2 一致

**验收标准：** A-10 满足

---

### V-11 — Bug D (F-9)：WS 重连后消息分流 🔴 P1

**目标：** 容器重启后 bot 重连时 active_channel 自动恢复到工作室频道

**验证步骤：**

1. **前置：设置状态**
   - 确保至少一只 bot（如 qa-bot）的 active_channel 已设到 `ws:R39开发工作室`
   - 确认 `_agent_active_channels.json` 中该 bot 的记录正确

2. **触发重启**
   - 🦸 项目管理 执行 Railway dev 容器重启（`hermes gateway restart` 或 Railway redeploy）

3. **验证重连后状态**
   - 重启后，各 bot 在大厅发一条消息
   - 确认消息是否出现在大厅还是工作室频道
   - 如果消息出现在大厅 → ❌ active_channel 未恢复
   - 如果消息出现在工作室频道 → ✅ active_channel 正确恢复

4. **检查 auth_ok 响应**
   - 查看 ws-bridge 日志：`Agent <id> authenticated (role=<role>) channel=<ch>`
   - 确认 channel 为 `ws:R39开发工作室` 而非 `lobby`

**期望结果：**
- auth_ok 返回正确的 active_channel
- bot 重连后消息自动路由到工作室频道

**验收标准：** 无独立验收编号（此 Bug 在 PRD 中标记为 F-9 需修复）

**服务器侧现状追踪：**

| 位置 | 行为 | 状态 |
|:-----|:-----|:----:|
| `handler.py:125` | auth_ok 附加 `active_channel`（从 `persistence.get_agent_channel()` 读取） | ✅ 服务器侧已实现 |
| `persistence.py:129-131` | 启动时从 `_agent_active_channels.json` 加载 | ✅ 持久化已实现 |
| `__main__.py:93` | 调用同一个 `handle_auth()` | ✅ 双入口同步 |
| **Bot 客户端** | 收到 auth_ok 后是否应用 `active_channel` | ⏳ 待验证 |

**如不通过 → FIX-C**

---

### V-12 — Bug E (F-10)：进度 Tab 空白 🟡 P2

**目标：** `!task_create` 及 `!task_update` 后进度 Tab 显示数据

**验证步骤：**

1. 在 `_admin` 频道执行：
   ```
   !task_create --context R39-test --name 验证进度 --role qa-bot
   ```
2. 打开 Web 端「📊 进度」Tab
3. 确认是否显示刚创建的任务
4. 更新任务：`!task_update <task_id> --state WORKING`
5. 刷新进度 Tab，确认状态更新

**期望结果：**
- 创建任务后进度 Tab 显示对应数据行（而非「暂无任务进度数据」）
- 更新状态后进度 Tab 同步显示新状态

**验收标准：** A-8（完整）

**根因分析：**

| 组件 | 现状 |
|:-----|:-----|
| `renderProgressTab()` | 从 `_admin` 频道读取消息，按 `content.indexOf('📊') === 0` 过滤（`templates.py:449`） |
| `_cmd_task_create()` | 返回文本响应，**不生成** `📊` 消息到 `_admin` 频道（`handler.py:593-610`） |
| `_cmd_task_update()` | 返回文本响应，**不生成** `📊` 消息到 `_admin` 频道（`handler.py:613-656`） |
| `__main__.py:623-624` | 当收到 `MSG_TASK_NOTIFY` 时，写入 `📊` 到 `_admin` 频道 |
| `_broadcast_task_notify()` | 广播 `MSG_TASK_NOTIFY` 给 workspace 成员 + web viewer，**不写** `📊` 到 `_admin`（`handler.py:773-822`） |

**结论：** 缺少 `📊` 格式进度消息的生成入口。需补：在 `_cmd_task_create()` / `_cmd_task_update()` 中写入 `📊` 到 `_admin` 频道，或由 `_broadcast_task_notify()` 统一写入。

**如不通过 → FIX-D**

---

## Part B — 修复方案（条件性执行）

---

### FIX-A — F-8 消息重复（V-1 不通过时）

**触发条件：** V-1 验证发现消息仍然重复

**诊断步骤：**

1. 确认 dev 容器运行的是包含 `d1d4bb0` 的版本：
   ```bash
   git log --oneline -3 -- server/templates.py
   ```
2. 检查 `save_message()` 和 `write_chat_log()` 是否双重写入同一消息：
   ```
   handler.py:255  write_chat_log(..., channel=ADMIN_CHANNEL)
   handler.py:976  write_chat_log(..., channel=channel)
   handler.py:1072 write_chat_log(..., channel=channel)
   ```
3. 确认 `web_viewer.py` 的 `/api/chat` 端点是否正确读回消息
4. 确认 `handle_api_chat` 去重逻辑是否生效

**修复方案：**

| 步骤 | 文件 | 改动 |
|:-----|:-----|:-----|
| 1 | `server/handler.py` | 在 `save_message()` + `write_chat_log()` 配对调用处增加 message_id 统一，确保两路径使用相同 ts |
| 2 | `server/templates.py` | 如哈希去重失效，改用 `message_id` 去重（需服务端在消息中附带 `msg_id`） |

---

### FIX-B — F-7 下拉刷新（V-2 不通过时）

**触发条件：** V-2 验证发现下拉刷新仍跳到错误 Tab

**诊断步骤：**

1. 检查 `templates.py` 的下拉刷新锚点逻辑
2. 确认 W-7 规则（「下拉刷新回到第一个 Tab」）是否已在代码中实现

**修复方案：**

| 步骤 | 文件 | 改动 |
|:-----|:-----|:-----|
| 1 | `server/templates.py` | 在 `window.addEventListener('beforeunload', ...)` 或刷新处理中，将 `activeTabId` 持久化到 `sessionStorage` |
| 2 | `server/templates.py` | 页面加载时优先从 `sessionStorage` 恢复 `activeTabId`，fallback 到第一个可见 Tab |

---

### FIX-C — F-9 WS 重连路由（V-11 不通过时）

**触发条件：** V-11 验证发现重连后消息分流到大厅

**诊断步骤：**

1. 检查 auth_ok 响应中的 `active_channel` 值：
   ```
   # 服务器日志
   Agent <id> authenticated (role=member) channel=lobby  ← 问题
   Agent <id> authenticated (role=member) channel=ws:R39开发工作室  ← 正常
   ```
2. 检查 `_agent_active_channels.json` 中目标 agent 的记录是否正确
3. 检查持久化加载：`persistence.py:131` `_load_json()` 是否正常
4. 确认 Gateway 侧是否将 auth_ok 的 `active_channel` 传递给了 bot

**修复方案（三选一或组合）：**

#### 方案 C1 — 服务端主动推（推荐）

在 `handle_auth()` 成功认证后，服务端主动向 agent 发送 `MSG_SET_ACTIVE_CHANNEL`：

```python
# handler.py:127 之后（handle_auth 内）
active_ch = persistence.get_agent_channel(agent_id)
if active_ch and active_ch != p.LOBBY:
    await _send(ws, {
        "type": p.MSG_SET_ACTIVE_CHANNEL,
        p.FIELD_ACTIVE_CHANNEL: active_ch,
        "agent_id": agent_id,
    })
```

**改动用：** `server/handler.py` — `handle_auth()` 函数（~3 行）

#### 方案 C2 — Gateway 侧同步

Gateway 插件在收到 auth_ok 后解析 `active_channel` 并设置到 bot 的内部状态。

**改动用：** Gateway 插件代码（不在本仓库内，需 🦸 项目管理 协同）

#### 方案 C3 — 双入口同步检查

确认 `__main__.py::ws_handler()` 的 auth 路径（line 93）使用的是同一 `handle_auth()` 函数。

**改动用：** 无需改动（已验证已同步）

#### 推荐执行顺序

> 先执行 C1（服务端主动推），这是最可控的方案。如 C1 仍不够，再配合 C2（Gateway 侧）。

---

### FIX-D — F-10 进度 Tab 空白（V-12 不通过时）

**触发条件：** V-12 验证发现 `!task_create` 后进度 Tab 仍空白

**根因：** `!task_create` and `!task_update` 不产出 `📊` 格式消息到 `_admin` 频道，导致 `renderProgressTab()` 的 `📊` 前缀过滤匹配不到数据。

**修复方案（推荐 D1 + D2 组合）：**

#### 方案 D1 — `_cmd_task_create` 补进度消息

在 `_cmd_task_create()` 返回前写入 `📊` 到 `_admin` 频道：

```python
# handler.py:610 之后（return 之前或之后）
write_chat_log(
    "系统",
    f"📊 {context_id} {name}: SUBMITTED",
    channel=p.ADMIN_CHANNEL,
)
```

**改动用：** `server/handler.py:610` 之后 — `_cmd_task_create()`（+2 行）

#### 方案 D2 — `_cmd_task_update` 补进度消息

在 `_cmd_task_update()` 状态更新成功后写入 `📊`：

```python
# handler.py:649 之后（ts.update_state 成功之后）
task = ts.get_task(task_id, config.DATA_DIR)
write_chat_log(
    "系统",
    f"📊 {task['context_id']} {task['name']}: {current.value} → {target.value}",
    channel=p.ADMIN_CHANNEL,
)
```

**改动用：** `server/handler.py:649` 之后 — `_cmd_task_update()`（+4 行）

#### 方案 D3（备选）— 统一入口

在 `_broadcast_task_notify()` 中统一写入 `📊`（无需改 D1/D2）：

```python
# handler.py:798 之后（_broadcast_task_notify 内）
notify_text = f"📊 {context_id} {task['name']}: {transition}"
write_chat_log("系统", notify_text, channel=p.ADMIN_CHANNEL)
```

**改动用：** `server/handler.py:798` 之后（+2 行）

> ⚠️ 注意：`_broadcast_task_notify()` 目前在 `_cmd_task_update()` 中被调用，但不在 `_cmd_task_create()` 中被调用。选 D3 需要同步将 task_create 也调用 `_broadcast_task_notify()`。

#### 推荐执行顺序

> D1 + D2 最小改动，各只加 2-4 行。D3 作为备选如果统一入口更方便。

---

## 附录 A — 代码变更汇总

### 本轮已合入 dev 的修复

| Commit | 内容 |
|:-------|:-----|
| `d1d4bb0` | F-8: ts 格式统一 + loadMessages() / appendMessage() 哈希去重 |
| `a3f0829` | R38: entrypoint.py + Dockerfile 补 init_task_store + load_cards |
| `bee3a43` | Step 4 ✅ / Step 5 ✅ — 编码 + 审查通过 |

### 本方案可能触发的改动（条件性）

| FIX | 文件 | 最大改动量 |
|:----|:-----|:----------|
| FIX-A | `server/handler.py`, `server/templates.py` | ~10 行 |
| FIX-B | `server/templates.py` | ~15 行 |
| FIX-C | `server/handler.py` | ~3 行 |
| FIX-D | `server/handler.py` | ~6-8 行 |

---

## 附录 B — 双入口同步检查表

| 改动文件 | handler.py (websockets) | __main__.py (aiohttp) | entrypoint.py (Docker) |
|:---------|:-----------------------:|:---------------------:|:----------------------:|
| FIX-C (主动推 active_channel) | 改 `handle_auth()` | 同函数，自动覆盖 ✅ | 无需改动 ✅ |
| FIX-D (写 📊 到 admin) | 改 `_cmd_task_create/update` | 自动覆盖（共享函数）✅ | 无需改动 ✅ |
| FIX-A (消息去重) | 改 save/write 配对 | 同函数 ✅ | 无需改动 ✅ |

> 所有条件性修复均通过共享函数（`handle_auth`, `_cmd_task_*`）实现，`handler.py` 和 `__main__.py` 自动同步。

---

## 附录 C — 验证结果记录模板

测试执行时填写：

```
| V-# | 验证项 | 结果 | 备注 |
|:---:|:-------|:----:|:-----|
| V-1 | F-8 消息重复 | ⬜ | |
| V-2 | F-7 下拉刷新 | ⬜ | |
| V-3 | Task 四命令 | ⬜ | |
| V-4 | 状态转换 | ⬜ | |
| V-5 | INPUT_REQUIRED | ⬜ | |
| V-6 | SQLite 持久化 | ⬜ | |
| V-7 | Agent Card | ⬜ | |
| V-8 | 进度 Tab 框架 | ⬜ | |
| V-9 | Tab 排序 W-6 | ⬜ | |
| V-10 | 刷新规则 W-7 | ⬜ | |
| V-11 | F-9 消息分流 | ⬜ | |
| V-12 | F-10 进度空白 | ⬜ | |
```

> ✅ 通过 / ❌ 不通过 / ⏭️ 跳过（已修复无需验证） / ⬜ 未执行

---

> **待 PM 评审 → 🦸 项目管理**
