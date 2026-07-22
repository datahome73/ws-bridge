# R142 需求文档 — 管线稳定性加固轮

> **来源文档：** `docs/research/L4-auto-pipeline-manager-needs-research.md`
> **轮次：** R142
> **类型：** 🛠️ 稳定性加固轮（Bugfix + 关键体验改进）
> **版本：** v1.0
> **日期：** 2026-07-22
> **状态：** 📝 初稿

---

## §0 本轮定位

基于经理 R127→R141 共 15 轮实际管线运行经验的调研报告，筛选 **P0/P1 中改动风险最低但体验收益最大的 5 项**：

| 优先级 | 需求 | 改动面 | 风险 | 经理报告章节 |
|:------:|:-----|:-------|:----:|:-----------:|
| **P0** 🟢 | `##status` in_progress 图标缺失 | 1 行字典 key | 🟢 零 | §2.3 |
| **P0** 🟢 | 闭环→统一通知管线协调者 | `_notify_pm` completed 分支增强 | 🟢 低 | §2.5 |
| **P0** 🟢 | 完成消息格式容错（B-4 修复） | `match_complete` 正则放宽 | 🟢 低 | §2.2, §7.1 |
| **P0** 🟢 | `##status` 真实性 — 显示完成时间/产出 | `_handle_hash_status` 增强 | 🟢 低 | §2.4 |
| **P1** 🟠 | 审查失败自动退回 Step 3 | `match_reject` handler + 状态机回退 | 🟡 中 | §4.3 |
| **P1** 🟠 | 闭环通知含各 Step 摘要（部署信息） | `_notify_pm` completed 分支增强 | 🟢 低 | §2.5 |
| **P2** 🟡 | 完成消息自动提示正确格式 | `_sm_handle_complete` 负匹配提示 | 🟢 低 | §7.1 |

**不改内容：** 权限模型重构、`_inbox:server` 开放、批次部署、`##force_advance##` — 涉及权限/架构改动，风险不可控，留待独立轮处理。

---

## §0.1 角色说明：管线协调者

> **统一概念：** 本需求文档及后续所有文档中，**管线协调者**是唯一的管线调度角色。

| 阶段 | 角色 | 说明 |
|:-----|:-----|:------|
| R127→R141（过往） | PM（小谷） | 小谷兼任需求分析和管线协调，人工推进每步 |
| 当前过渡期 | 管线协调者 | 配置 `PIPELINE_PM_AGENT_ID` 指向当前承担协调职责的 bot（可能是小谷或经理）。**代码中无硬编码，角色名统一为管线协调者** |
| 未来（完全自动化后） | 自动化调度 bot | 管线协调者本身就是一个自动化 bot，`##start##` → 全自动闭环，无需人工干预。之前的尝试因自动推进功能不完善而搁置，R142 正为此铺路 |

**工程影响：** 代码中 `_notify_pm` 函数名（通知管线协调者）和 `config.PIPELINE_PM_AGENT_ID` 配置名（管线协调者agent_id）暂不重命名，不做纯重命名改动。新代码直接以"管线协调者"指代该角色。

---

## §1 问题与方案

### 1.1 `##status` in_progress 图标缺失（TODO B-3）

**问题：** `_handle_hash_status` 的 `status_icons` 映射表缺 `"in_progress"` key，已派活的 step 显示 `⬜`（与 pending 混淆）→ 管线协调者看到⬜以为还没派活。

**根因：** `pipeline_engine.py` L1561-1567 `status_icons` 字典未包含 `"in_progress"`。

**改动方案：** 一行补 key：

```python
status_icons = {
    "pending": "⬜",
    "active": "🟢",
    "in_progress": "🔄",   # ← R142 新增
    "done": "✅",
    "failed": "❌",
    "skipped": "⏭",
}
```

**改动量：** 1 行。

**验收标准：**
- [x] `##status##R142` 派活后的 step 显示 `🔄` 而非 `⬜`

---

### 1.2 完成消息格式容错（B-4 修复）

**问题：** `_try_advance_pipeline` 当前用严格正则 `r"已完成 ✅ R(\d+) Step (\d+)"` 匹配完成消息。bot 端格式偏差（标点、多余空格、前缀差异）→ 静默忽略，不推进、不报错。

