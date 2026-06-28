# R50 代码审查报告

> **审查者：** 🔍 小周
> **审查时间：** 2026-06-28
> **审查范围：**
>   - `0778b48` ✅ — 方向 A: 自动 MSG_SET_ACTIVE_CHANNEL（+54/-22，代码存在）
>   - `fbfd902` ❌ — 方向 B: !pipeline_activate + !step_handoff（+251/-25，**commit 丢失**）
> **目标文件：** `server/handler.py`

---

## 审查结论速览

| 方向 | 提交 | 状态 | 行数 | 结论 |
|:----:|:----:|:----:|:----:|:----:|
| A | `0778b48` | ✅ 代码存在 | +54/-22 | **✅ 审查通过** |
| B | `fbfd902` | ❌ **commit 丢失** | +251/-25 | **⛔ 阻塞 — 无法审查** |

---

## 一、0778b48 — 方向 A: 自动 MSG_SET_ACTIVE_CHANNEL ✅

### 1.1 改动概览

| # | 改动点 | 行号 (dev HEAD) | 行数 |
|:-:|:-------|:---------------:|:----:|
| 1 | `_broadcast_active_channel(ws_id)` 公共函数提取 | L972-1007 | +36 |
| 2 | R37 B-1 rollcall 重构为调用该函数 | L2464 | 22行→1行 (-21) |
| 3 | `_cmd_step_complete` 自动广播频道切换 | L1510-1514 | +5 |
| 4 | `_cmd_rollcall_next` 管线上下文自动广播 | L866-871 | +6 |
| 5 | R37 B-1 22 行内联代码移除 | — | -22 |
| | **合计** | | **+54/-22** |

### 1.2 逐项审查

#### 1.2.1 `_broadcast_active_channel(ws_id)` — ✅ 通过

**位置：** L972-1007

| 审查项 | 结果 | 证据 |
|:-------|:----:|:------|
| **函数签名** | ✅ | `async def _broadcast_active_channel(ws_id: str) -> int` — 类型标注完整 |
| **空安全** | ✅ | `ws_obj is None` → 返回 0，不会出现 `NoneType has no attribute members` |
| **持久化顺序** | ✅ | 每个 member 循环中 `set_agent_channel()` + 循环后 `save_agent_channels()` — 与 R37 原始逻辑一致 |
| **连接发送** | ✅ | `_connections.get(member_id, set())` 安全迭代，兼容 `send_str` / `send` 两种协议 |
| **异常隔离** | ✅ | 单 conn 异常用 try/except pass 隔离，不阻断其他成员 |
| **日志** | ✅ | `R50 A: MSG_SET_ACTIVE_CHANNEL '%s' sent to %d online members` — 日志标记清晰 |
| **函数放置位置** | ✅ | 放在 `_update_pipeline_step` 和 `_clear_pipeline_state` 之间，与相邻函数风格一致 |
| **返回类型一致性** | 🟢 好 | 所有路径都返回 int（空返回 0，正常返回 online_count） |

**结论：** 与 R37 B-1 原始行为等价，提取干净，无逻辑偏差。✅

#### 1.2.2 R37 B-1 rollcall 重构 — ✅ 通过

**位置：** L2455-2470 (parent `ecf9ffd` L2400-2422 → 1 行函数调用)

| 审查项 | 结果 | 说明 |
|:-------|:----:|:------|
| **行为等价** | ✅ | 完全相同参数 `target_ch` 传入，逻辑完全一致 |
| **持久化优化** | ✅ | 原代码每成员循环 `save_agent_channels()`（N 次 I/O），新代码循环后只调用 1 次 |
| **日志迁移** | ✅ | 原 `R37: Auto MSG_SET_ACTIVE_CHANNEL` 日志保留在新函数中 |
| **回归风险** | 🟢 极低 | 纯提取替换，无新逻辑 |

**结论：** DRY 重构正确，22 行 → 1 行，且减少 N-1 次不必要的 I/O。✅

#### 1.2.3 `_cmd_step_complete` 自动广播 — ✅ 通过

