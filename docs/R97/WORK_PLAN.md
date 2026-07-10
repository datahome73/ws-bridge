---
pipeline:
  round_name: R97
  branch: dev
  steps: 6
  topology:
    auto_chain: true
    chain:
      - step: step1
        role: pm
        title: 标注 WORK_PLAN 已审核
      - step: step2
        role: arch
        title: 技术方案
      - step: step3
        role: dev
        title: 编码实现
      - step: step4
        role: review
        title: 代码审查
      - step: step5
        role: qa
        title: 测试验证
      - step: step6
        role: operations
        title: 合并部署
  workspace:
    members:
      - 小谷
      - 小开
      - 爱泰
      - 小周
      - 泰虾
      - 小爱
  work_plan_url: https://raw.githubusercontent.com/datahome73/ws-bridge/refs/heads/dev/docs/R97/WORK_PLAN.md
  requirements_url: https://raw.githubusercontent.com/datahome73/ws-bridge/refs/heads/main/docs/R97/R97-product-requirements.md
---

# R97 WORK_PLAN — AutoRouter 稳定化：PipelineContext 驱动

> **状态：** 📋 需求已审核通过 ✅ | WORK_PLAN 已审核通过 ✅
> **需求文档:** https://raw.githubusercontent.com/datahome73/ws-bridge/refs/heads/main/docs/R97/R97-product-requirements.md
> **基线:** `main` latest

---

## 概述

R97 重构 AutoRouter，使其从 PipelineContext（结构化 JSON）驱动，不再依赖 WORK_PLAN frontmatter 和 workspace 成员匹配。PM 也是链条的一环（Step 1）。

### 核心变化

| 维度 | 旧（R88） | 新（R97） |
|:-----|:----------|:----------|
| 拓扑来源 | WORK_PLAN frontmatter 解析 | PipelineContext 结构化 JSON |
| 角色映射 | config/agent_cards.json 或 Agent Card | AutoRouter 实时查询 Agent Card |
| 任务消息 | LLM 拼接 | 机械组装（模板变量替换） |
| PM 角色 | 站在管线外协调 | Step 1 执行者，统一收 inbox→干活→✅ 完成 |
| !pipeline_start | --work_plan_url 必传 | 零参数即可 |

### 团队

| Bot | 角色 | Agent ID | 本轮职责 |
|:----|:-----|:---------|:---------|
| 小谷 | 📋 pm | `ws_f26e585f6479` | Step 1 — 标注 WORK_PLAN 已审核 |
| 小开 | 🏗️ arch | `ws_3f7cdd736c1c` | Step 2 — 技术方案 |
| 爱泰 | 💻 dev | `ws_0bb747d3ea2a` | Step 3 — 编码实现 |
| 小周 | 🔍 review | `ws_fcf496ca1b4f` | **主审查** |
| 晓周 | 🔍 review(备选) | `ws_df77eb8e4b15` | 小周忙时可接手 |
| 泰虾 | 🦐 qa | `ws_eab784ac7652` | 测试验证 |
| 小爱 | 🦸 ops | `ws_c47032fa1f67` | 合并部署 |
| 小谷 | 📋 pm | `ws_f26e585f6479` | 需求+协调+Step 1 |

---

## Step 1 — PM 标注 WORK_PLAN 已审核（小谷）

**触发条件：** 项目负责人（大宏）按 `!pipeline_start` 授权按钮后，AutoRouter 派活 step1 到小谷 inbox。

任务内容：
- 标注本 WORK_PLAN 为「已审核通过 ✅」
- 推 git（commit 含"已审核"标记）
- 回复 `✅ 完成，已推 dev: <sha>`
- 完成后 AutoRouter 自动转 step2→arch

> 注：由于 R97 的 AutoRouter 改造尚未完成，step1 实际验证的是**授权模型在旧 AutoRouter 上是否能正确触发**。如果旧 AutoRouter 不识别 step1→pm，此步将手工 inbox 完成。

- [ ] 本 WORK_PLAN 已推 dev
- [ ] 等待 `!pipeline_start` 授权

---

## Step 2 — Arch 技术方案（小开）

**需求：** 为 R97 的 AutoRouter 重构输出技术方案。

**参考：**
- 需求文档: https://raw.githubusercontent.com/datahome73/ws-bridge/refs/heads/main/docs/R97/R97-product-requirements.md
- 当前 AutoRouter: `server/auto_router.py`
- 当前 PipelineContext: `server/pipeline_context.py`
- 当前 handler: `server/handler.py`（`_cmd_pipeline_start` 部分）

**技术方案重点：**

1. **PipelineContext 新结构** — dataclass `StepInfo` + `PipelineContext`，默认 Step 链（含 step1 pm）
2. **`_cmd_pipeline_start` 简化** — 创建 PipelineContext，不解析 frontmatter，不做 workspace 成员匹配
3. **AutoRouter 重构** — 从 PipelineContext 读拓扑，机械组装任务消息，实时查询 Agent Card 角色映射
4. **角色映射** — `_resolve_agent_by_role()` 函数，从 Agent Card pipeline_roles 实时查询
5. **授权模型** — step1 pm 触发 `!pipeline_start` 后 PM 作为执行者

