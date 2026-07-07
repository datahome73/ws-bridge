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
import secrets
from .templates import BIND_TEMPLATE, CHAT_TEMPLATE
import time as _time  # R76: explicit time import for archive state

logger = logging.getLogger("ws-bridge.web")

# ── In-memory chat log buffer (per channel) ────────────────────
_chat_buffers: dict[str, list[dict]] = {"lobby": []}
_MAX_BUFFER = 1000
_ws_clients: set = set()  # single set, JS does channel dispatch


async def _do_ws_send(ws, payload: str) -> None:
    """Fire-and-forget helper: safely send a WS payload, discard dead clients."""
    try:
        await ws.send_str(payload)
    except (ConnectionError, RuntimeError, OSError):
        _ws_clients.discard(ws)
    except Exception:
        pass


# ── Daily chat log file (per channel) ──────────────────────────


# ── R76: Archive state persistence ────────────────────────────────────

_ARCHIVE_STATE_FILE = "_archive_state.json"


def _load_archive_state() -> dict:
    """Load archive state from disk. Returns default if file missing."""
    path = config.DATA_DIR / _ARCHIVE_STATE_FILE
    if not path.exists():
        return {"last_archive_ts": 0, "archived_workspaces": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"last_archive_ts": 0, "archived_workspaces": []}


def _save_archive_state(state: dict) -> None:
    """Persist archive state to disk."""
    path = config.DATA_DIR / _ARCHIVE_STATE_FILE
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def set_archive_state(ws_id: str, ws_name: str, start_ts: float) -> None:
    """Record archive entry for a workspace. Called when last workspace closes."""
    now = _time.time()
    state = _load_archive_state()
    state["last_archive_ts"] = now
    state["archived_workspaces"].append({
        "id": ws_id,
        "name": ws_name,
        "created_at": start_ts,
        "closed_at": now,
        "archive_window": {"start": start_ts, "end": now},
    })
    _save_archive_state(state)


def _today_str() -> str:
    ict_now = datetime.now(timezone.utc) + timedelta(hours=7)
    return ict_now.strftime("%Y-%m-%d")


def write_chat_log(sender_name: str, content: str, channel: str = "lobby") -> None:
    """Append a chat message to channel-specific daily log file + buffer."""
    global _ws_clients, _chat_buffers
    ict_now = datetime.now(timezone.utc) + timedelta(hours=7)
    # 🔧 F-8: Use numeric ts (time.time()) for dedup consistency with DB path
    # Keep human-readable format for log file line
    ts_human = ict_now.strftime("%H:%M:%S")
    ts = time.time()
    line = f"[{ts_human}] {sender_name}: {content}"
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
    if len(_chat_buffers[channel]) > _MAX_BUFFER:
        _chat_buffers[channel][:100] = []

    # Push live to all WS clients with channel field
    payload = json.dumps({
        "type": "chat_message",
        "channel": channel,
        "message": entry,
    })
    for ws in list(_ws_clients):
        asyncio.create_task(_do_ws_send(ws, payload))


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
        seen_entries.add((e["ts"], e["sender"], e["content"], "buffer"))

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
                    key = (ts, sender, msg_content, day_str)
                    if key not in seen_entries:
                        seen_entries.add(key)
                        result.append({"ts": ts, "sender": sender, "content": msg_content})
        except OSError:
            continue

    # Return messages as collected (oldest-first from buffer + newest-first from file)
    return result


