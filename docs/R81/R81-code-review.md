# R81 代码审查报告 — Workspace 成员自我管理：5 命令 + 自动加入 + Inbox 邀请 👥

> **审查人：** 🔍 审查工程师
> **审查对象：** `3938e94` feat(R81): Workspace member self-management — 5 commands + auto-join + inbox invite
> **审查日期：** 2026-07-09
> **改动统计：** 1 文件, +284 行

---

## 0. 审查结论

> 🟢 **通过 — 0 项 🔴, 0 项 🟡, 0 项 💡 — 直接进入 Step 5 QA**

---

## 1. 改动统计

| 文件 | 行数 | 改动类型 | 说明 |
|:-----|:----:|:---------|:-----|
| `server/handler.py` | +284 | 新增 | 5 命令 + auto-join + inbox invite + `_resolve_workspace` 辅助函数 |

---

## 2. 逐项审查

### ✅ 2.1 Owner 守卫 — `_cmd_workspace_remove`

```python
# L4984-4985
if sender_id != ws.owner_id:
    return "❌ 权限不足：仅工作区所有者可移除成员"
```

**验证：**

| 场景 | 守卫检查 | 结果 |
|:-----|:---------|:-----|
| Owner 移除成员 | `sender_id == ws.owner_id` → 放行 | ✅ |
| 普通成员尝试移除 | `sender_id != ws.owner_id` → **拒绝** | ✅ |
| 目标 == owner | `target_id == ws.owner_id` → **拒绝**（L4987） | ✅ |
| 目标不在成员中 | `target_id not in ws.members` → 跳过（L4991） | ✅ |

**守卫强度：** 硬性检查，无 fallback。`min_role=2`（全员可用）但 owner 检查在函数内拦截——成员管理权限确实由 owner 守卫而非 `min_role` 兜底。✅

### ✅ 2.2 Owner 不能 leave 自己

```python
# L4909-4910
if sender_id == ws.owner_id:
    return "❌ 你是该工作区的所有者，不能退出。如需关闭请使用 !close_workspace"
```

| 场景 | 结果 |
|:-----|:-----|
| Owner leave 自己 | ❌ 拒绝，提示用 `!close_workspace` |
| 成员 leave | ✅ 放行 |
| 不在工作区中 | `sender_id not in ws.members` → 提示（L4905） |

**指导性消息：** 拒绝时提供替代方案（`!close_workspace`），而非仅拒绝。✅

### ✅ 2.3 `_broadcast_to_channel` 第二个参数类型

**函数签名（L320）：**
```python
async def _broadcast_to_channel(channel: str, payload: dict) -> int:
```

**所有调用点：**

| 命令 | 调用方式 | 类型正确 |
|:-----|:---------|:--------:|
| `_cmd_workspace_join` | `_broadcast_to_channel(ws_id, {dict})` | ✅ |
| `_cmd_workspace_leave` | `_broadcast_to_channel(ws_id, {dict})` | ✅ |
| `_cmd_workspace_add` | `_broadcast_to_channel(ws_id, {dict})` | ✅ |
| `_cmd_workspace_remove` | `_broadcast_to_channel(ws_id, {dict})` | ✅ |
| `_cmd_pipeline_start` B2 | `_broadcast_to_channel(target_ch, {dict})` | ✅ |

所有调用 `payload` 均为 dict 字面量。类型安全 ✅

### ✅ 2.4 审计日志不由函数体内手动记录

**验证：** `git diff 3938e94^..3938e94 | grep audit_logger` → 零匹配 ✅

新的 5 个命令未直接调用 `_audit_logger.log()`——audit 由中央路由器自动处理。符合审查要求。

### ✅ 2.5 Scope 合规

| 文件/模块 | 改动 | 状态 |
|:----------|:-----|:-----|
| `server/handler.py` | ✅ **唯一改动**（+284 行） | ✅ |
| `server/auth.py` | ❌ 未改动（角色等级无变化） | ✅ |
| `server/pipeline_context.py` | ❌ 未改动（状态机无变化） | ✅ |
| `server/templates.py` | ❌ 未改动（前端无变化） | ✅ |
| `shared/protocol.py` | ❌ 未改动 | ✅ |

**结论：** 零 scope creep ✅

### ✅ 2.6 无内部名残留

**验证：** `git diff 3938e94^..3938e94 | grep -n '小谷\|小爱\|小开\|爱泰\|小周\|泰虾\|大宏'` → 零匹配 ✅

---

## 3. 新增代码审查

### 3.1 `_resolve_workspace()` 辅助函数

```python
def _resolve_workspace(sender_id, params):
    ws_id = params.get("workspace", "") or persistence.get_agent_channel(sender_id) or ""
    if not ws_id:
        return (None, "❌ 无法确定工作区...")
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return (None, f"❌ 工作区 {ws_id} 不存在")
    return (ws_id, "")
```