**真实案例：**
| 实际消息 | 当前匹配 | 结果 |
|:---------|:--------:|:-----|
| `已完成 ✅ R142 Step 3##sha=xxx` | ✅ 匹配 | 正常 |
| `✅ 完成，已推 dev` | ❌ 不匹配 | 管线卡住 |
| `已完成，push 到 dev` | ❌ 不匹配 | 管线卡住 |
| `已完成 Step 3` | ❌ 不匹配 | 管线卡住 |
| `好的，已完成` | ❌ 不匹配 | 管线卡住 |

**改动方案：**

修改 `_try_advance_pipeline` 的匹配逻辑，从严格正则改为**多模式容错匹配**：

```python
def _try_extract_step_completion(content: str) -> tuple[Optional[int], Optional[int], dict]:
    """容错提取完成消息中的 R{N} 和 Step {N}。

    支持格式：
    - 已完成 ✅ R{N} Step {N}
    - ✅ 完成，R{N} Step {N}
    - 已完成 R{N} Step {N}
    - R{N} Step {N} 完成
    - R{N} step{N} 已完成
    """
    patterns = [
        r"已完成\s*✅?\s*R(\d+)\s*Step\s*(\d+)",
        r"✅\s*完成.*?R(\d+).*?Step\s*(\d+)",
        r"R(\d+)\s*Step\s*(\d+).*?(?:完成|已推|done)",
        r"已完成.*?R(\d+).*?Step\s*(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            round_num = int(m.group(1))
            step_num = int(m.group(2))
            # 提取 ##key=value
            kv = _extract_artifact_kv(content)
            return round_num, step_num, kv
    return None, None, {}
```

然后 `_try_advance_pipeline` 调用 `_try_extract_step_completion` 替代 `re.match(...)`。

**改动量：** 新增 ~30 行函数 + 替换 `_try_advance_pipeline` 中 ~5 行。

**验收标准：**
- [x] `已完成 ✅ R142 Step 3##sha=abc` → 正常推进（既有格式继续支持）
- [x] `✅ 完成，R142 Step 3 已推 dev` → 正常推进
- [x] `R142 Step 3 已完成` → 正常推进
- [x] `已完成 Step 3`（缺 R{N}）→ 不匹配，不推进
- [x] 原始严格格式的 ##key=value 提取不受影响

---

### 1.3 管线闭环通知 → 统一通知管线协调者（P0 §2.5）

**问题：** 当前 `_notify_pm` 在管线闭环时通知 PM（旧角色），但管线协调者收不到闭环通知。需要主动查 `##status##` 或等大宏在 TG 告知。

**设计原则：** PM 的协调职责已并入**管线协调者**角色——管线通知的统一目标是 `config.PIPELINE_PM_AGENT_ID`，该配置指向当前担任管线协调者的 bot。

**方案：** 增强 `_notify_pm`，使其在 `status="completed"` 时发送更丰富的闭环摘要（包含各 Step 状态/角色/产出），替代当前较简略的闭环通知。

具体改动：

1. 在 `_notify_pm` 的 `"completed"` 分支（L493-L506）增强摘要内容，增加：merge commit SHA（从 Step 6 output 提取）、部署版本号信息

2. 在 `_try_advance_pipeline` 中最后一 Step 完成时（L451-457），`_notify_pm(ctx, ctx.total_steps, "completed")` 调用保持不变——增强了内容后它自然发出更丰富的通知

```python
# 当前 _notify_pm completed 分支（L493-L506）：
elif status == "completed":
    # 构造完成摘要 — R142 增强
    step_lines = []
    for i, s in enumerate(ctx.steps, 1):
        role = role_names.get(i, "?")
        agent = s.get("agent_name", s.get("agent_id", "?")[:12])
        st = s.get("status", "?")
        icon = {"done": "✅", "pending": "⬜", "in_progress": "🔄",
                "failed": "❌", "skipped": "⏭"}.get(st, "⬜")
        out = s.get("output") or {}
        if isinstance(out, dict):
            sha = out.get("sha", "")
            out_short = f"sha={sha[:12]}" if sha else "-"
        else:
            out_short = str(out)[:40]
        step_lines.append(f"| {i} | {icon} {role} | {agent} | {out_short} |")
    table_header = "| Step | 角色 | 执行者 | 产出 |\n|:---:|:-----|:-------|:-----|\n"
    content = (
        f"🎉 **{ctx.round_name} 管线已完成！**\n\n"
        f"{table_header}{chr(10).join(step_lines)}"
    )
```