# R36 D-2: Keep backward-compat alias
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
            "token": entry.get("token", ""),
            "name": entry.get("name", ""),
        })
        resp.set_cookie(
            "ws_im_session",
            entry.get("token", ""),
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

    # R76 B3: optional since parameter — only messages after this timestamp
    since = request.query.get("since", None)
    if since:
        try:
            since = float(since)
        except (ValueError, TypeError):
            since = None

    # Try DB first (Phase 1 message_store)
    if since is not None:
        try:
            db_msgs = ms.get_messages_since(since, config.DATA_DIR, limit=limit, channel=channel)
            if db_msgs:
                # ★ 强制倒序：最新在上
                return web.json_response({"channel": channel, "messages": db_msgs})
        except Exception:
            pass
    else:
        try:
            db_msgs = ms.get_messages_by_channel(channel, config.DATA_DIR, limit=limit)
            if db_msgs:
                # ★ 强制倒序：最新在上
                db_msgs.reverse()
                return web.json_response({"channel": channel, "messages": db_msgs})
        except Exception:
            pass

    # Fallback to log file — R36 D-2: multi-day fallback (days=7 for broader history)
    messages = read_channel_logs(channel, days=7)
    if messages:
        # Sort by ts descending (newest first)
        def _sort_key(m):
            ts = m.get("ts", 0)
            if isinstance(ts, (int, float)):
                return ts
            try:
                parts = ts.split(":")
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            except (ValueError, IndexError):
                return 0
        messages.sort(key=_sort_key, reverse=True)
        # ★ 强制倒序：最新在上
        messages.reverse()
        return web.json_response({"channel": channel, "messages": messages[:limit]})
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

    # R76 B3: attach archive state so frontend knows whether to use since filtering
    try:
        active_ws = [w for w in ws_mod.get_all_workspaces()
                     if w.state == ws_mod.WorkspaceState.ACTIVE]
        arch_state = _load_archive_state()
        archive_state = {
            "active": len(active_ws) > 0,
            "last_archive_ts": arch_state.get("last_archive_ts", 0),
        }
    except Exception:
        archive_state = {"active": True, "last_archive_ts": 0}

    return web.json_response({"channels": channels, "archive_state": archive_state})


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


# ── R76 A: Inbox aggregation API ──────────────────────────────────────


async def handle_api_inbox(request: web.Request) -> web.Response:
    """Return aggregated inbox messages with resolved recipient names.

    GET /api/chat/inbox?token={token}&limit={n}&since={ts}
    """
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)

    limit = int(request.query.get("limit", "50"))
    since = request.query.get("since", None)
    since = float(since) if since else None

    try:
        db_msgs = ms.get_messages_by_channel_pattern(
            "_inbox:%", config.DATA_DIR, limit=limit, since=since
        )
    except Exception:
        db_msgs = []

    # Resolve recipient names from channel
    for m in db_msgs:
        owner_id = persistence.resolve_inbox_owner(m.get("channel", ""))
        m["to_name"] = auth.get_agent_name(owner_id) if owner_id else (owner_id or "?")
        m["to_agent"] = owner_id or ""

    return web.json_response({"messages": db_msgs})


# ── R76 B: Archive API — full channel history for a workspace ─────────


async def handle_api_archive(request: web.Request) -> web.Response:
    """Return all messages from a workspace's archive window, across all channels.

    GET /api/chat/archive?workspace_id={id}&token={token}
    """
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)

    ws_id = request.query.get("workspace_id", "")
    if not ws_id:
        return web.json_response({"error": "missing workspace_id"}, status=400)

    state = _load_archive_state()
    ws_info = None
    for ws in state.get("archived_workspaces", []):
        if ws["id"] == ws_id:
            ws_info = ws
            break
    if not ws_info:
        return web.json_response({"error": "workspace not found"}, status=404)

    start = ws_info["archive_window"]["start"]
    end = ws_info["archive_window"]["end"]

    all_msgs = ms.get_messages_by_time_range(start, end, config.DATA_DIR)

    # Add channel labels + inbox recipient resolution
    for m in all_msgs:
        ch = m.get("channel", "")
        if ch == "lobby":
            m["_channel_label"] = "大厅"
        elif ch == "_admin":
            m["_channel_label"] = "管理员"
        elif ch.startswith("_inbox:"):
            owner_id = persistence.resolve_inbox_owner(ch)
            to_name = auth.get_agent_name(owner_id) if owner_id else "?"
            m["to_name"] = to_name
            m["to_agent"] = owner_id or ""
            m["_channel_label"] = f"收件箱（{to_name}）"
        else:
            m["_channel_label"] = ch

    return web.json_response({
        "workspace": ws_info["name"],
        "period": ws_info["archive_window"],
        "messages": all_msgs,
        "total": len(all_msgs),
    })


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



# ── R40: GitHub OAuth ────────────────────────────────────────────────


