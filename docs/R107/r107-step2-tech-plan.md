# R107 技术方案 — Step 2 交付

> **轮次：** R107
> **角色：** 小开（架构师）
> **日期：** 2026-07-13

---

## 一、_handle_server_relay 两副本消除

### 1.1 现状

| 项 | 行号 | 说明 |
|:---|:-----|:------|
| `_try_advance_pipeline()` | L2381 | 同步函数 |
| **副本 1** `_handle_server_relay()` | **L2424 – L2627** | ~203 行 |
| **副本 2** `_handle_server_relay()` | **L2628 – L2830** | ~203 行，完全相同 |
| 调用点 | L2868 | `if await _handle_server_relay(ws, agent_id, msg):` |

### 1.2 方案

**保留：** 副本 1（L2424–L2627）
**删除：** 副本 2（L2628–L2830）

**调用点 L2868 无需修改** — 删除副本 2 后 L2868 自然调用唯一剩下的副本 1（签名完全一致）。

**验证：** `grep -c "async def _handle_server_relay" server/main.py` → 1

**净删除：** −203 行

---

## 二、Pipeline Context 4 新字段

### 2.1 dataclass 声明（pipeline_context.py L131 后）

```python
    # ── R107: Pipeline 业务字段 ──
    round_title: str = ""                        # 轮次标题
    references: dict = field(default_factory=dict)  # {requirements_url, work_plan_url}
    artifacts: dict = field(default_factory=dict)   # 每步产出 KV
    message_templates: dict = field(default_factory=dict)  # 派活模板
```

### 2.2 to_dict()（~L198 后） + from_dict()（~L220 后）

各 +4 行，字段名保持与声明一致，from_dict 用 `.get("field", {})` 保证旧数据反序列化兼容。

**合计：** +12 行

---

## 三、_render_template 设计

### 3.1 变量来源优先级（后覆盖前）

```
1. ctx.round_name / ctx.round_title      → {round}, {round_title}
2. ctx.references                        → {requirements_url}, {work_plan_url}
3. ctx.artifacts（按 step_key 字母序遍历） → {commit_sha}, {file_changes} 等
```

### 3.2 位置

`_send_to_agent()` (L2348) 之后、`_try_advance_pipeline()` (L2381) 之前，约 L2370。

### 3.3 代码

```python
def _render_template(template: str, ctx: PipelineContext) -> str:
    vars_pool = {
        "round": ctx.round_name,
        "round_title": ctx.round_title,
        "requirements_url": ctx.references.get("requirements_url", ""),
        "work_plan_url": ctx.references.get("work_plan_url", ""),
    }
    for step_key in sorted(ctx.artifacts.keys()):
        step_data = ctx.artifacts.get(step_key, {})
        if isinstance(step_data, dict):
            vars_pool.update(step_data)
    result = template
    for key, value in vars_pool.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result
```

未匹配的 `{var}` 保留原文。**~18 行**

---

## 四、_auto_dispatch + AUTO_DISPATCH_ENABLED

### 4.1 开关（config.py L82 后）

```python
# ── R107: 自动派活开关 — 默认关闭 ──
AUTO_DISPATCH_ENABLED: bool = os.environ.get("AUTO_DISPATCH_ENABLED", "0") == "1"
```

**+3 行**

### 4.2 辅助函数

```python
def _get_step_agent_name(ctx: PipelineContext, step_num: int) -> str:
    step_key = f"step{step_num}"
    info = next((s for s in ctx.steps if s.get("name") == step_key), None)
    if info:
        return info.get("agent_name", info.get("agent_id", "?"))
    return "?"
```

### 4.3 _auto_dispatch（~50 行）

