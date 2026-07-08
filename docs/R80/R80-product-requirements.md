# R80 产品需求 — 验证钩子系统：Step 自动验证推进 ✅🔁

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-09
> **基线：** `0475ede`（main 最新 — R79 合并部署）
> **本轮改动范围：** `server/handler.py` + `server/config.py` + 可选新模块
> **参考：** ARCHITECTURE-REQUIREMENTS.md §6 P1「验证钩子系统」、TODO.md F-17（已完成）、R79 §4（明确验证钩子留待 R80+）

---

## 0. 先验验证：已就绪的基础设施

| 验证项 | 结果 | 确认方式 |
|:-------|:----:|:---------|
| `_cmd_step_complete()` 流程完整（~L2742-3030） | ✅ | handler.py 现有代码 |
| `_verify_git_commit()` 模式已有（R55 C） | ✅ | handler.py ~L2068-2100 |
| PipelineContext `BLOCKED` 状态已定义 | ✅ | `pipeline_context.py` L28 |
| PipelineContextManager `transition_to()` 已实现 | ✅ | 可设管线为 BLOCKED 状态 |
| WORK_PLAN frontmatter 已支持 step 自定义 config | ✅ | R74 管线通用化完成 |
| `config.py` 环境变量配置模式成熟 | ✅ | 大量 ENABLE_XXX 常量 |
| `!_cmd*` 命令路由基础设施 | ✅ | 多年迭代成熟 |

---

## 1. 问题背景

### 1.1 现状：Step 推进无自动化验证门

当前管线 Step 推进流程：

```
bot 完成编码 → !step_complete step3 --output <sha>
  ├─ R55 C: Git commit 存在性检查 ✅/❌
  └─ 立即推进到 Step 4（审查）
```

**关键缺失：** 除了检查 commit 是否存在，Server 不执行任何实质性的验证。Step 的产出质量完全依赖下一角色的判断。

| 场景 | 当前行为 | 问题 |
|:-----|:---------|:-----|
| Dev 提交通知「编码完成」但 git log 零新提交 | `!step_complete` 因缺 --output 拒绝 | ✅ 已有保护（R65 B1 + R55 C） |
| Dev 提交了代码但 lint 有错 / 测试不过 | Server 不检查 → 直接推给 Review | ❌ 无保护 |
| Dev 提交但文件结构不符合技术方案 | Server 不检查 → Review 发现后退回 | ❌ 增加一轮往返 |
| History Tab 或 Web API 验证 | QA bot 人工检查 → 依赖 bot 回复速度 | ❌ 延迟+不确定性 |

### 1.2 根因分析

| # | 根因 | 说明 |
|:-:|:-----|:------|
| ① | **Server 对产出内容零理解** | Server 是纯规则引擎，不解析文档/代码内容。但 Server 可以**执行验证脚本**——脚本是规则化的外部程序，不依赖 LLM |
| ② | **没有「验证→推进」的两阶段模型** | 当前的 `step_complete` 是「声明完成→立即推进」的同步动作，没有「声明完成→执行验证→根据结果推进/退回」的分步模型 |
| ③ | **验证逻辑硬编码在 bot 代码中** | 各 bot 自行实现验证（如测试工程师的测试脚本），但 Server 无法触发/约束这些验证——验证是 bot 的自发行为，非管线强制门 |

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:-----|:------|
| 🔴 **管线质量无保障** | Dev 提交有问题的代码后直接推给 Review，浪费审查资源 |
| 🟡 **R79 已明确 R80 接手** | 验证钩子在 R79 不纳入范围中标注「留待 R80+」，阶段衔接自然 |
| 🟡 **基础设施已就绪** | PipelineContext BLOCKED 状态、_verify_git_commit 模式、frontmatter step config 都已存在——只差验证钩子串联 |
| 🟢 **改动量可控** | 纯 server 端 ~80 行净增，不改协议、不改 bot 代码、不改变现有 step_complete 流程 |

