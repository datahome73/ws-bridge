# R66 产品需求 — 管线参数化完善 🎯

> **版本：** v1.0（初稿，待项目负责人审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-03
> **本轮改动范围：** `server/handler.py`（管线层 6 处消费点统一替换）
> **参考：** docs/ARCHITECTURE-REQUIREMENTS.md §六 P0、R62 管线参数化经验、R65 git sync 自动推进

---

## 1. 问题背景

### 1.1 现状：Step 链硬编码，轮次间无法差异化

当前管线 Step 链完全由 `config.PIPELINE_STEP_MAP` 硬编码的 6 步模板驱动：

```python
PIPELINE_STEP_MAP = {
    "step1": {"role": "admin", "name": "管线启动", ...},
    "step2": {"role": "arch",  "name": "技术方案", ...},
    "step3": {"role": "dev",   "name": "编码", ...},
    "step4": {"role": "review","name": "代码审查", ...},
    "step5": {"role": "qa",    "name": "测试验证", ...},
    "step6": {"role": "admin", "name": "合并部署归档", ...},
}
```

所有轮次（R55~R65）走的都是同一份 Step 链，轮次之间无法差异化：

| 需求场景 | 当前状态 | 能否实现 |
|:---------|:---------|:--------:|
| 纯回归验证轮次（只需 Step 5+6） | ❌ 必须跑完 6 步 | 不行 |
| 插入「安全审查」新环节 | ❌ step7 不在映射表中 | 不行 |
| 新角色加入管线（security_review） | ❌ 角色硬编码在代码中 | 不行 |
| 不同轮次不同 Step 排序 | ❌ 全走同一序列 | 不行 |

### 1.2 根因分析：frontmatter 已解析但未闭环驱动

R62 实现了 `_parse_frontmatter()` + `_build_pipeline_config()`，但 frontmatter 的 step 定义**只能覆盖同名字段的配置，不能定义全新的 Step 序列**：

| 组件 | R62 状态 | 未闭环之处 |
|:-----|:--------|:-----------|
| `_parse_frontmatter()` | ✅ 存在 | 只解析 `pipeline:` 字段，step 列表不能动态自定 |
| `_build_pipeline_config()` | ✅ 存在 | 消费 `config.get("steps", {})`，但 step keys 仍必须匹配 `PIPELINE_STEP_MAP` 中的 key 名 |
| `_build_fallback_config()` | ✅ 存在 | 从 `PIPELINE_STEP_MAP` 硬编码构建——新轮次无 frontmatter 就走此路 |
| 模板变量 `${pipeline.xxx}` | ✅ 支持 | 仅支持 `requirements_url` 等几个变量，不支持 `${steps.stepN.output}` |
| 6 处消费位置 | ❌ 各自独立读取 | `step_complete/handoff/status/auto_advance/pipeline_start/reject` 每处都有自己的 `if pconfig else fallback` 逻辑 |

**核心矛盾：** R65 git sync 实现了自动推进，但推进的 Step 链仍然是硬编码的。「自动走 6 步」可以，「自动走 3 步」不行。

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:----|:------|
| 🔴 **管线通用化瓶颈** | ws-bridge 要向通用 A2A 平台发展，第一步就是 Step 链可配置 |
| 🔴 **每轮冗余** | PM 每轮花 10 分钟写 WORK_PLAN，但 Step 列表从不能用 |
| 🟡 **上下文断裂** | Step 交接时 PM 需手动粘贴上一轮产出——本应是自动的事 |
| 🟢 **改动集中** | 统一提取 `_get_step_config()` 公共函数，6 处原位替换，不入侵逻辑 |
| 🟢 **退化安全** | 旧 WORK_PLAN 无 frontmatter → 完美降级为 6 步，零行为变化 |

---

## 2. 功能需求

### 设计原则

