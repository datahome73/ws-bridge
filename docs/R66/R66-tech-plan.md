# R66 技术方案 — 管线参数化完善 🏗️

> **版本：** v1.0
> **状态：** ✅ 定稿（arch 已交付）
> **架构师：** 👷 arch
> **日期：** 2026-07-03
> **基于需求：** docs/R66/R66-product-requirements.md v1.0 ✅
> **参考 WORK_PLAN：** docs/R66/WORK_PLAN.md v1.0 ✅
> **基于代码基：** `dev` branch, `server/handler.py` (5619 lines), `server/config.py` (135 lines)

---

## 1. 精确改动点总览

### 1.1 全部 6 处消费点（精确行号 + 当前代码模式）

| # | 函数 | 行号 | 当前模式 | 替换为 |
|:-:|:-----|:----:|:---------|:-------|
| **1** | `_cmd_step_complete()` | L2253-2259 | `_PIPELINE_CONFIG.get(rn, {}).get("steps", {})` → fallback `_load_step_config()` | `_get_step_config(round_name)` |
| **2** | `_cmd_step_handoff()` | L2975-2981 | 同上 | 同上 |
| **3** | `_cmd_pipeline_status()` | L3139 | 直接 `_load_step_config()`（活跃管线状态展示） | `_get_step_config(round_name)` |
| **4** | `_auto_advance_pipeline()` | L1291 | 直接 `_load_step_config()` | `_get_step_config(round_name)` |
| **5** | `_cmd_pipeline_start()` | L1980 | 直接 `_load_step_config()`（收集角色→组建工作室） | `_get_step_config(round_name)` |
| **6** | `_cmd_step_reject()` | L2815 | 直接 `_load_step_config()`（Step 存在性校验） | `_get_step_config(round_name)` |

### 1.2 当前 `_build_fallback_config()` 隐含 bug

**位置：** `handler.py` L1122-1151

```python
steps[step_key] = {
    "role": role,
    "title": step_cfg.get("name", step_key),
    "context": { ... },
    "output_desc": "",
    "feedback_channel": "_admin",
    "timeout_minutes": ...,
    "escalation": ...,
}
# ❌ 缺少 "primary" 和 "backup" 字段！
```

**影响：** `PIPELINE_STEP_MAP` 中每个 step 都定义了 `primary`/`backup`（config.py L76-85），但 `_build_fallback_config()` 没有同步这两个字段到 `_PIPELINE_CONFIG` 的 steps 中。R57 主备切换功能虽然从 `step_config[next_step].get("primary")` 读取（L2339-2340），但旧格式退化路径下 `_PIPELINE_CONFIG` 中没有这个字段，导致主备切换退化为「点名全体模式」。

**修复：** `_build_fallback_steps()`（新函数）会从 `PIPELINE_STEP_MAP` 同步 `primary`/`backup`。

---

## 2. 新增函数设计

### 2.1 `_get_step_config(round_name)` — 公共 Step 配置读取

**位置：** 插入在 `_step_sort_key()` 和 `_load_step_config()` 之间（≈L1160 附近）

```python
def _get_step_config(round_name: str) -> dict[str, dict]:
    """优先 frontmatter，其次 fallback。纯函数，不依赖外部状态。

    Returns:
        {step_key: {role, title, primary, backup, context, ...}}
        退化: 无 frontmatter → _build_fallback_steps()
    """
    pconfig = _PIPELINE_CONFIG.get(round_name, {})
    psteps = pconfig.get("steps", {})
    if psteps:
        return psteps
    return _build_fallback_steps(round_name)
```

**约束：**
- ✅ 纯函数：只读 `_PIPELINE_CONFIG`，无副作用
- ✅ 无 frontmatter → fallback → 零行为变化
- ✅ frontmatter 有 `steps` → 完整覆盖
- ✅ frontmatter 有 `pipeline` 但无 `steps` → `_PIPELINE_CONFIG[round].steps` 为 `{}` → fallback

### 2.2 `_build_fallback_steps()` — 从 PIPELINE_STEP_MAP 构建

**位置：** `_get_step_config()` 之后

