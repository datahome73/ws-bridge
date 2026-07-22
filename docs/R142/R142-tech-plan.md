# R142 管线稳定性加固轮 — 技术方案

> **轮次：** R142
> **类型：** 🛠️ 稳定性加固轮（Bugfix + 关键体验改进）
> **作者：** 🏗️ 架构师（小开）
> **版本：** v1.0
> **日期：** 2026-07-22
> **基准提交：** `3e10a6e`（origin/dev HEAD）

---

## 目录

1. [问题概述](#1-问题概述)
2. [修改总表](#2-修改总表)
3. [依据代码现状的差异发现](#3-依据代码现状的差异发现)
4. [详细设计方案](#4-详细设计方案)
5. [数据流分析](#5-数据流分析)
6. [验收标准映射](#6-验收标准映射)
7. [不做事项](#7-不做事项)
8. [回顾与风险](#8-回顾与风险)

---

## 1. 问题概述

基于经理调研报告（L4-auto-pipeline-manager-needs-research.md），R142 选择 P0/P1 中改动风险最低但体验收益最大的 **7 项改动**，目标文件全部集中在一处：`server/ws_server/pipeline_engine.py`（2305 行）。

| 编号 | 需求 | 优先级 | 风险等级 | 实际改动量 |
|:----:|:-----|:------:|:--------:|:----------:|
| F-1 | `##status` in_progress 图标缺失 | P0 | 🟢 | +1 行 |
| F-2 | 完成消息格式容错（B-4 修复） | P0 | 🟢 | ~+35 行 |
| F-3 | 闭环→统一通知管线协调者 | P0 | 🟢 | ~+15 行（修改已有分支） |
| F-4 | `##status` 显示完成时间/产出 | P0 | 🟢 | ~+20 行（追加展示字段） |
| F-5 | 审查失败自动退回 Step 3 | P1 | 🟡 | **✅ 已存在，无需改动** |
| F-6 | 完成时间戳记录 | P0 | 🟢 | +1 行 |
| F-7 | 完成消息格式自动提示 | P2 | 🟢 | ~+22 行（新函数 + 调用） |
| | **合计** | | **6 🟢 + 1 🟡（已存在）** | **~+94 行** |

---

## 2. 修改总表

所有改动均在 `server/ws_server/pipeline_engine.py` 一个文件中完成。

| 编号 | 函数/位置 | 行号 | 改动类型 | 行数 | 风险 |
|:----:|:----------|:----:|:---------|:----:|:----:|
| F-1 | `_handle_hash_status()` — `status_icons` dict | L1561-L1567 | 增加 key | +1 | 🟢 |
| F-6 | `_try_advance_pipeline()` — `_step_info["status"] = "done"` 后 | L406 | 追加赋值 | +1 | 🟢 |
| F-2 | `_try_advance_pipeline()` — L367 严格 regex 替换 | L361-L369 | 新增函数 + 替换调用 | ~+35 | 🟢 |
| F-7 | `_try_advance_pipeline()` — 匹配失败分支 + 新函数 | L368-L369 | 新增提示逻辑 | ~+22 | 🟢 |
| F-4 | `_handle_hash_status()` — step_lines 后追加证据 | L1584-L1585 | 追加展示行 | ~+20 | 🟢 |
| F-3 | `_notify_pm()` — completed 分支增强 | L493-L506 | 修改表格内容 | ~+15 | 🟢 |
| F-5 | `_handle_reject()` L1033-L1107 | **无需改动** | 已存在 | 0 | 🟢 |

---

## 3. 依据代码现状的差异发现

### 3.1 F-5：审查回退 **已存在** ⚠️

**需求文档描述：** §1.5 「当前'退回 🔄'消息只转发给 PM（旧角色），不做状态回退」

**代码现状：** `_handle_reject`（L1033-L1107）已完整实现状态回退逻辑：

```python
# pipeline_engine.py L1033-L1097（R124 提取自 main.py）
async def _handle_reject(content: str, sender_agent_id: str) -> None:
    m = re.match(r"退回 🔄 (R\d+) Step (\d+)", content)
    ...
    rollback_start = 1 if rejected_step <= 2 else 2  # Step 4 → rollback_start=2
    for i in range(rollback_start, len(ctx.steps)):
        ctx.steps[i]["status"] = "pending"
        ctx.steps[i]["output"] = None
        ctx.steps[i]["result_msg"] = ""
    ctx.current_step = rollback_start + 1  # Step 4 → current_step=3
    mgr.save()
    await _notify_pm(ctx, rejected_step, "rejected", ...)
```

**调用链（已打通）：**
```
scenario_rules.py L154 _sm_handle_reject
    → L179 _ensure_engine().handle_reject(content, agent_id)
        → pipeline_engine.py L2027 PipelineEngine.handle_reject()
            → L1033 _handle_reject()  ← 完整回退逻辑
```

**结论：** F-5（审查退回自动状态回退）在 R124 已实现并交付。本轮无需任何修改。`_handle_reject` 当前行为：
- Step 4 被退回 → `rollback_start=2` → Steps 3/4/5/6 重置 pending → `current_step=3`
- Step 2 被退回 → `rollback_start=1` → Steps 2-6 重置 pending → `current_step=2`
- 累计退回 ≥4 次 → stuck（不阻塞，安全保护）
- 回退后通知 PM 含退回原因 + 回退目标

**建议：** 验收时确认此功能正常（RJ-1~RJ-5 验收标准），如已通过则无需编码。

### 3.2 现有 `_notify_pm` completed 分支产出显示问题

**现状：** L499-500：

```python
out = s.get("output", s.get("result_msg", ""))
out_short = out[:40] + "..." if len(str(out)) > 40 else out
```

`out` 可能是 dict（`{"sha": "abc1234"}`）或 str。dict 切片 `out[:40]` 会触发 `TypeError`。

**修复方案：** F-3 增强时一并修复，统一使用类型安全提取。

### 3.3 需求文档行号验证

| 需求引用行 | 实际行号 | 偏差 | 原因 |
|:-----------|:--------:|:----:|:-----|
| L1561-L1567 status_icons | L1561-L1567 | ✅ 精确 | 未变动 |
| L361-L474 _try_advance_pipeline | L361-L473 | ±1 | R141 有增删调整 |
| L493-L506 _notify_pm completed | L493-L506 | ✅ 精确 | 未变动 |
| L404-L406 _step_info["status"]="done" | L404-L406 | ✅ 精确 | 未变动 |
| L1033 _handle_reject | L1033-L1107 | ✅ 精确 | 已存在 |
| `_fmt_ts` | L756-L763 | ✅ 存在 | 可复用 |

---

## 4. 详细设计方案

### 4.1 F-1：status_icons 增加 `in_progress` 🟢

**位置：** `_handle_hash_status()` L1561-L1567

**改动：** 字典增加一行：

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

**验证：** `status_icons.get("in_progress", "⬜")` 返回 `"🔄"`。适用于 `_handle_hash_status` 中 L1581 的 lookup，以及 `_notify_pm` 中未来可能 added status 展示。

### 4.2 F-6：完成时间戳记录 🟢

**位置：** `_try_advance_pipeline()` L406 之后

**改动：**

```python
_step_info["status"] = "done"
_step_info["completed_at"] = time.time()  # ═══ R142 ═══
```

**设计理由：**
- `time.time()` 与当前函数中其他时间字段（`time.time()` used at L367 外）一致
- 非关键路径——不阻塞推进逻辑
- F-4 在 `##status##` 中读取 `completed_at` 展示

### 4.3 F-2：完成消息容错匹配 🟢

**位置：** 新增模块级函数 + 修改 `_try_advance_pipeline()` 调用

**改动方案：**

#### 新增函数 `_try_extract_step_completion()`（L369 之后插入）

```python
# ═══ R142: 容错完成消息匹配 ═══
def _try_extract_step_completion(content: str) -> tuple[Optional[int], Optional[int], dict]:
    """多模式容错匹配完成消息，提取 R{N}、Step {N} 和 ##key=value 参数。

    支持格式：
    - 已完成 ✅ R{N} Step {N}##key=val     (原始严格格式)
    - ✅ 完成，R{N} Step {N} 已推 dev
    - R{N} Step {N} 已完成
    - 已完成 R{N} Step {N}##sha=xxx
    """
    from typing import Optional
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
            kv = _extract_artifact_kv(content)
            return round_num, step_num, kv
    return None, None, {}
```

#### 修改 `_try_advance_pipeline()` L367-369

**当前代码：**
```python
m = re.match(r"已完成 ✅ R(\d+) Step (\d+)", content)
if not m:
    return False, "no match"
```

**改为：**
```python
_rn, _sn, _kv = _try_extract_step_completion(content)
if _rn is None:
    # ═══ R142: 格式提示（F-7）═══
    _lower = content.lower()
    if any(kw in _lower for kw in ("完成", "done", "推", "push", "merge", "deploy")):
        asyncio.ensure_future(_send_format_hint(agent_id))
    # ══════════════════════════
    return False, "no match"
round_name = f"R{_rn}"
completed_step = _sn
```

后续 `m.group(1)` / `m.group(2)` / `_kv` 引用替换为 `_rn` / `_sn` / `_kv`。

#### 受影响的后续代码行（需调整变量名）

| 所在行 | 当前代码 | 改为 |
|:------:|:---------|:-----|
| L370 | `round_name = f"R{m.group(1)}"` | `round_name = f"R{_rn}"`（已移至匹配块外） |
| L371 | `completed_step = int(m.group(2))` | `completed_step = _sn` |
| L382 | `_kv = _extract_artifact_kv(content)` | 删除此行（_kv 已由 _try_extract_step_completion 返回） |

**向后兼容性：** 第 1 个 pattern `r"已完成\s*✅?\s*R(\d+)\s*Step\s*(\d+)"` 与原 `re.match(r"已完成 ✅ R(\d+) Step (\d+)", ...)` 等价（允许 ✅ 后有可选空格）。使用 `re.search` 而非 `re.match`，在 ##key=value 前缀场景中无副作用（R{N} Step{N} 总在消息开头附近）。

### 4.4 F-7：格式错误完成消息自动提示 🟢

**位置：** 新增模块级函数

```python
# ═══ R142: 完成消息格式提示 ═══
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

**调用点：** 在 F-2 的 `_try_advance_pipeline` 匹配失败分支中（见 §4.3 代码）。

**防误报：** 仅当消息包含完成意图关键词（完成/done/推/push/merge/deploy）时触发提示。无关消息不触发。

### 4.5 F-4：`##status` 状态证据增强 🟢

**位置：** `_handle_hash_status()` step_lines 构造后（L1584 之后）

**改动：** 在 step_lines 循环后追加证据行：

```python
# ═══ R142: 状态证据 ═══
step_evidence_lines = []
for step in ctx.steps:
    evidence_parts = []
    st = step.get("status", "pending")
    if st == "done" and step.get("completed_at"):
        evidence_parts.append(f"完成于: {_fmt_ts(step['completed_at'])}")
    if st == "in_progress" and step.get("dispatched_at"):
        elapsed = int(time.time() - step["dispatched_at"])
        evidence_parts.append(f"已进行: {elapsed//60}分{elapsed%60}秒")
    if step.get("result_msg"):
        msg_snippet = step["result_msg"][:60].replace("\n", " ")
        evidence_parts.append(f"消息: {msg_snippet}")
    if evidence_parts:
        step_evidence_lines.append("  " + " | ".join(evidence_parts))
    else:
        step_evidence_lines.append("")
# 将证据追加到 status_text
if any(step_evidence_lines):
    status_text += "\n" + "\n".join(step_evidence_lines)
```

**字段依赖：**
- `completed_at` — 由 F-6 在 `_try_advance_pipeline` 中写入（§4.2）
- `dispatched_at` — 已有字段（R107 auto_dispatch 写入）
- `result_msg` — 已有字段（R123 写入 `content[:200]`）
- `_fmt_ts()` — 已有函数（L756-L763）

### 4.6 F-3：管线闭环通知增强（管线协调者统一通知） 🟢

**位置：** `_notify_pm()` completed 分支 L493-L506

**改动：** 增强表格行内容，修复 dict output 切片 bug，增加 SHA/部署信息：

```python
elif status == "completed":
    # 构造完成摘要 — R142 增强
    step_lines = []
    for i, s in enumerate(ctx.steps, 1):
        role = role_names.get(i, "?")
        agent = s.get("agent_name", s.get("agent_id", "?")[:12])
        out = s.get("output") or {}
        if isinstance(out, dict):
            sha = out.get("sha", "")
            out_short = f"sha={sha[:12]}" if sha else "-"
        else:
            out_short = str(out)[:40]
        step_lines.append(f"| {i} | {role} | {agent} | {out_short} |")
    table_header = "| Step | 角色 | 执行者 | 产出 |\n|:---:|:-----|:-------|:-----|\n"
    content = (
        f"🎉 **{ctx.round_name} 管线已完成！**\n\n"
        f"{table_header}{chr(10).join(step_lines)}"
    )
```

**关键修复：** L499-500 的 `out[:40]` dict 切片 bug 一并修复——现在统一使用 `out.get("sha", "")` 类型安全提取。

**通知目标：** 复用 `config.PIPELINE_PM_AGENT_ID`（管线协调者 agent_id）。不新增配置项、不硬编码。

**其他 status 分支不受影响：** dispatched/failed/rejected/retrying/stuck/archived 分支保持原样。

---

## 5. 数据流分析

### 5.1 完成消息处理流程（F-2 + F-6 + F-7）

```
bot → WS → scenario_rules.py Rule 60
         → relay → _handle_complete
            ↓
    _try_advance_pipeline(content, agent_id)
         ↓
    _try_extract_step_completion(content)
         ↓ 匹配成功                  ↓ 匹配失败
    ↓                              ↓ 含完成关键词?
    round_name, step_num, kv  ← yes → _send_format_hint
         ↓                              ↓ no → return False
    record completed_at (F-6)
    extract artifacts (sha等)
    advance_step()
    auto_dispatch_next()
    or → completed → _notify_pm (F-3)
```

### 5.2 `##status` 展示流程（F-1 + F-4）

```
user → ##status##R142
     ↓
_handle_hash_status(round_name, agent_id, ws)
     ↓
ctx = mgr.get(round_name)
     ↓
status_icons: {"in_progress": "🔄"}  ← F-1
     ↓
for step in ctx.steps:
    icon = status_icons.get(st, "⬜")
    step_lines.append(...)            ← 基础行
     ↓
step_evidence_lines:                 ← F-4
    completed_at → "完成于: 07-22 14:30"
    dispatched_at → "已进行: 5分23秒"
    result_msg → "消息: sha=abc1234..."
     ↓
_send(ws, {content: status_text ...})
```

### 5.3 闭环通知流程（F-3）

```
_try_advance_pipeline 最后一步完成
     ↓
asyncio.ensure_future(mgr.transition_to(COMPLETED))
asyncio.ensure_future(_notify_pm(ctx, 6, "completed"))  ← L454
     ↓
_notify_pm:
    pm_id = config.PIPELINE_PM_AGENT_ID
    → 角色名映射: role_names {1: "📋 PM", 2: "📐 Arch", ...}
    → 遍历 ctx.steps → 提取每个 step 的 sha (从 output dict)
    → 拼接 Markdown 表格 → 广播到 pm_id 的 _inbox
```

---

## 6. 验收标准映射

### ST-N: Status 增强（P0）

| 编号 | 描述 | 验证方法 | 依赖 |
|:----|:-----|:---------|:----:|
| ST-1 | `##status##R142` 已派活 step 显示 🔄 | 手动查看或单元测试断言 `status_icons["in_progress"] == "🔄"` | F-1 |
| ST-2 | ✅ step 显示 `完成于: 2026-07-22 14:30` | 代码审查 + 手动验证 | F-4 + F-6 |
| ST-3 | 🔄 step 显示 `已进行: 5分23秒` | 代码审查 + 手动验证（需有 `dispatched_at` 字段） | F-4 |
| ST-4 | 有 result_msg 的 step 展示消息片段 | 代码审查 | F-4 |

### CP-N: 完成消息容错（P0）

| 编号 | 描述 | 验证方法 |
|:----|:-----|:---------|
| CP-1 | `已完成 ✅ R142 Step 3##sha=abc` → 推进 | 单元测试：`_try_extract_step_completion` |
| CP-2 | `✅ 完成，R142 Step 3 已推 dev` → 推进 | 单元测试 |
| CP-3 | `R142 Step 3 已完成` → 推进 | 单元测试 |
| CP-4 | 无 R{N}的消息 → 不推进不报错 | 单元测试：返回 (None, None, {}) |
| CP-5 | `##key=value` 在容错匹配下仍能提取 | 单元测试：`##sha=abc` 在 `✅ 完成...` 中仍提取 |

### NT-N: 管线协调者闭环通知（P0）

| 编号 | 描述 | 验证方法 |
|:----|:-----|:---------|
| NT-1 | 全管线完成→管线协调者收到含 Step 摘要的通知 | 集成测试或 mock `_send_to_agent` |
| NT-2 | 通知含各 Step 状态/角色/产出 | 审查生成的 content 字符串 |
| NT-3 | 其他 status 分支不受影响 | 审查 if/elif 结构——completed 分支不修改其他分支 |

### RJ-N: 审查回退（P1，已存在）

| 编号 | 描述 | 验证方法 |
|:----|:-----|:---------|
| RJ-1 | `退回 🔄 R142 Step 4` → current_step=3 | 手动或用之前 R124 的测试 |
| RJ-2 | Step 3 发退回→不回退（只日志） | 手动或用之前 R124 的测试 |
| RJ-3 | 回退后通知管线协调者 | 代码审查 `_notify_pm` 被调用 |
| RJ-4 | 回退不自动派活 | 审查 `_handle_reject` 中无 `auto_dispatch` 调用 |
| RJ-5 | 异常时状态机不破坏 | `_handle_reject` 的模块级异常由 `_try_advance_pipeline` 捕获确保 |

### HT-N: 格式自动提示（P2）

| 编号 | 描述 | 验证方法 |
|:----|:-----|:---------|
| HT-1 | 含「完成」但格式错 → 回复格式提示 | 模拟调用：`_try_advance_pipeline("完成了，push 到 dev", agent_id)` → `_send_format_hint` 被调用 |
| HT-2 | 格式正确的完成消息→不回复提示 | `_try_extract_step_completion` 匹配成功 → 分支不进入提示逻辑 |
| HT-3 | 无关消息→不回复提示 | `"hello world"` → 不匹配完成关键词 → 不触发提示 |

---

## 7. 不做事项

| # | 事项 | 原因 |
|:-:|:-----|:-----|
| ❌ | 权限模型重构（§3.1） | 涉及 Gateway/auth 联动，风险高，需独立轮 |
| ❌ | `_inbox:server` 对经理开放（§6.3） | 权限变更需独立测试 |
| ❌ | 批次部署模式（§4.4） | 新功能开发，与稳定性目标无关 |
| ❌ | `!pipeline_status` 对经理开放（§3.2） | 非紧急，无明确阻断 |
| ❌ | `##force_advance##`（§6.2） | 涉及状态机核心语义变更 |
| ❌ | F-5 新增 `handle_reject` 代码（需求文档 §1.5 提议版） | **已存在**——当前 `_handle_reject` L1033-L1107 回调更具通用性（Step 任意→rollback_start 自动计算） |
| ❌ | 重命名 `_notify_pm` 函数为 `_notify_coordinator` | 纯重命名改动，不解决实际问题 |
| ❌ | 修改 `scenario_rules.py` 或 `scenario_matcher.py` | 调用链已验证打通，无需改动 |
| ❌ | 任何新增配置项或 env var | 所有改动复用现有配置项 |

---

## 8. 回顾与风险

### 8.1 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:----:|:---------|
| F-2 新 patterns 误匹配无关消息 | 低 | 中——可能触发意外推进 | 第 4 个 pattern `已完成.*?R(\d+).*?Step(\d+)` 最宽松，但满足`已完成` + `R{N}` + `Step{N}` 同时出现——日常消息中极低 |
| F-7 误报提示 | 低 | 低——提示无副作用 | 触发条件：匹配失败 + 完成关键词同时满足；无关消息无关键词 |
| F-2 遗留未替换的 `m.group()` 引用 | 低 | 中——NameError | 编码后 `search_files("m\\.group\\|\\b_kv\\b")` 确认无残留 |
| F-3 现有 `out[:40]` dict 切片 bug | 中（现存的） | 低——仅 completed 分支触达 | F-3 增强时一并修复 |

### 8.2 回归防护

| 改动 | 防护措施 |
|:-----|:---------|
| F-2（容错匹配） | 第 1 条 pattern 与原严格正则等价；Python 单元测试覆盖 5 种格式 |
| F-3（闭环通知） | 仅修改 completed 分支；dispatched/failed/rejected/stuck/archived 分支 if/elif 分离不受影响 |
| F-4（status 证据） | 纯展示层追加；不修改 `_handle_hash_status` 返回的 `True` |
| F-5（审查回退） | 全无改动——仅验证现有功能正常 |
| F-7（格式提示） | 匹配失败分支触发；匹配成功分支不进入该路径 |

### 8.3 执行顺序建议

```
提交 1/2（🟢 安全改动：F-1 + F-6 + F-4 + F-3）
  1. F-1: status_icons + in_progress（L1561-L1567）
  2. F-6: completed_at 记录（L406）
  3. F-4: status 证据增强（L1584-L1585 后追加）
  4. F-3: _notify_pm completed 分支增强（L493-L506）

验证：python3 -c "compile(open('pipeline_engine.py').read(),'pe.py','exec'); print('OK')"
验证：python3 -c "from server.ws_server import pipeline_engine; print('Import OK')"

提交 2/2（🟢 中等改动：F-2 + F-7）
  1. 新增 _try_extract_step_completion() 函数
  2. 新增 _send_format_hint() 函数
  3. 修改 _try_advance_pipeline() L367-369 + L370-382 变量替换

验证：单元测试 _try_extract_step_completion 5 种 format
验证：compile + import
```

---

## 附录 A：已存在功能验证（F-5）

当前 `_handle_reject`（L1033-L1107）的关键行为确认：

| 检查项 | 代码行 | 验证结果 |
|:-------|:------:|:---------|
| Step 4 退回 → Step 3 rollback | L1081: `rollback_start = 2`, L1094: `current_step = 3` | ✅ |
| 退回原因提取 | L1058-1064 | ✅ 支持全角—/半角--/- |
| 累计退回≥4 次→stuck | L1069-1078 | ✅ |
| 异常保护 | 无显式 try/except（但 `_handle_reject` 本身被 `_try_advance_pipeline` 调用路径覆盖） | ⚠️ 建议：R142 编码时可选加外层 try/except log |
| 通知 PM | L1098-1104 | ✅ |
| 不自动派活 | L1094 后无 auto_dispatch 调用 | ✅ |
| scenario_rules -> pipeline_engine 调用链 | rule 60 → `_sm_handle_reject` → `_ensure_engine().handle_reject()` → `_handle_reject()` | ✅ |

---

## 附录 B：预估 vs 实际改动量

| 编号 | 需求文档预估 | 实际 | 差异原因 |
|:----:|:-----------:|:----:|:---------|
| F-1 | +1 | +1 | ✅ 精确 |
| F-2 | +50 | +35 | 需求文档分解为函数定义(~30) + 调用替换(~5)，实际交互量更少 |
| F-3 | +20 | +15 | 增强现有分支而非重写 |
| F-4 | +20 | +20 | ✅ 精确 |
| F-5 | +30 | **0** | ⚠️ **已存在**——需求文档未发现 R124 已实现的 `_handle_reject` |
| F-6 | +1 | +1 | ✅ 精确 |
| F-7 | +20 | +22 | 新函数 + 调用点，含必要的导包和类型注释 |
| **合计** | **+132** | **+94** | **-38 行（主要是 F-5 已存在差异）** |