> **优先从 frontmatter：** 所有消费路径优先查 `_PIPELINE_CONFIG[round].steps`，找不到再回退到 `PIPELINE_STEP_MAP`。旧格式零改动。
>
> **增量迭代：** 不做并行 Step、条件分支——只做 Step 链可配置 + 上下文自动注入。
>
> **提取公共函数：** 6 处重复的 step 配置读取逻辑统一为 `_get_step_config()`，后续新增功能无需重复。

---

### 方向 A（核心）：WORK_PLAN frontmatter 驱动完整 Step 链 🔴 P0

**核心思路：** WORK_PLAN 的 YAML frontmatter 可以直接定义**任意数量、任意角色**的 Step 序列。`PIPELINE_STEP_MAP` 仅作为没有 frontmatter 时的退化配置。

#### A1 — frontmatter step 定义扩展

**位置：** 新增 `_get_step_config(round_name)` 公共函数

```yaml
# 改造后 frontmatter 示例（3 步轻量管线）：
pipeline:
  goal: "修复登录超时 Bug"
  branch: dev
  steps:
    step2:
      role: arch
      title: 问题分析
      primary: arch
      backup: dev
      timeout_minutes: 60
      context:
        bug_report_url: "${pipeline.bug_report_url}"
      output_desc: "根因分析文档"
    step3:
      role: dev
      title: 修复编码
      primary: dev
      backup: arch
      timeout_minutes: 180
      context:
        requirements_url: "${pipeline.requirements_url}"
        tech_plan_url: "${steps.step2.tech_plan_url}"
        tech_plan_sha: "${steps.step2.sha}"
      output_desc: "修复代码 + 测试"
    step4:
      role: qa
      title: 验证测试
      primary: qa
      backup: review
      timeout_minutes: 120
      output_desc: "测试报告"
```

| 增强点 | 当前 frontmatter | 改造后 |
|:-------|:-----------------|:-------|
| Step 数量 | 只能覆盖 step1~step6 的字段 | 可定义任意 Step 名（step2/step3/step4 或 step_a/step_b） |
| Step 角色 | 被 PIPELINE_STEP_MAP 限制 | 任意角色名，新角色可直接用 |
| primary/backup | 需在 PIPELINE_STEP_MAP 中硬编码 | frontmatter 中每步独立配置 |
| timeout/context | 可覆盖 | 可覆盖，且 context 支持跨 Step 引用 |

#### A2 — 公共函数 `_get_step_config()` 提取

**位置：** 新增函数，所有消费点统一调用

```python
# 新增公共函数
def _get_step_config(round_name: str) -> dict:
    """
    返回 round 的 step 配置 dict。优先 frontmatter，其次硬编码。
    Returns: {step_key: {role, title, primary, backup, context, ...}}
    退化: 无 frontmatter → _build_fallback_steps() → PIPELINE_STEP_MAP
    """
    pconfig = _PIPELINE_CONFIG.get(round_name, {})
    psteps = pconfig.get("steps", {})
    if psteps:
        return psteps
    return _build_fallback_steps(round_name)


# _build_fallback_steps() 新增——从 PIPELINE_STEP_MAP 构建，同时同步 primary/backup
def _build_fallback_steps(round_name: str) -> dict:
    """构建兼容旧格式的 step config（不含 step1）。"""
    step_map = config.PIPELINE_STEP_MAP
    steps = {}
    for step_key, step_cfg in step_map.items():
        if step_key == "step1":
            continue
        steps[step_key] = {
            "role": step_cfg.get("role", ""),
            "title": step_cfg.get("name", step_key),
            "primary": step_cfg.get("primary"),   # ← 新增：同步 primary
            "backup": step_cfg.get("backup"),     # ← 新增：同步 backup
            "context": {
                "requirements_url": _get_requirements_url(round_name),
                "work_plan_url": _get_work_plan_url(round_name),
            },
            "output_desc": "",
            "feedback_channel": "_admin",
            "timeout_minutes": int(step_cfg.get("timeout_hours", 6) * 60),
            "escalation": step_cfg.get("escalation", "notify_pm"),
        }
    return steps
```

**6 处消费位置统一替换：**

