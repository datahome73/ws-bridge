# -*- coding: utf-8 -*-
"""R136 EXT-3: ACK state machine — extracted from main.py.

Pure extraction — no semantic changes. Includes ACK timeout detection,
status formatting, task/channel ack timeout, and WS resolution.
"""
import asyncio
import json
import time
import logging

from . import state
from server.common import config
from . import workspace as ws_mod

logger = logging.getLogger("ws-bridge")


# ── R63 Phase 4: ACK state machine ──

ACK_TIMEOUT_SEC = 30  # Seconds from SENT to FAILED


async def _ack_timeout_task(ack_key: str) -> None:
    """30-second ACK timeout detection.

    If no ACK received within timeout, marks state as ack_timeout
    (not FAILED) — waits for git sync to detect new output instead.

    R65 C1: ACK 超时不标记 FAILED，改为 ack_timeout 等待标记.
    只有当 git sync + timeout_tracker 都无产出时才标记真正 FAILED.
    """
    await asyncio.sleep(ACK_TIMEOUT_SEC)
    ack_state = state._step_ack_states.get(ack_key, {})
    if ack_state.get("state") in ("SENT", "DELIVERED"):
        # ── R65 C1: ACK 超时 → 标记 ack_timeout（不标 FAILED）──
        ack_state["state"] = "ack_timeout"
        logger.info("[R65 C1] ACK 超时: %s (agent=%s) — 等待 git 产出，不标 FAILED",
                    ack_key, ack_state.get("agent_id", "?"))
        # 仅发送信息性消息，不触发 escalation
        await _send_ack_timeout_info(ack_key, ack_state)


async def _send_ack_timeout_info(ack_key: str, ack_state: dict) -> str:
    """ACK 超时信息通知（非告警）."""
    from .main import _get_agent_display, _persist_broadcast, _connections

    parts = ack_key.split("/", 1)
    round_name = parts[0] if len(parts) > 0 else "?"
    step_name = parts[1] if len(parts) > 1 else "?"
    agent_id = ack_state.get("agent_id", "")
    display_name = _get_agent_display(agent_id) if agent_id else "未知"

    info = (
        f"⏰ [ACK 未响应] {round_name} {step_name}\n"
        f"  目标: {display_name} — 30s 内未回复 ACK\n"
        f"  状态: ⚠️ 等待 git 产出（不标记失败）\n"
        f"  Git sync 将自动检测并推进"
    )

    # 广播到工作室
    for rname, pstate in state._PIPELINE_STATE.items():
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


async def _trigger_ack_escalation(ack_key: str, ack_state: dict) -> str:
    """ACK timeout → PM escalation alert.

    Args:
        ack_key: Key in state._step_ack_states.
        ack_state: Current state dict.

    Returns:
        Alert message string.
    """
    from .main import _get_agent_display, _persist_broadcast, _connections

    parts = ack_key.split("/", 1)
    round_name = parts[0] if len(parts) > 0 else "?"
    step_name = parts[1] if len(parts) > 1 else "?"
    agent_id = ack_state.get("agent_id", "")
    display_name = _get_agent_display(agent_id) if agent_id else "未知"

    alert = (
        f"🕐 [ACK 超时] {round_name} {step_name}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🎯 目标: {display_name}\n"
        f"📨 状态: {ack_state.get('state', 'UNKNOWN')}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"请 @PM 协调：等待 / 换备用 / 手动驱动 / 跳过"
    )

    # Broadcast to workspace if available
    for rname, pstate in state._PIPELINE_STATE.items():
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


def _format_ack_status(ack_key: str) -> str:
    """Format ACK state for pipeline_status display.

    Args:
        ack_key: Key in state._step_ack_states.

    Returns:
        Formatted status string, or empty string if not tracked.
    """
    ack_state = state._step_ack_states.get(ack_key)
    if not ack_state:
        return ""
    s = ack_state["state"]
    elapsed = time.time() - ack_state.get("sent_at", time.time())
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


# ── R12 P0.3: Task ack timeout ──


async def _task_ack_timeout(admin_ws, task_id: str, target_name: str) -> None:
    """30s timeout for task ack. Notify admin if no response."""
    await asyncio.sleep(30)
    state._task_ack_timers.pop(task_id, None)
    try:
        from .main import _send
        await _send(admin_ws, {
            "type": "delivery_status",
            "task_id": task_id,
            "status": "timeout",
            "message": f"⚠️ {target_name} 30 秒内未确认任务，建议检查",
        })
    except Exception:
        pass
    logger.warning("Task %s ack timeout for %s", task_id, target_name)


async def _channel_ack_timeout(ws_id: str) -> None:
    """30s timeout for channel switch ACK.
    On timeout: marks unresponsive members, calls _notify_rollcall_complete().
    """
    from .main import _connections, _notify_rollcall_complete

    await asyncio.sleep(30)
    ch_state = state._channel_ack_state.get(ws_id)
    if not ch_state:
        return
    timedout = ch_state["online_members"] - set(ch_state["acked_members"].keys())
    if timedout:
        from server.common import auth as _auth
        users = _auth.get_users()
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
    state._channel_ack_state.pop(ws_id, None)


def _resolve_ws_by_ack_task_id(ack_task_id: str) -> str | None:
    """Find workspace ID by its active ack_task_id."""
    for ws_id, ch_state in state._channel_ack_state.items():
        if ch_state.get("ack_task_id") == ack_task_id:
            return ws_id
    return None
