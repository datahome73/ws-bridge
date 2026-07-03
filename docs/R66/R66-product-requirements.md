# R66 产品需求 — 管线参数化完善 🎯

> **版本：** v1.0（初稿，待项目负责人审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-03
> **本轮改动范围：** `server/handler.py` + `server/config.py`（服务端管线层）
> **参考：** TODO.md v2.31、docs/ARCHITECTURE-REQUIREMENTS.md §3.3/§六 P0、R62 管线参数化经验

---

## 1. 问题背景

### 1.1 管线 Step 链仍被硬编码束缚

R62 实现了 `_PIPELINE_CONFIG` 与 `_PIPELINE_STATE` 分离，引入 frontmatter 解析器，但**管线 Step 链的实际定义仍严重依赖硬编码的 `config.PIPELINE_STEP_MAP`**：

```
!pipeline_start R{N}
    ↓
_parse_frontmatter(WORK_PLAN)  ← 解析 frontmatter，如果存在
    ↓ 有 frontmatter → _build_pipeline_config()  →  覆盖部分配置
    ↓ 无 frontmatter → _build_fallback_config()  → 从 PIPELINE_STEP_MAP 硬编码
    ↓
_PIPELINE_CONFIG[round_name]  ← 实际消费
    ↓
step_complete / step_handoff / pipeline_status
    ↓
读取 step_config → 仍依赖硬编码的 step_keys、primary/backup
```

| 依赖项 | 来源 | 能否被 frontmatter 覆盖 |
|:-------|:-----|:----------------------|
| Step 列表（step1~step6） | `PIPELINE_STEP_MAP` | ❌ 只能覆盖同名字段的配置，不能定义新的 Step 名称或数量 |
| 角色（arch/dev/review/qa/admin） | `PIPELINE_STEP_MAP` | ❌ 硬编码 5 角色体系 |
| primary/backup 换人策略 | `PIPELINE_STEP_MAP` | ❌ 每步的主要/备用角色在代码中写死 |
| 超时配置 | `PIPELINE_STEP_MAP`（`timeout_hours`） | 🟡 可被 frontmatter 覆盖 |
| Step 标题 | `PIPELINE_STEP_MAP`（`name`） | 🟡 可被 frontmatter 覆盖 |
| 上下文 URL | 硬编码 + 模板变量 | 🟡 有限覆盖 |

**具体阻塞场景：**

1. **新轮次想减少 Step**（如纯回归测试只走 Step 5+6）→ 做不到，管线必须走完完整 6 步
2. **新轮次想增加 Step**（如插入「安全审查」新环节）→ 做不到，没有 `step7` 在映射表中
3. **新角色要加入管线**（如新增 `security_review` 角色）→ 做不到，角色硬编码在代码中
4. **不同轮次需要不同的 Step 排序** → 做不到，所有轮次走同一套 Step 链

### 1.2 R62 已建基础但未闭环

| R62 产物 | 状态 | 未闭环之处 |
|:---------|:----|:-----------|
| `_parse_frontmatter()` | ✅ 存在 | 只能解析顶层 `pipeline:` 下的字段，step 列表无法动态定义 |
| `_build_pipeline_config()` | ✅ 存在 | 消费 `config.get("steps", {})`，但 step keys 最终仍需匹配 `PIPELINE_STEP_MAP` 中的 key 名 |
| `_build_fallback_config()` | ✅ 存在 | 从 `PIPELINE_STEP_MAP` 硬编码构建 step 列表——新轮次如果没有 frontmatter，走的就是这个退化路径 |
| 模板变量 `${pipeline.xxx}` | ✅ 支持 | 仅支持 `requirements_url` 等几个预定义变量，不支持 `${steps.stepN.output}` |
| `_PIPELINE_CONFIG` vs `_PIPELINE_STATE` | ✅ 分离 | 配置层已独立，但消费代码仍在多处回退到 `_load_step_config()` |

### 1.3 R65 自动推进 + 硬编码 Step = 矛盾

R65 实现了 git sync 驱动管线自动推进（`_auto_advance_pipeline`），但自动推进的逻辑是：

```
当前是 stepN → git 检测到新 commit → 自动推进到 stepN+1
                                                        ↑ 这里假设 stepN+1 一定是下一个 →
                                                          如果 step 可配置，自动推进逻辑
                                                          需要动态适配
```

