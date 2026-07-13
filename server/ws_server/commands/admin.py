"""R100: admin domain commands — extracted from handler.py."""

from .. import state, command_utils
from server.common import auth, persistence
import time
from .. import workspace as ws_mod

async def _cmd_list_agents(sender_id: str, params: dict) -> str:
    """List approved agents with online status."""
    from ..main import _connections
    users = auth.get_users()
    online_ids = set(_connections.keys())
    role_filter = params.get("role", "").lower()
    lines = [f"📋 共 {len(users)} 个已认证 agent："]
    for aid, u in sorted(users.items()):
        role = u.get("role", "member")
        if role_filter and role != role_filter:
            continue
        name = u.get("name", aid[:12])
        status = "🟢" if aid in online_ids else "🟡"
        lines.append(f"  {status} {name} ({role})")
    return "\n".join(lines)



async def _cmd_agent_status(sender_id: str, params: dict) -> str:
    """Show detailed agent info."""
    from ..main import _connections
    target = params.get("_positional", [None])[0] or params.get("agent")
    if not target:
        return "❌ 用法: !agent_status <agent_id|agent_name>"
    users = auth.get_users()
    found_id = target if target in users else None
    if not found_id:
        for aid, u in users.items():
            if u.get("name") == target:
                found_id = aid
                break
    if not found_id:
        return f"❌ 未找到 agent: {target}"
    u = users[found_id]
    channel = "lobby"  # R82: active channel removed
    online = "🟢" if found_id in _connections else "🟡"
    ws_list = ws_mod.get_workspaces_for_agent(found_id)
    ws_names = ", ".join(w.id for w in ws_list) if ws_list else "无"
    return (f"🔍 {u.get('name', found_id)}：\n"
            f"  角色={u.get('role', 'member')}\n"
            f"  活跃频道={channel}\n"
            f"  所属工作室={ws_names}\n"
            f"  在线={online}")



async def _cmd_approve_ws_admin(sender_id: str, params: dict) -> str:
    """Approve workspace admin request. P4 only."""
    ws_id = params.get("workspace", "")
    agent = params.get("agent", "")
    if not ws_id or not agent:
        return "❌ 用法: !approve_ws_admin --workspace <ws_id> --agent <agent>"
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作室 {ws_id} 不存在"
    result = ws_mod.approve_admin_request(ws_id, agent)
    if result:
        return f"✅ {agent} 已升级为 {ws_id} 的工作室管理员。"
    return f"❌ 审批失败：{agent} 没有待审批的管理员申请。"



async def _cmd_reject_ws_admin(sender_id: str, params: dict) -> str:
    """Reject workspace admin request. P4 only."""
    ws_id = params.get("workspace", "")
    agent = params.get("agent", "")
    reason = params.get("reason", "未说明原因")
    if not ws_id or not agent:
        return "❌ 用法: !reject_ws_admin --workspace <ws_id> --agent <agent> --reason <text>"
    result = ws_mod.reject_admin_request(ws_id, agent)
    if result:
        return f"ℹ️ {agent} 的管理员申请已拒绝（原因：{reason}）。"
    return f"❌ 拒绝失败：{agent} 没有待审批的管理员申请。"



async def _cmd_list_pending(sender_id: str, params: dict) -> str:
    """List pending admin requests. P4 only."""
    pending = ws_mod.get_pending_requests()
    if not pending:
        return "📋 暂无待审批的管理员申请。"
    lines = ["📋 待审批的管理员申请："]
    for req in pending:
        ws_id = req.get("workspace_id", "?")
        agent = req.get("agent_id", "?")
        lines.append(f"  - {agent} → {ws_id}")
    return "\n".join(lines)



async def _cmd_audit_log(sender_id: str, params: dict) -> str:
    """Query audit log. P3 (own) / P4 (all)."""
    from ..main import _audit_logger
    limit_str = params.get("limit", "10")
    try:
        limit = int(limit_str)
    except (ValueError, TypeError):
        limit = 10
    if auth.is_global_admin(sender_id):
        entries = _audit_logger.query(tail=limit)
    else:
        all_entries = _audit_logger.query(tail=100)
        entries = [e for e in all_entries
                   if e.get("agent_id") == sender_id][:limit]
    if not entries:
        return "📋 暂无审计记录"
    lines = [f"📋 最近 {len(entries)} 条操作记录："]
    for i, e in enumerate(entries, 1):
        ts_str = time.strftime("%H:%M", time.localtime(e.get("ts", 0)))
        op = e.get("agent_id", "")[:12]
        action = e.get("command", e.get("action", "?"))
        result = e.get("result", "")
        lines.append(f"  {i}. [{ts_str}] {op} → {action} ({result})")
    return "\n".join(lines)



async def _cmd_list_workspace_admins(sender_id: str, params: dict) -> str:
    """List workspace admins. P3 (own) / P4 (all)."""
    ws_id = params.get("workspace", "")
    if ws_id:
        ws = ws_mod.get_workspace(ws_id)
        if not ws:
            return f"❌ 工作室 {ws_id} 不存在"
        workspaces = [ws]
    else:
        all_ws = ws_mod.get_all_workspaces()
        if auth.is_global_admin(sender_id):
            workspaces = all_ws
        else:
            workspaces = [w for w in all_ws
                          if sender_id in w.admin_ids or sender_id == w.owner_id]
    if not workspaces:
        return "📋 暂无工作室管理员"
    lines = ["📋 工作室管理员列表："]
    for w in workspaces:
        admins = list(w.admin_ids) if hasattr(w, 'admin_ids') else []
        owner = w.owner_id if hasattr(w, 'owner_id') else ""
        admin_names = ", ".join(admins) if admins else "无"
        lines.append(f"  {w.id}: 管理员={admin_names}, 所有者={owner}")
    return "\n".join(lines)


# ── R38: Task command handlers ─────────────────────────────────────


async def _cmd_revoke_api_key(sender_id: str, params: dict) -> str:
    """吊销指定的 agent 的 api_key 并断连。

    用法：!revoke_api_key <agent_id>
    权限：L4 global admin
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!revoke_api_key <agent_id>"

    target_id = positional[0]

    if not auth.revoke_api_key(target_id):
        return f"❌ agent {target_id[:16]}... 没有 api_key 或已被吊销"

    # 断连
    _force_disconnect_revoked_agent(target_id)

    return f"✅ 已吊销 {target_id[:16]}... 的 api_key 并强制断连"


# Register R81 + R86 admin commands (after function definitions)

