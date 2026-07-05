"""WebSocket handler and broadcast logic — admin-relay mode + channel routing."""
import asyncio
import os
import json
import logging
import re
import time
import uuid

from . import agent_card as ac_mod  # R67: unified Agent Card interface
from . import auth, config, persistence
from . import message_store as ms
from . import workspace as ws_mod
from .audit import AuditLogger
from .web_viewer import write_chat_log
from . import task_store as ts
from . import timeout_tracker  # R63 Phase 1: Step countdown
from . import pipeline_sync as pps  # R65: Pipeline git sync
import shared.protocol as p

logger = logging.getLogger("ws-bridge")

_connections: dict[str, set] = {}

# P6: message send stats
_send_stats: dict = {"total": 0, "total_latency": 0.0}

# R35: Audit logger for admin commands
_audit_logger = AuditLogger(config.DATA_DIR)

_SILENT_PREFIXES = (
    "Operation interrupted",
    "Gateway is shutting down",
    "Gateway shut",
    "⚡ Interrupting",
    "⚠️ Gateway",
    "⏳ Gateway",
    "🤐",
)

# R11 P1.1: Delivery status per message per agent
_delivery_status: dict[str, dict[str, str]] = {}
# R11 P1.2: Offline push queue
_offline_push_queue: dict[str, list[dict]] = {}

# ── R42: Pipeline state ──────────────────────────────────────────
_PIPELINE_STATE: dict[str, dict] = {}  # round_name -> {active, current_step, ws_id, ...}

# ── R62: Pipeline config (read-only, separate from runtime state) ──
_PIPELINE_CONFIG: dict[str, dict] = {}  # round_name -> read-only config from WORK_PLAN

# ── R63 Phase 2-4: Feature toggle switches (env overridable) ─────
_ENABLE_R63_TIMEOUT: bool = os.environ.get("R63_ENABLE_TIMEOUT", "1") == "1"
_ENABLE_R63_AGENT_MAP: bool = os.environ.get("R63_ENABLE_AGENT_MAP", "1") == "1"
_ENABLE_R63_ACK: bool = os.environ.get("R63_ENABLE_ACK", "1") == "1"
_ROLE_AGENT_MAP: dict[str, list[str]] = {}    # role -> [agent_id, ...] (Phase 3)
_step_ack_states: dict[str, dict] = {}          # "{round}/{step}" -> state info (Phase 4)
# ── R63 Phase 5: End ──

# ── R65: Git pipeline sync state ───────────────────────────────
_GIT_SYNC_TASK: asyncio.Task | None = None

_LOBBY_PAUSED: bool = False
_LOBBY_PAUSED_ROUND: str = ""

# ── R55 A: Step advance 2s serialization buffer ────────────────
_step_advance_buffer: dict[str, float] = {}

# ── R57 A: Rollcall ACK events for 30s rollcall timeout ──────
_r57_rollcall_events: dict[str, asyncio.Event] = {}

# ── R43: Watchdog state ─────────────────────────────────────
_watchdog_started: bool = False
_watchdog_task: asyncio.Task | None = None
_watchdog_alerts: dict[str, float] = {}  # "{round}/{step}" → last_alert_ts

_offline_timers: dict[str, asyncio.Task] = {}

# R11 P1.3: Expose connections for web status API
def get_connections() -> dict[str, set]:
    return _connections

def get_delivery_status(msg_id: str) -> dict[str, str]:
    return _delivery_status.get(msg_id, {})


# ── R12 P0.3: Task ack tracking ────────────────────────────────────────
_task_ack_timers: dict[str, asyncio.Task] = {}

# ── R12 P1.1: Rate limiting ──────────────────────────────────────────────
_rate_limits: dict[str, dict[str, list[float]]] = {}
RATE_LIMIT_WINDOW = 3    # Max messages
RATE_LIMIT_SECONDS = 10  # Per this many seconds

# ── R12 P1.2: Duplicate content tracking ────────────────────────────────
_last_message: dict[str, dict] = {}

# ── R24: Lobby message prefix constants ─────────────────────────────
PREFIX_ANNOUNCE = "📢"
PREFIX_CHECKIN = "📋"
PREFIX_HELP = "🆘"

# ── R24: Lobby-specific rate limiter ─────────────────────────────────
_lobby_rate_limits: dict[str, list[float]] = {}
LOBBY_RATE_WINDOW_P1P2 = 2
LOBBY_RATE_WINDOW_P3 = 5
LOBBY_RATE_SECONDS = 60

# ── R53: Channel switch ACK state (replaces R37 rollcall) ────────
_channel_ack_state: dict[str, dict] = {}
# ws_id → {
#   "ack_task_id": str,           # per-broadcast unique ID
#   "online_members": set[str],   # members that were online at send time
#   "acked_members": dict[str,float],  # {agent_id: ack_timestamp}
#   "timer": asyncio.Task | None  # 30s timeout task
#   "callback": callable | None   # called on completion/partial
# }


async def _send(ws, data: dict) -> None:
    """Send JSON to a WebSocket (compatible with both websockets & aiohttp)."""
    if hasattr(ws, "send_json"):
        await ws.send_json(data)
    elif hasattr(ws, "send_str"):
        await ws.send_str(json.dumps(data))
    elif hasattr(ws, "send"):
        await ws.send(json.dumps(data))


# ── R29: Online member list builder ───────────────────────────────
def _build_online_list(users: dict) -> str:
    """Build a comma-separated online member list with admin annotation.
    Uses _connections (global) to determine who is online."""
    online_ids = set(_connections.keys())
    online_users = [(aid, users.get(aid, {})) for aid in online_ids if aid in users]
    admins = [(aid, u) for aid, u in online_users if u.get("role") == "admin"]
    members = [(aid, u) for aid, u in online_users if u.get("role") != "admin"]
    parts = []
    for aid, u in admins:
        name = u.get("name", aid[:12])
        parts.append(f"{name}(管理员)")
    for aid, u in members:
        name = u.get("name", aid[:12])
        parts.append(name)
    return "、".join(parts) if parts else "无"


async def handle_auth(ws, msg: dict) -> str | None:
    """Authenticate a connecting agent. Returns agent_id on success."""
    agent_id = msg.get("agent_id", "").strip()
    app_id = msg.get("app_id", "").strip()
    code = msg.get("code", "").strip()
    last_seen_ts = msg.get("last_seen_ts", 0)

    if not agent_id or not app_id:
        await _send(ws, {"type": "auth_error", "error": "Missing agent_id or app_id"})
        return None

    if auth.is_approved(agent_id):
        role = auth.get_users()[agent_id].get("role", "member")
        # R22: attach active channel for ALL roles (default lobby)
        response = {
            "type": "auth_ok",
            "agent_id": agent_id,
            "role": role,
            p.FIELD_ACTIVE_CHANNEL: persistence.get_agent_channel(agent_id) or p.LOBBY,
        }
        await _send(ws, response)
        active_ch = response[p.FIELD_ACTIVE_CHANNEL]
        ch_info = f" channel={active_ch}" if role == "admin" else ""
        logger.info("Agent %s authenticated (role=%s)%s", agent_id[:20], role, ch_info)
        # Offline catchup
        if last_seen_ts > 0:
            await _push_offline(ws, last_seen_ts)
        # R11 P1.2: After authentication, check offline push queue
        pending = _offline_push_queue.pop(agent_id, [])
        if pending:
            _offline_timers.pop(agent_id, None)  # Cancel timer
            all_sent = True
            for item in pending:
                try:
                    if hasattr(ws, "send_str"):
                        await ws.send_str(json.dumps(item))
                    elif hasattr(ws, "send"):
                        await ws.send(json.dumps(item))
                except Exception:
                    all_sent = False
            if all_sent:
                logger.info("Pushed %d offline-queued msgs to %s", len(pending), agent_id[:12])
        return agent_id

    if code:
        result = auth.approve(code)
        if result["type"] == "approve_ok":
            await _send(ws, {"type": "auth_ok", "agent_id": agent_id, "role": "member", p.FIELD_ACTIVE_CHANNEL: p.LOBBY})
            # R36: Welcome on code auto-approval (纯文本, write_chat_log)
            _agent_name_b4 = auth.get_users().get(agent_id, {}).get("name", agent_id[:12])
            write_chat_log("系统", f"[核准] 验证码核准 — 欢迎 {_agent_name_b4}")
            logger.info("Agent %s auto-approved via code", agent_id[:20])
            if last_seen_ts > 0:
                await _push_offline(ws, last_seen_ts)
            return agent_id
        else:
            await _send(ws, result)
            return None

    # R23: unregistered agent → registration channel (not pure pairing_code)
    new_code = auth.generate_code()
    auth.create_pairing_code(agent_id, app_id, msg.get("name", agent_id), new_code)
    persistence.save_pairing_codes(config.DATA_DIR)
    persistence.set_agent_channel(agent_id, p.REGISTRATION_CHANNEL)
    persistence.save_agent_channels(config.DATA_DIR)
    await _send(ws, {
        "type": "auth_ok",
        "agent_id": agent_id,
        "role": p.ROLE_UNREGISTERED,
        p.FIELD_ACTIVE_CHANNEL: p.REGISTRATION_CHANNEL,
        "pairing_code": new_code,
    })
    logger.info("Agent %s in registration channel (code=%s)", agent_id[:20], new_code)
    # R36 B-1: Welcome message to unregistered agent (纯文本, write_chat_log)
    _reg_name_b1 = msg.get("name", agent_id)
    write_chat_log("系统", f"[注册] 新代理 {_reg_name_b1}（{_get_agent_display(agent_id)}）已连接，配对码：{new_code}")
    # R36 B-2: Notify all online admins via _persist_admin_response
    _users_for_notify = auth.get_users()
    _admin_ids = {aid for aid, u in _users_for_notify.items() if u.get("role") == "admin"}
    _reg_name = msg.get("name", agent_id)
    _notify_content = f"新代理注册请求：{_reg_name}（{_get_agent_display(agent_id)}）配对码：{new_code} 使用 /approve 核准"
    for _admin_aid in _admin_ids:
        for _conn in list(_connections.get(_admin_aid, set())):
            try:
                await _persist_admin_response(_conn, "system", "系统", _notify_content)
            except Exception:
                pass
    return agent_id


async def _push_offline(ws, since_ts: float) -> None:
    """Push missed messages to a reconnecting agent."""
    try:
        offline = ms.get_messages_since(since_ts, config.DATA_DIR, limit=500)
    except Exception:
        logger.warning("Offline catchup query failed (maybe first run)")
        return
    if offline:
        await _send(ws, {
            "type": "offline_messages",
            "messages": offline,
            "count": len(offline),
        })
        logger.info("Pushed %d offline msgs to reconnecting agent", len(offline))


async def _flush_offline_push(agent_id: str) -> None:
    """R11 P1.2: Wait 3s for agent to come online, then flush (or discard)."""
    await asyncio.sleep(3)
    conns = _connections.get(agent_id, set())
    pending = _offline_push_queue.pop(agent_id, [])
    _offline_timers.pop(agent_id, None)
    if conns and pending:
        for conn in conns:
            for item in pending:
                try:
                    if hasattr(conn, "send_str"):
                        await conn.send_str(json.dumps(item))
                    elif hasattr(conn, "send"):
                        await conn.send(json.dumps(item))
                except Exception:
                    pass
        logger.info("Offline push: %d msgs delivered to %s after 3s", len(pending), agent_id[:12])
    elif pending:
        logger.info("Offline push: %d msgs for %s expired (still offline after 3s)", len(pending), agent_id[:12])


async def handle_approve(data: dict) -> dict:
    """Admin approves a pairing code."""
    code = data.get("code", "").strip()
    result = auth.approve(code, data.get("role", "member"))
    if result["type"] == "approve_ok":
        persistence.save_pairing_codes(config.DATA_DIR)
        persistence.save_approved_users(config.DATA_DIR)
        # R36 B-4: Admin approval confirmation notification (persisted for web viewer)
        _approved_id = result["agent_id"]
        _approved_name = auth.get_users().get(_approved_id, {}).get("name", _approved_id[:12])
        write_chat_log("系统",
            f"[核准] 管理员已核准代理 {_approved_name}（{_approved_id[:16]}）角色={data.get('role', 'member')}")
        logger.info("Approved agent %s (role=%s)", _approved_id[:20], data.get("role", "member"))
    return result


# ── R35: Admin command infrastructure ────────────────────────────


def _admin_msg(content: str) -> dict:
    """Build a response message for the _admin channel."""
    return {
        "type": "broadcast",
        "channel": p.ADMIN_CHANNEL,
        "from_name": "系统",
        "content": content,
        "ts": time.time(),
    }


async def _persist_admin_response(ws, sender_id: str, from_name: str, content: str) -> None:
    """Send admin response + persist to message store + chat log for web viewer."""
    msg = _admin_msg(content)
    await _send(ws, msg)
    try:
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent=sender_id, from_name=from_name,
            content=content, ts=time.time(),
            data_dir=config.DATA_DIR, channel=p.ADMIN_CHANNEL,
        )
    except Exception:
        pass
    write_chat_log(from_name, content, channel=p.ADMIN_CHANNEL)


async def _send_cmd_response(ws, sender_id: str, from_name: str, content: str, channel: str) -> None:
    """Send command response to the source channel (any channel, not just _admin).
    Used by R49 universal ! command routing."""
    msg = {
        "type": "broadcast",
        "channel": channel,
        "from_name": from_name,
        "from": from_name,
        "agent_id": "",
        "from_agent": "",
        "content": content,
    }
    await _send(ws, msg)
    try:
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent=sender_id, from_name=from_name,
            content=content, ts=time.time(),
            data_dir=config.DATA_DIR, channel=channel,
        )
    except Exception:
        pass
    write_chat_log(from_name, content, channel=channel)



