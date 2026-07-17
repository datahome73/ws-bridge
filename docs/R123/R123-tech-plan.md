# R123 技术方案

> **作者：** 📐 Arch（小开）
> **版本：** v1.0
> **依据：** `docs/R123/R123-product-requirements.md` v1.0 ✅
> **状态：** 待审核

---

## 1. 总体设计

### 1.1 问题+根因

**问题：** 管线派活模板在创建时冻结，Step N 的产出无法自动注入 Step N+1 的派活消息中。

**根因链：**
1. `_handle_hash_start`（L3259）调用 `_build_rich_templates(round_name, references, {})`，传入空 `{}`
2. `_build_rich_templates`（L3068-3071）读取 `step2_art = art.get("step2", {})` → `{}`，所有 artifact 字段为空
3. 即使 Step 2 完成后 `ctx.artifacts["step2"]` 获写入（L2468-2478），`message_templates` 不再重建
4. 模板中的 `step2_art.get('tech_plan_url', ...)` 在创建时被 f-string 计算为常量""
5. `_render_template`（L2664-2666）仅做 `{var}` 替换，无法引用 `{step2:tech_plan_url}` 格式

### 1.2 架构变更

**变更策略（PRD §3 Option 1）：**
- **不改** `_build_rich_templates` 的整体结构
- **改**模板内容：将硬编码的 `step2_art.get('tech_plan_url', ...)` 表达式替换为 `{step2:tech_plan_url}` 占位符
- **增强** `_render_template`：支持 `{stepN:field}` 变量格式，动态从 `ctx.artifacts` 和 `ctx.steps[N-1]` 取值
- **增强** `_try_advance_pipeline`：记录 step `output` 和 `result_msg`
- **增强** `_auto_dispatch`：Step ≥ 3 时追加前置步骤摘要

### 1.3 数据流

```
Bot 发送完成消息
    │
    ▼
_try_advance_pipeline
    ├── R115: 提取 ##key=value → ctx.artifacts["step{N}"]  (已有)
    ├── 🔴 NEW: 记录 output/result_msg → ctx.steps[i].output / result_msg
    ├── advance_step()
    └── _auto_dispatch(ctx, next_step)
            │
            ▼
        _render_template(模板, ctx, step_num)  ← 🔴 NEW: 支持 {stepN:field}
            │ 返回渲染后的派活文本
            ▼
        🔴 NEW: Step≥3 → 前置步骤摘要 + rendered text
            │
            ▼
        send_to_agent(target_agent_id)
```

---

## 2. 涉及文件

| 文件 | 改动类型 | 预估行数 | 对应需求 |
|:----|:--------|:--------:|:--------:|
| `server/ws_server/main.py` | 修改 | ~90 行 | A/B/C/D |
| `server/ws_server/pipeline_context.py` | 不修改 | 0 行 | D (向后兼容) |

**结论：改动范围仅限于 `main.py` 内三处函数 + 模板内容变更。**

---

## 3. 详细设计

### 3.1 需求 A — Step 产出自动记录

**位置：** `_try_advance_pipeline`，L2466-2491 区间内插入

**时机：** 在 `mgr.advance_step(round_name)`（L2480）**之前**记录产出。理由：
- advance 会改变 `ctx.current_step`，记录产出需要引用旧 step 索引
- 产出应记录在「发出前」的 step 上，属于该 step 的成果

**逻辑：**
```python
# 🔴 R123 新增: 在 L2479 处，advance_step 之前
step_idx = completed_step - 1
step_info = ctx.steps[step_idx] if step_idx < len(ctx.steps) else None
if step_info:
    # 构建 output dict
    _output = {}
    if _kv:  # 来自 R115 已提取的 ##key=value
        for k in ("sha", "commit_msg", "tech_plan_url", "branch_name",
                   "test_scope", "test_report_url", "test_summary",
                   "review_url"):
            if k in _kv:
                _output[k] = _kv[k]
    step_info["output"] = _output if _output else None
    step_info["result_msg"] = content[:200]  # 截断防长
```

**字段对应：**

| 完成消息 `##key=value` | `output` 字段 | 示例 |
|:-----------------------|:--------------|:-----|
| `##sha=abc1234` | `output["sha"]` | `"abc1234"` |
| `##commit_msg=feat...` | `output["commit_msg"]` | `"feat(R123): add..."` |
| `##tech_plan_url=...` | `output["tech_plan_url"]` | `"https://..."` |
| `##branch_name=dev` | `output["branch_name"]` | `"dev"` |
| `##review_url=...` | `output["review_url"]` | `"https://..."` |
| `##test_summary=3/3` | `output["test_summary"]` | `"3/3"` |
| `##test_report_url=...` | `output["test_report_url"]` | `"https://..."` |
| 无 `##` 时 | `output = None` | — |
| 完成消息全文 | `result_msg` | 截断 ≤200 字符 |