```python
async def _auto_dispatch(ctx: PipelineContext, step_num: int) -> bool:
    """自动派活下一步。开关关闭时仅模拟记录日志。"""
    if not config.AUTO_DISPATCH_ENABLED:
        next_tpl = ctx.message_templates.get(f"step{step_num}", "")
        if next_tpl:
            rendered = _render_template(next_tpl, ctx)
            target = _get_step_agent_name(ctx, step_num)
            logger.info("[R107] 自动派活已关闭 skip %s step%d→%s:\n%s",
                        ctx.round_name, step_num, target, rendered[:200])
        return False

    # 开关打开后的实际发送逻辑
    next_step_key = f"step{step_num}"
    next_template = ctx.message_templates.get(next_step_key)
    if not next_template:
        return False
    next_step_info = next(
        (s for s in ctx.steps if s.get("name") == next_step_key), None
    )
    if not next_step_info or not next_step_info.get("agent_id"):
        return False
    target_agent_id = next_step_info["agent_id"]
    content = _render_template(next_template, ctx)
    payload = {
        "type": "message", "channel": "_inbox:server",
        "content": content, "from_name": "小谷",
        "agent_id": config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID,
        "to_agent": target_agent_id,
        "id": f"auto-{ctx.round_name}-step{step_num}-{int(time.time()*1000)}",
        "ts": time.time(),
    }
    sent = await _send_to_agent(target_agent_id, payload)
    return sent > 0
```

---

## 五、同步函数启动 async

### 5.1 问题

`_try_advance_pipeline()` (L2381) 是 `def`（同步），不能 `await _auto_dispatch()`。

### 5.2 方案：asyncio.ensure_future

在 `_try_advance_pipeline` 推进成功分支末尾插入：

```python
        if completed_step == old_step:
            asyncio.ensure_future(mgr.advance_step(round_name))
            logger.info(...)
            # ── R107: 自动派活下一步 ──
            next_step = old_step + 1
            if next_step <= ctx.total_steps:
                asyncio.ensure_future(_auto_dispatch(ctx, next_step))
            else:
                # 最后一步 → 标记 completed
                asyncio.ensure_future(_mark_completed(round_name))
            return True, round_name
```

辅助函数：

```python
async def _mark_completed(round_name: str) -> None:
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if ctx:
        ctx.status = PipelineStatus.COMPLETED
        logger.info("[R107] %s 全管线已完成 ✅", round_name)
```

**+12 行**

---

## 六、变更行数汇总

| 文件 | 操作 | + | − | 净 |
|:-----|:------|:-:|:-:|:-:|
| config.py | AUTO_DISPATCH_ENABLED | 3 | 0 | +3 |
| pipeline_context.py | 4 字段 + to/from_dict | 12 | 0 | +12 |
| main.py | 删除副本 2 (L2628–2830) | 0 | 203 | −203 |
| main.py | _render_template + _get_step_agent_name | 23 | 0 | +23 |
| main.py | _auto_dispatch | 50 | 0 | +50 |
| main.py | _try_advance_pipeline 内部钩子 | 12 | 0 | +12 |
| main.py | _mark_completed | 5 | 0 | +5 |
| **合计** | | **105** | **203** | **−98** |

符合 PRD 估算（净减 ~-97 行）

---

## 七、影响确认

| 检查项 | 结论 |
|:-------|:------|
| 副本 2 删除后调用点需修改？ | ❌ 不需 — L2868 自然调唯一副本 |
| 开关关闭时绝对不发送？ | ✅ `if not AUTO_DISPATCH_ENABLED: return False` |
| 无 Pipeline Context 不误触？ | ✅ `mgr.get()` → None 直接 return |
| 旧数据反序列化兼容？ | ✅ `.get("field", default)` |
| 未匹配模板变量？ | ✅ `replace` 不匹配时保留原文 |
| 多轮次并发？ | ✅ `get(round_name)` 按名隔离 |
| ensure_future 异常逃逸？ | ✅ 建议加 `.add_done_callback(lambda f: f.exception())` |

---

## 八、验收标准 9 项覆盖

| # | 验收项 | 覆盖 |
|:-:|:-------|:------|
| 1 | `_handle_server_relay` 只有一份 | 删副本 2，grep -c → 1 |
| 2 | 4 新字段序列化正确 | dataclass + to/from_dict 同步 |
| 3 | _render_template 正确渲染 | 三层 vars_pool 优先级 |
| 4 | _auto_dispatch 存在可调用 | 函数定义 + _try_advance_pipeline 引用 |
| 5 | 开关关闭时不发消息 | `if not AUTO_DISPATCH_ENABLED: return` |
| 6 | 无 context 不执行 | `mgr.get()` guard |
| 7 | 最后一步 completed | `_mark_completed()` |
| 8 | 多轮次并发隔离 | `get(round_name)` |
| 9 | 开关关闭时 PM 操作不受影响 | 规则 2 转发 + bot 确认在钩子前 |
