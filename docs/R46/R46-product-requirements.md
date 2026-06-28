# R46 产品需求 — R44+R45 全链路实战验证

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-06-27
> **本轮改动范围：** 🟢 零代码改动，仅实战验证

---

## 1. 背景

### 1.1 R44+R45 改动汇总

经两轮开发，管线自动触发的链路已完整：

| 轮次 | 改动 | 位置 | 状态 |
|:-----|:------|:------|:----:|
| **R44 F-12** | `_can_broadcast()` _admin 频道 member 放开 + `_check_command_permission()` pipeline_start 白名单 | handler.py | ✅ 已部署 |
| **R44 F-13** | `_cmd_pipeline_start()` 自动从 `auth.get_users()` 收集角色成员 + 默认 step2 | handler.py | ✅ 已部署 |
| **R45 A** | WORK_PLAN.md 检查改为 GitHub dev 远程 HEAD + 本地 fallback，`WORK_PLAN_REPO_URL` 可配置 | config.py + handler.py | ✅ 已部署 |
| **R45 B (F-4)** | 测试标签 `[R{N}测试]` strip 后再匹配 `📢`/`📋`/`🆘` 前缀 | handler.py _classify_lobby_message() | ✅ 已部署 |

### 1.2 各部分已验证程度

| 改动 | 验证方式 | 已验证 | 未验证 |
|:-----|:---------|:------|:-------|
| F-12 _admin 放开 + 白名单 | 原始 WS 直连 `_admin` 发 `!pipeline_start` | ✅ 命令到达 _cmd_pipeline_start | ❌ TG DM → Gateway → _admin 全链路 |
| F-13 成员填充 + 默认 step2 | 代码级验证 | ✅ 逻辑正确 | ❌ 实战触发后工作区是否真有多成员 + 点名是否成功 |
| R45 A 远程 WORK_PLAN | 单元测试 | ✅ HEAD 请求正常 | ❌ `!pipeline_start R46` 完整触发 |
| R45 B (F-4) 标签前缀 | 代码级 | ✅ 逻辑正确 | ❌ 实战发 `[R46测试] 📢` 到 lobby |

### 1.3 本轮目标

**R46 不做任何代码改动**，通过一次完整的 `!pipeline_start R46` 触发和几条带测试标签的消息，验证全部四部分在实战中端到端正常工作。验证通过后，管线自动化就真正可用了。

---

## 2. 预期体验

### 2.1 管线启动全链路

```
PM(原始 WS → _admin) → 发「!pipeline_start R46」
  ↓
① _can_broadcast() → member 准入放开 ✅
② _check_command_permission() → 白名单放行 ✅
③ 远程 HEAD 检查 WORK_PLAN.md → GitHub dev 返回 200 ✅
④ 创建工作室 R46-dev → 角色成员自动填充 ✅
⑤ 点名 arch-bot（附带需求文档+WORK_PLAN URL）✅
⑥ 创建 Step 2 task ✅
  ↓
PM 收到：「🚀 R46 管线已启动 / Step: step2 → arch / ...」
```

### 2.2 测试标签前缀兼容

```
发送到 lobby：「[R46测试] 📢 管线验证开始」
  ↓
re.sub(r'^\[R\d+测试\]\s*', '', content) → "📢 管线验证开始"
  ↓
startswith("📢") → 'announce' ✅ → 正常广播
```

---

## 3. 验证项

### 方向 A — 管线启动全链路 🔴 P1