**关键约定：** bot 手动在完成消息中提供 `##sha=...##commit_msg=...`，Server **不自动调用 git**。bot 不提则 `output.sha` 为空。

**持久化：** 写入后调用 `mgr.save()`（已有调用 L2474-2477 和 L2489），不需新增。

### 3.2 需求 B — 动态模板变量

**位置：** `_render_template`，L2646-2667

**当前行为：**
```python
# 扁平 vars 字典，artifacts 逐 key 拍平覆盖
for step_key, step_artifacts in ctx.artifacts.items():
    vars.update(step_artifacts)
# 替换 {var}
template = template.replace(f"{{{key}}}", str(value))
```

**问题：** artifacts 按 step 键组织（`step2`、`step3`），但扁平合并后无法区分同名 key。且无法访问 step 元信息（`agent_name`、`result_msg`）。

**增强方案：**
```python
# 新增: 支持 {stepN:field} 变量语法
# 替换前，先用正则解析出 {stepN:field} 格式并逐条替换
_placeholder_re = re.compile(r"\{step(\d+):(\w+)\}")
def _resolve_step_var(m: re.Match) -> str:
    step_num = int(m.group(1))
    field = m.group(2)
    step_key = f"step{step_num}"
    step_idx = step_num - 1
    # 优先级:
    # 1. ctx.artifacts["step{N}"].get(field)
    # 2. ctx.steps[idx].output.get(field)
    # 3. ctx.steps[idx].get(field)  （如 agent_name、result_msg）
    # 4. ctx.references.get(field)
    # 5. 空字符串
    ...
template = _placeholder_re.sub(_resolve_step_var, template)
```

**变量解析优先级（高→低）：**

| 来源 | 示例 |
|:-----|:-----|
| `ctx.artifacts["step2"]["tech_plan_url"]` | `{step2:tech_plan_url}` |
| `ctx.steps[1]["output"]["sha"]` | `{step2:sha}` |
| `ctx.steps[1]["agent_name"]` | `{step2:agent_name}` |
| `ctx.steps[1]["result_msg"]` | `{step2:result_msg}` |
| `ctx.references["tech_plan_url"]` | `{step2:tech_plan_url}` 回退 |
| 均找不到 | 空字符串 `""` |

**现有变量不受影响：** `{round}`、`{round_title}`、`{requirements_url}`、`{work_plan_url}` 继续从原 `vars` 字典查找。增强逻辑**仅新增** `{stepN:field}` 格式的解析路径，原有 `template.replace()` 回退路径保留。

### 3.3 需求 B — 模板内容改造

**位置：** `_build_rich_templates`，L3060-3116

**改造方式：** 将函数中硬编码的 f-string 表达式替换为 `{stepN:field}` 占位符。

**具体变更：**

| 当前代码行 | 当前表达式 | 替换为 |
|:-----------|:-----------|:-------|
| L3084 | `step2_art.get('tech_plan_url', ref.get('tech_plan_url', ''))` | `{step2:tech_plan_url}` |
| L3091 | 同上 | `{step2:tech_plan_url}` |
| L3098 | `step3_art.get('test_scope', ref.get('test_scope', ''))` | `{step3:test_scope}` |
| L3100 | `step3_art.get('branch_name', ref.get('branch_name', ''))` | `{step3:branch_name}` |
| L3106 | `step5_art.get('branch', step3_art.get('branch_name', ref.get('branch_name', '')))` | `{step5:branch}` |
| L3108 | `step5_art.get('commit_sha', ref.get('commit_sha', ''))` | `{step5:commit_sha}` |
| L3110 | `step5_art.get('test_summary', ref.get('test_summary', ''))` | `{step5:test_summary}` |
| L3112 | `step5_art.get('test_report_url', ref.get('test_report_url', ''))` | `{step5:test_report_url}` |

**条件判断保持不变：** 每行模板的 `if value else ""` 外层逻辑改为：`_render_template` 中用 `{stepN:field}` 替换为 `""` 后，若结果为空字符串则不产生该行。即 `(f"... {value}\\n" if value else "")` 行结构改为：

