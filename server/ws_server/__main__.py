#!/usr/bin/env python3
"""WS Bridge server entry point — aiohttp (HTTP + WebSocket)."""
import asyncio
import json
import logging
import os
import secrets
import sys
import time
import uuid

from aiohttp import web

from server.common.config import HOST, PORT, DATA_DIR, ADMIN_AGENTS, DISPATCH_SENDER_ID  # R102: PM guard
from .main import handle_auth, handle_broadcast, handle_register, _connections  # R87
from . import scenario_matcher as _sm  # R126
from .message_store import init_db
from server.common.persistence import get_approved_users as _get_approved_users
from server.common.persistence import (
    load_approved_users,
    load_web_sessions,
    load_api_keys,
    save_approved_users,
    save_web_sessions,
    get_api_keys as _get_api_keys,  # R86 B1: key 活性检查
)
import shared.protocol as p

logger = logging.getLogger("ws-bridge")

# ── Logging config: show INFO+ in container logs ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)

# ── [REMOVED] Periodic cleanup task ──
#
# async def _auto_archive_loop():
#     ...removed...
#
# async def _periodic_cleanup():
#     ...removed...

# ── WS handler for aiohttp ──────────────────────────────────────────


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Handle WebSocket connections via aiohttp."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    agent_id = None
    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                if msg.type == web.WSMsgType.ERROR:
                    break
                continue

            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "error": "Invalid JSON"})
                continue

            msg_type = data.get("type", "")

            if msg_type == "auth" and agent_id is None:
                agent_id = await handle_auth(ws, data)
                if agent_id:
                    _connections.setdefault(agent_id, set()).add(ws)
                    logger.info("Agent %s connected (%d total)", agent_id[:20], sum(len(c) for c in _connections.values()))

            elif msg_type == p.MSG_REGISTER and agent_id is None:  # R72: 新增
                agent_id = await handle_register(ws, data)
                if agent_id:
                    _connections.setdefault(agent_id, set()).add(ws)
                    logger.info("Agent %s registered and connected (%d total)", agent_id[:20], sum(len(c) for c in _connections.values()))

            elif msg_type == "message" and agent_id:
                # ── R86 B1: key 活性检查 ──
                _key_records = _get_api_keys()
                _key_record = _key_records.get(agent_id)
                if not _key_record or _key_record.get("status") == "revoked":
                    await ws.send_json({
                        "type": "error",
                        "error": "认证已失效：你的 api_key 已被吊销。请重新 register。",
                    })
                    continue  # skip this message, keep connection alive
                # ═══ R87+R126: _inbox:server 中继拦截（规则表调度）═══
                if await _sm.dispatch(ws, agent_id, data):
                    continue
                # ═══ R102+R126: 非 _inbox:server 通道 → dispatch 内部自动修正 channel ═══
                if await _sm.dispatch(ws, agent_id, data):
                    continue
                # ════════════════════════════════════════════════════════════════════
                # ═══ R99: 权限检查 — _inbox:<bot_id> 需要 level>=4 ═══
                _channel = data.get("channel", "")
                if _channel.startswith(p.INBOX_CHANNEL_PREFIX) and _channel != f"{p.INBOX_CHANNEL_PREFIX}server":
                    from server.common import auth as _auth
                    _sender_level = _auth.get_level(agent_id)
                    if _sender_level < 4:
                        await ws.send_json({
                            "type": "error",
                            "error": f"❌ 无权限：当前等级 L{_sender_level}，需 L4 才能向其他 Bot 发消息。请提交 Agent Card 或联系管理员提升等级。",
                        })
                        continue
                # ════════════════════════════════════════════════════
                await handle_broadcast(ws, agent_id, data)

            elif msg_type == p.MSG_AGENT_CARD_REGISTER and agent_id:  # R72: 新增
                from .main import handle_agent_card_register
                result = await handle_agent_card_register(ws, agent_id, data)
                await ws.send_json(result)

            # ★ 删除: elif msg_type == "approve" and agent_id:  — 旧 approve 路径已移除（R72）

            # ── R4: Workspace message types — R134: removed
            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})



            elif msg_type == p.MSG_ADMIN_REQUEST_REJECTED and agent_id:
                from . import workspace as _ws_mod
                users = (await _get_users())
                if users.get(agent_id, {}).get("role") != "admin":
                    await ws.send_json({"type": "error", "error": "权限不足：仅全局管理员可审批"})
                    continue
                ws_id = data.get(p.FIELD_WORKSPACE_ID, "").strip()
                target_id = data.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                target_name = data.get(p.FIELD_TARGET_AGENT, "").strip()
                reject_reason = data.get(p.FIELD_REASON, "").strip()
                if not ws_id or not target_id:
                    await ws.send_json({"type": "error", "error": "缺少 workspace_id 或 target_agent_id"})
                    continue
                if not target_id and target_name:
                    for aid, u in users.items():
                        if u.get("name") == target_name:
                            target_id = aid
                            break
                if not target_id:
                    await ws.send_json({"type": "error", "error": f"未找到目标成员 {target_name}"})
                    continue
                success, msg_text = _ws_mod.reject_admin_request(ws_id, target_id, agent_id, reject_reason)
                if not success:
                    await ws.send_json({"type": "error", "error": msg_text})
                    continue
                import json as _json
                reject_payload = _json.dumps({
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
                await ws.send_json({"type": "ack", "message": f"✅ 已拒绝 {target_name or target_id[:12]} 的管理员申请"})
                logger.info("Admin request rejected: %s for '%s' by %s, reason: %s", target_id[:12], ws_id, agent_id[:12], reject_reason)

            # ── R82: removed MSG_SET_ACTIVE_CHANNEL handler



            elif msg_type == p.MSG_ADMIN_REQUEST_REJECTED and agent_id:
                users = await _get_users()
                if not users.get(agent_id, {}).get("role") == "admin":
                    await ws.send_json({"type": "error", "error": "权限不足"})
                    continue
                ws_id = data.get(p.FIELD_WORKSPACE_ID, "").strip()
                target_id = data.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                reason = data.get(p.FIELD_REASON, "").strip()
                if not ws_id or not target_id:
                    await ws.send_json({"type": "error", "error": "缺少 workspace_id 或 target_agent_id"})
                    continue
                success, msg_text = ws_mod.reject_admin_request(ws_id, target_id, agent_id, reason)
                if not success:
                    await ws.send_json({"type": "error", "error": msg_text})
                    continue
                await ws.send_json({"type": "ack", "message": f"❌ 已拒绝 {target_id[:12]} 的申请"})

            # ── R29: task_switch — fire-and-forget (only admin) ──────
            elif msg_type == p.MSG_TASK_SWITCH and agent_id:
                users = await _get_users()
                if users.get(agent_id, {}).get("role") != "admin":
                    await ws.send_json({"type": "error", "error": "权限不足：仅管理员可发送 task_switch"})
                    continue
                target_id = data.get("target", "").strip()
                if not target_id:
                    await ws.send_json({"type": "error", "error": "缺少 target 字段"})
                    continue
                # Resolve by name if needed
                if target_id not in users:
                    for aid, u in users.items():
                        if u.get("name") == target_id:
                            target_id = aid
                            break
                if target_id and target_id in users:
                    logger.info("Admin %s task-switched agent %s to lobby (R82: channel tracking removed)", agent_id[:12], target_id[:12])
                else:
                    logger.info("Admin %s task-switch target '%s' not found (silently ignored)", agent_id[:12], data.get("target", "")[:20])
                # Fire-and-forget: no ACK




            else:
                await ws.send_json({"type": "error", "error": "Unknown msg or not authenticated"})

    except Exception as e:
        logger.warning("WS error: %s", e)
    finally:
        if agent_id and agent_id in _connections:
            _connections[agent_id].discard(ws)
            if not _connections[agent_id]:
                del _connections[agent_id]
            logger.info("Agent %s disconnected (%d remaining)", agent_id[:20] if agent_id else "unknown", len(_connections))

    return ws


async def _get_users():
    """Lazy import to avoid circular dependency."""
    from server.common import auth
    return auth.get_users()


# ── P1: /api/status — online bot status ──────────────────────────


async def _api_status(request: web.Request) -> web.Response:
    """Return online/offline status for all approved agents."""
    from server.common.config import HIDDEN_AGENTS as _hidden
    from server.common.config import AGENT_WHITELIST as _whitelist
    from server.common.persistence import get_web_sessions as _gws  # noqa: F811
    users = _get_approved_users()
    from server.common.persistence import get_api_keys as _get_api_keys
    api_keys = _get_api_keys()
    now = time.time()
    agents_list = []
    seen = set()
    for agent_id, conns in list(_connections.items()):
        if agent_id in _hidden:
            continue
        info = users.get(agent_id, {})
        if not info:
            key_info = api_keys.get(agent_id, {})
            name = key_info.get("display_name", agent_id[:12])
        else:
            name = info.get("name", agent_id[:12])
        # R130: skip agents not in whitelist
        if name not in _whitelist:
            seen.add(agent_id)
            continue
        connected_at = min(
            (getattr(c, "_connected_at", now) for c in list(conns)),
            default=now,
        )
        agents_list.append({
            "id": agent_id[:16],
            "name": name,
            "online": True,
            "connections": len(list(conns)),
            "uptime_secs": int(now - connected_at),
        })
        seen.add(agent_id)
    for agent_id, info in users.items():
        if agent_id not in seen and agent_id not in _hidden:
            name = info.get("name", agent_id[:12])
            if name not in _whitelist:
                continue
            agents_list.append({
                "id": agent_id[:16],
                "name": name,
                "online": False,
                "connections": 0,
            })
    # R73: also list R72-registered agents that are offline
    for agent_id, key_info in api_keys.items():
        if agent_id not in seen and agent_id not in _hidden:
            name = key_info.get("display_name", agent_id[:12])
            if name not in _whitelist:
                continue
            agents_list.append({
                "id": agent_id[:16],
                "name": name,
                "online": False,
                "connections": 0,
            })
            seen.add(agent_id)
    return web.json_response({"agents": agents_list})


# ── P2: Web session persistence ──────────────────────────────────


_sessions: dict[str, dict] = {}


async def _auth_callback(request: web.Request) -> web.Response:
    """Auth callback: set session cookie and redirect to chat."""
    token = request.rel_url.query.get("token", "")
    agent_id = request.rel_url.query.get("agent_id", "")
    if token and agent_id:
        session_id = secrets.token_hex(16)
        _sessions[session_id] = {"agent_id": agent_id, "created_at": time.time()}
        resp = web.HTTPFound("/")
        resp.set_cookie("ws_im_session", session_id, max_age=604800)
        return resp
    return web.HTTPFound("/")


# ── P5: Enhanced health check ────────────────────────────────────


_start_time: float = 0.0


async def _api_health(request: web.Request) -> web.Response:
    verbose = request.rel_url.query.get("verbose", "").lower() in ("1", "true", "yes")
    status = {
        "status": "ok",
        "uptime_secs": int(time.time() - _start_time),
        "connections": len(_connections),
        "agents_online": len([a for a, cs in list(_connections.items()) if cs]),
    }
    if verbose:
        status["agents"] = {
            aid[:16]: {
                "name": _get_approved_users().get(aid, {}).get("name", "?"),
                "conns": len(list(cs)),
            }
            for aid, cs in list(_connections.items())
        }
    return web.json_response(status)


# ── Main ──────────────────────────────────────────────────────────────


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load persisted data
    load_approved_users(DATA_DIR)
    load_web_sessions(DATA_DIR)
    # R82: removed load_agent_channels
    load_api_keys(DATA_DIR)  # R72: API Key 存储

    # Initialise message store
    init_db(DATA_DIR)

    # R38: Initialise Task store + Agent Cards
    from .task_store import init_db as init_task_store
    init_task_store(DATA_DIR)
    from .agent_card import load_cards
    load_cards()


    logger.info("WS Bridge starting on %s:%d", HOST, PORT)
    logger.info("Admin agents: %s", ADMIN_AGENTS or "none")

    app = web.Application()

    # ── R118: 启动离线重试循环（通过 PipelineEngine）──
    async def _start_retry_loop(app):
        from .main import _ensure_engine
        asyncio.create_task(_ensure_engine()._retry_loop())
        logger.info("[R118] retry loop started")

    app.on_startup.append(_start_retry_loop)

    # ── R119: 启动时恢复活跃管线的自动派活（通过 PipelineEngine）──
    async def _restore_dispatches(app):
        from .main import _ensure_engine
        await _ensure_engine().restore_pipeline_dispatches()
        logger.info("[R119] pipeline dispatch restoration completed")

    app.on_startup.append(_restore_dispatches)

    # [REMOVED] Start periodic cleanup + auto-archive via on_startup
    # User requested to stop ALL auto features (2026-07-13)
    # app.on_startup.append(lambda _: asyncio.create_task(_periodic_cleanup()))
    # app.on_startup.append(lambda _: asyncio.create_task(_auto_archive_loop()))

    # Register WebSocket route
    app.router.add_get("/ws", ws_handler)

    # P1: /api/status
    app.router.add_get("/api/status", _api_status)
    # P2: auth callback for session persistence
    # P5: enhanced health check (override basic one)
    app.router.add_get("/api/health", _api_health)
    # R4: workspace API
    app.router.add_get("/api/workspaces", _ws_api.api_workspaces)

    global _start_time
    _start_time = time.time()

    print(f"READY: http://{HOST}:{PORT}/", flush=True)
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
