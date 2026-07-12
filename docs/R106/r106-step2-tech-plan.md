# R106 技术方案 — Step 2 交付

> **轮次：** R106a
> **角色：** 小开（架构师）
> **日期：** 2026-07-13

---

## 一、Task 1: pipeline_context.py 设计评估

### 现状
`server/pipeline_context.py` **已存在**（R77），包含 PipelineContext dataclass、PipelineContextManager（create/get/advance_step/get_all_active/archive/cancel）、JSON 持久化、PipelineStatus 枚举、StepInfo dataclass、_ensure_pipeline_manager()。

### 需新增的 4 个字段

| 字段 | 类型 | 默认值 | 用途 |
|:-----|:-----|:--------|:------|
| round_title | str | "" | 人类可读标题 |
| references | dict | {} | 文档 URL |
| artifacts | dict | {} | 每步产出 KV |
| message_templates | dict | {} | R106b 派活模板 |

**位置：** dataclass 声明区（tags 后）+ to_dict + from_dict = +12 行

### 需新增的工具函数

```python
import re
_COMPLETION_RE = re.compile(r"^已完成 ✅ R(\d+) Step (\d+)")
def parse_completion(content: str) -> tuple[str, int] | None:
    m = _COMPLETION_RE.match(content.strip())
    if m: return f"R{int(m.group(1))}", int(m.group(2))
    return None
```

= +6 行

### 无需新增（已有）
- `get(round_name)` L258
- `advance_step(round_name)` L354
- `get_all_active()` L277
- `_ensure_pipeline_manager()` main.py:39

---

## 二、Task 2: _handle_server_relay 两副本插入点

### 现状
server/main.py 有两份完全相同的 `_handle_server_relay()`:

| 副本 | 起始行 | 规则 2 (已完成 ✅) | return True |
|:-----|:-------|:-------------------|:------------|
| 副本 1 | L2348 | L2450–2474 | L2474 |
| 副本 2 | L2550 | L2652–2676 | L2676 |

### 精确插入
在两副本规则 2 的末尾、`return True` 之前：

**副本 1：L2473 与 L2474 之间**
**副本 2：L2675 与 L2676 之间**

### 插入代码（每副本 +10 行，共 +20 行）

```python
        # ── R106: Pipeline Context 自动推进 ──
        parsed = parse_completion(content)
        if parsed:
            round_name, step_num = parsed
            mgr = _ensure_pipeline_manager()
            ctx = mgr.get(round_name)
            if ctx:
                await mgr.advance_step(round_name)
                logger.info("[Pipeline] %s advanced to step %d by Step %d completion",
                            round_name, ctx.current_step, step_num)
```

### 顶层导入（+1 行）
```python
from .pipeline_context import parse_completion  # R106
```

### 同步验证
```bash
grep -c "# ── R106: Pipeline Context 自动推进 ──" server/main.py
# 预期: 2
```

> R107 必须消除两副本重复，抽取为共享函数。

---

## 三、Task 3: !pipeline_status 增强

### 现状
`!pipeline_status`（L1895）+ `_format_pipeline_context()`（L1150）已存在。

### 增强方式
在 `_format_pipeline_context()` 末尾、return 前追加 step 逐行状态展示（替换原 ack_states 区块）：

```python
    # ── R106: Step 逐行状态 ──
    role_map = {"pm":"PM","arch":"架构","dev":"开发","review":"审查","qa":"测试","operations":"运维"}
    lines.append("")
    for i in range(1, ctx.total_steps + 1):
        step_key = f"step{i}"
        step_info = next((s for s in ctx.steps if s.get("name") == step_key), None)
        role = (step_info or {}).get("role", step_info.get("executor_role", ""))
        role_zh = role_map.get(role, role)
        if i < ctx.current_step:
            emoji, txt = "✅", "已完成"
        elif i == ctx.current_step:
            emoji, txt = "🔄", "进行中"
        else:
            emoji, txt = "⏳", "待开始"
        lines.append(f"  Step {i} {emoji} {role_zh} → {txt}")
```

= +15 / -8 行，净增约 +7

---

## 四、变更汇总

| 文件 | 净增行数 |
|:-----|:--------:|
| server/pipeline_context.py — 4 个新字段 | +12 |
| server/pipeline_context.py — parse_completion() | +6 |
| server/main.py — 导入 | +1 |
| server/main.py — 两副本各 +10 行推进钩子 | +20 |
| server/main.py — !pipeline_status 增强 | +7 |
| **合计** | **~+46** |

(低于 PRD +115 估算，因 PipelineContextManager 主体已在 R77 实现)

---

## 五、影响确认

| 项 | 结论 |
|:---|:------|
| 收到 ✅ / 退回 🔄 / 失败 ❌ 前缀 | ✅ 不变 |
| PM 转发 (_send_to_agent pm_agent_id) | ✅ 在推进钩子之前 |
| bot 自动确认 | ✅ 在推进钩子之前 |
| 无管线时零影响 | ✅ mgr.get() 返回 None → 跳过 |
| 多轮次并发隔离 | ✅ get(round_name) 按名隔离 |
| 不自动派活 | ✅ 只 advance_step()，不 _send_to_agent |

## 六、验收覆盖

| # | 验收项 | 覆盖 |
|:-:|:-------|:-----|
| 1 | create_context 创建 JSON | 已有，补充 4 字段 |
| 2 | advance_step 正确推进 | 已有方法 |
| 3 | get_context 返回正确状态 | 已有 get() |
| 4 | 收到已完成 ✅ 后自动推进 | 两副本插入钩子 |
| 5 | !pipeline_status 显示 | 增强 _format_pipeline_context |
| 6 | 不自动派活 | 钩子只更新状态，不 _send_to_agent |
| 7 | 不破坏现有前缀匹配 | 插入在已有逻辑后、return 前 |
