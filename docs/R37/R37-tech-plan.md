# R37 技术方案 — 流水线单次触发优化 + 点名频道纪律

> **版本：** v1.0
> **状态：** ✅ 方案就绪
> **编制人：** 🏗️ 架构师
> **日期：** 2026-06-23
> **基于需求：** docs/R37/R37-requirements.md v1.0 ✅
> **基于工作：** docs/R37/WORK_PLAN.md v1.0 ✅

---

## 一、改动范围总览

本轮改动严格限定在 **第①类（服务器代码）**，不涉及 client/Web UI。

| 文件 | 改动类型 | 预估行数 |
|:-----|:---------|:--------:|
| `server/handler.py` | 功能新增 | ~90 行 |
| `shared/protocol.py` | 常量新增 | ~5 行 |
| `docs/WORKFLOW.md` | 流程更新 | ~15 行 |

**预估总计：~110 行**

---

## 二、方向 A — 流水线单次触发优化

### 2.1 当前状态

现有 `!create_workspace` 命令（R35）功能：
- 创建工作室 + 添加成员
- **不**自动通知成员
- **不**自动发起点名
- P4 权限

### 2.2 改动：`!create_workspace` 增强

在 `_cmd_create_workspace()` 中增加两步后处理逻辑：

```
!create_workspace <name> --members <ids>
    │
    ├─① 创建工作室（现有逻辑不变）
    │
    ├─② 更新创建者活跃频道 → 新工作室
    │     └─ persistence.set_agent_channel(sender_id, ws_id)
    │     └─ 发送 MSG_SET_ACTIVE_CHANNEL 确认
    │
    └─③ 自动向工作室发送点名通知消息
          └─ 通过 handle_broadcast() 或直接 _send_to_workspace_members()
```

#### ② 活跃频道自动绑定

创建者自动切换到新工作室：

```python
# 创建成功后
persistence.set_agent_channel(sender_id, ws_id)
persistence.save_agent_channels(config.DATA_DIR)
await _send(ws, {"type": p.MSG_CHANNEL_UPDATED, p.FIELD_ACTIVE_CHANNEL: ws_id})
```

#### ③ 点名通知自动触发

利用现有 `_broadcast_workspace_ready()` 或直接广播点名通知消息。

方案选型：**延用 `_broadcast_workspace_ready` 模式**，但不修改 `ws_mod.build_workspace_ready()` 的协议，而是在 `_cmd_create_workspace` 中引入一个通知步骤：

```python
# 点名通知
rollcall_msg = json.dumps({
    "type": "plain",
    "content": f"📋 **点名！@全员 工作室 {ws_name} 已创建。\n请回复「到」确认在线。**",
    "workspace_id": ws_id,
    "ts": time.time(),
})
for agent_id in all_members + [sender_id]:
    for conn in list(_connections.get(agent_id, set())):
        ...  # 发送逻辑
```

### 2.3 具体代码实现

#### `_cmd_create_workspace()` 增强（在 `server/handler.py:329`）

```python
async def _cmd_create_workspace(sender_id: str, params: dict) -> str:
    """Create a new workspace. P4 only. R37: auto-bind + auto-rollcall."""
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法: !create_workspace <name> --members <ids>"
    ws_name = positional[0]
    member_ids_raw = params.get("members", "")
    member_ids = [m.strip() for m in member_ids_raw.split(",") if m.strip()]
    ws_id = f"{p.WORKSPACE_ID_PREFIX}{sender_id[:8]}-{ws_name[:20]}"
    users = auth.get_users()
    sender_name = users.get(sender_id, {}).get("name", sender_id[:12])
    result = ws_mod.create_workspace(ws_id, ws_name, sender_id, sender_name)
    if not result:
        return f"❌ 创建失败：{ws_name} 可能已存在，或管理员名下活跃工作区过多"
    for mid in member_ids:
        if mid in users:
            ws_mod.add_member(ws_id, mid)
    
    # ── R37: Auto-bind creator's active channel ──
    persistence.set_agent_channel(sender_id, ws_id)
    persistence.save_agent_channels(config.DATA_DIR)
    
    # ── R37: Auto-send rollcall notification (async via task) ──
    import asyncio
    asyncio.ensure_future(_auto_rollcall_notify(ws_id, ws_name, member_ids + [sender_id]))
    
    member_list = ", ".join(member_ids) if member_ids else "无"
    return f"✅ 工作室 {ws_name} 已创建，活跃频道已绑定。点名通知已发送。成员: {member_list}"
```

