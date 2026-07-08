---
pipeline:
  name: "R80 验证钩子系统"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R80/WORK_PLAN.md"
  workspace:
    members:
      architect:
        mention_keyword: "小开;architect"
        rules: "输出技术方案文档"
      developer:
        mention_keyword: "爱泰;developer"
        rules: "按技术方案编码"
      reviewer:
        mention_keyword: "小周;reviewer"
        rules: "代码审查"
      qa:
        mention_keyword: "泰虾;qa"
        rules: "测试验证"
      admin:
        mention_keyword: "小爱;admin"
        rules: "合并部署归档"
      product-manager:
        mention_keyword: "小谷;pm"
        rules: "PM 协调"
  steps:
    step2:
      role: architect
      title: 技术方案
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R80/R80-product-requirements.md"
      timeout_minutes: 120
    step3:
      role: developer
      title: 编码实现
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R80/R80-product-requirements.md"
      timeout_minutes: 120
    step4:
      role: reviewer
      title: 代码审查
      timeout_minutes: 120
    step5:
      role: qa
      title: 测试验证
      timeout_minutes: 120
    step6:
      role: admin
      title: 合并部署归档
      timeout_minutes: 60
---

# R80 工作计划 — 验证钩子系统：Step 自动验证推进 ✅🔁

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** 📋 定稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R80/R80-product-requirements.md v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动量 ~100 行净增，严禁 scope creep**

- ✅ 改：`server/handler.py` — _cmd_step_complete 插入验证门 + 3 个新函数/命令
- ✅ 改：`server/config.py` — 3 个新常量
- ✅ 新增：`scripts/verify_default.py` — 默认验证脚本
- ❌ 不改入：`shared/protocol.py`、各 bot 代码、Web 前端
- ❌ 不改出：F-3 角色体系、R36-C 公开注册、管线仪表盘

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | architect | developer | — |
| Step 3 | 💻 编码 | developer | architect | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | reviewer | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | reviewer | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | admin | architect | — |

---

## 1. 管线总览

### 改动范围

仅 `server/handler.py` + `server/config.py` + `scripts/verify_default.py`，精确改动点：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A | `_cmd_step_complete()` 插入验证门（约 L2852 后） | `server/handler.py` | ~15 行 |
| 2 | A | 新增 `_run_validation_hook()` 函数 | `server/handler.py` | ~30 行 |
| 3 | B | 新增 `_cmd_step_force()` 命令 + 权限检查 | `server/handler.py` | ~15 行 |
| 4 | B | `_ADMIN_COMMANDS` 注册 `step_force` / `step_verify` | `server/handler.py` | ~4 行 |
| 5 | C | 新增 `_cmd_step_verify()` 命令 | `server/handler.py` | ~15 行 |
| 6 | C | `_cmd_step_complete()` 中 force_bypass 守卫 | `server/handler.py` | ~5 行 |
| 7 | D | `ENABLE_VALIDATION_HOOK` / `VALIDATION_DEFAULT_SCRIPT` / `VALIDATION_DEFAULT_TIMEOUT` | `server/config.py` | ~5 行 |
| 8 | D | `scripts/verify_default.py` — 默认验证脚本 | 新增文件 | ~30 行 |

**总估算：** ~100 行净增

### 关键注意事项

| 注意点 | 说明 |
|:-------|:------|
| 🔑 验证门插入点 | 在 `_cmd_step_complete()` 中 Task 标记完成 + step_outputs 记录之后（L2852），查找下一 Step 之前（L2854） |
| 🔑 force_bypass 参数 | 通过 `params["_force_mode"]` 传入，在验证门前判断 `if params.get('_force_mode') and _check_pm_or_admin()` |
| 🔑 `_check_pm_or_admin()` | 需新增或复用 `auth.is_global_admin(sender_id) or sender_id == config.PIPELINE_PM_AGENT_ID` |
| ⚠️ `asyncio.create_subprocess_shell` | 验证脚本执行用异步子进程，不阻塞事件循环 |
| ⚠️ 默认脚本 | `scripts/verify_default.py` 只做 commit 存在性检查，接收 `output_ref` 参数 |

