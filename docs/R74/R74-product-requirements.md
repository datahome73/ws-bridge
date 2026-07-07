# R74 产品需求 — 管线通用化：WORK_PLAN 单入口 + Raw URL 解耦 🌐

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-07
> **基线：** `85b5615`（main 最新）
> **本轮改动范围：** `server/handler.py` + `server/config.py`
> **参考：** docs/ARCHITECTURE-REQUIREMENTS.md §6 P0「管线参数化完善」

---

## 0. 先验验证：已就绪的基础设施

| 验证项 | 结果 | 确认方式 |
|:-------|:----:|:---------|
| R72 新认证体系（register → api_key → auth） | ✅ | 全员 6 bot 已迁移，`handler.py` handle_auth/handle_register |
| R72 Agent Card 自注册 | ✅ | `agent_card.py` register_from_agent()，pipeline_roles 能力声明 |
| R68 inbox 私有通道 | ✅ | `_inbox:<agent_id>` 通道，PM 单向派活，37/37 测试 ✅ |
| R69 inbox 上下文增强 | ✅ | step_outputs 结构化 + summary/artifact_url 注入 |
| R73 权限打通 | ✅ | L2 member 分支 + min_role 降级 + 运维 operations 角色名 |
| **总结** | ✅ | **基础设施已就绪，可以开始做通用化能力** |

---

## 1. 问题背景

### 1.1 现状：管线紧耦合在 ws-bridge 项目的目录约定上

当前管线从 WORK_PLAN URL 到各 Step 上下文 URL 全是硬编码拼接：

```python
# handler.py L1083 — 硬编码的 repo base
_R62_REPO_BASE = "https://raw.githubusercontent.com/datahome73/ws-bridge/dev"

# config.py L77-80 — 环境变量，但默认值还是写死
WORK_PLAN_REPO_URL = os.environ.get("WORK_PLAN_REPO_URL",
    "https://raw.githubusercontent.com/datahome73/ws-bridge/dev")

# 6 处拼接代码（handler.py L1158, 1175, 1213-1215, 2061, 2091-2104）
f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-product-requirements.md"
f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-tech-plan.md"
f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-review-report.md"
f"{_R62_REPO_BASE}/docs/{round_name}/test-report.md"
f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/WORK_PLAN.md"
```

这意味着：

| 问题 | 具体表现 |
|:-----|:---------|
| **必须要有 `docs/轮次/` 目录** | 没有这层目录结构，管线无法自动找到需求/方案/测试报告 URL |
| **不能跨项目** | 换一个仓库（如公开的 `my-community/project`）所有路径拼接都断裂 |
| **不能跨协议** | 假设了 `raw.githubusercontent.com` 域名——换成 GitLab / Gitee / 自托管 Git 服务全线断裂 |
| **bot 无法独立工作** | 新 bot 加入后，不知道从哪里读需求文档——因为没有显式 URL |

### 1.2 根因分析

| # | 根因 | 说明 |
|:-:|:-----|:------|
| 1 | R45/62 设计时假设了单项目 | ws-bridge 和它的文档在同一仓库内，所以用「轮次名 + 固定路径」拼接省事 |
| 2 | 渐进式构建导致路径耦合散布 | 需求 URL、方案 URL、产出推断 URL 在不同轮次分别加入，各造各的拼接方式 |
| 3 | 运维角色名 `admin` 未全局修正 | R72 设计文档就已扁平角色、R73 已经部署了 operations，但需求文档和部分代码仍沿用 admin |

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:-----|:------|
| 🔴 **P0 方向** | ARCHITECTURE-REQUIREMENTS.md §6 P0 最后一块未完成——「管线参数化完善：新轮次可完全定义自己的 Step 数/角色/超时」。你的期望更进一层——整个管线定义都放进 WORK_PLAN，不仅是 step 定义 |
| 🟡 **基础设施已就绪** | R72 认证 + R68 inbox + R73 权限已全部上线且稳定。做通用化的条件成熟 |
| 🟢 **一条改动解 N 个问题** | 换成 raw URL 显式配置后，同时解决目录依赖、跨项目、跨协议、bot 可读性问题 |