当 Step 数量和名称可变时，`_auto_advance_pipeline` 中的「找下一个 Step」逻辑必须从**硬编码索引**切换为**动态从 frontmatter 读取**。

### 1.4 R64/R65 实战暴露的跨 Step 上下文缺失

R64/R65 实战中，PM 在每个 Step 交接时需要手动粘贴上下文给下一角色：

```
Step 2 技术方案 → 架构师产出 SHA: abc123
  ↓ PM 手动复制 SHA 到 Step 3 的点名消息中
Step 3 编码 → 开发工程师需要知道方案 SHA 和 URL
```

**重复工作：** 每次交接 PM 都要从上一 Step 的产出中提取关键信息，手动附加到点名消息中。如果 Server 自动做这件事，PM 的协调负担大幅降低。

---

## 2. 功能需求

### 设计原则

> **最小改动原则：** 不改 `PIPELINE_STEP_MAP` 结构本身（保持向后兼容），只改消费端使其优先从 frontmatter 读取。旧格式完全不需修改。
>
> **优先从 frontmatter：** 所有消费路径优先查 `_PIPELINE_CONFIG[round].steps`，找不到才回退到 `PIPELINE_STEP_MAP`。
>
> **增量迭代：** R66 不做「并行 Step」「条件分支」等复杂特性——只做 Step 链的可配置化 + 上下文自动注入。

---

### 方向 A（核心）：WORK_PLAN frontmatter 驱动完整 Step 链 🔴 P0

**目标：** WORK_PLAN 的 YAML frontmatter 可以定义**任意数量、任意角色**的 Step 序列。新轮次不再依赖 `PIPELINE_STEP_MAP` 的 6 步模板。

#### A1 — frontmatter 扩展：`pipeline.steps` 支持完整定义

**位置：** 新增 `_parse_steps_from_frontmatter()` 函数或修改 `_build_pipeline_config()`

```yaml
# 当前 frontmatter（简化）：
pipeline:
  steps:
    step1:
      role: admin
      title: 管线启动
```

```yaml
# 改造后 frontmatter（完整示例）：
pipeline:
  goal: "修复 ws-bridge 登录超时 Bug"
  branch: dev
  steps:
    step1:
      role: admin
      title: 管线启动
      timeout_minutes: 30
    step2:
      role: arch
      title: 问题分析
      primary: arch
      backup: dev
      context:
        bug_report_url: "${pipeline.bug_report_url}"
      timeout_minutes: 60
      output_desc: "根因分析文档"
    step3:
      role: dev
      title: 修复编码
      primary: dev
      backup: arch
      context:
        requirements_url: "${pipeline.requirements_url}"
        tech_plan_url: "${pipeline.tech_plan_url}"
      timeout_minutes: 180
      output_desc: "修复代码 + 测试"
    # 👆 可以只写 3 步，也可以写 7 步，完全由 frontmatter 决定
```

**关键增强：** `pipeline.steps` 不再覆盖 `PIPELINE_STEP_MAP` 的同名字段——它直接定义完整的 Step 序列。`PIPELINE_STEP_MAP` 只在退化和旧格式兼容时使用。

#### A2 — Step 序列动态化：消费端解除硬编码

**位置：** `_cmd_step_complete()`、`_cmd_step_handoff()`、`_cmd_pipeline_status()`、`_auto_advance_pipeline()` 中的 Step 链读取路径

```python
# 改造前（handler.py 多处重复此模式）：
_pconfig_s = _PIPELINE_CONFIG.get(round_name, {}).get("steps", {})
if _pconfig_s:
    step_config = _pconfig_s
else:
    step_config = _load_step_config()  # ← 从 PIPELINE_STEP_MAP 硬编码
step_keys = sorted(step_config.keys(), key=_step_sort_key)

# 改造后——提取为公共函数 _get_step_config(round_name):
def _get_step_config(round_name: str) -> dict:
    """返回 round 的 step 配置 dict。优先 frontmatter，其次硬编码。
    Returns: {step_key: {role, title, primary, backup, context, ...}}
    """
    pconfig = _PIPELINE_CONFIG.get(round_name, {})
    psteps = pconfig.get("steps", {})
    if psteps:
        return psteps
    # 退化：没有 frontmatter step 定义 → 从 PIPELINE_STEP_MAP 构建
    return _build_fallback_steps(round_name)
```