**产出：** `docs/R97/R97-tech-plan.md`

---

## Step 3 — Dev 编码实现（爱泰）

**基于 arch 技术方案实现 3 个核心改动：**

### 3.1 PipelineContext 新结构（pipeline_context.py）

```python
@dataclass
class StepInfo:
    role: str          # "pm" | "arch" | "dev" | "review" | "qa" | "operations"
    status: str        # "pending" | "active" | "done" | "failed" | "skipped"
    agent_id: str
    agent_name: str
    output: dict | None = None

@dataclass
class PipelineContext:
    round_name: str
    status: str        # "running" | "stopped" | "done"
    created_at: float
    triggerer_id: str
    steps: dict[str, StepInfo]
    step_order: list[str]
    role_agent_map: dict[str, str]
    references: dict[str, str]

DEFAULT_STEP_ORDER = ["step1", "step2", "step3", "step4", "step5", "step6"]
```

### 3.2 `_cmd_pipeline_start` 简化（handler.py）

- 不再从 frontmatter 解析 topology
- 不再做 workspace 成员匹配
- 直接创建 PipelineContext（默认 Step 链）
- 广播 `_admin` 信号给 AutoRouter

### 3.3 AutoRouter 重构（auto_router.py）

- `_on_pipeline_ready()` → 从 `_pipeline_manager.get_context()` 读 context
- `_dispatch_step()` → 从 context 读角色+agent_id → 机械组装任务消息
- `_build_task_message()` → 模板变量替换（不涉及 LLM）
- `_on_step_complete()` → 更新 PipelineContext → 发下一棒
- `_resolve_agent_by_role()` → 从 Agent Card 实时查询
- `_refresh_role_map()` → 每次派活前刷新角色映射

### 3.4 向后兼容

- `--work_plan_url` 参数仍支持（存 references 里）
- 旧 AutoRouter 的 timeout 检测功能不做改动

**产出：**
- `server/pipeline_context.py` 改动（+50 行）
- `server/handler.py` 改动（+30/-20 行）
- `server/auto_router.py` 重构（+200/-150 行）
- 推 dev，commit message 含各改动点

---

## Step 4 — Review 代码审查

**主审查：小周**（晓周备选）

审查重点：
1. ✅ PipelineContext 设计是否合理（dataclass 字段是否完整）
2. ✅ AutoRouter 是否不再依赖 frontmatter/workspace
3. ✅ 角色映射实时查询逻辑是否正确
4. ✅ 任务消息机械组装 vs LLM 拼接的边界
5. ✅ 向后兼容 — 旧 `--work_plan_url` 参数是否正常降级
6. ✅ step1 pm 在链条中的定位

**产出：** `docs/R97/R97-code-review.md`

---

## Step 5 — QA 测试验证（泰虾）

逐项验收测试：

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `!pipeline_start R97` 零参数成功 | 只输轮次名，不需要任何 URL 参数 |
| 2 | PipelineContext 创建并持久化 | `_pipeline_manager.get_context("R97")` 返回完整结构 |
| 3 | AutoRouter 收到信号后自动派活 step1→PM | PM inbox 出现 Step 1 任务消息 |
| 4 | PM ✅ 完成后 AutoRouter 自动派活 step2→arch | arch inbox 出现 Step 2 任务 |
| 5 | 角色映射自动识别新 reviewer（晓周） | 无需配置，晓周上线后自动纳入 review 角色池 |
| 6 | 任务消息中包含前一棒 SHA 引用 | 消息格式含「前一棒已完成: xxxxxx」 |
| 7 | 全链 6 Step 自动走完不切手工 | PM 收到「R97 全部 Step 已完成！」 |
| 8 | 旧 `--work_plan_url` 参数向后兼容 | 带 URL 启动，context.references 包含该 URL |

**产出：** `docs/R97/R97-test-report.md`

---

## Step 6 — Ops 合并部署归档（小爱）

1. `git checkout main && git merge dev`
2. `git push origin main`
3. Docker 构建部署新镜像
4. 启动 AutoRouter（systemctl restart auto-router.service）
5. 确认 AutoRouter 日志无异常
6. TODO.md 更新版本号
7. 关闭工作室

---

## 风险

| 风险 | 缓解 |
|:-----|:------|
| AutoRouter 重构引入回归 | 旧代码全重写，核心逻辑变简单（读 context → 发 inbox → 更新 context） |
| 角色映射如果查询失败 → 派活无目标 | fallback：通知 PM 手工补充角色 |
| step1 pm 在旧 AutoRouter 上无法自动触发 | 第一步走手工 inbox，等 R97 部署后验证自动 |