```python
def _build_fallback_steps(round_name: str) -> dict[str, dict]:
    """从 PIPELINE_STEP_MAP 构建 fallback step 配置。
    与 _build_fallback_config() 同源但增加 primary/backup 同步。

    Returns:
        {step_key: {role, title, primary, backup, context, ...}}
    """
    step_map = _r42cfg.PIPELINE_STEP_MAP
    base_urls = {
        "requirements_url": f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-product-requirements.md",
        "work_plan_url": f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/WORK_PLAN.md",
    }
    steps = {}
    for step_key, step_cfg in step_map.items():
        if step_key == "step1":
            continue
        steps[step_key] = {
            "role": step_cfg.get("role", ""),
            "title": step_cfg.get("name", step_key),
            "primary": step_cfg.get("primary"),      # ← 新增：同步 primary
            "backup": step_cfg.get("backup"),          # ← 新增：同步 backup
            "context": {
                "requirements_url": base_urls["requirements_url"],
                "work_plan_url": base_urls["work_plan_url"],
            },
            "output_desc": "",
            "feedback_channel": "_admin",
            "timeout_minutes": int(step_cfg.get("timeout_hours", 6) * 60),
            "escalation": step_cfg.get("escalation", "notify_pm"),
        }
    return steps
```

**相比 `_build_fallback_config()` 的差异（重要）：**
| 字段 | `_build_fallback_config()` | `_build_fallback_steps()` |
|:-----|:--------------------------:|:-------------------------:|
| `primary` | ❌ 缺失 | ✅ `step_cfg.get("primary")` |
| `backup` | ❌ 缺失 | ✅ `step_cfg.get("backup")` |
| 返回值 | 整个 pipeline config dict | 仅 steps dict |
| 使用者 | `_cmd_pipeline_start()` 的旧格式路径 | `_get_step_config()` 的 fallback 路径 |

### 2.3 `_render_context()` — 模板变量渲染

**位置：** 新增函数，放在 `_get_step_config()` 附近

```python
def _render_context(context: dict, round_name: str, step_outputs: dict) -> dict:
    """解析 context 中的模板变量，返回渲染后的 dict。

    支持的变量格式：
        ${pipeline.xxx}       — pipeline-level 字段（requirements_url, work_plan_url 等）
        ${steps.stepN.xxx}    — 已完成 Step 的产出字段（sha, output_desc 等）

    Args:
        context: 原始 context dict（含模板变量）
        round_name: 管线标识（用于查 _PIPELINE_CONFIG）
        step_outputs: {step_key: {sha, timestamp, output_desc}}

    Returns:
        渲染后的 dict（变量被替换，不存在则返回空字符串）
    """
    pconfig = _PIPELINE_CONFIG.get(round_name, {})
    resolved = {}

    for ctx_key, ctx_value in context.items():
        if not isinstance(ctx_value, str):
            resolved[ctx_key] = ctx_value
            continue

        value = ctx_value

        # ${pipeline.xxx} — 原有逻辑
        if "${pipeline." in value:
            for match in _find_template_refs(value, "${pipeline."):
                ref_key = match  # 如 "requirements_url"
                ref_value = str(pconfig.get(ref_key, ""))
                value = value.replace("${pipeline." + ref_key + "}", ref_value)

        # ${steps.stepN.xxx} — 新增逻辑
        if "${steps." in value:
            for match in _find_template_refs(value, "${steps."):
                # match 如 "step2.sha"
                parts = match.split(".", 1)
                if len(parts) == 2:
                    step_key, field = parts
                    step_out = step_outputs.get(step_key, {})
                    replacement = str(step_out.get(field, ""))
                    value = value.replace("${steps." + match + "}", replacement)

        resolved[ctx_key] = value

    return resolved


def _find_template_refs(template_str: str, prefix: str) -> list[str]:
    """提取模板字符串中的所有变量引用名。"""
    import re
    refs = []
    start = 0
    while True:
        pos = template_str.find(prefix, start)
        if pos == -1:
            break
        end = template_str.find("}", pos)
        if end == -1:
            break
        ref = template_str[pos + len(prefix):end]
        refs.append(ref)
        start = end + 1
    return refs
```

**兼容性保障：**
- `${pipeline.xxx}` 保持原有行为不变
- `${steps.stepN.xxx}` 是纯增量扩展
- 找不到引用的变量 → `""` 空字符串（容错，不崩溃）
- 非字符串 context 值（如布尔值、数字）原样传递

---

## 3. 6 处消费点原位替换

### 3.1 替换模式模板

每一处的替换都是同一模式：

```diff
- # ── R62: Try _PIPELINE_CONFIG first, fallback to legacy ──
- _pconfig_s = _PIPELINE_CONFIG.get(round_name, {}).get("steps", {})
- if _pconfig_s:
-     step_config = _pconfig_s
- else:
-     step_config = _load_step_config()
+ step_config = _get_step_config(round_name)
```