---

## 2. 功能需求

### 设计原则

> **WORK_PLAN.md 是自动化管线的唯一入口参数。**
>
> 它包含：工作室定义、参与角色、各角色规则、任务列表、预期产出、回复对象、上下文链接（全部为 raw URL）。
>
> 管线启动器不再拼接 URL、不再假设目录结构、不再硬编码 6 步或角色名。WORK_PLAN 去哪，管线就去哪。

---

### 方向 A（核心）：WORK_PLAN frontmatter 承载全量配置 🔴 P0

#### A1 — frontmatter schema 扩展

当前 frontmatter 结构（只定义了 `pipeline.steps`）：

```yaml
pipeline:
  goal: "R74 管线通用化"
  branch: dev
  steps:
    step2:
      role: arch
      title: 技术方案
      context:
        requirements_url: "..."   # ⚠️ 虽支持 URL，但被拼接覆盖
      timeout_minutes: 360
```

**改造后的 frontmatter schema：**

```yaml
pipeline:
  # ── 基本信息 ──
  name: "R74 管线通用化"            # 轮次/任务名称
  description: "管线配置通用化，移除目录依赖"  # 可选描述

  # ── WORK_PLAN 自身 raw URL（最重要参数：所有 bot 通过此 URL 读完整上下文） ──
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R74/WORK_PLAN.md"

  # ── 工作室定义 ──
  workspace:
    name: "R74-dev"                # 工作室名（可选，默认用 pipeline.name）
    members:                       # 参与角色及规则
      arch:
        mention_keyword: "ArchBot;arch;架构师"
        rules: "输出技术方案文档，含代码对比和流程图"
      dev:
        mention_keyword: "DevBot;dev;开发"
        rules: "按技术方案编码，必须 git push"
      review:
        mention_keyword: "ReviewBot;review;审查"
        rules: "审查代码合规性，scope 不越界"
      qa:
        mention_keyword: "QABot;qa;测试"
        rules: "按验收标准逐项测试，输出测试报告"
      operations:
        mention_keyword: "OpsBot;operations;运维"
        rules: "合并部署归档"
      pm:
        mention_keyword: "PMBot;pm;需求分析师"
        rules: "编排管线，协调各角色"

  # ── Step 定义（全部使用 raw URL，每 step 均含 work_plan_url 引用） ──
  steps:
    step2:
      role: arch
      title: 技术方案
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/R74/R74-product-requirements.md"
      feedback_channel: "_admin"
      output_desc: "技术方案文档 URL 或 commit SHA"
      timeout_minutes: 360

    step3:
      role: dev
      title: 编码实现
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "同上 URL"
        tech_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R74/R74-tech-plan.md"
      feedback_channel: "_admin"
      output_desc: "编码 commit SHA"
      timeout_minutes: 720

    step4:
      role: review
      title: 代码审查
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "同上"
        tech_plan_url: "同上"
        commit_sha: "${steps.step3.sha}"       # 引用上一步产出
      feedback_channel: "_admin"
      output_desc: "审查报告 URL"
      timeout_minutes: 240

    step5:
      role: qa
      title: 测试验证
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "同上"
        tech_plan_url: "同上"
        commit_sha: "${steps.step3.sha}"
        review_report_url: "${steps.step4.artifact_url}"
      feedback_channel: "_admin"
      output_desc: "测试报告 URL"
      timeout_minutes: 360

    step6:
      role: operations
      title: 合并部署归档
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        merge_branch: "main"
      feedback_channel: "_admin"
      output_desc: "合并 commit SHA"
      timeout_minutes: 120
```

**schema 扩展点对比：**

