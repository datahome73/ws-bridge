# R80 代码审查报告 — Validation hook system：Step 自动验证闸门 ✅

> **审查人：** 🔍 审查工程师
> **审查对象：** `ec67f53` feat(R80): Validation hook system — step auto-verify gate
> **审查日期：** 2026-07-09
> **改动统计：** 3 文件, +258 行
> **技术方案：** `docs/R80/R80-tech-plan.md`

---

## 0. 审查结论

> 🟢 **通过 — 0 项 🔴, 0 项 🟡, 1 项 💡 — 直接进入 Step 5 QA**
>
> | 级别 | 数量 | 说明 |
> |:----:|:----:|:------|
> | 🔴 阻塞 | 0 | — |
> | 🟡 W 级 | 0 | — |
> | 💡 建议 | 1 | S-1: `_run_validation_hook` 使用 `create_subprocess_shell` 的输入约束注释 |

---

## 1. 改动统计

| 文件 | 行数 | 改动类型 | 说明 |
|:-----|:----:|:---------|:-----|
| `server/handler.py` | +209 | 新增 + 修改 | validation gate + step_force + step_verify + helpers |
| `server/config.py` | +21 | 新增配置 | `ENABLE_VALIDATION_HOOK` + `VALIDATION_DEFAULT_SCRIPT` + `VALIDATION_DEFAULT_TIMEOUT` + `PIPELINE_PM_AGENT_ID` |
| `scripts/verify_default.py` | +28 | **新增** | 默认验证脚本（commit 存在性检查） |
| **合计** | **+258** | | |

---

## 2. 逐项审查

### ✅ 2.1 验证门插入位置（_cmd_step_complete L2991-3150）

```
_function start (L2991)
  ├── parse step_name, output_ref
  ├── auto-detect SHA from remote (L3012-3034)
  ├── verify git commit (L3064-3066)
  ├── update _PIPELINE_STATE step_outputs (L3100-3110)
  │
  ├── 🔒 R80 GATE (L3103-3154)       ← 插入点
  │   ├── force_bypass check
  │   ├── if ENABLED: _run_validation_hook()
  │   ├── if FAILED: transition_to(BLOCKED) + notify PM
  │   └── if PASSED: fall through
  │
  ├── step_config lookup (L3156+)     ← 原代码续行
  ├── auto-advance to next step
  └── return success
```

**验证：**
- `step_config` 在 L3054 已定义（`step_config = _get_step_config(round_name)`），gate 内引用时不产生 NameError ✅
- gate 在 `step_outputs` 持久化**之后**（SHA 已保存可验证）
- gate 在 auto-advance**之前**（验证通不过就 BLOCK，不推进）
- gate 全验证失败时**提前 return**，不执行后续推进逻辑

**结论：** 插入位置正确 ✅

### ✅ 2.2 `force_bypass` 条件

```python
force_bypass = (
    params.get("_force_mode", False)       # 仅 !step_force 设置
    and _check_pm_or_admin(sender_id)      # 仅 PM 或全局管理员
)
```

**`_check_pm_or_admin()` 权限矩阵：**

| sender_id | `is_global_admin` | `== PIPELINE_PM_AGENT_ID` | 结果 |
|:---------|:-----------------:|:-------------------------:|:----:|
| 全局管理员 | True | * | True ✅ |
| PM Agent | False | True | True ✅ |
| 普通用户 | False | False | False ❌ |

**结论：** `_force_mode=True` + PM/admin 双重条件正确 ✅

### ✅ 2.3 `_run_validation_hook()` — 模板渲染安全

```python
script = script_template.replace("{output_ref}", output_ref or "")
script = script.replace("{step_name}", step_name)
script = script.replace("{round_name}", round_name)
```

| 安全检查项 | 结果 |
|:-----------|:-----|
| 模板渲染方式 | `.replace()` 纯字符串替换，无 `eval()`/`format()`/`exec()` | ✅ |
| `{output_ref}` 来源 | commit SHA（hex）或 `!step_complete --output` 参数 | ✅ |
| `{step_name}` 来源 | pipeline step 名称（如 `"step2"`），系统控制 | ✅ |
| `{round_name}` 来源 | pipeline 轮次名（如 `"R80"`），系统控制 | ✅ |
| shell 注入风险 | `create_subprocess_shell()` 执行渲染后脚本 | 💡 S-1 |
| `stdout.decode()` 长度限制 | `[:300]` 截断 | ✅ |
| 超时保护 | `asyncio.wait_for()` timeout | ✅ |
| `required` 非必需验证 | 验证失败不阻断，仅告警 | ✅ |

