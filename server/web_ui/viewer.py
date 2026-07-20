"""Web viewer — chat log viewer + bind code auth + multi-tab channels.

Adapted from server/web_viewer.py for web_ui/ package.
Imports common services from server.common.* instead of local . imports.
Workspace queries → HTTP poll to WS server /api/workspaces.
"""
import asyncio
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uuid

import aiohttp
from aiohttp import web

from server.common import auth, config, persistence
from server.common import message_store as ms
from server.web_ui.templates import BIND_TEMPLATE, CHAT_TEMPLATE
from server.ws_server.pipeline_context import PipelineContextManager

logger = logging.getLogger("ws-bridge.web")

# ── Web-ui specific persistence (sessions, bind codes) ────────────────
_web_sessions: dict = {}
_web_bind_codes: dict = {}
_data_dir_lock = threading.Lock()
_ARCHIVE_STATE_FILE = "_archive_state.json"


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.rename(path)


def load_web_sessions(data_dir: Path) -> None:
    global _web_sessions
    _web_sessions = _load_json(data_dir / "_web_sessions.json")


def save_web_sessions(data_dir: Path) -> None:
    with _data_dir_lock:
        _save_json_atomic(data_dir / "_web_sessions.json", _web_sessions)


def get_web_sessions() -> dict:
    with _data_dir_lock:
        return dict(_web_sessions)


def set_web_sessions(sessions: dict) -> None:
    global _web_sessions
    with _data_dir_lock:
        _web_sessions = dict(sessions)


def _load_web_bind_codes(data_dir: Path) -> None:
    global _web_bind_codes
    _web_bind_codes = _load_json(data_dir / "_web_bind_codes.json")


def save_web_bind_codes(data_dir: Path) -> None:
    with _data_dir_lock:
        _save_json_atomic(data_dir / "_web_bind_codes.json", _web_bind_codes)


def get_web_bind_codes() -> dict:
    with _data_dir_lock:
        return dict(_web_bind_codes)


def set_web_bind_codes(codes: dict) -> None:
    global _web_bind_codes
    with _data_dir_lock:
        _web_bind_codes = dict(codes)


# ── In-memory chat log buffer (per channel) ────────────────────
_chat_buffers: dict[str, list[dict]] = {"lobby": []}
_MAX_BUFFER = 1000

# ── Daily chat log file (per channel) ──────────────────────────
_CHAT_LOG_DIR = config.DATA_DIR / "chat_logs"

# ── R76: Archive state persistence ────────────────────────────────────


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
    try:
        path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("R76: Failed to save archive state: %s", exc)


def set_archive_state(ws_id: str, ws_name: str, start_ts: float) -> None:
    """Record archive entry for a workspace. Called when last workspace closes."""
    now = time.time()
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
    global _chat_buffers
    ict_now = datetime.now(timezone.utc) + timedelta(hours=7)
    ts_human = ict_now.strftime("%H:%M:%S")
    ts = time.time()
    line = f"[{ts_human}] {sender_name}: {content}"
    safe_channel = channel.replace("/", "_").replace(":", "_")

    _CHAT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = _today_str()
    try:
        log_file = _CHAT_LOG_DIR / f"chat_{today}_{safe_channel}.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        logger.warning("Failed to write chat log: %s", e)

    if channel not in _chat_buffers:
        _chat_buffers[channel] = []
    entry = {"ts": ts, "sender": sender_name, "from_name": sender_name, "content": content}
    if channel.startswith("_inbox:"):
        owner_id = persistence.resolve_inbox_owner(channel)
        if owner_id:
            entry["to_name"] = auth.get_agent_name(owner_id) or owner_id
            entry["to_agent"] = owner_id
    _chat_buffers[channel].append(entry)
    if len(_chat_buffers[channel]) > _MAX_BUFFER:
        _chat_buffers[channel][:100] = []


