"""R100: workspace domain commands — extracted from handler.py."""

from .. import state, command_utils
from server.common import auth
from .. import workspace as ws_mod
from server.common import config
import time
import uuid
from .. import message_store as ms
import shared.protocol as p

async def _cmd_create_workspace(sender_id: str, params: dict) -> str:
    """Create a new workspace. P3+ (workspace admin / global admin).

    R37: After creation, auto-bind creator's active channel and send
    roll-call notification to workspace as background task.
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法: !create_workspace <name> --members <ids>"
    ws_name = positional[0]
    member_ids_raw = params.get("members", "")
    member_ids = [m.strip() for m in member_ids_raw.split(",") if m.strip()]
    ws_id = f"{p.WORKSPACE_ID_PREFIX}{sender_id[:8]}-{ws_name[:20]}"
    users = auth.get_users()
    sender_name = users.get(sender_id, {}).get("name", sender_id[:12])
    
    # ── R70 Fix: Resolve member names to agent IDs ──
    def _resolve_member(name_or_id: str) -> str | None:
        if name_or_id in users:
            return name_or_id
        for aid, u in users.items():
            if u.get("name") == name_or_id:
                return aid
        return None
    
    result = ws_mod.create_workspace(ws_id, ws_name, sender_id, sender_name)
    if not result:
        # R91 🅱️: 区分重名 vs 超限
        existing_ws = ws_mod.get_workspace(ws_id)
        if existing_ws:
            return (
                f"❌ 创建失败：工作室「{ws_name}」已存在。\n"
                f"  使用 --workspace-id {ws_id} 附着，或先 !close_workspace {ws_id}"
            )
        active_count = sum(
            1 for w in ws_mod.get_all_workspaces()
            if w.owner_id == sender_id and w.state == ws_mod.WorkspaceState.ACTIVE
        )
        max_ws = int(os.environ.get("MAX_ACTIVE_WORKSPACES", "3"))
        return (
            f"❌ 创建失败：管理者名下已有 {active_count}/{max_ws} 活跃工作室。\n"
            f"  请先 !close_workspace 关闭旧工作室后再创建"
        )
    for mid_raw in member_ids:
        resolved = _resolve_member(mid_raw)
        if resolved:
            ws_mod.add_member(ws_id, resolved)

    # R82: removed auto-bind active channel — bot uses inbox only
    member_names = []
    for mid in member_ids:
        name = users.get(mid, {}).get("name", "")
        if not name:
            role = users.get(mid, {}).get("role", "")
            name = role if role else mid[:12]
        member_names.append(name)
    member_list = ", ".join(member_names) if member_names else "无"

    # R82: Removed MSG_SET_ACTIVE_CHANNEL broadcast — tasks delivered via inbox
    return f"✅ 工作室 {ws_name} 已创建。成员: {member_list}"



    def _resolve_member(name_or_id: str) -> str | None:
        if name_or_id in users:
            return name_or_id
        for aid, u in users.items():
            if u.get("name") == name_or_id:
                return aid
        return None
    
    result = ws_mod.create_workspace(ws_id, ws_name, sender_id, sender_name)
    if not result:
        # R91 🅱️: 区分重名 vs 超限
        existing_ws = ws_mod.get_workspace(ws_id)
        if existing_ws:
            return (
                f"❌ 创建失败：工作室「{ws_name}」已存在。\n"
                f"  使用 --workspace-id {ws_id} 附着，或先 !close_workspace {ws_id}"
            )
        active_count = sum(
            1 for w in ws_mod.get_all_workspaces()
            if w.owner_id == sender_id and w.state == ws_mod.WorkspaceState.ACTIVE
        )
        max_ws = int(os.environ.get("MAX_ACTIVE_WORKSPACES", "3"))
        return (
            f"❌ 创建失败：管理者名下已有 {active_count}/{max_ws} 活跃工作室。\n"
            f"  请先 !close_workspace 关闭旧工作室后再创建"
        )
    for mid_raw in member_ids:
        resolved = _resolve_member(mid_raw)
        if resolved:
            ws_mod.add_member(ws_id, resolved)

    # R82: removed auto-bind active channel — bot uses inbox only
    member_names = []
    for mid in member_ids:
        name = users.get(mid, {}).get("name", "")
        if not name:
            role = users.get(mid, {}).get("role", "")
            name = role if role else mid[:12]
        member_names.append(name)
    member_list = ", ".join(member_names) if member_names else "无"

    # R82: Removed MSG_SET_ACTIVE_CHANNEL broadcast — tasks delivered via inbox
    return f"✅ 工作室 {ws_name} 已创建。成员: {member_list}"



async def _cmd_close_workspace(sender_id: str, params: dict) -> str:
    """Close a workspace. P3+ (P3: own managed only)."""
    ws_id = params.get("_positional", [None])[0] or params.get("workspace")
    if not ws_id:
        return "❌ 用法: !close_workspace <ws_id> [--reason <text>]"
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作室 {ws_id} 不存在"
    if not auth.is_global_admin(sender_id):
        if not (sender_id in ws.admin_ids or sender_id == ws.owner_id):
            return "❌ 权限不足：你不是该工作室的管理员"
    reason = params.get("reason", "管理操作")
    ws_mod.start_closing(ws_id)
    timeout_tracker.reset()

    # R76 B2: check if no active workspace remains → trigger archive state
    try:
        active_ws = [w for w in ws_mod.get_all_workspaces()
                     if w.state == ws_mod.WorkspaceState.ACTIVE]
        if not active_ws:
            from . import web_viewer as wv
            start_ts = ws.created_at if isinstance(ws.created_at, (int, float)) else time.time()
            wv.set_archive_state(
                ws_id=ws.id,
                ws_name=ws.name,
                start_ts=start_ts,
            )
            logger.info("R76: Archive triggered — last workspace '%s' closed", ws.name)
    except Exception as e:
        logger.warning("R76: Archive state write failed (non-fatal): %s", e)

    # ── R79+: Notify all workspace members that the round is over ──
    # ── R98: 合并 ws.members + PipelineContext 参与者 ──
    try:
        _round_name = ws.name.split('-')[0] if '-' in ws.name else ws.name
        _end_msg = (
            f"📋 {_round_name} 轮的开发工作已经结束，更新记忆，话题归档。\n\n"
            f"工作室「{ws.name}」已关闭。下一轮开发将另启新工作室。"
        )

        # R98: 构建通知目标集合（member + pipeline 参与者，去重）
        _notify_ids = set(ws.members)
        _mgr = _ensure_pipeline_manager()
        _ctx = _mgr.get_context(_round_name)
        if _ctx and isinstance(_ctx, dict):
            for _step in _ctx.get("steps", {}).values():
                if isinstance(_step, dict) and _step.get("agent_id"):
                    _notify_ids.add(_step["agent_id"])
        _notify_ids.discard(sender_id)

        for _member_id in list(_notify_ids):
            _inbox_ch = f"_inbox:{_member_id}"
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent=state.SYSTEM_AGENT_ID, from_name="系统",
                content=_end_msg, ts=time.time(),
                data_dir=config.DATA_DIR, channel=_inbox_ch,
            )
            _payload = json.dumps({
                "type": "broadcast", "channel": _inbox_ch,
                "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
                "content": _end_msg, "ts": time.time(),
            })
            for _conn in list(_connections.get(_member_id, set())):
                try:
                    if hasattr(_conn, "send_str"):
                        await _conn.send_str(_payload)
                    elif hasattr(_conn, "send"):
                        await _conn.send(_payload)
                except Exception:
                    pass
        _member_count = len(_notify_ids)
        if _member_count > 0:
            logger.info("Round-end notifications sent to %d recipient(s) for %s",
                        _member_count, _round_name)
    except Exception as e:
        logger.warning("Round-end notification failed (non-fatal): %s", e)

    return f"✅ 工作室 {ws.name} 已归档。（原因：{reason}）"



async def _cmd_list_workspaces(sender_id: str, params: dict) -> str:
    """List workspaces. P3 (own) / P4 (all)."""
    all_ws = ws_mod.get_all_workspaces()
    if auth.is_global_admin(sender_id):
        visible = all_ws
    else:
        visible = [w for w in all_ws
                   if sender_id in w.admin_ids or sender_id == w.owner_id]
    if not visible:
        return "📋 暂无工作室"
    lines = ["📋 工作室列表："]
    for w in visible:
        status_icon = {"active": "🟢", "closing": "🟡", "archived": "⚫"}.get(
            w.state.value if hasattr(w.state, 'value') else str(w.state), "⚪")

    # ── R66 B4: Display step outputs in status ──
    step_outputs = pstate.get("step_outputs", {})
    if step_outputs:
        lines.append("  📦 Step 产出:")
        for out_step_key, out_info in sorted(step_outputs.items(), key=lambda x: _step_sort_key(x[0])):
            sha = out_info.get("sha", "")[:7]
            title = out_info.get("title", out_step_key)
            summary = out_info.get("summary", "")
            url = out_info.get("artifact_url", "")
            line = f"    {out_step_key} {title} — {sha}"
            if summary:
                line += f"\n      └ 💡 {summary[:80]}"
            if url:
                line += f"\n      └ 🔗 {url}"
            lines.append(line)

        lines.append(f"  {status_icon} {w.id} \"{w.name}\" ({len(w.members)}人)")
    return "\n".join(lines)



async def _cmd_workspace_join(sender_id: str, params: dict) -> str:
    """加入工作区。

    用法：!workspace_join [--workspace <ws_id>]
    权限：L2 member（全员可用）
    """
    ws_id, err = command_utils._resolve_workspace(sender_id, params)
    if err:
        return err

    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区 {ws_id} 不存在"

    if sender_id in ws.members:
        return f"⏳ 你已在工作区 {ws.name} 中"

    if ws_mod.add_member(ws_id, sender_id):
        # 切换活跃频道到工作区
        # R82: removed set_agent_channel
        # 广播加入通知
        sender_name = auth.get_agent_name(sender_id, sender_id[:12])
        await command_utils._broadcast_to_channel(ws_id, {
            "type": "broadcast", "channel": ws_id,
            "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"👋 {sender_name} 加入了工作区",
            "ts": time.time(),
        })
        return f"✅ 已加入工作区 {ws.name}"

    return f"❌ 加入工作区 {ws.name} 失败"



async def _cmd_workspace_leave(sender_id: str, params: dict) -> str:
    """退出工作区。

    用法：!workspace_leave [--workspace <ws_id>]
    权限：L2 member（全员可用）
    限制：Owner 不能退出自己的工作区
    """
    ws_id, err = command_utils._resolve_workspace(sender_id, params)
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
        await command_utils._broadcast_to_channel(ws_id, {
            "type": "broadcast", "channel": ws_id,
            "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"👋 {sender_name} 退出了工作区",
            "ts": time.time(),
        })
        return f"✅ 已退出工作区 {ws.name}"

    return f"❌ 退出工作区 {ws.name} 失败"



async def _cmd_workspace_add(sender_id: str, params: dict) -> str:
    """邀请他人加入工作区。

    用法：!workspace_add <agent_id> [--workspace <ws_id>]
    权限：L2 member（sender 必须在目标工作区中）
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!workspace_add <agent_id> [--workspace <ws_id>]"

    target_id = positional[0]
    ws_id, err = command_utils._resolve_workspace(sender_id, params)
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
        await command_utils._broadcast_to_channel(ws_id, {
            "type": "broadcast", "channel": ws_id,
            "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"📩 {sender_name} 邀请了 {target_id[:12]}... 加入工作区",
            "ts": time.time(),
        })
        return f"✅ {target_id[:12]}... 已加入工作区 {ws.name}"

    return f"❌ 邀请失败"



