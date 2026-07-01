# R62 技术方案 — 管线参数化改造

> **版本：** v1.1（审阅确认回复 v1.0 → v1.1）
> **编写：** 🏗️ 小开
> **日期：** 2026-07-01
> **状态：** 📝 初稿
> **基于需求：** `docs/R62/R62-product-requirements.md` v1.0
> **基于 WORK_PLAN：** `docs/R62/WORK_PLAN.md` v1.0

---

## 0. 前置确认（开放问题确认）

| # | 问题 | 结论 |
|:-:|:-----|:-----|
| 0-1 | WORK_PLAN 的 YAML frontmatter 当前为 YAML 格式。用 `json.loads` 还是写轻量 YAML 解析器？ | **轻量 indent-based 解析器** — 因为 frontmatter 仅含 dict of dicts + string values，无需全 YAML 规范。不引入 `import yaml` 新依赖。 |
| 0-2 | `_PIPELINE_CONFIG` 是否持久化？ | **仅内存** — 与 `_PIPELINE_STATE` 生命周期相同，不写盘。进程重启后需要重新 `!pipeline_start`。 |
| 0-3 | 旧格式 fallback 的 `_build_fallback_config()` 是否也写入 `_PIPELINE_CONFIG`？ | **是** — 统一写入统一读取，避免调用链出现「走 config 还是走 step_config」的分叉判断。 |
| 0-4 | WORK_PLAN URL 和 requirements URL 的来源？ | WORK_PLAN URL 从 `!pipeline_start --work_plan_url` 获取；requirements URL 由 config 中的 `config.WORK_PLAN_REPO_URL` + round_name 拼接（与当前硬编码模式相同，只是从 config dict 读而非硬编码在 f-string 中）。 |
| 0-5 | 模板变量 `${pipeline.xxx}` 解析 — 是否支持递归引用（如 `${steps.step2.output}`）？ | **否** — R62 过渡轮次只做 `SimpleReplace`：`${pipeline.xxx}` 替换。`${steps.stepN.output}` 在 step_complete 时动态注入，不在 config 构建时解析。 |
| 0-6 | 新 frontmatter 的 WORK_PLAN.md 格式使用 JSON 还是 YAML？ | **使用 YAML 格式（当前 WORK_PLAN 已有的格式）**，通过轻量解析器解析。因为 JSON 格式的 frontmatter 在 markdown 中可读性差，且需求文档描述的原型是用 `json.dumps` 输出的格式。WORK_PLAN 已经包含 YAML 格式 frontmatter 示例。 |

---

## 方向 A：核心实现

### A1 — `_PIPELINE_CONFIG` 全局 dict

**位置：** `handler.py` L44 之后（紧邻 `_PIPELINE_STATE`）

```python
# ── R62: Pipeline config (read-only, separate from runtime state) ──
_PIPELINE_CONFIG: dict[str, dict] = {}  # round_name -> read-only config from WORK_PLAN
```

**变动：**
- 新增 ~3 行，与 `_PIPELINE_STATE` 并列
- 生命周期：创建于 `!pipeline_start`，进程内存，不被 `_clear_pipeline_state()` 清除

### A2 — `_parse_frontmatter()` 轻量解析器

**策略：** 用 `split('---')` + 自编 indent-based YAML 子集解析器。

**为什么不走 `json.loads`：** WORK_PLAN 的 frontmatter 已经是 YAML 格式（缩进、键值对、无引号）。转换为 JSON 再 parse 需要做 YAML→JSON 转换，复杂度等价于直接写一个轻量解析器。

**为什么不引入 `import yaml`：** Scope 纪律明确「无新 pip 包引入」和「代码中不新增 import yaml」。pyyaml 不是标准库。

**实现方案（~15 行）：**