### 3.2 各点精确替换

#### 点 1：`_cmd_step_complete()` — L2253-2259

```python
    # ── R66: Replace 3-line pattern with unified _get_step_config() ──
    step_config = _get_step_config(round_name)
```

**后续影响：** L2388-2390 处 `_pconfig_n.get("steps", {}).get(next_step, {})` 可直接读 `step_config` 但可保持原样（非关键路径），也可优化为 `step_config.get(next_step, {})`。

#### 点 2：`_cmd_step_handoff()` — L2975-2981

```python
    # ── R66: Replace 3-line pattern with unified _get_step_config() ──
    step_config = _get_step_config(round_name)
```

#### 点 3：`_cmd_pipeline_status()` — L3139

注意：此函数有两个 Step 配置读取点：
- **L3088** (`pconfig.get("steps", {})`) — 读取 `_PIPELINE_CONFIG` 中已存数据，显示 config-only 模式。**保持不动**。
- **L3139** (`_load_step_config()`) — 活跃管线状态展示，**替换**为 `_get_step_config(round_name)`。

```python
    # ── R66: Use unified _get_step_config() instead of _load_step_config() ──
    step_config = _get_step_config(round_name)
```

#### 点 4：`_auto_advance_pipeline()` — L1291

```python
    # ── R66: Use unified _get_step_config() instead of _load_step_config() ──
    step_config = _get_step_config(round_name)
    current_step = pstate.get("current_step", "")
```

**额外注意：** L1367 处 `step_config[next_step].get("role", "")` 将自动使用 frontmatter 定义的 role — 零改动。

#### 点 5：`_cmd_pipeline_start()` — L1980

```python
    # ── R66: Use unified _get_step_config() instead of _load_step_config() ──
    step_config = _get_step_config(round_name)
    all_roles = set()
    for step_key, step_cfg in step_config.items():
        role = step_cfg.get("role", "")
        if role and step_key != "step1":
            all_roles.add(role)
```

#### 点 6：`_cmd_step_reject()` — L2815

```python
    # ── R66: Use unified _get_step_config() — support frontmatter-defined steps ──
    step_config = _get_step_config(round_name)
    if step_name not in step_config:
        return f"❌ Step「{step_name}」不存在于当前管线配置中"
```

---

## 4. 方向 A4：`_auto_advance_pipeline()` Step 查找动态化

**位置：** L1296-1306（当前是 `step_keys.index(current_step)` + 简单索引 +1）

```diff
    step_config = _get_step_config(round_name)
    current_step = pstate.get("current_step", "")
    if not current_step:
        return ""

-   # 获取当前 Step 在 step_config 中的索引
+   # R66: 动态从 step config 查找下一步（支持非连续 Step key）
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
    try:
        idx = step_keys.index(current_step)
    except ValueError:
        return ""

    if idx + 1 >= len(step_keys):
        return ""  # 已是最后一步

    next_step = step_keys[idx + 1]
```

**说明：** 现有逻辑已经使用 `step_keys = sorted(step_config.keys(), key=_step_sort_key)` + `step_keys.index()` 查找下一步。**替换 `_load_step_config()` 为 `_get_step_config()` 后，此逻辑自动适配 frontmatter 定义的任意 Step 序列。**

不需要额外修改——`_step_sort_key()` 已支持 `step10 > step9` 自然排序。对于非数字 Step 名（如 `step_a`），排序时排在数字之后。

---

## 5. 方向 B1：Step 产出自动记录

**位置：** `_cmd_step_complete()` 中成功处理后（≈L2250 附近，`pstate.pop("backup_active", None)` 之后）

```python
    # ── R66 B1: Record step output ──
    pstate = _PIPELINE_STATE.get(round_name)
    if pstate:
        step_outputs = pstate.setdefault("step_outputs", {})
        step_outputs[step_name] = {
            "sha": output_ref or "",
            "timestamp": time.time(),
            "output_desc": step_config.get(step_name, {}).get("output_desc", ""),
        }
```

**注意：** `step_config` 此时已经是 `_get_step_config(round_name)` 的返回值（来自替换后），所以 `step_config.get(step_name, {})` 自然拿到 frontmatter 中定义的 `output_desc`。

---

## 6. 方向 B2/B3：点名消息上下文注入

### 6.1 B2：Context 渲染时机

**位置：** `_cmd_step_complete()` 中 `primary_role = step_config[next_step].get("primary")` 之后（≈L2340），点名消息拼接之前