注意：使用 `asyncio.ensure_future()` 避免在 admin 命令的同步调用链中阻塞。

#### 新增 `_auto_rollcall_notify()` 函数

```python
async def _auto_rollcall_notify(ws_id: str, ws_name: str, member_ids: list[str]) -> None:
    """Send rollcall notification to all workspace members."""
    payload = json.dumps({
        "type": "plain",
        "content": f"📋 **点名！@全员**\n\n工作室 **{ws_name}** 已创建，请回复「到」确认在线。\n\n主持人（泰虾）请接管点名流程。",
        "workspace_id": ws_id,
        "ts": time.time(),
        "from_admin": True,
    })
    for agent_id in member_ids:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload)
                elif hasattr(conn, "send"):
                    await conn.send(payload)
            except Exception:
                pass
    logger.info("R37 auto-rollcall sent to %d members of '%s'", len(member_ids), ws_id)
```

---

## 三、方向 B — 点名频道纪律

### 3.1 核心方案

点名流程中增加两个服务器端钩子：

```
点名开始
    │
    ├─① 服务器自动向全员发送 MSG_SET_ACTIVE_CHANNEL → ws_id
    │     (在 Lobby "📋点名" 消息触发后自动执行)
    │
    ├─② 全员回复「到」
    │     └─ 服务器验证活跃频道
    │
    ├─③ 泰虾：「已切确认」
    │     └─ 全员回复「已切」
    │
    └─④ 服务器验证所有成员活跃频道 == ws_id → 通知点名完成
```

### 3.2 技术实现

#### 3.2.1 服务器自动 MSG_SET_ACTIVE_CHANNEL

在 `handle_broadcast()` 处理大厅 `📋点名` 类型消息时，增加自动频道切换逻辑：

```python
# 在 handle_broadcast() 中，处理大厅消息的部分
if content.startswith("📋"):
    # R37: Detect rollcall with workspace reference
    # Extract workspace name or ID from the content
    # Auto-send MSG_SET_ACTIVE_CHANNEL to all mentioned members
    ...
```

**具体方案：** 在 `handle_broadcast()` 的 `📋点名` 分支中（约 line 856-862），增加：

```python
# ── R37: Auto MSG_SET_ACTIVE_CHANNEL on rollcall ──
if content.startswith("📋"):
    # Extract workspace ID if present in content or from sender's channel
    ws_id_from_msg = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
    ws_target = ws_id_from_msg or persistence.get_agent_channel(sender_id)
    
    # Only process if target is a valid active workspace
    ws_obj = ws_mod.get_workspace(ws_target) if ws_target else None
    if ws_obj and ws_obj.state == ws_mod.WorkspaceState.ACTIVE:
        # Send MSG_SET_ACTIVE_CHANNEL to all targets
        for target_id in targets:
            if target_id != sender_id:
                # Check if target is already on correct channel
                current_channel = persistence.get_agent_channel(target_id)
                if current_channel != ws_target:
                    persistence.set_agent_channel(target_id, ws_target)
                    persistence.save_agent_channels(config.DATA_DIR)
                    for conn in list(_connections.get(target_id, set())):
                        try:
                            msg_set = json.dumps({
                                "type": p.MSG_SET_ACTIVE_CHANNEL,
                                p.FIELD_CHANNEL: ws_target,
                            })
                            if hasattr(conn, "send_str"):
                                await conn.send_str(msg_set)
                            elif hasattr(conn, "send"):
                                await conn.send(msg_set)
                        except Exception:
                            pass
```