```python
def _parse_frontmatter(content: str) -> dict:
    """Extract and parse YAML frontmatter from WORK_PLAN.md content.
    Supports: strings, nested dicts via indentation, list values.
    Returns: pipeline section dict or raises NoFrontmatterError.
    """
    # Step 1: Extract the frontmatter block (--- ... ---)
    parts = content.split('---')
    if len(parts) < 3:
        raise NoFrontmatterError("No YAML frontmatter block found")
    
    frontmatter_text = parts[1].strip()
    
    # Step 2: Simple indent-based YAML subset parser
    # Only handles: key: value, nested key: value (2-space indent), 
    # list items with "- " prefix
    import re
    
    lines = frontmatter_text.split('\n')
    result = {}
    stack = [(0, None, result)]  # (indent, parent_key, current_dict)
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        
        # Calculate indentation level (number of leading spaces / 2)
        indent = len(line) - len(line.lstrip(' '))
        
        # Remove items from stack that are less indented
        while stack and indent <= stack[-1][0]:
            stack.pop()
        
        if stripped.startswith('- '):
            # List item: add to parent list
            item_text = stripped[2:].strip()
            if stack and stack[-1][2] is not None:
                # Simple list of strings
                parent_key = stack[-1][1]
                parent_dict = stack[-1][2]
                if parent_key and parent_key not in parent_dict:
                    parent_dict[parent_key] = []
                if parent_key:
                    parent_dict[parent_key].append(_parse_scalar(item_text))
        elif ':' in stripped:
            key, _, value = stripped.partition(':')
            key = key.strip()
            value = value.strip()
            
            if stack:
                parent_dict = stack[-1][2]
                if value:
                    # key: value pair (scalar value)
                    parent_dict[key] = _parse_scalar(value)
                    stack.append((indent, key, {}))
                else:
                    # key: (no inline value, expect children)
                    parent_dict[key] = {}
                    stack.append((indent, key, parent_dict[key]))
    
    return result


def _parse_scalar(value: str):
    """Parse a scalar YAML value."""
    value = value.strip()
    if not value:
        return value
    # Remove surrounding quotes if present
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    # Boolean values
    if value.lower() in ('true', 'yes', 'on'):
        return True
    if value.lower() in ('false', 'no', 'off'):
        return False
    # Number values
    try:
        if '.' in value:
            return float(value)
        return int(value)
    except ValueError:
        pass
    return value
```

**自定义异常：**

```python
class NoFrontmatterError(ValueError):
    """Raised when WORK_PLAN content has no YAML frontmatter block."""
    pass
```

**边界情况：**
- 空 frontmatter（仅 `--- ---`）→ 退化到旧格式
- frontmatter 含空格行 → 跳过空行
- frontmatter 含中文 → 直接作为字符串值保留

### A2 — `_build_pipeline_config()` 模板变量填充

```python
def _build_pipeline_config(frontmatter: dict, round_name: str, base_urls: dict) -> dict:
    """Build _PIPELINE_CONFIG from frontmatter dict.
    
    Args:
        frontmatter: parsed pipeline section from WORK_PLAN frontmatter
        round_name: e.g. "R62"
        base_urls: dict with keys "work_plan_url", "requirements_url"
    
    Returns:
        Complete pipeline config dict with template variables resolved
    """
    config = frontmatter.get("pipeline", {})
    if not config:
        raise ValueError("Frontmatter missing 'pipeline' key")
    
    config["round"] = round_name
    config["work_plan_url"] = base_urls.get("work_plan_url", "")
    config["requirements_url"] = base_urls.get("requirements_url", 
        f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-product-requirements.md")
    
    # Resolve ${pipeline.xxx} template variables in step contexts
    config["steps"] = config.get("steps", {})
    for step_key, step_cfg in config["steps"].items():
        context = step_cfg.get("context", {})
        for ctx_key, ctx_value in list(context.items()):
            if isinstance(ctx_value, str) and "${pipeline." in ctx_value:
                ref_key = ctx_value.replace("${pipeline.", "").rstrip("}")
                if ref_key in config:
                    context[ctx_key] = str(config[ref_key])
    
    return config


# Base repo URL for default document URL construction
_R62_REPO_BASE = "https://raw.githubusercontent.com/datahome73/ws-bridge/dev"
```

**模板变量解析规则（R62 过渡轮次）：**
- **仅支持 `${pipeline.xxx}`** — 替换为 `config[xxx]`（如 `${pipeline.work_plan_url}`）
- **不支持 `${steps.stepN.output}`** — 这些在运行时动态注入
- 如模板变量引用了不存在的 key → 保留原样（退化不报错）

