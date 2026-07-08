# R80 技术方案 — 验证钩子系统：Step 自动验证推进 ✅🔁

> **版本：** v1.0
> **状态：** ✅ 技术方案
> **架构师：** 👷 架构师
> **日期：** 2026-07-09
> **基于需求：** docs/R80/R80-product-requirements.md v1.0
> **基线：** `1dbdee7`（main）
> **改动范围：** `server/handler.py` `server/config.py` `scripts/verify_default.py`

---

## 目录

1. [验证门插入点确认](#1-验证门插入点确认)
2. [_run_validation_hook() 函数签名](#2-_run_validation_hook-函数签名)
3. [模板变量设计](#3-模板变量设计)
4. [_check_pm_or_admin() 权限校验](#4-_check_pm_or_admin-权限校验)
5. [_cmd_step_force() 命令设计](#5-_cmd_step_force-命令设计)
6. [_cmd_step_verify() 命令设计](#6-_cmd_step_verify-命令设计)
7. [配置常量](#7-配置常量)
8. [改动汇总](#8-改动汇总)
9. [兼容性分析](#9-兼容性分析)

---

## 1. 验证门插入点确认

### 1.1 精确位置

**文件：** `server/handler.py`
**函数：** `_cmd_step_complete()`（L2742）
**插入点：** **L2853** — step_outputs 记录块结束之后，下一 Step 查找（L2854）之前。

```python
# L2840-2852: step_outputs 记录（R66/R69 已有）
        step_outputs[step_name] = {
            "sha": output_ref or "",
            "title": ...,
            "output_desc": ...,
            "summary": ...,
            "artifact_url": ...,
            "timestamp": time.time(),
        }
                                    # ← ★ R80 验证门插入于此（L2853 的空行位置）
# L2854: 下一 Step 查找
    step_config = _get_step_config(round_name)
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
```

### 1.2 为什么插在这里

| 理由 | 说明 |
|:-----|:------|
| ✅ 产出已记录 | step_outputs 已经写入，输出 SHA 可传给验证脚本 |
| ✅ 下一 Step 未开始 | 验证失败时不会导致状态不一致 |
| ✅ 变量已就绪 | `round_name`、`step_name`、`output_ref`、`step_config` 都在作用域内 |
| ✅ 不阻塞已有流程 | Task 标记、产出记录都已完成，仅追加验证 |

### 1.3 插入代码

```python
        # ── R80 A: Validation hook gate ──────────────────────────────
        force_bypass = (
            params.get("_force_mode", False)
            and _check_pm_or_admin(sender_id)
        )
        if config.ENABLE_VALIDATION_HOOK and not force_bypass:
            val_passed, val_msg = await _run_validation_hook(
                round_name, step_name, output_ref, step_config
            )
            if not val_passed:
                # Block the pipeline
                mgr = _ensure_pipeline_manager()
                try:
                    await mgr.transition_to(
                        round_name, PipelineStatus.BLOCKED,
                        blocked_reason=val_msg,
                    )
                except Exception:
                    pass
                # Notify PM
                pm_inbox = _get_pm_inbox()
                if pm_inbox:
                    try:
                        await _broadcast_to_channel(pm_inbox, {
                            "type": "broadcast",
                            "channel": pm_inbox,
                            "from_name": "系统",
                            "from_agent": SYSTEM_AGENT_ID,
                            "content": (
                                f"🔴 {round_name} {step_name} 验证失败\n\n"
                                f"{val_msg}\n\n"
                                f"操作：`!step_force {step_name} --output {output_ref}` 强制推进\n"
                                f"或修复后 `!step_verify {step_name}` 重新验证"
                            ),
                            "ts": time.time(),
                        })
                    except Exception:
                        pass
                return f"🔴 **{round_name} {step_name} 验证失败** ❌\n\n{val_msg}\n\n管线已进入 BLOCKED 状态。"
        # ── R80 A: End ──
```

---

## 2. _run_validation_hook() 函数签名

### 2.1 签名

```python
async def _run_validation_hook(
    round_name: str,
    step_name: str,
    output_ref: str,
    step_config: dict,
) -> tuple[bool, str]:
    """执行验证钩子。

    从 step_config 读取 validation 配置，执行子进程验证脚本。
    验证失败时返回 (False, 错误消息)。

    Args:
        round_name: 管线轮次名（模板变量 {round_name}）
        step_name: Step 名称（模板变量 {step_name}）
        output_ref: 产出引用（模板变量 {output_ref}）
        step_config: _get_step_config() 返回的 step 配置 dict

    Returns:
        (通过?, 消息)
        (True, "✅ ...") = 验证通过 / 跳过
        (False, "❌ ...") = 验证失败
    """
```

### 2.2 实现

```python
async def _run_validation_hook(
    round_name: str, step_name: str, output_ref: str, step_config: dict,
) -> tuple[bool, str]:
    """执行验证钩子。从 step_config 读取 validation 配置。"""
    val_config = step_config.get(step_name, {}).get("validation", {})
    if not val_config:
        return (True, "⏭️ 无验证脚本，跳过")

    script_template = val_config.get("script", config.VALIDATION_DEFAULT_SCRIPT)
    if not script_template:
        return (True, "⏭️ 验证脚本为空，跳过")
    timeout = val_config.get("timeout", config.VALIDATION_DEFAULT_TIMEOUT)
    required = val_config.get("required", True)

    # 模板渲染
    script = script_template.replace("{output_ref}", output_ref or "")
    script = script.replace("{step_name}", step_name)
    script = script.replace("{round_name}", round_name)

    try:
        proc = await asyncio.create_subprocess_shell(
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        if proc.returncode == 0:
            return (True, "✅ 验证通过（exit=0）")
        err_msg = (stderr.decode().strip()[:300]
                   or stdout.decode().strip()[:300])
        if required:
            return (False, f"❌ 验证失败（exit={proc.returncode}）: {err_msg}")
        return (True, f"⚠️ 验证警告（exit={proc.returncode}，非必需）: {err_msg}")
    except asyncio.TimeoutError:
        if required:
            return (False, f"❌ 验证超时（>{timeout}s）")
        return (True, f"⚠️ 验证超时（非必需）")
    except Exception as e:
        if required:
            return (False, f"❌ 验证异常: {e}")
        return (True, f"⚠️ 验证异常（非必需）: {e}")
```

### 2.3 函数位置

声明在 `_cmd_step_complete()` 之前，与其他辅助函数同级（约 L2700-L2741 区间）。

---

## 3. 模板变量设计

### 3.1 变量表

| 变量名 | 替换值 | 示例 | 说明 |
|:-------|:-------|:-----|:------|
| `{output_ref}` | `output_ref` 参数值 | `abc123def` | git commit SHA 或文件名 |
| `{step_name}` | 当前 Step 名 | `step2` | 小写 step 名称 |
| `{round_name}` | 管线轮次名 | `R80` | 大写 R + 数字 |
| `{workspace_dir}` | 仓库路径 | `/opt/data/ws-bridge` | 物理文件系统路径 |

### 3.2 渲染顺序

```python
script = script_template.replace("{output_ref}", output_ref or "")
script = script.replace("{step_name}", step_name)
script = script.replace("{round_name}", round_name)
script = script.replace("{workspace_dir}", config.REPO_PATH)
```

先替换长变量（避免 `{output_ref}` 与 `{output}` 混淆），按变量名长度排序。

### 3.3 WORK_PLAN 中的配置示例

```yaml
# 在 frontmatter pipeline.steps 中配置
steps:
  step2:
    role: architect
    title: 技术方案
    validation:
      script: "python3 scripts/verify_default.py {output_ref}"
      timeout: 30
      required: true
  step3:
    role: developer
    title: 编码实现
    validation:
      script: "python3 scripts/verify_commit.py {output_ref} {round_name}"
      timeout: 60
      required: true
```

---

## 4. _check_pm_or_admin() 权限校验

### 4.1 函数签名与实现

```python
# server/handler.py — 新增辅助函数

def _check_pm_or_admin(sender_id: str) -> bool:
    """检查发送者是否有「强制推进」权限。

    满足任一条件即可：
    1. 全局管理员（auth.is_global_admin）
    2. PM Agent（sender_id == config.PIPELINE_PM_AGENT_ID，如有配置）

    Args:
        sender_id: 待检查的 agent_id

    Returns:
        True = 有权限（PM 或全局管理员）
        False = 无权限
    """
    if auth.is_global_admin(sender_id):
        return True
    pm_agent = getattr(config, "PIPELINE_PM_AGENT_ID", None)
    if pm_agent and sender_id == pm_agent:
        return True
    return False
```

### 4.2 config.PIPELINE_PM_AGENT_ID

**新增**到 `server/config.py`：

```python
# R80: PM agent ID for validation force bypass
PIPELINE_PM_AGENT_ID: str = os.environ.get("WS_PM_AGENT_ID", "")
```

**环境变量：** `WS_PM_AGENT_ID`（可选，默认空字符串 — 空时 `_check_pm_or_admin` 仅检查全局管理员）。

### 4.3 调用场景

| 函数 | 调用 `_check_pm_or_admin()` | 用途 |
|:-----|:---------------------------|:------|
| `_cmd_step_complete()` 验证门 | 是 | 判断 `force_bypass = params.get("_force_mode") && _check_pm_or_admin(...)` |
| `_cmd_step_force()` | 是 | 判断调用者是否可执行强制推进 |

---

## 5. _cmd_step_force() 命令设计

### 5.1 命令接口

```
!step_force <step_name> --output <sha> [--reason "原因"]
```

### 5.2 权限模型

| 角色 | 是否可执行 | 说明 |
|:-----|:-----------|:------|
| 全局管理员（admin） | ✅ | 最高权限，可跳过任何验证 |
| PM（config.PIPELINE_PM_AGENT_ID） | ✅ | 可跳过验证 |
| 普通角色（arch/dev/review/qa） | ❌ | 需先联系 admin 或 PM |

### 5.3 实现

```python
async def _cmd_step_force(sender_id: str, params: dict) -> str:
    """强制推进 Step（跳过验证钩子）。

    用法：!step_force <step_name> --output <sha> [--reason "原因"]
    权限：仅 PM 或全局管理员可执行。
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_force <step_name> --output <sha> [--reason \"原因\"]"

    step_name = positional[0].lower()
    output_ref = params.get("output", "")
    reason = params.get("reason", "无说明")

    if not output_ref:
        return "❌ 缺少 --output <sha>"

    if not _check_pm_or_admin(sender_id):
        return "❌ 权限不足：仅 PM 或管理员可强制推进"

    # 审计日志
    _audit_logger.log(
        f"[R80] !step_force by {sender_id}: "
        f"{step_name} → {output_ref} (reason: {reason})"
    )

    # 传给 _cmd_step_complete，携带 _force_mode 标志
    params["_force_mode"] = True
    return await _cmd_step_complete(sender_id, params)
```

### 5.4 force_bypass 在验证门中的判定

```python
force_bypass = (
    params.get("_force_mode", False)
    and _check_pm_or_admin(sender_id)
)
```

`params.get("_force_mode")` 确保只有显式传入 force 标志时才跳过。从 `_cmd_step_force` 调用时设 `True`，从 `!_cmd_step_complete` 调用时值为 `None/False`。

---

## 6. _cmd_step_verify() 命令设计

### 6.1 命令接口

```
!step_verify <step_name> [--output <sha>]
```

### 6.2 实现

```python
async def _cmd_step_verify(sender_id: str, params: dict) -> str:
    """BLOCKED 状态下重新执行验证钩子。

    用法：!step_verify <step_name> [--output <sha>]
    若不传 --output，从 step_outputs 复用上次的 SHA。
    验证通过后将管线从 BLOCKED 恢复为 RUNNING。
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_verify <step_name> [--output <sha>]"

    step_name = positional[0].lower()
    output_ref = params.get("output", "")

    # 确定 round_name（从发送者的活跃频道推断）
    sender_ch = persistence.get_agent_channel(sender_id) or p.LOBBY
    round_name = next(
        (r for r, s in _PIPELINE_STATE.items() if s.get("ws_id") == sender_ch),
        None,
    )
    if not round_name:
        return "❌ 当前工作区无活跃管线"

    # 未提供 --output 时，从 step_outputs 复用
    if not output_ref:
        pstate = _PIPELINE_STATE.get(round_name, {})
        output_ref = (
            pstate.get("step_outputs", {})
            .get(step_name, {})
            .get("sha", "")
        )
        if not output_ref:
            return f"❌ 未找到 {step_name} 的历史产出 SHA，请使用 --output 指定"

    step_config = _get_step_config(round_name)
    val_passed, val_msg = await _run_validation_hook(
        round_name, step_name, output_ref, step_config,
    )

    if val_passed:
        # 恢复管线运行
        mgr = _ensure_pipeline_manager()
        try:
            await mgr.transition_to(round_name, PipelineStatus.RUNNING)
        except Exception:
            pass
        return (
            f"✅ **{round_name} {step_name} 验证通过** ✓\n\n"
            f"{val_msg}\n\n"
            f"管线已恢复 RUNNING 状态。"
        )

    return f"🔴 **{round_name} {step_name} 验证仍失败** ❌\n\n{val_msg}"
```

### 6.3 权限要求

| 角色 | 是否可执行 |
|:-----|:-----------|
| 任意活跃工作室成员 | ✅ |

`!step_verify` 不属于强制操作，不要求 PM/admin 权限。任何在工作室中的成员均可触发重新验证。

---

## 7. 配置常量

### 7.1 config.py 新增

```python
# ── R80: Validation hook system ────────────────────────────────
ENABLE_VALIDATION_HOOK: bool = (
    os.environ.get("R80_ENABLE_VALIDATION", "0") == "1"
)
"""验证钩子总开关。默认关闭（opt-in），旧管线不受影响。"""

VALIDATION_DEFAULT_SCRIPT: str = os.environ.get(
    "R80_VALIDATION_SCRIPT",
    "python3 scripts/verify_default.py {output_ref}",
)
"""默认验证脚本模板。未配 validation.script 时使用此值。"""

VALIDATION_DEFAULT_TIMEOUT: int = int(
    os.environ.get("R80_VALIDATION_TIMEOUT", "30")
)
"""默认验证超时（秒）。"""

PIPELINE_PM_AGENT_ID: str = os.environ.get("WS_PM_AGENT_ID", "")
"""PM 的 agent_id。用于 step_force 权限判断。为空时仅检查全局管理员。"""
```

### 7.2 handler.py 顶部新增

```python
# R80: System agent ID for validation notifications
SYSTEM_AGENT_ID: str = "_system"
```

### 7.3 默认验证脚本

```python
# scripts/verify_default.py
"""
R80: 全局默认验证脚本 — commit 存在性检查。

用法：python3 scripts/verify_default.py <output_ref>
exit=0: 存在  exit=1: 不存在
"""

import sys
import subprocess

output_ref = sys.argv[1] if len(sys.argv) > 1 else ""
if not output_ref:
    print("⏭️ 无 output_ref，跳过")
    sys.exit(0)

result = subprocess.run(
    ["git", "log", "--oneline", "-1", output_ref],
    capture_output=True, text=True,
)

if result.returncode != 0:
    print(f"❌ Commit {output_ref} 不存在于本地仓库")
    sys.exit(1)

print(f"✅ Commit {output_ref} 本地存在")
sys.exit(0)
```

---

## 8. 改动汇总

### 8.1 文件清单

| 文件 | 改动 | 行数 | 说明 |
|:-----|:------|:----:|:------|
| `server/config.py` | 新增 4 个常量 | ~5 行 | ENABLE_VALIDATION_HOOK / VALIDATION_DEFAULT_SCRIPT / VALIDATION_DEFAULT_TIMEOUT / PIPELINE_PM_AGENT_ID |
| `server/handler.py` | 新增 `_run_validation_hook()` | ~35 行 | 验证脚本执行（async subprocess + 模板渲染） |
| `server/handler.py` | 新增 `_check_pm_or_admin()` | ~10 行 | 权限校验辅助函数 |
| `server/handler.py` | 新增 `_cmd_step_force()` | ~20 行 | 强制推进命令 |
| `server/handler.py` | 新增 `_cmd_step_verify()` | ~25 行 | 重新验证命令 |
| `server/handler.py` | 修改 `_cmd_step_complete()` | ~15 行 | L2853 插入验证门 |
| `server/handler.py` | `_ADMIN_COMMANDS` 注册 | ~4 行 | step_force / step_verify |
| `scripts/verify_default.py` | **新增** | ~20 行 | 默认 commit 存在性检查 |
| **合计** | | **~100 行净增** | |

### 8.2 无改动项

| 模块 | 原因 |
|:-----|:------|
| `shared/protocol.py` | 本轮不新增消息类型 |
| `server/agent_card.py` | Agent Card 数据结构不变 |
| `server/pipeline_sync.py` | Git sync 独立 |
| `server/message_store.py` | 不新增查询函数 |
| Bot 代码 | 验证对 bot 透明 |
| Web/前端 | 不涉及 |

## 9. 兼容性分析

### 9.1 开关机制

| 开关状态 | 行为 | 兼容性 |
|:---------|:------|:-------|
| `ENABLE_VALIDATION_HOOK=False`（默认） | `_cmd_step_complete()` 不调用 `_run_validation_hook()`，流程与 R79 完全一致 | ✅ 零影响 |
| `ENABLE_VALIDATION_HOOK=True`，step 无 validation 配置 | `_run_validation_hook()` 读到空配置 → 返回 (True, "跳过") | ✅ 无阻塞 |
| `ENABLE_VALIDATION_HOOK=True`，有 validation 配置 | 执行验证 → 通过继续 / 失败 BLOCKED | ✅ 新行为 |

### 9.2 旧命令兼容

| 命令 | 改造后行为 | 兼容性 |
|:-----|:----------|:-------|
| `!step_complete` | 验证门开启时多一步验证 | ✅ 流程语义不变 |
| `!step_force` | 新命令 | ✅ 新增 |
| `!step_verify` | 新命令 | ✅ 新增 |
| `!pipeline_status` | 展示 BLOCKED 状态（已有） | ✅ 不变 |
| 其他 41 个命令 | 不受影响 | ✅ |

### 9.3 BLOCKED 状态的响应流程

```
!step_complete → 验证失败 → BLOCKED
    ↓
PM/admin: `!step_force step2 --output <sha>` → 跳过验证 → RUNNING
    ↓
Dev: 修复产出 → `!step_verify step2` → 验证通过 → RUNNING
```

---

## 10. 关键设计决策确认

| # | 决策项 | 决策 | 状态 |
|:-:|:-------|:-----|:-----|
| 1 | 验证门插入点 | `_cmd_step_complete()` L2853 — step_outputs 记录后、下一 Step 查找前 | ✅ 确认 |
| 2 | `_run_validation_hook()` 签名 | `(round_name, step_name, output_ref, step_config) → tuple[bool, str]` | ✅ 确认 |
| 3 | 模板变量 | `{output_ref}` / `{step_name}` / `{round_name}` / `{workspace_dir}` | ✅ 确认 |
| 4 | `_check_pm_or_admin()` | `auth.is_global_admin()` 或 `sender_id == PIPELINE_PM_AGENT_ID` | ✅ 确认 |
| 5 | `_cmd_step_force()` 权限 | 仅 PM/全局管理员可通过 `_force_mode=True` 跳过验证 | ✅ 确认 |
| 6 | 开关默认值 | `ENABLE_VALIDATION_HOOK=False`（opt-in，零影响旧管线） | ✅ 确认 |

---

## 11. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-09 | 初稿 — R80 验证钩子系统技术方案：验证门插入点 + _run_validation_hook + _cmd_step_force + _cmd_step_verify |
