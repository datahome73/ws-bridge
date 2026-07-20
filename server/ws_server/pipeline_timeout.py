# -*- coding: utf-8 -*-
"""R136 EXT-4: Pipeline timeout scanner — extracted from main.py.

Pure extraction — no semantic changes. References config, state,
_send_to_agent (from main.py via call-site import), and _ensure_pipeline_manager.
"""
import asyncio
import time
import logging

from . import state
from server.common import config

logger = logging.getLogger("ws-bridge")


# ═══ R122: 管线超时告警扫描 ════


def _ensure_timeout_scanner() -> None:
    """在 handler 初始化时调用一次。启动超时扫描定时循环。"""
    timeout_min = config.PIPELINE_TIMEOUT_ALERT_MINUTES
    scan_interval = config.PIPELINE_TIMEOUT_SCAN_INTERVAL
    if timeout_min <= 0:
        logger.info("[R122] 管线超时告警已禁用（PIPELINE_TIMEOUT_ALERT_MINUTES=%d）", timeout_min)
        return
    if state._TIMEOUT_SCAN_STARTED:
        return
    state._TIMEOUT_SCAN_TASK = asyncio.create_task(
        _start_timeout_scan_loop(timeout_min, scan_interval)
    )
    state._TIMEOUT_SCAN_STARTED = True
    logger.info(
        "[R122] 管线超时扫描已启动（timeout=%dmin, interval=%ds）",
        timeout_min, scan_interval,
    )


async def _start_timeout_scan_loop(timeout_min: int, scan_interval: int) -> None:
    """独立的超时扫描定时循环，每 scan_interval 秒执行一次。"""
    while True:
        await asyncio.sleep(scan_interval)
        try:
            await _pipeline_timeout_scan(timeout_min)
        except Exception as e:
            logger.warning("[R122] 超时扫描错误: %s", e)


async def _pipeline_timeout_scan(timeout_min: int) -> None:
    """遍历所有 RUNNING 管线，检查 in_progress step 是否超时。

    R122: 30min 首次告警（已有）
    R124: + 重发派活（re_notified）+ timeout 标记
    """
    from .pipeline_context import PipelineStatus as PS

    now = time.time()
    threshold = timeout_min * 60.0
    from .main import _ensure_pipeline_manager
    mgr = _ensure_pipeline_manager()
    alerted = 0

    for ctx in mgr.get_all_active():
        if ctx.status != PS.RUNNING:
            continue
        for step in (ctx.steps or []):
            if step.get("status") != "in_progress":
                continue
            dispatched_at = step.get("dispatched_at")
            if not dispatched_at:
                continue
            elapsed = now - dispatched_at
            step_key = step.get("name", step.get("step_key", ""))
            try:
                step_num = int(step_key.replace("step", ""))
            except (ValueError, TypeError):
                step_num = 0
            pm_id = config.PIPELINE_PM_AGENT_ID

            # ── R122 已有: 30min 首次告警（不动）──
            if elapsed >= threshold and not step.get("timeout_alerted"):
                step["timeout_alerted"] = True
                alerted += 1
                if pm_id:
                    alert_content = (
                        f"⏰ 管线超时告警\n\n"
                        f"**{ctx.round_name}** Step {step_key} 已超时 "
                        f"（{int(elapsed // 60)} 分钟无回复）\n\n"
                        f"状态: 已派活 → {step.get('agent_name', '?')}\n"
                        f"请检查 bot 状态或手动处理。"
                    )
                    try:
                        from .main import _send_to_agent
                        await _send_to_agent(pm_id, {
                            "type": "broadcast",
                            "channel": f"_inbox:{pm_id}",
                            "from_name": "系统",
                            "from_agent": state.SYSTEM_AGENT_ID,
                            "content": alert_content,
                            "ts": time.time(),
                        })
                        logger.info(
                            "[R122] 超时告警: %s Step %s → PM (%s)",
                            ctx.round_name, step_key, pm_id[:12],
                        )
                    except Exception as e:
                        logger.warning("[R122] 告警发送失败: %s", e)

            # ── R124: 30min 重发派活 ──
            _retry_min = getattr(config, "PIPELINE_TIMEOUT_RETRY_MINUTES", 30)
            if (_retry_min > 0
                    and elapsed >= _retry_min * 60
                    and step.get("timeout_alerted")
                    and not step.get("re_notified")):
                step["re_notified"] = True
                alerted += 1
                from .main import _auto_re_notify
                asyncio.ensure_future(_auto_re_notify(ctx, step_key, step_num))

            # ── R124: 45min timeout 标记 ──
            _mark_min = getattr(config, "PIPELINE_TIMEOUT_MARK_MINUTES", 45)
            if (_mark_min > 0
                    and elapsed >= _mark_min * 60
                    and step.get("re_notified")
                    and step.get("status") != "timeout"):
                step["status"] = "timeout"
                alerted += 1
                if pm_id and step_num:
                    from .main import _send_to_agent
                    await _send_to_agent(pm_id, {
                        "type": "broadcast",
                        "channel": f"_inbox:{pm_id}",
                        "from_name": "系统",
                        "from_agent": state.SYSTEM_AGENT_ID,
                        "content": (
                            f"⏰ {ctx.round_name} Step {step_key} bot 已 "
                            f"{int(elapsed // 60)} 分钟未响应，已标记 timeout。\n"
                            f"请 PM 处理。"
                        ),
                        "ts": time.time(),
                    })

    if alerted:
        try:
            mgr.save()
            logger.info("[R124] 超时扫描完成（%d 条变更），状态已持久化", alerted)
        except Exception:
            pass
