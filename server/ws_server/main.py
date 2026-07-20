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


async def _auto_advance_pipeline(round_name: str, result: dict) -> str:
    """Git sync 检测到新产出后自动推进状态机.

    Args:
        round_name: 管线标识
        result: PipelineGitSync.sync() 返回值

    Returns:
        广播消息文本.
    """
    pstate = state._PIPELINE_STATE.get(round_name)
    if not pstate:
        return ""

    step_config = _get_step_config(round_name)
    current_step = pstate.get("current_step", "")
    if not current_step:
        return ""

    # 获取当前 Step 在 step_config 中的索引
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
    try:
        idx = step_keys.index(current_step)
    except ValueError:
        return ""

    if idx + 1 >= len(step_keys):
        return ""  # 已是最后一步

    next_step = step_keys[idx + 1]
    new_sha = result.get("new_sha", "")

    # 1. 状态机推进
    pstate["current_step"] = next_step
    pstate["last_output_sha"] = new_sha
    # 更新 Task state
    tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
    for t in tasks:
        if t.get("name") == current_step and t.get("state") != p.TaskState.COMPLETED.value:
            await _cmd_task_update("系统", {
                "_positional": [t["id"]],
                "state": p.TaskState.COMPLETED.value,
                "output": new_sha,
            })
        if t.get("name") == next_step and t.get("state") == p.TaskState.PENDING.value:
            await _cmd_task_update("系统", {
                "_positional": [t["id"]],
                "state": p.TaskState.WORKING.value,
            })

    # 2. 清理旧 ACK FAILED 标记
    old_ack_key = f"{round_name}/{current_step}"
    if old_ack_key in state._step_ack_states:
        if state._step_ack_states[old_ack_key].get("state") == "FAILED":
            state._step_ack_states.pop(old_ack_key, None)
            logger.info("[R65] 清除 %s 的 FAILED 标记（git sync 发现新产出）", old_ack_key)

    # 3. 广播自动同步消息
    ws_id = pstate.get("ws_id", "")
    commit_short = new_sha[:7] if new_sha else "?"
    mode = result.get("mode", "auto")
    mode_label = "" if mode == "default" else f"（{mode} 匹配）"

    msg = (
        f"💻 {round_name} {current_step} → {next_step} 已自动同步\n"
        f"  commit: {commit_short}{mode_label}\n"
        f"→ @{next_step} 到你了！"
    )

    if ws_id:
        pm_name = config.PIPELINE_PM_NAME
        _persist_broadcast(ws_id, pm_name, msg)
        payload = json.dumps({
            "type": "broadcast", "channel": ws_id,
            "from_name": pm_name, "from": pm_name,
            "content": msg, "ts": time.time(),
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

    # 4. 点名下一角色（复用 R63 @role_name → @bot_name 机制）
    next_role = step_config[next_step].get("role", "")
    if next_role:
        cards = ac_mod.get_all_cards()
        ws_obj = ws_mod.get_workspace(ws_id) if ws_id else None
        if ws_obj and cards:
            matched = _find_agents_by_role(next_role, ws_obj.members, cards)
            users = auth.get_users()
            for aid in matched:
                name = users.get(aid, {}).get("name", aid[:12])
                mention = f"@{name} 🏗️ {round_name} {next_step} 到你了！"
                mention_payload = json.dumps({
                    "type": "broadcast", "channel": ws_id,
                    "from_name": pm_name, "from": pm_name,
                    "content": mention, "ts": time.time(),
                })
                for conn in list(_connections.get(aid, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(mention_payload)
                        elif hasattr(conn, "send"):
                            await conn.send(mention_payload)
                    except Exception:
                        pass

    # 5. 启动下一 Step timeout_tracker 倒计时
        timeout_min = step_config.get(next_step, {}).get("timeout_minutes", 20)
        timeout_tracker.start_timer(round_name, next_step, timeout_min)

    logger.info("[R65] 管线 %s 已自动推进：%s → %s (sha=%s)",
                round_name, current_step, next_step, commit_short)
    return msg


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


async def _verify_git_commit(commit_sha: str) -> tuple[bool, str]:
    """Check remote git dev branch for the given commit SHA via git ls-remote.
    Uses 10s timeout. On failure, degrades to a warning.
    Returns: (ok_to_proceed, message)
    """
    import subprocess
    repo_url = _r42cfg.GIT_REMOTE_URL
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "git", "ls-remote", repo_url, "refs/heads/dev",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ),
            timeout=10,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return True, (
                f"⚠️ git ls-remote 异常退出（{stderr.decode('utf-8', errors='replace')[:40]}），"
                f"已跳过验证，继续推进"
            )
        refs = stdout.decode("utf-8", errors="replace")
        if commit_sha in refs:
            return True, ""
        else:
            return False, (
                f"❌ Commit {commit_sha[:12]} 不存在于远程仓库 "
                f"（{repo_url}）的 dev 分支"
            )
    except asyncio.TimeoutError:
        return True, "⚠️ git ls-remote 超时（10s），已跳过验证，继续推进"
    except Exception as e:
        return True, f"⚠️ git 验证不可达（{str(e)[:40]}），已跳过验证，继续推进"


# ── R77: !pipeline command — unified pipeline context management ─────


def _format_pipeline_context(ctx: PipelineContext) -> str:
    """格式化 PipelineContext 为人类可读文本.R78 D2: 增强版 ACK 展示."""
    from datetime import datetime
    lines = [
        f"📋 {ctx.round_name} [{ctx.task_kind.value}]",
        f"  状态: {ctx.status.value}",
        f"  Step: {ctx.current_step}/{ctx.total_steps}",
        f"  阶段: {ctx.current_phase}",
    ]
    # ── R106: Step-by-step status (role mapping) ──
    step_roles = ["pm", "arch", "dev", "review", "qa", "operations"]
    role_names = {"pm": "PM", "arch": "架构师", "dev": "开发",
                  "review": "审查", "qa": "测试", "operations": "运维"}
    step_parts = []
    for i in range(1, ctx.total_steps + 1):
        step_key = f"step{i}"
        role = step_roles[i - 1] if i - 1 < len(step_roles) else "?"
        role_name = role_names.get(role, role)
        # Determine status from current_step + ack_states
        ack = ctx.ack_states.get(step_key, {})
        ack_state = ack.get("state", "")
        if ack_state == "FAILED":
            icon = "❌"
            desc = "失败"
        elif ack_state == "ACKED" or i < ctx.current_step:
            icon = "✅"
            desc = "已完成"
        elif i == ctx.current_step:
            icon = "🔄"
            desc = "进行中"
        elif ack_state in ("SENT", "DELIVERED", "IN_PROGRESS"):
            icon = "🔄"
            desc = "进行中"
        else:
            icon = "⏳"
            desc = "待开始"
        step_parts.append(f"  Step{i} {icon} {role_name} → {desc}")
    if step_parts:
        lines.append("  步骤:")
        lines.extend(step_parts)
    # R78 D2: ACK 状态逐 step 展示（缩略版）
    ack_parts = []
    for i in range(1, ctx.total_steps + 1):
        step = f"step{i}"
        ack = ctx.ack_states.get(step, {})
        state = ack.get("state", "")
        role = ack.get("role_name", "")
        if state == "ACKED":
            ack_parts.append(f"step{i} ✅{role}")
        elif state == "PENDING":
            ack_parts.append(f"step{i} ⏳{role}")
        elif state == "FAILED":
            ack_parts.append(f"step{i} ❌{role}")
        elif state in ("SENT", "DELIVERED", "IN_PROGRESS", "ACKNOWLEDGED"):
            ack_parts.append(f"step{i} 🔄{role}")
        else:
            ack_parts.append(f"step{i} ⬜")
    lines.append(f"  ACK: {' | '.join(ack_parts)}")
    if ctx.blocked_reason:
        lines.append(f"  阻塞: {ctx.blocked_reason}")
    if ctx.role_agent_map:
        parts = []
        for role, agents in ctx.role_agent_map.items():
            agents_str = ",".join(a[:12] for a in agents)
            parts.append(f"{role}={agents_str}")
        lines.append(f"  成员: {'; '.join(parts)}")
    if ctx.workspace_id:
        lines.append(f"  工作室: {ctx.workspace_id}")
    if ctx.created_at:
        lines.append(f"  创建: {datetime.fromtimestamp(ctx.created_at).strftime('%m/%d %H:%M')}")
    return "\n".join(lines)


async def _restore_pipeline_timers() -> None:
    """On server start, recover pipeline timeout timers from task store."""
    try:
        all_tasks = ts.list_tasks_by_context("", config.DATA_DIR)
        round_groups = {}
        for t in all_tasks:
            ctx = t.get("context", "")
            state = t.get("state", "")
            if ctx.startswith("R") and state not in ("completed", "cancelled"):
                if ctx not in round_groups:
                    round_groups[ctx] = []
                round_groups[ctx].append(t)
        for round_name, tasks in round_groups.items():
            if round_name in state._PIPELINE_STATE:
                continue
            tasks_sorted = sorted(tasks, key=lambda x: x.get("created_at", 0))
            current_step = tasks_sorted[0].get("name", "") if tasks_sorted else ""
            started_at = tasks_sorted[0].get("created_at", time.time())
            ws_id = "ws:" + round_name + "-dev"
            _set_pipeline_state(round_name, {
                "active": True,
                "current_step": current_step,
                "ws_id": ws_id,
                "started_at": started_at,
            })
            logger.info("R49 C restored timer: %s step=%s ws=%s", round_name, current_step, ws_id)
    except Exception:
        pass


# ═══ R119: 启动时恢复活跃管线的自动派活 ═══


async def _restore_pipeline_dispatches() -> None:
    """On server start, re-dispatch the current step for all RUNNING pipelines
    whose current step is still pending.  Handles the case where a container
    restart lost the original auto-dispatch message."""
    try:
        mgr = _ensure_pipeline_manager()
        for ctx in mgr.get_all_active():
            if ctx.status != PipelineStatus.RUNNING:
                continue
            step_num = ctx.current_step
            if step_num < 1 or step_num > ctx.total_steps:
                continue
            step_key = f"step{step_num}"
            step_info = next(
                (s for s in (ctx.steps or []) if s.get("name") == step_key), None,
            )
            if not step_info or step_info.get("status") not in ("pending", "in_progress"):
                continue
            logger.info("[R119] 恢复派活: %s step%d → %s",
                        ctx.round_name, step_num,
                        step_info.get("agent_id", "?")[:20])
            _enqueue_retry(ctx, step_num)
            _enqueue_retry(ctx, step_num)
    except Exception:
        pass


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


def _extract_artifact_kv(content: str) -> dict[str, str]:
    """从 '已完成 ✅ R{N} Step {N}##key=value##...' 中提取键值对。

    Args:
        content: 完整的完成消息文本

    Returns:
        提取的键值对 dict（不含 Step/round 信息）。
        无 ## 时返回空 dict。
    """
    if "##" not in content:
        return {}
    parts = content.split("##")
    result: dict[str, str] = {}
    for p in parts[1:]:  # parts[0] 是前缀段，跳过
        if "=" in p:
            key, value = p.split("=", 1)  # 仅第一个 = 做分隔
            key = key.strip()
            if key:
                result[key] = value
        else:
            logger.debug("[R115] 忽略不含 '=' 的 ## 段: %s", p[:50])
    return result


# ═══ R106: Pipeline step auto-advance on completion message ═════


def _try_advance_pipeline(content: str, agent_id: str) -> tuple[bool, str]:
    """Parse 已完成 ✅ R{N} Step {N} and auto-advance pipeline context.

    Returns:
        (True, "round_name") on success, (False, reason) on skip.
    """
    m = re.match(r"已完成 ✅ R(\d+) Step (\d+)", content)
    if not m:
        return False, "no match"
    round_name = f"R{m.group(1)}"
    completed_step = int(m.group(2))
    try:
        mgr = _ensure_pipeline_manager()
        ctx = mgr.get(round_name)
        if not ctx:
            logger.info("[R106] 管线 %s 无上下文，跳过自动推进", round_name)
            return False, "no context"
        old_step = ctx.current_step
        # Only advance if completed_step matches current_step
        if completed_step == old_step:
            # ═══ R115: 提取 ##key=value 并注入 artifacts ═══
            _kv = _extract_artifact_kv(content)
            if _kv:
                _step_key = f"step{completed_step}"
                if not hasattr(ctx, 'artifacts') or not ctx.artifacts:
                    ctx.artifacts = {}
                ctx.artifacts[_step_key] = _kv
                try:
                    mgr.save()
                except Exception:
                    pass
                logger.info("[R115] %s step%d artifacts: %s", round_name, completed_step, _kv)
            # ═══ R123: advance 前记录 step output + result_msg ═══
            _step_idx = completed_step - 1
            _step_info = ctx.steps[_step_idx] if _step_idx < len(ctx.steps) else None
            if _step_info:
                _output = {}
                if _kv:
                    for _k in ("sha", "commit_msg", "tech_plan_url", "branch_name",
                                "test_scope", "test_report_url", "test_summary",
                                "review_url"):
                        if _k in _kv:
                            _output[_k] = _kv[_k]
                _step_info["output"] = _output if _output else None
                _step_info["result_msg"] = content[:200]
                _step_info["status"] = "done"
                try:
                    mgr.save()
                except Exception:
                    pass
            # ═══ R124: Step 产出基本验证（SHA 格式 + 可选远程 git）═══
            if _kv:
                _step_v = _step_info if _step_info else None
                if _step_v:
                    _out_v = _step_v.get("output")
                    if not isinstance(_out_v, dict):
                        _out_v = {}
                    _sha_v = _kv.get("sha", "")
                    if _sha_v:
                        import re as _re_sha124
                        if _re_sha124.match(r"^[0-9a-f]{7,40}$", _sha_v):
                            _out_v["sha_validation"] = "valid_format"
                        else:
                            _out_v["sha_validation"] = "invalid_format"
                        _step_v["output"] = _out_v if _out_v else None
                        try:
                            mgr.save()
                        except Exception:
                            pass
                    # 远程 git 验证（可选、异步、不阻塞）
                    if (config.PIPELINE_OUTPUT_VERIFICATION and _sha_v
                            and _out_v.get("sha_validation") == "valid_format"):
                        asyncio.ensure_future(
                            _verify_sha_remote(round_name, completed_step, _sha_v)
                        )
            # ════════════════════════════════════════════════════════════════
            asyncio.ensure_future(mgr.advance_step(round_name))
            logger.info(
                "[R106] %s Step %d → %d (auto-advance from completion)",
                round_name, old_step, old_step + 1,
            )
            # ── R107: 自动派活下一步（受 AUTO_DISPATCH_ENABLED 控制）──
            next_step = old_step + 1
            if next_step <= ctx.total_steps:
                logger.info(
                    "[R117] %s Step %d 已完成，尝试自动派活 Step %d",
                    round_name, old_step, next_step,
                )
                asyncio.ensure_future(_auto_dispatch(ctx, next_step))
            else:
                # 最后一步已完成，标记管线 completed
                asyncio.ensure_future(mgr.transition_to(round_name, PipelineStatus.COMPLETED))
                logger.info("[R107] %s 全管线已完成 ✅", round_name)
                asyncio.ensure_future(_notify_pm(ctx, ctx.total_steps, "completed"))
                # ═══ R124: 自动归档 ═══
                asyncio.ensure_future(_archive_pipeline(round_name))
                # ═══════════════════════
            return True, round_name
        elif completed_step < old_step:
            logger.info(
                "[R106] %s Step %d already past completed Step %d (skip)",
                round_name, old_step, completed_step,
            )
            return False, "already past"
        else:
            logger.info(
                "[R106] %s Step %d > current %d (gap, skip)",
                round_name, completed_step, old_step,
            )
            return False, "future step"
    except Exception as e:
        logger.warning("[R106] 自动推进异常: %s", e)
        return False, f"error: {e}"


# ── R118: PM 通知函数 ──────────────────────────────────


async def _notify_pm(ctx: PipelineContext, step_num: int, status: str, detail: str = "") -> None:
    """发送管线通知给 PM。
    status: 'dispatched' | 'completed' | 'failed' | 'retrying'
    """
    pm_id = config.PIPELINE_PM_AGENT_ID
    role_names = {1: "📋 PM", 2: "📐 Arch", 3: "💻 Dev", 4: "👁 Review", 5: "🧪 QA", 6: "🚢 Ops"}
    step_role = role_names.get(step_num, "?")

    if status == "dispatched":
        agent_name = _get_step_agent_name(ctx, step_num)
        content = (
            f"✅ **{ctx.round_name} 管线自动推进**\n\n"
            f"Step {step_num} 🚀 已派活 → {agent_name}（{step_role}）\n"
            + (f"\n{detail}" if detail else "")
        )
    elif status == "completed":
        # 构造完成摘要
        step_lines = []
        for i, s in enumerate(ctx.steps, 1):
            role = role_names.get(i, "?")
            agent = s.get("agent_name", s.get("agent_id", "?")[:12])
            out = s.get("output", s.get("result_msg", ""))
            out_short = out[:40] + "..." if len(str(out)) > 40 else out
            step_lines.append(f"| {i} | {role} | {agent} | {out_short} |")
        table_header = "| Step | 角色 | 执行者 | 产出 |\n|:---:|:-----|:-------|:-----|\n"
        content = (
            f"🎉 **{ctx.round_name} 管线已完成！**\n\n"
            f"{table_header}{chr(10).join(step_lines)}"
        )
    elif status == "failed":
        agent_name = _get_step_agent_name(ctx, step_num)
        content = (
            f"⚠️ **{ctx.round_name} 管线异常**\n\n"
            f"Step {step_num}（{step_role}）→ {agent_name} 离线，"
            f"自动派活失败（5 次重试）\n"
            + (f"\n{detail}" if detail else "")
        )
    elif status == "retrying":
        agent_name = _get_step_agent_name(ctx, step_num)
        content = (
            f"⏳ **{ctx.round_name} 派活排队中**\n\n"
            f"Step {step_num}（{step_role}）→ {agent_name} 离线，排队中（{detail}）"
        )
    # ═══ R124: 驳回/卡死通知 ═══
    elif status == "rejected":
        content = (
            f"⚠️ **{ctx.round_name} 管线回退**\n\n"
            f"Step {step_num}（{step_role}）被退回\n"
            + (f"{detail}" if detail else "")
        )
    elif status == "stuck":
        content = (
            f"🔴 **{ctx.round_name} 管线已卡死**\n\n"
            + (f"{detail}" if detail else "")
        )
    elif status == "archived":
        content = (
            f"📦 **{ctx.round_name} 管线已完成并归档**\n\n"
            + (f"{detail}" if detail else "")
        )
    # ═══════════════════════════════════════════════════
    else:
        return

    payload = {
        "type": "broadcast",
        "channel": f"_inbox:{pm_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": content,
        "ts": time.time(),
    }
    sent = await _send_to_agent(pm_id, payload)
    logger.info("[R118] 通知 PM step%d status=%s sent=%d", step_num, status, sent)


# ── R118: 离线重试队列 ──────────────────────────────────

_pending_retries: dict[str, dict] = {}  # round_name → {ctx, step_num, retry_count, next_retry_at, notify_sent}

async def _retry_loop() -> None:
    """后台循环，每 30s 扫描待重试队列。最多重试 5 次，每次间隔 60s。"""
    while True:
        now = time.time()
        for round_name in list(_pending_retries.keys()):
            entry = _pending_retries[round_name]
            if now < entry["next_retry_at"]:
                continue
            ctx = entry["ctx"]
            step_num = entry["step_num"]
            entry["retry_count"] += 1
            logger.info("[R118] 重试派活 %s step%d (尝试 %d/5)",
                        round_name, step_num, entry["retry_count"])
            result = await _auto_dispatch(ctx, step_num)
            if result:
                del _pending_retries[round_name]
                logger.info("[R118] 重试成功: %s step%d", round_name, step_num)
            elif entry["retry_count"] >= 5:
                del _pending_retries[round_name]
                asyncio.ensure_future(
                    _notify_pm(ctx, step_num, "failed",
                               f"5 次重试均失败，目标 bot 持续离线"))
                logger.warning("[R118] 重试耗尽: %s step%d 5/5 失败", round_name, step_num)
            else:
                entry["next_retry_at"] = time.time() + 60
                if not entry.get("notify_sent"):
                    entry["notify_sent"] = True
                    asyncio.ensure_future(
                        _notify_pm(ctx, step_num, "retrying",
                                   f"尝试 {entry['retry_count']+1}/5"))
                logger.info("[R118] 重试排队: %s step%d 等待 60s",
                            round_name, step_num)
        await asyncio.sleep(30)


def _enqueue_retry(ctx: PipelineContext, step_num: int) -> None:
    """将失败的自动派活加入重试队列。"""
    round_name = ctx.round_name
    if round_name in _pending_retries:
        return  # 已在队列中
    _pending_retries[round_name] = {
        "ctx": ctx,
        "step_num": step_num,
        "retry_count": 0,
        "next_retry_at": time.time() + 60,
        "notify_sent": False,
    }
    logger.info("[R118] 入重试队列: %s step%d", round_name, step_num)


# ── R107: 消息模板渲染 ──────────────────────────────────


def _render_template(template: str, ctx: PipelineContext, step_num: int) -> str:
    """用 Pipeline Context 数据渲染模板字符串。

    变量来源优先级（高→低）:
    1. ctx.artifacts 中各 step 的产出 KV
    2. ctx.references 中的文档 URL
    3. ctx 基本信息 (round_name, round_title)

    R123 新增 {stepN:field} 变量语法，解析优先级:
    1. ctx.artifacts["step{N}"].get(field)
    2. ctx.steps[idx].output.get(field)   (当 output 是 dict 时)
    3. ctx.steps[idx].get(field)           (agent_name, result_msg 等)
    4. ctx.references.get(field)
    5. 空字符串
    """
    # ═══ R123: 先解析 {stepN:field} 占位符 ═══
    _step_placeholder_re = re.compile(r"\{step(\d+):(\w+)\}")

    def _resolve_step_var(m: re.Match) -> str:
        _sn = int(m.group(1))
        _field = m.group(2)
        _sk = f"step{_sn}"
        _idx = _sn - 1
        # 1. ctx.artifacts["step{N}"].get(field)
        _art = ctx.artifacts.get(_sk, {})
        if isinstance(_art, dict) and _field in _art:
            val = str(_art[_field])
            return val if val else ""
        # 2. ctx.steps[idx].output.get(field)
        if _idx < len(ctx.steps):
            _step = ctx.steps[_idx]
            if isinstance(_step, dict):
                _out = _step.get("output")
                if isinstance(_out, dict) and _field in _out:
                    val = str(_out[_field])
                    return val if val else ""
                # 3. ctx.steps[idx].get(field)
                if _field in _step:
                    val = str(_step[_field])
                    return val if val else ""
        # 4. ctx.references.get(field)
        if isinstance(ctx.references, dict) and _field in ctx.references:
            val = str(ctx.references[_field])
            return val if val else ""
        # 5. 空字符串
        return ""

    template = _step_placeholder_re.sub(_resolve_step_var, template)
    # ════════════════════════════════════════════════════════════════

    vars = {
        "round": ctx.round_name,
        "round_title": ctx.round_title,
        "requirements_url": ctx.references.get("requirements_url", ""),
        "work_plan_url": ctx.references.get("work_plan_url", ""),
    }
    # 补充来自 artifacts 的变量（覆盖同名变量）
    for step_key, step_artifacts in ctx.artifacts.items():
        if isinstance(step_artifacts, dict):
            vars.update(step_artifacts)
    # 填充模板中的 {var} 占位符
    for key, value in vars.items():
        template = template.replace(f"{{{key}}}", str(value))
    # ═══ R123: 清理空值字段行（##key## \n 残留）═══
    template = re.sub(r"^##\w+##\s*\n", "", template, flags=re.MULTILINE)
    template = template.strip()
    # ══════════════════════════════════════════════════
    return template


def _get_step_agent_name(ctx: PipelineContext, step_num: int) -> str:
    """辅助函数：获取指定 step 的 agent 名称。"""
    step_key = f"step{step_num}"
    info = next((s for s in ctx.steps if s.get("name") == step_key), None)
    if info:
        return info.get("agent_name", info.get("agent_id", "?"))
    return "?"


# ═══ R123: 前置步骤摘要生成 ═══
_ROLE_EMOJIS = {1: "📋", 2: "📐", 3: "💻", 4: "👁", 5: "🧪", 6: "🚢"}
_ROLE_NAMES = {1: "PM", 2: "Arch", 3: "Dev", 4: "Review", 5: "QA", 6: "Ops"}
_URL_FIELDS = {
    "tech_plan_url": "技术方案", "review_url": "审查报告",
    "test_report_url": "测试报告", "test_summary": "测试结果",
    "requirements_url": "需求文档", "work_plan_url": "工作计划",
}


def _build_step_summary(ctx: PipelineContext, step_num: int) -> str:
    """为 step_num 构建前序步骤完成摘要。仅显示已完成（status=done）的前置 step。"""
    lines = ["══════ 前置步骤状态 ══════"]
    has_prev = False
    for i, s in enumerate(ctx.steps, 1):
        if i >= step_num:
            break
        if s.get("status") != "done":
            continue
        has_prev = True
        emoji = _ROLE_EMOJIS.get(i, "?")
        rname = _ROLE_NAMES.get(i, "?")
        agent = s.get("agent_name", s.get("agent_id", "?")[:12])
        lines.append(f"\nStep {i} {emoji} {rname}（{agent}）✅")
        output = s.get("output")
        if isinstance(output, dict):
            sha = output.get("sha", "")
            if sha:
                lines.append(f"  提交: `{sha}` — {output.get('commit_msg', '')}")
            for k, label in _URL_FIELDS.items():
                if output.get(k):
                    lines.append(f"  产出: [{label}]({output[k]})")
        result_msg = s.get("result_msg", "")
        if result_msg:
            lines.append(f"  结果: {result_msg[:80]}")
    if not has_prev:
        return ""
    lines.append("\n════════════════════\n")
    return "\n".join(lines)
# ════════════════════════════════════════════════════════════════




def _find_archive(round_name: str) -> dict | None:
    """从 pipeline_archive.json 查找已归档轮次。"""
    from pathlib import Path
    archive_path = Path(config.DATA_DIR) / "pipeline_archive.json"
    if not archive_path.exists():
        return None
    try:
        records = json.loads(archive_path.read_text(encoding="utf-8"))
        for rec in records:
            if rec.get("round_name") == round_name:
                return rec
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _fmt_ts(ts: float) -> str:
    """格式化时间戳。"""
    if not ts:
        return "?"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (ValueError, OSError):
        return str(ts)


# ═══ R124: 远程 git SHA 验证 ──────────────────────
async def _verify_sha_remote(round_name: str, step_num: int, sha: str) -> None:
    """异步验证 SHA 在远程 dev 分支的存在性。不阻断管线推进。"""
    try:
        mgr = _ensure_pipeline_manager()
        ctx = mgr.get(round_name)
        if not ctx:
            return
        _step = ctx.steps[step_num - 1] if step_num - 1 < len(ctx.steps) else None
        if not _step:
            return
        _output = _step.get("output") or {}
        if not isinstance(_output, dict):
            _output = {}
        async with asyncio.timeout(5):
            proc = await asyncio.create_subprocess_exec(
                "git", "ls-remote", "origin", "dev",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if sha in stdout.decode("utf-8", errors="replace"):
                _output["sha_validation"] = "verified"
            else:
                _output["sha_validation"] = "not_found"
                _step["output"] = _output
                mgr.save()
                return
            proc2 = await asyncio.create_subprocess_exec(
                "git", "log", "--oneline", sha, "-1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout2, _ = await proc2.communicate()
            _msg = stdout2.decode("utf-8", errors="replace")
            _output["commit_round_match"] = "matched" if round_name in _msg else "mismatched"
        _step["output"] = _output
        mgr.save()
    except asyncio.TimeoutError:
        if ctx and _step:
            _step["output"]["sha_validation"] = "unchecked"
            mgr.save()
    except Exception as e:
        logger.warning("[R124] SHA 验证异常: %s", e)


async def _auto_re_notify(ctx, step_key: str, step_num: int) -> None:
    """超时后重新发送派活消息给原 bot。"""
    step_idx = step_num - 1
    if step_idx < 0 or step_idx >= len(ctx.steps):
        return
    step_info = ctx.steps[step_idx]
    target_agent_id = step_info.get("agent_id", "")
    if not target_agent_id:
        return
    tmpl = ctx.message_templates.get(step_key)
    if tmpl:
        content = _render_template(tmpl, ctx, step_num)
    else:
        content = f"📋 {ctx.round_name} Step {step_num} — {step_info.get('role', '?')}，请继续完成"
    # 头部加重发标记
    content = f"🔄 消息重发 — {content}"
    payload = {
        "type": "broadcast",
        "channel": f"_inbox:{target_agent_id}",
        "content": content,
        "from_name": "小谷",
        "agent_id": "ws_f26e585f6479",
        "id": f"retry-{ctx.round_name}-step{step_num}-{int(time.time() * 1000)}",
        "ts": time.time(),
    }
    sent = await _send_to_agent(target_agent_id, payload)
    pm_id = config.PIPELINE_PM_AGENT_ID
    if pm_id:
        agent_name = step_info.get("agent_name", target_agent_id[:12])
        await _send_to_agent(pm_id, {
            "type": "broadcast",
            "channel": f"_inbox:{pm_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"🔄 {ctx.round_name} Step {step_key} 超时，已重新发送派活消息给 {agent_name}",
            "ts": time.time(),
        })
    logger.info("[R124] 超时重发: %s Step %s → %s (sent=%d)",
                ctx.round_name, step_key, target_agent_id[:12], sent if sent else 0)
# ═══════════════════════════════════════════════════════════


async def _auto_dispatch(ctx: PipelineContext, step_num: int) -> bool:
    """自动派活下一步。受 AUTO_DISPATCH_ENABLED 开关控制。"""
    if not config.AUTO_DISPATCH_ENABLED:
        logger.info(
            "[R107] 自动派活已关闭，跳过 step%d 发送 (round=%s)",
            step_num, ctx.round_name,
        )
        # 模拟：仅打印渲染结果，不实际发送
        next_step_key = f"step{step_num}"
        next_template = ctx.message_templates.get(next_step_key, "")
        if next_template:
            rendered = _render_template(next_template, ctx, step_num)
            logger.info(
                "[R107] [模拟] 将派活 step%d 给 %s:\n%s",
                step_num,
                _get_step_agent_name(ctx, step_num),
                rendered,
            )
        return False

    # ← 实际发送逻辑（开关打开后才执行）
    next_step_key = f"step{step_num}"
    next_template = ctx.message_templates.get(next_step_key)
    if not next_template:
        logger.warning(
            "[R107] 管线 %s 缺少 step%d 模板，跳过自动派活",
            ctx.round_name, step_num,
        )
        return False

    next_step_info = next(
        (s for s in (ctx.steps or []) if s.get("name") == next_step_key), None,
    )
    if not next_step_info or not next_step_info.get("agent_id"):
        logger.warning(
            "[R107] 管线 %s step%d 无 agent_id，跳过自动派活",
            ctx.round_name, step_num,
        )
        return False

    target_agent_id = next_step_info["agent_id"]

    # ═══ R117 fix: card key → WS ID fallback ═══
    if not target_agent_id.startswith("ws_"):
        _fallback_id = _resolve_card_key_to_ws_id(target_agent_id)
        if _fallback_id:
            logger.info("[R117] card key %s → WS ID %s (fallback)",
                        target_agent_id, _fallback_id)
            target_agent_id = _fallback_id
            next_step_info["agent_id"] = _fallback_id
        else:
            logger.warning(
                "[R117] 无法解析 card key %s 为 WS ID，跳过自动派活 step %d of %s",
                target_agent_id, step_num, ctx.round_name,
            )
            return False

    content = _render_template(next_template, ctx, step_num)

    # ═══ R123: Step ≥ 3 时前置步骤摘要注入 ═══
    if step_num >= 3:
        _summary = _build_step_summary(ctx, step_num)
        if _summary:
            content = _summary + "\n" + content
    # ══════════════════════════════════════════════════════

    payload = {
        "type": "broadcast",
        "channel": f"_inbox:{target_agent_id}",
        "content": content,
        "from_name": "系统",
        "agent_id": state.SYSTEM_AGENT_ID,
        "to_agent": target_agent_id,
        "id": f"auto-{ctx.round_name}-step{step_num}-{int(time.time() * 1000)}",
        "ts": time.time(),
    }

    # ── R109 修复: 派活消息落库 ──
    try:
        ms.save_message(
            msg_id=payload["id"],
            msg_type="broadcast",
            from_agent=payload["agent_id"],
            from_name=payload["from_name"],
            content=content,
            ts=payload["ts"],
            data_dir=config.DATA_DIR,
            channel=f"_inbox:{target_agent_id}",
        )
    except Exception:
        pass  # 入库失败不阻塞派活

    sent = await _send_to_agent(target_agent_id, payload)
    logger.info("[R109] 自动派活 step%d → %s (%s): sent=%d",
                step_num, target_agent_id,
                next_step_info.get("agent_name", "?"), sent)
    # R118: 派活成功后通知 PM
    if sent > 0:
        # 标记 step 为进行中，防止重复派活
        next_step_info["status"] = "in_progress"
        # ═══ R122: 记录派活时间戳，供超时扫描 ═══
        next_step_info["dispatched_at"] = time.time()
        next_step_info["timeout_alerted"] = False
        try:
            mgr = _ensure_pipeline_manager()
            mgr.save()
        except Exception:
            pass
        asyncio.ensure_future(_notify_pm(ctx, step_num, "dispatched"))
    else:
        # R118: 离线重试
        _enqueue_retry(ctx, step_num)
    return sent > 0



# ═══ R124: 驳回管线状态回退 ═══
async def _handle_reject(content: str, sender_agent_id: str) -> None:
    """处理退回 🔄 R{N} Step {N} — 原因 消息。
    管线状态回退 + 通知 PM，不自动重新派活。
    异步后台执行（不阻塞 relay 返回）。
    """
    m = re.match(r"退回 🔄 (R\d+) Step (\d+)", content)
    if not m:
        logger.info("[R124] 退回消息格式不匹配: %s...", content[:60])
        return
    round_name = m.group(1)
    rejected_step = int(m.group(2))

    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        logger.info("[R124] 退回: 管线 %s 不存在，忽略", round_name)
        return

    # 已完成/已归档/已取消/已卡死 → 忽略
    from .pipeline_context import PipelineStatus as PS
    if ctx.status in (PS.COMPLETED, "cancelled", "stopped", "stuck"):
        logger.info("[R124] 退回: %s 状态=%s，忽略", round_name, ctx.status)
        return

    # 提取退回原因：支持全角 —、半角 --、-
    reject_reason = ""
    for sep in ("—", "--", "-"):
        if sep in content:
            reject_reason = content.split(sep, 1)[1].strip()[:200]
            break
    if not reject_reason:
        reject_reason = content[:100]

    # 轮次级退回计数检查（第 4 次 stuck）
    reject_count = getattr(ctx, "reject_count", 0) + 1
    ctx.reject_count = reject_count
    if reject_count >= 4:
        ctx.status = "stuck"
        mgr.save()
        logger.info("[R124] %s 第 4 次退回，标记 stuck", round_name)
        await _notify_pm(
            ctx, rejected_step, "stuck",
            f"🔴 {round_name} Step {rejected_step} 被退回。管线已卡死"
            f"（累计退回 {reject_count} 次），需要人工介入。\n原因: {reject_reason}",
        )
        return

    # 确定回退起点 index：Step 1/2 → index 0，Step 3+ → index 2
    rollback_start = 1 if rejected_step <= 2 else 2

    # 重置 affected steps
    for i in range(rollback_start, len(ctx.steps)):
        ctx.steps[i]["status"] = "pending"
        ctx.steps[i]["output"] = None
        ctx.steps[i]["result_msg"] = ""
        ctx.steps[i].pop("reject_reason", None)

    # 记录退回原因到回退目标 step
    ctx.steps[rollback_start]["reject_reason"] = reject_reason

    # 回退管线 current_step（1-indexed）
    ctx.current_step = rollback_start + 1

    # 持久化 + 通知 PM
    mgr.save()
    await _notify_pm(
        ctx, rejected_step, "rejected",
        f"🔄 {round_name} Step {rejected_step} 被退回（累计 {reject_count}/3）\n"
        f"原因: {reject_reason}\n"
        f"管线已退回到 Step {rollback_start + 1}（编码环节），未自动派活。\n"
        f"请 PM 决定下一步：派活 Dev 重做 or ##advance 跳过。",
    )
    logger.info("[R124] 退回处理完成: %s Step %d → rollback_to Step %d, reason=%s",
                round_name, rejected_step, rollback_start + 1, reject_reason)
# ════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════
# R111: ## 命令 — 简洁可靠的自动派活入口
# ════════════════════════════════════════════════════════════════


def _build_name_to_ws_map() -> dict[str, str]:
    """从 persistence.get_api_keys() 构建 display_name → ws_agent_id 映射."""
    _name_to_ws: dict[str, str] = {}
    for _aid, _rec in persistence.get_api_keys().items():
        _dn = _rec.get("display_name", "")
        if _dn:
            _name_to_ws[_dn] = _aid
    return _name_to_ws


def _resolve_card_key_to_ws_id(card_key: str) -> str:
    """多策略解析 card key → WS 连接 ID。

    优先级:
    1. display_name → api_keys (persistence.get_api_keys())
    2. display_name → state._r72_users name 匹配
    3. _connections + _r72_users name 交叉匹配
    """
    card = ac_mod.get_agent_card(card_key)
    if not card:
        return ""
    display_name = card.get("display_name", "")

    # 策略 1: display_name → api_keys
    if display_name:
        name_to_ws = _build_name_to_ws_map()
        _id = name_to_ws.get(display_name, "")
        if _id and _id.startswith("ws_"):
            return _id

    # 策略 2: display_name → state._r72_users
    if display_name:
        for _aid, _rec in state._r72_users.items():
            if _rec.get("name", "") == display_name:
                return _aid

    # 策略 3: _connections 中 ws_xxx → _r72_users name 匹配
    if display_name:
        for _aid in list(_connections.keys()):
            if _aid.startswith("ws_"):
                _info = state._r72_users.get(_aid, {})
                if _info.get("name", "") == display_name:
                    return _aid

    return ""


def _build_rich_templates(round_name: str, references: dict = None, artifacts: dict = None) -> dict[str, str]:
    """返回 6 步富上下文模板组，引用 references（文档 URL）和 artifacts（前序步产出）."""
    ref = references or {}
    req_url = ref.get("requirements_url", "")
    wp_url = ref.get("work_plan_url", "")

    return {
        "step1": "",
        "step2": (
            f"📋 **{round_name} Step 2 — 技术方案**\n\n"
            + (f"##需求文档## {req_url}\n" if req_url else "")
            + (f"##工作计划## {wp_url}\n" if wp_url else "")
            + "\n请完成技术方案并推 dev，回复：已完成 ✅ {round} Step 2"
        ),
        "step3": (
            f"💻 **{round_name} Step 3 — 编码实现**\n\n"
            + (f"##需求文档## {req_url}\n" if req_url else "")
            + "##技术方案## {step2:tech_plan_url}\n"
            + "\n请完成编码并推 dev，回复：已完成 ✅ {round} Step 3"
        ),
        "step4": (
            f"👁 **{round_name} Step 4 — 代码审查**\n\n"
            + (f"##需求文档## {req_url}\n" if req_url else "")
            + "##技术方案## {step2:tech_plan_url}\n"
            + "\n请审查代码并回复审查报告，回复：已完成 ✅ {round} Step 4"
        ),
        "step5": (
            f"🧪 **{round_name} Step 5 — 测试验证**\n\n"
            + (f"##需求文档## {req_url}\n" if req_url else "")
            + "##测试范围## {step3:test_scope}\n"
            + "##分支## {step3:branch_name}\n"
            + "\n请进行测试验证，回复：已完成 ✅ {round} Step 5"
        ),
        "step6": (
            f"🚀 **{round_name} Step 6 — 合并部署归档**\n\n"
            + "##分支## {step5:branch}\n"
            + "##commit## {step5:commit_sha}\n"
            + "##测试结果## {step5:test_summary}\n"
            + "##测试报告## {step5:test_report_url}\n"
            + "\n请合并部署归档并推送 main，回复：已完成 ✅ {round} Step 6"
        ),
    }




async def _handle_hash_advance(round_name: str, kv: dict, agent_id: str, ws) -> bool:
    """处理 ##advance 命令：PM 手动推进管线到下一步。

    ##advance##R{N}##step=N
    仅 PM（PIPELINE_PM_AGENT_ID）可用。
    """
    # ═══ 权限校验：仅 PM 可用 ═══
    pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
    if pm_agent_id and agent_id != pm_agent_id:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": "❌ 无权限: ##advance 仅 PM 可用",
            "ts": time.time(),
        })
        return True

    step_str = kv.get("step", "")
    if not step_str.isdigit():
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": "❌ 参数错误: 缺少 `step=N` 参数",
            "ts": time.time(),
        })
        return True
    step_num = int(step_str)

    # 构造完成消息并尝试推进
    content = f"已完成 ✅ {round_name} Step {step_num}"
    ok, reason = _try_advance_pipeline(content, agent_id)
    if ok:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"✅ **{round_name} Step {step_num}** 已手动推进（PM 确认）",
            "ts": time.time(),
        })
    else:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"⚠️ 推进失败: {reason}",
            "ts": time.time(),
        })
    return True


