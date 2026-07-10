# R98 技术方案 — !close_workspace 归档通知增强 🔧

> **版本：** v1.0
> **状态：** 📝 初稿
> **作者：** 🏗️ 小开 (arch)
> **日期：** 2026-07-11
> **改动文件：** `server/handler.py`（~+15 行，仅 `_cmd_close_workspace`）

---

## 改动一览

| 文件 | 位置 | 操作 | 行数 |
|:-----|:------|:----|:----:|
| `handler.py` | `_cmd_close_workspace()` L742-768 | 通知目标从 `ws.members` 改为 `ws.members ∪ PipelineContext 参与者` | ~+15 |

---

## 设计

### 改动前（L742-746）

```python
_notify_ids = ws.members  # set

for _member_id in list(ws.members):  # ← 仅 ws.members
    if _member_id == sender_id:
        continue
```

### 改动后

```python
# ── R98: 合并 ws.members + PipelineContext 参与者 ──
_notify_ids = set(ws.members)
try:
    _mgr = _ensure_pipeline_manager()
    if _mgr:
        _round_name = ws.name.split('-')[0] if '-' in ws.name else ws.name
        _ctx = _mgr.get_context(_round_name)
        if _ctx and isinstance(_ctx, dict):
            for _step in _ctx.get("steps", {}).values():
                if isinstance(_step, dict) and _step.get("agent_id"):
                    _notify_ids.add(_step["agent_id"])
except Exception:
    pass  # PipelineContext 不存在时静默回退到 ws.members 模式

_notify_ids.discard(sender_id)

for _member_id in list(_notify_ids):  # ← 改为合并后的集合
```

### 要点

1. **`_ensure_pipeline_manager()`** — 惰性获取 PipelineContextManager，已在 handler.py L78 定义，直接调用
2. **`isinstance(_ctx, dict)`** — 守卫，确保有 pipeline 时才扩增参与者
3. **`_step.get("agent_id")`** — 无 agent_id 的 step（如未派活的 step）静默跳过
4. **set 合并** — 天然去重，同一 bot 既是 workspace member 又是 pipeline participant 只收到一条
5. **`_notify_ids.discard(sender_id)`** — 通知范围移到循环外处理（原是在循环内 `if _member_id == sender_id: continue` 逐条判断）
6. **`try/except`** — 覆盖 PipelineContext 读取全流程，失败不阻塞归档

### _round_name 提取

复用已有逻辑（L743）：`ws.name.split('-')[0] if '-' in ws.name else ws.name`

例如 `R98-dev` → `R98`，用于查询 PipelineContext 的 key。

---

## 兼容性

| 场景 | 旧行为 | R98 后行为 | 兼容性 |
|:-----|:-------|:-----------|:------:|
| 无 PipelineContext 的 workspace | 通知 ws.members | 通知 ws.members（try/except 静默回退） | ✅ |
| PipelineContext 有参与者 | 仅 ws.members | ws.members + 参与者（去重） | ✅ 增强 |
| PipelineContext 的 step 无 agent_id | 仅 ws.members | 仅 ws.members（agent_id 为空时跳过） | ✅ |
| 调用者 | 不通知自己 | 不通知自己（discard(sender_id)） | ✅ |
| 通知发送失败 | 失败不阻塞 return | 不阻塞 return（try/except 保留） | ✅ |

---

## 验收清单

| # | 验收项 |
|:-:|:-------|
| 1 | 归档通知送达 ws.members + PipelineContext 参与者 |
| 2 | 同一 bot 只收一条（set 去重） |
| 3 | 调用者自己不收到 |
| 4 | 无 PipelineContext 时兼容旧行为 |
| 5 | 无 agent_id 的 step 静默跳过 |
| 6 | 通知失败不阻塞关闭 |
| 7 | !step_handoff 自动 close 正常 |

---

*改动极小，tech plan 精简。Step 3 Dev 可直接按此文编码。*