**位置：** L1510-1514

```python
# R50 A: Auto MSG_SET_ACTIVE_CHANNEL to workspace
try:
    await _broadcast_active_channel(ws_id)
except Exception:
    pass
```

| 审查项 | 结果 | 证据 |
|:-------|:----:|:------|
| **时序** | ✅ | Task 创建（L1498-1504）→ 广播频道切换（L1510-1512）→ 更新管线状态（L1517） |
| **ws_id 来源** | ✅ | `sender_ch`，已在管线活跃检查中确认有效 |
| **容错** | ✅ | try/except pass，广播失败不阻断管线推进 |
| **幂等性** | ✅ | 多次 `set_agent_channel` 写入相同值，结果一致 |

**⚠️ 问题：双发广播**

`_cmd_step_complete` 内部先调用 `_cmd_rollcall_next`（L1498-1501），后者已包含 `_broadcast_active_channel` 调用（L866-871）。然后在 L1510-1512 再次调用 `_broadcast_active_channel`，导致**同一个函数调用栈内触发两次 MSG_SET_ACTIVE_CHANNEL**。

**影响：** 两次广播同 ws_id 到同一连接，对客户端无实质影响（幂等）。但多一次全成员广播开销。

**建议：** 🟢 P4 — 可后续优化，当前不影响功能。

#### 1.2.4 `_cmd_rollcall_next` 自动广播 — ⚠️ 条件宽松

**位置：** L866-871

```python
if context_summary and ("R" in context_summary or "Step" in context_summary) and sender_ch != p.LOBBY:
    try:
        await _broadcast_active_channel(sender_ch)
    except Exception:
        pass
```

| 审查项 | 结果 | 说明 |
|:-------|:----:|:------|
| **触发条件** | ⚠️ **宽松** | `"R" in context_summary` 会匹配 `"refactor"`、`"config"`、`"report"`、`"error"` 等任何含字母 R 的单词 |
| **大小写** | ⚠️ 局限 | `"Step"` 要求大写 S，但 context 值可能小写（如 `step2`） |
| **非管线守卫** | ✅ | `sender_ch != p.LOBBY` 正确排除大厅中的普通点名 |
| **容错** | ✅ | try/except pass |

**建议：** 🟡 P2 — 改用 `sender_ch` 查活跃管线状态：

```python
is_pipeline_active = any(
    p.get("active") and p.get("ws_id") == sender_ch
    for p in _PIPELINE_STATE.values()
)
if is_pipeline_active:
    await _broadcast_active_channel(sender_ch)
```

优先级：🟡 P2（功能正确，边界误触几率低，建议优化但非阻塞）

#### 1.2.5 R37 B-1 内联代码删除 — ✅ 通过

原始 22 行内联代码（parent `ecf9ffd` L2400-2422）已完全替换为函数调用。通过 `git diff ecf9ffd..0778b48 -- server/handler.py` 验证无残留。✅

### 1.3 回归矩阵

| 场景 | _cmd_step_complete | _cmd_rollcall_next | R37 B-1 点名 |
|:-----|:------------------:|:------------------:|:------------:|
| 管线 Step 完成 | ✅ 广播 | N/A | N/A |
| 管线中 `!rollcall_next` | N/A | ✅ 触发（条件宽松） | N/A |
| 普通 `!rollcall_role`（📋点名） | N/A | N/A | ✅ 仍触发（R37 原始逻辑） |
| 非管线手动 `!rollcall_next` | N/A | ⚠️ 可能误触 | N/A |
| 大厅中 `!rollcall_next` | N/A | ✅ LOBBY 守卫跳过 | N/A |
| 工作室不存在 | ✅ 返回 0 | ✅ 返回 0 | ✅ 返回 0 |

### 1.4 0778b48 审查结论

