---
pipeline:
  goal: "多 Agent 协作基础设施——Step 倒计时心跳、Agent Card 注册+角色映射、ACK 保障触发机制。过渡轮次：旧路径完整保留，退化开关可控"
  steps:
    step2:
      role: arch
      title: 技术方案
      context:
        requirements_url: "${pipeline.requirements_url}"
        work_plan_url: "${pipeline.work_plan_url}"
      output_desc: "技术方案文档 URL（commit SHA）"
      feedback_channel: _admin
      timeout_minutes: 20
      escalation: notify_pm
    step3:
      role: dev
      title: 编码实现
      context:
        requirements_url: "${pipeline.requirements_url}"
        work_plan_url: "${pipeline.work_plan_url}"
        tech_plan_url: "${steps.step2.output}"
      input_from: step2
      output_desc: "代码 commit SHA"
      feedback_channel: _admin
      timeout_minutes: 40
      escalation: notify_pm
    step4:
      role: review
      title: 代码审查
      context:
        requirements_url: "${pipeline.requirements_url}"
        work_plan_url: "${pipeline.work_plan_url}"
        code_commit: "${steps.step3.output}"
      input_from: step3
      output_desc: "审查报告 URL（commit SHA）"
      feedback_channel: _admin
      timeout_minutes: 20
      escalation: notify_pm
    step5:
      role: qa
      title: 测试验证
      context:
        requirements_url: "${pipeline.requirements_url}"
        work_plan_url: "${pipeline.work_plan_url}"
        code_commit: "${steps.step3.output}"
      input_from: step3
      output_desc: "测试报告 URL（commit SHA）"
      feedback_channel: _admin
      timeout_minutes: 20
      escalation: notify_pm
    step6:
      role: admin
      title: 合并部署归档
      context:
        requirements_url: "${pipeline.requirements_url}"
        work_plan_url: "${pipeline.work_plan_url}"
        test_report: "${steps.step5.output}"
      input_from: step5
      output_desc: "main 分支 commit SHA"
      feedback_channel: _admin
      timeout_minutes: 10
      escalation: notify_pm
---

# R63 工作计划 — 多 Agent 协作基础设施（过渡轮次）

> **版本：** v1.2 🔄（编码审查完成，等待 QA）
> **状态：** ✅ Step 3 编码 + Step 4 审查完成 → ⏳ Step 5 QA 进行中
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R63/R63-product-requirements.md v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动集中在核心模块，严禁 scope creep**
- ✅ **纳入：** `server/handler.py`、`server/timeout_tracker.py`（新增）、`server/agent_card.py`、`server/config.py`、`docs/R63/*`
- ❌ **不改入：** `server/web_viewer.py`、`server/auth.py`、`server/workspace.py`、`server/message_store.py`、`shared/protocol.py`、`templates/`、前端代码、`server/persistence.py`
- ❌ **不引入新依赖：** 不新增 pip 包（纯标准库实现）
- 编码者超出 scope 的改动，审查者直接打回

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | admin | arch | — |

---

## 1. 管线总览

### 1.1 本轮核心交付

| # | 方向 | 交付 | 说明 |
|:-:|:----:|:-----|:------|
| 1 | A1 | 倒计时参数定义 | frontmatter `timeout_minutes` → `_PIPELINE_CONFIG.steps.stepN.timeout_minutes` |
| 2 | A2 | `timeout_tracker.py` | 独立倒计时模块：start/clear/get_remaining/is_expired |
| 3 | A3 | 倒计时心跳 + 超时触发 | `!pipeline_status` 显示剩余时间，归零触发 PM 协调 |
| 4 | A4 | Step 切换自动清理 | `!step_complete` / `step_handoff` → 清旧启新 |
| 5 | A5 | R62 `_PIPELINE_CONFIG` 落地 | frontmatter 解析器、config/state 分离、退化兼容 |
| 6 | B1-B6 | Agent Card 注册 + 角色映射 | schema 扩展、点名注册、`_ROLE_AGENT_MAP`、Step 路由改造 |
| 7 | C1-C5 | ACK 保障触发机制 | 状态机、delivery ACK + bot ACK 双通道、超时 PM 协调 |
| 8 | D | 退化开关 | `_ENABLE_R63_TIMEOUT` / `_ENABLE_R63_AGENT_MAP` / `_ENABLE_R63_ACK` |
| 9 | E | 顺手修复 | `_send_to_agent` from_name、旧 bug |

