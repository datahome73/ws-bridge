# -*- coding: utf-8 -*-
"""R100: WS message handler core — extracted from handler.py (renamed to main.py).

This file was created by splitting the original handler.py (7,024 lines)
into state.py + command_utils.py + commands/ + main.py.
Only the core WS routing and subsystems that will be split in Phase 2 remain.
"""

"""WebSocket handler and broadcast logic — admin-relay mode + channel routing."""
import asyncio
import os
import json
import logging
import re
import time
import uuid
from typing import Optional

from . import agent_card as ac_mod  # R67: unified Agent Card interface
from server.common import auth, config, persistence
from . import state  # R100: shared state container
from . import message_store as ms
from .audit import AuditLogger
from . import task_store as ts
from . import workspace as ws_mod  # R134: minimal stub — pipeline sync still uses get_workspace()
from . import timeout_tracker  # R63 Phase 1: Step countdown
from . import pipeline_sync as pps  # R65: Pipeline git sync
from .pipeline_context import PipelineContextManager, PipelineStatus, PipelineTaskKind, PipelineContext  # R77
_card_watcher = None  # R100: module-level for _ensure_card_watcher()
import shared.protocol as p
from .pipeline_engine import PipelineEngine

logger = logging.getLogger("ws-bridge")

from .connection_manager import _connections
# P6: message send stats
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
        from . import scenario_matcher as _sm
        _sm._engine = _ensure_engine()
    return engine
def _ensure_pipeline_manager() -> PipelineContextManager:
    """惰性初始化 PipelineContextManager."""
    if state._pipeline_manager is None:
        state._pipeline_manager = PipelineContextManager(data_dir=config.DATA_DIR)
    return state._pipeline_manager
from .connection_manager import get_connections


# ── R99/100: Role-Agent Map Refresh (migrated from command_utils.py) ──
logger_cu = __import__('logging').getLogger(__name__)

def _refresh_role_agent_map() -> None:
    """Rebuild state._ROLE_AGENT_MAP from Agent Card pipeline_roles."""
    from . import agent_card as ac_mod
    cards = ac_mod.get_all_cards()
    state._ROLE_AGENT_MAP = {}
    for aid, card in cards.items():
        roles = card.get("pipeline_roles", [])
        for role in roles:
            if role not in state._ROLE_AGENT_MAP:
                state._ROLE_AGENT_MAP[role] = []
            if aid not in state._ROLE_AGENT_MAP[role]:
                state._ROLE_AGENT_MAP[role].append(aid)
    logger_cu.info("R63 role-agent map refreshed: %d roles, %d entries",
                len(state._ROLE_AGENT_MAP),
                sum(len(v) for v in state._ROLE_AGENT_MAP.values()))
    # R78 A2: 同步写到 Manager 全局快照
    try:
        from .pipeline_context import PipelineContextManager
        mgr = PipelineContextManager.get_instance()
        mgr.set_global_role_map(dict(state._ROLE_AGENT_MAP))
    except Exception:
        pass


# ── _broadcast_to_channel (migrated from command_utils.py) ──
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

from .connection_manager import (
    _force_disconnect_revoked_agent,
    _send,
    handle_auth,
    _update_agent_online_status,
    _find_agent_by_name,
    handle_register,
    _build_registration_welcome,
    _build_admin_notification,
    _should_notify_admins,
    handle_agent_card_register,
)


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


    pass  # _ensure_watchdog extracted to watchdog.py

# ── R65 A2: Git sync lifecycle ──────────────────────────────────
from .git_sync_scheduler import (
    _ensure_git_scan,
    _start_git_sync_loop,
    _pipeline_git_sync_scan,
)

# ═══ R122: 管线超时告警扫描 ════
from .pipeline_timeout import (
    _ensure_timeout_scanner,
    _start_timeout_scan_loop,
    _pipeline_timeout_scan,
)



# ── R43: Watchdog ────────────────────────────────────────────────
from .watchdog import (
    _ensure_watchdog,
    _watchdog_loop,
    _watchdog_scan,
    _get_step_timeout,
    _trigger_timeout_escalation,
)


# ── R63 Phase 4: ACK state machine ──────────────────────────────
from .ack_machine import (
    ACK_TIMEOUT_SEC,
    _ack_timeout_task,
    _send_ack_timeout_info,
    _trigger_ack_escalation,
    _format_ack_status,
)


