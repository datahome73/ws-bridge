"""WebSocket handler and broadcast logic — admin-relay mode + channel routing."""
import asyncio
import json
import logging
import re
import time
import uuid

from . import auth, config, persistence
from . import message_store as ms
from . import workspace as ws_mod
from .web_viewer import write_chat_log
import shared.protocol as p

logger = logging.getLogger("ws-bridge")

_connections: dict[str, set] = {}

# P6: message send stats
_send_stats: dict = {"total": 0, "total_latency": 0.0}

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
        logger.info("Approved agent %s (role=%s)", result["agent_id"][:20], data.get("role", "member"))
    return result



async def handle_broadcast(ws, sender_id: str, msg: dict) -> None:
    """Admin-relay mode:
    - Non-admin (member) → relay ONLY to admin(s)
    - Admin → relay to specific target (via 'to' field or @mention)
    - All messages → written to chat log (大宏/网页端可见)
    - Channel messages (non-lobby) → scoped to workspace members + admin
    """
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

    # R12 P1.2: Nonsense message filter + duplicate detection
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

    # R26: 📢 admin-only check — non-admin agents cannot use 📢 prefix
    if content.startswith("📢") and sender_id not in config.BROADCAST_ADMINS:
        await _send(ws, {
            "type": "error",
            "error": "📢 公告仅管理员可用。如需广播请使用 @用户名 或 📋 点名前缀",
        })
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

            # Send ACK
            if msg_id:
                await _send(ws, {"type": "ack", "id": msg_id})

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

    # Send ACK to the original sender
    if msg_id:
        await _send(ws, {"type": "ack", "id": msg_id})
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

    # R29: 📋 roll-call — send online member list to admin
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


# ── R11 P2.2: Membership change notification ────────────────────


async def _notify_member_changed(ws_id: str, member_id: str, event: str) -> None:
    """Notify all workspace members of membership change (joined/removed)."""
    resolved = ws_mod.get_workspace(ws_id)
    if not resolved:
        return
    users = auth.get_users()
    member_name = users.get(member_id, {}).get("name", member_id[:12])
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

            # ── R29: workspace_reset ───────────────────────────────
            elif msg_type == p.MSG_WORKSPACE_RESET and agent_id:
                _users = auth.get_users()
                if _users.get(agent_id, {}).get("role") != "admin":
                    await _send(ws, {"type": "error", "error": "权限不足：仅管理员可执行 workspace_reset"})
                    continue

                all_flag = msg.get("all", False)
                target_id = msg.get("target", "").strip()

                if all_flag:
                    for aid in _users:
                        if aid != agent_id:
                            persistence.set_agent_channel(aid, p.LOBBY)
                    persistence.save_agent_channels(config.DATA_DIR)
                    logger.info("Admin %s reset ALL agents to lobby", agent_id[:12])
                    await _send(ws, {"type": "ack", "status": "ok",
                                     "message": f"✅ 已重置全部 {len(_users)} 个成员到 lobby"})
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
                    await _send(ws, {"type": "error", "error": "请指定 target 或设置 all: true"})

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