```python
    # ── R66 B2: Render context with template variables ──
    step_outputs = pstate.get("step_outputs", {}) if pstate else {}
    next_context = step_config.get(next_step, {}).get("context", {})
    rendered_context = _render_context(next_context, round_name, step_outputs)
```

### 6.2 B3：点名消息增强

**位置：** 点名消息拼接处（≈L2394-2412，`mention_msg` 构建区域）

```python
    # ── R66 B3: Append rendered context to rollcall message ──
    context_lines = []
    for ctx_key, ctx_value in rendered_context.items():
        if ctx_value:
            # 取 key 的可读标签
            label_map = {
                "requirements_url": "📄 需求",
                "work_plan_url": "📋 WORK_PLAN",
                "tech_plan_url": "🏗️ 技术方案",
                "bug_report_url": "🐛 Bug 报告",
            }
            label = label_map.get(ctx_key, f"📎 {ctx_key}")
            context_lines.append(f"  {label}: {ctx_value}")
    if context_lines:
        mention_msg += "\n" + "\n".join(context_lines)
```

### 6.3 B3（handoff）：`_cmd_step_handoff()` 同步增强

**位置：** L3027-3029 处

```python
    # ── R66 B2/B3: Render context for handoff rollcall ──
    pstate = _PIPELINE_STATE.get(round_name, {})
    step_outputs = pstate.get("step_outputs", {})
    next_context = step_config.get(next_step, {}).get("context", {})
    rendered_context = _render_context(next_context, round_name, step_outputs)
    context_lines = []
    for ctx_key, ctx_value in rendered_context.items():
        if ctx_value:
            context_lines.append(f"  📎 {ctx_key}: {ctx_value}")
    context_suffix = "\n" + "\n".join(context_lines) if context_lines else ""

    rollcall_result = await _cmd_rollcall_next(sender_id, {
        "_positional": [next_role],
        "context": f"{round_name} {next_step}: {context_summary}{context_suffix}",
    })
```

---

## 7. 方向 B4：`!pipeline_status` 产出展示

**位置：** `_cmd_pipeline_status()` 中，在活跃 Step 列表展示之后（≈L3175+）

```python
    # ── R66 B4: Display step outputs in status ──
    step_outputs = pstate.get("step_outputs", {})
    if step_outputs:
        lines.append(f"  📦 Step 产出:")
        for out_step_key, out_info in sorted(step_outputs.items(), key=lambda x: _step_sort_key(x[0])):
            sha = out_info.get("sha", "")[:7]
            desc = out_info.get("output_desc", "")
            if sha or desc:
                lines.append(f"    {out_step_key}: {sha}{' — ' + desc if desc else ''}")
```

---

## 8. `_load_step_config()` 残留验证

替换完成后，`grep -n '_load_step_config' server/handler.py` 应**仅**在以下位置出现：

| 行号 | 位置 | 原因 |
|:----:|:-----|:-----|
| L1164 | `_load_step_config()` 定义 | 函数定义本身，保留不变 |
| (内部) | `_build_fallback_steps()` 中 | 新函数仍需要引用 `PIPELINE_STEP_MAP`，但改用 `_r42cfg.PIPELINE_STEP_MAP` 直接引用而非通过 `_load_step_config()` |

**实际上 `_load_step_config()` 函数本身仍可保留**（作为简单封装），但所有 6 处消费点的调用全部替换为 `_get_step_config()`。可选方案：`_load_step_config()` 完全不再被引用后可以删除，但保留不碍事。

**验证命令：**
```bash
grep -n '_load_step_config' server/handler.py | grep -v 'def _load_step_config'
```
预期输出：**零结果**（提示 `def _load_step_config` 不匹配）

---

## 9. 关键函数签名总览

```python
# === 新增函数 ===
def _get_step_config(round_name: str) -> dict[str, dict]:
    """统一获取 Step 配置。优先 frontmatter，其次 fallback。"""

def _build_fallback_steps(round_name: str) -> dict[str, dict]:
    """从 PIPELINE_STEP_MAP 构建 fallback step 配置（含 primary/backup）。"""

def _render_context(context: dict, round_name: str, step_outputs: dict) -> dict:
    """解析 context 模板变量，返回渲染后 dict。"""

def _find_template_refs(template_str: str, prefix: str) -> list[str]:
    """提取模板字符串中所有变量引用名。"""

# === 不动函数（保留） ===
def _load_step_config() -> dict[str, dict]:
    """保留但不再被 6 处消费点引用。"""

def _build_fallback_config(...) -> dict:
    """保留，仍被 _cmd_pipeline_start() 旧格式路径使用。"""
```

