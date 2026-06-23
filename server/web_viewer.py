"""Web viewer — chat log viewer + bind code auth + multi-tab channels."""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uuid

import aiohttp
from aiohttp import web

from . import auth, config, persistence, workspace as ws_mod
from . import message_store as ms
from .templates import BIND_TEMPLATE, CHAT_TEMPLATE

logger = logging.getLogger("ws-bridge.web")

# ── In-memory chat log buffer (per channel) ────────────────────
_chat_buffers: dict[str, list[dict]] = {"lobby": []}
_MAX_BUFFER = 1000
_ws_clients: set = set()  # single set, JS does channel dispatch

# ── Daily chat log file (per channel) ──────────────────────────


def _today_str() -> str:
    ict_now = datetime.now(timezone.utc) + timedelta(hours=7)
    return ict_now.strftime("%Y-%m-%d")


def write_chat_log(sender_name: str, content: str, channel: str = "lobby") -> None:
    """Append a chat message to channel-specific daily log file + buffer."""
    global _ws_clients, _chat_buffers
    ict_now = datetime.now(timezone.utc) + timedelta(hours=7)
    ts = ict_now.strftime("%H:%M:%S")
    line = f"[{ts}] {sender_name}: {content}"
    safe_channel = channel.replace("/", "_").replace(":", "_")

    # Write to per-channel daily log file
    today = _today_str()
    try:
        config.CHAT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = config.CHAT_LOG_DIR / f"chat_{today}_{safe_channel}.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        logger.warning("Failed to write chat log: %s", e)

    # Add to in-memory buffer
    if channel not in _chat_buffers:
        _chat_buffers[channel] = []
    entry = {"ts": ts, "sender": sender_name, "content": content}
    _chat_buffers[channel].append(entry)
    # R32 D-1: Persist to message store for DB-backed retrieval
    try:
        ms.save_message(
            msg_id=str(uuid.uuid4()),
            msg_type="broadcast",
            from_agent="web_log",
            from_name=sender_name,
            content=content,
            ts=time.time(),
            data_dir=config.DATA_DIR,
            channel=channel,
        )
    except Exception:
        pass
    if len(_chat_buffers[channel]) > _MAX_BUFFER:
        _chat_buffers[channel][:100] = []

    # Push live to all WS clients with channel field
    payload = json.dumps({
        "type": "chat_message",
        "channel": channel,
        "message": entry,
    })
    dead = set()
    for ws in _ws_clients:
        try:
            ws.send_str(payload)
        except Exception:
            dead.add(ws)
    _ws_clients -= dead


def read_channel_logs(channel: str = "lobby", days: int = 1) -> list[dict]:
    """Read chat logs from channel-specific files, spanning multiple days.
    
    Args:
        channel: Channel name (default "lobby").
        days: Number of days to look back (default 1 = today only).
              Specify 7 for a week's worth of logs.
    
    Returns:
        List of message dicts, newest first.
    """
    # Try in-memory buffer first (always has latest)
    if channel in _chat_buffers and _chat_buffers[channel]:
        result = list(_chat_buffers[channel])
    else:
        result = []

    safe_channel = channel.replace("/", "_").replace(":", "_")
    seen_entries = set()
    # Dedup: mark buffer entries so we don't double-add from files
    for e in result:
        seen_entries.add((e["ts"], e["sender"], e["content"]))

    # Read from log files, going back 'days' days
    for offset in range(days):
        d = datetime.now(timezone.utc) + timedelta(hours=7) - timedelta(days=offset)
        day_str = d.strftime("%Y-%m-%d")
        path = config.CHAT_LOG_DIR / f"chat_{day_str}_{safe_channel}.log"
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            for line in reversed(lines):
                if not line:
                    continue
                if line.startswith("[") and "] " in line:
                    rest = line[1:].split("] ", 1)
                    ts = rest[0]
                    rest2 = rest[1].split(": ", 1) if len(rest) > 1 else ["", ""]
                    sender = rest2[0] if len(rest2) > 0 else ""
                    msg_content = rest2[1] if len(rest2) > 1 else ""
                    key = (ts, sender, msg_content)
                    if key not in seen_entries:
                        seen_entries.add(key)
                        result.append({"ts": ts, "sender": sender, "content": msg_content})
        except OSError:
            continue

    # Return newest first (most recent = last appended to result list)
    result.reverse()
    return result


