# -*- coding: utf-8 -*-
"""R136 EXT-2: Watchdog — extracted from main.py.

Pure extraction — no semantic changes. Covers watchdog loop, scan,
timeout escalation, alert dedup, alert sending, rerollcall, and clear.
"""
import asyncio
import json
import time
import logging

from . import state
from server.common import config
from . import agent_card as ac_mod
from . import timeout_tracker
from . import workspace as ws_mod
from .commands.pipeline import (
    _get_step_config,
)
import shared.protocol as p

logger = logging.getLogger("ws-bridge")


# ── R43: Watchdog ──


def _ensure_watchdog() -> None:
    """Lazily start the background watchdog loop on first call."""
    state._watchdog_task
    if state._watchdog_started:
        return
    state._watchdog_task = asyncio.create_task(_watchdog_loop())
    state._watchdog_started = True
    logger.info("R43 watchdog started (scan=%ds, realert=%ds)",
                state.WATCHDOG_SCAN_INTERVAL, state.WATCHDOG_REALERT_INTERVAL)


async def _watchdog_loop() -> None:
    """Background watchdog loop — scans all active pipelines every 10 min."""
    try:
        while True:
            await asyncio.sleep(state.WATCHDOG_SCAN_INTERVAL)
            await _watchdog_scan()
    except asyncio.CancelledError:
        logger.info("R43 watchdog loop cancelled — shutting down")


async def _watchdog_scan() -> None:
    """Scan all active pipelines and trigger alerts for timed-out steps."""
    if not state._PIPELINE_STATE:
        return  # A-2: no active pipelines → zero output

    # ── R67 C2: Mark stale agents offline ──
    try:
        ac_mod.mark_stale_offline()
    except Exception:
        pass  # non-blocking

    now = time.time()
    step_config = _get_step_config("")  # R67 D: unified step config (watchdog global)

    for round_name, pstate in list(state._PIPELINE_STATE.items()):
        if not pstate.get("active"):
            continue

        step_name = pstate.get("current_step", "")
        if not step_name:
            continue

        ws_id = pstate.get("ws_id", "")

        # ── R63 Phase 2: Use timeout_tracker if enabled ──
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
            state._watchdog_alerts[key] = now
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
    return float(state._STEP_TIMEOUT_DEFAULTS.get(step_name, float("inf")))


# ── R63 Phase 2: Timeout escalation ──


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
    from .main import _persist_broadcast, _connections

    step_cfg = state._PIPELINE_CONFIG.get(round_name, {}).get("steps", {}).get(step_name, {})
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


def _check_watchdog_alert(round_name: str, step_name: str) -> str | None:
    """Check dedup state and return 'first', 'repeat', or None (skip)."""
    key = f"{round_name}/{step_name}"
    now = time.time()
    last_alert = state._watchdog_alerts.get(key)

    if last_alert is None:
        # First-time timeout
        state._watchdog_alerts[key] = now
        return "first"

    # Already alerted — check cooldown
    elapsed = now - last_alert
    if elapsed < state.WATCHDOG_REALERT_INTERVAL:
        return None  # Skip — within cooldown

    state._watchdog_alerts[key] = now
    return "repeat"


def _clear_watchdog_alert(round_name: str, step_name: str) -> bool:
    """Clear watchdog alert marker. Returns True if an alert was active."""
    key = f"{round_name}/{step_name}"
    if key in state._watchdog_alerts:
        del state._watchdog_alerts[key]
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
    from .main import _persist_broadcast, _connections

    step_config = _get_step_config(round_name)
    step_info = step_config.get(step_name, {})
    step_display = step_info.get("name", step_name)
    role = step_info.get("role", "?")
    repeat_tag = f"（重复通知）" if alert_type == "repeat" else ""

    started_at = state._PIPELINE_STATE.get(round_name, {}).get("started_at", 0)
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
    pstate = state._PIPELINE_STATE.get(round_name, {})
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
    logger.info("R43 watchdog alert: %s/%s (%s)", round_name, step_name, alert_type)


async def _watchdog_rerollcall(round_name: str, step_name: str) -> None:
    """After timeout, try to rerollcall the current step owner in workspace."""
    pstate = state._PIPELINE_STATE.get(round_name, {})
    ws_id = pstate.get("ws_id", "")
    if not ws_id:
        return
    step_config = _get_step_config(round_name)
    step_info = step_config.get(step_name, {})
    role = step_info.get("role", "?")
    try:
        from .commands.pipeline import _cmd_rollcall_role as _rr
        await _rr("系统", {
            "_positional": [role],
            "context": round_name + " " + step_name + " timeout rerollcall",
        })
    except Exception:
        pass


async def _send_clear_alert(round_name: str, step_name: str, output_ref: str) -> None:
    """Send recovery notification to _admin channel."""
    from .main import _persist_broadcast

    step_config = _get_step_config(round_name)
    step_info = step_config.get(step_name, {})
    step_display = step_info.get("name", step_name)

    msg = (
        f"✅ {round_name} {step_display}（{step_name}）已恢复 — "
        f"已完成（{output_ref}）"
    )

    _persist_broadcast(p.ADMIN_CHANNEL, "系统", msg)
    logger.info("R43 watchdog clear: %s/%s", round_name, step_name)