| 位置 | 当前代码 | 替换为 |
|:-----|:---------|:-------|
| `_cmd_step_complete()` ~L2255 | `_pconfig_s = ... ; if _pconfig_s: ... else: _load_step_config()` | `step_config = _get_step_config(round_name)` |
| `_cmd_step_handoff()` ~L2976 | 同上 | 同上 |
| `_cmd_pipeline_status()` ~L3082 | 同上 | 同上 |
| `_auto_advance_pipeline()` ~L3200 | 同上 | 同上 |
| `_cmd_pipeline_start()` ~L2032 | 同上 | 同上 |
| `_cmd_step_reject()` 退回处理 | 同上 | 同上 |

**共 ~18 行改动，6 处原位替换。** `_load_step_config()` 函数仍然保留但只在 `_build_fallback_steps()` 内部引用。

#### A3 — 自动推进 `_auto_advance_pipeline()` 动态化

**位置：** R65 新增的自动推进函数

```python
# 改造前：硬编码 stepN → stepN+1
next_step = f"step{int(current_step.replace('step', '')) + 1}"

# 改造后：动态从 step config 取 next
step_config = _get_step_config(round_name)
step_keys = sorted(step_config.keys(), key=_step_sort_key)
current_idx = next(i for i, k in enumerate(step_keys) if k == current_step)
if current_idx + 1 < len(step_keys):
    next_step = step_keys[current_idx + 1]
```

`_step_sort_key` 已经存在（支持 step10 > step9 自然排序），可直接复用。

#### A4 — `primary`/`backup` 从 frontmatter 自动读取

**位置：** `_cmd_step_complete()` 中角色点名交接处

当前代码（~L2335-2340）已支持从 `step_config[next_step]` 读取 `primary`/`backup`：

```python
primary_role = step_config[next_step].get("primary")
backup_role = step_config[next_step].get("backup")
```

只要 step config 是从 frontmatter 读取的（通过 `_get_step_config()`），primary/backup 自然生效。**无需额外改动。**
退化路径 `_build_fallback_steps()` 从 `PIPELINE_STEP_MAP` 同步此字段，确保旧格式兼容。

| 场景 | primary/backup 来源 | 行为 |
|:-----|:--------------------|:-----|
| new WORK_PLAN 含 frontmatter steps | frontmatter 中每步自定 | 独立配置 |
| old WORK_PLAN 无 frontmatter | `PIPELINE_STEP_MAP`（通过 fallback） | ✅ 同步到 fallback |
| frontmatter 某步缺 primary/backup | 为 None → 回退为「点名全体」模式 | 兼容 |

---

### 方向 B（辅助）：Step 产出上下文自动注入 🟡 P1

**问题：** 当前 Step 交接时，PM 需手动从上一 Step 的产出中提取 SHA/URL 并粘贴到点名消息中。

**改造：** Step 完成后其产出自动记录，下一点名消息自动注入。

#### B1 — 产出记录

**位置：** `_cmd_step_complete()` 中

```python
# 在 step_complete 处理中，记录产出到 state
pstate = _PIPELINE_STATE.get(round_name, {})
step_outputs = pstate.setdefault("step_outputs", {})
step_outputs[step_name] = {
    "sha": output_ref,          # 来自 --output 参数或自动检测
    "timestamp": time.time(),
    "output_desc": step_config.get(step_name, {}).get("output_desc", ""),
}
```

#### B2 — 模板变量扩展：`${steps.stepN.xxx}`

**位置：** `_build_pipeline_config()` 或新的 `_render_step_context()` 函数

```python
def _render_context(context: dict, round_name: str, step_outputs: dict) -> dict:
    """解析 context 中的模板变量，用实际值替换。"""
    resolved = {}
    for ctx_key, ctx_value in context.items():
        if isinstance(ctx_value, str) and "${steps." in ctx_value:
            # ${steps.step2.sha} → step_outputs["step2"]["sha"]
            ref = ctx_value.replace("${steps.", "").rstrip("}")
            parts = ref.split(".")
            if len(parts) >= 2:
                step_key, field = parts[0], parts[1]
                step_out = step_outputs.get(step_key, {})
                resolved[ctx_key] = str(step_out.get(field, ""))
        elif isinstance(ctx_value, str) and "${pipeline." in ctx_value:
            # 原有逻辑不变
            ...
        else:
            resolved[ctx_key] = ctx_value
    return resolved
```

