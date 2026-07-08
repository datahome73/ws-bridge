---
pipeline:
  name: "R82 Inbox-Only 架构重构"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R82/WORK_PLAN.md"

  workspace:
    members:
      architect:
        mention_keyword: "小开;architect;架构师"
        rules: "输出技术方案文档"
      developer:
        mention_keyword: "爱泰;developer;开发"
        rules: "按技术方案编码实现"
      reviewer:
        mention_keyword: "小周;reviewer;审查"
        rules: "代码审查 + 兼容性检查"
      qa:
        mention_keyword: "泰虾;qa;测试"
        rules: "全量回归测试"
      operations:
        mention_keyword: "小爱;operations;运维"
        rules: "合并部署归档"

  steps:
    step2:
      role: architect
      title: "技术方案"
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R82/R82-product-requirements.md"
      timeout_minutes: 360
    step3:
      role: developer
      title: "编码实现"
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R82/R82-product-requirements.md"
      timeout_minutes: 360
    step4:
      role: reviewer
      title: "代码审查"
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R82/R82-product-requirements.md"
      timeout_minutes: 120
    step5:
      role: qa
      title: "测试验证"
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R82/R82-product-requirements.md"
      timeout_minutes: 240
    step6:
      role: operations
      title: "合并部署归档"
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R82/R82-product-requirements.md"
      timeout_minutes: 60
---

# R82 工作计划 — Inbox-Only 架构重构 🏗️

> **版本：** v1.0（初稿，待推）
> **状态：** 📋 草稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R82/R82-product-requirements.md v1.0 ✅（项目负责人审核通过）

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动方向：大幅删减代码，简化架构。净减行数是目标。**

**改动集中在 server 端**（handler.py、protocol.py、workspace.py、persistence.py、config.py）
**本轮的改动不会破坏客户端** — 旧客户端 WS 协议兼容，bot 收 inbox 消息不变

| 不改入 | 不改出 |
|:-------|:-------|
| 客户端代码（clients/） — 本轮不做客户端改动 | 不引入新协议/消息类型 |
| Web 端（web_viewer.py） — 只改影响 server 路由的部分 | 不新建任何通道 |
| 认证层（auth.py / api_key） — 已有体系不动 | 不增功能，只删减和简化 |
| Agent Card 注册 — 不动 | 不改 pipeline 状态机核心流程 |

**核心原则：所有改动必须是去除或简化，不是增加。能删就删，能简就简。**

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | architect | developer | — |
| Step 3 | 💻 编码 | developer | architect | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | reviewer | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | reviewer | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | operations | architect | |

---

## 1. 管线总览

### 改动范围

**核心文件：** `server/handler.py`、`shared/protocol.py`、`server/workspace.py`、`server/persistence.py`、`server/config.py`

**不动：** `clients/`（本轮不动客户端，部署后验证兼容性）、`server/web_viewer.py`（尽量不动）、`server/auth.py`、`server/agent_card.py`

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:-----|:-----|:----:|
| 1 | A1 | **Bot 广播路由改为 inbox-only** — `handle_broadcast` 中删除 bot 的 lobby/workspace 广播路由，bot 消息只走 inbox 路径。删减 `_is_nonsense`、`_is_duplicate`、`_SILENT_PREFIXES` 等由频道污染引入的滤网 | `server/handler.py` — `handle_broadcast()` | ~-80 行 |
| 2 | A1 | **删除 MSG_SET_ACTIVE_CHANNEL 机制** — 删除 `_broadcast_active_channel()` 函数及其所有调用点（~6 处调用）；删除 `set_active_channel` / `channel_updated` handler | `server/handler.py`、`shared/protocol.py` | ~-60 行 |
| 3 | A1 | **删除 `persistence.get/set_agent_channel()`** — 活跃频道持久化不再需要 | `server/persistence.py` | ~-15 行 |
| 4 | A2 | **新增 inbox 查询路由** — server 识别发往 `_inbox:server` 的 `!` 查询命令，执行后回复到查询者的收件箱，不广播到 admin | `server/handler.py` — 新增简单命令路由函数 | ~+40 行 |
| 5 | B | **工作室改为时间切片标记** — `!create_workspace` 不创建频道，只记录元数据（workspace_id/pipeline_id/created_at/roles/workflow_url）；`!close_workspace` 标记 closed_at + 归档；`!workspace view` 从 message_store 按时间切片查询 | `server/workspace.py`、`server/persistence.py`、`server/handler.py` | ~-30 行（频道相关代码删除）、~+80 行（元数据管理） |
| 6 | C | **admin 通道保留但 bot 不监听** — 进度通知继续发 admin，但 bot 不接收 admin 消息。`!` 命令路由保持从 admin 可用（给真人用） | `server/handler.py` — 修改广播路由 | ~-10 行 |
| 7 | — | **配置项清理** — 删除通道相关环境变量配置 | `server/config.py` | ~-5 行 |
| 8 | — | **协议常量清理** — 删除 MSG_SET_ACTIVE_CHANNEL、MSG_CHANNEL_UPDATED、FIELD_ACTIVE_CHANNEL 等 | `shared/protocol.py` | ~-10 行 |