### 1.2 改动范围

仅 `server/handler.py` + `server/timeout_tracker.py`（新增）+ `server/config.py` + `server/agent_card.py`，精确改动点：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A5 | `_PIPELINE_CONFIG: dict[str, dict] = {}` 全局 dict | handler.py ~L44（`_PIPELINE_STATE` 旁） | ~3 行 |
| 2 | A5 | `_parse_frontmatter(content) -> dict` — 解析 WORK_PLAN YAML frontmatter | handler.py 新增函数 | ~20 行 |
| 3 | A5 | `_build_pipeline_config(fm, round, urls) -> dict` — 填充 `${pipeline.xxx}` 模板 | handler.py 新增函数 | ~25 行 |
| 4 | A5 | `_build_fallback_config(round, urls) -> dict` — 旧格式退化 | handler.py 新增函数 | ~12 行 |
| 5 | A5 | `_cmd_pipeline_start()` 改造 — 解析 frontmatter → 生成 `_PIPELINE_CONFIG` | handler.py ~L1280 | ~20 行 |
| 6 | A5 | `_cmd_step_complete()` 改为从 config 读参数 | handler.py ~L1455 | ~25 行 |
| 7 | A5 | `_cmd_step_handoff()` 从 config 读下一 step | handler.py ~L2169 | ~15 行 |
| 8 | A5 | `_cmd_pipeline_status()` 支持 config-only 模式 | handler.py ~L2311 | ~15 行 |
| 9 | A5 | `_clear_pipeline_state()` 不清理 config | handler.py ~L949 | ~3 行 |
| 10 | A1 | `timeout_tracker.py` 独立模块 | **新增文件** | ~80 行 |
| 11 | A1 | `_PIPELINE_CONFIG.steps.stepN.timeout_minutes` 字段读取 | handler.py 集成 | ~5 行 |
| 12 | A3 | `!pipeline_status` 倒计时展示 | handler.py status 函数 | ~10 行 |
| 13 | A3 | 超时触发 PM 协调函数 | handler.py 新增 | ~20 行 |
| 14 | A4 | Step 切换时 `timeout_tracker.clear_timer()` 调用点 | handler.py step_complete/handoff 中 | ~5 行 |
| 15 | B1 | Agent Card schema 扩展（trigger_preference/capabilities/registered_at） | agent_card.py + handler.py | ~20 行 |
| 16 | B2 | 点名注册逻辑 — 回复「到」→ 自动注册/更新 card | handler.py rollcall 路径 | ~25 行 |
| 17 | B4 | `_ROLE_AGENT_MAP` 运行时映射表 + `get_agents_by_role()` | handler.py 新增全局 + 函数 | ~20 行 |
| 18 | B5 | Step 路由改造 — `_cmd_step_complete` 用映射表查目标 | handler.py ~L1510-1540 | ~15 行 |
| 19 | B6 | `!agent_role_map` / `!agent_card register` 管理命令 | handler.py 新增命令 | ~30 行 |
| 20 | C1-C2 | ACK 状态机 `_step_ack_states` + `_ack_timeout_task()` | handler.py 新增全局 + 函数 | ~40 行 |
| 21 | C3 | ACK 超时 → PM 协调 | handler.py 新增触发逻辑 | ~15 行 |
| 22 | C4 | Step 派发集成 ACK | handler.py step_complete 中 | ~15 行 |
| 23 | C5 | `!pipeline_status` ACK 状态展示 | handler.py status 函数 | ~10 行 |
| 24 | D | 三个退化开关 + 环境变量 | config.py | ~10 行 |
| 25 | D | 各开关在 handler 中消费 | handler.py 各函数 | ~10 行 |
| 26 | E | `_send_to_agent` from_name 修正（验证 `PIPELINE_PM_NAME` 覆盖） | handler.py 查漏补缺 | ~5 行 |

**总估算：** ~515 行净改（含 ~80 行新文件）

### 1.3 新增全局变量