**渲染时机：** Step 交接点名消息生成时（`_cmd_step_complete` 中）
**未完成产出：** `step_outputs[step_key]` 不存在时返回空字符串（容错）

#### B3 — 点名消息增强

**位置：** `_cmd_step_complete()` 中消息拼接处

```diff
点名消息从：
 @dev Step 3「编码」到你了！
  📄 需求：<url>
  📋 WORK_PLAN：<url>

改造为：
 @dev Step 3「编码」到你了！
  📄 需求：<url>
  📋 WORK_PLAN：<url>
+ 🏗️ 技术方案：<tech_plan_url> (SHA: abc123)
```

**实现方式：** context 渲染后的 dict 在点名消息中格式化输出。有上下文值的行自动追加到消息末尾，空值跳过。

#### B4 — `!pipeline_status` 产出展示

```diff
  Step 2: 技术方案  ✅ arch 完成
+ └─ 产出: abc123 — 根因分析文档
  Step 3: 编码     ▶ dev 进行中
+   └─ 上下文: 需求@<url>, 方案@<url>(abc123)
```

---

### 方向 C（兼容）：旧格式零变化 🟢 P2

| 场景 | 预期行为 | 验证方式 |
|:-----|:---------|:---------|
| 旧 WORK_PLAN 无 frontmatter | `!pipeline_start` → `_build_fallback_steps()` → 6 步，行为与 R65 完全一致 | 用 R65 WORK_PLAN 启动管线 |
| 有 frontmatter 但无 `pipeline.steps` | 同样走 fallback 6 步 | `_PIPELINE_CONFIG[round].steps` 为空时 |
| 有 partial frontmatter | 能覆盖的部分覆盖，不能的 fallback | 混合格式 |
| 旧格式下 primary/backup 正常 | `_build_fallback_steps()` 从 `PIPELINE_STEP_MAP` 同步 primary/backup | R56~R65 任意旧 WORK_PLAN 验证 |

```python
def _get_step_config(round_name: str) -> dict:
    pconfig = _PIPELINE_CONFIG.get(round_name, {})
    psteps = pconfig.get("steps", {})
    if psteps:
        return psteps
    return _build_fallback_steps(round_name)
```

**关键缺失修复：** 当前 `_build_fallback_config()` 没有从 `PIPELINE_STEP_MAP` 同步 `primary`/`backup` 字段，导致旧格式退化后主备切换功能失效。`_build_fallback_steps()` 同步此字段是必要的修复。

---

## 3. 验收标准

### 🎯 3.1 方向 A（frontmatter 驱动 Step 链）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | frontmatter 定义 3 步管线（step2/step3/step4）→ 管线只走 3 步 | step4 完成后直接关闭，不报错 | 创建 3 步 frontmatter → `!pipeline_start` → 验证 |
| ✅-2 | frontmatter 定义 7 步管线（step1~step7）→ 正常走 7 步 | 不报错 | 同上 |
| ✅-3 | frontmatter 定义新角色 `security_review` | `!step_complete` 点名 security_review 角色 | 验证点名消息目标 |
| ✅-4 | `_get_step_config()` 无 frontmatter → fallback 6 步 | 行为与 R65 完全一致 | 旧 WORK_PLAN 启动 |
| ✅-5 | `_get_step_config()` fallback 包含 primary/backup | 旧格式主备切换正常 | 模拟主角离线 → 备用自动接替 |
| ✅-6 | 6 处消费位置全部替换：零 `_load_step_config()` 残留 | `grep '_load_step_config' handler.py` 只在 `_build_fallback_steps` 内部出现 | 代码审查 |
| ✅-7 | auto-advance 动态找下一步 | 3 步管线中 auto-advance 正确走 step2→step3→step4→管线关闭 | 触发 git sync |
| ✅-8 | frontmatter 定义 step_a/step_b/step_c 自定义 Step 名 | 管线正常走 | 实测 |