---

## 2. 功能需求

### 设计原则

> **验证钩子是规则引擎的扩展，不是 LLM 的替代。** Server 执行的是**可脚本化**的验证——lint 检查、结构检查、commit 元数据检查。LLM 级别的语义理解（代码质量、设计合理性）仍由 Review/QA bot 负责。
>
> **两阶段模型：完成 → 验证 → 推进/退回。** `!step_complete` 不再直接推进管线，而是将 Step 标记为「待验证」(PENDING_VALIDATION)。验证通过后自动推进，验证失败则进入 BLOCKED 状态。
>
> **验证脚本是 WORK_PLAN frontmatter 的一部分。** 每个 Step 可以声明自己的验证脚本，也可以使用全局默认脚本。不与特定项目/仓库目录耦合。
>
> **验证失败不丢数据。** BLOCKED 状态的管线保留所有状态和产出，PM 可以修复后重新验证，也可以使用 `!step_force` 强制推进。

---

### 方向 A（核心）：验证钩子引擎 🔴 P0

在 `_cmd_step_complete()` 中插入验证门：Step 标记为完成 → 执行验证脚本 → 结果判定 → 推进或退回。

#### A1 — 验证钩子状态机

```
!step_complete stepN --output <sha>
  │
  ├─ 1. 标记 Task COMPLETED（同当前逻辑）✅
  ├─ 2. 记录 Step 产出（step_outputs）✅
  ├─ 3. 🔥[新增] 执行验证脚本
  │      ├─ ✅ 脚本返回 exit=0 → 继续推进（同当前逻辑）
  │      └─ ❌ 脚本返回 exit≠0 → 进入 BLOCKED 状态
  │
  └─ 4. 正常推进到下一 Step（仅验证通过时）
```

#### A2 — 验证脚本配置

验证脚本在 WORK_PLAN frontmatter 的 step 定义中配置：

```yaml
pipeline:
  steps:
    step3:
      role: developer
      title: 编码实现
      validation:
        script: "python3 scripts/verify_step3.py {output_ref}"
        timeout: 30           # 脚本超时（秒），默认 30
        required: true        # true=验证失败阻塞管线，false=仅警告

    step5:
      role: qa
      title: 测试报告
      validation:
        script: "python3 scripts/verify_step5.py {output_ref}"
        timeout: 60
        required: true
```

全局默认验证脚本（当 step 未声明 validation 时使用）：

```python
# config.py
ENABLE_VALIDATION_HOOK = True  # 总开关（默认关，opt-in）
VALIDATION_DEFAULT_SCRIPT = "python3 scripts/verify_default.py {output_ref}"
VALIDATION_DEFAULT_TIMEOUT = 30
```

**模板变量：**
- `{output_ref}` — `--output` 参数值（commit SHA / URL），自动注入
- `{step_name}` — 当前 Step 名（如 `step3`）
- `{round_name}` — 轮次名（如 `R80`）
- `{workspace_dir}` — 仓库根目录

#### A3 — 验证执行实现

```python
# handler.py — 新增函数
async def _run_validation_hook(
    round_name: str,
    step_name: str,
    output_ref: str,
    step_config: dict,
) -> tuple[bool, str]:
    """执行 Step 验证脚本。
    
    Returns: (passed, message)
    """
    val_config = step_config.get(step_name, {}).get("validation", {})
    if not val_config:
        return (True, "⏭️ 无验证脚本，跳过")
    
    script_template = val_config.get("script", "")
    if not script_template:
        return (True, "⏭️ 验证脚本为空，跳过")
    
    timeout = val_config.get("timeout", 30)
    required = val_config.get("required", True)
    
    # 模板渲染
    script = script_template.replace("{output_ref}", output_ref or "")
    
    try:
        proc = await asyncio.create_subprocess_shell(
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        
        if proc.returncode == 0:
            return (True, f"✅ 验证通过（exit=0）")
        else:
            err_msg = stderr.decode().strip()[:300] if stderr else stdout.decode().strip()[:300]
            if required:
                return (False, f"❌ 验证失败（exit={proc.returncode}）: {err_msg}")
            else:
                return (True, f"⚠️ 验证警告（exit={proc.returncode}，非必需）: {err_msg}")
    
    except asyncio.TimeoutError:
        if required:
            return (False, f"❌ 验证超时（>{timeout}s）")
        return (True, f"⚠️ 验证超时（>{timeout}s，非必需）")
    except Exception as e:
        if required:
            return (False, f"❌ 验证异常: {e}")
        return (True, f"⚠️ 验证异常（非必需）: {e}")
```

