# -*- coding: utf-8 -*-
"""WS message handler core — extracted from handler.py (renamed to main.py).

This file was created by splitting the original handler.py (7,024 lines)
into state.py + command_utils.py + commands/ + main.py.
Only the core WS routing and subsystems that will be split in Phase 2 remain.
"""

"""WebSocket handler and broadcast logic — admin-relay mode + channel routing."""
import asyncio
import json
import logging
import time
import uuid
from typing import Optional

import shared.protocol as p

from server.common import auth, config, persistence

from . import agent_card as ac_mod  # unified Agent Card interface
from . import message_store as ms
from . import scenario_matcher as _sm  # for _sm.dispatch() in handler()
from . import state  # shared state container
from .ack_machine import (
    ACK_TIMEOUT_SEC,
    _ack_timeout_task,
    _channel_ack_timeout,
    _format_ack_status,
    _resolve_ws_by_ack_task_id,
    _send_ack_timeout_info,
    _task_ack_timeout,
    _trigger_ack_escalation,
)
from .audit import AuditLogger
from .connection_manager import (
    _build_admin_notification,
    _build_registration_welcome,
    _connections,
    _find_agent_by_name,
    _force_disconnect_revoked_agent,
    _is_valid_agent_id,
    _send,
    _send_to_agent,
    _should_notify_admins,
    _update_agent_online_status,
    get_connections,
    handle_agent_card_register,
    handle_auth,
    handle_register,
)
from .git_sync_scheduler import (
    _ensure_git_scan,
    _pipeline_git_sync_scan,
    _start_git_sync_loop,
)
from .pipeline_context import PipelineContext, PipelineContextManager, PipelineStatus, PipelineTaskKind
from .pipeline_engine import PipelineEngine
from .pipeline_timeout import (
    _ensure_timeout_scanner,
    _pipeline_timeout_scan,
    _start_timeout_scan_loop,
)
from .scenario_rules import register_all_rules  # rule registration
from .watchdog import (
    _check_watchdog_alert,
    _clear_watchdog_alert,
    _elapsed_hours_display,
    _ensure_watchdog,
    _get_step_timeout,
    _send_clear_alert,
    _send_watchdog_alert,
    _trigger_timeout_escalation,
    _watchdog_loop,
    _watchdog_rerollcall,
    _watchdog_scan,
)

_card_watcher = None  # module-level for _ensure_card_watcher()
logger = logging.getLogger("ws-bridge")
_audit_logger = AuditLogger(config.DATA_DIR)
# ── PipelineEngine 实例（惰性初始化） ──
engine: Optional[PipelineEngine] = None


def _ensure_engine() -> PipelineEngine:
    global engine
    if engine is None:
        from .commands.pipeline import (
            _get_step_config, _find_agents_by_role,
            _set_pipeline_state, _step_sort_key,
        )
        from .pipeline_engine import _resolve_card_key_to_ws_id, _extract_artifact_kv
        engine = PipelineEngine(
            context_mgr=_ensure_pipeline_manager(),
            send_to_agent=_send_to_agent,
            send_ws=_send,
            resolve_card_key=_resolve_card_key_to_ws_id,
            get_step_config=_get_step_config,
            persist_broadcast=_persist_broadcast,
            find_agents_by_role=_find_agents_by_role,
            set_pipeline_state=_set_pipeline_state,
            extract_artifact_kv=_extract_artifact_kv,
        )
        # ── 注入 engine 引用到 scenario_matcher ──
        _sm._engine = _ensure_engine()
    return engine


def _ensure_pipeline_manager() -> PipelineContextManager:
    """惰性初始化 PipelineContextManager."""
    if state._pipeline_manager is None:
        state._pipeline_manager = PipelineContextManager(data_dir=config.DATA_DIR)
    return state._pipeline_manager


logger_cu = logging.getLogger(__name__)


# ── Role-Agent Map Refresh ──
def _refresh_role_agent_map() -> None:
    """Rebuild state._ROLE_AGENT_MAP from Agent Card pipeline_roles."""
    cards = ac_mod.get_all_cards()
    state._ROLE_AGENT_MAP = {}
    for aid, card in cards.items():
        roles = card.get("pipeline_roles", [])
        for role in roles:
            if role not in state._ROLE_AGENT_MAP:
                state._ROLE_AGENT_MAP[role] = []
            if aid not in state._ROLE_AGENT_MAP[role]:
                state._ROLE_AGENT_MAP[role].append(aid)
    logger_cu.info("role-agent map refreshed: %d roles, %d entries",
                len(state._ROLE_AGENT_MAP),
                sum(len(v) for v in state._ROLE_AGENT_MAP.values()))
    # 同步写到 Manager 全局快照
    try:
        mgr = PipelineContextManager.get_instance()
        mgr.set_global_role_map(dict(state._ROLE_AGENT_MAP))
    except Exception:
        pass


# ── _broadcast_to_channel ──
async def _broadcast_to_channel(channel: str, payload: dict) -> int:
    """向指定频道的所有连接广播消息。返回发送数。同时持久化。"""
    payload_json = json.dumps(payload)
    sent = 0
    for aid, conns in _connections.items():
        for conn in list(conns):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload_json)
                elif hasattr(conn, "send"):
                    await conn.send(payload_json)
                sent += 1
            except Exception:
                pass
    # 同时持久化到 DB + chat log
    try:
        ms.save_message(
            msg_id=str(uuid.uuid4()),
            msg_type="broadcast",
            from_agent=state.SYSTEM_AGENT_ID,
            from_name="系统",
            content=payload.get("content", ""),
            ts=time.time(),
            data_dir=config.DATA_DIR,
            channel=channel,
        )
    except Exception:
        pass
    return sent