### A3 — `_build_fallback_config()` 旧格式退化

```python
def _build_fallback_config(round_name: str, base_urls: dict) -> dict:
    """Build _PIPELINE_CONFIG from hardcoded PIPELINE_STEP_MAP (old format compat)."""
    from . import config as _r62cfg
    step_map = _r62cfg.PIPELINE_STEP_MAP
    
    work_plan_url = base_urls.get("work_plan_url", "")
    requirements_url = base_urls.get("requirements_url",
        f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-product-requirements.md")
    
    steps = {}
    for step_key, step_cfg in step_map.items():
        if step_key == "step1":
            continue  # step1 is auto-step, not part of pipeline flow
        role = step_cfg.get("role", "")
        steps[step_key] = {
            "role": role,
            "title": step_cfg.get("name", step_key),
            "context": {
                "requirements_url": requirements_url,
                "work_plan_url": work_plan_url,
            },
            "output_desc": "",
            "feedback_channel": "_admin",
            "timeout_minutes": int(step_cfg.get("timeout_hours", 6) * 60),
            "escalation": step_cfg.get("escalation", "notify_pm"),
        }
    
    return {
        "round": round_name,
        "goal": "",
        "work_plan_url": work_plan_url,
        "requirements_url": requirements_url,
        "steps": steps,
    }
```

### A3 — `_cmd_pipeline_start()` 改造

**位置：** L1230-1455

**改动概要：** 在 `_cmd_pipeline_start()` 中，WORK_PLAN 内容验证通过后、创建 workspace 之前，插入 config 生成逻辑。

**代码坐标 (exact line numbers based on current code):**

```python
# 在 work_plan_url 验证通过后、创建 workspace 之前（约 L1310-1320 之间），插入：

# ── R62 A3: Parse frontmatter → Build _PIPELINE_CONFIG ──
_pipeline_config = _PIPELINE_CONFIG.get(round_name)
if not _pipeline_config:
    # Try to fetch WORK_PLAN content and parse frontmatter
    import urllib.request as _r62url
    try:
        _r62req = _r62url.Request(work_plan_url or _remote_url)
        with _r62url.urlopen(_r62req, timeout=5) as _r62resp:
            wp_content = _r62resp.read().decode('utf-8')
    except Exception:
        wp_content = ""
    
    if wp_content:
        try:
            frontmatter = _parse_frontmatter(wp_content)
            config_data = _build_pipeline_config(frontmatter, round_name, {
                "work_plan_url": work_plan_url or _remote_url,
                "requirements_url": f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/{round_name}-product-requirements.md"
            })
            _PIPELINE_CONFIG[round_name] = config_data
        except (NoFrontmatterError, ValueError):
            # Fallback: old format WORK_PLAN
            config_data = _build_fallback_config(round_name, {
                "work_plan_url": work_plan_url or _remote_url,
                "requirements_url": f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/{round_name}-product-requirements.md"
            })
            _PIPELINE_CONFIG[round_name] = config_data
            write_chat_log("系统", f"📋 {round_name}：使用旧格式配置（无 machine-frontmatter）")
    else:
        # Can't fetch WORK_PLAN content → build minimal fallback
        config_data = _build_fallback_config(round_name, {
            "work_plan_url": work_plan_url or "",
            "requirements_url": f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/{round_name}-product-requirements.md"
        })
        _PIPELINE_CONFIG[round_name] = config_data
# ── R62 A3: End ──
```

**同时改造** kickoff_msg 从 config 读取 title：
```python
# 将 kickoff_msg (L1340) 改为从 _PIPELINE_CONFIG 读取：
step_config_from_config = _PIPELINE_CONFIG[round_name].get("steps", {})
start_step_from_config = step_config_from_config.get(start_step, {})
step_title = start_step_from_config.get("title", start_step)

kickoff_msg = (
    f"@全员 🚀 {round_name} 管线已启动！\n"
    f"下一棒：{target_role} → {step_title}\n\n"
    f"📄 需求：{_PIPELINE_CONFIG[round_name].get('requirements_url', '')}\n"
    f"📋 WORK_PLAN：{_PIPELINE_CONFIG[round_name].get('work_plan_url', '')}\n\n"
    f"各 bot 请切换活跃频道到此工作室，确认就绪。"
)
```