# ═══ R124: 手动归档 ─────────────────────────────
async def _handle_hash_archive(round_name: str, agent_id: str, ws) -> bool:
    """处理 ##archive##R{N} — PM 手动归档管线。"""
    pm_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
    if pm_id and agent_id != pm_id:
        await _send(ws, {
            "type": "broadcast", "channel": f"_inbox:{agent_id}",
            "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
            "content": "❌ 无权限: ##archive 仅 PM 可用",
            "ts": time.time(),
        })
        return True
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        await _send(ws, {
            "type": "broadcast", "channel": f"_inbox:{agent_id}",
            "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"❌ {round_name} 管线不存在",
            "ts": time.time(),
        })
        return True
    await _archive_pipeline(round_name)
    await _send(ws, {
        "type": "broadcast", "channel": f"_inbox:{agent_id}",
        "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
        "content": f"📦 {round_name} 管线已手动归档",
        "ts": time.time(),
    })
    return True
# ════════════════════════════════════════════════════


# ═══ R124: 管线自动归档 ═══
async def _archive_pipeline(round_name: str) -> None:
    """归档已完成管线：从活跃上下文移除，追加到 pipeline_archive.json。"""
    from pathlib import Path
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        return
    now = time.time()
    archive_record = {
        "round_name": ctx.round_name,
        "status": "completed",
        "archived_at": now,
        "completed_at": getattr(ctx, "updated_at", now),
        "reject_count": getattr(ctx, "reject_count", 0),
        "steps": ctx.steps,
        "artifacts": getattr(ctx, "artifacts", {}),
        "references": getattr(ctx, "references", {}),
        "summary": {
            "total_steps": len(ctx.steps),
            "completed_steps": sum(
                1 for s in (ctx.steps or []) if s.get("status") == "done"
            ),
            "reject_count": getattr(ctx, "reject_count", 0),
            "total_duration_sec": int(
                now - getattr(ctx, "created_at", now)
            ) if getattr(ctx, "created_at", None) else 0,
        },
    }
    mgr._contexts.pop(round_name, None)
    mgr.save()
    archive_path = Path(config.DATA_DIR) / "pipeline_archive.json"
    records: list[dict] = []
    if archive_path.exists():
        try:
            records = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            records = []
    records.append(archive_record)
    MAX_ARCHIVE_TRIM = 50
    KEEP_ARCHIVE = 30
    if len(records) > MAX_ARCHIVE_TRIM:
        records = records[-KEEP_ARCHIVE:]
    try:
        archive_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[R124] 归档完成: %s → %s (%d 条归档)",
                    round_name, archive_path, len(records))
        await _notify_pm(ctx, len(ctx.steps), "archived",
                         f"📦 {round_name} 管线已完成并归档")
    except (OSError, PermissionError) as e:
        logger.warning("[R124] 归档写入失败: %s", e)


