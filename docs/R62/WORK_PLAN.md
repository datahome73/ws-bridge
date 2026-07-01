---
pipeline:
  goal: "管线参数化改造——将 step 配置从硬编码抽离为 WORK_PLAN 驱动。过渡轮次：旧格式退化兼容、新格式灰度上线"
  steps:
    step2:
      role: arch
      title: 技术方案
      context:
        requirements_url: "${pipeline.requirements_url}"
        work_plan_url: "${pipeline.work_plan_url}"
      output_desc: "技术方案文档 URL（commit SHA）"
      feedback_channel: _admin
      timeout_minutes: 15
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
      timeout_minutes: 25
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
      timeout_minutes: 15
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
      timeout_minutes: 15
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

# R62 工作计划 — 管线参数化改造（过渡轮次）

> **版本：** v2.0 ✅（已归档）
> **状态：** ✅ 已归档
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R62/R62-product-requirements.md v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动极小，严禁 scope creep**
- 不改入：`server/web_viewer.py`、`server/auth.py`、`server/workplace.py`、`server/message_store.py`、`shared/protocol.py`、`templates.py`、前端代码
- 不改出：不引入新的 API 端点、不修改消息协议、不修改数据库 schema、不引入外部依赖（新 pip 包）
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

| # | 交付 | 说明 |
|:-:|:-----|:------|
| 1 | 参数包 schema | pipeline_config JSON 结构，每 step 含 role/title/context/output_desc/feedback/timeout |
| 2 | frontmatter 解析器 | `_parse_frontmatter()` — 从 WORK_PLAN.md 提取 YAML frontmatter |
| 3 | config 生成器 | `_build_pipeline_config()` / `_build_fallback_config()` — 填充模板变量 → 生成 _PIPELINE_CONFIG |
| 4 | 消化路径改造 | `!step_complete` + `!step_handoff` — 改从 config 读 step 参数 |
| 5 | 状态分层 | `_PIPELINE_CONFIG` 与 `_PIPELINE_STATE` 分离，state 清除不影响 config |
| 6 | 兼容守卫 | 无 frontmatter / 格式错误 → 静默退化到旧硬编码 |

### 1.2 改动范围

仅 `server/handler.py` + `server/config.py`，精确改动点：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A1 | 定义 `_PIPELINE_CONFIG` 全局 dict | `handler.py` ~L44（`_PIPELINE_STATE` 旁） | ~3 行 |
| 2 | A2 | `_parse_frontmatter()` — 从 WORK_PLAN 内容提取 YAML frontmatter | `handler.py` 新增函数 | ~15 行 |
| 3 | A2 | `_build_pipeline_config()` — frontmatter + round_name → 填充模板变量 | `handler.py` 新增函数 | ~20 行 |
| 4 | A3 | `_build_fallback_config()` — 旧格式退化 → 从 PIPELINE_STEP_MAP 生成兼容 config | `handler.py` 新增函数 | ~10 行 |
| 5 | A3 | `_cmd_pipeline_start()` — 读取 WORK_PLAN → 尝试 frontmatter → 生成 config | `handler.py` L1230 附近 | ~15 行 |
| 6 | A4 | `_cmd_step_complete()` — 角色/URL/模板消息改从 config 读 | `handler.py` L1455 附近 | ~20 行 |
| 7 | A4 | `_cmd_step_handoff()` — 下一 step 查找改从 config 读 | `handler.py` L2169 附近 | ~15 行 |
| 8 | A4 | `_cmd_pipeline_status()` — 支持 state 丢失时从 config 显示 step 列表 | `handler.py` L2311 附近 | ~10 行 |
| 9 | A5 | `_clear_pipeline_state()` — 不清理 config | `handler.py` L949 附近 | ~3 行 |
| 10 | B | 兼容守卫 — frontmatter 解析失败/格式错误时的退化路径 | handler.py 内嵌在 A3/A4 | ~5 行 |

**总估算：** ~116 行净改

### 1.3 新全局变量

```python
# handler.py — 与 _PIPELINE_STATE 并列
_PIPELINE_CONFIG: dict[str, dict] = {}  # round_name -> read-only config from WORK_PLAN
```

**生命周期：** 创建于 `!pipeline_start`，存活于服务进程生命周期，不清除、不持久化。配置层 + 运行时层解耦后，即使 state 丢失 config 仍在。

---

## 2. 管线步骤

### Step 1 — PM 准备

1. 推本 WORK_PLAN.md 到远程 dev 分支
2. 执行 `!pipeline_start R62 --work_plan_url <raw_url>` 启动管线

### Step 2 — Arch 技术方案

**主角：** arch | **备用：** dev

**任务：**
1. 阅读需求文档全文，理解 A1-A5 设计
2. 审查 pipeline_config schema 的完整性——字段够用但不冗余？
3. 确定 `_parse_frontmatter()` 的实现策略：
   - 纯 `split('---')` + `yaml.safe_load()` 已足够（Python 标准库无 yaml，考虑用 `json.loads` 解析？或新增 pyyaml 依赖？）
   - 需要 import yaml 还是用正则解析有限子集？
4. 输出 `docs/R62/R62-tech-plan.md`，包含：
   - `_parse_frontmatter()` 的具体实现方案
   - config 模板变量解析方式（`${pipeline.xxx}` 替换逻辑）
   - 各函数的签名和调用链
   - 对旧格式的退化测试策略