**所有消费位置（共 6 处）统一替换为调用 `_get_step_config()`：**

| 位置 | 功能 | 改动量 |
|:-----|:-----|:------|
| `_cmd_step_complete()` ~L2255 | 完成 Step → 找下一角色 | ~3 行 |
| `_cmd_step_handoff()` ~L2976 | 跳过 Step | ~3 行 |
| `_cmd_pipeline_status()` ~L3082 | 展示状态 | ~3 行 |
| `_auto_advance_pipeline()` ~L3200 | git sync 自动推进 | ~3 行 |
| `_cmd_pipeline_start()` ~L1937 | 启动时读取配置 | ~3 行 |
| `_cmd_step_reject()` / 退回处理 | 退回后找重试  | ~3 行 |

**共 ~18 行改动，6 处统一替换。**

#### A3 — `primary`/`backup` 从 frontmatter 读取

**位置：** 点名/交接时读取 `step_config[next_step]`

**当前逻辑（`_cmd_step_complete()` ~L2335-2340）：**
```python
primary_role = step_config[next_step].get("primary")
backup_role = step_config[next_step].get("backup")
```

**改造效果：** 已支持的字段无需改动。frontmatter 定义了 `primary`/`backup` 就用 frontmatter 的，没定义就为 None（仍然兼容当前行为——`_build_fallback_config` 不生成 primary/backup 字段，但 `_build_fallback_steps` 需要从 `PIPELINE_STEP_MAP` 同步过去）。

**注意：** `_build_fallback_steps()` 需要从 `PIPELINE_STEP_MAP` copy `primary`/`backup` 字段到 fallback step config，确保旧格式兼容。

#### A4 — `_auto_advance_pipeline` Step 查找动态化

**位置：** R65 新增的自动推进函数

当前假设 `stepN` → `stepN+1` 是固定映射。改造后从前面的 `_get_step_config()` + `_step_sort_key()` 读取 Step 列表，动态找下一个。

```python
# 改造前：
next_step = f"step{int(current_step.replace('step', '')) + 1}"

# 改造后：
step_config = _get_step_config(round_name)
step_keys = sorted(step_config.keys(), key=_step_sort_key)
current_idx = next(i for i, k in enumerate(step_keys) if k == current_step)
if current_idx + 1 < len(step_keys):
    next_step = step_keys[current_idx + 1]
```

---

### 方向 B（核心）：Step 产出上下文自动注入 🟡 P1

**目标：** Step 完成后，其产出（commit SHA、文档 URL）自动注入下一步的 baseline 上下文，PM 不再手动粘贴。

#### B1 — 定义 `output_schema`

**位置：** frontmatter 的 step 定义字段扩展

在 frontmatter 中，每个 Step 可以声明自己的产出格式：

```yaml
pipeline:
  steps:
    step2:
      role: arch
      title: 技术方案
      output_schema:
        sha: "${steps.step2.sha}"
        tech_plan_url: "${steps.step2.tech_plan_url}"
    step3:
      role: dev
      title: 编码
      context:
        requirements_url: "${pipeline.requirements_url}"
        tech_plan_url: "${steps.step2.tech_plan_url}"
        tech_plan_sha: "${steps.step2.sha}"
```

**模板变量扩展：** 新增 `${steps.stepN.sha}`、`${steps.stepN.output}`、`${steps.stepN.xxx}` 变量，在运行时根据 `_PIPELINE_STATE` 中的产出记录解析。

#### B2 — Step 产出自动解注入

**位置：** `_cmd_step_complete()` Step 交接点名时

`!step_complete step2 --output abc123` 执行后：

1. 记录产出到 `_PIPELINE_STATE[round]["step_outputs"]`
2. 在创建 Step 3 的点名消息时，用 Step 2 的产出 + `context` 模板变量 → 生成完整上下文
3. 点名消息自动包含：

```
@dev 🚨 Step「编码」到你了！

📄 需求：<requirements_url>
🏗️ 技术方案：<tech_plan_url> (SHA: abc123)

请按技术方案完成编码，产出推 dev 后 !step_complete step3 --output <sha>
```