```python
# handler.py
_PIPELINE_CONFIG: dict[str, dict] = {}       # round_name -> 只读配置 (R62 A5)
_ROLE_AGENT_MAP: dict[str, list[str]] = {}    # role -> [agent_id, ...]        (B4)
_step_ack_states: dict[str, dict] = {}        # "{round}/{step}" -> {state, agent_id, sent_at, deadline}  (C1)
_ENABLE_R63_TIMEOUT = True                    # 退化开关 (D)
_ENABLE_R63_AGENT_MAP = True                  # 退化开关 (D)
_ENABLE_R63_ACK = True                        # 退化开关 (D)
```

```python
# timeout_tracker.py
_timeout_timers: dict[str, dict] = {}         # "{round}/{step}" -> {deadline, notified, pm_escalated}
```

### 1.4 R62 前置验收（方向 A5）

由于 `_PIPELINE_CONFIG` 和 frontmatter 解析在 R62 已文档化但**代码未部署**，R63 方向 A5 需要恢复并实现以下 12 项：

| # | 检查项 | 完成标准 |
|:-:|:-------|:---------|
| ✅-23 | `!pipeline_start` 解析 frontmatter → 生成 `_PIPELINE_CONFIG` | 无报错 |
| ✅-24 | `_PIPELINE_CONFIG` 与 `_PIPELINE_STATE` 分离 | state 清空后 config 独立 |
| ✅-25 | `!step_complete` 从 config 读参数（URL/role/title） | 非硬编码 |
| ✅-26 | `!step_handoff` 从 config 读下一 step | 非硬编码排序 |
| ✅-27 | state 丢失后 `!pipeline_status` 仍可读 config | 展示 step 列表 |
| ✅-28 | 旧格式 WORK_PLAN → 退化到 `_build_fallback_config` | 写一条日志 |
| ✅-29 | frontmatter 格式错误 → 静默退化 | 不阻塞管线 |
| ✅-30 | 正常流转与改造前一致 | step1→...→step6 完整 |

---

## 2. 管线步骤

### Step 1 — PM 准备

1. 推本 WORK_PLAN.md 到远程 dev 分支
2. 执行 `!pipeline_start R63 --work_plan_url <raw_url>` 启动管线

**前置条件：** 需求文档已由项目负责人审核通过 ✅

### Step 2 — Arch 技术方案

**主角：** arch | **备用：** dev

**任务：**

1. 阅读需求文档全文，理解 A1-A5 + B1-B6 + C1-C5 + D + E
2. 设计 `timeout_tracker.py` 的 API（start/clear/get_remaining/is_expired + 超时回调）
3. 确定 `_parse_frontmatter()` 实现策略：
   - WORK_PLAN 的 `---pipeline:...---` 段是 YAML 格式
   - 纯 `split('---')` + 逐行解析有限子集（无需 pyyaml 依赖）
   - 支持 JSON 格式 frontmatter 作为备选
4. 设计 `_ROLE_AGENT_MAP` 构建策略：
   - Agent Card → `pipeline_roles` → 映射表
   - `get_agents_by_role()` → 映射表 → 过滤工作区成员
5. 设计 ACK 状态机细节：
   - 状态转换图
   - `_step_ack_states` 数据结构
   - delivery ACK 解析（WS 返回的 `"type": "ack"` 含 `delivery` 字段）
   - Bot ACK 检测（工作室消息匹配目标 agent）
6. 确定各退化开关的默认状态（建议全开 = True）
7. 输出 `docs/R63/R63-tech-plan.md`

**完成条件：** 技术方案文档提交到 dev 分支。

### Step 3 — Dev 编码实现

**主角：** dev | **备用：** arch

**任务：** 依据技术方案完成以下编码，按顺序逐项实现：

#### ⚡ 实施顺序（建议）