from .watchdog import (
    _check_watchdog_alert,
    _clear_watchdog_alert,
    _elapsed_hours_display,
    _send_watchdog_alert,
    _watchdog_rerollcall,
    _send_clear_alert,
)
# ── R55 C: Git commit verification ──────────────────────────




# ═══ R119: 启动时恢复活跃管线的自动派活 ═══


# ════════════════════════════════════════════════════════════

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
    await _ensure_engine().restore_pipeline_timers()
    # ── R65 A2: Start git sync loop (via PipelineEngine) ──
    _ensure_engine()._ensure_git_scan()
    # ── R122: Start timeout scanner (via PipelineEngine) ──
    _ensure_engine()._ensure_timeout_scanner()
    # ── R67 B1: Ensure agent cards loaded + watcher running ──
    _ensure_agent_cards_loaded()
    _ensure_card_watcher()

    content = msg.get("content", "")
    channel = msg.get(p.FIELD_CHANNEL, "")

    # R82 A1: Inbox fast path — skip all filters and routing
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
        # _inbox:server → handled by scenario matcher (rules handle it)
        if channel == f"{p.INBOX_CHANNEL_PREFIX}server":
            return
        # Otherwise → route directly to target agent's inbox (existing intercept handles it)
        # Fall through to normal inbox handling below

    users = auth.get_users()
    # R72: R72 agents live in state._r72_users, not in users
    sender_name = users.get(sender_id, {}).get("name") or \
                  state._r72_users.get(sender_id, {}).get("name", sender_id)

    # ── R68 A2: Inbox channel intercept ──
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
        owner_id = persistence.resolve_inbox_owner(channel)
        if not owner_id:
            await _send(ws, {"type": "error", "error": "❌ 无效的收件箱通道"})
            return

        # 权限：不允许向自己的收件箱发消息（防自刷）
        # 其他人均可写收件箱（回复路由）
        if sender_id == owner_id:
            await _send(ws, {"type": "error", "error": "❌ 不允许向自己的收件箱发消息"})
            return

        # 仅投递给目标 agent（单播，不广播给其他人）
        targets = [(aid, conns) for aid, conns in _connections.items() if aid == owner_id]
        # 持久化到 DB（R84: 确保 inbox 消息有完整 from_name/to_name 字段）
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


# ── R12 P0.3: Task ack timeout ────────────────────────────────────
from .ack_machine import (
    _task_ack_timeout,
    _channel_ack_timeout,
    _resolve_ws_by_ack_task_id,
)


# ── R87: _inbox:server 中继转发 ─────────────────────────────


from .connection_manager import (
    _is_valid_agent_id,
    _send_to_agent,
)


# ═══════════════════════════════════════════════════════════════
# R115: ## 键值对提取 — 从完成消息中解析产出上下文
# ═══════════════════════════════════════════════════════════════


# ── R118: PM 通知函数 ──────────────────────────────────


# ── R118: 离线重试队列 ──────────────────────────────────

# ── R107: 消息模板渲染 ──────────────────────────────────







# ═══ R124: 远程 git SHA 验证 ──────────────────────

# ═══ R124: 驳回管线状态回退 ═══
# ════════════════════════════════════════════════════════════════
# R111: ## 命令 — 简洁可靠的自动派活入口
# ════════════════════════════════════════════════════════════════




# ═══ R124: 手动归档 ─────────────────────────────