**总估算：** ~**-70 行净删**（删 ~210 行，增 ~140 行）

### 关键原则

| 原则 | 说明 |
|:-----|:------|
| **不破坏现有连接** | 旧 bot 的现有连接继续工作 — 不再收到 lobby/workspace/admin 广播，但这不影响 inbox 收发 |
| **`_inbox:server` 查询入口** | 发到 `_inbox:server` 的 `!` 命令被视为查询，server 处理后回该 bot 的 inbox，不广播 |
| **`_inbox:xxx` 不经过滤网** | inbox 消息直接投递，跳过 nonsense/duplicate/SILENT_PREFIXES 过滤 |

---

## 2. 管线步骤

### Step 1：管线启动 + inbox 派活

PM 启动管线后，server 执行：
1. 创建 workspace 元数据（时间戳 + pipeline_id + 角色清单）
2. 解析 WORK_PLAN frontmatter
3. 通过 inbox 向 architect bot 发送 Step 2 任务

**无频道切换、无活跃频道广播、无点名流程** — 直接 inbox 派活。

### Step 2：技术方案（architect — 架构师）

**任务：** 分析需求文档，输出技术方案 `docs/R82/R82-tech-plan.md`

**需要确定：**
- `handle_broadcast` 简化的精确改动范围：哪些广播路由分支可以删
- `_broadcast_active_channel` 的 6 个调用点和删除后的影响
- `_inbox:server` 查询路由的报文格式设计
- 工作室时间切片模型的数据结构
- 删除的内容对 pipeline 状态机是否有间接影响

**输出包含：** ① 精确函数/行号改动点 ② 删除路径/保留路径的决策树 ③ 兼容性分析 ④ 风险

### Step 3：编码（developer — 开发工程师）

**任务：** 按技术方案实现所有改动。

核心改动优先级：
1. `shared/protocol.py` — 清理通道相关常量
2. `server/handler.py`
   - 删除 `_broadcast_active_channel()`
   - 删除 `set_active_channel` handler
   - 简化 `handle_broadcast` — 删除 bot 视角的 lobby/workspace 广播路由
   - 新增 `_inbox:server` 查询路由
3. `server/persistence.py` — 删除 `get/set_agent_channel`，新增 workspace 元数据持久化
4. `server/config.py` — 清理通道配置项
5. `server/workspace.py` — 改为元数据模型

### Step 4：审查（reviewer — 审查工程师）

**审查重点：**
- 所有改动是否局限于 server 端（不动 clients/）
- 旧客户端是否不受影响（inbox 收发消息的协议不变）
- 删除的活跃频道切换是否被 pipeline 状态机任何路径依赖
- 代码净减行数（验证是否真正做了减法）
- 所有 bot 名/agent_id 脱敏

### Step 5：测试（qa — 测试工程师）

**测试重点：**
1. Bot A → Bot B inbox 消息 ✅ 送达
2. Bot 回复自动路由到发送者收件箱 ✅
3. `!agent_card list` 发到 `_inbox:server` → 回复到查询者 inbox ✅
4. `!pipeline_status R82` 发到 `_inbox:server` → 回复 ✅
5. 查询回复不广播到 admin 频道 ✅
6. 旧客户端（不升级）仍能正常收 inbox 消息 ✅
7. 无 `MSG_SET_ACTIVE_CHANNEL` 相关系统消息 ✅
8. `!create_workspace` 不产生频道切换广播 ✅