**注意：** 当前点名消息的格式生成在 `_cmd_step_complete()` 中的 `_build_rollcall_message()` 或内联文本拼接处。B2 需要修改这些文本拼接处，注入动态上下文。

#### B3 — `!pipeline_status` 展示 Step 产出

**位置：** `_cmd_pipeline_status()` 输出增强

```diff
 Step 2: 技术方案  ✅ arch 完成
+ └─ 产出: abc123 — 根因分析文档
 Step 3: 编码     ▶ dev 进行中 (⏱ 剩余 45 分钟)
+  └─ 上下文: 需求@<url>, 技术方案@<url>(abc123)
```

---

### 方向 C（辅助）：旧格式兼容守卫 🟢 P2

**目标：** 所有新功能对**没有 frontmatter 的旧 WORK_PLAN** 零行为变化。

| 场景 | 预期行为 | 验证方式 |
|:-----|:---------|:---------|
| 旧 WORK_PLAN 无 frontmatter | `!pipeline_start R{N}` 触发 `_build_fallback_config`，行为与 R65 完全一致 | 启动管线、step_complete、handoff 等全部正常 |
| 旧 WORK_PLAN 有 frontmatter 但无 `pipeline.steps` | 同样走 fallback | `_PIPELINE_CONFIG[round].steps` 为空时 fallback |
| 旧 WORK_PLAN 有 partial frontmatter（部分字段） | 能覆盖的部分覆盖，不能覆盖的 fallback | 混合格式兼容 |

```python
def _get_step_config(round_name: str) -> dict:
    pconfig = _PIPELINE_CONFIG.get(round_name, {})
    psteps = pconfig.get("steps", {})
    if psteps:
        return psteps
    return _build_fallback_steps(round_name)
```

**关键：** `_build_fallback_steps()` 必须从 `PIPELINE_STEP_MAP` 中同步 `primary`/`backup` 字段——当前 `_build_fallback_config()` 没有做这件事，导致旧格式退化后 primary/backup 缺失。

---

## 3. 验收标准

### 🎯 方向 A — frontmatter 驱动 Step 链

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | frontmatter 定义 3 步（step1/step2/step3） | 管线启动后只展示 3 步，step3 完成后管线关闭 | 创建测试 WORK_PLAN → `!pipeline_start` → 验证 |
| ✅-2 | frontmatter 定义 7 步（step1~step7） | 管线正常走 7 步，不报错 | 同上 |
| ✅-3 | `_get_step_config()` 返回优先从 frontmatter 读取 | frontmatter 中定义了 step2 的 role="security_review" → 点名 security_review 角色 | 验证点名消息目标角色 |
| ✅-4 | `_get_step_config()` 在不含 frontmatter 的旧 WORK_PLAN 中返回 `PIPELINE_STEP_MAP` 的 6 步 | 旧格式管线启动正常，行为零变化 | 用旧 WORK_PLAN → 验证 step_keys 仍为 step1~step6 |
| ✅-5 | `_get_step_config()` 的 fallback 包含 `primary`/`backup` 字段 | `PIPELINE_STEP_MAP` 中配置的 primary/backup 在 fallback 中可用 | 旧格式管线交接时正确启用主备 |
| ✅-6 | 所有 6 个消费位置统一替换为 `_get_step_config()`（无遗漏） | `grep '_load_step_config\\|PIPELINE_STEP_MAP' handler.py` 只在 fallback 和 config 内部出现 | 代码审查 |
| ✅-7 | 自动推进 `_auto_advance_pipeline()` 动态找下一步 | 4 步管线 auto-advance 正确从 step2→step3→step4→管线关闭 | 在 4 步管线中触发 git sync |
| ✅-8 | 非 step 名称（如 `step10`）正确处理 | `_step_sort_key` 排序正确 | 前端 frontmatter 定义 step10 → 排序在 step9 后 |

### 🎯 方向 B — Step 产出上下文注入

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-9 | `!step_complete step2 --output abc123` 后产出自动记录 | `_PIPELINE_STATE[round]["step_outputs"]["step2"]` 包含 `{sha: "abc123", ...}` | 代码审查 + `!pipeline_status --dump` 验证 |
| ✅-10 | Step 3 点名消息自动包含 Step 2 的产出 | 点名消息含「🏗️ 技术方案：<url> (SHA: abc123)」 | 实测 |
| ✅-11 | `${steps.step2.sha}` 模板变量正确解为 Step 2 的 commit SHA | frontmatter 中的模板变量在点名时被替换 | 实测 |
| ✅-12 | `${steps.step2.sha}` 在 Step 2 尚未完成时返回空字符串（容错） | 点名消息不显示失效的变量引用 | 在 Step 2 未完成时测试 context 渲染 |
| ✅-13 | `!pipeline_status` 展示 Step 产出 | 输出含「产出: abc123 — 根因分析文档」 | 实测 |