```python
# 改造前:
+ (f"##技术方案## {step2_art.get('tech_plan_url', ref.get('tech_plan_url', ''))}\\n"
   if (step2_art.get('tech_plan_url', ref.get('tech_plan_url', ''))) else "")
# 改造后: 占位符始终出现，render_template 解析为空时整行不输出
+ (f"##技术方案## {step2_art_placeholder}\\n"
   if step2_art_placeholder else "")
```

由于 `{step2:tech_plan_url}` 在 `_render_template` 解析后可能为空字符串，`if value else ""` 条件判断仍然有效。**只需改模板字符串中的值本身为占位符文本，保留下层条件判断包裹不变。**

### 3.4 需求 C — 前置步骤摘要注入

**位置：** `_auto_dispatch`，L2736 与 L2738 之间

**触发条件：** `step_num >= 3` 且存在至少一个已完成的前置 step（status="done"）。

**逻辑：**
```python
_summary = _build_step_summary(ctx, step_num)  # NEW helper
content = _summary + content  # 摘要追加到派活消息头部
```

**摘要生成函数 `_build_step_summary`：**
```python
def _build_step_summary(ctx, step_num: int) -> str:
    """为 step_num 构建前序步骤完成摘要。"""
    role_emojis = {1: "📋", 2: "📐", 3: "💻", 4: "👁", 5: "🧪", 6: "🚢"}
    role_names = {1: "PM", 2: "Arch", 3: "Dev", 4: "Review", 5: "QA", 6: "Ops"}
    lines = ["══════ 前置步骤状态 ══════"]
    for i, s in enumerate(ctx.steps, 1):
        if i >= step_num:
            break  # 只显示前序 step
        if s.get("status") != "done":
            continue  # 未完成不显示
        role_emoji = role_emojis.get(i, "?")
        role_name = role_names.get(i, "?")
        agent = s.get("agent_name", s.get("agent_id", "?")[:12])
        lines.append(f"\nStep {i} {role_emoji} {role_name}（{agent}）✅")
        output = s.get("output")
        if output and output.get("sha"):
            lines.append(f"  提交: `{output['sha']}` — {output.get('commit_msg', '')}")
        # URL 类产出
        url_fields = {"tech_plan_url": "技术方案", "review_url": "审查报告",
                      "test_report_url": "测试报告", "test_summary": "测试结果"}
        for k, label in url_fields.items():
            if output and output.get(k):
                lines.append(f"  产出: [{label}]({output[k]})")
        # 无 output 但有 result_msg 时回退
        result_msg = s.get("result_msg", "")
        if not (output and any(output.values())) and result_msg:
            lines.append(f"  结果: {result_msg[:80]}")
    lines.append("\n════════════════════")
    return "\n".join(lines)
```

**验证条件：**
- Step 2 派活：跳过（`step_num=2`, `i >= step_num` 不进入循环）
- Step 3 派活：仅显示 Step 2（已完成时）
- Step 5 派活：显示 Step 2~4（已完成的）
- 无前置完成时：输出空行

### 3.5 需求 D — 向后兼容

**已有数据安全：**

| 场景 | 处理方法 | 兼容性 |
|:-----|:---------|:------:|
| 旧 JSON 中 `output: null` | `step_info.get("output")` → `None` → output 部分跳过 | ✅ |
| 旧 JSON 中 `result_msg: ""` | `step_info.get("result_msg", "")` → `""` → 回退不显示 | ✅ |
| 旧 JSON 中缺失 `output` 字段 | `dict.get("output")` → `None` → output 部分跳过 | ✅ |
| 旧 JSON 中缺失 `result_msg` 字段 | `dict.get("result_msg", "")` → `""` | ✅ |
| 旧 `_build_rich_templates` 模板中无 `{stepN:field}` 占位符 | `_render_template` 中的正则找不到匹配，不变 | ✅ |
| 旧 `{round}`、`{requirements_url}` 等变量 | 保留原有 `vars` 字典 + `template.replace()` 逻辑，不受影响 | ✅ |
| R115 artifacts 存储逻辑 | 不动（L2466-2478 已有逻辑保持原样） | ✅ |
| R120 step 状态标记逻辑 | 不动（L2481-2491 已有逻辑保持原样） | ✅ |

---

## 4. 改动点汇总表（逐行）

