# -*- coding: utf-8 -*-
"""R139 EXT: Scenario rules — extracted from main.py.

Contains _sm_handle_*() callbacks for scenario_matcher rules
plus register_all_rules() to register them.
"""
import asyncio
import logging
import time
import uuid

from . import message_store as ms
from . import state
from server.common import config

logger = logging.getLogger("ws-bridge")


# ── Handle callbacks (each calls existing main.py functions) ────────

async def _sm_handle_loopback(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 10: test ✅ loopback."""
    from .main import _send  # lazy import

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
    from .main import _send_to_agent, _is_valid_agent_id  # lazy import

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
    from . import scenario_matcher as _sm
    return await _sm.handle_hash_cmd(ws, agent_id, msg, matched)


async def _sm_handle_query(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 25: ##query commands → scenario_matcher.handle_query."""
    from . import scenario_matcher as _sm
    return await _sm.handle_query(ws, agent_id, msg, matched)


async def _sm_handle_pm_guard(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 35: PM safety guard."""
    from .main import _send  # lazy import

    await _send(ws, {
        "type": "error",
        "error": "_inbox:server 仅接受 bot 消息，PM 请直接发 bot 收件箱.",
    })
    logger.warning("[Relay] 拒绝: PM %s 试图发消息到 _inbox:server", agent_id[:12])
    return True


async def _sm_handle_ack(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 40: 收到 ✅ / ACK ✅ → forward to PM."""
    from .main import _send_to_agent  # lazy import

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
    from .main import _ensure_engine, _send_to_agent  # lazy import

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
    from .main import _ensure_engine, _send_to_agent  # lazy import

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
    from .main import _send_to_agent  # lazy import

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


async def _sm_handle_exclamation(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 80: ! command → passthrough to normal routing."""
    sender_name = state._r72_users.get(agent_id, {}).get("name", agent_id[:12])
    logger.info("[Relay] 透传: %s 发送 ! 命令到 _inbox:server", sender_name)
    return False


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


# ── Rule registration ──────────────────────────────────────────────

def register_all_rules() -> None:
    """Register all scenario rules with lazy import of scenario_matcher."""
    from . import scenario_matcher as _sm  # function-body import, no circular dep

    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_loopback,
        handle=_sm_handle_loopback,
        priority=10, name="回路测试", protocol_ref="§7.1",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_to_agent,
        handle=_sm_handle_to_agent,
        priority=20, name="to_agent派活路由", protocol_ref="§7.2",
    ))
    # ── R131: ##query commands (rule 25) ──
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_query,
        handle=_sm_handle_query,
        priority=25, name="##query命令", protocol_ref="§R131",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_hash_cmd,
        handle=_sm_handle_hash,
        priority=30, name="##命令路由", protocol_ref="§7.3",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_pm_guard,
        handle=_sm_handle_pm_guard,
        priority=35, name="PM安全守卫", protocol_ref="§7.4",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_ack,
        handle=_sm_handle_ack,
        priority=40, name="ACK转发", protocol_ref="§7.5",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_complete,
        handle=_sm_handle_complete,
        priority=50, name="完成确认", protocol_ref="§7.6",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_reject,
        handle=_sm_handle_reject,
        priority=60, name="退回回退", protocol_ref="§7.7",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_fail,
        handle=_sm_handle_fail,
        priority=70, name="失败告警", protocol_ref="§7.8",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_exclamation,
        handle=_sm_handle_exclamation,
        priority=80, name="!命令透传", protocol_ref="§7.9",
    ))
    _sm.register_rule(_sm.HandlerRule(
        match=_sm.match_catchall,
        handle=_sm_handle_catchall,
        priority=90, name="入库留痕", protocol_ref="§7.10",
    ))