| # | 验证项 | 预期结果 | 当前状态 |
|:-:|:-------|:---------|:--------:|
| A-1 | PM 在 `_admin` 频道执行 `!pipeline_start R46` | 在 <10s 内收到成功反馈 | ⏳ 待验证 |
| A-2 | 反馈包含工作室名「R46-dev」 | `🚀 R46 管线已启动` | ⏳ 待验证 |
| A-3 | 反馈包含 Step 2 / arch 角色 | 起始正确 | ⏳ 待验证 |
| A-4 | 工作室成员包含 arch/dev/review/qa/admin 各角色 agent | `auth.get_users()` 中对应角色的 agent 均在 | ⏳ 待验证 |
| A-5 | `!pipeline_status` 显示 R46 活跃，current_step=step2 | 管线状态正确 | ⏳ 待验证 |
| A-6 | 构建 `!pipeline_status` 显示当前 step、工作室、启动时间 | 状态完整 | ⏳ 待验证 |
| A-7 | 测试完成后 `!step_complete Step6` 关闭管线 + 归档 | 正常运行 | ⏳ 待验证 |

### 方向 B — F-4 测试标签前缀 🟢 P3

| # | 验证项 | 发送内容 | 预期结果 |
|:-:|:-------|:---------|:---------|
| B-1 | announce 前缀兼容 | `[R46测试] 📢 验证消息` | lobby announce 通过 |
| B-2 | checkin 前缀兼容 | `[R46测试] 📋 @arch-bot` | lobby checkin 通过 |
| B-3 | help 前缀兼容 | `[R46测试] 🆘 求助` | lobby help 通过 |
| B-4 | mention 前缀兼容 | `[R46测试] @arch-bot 开工` | lobby mention 通过 |
| B-5 | 标签在后不退化 | `📢 [R46测试] 验证` | announce 正常 |
| B-6 | 无标签回归 | `📢 普通公告` | announce 正常 |

---

## 4. 验证方法

### 4.1 前置条件

- R45 代码已部署到生产环境（main 分支已包含 commit `9e92ce9` + `0f31719`）
- docs/R46/R46-product-requirements.md 和 WORK_PLAN.md 已推送到 dev 分支
- PM 可通过原始 WS 直连生产端口（28787）

### 4.2 执行方式

**Step 1 — 管线启动：** 通过原始 WS 直连生产 `_admin` 频道，发 `!pipeline_start R46`

**Step 2 — 管线状态确认：** 发 `!pipeline_status` 查看活跃状态

**Step 3 — 工作区验证：** 检查响应中的成员列表和 step 信息

**Step 4 — 标签前缀测试：** 向 lobby 发送带 `[R46测试]` 标签的各类型消息（经 Gateway 路由验证）

**Step 5 — 清理：** 执行 `!step_complete Step6` 关闭管线 + 清理工作区

### 4.3 不取巧原则

不模拟 HTTP 请求替代实战验证，不发代码级单元测试。**每条验证项都通过真实的 WebSocket 连接 + 真实的生产环境执行。**

---

## 5. 验收标准

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| **A-1** | `!pipeline_start R46` 返回 🚀 启动成功，含工作室和 Step 信息 | 🔴 P1 |
| **A-2** | `!pipeline_start R46` 中有工作室名「R46-dev」| 🟡 P2 |
| **A-3** | 启动 Step 为 step2，角色为 arch | 🟡 P2 |
| **A-4** | 工作区成员包含 arch/dev/review/qa/admin 各角色 agent | 🟡 P2 |
| **A-5** | `!pipeline_status` 显示 R46 为活跃状态 | 🟡 P2 |
| **A-7** | `!step_complete Step6` 正常关闭管线 | 🟢 P3 |
| **B-1~B-6** | 全部 6 条标签前缀验证通过 | 🟢 P3 |

---

## 6. 不纳入本轮需求

| 事项 | 原因 |
|:-----|:------|
| Gateway 侧 `_admin` 路由（send_message 可达性） | 独立方向，非验证轮范畴 |
| F-3 P3 角色体系 | 独立功能轮 |
| F-9 Web 端 Tab 加载空白 | 🔴 P0 但待定位 |
| 任何代码改动 | 本轮纯验证，不动代码 |

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v0.1 | 2026-06-27 | 初稿 — R46 全链路实战验证轮：验证 R44 F-12/F-13 + R45 方向 A/B 全部在生产环境端到端工作 |
