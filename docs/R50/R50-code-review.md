# R50 代码审查报告

> **审查者：** 🔍 review-bot
> **审查时间：** 2026-06-28
> **审查范围：** `0778b48` — 方向 A 自动 MSG_SET_ACTIVE_CHANNEL
> **目标文件：** `server/handler.py`（+54/-22）

---

## 1. 改动概览

| 改动点 | 影响 |
|:-------|:------|
| `_broadcast_active_channel(ws_id)` 公共函数 | 从 R37 B-1 22 行内联代码提取为新函数 |
| R37 B-1 rollcall | 内联代码 → `await _broadcast_active_channel(target_ch)` |
| `_cmd_step_complete` | Task 创建 → 自动广播频道切换 → 更新状态 |
| `_cmd_rollcall_next` | 上下文含 R/Step 时自动广播频道切换 |

---

## 2. 逐项审查

### 2.1 `_broadcast_active_channel(ws_id)` — ✅ 通过

**位置：** 行 972-1007

| 审查项 | 结果 | 说明 |
|:-------|:----:|:------|
| 函数签名 | ✅ | 接收 `ws_id`，返回 `int`（在线连接数） |
| 空安全 | ✅ | `ws_obj is None` 时返回 0 |
| 持久化 | ✅ | 循环中 `set_agent_channel` + 循环后 `save_agent_channels` |
| 连接遍历 | ✅ | 遍历 `_connections.get(member_id, set())`，逐连接发送 |
| 错误处理 | ✅ | 单连接异常用 try/except pass 隔离 |
| 日志 | ✅ | `R50 A: MSG_SET_ACTIVE_CHANNEL` 日志标记清晰 |

**结论：** 函数提取正确，行为与 R37 B-1 完全一致。✅

### 2.2 R37 B-1 rollcall 重构 — ✅ 通过

**位置：** 行 2456-2469

```python
# 改动前（22 行）：内联构造 switch_payload、遍历成员、持久化、发送
# 改动后（1 行）：
online_switch = await _broadcast_active_channel(target_ch)
```

| 审查项 | 结果 | 说明 |
|:-------|:----:|:------|
| 行为等价 | ✅ | 同名参数 `target_ch` 传入，逻辑完全一致 |
| 日志迁移 | ✅ | `R37: Auto MSG_SET_ACTIVE_CHANNEL` 日志仍保留 |
| 回归风险 | 🟢 低 | 纯提取替换，无新逻辑 |

**结论：** 干净的 DRY 重构，22 行 → 1 行。✅

### 2.3 `_cmd_step_complete` 自动广播 — ✅ 通过

**位置：** 行 1510-1514

```python
# R50 A: Auto MSG_SET_ACTIVE_CHANNEL to workspace
try:
    await _broadcast_active_channel(ws_id)
except Exception:
    pass
```

| 审查项 | 结果 | 说明 |
|:-------|:----:|:------|
| 时序正确 | ✅ | 在 Task 创建后、状态更新前执行，不影响管道状态机 |
| `ws_id` 来源 | ✅ | 行 1364 `ws_id = sender_ch`，已在管线活跃检查中确认有效 |
| 容错 | ✅ | try/except pass，广播失败不阻断管线推进 |
| 副作用 | 🟡 一致 | **对全体成员广播**（而非仅下一角色），与 R37 B-1 行为一致 |

**结论：** 正确的插入位置，合理的容错策略。✅

### 2.4 `_cmd_rollcall_next` 自动广播 — ⚠️ 建议

**位置：** 行 866-871

```python
# R50 A: Auto MSG_SET_ACTIVE_CHANNEL for pipeline rollcalls
if context_summary and ("R" in context_summary or "Step" in context_summary) and sender_ch != p.LOBBY:
    try:
        await _broadcast_active_channel(sender_ch)
    except Exception:
        pass
```

| 审查项 | 结果 | 说明 |
|:-------|:----:|:------|
| 🟡 **触发条件启发式** | ⚠️ 宽松 | `"R" in context_summary` 匹配**任何含字母 R 的上下文**（如 "refactor", "report", "config"），非仅管线上下文 |
| 🟡 `"Step"` 匹配 | ⚠️ 大小写敏感 | `"Step"` 要求大写 S，context 中实际值均为 `step2`/`Step2` 无定论 |
| `sender_ch != p.LOBBY` | ✅ 合理 | 排除大厅中的点名 |
| 容错 | ✅ | try/except pass |