async def _handle_hash_start(round_name: str, kv: dict, agent_id: str, ws) -> bool:
    """处理 ##start 命令：创建 PipelineContext + 落盘 + 自动派活 Step 1."""
    mgr = _ensure_pipeline_manager()
    if mgr.exists(round_name):
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"❌ {round_name} 管线已存在，无法重复创建",
            "ts": time.time(),
        })
        return True

    # 1. 刷新角色映射
    try:
        _refresh_role_agent_map()
    except Exception:
        pass

    # 2. 构建 steps（从 DEFAULT_STEPS 填充 agent_id）
    from .pipeline_context import DEFAULT_STEPS, DEFAULT_STEP_ORDER
    from . import agent_card as _ac_mod

    role_map = mgr.get_global_role_map()
    if not role_map:
        role_map = dict(getattr(state, '_ROLE_AGENT_MAP', {}))
    name_to_ws = _build_name_to_ws_map()

    steps_list: list[dict] = []
    for sk in DEFAULT_STEP_ORDER:
        step_info = DEFAULT_STEPS[sk]
        agents = role_map.get(step_info.role, [])
        agent_card_name = ""
        agent_id_for_step = ""
        if agents:
            agent_id_for_step = agents[0]
            card = _ac_mod.get_agent_card(agents[0])
            agent_card_name = card.get("display_name", agents[0][:12]) if card else agents[0][:12]
            # 通过 display_name 桥接卡 key → WS 连接 ID
            if card:
                _real_id = name_to_ws.get(card.get("display_name", ""))
                if _real_id:
                    agent_id_for_step = _real_id
                else:
                    # ═══ R117 fix: card key → WS ID fallback ═══
                    _fallback = _resolve_card_key_to_ws_id(agents[0])
                    if _fallback:
                        agent_id_for_step = _fallback
                        logger.info("[R117] ##start fallback: %s → %s",
                                    agents[0], _fallback)

        steps_list.append({
            "name": sk,
            "step_key": sk,
            "role": step_info.role,
            "title": step_info.title,
            "status": "pending",
            "agent_id": agent_id_for_step,
            "agent_name": agent_card_name,
            "output": None,
            "result_msg": "",
        })

    # 3. 构建 references
    references: dict[str, str] = {}
    for ref_key in ("requirements_url", "work_plan_url"):
        if kv.get(ref_key):
            references[ref_key] = kv[ref_key]

    # 4. 构建 message_templates（R118: 富上下文模板）
    templates = _build_rich_templates(round_name, references, {})

    # 5. 创建 PipelineContext
    from pathlib import Path
    workspace_dir = Path(getattr(config, 'REPO_PATH', '/opt/data/ws-bridge'))
    task_dir = Path(config.DATA_DIR) / "pipeline_tasks" / round_name

    ctx = PipelineContext(
        round_name=round_name,
        task_kind=PipelineTaskKind.DEV,
        workspace_dir=workspace_dir,
        task_dir=task_dir,
        workspace_id="",
        pm_inbox_id=config.PIPELINE_PM_AGENT_ID,
        status=PipelineStatus.INIT,
        current_step=1,
        total_steps=len(DEFAULT_STEPS),
        steps=steps_list,
        references=references,
        message_templates=templates,
        round_title=kv.get("round_title", round_name),
        created_by=agent_id,
        created_at=time.time(),
    )

    # 6. 落盘
    mgr.set_context(round_name, ctx)
    await mgr.transition_to(round_name, PipelineStatus.RUNNING)

    # 7. 自动派活（R118: Step 1 自动确认，PM 发 ##start 表示需求已就绪）
    ctx.current_step = 2
    ctx.steps[0]["status"] = "done"
    ctx.steps[0]["result_msg"] = "需求已就绪（##start 创建时自动确认）"
    # ═══ R119 fix: 落盘 Step 1 自动确认状态，防止容器重启后丢失 ═══
    try:
        mgr.save()
    except Exception:
        pass
    await _auto_dispatch(ctx, 2)

    # 8. 回复发送者
    await _send(ws, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": f"✅ {round_name} 管线已启动，Step 1 已派活",
        "ts": time.time(),
    })
    logger.info("[R111] ##start: %s by %s", round_name, agent_id[:16])
    return True