def _persist_broadcast(channel: str, from_name: str, content_text: str) -> None:
    """Persist a broadcast message to message store and chat log.

    Ensures rollcall and other WS-send-only paths have proper
    persistence (message_store + chat_log) for offline members and web UI.
    """
    try:
        msg_id = str(uuid.uuid4())
        ms.save_message(
            msg_id=msg_id, msg_type="broadcast",
            from_agent="系统", from_name=from_name,
            content=content_text, ts=time.time(),
            data_dir=config.DATA_DIR, channel=channel,
        )
    except Exception:
        pass


# ── Agent Card persistence ──
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


def _ensure_agent_cards_loaded() -> None:
    """Ensure agent cards are loaded and role map is built at startup.
    Idempotent — only runs on first call.
    """
    if state._cards_loaded_guard:
        return
    if not ac_mod.is_loaded():
        ac_mod.load_cards()
    _refresh_role_agent_map()
    state._cards_loaded_guard = True


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


async def handle_broadcast(ws, sender_id: str, msg: dict) -> None:
    """Admin-relay mode:
    - Non-admin (member) → relay ONLY to admin(s)
    - Admin → relay to specific target (via 'to' field or @mention)
    - All messages → written to chat log (大宏/网页端可见)
    - Channel messages (non-lobby) → scoped to workspace members + admin
    """
    # Lazy-start watchdog on first message
    _ensure_watchdog()
    # Restore pipeline timers on start
    await _ensure_engine().restore_pipeline_timers()
    # Start git sync loop (via PipelineEngine)
    _ensure_engine()._ensure_git_scan()
    # Start timeout scanner (via PipelineEngine)
    _ensure_engine()._ensure_timeout_scanner()
    # Ensure agent cards loaded + watcher running
    _ensure_agent_cards_loaded()
    _ensure_card_watcher()

    content = msg.get("content", "")
    channel = msg.get(p.FIELD_CHANNEL, "")

    # Inbox fast path — skip all filters and routing
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
        # _inbox:server → handled by scenario matcher (rules handle it)
        if channel == f"{p.INBOX_CHANNEL_PREFIX}server":
            return
        # Otherwise → route directly to target agent's inbox (existing intercept handles it)
        # Fall through to normal inbox handling below

    users = auth.get_users()
    # R72 agents live in state._r72_users, not in users
    sender_name = users.get(sender_id, {}).get("name") or \
                  state._r72_users.get(sender_id, {}).get("name", sender_id)

    # Inbox channel intercept
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
        owner_id = persistence.resolve_inbox_owner(channel)
        if not owner_id:
            await _send(ws, {"type": "error", "error": "❌ 无效的收件箱通道"})
            return

        # 不允许向自己的收件箱发消息（防自刷）
        if sender_id == owner_id:
            await _send(ws, {"type": "error", "error": "❌ 不允许向自己的收件箱发消息"})
            return

        # 仅投递给目标 agent（单播）
        targets = [(aid, conns) for aid, conns in _connections.items() if aid == owner_id]
        # 持久化到 DB
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent=sender_id, from_name=sender_name,
            content=content, ts=time.time(),
            data_dir=config.DATA_DIR, channel=channel,
        )
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

            elif msg_type == p.MSG_REGISTER and agent_id is None:
                agent_id = await handle_register(ws, msg)
                if agent_id:
                    _connections.setdefault(agent_id, set()).add(ws)
                    logger.info("Agent %s registered and connected (%d total)", agent_id[:20], sum(len(c) for c in _connections.values()))

            elif msg_type == "message" and agent_id:
                # key 活性检查
                agent_keys = persistence.get_api_keys()
                agent_key_record = agent_keys.get(agent_id)
                if not agent_key_record or agent_key_record.get("status") == "revoked":
                    await _send(ws, {
                        "type": "error",
                        "error": "认证已失效：你的 api_key 已被吊销.请重新 register.",
                    })
                    continue  # skip this message, keep connection alive
                # _inbox:server 中继拦截（规则表调度）
                if await _sm.dispatch(ws, agent_id, msg):
                    continue
                # 权限检查 — _inbox:<bot_id> 需要 level>=4
                _channel = msg.get("channel", "")
                if _channel.startswith(p.INBOX_CHANNEL_PREFIX) and _channel != state.SERVER_INBOX_CHANNEL:
                    _sender_level = auth.get_level(agent_id)
                    if _sender_level < 4:
                        await _send(ws, {
                            "type": "error",
                            "error": f"❌ 无权限：当前等级 L{_sender_level}，需 L4 才能向其他 Bot 发消息.请提交 Agent Card 或联系管理员提升等级.",
                        })
                        logger.info(
                            "拒绝: %s (L%d) 试图发消息到 %s",
                            agent_id[:12], _sender_level, _channel,
                        )
                        continue

                await handle_broadcast(ws, agent_id, msg)

            elif msg_type == p.MSG_AGENT_CARD_REGISTER and agent_id:
                result = await handle_agent_card_register(ws, agent_id, msg)
                await _send(ws, result)

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


# ═══════════════════════════════════════════════════════════════════════
# scenario_matcher rule registration
# ═══════════════════════════════════════════════════════════════════════

# Register rules (extracted to scenario_rules.py)
register_all_rules()
