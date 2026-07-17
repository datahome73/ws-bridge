# R123 产品需求文档（Product Requirements）

> **起草人：** 📋 PM（小谷）
> **状态：** 📝 草稿
> **版本：** v1.0

---

## 1. 背景与目标

R106→R122 完成了管线的自动派活闭环，bot 回复完成消息后自动推进并派发下一步。但经过 R119/R120/R121/R122 四轮实战验证，暴露了一个关键体验问题：

**每个 bot 接活时收到的上下文非常单薄，需要手动去翻前序步骤的产出。**

### 1.1 现状案例

R122 的场景举例：

```
Step 2（Arch → 小开）:
  收到派活 → "📋 R122 Step 2 — 技术方案"
  ↓ 写方案 → 推 git → "已完成 ✅ R122 Step 2##tech_plan_url=..."
  ↓ R115 存储 artifacts（✅ 存入 ctx.artifacts）
  ↓
Step 3（Dev → 爱泰）:
  收到派活 → "💻 R122 Step 3 — 编码实现"
            + "##需求文档## {req_url}"
            // 注意：##技术方案## 字段为空！
```

问题根因：**模板在管线创建时一次性生成**（`_build_rich_templates` 在第 3419 行被调用，传入空 `{}`），artifact 信息虽然在 step 完成时存入了 `ctx.artifacts`，但**模板不重新生成**。

### 1.2 当前已有但未串联的能力

| 已有能力 | 代码位置 | 状态 |
|:---------|:---------|:----:|
| Bot 完成消息带 `##key=value` 提取 | `_extract_artifact_kv()` / `main.py:2515` | ✅ R115 已建 |
| artifacts 存入 ctx | `ctx.artifacts[step_key] = kv` / `main.py:2566-2574` | ✅ R115 已建 |
| 模板渲染 `{placeholder}` 替换 | `_render_template()` / `main.py:2742-2763` | ✅ R107 已建 |
| 模板生成时引用 artifacts | `_build_rich_templates()` / `main.py:3159-3215` | ❌ 在创建时冻结，不随 artifacts 更新 |

### 1.3 目标

**当某步 bot 完成并提交产出后，Server 自动将该步的关键信息注入下一步的派活消息中。** 使每步 bot 接活时直接看到前序步骤的实际产出链接和结果摘要，无需手动翻查。

具体来说，做到以下效果：

**Step 3 派活消息中自动附带：**
```
##技术方案## https://github.com/.../R122-tech-plan.md
##arch_sha## abc1234
##arch_result## ✅ 已完成，技术方案已推 dev
```

**Step 5 派活消息中自动附带：**
```
##dev_sha## def5678
##dev_result## ✅ 已完成，核心功能已推 dev
##dev_commit_msg## feat(R122): implement core module
```

---

## 2. 根因分析

### 2.1 模板冻结

当前模板生成调用的完整链路：

```
_handle_hash_start（第 3419 行）
    → _build_rich_templates(round_name, references, {})
    → 模板字符串中嵌入 step2_art / step3_art 等的值
    → 存入 ctx.message_templates
    ↓ 此后 templates 不再更新
```

在调用时，传入的 `artifacts={}`，而 `step2_art = {}`、`step3_art = {}`、……全部为空。所以模板中的如下字段永远为空：

```python
# 第 3183 行（在 _build_rich_templates 中）
+ (f"##技术方案## {step2_art.get('tech_plan_url', ref.get('tech_plan_url', ''))}\\n"
```

这里 `step2_art` 在创建时是 `{}`，`ref` 也只有 `requirements_url` 和 `work_plan_url`。即使 Step 2 完成后 `ctx.artifacts["step2"] = {"tech_plan_url": "..."}`，**模板不再重新生成**。

### 2.2 Step 产出未记录

当 bot 发送 `已完成 ✅ R123 Step 2` 时，`_try_advance_pipeline` 仅记录：
- `ctx.steps[1]["status"] = "done"`（第 2583-2584 行）
- `ctx.artifacts["step2"] = kv`（第 2569 行，仅当消息含 `##key=value`）