#### 3.2.2 「已切」确认流程协议

方向 B 需要服务器端能够：
1. 接收「已切」确认消息
2. 验证活跃频道
3. 收集结果

**方案选型：** 定一个新的消息类型 `MSG_ROLLCALL_CONFIRM`，在 `shared/protocol.py` 中定义：

```python
MSG_ROLLCALL_CONFIRM = "rollcall_confirm"  # R37: Channel switch confirm
```

处理逻辑在 `handle_message` 的广播分支中：

```python
elif msg_type == p.MSG_ROLLCALL_CONFIRM:
    # Agent confirms channel switch
    ws_id = msg.get(p.FIELD_WORKSPACE_ID, "")
    if not ws_id:
        continue
    # Record confirmation
    persistence.set_agent_attr(agent_id, "rollcall_confirmed", ws_id)
    # Send ACK
    await _send(ws, {"type": "ack", "message": "✅ 频道切换已确认"})
```

#### 3.2.3 服务器端验证

新增 `_verify_rollcall_complete()` 函数：

```python
async def _verify_rollcall_complete(ws_id: str, member_ids: set[str]) -> dict:
    """Verify all members have switched to the target workspace channel.
    Returns dict of {agent_id: status} where status is 'ok' or 'needs_attention'.
    """
    results = {}
    for agent_id in member_ids:
        current_channel = persistence.get_agent_channel(agent_id)
        results[agent_id] = "ok" if current_channel == ws_id else "needs_attention"
    return results
```

此函数通过 `!check_rollcall` 命令或由点名主持人主动调用。

---

## 四、shared/protocol.py 新增常量

```python
# ── R37: Rollcall & Workspace-Lifecycle ──
MSG_ROLLCALL_CONFIRM = "rollcall_confirm"   # Agent → Server: rollcall channel confirm
MSG_ROLLCALL_VERIFY = "rollcall_verify"     # Server → Agent: rollcall verification
```

---

## 五、WORKFLOW.md 更新

### Step 1 变更
| 旧 | 新 |
|:---|:---|
| 仅小爱手动建工作室 | `!create_workspace <name> --members <ids>` → 自动创建 + 绑定频道 + 发点名通知 |

### Step 2 变更
| 旧 | 新 |
|:---|:---|
| 仅口头点名，无验证 | 服务器自动 `MSG_SET_ACTIVE_CHANNEL` |
| | 「已切」确认协议 |
| | 服务器端验证所有成员活跃频道 |

---

## 六、风险与兼容性

| 风险 | 缓解措施 |
|:-----|:---------|
| `_cmd_create_workspace` 当前是同步返回 str，R37 改异步后需要兼容 admin 命令调度器 | ❓ 需要确认 `_ADMIN_COMMANDS` 的 dispatch 是否支持 async handler，如果不支持则用 `asyncio.ensure_future` 调度后台任务 |
| 点名通知可能被成员在离线状态时遗漏 | 点名通知通过广播发送，在线成员即时收到；通知也写入 chat log 供离线查阅 |
| `MSG_SET_ACTIVE_CHANNEL` 在点名时自动发送可能覆盖成员手动切换的频道 | 只在点名场景触发，且目标频道为当前工作室，属于期望行为 |
| Lobby 「📋点名」消息的拦截逻辑是否需要和普通消息区分 | 不需要 — 现有 `📋点名` 前缀 + `_admin` 频道模式已能区分 |

---

## 七、未纳入方案

| 事项 | 原因 |
|:-----|:------|
| Android APK 封装 | 不涉及服务端逻辑 |
| P3 角色体系完善 | 独立方向 |
| 审批配对码全程自动化 | 超出 R35-1 范围 |
| 自动读取 WORK_PLAN.md 成员列表 | 脱敏原因，手动 `--members` 指定 |