**改动量：** 修改 `_notify_pm` 的 completed 分支 ~20 行（增强摘要内容），无新增函数、无新增配置项。

**验收标准：**
- [x] 全管线 6 Step 完成时，管线协调者（`config.PIPELINE_PM_AGENT_ID`）收到含 Step 摘要的闭环通知
- [x] 通知内容包含各 Step 状态、执行者、产出摘要
- [x] 不改变其他 status 分支（dispatched/failed/rejected 等保持原样）

---

### 1.4 `##status` 状态真实性增强（P0 §2.4）

**问题：** `##status` 返回的 ✅/🔄 可能是乐观推断而非真实证据。管线协调者收到 `✅` 会跳过催办，但实际可能未完成。

**方案：** `_handle_hash_status` 增加**产出时间戳和证据标识**：

```python
# 在 step_lines.append(...) 后（L1584 附近）追加：
# ═══ R142: 显示产出证据 ═══
step_time = step.get("completed_at") or step.get("dispatched_at")
step_evidence = []
if status == "done" and step.get("completed_at"):
    step_evidence.append(f"完成于: {_fmt_ts(step['completed_at'])}")
if status == "in_progress" and step.get("dispatched_at"):
    elapsed = int(time.time() - step["dispatched_at"])
    step_evidence.append(f"已进行: {elapsed//60}分{elapsed%60}秒")
if step.get("result_msg"):
    step_evidence.append(f"消息: {step['result_msg'][:60]}")
if step_evidence:
    step_lines[-1] += "  " + " | ".join(step_evidence)
```

同时在 `_try_advance_pipeline` 中当 step 推进时记录 `completed_at` 时间戳（L396-406 的 `_step_info["status"] = "done"` 处追加）：

```python
_step_info["status"] = "done"
_step_info["completed_at"] = time.time()  # ═══ R142 ═══
```

**改动量：** ~20 行增强。

**验收标准：**
- [x] Step ✅ 状态显示完成时间
- [x] Step 🔄 状态显示已进行时长
- [x] 有 result_msg 的 step 展示原始消息片段

---

### 1.5 审查失败自动退回 Step 3（P1 §4.3）

**问题：** 当前"退回 🔄"消息只转发给 PM（旧角色），不做状态回退。审查发现 bug 后管线卡在 Step 4，管线协调者需要手动 L3 调度「退回 Step 3→爱泰修复→重审」循环。

> ⚠️ **质量门禁：** 本节改动涉及状态机回退逻辑，有状态同步风险。实施时需：
> - 仅支持 Step 4（审查）→ Step 3（编码）单向回退
> - 不改变 Step 1/2/5/6 的状态
> - 回退后不自动派活（由管线协调者/后续完成消息触发）
> - 加日志 + try/except 包裹，异常不影响状态机

**方案：** 在 `_sm_handle_reject` 中（`scenario_rules.py` L154-180）增加状态回退逻辑。

当前 `_sm_handle_reject` 调用了 `_ensure_engine().handle_reject(content, agent_id)`，检查 `handle_reject` 的实现：

```python
# pipeline_engine.py 中查找 handle_reject
async def handle_reject(self, content: str, agent_id: str) -> None:
    """Handle 🔴 review rejection: rollback Step 4 → Step 3."""
    # Extract round_name from content
    m = re.search(r"R(\d+)", content)
    if not m:
        logger.info("[R142] reject: 无法提取轮次号，跳过回退")
        return
    round_name = f"R{m.group(1)}"
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        return
    # Only rollback if currently on Step 4 (review)
    if ctx.current_step != 4:
        logger.info("[R142] reject: %s current_step=%d ≠ 4，不触发回退",
                    round_name, ctx.current_step)
        return
    try:
        # Rollback Step 4 → reset to pending
        step4 = ctx.steps[3] if len(ctx.steps) > 3 else None
        if step4:
            step4["status"] = "pending"
        # Rollback Step 3 → pending (re-code)
        step3 = ctx.steps[2] if len(ctx.steps) > 2 else None
        if step3:
            step3["status"] = "pending"
            step3["result_msg"] = "🔄 审查退回，需要重新编码"
        ctx.current_step = 3
        mgr.save()
        logger.info("[R142] %s 审查退回 → Step 3", round_name)

        # 通知管线协调者
        await _notify_pm(ctx, 3, "rejected",
                         f"审查退回 Step 3（{_get_step_agent_name(ctx, 3)}）{content[:100]}")
    except Exception as e:
        logger.warning("[R142] 审查退回异常: %s", e)
```