# R32 D-2: Keep backward-compat alias
read_today_log = read_channel_logs


# ── Auth helpers ──────────────────────────────────────────────────


def validate_token(token: str) -> str | None:
    sessions = persistence.get_web_sessions()
    # R33: defensive — if sessions empty but token looks valid, log for debugging
    entry = sessions.get(token)
    if entry:
        return entry.get("name")
    # R33: debug log when valid-looking token is rejected (deployment session loss)
    if token and len(token) >= 8:
        logger.debug("validate_token: token %s... not found in %d sessions", token[:8], len(sessions))
    return None


# ── API handlers ──────────────────────────────────────────────────


async def handle_chat(request: web.Request) -> web.Response:
    """Serve the chat HTML page."""
    try:
        token = request.query.get("token", "")
        if not token:
            session_id = request.cookies.get("ws_im_session", "")
            if session_id:
                token = session_id
        viewer = validate_token(token) if token else None
        if not viewer:
            return web.Response(text=BIND_TEMPLATE, content_type="text/html", charset="utf-8")
        html = CHAT_TEMPLATE.replace("__TOKEN__", token).replace("__VIEWER__", viewer or "大宏")
        return web.Response(text=html, content_type="text/html", charset="utf-8")
    except Exception as e:
        logger.error("handle_chat error: %s", e, exc_info=True)
        return web.Response(text=f"Error: {e}", status=500)


async def handle_api_bind(request: web.Request) -> web.Response:
    code = auth.generate_web_bind_code()
    auth.create_web_bind_code(code)
    persistence.save_web_bind_codes(config.DATA_DIR)
    return web.json_response({"code": code})


async def handle_api_check(request: web.Request) -> web.Response:
    code = request.query.get("code", "").strip().upper()
    if not code.startswith(auth.WEB_CODE_PREFIX):
        return web.json_response({"approved": False})
    codes = persistence.get_web_bind_codes()
    entry = codes.get(code)
    if not entry:
        return web.json_response({"approved": False, "error": "not_found"})
    if entry.get("approved"):
        # R8: Set session cookie (7 days) so client restores login on reopen
        resp = web.json_response({
            "approved": True,
            "token": entry["token"],
            "name": entry.get("name", ""),
        })
        resp.set_cookie(
            "ws_im_session",
            entry["token"],
            max_age=604800,     # 7 days
            httponly=True,
            samesite="Lax",
            path="/",
        )
        return resp
    return web.json_response({"approved": False})


async def handle_api_chat(request: web.Request) -> web.Response:
    """Return messages for a specific channel (from DB + log fallback)."""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)

    channel = request.query.get("channel", "lobby")
    limit = int(request.query.get("limit", "50"))

    # Try DB first (Phase 1 message_store)
    try:
        db_msgs = ms.get_messages_by_channel(channel, config.DATA_DIR, limit=limit)
        if db_msgs:
            # DB returns newest first (ORDER BY ts DESC); frontend reverse-iterates
            return web.json_response({"channel": channel, "messages": db_msgs})
    except Exception:
        pass

    # Fallback to log file (log returns oldest→newest, reverse for newest→oldest)
    messages = read_today_log(channel)
    if messages:
        msgs = messages[-limit:]
        msgs.reverse()
        return web.json_response({"channel": channel, "messages": msgs})
    return web.json_response({"channel": channel, "messages": []})


async def handle_api_channels(request: web.Request) -> web.Response:
    """Return available channels — dynamically from workspace module, with state (active/archived)."""
    channels = [
        {"id": "lobby", "name": "大厅", "emoji": "🌐", "state": "active"},
    ]
    # Merge all workspaces (active + archived)
    try:
        ws_list = ws_mod.get_all_workspaces()
        for ws in ws_list:
            state = ws.state.value
            channels.append({
                "id": ws.id,
                "name": ws.name,
                "emoji": "📋" if state == "active" else "🗂️",
                "state": state,
                "admin_ids": list(ws.admin_ids),
            })
    except Exception:
        pass
    return web.json_response({"channels": channels})