| 维度 | 评分 | 说明 |
|:-----|:----:|:------|
| 功能正确性 | ✅ 通过 | 自动 MSG_SET_ACTIVE_CHANNEL 功能完整 |
| 代码质量 | ✅ 通过 | 干净提取，22 行 → 1 行函数调用 |
| 回归安全 | ✅ 通过 | 行为与 R37 等价 + 减少 N-1 次 I/O |
| 边界处理 | ✅ 通过 | try/except 全覆盖，空安全 |
| 风格一致 | 🟢 良好 | 与项目风格一致，日志标记清晰 |

**整体结论：✅ 审查通过。** 可进入下一步。

**建议优化（非阻塞）：**
| # | 问题 | 优先级 | 建议 |
|:-:|:-----|:------:|:-----|
| 1 | `_cmd_rollcall_next` 触发条件宽松 | 🟡 P2 | 改用活跃管线 ws_id 精确匹配 |
| 2 | `_cmd_step_complete` 双发广播 | 🟢 P3 | 删除 L1510-1512 的重复 `_broadcast_active_channel` 调用 |

---

## 二、fbfd902 — 方向 B: !pipeline_activate + !step_handoff ❌

### 2.1 状态：commit 丢失

| 属性 | 值 |
|:-----|:-----|
| 预期内容 | `!pipeline_activate` + `!step_handoff` 两条 admin 命令，+251/-25 |
| 审查状态 | **⛔ 阻塞** |
| 原因 | **fbfd902 在 dev 分支上不存在** — 经 `git ls-remote` 全仓库搜索无此 commit。该提交在 force-push 中丢失（详见 `docs/R50/R50-issues-summary.md` #1） |
| 来源引用 | issues-summary: "方向 B（`!pipeline_activate` / `!step_handoff`）在 `fbfd902` 提交但未部署" |
| 影响 | 无法审查方向 B 的实际代码。技术方案已就位（`R50-tech-plan.md` §2 含完整伪代码），但实际实现未推送到 remote |

### 2.2 影响范围 & 修复建议

方向 B 为方向 A 的补充——A 已覆盖 Step 交接自动切频道场景，B 提供独立的 `!pipeline_activate` / `!step_handoff` 命令作为显式操作路径。**方向 A 已通过审查，管线流转不受阻塞**。

**修复方案（二选一）：**

| 方案 | 操作 | 复杂度 | 备注 |
|:----|:------|:------:|:------|
| **A** | 按 tech-plan §2 重新编码 `!pipeline_activate` + `!step_handoff` | 🟡 中等 | ~250 行，需要 dev-bot 重新实现 |
| **B** | 方向 B 作为 R51 的低优先级补充 | 🟢 低 | 方向 A 已覆盖核心场景 |

**建议：** 方向 A 已通过审查，当前管线流转所需功能已就绪。方向 B 可暂缓。

---

## 三、跨方向回归检查

| 检查项 | 状态 | 说明 |
|:-------|:----:|:------|
| 现有 `!pipeline_start` 不受影响 | ✅ | 未修改 |
| 现有 `!step_complete` 行为不变 | ✅ | 仅新增广播，原有逻辑链不变 |
| 现有 `!rollcall_role` 不受影响 | ✅ | R37 B-1 原始路径保留 |
| 现有 `!rollcall_next` 功能不变 | ✅ | 仅新增条件触发的广播 |
| `_PIPELINE_STATE` 结构不变 | ✅ | 无字段增减 |
| `_ADMIN_COMMANDS` 结构不变 | ✅ | 方向 B 命令未注册（丢失） |
| Gateway 兼容性 | ✅ | 不影响 gateway 路径 |
| 数据持久化 | ✅ | 循环后一次性 `save_agent_channels` 优于原逻辑 |

---

## 四、审查总结

| 方向 | commit | 审查结论 | 下一步 |
|:----:|:------:|:--------:|:-------|
| A | `0778b48` | **✅ 通过** | 可进入测试验证（Step 5） |
| B | `fbfd902` | **❌ commit 丢失** | 需重新编码或暂缓至 R51 |

**当前管线状态：** 方向 A 已审查通过。建议 PM 决策方向 B 处理方式后，进入 Step 5 测试验证。