# ═══ R124: 管线自动归档 ═══
# ════════════════════════════════════════════════════════════════


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

            elif msg_type == p.MSG_REGISTER and agent_id is None:  # R72: 新增
                agent_id = await handle_register(ws, msg)
                if agent_id:
                    _connections.setdefault(agent_id, set()).add(ws)
                    logger.info("Agent %s registered and connected (%d total)", agent_id[:20], sum(len(c) for c in _connections.values()))

            elif msg_type == "message" and agent_id:
                # ── R86 B1: key 活性检查 ──
                agent_keys = persistence.get_api_keys()
                agent_key_record = agent_keys.get(agent_id)
                if not agent_key_record or agent_key_record.get("status") == "revoked":
                    await _send(ws, {
                        "type": "error",
                        "error": "认证已失效：你的 api_key 已被吊销.请重新 register.",
                    })
                    continue  # skip this message, keep connection alive
                # ═══ R87+R126: _inbox:server 中继拦截（规则表调度）═══
                if await _sm.dispatch(ws, agent_id, msg):
                    continue
                # ════════════════════════════════════════
                # ═══ R99: 权限检查 — _inbox:<bot_id> 需要 level>=4 ═══
                _channel = msg.get("channel", "")
                if _channel.startswith(p.INBOX_CHANNEL_PREFIX) and _channel != state.SERVER_INBOX_CHANNEL:
                    _sender_level = auth.get_level(agent_id)
                    if _sender_level < 4:
                        await _send(ws, {
                            "type": "error",
                            "error": f"❌ 无权限：当前等级 L{_sender_level}，需 L4 才能向其他 Bot 发消息.请提交 Agent Card 或联系管理员提升等级.",
                        })
                        logger.info(
                            "[R99] 拒绝: %s (L%d) 试图发消息到 %s",
                            agent_id[:12], _sender_level, _channel,
                        )
                        continue
                # ════════════════════════════════════════════════════

                await handle_broadcast(ws, agent_id, msg)

            elif msg_type == p.MSG_AGENT_CARD_REGISTER and agent_id:  # R72: 新增
                result = await handle_agent_card_register(ws, agent_id, msg)
                await _send(ws, result)

            # ★ 删除: elif msg_type == "approve" and agent_id:  — 旧 approve 路径已移除（R72）
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