async def handle_ws_chat(request: web.Request) -> web.WebSocketResponse:
    """WebSocket endpoint for live chat updates."""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.WebSocketResponse()

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    _ws_clients.add(ws)

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.PONG:
                continue
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
    except Exception:
        pass
    finally:
        _ws_clients.discard(ws)
    return ws


async def handle_api_approve_web(request: web.Request) -> web.Response:
    peer = request.remote
    if peer not in ("127.0.0.1", "::1", "localhost"):
        return web.json_response({"error": "forbidden"}, status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)

    code = body.get("code", "").strip().upper()
    name = body.get("name", "大宏")
    result = auth.approve_web_bind_code(code, name)
    persistence.save_web_bind_codes(config.DATA_DIR)
    persistence.save_web_sessions(config.DATA_DIR)

    if result.get("type") == "approve_ok":
        logger.info("Web viewer '%s' approved", name)
    return web.json_response(result)


# ── R8: Logout endpoint ────────────────────────────────────────


async def handle_api_logout(request: web.Request) -> web.Response:
    """Clear session cookie → client returns to bind page on reload."""
    resp = web.json_response({"ok": True})
    resp.del_cookie("ws_im_session", path="/")
    return resp


# ── R8: Message search endpoint ─────────────────────────────────


async def handle_api_chat_search(request: web.Request) -> web.Response:
    """Search messages in a channel. Query params: q, channel, sender, limit."""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)

    q = request.query.get("q", "").strip()
    if not q or len(q) < 1:
        return web.json_response({"error": "Query too short"}, status=400)

    channel = request.query.get("channel", None) or None
    sender = request.query.get("sender", None) or None
    limit = int(request.query.get("limit", "50"))

    results = ms.search_messages(
        query=q,
        data_dir=config.DATA_DIR,
        limit=limit,
        channel=channel,
        sender=sender,
    )
    return web.json_response({
        "query": q,
        "channel": channel or "all",
        "sender": sender or "",
        "count": len(results),
        "results": results,
    })


async def _handle_health(request: web.Request) -> web.Response:
    return web.Response(text="ok\n")


# ── R11 P1.3: Online status API ────────────────────────────────────


async def handle_api_agents_status(request: web.Request) -> web.Response:
    """Return online/offline status for all registered agents."""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)

    # Lazy import to avoid circular dep (handler.py imports web_viewer.write_chat_log)
    from . import handler as _handler
    connections = _handler.get_connections()
    users = auth.get_users()
    result = {}
    for agent_id, user_info in users.items():
        name = user_info.get("name", agent_id[:12])
        is_online = agent_id in connections
        workspaces = []
        try:
            ws_list = ws_mod.get_workspaces_for_agent(agent_id)
            workspaces = [w.id for w in ws_list if w.state == ws_mod.WorkspaceState.ACTIVE]
        except Exception:
            pass
        result[agent_id] = {
            "name": name,
            "online": is_online,
            "role": user_info.get("role", "member"),
            "workspaces": workspaces,
        }
    return web.json_response({
        "agents": result,
        "total": len(result),
        "online": sum(1 for a in result.values() if a["online"]),
    })


# ── Routes registration ──────────────────────────────────────────


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/", handle_chat)
    app.router.add_get("/chat", handle_chat)
    app.router.add_get("/api/bind", handle_api_bind)
    app.router.add_get("/api/check", handle_api_check)
    app.router.add_get("/api/chat", handle_api_chat)
    app.router.add_post("/api/approve_web", handle_api_approve_web)
    app.router.add_get("/ws/chat", handle_ws_chat)
    app.router.add_get("/api/channels", handle_api_channels)
    app.router.add_get("/health", _handle_health)
    # R8: logout
    app.router.add_post("/api/logout", handle_api_logout)
    # R8: search
    app.router.add_get("/api/chat/search", handle_api_chat_search)
    # R11 P1.3: agent status
    app.router.add_get("/api/agents/status", handle_api_agents_status)