**完成条件：** ✅ 技术方案文档已提交 dev 分支 [9350a0f](https://github.com/datahome73/ws-bridge/blob/9350a0f/docs/R62/R62-tech-plan.md)

### Step 3 — Dev 编码实现

**主角：** dev | **备用：** arch

**任务：**
依据技术方案完成以下编码，逐项验证后推 dev：

| # | 函数/改动 | 说明 |
|:-:|:----------|:------|
| 1 | `_PIPELINE_CONFIG = {}` | 全局 dict，与 `_PIPELINE_STATE` 并列 |
| 2 | `_parse_frontmatter(content) -> dict` | 解析 WORK_PLAN 的 `---...---` 段，返回 pipeline 配置 dict |
| 3 | `_build_pipeline_config(frontmatter, round_name, base_urls) -> dict` | 填充 `${pipeline.xxx}` 模板变量 |
| 4 | `_build_fallback_config(round_name) -> dict` | 从 `PIPELINE_STEP_MAP` + 硬编码 URL 生成兼容格式 |
| 5 | `_cmd_pipeline_start()` 改造 | A3 — 解析→生成→存储 `_PIPELINE_CONFIG` |
| 6 | `_cmd_step_complete()` 改造 | A4 — 从 config 读参数 |
| 7 | `_cmd_step_handoff()` 改造 | A4 — 从 config 读下一 step |
| 8 | `_cmd_pipeline_status()` 改造 | 支持 config-only 模式 |
| 9 | `_clear_pipeline_state()` 改造 | 不清除 `_PIPELINE_CONFIG` |

**完成条件：** 代码推 dev，服务端重启验证通过。

### Step 4 — Review 代码审查

**主角：** review | **备用：** qa

**审查重点：**
1. ✅ **Scope 合规** — 没有引入不在范围内的改动（未改 web_viewer/auth/workpace/protocol/templates）
2. ✅ **兼容守卫** — `_parse_frontmatter()` 失败或旧格式时无条件退化，不抛异常
3. ✅ **模板变量解析** — `${pipeline.xxx}` 替换逻辑正确处理递归引用
4. ✅ **状态分层** — `_clear_pipeline_state()` 不再动 `_PIPELINE_CONFIG`
5. ✅ **无新依赖** — 代码中不新增 `import yaml`（用 JSON 替代，markdown frontmatter 约定为 JSON 格式而非 YAML）
6. ✅ **行号回退确认** — 所有改动点与 WORK_PLAN §1.2 一致
7. ✅ **grep 残留零** — 无内部名残留

**完成条件：** 审查报告 `docs/R62/R62-code-review.md` 推 dev。

### Step 5 — QA 测试

**主角：** qa | **备用：** review

**测试场景：**

| # | 场景 | 方法 | 预期 |
|:-:|:-----|:-----|:------|
| 1 | 新格式管线启动 | `!pipeline_start R62 --work_plan_url <含frontmatter的URL>` | 成功生成 _PIPELINE_CONFIG |
| 2 | 旧格式管线启动 | `!pipeline_start R61-fallback`（旧 WORK_PLAN 无 frontmatter） | 无报错，退化到 _build_fallback_config |
| 3 | 状态丢失恢复 | 启动→手动跳过→验证 `!pipeline_status` | 仍展示 step 列表 |
| 4 | 标准流转 | `!step_complete Step2 → Step3` | 消息使用 config 中的 title |
| 5 | 异常 frontmatter | work_plan 内容含格式错误 | 静默退化，不报错 |

**完成条件：** 测试报告 `docs/R62/R62-test-report.md` 推 dev。

### Step 6 — Admin 合并部署归档

**主角：** admin | **备用：** arch

**操作：**
1. 合并 dev→main
2. 部署生产容器（`ws-bridge:r62`）
3. 健康检查确认新容器 pending
4. 关闭 R62-dev 工作室
5. 恢复大厅接收

---

## 3. 验收清单（从需求文档复制）

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | `!pipeline_start R62` 解析 frontmatter | ✅ |
| ✅-2 | `_PIPELINE_CONFIG` 与 `_PIPELINE_STATE` 分离 | ✅ |
| ✅-3 | `!step_complete` 从 config 读参数 | ✅ |
| ✅-4 | `!step_handoff` 从 config 读下一 step | ✅ |
| ✅-5 | state 丢失后 `!pipeline_status` 仍可读 config | ✅ |
| ✅-6 | step 交接消息使用 `steps.stepN.title` | ✅ |
| ✅-7 | 旧格式 WORK_PLAN 不报错 | ✅ |
| ✅-8 | 退化时写一条日志 | ✅ |
| ✅-9 | frontmatter 格式错误不阻塞 | ✅ |
| ✅-10 | `!step_handoff` 跳过后 pipeline_status 仍返回 step 列表 | ✅ |
| ✅-11 | state 清空后 pipeline_start 不报「已活跃」 | ✅ |
| ✅-12 | 正常流转与改造前一致 | ✅ |

---

## 4. 脱敏检查清单

- [ ] docs/R62/*.md 零内部名残留
- [ ] 代码 diff 零内部名/URL/端口泄露
- [ ] `grep` 内部名/域名模式 零匹配

---

## 5. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v2.0 | 2026-07-01 | Step 6 ✅ 合并部署归档 — dev→main `0294fdb`，部署 ws-bridge:r62，12/12 验收全通过 |
| v1.0 | 2026-07-01 | Step 2 ✅ 技术方案完成 — 推 dev `9350a0f` ||