#### A4 — `_cmd_step_complete()` 中的验证门

在现有流程的 Task 标记完成 + Step 产出记录之后、查找下一 Step 之前，插入验证：

```python
# 第 2820-2852 行保持不变（标记 Task + 记录产出）
# ... 现有代码 ...

# ── R80 A: 验证钩子 ──
if config.ENABLE_VALIDATION_HOOK:
    val_passed, val_msg = await _run_validation_hook(
        round_name, step_name, output_ref, step_config
    )
    if not val_passed:
        # 验证失败 → 设管线为 BLOCKED
        try:
            mgr = PipelineContextManager(config.DATA_DIR)
            await mgr.transition_to(round_name, PipelineStatus.BLOCKED,
                blocked_reason=val_msg)
        except Exception:
            pass  # 非致命，记录日志即可
        
        # 向 PM 收件箱发送通知
        pm_inbox = f"_inbox:{_PIPELINE_STATE.get(round_name, {}).get('pm_agent_id', '')}"
        await _send_to_channel_or_log(pm_inbox,
            f"🔴 **{round_name} Step {step_name} 验证失败**\n\n{val_msg}\n\n"
            f"• `!step_verify` — 重新执行验证\n"
            f"• `!step_force step{step_name} --output {output_ref}` — 跳过验证强制推进"
        )
        
        return f"🔴 **{round_name} {step_name} 验证失败** ❌\n\n{val_msg}\n\n管线已进入 BLOCKED 状态。"
# ── R80 A: End ──
```

#### A5 — 健壮性保障

| 条件 | 行为 |
|:-----|:------|
| `ENABLE_VALIDATION_HOOK = False` | 完全不执行验证，走旧流程（退化开关） |
| Step 未配置 validation.script | 跳过验证，正常推进 |
| 验证脚本不存在/不可执行 | 记录 warning，如果 required=True 则阻塞 |
| 验证超时 | 根据 required 决定阻塞或仅警告 |
| 已有 `_PIPELINE_STATE` 损坏 | 跳过验证，log warning |
| 脚本包含敏感操作 | 验证脚本由 WORK_PLAN 作者编写，Server 仅执行——与 !pipeline_start 执行 frontmatter 的信任模型一致 |

---

### 方向 B（核心）：`!step_force` 强制推进命令 🔴 P0

当验证失败或管线被 BLOCKED 时，PM 或 admin 可以使用 `!step_force` 跳过验证直接推进。

#### B1 — 命令定义

```
用法: !step_force <step_name> --output <sha> [--reason "原因"]
```

```python
async def _cmd_step_force(sender_id: str, params: dict) -> str:
    """强制推进 Step（跳过验证钩子，仅限 PM/admin 使用）"""
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_force <step_name> --output <sha> [--reason \"原因\"]"
    
    step_name = positional[0].lower()
    output_ref = params.get("output", "")
    reason = params.get("reason", "无说明")
    
    if not output_ref:
        return "❌ 缺少 --output <sha>"
    
    # 权限检查：仅 PM 或 admin
    if not _check_pm_or_admin(sender_id):
        return "❌ 权限不足：仅 PM 或管理员可强制推进"
    
    # 记录 audit
    _audit_logger.log(f"[R80] !step_force by {sender_id}: {step_name} → {output_ref} (reason: {reason})")
    
    # 以 force_mode=True 调用 step_complete 内部逻辑（跳过验证）
    params["_force_mode"] = True
    params["_positional"] = [step_name]
    params["output"] = output_ref
    
    return await _cmd_step_complete(sender_id, params)
```