def read_channel_logs(channel: str = "lobby", days: int = 1) -> list[dict]:
    """Read chat logs from channel-specific files, spanning multiple days."""
    if channel in _chat_buffers and _chat_buffers[channel]:
        result = list(_chat_buffers[channel])
    else:
        result = []

    safe_channel = channel.replace("/", "_").replace(":", "_")
    seen_entries = set()
    for e in result:
        seen_entries.add((e["ts"], e["sender"], e["content"], "buffer"))

    for offset in range(days):
        d = datetime.now(timezone.utc) + timedelta(hours=7) - timedelta(days=offset)
        day_str = d.strftime("%Y-%m-%d")
        path = _CHAT_LOG_DIR / f"chat_{day_str}_{safe_channel}.log"
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
    return result


read_today_log = read_channel_logs


# ── Auth helpers (bind code deprecated in R83, kept as stubs) ──────


WEB_CODE_PREFIX = "WSIM-"


def validate_token(token: str) -> str | None:
    sessions = get_web_sessions()
    entry = sessions.get(token)
    if entry:
        return entry.get("name")
    if token and len(token) >= 8:
        logger.debug("validate_token: token %s... not found in %d sessions", token[:8], len(sessions))
    return None


async def _fetch_channels_from_wss() -> dict:
    """HTTP poll workspace list from WSS core's /api/workspaces."""
    url = f"http://127.0.0.1:{config.PORT}/api/workspaces"
    try:
        async with asyncio.timeout(5):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
    except Exception:
        pass
    return {"workspaces": [], "count": 0}


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
    """Bind code deprecated in R83 — return error."""
    return web.json_response({"error": "bind_code_deprecated", "message": "请使用 GitHub 登录"})


async def handle_api_check(request: web.Request) -> web.Response:
    """Bind code deprecated in R83 — return error."""
    return web.json_response({"approved": False, "error": "deprecated"})


async def handle_api_chat(request: web.Request) -> web.Response:
    """Return messages for a specific channel (from DB + log fallback)."""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)

    channel = request.query.get("channel", "lobby")
    limit = int(request.query.get("limit", "50"))

    since = request.query.get("since", None)
    if since:
        try:
            since = float(since)
        except (ValueError, TypeError):
            since = None

    # Try DB first
    if since is not None:
        try:
            db_msgs = ms.get_messages_since(since, config.DATA_DIR, limit=limit, channel=channel)
            if db_msgs:
                return web.json_response({"channel": channel, "messages": db_msgs})
        except Exception:
            pass
    else:
        try:
            db_msgs = ms.get_messages_by_channel(channel, config.DATA_DIR, limit=limit)
            if db_msgs:
                return web.json_response({"channel": channel, "messages": db_msgs})
        except Exception:
            pass

    # Fallback to log file
    messages = read_channel_logs(channel, days=7)
    if messages:
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
        return web.json_response({"channel": channel, "messages": messages[:limit]})
    return web.json_response({"channel": channel, "messages": []})


async def handle_api_channels(request: web.Request) -> web.Response:
    """Return available channels — HTTP poll from WSS workspace API."""
    channels = [
        {"id": "lobby", "name": "大厅", "emoji": "🌐", "state": "active"},
    ]
    try:
        data = await _fetch_channels_from_wss()
        for ws in data.get("workspaces", []):
            channels.append({
                "id": ws["id"],
                "name": ws["name"],
                "emoji": "📋" if ws.get("state") == "active" else "🗂️",
                "state": ws.get("state", "active"),
                "admin_ids": [],
            })
    except Exception:
        pass

    try:
        arch_state = _load_archive_state()
        archive_state = {
            "active": True,
            "last_archive_ts": arch_state.get("last_archive_ts", 0),
        }
    except Exception:
        archive_state = {"active": True, "last_archive_ts": 0}

    return web.json_response({"channels": channels, "archive_state": archive_state})


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
    logger.warning("Web viewer bind code rejected: deprecated feature removed in R83")
    return web.json_response({"type": "error", "error": "bind_code_deprecated"})


async def handle_api_logout(request: web.Request) -> web.Response:
    """Clear session cookie → client returns to bind page on reload."""
    resp = web.json_response({"ok": True})
    resp.del_cookie("ws_im_session", path="/")
    return resp


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


