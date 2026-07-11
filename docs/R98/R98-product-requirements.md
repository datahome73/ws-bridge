# R98 — !close_workspace 归档通知增强 + 小修复 🔧

> **版本：** v1.0（初稿）
> **日期：** 2026-07-12
> **作者：** PM 小谷（基于 R97 复盘发现的 F-24）
> **状态：** ⏳ 待审核
> **基线：** R97 后 main latest (`e375714`)
> **本轮改动范围：** `server/handler.py`（`_cmd_close_workspace`）
> **参考：** `docs/TODO.md` F-24
> **F-24 来源：** [R97 复盘](https://github.com/datahome73/ws-bridge/issues?q=F-24)

---

## 0. 触发事件 — R97 关闭通知缺失

R97 完成后，`!close_workspace` 发出的归档通知只到了部分 bot 的 inbox：

```
今天 00:18  系统  →  泰虾
📋 R97 轮的开发工作已经结束，更新记忆，话题归档。
工作室「R97-dev」已关闭。下一轮开发将另启新工作室。
```

**实际只发了 1/6 个 bot。** 原因是通知目标仅取 `ws.members`，但 R97 后 workspace 成员≠管线参与者。

### 根因链

| 层 | 问题 |
|:--|:-----|
| 现象 | 关闭归档通知只发了泰虾 |
| 直接原因 | `_cmd_close_workspace` 通知循环 `for _member_id in list(ws.members)` |
| 深层原因 | R97 后 `!pipeline_start` 不再创建 workspace，workspace 成员集和管线参与者是两套数据 |
| 根源 | 通知逻辑没有考虑 PipelineContext 中的参与 bot |

### 修复方向

`_cmd_close_workspace` 关闭工作室时：
1. **继续发给 `ws.members`**（保持兼容）
2. **额外从 PipelineContext 读取**所有 step 的 `agent_id`，给每位管线参与者发归档通知
3. 去重（同一 bot 既是 member 又是 pipeline 参与者只收一次）

---

## 1. 设计思路

### 1.1 核心变化

| 维度 | 当前行为（R97） | R98 新行为 |
|:-----|:--------------|:----------|
| 通知目标 | `ws.members`（排除 sender） | `ws.members` + **PipelineContext 所有 step 的 agent_id**（去重） |
| 信息来源 | 仅 workspace 数据 | workspace + PipelineContext 双源合并 |
| 通知消息 | “工作室已关闭” 单个消息 | 同一条消息，发给更全的列表 |
| sender 排除 | 仍在（不发给调用者） | 保留（调用者知道自己在做什么） |

### 1.2 改动范围（极小）

只改 `_cmd_close_workspace` 中的通知循环（handler.py ~L738-774），**不涉及 AutoRouter、PipelineContext 主体逻辑**。

```python
# R98 改动示意：合并通知目标
members_to_notify = set(ws.members)

# 从 PipelineContext 补充管线参与者
ctx = mgr.get_context(_round_name)
if ctx and isinstance(ctx, dict):
    for step in ctx.get("steps", {}).values():
        if step.get("agent_id"):
            members_to_notify.add(step["agent_id"])

# 排除发送者
members_to_notify.discard(sender_id)

# 通知循环
for _member_id in members_to_notify:
    ...
```

改动量：约 +15 行。

### 1.3 消息内容不变

```
📋 R{N} 轮的开发工作已经结束，更新记忆，话题归档。

工作室「{ws.name}」已关闭。下一轮开发将另启新工作室。
```

不修改消息文本，只扩大送达范围。

### 1.4 异常安全

| 场景 | 行为 |
|:-----|:-----|
| PipelineContext 不存在（纯 workspace 场景） | 回退到 `ws.members` 通知（兼容旧行为） |
| PipelineContext 中某 step 无 agent_id | 跳过该 step（防止通知空 ID） |
| 重复 agent_id（既在 members 又在 context） | set 自动去重 |
| `sender_id` 是成员之一 | 正常排除（不骚扰调用者） |

---

## 2. 改动细节

### 2.1 `handler.py` — `_cmd_close_workspace` 通知块

**位置：** `~L738-774`

**改动点：** 在 `for _member_id in list(ws.members)` 之前，合并 pipeline 参与者到 set。

```python
# ── R79+: Notify all workspace members that the round is over ──
try:
    _round_name = ws.name.split('-')[0] if '-' in ws.name else ws.name
    _end_msg = (
        f"📋 {_round_name} 轮的开发工作已经结束，更新记忆，话题归档。\n\n"
        f"工作室「{ws.name}」已关闭。下一轮开发将另启新工作室。"
    )

    # R98: 合并 ws.members + PipelineContext 参与者
    _notify_ids = set(ws.members)
    _mgr = _ensure_pipeline_manager()
    _ctx = _mgr.get_context(_round_name)
    if _ctx and isinstance(_ctx, dict):
        for _step in _ctx.get("steps", {}).values():
            if isinstance(_step, dict) and _step.get("agent_id"):
                _notify_ids.add(_step["agent_id"])

    for _member_id in list(_notify_ids):
        if _member_id == sender_id:
            continue
        _inbox_ch = f"_inbox:{_member_id}"
        write_chat_log("系统", _end_msg, channel=_inbox_ch)
        ms.save_message(...)
        _payload = json.dumps({...})
        for _conn in list(_connections.get(_member_id, set())):
            ...  # send via WS
except Exception as e:
    logger.warning("Round-end notification failed (non-fatal): %s", e)
```

### 2.2 不在此轮改动的

| 事项 | 原因 |
|:-----|:------|
| 通知消息内容格式化 | 当前文本足够，不改 |
| `_admin` 频道的 PIPELINE_COMPLETE 消息 | 已在 `_cmd_step_handoff`/`_cmd_task_update` 中处理 |
| workspace 成员管理 | R81 已完成（self-management） |
| AutoRouter 逻辑 | 不涉及 — 纯通知问题 |
| `!pipeline_stop` 通知 | R95 已有关闭信号 |

---

## 3. 验收标准

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `!close_workspace` 后归档通知送达全部管线 bot | 每位管线参与者的 inbox 出现「工作室已关闭」消息 |
| 2 | ws.members 中非管线成员也收到通知 | 纯 workspace 成员（如 observer）也收到 |
| 3 | 调用者自己不收到通知 | sender inbox 无此消息（sender 已知动作） |
| 4 | PipelineContext 不存在时兼容旧行为 | 纯 workspace（无 pipeline）关闭时通知仅发 ws.members |
| 5 | 同一 bot 既是 member 又是 pipeline 参与者只收**一条** | 去重正确 |
| 6 | 无 agent_id 的 step 不产生空通知 | context 中 step.agent_id="" 的 step 静默跳过 |
| 7 | 通知失败不阻塞关闭 | `try/except` 包裹，失败仅打 warning 日志 |
| 8 | 不影响 `!step_handoff` 自动关闭 | pipeline 最后一步的自动 close 仍正常 |

---

## 4. 改动文件清单

| 文件 | 改动量 | 说明 |
|:-----|:------:|:-----|
| `server/handler.py` | ~+15 行 | `_cmd_close_workspace` 通知目标合并 PipelineContext 参与者 |
| | **合计** | **~+15 行** |

---

## 5. 风险与缓解

| 风险 | 缓解 |
|:-----|:------|
| PipelineContext 为空或结构异常 | `isinstance(ctx, dict)` 守卫 + `try/except` 包裹，失败静默回退 |
| `_ensure_pipeline_manager()` 开销 | 已在 `_cmd_pipeline_start` 等路径中缓存，通知场景仅调一次 |
| 发送过多 inbox 消息 | 当前 R79+ 模式已是逐条发 inbox，不改变发送方式 |
| sender 身份误判（如系统级 close） | sender_id 不在成员/参与者中则全部发送（无人被排除） |