`_cmd_step_complete()` 中增加 `_force_mode` 守卫：

```python
# ── R80 B: Force mode bypass —─
if params.get("_force_mode") and _check_pm_or_admin(sender_id):
    force_bypass = True
else:
    force_bypass = False
# ── R80 B: End ──

# 验证门（仅非 force 模式执行）
if config.ENABLE_VALIDATION_HOOK and not force_bypass:
    val_passed, val_msg = await _run_validation_hook(...)
```

#### B2 — 权限控制

| 角色 | `!step_force` | 说明 |
|:-----|:-------------:|:------|
| PM 📋 | ✅ | 协调者可强制推进 |
| admin/operations 🛠️ | ✅ | 管理员可强制推进 |
| arch/dev/review/qa | ❌ | 角色不可跳过本角色的验证 |

---

### 方向 C（辅助）：`!step_verify` 重新验证命令 🟡 P1

当修复了验证失败的原因后，PM 可以触发重新验证，不需要重新提交 `!step_complete`。

#### C1 — 命令定义

```
用法: !step_verify <step_name> [--output <sha>]
```

- 如果 `--output` 未传，使用之前 `step_outputs` 中记录的 SHA
- 重新执行验证脚本
- 验证通过 → 管线从 BLOCKED 恢复到 RUNNING 并自动推进到下一 Step
- 验证失败 → 保持 BLOCKED，更新失败消息

---

### 方向 D（可选）：默认验证脚本（lint 检查）🟢 P2

提供一个全局默认验证脚本，当 Step 未配置自定义脚本时使用。

#### D1 — 默认脚本：git commit 元数据检查

```python
# scripts/verify_default.py
# 全局默认验证脚本：检查 commit 是否存在、author 是否合规
import sys, subprocess, os

output_ref = sys.argv[1] if len(sys.argv) > 1 else ""
if not output_ref:
    print("⏭️ 无 output_ref，跳过")
    sys.exit(0)

# 检查 commit 存在
result = subprocess.run(
    ["git", "log", "--oneline", "-1", output_ref],
    capture_output=True, text=True, cwd=os.environ.get("REPO_PATH", ".")
)
if result.returncode != 0:
    print(f"❌ Commit {output_ref} 不存在于本地仓库")
    sys.exit(1)

print(f"✅ Commit {output_ref} 本地存在")
sys.exit(0)
```

#### D2 — 配置

```python
# config.py
ENABLE_VALIDATION_HOOK = True
VALIDATION_DEFAULT_SCRIPT = "python3 scripts/verify_default.py {output_ref}"
VALIDATION_DEFAULT_TIMEOUT = 15
```

---

## 3. 验收标准

### 🎯 3.1 方向 A：验证钩子引擎

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | Step 配置了 validation.script 且 exit=0 → 正常推进 | Step 完成后管线正常流转到下一 Step | 配置验证脚本 `echo "ok"`（exit 0）→ `!step_complete` → 检查推进成功 |
| ✅-2 | Step 配置了 validation.script 且 exit≠0 → 管线进入 BLOCKED | `!pipeline_status` 显示 BLOCKED，不推进 | 配置验证脚本 `exit 1` → `!step_complete` → 检查状态为 BLOCKED |
| ✅-3 | `ENABLE_VALIDATION_HOOK = False` 时不执行验证 | Step 完成后直接推进，不调用验证脚本 | 关闭开关 → 验证脚本内有日志写入 → 检查日志无验证记录 |
| ✅-4 | Step 未配置 validation → 跳过验证直接推进 | 正常推进，无验证影响 | 不配 validation → `!step_complete` → 正常推进 |
| ✅-5 | 验证脚本 timeout → 根据 required 阻塞或警告 | required=true 时阻塞，false 时警告 | 配置 `script: "sleep 60"` + `timeout: 3` → 检查超时处理 |
| ✅-6 | 验证失败时 PM inbox 收到 BLOCKED 通知 | PM 收件箱出现「验证失败」通知消息 | 模拟验证失败 → 检查 PM 收件箱消息 |
| ✅-7 | BLOCKED 状态可在 `pipeline_context.json` 中查到 | `status: "blocked"`, `blocked_reason` 字段有内容 | 读取持久化文件 |
| ✅-8 | 模板变量 `{output_ref}`/`{step_name}`/`{round_name}` 正确渲染 | 脚本接收到正确的参数值 | 配置 `script: "echo {output_ref} {step_name}"` → 检查 stdout 正确 |