但**未记录**：
- `ctx.steps[1]["output"]`（如 `{"sha": "abc1234"}`）
- `ctx.steps[1]["result_msg"]`（如 `"已完成 ✅ R123 Step 2，已推 dev: abc1234"`）

### 2.3 模板引用的是硬编码字符串而非变量

`_build_rich_templates` 用 f-string 直接嵌入 artifact 值：

```python
step2_art.get('tech_plan_url', '')  # 创建时计算，之后不变
```

而非用模板变量：

```python
# 应该这样（示例）：
{prev_step_output}
{prev_step_sha}
{prev_artifact:tech_plan_url}
```

这样 `_render_template` 在派活时动态填充。

---

## 3. 功能需求

### 需求 A — Step 产出自动记录

> **动机：** 每次 bot 完成一个 step，Server 应将关键产出信息（SHA、commit message、result_msg、artifact KV）记录到 `ctx.steps[].output` 和 `ctx.steps[].result_msg`，供后续 step 使用。

**触发条件：** `_try_advance_pipeline` 成功解析完成消息并推进 step。

**行为描述：**
- 在 `_try_advance_pipeline` 中，推进 step 之前，将完成信息记录到 step 对应的 `ctx.steps[i]`：
  - `output`: 包含 `{sha, commit_msg, ...}` 的 dict。优先从 `##key=value` 中提取，找不到则记录关键字段
  - `result_msg`: 完整的完成消息原文
- 记录后调用 `mgr.save()` 持久化

**验收标准：**
- [ ] A-1：bot 发送 `已完成 ✅ R123 Step 2##sha=abc1234` 后，`ctx.steps[1]["output"] = {"sha": "abc1234"}`
- [ ] A-2：bot 发送 `已完成 ✅ R123 Step 2 ...`（无 `##`）后，`ctx.steps[1]["result_msg"]` 包含原文
- [ ] A-3：`mgr.save()` 在记录产出后调用，产出 JSON 完整保存到 `pipeline_contexts.json`
- [ ] A-4：已有 R115 artifact 逻辑不被破坏（`ctx.artifacts["step2"]` 仍然保存）

### 需求 B — 动态模板重建

> **动机：** 模板不应在管线创建时冻结。每次派活下一步时，应根据最新的 `ctx.artifacts`、`ctx.steps` 数据动态重建模板。

**触发条件：** `_auto_dispatch(ctx, step_num)` 被调用时。

**行为描述：**
- 在 `_auto_dispatch` 中，读取模板前，调用一个重建函数

**实现方案（推荐 Option 1）：**

**Option 1：派活时即时渲染（推荐）**
- 不改 `_build_rich_templates` 的结构
- 在 `_auto_dispatch` 中，把模板中的 `{placeholder}` 变量扩展为支持 `{step2:sha}`、`{step2:result_msg}`、`{step1:agent_name}` 等动态引用
- `_render_template` 增强：从 `ctx.steps[i].output`、`ctx.steps[i].result_msg`、`ctx.artifacts` 中查找变量值
- 模板本身用 `{step2:tech_plan_url}` 占位符，而不是在 f-string 中嵌入值

**Option 2：每次 advance 时重建 message_templates**
- 在 `_try_advance_pipeline` 中 advance 后，重新调用 `_build_rich_templates` 用最新的 `ctx.references` 和 `ctx.artifacts`
- 覆盖 `ctx.message_templates`
- 优点：改动最小，不改模板结构
- 缺点：`_build_rich_templates` 对 `artifacts` 的字段名（`tech_plan_url`、`branch_name`、`test_summary` 等）是硬编码的，灵活性差