async def handle_api_inbox(request: web.Request) -> web.Response:
    """Return aggregated inbox messages with resolved recipient names."""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)

    limit = int(request.query.get("limit", "50"))
    since = request.query.get("since", None)
    if since:
        try:
            since = float(since)
        except (ValueError, TypeError):
            since = None

    try:
        db_msgs = ms.get_messages_by_channel_pattern(
            "_inbox:%", config.DATA_DIR, limit=limit, since=since
        )
    except Exception:
        db_msgs = []

    for m in db_msgs:
        owner_id = persistence.resolve_inbox_owner(m.get("channel", ""))
        m["to_name"] = auth.get_agent_name(owner_id) if owner_id else (owner_id or "?")
        m["to_agent"] = owner_id or ""
        if not m.get("from_name"):
            agent_id = m.get("from_agent") or m.get("agent_id") or ""
            m["from_name"] = auth.get_agent_name(agent_id) if agent_id else "系统"

    return web.json_response({"messages": db_msgs})


async def handle_api_archive(request: web.Request) -> web.Response:
    """Return all messages from a workspace's archive window, across all channels."""
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
    all_msgs.reverse()

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


async def handle_api_agents_status(request: web.Request) -> web.Response:
    """Return online/offline status for all registered agents (from WS poll cache)."""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)

    # Get status from WS /api/status HTTP poll (via bot status cache)
    from server.web_ui.main import _BOT_STATUS_CACHE
    cached = _BOT_STATUS_CACHE.get("agents", [])
    users = auth.get_users()

    result = {}
    for agent_info in cached:
        aid = agent_info.get("id", "")
        if not aid:
            continue
        name = agent_info.get("name", aid[:12])
        result[aid] = {
            "name": name,
            "online": agent_info.get("online", False),
            "role": users.get(aid, {}).get("role", "member"),
            "workspaces": [],
        }
    # Add offline users from approved_users
    for agent_id, user_info in users.items():
        if agent_id not in result:
            result[agent_id] = {
                "name": user_info.get("name", agent_id[:12]),
                "online": False,
                "role": user_info.get("role", "member"),
                "workspaces": [],
            }

    return web.json_response({
        "agents": result,
        "total": len(result),
        "online": sum(1 for a in result.values() if a["online"]),
    })


# ── R40: GitHub OAuth ────────────────────────────────────────────────

# GitHub OAuth config — web-ui only
_GITHUB_CLIENT_ID = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "")
_GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "")
_GITHUB_REDIRECT_URI = os.environ.get(
    "GITHUB_OAUTH_REDIRECT_URI",
    os.environ.get("WS_PUBLIC_URL", "http://0.0.0.0:8765") + "/auth/github/callback",
)
_OAUTH_NAME_MAP: dict[str, str] = {}
_raw = os.environ.get("OAUTH_NAME_MAP", "")
if _raw.strip():
    try:
        _OAUTH_NAME_MAP.update(json.loads(_raw))
    except json.JSONDecodeError:
        pass