| 阶段 | 包含 | 验证方法 |
|:----|:-----|:---------|
| **Phase 1** | A5 `_PIPELINE_CONFIG` + frontmatter 解析 + config/state 分离 | `!pipeline_start` 新/旧格式 |
| **Phase 2** | A1-A4 `timeout_tracker.py` + 倒计时集成 | `!pipeline_status` 显示剩余时间 |
| **Phase 3** | B1-B6 Agent Card 注册 + `_ROLE_AGENT_MAP` + Step 路由 | `!agent_role_map` + `!step_complete` |
| **Phase 4** | C1-C5 ACK 状态机 + 超时触发 | delivery ack 状态变化 |
| **Phase 5** | D + E 退化开关 + 顺手修复 | 开关关闭时旧行为不变 |

#### 各 Phase 详细编码

**Phase 1 — `_PIPELINE_CONFIG` + frontmatter 解析：**

1. `handler.py` `_PIPELINE_CONFIG: dict[str, dict] = {}` — 与 `_PIPELINE_STATE` 并列
2. `_parse_frontmatter(content: str) → dict` — 抽取 `---` 段，解析有限 YAML 子集（无 pyyaml）
3. `_build_pipeline_config(frontmatter: dict, round_name: str, base_urls: dict) → dict` — 填充 `${pipeline.xxx}` 模板
4. `_build_fallback_config(round_name: str, base_urls: dict) → dict` — 从 `PIPELINE_STEP_MAP` + 硬编码 URL
5. `NoFrontmatterError` / `ConfigParseError` — 异常类
6. `_cmd_pipeline_start()` 改造：读 WORK_PLAN → 尝试 frontmatter → 生成 config
7. `_cmd_step_complete()` / `_cmd_step_handoff()` → 从 config 读参数
8. `_cmd_pipeline_status()` → config-only 模式
9. `_clear_pipeline_state()` → **不清除** `_PIPELINE_CONFIG`

**Phase 2 — `timeout_tracker.py` + 倒计时集成：**

1. 新建 `server/timeout_tracker.py` — 独立模块
2. `start_timer(round, step, timeout_minutes)` — 启动倒计时，先 clear 同 round
3. `clear_timer(round_name)` — 清除 round 内所有定时器
4. `get_remaining(round, step) → float` — 返回剩余秒数
5. `is_expired(round, step) → bool` — 检查是否超时
6. 超时回调：超时 → 工作室告警 `@PM` + `_admin` 频道告警
7. `_cmd_pipeline_status()` 展示：`⏱ 剩余：12分30秒 / 15分钟`
8. `_cmd_step_complete` 中：完成 → `clear_timer()` → `start_timer()` 下一步
9. `_cmd_step_handoff` 中：同上
10. `_cmd_pipeline_activate` 中：启动当前 step 定时器

**Phase 3 — Agent Card + 角色映射：**

1. `agent_card.py` schema 扩展：`trigger_preference` / `capabilities` / `registered_at` 可选字段（不破坏旧 card 读取）
2. `handler.py` `_ROLE_AGENT_MAP: dict[str, list[str]] = {}` — 运行时映射表
3. `refresh_role_agent_map()` — 从 Agent Card `pipeline_roles` → 构建 `_ROLE_AGENT_MAP`
4. `get_agents_by_role(role, workspace_members=[]) → list[str]` — 先映射表 → 过滤 → 回退 auth
5. 点名回复（`!rollcall` / `!rollcall_role` 收到「到」回复）→ 触发注册：
   - 已有 card → 更新 `last_online` + `status`
   - 无 card → 智能注册（从 auth 取 name/role）
   - 注册后 → `refresh_role_agent_map()`
6. `_cmd_step_complete()` 中下一角色查找：从 `get_agents_by_role()` → 过滤工作区成员
7. `_cmd_step_handoff()` 同理
8. 命令增强：
   - `!agent_card register <agent_id>` — 强制注册/更新
   - `!agent_card auto-register` — 扫描在线 agent 补全
   - `!agent_role_map` — 展示映射表
   - `!agent_role_map --refresh` — 重建映射表

**Phase 4 — ACK 状态机：**

1. `_step_ack_states: dict[str, dict] = {}` — `"{round}/{step}"` → 状态
2. `_assign_step_agent(round, step, target_agent, context_msg)` — 发送消息→注册 ACK 定时器
3. `_ack_timeout_task(ack_key)` — 30 秒超时异步任务
4. delivery ACK 解析 — `handler.py` 的 ack 处理分支检测 `delivery.sent`
5. Bot ACK 检测 — 在 `handler()` 消息处理分支匹配目标 agent 回复
6. PM 协调触发 — `_trigger_pm_escalation(ack_key, state)`
7. `_cmd_pipeline_status()` ACK 展示