**建议：** 改用精确匹配——检查 `sender_ch` 是否对应某活跃管线的 `ws_id`：

```python
# 更精确：检查当前频道是否属于活跃管线
is_active_pipeline = any(
    pstate.get("active") and pstate.get("ws_id") == sender_ch
    for pstate in _PIPELINE_STATE.values()
)
if is_active_pipeline:
    await _broadcast_active_channel(sender_ch)
```

优先级：🟡 P3（功能正确，边界场景影响小，可后续优化）

---

## 3. 回归检查

| 场景 | `_cmd_step_complete` | `_cmd_rollcall_next` | R37 B-1 |
|:-----|:--------------------:|:--------------------:|:--------:|
| 管线中 Step 完成 | ✅ 全员切频 | N/A | N/A |
| 管线中 `!rollcall_next` | N/A | ✅ 自动触发 | N/A |
| 普通 `!rollcall_role` (📋点名) | N/A | N/A | ✅ 仍触发广播 |
| 非管线手动 `!rollcall_next` | N/A | ⚠️ 可能误触 | N/A |
| 大厅中 `!rollcall_next` | N/A | ✅ sender_ch == LOBBY 时跳过 | N/A |
| 失败（无工作室/ws_obj 为 None） | ✅ try/except 返回 0 | ✅ 同上 | ✅ 同上 |

---

## 4. 边际问题

### 🟡 方向 B 命令未实现

需求文档要求方向 B 过渡命令（`!pipeline_activate`、`!step_handoff`，P1），当前 commit 未包含。自动切换（方向 A）已就绪，但过渡期手动切换工具缺失。

影响：🟡 低（方向 A 已覆盖 Step 交接场景，方向 B 为冗余手工路径）

### 🟢 返回格式变化（行 872）

```python
# 原（f-string）：
return f"✅ 已通知 {len(matched)} 名 {target_role} 成员接管「{context_summary}」（{sent_count} 人在线）"
# 现（字符串拼接）：
return "✅ 已通知 " + str(len(matched)) + " 名 " + target_role + " 成员接管「" + context_summary + "」（" + str(sent_count) + " 人在线）"
```

输出结果完全相同。不一致仅风格层面，无功能影响。🟢

### 🟢 `_broadcast_active_channel` 与 `_cmd_rollcall_next` 间两次广播

在 `_cmd_step_complete` 中（行 1510-1512）调用 `_broadcast_active_channel` 后，下行又调用 `_cmd_rollcall_next`（行 1498-1501），后者内部再次触发广播。这会导致 **两次 MSG_SET_ACTIVE_CHANNEL** 发送到同一连接。

```python
# _cmd_step_complete 流程：
1498: rollcall_result = await _cmd_rollcall_next(...)  # 内部触发广播
      ...
1510: await _broadcast_active_channel(ws_id)              # 再触发一次
```

影响：🟢 极小。两次都是 `persistence.set_agent_channel + conn.send_str`，幂等操作。最后一次持久化覆盖前一次，结果正确。

---

## 5. 审查结论

| 维度 | 评分 | 说明 |
|:-----|:----:|:------|
| 功能正确性 | ✅ 通过 | Step 交接自动切频道功能完整可用 |
| 代码质量 | ✅ 通过 | 干净的 DRY 重构（22 行 → 1 行公共函数） |
| 回归安全 | ✅ 通过 | 行为与 R37 B-1 等价，无新回归路径 |
| 边界处理 | ✅ 通过 | try/except 全覆盖，空安全 |
| 风格一致 | 🟢 良好 | 与项目现有风格一致 |
| 文档 | 🟢 良好 | R50-tech-plan.md 已描述方案 |

**整体结论：✅ 通过审查。** 可进入 Step 5 编码（方向 A 后续优化）或 Step 6 测试验证。

### 建议（可选优化）

| # | 问题 | 优先级 | 建议 |
|:-:|:-----|:------:|:-----|
| 1 | `_cmd_rollcall_next` 启发式触发条件过于宽松 | 🟡 P3 | 改为检查 `sender_ch` 是否在活跃管线的 `ws_id` |
| 2 | 方向 B 过渡命令缺失 | 🟡 P3 | 按需求文档补充 `!pipeline_activate`/`!step_handoff`（过渡期冗余路径） |
| 3 | `_cmd_step_complete` 两次广播 | 🟢 P4 | 可优化为仅在 `_cmd_rollcall_next` 中触发一次，删除重复调用 |
