"""R63 Phase 1: Timeout tracker — per-step countdown for pipeline steps.

Independent module, decoupled from _PIPELINE_STATE / _PIPELINE_CONFIG.
Pure in-memory timer dict. No async, no new deps.

API:
  start_timer(round_name, step_name, timeout_minutes, on_timeout=None)
  clear_timer(round_name)
  get_remaining(round_name, step_name) -> float
  is_expired(round_name, step_name) -> bool
  get_timer_info(round_name, step_name) -> dict | None
  all_timers() -> dict
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Callable

logger = logging.getLogger("ws-bridge.timeout_tracker")

# ── Internal state ────────────────────────────────────────────────
# key   = "{round_name}/{step_name}"
# value = {
#     "deadline": float,        # time.time() + timeout_minutes * 60
#     "notified": bool,         # timeout alert already sent (dedup)
#     "pm_escalated": bool,     # PM escalation already triggered
#     "timeout_minutes": int,   # original config value
# }
_timeout_timers: dict[str, dict] = {}


def start_timer(round_name: str, step_name: str,
                timeout_minutes: int) -> None:
    """Start a countdown for a pipeline step.
    
    Clears any existing timer for the same round first.
    
    Args:
        round_name: Pipeline round name (e.g. "R63").
        step_name: Step key (e.g. "step2").
        timeout_minutes: Step timeout in minutes.
    """
    clear_timer(round_name)
    deadline = time.time() + timeout_minutes * 60
    key = f"{round_name}/{step_name}"
    _timeout_timers[key] = {
        "deadline": deadline,
        "notified": False,
        "pm_escalated": False,
        "timeout_minutes": timeout_minutes,
    }
    logger.info("Timer started: %s (%d min, deadline=%.0f)",
                key, timeout_minutes, deadline)


def clear_timer(round_name: str) -> None:
    """Clear all timers for a round.
    
    Called on step complete, step handoff, or pipeline close.
    
    Args:
        round_name: Pipeline round name.
    """
    prefix = f"{round_name}/"
    keys = [k for k in _timeout_timers if k.startswith(prefix)]
    for k in keys:
        del _timeout_timers[k]
    if keys:
        logger.info("Timer cleared: %s (%d timers)", round_name, len(keys))


def get_remaining(round_name: str, step_name: str) -> float:
    """Get remaining seconds for a step timer.
    
    Args:
        round_name: Pipeline round name.
        step_name: Step key.
    
    Returns:
        Remaining seconds. 0.0 if not set or already expired.
    """
    timer = _timeout_timers.get(f"{round_name}/{step_name}")
    if not timer:
        return 0.0
    return max(0.0, timer["deadline"] - time.time())


def is_expired(round_name: str, step_name: str) -> bool:
    """Check if a step timer has expired.
    
    Args:
        round_name: Pipeline round name.
        step_name: Step key.
    
    Returns:
        True if expired or not set.
    """
    return get_remaining(round_name, step_name) <= 0.0


def get_timer_info(round_name: str, step_name: str) -> Optional[dict]:
    """Get full timer state dict for display/status.
    
    Args:
        round_name: Pipeline round name.
        step_name: Step key.
    
    Returns:
        Timer dict or None if not set.
    """
    return _timeout_timers.get(f"{round_name}/{step_name}")


def all_timers() -> dict[str, dict]:
    """Get all active timers (for debugging/inspection).
    
    Returns:
        Copy of all timer states.
    """
    return dict(_timeout_timers)


def format_remaining(round_name: str, step_name: str) -> str:
    """Format remaining time for pipeline_status display.
    
    Format: "⏱ 剩余: 12分30秒 / 15分钟"
    
    Args:
        round_name: Pipeline round name.
        step_name: Step key.
    
    Returns:
        Formatted string, or "⏱ 未设置" if no timer.
    """
    timer = _timeout_timers.get(f"{round_name}/{step_name}")
    if not timer:
        return "⏱ 未设置"
    
    remaining = max(0.0, timer["deadline"] - time.time())
    total = timer["timeout_minutes"] * 60
    minutes = int(remaining // 60)
    seconds = int(remaining % 60)
    
    if is_expired(round_name, step_name):
        over_by = int(total - remaining) if remaining > 0 else int(time.time() - timer["deadline"])
        over_min = over_by // 60
        over_sec = over_by % 60
        return f"⏰ 已超时 {over_min}分{over_sec}秒 / {timer['timeout_minutes']}分钟"
    
    return f"⏱ 剩余: {minutes}分{seconds}秒 / {timer['timeout_minutes']}分钟"


def reset() -> None:
    """Clear all timers (for testing)."""
    _timeout_timers.clear()


# ── Legacy handler imports compatibility ──────────────────────────
# The _watchdog_loop in handler.py uses these concepts:
#   - _get_step_timeout(step_name) -> hours (from config)
#   - _check_watchdog_alert(round, step) -> "first"|"repeat"|None
# Phase 2 will integrate timeout_tracker into those functions.