| 字段 | 当前 | 改造后 | 说明 |
|:-----|:-----|:-------|:------|
| `pipeline.work_plan_url` | ❌ 无 | ✅ **新增（必填）** | WORK_PLAN 自身的 raw URL，**最重要参数**——所有 bot 通过它读完整上下文。`\${pipeline.work_plan_url}` 可在各 step context 中引用 |
| `pipeline.workspace` | ❌ 无 | ✅ 有 | 定义工作室名称和成员角色规则 |
| `pipeline.steps.*.context.*` | `requirements_url` 等被拼接覆盖 | ✅ 完全由 frontmatter 控制，不覆盖 | 所有 URL 是显式 raw URL |
| `pipeline.branch` | `branch: dev`（已存在） | ✅ 保留 | git 分支名，用于产出推断（可选） |
| `pipeline.workspace.members` | ❌ 无 | ✅ 新增 | 角色映射 + 触发词 + 行为规则 |

> 🎯 **核心设计决策：** `!pipeline_start` 不再拼接任何一个 URL。所有 URL 来自 frontmatter 或显式参数。`_R62_REPO_BASE` 和 `WORK_PLAN_REPO_URL` 的路径拼接逻辑全部删除。

#### A2 — `!pipeline_start` 行为变更

```yaml
# 当前：
!pipeline_start R74 --work_plan_url <url或空>
#   → 无 URL 时：拼接 f"{WORK_PLAN_REPO_URL}/docs/R74/WORK_PLAN.md"
#   → 无 frontmatter 时：静默回退 PIPELINE_STEP_MAP

# 改造后：
!pipeline_start R74
#   → 第一步：检查该轮次是否有已有 _PIPELINE_CONFIG
#     ├─ 有 → 复用（兼容已启动管线恢复）
#     └─ 无 → 需要 WORK_PLAN URL 来源（见下）

# URL 来源优先级（R45 兼容）：
# 1. --work_plan_url <raw_url> 显式传入
# 2. 环境变量 WORK_PLAN_REPO_URL + 轮次名拼接（退化，保留兼容）
# 3. ❌ 不再尝试本地路径读取

# frontmatter 解析后：
# 1. 检查是否有 pipeline.steps
#   ├─ 无 → ❌ 返回错误：“WORK_PLAN 缺少 pipeline.steps 定义”
#   └─ 有 → 直接用 frontmatter 的 steps（含所有 raw URL）
# 2. 检查是否有 pipeline.workspace
#   ├─ 有 → 用 workspace 定义创建/校验工作室
#   └─ 无 → 用默认行为（创建轮次名工作室，从 steps 推断角色）
# 3. ❌ 不再回退 PIPELINE_STEP_MAP
```

**关键行为对比：**

| 场景 | 当前 | 改造后 |
|:-----|:-----|:-------|
| 新轮次 + 完整 frontmatter | 拼接 URL，回退 | ✅ 直接使用 raw URL，无拼接 |
| 新轮次 + 缺 steps | 静默回退 6 步 | ❌ 明确错误 |
| 有 `_PIPELINE_CONFIG` 的旧轮次 | 复用 | ✅ 复用（兼容） |
| 跨项目（如 `my-org/other-project`） | URL 拼接路径断裂 | ✅ frontmatter 里配 raw URL 就行 |
| 非 GitHub repo（GitLab/Gitee/自托管） | URL 拼接域名不对 | ✅ raw URL 指向任何 Git 平台 |

---

### 方向 B（清理）：移除所有硬编码路径拼接 🔴 P1

#### B1 — 删除 `_R62_REPO_BASE`

**位置：** `handler.py` L1083

```python
# ❌ 删除
_R62_REPO_BASE = "https://raw.githubusercontent.com/datahome73/ws-bridge/dev"
```

影响：以下拼接代码必须修改：