async def handle_github_login(request: web.Request) -> web.Response:
    """Redirect to GitHub OAuth authorization page."""
    client_id = config.GITHUB_OAUTH_CLIENT_ID
    if not client_id:
        return web.Response(text="GitHub OAuth not configured", status=501)
    redirect_uri = config.GITHUB_OAUTH_REDIRECT_URI
    state = secrets.token_hex(16)
    if "oauth_states" not in request.app:
        request.app["oauth_states"] = {}
    request.app["oauth_states"][state] = True
    import urllib.parse as _urlparse
    github_url = (
        "https://github.com/login/oauth/authorize?"
        "client_id=" + _urlparse.quote(client_id, safe="") + "&"
        "redirect_uri=" + _urlparse.quote(redirect_uri, safe="") + "&"
        "state=" + _urlparse.quote(state, safe="") + "&"
        "scope=read:user"
    )
    raise web.HTTPFound(location=github_url)


async def handle_github_callback(request: web.Request) -> web.Response:
    """Handle GitHub OAuth callback -- exchange code for token, then session."""
    code = request.query.get("code", "")
    state = request.query.get("state", "")
    if not code or not state:
        return web.Response(text="Missing code or state parameter", status=400)

    stored_states = request.app.get("oauth_states", {})
    if state not in stored_states:
        return web.Response(text="Invalid state (CSRF)", status=403)
    # Consume state to prevent replay
    del stored_states[state]

    # Exchange code for access token
    token_url = "https://github.com/login/oauth/access_token"
    payload = {
        "client_id": config.GITHUB_OAUTH_CLIENT_ID,
        "client_secret": config.GITHUB_OAUTH_CLIENT_SECRET,
        "code": code,
        "redirect_uri": config.GITHUB_OAUTH_REDIRECT_URI,
    }
    headers = {"Accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, json=payload, headers=headers) as resp:
                token_data = await resp.json()
    except Exception as e:
        logger.error("GitHub OAuth token exchange failed: %s", e)
        return web.Response(text="OAuth token exchange failed", status=502)

    access_token = token_data.get("access_token")
    if not access_token:
        return web.Response(text="OAuth failed: " + token_data.get("error_description", "unknown"), status=400)

    # Fetch GitHub user info
    user_url = "https://api.github.com/user"
    user_headers = {
        "Authorization": "Bearer " + access_token,
        "Accept": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(user_url, headers=user_headers) as resp:
                user_data = await resp.json()
    except Exception as e:
        logger.error("GitHub user fetch failed: %s", e)
        return web.Response(text="Failed to fetch GitHub user", status=502)

    github_login = user_data.get("login", "")
    github_name = user_data.get("name", "") or github_login

    if not github_login:
        return web.Response(text="Could not determine GitHub username", status=400)

    # Resolve display name via map, fallback to GitHub login
    display_name = config.OAUTH_NAME_MAP.get(github_login, github_name)

    # Generate session token
    import hashlib
    import time as _time
    raw = "github:" + github_login + ":" + str(_time.time()) + ":" + secrets.token_hex(8)
    token = hashlib.sha256(raw.encode()).hexdigest()

    sessions = persistence.get_web_sessions()
    sessions[token] = {
        "name": display_name,
        "created_at": _time.time(),
        "oauth_provider": "github",
        "oauth_login": github_login,
    }
    persistence.set_web_sessions(sessions)
    persistence.save_web_sessions(config.DATA_DIR)

    # Set cookie and redirect to /chat
    resp = web.HTTPFound(location="/chat")
    _scheme = request.url.scheme if hasattr(request, "url") else "http"
    resp.set_cookie(
        "ws_im_session",
        token,
        max_age=604800,     # 7 days
        httponly=True,
        secure=True if _scheme == "https" else False,
        samesite="Lax",
        path="/",
    )
    raise resp


async def handle_api_auth_me(request: web.Request) -> web.Response:
    """Return current user identity (from token or cookie)."""
    token = request.query.get("token", "")
    if not token:
        token = request.cookies.get("ws_im_session", "")
    viewer = validate_token(token) if token else None
    if not viewer:
        return web.json_response({"authenticated": False})
    return web.json_response({
        "authenticated": True,
        "name": viewer,
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
    # R40: GitHub OAuth
    app.router.add_get("/auth/github/login", handle_github_login)
    app.router.add_get("/auth/github/callback", handle_github_callback)
    app.router.add_get("/api/auth/me", handle_api_auth_me)
    # R76 A: inbox aggregation
    app.router.add_get("/api/chat/inbox", handle_api_inbox)
    # R76 B: archive full channel history
    app.router.add_get("/api/chat/archive", handle_api_archive)
