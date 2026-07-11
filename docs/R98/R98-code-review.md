# R98 代码审查报告 — !close_workspace 归档通知增强 🔧

> **审查人：** 🔍 小周
> **审查基准：** `b6e0524` → `6357b2b` + `4e31b5f` + `664d0ed`
> **改动文件：** `server/handler.py` (~+15) · `server/pipeline_context.py` (+1)
> **净变化：** +15 行（三 commit 合计 ~+22 行）
> **参考文档：** `docs/R98/R98-tech-plan.md`

---

## 审查结论：🟢 通过

7 项检查全通过。改动边界清晰，守卫齐全，兼容修复精准。

---

## 1. isinstance(_ctx, dict) 守卫是否齐全

**判定：🟢 通过**

```python
_notify_ids = set(ws.members)
_mgr = _ensure_pipeline_manager()
_ctx = _mgr.get_context(_round_name)
if _ctx and isinstance(_ctx, dict):                     # ← 守卫
    for _step in _ctx.get("steps", {}).values():
        if isinstance(_step, dict) and _step.get("agent_id"):
            _notify_ids.add(_step["agent_id"])
```

| 场景 | `_ctx` 类型 | 行为 |
|:-----|:-----------|:-----|
| PipelineContext dataclass | `PipelineContext` 对象 | `isinstance(_ctx, dict)` = False → 跳过 |
| R97+ dict 上下文 | `dict` | `isinstance(_ctx, dict)` = True → 处理 |
| 无上下文 | `None` | `_ctx` falsy → 跳过 |

`try/except` 包裹整个块 → 任何异常不阻塞关闭 ✅

---

## 2. `_step.get("agent_id")` 空值保护

**判定：🟢 通过**

```python
if isinstance(_step, dict) and _step.get("agent_id"):
```

| 场景 | `_step` 类型 | `agent_id` | 行为 |
|:-----|:------------|:----------|:-----|
| 已派活的 step | `dict` | `"ws_xxx"` | ✅ 加入通知 |
| 未派活的 step | `dict` | `""` (空字符串) | `_step.get("agent_id")` = `""` → falsy → 跳过 |
| 从未派活的 step | `dict` | 无此 key | `_step.get("agent_id")` = `None` → falsy → 跳过 |
| `steps` 值不是 dict | 任意 | — | `isinstance(_step, dict)` = False → 跳过 |

**双重守卫**（isinstance + .get）确保无异常风险 ✅

---

## 3. `_notify_ids.discard(sender_id)` 在 sender 非成员时无害

**判定：🟢 通过**

```python
_notify_ids.discard(sender_id)
```

`set.discard(elem)` 与 `set.remove(elem)` 的区别：

| 方法 | elem 在集合中 | elem 不在集合中 |
|:-----|:------------|:---------------|
| `discard` | 移除 | ❌ 无操作，无异常 |
| `remove` | 移除 | 🔴 抛 KeyError |

使用 `discard` 是正确选择。无论 sender 是 workspace member、PipelineContext 参与者、或两者都不是，都安全。 ✅

---

## 4. try/except 包裹整个通知块

**判定：🟢 通过**

```python
# ── R79+: Notify all workspace members ──
# ── R98: 合并 ws.members + PipelineContext 参与者 ──
try:
    _round_name = ...
    _end_msg = ...
    _notify_ids = set(ws.members)                # ← 集合构建
    _mgr = _ensure_pipeline_manager()
    _ctx = _mgr.get_context(_round_name)          # ← PipelineContext 读取
    if _ctx and isinstance(_ctx, dict):
        for _step in _ctx.get("steps", {}).values():
            ...                                    # ← step 遍历
    _notify_ids.discard(sender_id)
    for _member_id in list(_notify_ids):
        ... send notifications ...                # ← 发送
    ...
except Exception as e:
    logger.warning("Round-end notification failed (non-fatal): %s", e)
```

整个通知流程（从 round_name 提取到逐个发送）都在 `try/except Exception` 内。任何阶段失败 → 日志警告 → 不阻塞 `!close_workspace` 的 return。 ✅

---

## 5. 日志从 member(s) 改为 recipient(s)

**判定：🟢 通过**

```python
# 改前
logger.info("Round-end notifications sent to %d member(s) for %s", ...)

# 改后
logger.info("Round-end notifications sent to %d recipient(s) for %s", ...)
```

通知目标集合现在可能包含非 workspace member 的 PipelineContext 参与者。"recipient(s)" 比 "member(s)" 更准确。 ✅

---

## 6. 兼容修复：`_save()` dict 兼容 (`4e31b5f`)

**判定：🟢 通过**

```python
data = {
    round_name: ctx.to_dict() if hasattr(ctx, "to_dict") else ctx
    for round_name, ctx in self._contexts.items()
}
```

| 场景 | 处理 | 结果 |
|:-----|:------|:------|
| `PipelineContext` 对象 | `hasattr(ctx, "to_dict")` = True → `ctx.to_dict()` | ✅ 序列化为 dict |
| 普通 dict | `hasattr(ctx, "to_dict")` = False → `ctx` 原样写入 | ✅ 正确 |

`hasattr` 用 duck typing 代替 type check，更 Pythonic。 ✅

---

## 7. 兼容修复：`_cmd_pipeline_stop` dict 兼容 (`664d0ed`)

**判定：🟢 通过**

### 发起者提取

```python
creator = ctx.created_by if hasattr(ctx, "created_by") else ctx.get("created_by", "")
```

| 场景 | 结果 |
|:-----|:------|
| `PipelineContext.created_by` 属性 | `hasattr` True → 直接读取 ✅ |
| `dict["created_by"]` | `hasattr` False → `.get()` 兜底 ✅ |

### 状态检查

```python
_ctx_status = ctx.status.value if hasattr(ctx, "status") and hasattr(ctx.status, "value") else \
              ctx.status if hasattr(ctx, "status") else \
              ctx.get("status", "")
```

| 场景 | 匹配分支 | 结果 |
|:-----|:---------|:------|
| `PipelineStatus` enum | `hasattr(ctx.status, "value")` | ✅ `.value` |
| str 属性 | `hasattr(ctx, "status")` | ✅ 直接读 |
| dict key | 兜底 | ✅ `.get()` |

### 状态值扩展

```python
if _ctx_status in ("stopped", "done"):   # ← 新增 "done"
```

已完成管线 `!pipeline_stop` 不再报"状态转换失败"。 ✅

---

## 审查汇总

| 检查项 | 优先级 | 结果 | 备注 |
|:-------|:------:|:----:|:------|
| `isinstance(_ctx, dict)` 守卫 | 🔴 | 🟢 | 双类型兼容 |
| `_step.get("agent_id")` 空值保护 | 🔴 | 🟢 | 空串/None/isinstance 三重保险 |
| `discard(sender_id)` 安全 | 🔴 | 🟢 | `discard` 而非 `remove` |
| try/except 包裹通知块 | 🔴 | 🟢 | 失败不阻塞关闭 |
| 日志 wording | 🟢 | 🟢 | `member` → `recipient` |
| `_save()` dict 兼容 | 🟢 | 🟢 | `hasattr` duck typing |
| `_cmd_pipeline_stop` dict 兼容 | 🟢 | 🟢 | 3 层 status fallback + "done" 支持 |

**最终结论：🟢 通过** — 归档通知合并目标集合守卫齐全、异常安全、兼容修复精准。可进入 Step 5 🦐 QA。

---

*报告编写: 🔍 小周 · 2026-07-11*