**改动量：** 修改 `handle_reject` 方法（需确认当前是 stub 还是已有逻辑）~30 行。

**验收标准：**
- [x] 审查 bot 发送 `退回 🔄 R142 Step 4: 需修复` → Step 4 ⬜ pending, Step 3 ⬜ pending, current_step=3
- [x] 当前 Step ≠ 4 时不回退（只日志记录，不报错）
- [x] 回退后通知 PM（含退回原因摘要）
- [x] 回退不自动派活——由后续完成消息触发推进

---

### 1.6 完成消息格式自动提示（P2 §7.1）

**问题：** bot 发送格式不正确的完成消息时，状态机静默忽略。bot 不知道格式有误，管线因此卡住。

**方案：** 在 `_try_advance_pipeline` 中，当 `_try_extract_step_completion` 返回 None（无法提取 step 信息）但消息包含明显完成意图（包含"完成""done"等关键词）时，向 bot 回复格式提示：

```python
# 在 _try_advance_pipeline 中，匹配失败后：
if not m:
    # ═══ R142: 格式提示 ═══
    _lower = content.lower()
    if any(kw in _lower for kw in ("完成", "done", "推", "push", "merge", "deploy")):
        # 消息看起来是完成意图但格式不对 → 异步通知
        asyncio.ensure_future(_send_format_hint(agent_id))
    return False, "no match"
```

```python
async def _send_format_hint(agent_id: str) -> None:
    """向 bot 发送完成消息格式提示。"""
    await _send_to_agent(agent_id, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": (
            "❌ 完成消息格式不识别。请使用以下格式之一：\n"
            "  ✅ 已完成 ✅ R142 Step 3##sha=xxx\n"
            "  ✅ ✅ 完成，R142 Step 3 已推 dev"
        ),
        "ts": time.time(),
    })
```

**改动量：** ~20 行新增。

**验收标准：**
- [x] bot 发 `已完成 R142 Step 3` → 正常匹配推进（无提示）
- [x] bot 发 `完成了，push 到 dev` → 回复格式提示
- [x] bot 发无关消息 → 不回复提示（避免误报）

---

## §2 改动清单

| 编号 | 文件 | 改动 | 行数 | 风险 |
|:----:|:-----|:-----|:----:|:----:|
| F-1 | `pipeline_engine.py` | `status_icons` 加 `"in_progress": "🔄"` | +1 | 🟢 |
| F-2 | `pipeline_engine.py` | `_try_advance_pipeline` 容错匹配 + 格式提示 | +50 | 🟢 |
| F-3 | `pipeline_engine.py` | `_notify_pm` completed 分支增强（管线协调者统一通知） | +20 | 🟢 |
| F-4 | `pipeline_engine.py` | `##status` 时间戳/证据增强 | +20 | 🟢 |
| F-5 | `pipeline_engine.py` | `handle_reject` 状态回退 | +30 | 🟡 |
| F-6 | `pipeline_engine.py` | `completed_at` 记录推进时间 | +1 | 🟢 |
| F-7 | `scenario_rules.py` | `handle_reject` 调用不变（engine 方法已改） | 0 | 🟢 |
| | **合计** | | **~+132** | **6 🟢 + 1 🟡** |

---

## §3 集成步骤

```
Step 1: PM 审核本需求文档 → 推 dev
Step 2: Arch 确认改动方案（± 修改细节）
Step 3: Dev 实现 7 项改动
Step 4: Review 审查 — 重点：F-5 回退逻辑的边界情况
Step 5: QA 验收 — 26 项验收标准全绿
Step 6: Ops 合入 main 部署
```

---

## §4 质量保证

### 4.1 不改的内容（= 不引入回归风险）