async def _handle_hash_status(round_name: str, agent_id: str, ws) -> bool:
    """处理 ##status 命令：查询管线当前状态."""
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        # ═══ R124: 尝试从归档文件查找 ═══
        _archive_info = _find_archive(round_name)
        if _archive_info:
            await _send(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": (
                    f"📦 {round_name} 已归档\n"
                    f"状态: {_archive_info.get('status', 'completed')}\n"
                    f"归档时间: {_fmt_ts(_archive_info.get('archived_at', 0))}\n"
                    f"总步数: {_archive_info.get('summary', {}).get('total_steps', 0)}"
                    f" / 完成: {_archive_info.get('summary', {}).get('completed_steps', 0)}"
                ),
                "ts": time.time(),
            })
            return True
        # ════════════════════════════════════════════
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"❌ {round_name} 管线不存在",
            "ts": time.time(),
        })
        return True

    # 拼装状态文本
    step_lines = []
    status_icons = {
        "pending": "⬜",
        "active": "🟢",
        "done": "✅",
        "failed": "❌",
        "skipped": "⏭",
    }
    step_names = {
        "pm": "小谷",
        "arch": "小开",
        "dev": "爱泰",
        "review": "小周",
        "qa": "泰虾",
        "operations": "小爱",
    }

    for step in ctx.steps:
        step_key = step.get("step_key", step.get("name", "?"))
        step_num = step_key.replace("step", "")
        st = step.get("status", "pending")
        icon = status_icons.get(st, "⬜")
        role = step.get("role", "?")
        name = step_names.get(role, role)
        step_lines.append(f"  Step {step_num}: {icon} {name}")

    status_text = (
        f"📊 **{round_name} 管线状态**\n"
        f"  状态: {ctx.status.value}\n"
        f"  当前步: Step {ctx.current_step}\n"
        + "\n".join(step_lines)
    )

    await _send(ws, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": status_text,
        "ts": time.time(),
    })
    return True


async def _handle_hash_stop(round_name: str, agent_id: str, ws) -> bool:
    """处理 ##stop 命令：停止/取消管线."""
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"❌ {round_name} 管线不存在",
            "ts": time.time(),
        })
        return True

    await mgr.cancel(round_name)
    await _send(ws, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": f"🛑 {round_name} 管线已停止（CANCELLED）",
        "ts": time.time(),
    })
    logger.info("[R111] ##stop: %s by %s", round_name, agent_id[:16])
    return True


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


async def _sm_handle_pm_guard(ws, agent_id: str, msg: dict, matched) -> bool:
    """Rule 35: PM safety guard."""
    await _send(ws, {
        "type": "error",
        "error": "_inbox:server 仅接受 bot 消息，PM 请直接发 bot 收件箱.",
    })
    logger.warning("[Relay] 拒绝: PM %s 试图发消息到 _inbox:server", agent_id[:12])
    return True


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
    match=_sm.match_pm_guard,
    handle=_sm_handle_pm_guard,
    priority=35,
    name="PM安全守卫",
    protocol_ref="§7.4",
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