### 🎯 方向 C — 旧格式兼容

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-14 | 无 frontmatter 的旧 WORK_PLAN → 管线启动正常 | 行为与 R65 完全一致 | 用旧 WORK_PLAN 走完整管线 |
| ✅-15 | 旧格式管线启用主备换人 | `primary`/`backup` 字段在 fallback 中正确传播 | R56~R65 任意旧 WORK_PLAN 验证 |
| ✅-16 | partial frontmatter（有 pipeline 但无 steps） | 正常 fallback 到 6 步 | 创建半格式 WORK_PLAN 测试 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| 并行 Step | 同时执行多个不依赖的 Step | 复杂度高，留到后续轮次 |
| 条件分支 | Step 完成后根据条件走不同分支 | 过度工程，当前不需要 |
| Agent Card 持久化 | 角色映射持久化到磁盘 | R63 已有 schema，后续轮次专门处理 |
| Agent 注册/API Key 体系 | 新 agent 注册和认证 | 独立轮次（参考 ARCHITECTURE-REQUIREMENTS.md §3.8） |
| Web 端管线仪表盘 | Step 进度条等可视化 | 独立轮次 |
| Gateway 层改动 | gateway-plugin/* | 本轮不动网关层 |
| 前端/Web UI 改动 | templates.py / web_viewer.py 前端 | 纯后端改动 |
| R65 git sync 优化 | git sync 的稳定性增强 | 超出本轮范围 |

---

## 5. 管线计划

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **Step 1** | 📋 PM | WORK_PLAN.md | 20min |
| **Step 2** | 👷 Arch | 技术方案 + 代码实现 | 30min |
| **Step 3** | 👨‍💻 Dev | 编码实现 | 40min |
| **Step 4** | 👀 Review | 代码审查 | 15min |
| **Step 5** | 🦐 QA | 测试报告 | 15min |
| **Step 6** | 🛠️ Admin | 合并 dev→main，部署 | 15min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **修改** — 新增 `_get_step_config()` 公共函数 + 6 处消费位置统一替换 + `_build_fallback_steps()` + B2 上下文注入逻辑 + 模板变量渲染 | ~100 行净增，~30 行修改 |
| `server/config.py` | **修改** — 可能新增 R66 配置开关 | ~5 行 |
| `docs/R66/*` | **新增** — 需求文档 + WORK_PLAN + 技术方案 | ~200 行 |
| **合计** | | **~100 行代码净增，6 处统一替换** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| `_get_step_config()` 遗漏某消费位置 | 某功能仍引用旧 `PIPELINE_STEP_MAP` | `grep '_load_step_config\\|PIPELINE_STEP_MAP'` 验证零残留，dev 实测管线全流程 |
| frontmatter 定义 7 步但 handler 中有硬编码索引假设 | auto-advance 或 step_complete 报错 | 替换所有硬编码索引为动态 `_get_step_config() + _step_sort_key` |
| 旧格式 `_build_fallback_steps()` 漏了 primary/backup | 旧格式管线失去主备切换能力 | 从 `PIPELINE_STEP_MAP` 同步 primary/backup，单元测试验证 |
| 上下文注入在 Step 首次启动时引用未完成的 Step 产出 | 点名消息中出现空或错误的变量值 | 未完成的 Step 产出返回空字符串，点名消息不报错 |
| frontmatter 定义 Step 时 key 名不连续（如 step2、step4 跳 step3） | auto-advance 行为异常 | 按 key 排序后顺序推进——跳步不会自动化，需 `!step_handoff`。这是合理的约束 |

---

## 6. 脱敏检查清单

- [ ] docs/R66/*.md 零内部名残留
- [ ] `grep -n '内部名' docs/R66/*.md` 零匹配
- [ ] handler.py diff 零内部 URL/端口泄露