---

## 2. 管线步骤

### Step 1：文档就绪（PM — 本轮）

- ✅ 需求文档已审核通过
- ✅ WORK_PLAN 编写中
- 状态：📋 **当前**

### Step 2：技术方案（Architect — 主角：小开，备用：爱泰）

**任务：** 输出技术方案文档 `docs/R80/R80-tech-plan.md`

**关键设计决策待确认：**

1. **验证门插入点确认：** `_cmd_step_complete()` 中具体在哪个位置插（当前 L2852 是 step_outputs 记录末尾，L2854 是 `sorted(step_config.keys())` 查找下一 Step）
2. **`_run_validation_hook()` 函数签名确认**
3. **模板变量设计：** `{output_ref}` / `{step_name}` / `{round_name}` / `{workspace_dir}`
4. **`_check_pm_or_admin()` 辅助函数**
5. **`_cmd_step_force()` 权限模型**

**完成条件：** 技术方案推 dev + SHA

### Step 3：编码（Developer — 主角：爱泰，备用：小开）

**精确改动点：**

#### 改动 1：`server/config.py` — 新增 3 个常量

```python
# R80: Validation hook system
ENABLE_VALIDATION_HOOK = False   # 默认关，opt-in
VALIDATION_DEFAULT_SCRIPT = "python3 scripts/verify_default.py {output_ref}"
VALIDATION_DEFAULT_TIMEOUT = 30  # 秒
```

#### 改动 2：`server/handler.py` — 新增 `_run_validation_hook()` 函数

```python
async def _run_validation_hook(
    round_name: str, step_name: str, output_ref: str, step_config: dict,
) -> tuple[bool, str]:
    """从 step_config 读取 validation 配置，执行子进程验证脚本。"""
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
            script, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0:
            return (True, "✅ 验证通过（exit=0）")
        err_msg = stderr.decode().strip()[:300] or stdout.decode().strip()[:300]
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

#### 改动 3：`server/handler.py` — `_cmd_step_complete()` 中插入验证门

在 step_outputs 记录（~L2852）后、查找下一 Step（~L2854）前插入：

```python
    # ── R80 A: Validation hook gate ──
    force_bypass = params.get("_force_mode", False) and (
        auth.is_global_admin(sender_id) or sender_id == config.PIPELINE_PM_AGENT_ID
    )
    if config.ENABLE_VALIDATION_HOOK and not force_bypass:
        val_passed, val_msg = await _run_validation_hook(
            round_name, step_name, output_ref, step_config
        )
        if not val_passed:
            try:
                mgr = PipelineContextManager(config.DATA_DIR)
                await mgr.transition_to(round_name, PipelineStatus.BLOCKED, blocked_reason=val_msg)
            except Exception:
                pass
            return f"🔴 **{round_name} {step_name} 验证失败** ❌\n\n{val_msg}\n\n管线已进入 BLOCKED 状态。"
    # ── R80 A: End ──