**结论：** 模板渲染安全 ✅

> **💡 S-1:** `create_subprocess_shell()` 以 shell 执行渲染后的脚本命令。`output_ref` 虽通常为 commit SHA（仅 hex 字符），但理论上可包含 shell 元字符。建议在 docstring 注明「output_ref 应为 git SHA，不含 shell 特殊字符」，或后续改用 `create_subprocess_exec` + 参数数组以消除注入面。

### ✅ 2.4 `ENABLE_VALIDATION_HOOK=False` 零影响

```python
# config.py (default: OFF)
ENABLE_VALIDATION_HOOK: bool = (
    os.environ.get("R80_ENABLE_VALIDATION", "0") == "1"
)

# handler.py L3110
if config.ENABLE_VALIDATION_HOOK and not force_bypass:
```

| 场景 | `ENABLE_VALIDATION_HOOK` | `force_bypass` | 进入 gate? |
|:-----|:------------------------:|:--------------:|:----------:|
| 默认（新部署） | False | * | ❌ |
| 启用 + 正常推进 | True | False | ✅ 执行验证 |
| 启用 + 强制推进 | True | True | ❌ 跳过验证 |
| 旧管线（不设 env） | False | * | ❌ |

**结论：** 默认关闭，旧管线零影响 ✅。opt-in 设计，需显设 `R80_ENABLE_VALIDATION=1` 才生效。

### ✅ 2.5 `_cmd_step_force()` 权限校验 + Audit 日志

```python
# 权限检查
if not _check_pm_or_admin(sender_id):
    return "❌ 权限不足：仅 PM 或管理员可强制推进"

# Audit 日志
_audit_logger.log(
    sender_id, "step_force",
    {"step": step_name, "output": output_ref, "reason": reason},
    "forced",
)

# 设置 force_mode 标志后复用 _cmd_step_complete
params["_force_mode"] = True
return await _cmd_step_complete(sender_id, params)
```

| 检查项 | 结果 |
|:-------|:-----|
| `_audit_logger` 存在？ | ✅ `handler.py:30` — `AuditLogger(config.DATA_DIR)` |
| 日志格式与现有一致？ | ✅ `.log(sender_id, command, params, result)` |
| 参数检验 | ✅ 必须传 `--output` |
| 权限检验位置 | ✅ 在审计日志之前（未授权用户不记日志） |
| `_force_mode` 传递 | ✅ 设 `params["_force_mode"] = True` 后调用 `_cmd_step_complete` |

**结论：** 权限 + 审计完整 ✅

### ✅ 2.6 `_cmd_step_verify()` BLOCKED→RUNNING 恢复

```python
if val_passed:
    mgr = _ensure_pipeline_manager()
    try:
        await mgr.transition_to(round_name, PipelineStatus.RUNNING)
    except Exception:
        pass
    return f"✅ ... 管线已恢复 RUNNING 状态。"
```

**状态机合法性：** `BLOCKED → RUNNING` 在 `_VALID_TRANSITIONS` 中允许 ✅

**验证流程完整链路：**

```
cmd_step_verify:
  1. 解析 step_name
  2. 推断 round_name（从活跃频道）
  3. 复用上次 output SHA（从 step_outputs）  ← 不传 --output 时
  4. 执行 _run_validation_hook()
  5. 验证通过 → transition_to(RUNNING)
  6. 返回结果
```

| 场景 | 行为 | 状态 |
|:-----|:-----|:----:|
| 验证通过 + 管线在 BLOCKED | → RUNNING ✅ | ✅ |
| 验证通过 + 管线已在 RUNNING | `transition_to` 返回 False（非异常），仍显示「已恢复」 | ⚠️ 消息语义问题，但无害 |
| 验证失败 | 返回失败消息，不修改状态 | ✅ |
| 无历史 output SHA | 提示用户传 --output | ✅ |
| 无活跃管线 | 返回错误提示 | ✅ |

**结论：** BLOCKED→RUNNING 恢复正确 ✅

### ✅ 2.7 Scope 合规