| # | 事项 | 原因 |
|:-:|:-----|:-----|
| ❌ | 权限模型重构（§3.1） | 涉及 Gateway/auth 联动，风险高 |
| ❌ | `_inbox:server` 对经理开放（§6.3） | 权限变更需独立测试 |
| ❌ | 批次部署模式（§4.4） | 新功能开发，与稳定性目标无关 |
| ❌ | `!pipeline_status` 对经理开放（§3.2） | 非紧急，无明确阻断 |
| ❌ | 强制推进接口 `##force_advance##`（§6.2） | 涉及状态机核心语义变更 |

### 4.2 回归防护

- **F-2（容错匹配）**：原始严格格式仍被新函数支持（第 1 条 pattern 与原正则等价），**不存在格式降级风险**
- **F-3（管线协调者通知）**：增强 `_notify_pm` 的 completed 分支，**不改变其他 status 分支**
- **F-5（审查回退）**：只有 `current_step == 4` 时才触发回退，**其他 step 不干扰**

### 4.3 验收计数

| 分组 | P0 项 | P1 项 | P2 项 | 合计 |
|:-----|:-----:|:-----:|:-----:|:----:|
| status 图标修复 | 1 | 0 | 0 | 1 |
| 完成消息容错 | 1 | 0 | 0 | 1 |
| 闭环通知（管线协调者） | 1 | 1 | 0 | 2 |
| status 真实性 | 1 | 0 | 0 | 1 |
| 审查回退 | 0 | 1 | 0 | 1 |
| 格式提示 | 0 | 0 | 1 | 1 |
| **合计** | **4** | **2** | **1** | **7** |

---

## §5 验收标准

### ST-N: Status 增强（P0）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| ST-1 | `##status##R142` 已派活 step 显示 `🔄` 而非 `⬜` | 功能 | P0 |
| ST-2 | `##status##` ✅ step 显示完成时间 | 功能 | P0 |
| ST-3 | `##status##` 🔄 step 显示已进行时长 | 功能 | P0 |
| ST-4 | `##status##` 有 result_msg 的 step 展示消息片段 | 功能 | P0 |

### CP-N: 完成消息容错（P0）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| CP-1 | `已完成 ✅ R142 Step 3##sha=abc` → 推进 | 功能 | P0 |
| CP-2 | `✅ 完成，R142 Step 3 已推 dev` → 推进 | 功能 | P0 |
| CP-3 | `R142 Step 3 已完成` → 推进 | 功能 | P0 |
| CP-4 | 无 R{N} 的消息 → 不推进，不报错 | 功能 | P0 |
| CP-5 | `##key=value` 在容错匹配下仍能提取 | 功能 | P0 |

### NT-N: 管线协调者闭环通知（P0）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| NT-1 | 全管线完成后管线协调者收到含 Step 摘要的闭环通知 | 功能 | P0 |
| NT-2 | 通知含各 Step 状态摘要（角色/执行者/产出） | 功能 | P0 |
| NT-3 | 其他 status 分支（dispatched/failed/rejected）不受影响 | 回归 | P0 |

### RJ-N: 审查回退（P1）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| RJ-1 | `退回 🔄 R142 Step 4` → current_step=3, Step 4⬜ Step 3⬜ | 功能 | P1 |
| RJ-2 | 当前 step=3 时发退回 → 不回退（只日志） | 功能 | P1 |
| RJ-3 | 回退后通知管线协调者（含退回原因） | 功能 | P1 |
| RJ-4 | 回退不自动派活 | 功能 | P1 |
| RJ-5 | 异常时状态机不被破坏 | 安全 | P1 |

### HT-N: 格式自动提示（P2）

| 编号 | 描述 | 类型 | 优先级 |
|:----|:-----|:----:|:------:|
| HT-1 | 包含「完成」关键词但格式错误 → bot 收到格式提示 | 功能 | P2 |
| HT-2 | 格式正确的完成消息 → 不回复提示 | 功能 | P2 |
| HT-3 | bot 发无关消息 → 不回复提示 | 功能 | P2 |

---

## §6 变更记录

| 日期 | 版本 | 变更 |
|:----|:----:|:-----|
| 2026-07-22 | v1.0 | 初版 — 管线稳定性加固轮（基于经理调研报告） |