---

## 10. 改动估算精确化

| # | 改动项 | 位置 | 类型 | 行数 |
|:-:|:-------|:-----|:----|:----:|
| 1 | 新增 `_get_step_config()` | handler.py ~L1160 | +新增 | ~8 行 |
| 2 | 新增 `_build_fallback_steps()` | handler.py ~L1170 | +新增 | ~22 行 |
| 3 | 新增 `_render_context()` + `_find_template_refs()` | handler.py ~L1200 | +新增 | ~45 行 |
| 4 | 点 1 替换 `_cmd_step_complete()` | L2253-2259 | 4→1 行 | -3 行 |
| 5 | 点 2 替换 `_cmd_step_handoff()` | L2975-2981 | 4→1 行 | -3 行 |
| 6 | 点 3 替换 `_cmd_pipeline_status()` | L3139 | 1→1 行 | 0 行 |
| 7 | 点 4 替换 `_auto_advance_pipeline()` | L1291 | 1→1 行 | 0 行 |
| 8 | 点 5 替换 `_cmd_pipeline_start()` | L1980 | 1→1 行 | 0 行 |
| 9 | 点 6 替换 `_cmd_step_reject()` | L2815 | 1→1 行 | 0 行 |
| 10 | B1 产出记录 | `_cmd_step_complete()` ~L2250 | +新增 | ~8 行 |
| 11 | B2/B3 上下文渲染+消息注入（complete） | ~L2340 | +新增 | ~18 行 |
| 12 | B2/B3 上下文渲染+消息注入（handoff） | ~L3027 | +新增 | ~12 行 |
| 13 | B4 status 展示 | ~L3175 | +新增 | ~10 行 |
| | **合计** | | | **~+120 行净增，-6 行删除** |

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| `_get_step_config()` 中 `psteps` 为 `{}` 时被判断为 falsy → 误走 fallback | frontmatter 中定义了空 steps 时丢失 | `if psteps:` 在 `{}` 时自然走 fallback，与需求一致 |
| `_build_fallback_steps()` 与 `_build_fallback_config()` 的 URL 逻辑不一致 | 退化路径下 URL 不匹配 | 前者用 `_R62_REPO_BASE` + `WORK_PLAN_REPO_URL` 拼接，后者接收 `base_urls` 参数。保持一致。 |
| `_cmd_pipeline_start()` L1980 中 `round_name` 尚未解析到 `_PIPELINE_CONFIG` | 新启动管线 `_PIPELINE_CONFIG` 可能已有（L1954 刚写入） | L1980 执行时 `_PIPELINE_CONFIG[round_name]` 已存在（L1954/L1960/L1967 都已赋值），安全 |
| frontmatter 定义 step_a/step_b → `_step_sort_key()` 对非数字 key 支持 | 排序顺序不可预期 | `_step_sort_key()` 当前 `re.match(r'step(\\d+)', key)` 非数字返回 `(0, key)`，排在所有数字 key 之前。可接受。 |

---

## 12. 验证命令

```bash
# 1. 零 _load_step_config 消费残留
grep -n '_load_step_config' server/handler.py | grep -v 'def _load_step_config'
# 预期: 零输出

# 2. 语法检查
python3 -c "import py_compile; py_compile.compile('server/handler.py', doraise=True)"
# 预期: 无错误

# 3. 旧格式兼容验证（无 frontmatter 的 WORK_PLAN）
# 用 R65 WORK_PLAN 启动管线 → _get_step_config() 走 _build_fallback_steps()
# → primary/backup 正确同步
```

---

## 13. 与 R65/R62 的关系

```
R62 ── _parse_frontmatter() + _build_pipeline_config() + _PIPELINE_CONFIG
 │        骨架：frontmatter 解析 → 存到 _PIPELINE_CONFIG
 │
R65 ── _auto_advance_pipeline()
 │        步态：git sync 自动推进状态机
 │
R66 ── _get_step_config() + _render_context() + 6 处统一替换
 │        筋肉：消费端全部走 frontmatter 驱动
 │        方向 A：任意长度/角色的 Step 链
 │        方向 B：Step 产出自动注入上下文
 │        方向 C：旧格式完美退化
 │
R67+ ─ 并行 Step / 条件分支 / Agent Card 持久化 / Web 仪表盘
```

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-03 | 初稿 — 基于 R66 需求 + WORK_PLAN + 代码基分析交付 |