async def handle_github_login(request: web.Request) -> web.Response:
    """Redirect to GitHub OAuth authorization page."""
    if not _GITHUB_CLIENT_ID:
        return web.Response(text="GitHub OAuth not configured", status=501)
    redirect_uri = _GITHUB_REDIRECT_URI
    state = secrets.token_hex(16)
    if "oauth_states" not in request.app:
        request.app["oauth_states"] = {}
    request.app["oauth_states"][state] = True
    import urllib.parse as _urlparse
    github_url = (
        "https://github.com/login/oauth/authorize?"
        "client_id=" + _urlparse.quote(_GITHUB_CLIENT_ID, safe="") + "&"
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
    del stored_states[state]

    # Exchange code for access token
    token_url = "https://github.com/login/oauth/access_token"
    payload = {
        "client_id": _GITHUB_CLIENT_ID,
        "client_secret": _GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": _GITHUB_REDIRECT_URI,
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

    display_name = _OAUTH_NAME_MAP.get(github_login, github_name)

    import hashlib
    import time as _time
    raw = "github:" + github_login + ":" + str(_time.time()) + ":" + secrets.token_hex(8)
    token = hashlib.sha256(raw.encode()).hexdigest()

    sessions = get_web_sessions()
    sessions[token] = {
        "name": display_name,
        "created_at": _time.time(),
        "oauth_provider": "github",
        "oauth_login": github_login,
    }
    set_web_sessions(sessions)
    save_web_sessions(config.DATA_DIR)

    resp = web.HTTPFound(location="/chat")
    _scheme = request.url.scheme if hasattr(request, "url") else "http"
    resp.set_cookie(
        "ws_im_session",
        token,
        max_age=604800,
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


# ── R104: Workspace list API for web service ─────────────────────────


async def handle_api_workspaces(request: web.Request) -> web.Response:
    """GET /api/workspaces — HTTP relay to WSS core."""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)
    data = await _fetch_channels_from_wss()
    return web.json_response(data)


# ── R112: Lazy singleton for PipelineContextManager ─────────────────


_PIPELINE_MGR: PipelineContextManager | None = None


def _get_pipeline_mgr() -> PipelineContextManager:
    global _PIPELINE_MGR
    _PIPELINE_MGR = PipelineContextManager(data_dir=config.DATA_DIR)
    return _PIPELINE_MGR


def _summarize_steps(steps: list) -> list:
    """R112: 从 StepInfo 列表提取前端展示字段。"""
    result = []
    for s in steps:
        if isinstance(s, dict):
            result.append({
                "step_key": s.get("step_key", ""),
                "role": s.get("role", ""),
                "title": s.get("title", ""),
                "status": s.get("status", "pending"),
                "agent_name": s.get("agent_name", ""),
                "result_msg": s.get("result_msg", ""),
                "output": s.get("output"),
            })
    return result


async def handle_api_pipelines(request: web.Request) -> web.Response:
    """R112: GET /api/pipelines — 返回所有管线的摘要列表。"""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        mgr = _get_pipeline_mgr()
        items = []
        for ctx in mgr.get_all_active():
            d = ctx.to_dict()
            items.append({
                "round_name": d["round_name"],
                "round_title": d.get("round_title", d["round_name"]),
                "status": d["status"],
                "current_step": d["current_step"],
                "total_steps": d["total_steps"],
                "created_at": d["created_at"],
                "updated_at": d["updated_at"],
                "steps": _summarize_steps(d.get("steps", [])),
                "references": d.get("references", {}),
            })
        return web.json_response({"pipelines": items})
    except Exception as exc:
        logger.warning("[R112] 获取管线列表异常: %s", exc)
        return web.json_response({"pipelines": []})


async def handle_api_pipeline_detail(request: web.Request) -> web.Response:
    """R112: GET /api/pipelines/{round_name} — 单管线完整详情。"""
    token = request.query.get("token", "")
    if not validate_token(token):
        return web.json_response({"error": "unauthorized"}, status=401)
    round_name = request.match_info.get("round_name", "")
    if not round_name:
        return web.json_response({"error": "missing round_name"}, status=400)
    try:
        mgr = _get_pipeline_mgr()
        ctx = mgr.get(round_name)
        if not ctx:
            return web.json_response({"error": f"pipeline {round_name} not found"}, status=404)
        return web.json_response(ctx.to_dict())
    except Exception as exc:
        logger.warning("[R112] 获取管线详情异常: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)


# ── Routes registration ──────────────────────────────────────────


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/", handle_chat)
    app.router.add_get("/chat", handle_chat)
    app.router.add_get("/api/bind", handle_api_bind)
    app.router.add_get("/api/check", handle_api_check)
    app.router.add_get("/api/chat", handle_api_chat)
    app.router.add_post("/api/approve_web", handle_api_approve_web)
    app.router.add_get("/api/channels", handle_api_channels)
    app.router.add_get("/health", _handle_health)
    app.router.add_post("/api/logout", handle_api_logout)
    app.router.add_get("/api/chat/search", handle_api_chat_search)
    app.router.add_get("/api/agents/status", handle_api_agents_status)
    app.router.add_get("/auth/github/login", handle_github_login)
    app.router.add_get("/auth/github/callback", handle_github_callback)
    app.router.add_get("/api/auth/me", handle_api_auth_me)
    app.router.add_get("/api/chat/inbox", handle_api_inbox)
    app.router.add_get("/api/chat/archive", handle_api_archive)
    app.router.add_get("/api/workspaces", handle_api_workspaces)
    app.router.add_get("/api/pipelines", handle_api_pipelines)
    app.router.add_get("/api/pipelines/{round_name}", handle_api_pipeline_detail)