### A4 — `_cmd_step_complete()` 改造

**位置：** L1455-1700

**关键改动点（约 20 行）：**

**1. step_keys 排序改从 config 读** (L1529 附近)：
```python
# 当前代码：
step_config = _load_step_config()
step_keys = sorted(step_config.keys(), key=_step_sort_key)

# 改造后：
config_data = _PIPELINE_CONFIG.get(round_name)
if config_data and config_data.get("steps"):
    step_config_from_conf = config_data["steps"]
    step_keys = sorted(step_config_from_conf.keys(), key=_step_sort_key)
else:
    step_config_from_conf = _load_step_config()
    step_keys = sorted(step_config_from_conf.keys(), key=_step_sort_key)
```

**2. 交接通知消息从 config 读 title** (L1640-1665 附近)：

获取 step title：
```python
next_step_title = step_config_from_conf.get(next_step, {}).get("title", next_step)
```

改造 `context_summary` 使用 title：
```python
context_summary = f"上一 Step「{step_name}」产出: {output_ref}"
```

改造 `mention_msg` 使用 config 中的 URL：
```python
# 从 config 读取
req_url = config_data.get("requirements_url", f"https://raw.githubusercontent.com/.../{round_name}/...")
plan_url = config_data.get("work_plan_url", f"https://raw.githubusercontent.com/.../{round_name}/WORK_PLAN.md")

# 消息模板
mention_msg = (
    f"@{primary_name} 🚨 Step「{next_step} ({next_step_title})」到你了！\n\n"
    f"📄 需求：{req_url}\n"
    f"📋 WORK_PLAN：{plan_url}\n"
    f"🔗 上一步产出：{output_ref}\n\n"
    ...
)
```

**3. 最后一步（最终 Step）的 cleanup_msg 也读 title：**
```python
# 不用改太多，主要改动在交接通知段和 step_keys 排序
```

### A4 — `_cmd_step_handoff()` 改造

**位置：** L2169-2260

**与 `_cmd_step_complete()` 基本相同的改造：**
- step_keys 排序改从 `_PIPELINE_CONFIG[round_name].steps` 读
- 角色查找改从 config 读
- 消息模板中的 URL 从 config 读取

### A4 — `_cmd_pipeline_status()` 改造

**位置：** L2311-2420

**改造成支持 config-only 模式：**
- 当前：`if not _PIPELINE_STATE: return "📊 当前无活跃管线`
- 改造后：如果 state 为空但有 config，从 config 显示 step 列表

```python
async def _cmd_pipeline_status(sender_id: str, params: dict) -> str:
    if not _PIPELINE_STATE and not _PIPELINE_CONFIG:
        return "📊 当前无活跃管线"
    
    lines = []
    
    # ── R62: Show config-only rounds (state lost) ──
    if not _PIPELINE_STATE and _PIPELINE_CONFIG:
        for round_name, pconfig in sorted(_PIPELINE_CONFIG.items()):
            if round_name in _PIPELINE_STATE:
                continue  # Will be shown below
            lines.append(f"📊 **{round_name} 管线配置（state 不存在，config 仍在）**")
            lines.append(f"  目标: {pconfig.get('goal', '')}")
            step_config_from_conf = pconfig.get("steps", {})
            for step_key, step_info in sorted(
                step_config_from_conf.items(),
                key=lambda item: _step_sort_key(item[0]),
            ):
                role = step_info.get("role", "?")
                title = step_info.get("title", step_key)
                lines.append(f"  ⏳ {step_key} — {role}（{title}）")
            lines.append("")
    
    # ... (existing _PIPELINE_STATE display logic)
```

### A5 — `_clear_pipeline_state()` 改造

**位置：** L949

**当前实现：**
```python
def _clear_pipeline_state(round_name: str) -> None:
    _PIPELINE_STATE.pop(round_name, None)
```

**改造：**
```python
def _clear_pipeline_state(round_name: str) -> None:
    _PIPELINE_STATE.pop(round_name, None)
    # Note: _PIPELINE_CONFIG is NOT cleared here — R62: state/config separation
```