### 🎯 3.2 方向 B：`!step_force` 强制推进

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-9 | PM/admin 使用 `!step_force` 跳过验证推进 | BLOCKED 管线被推进到下一 Step | 验证失败后 → `!step_force stepN --output <sha>` → 检查推进成功 |
| ✅-10 | 非 PM/admin 使用 `!step_force` 被拒绝 | 返回「权限不足」 | 用普通角色身份发 `!step_force` |
| ✅-11 | `!step_force` 不走验证钩子 | force_mode 时验证脚本不执行 | 验证脚本内有日志写入 → force 后检查无日志记录 |
| ✅-12 | `_audit_logger` 记录 force 操作 | audit 日志含「!step_force by <id>: stepN → sha (reason: ...)」| 检查 audit 日志 |

### 🎯 3.3 方向 C：`!step_verify` 重新验证

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-13 | BLOCKED 状态下 `!step_verify` 重新执行验证 | 验证脚本再次执行 | 修复验证条件后 → `!step_verify stepN` → 检查脚本执行 |
| ✅-14 | 验证通过后管线自动恢复为 RUNNING 并推进 | 状态从 BLOCKED 变为 RUNNING，Step 推进 | 同上 → `!pipeline_status` 验证 |
| ✅-15 | 不带 `--output` 时复用之前记录的 SHA | 使用 `step_outputs` 中的值 | 检查脚本接收到的参数 |