| # | 文件 | 行号(约) | 改动类型 | 说明 |
|:-:|:----|:--------:|:--------:|:-----|
| 1 | main.py | L2479 (advance_step 前) | 新增 ~20 行 | 记录 step output + result_msg |
| 2 | main.py | L2646-2667 (_render_template) | 修改 + 新增 ~30 行 | 增强支持 `{stepN:field}` 变量 |
| 3 | main.py | L3074-3116 (_build_rich_templates) | 修改 ~12 行 | 硬编码表达式 → `{stepN:field}` 占位符 |
| 4 | main.py | L2736-2738 (_auto_dispatch) | 新增 ~5 行 | 调用 `_build_step_summary` 追加摘要 |
| 5 | main.py | 文件末尾/工具函数区 | 新增 ~30 行 | `_build_step_summary` 辅助函数 |

**合计改动量：~97 行（不含注释和空行）**

---

## 5. 验收验证

### 5.1 对应需求 A — Step 产出自动记录

| 验收项 | 验证方法 | 预期 |
|:------|:---------|:-----|
| A-1 | 发送完成消息含 `##sha=abc1234` | `ctx.steps[1]["output"]["sha"]` == `"abc1234"` |
| A-2 | 发送完成消息无 `##` | `ctx.steps[1]["result_msg"]` == 原文（≤200 字符） |
| A-3 | 验证 `mgr.save()` 后 JSON 内容 | `pipeline_contexts.json` 中 steps[i].output 正确序列化 |
| A-4 | R115 artifacts 完整性 | `ctx.artifacts["step2"]` 仍保存所有 `##key=value` |

### 5.2 对应需求 B — 动态模板重建

| 验收项 | 验证方法 | 预期 |
|:------|:---------|:-----|
| B-1 | 模板含 `{step2:tech_plan_url}`，Step 2 有 artifact | 渲染为实际 URL |
| B-2 | 模板含 `{step2:sha}`，Step 2 output.sha=abc | 渲染为 `"abc"` |
| B-3 | 模板含 `{step3:agent_name}` | 渲染为 Step 3 的 agent_name |
| B-4 | 无 artifacts 时 `{step2:tech_plan_url}` | 渲染为 `""`，if 条件判断不产生行 |
| B-5 | `{round}` 等旧变量 | 继续正常渲染 |

### 5.3 对应需求 C — 前置步骤摘要注入

| 验收项 | 验证方法 | 预期 |
|:------|:---------|:-----|
| C-1 | Step 3 派活消息 | 头部包含 Step 2 完成摘要行 |
| C-2 | Step 2 派活消息 | 头部不包含摘要（`_build_step_summary` 返回空） |
| C-3 | Step 6 派活消息 | 包含 Step 2~5 已完成 step 的摘要行 |
| C-4 | 前序 step 状态非 "done" | 该 step 不出现在摘要中 |

### 5.4 对应需求 D — 向后兼容

| 验收项 | 验证方法 | 预期 |
|:------|:---------|:-----|
| D-1 | 旧 JSON 含 `output: null` | 正常加载，摘要显示跳过 |
| D-2 | 旧 JSON 不含 `result_msg` 字段 | `get("result_msg", "")` 正常 |
| D-3 | 旧模板（R122 已存） | 无 `{stepN:}` 占位符，原样渲染 |

---

## 6. 不做事项（明确排除）

| 排除项 | 理由 |
|:-------|:-----|
| ❌ 修改 `pipeline_context.py`（StepInfo / PipelineContext 数据结构） | 已有 `output`/`result_msg` 字段，仅补充写入逻辑 |
| ❌ Git 提交自动检测获取 SHA | 已在需求文档中排除，bot 手动提供 |
| ❌ 修改 Agent 卡/角色映射持久化 | 正交功能 |
| ❌ 验证钩子系统/自动测试 | 正交功能 |
| ❌ 修改 _build_rich_templates 参数签名或函数结构 | Option 1 方案不改变其签名 |

---

## 7. 开放讨论

| # | 问题 | 建议 | 决策 |
|:-:|:-----|:-----|:----:|
| 1 | `{step2:sha}` 格式 vs `{prev_sha}` 格式 | `{stepN:field}` 显式指定 step，可读性强，支持跨多 step 引用 | ✅ |
| 2 | 摘要太长时截断策略 | 默认显示所有已完成 step，不截断。≥5 步时建议 `...` 省略中间 | 🔲 |
| 3 | 同一 step 多次完成（Dev 迭代） | output 仅记录最后一次，之前 commit 只通过 result_msg 体现 | 🔲 |

---

> **审核记录：**
> - v1.0 提交审核：[2026-07-17]