async def _sm_handle_loopback(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 10: test ✅ loopback."""
    from_name = msg.get("from_name", "?")
    logger.info("🔄 Loopback test from %s (%s)", from_name, agent_id[:16])
    try:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"✅ test 确认 — 双向通信正常（{from_name}）",
            "ts": time.time(),
        })
    except Exception as e:
        logger.warning("R96: 回路测试回复失败: %s", e)
    return True


async def _sm_handle_to_agent(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 20: to_agent dispatch routing."""
    to_agent = matched  # resolved by match_to_agent
    # Validate agent_id format
    if not _is_valid_agent_id(to_agent):
        logger.warning("[Dispatch] 拒绝: 非法 to_agent=%s", to_agent)
        return True
    relay_payload = {
        "type": "broadcast",
        "channel": f"_inbox:{to_agent}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": msg.get("content", "").strip(),
        "ts": time.time(),
    }
    # R109: persist relay message
    try:
        ms.save_message(
            msg_id=str(uuid.uuid4()),
            msg_type="broadcast",
            from_agent=state.SYSTEM_AGENT_ID,
            from_name="系统",
            content=relay_payload["content"],
            ts=relay_payload["ts"],
            data_dir=config.DATA_DIR,
            channel=relay_payload["channel"],
        )
    except Exception:
        pass
    await _send_to_agent(to_agent, relay_payload)
    logger.info("[Dispatch] %s → %s: %s...",
                 agent_id[:12], to_agent[:16],
                 (msg.get("content") or "")[:60])
    return True


async def _sm_handle_hash(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 30: ## commands → scenario_matcher.handle_hash_cmd."""
    return await _sm.handle_hash_cmd(ws, agent_id, msg, matched)


async def _sm_handle_query(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 25: ##query commands → scenario_matcher.handle_query."""
    return await _sm.handle_query(ws, agent_id, msg, matched)


async def _sm_handle_step(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 28: ##step commands → scenario_matcher.handle_step."""
    return await _sm.handle_step(ws, agent_id, msg, matched)


async def _sm_handle_ack(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 40: 收到 ✅ / ACK ✅ → forward to PM."""
    content = (msg.get("content") or "").strip()
    sender_name = state._r72_users.get(agent_id, {}).get("name", agent_id[:12])
    pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
    if pm_agent_id:
        await _send_to_agent(pm_agent_id, {
            "type": "broadcast",
            "channel": f"_inbox:{pm_agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"📬 {sender_name} 已接活:\n{content}",
            "ts": time.time(),
        })
    logger.info("[Relay] ACK: %s → PM", sender_name)
    return True


async def _sm_handle_complete(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 50: 已完成 ✅ / ✅ 完成 → forward PM + auto-confirm + advance."""
    content = (msg.get("content") or "").strip()
    sender_name = state._r72_users.get(agent_id, {}).get("name", agent_id[:12])
    pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
    # Forward to PM
    if pm_agent_id:
        await _send_to_agent(pm_agent_id, {
            "type": "broadcast",
            "channel": f"_inbox:{pm_agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"✅ {sender_name} 任务完成:\n{content}",
            "ts": time.time(),
        })
    # Auto-confirm to bot
    await _send_to_agent(agent_id, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": "✅ 确认，已收到你的完成通知.本轮任务完成.",
        "ts": time.time(),
    })
    logger.info("[Relay] 完成: %s → PM + 自动确认", sender_name)
    _ensure_engine().try_advance(content, agent_id)
    return True


async def _sm_handle_reject(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 60: 退回 🔄 → forward PM + auto-confirm + rollback."""
    content = (msg.get("content") or "").strip()
    sender_name = state._r72_users.get(agent_id, {}).get("name", agent_id[:12])
    pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
    if pm_agent_id:
        await _send_to_agent(pm_agent_id, {
            "type": "broadcast",
            "channel": f"_inbox:{pm_agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"🔄 {sender_name} 退回:\n{content}",
            "ts": time.time(),
        })
    await _send_to_agent(agent_id, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": "🔄 已记录退回.",
        "ts": time.time(),
    })
    logger.info("[Relay] 退回: %s → PM + 自动确认", sender_name)
    asyncio.ensure_future(_ensure_engine().handle_reject(content, agent_id))
    return True


async def _sm_handle_fail(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 70: 失败 ❌ → forward PM + auto-confirm."""
    content = (msg.get("content") or "").strip()
    sender_name = state._r72_users.get(agent_id, {}).get("name", agent_id[:12])
    pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
    if pm_agent_id:
        await _send_to_agent(pm_agent_id, {
            "type": "broadcast",
            "channel": f"_inbox:{pm_agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"⚠️ {sender_name} 失败:\n{content}",
            "ts": time.time(),
        })
    await _send_to_agent(agent_id, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": "⚠️ 已记录失败.",
        "ts": time.time(),
    })
    logger.info("[Relay] 失败: %s → PM + 自动确认", sender_name)
    return True


async def _sm_handle_catchall(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 90: no match → store silently."""
    content = (msg.get("content") or "").strip()
    sender_name = state._r72_users.get(agent_id, {}).get("name", agent_id[:12])
    channel = msg.get("channel", "")
    try:
        ms.save_message(
            msg_id=str(uuid.uuid4()),
            msg_type="message",
            channel=channel,
            from_agent=agent_id,
            from_name=sender_name,
            content=content,
            ts=time.time(),
            data_dir=config.DATA_DIR,
        )
    except Exception:
        pass
    logger.info("[Relay] 沉默: %s 内容=%s...", sender_name, content[:60])
    return True


# ── Register all rules ──────────────────────────────────────────────

from . import scenario_matcher as _sm

_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_loopback,
    handle=_sm_handle_loopback,
    priority=10,
    name="回路测试",
    protocol_ref="§7.1",
))
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_to_agent,
    handle=_sm_handle_to_agent,
    priority=20,
    name="to_agent派活路由",
    protocol_ref="§7.2",
))
# ── R131: ##query commands (rule 25) ──
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_query,
    handle=_sm_handle_query,
    priority=25,
    name="##query命令",
    protocol_ref="§R131",
))
# ── R132: ##step commands (rule 28) ──
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_step,
    handle=_sm_handle_step,
    priority=28,
    name="##step命令",
    protocol_ref="§R132",
))
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_hash_cmd,
    handle=_sm_handle_hash,
    priority=30,
    name="##命令路由",
    protocol_ref="§7.3",
))
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_ack,
    handle=_sm_handle_ack,
    priority=40,
    name="ACK转发",
    protocol_ref="§7.5",
))
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_complete,
    handle=_sm_handle_complete,
    priority=50,
    name="完成确认",
    protocol_ref="§7.6",
))
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_reject,
    handle=_sm_handle_reject,
    priority=60,
    name="退回回退",
    protocol_ref="§7.7",
))
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_fail,
    handle=_sm_handle_fail,
    priority=70,
    name="失败告警",
    protocol_ref="§7.8",
))
_sm.register_rule(_sm.HandlerRule(
    match=_sm.match_catchall,
    handle=_sm_handle_catchall,
    priority=90,
    name="入库留痕",
    protocol_ref="§7.10",
))