### 🎯 3.4 方向 D：默认验证脚本

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-16 | 默认脚本正确检查 commit 存在性 | commit 存在 → exit 0；不存在 → exit 1 | `python3 scripts/verify_default.py <valid_sha>` → exit 0；`python3 scripts/verify_default.py <invalid_sha>` → exit 1 |
| ✅-17 | 默认脚本配置继承到未配 validation 的 step | 无 validation 的 step 自动走默认脚本 | 配置默认脚本 + 不配 step validation → step_complete 执行默认验证 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| ❌ 修改机器人行为 | 不改任何 bot 代码（arch/dev/review/qa/operations/PM） | 纯 server 端改动 |
| ❌ 修改注册/认证协议 | register / auth 消息格式不变 | 不同轮次 |
| ❌ Web 前端改动 | 不需修改 web_viewer.py / templates.py | 验证结果通过 `!pipeline_status` 和 inbox 查看 |
| ❌ F-3 workspace_admin 角色体系 | 独立功能，与验证钩子正交 | 留待 R81+ |
| ❌ R36-C 公开注册通信通道 | 公开注册场景 | R79 已明确排除 |
| ❌ 管线仪表盘 | Web 端 Step 进度条 | 架构 P1 的另一条方向 |
| ❌ 智能验证（LLM 级语义检查） | Server 只执行可脚本化验证 | Server 是纯规则引擎，语义检查归 Review/QA |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 15min |
| **3** | 👨‍💻 Dev | 编码实现 | 20min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 15min |
| **6** | 🛠️ Operations | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **修改** — `_cmd_step_complete()` 插入验证门 + `_run_validation_hook()` 新函数 + `_cmd_step_force()` 新命令 + `_cmd_step_verify()` 新命令 | ~60 行 |
| `server/handler.py` | **修改** — `_ADMIN_COMMANDS` 注册表新增 `step_force` / `step_verify` 命令 | ~4 行 |
| `server/config.py` | **新增常量** — `ENABLE_VALIDATION_HOOK` / `VALIDATION_DEFAULT_SCRIPT` / `VALIDATION_DEFAULT_TIMEOUT` | ~5 行 |
| `server/pipeline_context.py` | **修改** — 如果 `transition_to(BLOCKED)` 无 `blocked_reason` 参数时加上支持 | ~2 行 |
| `scripts/verify_default.py` | **新增** — 全局默认验证脚本（commit 存在性检查） | ~30 行 |
| **合计** | | **~100 行净增** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| 验证脚本执行时阻塞主 handler 事件循环 | 所有 WS 消息处理延迟 | `create_subprocess_shell` 是异步的（非阻塞），不会阻塞事件循环 |
| 验证脚本执行耗时过长 | 推进延迟数秒 | timeout 默认 30s，超时后自动终止 |
| 验证脚本注入危险命令 | 安全风险 | 验证脚本配置在 WORK_PLAN frontmatter 中，权限模型与 frontmatter 的信任级别一致——能写 frontmatter 的人已经可以控制管线行为 |
| `ENABLE_VALIDATION_HOOK=True` 影响旧轮次 | 旧轮次无验证脚本 → 跳过 | Step 未配 validation 时自动跳过，不影响 |
| force 模式被滥用 | bypass 验证门导致低质量推进 | Audit 日志记录每次 force 操作，PM/admin 可追溯 |

---

## 6. 影响范围

| 模块 | 影响 | 说明 |
|:-----|:-----|:------|
| `server/handler.py` | 🟡 中等 | `_cmd_step_complete()` 插入验证门（~20 行）+ 新增 3 个函数/命令 |
| `server/config.py` | ℹ️ 轻微 | 3 个新常量 |
| `server/pipeline_context.py` | ℹ️ 轻微 | 可选补 `transition_to(BLOCKED, blocked_reason)` 参数支持 |
| `scripts/verify_default.py` | 🆕 新增 | 默认验证脚本 ~30 行 |
| `shared/protocol.py` | ℹ️ 无影响 | 不新增消息类型 |
| 各 bot 代码 | ✅ 无影响 | bot 无需更新 |
| Web 前端 | ✅ 无影响 | 不涉及前端 |

---

## 7. 技术方案参考

- `server/handler.py` — `_cmd_step_complete()` (L2742-3030) — 插入验证门的主要位置
- `server/handler.py` — `_verify_git_commit()` (L2068-2100) — R55 C 的 git commit 验证模式，可直接复用 `asyncio.create_subprocess_exec/shell` 模式
- `server/pipeline_context.py` — `PipelineStatus.BLOCKED` (L28) + `transition_to()` — BLOCKED 状态已就绪
- `server/config.py` — `ENABLE_GIT_SYNC` 常量模式 — `ENABLE_VALIDATION_HOOK` 的配置模式参照
- `server/handler.py` — `_ADMIN_COMMANDS` — 命令注册表位置，新增 `step_force` / `step_verify`
- `server/handler.py` — `_PIPELINE_STATE` 的 `step_outputs` (L2843-2852) — 用于 `!step_verify` 复用之前的输出

---

## 8. 脱敏检查清单

- [ ] docs/R80/*.md 零内部名残留
- [ ] `grep -nE '内部名模式' docs/R80/*.md` 零匹配
- [ ] 使用通用角色名（PM / arch / dev / review / QA / operations）
- [ ] 不包含真实 agent_id / token / URL
- [ ] Server 是纯规则引擎，不引入 LLM 依赖

---

*需求文档生成：2026-07-09 🧐 PM*
