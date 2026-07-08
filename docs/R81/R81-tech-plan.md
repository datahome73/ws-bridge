# R81 技术方案 — 工作区成员自动化管理 🤖

> **版本：** v1.0
> **状态：** ✅ 技术方案
> **架构师：** 👷 架构师
> **日期：** 2026-07-09
> **基线：** `1dbdee7`（main）
> **改动范围：** `server/handler.py` `server/workspace.py`（接口确认）

---

## 目录

1. [方向 A：5 个新 workspace 命令](#1-方向-a5-个新-workspace-命令)
2. [方向 B：自动化成员补充](#2-方向-b自动化成员补充)
3. [方向 C：成员列表查询](#3-方向-c成员列表查询)
4. [方向 D：min_role 降级评估](#4-方向-dmin_role-降级评估)
5. [改动汇总](#5-改动汇总)
6. [兼容性分析](#6-兼容性分析)

---

## 1. 方向 A：5 个新 workspace 命令

### 1.1 活跃频道推断模式

所有新命令使用统一的「当前活跃工作区」推断逻辑：

```python
def _resolve_workspace(sender_id: str, params: dict) -> tuple[str | None, str]:
    """确定目标工作区 ID。
    
    优先级:
    1. `--workspace <ws_id>` 显式参数
    2. `persistence.get_agent_channel(sender_id)` 当前活跃频道
    
    Returns:
        (ws_id, error_msg) — ws_id 为 None 时表示未找到
    """
    ws_id = params.get("workspace", "") or persistence.get_agent_channel(sender_id) or ""
    if not ws_id:
        return (None, "❌ 无法确定工作区。请使用 --workspace <ws_id> 指定，或先加入一个工作区。")
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return (None, f"❌ 工作区 {ws_id} 不存在")
    return (ws_id, "")
```

### 1.2 _cmd_workspace_join()

```python
async def _cmd_workspace_join(sender_id: str, params: dict) -> str:
    """加入工作区。
    
    用法：!workspace_join [--workspace <ws_id>]
    权限：L2 member（全员可用）
    """
    ws_id, err = _resolve_workspace(sender_id, params)
    if err:
        return err
    
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区 {ws_id} 不存在"
    
    if sender_id in ws.members:
        return f"⏳ 你已在工作区 {ws.name} 中"
    
    if ws_mod.add_member(ws_id, sender_id):
        # 切换活跃频道到工作区
        persistence.set_agent_channel(sender_id, ws_id)
        persistence.save_agent_channels(config.DATA_DIR)
        
        # 广播加入通知
        sender_name = auth.get_agent_name(sender_id, sender_id[:12])
        await _broadcast_to_channel(ws_id, {
            "type": "broadcast", "channel": ws_id,
            "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
            "content": f"👋 {sender_name} 加入了工作区",
            "ts": time.time(),
        })
        _audit_logger.log(f"[R81] !workspace_join by {sender_id} → {ws_id}")
        return f"✅ 已加入工作区 {ws.name}"
    
    return f"❌ 加入工作区 {ws.name} 失败"
```

### 1.3 _cmd_workspace_leave()

```python
async def _cmd_workspace_leave(sender_id: str, params: dict) -> str:
    """退出工作区。
    
    用法：!workspace_leave [--workspace <ws_id>]
    权限：L2 member（全员可用）
    限制：Owner 不能退出自己的工作区
    """
    ws_id, err = _resolve_workspace(sender_id, params)
    if err:
        return err
    
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区 {ws_id} 不存在"
    
    if sender_id not in ws.members:
        return f"⏳ 你不在工作区 {ws.name} 中"
    
    # Owner 守卫
    if sender_id == ws.owner_id:
        return "❌ 你是该工作区的所有者，不能退出。如需关闭请使用 !close_workspace"
    
    if ws_mod.remove_member(ws_id, sender_id):
        sender_name = auth.get_agent_name(sender_id, sender_id[:12])
        await _broadcast_to_channel(ws_id, {
            "type": "broadcast", "channel": ws_id,
            "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
            "content": f"👋 {sender_name} 退出了工作区",
            "ts": time.time(),
        })
        _audit_logger.log(f"[R81] !workspace_leave by {sender_id} → {ws_id}")
        return f"✅ 已退出工作区 {ws.name}"
    
    return f"❌ 退出工作区 {ws.name} 失败"
```

### 1.4 _cmd_workspace_add()

```python
async def _cmd_workspace_add(sender_id: str, params: dict) -> str:
    """邀请他人加入工作区。
    
    用法：!workspace_add <agent_id> [--workspace <ws_id>]
    权限：L2 member（sender 必须在目标工作区中）
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!workspace_add <agent_id> [--workspace <ws_id>]"
    
    target_id = positional[0]
    ws_id, err = _resolve_workspace(sender_id, params)
    if err:
        return err
    
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区 {ws_id} 不存在"
    
    # sender 必须在目标工作区中
    if sender_id not in ws.members:
        return f"❌ 你不在工作区 {ws.name} 中，无法邀请他人"
    
    if target_id in ws.members:
        return f"⏳ {target_id[:12]}... 已在工作区中"
    
    if ws_mod.add_member(ws_id, target_id):
        sender_name = auth.get_agent_name(sender_id, sender_id[:12])
        await _broadcast_to_channel(ws_id, {
            "type": "broadcast", "channel": ws_id,
            "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
            "content": f"📩 {sender_name} 邀请了 {target_id[:12]}... 加入工作区",
            "ts": time.time(),
        })
        _audit_logger.log(f"[R81] !workspace_add by {sender_id} → {ws_id} target={target_id}")
        return f"✅ {target_id[:12]}... 已加入工作区 {ws.name}"
    
    return f"❌ 邀请失败"
```

### 1.5 _cmd_workspace_remove() — 仅 owner

```python
async def _cmd_workspace_remove(sender_id: str, params: dict) -> str:
    """从工作区移除成员（仅 owner）。
    
    用法：!workspace_remove <agent_id> [--workspace <ws_id>]
    权限：L2 member（但仅 ws.owner_id 可执行）
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!workspace_remove <agent_id> [--workspace <ws_id>]"
    
    target_id = positional[0]
    ws_id, err = _resolve_workspace(sender_id, params)
    if err:
        return err
    
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区 {ws_id} 不存在"
    
    # Owner 检查（硬性守卫）
    if sender_id != ws.owner_id:
        return "❌ 权限不足：仅工作区所有者可移除成员"
    
    if target_id == ws.owner_id:
        return "❌ 不能移除工作区所有者"
    
    if target_id not in ws.members:
        return f"⏳ {target_id[:12]}... 不在工作区中"
    
    if ws_mod.remove_member(ws_id, target_id):
        sender_name = auth.get_agent_name(sender_id, sender_id[:12])
        target_name = auth.get_agent_name(target_id, target_id[:12])
        await _broadcast_to_channel(ws_id, {
            "type": "broadcast", "channel": ws_id,
            "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
            "content": f"🚫 {sender_name} 移除了 {target_name}",
            "ts": time.time(),
        })
        _audit_logger.log(f"[R81] !workspace_remove by {sender_id} → {ws_id} target={target_id}")
        return f"✅ 已从工作区移除 {target_id[:12]}..."
    
    return f"❌ 移除失败"
```

### 1.6 命令注册

在 `_ADMIN_COMMANDS` 字典中新增 5 条注册（L4405 区域末尾）：

```python
"workspace_join": {
    "handler": _cmd_workspace_join, "min_role": 2,
    "usage": "!workspace_join [--workspace <ws_id>]",
},
"workspace_leave": {
    "handler": _cmd_workspace_leave, "min_role": 2,
    "usage": "!workspace_leave [--workspace <ws_id>]",
},
"workspace_add": {
    "handler": _cmd_workspace_add, "min_role": 2,
    "usage": "!workspace_add <agent_id> [--workspace <ws_id>]",
},
"workspace_remove": {
    "handler": _cmd_workspace_remove, "min_role": 2,
    "usage": "!workspace_remove <agent_id> [--workspace <ws_id>]",
},
"workspace_list_members": {
    "handler": _cmd_workspace_list_members, "min_role": 2,
    "usage": "!workspace_list_members [--workspace <ws_id>]",
},
```

---

## 2. 方向 B：自动化成员补充

### 2.1 点名 ACK 后自动加入工作区

**入口位置：** `_cmd_rollcall` / `_cmd_rollcall_role` 的 ACK 响应处理部分。

点名流程中，bot 通过 `!ack` 命令或自动 ACK 机制响应。在其响应处理中追加自动加入逻辑：

```python
# 在点名 ACK 处理函数的末尾追加（约 L3400-3500 区域）

# ── R81 B1: ACK 后自动加入工作区 ──
try:
    # 从当前活跃频道推断工作区
    ack_ch = persistence.get_agent_channel(sender_id) or ""
    if ack_ch and ack_ch.startswith(p.WORKSPACE_ID_PREFIX):
        ack_ws = ws_mod.get_workspace(ack_ch)
        if ack_ws and sender_id not in ack_ws.members:
            ws_mod.add_member(ack_ch, sender_id)
            logger.info(
                "R81 B1: Auto-added %s to workspace %s on ACK",
                sender_id[:12], ack_ch[:20],
            )
except Exception as e:
    logger.warning("R81 B1: Auto-add on ACK failed: %s", e)
```

### 2.2 pipeline_start 成员不足时 inbox 邀请

**入口位置：** `_cmd_pipeline_start()` 末尾（约 L2140-2160 区域），创建工作区之后。

```python
# ── R81 B2: 成员不足检测 + inbox 邀请 ──
try:
    ws_obj = ws_mod.get_workspace(ws_id)
    if ws_obj and len(ws_obj.members) <= 2:
        # 从 WORK_PLAN frontmatter 或 step_config 获取缺失的角色
        step_config = _get_step_config(round_name)
        all_roles = set()
        for step_key, step_cfg in step_config.items():
            role = step_cfg.get("role", "")
            if role:
                all_roles.add(role)
        
        invited = []
        for role in all_roles:
            agents = _get_agents_by_role(role)
            for aid in agents:
                if aid not in ws_obj.members:
                    target_ch = persistence.get_inbox_channel(aid)
                    if target_ch:
                        await _broadcast_to_channel(target_ch, {
                            "type": "broadcast", "channel": target_ch,
                            "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
                            "content": (
                                f"📩 管线 {round_name} 已在工作区 {ws_obj.name} 启动。\n"
                                f"角色 {role} 需要你的参与。\n"
                                f"请使用 `!workspace_join --workspace {ws_id}` 加入。"
                            ),
                            "ts": time.time(),
                        })
                        invited.append(f"{role}({aid[:12]})")
        
        if invited:
            logger.info(
                "R81 B2: Invited %d agents to join %s: %s",
                len(invited), ws_id, ", ".join(invited),
            )
except Exception as e:
    logger.warning("R81 B2: Member invite failed: %s", e)
```

---

## 3. 方向 C：成员列表查询

### 3.1 返回格式

```python
async def _cmd_workspace_list_members(sender_id: str, params: dict) -> str:
    """列出工作区成员。
    
    用法：!workspace_list_members [--workspace <ws_id>]
    权限：L2 member
    """
    ws_id, err = _resolve_workspace(sender_id, params)
    if err:
        return err
    
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区 {ws_id} 不存在"
    
    lines = [f"📋 工作区: {ws.name} ({ws.id})"]
    lines.append(f"  状态: {ws.state.value}")
    lines.append(f"  成员: {len(ws.members)} 人")
    lines.append("")
    
    for member_id in sorted(ws.members):
        name = auth.get_agent_name(member_id, member_id[:12])
        # 角色标识
        if member_id == ws.owner_id:
            role_badge = "👑 owner"
        elif member_id in ws.admin_ids:
            role_badge = "🛡️ admin"
        else:
            role_badge = "👤 member"
        # 在线状态
        is_online = member_id in _connections and bool(_connections[member_id])
        status_dot = "🟢" if is_online else "⚪"
        
        lines.append(f"  {status_dot} {name} ({member_id[:12]}...) {role_badge}")
    
    return "\n".join(lines)
```

**输出示例：**

```
📋 工作区: R81-dev (ws:ws_f26e5-R81-dev)
  状态: active
  成员: 4 人

  🟢 需求分析师 (ws_f26e585...) 👑 owner
  🟢 架构师 (ws_3f7cdd7...) 👤 member
  ⚪ 开发工程师 (ws_0bb747d...) 👤 member
  🟢 审查工程师 (ws_fcf496c...) 👤 member
```

### 3.2 成员角色枚举逻辑

| 条件 | 角色标识 | 说明 |
|:-----|:--------|:------|
| `member_id == ws.owner_id` | 👑 owner | 工作区创建者，不可 leave |
| `member_id in ws.admin_ids` | 🛡️ admin | 工作区管理员（R6 体系） |
| 其他 | 👤 member | 普通成员 |

---

## 4. 方向 D：min_role 降级评估

### 4.1 评估标准

| 等级 | role_level() 值 | 对应角色 |
|:-----|:---------------|:---------|
| L4 | 4 | 全局管理员（global_admin） |
| L3 | 3 | 工作区管理员（workspace_admin） |
| L2 | 2 | 普通成员（member） |
| L1 | 1 | 观察者（observer） |

### 4.2 可安全降级到 min_role=2 的命令

| 命令 | 当前 min_role | 评估 | 理由 |
|:-----|:-------------:|:----|:------|
| `create_workspace` | 3 | ❌ **保留** | 创建工作区需要 L3+，避免 L2 成员创建过多工作区 |
| `close_workspace` | 3 | ❌ **保留** | 关闭工作区影响所有成员，需 L3+ |
| `list_workspaces` | 3 | ✅ **可降级到 2** | 仅查询，零风险 |
| `list_agents` | 3 | ✅ **可降级到 2** | 仅查询 agent 列表，零风险 |
| `agent_status` | 3 | ✅ **可降级到 2** | 仅查询单 agent 状态，零风险 |
| `audit_log` | 3 | ⚠️ **建议保留** | 审计日志含敏感操作记录，建议 L3+ |
| `list_workspace_admins` | 3 | ✅ **可降级到 2** | 仅查询管理员列表 |
| `task_create` | 3 | ❌ **保留** | 创建 task 影响管线流程 |
| `task_update` | 3 | ❌ **保留** | 更新 task 状态影响管线 |
| `task_list` | 3 | ✅ **可降级到 2** | 仅查询 task |
| `task_delete` | 3 | ❌ **保留** | 删除操作需审慎 |
| `pipeline_start` | 3 | ❌ **保留** | 启动管线影响整个工作区 |
| `pipeline_status` | 3 | ✅ **可降级到 2** | 仅查询管线状态 |
| `pipeline_block` | 3 | ⚠️ **建议保留** | 阻塞影响团队 |
| `pipeline_force_complete` | 4 | ❌ **保留** | 跳过验证仅限 L4 |
| `step_complete` | 3 | ❌ **保留** | 推进 step 影响管线顺序 |
| `step_force` | 3 | ❌ **保留** | 强制推进需验证身份 |
| `step_verify` | 3 | ✅ **可降级到 2** | 重新执行验证，无风险 |

### 4.3 降级汇总

| 等级 | 命令数 |
|:-----|:------|
| 可降级（✅ 无条件） | 6 个（list_workspaces, list_agents, agent_status, list_workspace_admins, task_list, pipeline_status, step_verify） |
| 建议保留（⚠️ 暂缓） | 2 个（audit_log, pipeline_block） |
| 必须保留（❌ 不可降） | 其余 10+ 个 |

### 4.4 实施建议

本轮不编码降级。如后续轮次实施，仅需改动 `_ADMIN_COMMANDS` 字典中对应命令的 `min_role` 值：

```python
# 示例：将 list_workspaces 从 L3 降级到 L2
"list_workspaces": {
    "handler": _cmd_list_workspaces, "min_role": 2,  # ← 3 → 2
    "workspace_scope": True,
},
```

---

## 5. 改动汇总

### 5.1 文件清单

仅 `server/handler.py`：

| # | 改动 | 行数 | 说明 |
|:-:|:------|:----:|:------|
| 1 | 新增 `_resolve_workspace()` 辅助函数 | ~12 | 活跃频道推断 |
| 2 | 新增 `_cmd_workspace_join()` | ~25 | 加入工作区 |
| 3 | 新增 `_cmd_workspace_leave()` | ~25 | 退出工作区（owner 守卫） |
| 4 | 新增 `_cmd_workspace_add()` | ~25 | 邀请他人 |
| 5 | 新增 `_cmd_workspace_remove()` | ~30 | 移除成员（仅 owner） |
| 6 | 新增 `_cmd_workspace_list_members()` | ~25 | 成员列表查询 |
| 7 | `_ADMIN_COMMANDS` 注册 5 条 | ~25 | min_role=2 |
| 8 | ACK 处理追加自动加入 | ~15 | 方向 B1 |
| 9 | pipeline_start 追加成员邀请 | ~15 | 方向 B2 |
| **合计** | | **~195 行净增** | |

### 5.2 无改动项

| 模块 | 原因 |
|:-----|:------|
| `server/workspace.py` | `add_member()` / `remove_member()` 已就绪，接口确认即可 |
| `server/auth.py` | 角色等级逻辑不变 |
| `shared/protocol.py` | 本轮不新增消息类型 |
| Bot 代码 | 新命令对 bot 透明 |
| 管线状态机 | 不改 _PIPELINE_STATE / _PIPELINE_CONFIG |

### 5.3 workspace.py 接口确认

| 函数 | 签名 | 已有 |
|:-----|:------|:----:|
| `add_member(ws_id, agent_id) → bool` | ✅ 已存在 L332 | ✅ |
| `remove_member(ws_id, agent_id) → bool` | ✅ 已存在 L341 | ✅ |
| `get_workspace(ws_id) → Workspace` | ✅ 已有 | ✅ |
| `Workspace.owner_id` | ✅ 已有 L182 | ✅ |
| `Workspace.members` | ✅ set[str], L185 | ✅ |
| `Workspace.admin_ids` | ✅ set[str], L186 | ✅ |

---

## 6. 兼容性分析

### 6.1 权限模型

| 命令 | min_role | owner 守卫 | 是否影响现有流程 |
|:-----|:--------:|:-----------|:----------------|
| `workspace_join` | 2 | — | ✅ 新增 |
| `workspace_leave` | 2 | `sender_id != ws.owner_id` | ✅ 新增 |
| `workspace_add` | 2 | — | ✅ 新增 |
| `workspace_remove` | 2 | `sender_id == ws.owner_id` | ✅ 新增 |
| `workspace_list_members` | 2 | — | ✅ 新增 |

### 6.2 现有流程影响

| 场景 | 改造前 | 改造后 | 兼容性 |
|:-----|:-------|:-------|:-------|
| 点名 ACK | 仅记录 ACK 状态 | ACK 后检查并自动加入工作区 | ✅ 零影响（非侵入追加） |
| `!pipeline_start` | 创建工作室 + 角色映射 | 追加成员不足检测 + inbox 邀请 | ✅ 零影响（追加 try/except） |
| 现有 `!create_workspace` | 不变 | 不变 | ✅ |
| 现有 41 个命令 | 不变 | 不变 | ✅ |
| 已有成员的 workspace | 不变 | 不变（新命令无读旧数据影响） | ✅ |

### 6.3 安全边界

| 场景 | 处理 | 防护 |
|:-----|:------|:------|
| 未认证 agent 执行命令 | `_check_command_permission()` 拒绝 | 已有框架 |
| Owner 执行 `leave` | 返回 "❌ 你是该工作区的所有者" | 硬性守卫 |
| 非 owner 执行 `remove` | 返回 "❌ 权限不足" | 硬性守卫 |
| Owner 被 `remove` | 返回 "❌ 不能移除工作区所有者" | 硬性守卫 |
| 邀请已存在成员 | 返回 "⏳ 已在工作区中" | 幂等 |
| 退出未加入的工作区 | 返回 "⏳ 你不在工作区中" | 幂等 |

---

## 7. 审计日志

所有 5 个新命令通过 `_audit_logger.log()` 记录操作记录：

| 命令 | 日志内容 | 审计格式 |
|:-----|:---------|:---------|
| `workspace_join` | `[R81] !workspace_join by {sender_id} → {ws_id}` | 含操作者 + 目标工作区 |
| `workspace_leave` | `[R81] !workspace_leave by {sender_id} → {ws_id}` | 含操作者 + 退出工作区 |
| `workspace_add` | `[R81] !workspace_add by {sender_id} → {ws_id} target={target_id}` | 含操作者 + 被邀请人 |
| `workspace_remove` | `[R81] !workspace_remove by {sender_id} → {ws_id} target={target_id}` | 含操作者 + 被移除人 |
| `workspace_list_members` | 不记录（仅查询，无副作用） | — |

现有 `_audit_logger.log()` 模式（参考 `_cmd_create_workspace` / `_cmd_close_workspace` 等）直接复用。

---

## 8. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-09 | 初稿 — R81 工作区成员自动化管理：5 个新命令 + 2 处自动补充 + 1 个查询 + min_role 降级评估 |