**其实不需要任何代码改动** — `_clear_pipeline_state()` 只操作 `_PIPELINE_STATE`，而 `_PIPELINE_CONFIG` 是独立的新 dict。只要 `_clear_pipeline_state()` 不引用 `_PIPELINE_CONFIG`，分离自动生效。**但是需要加注释**来说明这是有意设计。

---

## 方向 B：旧格式兼容守卫

### 守卫条件（5 行）

在 `_cmd_pipeline_start()` 的 frontmatter 解析段中：

| 条件 | 行为 |
|:-----|:------|
| `split('---')` 产生 < 3 个 segment | → `raise NoFrontmatterError` → 退化到旧格式 |
| frontmatter 为空（`--- ---`）| → `raise NoFrontmatterError` → 退化到旧格式 |
| frontmatter 有语法错误 | → 捕获通用 `Exception` → write log warning + 退化 |
| frontmatter 缺少 `pipeline` key | → 退化，不报错 |
| `_build_pipeline_config()` 抛出异常 | → 退化到回退 config |

**退化消息：**
```python
write_chat_log("系统", f"📋 {round_name}：使用旧格式配置（无 machine-frontmatter）")
```

**不阻塞管线** — 旧格式 WORK_PLAN 和无 frontmatter 的文档不应阻止任何管线功能。

---

## 验收标准映射

| # | 验收标准 | 实现位置 | 验证方法 |
|:-:|:---------|:---------|:---------|
| ✅-1 | `!pipeline_start R62` 解析 frontmatter → 生成 `_PIPELINE_CONFIG` | `_cmd_pipeline_start()` A3 插入段 + `_parse_frontmatter()` + `_build_pipeline_config()` | 启动后检查 `_PIPELINE_CONFIG` 含有 `steps`、`round`、`work_plan_url` |
| ✅-2 | `_PIPELINE_CONFIG` 与 `_PIPELINE_STATE` 分离 | `_clear_pipeline_state()` 不碰 config + config 是独立 dict | `_clear_pipeline_state()` 后 `_PIPELINE_CONFIG` 仍存在 |
| ✅-3 | `!step_complete` 从 config 读参数 | `_cmd_step_complete()` 的 step_keys 排序 + 消息模板 | step 交接消息使用 config 中的 title、URL |
| ✅-4 | `!step_handoff` 从 config 读下一 step | `_cmd_step_handoff()` 改造 | 走 config `steps` 键顺序，不再 `sorted()` |
| ✅-5 | state 丢失后 `!pipeline_status` 仍可读 config | `_cmd_pipeline_status()` config-only 模式 | state 为空时显示 config 中的 step 列表 |
| ✅-6 | step 交接消息使用 `steps.stepN.title` | `_cmd_step_complete()` 交接通知段 | 消息显示「技术方案 → 编码实现」 |
| ✅-7 | 旧格式 WORK_PLAN 不报错 | `NoFrontmatterError` → `_build_fallback_config()` | 无 frontmatter → 正常启动 |
| ✅-8 | 退化时写一条日志 | `write_chat_log("系统", "使用旧格式配置...")` | 检查 admin 频道日志 |
| ✅-9 | frontmatter 格式错误不阻塞 | 通用异常捕获 → 退化 | 乱码 frontmatter → 正常启动 + warning |
| ✅-10 | 跳过 Step 后 `!pipeline_status` 仍返回列表 | config-only 模式 | state 被 `_clear_pipeline_state` 清空后 status 仍展示 |
| ✅-11 | 旧 state 不存在时 `!pipeline_start` 不报「已活跃」 | `pipeline_is_active()` 检查 state 而非 config | 重启管线不冲突 |
| ✅-12 | 正常流转与改造前一致 | config-based 和旧 code path 交叉验证 | `_build_fallback_config` 生成的 config 与硬编码行为一致 |

---

## 修改文件清单