| 位置 | 当前代码 | 改造后 |
|:-----|:---------|:-------|
| `_build_pipeline_config` L1158 | `f"{_R62_REPO_BASE}/docs/..."` | 从 `base_urls` 参数读取（由 frontmatter 提供） |
| `_build_fallback_config` L1175 | 同上 | 改为 `base_urls.get("requirements_url", "")` |
| `_infer_artifact_url` L1213-1215 | 硬编码 step2/4/5 URL | 改为从 `step_config` 参数读取 `artifact_url` |

#### B2 — `_infer_artifact_url()` 从 frontmatter 读 artifact_url

**位置：** `handler.py` L1210-1216

```python
# 当前：硬编码 step2/4/5 映射
# 改造后：优先从 step_config 读 artifact_url，无定义才回退（兼容旧轮次）

def _infer_artifact_url(step_name: str, round_name: str,
                        step_config: dict | None = None) -> str:
    # 优先：从 frontmatter step 配置读
    if step_config and step_name in step_config:
        art = step_config[step_name].get("artifact_url", "")
        if art:
            return art
    # 回退：硬编码 URL（兼容旧轮次）
    step_urls = {
        "step2": f"https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/{round_name}/{round_name}-tech-plan.md",
        ...
    }
    return step_urls.get(step_name, "")
```

> **注：** 回退 URL 用 `raw.githubusercontent.com` 的 `main` 分支（因为 R72/R73 已合并到 main），不再用 dev 分支。

#### B3 — 整理 `config.py` 中的默认值

`WORK_PLAN_REPO_URL` 环境变量保留（用于退化兼容），但 `!pipeline_start` 不再默认依赖它。新轮次必须通过 frontmatter 或 `--work_plan_url` 提供原始 URL。

---

### 方向 C（顺手）：运维角色名 `admin` → `operations` 🟡 P1

`handler.py` 中所有角色匹配 `admin` 的地方改为 `operations`：

```bash
grep -n '"admin"' server/handler.py
grep -n "'admin'" server/handler.py
grep -n 'role.*admin' server/handler.py
```

| 位置 | 当前值 | 改为 |
|:-----|:-------|:-----|
| `PIPELINE_STEP_MAP` step1/step6 role | `admin` | `operations` |
| `config.py` 中角色定义 | `admin` | `operations` |
| 各命令权限派发 | `admin` | `operations` |

> **注意：** R73 已部署了运维 operations 角色名，但代码里 `PIPELINE_STEP_MAP` 等位置可能还有 `admin` 残留。本轮做一次全面清理。

---

## 3. 验收标准

### 🎯 3.1 方向 A

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 完整 frontmatter + raw URL → `!pipeline_start` | 管线使用 frontmatter 中的 raw URL，不拼接 | 发 `!pipeline_start R74` → 检查 `_PIPELINE_CONFIG[R74]` 中的 URL 字段 = frontmatter 的 raw URL，非拼接值 |
| ✅-2 | 缺 `pipeline.steps` 的 frontmatter → `!pipeline_start` | ❌ 返回错误 "缺少 pipeline.steps" | 创建无 steps 的 WORK_PLAN → 启动 → 检查错误消息 |
| ✅-3 | frontmatter 定义 `workspace.members` → 工作室成员按定义创建 | 工作室包含相应角色 | frontmatter 定义 `arch/dev` 两个成员 → 启动后 `!pipeline_status` 成员列表匹配 |
| ✅-4 | 有 `_PIPELINE_CONFIG` 的旧轮次 → `!pipeline_status` | 正常，不报错 | `!pipeline_status R72` → 正常显示 |