**Phase 5 — 退化开关 + 顺手修复：**

1. `config.py`：`R63_ENABLE_TIMEOUT` / `R63_ENABLE_AGENT_MAP` / `R63_ENABLE_ACK` 环境变量
2. handler.py 各主函数入口加退化守卫
3. E1: 检查 `_send_to_agent` `from_name` 是否已全部使用 `PIPELINE_PM_NAME`（R58 修复不彻底的场景）
4. E2: 方向 B 回退 auth（已包含在 B 设计中）

**完成条件：** 代码推 dev，服务端重启验证 Phase 1-5 逐项通过。

### Step 4 — Review 代码审查

**主角：** review | **备用：** qa

**审查重点：**

1. ✅ **Scope 合规** — 没有引入不在范围内的改动（未改 web_viewer/auth/workspace/protocol/templates/persistence）
2. ✅ **`_PIPELINE_CONFIG` 分离** — `_clear_pipeline_state()` 不碰 config；config 只读不写
3. ✅ **退化兼容** — 所有新功能有 guard（开关关闭时旧行为不变）
4. ✅ **frontmatter 解析** — 格式错误只退化不报错，无 pyyaml 依赖
5. ✅ **`timeout_tracker.py`** — 定时器无泄漏、step 切换时正确清理
6. ✅ **`_ROLE_AGENT_MAP`** — 构建逻辑正确（card 优先、auth 回退），不阻塞无 card 场景
7. ✅ **ACK 状态机** — 超时处理不泄漏异步任务，PM 协调不重复触发
8. ✅ **`_find_agents_by_role` 已存在但未被 `_cmd_step_complete` 调用** — 确认新代码调用 `get_agents_by_role()` 而非旧函数
9. ✅ **无新依赖** — 不新增 `import yaml`（纯标准库解析）
10. ✅ **行号回退确认** — 所有改动点与 §1.2 一致
11. ✅ **grep 残留零** — 无内部名残留

**完成条件：** 审查报告 `docs/R63/R63-code-review.md` 推 dev。

### Step 5 — QA 测试

**主角：** qa | **备用：** review

**测试场景：**

| # | 场景 | 方法 | 预期 |
|:-:|:-----|:-----|:------|
| 1 | 新格式管线启动 | `!pipeline_start R63 --work_plan_url <含frontmatter的URL>` | 生成 `_PIPELINE_CONFIG` |
| 2 | 旧格式管线启动 | `!pipeline_start R63-fallback`（旧 WORK_PLAN 无 frontmatter） | 退化到 `_build_fallback_config` |
| 3 | 倒计时展示 | Step 启动后查 `!pipeline_status` | 显示 `⏱ 剩余：N 分 / M 分钟` |
| 4 | 倒计时超时 | 手动等（或 mock time）超时 | `@PM` 告警到场 |
| 5 | Step 切换清理 | complete step2 → 查 `timeout_tracker` | step2 定时器清除，step3 启动 |
| 6 | 角色映射 | `!agent_role_map` | 显示正确 role→agent 对应 |
| 7 | 点名注册 | 点名 → agent 回复「到」 | card 自动注册/更新 |
| 8 | 路由查找 | `!step_complete` 用映射表查目标 | 不报「未找到角色」 |
| 9 | ACK 状态 | 派发后查 `!pipeline_status` | 显示 `SENT → DELIVERED → ✅ ACK` |
| 10 | 退化开关 | 关闭三个开关 → 重复测试 1-9 | 旧行为完整 |
| 11 | config-only 模式 | state 丢失后 `!pipeline_status` | 仍展示 step 列表 |
| 12 | frontmatter 格式错误 | work_plan 内容含格式错误 | 静默退化 |
| 13 | 派发给离线 agent | delivery sent=0 | 30s 内切换备用（未超时？）|
| 14 | ACK 超时 | mock 30s 无 ACK | PM 协调触发 |

**完成条件：** 测试报告 `docs/R63/R63-test-report.md` 推 dev。