def _parse_command(content: str) -> tuple[str | None, dict]:
    """Parse '!<command> [args...]' into (command_name, params dict)."""
    if not content.startswith("!"):
        return None, {}

    parts = content[1:].strip().split()
    if not parts:
        return None, {}

    cmd = parts[0].lower()
    params: dict = {"_raw": content}
    positional: list[str] = []
    i = 1
    while i < len(parts):
        token = parts[i]
        if token.startswith("--"):
            key = token[2:]
            i += 1
            if i < len(parts):
                val = parts[i]
                if (val.startswith('"') and val.endswith('"')) or \
                   (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                params[key] = val
            else:
                params[key] = ""
        else:
            positional.append(token)
        i += 1

    if positional:
        params["_positional"] = positional
    return cmd, params


def _is_any_workspace_admin(agent_id: str) -> bool:
    """Check if agent is a workspace admin of ANY workspace (P3 level)."""
    for ws in ws_mod.get_all_workspaces():
        if agent_id in ws.admin_ids or agent_id == ws.owner_id:
            return True
    return False


def _log_audit(
    agent_id: str, command: str, params: dict,
    result: str, detail: str = "",
) -> None:
    """Log an admin command execution to the audit logger."""
    _audit_logger.log(agent_id, command, params, result, detail)


def _check_command_permission(
    agent_id: str, cmd_name: str, cmd: dict, params: dict,
) -> tuple[bool, str]:
    """Check if agent has permission to run this command."""
    # P4 → always allowed
    if auth.is_global_admin(agent_id):
        return True, ""

    min_role = cmd.get("min_role", 4)
    ws_scope = cmd.get("workspace_scope", False)

    # ── R44 F-12: PM pipeline_start bypass ────────────────
    # Allow any authenticated member to trigger !pipeline_start
    # from the _admin channel. Only this one command is exempted.
    if cmd_name == "pipeline_start" and min_role <= 3:
        return True, ""

    # ── R55 A: step_complete auto-mode bypass ──────────────
    # Any workspace member can advance a pending step in auto mode.
    # The actual step-level validity + mode check happens inside
    # _cmd_step_complete, where we have the round context.
    if cmd_name == "step_complete" and min_role <= 1:
        return True, ""

    # P3: verify actual workspace admin before allowing ws_scope commands
    if min_role <= 3 and ws_scope:
        if _is_any_workspace_admin(agent_id) or auth.is_global_admin(agent_id):
            return True, ""
        return False, "权限不足：仅工作区管理员或超级管理员可执行"

    if min_role <= 3 and not ws_scope:
        if _is_any_workspace_admin(agent_id):
            return True, ""
        return False, "权限不足：仅工作区管理员或超级管理员可执行"

    return False, "权限不足：管理操作仅限管理员"


# ── R35: Admin command handlers ──────────────────────────────────


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
        return f"❌ 创建失败：{ws_name} 可能已存在，或管理员名下活跃工作区过多"
    for mid_raw in member_ids:
        resolved = _resolve_member(mid_raw)
        if resolved:
            ws_mod.add_member(ws_id, resolved)

    # Auto-bind creator's active channel to new workspace
    persistence.set_agent_channel(sender_id, ws_id)
    persistence.save_agent_channels(config.DATA_DIR)

    member_names = []
    for mid in member_ids:
        name = users.get(mid, {}).get("name", "")
        if not name:
            role = users.get(mid, {}).get("role", "")
            name = role if role else mid[:12]
        member_names.append(name)
    member_list = ", ".join(member_names) if member_names else "无"

    # R53: Broadcast MSG_SET_ACTIVE_CHANNEL with ACK (replaces R37 text rollcall)
    asyncio.create_task(_broadcast_active_channel(ws_id))

    return f"✅ 工作室 {ws_name} 已创建。成员: {member_list}（ACK 点名已发送）"


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
    ws_mod.force_close(ws_id)
    timeout_tracker.reset()
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


async def _cmd_list_agents(sender_id: str, params: dict) -> str:
    """List approved agents with online status."""
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
    channel = persistence.get_agent_channel(found_id) or "lobby"
    online = "🟢" if found_id in _connections else "🟡"
    ws_list = ws_mod.get_workspaces_for_agent(found_id)
    ws_names = ", ".join(w.id for w in ws_list) if ws_list else "无"
    return (f"🔍 {u.get('name', found_id)}：\n"
            f"  角色={u.get('role', 'member')}\n"
            f"  活跃频道={channel}\n"
            f"  所属工作室={ws_names}\n"
            f"  在线={online}")


async def _cmd_approve_pairing(sender_id: str, params: dict) -> str:
    """Approve a pairing code. P4 only."""
    code = params.get("_positional", [None])[0]
    if not code:
        return "❌ 用法: !approve_pairing <code> [--role <role>]"
    role = params.get("role", "member")
    result = auth.approve(code, role)
    if result["type"] == "approve_ok":
        persistence.save_pairing_codes(config.DATA_DIR)
        persistence.save_approved_users(config.DATA_DIR)
        return f"✅ 配对码 {code} 已确认，{result['agent_id'][:12]} 已获得 {role} 角色。"
    return f"❌ {result.get('error', '审批失败')}"


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

async def _cmd_task_create(sender_id: str, params: dict) -> str:
    """Create a new task in SUBMITTED state.
    Usage: !task_create --context <R{N}> --name <step> [--role <role>]"""
    context_id = params.get("context", "")
    name = params.get("name", "")
    if not context_id or not name:
        return "❌ 用法：!task_create --context <R{N}> --name <step> [--role <role>]"
    assigned_role = params.get("role", "")
    task = ts.create_task(
        context_id=context_id, name=name,
        assigned_role=assigned_role,
        created_by=sender_id,
        data_dir=config.DATA_DIR,
    )
    # R41 C: Broadcast task_notify on creation
    asyncio.create_task(_broadcast_task_notify(task, f"{task['state']} → {task['state']}"))
    return (f"✅ Task 已创建：{task['name']} ({task['state']})\n"
            f"  ID: {task['id']}\n"
            f"  Context: {task['context_id']}\n"
            f"  Role: {task.get('assigned_role', '未指定')}")


async def _cmd_task_update(sender_id: str, params: dict) -> str:
    """Update a task's state.
    Usage: !task_update <task_id> --state <new_state> [--output <path>]"""
    positional = params.get("_positional", [])
    task_id = params.get("_task_id", positional[0] if positional else "")
    new_state = params.get("state", "")
    if not task_id or not new_state:
        return "❌ 用法：!task_update <task_id> --state <new_state> [--output <path>]"
    task = ts.get_task(task_id, config.DATA_DIR)
    if not task:
        return f"❌ Task {task_id[:12]} 不存在"
    # Permission: assigned_role match or global admin bypass
    if task.get("assigned_role"):
        users = auth.get_users()
        sender_info = users.get(sender_id, {})
        if sender_info.get("role") != "admin":
            if task["assigned_role"] not in (sender_id, sender_info.get("name", "")):
                return f"❌ 权限不足：Task 分配给 {task['assigned_role']}，你不可更新"
    try:
        current = p.TaskState(task["state"])
        target = p.TaskState(new_state)
    except ValueError:
        valid = [s.value for s in p.TaskState]
        return f"❌ 无效状态：{new_state}。有效值：{', '.join(valid)}"
    allowed = p.TASK_VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        return f"❌ 不允许的转换：{current.value} → {target.value}"
    # Reject ceiling check
    if target == p.TaskState.INPUT_REQUIRED:
        ts.increment_reject_count(task_id, config.DATA_DIR)
        task_d = ts.get_task(task_id, config.DATA_DIR)
        if task_d["reject_count"] >= p.TASK_REJECT_CEILING:
            ts.update_state(task_id, p.TaskState.FAILED.value, config.DATA_DIR)
            task_d = ts.get_task(task_id, config.DATA_DIR)
            return (f"❌ 审查已达上限 ({p.TASK_REJECT_CEILING}次)，已锁定 FAILED\n"
                    f"  {task_d['name']}: {task_d['state']} (rejects: {task_d['reject_count']})")
    ts.update_state(task_id, new_state, config.DATA_DIR)
    output_ref = params.get("output", "")
    if output_ref:
        ts.add_output_ref(task_id, output_ref, config.DATA_DIR)
    task = ts.get_task(task_id, config.DATA_DIR)
    # R41 C: Broadcast task_notify on update
    asyncio.create_task(_broadcast_task_notify(task,
        f"{task['state']} → {new_state}"))
    refs = task.get("output_refs", [])
    refs_str = f", 产出: {', '.join(refs)}" if refs else ""
    return f"✅ Task 已更新：{task['name']} → {task['state']}{refs_str}"


async def _cmd_task_query(sender_id: str, params: dict) -> str:
    """Query tasks by context or single task.
    Usage: !task_query --context <R{N}> | !task_query <task_id>"""
    positional = params.get("_positional", [])
    task_id = params.get("_task_id", positional[0] if positional else "")
    context_id = params.get("context", "")
    if task_id:
        task = ts.get_task(task_id, config.DATA_DIR)
        if not task:
            return f"❌ Task {task_id[:12]} 不存在"
        refs = task.get("output_refs", [])
        refs_str = f", 产出: {'; '.join(refs)}" if refs else ""
        return (f"📋 Task：{task['name']}\n"
                f"  State: {task['state']}\n"
                f"  Context: {task['context_id']}\n"
                f"  Assigned: {task.get('assigned_role', '未指定')}\n"
                f"  Rejects: {task.get('reject_count', 0)}{refs_str}\n"
                f"  Updated: {task['updated_at']}")
    elif context_id:
        tasks = ts.list_tasks_by_context(context_id, config.DATA_DIR)
        if not tasks:
            return f"📋 Context {context_id} 暂无 Task"
        lines = [f"📋 {context_id} 任务列表 ({len(tasks)}):"]
        for t in tasks:
            icon = p.TASK_STATE_ICONS.get(t["state"], "❓")
            lines.append(f"  {icon} {t['name']:20s} [{t['state']}]  {t['id'][:8]}")
        return "\n".join(lines)
    else:
        return "❌ 用法：!task_query <task_id> | !task_query --context <R{N}>"


async def _cmd_task_list(sender_id: str, params: dict) -> str:
    """List recent tasks across all contexts.
    Usage: !task_list [--limit <n>]"""
    limit = int(params.get("limit", "10"))
    tasks = ts.list_all_tasks(config.DATA_DIR, limit)
    if not tasks:
        return "📋 暂无 Task"
    lines = [f"📋 最近 {len(tasks)} 个 Task:"]
    for t in tasks:
        icon = p.TASK_STATE_ICONS.get(t["state"], "❓")
        lines.append(f"  {icon} [{t['context_id']}] {t['name']:20s} [{t['state']}]  {t['id'][:8]}")
    return "\n".join(lines)


async def _cmd_rollcall_role(sender_id: str, params: dict) -> str:
    """点名指定角色成员 — 使用 ACK 确认制代替文本「到」。
    Usage: !rollcall_role <role> [--context <msg>]
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法: !rollcall_role <role> [--context <msg>]"
    target_role = positional[0].lower()
    context_msg = params.get("context", "")
    sender_ch = persistence.get_agent_channel(sender_id) or p.LOBBY
    if not sender_ch or sender_ch == p.LOBBY:
        return "❌ 请先进入工作区频道"
    ws_obj = ws_mod.get_workspace(sender_ch)
    if not ws_obj:
        return f"❌ 工作区 {sender_ch} 不存在或已归档"
    users = auth.get_users()
    matched = [aid for aid in ws_obj.members
               if users.get(aid, {}).get("role", "member") == target_role]
    if not matched:
        return f"❌ 工作区中未找到角色为「{target_role}」的成员"
    sender_name = users.get(sender_id, {}).get("name", sender_id[:12])
    names = [users.get(aid, {}).get("name", aid[:12]) for aid in matched]
    names_str = ", ".join(names)
    suffix = f"（背景：{context_msg}）" if context_msg else ""
    # ★ R53: Use ACK-driven broadcast instead of text "回复到"
    _persist_broadcast(sender_ch, "系统", f"📋 {sender_name} 点名 {target_role} 成员{suffix}")
    ack_result = await _broadcast_active_channel(sender_ch)
    return f"✅ 已点名 {target_role}：{names_str}（{ack_result['online_count']} 人在线，等待 ACK 确认）"


async def _cmd_rollcall_next(sender_id: str, params: dict) -> str:
    """点名下一环节负责人 — 使用 ACK 确认制代替文本「到」。
    Usage: !rollcall_next <role> --context <摘要>
    
    不再发送「请回复到开始」文本消息。
    改为通过 _broadcast_active_channel(ws_id) 启动 ACK 等待。
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法: !rollcall_next <role> --context <摘要>"
    target_role = positional[0].lower()
    context_summary = params.get("context", "")
    if not context_summary:
        return "❌ 请提供 --context <摘要>"
    sender_ch = persistence.get_agent_channel(sender_id) or p.LOBBY
    if not sender_ch or sender_ch == p.LOBBY:
        return "❌ 请先进入工作区频道"
    ws_obj = ws_mod.get_workspace(sender_ch)
    if not ws_obj:
        return f"❌ 工作区 {sender_ch} 不存在或已归档"
    users = auth.get_users()
    matched = [aid for aid in ws_obj.members
               if users.get(aid, {}).get("role", "member") == target_role]
    if not matched:
        return f"❌ 工作区中未找到角色为「{target_role}」的成员"
    names = [users.get(aid, {}).get("name", aid[:12]) for aid in matched]
    names_str = ", ".join(names)
    # Persist the rollcall context for audit
    _persist_broadcast(sender_ch, "系统", f"🏗️ 下一环节：{context_summary}\n📋 负责人：{names_str}")
    # ★ R53: Use ACK-driven channel broadcast instead of text "回复到"
    ack_result = await _broadcast_active_channel(sender_ch)
    # ── R58 B2: Log rollcall ACK status (soft check, no blocking) ──
    timedout = ack_result.get("timedout_members", set())
    if timedout:
        logger.info(
            "点名 %s ACK 超时: %s (在线 %d, ACK %d, 超时 %d)",
            target_role,
            ",".join(timedout),
            ack_result.get("online_count", 0),
            len(ack_result.get("acked_members", set())),
            len(timedout),
        )
    # ── R58 B2: End ACK log ──
    return f"✅ 已点名 {names_str}（{ack_result['online_count']} 人在线），等待 ACK 确认..."



def _persist_broadcast(channel: str, from_name: str, content_text: str) -> None:
    """Persist a broadcast message to message store and chat log.

    R41 D: Ensures rollcall and other WS-send-only paths have proper
    persistence (message_store + chat_log) for offline members and web UI.
    """
    try:
        import uuid as _uuid
        msg_id = str(_uuid.uuid4())
        ms.save_message(
            msg_id=msg_id, msg_type="broadcast",
            from_agent="系统", from_name=from_name,
            content=content_text, ts=__import__("time").time(),
            data_dir=config.DATA_DIR, channel=channel,
        )
        write_chat_log(from_name, content_text, channel=channel)
    except Exception:
        pass



# ── R49 B: Agent Card persistence ──────────────────────────────────────


def _get_agent_display(agent_id: str) -> str:
    """统一 agent 显示名：display_name > name > role > agent_id[:12]"""
    cards = ac_mod.get_all_cards()
    card = cards.get(agent_id, {})
    if card.get("display_name"):
        return card["display_name"]
    users = auth.get_users()
    u = users.get(agent_id, {})
    if u.get("name"):
        return u["name"]
    if u.get("role"):
        return u["role"]
    return agent_id[:12]


def _get_agent_card_roles(agent_id: str, cards: dict = None) -> list[str]:
    """Get pipeline roles for an agent from cards. Returns [] if not found."""
    if cards is None:
        cards = ac_mod.get_all_cards()
    card = cards.get(agent_id, {})
    return card.get("pipeline_roles", [])


def _find_agents_by_role(role: str, member_ids: list[str], cards: dict) -> list[str]:
    """Find workspace members whose agent card has the given pipeline role."""
    return [
        aid for aid in member_ids
        if role in _get_agent_card_roles(aid, cards)
    ]


# ── R63 Phase 3: Role-agent mapping ────────────────────────────────


def _refresh_role_agent_map() -> None:
    """Rebuild _ROLE_AGENT_MAP from Agent Card pipeline_roles.

    Called on:
    - Agent card registration / update
    - !agent_role_map --refresh command
    - Handler initialization (load_cards)
    """
    global _ROLE_AGENT_MAP
    cards = ac_mod.get_all_cards()
    _ROLE_AGENT_MAP = {}
    for aid, card in cards.items():
        roles = card.get("pipeline_roles", [])
        for role in roles:
            if role not in _ROLE_AGENT_MAP:
                _ROLE_AGENT_MAP[role] = []
            if aid not in _ROLE_AGENT_MAP[role]:
                _ROLE_AGENT_MAP[role].append(aid)
    logger.info("R63 role-agent map refreshed: %d roles, %d entries",
                len(_ROLE_AGENT_MAP),
                sum(len(v) for v in _ROLE_AGENT_MAP.values()))


# ---- R67 B1: Startup card load + watcher ------------------------------
# These run at module import time (after _refresh_role_agent_map is defined).
_cards_loaded_guard: bool = False
_card_watcher: "ac_mod.CardFileWatcher | None" = None  # type: ignore[name-defined]


def _ensure_agent_cards_loaded() -> None:
    """Ensure agent cards are loaded and role map is built at startup.
    Idempotent — only runs on first call.
    """
    global _cards_loaded_guard
    if _cards_loaded_guard:
        return
    if not ac_mod.is_loaded():
        ac_mod.load_cards()
    _refresh_role_agent_map()
    _cards_loaded_guard = True


def _ensure_card_watcher() -> None:
    """Ensure CardFileWatcher is running (idempotent)."""
    global _card_watcher
    if _card_watcher is not None and _card_watcher.is_running():
        return
    _card_watcher = ac_mod.CardFileWatcher(
        ac_mod.get_cards_path(),
        on_change=_refresh_role_agent_map,
    )
    _card_watcher.start()


def _get_agents_by_role(role: str,
                        workspace_members: list[str] = None) -> list[str]:
    """Find agents by pipeline role.

    Priority chain:
    1. _ROLE_AGENT_MAP (from Agent Card pipeline_roles)
    2. Fallback: auth.get_users().role (legacy compat)
    3. Optional: filter by workspace_members

    Args:
        role: Pipeline role name (arch/dev/review/qa/admin).
        workspace_members: Optional list of member IDs to filter by.

    Returns:
        List of matching agent IDs.
    """
    agents = _ROLE_AGENT_MAP.get(role, [])
    if not agents:
        # Fallback to auth roles
        users = auth.get_users()
        agents = [aid for aid, u in users.items()
                  if u.get("role", "member") == role]
    if workspace_members:
        agents = [a for a in agents if a in workspace_members]
    return agents


async def _handle_rollcall_ack(sender_id: str, content: str,
                                ws_id: str) -> None:
    """Handle rollcall response -> auto-register/update Agent Card.

    R63 Phase 3: When agent replies to rollcall, register or update card.
    R67: Unified — always go through ac_mod.register_agent.

    Args:
        sender_id: Agent ID who replied.
        content: Message content (checked for ack keywords).
        ws_id: Workspace ID (for context, unused in registration).
    """
    users = auth.get_users()
    u = users.get(sender_id, {})
    name = u.get("name", sender_id[:12])
    role = u.get("role", "member")

    # R67: Unified — always go through ac_mod.register_agent
    ac_mod.register_agent(sender_id, name, role)
    _refresh_role_agent_map()
# ── R63 Phase 3: End ──


# ── R42: Pipeline helpers ──────────────────────────────────────────


# ── R62: NoFrontmatterError ──
class NoFrontmatterError(ValueError):
    """Raised when WORK_PLAN content has no YAML frontmatter block."""
    pass


# ── R62 A2: Lightweight YAML frontmatter parser ──
_R62_REPO_BASE = "https://raw.githubusercontent.com/datahome73/ws-bridge/dev"


def _parse_scalar(value: str):
    """Parse a scalar YAML value."""
    value = value.strip()
    if not value:
        return value
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    if value.lower() in ('true', 'yes', 'on'):
        return True
    if value.lower() in ('false', 'no', 'off'):
        return False
    try:
        if '.' in value:
            return float(value)
        return int(value)
    except ValueError:
        pass
    return value


def _parse_frontmatter(content: str) -> dict:
    """Extract and parse YAML frontmatter from WORK_PLAN.md content.
    Supports: strings, nested dicts via indentation, list values.
    Returns: pipeline section dict or raises NoFrontmatterError.
    """
    parts = content.split('---')
    if len(parts) < 3:
        raise NoFrontmatterError("No YAML frontmatter block found")
    frontmatter_text = parts[1].strip()
    lines = frontmatter_text.split('\n')
    result = {}
    stack = [(0, None, result)]
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(line) - len(line.lstrip(' '))
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if stripped.startswith('- '):
            item_text = stripped[2:].strip()
            if stack and stack[-1][2] is not None:
                parent_key = stack[-1][1]
                parent_dict = stack[-1][2]
                if parent_key and parent_key not in parent_dict:
                    parent_dict[parent_key] = []
                if parent_key:
                    parent_dict[parent_key].append(_parse_scalar(item_text))
        elif ':' in stripped:
            key, _, value = stripped.partition(':')
            key = key.strip()
            value = value.strip()
            if stack:
                parent_dict = stack[-1][2]
                if value:
                    parent_dict[key] = _parse_scalar(value)
                    stack.append((indent, key, {}))
                else:
                    parent_dict[key] = {}
                    stack.append((indent, key, parent_dict[key]))
    return result


def _build_pipeline_config(frontmatter: dict, round_name: str, base_urls: dict) -> dict:
    """Build _PIPELINE_CONFIG from frontmatter dict."""
    config = frontmatter.get("pipeline", {})
    if not config:
        raise ValueError("Frontmatter missing 'pipeline' key")
    config["round"] = round_name
    config["work_plan_url"] = base_urls.get("work_plan_url", "")
    config["requirements_url"] = base_urls.get("requirements_url",
        f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-product-requirements.md")
    config["steps"] = config.get("steps", {})
    for step_key, step_cfg in config["steps"].items():
        context = step_cfg.get("context", {})
        for ctx_key, ctx_value in list(context.items()):
            if isinstance(ctx_value, str) and "${pipeline." in ctx_value:
                ref_key = ctx_value.replace("${pipeline.", "").rstrip("}")
                if ref_key in config:
                    context[ctx_key] = str(config[ref_key])
    return config


def _build_fallback_config(round_name: str, base_urls: dict) -> dict:
    """Build _PIPELINE_CONFIG from hardcoded PIPELINE_STEP_MAP (old format compat)."""
    step_map = _r42cfg.PIPELINE_STEP_MAP
    work_plan_url = base_urls.get("work_plan_url", "")
    requirements_url = base_urls.get("requirements_url",
        f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-product-requirements.md")
    steps = {}
    for step_key, step_cfg in step_map.items():
        if step_key == "step1":
            continue
        role = step_cfg.get("role", "")
        steps[step_key] = {
            "role": role,
            "title": step_cfg.get("name", step_key),
            "context": {
                "requirements_url": requirements_url,
                "work_plan_url": work_plan_url,
            },
            "output_desc": "",
            "feedback_channel": "_admin",
            "timeout_minutes": int(step_cfg.get("timeout_hours", 6) * 60),
            "escalation": step_cfg.get("escalation", "notify_pm"),
        }
    return {
        "round": round_name,
        "goal": "",
        "work_plan_url": work_plan_url,
        "requirements_url": requirements_url,
        "steps": steps,
    }


def _step_sort_key(step_name: str) -> tuple:
    """Sort step1, step2, ..., step10 naturally."""
    import re
    m = re.match(r'step(\d+)', step_name.lower())
    return (int(m.group(1)),) if m else (0, step_name)


# ── R69 A1: Auto-infer artifact URL by step type ──
def _infer_artifact_url(step_name: str, round_name: str) -> str:
    """Auto-infer artifact URL based on step type. Returns '' if unknown."""
    step_urls = {
        "step2": f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-tech-plan.md",
        "step4": f"{_R62_REPO_BASE}/docs/{round_name}/{round_name}-review-report.md",
        "step5": f"{_R62_REPO_BASE}/docs/{round_name}/test-report.md",
    }
    return step_urls.get(step_name, "")


from . import config as _r42cfg


def _load_step_config() -> dict[str, dict]:
    """Load step map from config."""
    return _r42cfg.PIPELINE_STEP_MAP



def _get_step_config(round_name: str) -> dict[str, dict]:
    """Unified step config reader: prefer frontmatter, fallback to legacy."""
    pconfig = _PIPELINE_CONFIG.get(round_name, {})
    psteps = pconfig.get("steps", {})
    if psteps:
        return psteps
    return _build_fallback_steps(round_name)


def _build_fallback_steps(round_name: str) -> dict[str, dict]:
    """Build fallback steps from PIPELINE_STEP_MAP, syncing primary/backup."""
    step_map = config.PIPELINE_STEP_MAP
    steps = {}
    for step_key, step_cfg in step_map.items():
        if step_key == "step1":
            continue
        steps[step_key] = {
            "role": step_cfg.get("role", ""),
            "title": step_cfg.get("name", step_key),
            "primary": step_cfg.get("primary"),
            "backup": step_cfg.get("backup"),
            "context": {
                "requirements_url": _get_requirements_url(round_name),
                "work_plan_url": _get_work_plan_url(round_name),
            },
            "output_desc": "",
            "feedback_channel": "_admin",
            "timeout_minutes": int(step_cfg.get("timeout_hours", 6) * 60),
            "escalation": step_cfg.get("escalation", "notify_pm"),
        }
    return steps


def _render_context(context: dict, round_name: str, step_outputs: dict) -> dict:
    """Resolve template variables like ${steps.stepN.sha} in context values."""
    resolved = {}
    for ctx_key, ctx_value in context.items():
        if not isinstance(ctx_value, str):
            resolved[ctx_key] = ctx_value
            continue
        value = ctx_value
        if "${steps." in value:
            for match in _find_template_refs(value, "${steps."):
                parts = match.split(".", 1)
                if len(parts) == 2:
                    step_key, field = parts
                    step_out = step_outputs.get(step_key, {})
                    replacement = str(step_out.get(field, ""))
                    value = value.replace("${steps." + match + "}", replacement)
        resolved[ctx_key] = value
    return resolved


def _find_template_refs(template_str: str, prefix: str) -> list[str]:
    """Extract all template variable references from a string."""
    refs = []
    start = 0
    while True:
        pos = template_str.find(prefix, start)
        if pos == -1:
            break
        end = template_str.find("}", pos)
        if end == -1:
            break
        ref = template_str[pos + len(prefix):end]
        refs.append(ref)
        start = end + 1
    return refs


def _set_pipeline_state(round_name: str, state: dict) -> None:
    _PIPELINE_STATE[round_name] = state


def _update_pipeline_step(round_name: str, step: str) -> None:
    if round_name in _PIPELINE_STATE:
        _PIPELINE_STATE[round_name]["current_step"] = step


def _clear_pipeline_state(round_name: str) -> None:
    _PIPELINE_STATE.pop(round_name, None)
    # R62: _PIPELINE_CONFIG is NOT cleared here — config/state separation


def pipeline_is_active(round_name: str) -> bool:
    state = _PIPELINE_STATE.get(round_name)
    return bool(state and state.get("active"))


def pipeline_exists(round_name: str) -> bool:
    """Check if pipeline exists (created but may or may not be active)."""
    return round_name in _PIPELINE_STATE


def set_lobby_paused(paused: bool, round_name: str = "") -> None:
    global _LOBBY_PAUSED, _LOBBY_PAUSED_ROUND
    _LOBBY_PAUSED = paused
    _LOBBY_PAUSED_ROUND = round_name if paused else ""
    logger.info("R42 lobby-pause: %s (round=%s)", paused, _LOBBY_PAUSED_ROUND)


# ── R43: Watchdog helpers ──────────────────────────────────────────


WATCHDOG_SCAN_INTERVAL: int = 600       # 10 分钟（秒）
WATCHDOG_REALERT_INTERVAL: int = 1800   # 30 分钟（秒）

# 超时默认值（与 config.py STEP_TIMEOUT_DEFAULTS 保持一致）
_STEP_TIMEOUT_DEFAULTS: dict[str, float] = {
    "step1": 2.0,
    "step2": 6.0,
    "step3": 12.0,
    "step4": 4.0,
    "step5": 6.0,
    "step6": 2.0,
}


def _ensure_watchdog() -> None:
    """Lazily start the background watchdog loop on first call."""
    global _watchdog_started, _watchdog_task
    if _watchdog_started:
        return
    _watchdog_task = asyncio.create_task(_watchdog_loop())
    _watchdog_started = True
    logger.info("R43 watchdog started (scan=%ds, realert=%ds)",
                WATCHDOG_SCAN_INTERVAL, WATCHDOG_REALERT_INTERVAL)


# ── R65 A2: Git sync lifecycle ──────────────────────────────────


def _ensure_git_scan() -> None:
    """在 handler 初始化时调用一次。启动 git sync 定时循环。"""
    global _GIT_SYNC_TASK
    if not config.ENABLE_GIT_SYNC:
        logger.info("[R65] Git sync 已禁用（ENABLE_GIT_SYNC=false）")
        return
    if _GIT_SYNC_TASK is None or _GIT_SYNC_TASK.done():
        _GIT_SYNC_TASK = asyncio.create_task(_start_git_sync_loop())
        logger.info("[R65] Git sync watchdog 已启动（interval=%ds）", config.GIT_SYNC_INTERVAL)


async def _start_git_sync_loop():
    """独立的 git 同步定时循环，每 GIT_SYNC_INTERVAL 秒执行一次。"""
    while True:
        await asyncio.sleep(config.GIT_SYNC_INTERVAL)
        try:
            await _pipeline_git_sync_scan()
        except Exception as e:
            logger.warning("[R65] git_sync_scan error: %s", e)


async def _pipeline_git_sync_scan():
    """遍历所有活跃管线，检查 git 同步。"""
    for pid, pstate in list(_PIPELINE_STATE.items()):
        if not pstate.get("active"):
            continue
        if not config.ENABLE_GIT_SYNC:
            continue

        # 从 _PIPELINE_CONFIG 读取管线专属配置
        pconfig = _PIPELINE_CONFIG.get(pid, {})
        sync_config = {
            "branch": pconfig.get("git_sync_branch", config.GIT_SYNC_BRANCH),
            "repo_path": pconfig.get("repo_path", config.REPO_PATH),
            "last_sha": pstate.get("last_output_sha", ""),
            "fallback_enabled": config.GIT_SYNC_FALLBACK,
        }

        syncer = pps.PipelineGitSync(pid, sync_config)
        result = await syncer.sync()
        if result and result.get("synced"):
            await _auto_advance_pipeline(pid, result)
            pstate["_last_git_sync_ts"] = time.time()
# ── R65 A2: End ──


async def _auto_advance_pipeline(round_name: str, result: dict) -> str:
    """Git sync 检测到新产出后自动推进状态机。

    Args:
        round_name: 管线标识
        result: PipelineGitSync.sync() 返回值

    Returns:
        广播消息文本。
    """
    pstate = _PIPELINE_STATE.get(round_name)
    if not pstate:
        return ""

    step_config = _get_step_config(round_name)
    current_step = pstate.get("current_step", "")
    if not current_step:
        return ""

    # 获取当前 Step 在 step_config 中的索引
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
    try:
        idx = step_keys.index(current_step)
    except ValueError:
        return ""

    if idx + 1 >= len(step_keys):
        return ""  # 已是最后一步

    next_step = step_keys[idx + 1]
    new_sha = result.get("new_sha", "")

    # 1. 状态机推进
    pstate["current_step"] = next_step
    pstate["last_output_sha"] = new_sha
    # 更新 Task state
    tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
    for t in tasks:
        if t.get("name") == current_step and t.get("state") != p.TaskState.COMPLETED.value:
            await _cmd_task_update("系统", {
                "_positional": [t["id"]],
                "state": p.TaskState.COMPLETED.value,
                "output": new_sha,
            })
        if t.get("name") == next_step and t.get("state") == p.TaskState.PENDING.value:
            await _cmd_task_update("系统", {
                "_positional": [t["id"]],
                "state": p.TaskState.WORKING.value,
            })

    # 2. 清理旧 ACK FAILED 标记
    old_ack_key = f"{round_name}/{current_step}"
    if old_ack_key in _step_ack_states:
        if _step_ack_states[old_ack_key].get("state") == "FAILED":
            _step_ack_states.pop(old_ack_key, None)
            logger.info("[R65] 清除 %s 的 FAILED 标记（git sync 发现新产出）", old_ack_key)

    # 3. 广播自动同步消息
    ws_id = pstate.get("ws_id", "")
    commit_short = new_sha[:7] if new_sha else "?"
    mode = result.get("mode", "auto")
    mode_label = "" if mode == "default" else f"（{mode} 匹配）"

    msg = (
        f"💻 {round_name} {current_step} → {next_step} 已自动同步\n"
        f"  commit: {commit_short}{mode_label}\n"
        f"→ @{next_step} 到你了！"
    )

    if ws_id:
        pm_name = config.PIPELINE_PM_NAME
        _persist_broadcast(ws_id, pm_name, msg)
        payload = json.dumps({
            "type": "broadcast", "channel": ws_id,
            "from_name": pm_name, "from": pm_name,
            "content": msg, "ts": time.time(),
        })
        ws_obj = ws_mod.get_workspace(ws_id)
        if ws_obj:
            for member_id in ws_obj.members:
                for conn in list(_connections.get(member_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(payload)
                        elif hasattr(conn, "send"):
                            await conn.send(payload)
                    except Exception:
                        pass

    # 4. 点名下一角色（复用 R63 @role_name → @bot_name 机制）
    next_role = step_config[next_step].get("role", "")
    if next_role:
        cards = ac_mod.get_all_cards()
        ws_obj = ws_mod.get_workspace(ws_id) if ws_id else None
        if ws_obj and cards:
            matched = _find_agents_by_role(next_role, ws_obj.members, cards)
            users = auth.get_users()
            for aid in matched:
                name = users.get(aid, {}).get("name", aid[:12])
                mention = f"@{name} 🏗️ {round_name} {next_step} 到你了！"
                mention_payload = json.dumps({
                    "type": "broadcast", "channel": ws_id,
                    "from_name": pm_name, "from": pm_name,
                    "content": mention, "ts": time.time(),
                })
                for conn in list(_connections.get(aid, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(mention_payload)
                        elif hasattr(conn, "send"):
                            await conn.send(mention_payload)
                    except Exception:
                        pass

    # 5. 启动下一 Step timeout_tracker 倒计时
    if _ENABLE_R63_TIMEOUT:
        timeout_min = step_config.get(next_step, {}).get("timeout_minutes", 20)
        timeout_tracker.start_timer(round_name, next_step, timeout_min)

    logger.info("[R65] 管线 %s 已自动推进：%s → %s (sha=%s)",
                round_name, current_step, next_step, commit_short)
    return msg


async def _watchdog_loop() -> None:
    """Background watchdog loop — scans all active pipelines every 10 min."""
    try:
        while True:
            await asyncio.sleep(WATCHDOG_SCAN_INTERVAL)
            await _watchdog_scan()
    except asyncio.CancelledError:
        logger.info("R43 watchdog loop cancelled — shutting down")


async def _watchdog_scan() -> None:
    """Scan all active pipelines and trigger alerts for timed-out steps."""
    if not _PIPELINE_STATE:
        return  # A-2: no active pipelines → zero output

    # ── R67 C2: Mark stale agents offline ──────────────────────
    try:
        ac_mod.mark_stale_offline()
    except Exception:
        pass  # non-blocking

    now = time.time()
    step_config = _get_step_config("")  # R67 D: unified step config (watchdog global)

    for round_name, pstate in list(_PIPELINE_STATE.items()):
        if not pstate.get("active"):
            continue

        step_name = pstate.get("current_step", "")
        if not step_name:
            continue

        ws_id = pstate.get("ws_id", "")

        # ── R63 Phase 2: Use timeout_tracker if enabled ──
        if _ENABLE_R63_TIMEOUT:
            if not timeout_tracker.is_expired(round_name, step_name):
                continue  # Not yet expired, skip

            # Check dedup — only alert if not already notified
            timer_info = timeout_tracker.get_timer_info(round_name, step_name)
            if timer_info and timer_info.get("notified"):
                continue  # Already notified, skip

            # Mark notified and send alert
            if timer_info is not None:
                timer_info["notified"] = True
            await _trigger_timeout_escalation(round_name, step_name, ws_id=ws_id)

            # Also mark in old watchdog_alerts for backward compat
            key = f"{round_name}/{step_name}"
            _watchdog_alerts[key] = now
            continue
        # ── R63 Phase 2: End timeout_tracker path ──

        # Calculate elapsed time
        started_at = pstate.get("started_at", now)
        elapsed_hours = (now - started_at) / 3600.0

        # Get timeout threshold
        timeout_hours = _get_step_timeout(round_name, step_name)

        # Skip if not timed out
        if elapsed_hours <= timeout_hours:
            continue

        # Check/record alert status
        alert_type = _check_watchdog_alert(round_name, step_name)
        if alert_type is None:
            continue  # Within cooldown period
        if alert_type == "cooldown":
            continue

        # Send alert
        await _send_watchdog_alert(
            round_name, step_name, elapsed_hours, timeout_hours, alert_type,
        )


def _get_step_timeout(round_name: str, step_name: str) -> float:
    """Get timeout_hours for a step — config > default > infinity."""
    step_config = _get_step_config(round_name)
    step_info = step_config.get(step_name, {})
    if step_info and "timeout_hours" in step_info:
        return float(step_info["timeout_hours"])
    return float(_STEP_TIMEOUT_DEFAULTS.get(step_name, float("inf")))


# ── R63 Phase 2: Timeout escalation ─────────────────────────────


async def _trigger_timeout_escalation(round_name: str, step_name: str,
                                       ws_id: str = "") -> str:
    """超时触发 → 工作室 @PM + _admin 频道告警 (R63 Phase 2).

    Args:
        round_name: Pipeline round name (e.g. "R63").
        step_name: Step key (e.g. "step2").
        ws_id: Workspace ID for broadcasting alert.

    Returns:
        Alert message string.
    """
    step_cfg = _PIPELINE_CONFIG.get(round_name, {}).get("steps", {}).get(step_name, {})
    timeout_mins = step_cfg.get("timeout_minutes", 15)
    remaining = timeout_tracker.get_remaining(round_name, step_name)
    over_by = max(0, int(timeout_mins * 60 - remaining))

    alert = (
        f"⏰ [超时告警] {round_name} {step_name}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⏱ 预期完成时间: {timeout_mins}分钟\n"
        f"🕐 已超时: {over_by // 60}分{over_by % 60}秒\n"
        f"━━━━━━━━━━━━━━━\n"
        f"请 @PM 协调：是否跳过 / 换人 / 手动干预"
    )

    if ws_id:
        pm_name = config.PIPELINE_PM_NAME
        _persist_broadcast(ws_id, pm_name, alert)
        payload = json.dumps({
            "type": "broadcast", "channel": ws_id,
            "from_name": pm_name, "from": pm_name,
            "content": alert, "ts": time.time(),
        })
        ws_obj = ws_mod.get_workspace(ws_id)
        if ws_obj:
            for member_id in ws_obj.members:
                for conn in list(_connections.get(member_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(payload)
                        elif hasattr(conn, "send"):
                            await conn.send(payload)
                    except Exception:
                        pass
    return alert
# ── R63 Phase 2: End ──


# ── R63 Phase 4: ACK state machine ──────────────────────────────

ACK_TIMEOUT_SEC = 30  # Seconds from SENT to FAILED


async def _ack_timeout_task(ack_key: str) -> None:
    """30-second ACK timeout detection.

    If no ACK received within timeout, marks state as ack_timeout
    (not FAILED) — waits for git sync to detect new output instead.

    R65 C1: ACK 超时不标记 FAILED，改为 ack_timeout 等待标记。
    只有当 git sync + timeout_tracker 都无产出时才标记真正 FAILED。
    """
    await asyncio.sleep(ACK_TIMEOUT_SEC)
    state = _step_ack_states.get(ack_key, {})
    if state.get("state") in ("SENT", "DELIVERED"):
        # ── R65 C1: ACK 超时 → 标记 ack_timeout（不标 FAILED）──
        state["state"] = "ack_timeout"
        logger.info("[R65 C1] ACK 超时: %s (agent=%s) — 等待 git 产出，不标 FAILED",
                    ack_key, state.get("agent_id", "?"))
        # 仅发送信息性消息，不触发 escalation
        await _send_ack_timeout_info(ack_key, state)


async def _send_ack_timeout_info(ack_key: str, state: dict) -> str:
    """ACK 超时信息通知（非告警）。"""
    parts = ack_key.split("/", 1)
    round_name = parts[0] if len(parts) > 0 else "?"
    step_name = parts[1] if len(parts) > 1 else "?"
    agent_id = state.get("agent_id", "")
    display_name = _get_agent_display(agent_id) if agent_id else "未知"

    info = (
        f"⏰ [ACK 未响应] {round_name} {step_name}\n"
        f"  目标: {display_name} — 30s 内未回复 ACK\n"
        f"  状态: ⚠️ 等待 git 产出（不标记失败）\n"
        f"  Git sync 将自动检测并推进"
    )

    # 广播到工作室
    for rname, pstate in _PIPELINE_STATE.items():
        if rname == round_name:
            ws_id = pstate.get("ws_id", "")
            if ws_id:
                pm_name = config.PIPELINE_PM_NAME
                _persist_broadcast(ws_id, pm_name, info)
                payload = json.dumps({
                    "type": "broadcast", "channel": ws_id,
                    "from_name": pm_name, "from": pm_name,
                    "content": info, "ts": time.time(),
                })
                ws_obj = ws_mod.get_workspace(ws_id)
                if ws_obj:
                    for member_id in ws_obj.members:
                        for conn in list(_connections.get(member_id, set())):
                            try:
                                if hasattr(conn, "send_str"):
                                    await conn.send_str(payload)
                                elif hasattr(conn, "send"):
                                    await conn.send(payload)
                            except Exception:
                                pass
            break

    logger.info("[R65 C1] ACK 超时信息: %s (target=%s)", ack_key, display_name)
    return info


async def _trigger_ack_escalation(ack_key: str, state: dict) -> str:
    """ACK timeout → PM escalation alert.

    Args:
        ack_key: Key in _step_ack_states.
        state: Current state dict.

    Returns:
        Alert message string.
    """
    parts = ack_key.split("/", 1)
    round_name = parts[0] if len(parts) > 0 else "?"
    step_name = parts[1] if len(parts) > 1 else "?"
    agent_id = state.get("agent_id", "")
    display_name = _get_agent_display(agent_id) if agent_id else "未知"

    alert = (
        f"🕐 [ACK 超时] {round_name} {step_name}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🎯 目标: {display_name}\n"
        f"📨 状态: {state.get('state', 'UNKNOWN')}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"请 @PM 协调：等待 / 换备用 / 手动驱动 / 跳过"
    )

    # Broadcast to workspace if available
    for rname, pstate in _PIPELINE_STATE.items():
        if rname == round_name:
            ws_id = pstate.get("ws_id", "")
            if ws_id:
                pm_name = config.PIPELINE_PM_NAME
                _persist_broadcast(ws_id, pm_name, alert)
                payload = json.dumps({
                    "type": "broadcast", "channel": ws_id,
                    "from_name": pm_name, "from": pm_name,
                    "content": alert, "ts": time.time(),
                })
                ws_obj = ws_mod.get_workspace(ws_id)
                if ws_obj:
                    for member_id in ws_obj.members:
                        for conn in list(_connections.get(member_id, set())):
                            try:
                                if hasattr(conn, "send_str"):
                                    await conn.send_str(payload)
                                elif hasattr(conn, "send"):
                                    await conn.send(payload)
                            except Exception:
                                pass
            break

    logger.info("ACK escalation: %s (target=%s)", ack_key, display_name)
    return alert


def _update_step_ack_state(sender_id: str, content: str) -> None:
    """Update _step_ack_states when bot responds in a workspace.

    R63 Phase 4: Bot ACK detection — any message from a target agent
    is treated as ACK. If content contains ack keywords, mark IN_PROGRESS.

    Args:
        sender_id: Agent ID who sent the message.
        content: Message content (checked for ack keywords).
    """
    if not _ENABLE_R63_ACK:
        return

    ack_keywords = ["收到", "好的", "在", "到", "接", "OK", "ok", "开始", "done"]
    is_ack = any(kw in content for kw in ack_keywords)

    for ack_key, ack_state in _step_ack_states.items():
        if ack_state.get("agent_id") == sender_id and ack_state["state"] in ("SENT", "DELIVERED"):
            old_state = ack_state["state"]
            if is_ack:
                ack_state["state"] = "IN_PROGRESS"
            else:
                ack_state["state"] = "ACKNOWLEDGED"
            logger.info("ACK updated: %s %s → %s (from %s)",
                        ack_key, old_state, ack_state["state"], sender_id[:12])


def _format_ack_status(ack_key: str) -> str:
    """Format ACK state for pipeline_status display.

    Args:
        ack_key: Key in _step_ack_states.

    Returns:
        Formatted status string, or empty string if not tracked.
    """
    state = _step_ack_states.get(ack_key)
    if not state:
        return ""
    s = state["state"]
    elapsed = time.time() - state.get("sent_at", time.time())
    if s == "SENT":
        return f"📨 SENT → 等待 ACK ({int(elapsed)}秒)"
    elif s == "DELIVERED":
        return f"📬 DELIVERED → 等待 ACK ({int(elapsed)}秒)"
    elif s == "ACKNOWLEDGED":
        return f"✅ ACKNOWLEDGED ({int(elapsed)}秒确认)"
    elif s == "IN_PROGRESS":
        return f"🟢 IN_PROGRESS ({int(elapsed)}秒)"
    elif s == "FAILED":
        return f"❌ FAILED — 超时无响应"
    return f"❓ {s}"


# ── R63 Phase 4: End ──


def _check_watchdog_alert(round_name: str, step_name: str) -> str | None:
    """Check dedup state and return 'first', 'repeat', or None (skip)."""
    key = f"{round_name}/{step_name}"
    now = time.time()
    last_alert = _watchdog_alerts.get(key)

    if last_alert is None:
        # First-time timeout
        _watchdog_alerts[key] = now
        return "first"

    # Already alerted — check cooldown
    elapsed = now - last_alert
    if elapsed < WATCHDOG_REALERT_INTERVAL:
        return None  # Skip — within cooldown

    _watchdog_alerts[key] = now
    return "repeat"


def _clear_watchdog_alert(round_name: str, step_name: str) -> bool:
    """Clear watchdog alert marker. Returns True if an alert was active."""
    key = f"{round_name}/{step_name}"
    if key in _watchdog_alerts:
        del _watchdog_alerts[key]
        return True
    return False


def _elapsed_hours_display(elapsed_hours: float) -> str:
    """Format elapsed time for display."""
    if elapsed_hours < 1:
        return f"{int(elapsed_hours * 60)} 分钟"
    return f"{elapsed_hours:.1f} 小时"


async def _send_watchdog_alert(
    round_name: str,
    step_name: str,
    elapsed_hours: float,
    timeout_hours: float,
    alert_type: str,
) -> None:
    """Send timeout alert to _admin channel."""
    step_config = _get_step_config(round_name)
    step_info = step_config.get(step_name, {})
    step_display = step_info.get("name", step_name)
    role = step_info.get("role", "?")
    repeat_tag = f"（重复通知）" if alert_type == "repeat" else ""

    started_at = _PIPELINE_STATE.get(round_name, {}).get("started_at", 0)
    import datetime as _dt
    started_dt = _dt.datetime.fromtimestamp(started_at).strftime("%Y-%m-%d %H:%M")

    msg = (
        f"⚠️ {round_name} 管线超时告警{repeat_tag}\n"
        f"  Step: {step_display}（{step_name}）\n"
        f"  责任人: {role}\n"
        f"  已挂起: {_elapsed_hours_display(elapsed_hours)}（超时阈值: {timeout_hours}h）\n"
        f"  启动时间: {started_dt}\n"
        f"  建议操作: 联系 {role} 或考虑换人"
    )

    _persist_broadcast(p.ADMIN_CHANNEL, "系统", msg)
    # R49 C: Also broadcast to active workspace if available
    pstate = _PIPELINE_STATE.get(round_name, {})
    ws_id = pstate.get("ws_id", "")
    if ws_id:
        ws_obj = ws_mod.get_workspace(ws_id)
        if ws_obj:
            ws_msg_lines = [
                "Timeout alert: " + round_name + " / " + step_display,
                "  Owner: " + role,
                "  Elapsed: " + _elapsed_hours_display(elapsed_hours) + " (limit: " + str(timeout_hours) + "h)",
                "  Please handle or delegate.",
            ]
            ws_msg = "\n".join(ws_msg_lines)
            ws_payload = json.dumps({
                "type": "broadcast", "channel": ws_id,
                "from_name": "\u7cfb\u7edf", "from": "\u7cfb\u7edf",
                "content": ws_msg, "ts": time.time(),
            })
            for agent_id in ws_obj.members:
                for conn in list(_connections.get(agent_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            conn.send_str(ws_payload)
                        else:
                            conn.send(ws_payload)
                    except Exception:
                        pass
            write_chat_log("\u7cfb\u7edf", ws_msg, channel=ws_id)
    logger.info("R43 watchdog alert: %s/%s (%s)", round_name, step_name, alert_type)




async def _watchdog_rerollcall(round_name: str, step_name: str) -> None:
    """After timeout, try to rerollcall the current step owner in workspace."""
    pstate = _PIPELINE_STATE.get(round_name, {})
    ws_id = pstate.get("ws_id", "")
    if not ws_id:
        return
    step_config = _get_step_config(round_name)
    step_info = step_config.get(step_name, {})
    role = step_info.get("role", "?")
    try:
        await _cmd_rollcall_role("系统", {
            "_positional": [role],
            "context": round_name + " " + step_name + " timeout rerollcall",
        })
    except Exception:
        pass


async def _send_clear_alert(round_name: str, step_name: str, output_ref: str) -> None:
    """Send recovery notification to _admin channel."""
    step_config = _get_step_config(round_name)
    step_info = step_config.get(step_name, {})
    step_display = step_info.get("name", step_name)

    msg = (
        f"✅ {round_name} {step_display}（{step_name}）已恢复 — "
        f"已完成（{output_ref}）"
    )

    _persist_broadcast(p.ADMIN_CHANNEL, "系统", msg)
    logger.info("R43 watchdog clear: %s/%s", round_name, step_name)




# ── R55 C: Git commit verification ──────────────────────────


async def _verify_git_commit(commit_sha: str) -> tuple[bool, str]:
    """Check remote git dev branch for the given commit SHA via git ls-remote.
    Uses 10s timeout. On failure, degrades to a warning.
    Returns: (ok_to_proceed, message)
    """
    import subprocess
    repo_url = _r42cfg.GIT_REMOTE_URL
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "git", "ls-remote", repo_url, "refs/heads/dev",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ),
            timeout=10,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return True, (
                f"⚠️ git ls-remote 异常退出（{stderr.decode('utf-8', errors='replace')[:40]}），"
                f"已跳过验证，继续推进"
            )
        refs = stdout.decode("utf-8", errors="replace")
        if commit_sha in refs:
            return True, ""
        else:
            return False, (
                f"❌ Commit {commit_sha[:12]} 不存在于远程仓库 "
                f"（{repo_url}）的 dev 分支"
            )
    except asyncio.TimeoutError:
        return True, "⚠️ git ls-remote 超时（10s），已跳过验证，继续推进"
    except Exception as e:
        return True, f"⚠️ git 验证不可达（{str(e)[:40]}），已跳过验证，继续推进"


# ── R42: Pipeline commands ─────────────────────────────────────────

async def _cmd_pipeline_start(sender_id: str, params: dict) -> str:
    """启动管线。
    用法：!pipeline_start <R{N}> [--from <step>] [--workspace-id <ws_id>]
    仅在 _admin 频道可用。
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!pipeline_start <R{N}> [--from <step>] [--workspace-id <ws_id>]"
    round_name = positional[0].upper()
    from_step = params.get("from", "")
    # ── R71: Optional --workspace-id to attach to existing workspace ──
    explicit_ws_id = params.get("workspace_id", params.get("ws", ""))

    # ── R55 E: Mode parameter ──
    mode = params.get("mode", "auto").lower()
    if mode not in ("auto", "manual"):
        return "❌ mode 参数仅支持 auto（自动驾驶）或 manual（手动模式）"

    # 验证前置决策状态 — R48 A: --work-plan-url 参数优先 + R45 fallback
    work_plan_url = params.get("work_plan_url", "")
    _remote_url = ""  # R62: initialize early
    work_plan_ok = False
    import urllib.request as _r45url
    if work_plan_url:
        # 方向 A: 使用传入的 URL
        try:
            _r48req = _r45url.Request(work_plan_url, method='HEAD')
            with _r45url.urlopen(_r48req, timeout=5) as _r48resp:
                if _r48resp.status == 200:
                    work_plan_ok = True
        except Exception:
            pass
        if not work_plan_ok:
            return f"❌ WORK_PLAN URL 不可达：{work_plan_url}"
    else:
        # R45 fallback: 拼接默认 URL
        _remote_url = f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/WORK_PLAN.md"
        try:
            _r45req = _r45url.Request(_remote_url, method='HEAD')
            with _r45url.urlopen(_r45req, timeout=5) as _r45resp:
                if _r45resp.status == 200:
                    work_plan_ok = True
        except Exception:
            pass
        if not work_plan_ok:
            import os as _r42os
            work_plan_path = f"docs/{round_name}/WORK_PLAN.md"
            work_plan_ok = _r42os.path.exists(work_plan_path)
        if not work_plan_ok:
            return f"❌ {round_name} 未找到 WORK_PLAN.md（远程+本地均失败），请先完成 Step A/B"

    # ── R62 A3: Parse frontmatter → Build _PIPELINE_CONFIG ──
    _pipeline_config = _PIPELINE_CONFIG.get(round_name)
    if not _pipeline_config:
        import urllib.request as _r62url
        try:
            _r62req = _r62url.Request(work_plan_url or _remote_url)
            with _r62url.urlopen(_r62req, timeout=5) as _r62resp:
                wp_content = _r62resp.read().decode('utf-8')
        except Exception:
            wp_content = ""
        if wp_content:
            try:
                frontmatter = _parse_frontmatter(wp_content)
                config_data = _build_pipeline_config(frontmatter, round_name, {
                    "work_plan_url": work_plan_url or _remote_url,
                    "requirements_url": f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/{round_name}-product-requirements.md"
                })
                _PIPELINE_CONFIG[round_name] = config_data
            except (NoFrontmatterError, ValueError):
                config_data = _build_fallback_config(round_name, {
                    "work_plan_url": work_plan_url or _remote_url,
                    "requirements_url": f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/{round_name}-product-requirements.md"
                })
                _PIPELINE_CONFIG[round_name] = config_data
                write_chat_log("系统", f"📋 {round_name}：使用旧格式配置（无 machine-frontmatter）")
        else:
            config_data = _build_fallback_config(round_name, {
                "work_plan_url": work_plan_url or "",
                "requirements_url": f"{config.WORK_PLAN_REPO_URL}/docs/{round_name}/{round_name}-product-requirements.md"
            })
            _PIPELINE_CONFIG[round_name] = config_data
    # ── R62 A3: End ──

    # 锁定管线（防重复）
    if pipeline_is_active(round_name):
        return f"❌ {round_name} 管线已活跃，不可重复启动"

    # 暂停大厅接收（方向 D）
    set_lobby_paused(True, round_name)

    # ── R44 F-13: Auto-collect workspace members ──────────
    # ── R49 B: Use agent cards if available ──────────
    cards = ac_mod.get_all_cards()
    step_config = _get_step_config(round_name)
    all_roles = set()
    for step_key, step_cfg in step_config.items():
        role = step_cfg.get("role", "")
        if role and step_key != "step1":
            all_roles.add(role)

    users = auth.get_users()
    member_ids = []
    if cards:
        # Agent cards exist: collect agents whose pipeline_roles intersect all_roles
        seen = set()
        for aid, card in cards.items():
            p_roles = set(card.get("pipeline_roles", []))
            if p_roles & all_roles:
                member_ids.append(aid)
                seen.add(aid)
        # Also include any auth users who have matching role but no card
        for aid, u in users.items():
            if aid not in seen and u.get("role", "member") in all_roles:
                member_ids.append(aid)
    else:
        # No cards: fallback to auth.get_users() role field
        for aid, u in users.items():
            if u.get("role", "member") in all_roles:
                member_ids.append(aid)

    # ── R71: Optional --workspace-id to attach to existing workspace ──
    if explicit_ws_id:
        # R71: Use the explicitly provided workspace ID — skip create/reuse
        ws_id = explicit_ws_id
        create_result = f"✅ 附着到已有工作室 {ws_id[:16]}…"
        # Verify the workspace exists
        _ws_check = ws_mod.get_workspace(ws_id)
        if _ws_check:
            create_result = f"✅ 附着到已有工作室「{_ws_check.name}」({ws_id[:16]}…)"
        else:
            create_result = f"⚠️ 指定工作室 {ws_id[:16]}… 不存在，仍以该 ID 启动管线"
        # Skip member auto-discovery — workspace already has its members
        member_ids = list(_ws_check.members) if _ws_check else []
    else:
        # ── R70 Fix: 先检查是否已有当前 round 的工作室 ──
        sender_ch = persistence.get_agent_channel(sender_id) or p.LOBBY
        existing_ws = ws_mod.get_workspace(sender_ch) if sender_ch != p.LOBBY else None
        if existing_ws and round_name in existing_ws.name:
            # Reuse existing workspace instead of creating a new one
            ws_id = existing_ws.id
            create_result = f"✅ 复用现有工作室「{existing_ws.name}」({ws_id[:16]}…)"
            logger.info(
                "R70: Reusing existing workspace %s for pipeline %s (sender %s)",
                ws_id, round_name, sender_id[:12],
            )
        else:
            # 创建工作室（带自动组建）
            create_params = {
                "_positional": [f"{round_name}-dev"],
                "members": ",".join(member_ids),
            }
            create_result = await _cmd_create_workspace(sender_id, create_params)
            # 从结果提取 ws_id（调用 persistence 获取最新频道）
            ws_id = persistence.get_agent_channel(sender_id) or f"__{round_name}_ws"

    # R50+: Broadcast MSG_SET_ACTIVE_CHANNEL to all workspace members
    # (F-20: pipeline_start was missing this — members never saw rollcall/assignment)
    await _broadcast_active_channel(ws_id)

    # 查 Step 映射表，找起始角色（必须在 R58 A3 之前，因为 kickoff_msg 引用 target_role）
    start_step = from_step if from_step else "step2"  # R44: default step2 (tech plan)
    target_role = step_config[start_step]["role"]
    # ── R59 C: Apply role override if configured for kickoff ──
    _role_overrides = getattr(config, "PIPELINE_ROLE_OVERRIDES", {})
    if start_step in _role_overrides:
        target_role = _role_overrides[start_step]
    # ── R59 C: End role override ──

    # ── R58 A3: Initial kickoff PM @mention notification ──
    pm_name = config.PIPELINE_PM_NAME
    # ── R62: Read from _PIPELINE_CONFIG ──
    _pconfig = _PIPELINE_CONFIG.get(round_name, {})
    _pconfig_steps = _pconfig.get("steps", {})
    _step_cfg_from_pconfig = _pconfig_steps.get(start_step, {})
    _step_title = _step_cfg_from_pconfig.get("title", start_step)
    _req_url = _pconfig.get("requirements_url",
        f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/{round_name}-product-requirements.md")
    _plan_url = _pconfig.get("work_plan_url",
        f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/WORK_PLAN.md")
    kickoff_msg = (
        f"@全员 🚀 {round_name} 管线已启动！\n"
        f"下一棒：{target_role} → {_step_title}\n\n"
        f"📄 需求：{_req_url}\n"
        f"📋 WORK_PLAN：{_plan_url}\n\n"
        f"各 bot 请切换活跃频道到此工作室，确认就绪。"
    )
    _persist_broadcast(ws_id, pm_name, kickoff_msg)
    kickoff_payload = json.dumps({
        "type": "broadcast", "channel": ws_id,
        "from_name": pm_name, "from": pm_name,
        "content": kickoff_msg, "ts": time.time(),
    })
    # 用 ws_mod.get_workspace 替代不存在的 ws_obj 变量（R58 A3 Bug）
    ws_obj_2 = ws_mod.get_workspace(ws_id)
    if ws_obj_2:
        for member_id in ws_obj_2.members:
            for conn in list(_connections.get(member_id, set())):
                try:
                    if hasattr(conn, "send_str"):
                        await conn.send_str(kickoff_payload)
                    elif hasattr(conn, "send"):
                        await conn.send(kickoff_payload)
                except Exception:
                    pass
    # ── R58 A3: End kickoff notification ──

    # 点名架构师，附带文档 URL（R48: 有自定义 URL 时只传 WORK_PLAN 链接）
    if work_plan_url:
        context_urls = f"WORK_PLAN: {work_plan_url}"
    else:
        context_urls = (
            f"需求: docs/{round_name}/{round_name}-product-requirements.md | "
            f"WORK_PLAN: docs/{round_name}/WORK_PLAN.md"
        )
    rollcall_result = await _cmd_rollcall_next(sender_id, {
        "_positional": [target_role],
        "context": f"{round_name} {start_step}: {context_urls}",
    })

    # 创建 Step Task
    task_result = await _cmd_task_create(sender_id, {
        "context": round_name,
        "name": start_step,
        "role": target_role,
    })

    # 设置管线状态
    _set_pipeline_state(round_name, {
        "active": True,
        "current_step": start_step,
        "ws_id": ws_id,
        "started_at": __import__("time").time(),
        "work_plan_url": work_plan_url or None,   # R48 A: 传入的 WORK_PLAN URL
        "triggerer_id": sender_id,                 # R48 B: 管线触发者
        "mode": mode,                              # R55 E: 自动/手动模式
    })

    return (
        f"🚀 **{round_name} 管线已启动**\n"
        f"  Step: {start_step} → {target_role}\n"
        f"  工作室: {ws_id}\n"
        f"  {create_result}\n"
        f"  {rollcall_result}\n"
        f"  {task_result}"
    )


# ── R50: Pipeline activate command ────────────────────────────────


async def _cmd_pipeline_activate(sender_id: str, params: dict) -> str:
    """激活已启动但未活跃的管线。
    用法：!pipeline_activate <R{N}> [--ws <workspace_id>]
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!pipeline_activate <R{N}> [--ws <workspace_id>]"
    round_name = positional[0].upper()
    ws_id = params.get("ws", "")

    if not pipeline_exists(round_name):
        return f"❌ {round_name} 管线不存在，请先执行 !pipeline_start {round_name}"
    if pipeline_is_active(round_name):
        return f"❌ {round_name} 管线已激活，无需重复激活"

    # Use provided --ws or fallback to pipeline state
    if not ws_id:
        ws_id = _PIPELINE_STATE.get(round_name, {}).get("ws_id", "")
    if not ws_id:
        return f"❌ {round_name} 未找到工作室 ID，请用 --ws <workspace_id> 指定"

    ws_obj = ws_mod.get_workspace(ws_id)
    if not ws_obj:
        return f"❌ 工作室 {ws_id} 不存在"

    # Broadcast MSG_SET_ACTIVE_CHANNEL to all workspace members
    switch_count = await _broadcast_active_channel(ws_id)

    # Activate pipeline
    _set_pipeline_state(round_name, {
        "active": True,
        "current_step": _PIPELINE_STATE.get(round_name, {}).get("current_step", "step1"),
        "ws_id": ws_id,
        "activated_at": __import__("time").time(),
    })

    return (
        f"🚀 **{round_name} 管线已激活**\n"
        f"  工作室: {ws_id}\n"
        f"  MSG_SET_ACTIVE_CHANNEL 已发送至 {switch_count['online_count']} 个在线成员\n"
        f"  请各成员确认频道已切换到工作室"
    )


# ── R68 A3: Send inbox task assignment + workspace notification ──
async def _send_inbox_task(
    target_agent_id: str,
    round_name: str,
    next_step: str,
    step_config: dict,
    output_ref: str,
    workspace_id: str,
    pm_name: str,
    pm_agent_id: str = "system",  # ← R69 B1
) -> None:
    """Send full task to target agent's inbox + lightweight workspace notification."""
    inbox_ch = persistence.get_inbox_channel(target_agent_id)
    _pstate = _PIPELINE_STATE.get(round_name, {})
    _pconfig = _PIPELINE_CONFIG.get(round_name, {})

    # Collect context URLs
    req_url = _pconfig.get("requirements_url",
        f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/{round_name}-product-requirements.md")
    plan_url = _pconfig.get("work_plan_url",
        _pstate.get("work_plan_url",
            f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/WORK_PLAN.md"))

    # ── R69 A3: Build rich context from step_outputs ──
    _pstate_step_outputs = _pstate.get("step_outputs", {})
    _prev_step_key = None
    if _pstate_step_outputs:
        for _sk in reversed(sorted(_pstate_step_outputs.keys(), key=_step_sort_key)):
            if _sk != next_step:
                _prev_step_key = _sk
                break
    _prev_section = ""
    if _prev_step_key:
        _prev_out = _pstate_step_outputs[_prev_step_key]
        _prev_sha = _prev_out.get("sha", "")[:7]
        _prev_title = _prev_out.get("title", _prev_step_key)
        _prev_summary = _prev_out.get("summary", "")
        _prev_url = _prev_out.get("artifact_url", "")
        _prev_section = f"🏗️ 前序 Step {_prev_step_key.replace('step','')}「{_prev_title}」✅ ({_prev_sha})\n"
        if _prev_summary:
            _prev_section += f"  └ 💡 {_prev_summary}\n"
        if _prev_url:
            _prev_section += f"  └ 🔗 {_prev_url}\n"

    _step_title = _pconfig.get("steps", {}).get(next_step, {}).get("title", next_step)
    inbox_msg = (
        f"📥 任务分配 — {round_name} Step「{_step_title}」\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_prev_section}\n"
        f"📄 参考资料:\n"
        f"  📄 需求：{req_url}\n"
        f"  📋 WORK_PLAN：{plan_url}\n\n"
        f"🎯 你的任务: 请按技术方案完成 {next_step}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"完成后: git push dev → !step_complete {next_step} --output <sha>"
    )

    # Persist inbox message
    write_chat_log(pm_name, inbox_msg, channel=inbox_ch)
    ms.save_message(
        msg_id=str(uuid.uuid4()), msg_type="broadcast",
        from_agent="system", from_name=pm_name,
        content=inbox_msg, ts=time.time(),
        data_dir=config.DATA_DIR, channel=inbox_ch,
    )

    # Send to target agent's connections (unicast)
    inbox_payload = json.dumps({
        "type": "broadcast", "channel": inbox_ch,
        "from_name": pm_name, "from": pm_name,
        "agent_id": pm_agent_id,       # ← R69 B1
        "from_agent": pm_agent_id,     # ← R69 B1
        "content": inbox_msg, "ts": time.time(),
    })
    conns = _connections.get(target_agent_id, set())
    for conn in list(conns):
        try:
            if hasattr(conn, "send_str"):
                await conn.send_str(inbox_payload)
            elif hasattr(conn, "send"):
                await conn.send(inbox_payload)
        except Exception:
            pass

    logger.info("Inbox task [%s] %s → %s", round_name, pm_name, target_agent_id[:12])

    # 🏠 工作室轻量通知
    ws_obj = ws_mod.get_workspace(workspace_id)
    if ws_obj:
        users = auth.get_users()
        target_name = users.get(target_agent_id, {}).get("name", target_agent_id[:12])
        notify_msg = f"@{target_name} 🔔 Step「{_step_title}」已分配，请查看收件箱 📥"
        _persist_broadcast(workspace_id, "系统", notify_msg)
        notify_payload = json.dumps({
            "type": "broadcast", "channel": workspace_id,
            "from_name": "系统", "from": "系统",
            "content": notify_msg, "ts": time.time(),
        })
        for member_id in ws_obj.members:
            for conn in list(_connections.get(member_id, set())):
                try:
                    if hasattr(conn, "send_str"):
                        await conn.send_str(notify_payload)
                    elif hasattr(conn, "send"):
                        await conn.send(notify_payload)
                except Exception:
                    pass


async def _cmd_step_complete(sender_id: str, params: dict) -> str:
    """标记 Step 完成，自动点名下一人。
    用法：!step_complete <step_name> [--output <commit/file>]
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_complete <step_name> [--output <commit/file>]"
    step_name = positional[0].lower()
    output_ref = params.get("output", "")

    # ── R65 B1: Auto-detect SHA when --output is missing ──
    if not output_ref and config.ENABLE_GIT_SYNC:
        try:
            branch = config.GIT_SYNC_BRANCH
            proc = await asyncio.create_subprocess_exec(
                "git", "log", "-1", "--format=%H", f"origin/{branch}",
                cwd=config.REPO_PATH,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode == 0:
                sha = stdout.decode().strip()
                if sha:
                    output_ref = sha
                    logger.info("[R65 B1] 自动检测最新 SHA: %s", sha)
            else:
                logger.warning("[R65 B1] git log 失败: %s", stderr.decode().strip())
        except Exception as e:
            logger.warning("[R65 B1] 自动检测 SHA 异常: %s", e)
    # ── R65 B1: End ──

    if not output_ref:
        return "❌ 缺少 --output <sha>，且无法自动检测最新 commit"

    sender_ch = persistence.get_agent_channel(sender_id) or p.LOBBY
    ws_obj = ws_mod.get_workspace(sender_ch)
    if not ws_obj:
        return "❌ 请在工作区中使用此命令"

    # 从 ws name 提取 round_name
    round_name = None
    for rname, pstate in _PIPELINE_STATE.items():
        if pstate.get("ws_id") == sender_ch:
            round_name = rname
            break
    if not round_name:
        return "❌ 当前工作区无活跃管线（可能已结束或被手动创建）"

    # ── R55 E: Mode check ──
    # In manual mode, only the step's role can advance
    pstate = _PIPELINE_STATE.get(round_name, {})
    # ── R70 Fix: step_config always defined (was inside manual block) ──
    step_config = _get_step_config(round_name)
    if pstate.get("mode", "auto") == "manual":
        step_role = step_config.get(step_name, {}).get("role", "")
        if step_role:
            users = auth.get_users()
            sender_role = users.get(sender_id, {}).get("role", "member")
            if sender_role != step_role and not auth.is_global_admin(sender_id):
                return f"❌ manual 模式下仅 {step_role} 可推进 Step「{step_name}」"

    # ── R55 C: Git commit verification ──
    if output_ref:
        git_ok, git_msg = await _verify_git_commit(output_ref)
        if not git_ok:
            return git_msg  # ❌ prevents advance

    # ── R55 A: 2s serialization buffer ──
    buffer_key = f"{round_name}:{step_name}"
    last_ts = _step_advance_buffer.get(buffer_key, 0.0)
    if time.time() - last_ts < 2.0:
        return f"❌ {step_name} 正在被推进中（2 秒序列化缓冲），请稍后重试"
    _step_advance_buffer[buffer_key] = time.time()

    # 提取 ws_id
    ws_id = sender_ch

    # 标记当前 Task completed
    tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
    current_task = None
    for t in tasks:
        if t.get("name") == step_name and t.get("state") != p.TaskState.COMPLETED.value:
            current_task = t
            break
    if not current_task:
        return f"❌ 未找到 Step「{step_name}」的活跃 Task（可能已完成）"

    task_update_params = {
        "_positional": [current_task["id"]],
        "state": p.TaskState.COMPLETED.value,
        "output": output_ref,
    }
    task_result = await _cmd_task_update(sender_id, task_update_params)

    # ── R57: Clear backup_active marker on step completion ──
    pstate.pop("backup_active", None)

    # ── R66 B1 + R69 A1: Record step output with context ──
    pstate_b1 = _PIPELINE_STATE.get(round_name)
    if pstate_b1:
        step_outputs = pstate_b1.setdefault("step_outputs", {})
        step_outputs[step_name] = {
            "sha": output_ref or "",
            "title": step_config.get(step_name, {}).get("title", step_name),
            "output_desc": step_config.get(step_name, {}).get("output_desc", ""),
            "summary": params.get("summary", step_config.get(step_name, {}).get("output_desc", "")),
            "artifact_url": params.get("artifact_url",
                _infer_artifact_url(step_name, round_name)),
            "timestamp": time.time(),
        }

    # 查 Step 映射表 → 找下一角色
    step_config = _get_step_config(round_name)
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
    current_idx = None
    for i, k in enumerate(step_keys):
        if k == step_name:
            current_idx = i
            break
    if current_idx is None or current_idx + 1 >= len(step_keys):
        # 最后一步 → 管线结束
        # R48 B: 在清理前提取触发者信息
        triggerer_id = _PIPELINE_STATE.get(round_name, {}).get("triggerer_id", "")

        close_result = await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})
        if "❌" in str(close_result):
            return f"❌ 管线关闭失败，请手动处理：\n{close_result}"
        set_lobby_paused(False)

        # ── R48 B: 写入 _admin 频道完结通知 ──
        try:
            admin_channel = p.ADMIN_CHANNEL
            cleanup_msg = (
                f"🔔 [PIPELINE_COMPLETE] {round_name} — 所有 Step 已完结 ✅\n"
                f"最终产出: {output_ref}\n"
                f"工作室已关闭，大厅已恢复接收"
            )
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=cleanup_msg, ts=time.time(),
                data_dir=config.DATA_DIR, channel=admin_channel,
            )
            write_chat_log("系统", cleanup_msg, channel=admin_channel)
        except Exception:
            pass
        # ── R48 B: End ──

        _clear_pipeline_state(round_name)

        return (
            f"🏁 **{round_name} 管线已完成！**\n"
            f"  🎯 产出: {output_ref}\n"
            f"  {task_result}\n"
            f"  工作室已关闭，大厅已恢复接收"
        )

    next_step = step_keys[current_idx + 1]
    next_role = step_config[next_step]["role"]
    # ── R59 C: Apply role override if configured ──
    _role_overrides = getattr(config, "PIPELINE_ROLE_OVERRIDES", {})
    if next_step in _role_overrides:
        next_role = _role_overrides[next_step]
    # ── R59 C: End role override ──

    # ── R43 D: Resolve next role display name ──
    # ── R49 B: Use agent cards if available ──
    users = auth.get_users()
    cards = ac_mod.get_all_cards()
    if cards:
        matched = _find_agents_by_role(next_role, ws_obj.members, cards)
        next_role_names = [
            users.get(aid, {}).get("name", aid[:12])
            for aid in matched
        ]
    else:
        next_role_names = [
            users.get(aid, {}).get("name", aid[:12])
            for aid in ws_obj.members
            if users.get(aid, {}).get("role", "member") == next_role
        ]
    next_role_display = ", ".join(next_role_names) if next_role_names else next_role

    # ── R66 B2: Render context for rollcall ──
    _b2_step_outputs = pstate.get("step_outputs", {}) if pstate else {}
    _b2_next_context = step_config.get(next_step, {}).get("context", {})
    _b2_rendered = _render_context(_b2_next_context, round_name, _b2_step_outputs)
    _b2_context_lines = []
    for _k, _v in _b2_rendered.items():
        if _v:
            _labels = {
                "requirements_url": "📄 需求",
                "work_plan_url": "📋 WORK_PLAN",
                "tech_plan_url": "🏗️ 技术方案",
                "bug_report_url": "🐛 Bug 报告",
            }
            _label = _labels.get(_k, f"📎 {_k}")
            _b2_context_lines.append(f"  {_label}: {_v}")
    _b2_suffix = "\n" + "\n".join(_b2_context_lines) if _b2_context_lines else ""

    # ── R55 F: Targeted handoff (replace broadcast rollcall) ──
    # Send MSG_SET_ACTIVE_CHANNEL + task notification only to next step's agents
    context_summary = f"上一 Step「{step_name}」产出: {output_ref}"
    targeted_notify = f"🎯 新任务：{round_name} {next_step} ({next_role})\n{context_summary}{_b2_suffix}"

    # ── R57 A: Online pre-check + rollcall with backup fallback ──
    member_ids = list(ws_obj.members)

    # Read primary/backup config
    primary_role = step_config[next_step].get("primary")
    backup_role = step_config[next_step].get("backup")

    # Resolve primary agent
    primary_agents: list[str] = []
    if cards and primary_role:
        primary_agents = _find_agents_by_role(primary_role, member_ids, cards)

    if not primary_agents:
        # No primary config → fallback to original full-notify behaviour (A-9 compat)
        if cards:
            target_agents = _find_agents_by_role(next_role, member_ids, cards)
        else:
            target_agents = [
                aid for aid in member_ids
                if users.get(aid, {}).get("role", "member") == next_role
            ]
        for agent_id in target_agents:
            await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
        rollcall_result = f"📨 已通知 {next_role_display}（{len(target_agents)} 人）接管 {next_step}"
    else:
        target_agents = []
        primary_agent = primary_agents[0]
        primary_name = users.get(primary_agent, {}).get("name", primary_agent[:12])
        conns = _connections.get(primary_agent, set())

        if not conns:
            # ── Primary offline → direct backup, 0s wait ──
            rollcall_result = await _r57_switch_to_backup(
                round_name, next_step, next_role,
                backup_role, member_ids, cards, users,
                ws_obj, sender_ch, targeted_notify, primary_name,
                reason="primary_offline",
            )
        else:
            # ── R68 A3: inbox task assignment + workspace notification ──
            if next_role == "arch":
                pm_name = config.PIPELINE_ARCH_FROM_NAME
            else:
                pm_name = config.PIPELINE_PM_NAME

            # Send full task to inbox
            await _send_inbox_task(
                target_agent_id=primary_agent,
                round_name=round_name,
                next_step=next_step,
                step_config=step_config,
                output_ref=output_ref,
                workspace_id=sender_ch,
                pm_name=pm_name,
                pm_agent_id=sender_id,  # ← R69 B1
            )

            # Start 30s rollcall timer (keep existing rollcall logic)
            ack_received = await _r57_wait_for_ack(primary_agent, timeout=30)

            if ack_received:
                # Primary confirmed ✓ normal handoff
                if cards:
                    target_agents = _find_agents_by_role(next_role, member_ids, cards)
                else:
                    target_agents = [
                        aid for aid in member_ids
                        if users.get(aid, {}).get("role", "member") == next_role
                    ]
                for agent_id in target_agents:
                    await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
                rollcall_result = f"✅ 主角 {primary_name} 已确认，正常交接 {next_step}"
            else:
                # Primary 30s no response → switch to backup
                rollcall_result = await _r57_switch_to_backup(
                    round_name, next_step, next_role,
                    backup_role, member_ids, cards, users,
                    ws_obj, sender_ch, targeted_notify, primary_name,
                    reason="primary_timeout",
                )

    # 创建下一步的 Task
    next_task_result = await _cmd_task_create(sender_id, {
        "context": round_name,
        "name": next_step,
        "role": next_role,
    })

    # ── R58 C2: Record notification status to pstate ──
    step_notifications = pstate.setdefault("step_notifications", {})
    step_notifications[next_step] = {
        "status": "notified",
        "notified_at": time.time(),
        "target_agents": target_agents,
    }
    # ── R58 C2: End notification status ──

    # ── R59 B3: PM auto-fallback monitor for dev ──
    # dev(爱泰) 无法通过 ws-bridge 代码自动触发（方向 A 实验确认任何 from_name 均无效）。
    # B3 兜底成为 dev 触发的主要通道（而非备用）。
    if next_role == "dev" and next_step != "step6":
        asyncio.create_task(_r59_auto_fallback_monitor(
            round_name=round_name,
            next_step=next_step,
            next_role=next_role,
            primary_agent=locals().get('primary_agent', None),
            primary_name=locals().get('primary_name', next_role),
            sender_ch=sender_ch,
            ws_obj=ws_obj,
            timeout_minutes=5,
        ))
    # ── R59 B3: End ──

    # 更新管线状态
    _update_pipeline_step(round_name, next_step)

    # 通知 PM（在 _admin 频道发进度）
    try:
        admin_channel = p.ADMIN_CHANNEL
        notify_msg = (
            f"📋 {round_name} 进度：{step_name} ✅ → "
            f"下一棒 {next_role}（{next_step}）产出: {output_ref or '(未提供)'}"
        )
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent="系统", from_name="系统",
            content=notify_msg, ts=time.time(),
            data_dir=config.DATA_DIR, channel=admin_channel,
        )
    except Exception:
        pass

    # ── R43 C: Send clear alert if watchdog was active ──
    if _clear_watchdog_alert(round_name, step_name):
        await _send_clear_alert(round_name, step_name, output_ref)

    # ── R63 Phase 2: Step-complete → clear old timer, start next step timer ──
    if _ENABLE_R63_TIMEOUT:
        timeout_tracker.clear_timer(round_name)
        _step_timeout_mins = step_config.get(next_step, {}).get("timeout_minutes",
            int(step_config.get(next_step, {}).get("timeout_hours", 6) * 60))
        timeout_tracker.start_timer(round_name, next_step, int(_step_timeout_mins))
    # ── R63 Phase 2: End ──

    # ── R63 Phase 4: Start ACK state machine for next step assignment ──
    if _ENABLE_R63_ACK:
        ack_key = f"{round_name}/{next_step}"
        _step_ack_states[ack_key] = {
            "state": "SENT",
            "agent_id": primary_agent if 'primary_agent' in dir() and primary_agents else "",
            "sent_at": time.time(),
            "deadline": time.time() + 30,
            "delivery_sent": 0,
        }
        asyncio.create_task(_ack_timeout_task(ack_key))
    # ── R63 Phase 4: End ──

    # ── R53 D: Enhanced return value with ACK confirm ──
    # ── R55 F: Use targeted handoff result ──
    return (
        f"✅ **{step_name} 完成** → 交接给 {next_role} {next_step}\n"
        f"  📨 已定向通知 {next_role_display}（{len(target_agents)} 人）接管\n"
        f"  {task_result}\n"
        f"  {next_task_result}"
    )


# ── R55 F: Targeted send helper ────────────────────────────


async def _send_to_agent(agent_id: str, text: str, ws_id: str = "") -> bool:
    """Send a text message directly to a specific agent (not broadcast).
    If the agent has live connections, send the text. If not, and ws_id
    is provided, fall back to broadcasting to all workspace members.
    Returns True if at least one connection received it.
    """
    conns = _connections.get(agent_id, set())
    if not conns:
        # Offline fallback: broadcast to workspace members
        if ws_id:
            ws_obj = ws_mod.get_workspace(ws_id)
            if ws_obj:
                fallback = json.dumps({
                    "type": "broadcast",
                    "channel": ws_id,
                    "from_name": "系统",
                    "content": text,
                    "ts": time.time(),
                })
                for member_id in ws_obj.members:
                    for conn in list(_connections.get(member_id, set())):
                        try:
                            if hasattr(conn, "send_str"):
                                await conn.send_str(fallback)
                            elif hasattr(conn, "send"):
                                await conn.send(fallback)
                        except Exception:
                            pass
                write_chat_log("系统", f"[回退广播 @{ws_id}] {text}", channel=ws_id)
        else:
            write_chat_log("系统", f"[定向通知 @{_get_agent_display(agent_id)}] {text}")
        return False
    payload = {
        "type": p.MSG_BROADCAST,
        "from_agent": "系统",
        "from_name": "系统",
        "content": text,
        "ts": time.time(),
    }
    sent = False
    for ws in conns:
        try:
            await _send(ws, payload)
            sent = True
        except Exception:
            pass
    if not sent:
        write_chat_log("系统", f"[定向通知 @{_get_agent_display(agent_id)}] {text}")
    return sent


# ── R57 A: Backup takeover handler ──────────────────────────
async def _r57_switch_to_backup(
    round_name: str, next_step: str, next_role: str,
    backup_role: str | None, member_ids: list[str],
    cards: dict, users: dict, ws_obj, sender_ch: str,
    targeted_notify: str, primary_name: str,
    reason: str,
) -> str:
    """R57: 主角离线或无响应时，切换备用接替。

    reason: "primary_offline" | "primary_timeout"
    返回 rollcall_result 字符串。
    """
    # Broadcast swap announcement to workspace
    if reason == "primary_offline":
        swap_msg = f"⚠️ 主角 {primary_name} 离线，{next_step} 由备用接替"
    else:
        swap_msg = f"⚠️ 主角 {primary_name} 未响应，{next_step} 由备用接替"
    _persist_broadcast(sender_ch, "系统", swap_msg)

    backup_assigned = False

    # Find backup agent
    backup_agents: list[str] = []
    if cards and backup_role:
        backup_agents = _find_agents_by_role(backup_role, member_ids, cards)
    if not backup_agents:
        # No backup config → notify all matching role (A-9 compatibility)
        if cards:
            backup_agents = _find_agents_by_role(next_role, member_ids, cards)
        else:
            backup_agents = [
                aid for aid in member_ids
                if users.get(aid, {}).get("role", "member") == next_role
            ]

    for backup_agent in backup_agents:
        backup_conns = _connections.get(backup_agent, set())
        backup_name = users.get(backup_agent, {}).get("name", backup_agent[:12])
        if backup_conns:
            # Backup online → targeted notification with full context
            backup_notify = targeted_notify + "\n（🔧 您作为备用接替此 Step）"
            await _send_to_agent(backup_agent, backup_notify, ws_id=sender_ch)
            backup_assigned = True
            # Record backup_active in pipeline state for !pipeline_status marker
            for rname, pstate in _PIPELINE_STATE.items():
                if pstate.get("ws_id") == sender_ch:
                    pstate["backup_active"] = {"step": next_step, "role": backup_role or next_role}
                    break

    if not backup_assigned:
        # Backup also offline → system broadcast in workspace
        critical_msg = f"🔴 {next_step} 主角和备用均不在线，等待协调"
        _persist_broadcast(sender_ch, "系统", critical_msg)
        # _admin channel log
        try:
            admin_channel = p.ADMIN_CHANNEL
            admin_msg = f"📋 {round_name} | {next_step} | 主角+备用均离线，需人工介入"
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=admin_msg, ts=time.time(),
                data_dir=config.DATA_DIR, channel=admin_channel,
            )
            write_chat_log("系统", admin_msg, channel=admin_channel)
        except Exception:
            pass

    # _admin channel: log the swap
    try:
        admin_channel = p.ADMIN_CHANNEL
        log_msg = f"📋 {round_name} | {next_step} | {reason.replace('_', ' ')} → 备用接替"
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent="系统", from_name="系统",
            content=log_msg, ts=time.time(),
            data_dir=config.DATA_DIR, channel=admin_channel,
        )
        write_chat_log("系统", log_msg, channel=admin_channel)
    except Exception:
        pass

    return f"🔄 {next_step} — 由备用接替（{reason.replace('_', ' ')}）"


async def _r57_wait_for_ack(agent_id: str, timeout: int = 30) -> bool:
    """等待 agent 在 timeout 秒内回复确认消息。返回是否收到确认。

    使用 asyncio.Event 实现点名等待。当 agent 在工作室发送任意消息时，
    通过 ACK 监听钩入点触发 event set。
    """
    event = asyncio.Event()
    _r57_rollcall_events[agent_id] = event
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False
    finally:
        _r57_rollcall_events.pop(agent_id, None)


# ── R59 B3: PM auto-fallback monitor ──────────────────────────


async def _r59_auto_fallback_monitor(
    round_name: str, next_step: str, next_role: str,
    primary_agent: str | None, primary_name: str,
    sender_ch: str, ws_obj,
    timeout_minutes: int = 5,
) -> None:
    """R59 B3: PM 自动兜底 — 检查 dev 是否在超时内响应。

    R59 方向 A 实验证实 dev(爱泰) 对任何 from_name 均无响应。
    此兜底机制成为 dev 触发的主要通道（而非备用）。

    超时后：
    1. 在工作室内输出催促消息（@bot 点名）
    2. 通过 _admin 频道日志通知项目负责人（由 TG 桥接转发）
    """
    await asyncio.sleep(timeout_minutes * 60)

    try:
        # 检查 pipeline_state 中的 notification status
        pstate = _PIPELINE_STATE.get(round_name, {})
        step_notif = pstate.get("step_notifications", {}).get(next_step, {})
        ack_status = step_notif.get("ack_status", "")

        # 检查是否有活跃 Task（表示 bot 已响应并开始工作）
        has_active_task = False
        try:
            tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
            has_active_task = any(
                t.get("name") == next_step and
                t.get("state") not in ("completed", "pending")
                for t in tasks
            )
        except Exception:
            pass

        already_responded = has_active_task or ack_status in ("acknowledged", "completed")

        if not already_responded:
            # Bot 未响应 → 在工作室内催促
            reminder_msg = (
                f"@{primary_name} ⏰ Step「{next_step}」已通知 {timeout_minutes} 分钟，"
                f"请确认收到。若无法响应，请联系项目负责人处理。"
            )
            _persist_broadcast(sender_ch, config.PIPELINE_PM_NAME, reminder_msg)
            reminder_payload = json.dumps({
                "type": "broadcast", "channel": sender_ch,
                "from_name": config.PIPELINE_PM_NAME, "from": config.PIPELINE_PM_NAME,
                "content": reminder_msg, "ts": time.time(),
            })
            for member_id in ws_obj.members:
                for conn in list(_connections.get(member_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(reminder_payload)
                        elif hasattr(conn, "send"):
                            await conn.send(reminder_payload)
                    except Exception:
                        pass

            # TG 通知项目负责人（走 _admin 频道日志，由 TG 桥接转发）
            try:
                admin_channel = p.ADMIN_CHANNEL
                tg_alert = (
                    f"📋 [R59_FALLBACK] {round_name} | Step「{next_step}」({next_role}) "
                    f"已通知 {timeout_minutes} 分钟但 bot {primary_name} 未响应。\n"
                    f"工作室: {sender_ch}\n"
                    f"请检查是否需要 TG 转发触发。"
                )
                ms.save_message(
                    msg_id=str(uuid.uuid4()), msg_type="broadcast",
                    from_agent="系统", from_name="系统",
                    content=tg_alert, ts=time.time(),
                    data_dir=config.DATA_DIR, channel=admin_channel,
                )
                write_chat_log("系统", tg_alert, channel=admin_channel)
            except Exception:
                pass
    except Exception as e:
        write_chat_log("系统", f"[R59_FALLBACK 异常] {e}")
# ── R59 B3: End ──
# ── R55 B: Step reject command ─────────────────────────────


async def _cmd_step_reject(sender_id: str, params: dict) -> str:
    """退回 Step N 到 pending 状态，附退回理由。
    用法：!step_reject <step_name> --reason <原因>
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_reject <step_name> --reason <原因>"
    step_name = positional[0].lower().strip()
    reason = params.get("reason", "")
    if not reason:
        return "❌ 退回必须附理由：!step_reject <step_name> --reason <原因>"

    # 解析管线上下文
    sender_ch = persistence.get_agent_channel(sender_id) or p.LOBBY
    ws_obj = ws_mod.get_workspace(sender_ch)
    if not ws_obj:
        return "❌ 请在工作区中使用此命令"

    round_name = None
    for rname, pstate in _PIPELINE_STATE.items():
        if pstate.get("ws_id") == sender_ch:
            round_name = rname
            break
    if not round_name:
        return "❌ 当前工作区无活跃管线（可能已结束或被手动创建）"

    # 前置校验：step 必须在 PIPELINE_STEP_MAP 中
    step_config = _get_step_config(round_name)
    if step_name not in step_config:
        return f"❌ Step「{step_name}」不存在于管线映射中"

    # 找到当前 active task for this step
    tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
    current_task = None
    for t in tasks:
        if t.get("name") == step_name and t.get("state") != p.TaskState.COMPLETED.value:
            current_task = t
            break
    if not current_task:
        return f"❌ Step「{step_name}」没有活跃 Task，无法退回"

    # 检查退回次数上限
    reject_count = current_task.get("reject_count", 0) + 1
    if reject_count >= p.TASK_REJECT_CEILING:
        # R55 W-3: 第 TASK_REJECT_CEILING 次退回 → 升级给 PM
        # TASK_REJECT_CEILING=2 表示第 2 次退回（即 2 次机会后）升级
        # 第 3 次退回 → 升级给 PM
        try:
            admin_channel = p.ADMIN_CHANNEL
            escalation_msg = (
                f"🚨 [ESCALATION] {round_name} {step_name} 已被退回 "
                f"{reject_count} 次，需 PM 介入协调\n"
                f"最近理由: {reason}\n"
                f"退回者: {sender_id[:12]}"
            )
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=escalation_msg, ts=time.time(),
                data_dir=config.DATA_DIR, channel=admin_channel,
            )
        except Exception:
            pass
        return (
            f"🚨 {step_name} 已被退回 {reject_count} 次，"
            f"超过上限（{p.TASK_REJECT_CEILING}），自动升级给 PM 协调"
        )

    # 处理原 task: 标记 INPUT_REQUIRED + 写入 reject_count
    ts.update_state(current_task["id"], p.TaskState.INPUT_REQUIRED.value, config.DATA_DIR)
    ts.increment_reject_count(current_task["id"], config.DATA_DIR)

    # 写入退回记录到 _PIPELINE_STATE
    pstate = _PIPELINE_STATE.setdefault(round_name, {})
    rejected_steps = pstate.setdefault("rejected_steps", {})
    rejected_steps[step_name] = {
        "reject_count": reject_count,
        "last_reason": reason,
        "rejected_by": sender_id,
        "rejected_at": time.time(),
    }

    # 更新 step 指针（如果当前已推进到此 step 之后，回退）
    current_pstate = _PIPELINE_STATE.get(round_name, {})
    current_step = current_pstate.get("current_step", "")
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
    current_idx = None
    target_idx = None
    for i, k in enumerate(step_keys):
        if k == step_name:
            target_idx = i
        if k == current_step:
            current_idx = i
    if target_idx is not None and current_idx is not None and current_idx > target_idx:
        _update_pipeline_step(round_name, step_name)

    # 创建新 task（重新从 SUBMITTED 开始）
    next_task_result = await _cmd_task_create(sender_id, {
        "context": round_name,
        "name": step_name,
        "role": step_config[step_name].get("role", ""),
    })

    # 通知被退回角色（方向 F：定向发送）
    users = auth.get_users()
    step_role = step_config[step_name].get("role", "")
    cards = ac_mod.get_all_cards()
    member_ids = list(ws_obj.members)
    if cards:
        target_agents = _find_agents_by_role(step_role, member_ids, cards)
    else:
        target_agents = [
            aid for aid in member_ids
            if users.get(aid, {}).get("role", "member") == step_role
        ]
    reject_notify = f"🔄 {step_name} 被退回（第 {reject_count} 轮）：{reason}"
    for agent_id in target_agents:
        await _send_to_agent(agent_id, reject_notify, ws_id=sender_ch)

    # _admin 频道记录退回日志（PM 可见）
    try:
        admin_channel = p.ADMIN_CHANNEL
        log_msg = (
            f"📋 {round_name} 退回：{step_name} ❌（第 {reject_count} 轮）\n"
            f"  理由：{reason}\n"
            f"  退回者：{sender_id[:12]}"
        )
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent="系统", from_name="系统",
            content=log_msg, ts=time.time(),
            data_dir=config.DATA_DIR, channel=admin_channel,
        )
    except Exception:
        pass

    return f"🔄 {step_name} 已退回（第 {reject_count} 轮）：{reason}\n{next_task_result}"


# ── R69 B2: Workspace reset ──
async def _cmd_workspace_reset(sender_id: str, params: dict) -> str:
    """重置工作室：关闭当前工作室 + 清理管线状态 + 成员频道回大厅。"""
    sender_ch = persistence.get_agent_channel(sender_id) or p.LOBBY
    if not sender_ch:
        return "❌ 无法确定当前工作区"
    ws_obj = ws_mod.get_workspace(sender_ch)
    if not ws_obj:
        return "❌ 未找到活跃工作室"
    ws_id = ws_obj.id
    ws_name = ws_obj.name
    close_result = await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})
    await _broadcast_active_channel(p.LOBBY)
    for pid, pst in list(_PIPELINE_STATE.items()):
        if pst.get("ws_id") == ws_id:
            _PIPELINE_STATE[pid]["active"] = False
    return f"✅ 工作室「{ws_name}」({ws_id[:12]}) 已重置 — 归档 + 回大厅 + 管线清理完成"


# ── R50: Step handoff command ──────────────────────────────────────


async def _cmd_step_handoff(sender_id: str, params: dict) -> str:
    """标记 Step 完成并交接给下一角色，同时广播 MSG_SET_ACTIVE_CHANNEL。
    用法：!step_handoff <step_name> --output <commit/file>
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_handoff <step_name> --output <commit/file>"
    step_name = positional[0].lower()
    output_ref = params.get("output", "")
    if not output_ref:
        return "❌ --output 为必填参数，请提供 commit SHA 或文件路径"

    sender_ch = persistence.get_agent_channel(sender_id) or p.LOBBY
    ws_obj = ws_mod.get_workspace(sender_ch)
    if not ws_obj:
        return "❌ 请在工作区中使用此命令"

    # Extract round_name from pipeline state
    round_name = None
    for rname, pstate in _PIPELINE_STATE.items():
        if pstate.get("ws_id") == sender_ch:
            round_name = rname
            break
    if not round_name:
        return "❌ 当前工作区无活跃管线（可能已结束或被手动创建）"

    ws_id = sender_ch

    # Mark current Task completed
    tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
    current_task = None
    for t in tasks:
        if t.get("name") == step_name and t.get("state") != p.TaskState.COMPLETED.value:
            current_task = t
            break
    if not current_task:
        return f"❌ 未找到 Step「{step_name}」的活跃 Task（可能已完成）"

    task_update_params = {
        "_positional": [current_task["id"]],
        "state": p.TaskState.COMPLETED.value,
        "output": output_ref,
    }
    task_result = await _cmd_task_update(sender_id, task_update_params)

    # Look up next step
    step_config = _get_step_config(round_name)
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
    current_idx = None
    for i, k in enumerate(step_keys):
        if k == step_name:
            current_idx = i
            break
    if current_idx is None or current_idx + 1 >= len(step_keys):
        # Final step → pipeline complete
        close_result = await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})
        if "❌" in str(close_result):
            return f"❌ 管线关闭失败，请手动处理：\n{close_result}"
        set_lobby_paused(False)
        _clear_pipeline_state(round_name)

        # Cleanup progress notification (R47 A4)
        try:
            cleanup_msg = f"📊 {round_name} 管线已完成 ✅ 所有 Step 已完结，工作室已关闭"
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=cleanup_msg, ts=time.time(),
                data_dir=config.DATA_DIR, channel=p.ADMIN_CHANNEL,
            )
            write_chat_log("系统", cleanup_msg, channel=p.ADMIN_CHANNEL)
        except Exception:
            pass

        return (
            f"🏁 **{round_name} 管线已完成！**\n"
            f"  {task_result}\n"
            f"  工作室已关闭，大厅已恢复接收"
        )

    next_step = step_keys[current_idx + 1]
    next_role = step_config[next_step]["role"]

    # Resolve next role display names
    users = auth.get_users()
    next_role_names = [
        users.get(aid, {}).get("name", aid[:12])
        for aid in ws_obj.members
        if users.get(aid, {}).get("role", "member") == next_role
    ]
    next_role_display = ", ".join(next_role_names) if next_role_names else next_role

    # Rollcall next role
    # ── R66 B2/B3: Render context for handoff rollcall ──
    _h_pstate = _PIPELINE_STATE.get(round_name, {})
    _h_step_outputs = _h_pstate.get("step_outputs", {})
    _h_next_context = step_config.get(next_step, {}).get("context", {})
    _h_rendered = _render_context(_h_next_context, round_name, _h_step_outputs)
    _h_context_lines = []
    for _k, _v in _h_rendered.items():
        if _v:
            _h_context_lines.append(f"  📎 {_k}: {_v}")
    _h_suffix = "\n" + "\n".join(_h_context_lines) if _h_context_lines else ""
    context_summary = f"上一 Step「{step_name}」产出: {output_ref}"
    rollcall_result = await _cmd_rollcall_next(sender_id, {
        "_positional": [next_role],
        "context": f"{round_name} {next_step}: {context_summary}{_h_suffix}",
    })

    # ── R68 A3: Send inbox task to primary agent (with workspace fallback) ──
    _h_cards = ac_mod.get_all_cards()
    _h_member_ids = list(ws_obj.members)
    _h_primary_role = step_config.get(next_step, {}).get("primary")
    _h_primary_agents = (
        _find_agents_by_role(_h_primary_role, _h_member_ids, _h_cards)
        if _h_cards and _h_primary_role else []
    )
    if _h_primary_agents:
        await _send_inbox_task(
            target_agent_id=_h_primary_agents[0],
            round_name=round_name,
            next_step=next_step,
            step_config=step_config,
            output_ref=output_ref,
            workspace_id=ws_id,
            pm_name="PM",
            pm_agent_id=sender_id,  # ← R69 B1
        )
    else:
        _h_fb_users = auth.get_users()
        _h_fb_role_names = [
            _h_fb_users.get(aid, {}).get("name", aid[:12])
            for aid in ws_obj.members
            if _h_fb_users.get(aid, {}).get("role", "member") == next_role
        ]
        _h_fb_display = ", ".join(_h_fb_role_names) if _h_fb_role_names else next_role
        _h_fb_plan_url = _PIPELINE_CONFIG.get(round_name, {}).get("work_plan_url", "")
        _h_fb_msg = (
            f"@{_h_fb_display} 🚨 Step「{next_step}」到你了！\n\n"
            f"📋 WORK_PLAN：{_h_fb_plan_url}\n"
            f"🔗 上一步产出：{output_ref}\n\n"
            f"请确认收到后开始工作。完成后调用 !step_complete {next_step} --output <sha>"
        )
        _persist_broadcast(ws_id, "系统", _h_fb_msg)
        _h_fb_payload = json.dumps({
            "type": "broadcast", "channel": ws_id,
            "from_name": "系统", "from": "系统",
            "content": _h_fb_msg, "ts": time.time(),
        })
        for _h_fb_mid in ws_obj.members:
            for _h_fb_conn in list(_connections.get(_h_fb_mid, set())):
                try:
                    if hasattr(_h_fb_conn, "send_str"):
                        await _h_fb_conn.send_str(_h_fb_payload)
                    elif hasattr(_h_fb_conn, "send"):
                        await _h_fb_conn.send(_h_fb_payload)
                except Exception:
                    pass
        logger.info("R68 inbox fallback: broadcast @mention to workspace %s (no primary agent for %s)", ws_id, next_role)

    # Create next step Task
    next_task_result = await _cmd_task_create(sender_id, {
        "context": round_name,
        "name": next_step,
        "role": next_role,
    })

    # Update pipeline state
    _update_pipeline_step(round_name, next_step)

    # ★ R50: Broadcast MSG_SET_ACTIVE_CHANNEL to all workspace members
    switch_count = await _broadcast_active_channel(ws_id)

    # Notify PM in _admin channel
    try:
        admin_channel = p.ADMIN_CHANNEL
        notify_msg = (
            f"📋 {round_name} 进度：{step_name} ✅ → "
            f"下一棒 {next_role}（{next_step}）产出: {output_ref or '(未提供)'}"
        )
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent="系统", from_name="系统",
            content=notify_msg, ts=time.time(),
            data_dir=config.DATA_DIR, channel=admin_channel,
        )
    except Exception:
        pass

    # Clear watchdog alert if active
    if _clear_watchdog_alert(round_name, step_name):
        await _send_clear_alert(round_name, step_name, output_ref)

    return (
        f"✅ **{step_name} 完成 → 交接给 {next_role} {next_step}**\n"
        f"  产出: {output_ref}\n"
        f"  MSG_SET_ACTIVE_CHANNEL 已发送至 {switch_count['online_count']} 个在线成员\n"
        f"  ⏳ 等待 {next_role_display} ACK 确认\n"
        f"  {rollcall_result}\n"
        f"  {next_task_result}"
    )


async def _cmd_pipeline_status(sender_id: str, params: dict) -> str:
    """查询当前所有活跃管线的 Step 进度表。"""
    lines = []

    # ── R62: Config-only mode (no state, but config exists) ──
    if _PIPELINE_CONFIG and not _PIPELINE_STATE:
        for round_name, pconfig in sorted(_PIPELINE_CONFIG.items()):
            if round_name in _PIPELINE_STATE:
                continue
            lines.append(f"📊 **{round_name} 管线配置（state 不存在，config 仍在）**")
            lines.append(f"  目标: {pconfig.get('goal', '')}")
            step_config_c = pconfig.get("steps", {})
            for step_key, step_info in sorted(
                step_config_c.items(),
                key=lambda item: _step_sort_key(item[0]),
            ):
                role = step_info.get("role", "?")
                title = step_info.get("title", step_key)
                lines.append(f"  ⏳ {step_key} — {role}（{title}）")
            lines.append("")

    if not _PIPELINE_STATE and not lines:
        # ── R62: If verbose is requested but no state/config, show empty
        if params.get("verbose") or params.get("dump"):
            lines.append("📊 当前无活跃管线（无 _PIPELINE_CONFIG）")
        else:
            return "📊 当前无活跃管线"

    for round_name, pstate in sorted(_PIPELINE_STATE.items()):
        if not pstate.get("active"):
            continue
        lines.append(f"📊 **{round_name} 管线状态**")
        # R48 A: 展示 work_plan_url（如有）
        if pstate.get("work_plan_url"):
            lines.append(f"  📎 WORK_PLAN: {pstate['work_plan_url']}")
        # ── R55 D: Mode marker ──
        mode = pstate.get("mode", "auto")
        mode_icon = "🚀" if mode == "auto" else "📋"
        lines.append(f"  模式: {mode_icon} {mode}")
        # ── R57 C-2: Display member names with online status ──
        ws_id = pstate.get("ws_id", "")
        if ws_id:
            ws_obj_from_state = ws_mod.get_workspace(ws_id)
            if ws_obj_from_state:
                users_for_status = auth.get_users()
                member_info = []
                for mid in ws_obj_from_state.members:
                    name = users_for_status.get(mid, {}).get("name", "")
                    role_label = users_for_status.get(mid, {}).get("role", "")
                    label = name if name else (role_label if role_label else mid[:12])
                    online = "🟢" if mid in _connections and _connections[mid] else "🔴"
                    member_info.append(f"{online}{label}")
                if member_info:
                    lines.append(f"  成员: {' · '.join(member_info)}")
        # ── R55 D: Rejected steps context ──
        rejected_steps = pstate.get("rejected_steps", {})
        if rejected_steps:
            lines.append(f"  🔄 退回记录:")
            for rstep, rinfo in rejected_steps.items():
                lines.append(
                    f"    {rstep}: 第{rinfo['reject_count']}轮 — {rinfo['last_reason'][:40]}"
                )
        step_config = _get_step_config(round_name)
        tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)

        for step_key, step_info in sorted(
            step_config.items(),
            key=lambda item: _step_sort_key(item[0]),
        ):
            role = step_info["role"]

            matched = [t for t in tasks if t.get("name") == step_key]
            task_state = "⏳"
            if matched:
                t = matched[0]
                ts_state = t.get("state", "")
                if ts_state == p.TaskState.COMPLETED.value:
                    task_state = "✅"
                elif ts_state == p.TaskState.WORKING.value:
                    task_state = "🟢"
                elif ts_state == p.TaskState.FAILED.value:
                    task_state = "❌"
                elif ts_state == p.TaskState.SUBMITTED.value:
                    # ★ R53 B-4: Check for active ACK timer
                    if t["id"] in _task_ack_timers:
                        task_state = "⏳"  # waiting_ack
                    else:
                        task_state = "⬜"  # submitted, no pending ack
                elif ts_state == p.TaskState.INPUT_REQUIRED.value:
                    task_state = "🔄"  # R55 B: rejected, needs rework

            current = " ◀ 当前" if step_key == pstate.get("current_step") else ""
            # ── R63 Phase 2: Countdown display on current step ──
            if current and _ENABLE_R63_TIMEOUT:
                remaining_str = timeout_tracker.format_remaining(round_name, step_key)
                current += f" ({remaining_str})"
            # ── R63 Phase 2: End countdown ──
            # ── R63 Phase 4: ACK state display on current step ──
            if current:
                ack_status = _format_ack_status(f"{round_name}/{step_key}")
                if ack_status:
                    current += f" | {ack_status}"
            # ── R63 Phase 4: End ──
            # ── R58 C3: Notification status display ──
            step_notifications = pstate.get("step_notifications", {})
            notify_info = step_notifications.get(step_key, {})
            notify_status = notify_info.get("status", "")
            notify_mark = ""
            if notify_status == "notified":
                notify_mark = " 📨"
            elif notify_status == "acknowledged":
                notify_mark = " ✅ACK"
            elif notify_status == "no_response":
                notify_mark = " ❌静默"
            # ── R58 C3: End notification status ──
            # ── R57 A-6: Backup takeover marker ──
            backup_suffix = ""
            pipeline_backup = pstate.get("backup_active", {})
            if step_key == pipeline_backup.get("step"):
                backup_suffix = "（备用接替）"
            lines.append(f"  {task_state} {step_key} — {role}{current}{backup_suffix}{notify_mark}")

        # ── R65 A4: Git sync status line ──
        if config.ENABLE_GIT_SYNC and _GIT_SYNC_TASK is not None:
            last_sync_ts = pstate.get("_last_git_sync_ts", 0)
            if last_sync_ts:
                delta = int(time.time() - last_sync_ts)
                sync_display = f"{delta}s 前" if delta < 120 else f"{delta // 60}m 前"
            else:
                sync_display = "—"
            pconfig = _PIPELINE_CONFIG.get(round_name, {})
            branch = pconfig.get("git_sync_branch", config.GIT_SYNC_BRANCH) if _PIPELINE_CONFIG.get(round_name, {}) else config.GIT_SYNC_BRANCH
            lines.append(f"  🔄 Git 同步: 启用 ✅（最后检查: {sync_display}, {branch}）")
        # ── R65 A4: End ──

    if not lines:
        return "📊 当前无活跃管线"
    # ── R62: --verbose / --dump: show _PIPELINE_CONFIG summary ──
    if params.get("verbose") or params.get("dump"):
        lines.append("")
        lines.append("📋 _PIPELINE_CONFIG:")
        if _PIPELINE_CONFIG:
            for _rname, _pconf in sorted(_PIPELINE_CONFIG.items()):
                lines.append(f"  [{_rname}] round={_pconf.get('round','')} | goal={_pconf.get('goal','')} | work_plan_url={_pconf.get('work_plan_url','')} | requirements_url={_pconf.get('requirements_url','')}")
                for _sk in sorted(_pconf.get('steps', {}).keys(), key=_step_sort_key):
                    _sc = _pconf['steps'][_sk]
                    lines.append(f"    {_sk}: role={_sc.get('role','')} | title={_sc.get('title','')}")
        else:
            lines.append("  无 _PIPELINE_CONFIG")
    return "\n".join(lines)


# ── R55 E: Pipeline mode switch ─────────────────────────────


async def _cmd_pipeline_mode(sender_id: str, params: dict) -> str:
    """切换管线模式。
    用法：!pipeline_mode <auto|manual>
    """
    positional = params.get("_positional", [])
    if not positional or positional[0] not in ("auto", "manual"):
        return "❌ 用法：!pipeline_mode auto|manual"
    target_mode = positional[0]

    sender_ch = persistence.get_agent_channel(sender_id) or p.LOBBY
    round_name = None
    for rname, pstate in _PIPELINE_STATE.items():
        if pstate.get("ws_id") == sender_ch:
            round_name = rname
            break
    if not round_name:
        return "❌ 当前工作区无活跃管线"

    _PIPELINE_STATE[round_name]["mode"] = target_mode
    icon = "🚀" if target_mode == "auto" else "📋"
    return f"✅ 管线 {round_name} 已切换为 {icon} {target_mode} 模式"


# ── R59 C: Pipeline role override ────────────────────────────


async def _cmd_pipeline_role_override(sender_id: str, params: dict) -> str:
    """覆盖指定 Step 的执行角色。
    用法：!pipeline_role_override <step> --executor <role>

    示例：
      !pipeline_role_override step3 --executor arch
      → Step 3（编码）由 arch 执行而非 dev
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!pipeline_role_override <step> --executor <role>"
    step = positional[0].lower()
    executor = params.get("executor", "")
    if not executor:
        return "❌ 请指定 --executor <role>"

    # 验证 step 存在
    step_config = _load_step_config()
    if step not in step_config:
        return f"❌ Step「{step}」不存在"

    # 保存覆盖到配置
    if not hasattr(config, "PIPELINE_ROLE_OVERRIDES"):
        config.PIPELINE_ROLE_OVERRIDES = {}
    config.PIPELINE_ROLE_OVERRIDES[step] = executor

    original_role = step_config[step]["role"]
    return (
        f"✅ Step「{step}」执行角色覆盖为「{executor}」（原：{original_role}）\n"
        f"📋 约束提醒：若覆盖导致写方案者=编码者，请在 WORK_PLAN 中显式豁免"
    )


# ── R49 B: Agent Card commands ──────────────────────────────────────



async def _cmd_agent_card_list(sender_id: str, params: dict) -> str:
    """Display all current agent cards.
    Also serves as subcommand dispatcher for !agent_card <sub> ... syntax.
    """
    # R49 A: Subcommand dispatch — allow !agent_card get/set/unset/reload/watch
    positional = params.get("_positional", [])
    if positional and positional[0] in ("get", "set", "unset", "reload", "watch"):
        sub_cmd = positional[0]
        sub_params = dict(params)
        sub_params["_positional"] = positional[1:]
        handler_map = {
            "get": _cmd_agent_card_get,
            "set": _cmd_agent_card_set,
            "unset": _cmd_agent_card_unset,
            "reload": _cmd_agent_card_reload,
            "watch": _cmd_agent_card_watch,
        }
        return await handler_map[sub_cmd](sender_id, sub_params)
    # Otherwise list all cards
    cards = ac_mod.get_all_cards()
    if not cards:
        return "No agent cards found."
    lines = ["Agent Cards ({0}):".format(len(cards))]
    for aid, card in sorted(cards.items()):
        name = card.get("display_name", card.get("name", aid[:12]))
        roles = ", ".join(card.get("pipeline_roles", []))
        skills = ", ".join(card.get("skills", []))
        status = card.get("status", "unknown")
        line = "  {0} [{1}] status={2}".format(name, roles, status)
        if skills:
            line += " skills=[{0}]".format(skills)
        lines.append(line)
    return "\n".join(lines)


async def _cmd_agent_card_get(sender_id: str, params: dict) -> str:
    """Show a single agent card.
    Usage: !agent_card get <agent_id>
    """
    positional = params.get("_positional", [])
    if not positional:
        return "Usage: !agent_card get <agent_id>"
    agent_id = positional[0]
    cards = ac_mod.get_all_cards()
    card = cards.get(agent_id)
    if not card:
        return "No card for agent " + agent_id[:24]
    name = card.get("display_name", card.get("name", agent_id[:12]))
    roles = ", ".join(card.get("pipeline_roles", []))
    skills = ", ".join(card.get("skills", []))
    status = card.get("status", "unknown")
    updated = card.get("updated_at", "")
    return "\n".join([
        "Card for " + agent_id[:24],
        "  Name: " + name,
        "  Roles: [" + roles + "]",
        "  Skills: [" + skills + "]",
        "  Status: " + status,
        "  Updated: " + str(updated),
    ])


async def _cmd_agent_card_set(sender_id: str, params: dict) -> str:
    """Set or update an agent card.
    Usage: !agent_card set <agent_id> --role <r1,r2> [--name <display>] [--skills <s1,s2>]
    """
    positional = params.get("_positional", [])
    if not positional:
        return "Usage: !agent_card set <agent_id> --role <r1,r2> [--name <n>] [--skills <s1,s2>]"
    agent_id = positional[0]
    role_str = params.get("role", "")
    if not role_str:
        return "--role is required"
    name = params.get("name", "")
    skills_str = params.get("skills", "")

    cards = ac_mod.get_all_cards()
    card = cards.get(agent_id, {})
    card["pipeline_roles"] = [r.strip() for r in role_str.split(",") if r.strip()]
    if name:
        card["display_name"] = name
    if skills_str:
        card["skills"] = [s.strip() for s in skills_str.split(",") if s.strip()]
    card["status"] = card.get("status", "online")
    card["updated_at"] = time.time()

    ac_mod.update_card(agent_id, card)
    _refresh_role_agent_map()
    roles_display = ", ".join(card["pipeline_roles"])
    name_display = card.get("display_name", agent_id[:12])
    return "Card set: {0} -> {1} roles=[{2}]".format(agent_id[:24], name_display, roles_display)


async def _cmd_agent_card_unset(sender_id: str, params: dict) -> str:
    """Delete an agent card.
    Usage: !agent_card unset <agent_id>
    """
    positional = params.get("_positional", [])
    if not positional:
        return "Usage: !agent_card unset <agent_id>"
    agent_id = positional[0]
    if ac_mod.remove_card(agent_id):
        _refresh_role_agent_map()
        return "Deleted card for " + agent_id[:24]
    return "No card for agent " + agent_id[:24]


async def _cmd_agent_card_reload(sender_id: str, params: dict) -> str:
    """Reload agent cards from disk (no restart needed). R67: also refresh role map."""
    ac_mod.reload_cards()
    _refresh_role_agent_map()
    cards = ac_mod.get_all_cards()
    return "Reloaded agent cards: {0} records, role map refreshed".format(len(cards))


async def _cmd_agent_card_watch(sender_id: str, params: dict) -> str:
    """启动/停止文件变动监听。
    用法：!agent_card watch [start|stop|status]
    """
    global _card_watcher
    positional = params.get("_positional", ["status"])
    if not positional:
        return "用法：!agent_card watch [start|stop|status]"
    sub = positional[0]

    if sub == "start":
        if _card_watcher and _card_watcher.is_running():
            return "✅ 文件监听已在运行"
        _card_watcher = ac_mod.CardFileWatcher(
            ac_mod.get_cards_path(),
            on_change=_refresh_role_agent_map,
        )
        _card_watcher.start()
        return "✅ 文件监听已启动"
    elif sub == "stop":
        if _card_watcher and _card_watcher.is_running():
            _card_watcher.stop()
            return "✅ 文件监听已停止"
        return "⚠️ 无运行中的文件监听"
    else:
        running = _card_watcher is not None and _card_watcher.is_running()
        return "📋 文件监听状态：{}".format("🟢 运行中" if running else "🔴 已停止")


# ── R63 Phase 3: Agent role map + card registration commands ─────


async def _cmd_agent_role_map(sender_id: str, params: dict) -> str:
    """展示当前角色↔Agent 映射表。
    用法：!agent_role_map [--refresh]
    """
    if params.get("refresh"):
        _refresh_role_agent_map()
        cards = ac_mod.get_all_cards()
        # Also rebuild from auth for roles not in cards
        users = auth.get_users()
        for aid, u in users.items():
            role = u.get("role", "member")
            if role and role != "member":
                if role not in _ROLE_AGENT_MAP:
                    _ROLE_AGENT_MAP[role] = []
                if aid not in _ROLE_AGENT_MAP[role]:
                    _ROLE_AGENT_MAP[role].append(aid)

    lines = [f"📋 角色↔Agent 映射表 ({len(_ROLE_AGENT_MAP)} 个角色):"]
    for role, agents in sorted(_ROLE_AGENT_MAP.items()):
        names = []
        for aid in agents:
            display = _get_agent_display(aid)
            online = "🟢" if aid in _connections and _connections[aid] else "🔴"
            names.append(f"{online}{display}")
        lines.append(f"  {role} → {' | '.join(names) if names else '(无)'}")

    # Show unregistered roles
    all_roles = {v.get("role") for v in auth.get_users().values()
                 if v.get("role") and v.get("role") != "member"}
    registered_roles = set(_ROLE_AGENT_MAP.keys())
    unregistered = all_roles - registered_roles
    if unregistered:
        lines.append(f"  ⚠️ 未注册角色: {', '.join(sorted(unregistered))}")

    return "\n".join(lines) if len(lines) > 1 else "📋 当前无角色映射"


async def _cmd_agent_card_register(sender_id: str, params: dict) -> str:
    """强制注册/更新 Agent Card。
    用法：!agent_card register <agent_id> [--name <name>] [--role <role>]
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!agent_card register <agent_id> [--name <name>] [--role <role>]"
    target_id = positional[0]
    name = params.get("name", "")
    role = params.get("role", "")

    users = auth.get_users()
    u = users.get(target_id, {})
    if not name:
        name = u.get("name", target_id[:12])
    if not role:
        role = u.get("role", "member")

    from . import agent_card as ac_mod
    card = ac_mod.register_agent(target_id, name, role, force=True)
    _refresh_role_agent_map()
    return (
        f"✅ Agent Card 已注册：{target_id}\n"
        f"  名称: {name}\n"
        f"  角色: {role}\n"
        f"  pipeline_roles: {card.get('pipeline_roles', [])}"
    )


async def _cmd_agent_card_auto_register(sender_id: str, params: dict) -> str:
    """扫描所有在线 agent，自动补全缺失的 card。
    用法：!agent_card auto-register
    """
    online_agents = list(_connections.keys())
    users = auth.get_users()
    name_map = {aid: users.get(aid, {}).get("name", aid[:12]) for aid in online_agents}
    role_map = {aid: users.get(aid, {}).get("role", "member") for aid in online_agents}

    from . import agent_card as ac_mod
    count = ac_mod.auto_register_missing(online_agents, name_map, role_map)
    _refresh_role_agent_map()

    if count:
        return f"✅ 自动注册了 {count} 个 Agent Card\n  !agent_role_map 查看最新映射表"
    return "✅ 所有在线 Agent 已有 Card，无需注册"


# ── R63 Phase 3: End ──


# ── R35: Admin command registry ──────────────────────────────────

_ADMIN_COMMANDS: dict[str, dict] = {
    "create_workspace": {
        "handler": _cmd_create_workspace, "min_role": 3, "workspace_scope": True,
        "usage": "!create_workspace <name> --members <ids>",
    },
    "close_workspace": {
        "handler": _cmd_close_workspace, "min_role": 3, "workspace_scope": True,
        "usage": "!close_workspace <ws_id> [--reason <text>]",
    },
    "list_workspaces": {
        "handler": _cmd_list_workspaces, "min_role": 3, "workspace_scope": True,
        "usage": "!list_workspaces",
    },
    "list_agents": {
        "handler": _cmd_list_agents, "min_role": 3, "workspace_scope": True,
        "usage": "!list_agents [--role <role>]",
    },
    "agent_status": {
        "handler": _cmd_agent_status, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_status <agent_id>",
    },
    "approve_pairing": {
        "handler": _cmd_approve_pairing, "min_role": 4, "workspace_scope": False,
        "usage": "!approve_pairing <code> [--role <role>]",
    },
    "approve_ws_admin": {
        "handler": _cmd_approve_ws_admin, "min_role": 4, "workspace_scope": False,
        "usage": "!approve_ws_admin --workspace <ws_id> --agent <agent>",
    },
    "reject_ws_admin": {
        "handler": _cmd_reject_ws_admin, "min_role": 4, "workspace_scope": False,
        "usage": "!reject_ws_admin --workspace <ws_id> --agent <agent> --reason <text>",
    },
    "list_pending": {
        "handler": _cmd_list_pending, "min_role": 4, "workspace_scope": False,
        "usage": "!list_pending",
    },
    "audit_log": {
        "handler": _cmd_audit_log, "min_role": 3, "workspace_scope": True,
        "usage": "!audit_log [--limit <n>]",
    },
    "list_workspace_admins": {
        "handler": _cmd_list_workspace_admins, "min_role": 3, "workspace_scope": True,
        "usage": "!list_workspace_admins [--workspace <ws_id>]",
    },
    # ── R38: Task commands ──
    "task_create": {
        "handler": _cmd_task_create, "min_role": 3, "workspace_scope": True,
        "usage": "!task_create --context <R{N}> --name <step> [--role <role>]",
    },
    "task_update": {
        "handler": _cmd_task_update, "min_role": 3, "workspace_scope": True,
        "usage": "!task_update <task_id> --state <new_state> [--output <path>]",
    },
    "task_query": {
        "handler": _cmd_task_query, "min_role": 3, "workspace_scope": True,
        "usage": "!task_query <task_id> | !task_query --context <R{N}>",
    },
    "task_list": {
        "handler": _cmd_task_list, "min_role": 3, "workspace_scope": True,
        "usage": "!task_list [--limit <n>]",
    },
        # ── R49 B: Agent Card commands ──
    "agent_card": {
        "handler": _cmd_agent_card_list, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card [list|get|set|unset|reload] ...",
    },
    "agent_card_list": {
        "handler": _cmd_agent_card_list, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card list",
    },
    "agent_card_get": {
        "handler": _cmd_agent_card_get, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card get <agent_id>",
    },
    "agent_card_set": {
        "handler": _cmd_agent_card_set, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card set <agent_id> --role <r1,r2> [--name <n>]",
    },
    "agent_card_unset": {
        "handler": _cmd_agent_card_unset, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card unset <agent_id>",
    },
    "agent_card_reload": {
        "handler": _cmd_agent_card_reload, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card reload",
    },
    # ── R63 Phase 3: Agent role map + card registration ──
    "agent_role_map": {
        "handler": _cmd_agent_role_map, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_role_map [--refresh]",
    },
    "agent_card_register": {
        "handler": _cmd_agent_card_register, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card register <agent_id> [--name <name>] [--role <role>]",
    },
    "agent_card_auto_register": {
        "handler": _cmd_agent_card_auto_register, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card auto-register",
    },
    # ── R63 Phase 3: End ──
# ── R41 D: Roll-call commands ──
    "rollcall_role": {
        "handler": _cmd_rollcall_role, "min_role": 3, "workspace_scope": True,
        "usage": "!rollcall_role <role> [--context <msg>]",
    },
    "rollcall_next": {
        "handler": _cmd_rollcall_next, "min_role": 3, "workspace_scope": True,
        "usage": "!rollcall_next <role> --context <摘要>",
    },
    # ── R42: Pipeline commands ──
    "pipeline_start": {
        "handler": _cmd_pipeline_start, "min_role": 3, "workspace_scope": False,
        "usage": "!pipeline_start <R{N}> [--from <step>]",
    },
    "step_complete": {
        "handler": _cmd_step_complete, "min_role": 1, "workspace_scope": True,
        "usage": "!step_complete <step_name> [--output <commit/file>]",
    },
    "pipeline_status": {
        "handler": _cmd_pipeline_status, "min_role": 3, "workspace_scope": False,
        "usage": "!pipeline_status",
    },
    # ── R50: Pipeline activation & step handoff ──
    "pipeline_activate": {
        "handler": _cmd_pipeline_activate, "min_role": 3, "workspace_scope": False,
        "usage": "!pipeline_activate <R{N}> [--ws <workspace_id>]",
    },
    "step_handoff": {
        "handler": _cmd_step_handoff, "min_role": 3, "workspace_scope": True,
        "usage": "!step_handoff <step_name> --output <commit/file>",
    },
    # ── R55 B: Step reject ──
    "step_reject": {
        "handler": _cmd_step_reject, "min_role": 1, "workspace_scope": True,
        "usage": "!step_reject <step_name> --reason <原因>",
    },
    # ── R55 E: Pipeline mode switch ──
    "pipeline_mode": {
        "handler": _cmd_pipeline_mode, "min_role": 3, "workspace_scope": True,
        "usage": "!pipeline_mode <auto|manual>",
    },
    # ── R59 C: Pipeline role override ──
    "pipeline_role_override": {
        "handler": _cmd_pipeline_role_override, "min_role": 3, "workspace_scope": True,
        "usage": "!pipeline_role_override <step> --executor <role>",
    },
    # ── R69 B2: Workspace reset ──
    "workspace_reset": {
        "handler": _cmd_workspace_reset, "min_role": 3, "workspace_scope": True,
        "usage": "!workspace_reset — 关闭当前工作室 + 清理管线状态 + 回大厅",
    },
}



async def _restore_pipeline_timers() -> None:
    """On server start, recover pipeline timeout timers from task store."""
    try:
        all_tasks = ts.list_tasks_by_context("", config.DATA_DIR)
        round_groups = {}
        for t in all_tasks:
            ctx = t.get("context", "")
            state = t.get("state", "")
            if ctx.startswith("R") and state not in ("completed", "cancelled"):
                if ctx not in round_groups:
                    round_groups[ctx] = []
                round_groups[ctx].append(t)
        for round_name, tasks in round_groups.items():
            if round_name in _PIPELINE_STATE:
                continue
            tasks_sorted = sorted(tasks, key=lambda x: x.get("created_at", 0))
            current_step = tasks_sorted[0].get("name", "") if tasks_sorted else ""
            started_at = tasks_sorted[0].get("created_at", time.time())
            ws_id = "ws:" + round_name + "-dev"
            _set_pipeline_state(round_name, {
                "active": True,
                "current_step": current_step,
                "ws_id": ws_id,
                "started_at": started_at,
            })
            logger.info("R49 C restored timer: %s step=%s ws=%s", round_name, current_step, ws_id)
    except Exception:
        pass


# ── R38: Task notify broadcast ─────────────────────────────────────


async def _broadcast_task_notify(
        task: dict,
        transition: str,
        ) -> None:
        """Broadcast MSG_TASK_NOTIFY to workspace members of the task's context.

        transition is a short description e.g. 'SUBMITTED → WORKING'.
        Also pushes to web viewer WS clients for live progress updates.
        """
        context_id = task.get("context_id", "")
        if not context_id:
            return
        workspace = ws_mod.get_workspace(context_id)
        if not workspace:
            return
        payload = json.dumps({
            "type": p.MSG_TASK_NOTIFY,
            "task_id": task["id"],
            "name": task["name"],
            "state": task["state"],
            "transition": transition,
            "assigned_role": task.get("assigned_role", ""),
            "context_id": context_id,
            "ts": time.time(),
        })
        targets = workspace.members
        for agent_id in targets:
            for conn in list(_connections.get(agent_id, set())):
                try:
                    if hasattr(conn, "send_str"):
                        await conn.send_str(payload)
                    elif hasattr(conn, "send"):
                        await conn.send(payload)
                except Exception:
                    pass

        # Push to web viewer WS clients
        try:
            from .web_viewer import _ws_clients as _web_clients
            dead = set()
            for ws in _web_clients:
                try:
                    ws.send_str(payload)
                except Exception:
                    dead.add(ws)
            _web_clients -= dead
        except ImportError:
            pass

        # R41 C: Write task_notify to admin channel
        try:
            content_str = f"📊 {context_id} {task['name']}: {transition}"
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=content_str, ts=time.time(),
                data_dir=config.DATA_DIR, channel=p.ADMIN_CHANNEL,
            )
            write_chat_log("系统", content_str, channel=p.ADMIN_CHANNEL)
        except Exception:
            pass
        logger.info("task_notify '%s' → %s (%s)", task["name"], context_id, transition)


async def handle_broadcast(ws, sender_id: str, msg: dict) -> None:
    """Admin-relay mode:
    - Non-admin (member) → relay ONLY to admin(s)
    - Admin → relay to specific target (via 'to' field or @mention)
    - All messages → written to chat log (大宏/网页端可见)
    - Channel messages (non-lobby) → scoped to workspace members + admin
    """
    # ── R43 A: Lazy-start watchdog on first message ──
    _ensure_watchdog()
    # R49 C: Restore pipeline timers on start
    _restore_pipeline_timers()
    # ── R65 A2: Start git sync loop ──
    _ensure_git_scan()
    # ── R67 B1: Ensure agent cards loaded + watcher running ──
    _ensure_agent_cards_loaded()
    _ensure_card_watcher()

    content = msg.get("content", "")
    channel = msg.get(p.FIELD_CHANNEL) or persistence.get_agent_channel(sender_id) or p.LOBBY

    # R23: unregistered bots → registration channel only (cannot specify channel)
    if not auth.is_approved(sender_id):
        channel = p.REGISTRATION_CHANNEL

    # R12 P1.1: Rate limiting check (before anything else)
    users = auth.get_users()
    sender_role = users.get(sender_id, {}).get("role", "member")
    allowed, retry_after = _check_rate_limit(sender_id, channel, sender_role)
    if not allowed:
        await _send(ws, {
            "type": p.MSG_RATE_LIMITED,
            "reason": f"消息频率过高，{RATE_LIMIT_SECONDS}秒内最多发{RATE_LIMIT_WINDOW}条",
            p.FIELD_RETRY_AFTER: retry_after,
        })
        logger.info("Rate-limited %s in '%s' (retry after %ds)", sender_id[:12], channel, retry_after)
        return

    # R35: ! commands skip nonsense/duplicate filtering
    if not content.startswith("!"):
        if _is_nonsense(content, sender_id, channel):
            logger.info("Nonsense msg filtered from %s in '%s': %s", sender_id[:12], channel, content[:40])
            return
        if _is_duplicate(content, sender_id):
            logger.info("Duplicate msg filtered from %s: %s", sender_id[:12], content[:40])
            return

    # Skip system/noise
    if any(content.startswith(p) for p in _SILENT_PREFIXES) or content.strip("🤐") == "":
        logger.info("Silent msg filtered: %s", content[:60])
        return

    users = auth.get_users()
    sender_name = users.get(sender_id, {}).get("name", sender_id)
    sender_role = users.get(sender_id, {}).get("role", "member")
    admin_ids = {aid for aid, u in users.items() if u.get("role") == "admin"}

    # ── R57 A: Rollcall ACK hook — any message from a waited-on agent fires event ──
    if sender_id in _r57_rollcall_events:
        event = _r57_rollcall_events.get(sender_id)
        if event and not event.is_set():
            event.set()
            logger.info("R57 rollcall ACK from %s (%s)", sender_id[:12], sender_name)

    # ── R63 Phase 3: Rollcall auto-register ──
    # If in a workspace, try to register/update agent card on response
    if channel.startswith(p.WORKSPACE_ID_PREFIX) or channel.startswith("ws:"):
        try:
            await _handle_rollcall_ack(sender_id, content, channel)
        except Exception:
            pass

    # ── R63 Phase 4: Bot ACK detection for step assignment ──
    _update_step_ack_state(sender_id, content)

    # ── R26 P0: 📢 broadcast admin-only check ──
    if content.startswith("📢") and sender_role != "admin":
        await _send(ws, {"type": "error", "error": "「📢」广播仅限管理员使用"})
        return

    # R11 P2.1: Parse mentions from content (used in both lobby and workspace)
    mention_names = set()
    for m in re.finditer(r'@(\S+)', content):
        name = m.group(1)
        if any(users.get(aid, {}).get("name") == name for aid in users):
            mention_names.add(name)
    is_task = bool(mention_names) or content.startswith("!")

    # ── R49: Universal ! command routing (works in any channel) ──
    if content.startswith("!"):
        cmd_name, params = _parse_command(content)
        if not cmd_name or cmd_name not in _ADMIN_COMMANDS:
            available = ", ".join(f"!{k}" for k in sorted(_ADMIN_COMMANDS))
            await _send_cmd_response(ws, sender_id, "系统", f"❌ 未知命令。可用命令：{available}", channel)
            return
        cmd = _ADMIN_COMMANDS[cmd_name]
        allowed, reason = _check_command_permission(sender_id, cmd_name, cmd, params)
        if not allowed:
            await _send_cmd_response(ws, sender_id, "系统", f"❌ {reason}", channel)
            return
        try:
            result = await cmd["handler"](sender_id, params)
            _log_audit(sender_id, cmd_name, params, "success", result)
            await _send_cmd_response(ws, sender_id, "系统", result, channel)
        except Exception as e:
            err_msg = f"❌ 执行失败: {e}"
            _log_audit(sender_id, cmd_name, params, "error", err_msg)
            logger.error("Admin cmd !%s failed: %s", cmd_name, e)
            await _send_cmd_response(ws, sender_id, "系统", err_msg, channel)
        return

    # ── R35: _admin channel intercept ──
    if channel == p.ADMIN_CHANNEL:
        # Persist the admin's command message for web viewer
        msg_id = str(uuid.uuid4())
        try:
            ms.save_message(
                msg_id=msg_id, msg_type="broadcast",
                from_agent=sender_id, from_name=sender_name,
                content=content, ts=time.time(),
                data_dir=config.DATA_DIR, channel=p.ADMIN_CHANNEL,
            )
        except Exception:
            pass
        write_chat_log(sender_name, content, channel=p.ADMIN_CHANNEL)

        # R49: ! commands now handled by universal routing above.
        # _admin channel still persists admin messages for logging.
        # Non-! messages in _admin are silently logged (admin channel only supports ! commands).
        if not content.startswith("!"):
            resp = "ℹ️ 管理频道仅支持 ! 命令"
            await _persist_admin_response(ws, sender_id, "系统", resp)
        return

    # ── R68 A2: Inbox channel intercept ──
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
        owner_id = persistence.resolve_inbox_owner(channel)
        if not owner_id:
            await _send(ws, {"type": "error", "error": "❌ 无效的收件箱通道"})
            return

        # 权限：仅 admin 可向收件箱发消息
        if sender_role != "admin":
            await _send(ws, {"type": "error", "error": "❌ 权限不足：仅管理员可向收件箱发消息"})
            return

        # 仅投递给目标 agent（单播，不广播给其他人）
        targets = [(aid, conns) for aid, conns in _connections.items() if aid == owner_id]
        # 写日志
        write_chat_log(sender_name, content, channel=channel)
        # 构建广播消息
        broadcast = json.dumps({
            "type": "broadcast", "channel": channel,
            "from_name": sender_name, "agent_id": sender_id,
            "from": sender_name, "from_agent": sender_id,
            "content": content, "ts": time.time(),
        })
        sent = 0
        for agent_id, conns in targets:
            for conn in list(conns):
                try:
                    if hasattr(conn, "send_str"):
                        await conn.send_str(broadcast)
                    elif hasattr(conn, "send"):
                        await conn.send(broadcast)
                    sent += 1
                except Exception:
                    pass
        logger.info("Inbox [%s] %s→%s: %s", channel, sender_name, owner_id[:12] if owner_id else "?", content[:60])
        await _send(ws, {"type": "ack", "channel": channel, "sent": sent, "to": owner_id})
        return

    # ── Channel resolution (fall back to lobby for unknown channels) ──
    resolved_workspace = None
    if channel != p.LOBBY:
        # R23: registration channel → skip workspace resolution
        if channel == p.REGISTRATION_CHANNEL:
            pass
        else:
            resolved_workspace = ws_mod.get_workspace(channel)
            if not resolved_workspace:
                # Unknown channel from Hermes built-in ws_bridge adapter
                # (hardcoded chat_id="ws_bridge_group"). Try to auto-route
                # to the sender's active workspace if they have exactly one.
                agent_workspaces = ws_mod.get_workspaces_for_agent(sender_id)
                active = [w for w in agent_workspaces if w.state == ws_mod.WorkspaceState.ACTIVE]
                if len(active) == 1:
                    resolved_workspace = active[0]
                    channel = resolved_workspace.id
                    logger.info(
                        "Auto-routed %s to workspace '%s'",
                        sender_id[:12], channel,
                    )
                else:
                    logger.info("Unknown channel '%s' — falling back to lobby", channel)
                    channel = p.LOBBY

    # ── R6: Broadcast permission check ──
    allowed, reason = _can_broadcast(sender_id, channel, msg)
    if not allowed:
        await _send(ws, {"type": "error", "error": f"权限不足：{reason}"})
        return

        # ── R42 D: Lobby pause intercept ──
    if _LOBBY_PAUSED and channel == p.LOBBY:
        # If sender has an active workspace, auto-route there
        agent_workspaces = ws_mod.get_workspaces_for_agent(sender_id)
        active = [w for w in agent_workspaces if w.state == ws_mod.WorkspaceState.ACTIVE]
        if active:
            channel = active[0].id
            resolved_workspace = active[0]
            logger.info("R42 lobby-pause: routed %s to workspace '%s'", sender_id[:12], channel)
        else:
            await _send(ws, {
                "type": "error",
                "error": f"🔒 管线 {_LOBBY_PAUSED_ROUND} 进行中，大厅已暂停接收消息。请在工作区中发言。",
            })
            return

    # ── Channel-scoped routing ──────────────────────────────────────
    if channel != p.LOBBY and resolved_workspace:
            # Known workspace → route to members + admin
            if resolved_workspace.state == ws_mod.WorkspaceState.CLOSING:
                await _send(ws, {"type": "error", "error": f"Workspace '{channel}' is closing, no new messages allowed"})
                return
            if resolved_workspace.state == ws_mod.WorkspaceState.ARCHIVED:
                await _send(ws, {"type": "error", "error": f"Workspace '{channel}' is archived, read-only"})
                return

            # Update activity
            ws_mod.touch(channel)

            # Only members + admin
            member_ids = resolved_workspace.members
            targets = [
                (aid, conns) for aid, conns in _connections.items()
                if (aid in member_ids or aid in admin_ids) and aid != sender_id
            ]
            if not targets:
                logger.info("Workspace '%s': no online members, msg logged only", channel)
                write_chat_log(sender_name, content, channel=channel)
                return

            broadcast = json.dumps({
                "type": "broadcast",
                "channel": channel,
                # New unified field names
                "from_name": sender_name,
                "agent_id": sender_id,
                # Legacy field names (Hermes built-in ws_bridge adapter reads these)
                "from": sender_name,
                "from_agent": sender_id,
                "content": content,
                "ts": time.time(),
                # R11 P2.1: Mentions metadata
                p.FIELD_MENTIONS: list(mention_names) if mention_names else None,
                p.FIELD_IS_TASK: is_task or None,
            })

            # Persist with channel
            msg_id = msg.get("id", "") or str(uuid.uuid4())
            try:
                ms.save_message(
                    msg_id=msg_id,
                    msg_type="broadcast",
                    from_agent=sender_id,
                    from_name=sender_name,
                    content=content,
                    ts=time.time(),
                    data_dir=config.DATA_DIR,
                    channel=channel,
                )
            except Exception:
                pass

            sent = 0
            target_names = []
            # R11 P1.1: Track delivery
            _delivery_status[msg_id] = {}
            for agent_id, conns in targets:
                target_names.append(users.get(agent_id, {}).get("name", agent_id[:12]))
                for conn in list(conns):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(broadcast)
                        elif hasattr(conn, "send"):
                            await conn.send(broadcast)
                        sent += 1
                    except Exception:
                        pass
                # R11 P1.1: Mark delivery
                _delivery_status[msg_id][agent_id] = p.DELIVERY_SENT

            # R34 B: Send ACK with delivery stats (workspace path)
            if msg_id:
                _online = set(_connections.keys())
                sent_list = []
                offline_list = []
                for aid in member_ids:
                    if aid == sender_id:
                        continue
                    name = users.get(aid, {}).get("name", aid[:12])
                    if aid in _online:
                        sent_list.append(name)
                    else:
                        offline_list.append(name)
                await _send(ws, {
                    "type": "ack",
                    "id": msg_id,
                    "delivery": {
                        "total": len(member_ids) - 1,  # exclude sender
                        "sent": len(sent_list),
                        "offline": len(offline_list),
                        "targets": sent_list,
                        "offline_targets": offline_list,
                    }
                })

            # R11 P1.1: Send delivery_status to admin senders in workspace
            if sender_role == "admin" and msg_id:
                online = set(_connections.keys())
                status_report = {}
                for aid in member_ids:
                    if aid == sender_id:
                        continue
                    name = users.get(aid, {}).get("name", aid[:12])
                    status_report[name] = "sent" if aid in online else "offline"
                await _send(ws, {
                    "type": p.MSG_DELIVERY_STATUS,
                    "id": msg_id,
                    "status": status_report,
                    "total": len(status_report),
                    "delivered": sum(1 for s in status_report.values() if s == "sent"),
                })

            logger.info("Channel [%s] %s→%s: %s", channel, sender_name, ",".join(target_names), content[:60])
            write_chat_log(sender_name, content, channel=channel)

            return
    # ── R24: Lobby routing with prefix classification ─────────────────
    if channel == p.LOBBY:
        msg_type, target_names = _classify_lobby_message(content)

        if msg_type == 'plain':
            await _send(ws, {
                "type": "error",
                "error": "大厅消息需要明确类型。请使用 📢公告 / 📋点名 / 🆘求助 / @用户名。\n普通讨论请在工作室频道进行。",
            })
            logger.info("Lobby plain msg blocked from %s: %s", sender_id[:12], content[:40])
            return

        # Lobby-specific rate limit
        allowed, retry_after = _check_lobby_rate_limit(sender_id, sender_role)
        if not allowed:
            await _send(ws, {
                "type": p.MSG_RATE_LIMITED,
                "reason": f"大厅消息频率过高，请{retry_after}秒后再试",
                p.FIELD_RETRY_AFTER: retry_after,
            })
            return

        # Route by type
        targets = []
        if msg_type == 'announce':
            # 📢 → broadcast to ALL online bots (admin-only)
            if sender_role != "admin":
                await _send(ws, {
                    "type": "error",
                    "error": "📢 公告仅管理员可用。请使用 📋点名 / 🆘求助 / @用户名 发送大厅消息。",
                })
                return
            targets = [(aid, conns) for aid, conns in _connections.items() if aid != sender_id]

        elif msg_type == 'help':
            # 🆘 → P4 admin only
            targets = [(aid, conns) for aid, conns in _connections.items() if aid in admin_ids]

        elif msg_type == 'checkin':
            # 📋 → route to @mentioned targets
            targets = []
            for name in target_names:
                for aid, conns in _connections.items():
                    if users.get(aid, {}).get("name") == name and aid != sender_id:
                        targets.append((aid, conns))
                        break
            if not targets:
                await _send(ws, {"type": "error", "error": f"未找到在线目标: {', '.join(target_names)}"})
                return

        elif msg_type == 'mention':
            # @name → route to target + admin
            targets = []
            for name in target_names:
                for aid, conns in _connections.items():
                    if users.get(aid, {}).get("name") == name and aid != sender_id:
                        targets.append((aid, conns))
                        break
            # Always include admins
            for aid, conns in _connections.items():
                if aid in admin_ids and aid != sender_id:
                    if not any(t[0] == aid for t in targets):
                        targets.append((aid, conns))

        if not targets:
            logger.info("Lobby msg from %s has no online targets", sender_id[:12])
            write_chat_log(sender_name, content, channel=p.LOBBY)
            return

    # ── R24: Registration channel → admin relay fallback ────────────
    if channel == p.REGISTRATION_CHANNEL:
        targets = [(aid, conns) for aid, conns in _connections.items() if aid in admin_ids]
        if not targets:
            logger.info("Reg channel: no admin online, msg from %s logged only", sender_id[:12])
            write_chat_log(sender_name, content, channel=channel)
            return

    # Use dual field names (new unified + legacy compat)
    broadcast = json.dumps({
        "type": "broadcast",
        "channel": channel,
        # New unified field names
        "from_name": sender_name,
        "agent_id": sender_id,
        # Legacy field names (Hermes built-in ws_bridge adapter reads these)
        "from": sender_name,
        "from_agent": sender_id,
        "content": content,
        "ts": time.time(),
        # R11 P2.1: Mentions metadata
        p.FIELD_MENTIONS: list(mention_names) if mention_names else None,
        p.FIELD_IS_TASK: is_task or None,
    })
    # P6: timing
    _t0 = time.time()
    msg_id = msg.get("id", "") or str(uuid.uuid4())
    # Persist before broadcasting
    try:
        ms.save_message(
            msg_id=msg_id,
            msg_type="broadcast",
            from_agent=sender_id,
            from_name=sender_name,
            content=content,
            ts=time.time(),
            data_dir=config.DATA_DIR,
        )
    except Exception:
        pass
    sent = 0
    target_names = []
    # R11 P1.1: Track delivery
    _delivery_status[msg_id] = {}
    for agent_id, conns in targets:
        target_names.append(users.get(agent_id, {}).get("name", agent_id[:12]))
        delivered = False
        for conn in list(conns):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(broadcast)
                elif hasattr(conn, "send"):
                    await conn.send(broadcast)
                sent += 1
                delivered = True
            except Exception:
                pass
        # R11 P1.1: Mark delivery status
        _delivery_status[msg_id][agent_id] = p.DELIVERY_SENT if delivered else p.DELIVERY_SENT
    # R11 P1.2: Offline push — agents not in targets get queued (if admin message)
    if sender_role == "admin":
        all_agents = {aid for aid in users}
        online_agents = {aid for aid in _connections}
        offline_agents = all_agents - online_agents
        # R41 B: Persist offline-queued messages to message store
        if offline_agents:
            try:
                ms.save_message(
                    msg_id=msg_id, msg_type="broadcast",
                    from_agent=sender_id, from_name=sender_name,
                    content=content, ts=time.time(),
                    data_dir=config.DATA_DIR, channel=channel,
                )
            except Exception:
                pass
        for offline_id in offline_agents:
            _offline_push_queue.setdefault(offline_id, []).append({
                "type": "broadcast",
                "id": msg_id,
                "channel": channel,
                "from_name": sender_name,
                "agent_id": sender_id,
                "from": sender_name,
                "from_agent": sender_id,
                "content": content,
                "ts": time.time(),
            })
            if offline_id not in _offline_timers:
                _offline_timers[offline_id] = asyncio.create_task(
                    _flush_offline_push(offline_id)
                )

    # R34 B: Send ACK with delivery stats (lobby path)
    if msg_id:
        _online = set(_connections.keys())
        # targets = routed online recipients (already built above, but may include sender)
        lobby_sent_list = [users.get(aid, {}).get("name", aid[:12]) for aid, _ in targets if aid != sender_id]
        # Offline: all users (except sender) minus online = the ones not reachable
        lobby_all_non_sender = {aid for aid in users if aid != sender_id}
        lobby_offline_ids = lobby_all_non_sender - _online
        lobby_offline_list = [users.get(aid, {}).get("name", aid[:12]) for aid in lobby_offline_ids]
        await _send(ws, {
            "type": "ack",
            "id": msg_id,
            "delivery": {
                "total": len(lobby_all_non_sender),
                "sent": len(lobby_sent_list),
                "offline": len(lobby_offline_list),
                "targets": lobby_sent_list,
                "offline_targets": lobby_offline_list,
            }
        })
    # R11 P1.1: Send delivery_status to admin senders
    if sender_role == "admin" and msg_id:
        online = set(_connections.keys())
        status_report = {}
        for aid in {u for u in users}:
            name = users.get(aid, {}).get("name", aid[:12])
            if aid == sender_id:
                continue
            if aid in online:
                status_report[name] = "sent"
            else:
                status_report[name] = "offline"
        await _send(ws, {
            "type": p.MSG_DELIVERY_STATUS,
            "id": msg_id,
            "status": status_report,
            "total": len(status_report),
            "delivered": sum(1 for s in status_report.values() if s == "sent"),
        })

    # P6: record latency
    _latency = time.time() - _t0
    _send_stats["total"] += 1
    _send_stats["total_latency"] += _latency
    if sender_role == "admin":
        logger.info("Admin-relay %s➔%s: %s", sender_name, ",".join(target_names), content[:60])
    else:
        logger.info("Member %s→admin: %s", sender_name, content[:60])

    # Write to chat log (大宏/网页端可见所有消息)
    write_chat_log(sender_name, content)

    # ── R29: 📋 roll-call — send online member list to admin
    # R33-1: Also allow workspace admin_ids (e.g. 泰虾) to call roll-call
    is_ws_admin = (resolved_workspace is not None and
                   (sender_id in resolved_workspace.admin_ids or
                    sender_id == resolved_workspace.owner_id))
    if (sender_role == "admin" or is_ws_admin) and content.startswith("📋"):
        online_list = _build_online_list(users)
        await _send(ws, {
            "type": "broadcast",
            "channel": p.LOBBY,
            "from_name": "系统",
            "from": "系统",
            "agent_id": "",
            "from_agent": "",
            "content": f"📋 当前在线：{online_list}",
            "ts": time.time(),
        })
        logger.info("Admin %s roll-call — online list sent (%s)", sender_id[:12], online_list)

        # R53: Broadcast MSG_SET_ACTIVE_CHANNEL with ACK (replaces R37 text rollcall)
        if resolved_workspace:
            target_ch = resolved_workspace.id
            ack_result = await _broadcast_active_channel(target_ch)


# ── R50: Shared MSG_SET_ACTIVE_CHANNEL broadcast ─────────────────


async def _broadcast_active_channel(ws_id: str) -> dict:
    """Broadcast MSG_SET_ACTIVE_CHANNEL with ACK waiting.
    Returns: {online_count, acked_members: set[str], timedout_members: set[str]}
    Also persists the channel for offline members so they pick it up on reconnection.
    """
    ws_obj = ws_mod.get_workspace(ws_id)
    if not ws_obj:
        return {"online_count": 0, "acked_members": set(), "timedout_members": set()}

    # ★ R53: Generate per-broadcast ack_task_id
    ack_task_id = str(uuid.uuid4())

    switch_payload = json.dumps({
        "type": p.MSG_SET_ACTIVE_CHANNEL,
        p.FIELD_CHANNEL: ws_id,
        p.FIELD_TASK_ID: ack_task_id,
        "from_name": "系统",
        "from": "系统",
        "content": f"请将活跃频道切换至 {ws_id} 后回复 ACK",
        "ts": time.time(),
    })

    online_members = set()
    for member_id in ws_obj.members:
        persistence.set_agent_channel(member_id, ws_id)
        for conn in list(_connections.get(member_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(switch_payload)
                elif hasattr(conn, "send"):
                    await conn.send(switch_payload)
                online_members.add(member_id)
            except Exception:
                pass

    persistence.save_agent_channels(config.DATA_DIR)

    # ★ R53: Register ACK state and start 30s timeout
    _channel_ack_state[ws_id] = {
        "ack_task_id": ack_task_id,
        "online_members": online_members,
        "acked_members": {},
        "timer": asyncio.create_task(_channel_ack_timeout(ws_id)),
    }

    logger.info(
        "MSG_SET_ACTIVE_CHANNEL '%s' sent to %d online members (ack=%s)",
        ws_id, len(online_members), ack_task_id[:8],
    )
    return {
        "online_count": len(online_members),
        "acked_members": set(),
        "timedout_members": set(),
    }


# ── R11 P2.2: Membership change notification ────────────────────


async def _notify_member_changed(ws_id: str, member_id: str, event: str) -> None:
    """Notify all workspace members of membership change (joined/removed)."""
    resolved = ws_mod.get_workspace(ws_id)
    if not resolved:
        return
    member_name = _get_agent_display(member_id)
    payload = json.dumps({
        "type": p.MSG_MEMBER_CHANGED,
        p.FIELD_WORKSPACE_ID: ws_id,
        p.FIELD_MEMBER_EVENT: event,
        p.FIELD_TARGET_AGENT_ID: member_id,
        "member_name": member_name,
        "ts": time.time(),
    })
    targets = resolved.members | {member_id} if event == "joined" else resolved.members
    for agent_id in targets:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload)
                elif hasattr(conn, "send"):
                    await conn.send(payload)
            except Exception:
                pass


# ── R24: Lobby-specific rate limiter ─────────────────────────────────


def _check_lobby_rate_limit(agent_id: str, role: str) -> tuple[bool, float]:
    """Check lobby-specific rate limit. P4 unlimited, P3=5/60s, P1/P2=2/60s."""
    if role == "admin":
        return True, 0
    window = LOBBY_RATE_WINDOW_P3 if role == "workspace_admin" else LOBBY_RATE_WINDOW_P1P2
    now = time.time()
    window_start = now - LOBBY_RATE_SECONDS
    timestamps = _lobby_rate_limits.setdefault(agent_id, [])
    timestamps[:] = [t for t in timestamps if t > window_start]
    if len(timestamps) >= window:
        retry_after = int(timestamps[0] + LOBBY_RATE_SECONDS - now) + 1
        return False, retry_after
    timestamps.append(now)
    return True, 0


# ── R24: Lobby message classification ───────────────────────────────


def _classify_lobby_message(content: str) -> tuple[str, list[str]]:
    """Classify lobby message by prefix.
    Returns (type, extracted_names).
    Types: 'announce', 'checkin', 'help', 'mention', 'plain'
    """
    content = content.strip()
    # R45 B (F-4): Strip [R{N}测试] test tags before prefix check
    content = re.sub(r'^\[R\d+测试\]\s*', '', content).strip()
    if content.startswith(PREFIX_ANNOUNCE):
        return 'announce', []
    if content.startswith(PREFIX_CHECKIN):
        names = [m.group(1) for m in re.finditer(r'@(\S+)', content)]
        return 'checkin', names
    if content.startswith(PREFIX_HELP):
        return 'help', []
    names = [m.group(1) for m in re.finditer(r'@(\S+)', content)]
    if names:
        return 'mention', names
    return 'plain', []


# ── R12 P1.1: Rate limiting ──────────────────────────────────────────


def _check_rate_limit(agent_id: str, channel: str, role: str) -> tuple[bool, float]:
    """Check if agent is rate-limited in channel. Returns (allowed, retry_after)."""
    if role == "admin":
        return True, 0
    now = time.time()
    window_start = now - RATE_LIMIT_SECONDS
    agent_limits = _rate_limits.setdefault(agent_id, {})
    timestamps = agent_limits.setdefault(channel, [])
    timestamps[:] = [t for t in timestamps if t > window_start]
    if len(timestamps) >= RATE_LIMIT_WINDOW:
        retry_after = int(timestamps[0] + RATE_LIMIT_SECONDS - now) + 1
        return False, retry_after
    timestamps.append(now)
    return True, 0


# ── R12 P1.2: Nonsense message patterns ────────────────────────────


_NONSENSE_PATTERNS = [
    re.compile(r'^[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F'
               r'\U0001F680-\U0001F6FF\u2600-\u27BF\u2B50\u2702-\u27B0'
               r'\uFE0F✅❌⚠️🟢🟡🔴⬜⬛➕➖🔄🤐👂🤫🦐🧐🦾📋'
               r'\s\*]+$'),
    re.compile(r'^\*\s*静默待命.*\*[\s🤫]*$'),
    re.compile(r'^\*\s*弹药上膛.*\*[\s🦐🚀]*$'),
    re.compile(r'^到[\s✅]*$'),
]


def _is_nonsense(content: str, agent_id: str, channel: str) -> bool:
    """Check if message is nonsense (pure emoji, heartbeat, etc.)."""
    stripped = content.strip()
    if not stripped:
        return True
    for pattern in _NONSENSE_PATTERNS:
        if pattern.match(stripped):
            return True
    if '@' in stripped or 'http' in stripped.lower():
        return False
    text_chars = sum(1 for c in stripped if c.isascii() and c.isalnum())
    if text_chars >= 5:
        return False
    has_cjk = any('\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf' for c in stripped)
    if has_cjk:
        return False
    if text_chars < 3 and not has_cjk:
        return True
    return False


def _is_duplicate(content: str, agent_id: str) -> bool:
    """Check if agent is sending the same content within 30 seconds."""
    entry = _last_message.get(agent_id)
    now = time.time()
    if entry and entry["content"] == content and (now - entry["ts"]) < 30:
        return True
    _last_message[agent_id] = {"content": content, "ts": now}
    return False


# ── R12 P0.3: Task ack timeout ────────────────────────────────────


async def _task_ack_timeout(admin_ws, task_id: str, target_name: str) -> None:
    """30s timeout for task ack. Notify admin if no response."""
    await asyncio.sleep(30)
    _task_ack_timers.pop(task_id, None)
    try:
        await _send(admin_ws, {
            "type": "delivery_status",
            "task_id": task_id,
            "status": "timeout",
            "message": f"⚠️ {target_name} 30 秒内未确认任务，建议检查",
        })
    except Exception:
        pass
    logger.warning("Task %s ack timeout for %s", task_id, target_name)


# ── R53: Channel switch verification ────────────────────────────


async def _notify_rollcall_complete(ws_id: str) -> None:
    """Verify all members have switched channels and notify host (R53)."""
    ws_obj = ws_mod.get_workspace(ws_id)
    if not ws_obj:
        return
    unconfirmed = []
    for member_id in ws_obj.members:
        ch = persistence.get_agent_channel(member_id)
        if ch != ws_id:
            unconfirmed.append(member_id)

    users = auth.get_users()
    payload = json.dumps({
        "type": "broadcast",
        "channel": ws_id,
        "from_name": "系统",
        "from": "系统",
        "agent_id": "",
        "from_agent": "",
        "ts": time.time(),
    })
    if not unconfirmed:
        content = "✅ 点名完成：全员活跃频道已锁定。"
        logger.info("R53: Roll-call complete for '%s' — all members confirmed", ws_id)
    else:
        names = [users.get(uid, {}).get("name", uid[:12]) for uid in unconfirmed]
        content = f"⚠️ 点名完成（部分）：以下成员未确认频道切换：{', '.join(names)}"
        logger.info("R53: Roll-call complete for '%s' — %d unconfirmed: %s", ws_id, len(unconfirmed), names)

    payload = json.dumps({**json.loads(payload), "content": content})
    for admin_id in ws_obj.admin_ids:
        for conn in list(_connections.get(admin_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload)
                elif hasattr(conn, "send"):
                    await conn.send(payload)
            except Exception:
                pass
    # R53: Cleanup ACK state
    _channel_ack_state.pop(ws_id, None)


# ── R53: Channel switch ACK timeout (30s, replaces R37 3min) ───

async def _channel_ack_timeout(ws_id: str) -> None:
    """30s timeout for channel switch ACK.
    On timeout: marks unresponsive members, calls _notify_rollcall_complete().
    """
    await asyncio.sleep(30)
    state = _channel_ack_state.get(ws_id)
    if not state:
        return
    timedout = state["online_members"] - set(state["acked_members"].keys())
    if timedout:
        users = auth.get_users()
        names = [users.get(uid, {}).get("name", uid[:12]) for uid in timedout]
        alert_payload = json.dumps({
            "type": "broadcast",
            "channel": ws_id,
            "from_name": "系统",
            "from": "系统",
            "agent_id": "",
            "from_agent": "",
            "content": f"⏰ 点名超时（30s）：以下 {len(timedout)} 名成员未回复 ACK：{', '.join(names)}",
            "ts": time.time(),
        })
        ws_obj = ws_mod.get_workspace(ws_id)
        if ws_obj:
            for admin_id in ws_obj.admin_ids:
                for conn in list(_connections.get(admin_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(alert_payload)
                        elif hasattr(conn, "send"):
                            await conn.send(alert_payload)
                    except Exception:
                        pass
        logger.info("R53: Channel ACK timeout for '%s': %d unconfirmed", ws_id, len(timedout))
    # Call rollcall complete with partial results
    asyncio.create_task(_notify_rollcall_complete(ws_id))
    # Cleanup
    _channel_ack_state.pop(ws_id, None)


def _resolve_ws_by_ack_task_id(ack_task_id: str) -> str | None:
    """Find workspace ID by its active ack_task_id."""
    for ws_id, state in _channel_ack_state.items():
        if state.get("ack_task_id") == ack_task_id:
            return ws_id
    return None


# ── R12 P0.4: Workspace ready broadcast ────────────────────────────


async def _broadcast_workspace_ready(ws_id: str, name: str, owner_name: str, members: set[str]) -> None:
    """Broadcast workspace_ready to all members."""
    from . import workspace as ws_mod
    payload = ws_mod.build_workspace_ready(ws_id, name, owner_name, members)
    payload_json = json.dumps(payload)
    for agent_id in members:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload_json)
                elif hasattr(conn, "send"):
                    await conn.send(payload_json)
            except Exception:
                pass
    logger.info("workspace_ready broadcast to %d members of '%s'", len(members), ws_id)


# ── R12 P2: Stage completed broadcast ──────────────────────────────


async def _broadcast_stage_completed(
    ws_id: str,
    completed_by: str,
    stage: str,
    output: str,
    next_holder: str,
    next_stage: str,
) -> None:
    """Notify next holder that a stage has been completed."""
    workspace = ws_mod.get_workspace(ws_id)
    if not workspace:
        return
    users = auth.get_users()
    next_id = None
    for aid, u in users.items():
        if u.get("name") == next_holder:
            next_id = aid
            break
    payload = json.dumps({
        "type": p.MSG_STAGE_COMPLETED,
        "workspace_id": ws_id,
        "completed_by": completed_by,
        "stage": stage,
        "output": output,
        "next_holder": next_holder,
        "next_stage": next_stage,
        "ts": time.time(),
    })
    targets = [next_id] if next_id else workspace.members
    for agent_id in targets:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload)
                elif hasattr(conn, "send"):
                    await conn.send(payload)
            except Exception:
                pass
    logger.info("stage_completed '%s' → %s (next: %s)", stage, next_holder, next_stage)


# ── R6: Broadcast Permission Check ──────────────────────────────


def _can_broadcast(agent_id: str, channel: str, msg: dict) -> tuple[bool, str]:
    """Check if agent can broadcast in the given channel.
    Returns (allowed: bool, reason: str).
    """
    # L4 global admin: any channel
    if auth.is_global_admin(agent_id):
        return True, ""

    # R35: _admin channel — only admins (P3/P4) can send
    # R44 F-12: PM pipeline_start bypass — allow broadcast, command-level check still applies
    if channel == p.ADMIN_CHANNEL:
        if auth.is_global_admin(agent_id):
            return True, ""
        if _is_any_workspace_admin(agent_id):
            return True, ""
        # R44: member broadcast allowed; _check_command_permission enforces pipeline_start only
        return True, ""

    # R23: registration channel → allow (admin-relay handles routing)
    if channel == p.REGISTRATION_CHANNEL:
        return True, ""

    # Lobby: members can reply (routing already limits to admin-only)
    if channel == p.LOBBY:
        return True, ""

    # Workspace: must be a member
    members = ws_mod.get_workspace_members(channel)
    if agent_id not in members:
        return False, "您不是该工作区成员"

    # R10: token ring permission check
    reply_to = msg.get(p.FIELD_TOKEN_REPLY_TO)
    allowed, reason = ws_mod.can_send_in_token_mode(channel, agent_id, reply_to)
    if not allowed:
        return False, reason

    return True, ""


async def handler(ws):
    """Per-connection WebSocket handler (legacy — used by websockets library)."""
    agent_id = None
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, {"type": "error", "error": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "auth" and agent_id is None:
                agent_id = await handle_auth(ws, msg)
                if agent_id:
                    _connections.setdefault(agent_id, set()).add(ws)
                    logger.info("Agent %s connected (%d total)", agent_id[:20], sum(len(c) for c in _connections.values()))

            elif msg_type == "message" and agent_id:
                await handle_broadcast(ws, agent_id, msg)

            elif msg_type == "approve" and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    result = await handle_approve(msg)
                    await _send(ws, result)

            elif msg_type == p.MSG_WORKSPACE_CREATE and agent_id:
                # Bot requests creating a workspace → route to admin(s) for approval
                ws_name = msg.get("name", "").strip()
                if not ws_name:
                    await _send(ws, {"type": "error", "error": "Missing workspace name"})
                    continue
                ws_id = f"{p.WORKSPACE_ID_PREFIX}{agent_id[:8]}-{ws_name[:20]}"
                _users = auth.get_users()
                _sender_name = _users.get(agent_id, {}).get("name", agent_id)
                _admin_ids = {aid for aid, u in _users.items() if u.get("role") == "admin"}
                create_payload = json.dumps({
                    "type": "broadcast",
                    "channel": p.LOBBY,
                    "content": f"@{agent_id} requests workspace: {ws_name}",
                    "from_name": _sender_name,
                    "agent_id": agent_id,
                    "ts": time.time(),
                    "_workspace_request": {
                        "id": ws_id,
                        "name": ws_name,
                        "requester_id": agent_id,
                    },
                })
                # Send to admin(s)
                for admin_aid in _admin_ids:
                    for conn in list(_connections.get(admin_aid, set())):
                        try:
                            if hasattr(conn, "send_str"):
                                await conn.send_str(create_payload)
                            elif hasattr(conn, "send"):
                                await conn.send(create_payload)
                        except Exception:
                            pass

            elif msg_type == p.MSG_WORKSPACE_CREATE_APPROVED and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    ws_id = msg.get("id", "").strip()
                    ws_name = msg.get("name", "").strip()
                    owner_id = msg.get("owner_id", "").strip()
                    owner_name = msg.get("owner_name", "").strip()
                    if ws_id and owner_id:
                        result = ws_mod.create_workspace(ws_id, ws_name or ws_id, owner_id, owner_name)
                        if result:
                            # R7: auto-bind owner's active channel
                            persistence.set_agent_channel(owner_id, ws_id)
                            persistence.save_agent_channels(config.DATA_DIR)
                            await _send(ws, {"type": "ok", "workspace_id": ws_id})
                            logger.info("Workspace '%s' created by admin — owner %s channel set to '%s'",
                                         ws_id, owner_id[:20], ws_id)
                            # R12 P0.4: Send workspace_ready notification
                            asyncio.create_task(
                                _broadcast_workspace_ready(ws_id, ws_name or ws_id, owner_name or owner_id, result.members)
                            )
                        else:
                            await _send(ws, {"type": "error", "error": f"Failed to create workspace '{ws_id}' (owner may have too many active)"})

            elif msg_type == p.MSG_WORKSPACE_CLOSE and agent_id:
                ws_id = msg.get("workspace_id", "").strip()
                if not ws_id:
                    await _send(ws, {"type": "error", "error": "Missing workspace_id"})
                    continue
                if ws_mod.start_closing(ws_id):
                    await _send(ws, {"type": "ok", "workspace_id": ws_id, "message": f"Workspace '{ws_id}' closing initiated"})
                    # Notify members
                    asyncio.create_task(_broadcast_workspace_closing(ws_id))
                else:
                    await _send(ws, {"type": "error", "error": f"Failed to close workspace '{ws_id}' (not found or not active)"})

            elif msg_type == p.MSG_WORKSPACE_ADD_MEMBER and agent_id:
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                member_id = msg.get(p.FIELD_MEMBER_ID, "").strip()
                if ws_id and member_id:
                    resolved_workspace = ws_mod.get_workspace(ws_id)
                    if resolved_workspace and resolved_workspace.state == ws_mod.WorkspaceState.ACTIVE:
                        if auth.can_manage_workspace(ws_id, agent_id):
                            if ws_mod.add_member(ws_id, member_id):
                                # R22: auto-set active channel for new member (if none set)
                                if not persistence.get_agent_channel(member_id):
                                    persistence.set_agent_channel(member_id, ws_id)
                                    persistence.save_agent_channels(config.DATA_DIR)
                                    logger.info("Auto-set %s active channel to %s", member_id[:20], ws_id)

                                await _send(ws, {"type": "ok", "workspace_id": ws_id, "member_id": member_id})
                                logger.info("Member %s added to workspace '%s'", member_id, ws_id)
                                # R11 P2.2: Notify workspace members of membership change
                                asyncio.create_task(_notify_member_changed(ws_id, member_id, "joined"))
                            else:
                                await _send(ws, {"type": "error", "error": "Failed to add member"})
                        else:
                            await _send(ws, {"type": "error", "error": "Permission denied"})
                    else:
                        await _send(ws, {"type": "error", "error": "Workspace not found or not active"})
                else:
                    await _send(ws, {"type": "error", "error": "Missing workspace_id or member_id"})

            elif msg_type == p.MSG_WORKSPACE_REMOVE_MEMBER and agent_id:
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                member_id = msg.get(p.FIELD_MEMBER_ID, "").strip()
                if ws_id and member_id:
                    resolved_workspace = ws_mod.get_workspace(ws_id)
                    if resolved_workspace and resolved_workspace.state == ws_mod.WorkspaceState.ACTIVE:
                        if auth.can_manage_workspace(ws_id, agent_id):
                            if ws_mod.remove_member(ws_id, member_id):
                                await _send(ws, {"type": "ok", "workspace_id": ws_id, "member_id": member_id})
                                logger.info("Member %s removed from workspace '%s'", member_id, ws_id)
                                # R11 P2.2: Notify workspace members of membership change
                                asyncio.create_task(_notify_member_changed(ws_id, member_id, "removed"))
                            else:
                                await _send(ws, {"type": "error", "error": "Failed to remove member"})
                        else:
                            await _send(ws, {"type": "error", "error": "Permission denied"})
                    else:
                        await _send(ws, {"type": "error", "error": "Workspace not found or not active"})
                else:
                    await _send(ws, {"type": "error", "error": "Missing workspace_id or member_id"})

            elif msg_type == p.MSG_SET_ADMIN and agent_id:
                # Only global admin can set workspace admin
                if auth.is_global_admin(agent_id):
                    ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                    target_id = msg.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                    target_name = msg.get("target_name", target_id).strip()
                    if ws_id and target_id:
                        if auth.set_workspace_admin(ws_id, target_id, agent_id):
                            await _send(ws, {"type": "ok", "workspace_id": ws_id, "admin_id": target_id, "admin_name": target_name})
                            logger.info("Agent %s set as admin of workspace '%s' by %s", target_id[:20], ws_id, agent_id[:20])
                        else:
                            await _send(ws, {"type": "error", "error": "Failed to set admin"})
                    else:
                        await _send(ws, {"type": "error", "error": "Missing workspace_id or target_agent_id"})


            # ── R12 P0.2: Task Assignment ────────────────────────
            elif msg_type == p.MSG_TASK_ASSIGNMENT and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") != "admin":
                    await _send(ws, {"type": "error", "error": "Permission denied: only admin can assign tasks"})
                    continue

                target_name = msg.get(p.FIELD_TARGET_AGENT, "").strip()
                target_id = msg.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                step = msg.get(p.FIELD_TASK_STEP, "")
                description = msg.get(p.FIELD_TASK_DESC, "")
                channel = msg.get(p.FIELD_CHANNEL, p.LOBBY)
                task_id = str(time.time())

                # Resolve target agent_id if only name provided
                if not target_id and target_name:
                    for aid, u in users.items():
                        if u.get("name") == target_name:
                            target_id = aid
                            break

                if not target_id:
                    await _send(ws, {"type": "error", "error": f"Target agent '{target_name}' not found"})
                    continue

                assign_payload = {
                    "type": p.MSG_TASK_ASSIGNMENT,
                    "task_id": task_id,
                    "channel": channel,
                    "from_name": users.get(agent_id, {}).get("name", agent_id),
                    "agent_id": agent_id,
                    p.FIELD_TARGET_AGENT: target_name or users.get(target_id, {}).get("name", target_id),
                    p.FIELD_TARGET_AGENT_ID: target_id,
                    p.FIELD_TASK_STEP: step,
                    p.FIELD_TASK_DESC: description,
                    "ts": time.time(),
                }

                target_conns = _connections.get(target_id, set())
                if target_conns:
                    payload_json = json.dumps(assign_payload)
                    for conn in list(target_conns):
                        try:
                            if hasattr(conn, "send_str"):
                                await conn.send_str(payload_json)
                            elif hasattr(conn, "send"):
                                await conn.send(payload_json)
                        except Exception:
                            pass
                    await _send(ws, {
                        "type": "delivery_status",
                        "task_id": task_id,
                        "status": "delivered",
                        "message": f"✅ 已送达目标 {target_name or target_id[:12]}，等待响应",
                    })
                    _task_ack_timers[task_id] = asyncio.create_task(
                        _task_ack_timeout(ws, task_id, target_name or target_id[:12])
                    )
                    logger.info("Task assigned to %s (task_id=%s): %s", target_id[:12], task_id, description[:60])
                else:
                    _offline_push_queue.setdefault(target_id, []).append(assign_payload)
                    if target_id not in _offline_timers:
                        _offline_timers[target_id] = asyncio.create_task(
                            _flush_offline_push(target_id)
                        )
                    await _send(ws, {
                        "type": "delivery_status",
                        "task_id": task_id,
                        "status": "queued",
                        "message": f"❌ 目标 {target_name or target_id[:12]} 离线，消息已保存，上线后自动补发",
                    })
                    logger.info("Task for %s queued (offline): %s", target_id[:12], description[:60])

            # ── R29: task_switch — fire-and-forget ─────────────────
            elif msg_type == p.MSG_TASK_SWITCH and agent_id:
                _users = auth.get_users()
                if _users.get(agent_id, {}).get("role") != "admin":
                    await _send(ws, {"type": "error", "error": "权限不足：仅管理员可发送 task_switch"})
                    continue

                target_id = msg.get("target", "").strip()
                if not target_id:
                    await _send(ws, {"type": "error", "error": "缺少 target 字段"})
                    continue

                # Resolve target by name if only name provided
                if target_id not in _users:
                    for aid, u in _users.items():
                        if u.get("name") == target_id:
                            target_id = aid
                            break

                if target_id and target_id in _users:
                    persistence.set_agent_channel(target_id, p.LOBBY)
                    persistence.save_agent_channels(config.DATA_DIR)
                    logger.info("Admin %s task-switched agent %s to lobby",
                                 agent_id[:12], target_id[:12])
                else:
                    logger.info("Admin %s task-switch target '%s' not found (silently ignored)",
                                 agent_id[:12], msg.get("target", "")[:20])
                # Fire-and-forget: 不回复 ACK

            # ── R29/R34: workspace_reset ──────────────────────────
            elif msg_type == p.MSG_WORKSPACE_RESET and agent_id:
                _users = auth.get_users()
                if _users.get(agent_id, {}).get("role") != "admin":
                    await _send(ws, {"type": "error", "error": "权限不足：仅管理员可执行 workspace_reset"})
                    continue

                workspace_id = msg.get("workspace_id", "").strip()
                all_flag = msg.get("all", False)
                target_id = msg.get("target", "").strip()

                # ── R34: Workspace-scoped reset ──────────────────
                if workspace_id:
                    ws_info = ws_mod.get_workspace(workspace_id)
                    if not ws_info:
                        await _send(ws, {"type": "error", "error": f"工作室 '{workspace_id}' 不存在"})
                        continue
                    if ws_info.state == ws_mod.WorkspaceState.CLOSING:
                        await _send(ws, {"type": "error", "error": f"工作室 '{workspace_id}' 正在关闭中，无法重置"})
                        continue
                    if ws_info.state == ws_mod.WorkspaceState.ARCHIVED:
                        await _send(ws, {"type": "error", "error": f"工作室 '{workspace_id}' 已归档，无法重置"})
                        continue

                    sender_name = _users.get(agent_id, {}).get("name", agent_id[:12])
                    member_ids = ws_info.members

                    reset_content = f"⚠️ 工作室 {workspace_id} 已重置，请各成员确认就位 🫡"
                    broadcast_payload = {
                        "type": "broadcast",
                        "channel": workspace_id,
                        "subtype": "workspace_reset",
                        "force": True,
                        "from_name": sender_name,
                        "agent_id": agent_id,
                        "from": sender_name,
                        "from_agent": agent_id,
                        "content": reset_content,
                        "ts": time.time(),
                    }
                    broadcast_json = json.dumps(broadcast_payload)

                    sent = 0
                    offline = 0
                    target_names = []
                    offline_names = []
                    _online = set(_connections.keys())

                    for mid in member_ids:
                        name = _users.get(mid, {}).get("name", mid[:12])
                        if mid in _online:
                            for conn in list(_connections.get(mid, set())):
                                try:
                                    if hasattr(conn, "send_str"):
                                        await conn.send_str(broadcast_json)
                                    elif hasattr(conn, "send"):
                                        await conn.send(broadcast_json)
                                    sent += 1
                                except Exception:
                                    pass
                            target_names.append(name)
                        else:
                            offline += 1
                            offline_names.append(name)
                            _offline_push_queue.setdefault(mid, []).append({
                                "type": "broadcast",
                                "channel": workspace_id,
                                "subtype": "workspace_reset",
                                "force": True,
                                "from_name": sender_name,
                                "agent_id": agent_id,
                                "content": reset_content,
                                "ts": time.time(),
                            })
                            if mid not in _offline_timers:
                                _offline_timers[mid] = asyncio.create_task(
                                    _flush_offline_push(mid)
                                )

                        persistence.set_agent_channel(mid, workspace_id)

                    persistence.save_agent_channels(config.DATA_DIR)
                    write_chat_log(sender_name, reset_content, channel=workspace_id)

                    reset_id = str(uuid.uuid4())
                    await _send(ws, {
                        "type": "ack",
                        "id": reset_id,
                        "delivery": {
                            "total": len(member_ids),
                            "sent": sent,
                            "offline": offline,
                            "targets": target_names,
                            "offline_targets": offline_names,
                        }
                    })
                    logger.info("Admin %s reset workspace '%s': %d sent, %d offline",
                                 agent_id[:12], workspace_id, sent, offline)

                # ── R29: Global reset (all: true) ────────────────
                elif all_flag:
                    for aid in _users:
                        if aid != agent_id:
                            persistence.set_agent_channel(aid, p.LOBBY)
                    persistence.save_agent_channels(config.DATA_DIR)
                    logger.info("Admin %s reset ALL agents to lobby", agent_id[:12])
                    await _send(ws, {"type": "ack", "status": "ok",
                                     "message": f"✅ 已重置全部 {len(_users)} 个成员到 lobby"})

                # ── R29: Single-target reset ─────────────────────
                elif target_id:
                    if target_id not in _users:
                        for aid, u in _users.items():
                            if u.get("name") == target_id:
                                target_id = aid
                                break
                    if target_id and target_id in _users:
                        persistence.set_agent_channel(target_id, p.LOBBY)
                        persistence.save_agent_channels(config.DATA_DIR)
                        target_name = _users.get(target_id, {}).get("name", target_id[:12])
                        logger.info("Admin %s reset agent %s to lobby", agent_id[:12], target_id[:12])
                        await _send(ws, {"type": "ack", "status": "ok",
                                         "message": f"✅ 已重置 {target_name} 到 lobby"})
                    else:
                        await _send(ws, {"type": "error", "error": f"目标成员 '{msg.get('target', '')}' 不存在"})

                else:
                    await _send(ws, {"type": "error", "error": "请指定 workspace_id、target 或设置 all: true"})

            # ── R67 C1: Heartbeat — update last_online silently ──────
            elif msg_type == p.MSG_HEARTBEAT:
                agent_id = sender_id
                card = ac_mod.get_agent_card(agent_id)
                if card:
                    card["last_online"] = time.time()
                    card["status"] = "online"
                    ac_mod.save_cards()
                continue  # do NOT broadcast heartbeat

            # ── R53 A-4: Channel switch ACK ──────────────────────
            elif msg_type == p.MSG_ACK and agent_id:
                ack_task_id = msg.get(p.FIELD_TASK_ID, "")
                status = msg.get(p.FIELD_TASK_STATUS, "switched")  # "switched" | "failed"
                channel = msg.get(p.FIELD_CHANNEL, "")

                # Find matching channel_ack_state by ack_task_id
                ws_id = _resolve_ws_by_ack_task_id(ack_task_id)
                if not ws_id or ws_id not in _channel_ack_state:
                    continue  # stale ACK or not waiting

                state = _channel_ack_state[ws_id]
                if status == "switched":
                    state["acked_members"][agent_id] = time.time()
                    await _send(ws, {"type": "ack", "status": "ok",
                                     "message": "✅ 频道切换已确认"})

                    # All online members acknowledged?
                    if set(state["acked_members"].keys()) >= state["online_members"]:
                        state["timer"].cancel()
                        asyncio.create_task(_notify_rollcall_complete(ws_id))
                # "failed" → record but don't block

            # ── R12 P0.3: Task ACK ──────────────────────────────
            elif msg_type == p.MSG_TASK_ACK and agent_id:
                task_id = msg.get(p.FIELD_TASK_ID, "")
                status = msg.get(p.FIELD_TASK_STATUS, "accepted")
                reason = msg.get(p.FIELD_TASK_REASON, "")

                timer = _task_ack_timers.pop(task_id, None)
                if timer:
                    timer.cancel()

                users = auth.get_users()
                admin_ids = {aid for aid, u in users.items() if u.get("role") == "admin"}
                sender_name = users.get(agent_id, {}).get("name", agent_id[:12])

                if status == "accepted":
                    # ★ R53 B-2: Advance task from submitted → working
                    task = ts.get_task(task_id, config.DATA_DIR)
                    if task and task.get("state") == p.TaskState.SUBMITTED.value:
                        ts.update_task(task_id, state=p.TaskState.WORKING.value, data_dir=config.DATA_DIR)
                        logger.info("R53: Task %s advanced to WORKING (ack by %s)", task_id, agent_id[:12])

                    ack_msg = json.dumps({
                        "type": p.MSG_DELIVERY_STATUS,
                        "task_id": task_id,
                        "status": "accepted",
                        "agent_id": agent_id,
                        "agent_name": sender_name,
                        "message": f"✅ {sender_name} 已接受任务",
                        "ts": time.time(),
                    })
                    for admin_id in admin_ids:
                        for conn in list(_connections.get(admin_id, set())):
                            try:
                                if hasattr(conn, "send_str"):
                                    await conn.send_str(ack_msg)
                                elif hasattr(conn, "send"):
                                    await conn.send(ack_msg)
                            except Exception:
                                pass
                    logger.info("Task %s accepted by %s", task_id, agent_id[:12])
                elif status == "rejected":
                    reject_msg = json.dumps({
                        "type": p.MSG_DELIVERY_STATUS,
                        "task_id": task_id,
                        "status": "rejected",
                        "agent_id": agent_id,
                        "agent_name": sender_name,
                        "reason": reason,
                        "message": f"❌ {sender_name} 拒绝了任务：{reason}",
                        "ts": time.time(),
                    })
                    for admin_id in admin_ids:
                        for conn in list(_connections.get(admin_id, set())):
                            try:
                                if hasattr(conn, "send_str"):
                                    await conn.send_str(reject_msg)
                                elif hasattr(conn, "send"):
                                    await conn.send(reject_msg)
                            except Exception:
                                pass
                    logger.info("Task %s rejected by %s: %s", task_id, agent_id[:12], reason)
                else:
                    await _send(ws, {"type": "error", "error": "Permission denied: only global admin can set workspace admin"})

            # ── R15: Workspace Admin Request ──────────────────────
            elif msg_type == p.MSG_ADMIN_REQUEST and agent_id:
                users = auth.get_users()
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                reason = msg.get(p.FIELD_REASON, "").strip()
                if not ws_id:
                    await _send(ws, {"type": "error", "error": "缺少 workspace_id"})
                    continue
                resolved = ws_mod.get_workspace(ws_id)
                if not resolved:
                    await _send(ws, {"type": "error", "error": "工作室不存在"})
                    continue
                if agent_id not in resolved.members:
                    await _send(ws, {"type": "error", "error": "您不是该工作室成员"})
                    continue
                if agent_id in resolved.admin_ids or agent_id == resolved.owner_id:
                    await _send(ws, {"type": "error", "error": "您已是该工作室的管理员"})
                    continue
                success, msg_text = ws_mod.submit_admin_request(ws_id, agent_id, reason)
                if not success:
                    await _send(ws, {"type": "error", "error": msg_text})
                    continue
                await _send(ws, {"type": "ack", "status": "submitted", "message": msg_text})
                # Notify all global admins
                requester_name = users.get(agent_id, {}).get("name", agent_id[:12])
                admin_ids = {aid for aid, u in users.items() if u.get("role") == "admin"}
                notify_payload = json.dumps({
                    "type": p.MSG_ADMIN_REQUEST,
                    "workspace_id": ws_id,
                    "requester_id": agent_id,
                    "requester_name": requester_name,
                    "reason": reason,
                    "ts": time.time(),
                })
                for admin_id in admin_ids:
                    for conn in list(_connections.get(admin_id, set())):
                        try:
                            if hasattr(conn, "send_str"):
                                await conn.send_str(notify_payload)
                            elif hasattr(conn, "send"):
                                await conn.send(notify_payload)
                        except Exception:
                            pass
                logger.info("Admin request from %s for workspace '%s': %s", agent_id[:12], ws_id, reason[:60])

            # ── R15: Workspace Admin Approved ─────────────────────
            elif msg_type == p.MSG_ADMIN_REQUEST_APPROVED and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") != "admin":
                    await _send(ws, {"type": "error", "error": "权限不足：仅全局管理员可审批"})
                    continue
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                target_id = msg.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                target_name = msg.get(p.FIELD_TARGET_AGENT, "").strip()
                if not ws_id or not target_id:
                    await _send(ws, {"type": "error", "error": "缺少 workspace_id 或 target_agent_id"})
                    continue
                # Resolve target_id by name if needed
                if not target_id and target_name:
                    for aid, u in users.items():
                        if u.get("name") == target_name:
                            target_id = aid
                            break
                if not target_id:
                    await _send(ws, {"type": "error", "error": f"未找到目标成员 {target_name}"})
                    continue
                # Update request status
                success, msg_text = ws_mod.approve_admin_request(ws_id, target_id, agent_id)
                if not success:
                    await _send(ws, {"type": "error", "error": msg_text})
                    continue
                # Call set_admin
                target_name_resolved = target_name or users.get(target_id, {}).get("name", target_id[:12])
                if not auth.set_workspace_admin(ws_id, target_id, agent_id):
                    await _send(ws, {"type": "error", "error": "设置管理员失败"})
                    continue
                # Notify the applicant
                notify_payload = json.dumps({
                    "type": p.MSG_ADMIN_NOTIFICATION,
                    "workspace_id": ws_id,
                    "status": "approved",
                    "message": f"✅ 你已成为 {ws_id} 的管理员",
                    "ts": time.time(),
                })
                for conn in list(_connections.get(target_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(notify_payload)
                        elif hasattr(conn, "send"):
                            await conn.send(notify_payload)
                    except Exception:
                        pass
                # Broadcast to workspace
                broadcast_payload = json.dumps({
                    "type": "broadcast",
                    "channel": ws_id,
                    "from_name": "系统",
                    "content": f"{target_name_resolved} 已成为 {ws_id} 的管理员",
                    "ts": time.time(),
                })
                for member_id in resolved.members if (resolved := ws_mod.get_workspace(ws_id)) else set():
                    for conn in list(_connections.get(member_id, set())):
                        try:
                            if hasattr(conn, "send_str"):
                                await conn.send_str(broadcast_payload)
                            elif hasattr(conn, "send"):
                                await conn.send(broadcast_payload)
                        except Exception:
                            pass
                await _send(ws, {"type": "ack", "message": f"✅ {target_name_resolved} 已成为管理员"})
                logger.info("Admin request approved: %s → admin of '%s' by %s", target_id[:12], ws_id, agent_id[:12])

            # ── R15: Workspace Admin Rejected ─────────────────────
            elif msg_type == p.MSG_ADMIN_REQUEST_REJECTED and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") != "admin":
                    await _send(ws, {"type": "error", "error": "权限不足：仅全局管理员可审批"})
                    continue
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                target_id = msg.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                target_name = msg.get(p.FIELD_TARGET_AGENT, "").strip()
                reject_reason = msg.get(p.FIELD_REASON, "").strip()
                if not ws_id or not target_id:
                    await _send(ws, {"type": "error", "error": "缺少 workspace_id 或 target_agent_id"})
                    continue
                if not target_id and target_name:
                    for aid, u in users.items():
                        if u.get("name") == target_name:
                            target_id = aid
                            break
                if not target_id:
                    await _send(ws, {"type": "error", "error": f"未找到目标成员 {target_name}"})
                    continue
                success, msg_text = ws_mod.reject_admin_request(ws_id, target_id, agent_id, reject_reason)
                if not success:
                    await _send(ws, {"type": "error", "error": msg_text})
                    continue
                # Notify the applicant
                reject_payload = json.dumps({
                    "type": p.MSG_ADMIN_NOTIFICATION,
                    "workspace_id": ws_id,
                    "status": "rejected",
                    "reason": reject_reason,
                    "message": f"❌ 申请被拒绝：{reject_reason}" if reject_reason else "❌ 申请被拒绝",
                    "ts": time.time(),
                })
                for conn in list(_connections.get(target_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(reject_payload)
                        elif hasattr(conn, "send"):
                            await conn.send(reject_payload)
                    except Exception:
                        pass
                await _send(ws, {"type": "ack", "message": f"✅ 已拒绝 {target_name or target_id[:12]} 的管理员申请"})
                logger.info("Admin request rejected: %s for '%s' by %s, reason: %s", target_id[:12], ws_id, agent_id[:12], reject_reason)

            elif msg_type == p.MSG_SET_ACTIVE_CHANNEL and agent_id:
                new_channel = msg.get(p.FIELD_CHANNEL, "").strip()
                if not new_channel:
                    await _send(ws, {"type": "error", "error": "Missing channel field"})
                    continue

                # Lobby is always allowed
                if new_channel == p.LOBBY:
                    persistence.set_agent_channel(agent_id, new_channel)
                    persistence.save_agent_channels(config.DATA_DIR)
                    await _send(ws, {"type": p.MSG_CHANNEL_UPDATED, p.FIELD_ACTIVE_CHANNEL: new_channel})
                    logger.info("Agent %s active channel set to lobby", agent_id[:20])
                    continue

                # Workspace: verify membership
                ws_obj = ws_mod.get_workspace(new_channel)
                if not ws_obj or ws_obj.state != ws_mod.WorkspaceState.ACTIVE:
                    await _send(ws, {'type': 'error', 'error': f"Workspace '{new_channel}' not found or not active"})
                    continue
                if agent_id not in ws_obj.members and agent_id != ws_obj.owner_id:
                    await _send(ws, {'type': 'error', 'error': 'You are not a member of this workspace'})
                    continue

                persistence.set_agent_channel(agent_id, new_channel)
                persistence.save_agent_channels(config.DATA_DIR)
                await _send(ws, {"type": p.MSG_CHANNEL_UPDATED, p.FIELD_ACTIVE_CHANNEL: new_channel})
                logger.info("Agent %s active channel set to '%s'", agent_id[:20], new_channel)

            elif msg_type == p.MSG_REGISTER_AGENT and agent_id:
                # R23: Only P4 (global admin) can register agents
                users = auth.get_users()
                role = users.get(agent_id, {}).get("role", "member")
                if role != "admin":
                    await _send(ws, {"type": "error", "error": "Permission denied: only admin can register agents"})
                    continue
                target_id = msg.get("target_agent_id", "").strip()
                if not target_id:
                    await _send(ws, {"type": "error", "error": "Missing target_agent_id"})
                    continue
                # Approve agent via persistence (not auth — auth reads from persistence)
                users[target_id] = {"name": target_id, "role": "member"}
                persistence.set_approved_users(users)
                persistence.save_approved_users(config.DATA_DIR)
                # Move to lobby + clean registration channel
                persistence.set_agent_channel(target_id, p.LOBBY)
                persistence.save_agent_channels(config.DATA_DIR)
                # Notify if online
                for conn in list(_connections.get(target_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(json.dumps({
                                "type": p.MSG_REGISTRATION_CONFIRMED,
                                p.FIELD_ACTIVE_CHANNEL: p.LOBBY,
                            }))
                        elif hasattr(conn, "send"):
                            await conn.send(json.dumps({
                                "type": p.MSG_REGISTRATION_CONFIRMED,
                                p.FIELD_ACTIVE_CHANNEL: p.LOBBY,
                            }))
                    except Exception:
                        pass
                # R36 B-3: Welcome message to newly registered agent (纯文本, write_chat_log)
                _reg_name = users.get(target_id, {}).get("name", target_id[:12])
                write_chat_log("系统", f"[注册] 注册成功 — 欢迎 {_reg_name}（使用 @点名 或 📋 等前缀与队友沟通）")
                await _send(ws, {"type": "ok", "message": f"Agent {target_id[:20]} registered"})
                logger.info("[REG] Agent %s registered by %s", target_id[:20], agent_id[:20])

            elif msg_type == p.MSG_MANAGE_MEMBER and agent_id:
                # Workspace admin can add/remove members in their workspace
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                target_id = msg.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                action = msg.get(p.FIELD_ACTION, "").strip()
                if ws_id and target_id and action:
                    resolved_workspace = ws_mod.get_workspace(ws_id)
                    if resolved_workspace and resolved_workspace.state == ws_mod.WorkspaceState.ACTIVE:
                        if auth.can_manage_workspace(ws_id, agent_id):
                            if action == "add":
                                if ws_mod.add_member(ws_id, target_id):
                                    await _send(ws, {"type": "ok", "workspace_id": ws_id, "member_id": target_id, "action": "add"})
                                    logger.info("Member %s added to workspace '%s' by admin %s", target_id[:20], ws_id, agent_id[:20])
                                else:
                                    await _send(ws, {"type": "error", "error": "Failed to add member"})
                            elif action == "remove":
                                if ws_mod.remove_member(ws_id, target_id):
                                    await _send(ws, {"type": "ok", "workspace_id": ws_id, "member_id": target_id, "action": "remove"})
                                    logger.info("Member %s removed from workspace '%s' by admin %s", target_id[:20], ws_id, agent_id[:20])
                                else:
                                    await _send(ws, {"type": "error", "error": "Failed to remove member"})
                            else:
                                await _send(ws, {"type": "error", "error": f"Unknown action '{action}': use 'add' or 'remove'"})
                        else:
                            await _send(ws, {"type": "error", "error": "Permission denied"})
                    else:
                        await _send(ws, {"type": "error", "error": "Workspace not found or not active"})
                else:
                    await _send(ws, {"type": "error", "error": "Missing workspace_id, target_agent_id, or action"})

            elif msg_type == p.MSG_WORKSPACE_ACK_CLOSE and agent_id:
                ws_id = msg.get("workspace_id", "").strip()
                if ws_id:
                    ws_mod.confirm_ack(ws_id, agent_id)
                    resolved_workspace = ws_mod.get_workspace(ws_id)
                    if resolved_workspace and resolved_workspace.closing_acks >= resolved_workspace.members:
                        await _broadcast_workspace_closing(ws_id, force_finalize=True)

            elif msg_type == "approve_web" and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    code = msg.get("code", "").strip().upper()
                    name = msg.get("name", "大宏")
                    result = auth.approve_web_bind_code(code, name)
                    if result.get("type") == "approve_ok":
                        persistence.save_web_bind_codes(config.DATA_DIR)
                        persistence.save_web_sessions(config.DATA_DIR)
                        logger.info("Web viewer '%s' approved via WS", name)
                    await _send(ws, result)

            elif msg_type == p.MSG_TOKEN_SET_MODE and agent_id:
                # Admin only: set token/free mode
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                    mode = msg.get(p.FIELD_TOKEN_MODE, "").strip()
                    if ws_id and mode:
                        if ws_mod.set_token_mode(ws_id, mode):
                            await _send(ws, {"type": p.MSG_TOKEN_MODE_SET, "workspace_id": ws_id, "mode": mode})
                            logger.info("Admin %s set workspace '%s' token mode → %s", agent_id[:20], ws_id, mode)
                        else:
                            await _send(ws, {"type": "error", "error": "Failed to set token mode"})
                    else:
                        await _send(ws, {"type": "error", "error": "Missing workspace_id or mode"})
                else:
                    await _send(ws, {"type": "error", "error": "Permission denied: only admin can change token mode"})

            elif msg_type == p.MSG_TOKEN_SET_ORDER and agent_id:
                # Admin only: set token order
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                    order = msg.get(p.FIELD_TOKEN_ORDER, [])
                    if ws_id and order:
                        if ws_mod.set_token_order(ws_id, order):
                            await _send(ws, {"type": p.MSG_TOKEN_ORDER_SET, "workspace_id": ws_id, "order": order})
                            logger.info("Admin %s set workspace '%s' token order", agent_id[:20], ws_id)
                    else:
                        await _send(ws, {"type": "error", "error": "Missing workspace_id or order"})
                else:
                    await _send(ws, {"type": "error", "error": "Permission denied"})

            elif msg_type == p.MSG_TOKEN_ADVANCE and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                    next_token = msg.get(p.FIELD_TOKEN_CURRENT, 0)
                    if ws_id:
                        if ws_mod.advance_token(ws_id, next_token):
                            stats = ws_mod.get_token_status(ws_id)
                            await _send(ws, {"type": p.MSG_TOKEN_ADVANCED, "workspace_id": ws_id, **stats})
                    else:
                        await _send(ws, {"type": "error", "error": "Missing workspace_id"})
                else:
                    await _send(ws, {"type": "error", "error": "Permission denied"})

            elif msg_type == p.MSG_TOKEN_SKIP and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                    if ws_id:
                        if ws_mod.skip_token(ws_id):
                            stats = ws_mod.get_token_status(ws_id)
                            await _send(ws, {"type": p.MSG_TOKEN_SKIPPED, "workspace_id": ws_id, **stats})
                        else:
                            await _send(ws, {"type": "error", "error": "Cannot skip: already at end of order"})
                else:
                    await _send(ws, {"type": "error", "error": "Permission denied"})

            elif msg_type == p.MSG_TOKEN_STATUS and agent_id:
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                if ws_id:
                    stats = ws_mod.get_token_status(ws_id)
                    if stats:
                        await _send(ws, {"type": p.MSG_TOKEN_STATUS_RESULT, "workspace_id": ws_id, **stats})
                    else:
                        await _send(ws, {"type": "error", "error": "Workspace not found"})

            elif msg_type == "ping":
                await _send(ws, {"type": "pong"})

            else:
                await _send(ws, {"type": "error", "error": "Unknown msg or not authenticated"})

    except Exception as e:
        logger.warning("Connection error: %s", e)
    finally:
        if agent_id and agent_id in _connections:
            _connections[agent_id].discard(ws)
            if not _connections[agent_id]:
                del _connections[agent_id]
            logger.info("Agent %s disconnected (%d remaining)", agent_id[:20] if agent_id else "unknown", len(_connections))


# ── Workspace Closing ──────────────────────────────────────────────

async def _broadcast_workspace_closing(ws_id: str, force_finalize: bool = False) -> None:
    """Notify workspace members of impending close and wait for ACKs."""
    resolved_workspace = ws_mod.get_workspace(ws_id)
    if not resolved_workspace or resolved_workspace.state != ws_mod.WorkspaceState.CLOSING:
        return

    deadline_ts = time.time() + p.WORKSPACE_CLOSING_TIMEOUT
    payload = json.dumps({
        "type": p.MSG_WORKSPACE_CLOSING,
        p.FIELD_WORKSPACE_ID: ws_id,
        p.FIELD_REASON: "task_completed",
        p.FIELD_DEADLINE_TS: deadline_ts,
        p.FIELD_ACK_REQUIRED: True,
    })

    # Broadcast to all members
    for agent_id in resolved_workspace.members:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload)
                elif hasattr(conn, "send"):
                    await conn.send(payload)
            except Exception:
                pass

    if force_finalize:
        ws_mod.finalize_close(ws_id)
        await _broadcast_workspace_archived(ws_id, resolved_workspace)
        return

    # Wait for ACKs with timeout
    await asyncio.sleep(p.WORKSPACE_CLOSING_TIMEOUT)

    # Force-close any unacked members
    resolved_workspace = ws_mod.get_workspace(ws_id)
    if resolved_workspace and resolved_workspace.state == ws_mod.WorkspaceState.CLOSING:
        unacked = resolved_workspace.members - resolved_workspace.closing_acks
        if unacked:
            logger.warning("Workspace '%s': force-closing unacked members: %s", ws_id, unacked)
            for aid in unacked:
                resolved_workspace.closing_acks.add(aid)
        ws_mod.finalize_close(ws_id)
        await _broadcast_workspace_archived(ws_id, resolved_workspace)


# ── Broadcast Workspace Archived ──────────────────────────────────


async def _broadcast_workspace_archived(ws_id: str, resolved_workspace=None) -> None:
    """Broadcast that workspace has been archived — Web UI uses to regroup tab."""
    if resolved_workspace is None:
        resolved_workspace = ws_mod.get_workspace(ws_id)
    if not resolved_workspace:
        return
    # R7: reset owner's active channel when workspace is archived
    persistence.reset_agent_channel(resolved_workspace.owner_id)
    persistence.save_agent_channels(config.DATA_DIR)
    logger.info("Owner %s active channel reset (workspace '%s' archived)",
                 resolved_workspace.owner_id[:20], ws_id)
    arch_payload = json.dumps({
        "type": "broadcast",
        "channel": ws_id,
        "from_name": "系统",
        "content": f"workspace {ws_id} 已归档",
        "_workspace_event": "archived",
        "workspace_id": ws_id,
        "ts": time.time(),
    })
    for agent_id in resolved_workspace.members:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(arch_payload)
                elif hasattr(conn, "send"):
                    await conn.send(arch_payload)
            except Exception:
                pass