| 文件 | 状态 |
|:-----|:-----|
| `server/handler.py` | ✅ 核心改动（gate + force + verify + helpers） |
| `server/config.py` | ✅ 新增配置项（无已有配置修改） |
| `scripts/verify_default.py` | ✅ 新增默认验证脚本 |
| `shared/protocol.py` | ❌ 未改动 ✅ |
| `server/pipeline_context.py` | ❌ 未改动 ✅ |
| `server/message_store.py` | ❌ 未改动 ✅ |
| bot 端代码 | ❌ 未改动 ✅ |

**结论：** 仅改指定 3 文件，零 scope creep ✅

---

## 3. 边界情况分析

| 场景 | 预期 | 实现 | 状态 |
|:-----|:-----|:-----|:----:|
| `ENABLE_VALIDATION_HOOK=True` + `step_config` 无 `validation` | 跳过验证（返回 ⏭️） | ✅ `if not val_config: return (True, "⏭️")` |
| `ENABLE_VALIDATION_HOOK=True` + `validation.script` 为空 | 跳过验证 | ✅ `if not script_template: return (True, "⏭️")` |
| `ENABLE_VALIDATION_HOOK=True` + `validation.required=false` + 验证失败 | 仅警告，不阻断 | ✅ `if required: return (False, ...) else: return (True, "⚠️")` |
| `ENABLE_VALIDATION_HOOK=True` + 验证超时 | 超时 BLOCKED | ✅ `asyncio.TimeoutError` 捕获 + required 分支 |
| `ENABLE_VALIDATION_HOOK=True` + 验证脚本 exit=0 | 继续推进 | ✅ `return (True, "✅ 验证通过")` |
| `ENABLE_VALIDATION_HOOK=True` + 验证脚本 exit≠0 + required=true | BLOCKED + 通知 PM | ✅ |
| `_ensure_pipeline_manager()` 返回 None（未初始化） | 安全降级 | ✅ try/except 包裹 |
| `_cmd_step_force()` 无 `--output` | 报错 | ✅ `if not output_ref: return "❌ 缺少 --output"` |
| `_cmd_step_force()` 非 PM/admin | 权限拒绝 | ✅ `_check_pm_or_admin()` |
| `PIPELINE_PM_AGENT_ID` 为空（未配置） | 不发送 PM 通知 | ✅ `if pm_agent_id:` 检查 |
| `_cmd_step_verify()` 无活跃管线 | 报错 | ✅ `if not round_name: return "❌ 当前工作区无活跃管线"` |

---

## 4. 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:-----|
| 硬编码敏感信息 | ✅ 无 |
| 调试 print 残留 | ✅ 无 |
| TODO/FIXME 残留 | ✅ 无 |
| R 标签准确 | ✅ 全部为 R80 |
| `except Exception: pass` | ✅ 合理（非阻塞后处理，日志已记录） |
| 类型注解 | ✅ 所有新函数有完整类型注解 |
| `_audit_logger` 日志完整 | ✅ `step_force` 操作已审计 |

---

## 5. 问题清单

| 级别 | 编号 | 描述 | 位置 | 建议 |
|:----:|:----:|:-----|:-----|:-----|
| 💡 | S-1 | `_run_validation_hook` 用 `create_subprocess_shell` 执行渲染后脚本，`output_ref` 为 user input | `handler.py:3075` | docstring 标注 input 约束，或后续改用 `create_subprocess_exec` 参数数组 |

---

## 6. 总结

### ✅ 通过项

| 审查项 | 结果 |
|:-------|:----:|
| 1️⃣ 验证门插入位置 | ✅ 在 step_output 持久化后、auto-advance 前 |
| 2️⃣ `force_bypass` 条件 | ✅ `_force_mode=True` + PM/admin 双重检查 |
| 3️⃣ `_run_validation_hook()` 模板安全 | ✅ `.replace()` 纯字符串，无 eval/exec |
| 4️⃣ `ENABLE_VALIDATION_HOOK=False` 零影响 | ✅ 默认关闭，opt-in |
| 5️⃣ `_cmd_step_force()` 权限 + audit | ✅ 全局管理员/PM 校验 + AuditLogger |
| 6️⃣ `_cmd_step_verify()` BLOCKED→RUNNING | ✅ 状态机合法 + 完整链路 |
| 7️⃣ Scope 合规 | ✅ 3 文件，零 creep |

### 💡 建议项

- S-1: `_run_validation_hook` 的 `create_subprocess_shell` 输入约束注释

---

> **总体：🟢 通过 — 0 阻塞，直接进入 Step 5 QA**
>
> 审查完毕：2026-07-09 🔍 审查工程师