### 🎯 3.2 方向 B

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-5 | `_R62_REPO_BASE` 已从 handler.py 删除 | 零匹配 | `grep -n '_R62_REPO_BASE' server/handler.py` → exit=1 |
| ✅-6 | `!pipeline_start` 不拼接 `docs/轮次/` 路径 | 新轮次无 raw URL 的 context 字段为空串而非拼接值 | frontmatter 不配 `requirements_url` → 启动后检查 context 为空 |
| ✅-7 | `_infer_artifact_url` 优先读 frontmatter artifact_url | 自定义 artifact_url 生效 | frontmatter step2 配 `artifact_url: "https://..."` → `!step_complete step2 --summary x` 自动推断为该 URL |

### 🎯 3.3 方向 C

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-8 | 代码中 `role: admin` 全改为 `role: operations` | 零残留 `"admin"` 角色引用 | `grep -n '"admin"' server/handler.py` → 仅排除正常 admin 命令名称 |
| ✅-9 | `PIPELINE_STEP_MAP` 中 role 已更新 | step1/step6 role = operations | 检查 `_build_legacy_steps()` 的 role 值 |
| ✅-10 | R74 需求文档不出现 admin 角色名 | 使用 operations/运维 | `grep -n 'admin' docs/R74/R74-product-requirements.md` → 零匹配 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| 完整重写 frontmatter 解析器 | 当前 `_parse_frontmatter` 是轻量 YAML 解析，功能够用 | 功能完整性够用，不引入第三方库 |
| inbox 消息格式改造 | inbox 双向回复通道改进 | inbox 已充分测试通过，本轮不动 |
| Web 前端改造 | 管线仪表盘等 | 架构 P1，独立轮次 |
| 多项目/多仓库自动发现 | 自动跨 repo 拉取 WORK_PLAN | 本轮先做「显式 URL 配置」，未来可加发现机制 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 15min |
| **3** | 👨‍💻 Dev | 编码实现 | 20min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 15min |
| **6** | 🛠️ Operations（运维） | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **删除** `_R62_REPO_BASE` 常量 | -1 行 |
| `server/handler.py` | **修改** `_build_pipeline_config()` L1157-1158 — 不再用拼接覆盖 context URL | ~5 行 |
| `server/handler.py` | **修改** `_build_fallback_config()` L1174-1175 — 同理 | ~3 行 |
| `server/handler.py` | **修改** `_infer_artifact_url()` L1210-1216 — 增加 step_config 参数 | ~10 行 |
| `server/handler.py` | **修改** `_cmd_pipeline_start()` L2076-2106 — frontmatter 缺失 steps 报错 + 新增 workspace.members 读取 | ~20 行 |
| `server/handler.py` | **修改** `_get_step_config()` L1229-1235 — 不再回退 `_build_fallback_steps`（仅 `--force`） | ~5 行 |
| `server/handler.py` | **修改** 角色匹配 admin→operations | ~5 处 |
| `server/config.py` | **修改** PIPELINE_STEP_MAP 角色名 operations | ~2 行 |
| **合计** | | **~50 行净增 / -1 行删除 ≈ 49 行净增** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| 旧轮次无 raw URL context，`!pipeline_status` 显示空 | 旧轮次信息不完整 | `_build_fallback_config` 保留对旧轮次的拼接回退（仅 `_PIPELINE_CONFIG` 为空时） |
| `WORK_PLAN_REPO_URL` 依赖者断联 | `--work_plan_url` 不传时找不到 WORK_PLAN | 保留环境变量拼接作为退化路径，打印 deprecation warning |

---

## 6. 脱敏检查清单

- [ ] docs/R74/*.md 零内部名残留
- [ ] `grep -nE '^(小|@)\w+' docs/R74/*.md` 零匹配
- [ ] 使用通用角色名（PM / arch / dev / review / QA / operations）
- [ ] 不包含真实 agent_id / token / URL

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-07 | 初稿 — R74 管线通用化：WORK_PLAN 单入口 + Raw URL 解耦。方向说明：项目负责人纠正——解决 `docs/轮次/` 目录依赖问题，WORK_PLAN 作为唯一入口参数，全量 raw URL 配置，跨项目通用化 |