**验收标准：**
- [ ] B-1：Step 2 完成后，Step 3 派活消息中自动包含 `##技术方案##` 链接（从 `ctx.artifacts.step2.tech_plan_url` 读取）
- [ ] B-2：Step 3 完成后，Step 4 派活消息中自动包含 `##dev_sha##`（从 `ctx.steps[2].output.sha` 读取）
- [ ] B-3：Step 4 完成后，Step 5 派活消息中自动包含前序步骤的审查报告链接
- [ ] B-4：无 artifacts（空 `{}`）时，模板不显示空占位符，不产生多余的空行
- [ ] B-5：已完成的 step 产出更新后，后续派活的模板自动反映最新值

### 需求 C — 前一 step 完成摘要自动注入

> **动机：** 每个 bot 接活时，应该在上方看到一个简洁的前置步骤完成摘要，而不是纯 URL 列表。

**触发条件：** `_auto_dispatch` 派活 Step N（N >= 3）时。

**行为描述：**
- 派活消息头部自动附加一段摘要文本，格式如下：
```
════════ 前置步骤完成摘要 ════════
Step 2 📐 Arch（小开）
  ✅ abc1234 — feat(R123): add tech plan
  📄 技术方案 → https://...
────────────────────────────────────
```
- 摘要内容来自 `ctx.steps[N-2]`、`ctx.steps[N-1]` 等的 `output`、`result_msg`、`agent_name`
- 不包含当前 step 本身的产出（还没做）
- 所有 step 的完成消息自动添加这段摘要

**格式说明：**
```
════════ 前序步骤状态 ════════
Step 2 → 小开 ✅
  提交: abc1234 — feat(R123): add tech plan
  方案: https://github.com/.../R123-tech-plan.md
Step 3 → 爱泰 ✅
  提交: def5678 — feat(R123): implement core
  分支: dev
══════════════════════════════
```

**验收标准：**
- [ ] C-1：Step 3 派活消息开头包含 Step 2 的完成摘要
- [ ] C-2：Step 4 派活消息开头包含 Step 2 + Step 3 的完成摘要
- [ ] C-3：Step 2 派活消息不包含摘要（前面只有 Step 1，是 PM 自己）
- [ ] C-4：Step 6 派活消息包含 Step 2~5 的完整摘要
- [ ] C-5：摘要中 step 状态为 pending 或未开始时，不显示该 step 的行

### 需求 D — 向后兼容

> **动机：** 改造不能破坏已有 R115 artifact 存储逻辑和现有管线上下文结构。

**已有管线数据格式（`pipeline_contexts.json`）：**
```json
{
  "round_name": "R122",
  "artifacts": {
    "step2": {"tech_plan_url": "https://..."}
  },
  "steps": [
    {"name": "step1", "status": "done", "output": null, "result_msg": "..."},
    {"name": "step2", "status": "done", "output": null, "result_msg": ""},
    ...
  ],
  "message_templates": { /* 旧模板，仍然可用 */ }
}
```

**验收标准：**
- [ ] D-1：旧 `pipeline_contexts.json` 文件可以被正确读取（`output: null`、`result_msg: ""` 正常处理）
- [ ] D-2：已有 R115 artifact 存储逻辑不修改，不破坏
- [ ] D-3：已有 R120 step 状态标记逻辑不修改
- [ ] D-4：`_render_template` 原 `{round}`、`{requirements_url}` 等变量仍然正常解析
- [ ] D-5：管线重启后从 JSON 恢复上下文，动态重建的模板与 JSON 中持久化的数据一致

---

## 4. 方向决定

| 决定事项 | 选择 | 说明 |
|:--------|:----|:-----|
| 模板更新策略 | **Option 1：派活时即时渲染（增强 `_render_template`）** | 不改模板生成函数，只改渲染逻辑。模板用 `{placeholder}` 占位符，渲染时从 `ctx.steps`、`ctx.artifacts` 动态填充 |
| Step 产出记录 | ✅ 在 `_try_advance_pipeline` 中同步记录 | advance step 之前，将 output + result_msg 写入 ctx.steps[i] |
| 摘要注入 | ✅ Step N >= 3 时自动追加前序步骤摘要 | 在 `_auto_dispatch` 中构建摘要文本 |
| 旧数据兼容 | ✅ 所有新字段用 `dict.get()` 安全读取 | `output: null` / `result_msg: ""` / 缺失字段均可正常处理 |