| 检查项 | 结果 |
|:-------|:-----|
| 优先级顺序 | 显式 `--workspace` > 活跃频道 | ✅ |
| 三元 `or` 短路 | 依次尝试，不冗余 | ✅ |
| workspace 存在性验证 | `ws_mod.get_workspace()` | ✅ |
| 返回元组格式 | `(ws_id\|None, err_msg)` | ✅ |

被全部 5 个新命令复用 ✅

### 3.2 R81 B1: ACK 后自动加入工作区

```python
# handler() L6561-6579
if ack_ch and ack_ch.startswith(p.WORKSPACE_ID_PREFIX):
    ack_ws = ws_mod.get_workspace(ack_ch)
    if ack_ws and agent_id not in ack_ws.members:
        ws_mod.add_member(ack_ch, agent_id)
```

- ✅ 仅在 ACK 确认频道路径时触发
- ✅ 仅对 workspace 频道生效（`WORKSPACE_ID_PREFIX`）
- ✅ 仅当成员不在时加入（`not in ws.members`）
- ✅ try/except 全覆盖

### 3.3 R81 B2: 管线启动时 Inbox 邀请

```python
# _cmd_pipeline_start() L2781-2820
if ws_obj and len(ws_obj.members) <= 2:
    for role in all_roles:
        agents = _get_agents_by_role(role)
        for aid in agents:
            if aid not in ws_obj.members:
                target_ch = persistence.get_inbox_channel(aid)
                await _broadcast_to_channel(target_ch, {...})
```

- ✅ 仅成员 ≤2 时触发
- ✅ 遍历所有 step role → 找未加入的 agent
- ✅ 通过 inbox 通道发送（非广播）
- ✅ try/except 全覆盖

### 3.4 命令注册表

| 命令 | `min_role` | 实际权限守卫 | 一致性 |
|:-----|:----------:|:-------------|:-------|
| `workspace_join` | 2 | 成员检查 | ✅ |
| `workspace_leave` | 2 | Owner 守卫 | ✅ |
| `workspace_add` | 2 | sender 必须在工作区 | ✅ |
| `workspace_remove` | 2 | Owner 守卫（硬性） | ✅ |
| `workspace_list_members` | 2 | 无额外守卫 | ✅ |

---

## 4. 边界情况分析

| 场景 | 预期 | 实现 | 状态 |
|:-----|:-----|:-----|:----:|
| Owner 被 `workspace_remove` 目标 | 拒绝 | ✅ `if target_id == ws.owner_id: return "❌"` |
| 非成员 `workspace_remove` | 提示不在工作区 | ✅ `if target_id not in ws.members: return "⏳"` |
| `workspace_add` 不在工作区 | 拒绝 | ✅ `if sender_id not in ws.members: return "❌"` |
| `workspace_add` 已存在 | 提示已在 | ✅ `if target_id in ws.members: return "⏳"` |
| `workspace_join` 已在 | 提示已在 | ✅ `if sender_id in ws.members: return "⏳"` |
| `workspace_leave` 不在 | 提示不在 | ✅ `if sender_id not in ws.members: return "⏳"` |
| `_resolve_workspace` 返回 None | 函数返回 err | ✅ 所有调用者检查 `if err:` |
| B1 ACK 频道非 workspace | 跳过 | ✅ `startswith(WORKSPACE_ID_PREFIX)` |
| B2 成员 >2 | 不邀请 | ✅ `len(ws_obj.members) <= 2` |
| B2 inbox 通道不存在 | 安全跳过 | ✅ `if target_ch:` |

---

## 5. 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:-----|
| 硬编码敏感信息 | ✅ 无 |
| 调试 print 残留 | ✅ 无 |
| TODO/FIXME 残留 | ✅ 无 |
| 内部角色名残留 | ✅ 无 |
| R 标签准确 | ✅ 全部为 R81 |
| `except Exception: pass` | ✅ 合理使用（B1/B2 非阻塞） |

---

## 6. 总结

| 审查项 | 结果 |
|:-------|:-----|
| 1️⃣ Owner 守卫 `_cmd_workspace_remove` | ✅ `sender_id != ws.owner_id` 硬性守卫 |
| 2️⃣ Owner leave 检查 | ✅ `sender_id == ws.owner_id` → 拒绝 + 指导 |
| 3️⃣ `_broadcast_to_channel(payload)` 类型 | ✅ `payload: dict` 全部正确 |
| 4️⃣ 审计日志不由函数体记录 | ✅ 零手动 `audit_logger.log` |
| 5️⃣ Scope 合规 | ✅ 仅 1 文件，无 auth/状态机/前端改动 |
| 6️⃣ 内部名残留 | ✅ 零残留 |

---

> **总体：🟢 通过 — 0 阻塞，直接进入 Step 5 QA**
>
> 审查完毕：2026-07-09 🔍 审查工程师