```

#### 改动 4：`server/handler.py` — 新增 `_cmd_step_force()` 命令

```python
async def _cmd_step_force(sender_id: str, params: dict) -> str:
    """强制推进 Step（跳过验证钩子）"""
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_force <step_name> --output <sha> [--reason \"原因\"]"
    step_name = positional[0].lower()
    output_ref = params.get("output", "")
    reason = params.get("reason", "无说明")
    if not output_ref:
        return "❌ 缺少 --output <sha>"
    if not (auth.is_global_admin(sender_id) or sender_id == config.PIPELINE_PM_AGENT_ID):
        return "❌ 权限不足：仅 PM 或管理员可强制推进"
    _audit_logger.log(f"[R80] !step_force by {sender_id}: {step_name} → {output_ref} (reason: {reason})")
    params["_force_mode"] = True
    params["_positional"] = [step_name]
    params["output"] = output_ref
    return await _cmd_step_complete(sender_id, params)
```

#### 改动 5：`server/handler.py` — 新增 `_cmd_step_verify()` 命令

```python
async def _cmd_step_verify(sender_id: str, params: dict) -> str:
    """BLOCKED 状态下重新执行验证"""
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_verify <step_name> [--output <sha>]"
    step_name = positional[0].lower()
    output_ref = params.get("output", "")
    sender_ch = persistence.get_agent_channel(sender_id) or p.LOBBY
    round_name = next((r for r, s in _PIPELINE_STATE.items() if s.get("ws_id") == sender_ch), None)
    if not round_name:
        return "❌ 当前工作区无活跃管线"
    if not output_ref:
        pstate = _PIPELINE_STATE.get(round_name, {})
        output_ref = pstate.get("step_outputs", {}).get(step_name, {}).get("sha", "")
    step_config = _get_step_config(round_name)
    val_passed, val_msg = await _run_validation_hook(round_name, step_name, output_ref, step_config)
    if val_passed:
        try:
            mgr = PipelineContextManager(config.DATA_DIR)
            await mgr.transition_to(round_name, PipelineStatus.RUNNING)
        except Exception:
            pass
        return f"✅ **{round_name} {step_name} 验证通过** ✓\n\n{val_msg}\n\n管线已恢复 RUNNING。"
    return f"🔴 **{round_name} {step_name} 验证仍失败** ❌\n\n{val_msg}"
```

#### 改动 6：`server/handler.py` — `_ADMIN_COMMANDS` 注册

```python
"step_force": {
    "handler": _cmd_step_force, "min_role": 3,
    "desc": "强制推进 Step（跳过验证）",
},
"step_verify": {
    "handler": _cmd_step_verify, "min_role": 2,
    "desc": "BLOCKED 状态下重新执行验证",
},
```

#### 改动 7：`scripts/verify_default.py` — 新增文件

```python
"""R80: 全局默认验证脚本 — commit 存在性检查。"""
import sys, subprocess
output_ref = sys.argv[1] if len(sys.argv) > 1 else ""
if not output_ref:
    print("⏭️ 无 output_ref，跳过"); sys.exit(0)
result = subprocess.run(["git", "log", "--oneline", "-1", output_ref],
    capture_output=True, text=True)
if result.returncode != 0:
    print(f"❌ Commit {output_ref} 不存在于本地仓库"); sys.exit(1)
print(f"✅ Commit {output_ref} 本地存在"); sys.exit(0)
```

**完成后：** `git add server/handler.py server/config.py scripts/verify_default.py` → commit → `git push origin dev`

### Step 4：审查（Reviewer — 主角：小周，备用：泰虾）

**审查重点：**

| # | 审查项 | 预期 |
|:-:|:-------|:-----|
| 1 | 验证门插入 `_cmd_step_complete()` 位置正确 | Task 标记 + step_outputs 之后，下一 Step 查找之前 |
| 2 | `force_bypass` 条件正确 | 仅 `_force_mode=True` + PM/admin |
| 3 | 模板渲染安全 | `{output_ref}` / `{step_name}` / `{round_name}` 替换正确 |
| 4 | `ENABLE_VALIDATION_HOOK=False` 零影响 | 旧流程完全不变 |
| 5 | `_cmd_step_force()` 权限校验 | 非 PM/admin → 「权限不足」 |
| 6 | audit 日志记录 force 操作 | 含 sender_id / step / output / reason |
| 7 | `PipelineContext` BLOCKED ↔ RUNNING 转换正确 | `transition_to(RUNNING)` 在验证通过后执行 |
| 8 | 无 scope creep | 只改 ~100 行 |

### Step 5：测试（QA — 主角：泰虾，备用：小周）

**验收标准测试（从需求文档 §3 复制）：**

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | validation.script exit=0 → 正常推进 | 配置 `echo "ok"`（exit 0）→ 推进成功 | 脚本级测试 |
| ✅-2 | validation.script exit≠0 → BLOCKED | `!pipeline_status` 显示 BLOCKED | exit 1 脚本 |
| ✅-3 | `ENABLE_VALIDATION_HOOK=False` 时不验证 | 不调用 `_run_validation_hook` | 关闭开关测试 |
| ✅-4 | 无 validation 配置 → 跳过 | 正常推进 | 无配置测试 |
| ✅-5 | 脚本 timeout → 按要求阻塞/警告 | required=true 阻塞 | sleep 60 + timeout 3 |
| ✅-6 | 验证失败时 PM inbox 收到通知 | PM 收件箱出现通知消息 | 模拟验证失败 |
| ✅-7 | BLOCKED 状态持久化 | `pipeline_context.json` 含 blocked_reason | 读取文件 |
| ✅-8 | 模板变量正确渲染 | 脚本收到正确参数 | `echo {output_ref}` 脚本 |
| ✅-9 | PM/admin `!step_force` 跳过验证推进 | BLOCKED 管线被推进 | force 测试 |
| ✅-10 | 非 PM/admin `!step_force` 被拒 | 返回「权限不足」 | 普通角色发 force |
| ✅-11 | `!step_force` 不走验证钩子 | 验证脚本不执行 | force 时验证脚本无日志 |
| ✅-12 | audit 日志记录 force 操作 | 含操作信息 | 检查日志 |
| ✅-13 | `!step_verify` 重新执行验证 | 验证脚本再次执行 | 修复后 `!step_verify` |
| ✅-14 | 验证通过后恢复 RUNNING | 状态从 BLOCKED→RUNNING | `!pipeline_status` |
| ✅-15 | 不带 `--output` 时复用已有 SHA | 从 step_outputs 取 | 检查参数 |
| ✅-16 | 默认脚本检查 commit 存在性 | 存在→exit 0；不存在→exit 1 | `python3 verify_default.py` |
| ✅-17 | 默认脚本自动应用到无配置的 step | 无 validation 的走默认脚本 | 不配 validation 验证 |

### Step 6：合并部署归档（Admin — 主角：小爱，备用：小开）

**操作顺序：**

```bash
# 1. 合并 dev → main
git checkout main && git merge dev && git push origin main

# 2. 远程服务器 pull + rebuild + 重启
cd /opt/data/ws-bridge && git pull origin main
docker build -t ws-bridge:r80 .
docker stop ws-bridge && docker rm ws-bridge
docker run -d --name ws-bridge ... ws-bridge:r80

# 3. 验证部署
!pipeline_status R80

# 4. TODO.md v2.46 → v2.47
# 5. 关闭工作室 + 归档
```

---

## 3. 验收清单（从需求文档复制）

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | Step 配了 validation.script 且 exit=0 → 正常推进 | ⬜ |
| ✅-2 | Step 配了 validation.script 且 exit≠0 → BLOCKED | ⬜ |
| ✅-3 | `ENABLE_VALIDATION_HOOK=False` 时不执行验证 | ⬜ |
| ✅-4 | Step 未配 validation → 跳过验证直接推进 | ⬜ |
| ✅-5 | 验证脚本 timeout → 按要求阻塞/警告 | ⬜ |
| ✅-6 | 验证失败时 PM inbox 收到 BLOCKED 通知 | ⬜ |
| ✅-7 | BLOCKED 状态可在 pipeline_context.json 中查到 | ⬜ |
| ✅-8 | 模板变量正确渲染 | ⬜ |
| ✅-9 | PM/admin 使用 `!step_force` 跳过验证推进 | ⬜ |
| ✅-10 | 非 PM/admin 使用 `!step_force` 被拒 | ⬜ |
| ✅-11 | `!step_force` 不走验证钩子 | ⬜ |
| ✅-12 | audit 日志记录 force 操作 | ⬜ |
| ✅-13 | BLOCKED 下 `!step_verify` 重新执行验证 | ⬜ |
| ✅-14 | 验证通过后管线恢复 RUNNING 并推进 | ⬜ |
| ✅-15 | 不带 `--output` 时复用之前记录的 SHA | ⬜ |
| ✅-16 | 默认脚本正确检查 commit 存在性 | ⬜ |
| ✅-17 | 默认脚本配置继承到未配 validation 的 step | ⬜ |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-09 | 初稿 — R80 验证钩子系统 WORK_PLAN（审核后定稿） |