### 🎯 3.2 方向 B（Step 产出上下文注入）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-9 | `!step_complete step2 --output abc123` 后产出自动记录 | `step_outputs["step2"] = {sha: "abc123", ...}` | `!pipeline_status --dump` 或代码验证 |
| ✅-10 | Step 3 点名消息自动含 Step 2 产出 | 消息中有「🏗️ 技术方案：<url> (SHA: abc123)」 | 实测 |
| ✅-11 | `${steps.step2.sha}` 模板变量正确解为 Step 2 SHA | context 渲染后变量被替换 | 实测 |
| ✅-12 | 未完成 Step 的产出变量返回空字符串（容错） | 点名消息不出现「undefined」或错误拼接 | 在 Step 2 未完成时触发 Step 3 |
| ✅-13 | `!pipeline_status` 展示 Step 产出 | 输出含「产出: abc123 — 根因分析文档」 | 实测 |

### 🎯 3.3 方向 C（旧格式兼容）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-14 | 无 frontmatter 旧 WORK_PLAN → 管线启动正常 | 行为与 R65 一致 | 用 R65 WORK_PLAN 走完整管线 |
| ✅-15 | 旧格式主备切换正常 | primary/backup 正确 | 模拟离线换人 |
| ✅-16 | partial frontmatter（有 pipeline 但无 steps） | 正常 fallback 6 步 | 创建半格式 WORK_PLAN |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| 并行 Step | 同时执行多个不依赖的 Step | 复杂度高，留后续 |
| 条件分支 | Step 完成后不同条件走不同分支 | 过度工程 |
| Agent Card 持久化 | 角色映射持久化到磁盘 | 独立轮次 |
| Agent 注册/API Key | 新 agent 注册和认证 | 独立轮次（§3.8） |
| Web 端管线仪表盘 | Step 进度条可视化 | 独立轮次 |
| Gateway 层 | gateway-plugin/ | 本轮不动 |
| 前端/Web UI | templates.py / web_viewer.py | 纯后端改动 |
| R65 git sync 优化 | 稳定性增强 | 超出本轮 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 20min |
| **2** | 👷 Arch | 技术方案 + 函数设计 | 30min |
| **3** | 👨‍💻 Dev | 编码实现 | 40min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 15min |
| **6** | 🛠️ Admin | 合并部署归档 | 15min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **修改** — 新增 `_get_step_config()` + `_build_fallback_steps()` + B1 产出记录 + B2/B3 上下文渲染 + 6 处原位替换 | ~100 行净增，~30 行修改 |
| `server/config.py` | **修改** — 可能新增 R66 开关 | ~5 行 |
| docs/R66/* | **新增** — 需求文档 + WORK_PLAN + 技术方案 + 测试报告 | ~200 行 |
| **合计** | | **~100 行代码净增，6 处替换** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| `_get_step_config()` 遗漏某消费位置 | 某功能仍引用旧 `PIPELINE_STEP_MAP` | `grep` 验证零 `_load_step_config` 残留 + 管线全流程实测 |
| frontmatter 定义非连续 Step key（step2 跳 step4）| auto-advance 行为异常 | 按 key 排序顺序推进——跳步非自动化，需 `!step_handoff`。合理约束 |
| `_build_fallback_steps()` 漏 primary/backup | 旧格式主备失效 | 从 `PIPELINE_STEP_MAP` 同步 |
| 未完成的 Step 产出被引用 | 点名消息含空/错误值 | 返回空字符串，点名消息容错 |

---

## 6. 脱敏检查清单

- [ ] docs/R66/*.md 零内部名残留
- [ ] `grep -n '内部名模式' docs/R66/*.md` 零匹配
- [ ] handler.py diff 零内部 URL/端口泄露