async def _cmd_workspace_remove(sender_id: str, params: dict) -> str:
    """从工作区移除成员（仅 owner）。

    用法：!workspace_remove <agent_id> [--workspace <ws_id>]
    权限：L2 member（但仅 ws.owner_id 可执行）
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!workspace_remove <agent_id> [--workspace <ws_id>]"

    target_id = positional[0]
    ws_id, err = command_utils._resolve_workspace(sender_id, params)
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
        await command_utils._broadcast_to_channel(ws_id, {
            "type": "broadcast", "channel": ws_id,
            "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"🚫 {sender_name} 移除了 {target_name}",
            "ts": time.time(),
        })
        return f"✅ 已从工作区移除 {target_id[:12]}..."

    return f"❌ 移除失败"



async def _cmd_workspace_list_members(sender_id: str, params: dict) -> str:
    """列出工作区成员。

    用法：!workspace_list_members [--workspace <ws_id>]
    权限：L2 member
    """
    ws_id, err = command_utils._resolve_workspace(sender_id, params)
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


# ── R86 C1: revoke_api_key admin command ─────────────────────────



async def _cmd_workspace_reset(sender_id: str, params: dict) -> str:
    """R82: 重置工作室：关闭 + 清理管线状态。"""
    ws_id_param = params.get("_positional", [None])[0] or params.get("workspace", "")
    if not ws_id_param:
        return "❌ 请使用 --workspace <ws_id> 指定工作区"
    ws_obj = ws_mod.get_workspace(ws_id_param)
    if not ws_obj:
        return "❌ 未找到活跃工作室"
    ws_id = ws_obj.id
    ws_name = ws_obj.name
    close_result = await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})
    # R82: removed _broadcast_active_channel
    for pid, pst in list(state._PIPELINE_STATE.items()):
        if pst.get("ws_id") == ws_id:
            state._PIPELINE_STATE[pid]["active"] = False
    return f"✅ 工作室「{ws_name}」({ws_id[:12]}) 已重置 — 归档 + 回大厅 + 管线清理完成"


# ── R50: Step handoff command ──────────────────────────────────────