| # | 文件 | 改动类型 | 估算行数 | 说明 |
|:-:|:-----|:--------:|:--------:|:-----|
| 1 | `server/handler.py` L44 后 | **新增** | ~3 行 | `_PIPELINE_CONFIG= {}` 全局变量 |
| 2 | `server/handler.py` 新增 | **新增函数** | ~15 行 | `_parse_frontmatter()` — 轻量 YAML frontmatter 解析 |
| 3 | `server/handler.py` 新增 | **新增函数** | ~20 行 | `_build_pipeline_config()` — 模板变量填充 |
| 4 | `server/handler.py` 新增 | **新增函数** | ~10 行 | `_build_fallback_config()` — 旧格式兼容 |
| 5 | `server/handler.py` 新增 | **新增异常** | ~3 行 | `NoFrontmatterError` 类 |
| 6 | `server/handler.py` L1310 附近 | **修改** | ~20 行 | `_cmd_pipeline_start()` — frontmatter 解析 + config 存储 |
| 7 | `server/handler.py` L1340-1346 | **修改** | ~5 行 | `_cmd_pipeline_start()` — kickoff_msg 从 config 读 URL/title |
| 8 | `server/handler.py` L1529 附近 | **修改** | ~5 行 | `_cmd_step_complete()` — step_keys 从 config 读 |
| 9 | `server/handler.py` L1600-1665 | **修改** | ~10 行 | `_cmd_step_complete()` — 通知消息从 config 读 title/URL |
| 10 | `server/handler.py` L2188 附近 | **修改** | ~10 行 | `_cmd_step_handoff()` — step_keys + 消息从 config 读 |
| 11 | `server/handler.py` L2313-2320 | **修改** | ~10 行 | `_cmd_pipeline_status()` — 支持 config-only 模式 |
| 12 | `server/handler.py` L949 | **注释** | ~2 行 | 加注释确认 `_clear_pipeline_state` 不清理 config |
| 13 | `docs/R62/R62-tech-plan.md` | **新增** | — | 本文件 |

**总估算：** ~113 行净改（与 WORK_PLAN 的 ~116 行一致）

---

## 风险与边界

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| `_parse_frontmatter()` 对复杂 YAML 解析失败 | 活跃管线初始化受阻 | 有异常捕获 + 退化到旧格式，管线不阻塞 |
| 模板变量 `${pipeline.xxx}` 引用 key 不存在 | 消息中显示原始 `${pipeline.xxx}` 字符串 | 保留原样不报错 |
| 旧格式 `_build_fallback_config` 生成的 step key 与 config 不兼容 | step_complete 找不到 step | step2~step6 相同，不产生新 step key |
| 并行管线中两个 round_name 都有 config | status 显示混乱 | 按 round_name 分别显示 |

---

## 验证清单

- [ ] 语法检查：`python3 -c "compile(open('server/handler.py').read(), 'handler.py', 'exec'); print('OK')"`
- [ ] `_parse_frontmatter()` 能解析 R62 WORK_PLAN.md 的真实 frontmatter
- [ ] 无 frontmatter 的旧 WORK_PLAN → `_build_fallback_config()` 被调用，无报错
- [ ] `_clear_pipeline_state()` 后 `_PIPELINE_CONFIG[round_name]` 仍存在
- [ ] `!step_complete` 交接消息中的 URL 来自 config（非硬编码）
- [ ] `!pipeline_status` 在 state 为空时能展示 config step 列表
- [ ] `grep -n 'raw.githubusercontent.com.*{round_name}'` handler.py 确认硬编码 URL 已减少

---

## 6. 审阅确认回复

> 🧐 小谷 R-1~R-5 确认答复（v1.0 → v1.1）

### R-1: `_parse_frontmatter()` 解析能力边界 ✅ 已明确

**支持的 YAML 子集：**
| 特征 | 支持 | 说明 |
|:-----|:----:|:------|
| String values `key: val` | ✅ | 含中文、特殊字符 |
| Nested dicts (2-space indent) | ✅ | `parent:\n  child: val` |
| 注释行 `# comment` | ✅ | 静默跳过 |
| Scalar types (int, float, bool) | ✅ | 自动类型推断 |
| quoted strings `"..."` / `'...'` | ✅ | 去引号后保留 |
| template vars `${pipeline.xxx}` | ✅ | 保留为字符串，由上层替换 |
| List of scalars `- item` | ✅ | 返回 Python list |
| Empty lines | ✅ | 静默跳过 |
| List of dicts `- key: val` | ❌ | 静默忽略（未来扩展前保持不支持）|
| Block scalars `|` / `>` | ❌ | 静默忽略 |
| Aliases `&anchor` / `*alias` | ❌ | 静默忽略 |
| Multi-doc `---` `...` | ❌ | 只解析第一个 frontmatter 块 |