### Step 6：合并部署归档（operations — 运维）

1. git checkout main && git merge dev
2. git push origin main
3. docker build -t ws-bridge:r82 .
4. 部署生产容器
5. `!pipeline_status R82` 确认健康
6. 关闭工作室
7. TODO.md 更新版本号

---

## 3. 验收清单（从需求文档复制）

### 🎯 3.1 方向 A — Inbox-Only 架构

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | Bot 连上后只收自己 inbox | bot 不收到 lobby/workspace/admin 的消息 | 启动测试 bot，连 WS，只发 inbox 消息 → 只有 inbox 消息被接收 |
| ✅-2 | Bot 发消息到他人 inbox | 目标 bot 正确收到，其他 bot 不收 | Bot A 发消息到 Bot B inbox → Bot B 收、Bot C 不收 |
| ✅-3 | Bot 回复自动路由到发送者收件箱 | 无需指定 channel，server 自动回发给发送者 inbox | Bot B 回复 Bot A 的消息 → Bot A 的 inbox 收到回复 |
| ✅-4 | Bot 发送 `!agent_card list` 到 `_inbox:server` | Server 回复格式化卡片列表到该 bot 的 inbox | Test bot 发查询 → 自己 inbox 收回复 |
| ✅-5 | Bot 发送 `!pipeline_status R82` 到 `_inbox:server` | Server 回复管线状态到该 bot 的 inbox | 同上 |
| ✅-6 | 查询结果不广播到 admin | admin 频道无该查询/回复消息 | 观察 admin 频道，无干扰消息 |
| ✅-7 | 删除 MSG_SET_ACTIVE_CHANNEL | 协议中无此消息类型，handler 中无处理代码 | grep 零匹配 |
| ✅-8 | 删除 `_broadcast_active_channel()` | handler 中无此函数 | grep 零匹配 |
| ✅-9 | 删除 `persistence.get/set_agent_channel()` | persistence 中无此函数 | grep 零匹配 |
| ✅-10 | Bot 客户端无频道切换代码 | WsBridgeClient 无 `switch_channel`、`current_channel` 等方法 | 检查 clients/ 代码 |
| ✅-11 | 旧 bot 无需改 apikey/注册流程 | 兼容现有 bot，不破坏 auth | 现有 bot 连上后行为正常 |
| ✅-12 | Bot 发消息到 inbox 不经过 nonsense/duplicate 过滤 | inbox 消息直达，不误拦截 | 发多条相同 inbox 消息 → 全部送达，不丢 |

### 🎯 3.2 方向 B — 工作室时间切片

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-13 | `!create_workspace` 不创建频道，只打时间标记 | websocket 无 MSG_SET_ACTIVE_CHANNEL 广播，persistence 记录元数据 | 创建后检查 persistence 中有记录，无频道广播 |
| ✅-14 | 查看工作室 = 按时间区间筛选 inbox 消息 | `!workspace view ws:xxx` 返回该时间段内的所有 inbox 消息 | 在时间内发多条 inbox 消息 → view 正确显示 |
| ✅-15 | 工作室关闭 = 标记 closed_at | workspace 元数据 status=archived、closed_at 有值 | close 后检查元数据 |
| ✅-16 | `!pipeline_start` 不触发频道切换 | 只有 Step 任务以 inbox 消息派发 | 启动管线后检查 inbox 消息送达，无频道切换广播 |

### 🎯 3.3 方向 C — Admin 保留

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-17 | admin 频道管线进度通知正常 | admin 可以看到 Step 完成通知和进度消息 | `!step_complete` 后 admin 频道收到通知 |
| ✅-18 | bot 不接收 admin 消息 | bot 的 inbox 无任何 admin 频道的消息投递 | 检查 bot 连接的 recv 输出，无 admin 消息 |
| ✅-19 | Web 端 admin tab 正常 | admin 频道在 Web 端可正常查看 | 打开 Web → admin tab → 有消息渲染 |

---

## 4. 脱敏检查清单

- [ ] frontmatter 用真实 bot 名（机器解析需要）
- [ ] 正文用角色名（architect/developer/reviewer/qa/operations/pm）
- [ ] `grep -nE '内部名模式' docs/R82/*.md` 零匹配（frontmatter 区忽略）
- [ ] 不包含真实 agent_id / token / URL
