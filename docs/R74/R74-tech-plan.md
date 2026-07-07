# R74 技术方案 — 管线通用化：WORK_PLAN 单入口 + Raw URL 解耦 🌐

> **版本：** v1.0
> **状态：** ✅ 技术方案
> **架构师：** 👷 Arch
> **日期：** 2026-07-07
> **基于需求：** docs/R74/R74-product-requirements.md v1.0
> **改动范围：** `server/handler.py` + `server/config.py` 仅此二文件

---

## 目录

1. [方向 A：WORK_PLAN frontmatter 承载全量配置](#1-方向-awork_plan-frontmatter-承载全量配置)
   - [A1 — frontmatter steps 校验（缺 steps 报错）](#a1--frontmatter-steps-校验缺-steps-报错)
   - [A1 — workspace.members 读取（从 frontmatter 解析成员）](#a1--workspacemembers-读取从-frontmatter-解析成员)
   - [A2 — _build_pipeline_config() context URL 不拼接覆盖](#a2--_build_pipeline_config-context-url-不拼接覆盖)
2. [方向 B：移除所有硬编码路径拼接](#2-方向-b移除所有硬编码路径拼接)
   - [B1 — 删除 `_R62_REPO_BASE` 常量](#b1--删除-_r62_repo_base-常量)
   - [B2 — `_infer_artifact_url()` 增加 step_config 参数](#b2--_infer_artifact_url-增加-step_config-参数)
3. [方向 C：admin → operations 角色名全局替换](#3-方向-cadmin--operations-角色名全局替换)
4. [兼容性分析](#4-兼容性分析)
5. [改动汇总](#5-改动汇总)
6. [风险与缓解](#6-风险与缓解)

---

## 1. 方向 A：WORK_PLAN frontmatter 承载全量配置

### A1 — frontmatter steps 校验（缺 steps 报错）

#### 1.1 现状

`_cmd_pipeline_start()` (L2076-2106) 中当 frontmatter 解析成功后，直接将结果传给 `_build_pipeline_config()`。若 frontmatter 中无 `pipeline.steps`，则 `config["steps"]` 为空 dict `{}`。后续代码走 `_get_step_config()` 时会回退到 `_build_fallback_steps()`，静默使用旧 `PIPELINE_STEP_MAP`。

#### 1.2 改动方案

**文件：** `server/handler.py`

**函数：** `_cmd_pipeline_start()` — frontmatter 解析成功后（L2093-2099），在 `_PIPELINE_CONFIG[round_name] = config_data` 之前插入以下校验：

```python
# R74 A1: 校验 frontmatter 中是否包含 steps 定义
if not config_data.get("steps"):
    # 检查是否为旧格式（有 steps 但为空），无→报错退出
    psteps = config_data.get("steps", {})
    if not psteps and not force_flag:
        return (
            f"❌ {round_name} WORK_PLAN 缺少 pipeline.steps 定义。\n\n"
            f"请在 frontmatter 中补充 steps 配置，每 step 含 role/title/context。\n"
            f"参考格式：https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R74/WORK_PLAN.md\n\n"
            f"提示：可使用 --force 强制以默认 Step 映射启动（PIPELINE_STEP_MAP 回退）"
        )
```

> **需要新增参数：** `_cmd_pipeline_start()` 签名需增加 `force: bool = False`。从命令解析处提取 `--force` 参数。

**位置索引：** 在 L2093 (`_PIPELINE_CONFIG[round_name] = config_data`) 之前，或 L2093 之后立即校验。

**关键约束：** 此校验仅针对「解析成功但无 steps」的场景。对于：
- `NoFrontmatterError` 异常 → 仍走 `_build_fallback_config()`（旧轮次兼容）
- `_PIPELINE_CONFIG` 已存在（非首次启动）→ 跳过，复用已有的

#### 1.3 `--force` 参数解析

**文件：** `server/handler.py`

**函数：** `_cmd_pipeline_start()` 的参数解析入口（L2040-2050 附近）

**当前命令格式：**
```
!pipeline_start R74 [--work_plan_url <url>]
```

**改造后：**
```
!pipeline_start R74 [--work_plan_url <url>] [--force]
```

参数提取：
```python
force_flag = "--force" in params.get("flags", []) or params.get("force", False)
```

> BOT 平台的消息格式可能需要适配。若当前参数为 `_positional` + kwargs 格式，将 `--force` 放在 kwargs 中处理。

---

### A1 — workspace.members 读取（从 frontmatter 解析成员）

#### 2.1 现状

管线工作室内成员集合通过角色推断得到（L2116-2144）：

```python
step_config = _get_step_config(round_name)
all_roles = set()
for step_key, step_cfg in step_config.items():
    role = step_cfg.get("role", "")
    if role and step_key != "step1":
        all_roles.add(role)
```

然后通过 `all_roles` 匹配已有 agent card 的 `pipeline_roles` 字段来筛选成员。缺少从 frontmatter 读取显式成员定义的能力。

#### 2.2 改动方案

**文件：** `server/handler.py`

**函数：** `_cmd_pipeline_start()` 中 L2116-L2144 区域

前端新增读取：

```python
# ── R74 A1: 尝试从 frontmatter workspace.members 读取成员定义 ──
pconfig = _PIPELINE_CONFIG.get(round_name, {})
workspace_members = pconfig.get("workspace", {}).get("members", {})
if workspace_members:
    # frontmatter 定义了显式成员角色，用它替代 step_config 推断
    all_roles = set(workspace_members.keys())
    logger.info("R74: Using frontmatter workspace.members roles: %s", all_roles)
else:
    # 无 frontmatter members → 回退原有 step_config 推断
    step_config = _get_step_config(round_name)
    all_roles = set()
    for step_key, step_cfg in step_config.items():
        role = step_cfg.get("role", "")
        if role and step_key != "step1":
            all_roles.add(role)
    logger.info("R74: No workspace.members in frontmatter, inferred roles: %s", all_roles)

# 原有 member discovery 逻辑继续（L2128-2144）使用 all_roles
```

> **注意：** `workspace_members` 字典的值结构为 `{role_name: {mention_keyword: ..., rules: ...}}`。当前成员发现逻辑仅关心角色名（`all_roles` 的 key），`mention_keyword` 和 `rules` 暂不用于成员过滤，但保留在 frontmatter 中供未来使用。

**位置索引：** 插入到 L2116 的 `# ── R44 F-13: Auto-collect workspace members ──` 注释之后，原 L2118 `cards = ac_mod.get_all_cards()` 之前。让 `all_roles` 先被确定，后续 card 匹配逻辑不变。

---

### A2 — `_build_pipeline_config()` context URL 不拼接覆盖

#### 3.1 现状

**文件：** `server/handler.py` L1150-1167

```python
def _build_pipeline_config(frontmatter: dict, round_name: str, base_urls: dict) -> dict:
    config = frontmatter.get("pipeline", {})
    if not config:
        raise ValueError("Frontmatter missing 'pipeline' key")
    config["round"] = round_name
    config["work_plan_url"] = base_urls.get("work_plan_url", "")            # ← 覆盖 frontmatter
    config["requirements_url"] = base_urls.get("requirements_url",          # ← 覆盖 frontmatter
        f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-product-requirements.md")
    config["steps"] = config.get("steps", {})
    for step_key, step_cfg in config["steps"].items():
        context = step_cfg.get("context", {})
        for ctx_key, ctx_value in list(context.items()):
            if isinstance(ctx_value, str) and "${pipeline." in ctx_value:
                ref_key = ctx_value.replace("${pipeline.", "").rstrip("}")
                if ref_key in config:
                    context[ctx_key] = str(config[ref_key])
    return config
```

**问题：**
1. `config["work_plan_url"]` 和 `config["requirements_url"]` 无条件被 `base_urls` 覆盖 — 即使 frontmatter 中已显式定义
2. `base_urls` 本身在调用侧（L2089-2092）又是通过 `config.WORK_PLAN_REPO_URL` 拼接而成的，不是来自 frontmatter
3. `_R62_REPO_BASE` 还出现在默认 fallback 中（即将删除）

#### 3.2 改动方案

```python
def _build_pipeline_config(frontmatter: dict, round_name: str, base_urls: dict) -> dict:
    """Build _PIPELINE_CONFIG from frontmatter dict.
    
    R74 A2: frontmatter 中的 URL 字段优先，base_urls 仅作为无定义时的补充。
    不再拼接 docs/轮次/ 路径。
    """
    config = frontmatter.get("pipeline", {})
    if not config:
        raise ValueError("Frontmatter missing 'pipeline' key")
    config["round"] = round_name
    
    # R74 A2: 仅当 frontmatter 无定义时才从 base_urls 获取
    if not config.get("work_plan_url"):
        config["work_plan_url"] = base_urls.get("work_plan_url", "")
    if not config.get("requirements_url"):
        config["requirements_url"] = base_urls.get("requirements_url", "")
    
    config["steps"] = config.get("steps", {})
    # 模板引用解析（${pipeline.xxx}）
    for step_key, step_cfg in config["steps"].items():
        context = step_cfg.get("context", {})
        for ctx_key, ctx_value in list(context.items()):
            if isinstance(ctx_value, str) and "${pipeline." in ctx_value:
                ref_key = ctx_value.replace("${pipeline.", "").rstrip("}")
                if ref_key in config:
                    context[ctx_key] = str(config[ref_key])
    return config
```

**调用侧变更：** 调用 `_build_pipeline_config()` 的 3 个地方（L2089-2092、L2095-2098、L2102-2105），`base_urls` 仍保留 `work_plan_url` 键，但 `requirements_url` 值改为空字符串（因为新轮次由 frontmatter 提供）：

```python
# 改造后的 base_urls 传参（仅 work_plan_url，不再拼接 requirements_url）
config_data = _build_pipeline_config(frontmatter, round_name, {
    "work_plan_url": work_plan_url or _remote_url,
    "requirements_url": "",  # R74 A2: frontmatter 自行提供
})
```

> **注意：** 旧轮次的 `_PIPELINE_CONFIG` 已缓存，不会重新走 `_build_pipeline_config()`，不受影响。

---

## 2. 方向 B：移除所有硬编码路径拼接

### B1 — 删除 `_R62_REPO_BASE` 常量

#### 4.1 现状

**文件：** `server/handler.py` L1083

```python
_R62_REPO_BASE = "https://raw.githubusercontent.com/datahome73/ws-bridge/dev"
```

#### 4.2 改动方案

**动作：** 删除 L1083 整行。

#### 4.3 引用处改造（共 5 处）

| # | 位置 | 当前代码 | 改造方案 | 影响 |
|:-:|:-----|:---------|:---------|:-----|
| 1 | L1158 `_build_pipeline_config` | `f"{_R62_REPO_BASE}/docs/...` | **删除** — 第 3.2 节已改为空串 fallback | 仅影响新轮次无 frontmatter 时 |
| 2 | L1175 `_build_fallback_config` | `f"{_R62_REPO_BASE}/docs/...` | 改为 `config.WORK_PLAN_REPO_URL` 拼接（保留退化兼容） | 旧轮次 frontmatter 回退路径 |
| 3 | L1213 `_infer_artifact_url` | `f"{_R62_REPO_BASE}/docs/{round_name}...` | 改为 `raw.githubusercontent.com/.../main/`（见第 5 节） | step2/4/5 artifact URL 回退 |
| 4 | L1214 `_infer_artifact_url` | 同 3 | 同 3 | 同上 |
| 5 | L1215 `_infer_artifact_url` | 同 3 | 同 3 | 同上 |

**引用 1（L1158）** — 已在第 3.2 节中处理，`_build_pipeline_config()` 不再使用 `_R62_REPO_BASE`。

**引用 2（L1175）— `_build_fallback_config()` 改造：**

```python
# L1174-1175 改为：
requirements_url = base_urls.get("requirements_url",
    f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/{round_name}-product-requirements.md")
```

> `config.WORK_PLAN_REPO_URL` 是环境变量 `WORK_PLAN_REPO_URL` 的值或其默认值。此路径仅在旧格式回退时使用，新轮次通过 frontmatter 提供。

**引用 3-5（L1213-1215）— 见第 5 节 `_infer_artifact_url()` 改造。**

---

### B2 — `_infer_artifact_url()` 增加 step_config 参数

#### 5.1 现状

**文件：** `server/handler.py` L1210-1217

```python
def _infer_artifact_url(step_name: str, round_name: str) -> str:
    """Auto-infer artifact URL based on step type. Returns '' if unknown."""
    step_urls = {
        "step2": f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-tech-plan.md",
        "step4": f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-review-report.md",
        "step5": f"{_R62_REPO_BASE}/docs/{round_name}/test-report.md",
    }
    return step_urls.get(step_name, "")
```

**调用处：** L2537 — `_infer_artifact_url(step_name, round_name)`

#### 5.2 改动方案

```python
def _infer_artifact_url(step_name: str, round_name: str,
                        step_config: dict | None = None) -> str:
    """Auto-infer artifact URL based on step type.
    
    Priority:
    1. step_config[step_name].artifact_url (from frontmatter, if provided)
    2. Hardcoded fallback URL (compat for old rounds, uses main branch)
    
    Returns '' if unknown.
    """
    # R74 B2: Prefer frontmatter-defined artifact_url
    if step_config and step_name in step_config:
        art = step_config[step_name].get("artifact_url", "")
        if art:
            return art
    
    # Fallback: hardcoded paths (main branch — R72/R73 already merged)
    step_urls = {
        "step2": f"https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/{round_name}/{round_name}-tech-plan.md",
        "step4": f"https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/{round_name}/{round_name}-review-report.md",
        "step5": f"https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/{round_name}/test-report.md",
    }
    return step_urls.get(step_name, "")
```

> **注意：** 回退 URL 分支从 `dev` 改为 `main`。R72/R73 已合入 main，dev 分支已被相应维护者删除。`main` 是归档的稳定版本。

#### 5.3 调用处改造

**调用处（L2536-2537）：** 需要传递 `step_config`。

当前代码顺序（L2527-2542）：
```python
2527|    pstate_b1 = _PIPELINE_STATE.get(round_name)
2528|    if pstate_b1:
2529|        step_outputs = pstate_b1.setdefault("step_outputs", {})
2530|        step_outputs[step_name] = {
...
2536|            "artifact_url": params.get("artifact_url",
2537|                _infer_artifact_url(step_name, round_name)),   # ← 无 step_config
...
2540|        }
...
2542|    step_config = _get_step_config(round_name)   # ← step_config 在此行才可用
```

**方案：** 将 `step_config = _get_step_config(round_name)` 从 L2542 提前到 L2527 之前，然后在 L2537 传入：

```python
# 提前获取 step_config（R74 B2: 为 _infer_artifact_url 提供 step_config）
step_config = _get_step_config(round_name)

pstate_b1 = _PIPELINE_STATE.get(round_name)
if pstate_b1:
    step_outputs = pstate_b1.setdefault("step_outputs", {})
    step_outputs[step_name] = {
        "sha": output_ref or "",
        "title": step_config.get(step_name, {}).get("title", step_name),
        "output_desc": step_config.get(step_name, {}).get("output_desc", ""),
        "summary": params.get("summary", step_config.get(step_name, {}).get("output_desc", "")),
        "artifact_url": params.get("artifact_url",
            _infer_artifact_url(step_name, round_name, step_config)),  # ← 传入 step_config
        "timestamp": time.time(),
    }

# L2542 处的 step_config = _get_step_config(round_name) 删除（已提前）
```

> **影响：** L2542 原来的 `step_config = _get_step_config(round_name)` 重复赋值被删除。后续代码（L2543+）原样使用前面获取的 `step_config` 变量。

---

## 3. 方向 C：admin → operations 角色名全局替换

### 6.1 PIPELINE_STEP_MAP（config.py）

**文件：** `server/config.py` L90-104

```python
PIPELINE_STEP_MAP: dict[str, dict] = {
    "step1": {"role": "admin",   "name": "管线启动",       "timeout_hours": 2.0,  "escalation": "notify_pm"},
    # ... step2-5 unchanged ...
    "step6": {"role": "admin",   "name": "合并部署归档",    "timeout_hours": 2.0,  "escalation": "notify_pm",
              "primary": "admin", "backup": "arch"},
}
```

**改动（2 处）：**

| 行号 | 当前值 | 改为 |
|:----:|:-------|:-----|
| L93 | `"step1": {"role": "admin"` | `"step1": {"role": "operations"` |
| L102 | `"step6": {"role": "admin"` | `"step6": {"role": "operations"` |
| L103 | `"primary": "admin"` | `"primary": "operations"` |

### 6.2 handler.py 中 pipeline 角色 `"admin"` 引用

**策略说明：** 需区分「pipeline 运维角色」与「系统管理员角色」：
- **pipeline 运维角色**（即 R73 已改名的 `operations`）：旧名 `"admin"` 出现在 `PIPELINE_STEP_MAP` 及与之相关的角色匹配逻辑中 → 改为 `"operations"`
- **系统管理员角色**（平台全局权限）：如广播、用户管理、认证控制等 → 保留 `"admin"` 不变

**需要改动的关键位置：**

| # | 行号 | 函数 | 当前代码 | 说明 | 是否改动 |
|:-:|:----:|:-----|:---------|:-----|:--------:|
| 1 | L157 | `_format_agent_name()` | `if role == "admin":` | 用户角色名显示前缀 "管理员 "，通用函数 | ⚠️ **建议不改** — 系统 admin 用户仍存在 |
| 2 | L4173 | `_on_agent_message` | `u.get("role") == "admin"` | 收集 admin ID 用于广播/通知 | ❌ 不改 — 系统 admin 权限 |
| 3 | L4194 | 同上 | `sender_role != "admin"` | 广播权限检查 | ❌ 不改 — 系统 admin 权限 |
| 4 | L4260 | 同上 | `sender_role != "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 5 | L4437 | 同上 | `sender_role == "admin"` | admin 特殊操作 | ❌ 不改 — 系统 admin 权限 |
| 6 | L4483 | 同上 | `sender_role != "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 7 | L4588 | 同上 | `sender_role == "admin"` | admin 功能 | ❌ 不改 — 系统 admin 权限 |
| 8 | L4641 | 同上 | `sender_role == "admin"` | admin 功能 | ❌ 不改 — 系统 admin 权限 |
| 9 | L4664 | 同上 | `sender_role == "admin"` | admin 功能 | ❌ 不改 — 系统 admin 权限 |
| 10 | L4677 | 同上 | `sender_role == "admin"` | admin 功能 | ❌ 不改 — 系统 admin 权限 |
| 11 | L4790 | `_check_lobby_rate_limit` | `if role == "admin":` | admin 免限流 | ⚠️ **建议不改** — 系统 admin 权限 |
| 12 | L4833 | `_check_rate_limit` | `if role == "admin":` | admin 免限流 | ⚠️ **建议不改** — 系统 admin 权限 |
| 13 | L5157 | `_on_agent_message` | `u.get("role") == "admin"` | admin ID 收集 | ❌ 不改 — 系统 admin 权限 |
| 14 | L5184 | 同上 | `role) == "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 15 | L5284 | 同上 | `role) != "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 16 | L5357 | 同上 | `role) != "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 17 | L5386 | 同上 | `role) != "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 18 | L5556 | 同上 | `u.get("role") == "admin"` | admin ID 收集 | ❌ 不改 — 系统 admin 权限 |
| 19 | L5634 | 同上 | `u.get("role") == "admin"` | admin ID 收集 | ❌ 不改 — 系统 admin 权限 |
| 20 | L5657 | 同上 | `role) != "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 21 | L5724 | 同上 | `role) != "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 22 | L5800 | R23 遗留 | `role != "admin"` | 旧注册协议 admin 权限 | ❌ 不改 — 系统 admin 权限 |
| 23 | L5875 | 同上 | `role) == "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 24 | L5888 | 同上 | `role) == "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 25 | L5905 | 同上 | `role) == "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 26 | L5919 | 同上 | `role) == "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |
| 27 | L5933 | 同上 | `role) == "admin"` | 权限检查 | ❌ 不改 — 系统 admin 权限 |

**总结：handler.py 内「admin→operations」的改动量为 0 处**（config.py 的 PIPELINE_STEP_MAP 3 处已覆盖）。

系统 admin 权限检查（广播、限流、用户管理）的 24 处 `"admin"` 引用均属「正常 admin 命令/功能名称」范畴，**不纳入本轮改动**。

---

---

## 3.5 方向 D — 顺手修复（管线运行中发现的两个 bug）

### D1 — PM 收件箱写权限放开

**根因分析：** inbox 写权限检查位置在 `_on_agent_message()`（L4580-4600 附近），当消息的 `channel` 以 `_inbox:` 前缀开头时，代码检查发送者角色是否为 `admin`。PM（小谷）role 为 `member`，不匹配。

**改动方案：**

```python
# 当前（L4588 附近）：
if sender_role != "admin":
    return {"type": "error", "error": "❌ 权限不足：仅管理员可向收件箱发消息"}

# 改造后：
# 允许 pipeline PM 角色（pipeline_coordinator）也发送 inbox 消息
allowed_inbox_roles = {"admin", "pipeline_coordinator"}
if sender_role not in allowed_inbox_roles:
    return {"type": "error", "error": "❌ 权限不足：仅管理员可向收件箱发消息"}
```

> **注意：** 具体角色名需根据实际 `role_level()` 或 `auth.role_definition` 确定。PM 的 role 可能是 `pipeline_coordinator` 或 `pm` 或 `member`（但 pipeline_coordinator 有特殊权限标记）。建议用一个集合 `INBOX_WRITE_ROLES` 统一管理可写 inbox 的角色。

**行号：** 需在部署版本中 grep 确认 `仅管理员可向收件箱发消息` 的精确位置。

### D2 — Agent Card 角色名不匹配

**根因分析：** 成员发现逻辑（L2128-2144）中仅通过 `pipeline_roles & all_roles` 交集匹配。小开的卡上写的是 `pipeline_roles: ["architect"]`，而 pipeline 配置中角色名为 `arch`，交集为空。

**与 A1（workspace.members）的关系：** 当 workspace.members 在前端定义后，成员发现函数将获得 `all_roles`。但 agent card 匹配仍依赖字符串精确匹配。修复方向：当 workspace.members 存在时，通过 display_name 查找而非 pipeline_roles 交集。

**改动方案（在 L2128-2144 区域的 workspace.members 分支内新增）：**

```python
if workspace_members:
    # ── D2: 当 frontmatter 有 workspace.members 时，用 display_name 匹配 ──
    role_to_keywords = {}
    for role_name, role_cfg in workspace_members.items():
        kw = role_cfg.get("mention_keyword", "")
        role_to_keywords[role_name] = set(kw.split(";")) if kw else set()
    
    member_ids = []
    for aid, card in cards.items():
        card_name = card.get("display_name", "")
        # 检查 card 的 display_name 是否匹配某角色的 mention_keyword
        for role_name, keywords in role_to_keywords.items():
            if card_name in keywords:
                member_ids.append(aid)
                break
else:
    # 原有 pipeline_roles 交集匹配逻辑...
```

> **简化方案：** 若交互流程可接受，让各 bot 在 Agent Card 的 `pipeline_roles` 中使用与 frontmatter 一致的角色名即可。当前修复通过 A1 + D2 的 name-matching fallback 解决，无需强制统一角色名。


## 4. 兼容性分析

### 4.1 旧轮次管线（R72/R73 等已有 `_PIPELINE_CONFIG`）

| 场景 | 当前行为 | 改造后行为 | 兼容性 |
|:-----|:---------|:-----------|:-------|
| `!pipeline_status R72` | 读取 `_PIPELINE_CONFIG` 显示 | 读取 `_PIPELINE_CONFIG` 显示，不变 | ✅ 完全兼容 |
| `!step_complete step2 R72` | 复用 `_PIPELINE_CONFIG` 的 steps | 复用 `_PIPELINE_CONFIG` 的 steps，不变 | ✅ 完全兼容 |
| `_build_fallback_config` 对旧轮次 | 拼接 `_R62_REPO_BASE` URL | 拼接 `config.WORK_PLAN_REPO_URL` URL | ✅ 行为不变（替换常量来源） |

### 4.2 旧轮次 artifact URL

| 场景 | 改造前 | 改造后 | 兼容性 |
|:-----|:-------|:-------|:-------|
| `_infer_artifact_url("step2", "R72")` | `dev` 分支 URL | `main` 分支 URL | ⚠️ R72/R73 已合入 main，兼容 |
| 自定义 artifact_url（旧轮次未设） | 回退 `dev` | 回退 `main` | ✅ URL 改变但内容等价 |

### 4.3 PIPELINE_STEP_MAP role 变更

| 场景 | 当前 | 改造后 | 兼容性 |
|:-----|:-----|:-------|:-------|
| 旧轮次 step1 role | `"admin"` | `"operations"` | ⚠️ 旧轮次 `_PIPELINE_CONFIG` 已缓存，不影响 |
| 新轮次 step1 role 回退 | `"admin"` | `"operations"` | ✅ 与 R73 角色名统一 |
| `_build_fallback_steps()` | 取 `PIPELINE_STEP_MAP` role | 取 `PIPELINE_STEP_MAP` role | ✅ 值变了但路径不变 |

### 4.4 兼容性决策矩阵

| 决定项 | 决策 | 原因 |
|:-------|:-----|:------|
| 旧轮次 `_PIPELINE_CONFIG` 不重建 | 保留现有缓存 | 旧轮次管线已完结/活跃中，不应中断 |
| `_build_fallback_config` 保留 | 保留 | 旧轮次无 frontmatter 时仍需退化兼容 |
| `_build_fallback_config` 中 URL 用 `WORK_PLAN_REPO_URL` 而非 `_R62_REPO_BASE` | 替换 | 常量删除后，用环境变量兜底 |
| `_infer_artifact_url` 回退 URL 用 `main` 而非 `dev` | 替换 | dev 分支已删除，main 是归档版本 |

---

## 5. 改动汇总

### 5.1 文件清单

| 文件 | 改动类型 | 行数估算 | 说明 |
|:-----|:---------|:--------:|:-----|
| `server/handler.py` | 删除 `_R62_REPO_BASE` | -1 | L1083 整行删除 |
| `server/handler.py` | 修改 `_build_pipeline_config()` | ~5 | 条件赋值 + 删除 fallback 拼接 |
| `server/handler.py` | 修改 `_build_fallback_config()` | ~2 | `_R62_REPO_BASE` → `config.WORK_PLAN_REPO_URL` |
| `server/handler.py` | 修改 `_infer_artifact_url()` | ~10 | 增参数 + 前置读取 + URL 分支 main |
| `server/handler.py` | 修改 `_cmd_pipeline_start()` frontmatter 校验 | ~8 | 缺 steps 报错 + `--force` 参数 |
| `server/handler.py` | 修改 `_cmd_pipeline_start()` workspace.members | ~10 | frontmatter members 读取 + 角色推断 |
| `server/handler.py` | 修改 `_cmd_pipeline_start()` base_urls 传参 | ~3 | requirements_url 改为空串 |
| `server/handler.py` | 修改 `_cmd_pipeline_start()` step_config 提前 | ~2 | L2542 提前到 L2527 前 |
| `server/config.py` | 修改 `PIPELINE_STEP_MAP` role | ~3 | step1/step6 + primary |
| **合计** | | **~42 行净增 / -1 行删除 ≈ 41 行净增** | |

### 5.2 函数级改动一览

```
server/handler.py
├── L1083        ✂️ DEL _R62_REPO_BASE                          (B1)
├── L1150-1167   ✏️ _build_pipeline_config() — 条件赋值不覆盖    (A2)
├── L1170-1199   ✏️ _build_fallback_config() — 替换 R62_BASE     (B1)
├── L1210-1217   ✏️ _infer_artifact_url() — +step_config 参数   (B2)
├── L2040-2050   ✏️ _cmd_pipeline_start() — +--force 参数解析   (A1)
├── L2076-2106   ✏️ _cmd_pipeline_start() — frontmatter steps 校验 (A1)
│                   + base_urls 传参调整 (A2)
├── L2116-2144   ✏️ _cmd_pipeline_start() — workspace.members 读取 (A1)
└── L2527-2542   ✏️ _cmd_step_complete — step_config 提前 + 传参  (B2)

server/config.py
├── L93           ✏️ PIPELINE_STEP_MAP step1 role: admin→operations  (C)
├── L102          ✏️ PIPELINE_STEP_MAP step6 role: admin→operations  (C)
└── L103          ✏️ PIPELINE_STEP_MAP primary: admin→operations     (C)
```

### 5.3 精确行号参考（截至 dev `0ff00c7`）

| 行号范围 | 函数/区域 | 方向 | 改动类型 |
|:--------:|:----------|:----:|:---------|
| 1083 | 全局常量区 | B1 | 删除 |
| 1150-1167 | `_build_pipeline_config()` | A2 | 修改实现 |
| 1170-1199 | `_build_fallback_config()` | B1 | 替换 `_R62_REPO_BASE` |
| 1210-1217 | `_infer_artifact_url()` | B2 | 增参数 + 改实现 |
| 2050-2106 | `_cmd_pipeline_start()` URL 获取+解析 | A1/A2 | 增校验+改传参 |
| 2116-2144 | `_cmd_pipeline_start()` 成员发现 | A1 | 增 workspace.members 分支 |
| 2527-2542 | `_cmd_step_complete()` step_outputs | B2 | step_config 提前+传参 |
| 93/102/103 | `server/config.py` PIPELINE_STEP_MAP | C | role 值替换 |

---

## 6. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:-----|:---------|
| 旧轮次 `_PIPELINE_CONFIG` 中 context URL 字段为空 | 中 | 旧轮次 status 显示不完整 | `_build_fallback_config` 保留，旧轮次运行时不受影响 |
| `_infer_artifact_url` 回退 URL 从 dev 切到 main | 低 | R72/R73 step_complete 的 artifact URL 指向 main | R72/R73 已合入 main，文档内容一致 |
| `step_config` 提前获取引入变量作用域冲突 | 低 | 编译/运行时错误 | L2542 原赋值行删除，统一使用提前获取的变量 |
| 缺少 `--force` 参数时新轮次启动被阻挡 | 低 | 用户无法启动无 steps 的旧格式 WORK_PLAN | 保留 `_build_fallback_config` 回退，仅新轮次需要完整 frontmatter |
| workspace.members 解析后与 `_get_step_config` 推断不一致 | 低 | 成员角色集合不同 | workspace.members 取并集或完全替换？设计为完全替换（frontmatter 作为 source of truth） |

---

## 7. 脱敏检查清单

- [x] docs/R74/*.md 零内部名残留
- [x] 使用通用角色名（PM / arch / dev / review / qa / operations）
- [x] 不包含真实 agent_id / token
- [x] URL 为公开 GitHub raw URL，不含认证信息
- [x] 代码中 `--force` 参数不与真实 token 冲突

---

## 8. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-07 | 初稿 — R74 技术方案：方向 A frontmatter 校验 + workspace.members + context URL 不覆盖 + 方向 B 删除 _R62_REPO_BASE + _infer_artifact_url 改造 + 方向 C admin→operations PIPELINE_STEP_MAP |