### R-2: 参数映射表 ✅ 已补充

| # | 当前硬编码位置（handler.py）| 硬编码内容 | 新 config key 路径 | 默认值 |
|:-:|:---------------------------|:-----------|:--------------------|:-------|
| 1 | L1340-1346 kickoff_msg | `f"下一棒：{target_role} → {start_step}"` | `steps.{step}.title` | `start_step` 自身 |
| 2 | L1343 kickoff_msg URL | `f"raw.githubusercontent.com/.../docs/{round_name}/..."` | `pipeline.requirements_url` | `config.WORK_PLAN_REPO_URL + ...` |
| 3 | L1343 kickoff_msg WORK_PLAN URL | 同上 | `pipeline.work_plan_url` | 同上 |
| 4 | L1529 step_keys 排序 | `sorted(step_config.keys(), key=...)` | `steps` dict 的 keys | `PIPELINE_STEP_MAP.keys()` |
| 5 | L1601 context_summary | `f"上一 Step「{step_name}」产出: {output_ref}"` | 每 step 的 `title` | `step_name` 自身 |
| 6 | L1635-1640 req_url | `f"raw.githubusercontent.com/.../docs/{round_name}/..."` | `steps.{step}.context.requirements_url` | `pipeline.requirements_url` |
| 7 | L1635-1640 plan_url | 同上 | `steps.{step}.context.work_plan_url` | `pipeline.work_plan_url` |
| 8 | L1643-1665 mention_msg 格式 | `f"@{primary_name} 🚨 Step「{next_step}」到你了！"` | `steps.{step}.title` 替换 `{next_step}` | `next_step` 自身 |
| 9 | L2313 `_cmd_pipeline_status` | `if not _PIPELINE_STATE: return "..."` | 新增：state 为空时从 config 读 step 列表 | — |

### R-3: `!close_workspace` 与 config 的关系 ✅ 确认

`_cmd_close_workspace()` (L462) **不调用 `_clear_pipeline_state()`**，只调 `ws_mod.force_close(ws_id)`。Config 清理仅发生在管线自然结束（`_cmd_step_complete` L1564 / `_cmd_step_handoff` L2228 的最后一步）。所以：
- `!close_workspace` → `_PIPELINE_CONFIG` **不受影响**
- 管线 step_complete 最后一步 → `_clear_pipeline_state` + config 不受影响

### R-4: 半退 vs 全退 ✅ 补充说明

R62 过渡轮次建议**全退**，原因：
1. frontmatter 是新事物，生效条件应该是**要么全有用，要么全不用**
2. 半退需要逐字段异常处理，增加 ~30 行防御代码
3. 旧格式退化仍能正常跑管线——功能一致
4. 下个轮次（R63）可改为半退，到时流程更成熟

**例外：** 如果 `pipeline.requirements_url` 字段缺失，仅该字段降级为旧硬编码拼接，不整块退化。

### R-5: 调试辅助命令 ✅ 采纳

扩展 `!pipeline_status --verbose`（或 `--dump`），输出当前 round 的 `_PIPELINE_CONFIG` JSON 摘要。

```python
# 在 _cmd_pipeline_status 中（约 L2311）：
if params.get("verbose") or params.get("dump"):
    lines.append("")
    lines.append("📋 _PIPELINE_CONFIG:")
    pconfig = _PIPELINE_CONFIG.get(round_name, {})
    lines.append(f"  round: {pconfig.get('round', '')}")
    lines.append(f"  goal: {pconfig.get('goal', '')}")
    lines.append(f"  work_plan_url: {pconfig.get('work_plan_url', '')}")
    lines.append(f"  requirements_url: {pconfig.get('requirements_url', '')}")
    for step_key in sorted(pconfig.get('steps', {}).keys(), key=_step_sort_key):
        step_cfg = pconfig['steps'][step_key]
        lines.append(f"  {step_key}: role={step_cfg.get('role','')} | title={step_cfg.get('title','')}")
```

此改动已纳入技术方案改动清单。