---

## 5. 不做事项（明确排除）

| 排除项 | 理由 |
|:-------|:------|
| ❌ **Git 提交自动检测推进（git auto-detect）** | 本轮不做。调研已记录到 `docs/R123/git-auto-detect-research.md` |
| ❌ **Agent 卡/角色映射持久化** | 与跨 step 上下文无关，后续轮次再做 |
| ❌ **验证钩子系统（自动测试）** | 功能正交，与上下文注入不相关 |
| ❌ **修改 `_build_rich_templates` 的硬编码字段名** | 字段名不改，通过 `_render_template` 增强来实现动态引用。`{step2:tech_plan_url}` 比 `step2_art.get('tech_plan_url', '')` 灵活 |
| ❌ **修改 PipelineContext 的序列化结构** | 保持向后兼容，只新增字段或利用已有字段 |

---

## 6. 开放问题

| # | 问题 | 建议方向 | 决策者 |
|:-:|:-----|:--------|:------|
| 1 | 模板变量命名格式？`{step2:sha}` vs `{prev_sha}` vs `{step2_sha}`？ | 建议 `{step2:sha}` 格式，与 artifacts 的 step_key 命名一致 | PM |
| 2 | 摘要样式是否允许换行/emoji？还是纯文本无格式？ | 建议保留换行和 emoji，bot 能接受 Markdown | PM |
| 3 | 注入的摘要太长怎么办（5 步完成后可能 20 行）？ | 建议默认显示所有已完成 step，太长可被 `...` 截断 | PM |
| 4 | 如果同一 step 有多个 commit（Dev 迭代），output 记录最后一次还是全部？ | 建议记录最后一次，之前的 commit 只通过 result_msg 体现 | PM |
| 5 | 需求 A 中 output 的 sha 从哪里获取？bot 需手动在完成消息中 `##sha=...` 还是 Server 尝试从 git 获取？ | 优先 bot 手动提供（已有 R115），不自动调用 git。bot 不提则 output.sha 为空 | PM |
| 6 | _render_template 增强后，现有模板（已存的 context JSON）中的 `{round}` 等变量是否受影响？ | 不受影响——`{round}` 继续从 ctx 基本信息读取。新增的 `{step2:sha}` 等变量只在新建的管线上下文中可用 | PM |

---

## 7. 验收检查表

| # | 验收项 | 类型 | 优先级 |
|:-:|:------|:----:|:-----:|
| A-1 | 完成消息中的 `##sha=abc1234` 记录到 `ctx.steps[i].output` | P0 | 🟢 |
| A-2 | 完成消息原文记录到 `ctx.steps[i].result_msg` | P0 | 🟢 |
| A-3 | 产出记录后 `mgr.save()` 持久化 | P0 | 🟢 |
| A-4 | R115 artifacts 不破坏 | P0 | 🟢 |
| B-1 | Step 3 派活消息自动包含 Step 2 的 `##技术方案##` 链接 | P0 | 🟢 |
| B-2 | 无 artifacts 时模板不产生空占位符 | P1 | 🟡 |
| B-3 | 已有 `{round}` `{requirements_url}` 等模板变量继续工作 | P0 | 🟢 |
| C-1 | Step 3+ 派活消息追加前置步骤摘要 | P1 | 🟡 |
| C-2 | 摘要格式正确（role/agent/sha/msg） | P1 | 🟡 |
| C-3 | Step 2 不出现摘要 | P2 | 🔵 |
| D-1 | 旧 `pipeline_contexts.json` 可正常加载 | P0 | 🟢 |
| D-2 | `output: null` / `result_msg: ""` 安全读取 | P0 | 🟢 |
| D-3 | 全线管自动派活回归测试 | P0 | 🟢 |

---

> **审核记录：**
> - v1.0 提交审核：[2026-07-17]
> - 项目负责人审核意见：待定