### Step 6 — Admin 合并部署归档

**主角：** admin | **备用：** arch

**操作：**

1. 合并 dev→main（`git checkout main && git merge dev && git push origin main`）
2. 构建生产容器：`docker build -t ws-bridge:r63 . && docker compose up -d`
3. 健康检查：`!pipeline_status` + 各 bot 在线确认
4. 关闭 R63-dev 工作室：`!close_workspace`
5. TODO.md 更新：标注 R63 已完成项 + 🔴 P0 完成情况
6. 恢复大厅接收

---

## 3. 验收清单（从需求文档复制）

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | `timeout_minutes` 从 frontmatter 读入 `_PIPELINE_CONFIG` | ✅ |
| ✅-2 | 无 frontmatter → 从 `PIPELINE_STEP_MAP` 读 `timeout_hours` | ✅ |
| ✅-3 | step 激活后启动精确倒计时 | ✅ |
| ✅-4 | `!pipeline_status` 显示剩余时间 | ✅ |
| ✅-5 | 倒计时归零触发 PM 告警 | ✅ |
| ✅-6 | Step 完成→自动清除旧倒计时，启动下一步 | ✅ |
| ✅-7 | Step 跳过→清除当前 round 定时器 | ✅ |
| ✅-8 | 管线关闭→全清 | ✅ |
| ✅-9 | Agent 回复点名→自动注册/更新 Agent Card | ✅ |
| ✅-10 | Agent Card schema 扩展 | ✅ |
| ✅-11 | `_ROLE_AGENT_MAP` 正确构建 | ✅ |
| ✅-12 | `get_agents_by_role()` 先查映射表再回退 | ✅ |
| ✅-13 | `!step_complete` 用映射表查找下一角色 (F-16 解决) | ✅ |
| ✅-14 | `!agent_role_map` 展示映射表 | ✅ |
| ✅-15 | ACK 状态机：SENT→DELIVERED→ACKNOWLEDGED→IN_PROGRESS | ✅ |
| ✅-16 | Bot 回复「到」→ ACKNOWLEDGED | ✅ |
| ✅-17 | 30 秒无 ACK → PM 协调 | ✅ |
| ✅-18 | delivery sent=0 → 切换备用 | ✅ |
| ✅-19 | `!pipeline_status` 显示派发状态 | ✅ |
| ✅-20 | 关闭所有 R63 开关→管线行为与 R61 一致 | ✅ |
| ✅-21 | 开关独立生效 | ✅ |
| ✅-22 | 无 frontmatter → 无报错启动 | ✅ |
| ✅-23 | `!pipeline_start` 解析 frontmatter → `_PIPELINE_CONFIG` | ✅ |
| ✅-24 | config 与 state 分离 | ✅ |
| ✅-25 | `!step_complete` 从 config 读参数 | ✅ |
| ✅-26 | `!step_handoff` 从 config 读下一 step | ✅ |
| ✅-27 | state 丢失后 `!pipeline_status` 仍可读 config | ✅ |
| ✅-28 | 旧格式 WORK_PLAN → 退化 | ✅ |
| ✅-29 | frontmatter 格式错误→静默退化 | ✅ |
| ✅-30 | 正常流转与改造前一致 | ✅ |

---

## 4. 不纳入范围 / 严禁 scope creep

| 事项 | 说明 |
|:-----|:------|
| Agent Card Web 编辑器 | CLI 命令足够，不做前端 |
| `!step_reject` 参数化改造 | 影响小，延后 |
| 持久化 `_PIPELINE_CONFIG` 到磁盘 | 仅进程内存，重启后重建 |
| Web 端倒计时 UI | 纯后端能力 |
| 历史 WORK_PLAN 加 frontmatter | 退化兼容即可 |
| 多项目 pipeline_config 模板 | 先通用化，延后模板化 |
| 修改 bot 端代码 / LLM Agent 行为 | 纯服务端改动 |

---

## 5. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.1 | 2026-07-02 | Step 5+6 ✅ 测试验证 + 合并部署归档 (dev: 8830685, main: 981ee9d) |
| v1.0 | 2026-07-01 | 初始版本，基于 R63 需求文档 v1.0 ✅ |
