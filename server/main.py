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

from . import agent_card as ac_mod  # R67: unified Agent Card interface
from . import auth, config, persistence
from . import state  # R100: shared state container
from . import command_utils  # R100: command routing utilities
from . import message_store as ms
from . import workspace as ws_mod
from .audit import AuditLogger
from . import task_store as ts
from . import timeout_tracker  # R63 Phase 1: Step countdown
from . import pipeline_sync as pps  # R65: Pipeline git sync
from .pipeline_context import PipelineContextManager, PipelineStatus, PipelineTaskKind, PipelineContext  # R77
from .command_utils import _refresh_role_agent_map, _broadcast_to_channel
_card_watcher = None  # R100: module-level for _ensure_card_watcher()
import shared.protocol as p

logger = logging.getLogger("ws-bridge")

_connections: dict[str, set] = {}
# P6: message send stats
state._send_stats: dict = {"total": 0, "total_latency": 0.0}
_audit_logger = AuditLogger(config.DATA_DIR)
def _ensure_pipeline_manager() -> PipelineContextManager:
    """惰性初始化 PipelineContextManager."""
    if state._pipeline_manager is None:
        state._pipeline_manager = PipelineContextManager(data_dir=config.DATA_DIR)
    return state._pipeline_manager
def get_connections() -> dict[str, set]:
    return _connections

def get_delivery_status(msg_id: str) -> dict[str, str]:
    return state._delivery_status.get(msg_id, {})
def _force_disconnect_revoked_agent(agent_id: str) -> None:
    """吊销 api_key 后强制断连 agent 的所有连接."""
    conns = list(_connections.get(agent_id, set()))
    for conn in conns:
        try:
            if hasattr(conn, "close"):
                asyncio.create_task(conn.close())
        except Exception:
            pass
    _connections.pop(agent_id, None)
async def _send(ws, data: dict) -> None:
    """Send JSON to a WebSocket (compatible with both websockets & aiohttp)."""
    if hasattr(ws, "send_json"):
        await ws.send_json(data)
    elif hasattr(ws, "send_str"):
        await ws.send_str(json.dumps(data))
    elif hasattr(ws, "send"):
        await ws.send(json.dumps(data))

def _build_online_list(users: dict) -> str:
    """Build a comma-separated online member list with admin annotation.
    Uses _connections (global) to determine who is online.
    R72 B: 也包含通过 api_key 注册的 agent（不在 approved_users 中）."""
    # Build a name map: approved_users first, then api_keys as fallback
    api_keys = persistence.get_api_keys() if hasattr(persistence, 'get_api_keys') else {}
    online_ids = set(_connections.keys())
    parts = []
    for aid in sorted(online_ids):
        u = users.get(aid, {})
        name = u.get("name", "")
        role = u.get("role", "")
        if not name:
            # R72: fallback to api_key display_name or agent card
            ak = api_keys.get(aid, {})
            name = ak.get("display_name", "")
            from . import agent_card as ac_mod
            if not name:
                card = ac_mod.get_all_cards().get(aid, {})
                name = card.get("display_name", "")
        if not name:
            name = aid[:12]
        prefix = ""
        if role == "admin":
            prefix = "管理员 "
        parts.append(f"{prefix}{name}")
    return "、".join(parts) if parts else "无"

async def handle_auth(ws, msg: dict) -> str | None:
    """R72: api_key 认证.不再支持 agent_id + app_id + pairing_code."""
    api_key = msg.get(p.FIELD_API_KEY, "").strip()
    if not api_key:
        await _send(ws, {"type": "auth_error", "error": "Missing api_key"})
        return None

    agent_id = auth.validate_api_key(api_key)
    if not agent_id:
        await _send(ws, {"type": "auth_error", "error": "Invalid api_key"})
        return None

    display_name = persistence.get_api_keys().get(agent_id, {}).get("display_name", agent_id)
    await _send(ws, {
        "type": "auth_ok",
        "agent_id": agent_id,
        "display_name": display_name,
    })
    logger.info("Agent %s authenticated (api_key)", agent_id[:20])

    # ── R72 B: 认证成功后同步更新 Agent Card 的在线状态 ──
    _update_agent_online_status(agent_id)

    # ── R72 C: 将 R72 agent 注册到 users 字典，确保大厅路由可查 ──
    state._r72_users[agent_id] = {"name": display_name}

    return agent_id


def _update_agent_online_status(agent_id: str) -> None:
    """R72 B: 认证/注册后同步更新 Agent Card 状态为 online 并刷新 last_online.
    确保 card 状态与 WebSocket 连接状态一致，防止 mark_stale_offline 后无法恢复."""
    import server.agent_card as ac_mod
    cards = ac_mod.get_all_cards()
    card = cards.get(agent_id)
    if card:
        card["status"] = "online"
        card["last_online"] = time.time()
        ac_mod.update_card(agent_id, card)


# ── R86 A1: display_name duplicate check ──────────────────────────


def _find_agent_by_name(keys: dict, display_name: str) -> str | None:
    """在 _api_keys 中按 display_name 查找已存在的 agent_id.返回 agent_id 或 None."""
    for agent_id, record in keys.items():
        if record.get("display_name") == display_name:
            return agent_id
    return None


async def handle_register(ws, msg: dict) -> str | None:
    """R72: 新 bot 注册.返回 agent_id + api_key，同一连接立即生效."""
    display_name = msg.get("display_name", "").strip()
    if not display_name:
        await _send(ws, {"type": "auth_error", "error": "Missing display_name"})
        return None

    # ── R86 A1: display_name 重复检测 ──
    keys = persistence.get_api_keys()
    existing = _find_agent_by_name(keys, display_name)
    if existing:
        await _send(ws, {
            "type": "auth_error",
            "error": f"'{display_name}' 已存在，请使用 auth 或换一个 display_name.如遗忘 api_key 请联系管理员重置.",
            "existing_agent_id": existing,
        })
        return None

    # 1. 生成 ws-bridge 自有 agent_id
    agent_id = auth.generate_agent_id()
    # 2. 生成 api_key
    api_key = auth.create_api_key(agent_id)
    # 3. 持久化到 _api_keys.json
    keys[agent_id] = {
        "api_key": api_key,
        "display_name": display_name,
        "description": msg.get("description", ""),
        "created_at": time.time(),
        "expires_at": None,
        "status": "active",
        "level": 2,  # ── R99: 新注册默认 L2 ──
    }
    persistence.set_api_keys(keys)
    persistence.save_api_keys(config.DATA_DIR)

    # 4. 注册 inbox channel (R82: removed persistent channel binding — inbox is implicit)
    # 5. 返回凭证（同一连接继续使用）
    await _send(ws, {
        "type": p.MSG_REGISTER_OK,
        "agent_id": agent_id,
        "api_key": api_key,
        "display_name": display_name,
        "created_at": time.time(),
    })
    logger.info("Agent registered: %s (%s)", agent_id[:20], display_name)

    # ── 同步更新 Agent Card 状态（如存在历史卡片） ──
    _update_agent_online_status(agent_id)

    # ── R72 C: 注册后写入 state._r72_users，确保大厅路由可查 ──
    state._r72_users[agent_id] = {"name": display_name}

    return agent_id


# ── R79: Registration helpers ─────────────────────────────────────────


def _build_registration_welcome(agent_id: str, display_name: str,
                                pipeline_roles: list[str]) -> str:
    """构建注册欢迎消息文本."""
    roles_str = ", ".join(pipeline_roles) if pipeline_roles else "未声明"
    return (
        f"🎉 欢迎加入 ws-bridge！\n\n"
        f"你已成功注册，Agent ID: {agent_id[:16]}...\n"
        f"当前角色: {roles_str}\n\n"
        f"📋 下一事项：\n"
        f"  1. 配置 config.yaml（bot_name / mention_keyword）\n"
        f"  2. 阅读 WORKSPACE_RULES.md 了解平台规则\n"
        f"  3. 在频道中 @管理员 确认配置完毕\n\n"
        f"💡 帮助：发送 !help 查看可用命令"
    )


def _build_admin_notification(agent_id: str, display_name: str,
                              pipeline_roles: list[str]) -> str:
    """构建管理员通知消息文本."""
    roles_str = ", ".join(pipeline_roles) if pipeline_roles else "未声明"
    return (
        f"📢 新 bot 注册通知\n\n"
        f"Agent ID: {agent_id[:16]}...\n"
        f"显示名称: {display_name}\n"
        f"角色: {roles_str}\n\n"
        f"操作:\n"
        f"  !agent_card set {agent_id} roles...   修改角色"
    )


def _should_notify_admins(display_name: str) -> bool:
    """R82: 简化 — 管理员注册不发通知."""
    # R82: BROADCAST_ADMINS removed; always notify for non-admin registrations
    return True


async def handle_agent_card_register(ws, agent_id: str, msg: dict) -> dict:
    """R72: Bot 自主注册 Agent Card.返回确认消息.

    R79: 追加欢迎消息 + 管理员通知 + 频道切换 + 大厅广播.
    """
    result = ac_mod.register_from_agent(agent_id, msg)

    # ── R79: 注册后行为（全部 try/except，不阻断注册流程）──
    try:
        card = ac_mod.get_card(agent_id) or {}
        display_name = card.get("display_name", "") or agent_id[:12]
        pipeline_roles = card.get("pipeline_roles", [])

        # A: 发送欢迎消息到 bot 连接
        try:
            welcome = _build_registration_welcome(agent_id, display_name, pipeline_roles)
            target_ch = p.LOBBY
            await _send(ws, {
                "type": p.MSG_BROADCAST, "channel": target_ch,
                "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
                "content": welcome, "ts": time.time(),
            })
            logger.info("R79 A: Welcome sent to %s", agent_id[:20])
        except Exception as e:
            logger.warning("R79 A: Welcome failed for %s: %s", agent_id[:20], e)

        # B: 管理员通知（非管理员注册时）
        try:
            if _should_notify_admins(display_name):
                notify = _build_admin_notification(agent_id, display_name, pipeline_roles)
                await _broadcast_to_channel(p.ADMIN_CHANNEL, {
                    "type": p.MSG_BROADCAST, "channel": p.ADMIN_CHANNEL,
                    "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
                    "content": notify, "ts": time.time(),
                })
                logger.info("R79 B: Admin notified for %s", agent_id[:20])
        except Exception as e:
            logger.warning("R79 B: Admin notification failed: %s", e)

        # C: R82 removed — active channel management no longer needed (bot uses inbox)

        # D: 大厅广播（默认关闭）
        if REGISTRATION_BROADCAST_ENABLED:
            try:
                bcast = f"🆕 新伙伴加入：{display_name}\n角色：{', '.join(pipeline_roles) if pipeline_roles else '未声明'}"
                await _broadcast_to_channel(p.LOBBY, {
                    "type": p.MSG_BROADCAST, "channel": p.LOBBY,
                    "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
                    "content": bcast, "ts": time.time(),
                })
            except Exception as e:
                logger.warning("R79 D: Lobby broadcast failed: %s", e)

    except Exception as e:
        logger.warning("R79: Registration post-process error (non-fatal): %s", e)

    return result


async def _push_offline(ws, since_ts: float) -> None:
    """Push missed messages to a reconnecting agent."""
    try:
        offline = ms.get_messages_since(since_ts, config.DATA_DIR, limit=500)
    except Exception:
        logger.warning("Offline catchup query failed (maybe first run)")
        return
    if offline:
        await _send(ws, {
            "type": "offline_messages",
            "messages": offline,
            "count": len(offline),
        })
        logger.info("Pushed %d offline msgs to reconnecting agent", len(offline))


async def _flush_offline_push(agent_id: str) -> None:
    """R11 P1.2: Wait 3s for agent to come online, then flush (or discard)."""
    await asyncio.sleep(3)
    conns = _connections.get(agent_id, set())
    pending = state._offline_push_queue.pop(agent_id, [])
    state._offline_timers.pop(agent_id, None)
    if conns and pending:
        for conn in conns:
            for item in pending:
                try:
                    if hasattr(conn, "send_str"):
                        await conn.send_str(json.dumps(item))
                    elif hasattr(conn, "send"):
                        await conn.send(json.dumps(item))
                except Exception:
                    pass
        logger.info("Offline push: %d msgs delivered to %s after 3s", len(pending), agent_id[:12])
    elif pending:
        logger.info("Offline push: %d msgs for %s expired (still offline after 3s)", len(pending), agent_id[:12])


# ── R35: Admin command infrastructure ────────────────────────────


def _admin_msg(content: str) -> dict:
    """Build a response message for the _admin channel."""
    return {
        "type": "broadcast",
        "channel": p.ADMIN_CHANNEL,
        "from_name": "系统",
        "content": content,
        "ts": time.time(),
    }


async def _persist_admin_response(ws, sender_id: str, from_name: str, content: str) -> None:
    """Send admin response + persist to message store + chat log for web viewer."""
    msg = _admin_msg(content)
    await _send(ws, msg)
    try:
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent=sender_id, from_name=from_name,
            content=content, ts=time.time(),
            data_dir=config.DATA_DIR, channel=p.ADMIN_CHANNEL,
        )
    except Exception:
        pass

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


def _get_agents_by_role(role: str,
                        workspace_members: list[str] = None) -> list[str]:
    """Find agents by pipeline role.

    Priority chain:
    1. PipelineContextManager.get_role_agents() (R78 new path)
    2. state._ROLE_AGENT_MAP (DEPRECATED fallback)
    3. Fallback: auth.get_users().role (legacy compat)
    4. Optional: filter by workspace_members

    Args:
        role: Pipeline role name (arch/dev/review/qa/admin).
        workspace_members: Optional list of member IDs to filter by.

    Returns:
        List of matching agent IDs.
    """
    # R78 A4: 优先走 Manager 查询
    try:
        mgr = _ensure_pipeline_manager()
        agents = mgr.get_role_agents(role)
    except Exception:
        agents = []
    if not agents:
        agents = state._ROLE_AGENT_MAP.get(role, [])
    if not agents:
        # Fallback to auth roles
        users = auth.get_users()
        agents = [aid for aid, u in users.items()
                  if u.get("role", "member") == role]
    if workspace_members:
        agents = [a for a in agents if a in workspace_members]
    return agents


async def _handle_rollcall_ack(sender_id: str, content: str,
                                ws_id: str) -> None:
    """Handle rollcall response -> auto-register/update Agent Card.

    R63 Phase 3: When agent replies to rollcall, register or update card.
    R67: Unified — always go through ac_mod.register_agent.
    """

def _ensure_watchdog() -> None:
    """Lazily start the background watchdog loop on first call."""
    state._watchdog_task
    if state._watchdog_started:
        return
    state._watchdog_task = asyncio.create_task(_watchdog_loop())
    state._watchdog_started = True
    logger.info("R43 watchdog started (scan=%ds, realert=%ds)",
                state.WATCHDOG_SCAN_INTERVAL, state.WATCHDOG_REALERT_INTERVAL)


# ── R65 A2: Git sync lifecycle ──────────────────────────────────


def _ensure_git_scan() -> None:
    """在 handler 初始化时调用一次.启动 git sync 定时循环."""
    if not config.ENABLE_GIT_SYNC:
        logger.info("[R65] Git sync 已禁用（ENABLE_GIT_SYNC=false）")
        return
    if state._GIT_SYNC_TASK is None or state._GIT_SYNC_TASK.done():
        state._GIT_SYNC_TASK = asyncio.create_task(_start_git_sync_loop())
        logger.info("[R65] Git sync watchdog 已启动（interval=%ds）", config.GIT_SYNC_INTERVAL)


async def _start_git_sync_loop():
    """独立的 git 同步定时循环，每 GIT_SYNC_INTERVAL 秒执行一次."""
    while True:
        await asyncio.sleep(config.GIT_SYNC_INTERVAL)
        try:
            await _pipeline_git_sync_scan()
        except Exception as e:
            logger.warning("[R65] git_sync_scan error: %s", e)


async def _pipeline_git_sync_scan():
    """遍历所有活跃管线，检查 git 同步."""
    for pid, pstate in list(state._PIPELINE_STATE.items()):
        if not pstate.get("active"):
            continue
        if not config.ENABLE_GIT_SYNC:
            continue

        # 从 state._PIPELINE_CONFIG 读取管线专属配置
        pconfig = state._PIPELINE_CONFIG.get(pid, {})
        sync_config = {
            "branch": pconfig.get("git_sync_branch", config.GIT_SYNC_BRANCH),
            "repo_path": pconfig.get("repo_path", config.REPO_PATH),
            "last_sha": pstate.get("last_output_sha", ""),
            "fallback_enabled": config.GIT_SYNC_FALLBACK,
        }

        syncer = pps.PipelineGitSync(pid, sync_config)
        result = await syncer.sync()
        if result and result.get("synced"):
            await _auto_advance_pipeline(pid, result)
            pstate["_last_git_sync_ts"] = time.time()
# ── R65 A2: End ──


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

    # ── R67 C2: Mark stale agents offline ──────────────────────
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


# ── R63 Phase 2: Timeout escalation ─────────────────────────────


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
# ── R63 Phase 2: End ──


# ── R63 Phase 4: ACK state machine ──────────────────────────────

ACK_TIMEOUT_SEC = 30  # Seconds from SENT to FAILED


async def _ack_timeout_task(ack_key: str) -> None:
    """30-second ACK timeout detection.

    If no ACK received within timeout, marks state as ack_timeout
    (not FAILED) — waits for git sync to detect new output instead.

    R65 C1: ACK 超时不标记 FAILED，改为 ack_timeout 等待标记.
    只有当 git sync + timeout_tracker 都无产出时才标记真正 FAILED.
    """
    await asyncio.sleep(ACK_TIMEOUT_SEC)
    state = state._step_ack_states.get(ack_key, {})
    if state.get("state") in ("SENT", "DELIVERED"):
        # ── R65 C1: ACK 超时 → 标记 ack_timeout（不标 FAILED）──
        state["state"] = "ack_timeout"
        logger.info("[R65 C1] ACK 超时: %s (agent=%s) — 等待 git 产出，不标 FAILED",
                    ack_key, state.get("agent_id", "?"))
        # 仅发送信息性消息，不触发 escalation
        await _send_ack_timeout_info(ack_key, state)


async def _send_ack_timeout_info(ack_key: str, state: dict) -> str:
    """ACK 超时信息通知（非告警）."""
    parts = ack_key.split("/", 1)
    round_name = parts[0] if len(parts) > 0 else "?"
    step_name = parts[1] if len(parts) > 1 else "?"
    agent_id = state.get("agent_id", "")
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


async def _trigger_ack_escalation(ack_key: str, state: dict) -> str:
    """ACK timeout → PM escalation alert.

    Args:
        ack_key: Key in state._step_ack_states.
        state: Current state dict.

    Returns:
        Alert message string.
    """
    parts = ack_key.split("/", 1)
    round_name = parts[0] if len(parts) > 0 else "?"
    step_name = parts[1] if len(parts) > 1 else "?"
    agent_id = state.get("agent_id", "")
    display_name = _get_agent_display(agent_id) if agent_id else "未知"

    alert = (
        f"🕐 [ACK 超时] {round_name} {step_name}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🎯 目标: {display_name}\n"
        f"📨 状态: {state.get('state', 'UNKNOWN')}\n"
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


def _update_step_ack_state(sender_id: str, content: str) -> None:
    """Update state._step_ack_states when bot responds in a workspace.

    R63 Phase 4: Bot ACK detection — any message from a target agent
    is treated as ACK. If content contains ack keywords, mark IN_PROGRESS.

    Args:
        sender_id: Agent ID who sent the message.
        content: Message content (checked for ack keywords).
    """

    ack_keywords = ["收到", "好的", "在", "到", "接", "OK", "ok", "开始", "done"]
    is_ack = any(kw in content for kw in ack_keywords)

    for ack_key, ack_state in state._step_ack_states.items():
        if ack_state.get("agent_id") == sender_id and ack_state["state"] in ("SENT", "DELIVERED"):
            old_state = ack_state["state"]
            if is_ack:
                ack_state["state"] = "IN_PROGRESS"
            else:
                ack_state["state"] = "ACKNOWLEDGED"
            logger.info("ACK updated: %s %s → %s (from %s)",
                        ack_key, old_state, ack_state["state"], sender_id[:12])
            # R78 B3: 双写 Manager
            try:
                mgr = _ensure_pipeline_manager()
                round_name = ack_key.split("/")[0]
                step = ack_key.split("/")[1] if "/" in ack_key else ack_key
                asyncio.ensure_future(mgr.set_ack_state(round_name, step, dict(ack_state)))
            except Exception:
                pass


def _format_ack_status(ack_key: str) -> str:
    """Format ACK state for pipeline_status display.

    Args:
        ack_key: Key in state._step_ack_states.

    Returns:
        Formatted status string, or empty string if not tracked.
    """
    state = state._step_ack_states.get(ack_key)
    if not state:
        return ""
    s = state["state"]
    elapsed = time.time() - state.get("sent_at", time.time())
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


# ── R63 Phase 4: End ──


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
        await _cmd_rollcall_role("系统", {
            "_positional": [role],
            "context": round_name + " " + step_name + " timeout rerollcall",
        })
    except Exception:
        pass


async def _send_clear_alert(round_name: str, step_name: str, output_ref: str) -> None:
    """Send recovery notification to _admin channel."""
    step_config = _get_step_config(round_name)
    step_info = step_config.get(step_name, {})
    step_display = step_info.get("name", step_name)

    msg = (
        f"✅ {round_name} {step_display}（{step_name}）已恢复 — "
        f"已完成（{output_ref}）"
    )

    _persist_broadcast(p.ADMIN_CHANNEL, "系统", msg)
    logger.info("R43 watchdog clear: %s/%s", round_name, step_name)




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


# ── R38: Task notify broadcast ─────────────────────────────────────


async def _broadcast_task_notify(
        task: dict,
        transition: str,
        ) -> None:
        """Broadcast MSG_TASK_NOTIFY to workspace members of the task's context.

        transition is a short description e.g. 'SUBMITTED → WORKING'.
        Also pushes to web viewer WS clients for live progress updates.
        """
        context_id = task.get("context_id", "")
        if not context_id:
            return
        workspace = ws_mod.get_workspace(context_id)
        if not workspace:
            return
        payload = json.dumps({
            "type": p.MSG_TASK_NOTIFY,
            "task_id": task["id"],
            "name": task["name"],
            "state": task["state"],
            "transition": transition,
            "assigned_role": task.get("assigned_role", ""),
            "context_id": context_id,
            "ts": time.time(),
        })
        targets = workspace.members
        for agent_id in targets:
            for conn in list(_connections.get(agent_id, set())):
                try:
                    if hasattr(conn, "send_str"):
                        await conn.send_str(payload)
                    elif hasattr(conn, "send"):
                        await conn.send(payload)
                except Exception:
                    pass

        # R41 C: Write task_notify to admin channel
        try:
            content_str = f"📊 {context_id} {task['name']}: {transition}"
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=content_str, ts=time.time(),
                data_dir=config.DATA_DIR, channel=p.ADMIN_CHANNEL,
            )
        except Exception:
            pass
        logger.info("task_notify '%s' → %s (%s)", task["name"], context_id, transition)


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
    _restore_pipeline_timers()
    # ── R65 A2: Start git sync loop ──
    _ensure_git_scan()
    # ── R67 B1: Ensure agent cards loaded + watcher running ──
    _ensure_agent_cards_loaded()
    _ensure_card_watcher()

    content = msg.get("content", "")
    channel = msg.get(p.FIELD_CHANNEL, "")

    # R82 A1: Inbox fast path — skip all filters and routing
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
        # _inbox:server → query command
        if channel == f"{p.INBOX_CHANNEL_PREFIX}server":
            await _handle_server_query(ws, sender_id, content)
            return
        # Otherwise → route directly to target agent's inbox (existing intercept handles it)
        # Fall through to normal inbox handling below

    # R23: unregistered bots → registration channel only (cannot specify channel)
    if not auth.is_approved(sender_id):
        channel = p.REGISTRATION_CHANNEL

    # R12 P1.1: Rate limiting check (before anything else)
    users = auth.get_users()
    sender_role = users.get(sender_id, {}).get("role", "member")
    allowed, retry_after = _check_rate_limit(sender_id, channel, sender_role)
    if not allowed:
        await _send(ws, {
            "type": p.MSG_RATE_LIMITED,
            "reason": f"消息频率过高，{state.RATE_LIMIT_SECONDS}秒内最多发{state.RATE_LIMIT_WINDOW}条",
            p.FIELD_RETRY_AFTER: retry_after,
        })
        logger.info("Rate-limited %s in '%s' (retry after %ds)", sender_id[:12], channel, retry_after)
        return

    # R35: ! commands skip nonsense/duplicate filtering
    if not content.startswith("!"):
        if _is_nonsense(content, sender_id, channel):
            logger.info("Nonsense msg filtered from %s in '%s': %s", sender_id[:12], channel, content[:40])
            return
        if _is_duplicate(content, sender_id):
            logger.info("Duplicate msg filtered from %s: %s", sender_id[:12], content[:40])
            return

    # Skip system/noise
    if any(content.startswith(p) for p in state._SILENT_PREFIXES) or content.strip("🤐") == "":
        logger.info("Silent msg filtered: %s", content[:60])
        return

    users = auth.get_users()
    # R72: R72 agents live in state._r72_users, not in users
    sender_name = users.get(sender_id, {}).get("name") or \
                  state._r72_users.get(sender_id, {}).get("name", sender_id)
    sender_role = users.get(sender_id, {}).get("role", "member")
    admin_ids = {aid for aid, u in users.items() if u.get("role") == "admin"}

    # ── R57 A: Rollcall ACK hook — any message from a waited-on agent fires event ──
    if sender_id in state._r57_rollcall_events:
        event = state._r57_rollcall_events.get(sender_id)
        if event and not event.is_set():
            event.set()
            logger.info("R57 rollcall ACK from %s (%s)", sender_id[:12], sender_name)

    # ── R63 Phase 3: Rollcall auto-register ──
    # If in a workspace, try to register/update agent card on response
    if channel.startswith(p.WORKSPACE_ID_PREFIX) or channel.startswith("ws:"):
        try:
            await _handle_rollcall_ack(sender_id, content, channel)
        except Exception:
            pass

    # ── R63 Phase 4: Bot ACK detection for step assignment ──
    _update_step_ack_state(sender_id, content)

    # ── R26 P0: 📢 broadcast admin-only check ──
    if content.startswith("📢") and sender_role != "admin":
        await _send(ws, {"type": "error", "error": "「📢」广播仅限管理员使用"})
        return

    # R11 P2.1: Parse mentions from content (used in both lobby and workspace)
    mention_names = set()
    for m in re.finditer(r'@(\S+)', content):
        name = m.group(1)
        if any(users.get(aid, {}).get("name") == name for aid in users):
            mention_names.add(name)
    is_task = bool(mention_names) or content.startswith("!")

    # ── R49: Universal ! command routing (works in any channel) ──
    if content.startswith("!"):
        # R100: 延迟导入避免循环依赖
        from .commands import _ADMIN_COMMANDS as _cmds
        cmd_name, params = command_utils._parse_command(content)
        if not cmd_name or cmd_name not in _cmds:
            available = ", ".join(f"!{k}" for k in sorted(_cmds))
            await command_utils._send_cmd_response(ws, sender_id, "系统", f"❌ 未知命令.可用命令：{available}", channel)
            return
        cmd = _cmds[cmd_name]
        allowed, reason = command_utils._check_command_permission(sender_id, cmd_name, cmd, params)
        if not allowed:
            await command_utils._send_cmd_response(ws, sender_id, "系统", f"❌ {reason}", channel)
            return
        try:
            result = await cmd["handler"](sender_id, params)
            command_utils._log_audit(sender_id, cmd_name, params, "success", result)
            await command_utils._send_cmd_response(ws, sender_id, "系统", result, channel)
        except Exception as e:
            err_msg = f"❌ 执行失败: {e}"
            command_utils._log_audit(sender_id, cmd_name, params, "error", err_msg)
            logger.error("Admin cmd !%s failed: %s", cmd_name, e)
            await _send_cmd_response(ws, sender_id, "系统", err_msg, channel)
        return

    # ── R35: _admin channel intercept ──
    if channel == p.ADMIN_CHANNEL:
        # Persist the admin's command message for web viewer
        msg_id = str(uuid.uuid4())
        try:
            ms.save_message(
                msg_id=msg_id, msg_type="broadcast",
                from_agent=sender_id, from_name=sender_name,
                content=content, ts=time.time(),
                data_dir=config.DATA_DIR, channel=p.ADMIN_CHANNEL,
            )
        except Exception:
            pass
        # R49: ! commands now handled by universal routing above.
        # _admin channel still persists admin messages for logging.
        # Non-! messages in _admin are silently logged (admin channel only supports ! commands).
        if not content.startswith("!"):
            resp = "ℹ️ 管理频道仅支持 ! 命令"
            await _persist_admin_response(ws, sender_id, "系统", resp)
        return

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

    # ── Channel resolution (fall back to lobby for unknown channels) ──
    resolved_workspace = None
    if channel != p.LOBBY:
        # R23: registration channel → skip workspace resolution
        if channel == p.REGISTRATION_CHANNEL:
            pass
        else:
            resolved_workspace = ws_mod.get_workspace(channel)
            if not resolved_workspace:
                # Unknown channel from Hermes built-in ws_bridge adapter
                # (hardcoded chat_id="ws_bridge_group"). Try to auto-route
                # to the sender's active workspace if they have exactly one.
                agent_workspaces = ws_mod.get_workspaces_for_agent(sender_id)
                active = [w for w in agent_workspaces if w.state == ws_mod.WorkspaceState.ACTIVE]
                if len(active) == 1:
                    resolved_workspace = active[0]
                    channel = resolved_workspace.id
                    logger.info(
                        "Auto-routed %s to workspace '%s'",
                        sender_id[:12], channel,
                    )
                else:
                    logger.info("Unknown channel '%s' — falling back to lobby", channel)
                    channel = p.LOBBY

    # ── R6: Broadcast permission check ──
    allowed, reason = _can_broadcast(sender_id, channel, msg)
    if not allowed:
        await _send(ws, {"type": "error", "error": f"权限不足：{reason}"})
        return

        # ── R42 D: Lobby pause intercept ──
    if state._LOBBY_PAUSED and channel == p.LOBBY:
        # If sender has an active workspace, auto-route there
        agent_workspaces = ws_mod.get_workspaces_for_agent(sender_id)
        active = [w for w in agent_workspaces if w.state == ws_mod.WorkspaceState.ACTIVE]
        if active:
            channel = active[0].id
            resolved_workspace = active[0]
            logger.info("R42 lobby-pause: routed %s to workspace '%s'", sender_id[:12], channel)
        else:
            await _send(ws, {
                "type": "error",
                "error": f"🔒 管线 {state._LOBBY_PAUSED_ROUND} 进行中，大厅已暂停接收消息.请在工作区中发言.",
            })
            return

    # ── Channel-scoped routing ──────────────────────────────────────
    if channel != p.LOBBY and resolved_workspace:
            if resolved_workspace.state == ws_mod.WorkspaceState.ARCHIVED:
                await _send(ws, {"type": "error", "error": f"Workspace '{channel}' is archived, read-only"})
                return

            # Update activity
            ws_mod.touch(channel)

            # Only members + admin
            member_ids = resolved_workspace.members
            targets = [
                (aid, conns) for aid, conns in _connections.items()
                if (aid in member_ids or aid in admin_ids) and aid != sender_id
            ]
            if not targets:
                logger.info("Workspace '%s': no online members, msg logged only", channel)
                return

            broadcast = json.dumps({
                "type": "broadcast",
                "channel": channel,
                # New unified field names
                "from_name": sender_name,
                "agent_id": sender_id,
                # Legacy field names (Hermes built-in ws_bridge adapter reads these)
                "from": sender_name,
                "from_agent": sender_id,
                "content": content,
                "ts": time.time(),
                # R11 P2.1: Mentions metadata
                p.FIELD_MENTIONS: list(mention_names) if mention_names else None,
                p.FIELD_IS_TASK: is_task or None,
            })

            # Persist with channel
            msg_id = msg.get("id", "") or str(uuid.uuid4())
            try:
                ms.save_message(
                    msg_id=msg_id,
                    msg_type="broadcast",
                    from_agent=sender_id,
                    from_name=sender_name,
                    content=content,
                    ts=time.time(),
                    data_dir=config.DATA_DIR,
                    channel=channel,
                )
            except Exception:
                pass

            sent = 0
            target_names = []
            # R11 P1.1: Track delivery
            state._delivery_status[msg_id] = {}
            for agent_id, conns in targets:
                target_names.append(users.get(agent_id, {}).get("name", agent_id[:12]))
                for conn in list(conns):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(broadcast)
                        elif hasattr(conn, "send"):
                            await conn.send(broadcast)
                        sent += 1
                    except Exception:
                        pass
                # R11 P1.1: Mark delivery
                state._delivery_status[msg_id][agent_id] = p.DELIVERY_SENT

            # R34 B: Send ACK with delivery stats (workspace path)
            if msg_id:
                _online = set(_connections.keys())
                sent_list = []
                offline_list = []
                for aid in member_ids:
                    if aid == sender_id:
                        continue
                    name = users.get(aid, {}).get("name", aid[:12])
                    if aid in _online:
                        sent_list.append(name)
                    else:
                        offline_list.append(name)
                await _send(ws, {
                    "type": "ack",
                    "id": msg_id,
                    "delivery": {
                        "total": len(member_ids) - 1,  # exclude sender
                        "sent": len(sent_list),
                        "offline": len(offline_list),
                        "targets": sent_list,
                        "offline_targets": offline_list,
                    }
                })

            # R11 P1.1: Send delivery_status to admin senders in workspace
            if sender_role == "admin" and msg_id:
                online = set(_connections.keys())
                status_report = {}
                for aid in member_ids:
                    if aid == sender_id:
                        continue
                    name = users.get(aid, {}).get("name", aid[:12])
                    status_report[name] = "sent" if aid in online else "offline"
                await _send(ws, {
                    "type": p.MSG_DELIVERY_STATUS,
                    "id": msg_id,
                    "status": status_report,
                    "total": len(status_report),
                    "delivered": sum(1 for s in status_report.values() if s == "sent"),
                })

            logger.info("Channel [%s] %s→%s: %s", channel, sender_name, ",".join(target_names), content[:60])
            return
    # ── R24: Lobby routing with prefix classification ─────────────────
    if channel == p.LOBBY:
        msg_type, target_names = _classify_lobby_message(content)

        if msg_type == 'plain':
            await _send(ws, {
                "type": "error",
                "error": "大厅消息需要明确类型.请使用 📢公告 / 📋点名 / 🆘求助 / @用户名.\n普通讨论请在工作室频道进行.",
            })
            logger.info("Lobby plain msg blocked from %s: %s", sender_id[:12], content[:40])
            return

        # Lobby-specific rate limit
        allowed, retry_after = _check_lobby_rate_limit(sender_id, sender_role)
        if not allowed:
            await _send(ws, {
                "type": p.MSG_RATE_LIMITED,
                "reason": f"大厅消息频率过高，请{retry_after}秒后再试",
                p.FIELD_RETRY_AFTER: retry_after,
            })
            return

        # Route by type
        targets = []
        if msg_type == 'announce':
            # 📢 → broadcast to admin/web viewers only (R82: bot connections excluded)
            if sender_role != "admin":
                await _send(ws, {
                    "type": "error",
                    "error": "📢 公告仅管理员可用.请使用 📋点名 / 🆘求助 / @用户名 发送大厅消息.",
                })
                return
            targets = [(aid, conns) for aid, conns in _connections.items() if aid != sender_id]

        elif msg_type == 'help':
            # 🆘 → P4 admin only
            targets = [(aid, conns) for aid, conns in _connections.items() if aid in admin_ids]

        elif msg_type == 'checkin':
            # 📋 → route to @mentioned targets
            targets = []
            for name in target_names:
                for aid, conns in _connections.items():
                    u = users.get(aid, {}) or state._r72_users.get(aid, {})
                    if u.get("name") == name and aid != sender_id:
                        targets.append((aid, conns))
                        break
            if not targets:
                await _send(ws, {"type": "error", "error": f"未找到在线目标: {', '.join(target_names)}"})
                return

        elif msg_type == 'mention':
            # @name → route to target + admin
            targets = []
            for name in target_names:
                for aid, conns in _connections.items():
                    u = users.get(aid, {}) or state._r72_users.get(aid, {})
                    if u.get("name") == name and aid != sender_id:
                        targets.append((aid, conns))
                        break
            # Always include admins
            for aid, conns in _connections.items():
                if aid in admin_ids and aid != sender_id:
                    if not any(t[0] == aid for t in targets):
                        targets.append((aid, conns))

        if not targets:
            logger.info("Lobby msg from %s has no online targets", sender_id[:12])
            return

    # ── R24: Registration channel → admin relay fallback ────────────
    if channel == p.REGISTRATION_CHANNEL:
        targets = [(aid, conns) for aid, conns in _connections.items() if aid in admin_ids]
        if not targets:
            logger.info("Reg channel: no admin online, msg from %s logged only", sender_id[:12])
            return

    # Use dual field names (new unified + legacy compat)
    broadcast = json.dumps({
        "type": "broadcast",
        "channel": channel,
        # New unified field names
        "from_name": sender_name,
        "agent_id": sender_id,
        # Legacy field names (Hermes built-in ws_bridge adapter reads these)
        "from": sender_name,
        "from_agent": sender_id,
        "content": content,
        "ts": time.time(),
        # R11 P2.1: Mentions metadata
        p.FIELD_MENTIONS: list(mention_names) if mention_names else None,
        p.FIELD_IS_TASK: is_task or None,
    })
    # P6: timing
    _t0 = time.time()
    msg_id = msg.get("id", "") or str(uuid.uuid4())
    # Persist before broadcasting
    try:
        ms.save_message(
            msg_id=msg_id,
            msg_type="broadcast",
            from_agent=sender_id,
            from_name=sender_name,
            content=content,
            ts=time.time(),
            data_dir=config.DATA_DIR,
        )
    except Exception:
        pass
    sent = 0
    target_names = []
    # R11 P1.1: Track delivery
    state._delivery_status[msg_id] = {}
    for agent_id, conns in targets:
        target_names.append(users.get(agent_id, {}).get("name", agent_id[:12]))
        delivered = False
        for conn in list(conns):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(broadcast)
                elif hasattr(conn, "send"):
                    await conn.send(broadcast)
                sent += 1
                delivered = True
            except Exception:
                pass
        # R11 P1.1: Mark delivery status
        state._delivery_status[msg_id][agent_id] = p.DELIVERY_SENT if delivered else p.DELIVERY_SENT
    # R11 P1.2: Offline push — agents not in targets get queued (if admin message)
    if sender_role == "admin":
        all_agents = {aid for aid in users}
        online_agents = {aid for aid in _connections}
        offline_agents = all_agents - online_agents
        # R41 B: Persist offline-queued messages to message store
        if offline_agents:
            try:
                ms.save_message(
                    msg_id=msg_id, msg_type="broadcast",
                    from_agent=sender_id, from_name=sender_name,
                    content=content, ts=time.time(),
                    data_dir=config.DATA_DIR, channel=channel,
                )
            except Exception:
                pass
        for offline_id in offline_agents:
            state._offline_push_queue.setdefault(offline_id, []).append({
                "type": "broadcast",
                "id": msg_id,
                "channel": channel,
                "from_name": sender_name,
                "agent_id": sender_id,
                "from": sender_name,
                "from_agent": sender_id,
                "content": content,
                "ts": time.time(),
            })
            if offline_id not in state._offline_timers:
                state._offline_timers[offline_id] = asyncio.create_task(
                    _flush_offline_push(offline_id)
                )

    # R34 B: Send ACK with delivery stats (lobby path)
    if msg_id:
        _online = set(_connections.keys())
        # targets = routed online recipients (already built above, but may include sender)
        lobby_sent_list = [users.get(aid, {}).get("name", aid[:12]) for aid, _ in targets if aid != sender_id]
        # Offline: all users (except sender) minus online = the ones not reachable
        lobby_all_non_sender = {aid for aid in users if aid != sender_id}
        lobby_offline_ids = lobby_all_non_sender - _online
        lobby_offline_list = [users.get(aid, {}).get("name", aid[:12]) for aid in lobby_offline_ids]
        await _send(ws, {
            "type": "ack",
            "id": msg_id,
            "delivery": {
                "total": len(lobby_all_non_sender),
                "sent": len(lobby_sent_list),
                "offline": len(lobby_offline_list),
                "targets": lobby_sent_list,
                "offline_targets": lobby_offline_list,
            }
        })
    # R11 P1.1: Send delivery_status to admin senders
    if sender_role == "admin" and msg_id:
        online = set(_connections.keys())
        status_report = {}
        for aid in {u for u in users}:
            name = users.get(aid, {}).get("name", aid[:12])
            if aid == sender_id:
                continue
            if aid in online:
                status_report[name] = "sent"
            else:
                status_report[name] = "offline"
        await _send(ws, {
            "type": p.MSG_DELIVERY_STATUS,
            "id": msg_id,
            "status": status_report,
            "total": len(status_report),
            "delivered": sum(1 for s in status_report.values() if s == "sent"),
        })

    # P6: record latency
    _latency = time.time() - _t0
    state._send_stats["total"] += 1
    state._send_stats["total_latency"] += _latency
    if sender_role == "admin":
        logger.info("Admin-relay %s➔%s: %s", sender_name, ",".join(target_names), content[:60])
    else:
        logger.info("Member %s→admin: %s", sender_name, content[:60])

    # ── R29: 📋 roll-call — send online member list to admin
    # R33-1: Also allow workspace admin_ids (e.g. 泰虾) to call roll-call
    is_ws_admin = (resolved_workspace is not None and
                   (sender_id in resolved_workspace.admin_ids or
                    sender_id == resolved_workspace.owner_id))
    if (sender_role == "admin" or is_ws_admin) and content.startswith("📋"):
        online_list = _build_online_list(users)
        await _send(ws, {
            "type": "broadcast",
            "channel": p.LOBBY,
            "from_name": "系统",
            "from": "系统",
            "agent_id": "",
            "from_agent": "",
            "content": f"📋 当前在线：{online_list}",
            "ts": time.time(),
        })
        logger.info("Admin %s roll-call — online list sent (%s)", sender_id[:12], online_list)

        # R82: removed MSG_SET_ACTIVE_CHANNEL broadcast



# ── R82: _inbox:server query routing ─────────────────────


async def _handle_server_query(ws, sender_id: str, content: str) -> None:
    """Handle ! commands sent to _inbox:server channel.
    Executes query commands and replies to sender's inbox.
    """
    if not content.startswith("!"):
        return  # non-command silently ignored

    sender_name = auth.get_agent_name(sender_id, sender_id[:12])
    reply_ch = persistence.get_inbox_channel(sender_id)
    if not reply_ch:
        logger.warning("R82: Cannot reply to %s — no inbox channel", sender_id[:12])
        return

    parts = content.strip().split(maxsplit=1)
    cmd = parts[0].lower() if parts else ""
    params_str = parts[1] if len(parts) > 1 else ""

    reply_text = ""

    if cmd == "!agent_card":
        sub_parts = params_str.split(maxsplit=1)
        sub_cmd = sub_parts[0] if sub_parts else ""
        if sub_cmd == "list":
            cards = ac_mod.get_all_cards()
            lines = [f"📇 Agent Cards ({len(cards)}):"]
            for aid, card in sorted(cards.items()):
                name = card.get("display_name", aid[:12])
                roles = ", ".join(card.get("pipeline_roles", []))
                status = card.get("status", "offline")
                roles_str = f" 角色: {roles}" if roles else ""
                lines.append(f"  {name} ({aid[:12]}...) [{status}] {roles_str}")
            reply_text = "\n".join(lines)
        else:
            reply_text = f"❌ 未知子命令: !agent_card {sub_cmd}"

    elif cmd == "!pipeline_status":
        round_name = params_str.strip()
        if round_name:
            mgr = _ensure_pipeline_manager()
            ctx = mgr.get(round_name)
            if ctx:
                reply_text = _format_pipeline_context(ctx)
            else:
                reply_text = f"❌ 管线 {round_name} 不存在"
        else:
            mgr = _ensure_pipeline_manager()
            active = mgr.get_all_active()
            if active:
                lines = ["📋 活跃管线:"]
                for ctx in sorted(active, key=lambda c: c.round_name):
                    lines.append(f"  {ctx.round_name} [{ctx.task_kind.value}] {ctx.status.value} step={ctx.current_step}/{ctx.total_steps}")
                reply_text = "\n".join(lines)
            else:
                reply_text = "📋 当前无活跃管线"

    elif cmd == "!list_workspaces":
        ws_list = ws_mod.get_all_workspaces()
        if ws_list:
            lines = [f"📋 工作区 ({len(ws_list)}):"]
            for ws_item in ws_list:
                state = ws_item.state.value
                lines.append(f"  {ws_item.id} '{ws_item.name}' [{state}] members={len(ws_item.members)}")
            reply_text = "\n".join(lines)
        else:
            reply_text = "📋 当前无工作区"

    elif cmd == "!my_id":
        reply_text = f"🆔 你的 agent_id: {sender_id}"

    elif cmd == "!help":
        reply_text = "📖 可用查询: !agent_card list, !pipeline_status [R], !list_workspaces, !my_id"

    else:
        reply_text = f"❌ 未知命令: {cmd}\n可用查询: !agent_card list, !pipeline_status [R], !list_workspaces, !my_id"

    if not reply_text:
        return

    # Reply to sender's inbox
    try:
        import time as _time
        await _broadcast_to_channel(reply_ch, {
            "type": "broadcast", "channel": reply_ch,
            "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
            "content": reply_text, "ts": _time.time(),
        })
        logger.info("R82: Replied to %s via %s for '%s'", sender_id[:12], reply_ch, content[:40])
    except Exception as e:
        logger.warning("R82: Failed to reply to %s: %s", sender_id[:12], e)


# ── R11 P2.2: Membership change notification ────────────────────
# ── R11 P2.2: Membership change notification ────────────────────


async def _notify_member_changed(ws_id: str, member_id: str, event: str) -> None:
    """Notify all workspace members of membership change (joined/removed)."""
    resolved = ws_mod.get_workspace(ws_id)
    if not resolved:
        return
    member_name = _get_agent_display(member_id)
    payload = json.dumps({
        "type": p.MSG_MEMBER_CHANGED,
        p.FIELD_WORKSPACE_ID: ws_id,
        p.FIELD_MEMBER_EVENT: event,
        p.FIELD_TARGET_AGENT_ID: member_id,
        "member_name": member_name,
        "ts": time.time(),
    })
    targets = resolved.members | {member_id} if event == "joined" else resolved.members
    for agent_id in targets:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload)
                elif hasattr(conn, "send"):
                    await conn.send(payload)
            except Exception:
                pass


# ── R24: Lobby-specific rate limiter ─────────────────────────────────


def _check_lobby_rate_limit(agent_id: str, role: str) -> tuple[bool, float]:
    """Check lobby-specific rate limit. P4 unlimited, P3=5/60s, P1/P2=2/60s."""
    if role == "admin":
        return True, 0
    window = state.LOBBY_RATE_WINDOW_P3 if role == "workspace_admin" else state.LOBBY_RATE_WINDOW_P1P2
    now = time.time()
    window_start = now - state.LOBBY_RATE_SECONDS
    timestamps = state._lobby_rate_limits.setdefault(agent_id, [])
    timestamps[:] = [t for t in timestamps if t > window_start]
    if len(timestamps) >= window:
        retry_after = int(timestamps[0] + state.LOBBY_RATE_SECONDS - now) + 1
        return False, retry_after
    timestamps.append(now)
    return True, 0


# ── R24: Lobby message classification ───────────────────────────────


def _classify_lobby_message(content: str) -> tuple[str, list[str]]:
    """Classify lobby message by prefix.
    Returns (type, extracted_names).
    Types: 'announce', 'checkin', 'help', 'mention', 'plain'
    """
    content = content.strip()
    # R45 B (F-4): Strip [R{N}测试] test tags before prefix check
    content = re.sub(r'^\[R\d+测试\]\s*', '', content).strip()
    if content.startswith(state.PREFIX_ANNOUNCE):
        return 'announce', []
    if content.startswith(state.PREFIX_CHECKIN):
        names = [m.group(1) for m in re.finditer(r'@(\S+)', content)]
        return 'checkin', names
    if content.startswith(state.PREFIX_HELP):
        return 'help', []
    names = [m.group(1) for m in re.finditer(r'@(\S+)', content)]
    if names:
        return 'mention', names
    return 'plain', []


# ── R12 P1.1: Rate limiting ──────────────────────────────────────────


def _check_rate_limit(agent_id: str, channel: str, role: str) -> tuple[bool, float]:
    """Check if agent is rate-limited in channel. Returns (allowed, retry_after)."""
    if role == "admin":
        return True, 0
    now = time.time()
    window_start = now - state.RATE_LIMIT_SECONDS
    agent_limits = state._rate_limits.setdefault(agent_id, {})
    timestamps = agent_limits.setdefault(channel, [])
    timestamps[:] = [t for t in timestamps if t > window_start]
    if len(timestamps) >= state.RATE_LIMIT_WINDOW:
        retry_after = int(timestamps[0] + state.RATE_LIMIT_SECONDS - now) + 1
        return False, retry_after
    timestamps.append(now)
    return True, 0


# ── R12 P1.2: Nonsense message patterns ────────────────────────────


state._NONSENSE_PATTERNS = [
    re.compile(r'^[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F'
               r'\U0001F680-\U0001F6FF\u2600-\u27BF\u2B50\u2702-\u27B0'
               r'\uFE0F✅❌⚠️🟢🟡🔴⬜⬛➕➖🔄🤐👂🤫🦐🧐🦾📋'
               r'\s\*]+$'),
    re.compile(r'^\*\s*静默待命.*\*[\s🤫]*$'),
    re.compile(r'^\*\s*弹药上膛.*\*[\s🦐🚀]*$'),
    re.compile(r'^到[\s✅]*$'),
]


def _is_nonsense(content: str, agent_id: str, channel: str) -> bool:
    """Check if message is nonsense (pure emoji, heartbeat, etc.)."""
    stripped = content.strip()
    if not stripped:
        return True
    for pattern in state._NONSENSE_PATTERNS:
        if pattern.match(stripped):
            return True
    if '@' in stripped or 'http' in stripped.lower():
        return False
    text_chars = sum(1 for c in stripped if c.isascii() and c.isalnum())
    if text_chars >= 5:
        return False
    has_cjk = any('\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf' for c in stripped)
    if has_cjk:
        return False
    if text_chars < 3 and not has_cjk:
        return True
    return False


def _is_duplicate(content: str, agent_id: str) -> bool:
    """Check if agent is sending the same content within 30 seconds."""
    entry = state._last_message.get(agent_id)
    now = time.time()
    if entry and entry["content"] == content and (now - entry["ts"]) < 30:
        return True
    state._last_message[agent_id] = {"content": content, "ts": now}
    return False


# ── R12 P0.3: Task ack timeout ────────────────────────────────────


async def _task_ack_timeout(admin_ws, task_id: str, target_name: str) -> None:
    """30s timeout for task ack. Notify admin if no response."""
    await asyncio.sleep(30)
    state._task_ack_timers.pop(task_id, None)
    try:
        await _send(admin_ws, {
            "type": "delivery_status",
            "task_id": task_id,
            "status": "timeout",
            "message": f"⚠️ {target_name} 30 秒内未确认任务，建议检查",
        })
    except Exception:
        pass
    logger.warning("Task %s ack timeout for %s", task_id, target_name)


# ── R53: Channel switch verification ────────────────────────────


async def _notify_rollcall_complete(ws_id: str) -> None:
    """Verify all members have switched channels and notify host (R53)."""
    ws_obj = ws_mod.get_workspace(ws_id)
    if not ws_obj:
        return
    unconfirmed = []
    for member_id in ws_obj.members:
        ch = ""
        if ch != ws_id:
            unconfirmed.append(member_id)

    users = auth.get_users()
    payload = json.dumps({
        "type": "broadcast",
        "channel": ws_id,
        "from_name": "系统",
        "from": "系统",
        "agent_id": "",
        "from_agent": "",
        "ts": time.time(),
    })
    if not unconfirmed:
        content = "✅ 点名完成：全员活跃频道已锁定."
        logger.info("R53: Roll-call complete for '%s' — all members confirmed", ws_id)
    else:
        names = [users.get(uid, {}).get("name", uid[:12]) for uid in unconfirmed]
        content = f"⚠️ 点名完成（部分）：以下成员未确认频道切换：{', '.join(names)}"
        logger.info("R53: Roll-call complete for '%s' — %d unconfirmed: %s", ws_id, len(unconfirmed), names)

    payload = json.dumps({**json.loads(payload), "content": content})
    for admin_id in ws_obj.admin_ids:
        for conn in list(_connections.get(admin_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload)
                elif hasattr(conn, "send"):
                    await conn.send(payload)
            except Exception:
                pass
    # R53: Cleanup ACK state
    state._channel_ack_state.pop(ws_id, None)


# ── R53: Channel switch ACK timeout (30s, replaces R37 3min) ───

async def _channel_ack_timeout(ws_id: str) -> None:
    """30s timeout for channel switch ACK.
    On timeout: marks unresponsive members, calls _notify_rollcall_complete().
    """
    await asyncio.sleep(30)
    state = state._channel_ack_state.get(ws_id)
    if not state:
        return
    timedout = state["online_members"] - set(state["acked_members"].keys())
    if timedout:
        users = auth.get_users()
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
    for ws_id, state in state._channel_ack_state.items():
        if state.get("ack_task_id") == ack_task_id:
            return ws_id
    return None


# ── R12 P0.4: Workspace ready broadcast ────────────────────────────


async def _broadcast_workspace_ready(ws_id: str, name: str, owner_name: str, members: set[str]) -> None:
    """Broadcast workspace_ready to all members."""
    from . import workspace as ws_mod
    payload = ws_mod.build_workspace_ready(ws_id, name, owner_name, members)
    payload_json = json.dumps(payload)
    for agent_id in members:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload_json)
                elif hasattr(conn, "send"):
                    await conn.send(payload_json)
            except Exception:
                pass
    logger.info("workspace_ready broadcast to %d members of '%s'", len(members), ws_id)


# ── R12 P2: Stage completed broadcast ──────────────────────────────


async def _broadcast_stage_completed(
    ws_id: str,
    completed_by: str,
    stage: str,
    output: str,
    next_holder: str,
    next_stage: str,
) -> None:
    """Notify next holder that a stage has been completed."""
    workspace = ws_mod.get_workspace(ws_id)
    if not workspace:
        return
    users = auth.get_users()
    next_id = None
    for aid, u in users.items():
        if u.get("name") == next_holder:
            next_id = aid
            break
    payload = json.dumps({
        "type": p.MSG_STAGE_COMPLETED,
        "workspace_id": ws_id,
        "completed_by": completed_by,
        "stage": stage,
        "output": output,
        "next_holder": next_holder,
        "next_stage": next_stage,
        "ts": time.time(),
    })
    targets = [next_id] if next_id else workspace.members
    for agent_id in targets:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload)
                elif hasattr(conn, "send"):
                    await conn.send(payload)
            except Exception:
                pass
    logger.info("stage_completed '%s' → %s (next: %s)", stage, next_holder, next_stage)


# ── R6: Broadcast Permission Check ──────────────────────────────


def _can_broadcast(agent_id: str, channel: str, msg: dict) -> tuple[bool, str]:
    """Check if agent can broadcast in the given channel.
    Returns (allowed: bool, reason: str).
    """
    # L4 global admin: any channel
    if auth.is_global_admin(agent_id):
        return True, ""

    # R35: _admin channel — only admins (P3/P4) can send
    # R44 F-12: PM pipeline_start bypass — allow broadcast, command-level check still applies
    if channel == p.ADMIN_CHANNEL:
        if auth.is_global_admin(agent_id):
            return True, ""
        if _is_any_workspace_admin(agent_id):
            return True, ""
        # R44: member broadcast allowed; _check_command_permission enforces pipeline_start only
        return True, ""

    # R23: registration channel → allow (admin-relay handles routing)
    if channel == p.REGISTRATION_CHANNEL:
        return True, ""

    # Lobby: members can reply (routing already limits to admin-only)
    if channel == p.LOBBY:
        return True, ""

    # Workspace: must be a member
    members = ws_mod.get_workspace_members(channel)
    if agent_id not in members:
        return False, "您不是该工作区成员"

    # R10: token ring permission check
    reply_to = msg.get(p.FIELD_TOKEN_REPLY_TO)
    allowed, reason = ws_mod.can_send_in_token_mode(channel, agent_id, reply_to)
    if not allowed:
        return False, reason

    return True, ""


# ── R87: _inbox:server 中继转发 ─────────────────────────────


def _is_valid_agent_id(aid: str) -> bool:
    """粗校验：格式 must be ws_xxx."""
    return bool(aid and aid.startswith("ws_") and len(aid) > 10)


async def _send_to_agent(target_agent_id: str, payload: dict) -> int:
    """定向发送 payload 给指定 agent 的所有 WS 连接。不广播。同时持久化到 DB。"""
    payload_json = json.dumps(payload)
    sent = 0
    for conn in list(_connections.get(target_agent_id, set())):
        try:
            if hasattr(conn, "send_str"):
                await conn.send_str(payload_json)
            elif hasattr(conn, "send"):
                await conn.send(payload_json)
            sent += 1
        except Exception:
            pass
    # 同时持久化到 DB
    try:
        ms.save_message(
            msg_id=str(uuid.uuid4()),
            msg_type="broadcast",
            from_agent=state.SYSTEM_AGENT_ID,
            from_name="系统",
            content=payload.get("content", ""),
            ts=time.time(),
            data_dir=config.DATA_DIR,
            channel=payload.get("channel", ""),
        )
    except Exception:
        pass
    return sent


# ── R106: Pipeline step auto-advance on completion message ─────────


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
            asyncio.ensure_future(mgr.advance_step(round_name))
            logger.info(
                "[R106] %s Step %d → %d (auto-advance from completion)",
                round_name, old_step, old_step + 1,
            )
            # ── R107: 自动派活下一步（受 AUTO_DISPATCH_ENABLED 控制）──
            next_step = old_step + 1
            if next_step <= ctx.total_steps:
                asyncio.ensure_future(_auto_dispatch(ctx, next_step))
            else:
                # 最后一步已完成，标记管线 completed
                asyncio.ensure_future(mgr.transition_to(round_name, PipelineStatus.COMPLETED))
                logger.info("[R107] %s 全管线已完成 ✅", round_name)
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


# ── R107: 消息模板渲染 ──────────────────────────────────


def _render_template(template: str, ctx: PipelineContext, step_num: int) -> str:
    """用 Pipeline Context 数据渲染模板字符串。

    变量来源优先级（高→低）:
    1. ctx.artifacts 中各 step 的产出 KV
    2. ctx.references 中的文档 URL
    3. ctx 基本信息 (round_name, round_title)
    """
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
    return template


def _get_step_agent_name(ctx: PipelineContext, step_num: int) -> str:
    """辅助函数：获取指定 step 的 agent 名称。"""
    step_key = f"step{step_num}"
    info = next((s for s in ctx.steps if s.get("name") == step_key), None)
    if info:
        return info.get("agent_name", info.get("agent_id", "?"))
    return "?"


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
        (s for s in ctx.steps if s.get("name") == next_step_key), None,
    )
    if not next_step_info or not next_step_info.get("agent_id"):
        logger.warning(
            "[R107] 管线 %s step%d 无 agent_id，跳过自动派活",
            ctx.round_name, step_num,
        )
        return False

    target_agent_id = next_step_info["agent_id"]
    content = _render_template(next_template, ctx, step_num)

    payload = {
        "type": "message",
        "channel": "_inbox:server",
        "content": content,
        "from_name": "小谷",
        "agent_id": "ws_f26e585f6479",
        "to_agent": target_agent_id,
        "id": f"auto-{ctx.round_name}-step{step_num}-{int(time.time() * 1000)}",
        "ts": time.time(),
    }

    sent = await _send_to_agent(target_agent_id, payload)
    return sent > 0


async def _handle_server_relay(ws, agent_id: str, msg: dict) -> bool:
    """R87: 处理发往 _inbox:server 的 bot 回复中继.

    Args:
        ws: WebSocket 连接
        agent_id: 发送消息的 bot 的 agent_id（已认证）
        msg: 消息 dict（必须含 channel/content 字段）

    Returns:
        True  — 消息已由中继处理（调用方应 continue，不继续路由）
        False — 不是 _inbox:server 消息（调用方继续正常路由）
    """
    channel = msg.get("channel", "")
    content = (msg.get("content") or "").strip()

    # ── R96: 回路测试拦截 ──
    if content.startswith("test ✅"):
        from_name = msg.get("from_name", "?")
        logger.info(
            "🔄 Loopback test from %s (%s)", from_name, agent_id[:16]
        )
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
    # ═══════════════════════════════════════════

    # 非中继消息 → 走正常路由
    if channel != state.SERVER_INBOX_CHANNEL:
        return False

    # ── 获取发送者信息 ──
    sender_name = state._r72_users.get(agent_id, {}).get("name", agent_id[:12])
    pm_agent_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID

    # ═══ R102: to_agent 派活路由 ═══
    # 支持顶层 to_agent 字段 (ws_client.send_message(to_agent=...))
    # 也兼容 JSON 内嵌 (json.dumps({"to_agent":..., "content":...}) 作为 content)
    to_agent = (msg.get("to_agent") or "").strip()
    if not to_agent:
        # 回退: 尝试从内容 JSON 中解析
        text = msg.get("content", "").strip()
        if text.startswith("{"):
            try:
                inner = json.loads(text)
                to_agent = (inner.get("to_agent") or "").strip()
            except json.JSONDecodeError:
                pass
    if to_agent:
        # 校验: 必须是合法 agent_id 格式
        if not _is_valid_agent_id(to_agent):
            logger.warning("[Dispatch] 拒绝: 非法 to_agent=%s", to_agent)
            return True
        # 隐藏发件人，构造转发 payload
        relay_payload = {
            "type": "broadcast",
            "channel": f"_inbox:{to_agent}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": msg.get("content", "").strip(),
            "ts": time.time(),
        }
        await _send_to_agent(to_agent, relay_payload)
        logger.info("[Dispatch] %s → %s: %s...",
                     agent_id[:12], to_agent[:16],
                     (msg.get("content") or "")[:60])
        return True
    # ═══════════════════════════════════════════

    # ═══ 安全守卫: PM 误发 _inbox:server ═══
    # 排除带 to_agent 的派活消息（已在上面拦截）
    if pm_agent_id and agent_id == pm_agent_id:
        await _send(ws, {
            "type": "error",
            "error": "_inbox:server 仅接受 bot 消息，PM 请直接发 bot 收件箱.",
        })
        logger.warning("[Relay] 拒绝: PM %s 试图发消息到 _inbox:server", agent_id[:12])
        return True

    # ═══ 规则 1: 收到 ✅ / ACK ✅ → 转发 PM（进度通知）═══
    if content.startswith("收到 ✅") or content.startswith("ACK ✅"):
        if pm_agent_id:
            await _send_to_agent(pm_agent_id, {
                    "type": "broadcast",
                    "channel": f"_inbox:{pm_agent_id}",
                    "from_name": "系统",
                    "from_agent": state.SYSTEM_AGENT_ID,
                    "content": f"📬 {sender_name} 已接活:\n{content}",
                    "ts": time.time(),
                },
            )
        logger.info("[Relay] ACK: %s → PM", sender_name)
        return True

    # ═══ 规则 2: 已完成 ✅ / ✅ 完成 → 转发PM + 自动确认bot（同时触发）═══
    if content.startswith("已完成 ✅") or content.startswith("✅ 完成"):
        # ⑤ 转发给 PM
        if pm_agent_id:
            await _send_to_agent(pm_agent_id, {
                    "type": "broadcast",
                    "channel": f"_inbox:{pm_agent_id}",
                    "from_name": "系统",
                    "from_agent": state.SYSTEM_AGENT_ID,
                    "content": f"✅ {sender_name} 任务完成:\n{content}",
                    "ts": time.time(),
                },
            )
        # ⑥ 自动确认给 bot（发到 bot 的 inbox，不走 _inbox:server）
        await _send_to_agent(agent_id, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": "✅ 确认，已收到你的完成通知.本轮任务完成.",
                "ts": time.time(),
            },
        )
        logger.info("[Relay] 完成: %s → PM + 自动确认", sender_name)
        # ═══ R106: 自动推进管线 step ═══
        _try_advance_pipeline(content, agent_id)
        return True

    # ═══ 规则 3: 退回 🔄 ═══
    if content.startswith("退回 🔄"):
        if pm_agent_id:
            await _send_to_agent(pm_agent_id, {
                    "type": "broadcast",
                    "channel": f"_inbox:{pm_agent_id}",
                    "from_name": "系统",
                    "from_agent": state.SYSTEM_AGENT_ID,
                    "content": f"🔄 {sender_name} 退回:\n{content}",
                    "ts": time.time(),
                },
            )
        # 自动确认给 bot
        await _send_to_agent(agent_id, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": "🔄 已记录退回.",
                "ts": time.time(),
            },
        )
        logger.info("[Relay] 退回: %s → PM + 自动确认", sender_name)
        return True

    # ═══ 规则 4: 失败 ❌ ═══
    if content.startswith("失败 ❌"):
        if pm_agent_id:
            await _send_to_agent(pm_agent_id, {
                    "type": "broadcast",
                    "channel": f"_inbox:{pm_agent_id}",
                    "from_name": "系统",
                    "from_agent": state.SYSTEM_AGENT_ID,
                    "content": f"⚠️ {sender_name} 失败:\n{content}",
                    "ts": time.time(),
                },
            )
        # 自动确认给 bot
        await _send_to_agent(agent_id, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": "⚠️ 已记录失败.",
                "ts": time.time(),
            },
        )
        logger.info("[Relay] 失败: %s → PM + 自动确认", sender_name)
        return True

    # ═══ 规则 0: ! 命令 → 透传到 normal routing（兼容 R82 _handle_server_query）═══
    if content.startswith("!"):
        logger.info("[Relay] 透传: %s 发送 ! 命令到 _inbox:server", sender_name)
        return False

    # ═══ 规则 5: 无匹配 → 入库留痕 ═══
    # 入库留痕（不转发，不回复）
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
        pass  # 入库失败不阻塞主流程
    logger.info("[Relay] 沉默: %s 内容=%s...", sender_name, content[:60])
    return True


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
                # ═══ R87: _inbox:server 中继拦截 ═══
                if await _handle_server_relay(ws, agent_id, msg):
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

            elif msg_type == p.MSG_WORKSPACE_CREATE and agent_id:
                # Bot requests creating a workspace → route to admin(s) for approval
                ws_name = msg.get("name", "").strip()
                if not ws_name:
                    await _send(ws, {"type": "error", "error": "Missing workspace name"})
                    continue
                ws_id = f"{p.WORKSPACE_ID_PREFIX}{agent_id[:8]}-{ws_name[:20]}"
                _users = auth.get_users()
                _sender_name = _users.get(agent_id, {}).get("name") or \
                               state._r72_users.get(agent_id, {}).get("name", agent_id)
                _admin_ids = {aid for aid, u in _users.items() if u.get("role") == "admin"}
                create_payload = json.dumps({
                    "type": "broadcast",
                    "channel": p.LOBBY,
                    "content": f"@{agent_id} requests workspace: {ws_name}",
                    "from_name": _sender_name,
                    "agent_id": agent_id,
                    "ts": time.time(),
                    "_workspace_request": {
                        "id": ws_id,
                        "name": ws_name,
                        "requester_id": agent_id,
                    },
                })
                # Send to admin(s)
                for admin_aid in _admin_ids:
                    for conn in list(_connections.get(admin_aid, set())):
                        try:
                            if hasattr(conn, "send_str"):
                                await conn.send_str(create_payload)
                            elif hasattr(conn, "send"):
                                await conn.send(create_payload)
                        except Exception:
                            pass

            elif msg_type == p.MSG_WORKSPACE_CREATE_APPROVED and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    ws_id = msg.get("id", "").strip()
                    ws_name = msg.get("name", "").strip()
                    owner_id = msg.get("owner_id", "").strip()
                    owner_name = msg.get("owner_name", "").strip()
                    if ws_id and owner_id:
                        result = ws_mod.create_workspace(ws_id, ws_name or ws_id, owner_id, owner_name)
                        if result:
                            # R82: removed auto-bind active channel
                            await _send(ws, {"type": "ok", "workspace_id": ws_id})
                            logger.info("Workspace '%s' created by admin — owner %s channel set to '%s'",
                                         ws_id, owner_id[:20], ws_id)
                            # R12 P0.4: Send workspace_ready notification
                            asyncio.create_task(
                                _broadcast_workspace_ready(ws_id, ws_name or ws_id, owner_name or owner_id, result.members)
                            )
                        else:
                            await _send(ws, {"type": "error", "error": f"Failed to create workspace '{ws_id}' (owner may have too many active)"})

            elif msg_type == p.MSG_WORKSPACE_CLOSE and agent_id:
                ws_id = msg.get("workspace_id", "").strip()
                if not ws_id:
                    await _send(ws, {"type": "error", "error": "Missing workspace_id"})
                    continue
                if ws_mod.start_closing(ws_id):
                    await _send(ws, {"type": "ok", "workspace_id": ws_id, "message": f"Workspace '{ws_id}' closing initiated"})
                    # Notify members
                    asyncio.create_task(_broadcast_workspace_closing(ws_id))
                else:
                    await _send(ws, {"type": "error", "error": f"Failed to close workspace '{ws_id}' (not found or not active)"})

            elif msg_type == p.MSG_WORKSPACE_ADD_MEMBER and agent_id:
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                member_id = msg.get(p.FIELD_MEMBER_ID, "").strip()
                if ws_id and member_id:
                    resolved_workspace = ws_mod.get_workspace(ws_id)
                    if resolved_workspace and resolved_workspace.state == ws_mod.WorkspaceState.ACTIVE:
                        if auth.can_manage_workspace(ws_id, agent_id):
                            if ws_mod.add_member(ws_id, member_id):
                                # R82: removed auto-set active channel

                                await _send(ws, {"type": "ok", "workspace_id": ws_id, "member_id": member_id})
                                logger.info("Member %s added to workspace '%s'", member_id, ws_id)
                                # R11 P2.2: Notify workspace members of membership change
                                asyncio.create_task(_notify_member_changed(ws_id, member_id, "joined"))
                            else:
                                await _send(ws, {"type": "error", "error": "Failed to add member"})
                        else:
                            await _send(ws, {"type": "error", "error": "Permission denied"})
                    else:
                        await _send(ws, {"type": "error", "error": "Workspace not found or not active"})
                else:
                    await _send(ws, {"type": "error", "error": "Missing workspace_id or member_id"})

            elif msg_type == p.MSG_WORKSPACE_REMOVE_MEMBER and agent_id:
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                member_id = msg.get(p.FIELD_MEMBER_ID, "").strip()
                if ws_id and member_id:
                    resolved_workspace = ws_mod.get_workspace(ws_id)
                    if resolved_workspace and resolved_workspace.state == ws_mod.WorkspaceState.ACTIVE:
                        if auth.can_manage_workspace(ws_id, agent_id):
                            if ws_mod.remove_member(ws_id, member_id):
                                await _send(ws, {"type": "ok", "workspace_id": ws_id, "member_id": member_id})
                                logger.info("Member %s removed from workspace '%s'", member_id, ws_id)
                                # R11 P2.2: Notify workspace members of membership change
                                asyncio.create_task(_notify_member_changed(ws_id, member_id, "removed"))
                            else:
                                await _send(ws, {"type": "error", "error": "Failed to remove member"})
                        else:
                            await _send(ws, {"type": "error", "error": "Permission denied"})
                    else:
                        await _send(ws, {"type": "error", "error": "Workspace not found or not active"})
                else:
                    await _send(ws, {"type": "error", "error": "Missing workspace_id or member_id"})

            elif msg_type == p.MSG_SET_ADMIN and agent_id:
                # Only global admin can set workspace admin
                if auth.is_global_admin(agent_id):
                    ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                    target_id = msg.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                    target_name = msg.get("target_name", target_id).strip()
                    if ws_id and target_id:
                        if auth.set_workspace_admin(ws_id, target_id, agent_id):
                            await _send(ws, {"type": "ok", "workspace_id": ws_id, "admin_id": target_id, "admin_name": target_name})
                            logger.info("Agent %s set as admin of workspace '%s' by %s", target_id[:20], ws_id, agent_id[:20])
                        else:
                            await _send(ws, {"type": "error", "error": "Failed to set admin"})
                    else:
                        await _send(ws, {"type": "error", "error": "Missing workspace_id or target_agent_id"})


            # ── R12 P0.2: Task Assignment ────────────────────────
            elif msg_type == p.MSG_TASK_ASSIGNMENT and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") != "admin":
                    await _send(ws, {"type": "error", "error": "Permission denied: only admin can assign tasks"})
                    continue

                target_name = msg.get(p.FIELD_TARGET_AGENT, "").strip()
                target_id = msg.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                step = msg.get(p.FIELD_TASK_STEP, "")
                description = msg.get(p.FIELD_TASK_DESC, "")
                channel = msg.get(p.FIELD_CHANNEL, p.LOBBY)
                task_id = str(time.time())

                # Resolve target agent_id if only name provided
                if not target_id and target_name:
                    for aid, u in users.items():
                        if u.get("name") == target_name:
                            target_id = aid
                            break

                if not target_id:
                    await _send(ws, {"type": "error", "error": f"Target agent '{target_name}' not found"})
                    continue

                assign_payload = {
                    "type": p.MSG_TASK_ASSIGNMENT,
                    "task_id": task_id,
                    "channel": channel,
                    "from_name": users.get(agent_id, {}).get("name", agent_id),
                    "agent_id": agent_id,
                    p.FIELD_TARGET_AGENT: target_name or users.get(target_id, {}).get("name", target_id),
                    p.FIELD_TARGET_AGENT_ID: target_id,
                    p.FIELD_TASK_STEP: step,
                    p.FIELD_TASK_DESC: description,
                    "ts": time.time(),
                }

                target_conns = _connections.get(target_id, set())
                if target_conns:
                    payload_json = json.dumps(assign_payload)
                    for conn in list(target_conns):
                        try:
                            if hasattr(conn, "send_str"):
                                await conn.send_str(payload_json)
                            elif hasattr(conn, "send"):
                                await conn.send(payload_json)
                        except Exception:
                            pass
                    await _send(ws, {
                        "type": "delivery_status",
                        "task_id": task_id,
                        "status": "delivered",
                        "message": f"✅ 已送达目标 {target_name or target_id[:12]}，等待响应",
                    })
                    state._task_ack_timers[task_id] = asyncio.create_task(
                        _task_ack_timeout(ws, task_id, target_name or target_id[:12])
                    )
                    logger.info("Task assigned to %s (task_id=%s): %s", target_id[:12], task_id, description[:60])
                else:
                    state._offline_push_queue.setdefault(target_id, []).append(assign_payload)
                    if target_id not in state._offline_timers:
                        state._offline_timers[target_id] = asyncio.create_task(
                            _flush_offline_push(target_id)
                        )
                    await _send(ws, {
                        "type": "delivery_status",
                        "task_id": task_id,
                        "status": "queued",
                        "message": f"❌ 目标 {target_name or target_id[:12]} 离线，消息已保存，上线后自动补发",
                    })
                    logger.info("Task for %s queued (offline): %s", target_id[:12], description[:60])

            # ── R29: task_switch — fire-and-forget ─────────────────
            elif msg_type == p.MSG_TASK_SWITCH and agent_id:
                _users = auth.get_users()
                if _users.get(agent_id, {}).get("role") != "admin":
                    await _send(ws, {"type": "error", "error": "权限不足：仅管理员可发送 task_switch"})
                    continue

                target_id = msg.get("target", "").strip()
                if not target_id:
                    await _send(ws, {"type": "error", "error": "缺少 target 字段"})
                    continue

                # Resolve target by name if only name provided
                if target_id not in _users:
                    for aid, u in _users.items():
                        if u.get("name") == target_id:
                            target_id = aid
                            break

                if target_id and target_id in _users:
                    # R82: removed set_agent_channel
                    logger.info("Admin %s task-switched agent %s to lobby (R82: channel tracking removed)",
                                 agent_id[:12], target_id[:12])
                else:
                    logger.info("Admin %s task-switch target '%s' not found (silently ignored)",
                                 agent_id[:12], msg.get("target", "")[:20])
                # Fire-and-forget: 不回复 ACK

            # ── R29/R34: workspace_reset ──────────────────────────
            elif msg_type == p.MSG_WORKSPACE_RESET and agent_id:
                _users = auth.get_users()
                if _users.get(agent_id, {}).get("role") != "admin":
                    await _send(ws, {"type": "error", "error": "权限不足：仅管理员可执行 workspace_reset"})
                    continue

                workspace_id = msg.get("workspace_id", "").strip()
                all_flag = msg.get("all", False)
                target_id = msg.get("target", "").strip()

                # ── R34: Workspace-scoped reset ──────────────────
                if workspace_id:
                    ws_info = ws_mod.get_workspace(workspace_id)
                    if not ws_info:
                        await _send(ws, {"type": "error", "error": f"工作室 '{workspace_id}' 不存在"})
                        continue
                    if ws_info.state == ws_mod.WorkspaceState.CLOSING:
                        await _send(ws, {"type": "error", "error": f"工作室 '{workspace_id}' 正在关闭中，无法重置"})
                        continue
                    if ws_info.state == ws_mod.WorkspaceState.ARCHIVED:
                        await _send(ws, {"type": "error", "error": f"工作室 '{workspace_id}' 已归档，无法重置"})
                        continue

                    sender_name = _users.get(agent_id, {}).get("name") or \
                                   state._r72_users.get(agent_id, {}).get("name", agent_id[:12])
                    member_ids = ws_info.members

                    reset_content = f"⚠️ 工作室 {workspace_id} 已重置，请各成员确认就位 🫡"
                    broadcast_payload = {
                        "type": "broadcast",
                        "channel": workspace_id,
                        "subtype": "workspace_reset",
                        "force": True,
                        "from_name": sender_name,
                        "agent_id": agent_id,
                        "from": sender_name,
                        "from_agent": agent_id,
                        "content": reset_content,
                        "ts": time.time(),
                    }
                    broadcast_json = json.dumps(broadcast_payload)

                    sent = 0
                    offline = 0
                    target_names = []
                    offline_names = []
                    _online = set(_connections.keys())

                    for mid in member_ids:
                        name = _users.get(mid, {}).get("name") or \
                               state._r72_users.get(mid, {}).get("name", mid[:12])
                        if mid in _online:
                            for conn in list(_connections.get(mid, set())):
                                try:
                                    if hasattr(conn, "send_str"):
                                        await conn.send_str(broadcast_json)
                                    elif hasattr(conn, "send"):
                                        await conn.send(broadcast_json)
                                    sent += 1
                                except Exception:
                                    pass
                            target_names.append(name)
                        else:
                            offline += 1
                            offline_names.append(name)
                            state._offline_push_queue.setdefault(mid, []).append({
                                "type": "broadcast",
                                "channel": workspace_id,
                                "subtype": "workspace_reset",
                                "force": True,
                                "from_name": sender_name,
                                "agent_id": agent_id,
                                "content": reset_content,
                                "ts": time.time(),
                            })
                            if mid not in state._offline_timers:
                                state._offline_timers[mid] = asyncio.create_task(
                                    _flush_offline_push(mid)
                                )

                        # R82: removed set_agent_channel

                    reset_id = str(uuid.uuid4())
                    await _send(ws, {
                        "type": "ack",
                        "id": reset_id,
                        "delivery": {
                            "total": len(member_ids),
                            "sent": sent,
                            "offline": offline,
                            "targets": target_names,
                            "offline_targets": offline_names,
                        }
                    })
                    logger.info("Admin %s reset workspace '%s': %d sent, %d offline",
                                 agent_id[:12], workspace_id, sent, offline)

                # ── R29: Global reset (all: true) ────────────────
                elif all_flag:
                    # R82: removed global agent channel reset
                    logger.info("Admin %s reset ALL agents (R82: channel tracking removed)", agent_id[:12])
                    await _send(ws, {"type": "ack", "status": "ok",
                                     "message": f"✅ 已重置全部 {len(_users)} 个成员到 lobby"})

                # ── R29: Single-target reset ─────────────────────
                elif target_id:
                    if target_id not in _users:
                        for aid, u in _users.items():
                            if u.get("name") == target_id:
                                target_id = aid
                                break
                    if target_id and target_id in _users:
                        # R82: removed set_agent_channel
                        target_name = _users.get(target_id, {}).get("name", target_id[:12])
                        logger.info("Admin %s reset agent %s to lobby", agent_id[:12], target_id[:12])
                        await _send(ws, {"type": "ack", "status": "ok",
                                         "message": f"✅ 已重置 {target_name} 到 lobby"})
                    else:
                        await _send(ws, {"type": "error", "error": f"目标成员 '{msg.get('target', '')}' 不存在"})

                else:
                    await _send(ws, {"type": "error", "error": "请指定 workspace_id、target 或设置 all: true"})

            # ── R67 C1: Heartbeat — update last_online silently ──────
            elif msg_type == p.MSG_HEARTBEAT:
                agent_id = sender_id
                card = ac_mod.get_agent_card(agent_id)
                if card:
                    card["last_online"] = time.time()
                    card["status"] = "online"
                    ac_mod.save_cards()
                continue  # do NOT broadcast heartbeat

            # ── R53 A-4: Channel switch ACK ──────────────────────
            elif msg_type == p.MSG_ACK and agent_id:
                ack_task_id = msg.get(p.FIELD_TASK_ID, "")
                status = msg.get(p.FIELD_TASK_STATUS, "switched")  # "switched" | "failed"
                channel = msg.get(p.FIELD_CHANNEL, "")

                # Find matching channel_ack_state by ack_task_id
                ws_id = _resolve_ws_by_ack_task_id(ack_task_id)
                if not ws_id or ws_id not in state._channel_ack_state:
                    continue  # stale ACK or not waiting

                state = state._channel_ack_state[ws_id]
                if status == "switched":
                    state["acked_members"][agent_id] = time.time()

                    # ── R81 B1: ACK 后自动加入工作区 ──
                    try:
                        ack_ch = "" or ""
                        if ack_ch and ack_ch.startswith(p.WORKSPACE_ID_PREFIX):
                            ack_ws = ws_mod.get_workspace(ack_ch)
                            if ack_ws and agent_id not in ack_ws.members:
                                ws_mod.add_member(ack_ch, agent_id)
                                logger.info(
                                    "R81 B1: Auto-added %s to workspace %s on ACK",
                                    agent_id[:12], ack_ch[:20],
                                )
                    except Exception as e:
                        logger.warning("R81 B1: Auto-add on ACK failed: %s", e)

                    await _send(ws, {"type": "ack", "status": "ok",
                                     "message": "✅ 频道切换已确认"})

                    # All online members acknowledged?
                    if set(state["acked_members"].keys()) >= state["online_members"]:
                        state["timer"].cancel()
                        asyncio.create_task(_notify_rollcall_complete(ws_id))
                # "failed" → record but don't block

            # ── R12 P0.3: Task ACK ──────────────────────────────
            elif msg_type == p.MSG_TASK_ACK and agent_id:
                task_id = msg.get(p.FIELD_TASK_ID, "")
                status = msg.get(p.FIELD_TASK_STATUS, "accepted")
                reason = msg.get(p.FIELD_TASK_REASON, "")

                timer = state._task_ack_timers.pop(task_id, None)
                if timer:
                    timer.cancel()

                users = auth.get_users()
                admin_ids = {aid for aid, u in users.items() if u.get("role") == "admin"}
                sender_name = users.get(agent_id, {}).get("name") or \
                              state._r72_users.get(agent_id, {}).get("name", agent_id[:12])

                if status == "accepted":
                    # ★ R53 B-2: Advance task from submitted → working
                    task = ts.get_task(task_id, config.DATA_DIR)
                    if task and task.get("state") == p.TaskState.SUBMITTED.value:
                        ts.update_task(task_id, state=p.TaskState.WORKING.value, data_dir=config.DATA_DIR)
                        logger.info("R53: Task %s advanced to WORKING (ack by %s)", task_id, agent_id[:12])

                    ack_msg = json.dumps({
                        "type": p.MSG_DELIVERY_STATUS,
                        "task_id": task_id,
                        "status": "accepted",
                        "agent_id": agent_id,
                        "agent_name": sender_name,
                        "message": f"✅ {sender_name} 已接受任务",
                        "ts": time.time(),
                    })
                    for admin_id in admin_ids:
                        for conn in list(_connections.get(admin_id, set())):
                            try:
                                if hasattr(conn, "send_str"):
                                    await conn.send_str(ack_msg)
                                elif hasattr(conn, "send"):
                                    await conn.send(ack_msg)
                            except Exception:
                                pass
                    logger.info("Task %s accepted by %s", task_id, agent_id[:12])
                elif status == "rejected":
                    reject_msg = json.dumps({
                        "type": p.MSG_DELIVERY_STATUS,
                        "task_id": task_id,
                        "status": "rejected",
                        "agent_id": agent_id,
                        "agent_name": sender_name,
                        "reason": reason,
                        "message": f"❌ {sender_name} 拒绝了任务：{reason}",
                        "ts": time.time(),
                    })
                    for admin_id in admin_ids:
                        for conn in list(_connections.get(admin_id, set())):
                            try:
                                if hasattr(conn, "send_str"):
                                    await conn.send_str(reject_msg)
                                elif hasattr(conn, "send"):
                                    await conn.send(reject_msg)
                            except Exception:
                                pass
                    logger.info("Task %s rejected by %s: %s", task_id, agent_id[:12], reason)
                else:
                    await _send(ws, {"type": "error", "error": "Permission denied: only global admin can set workspace admin"})

            # ── R15: Workspace Admin Request ──────────────────────
            elif msg_type == p.MSG_ADMIN_REQUEST and agent_id:
                users = auth.get_users()
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                reason = msg.get(p.FIELD_REASON, "").strip()
                if not ws_id:
                    await _send(ws, {"type": "error", "error": "缺少 workspace_id"})
                    continue
                resolved = ws_mod.get_workspace(ws_id)
                if not resolved:
                    await _send(ws, {"type": "error", "error": "工作室不存在"})
                    continue
                if agent_id not in resolved.members:
                    await _send(ws, {"type": "error", "error": "您不是该工作室成员"})
                    continue
                if agent_id in resolved.admin_ids or agent_id == resolved.owner_id:
                    await _send(ws, {"type": "error", "error": "您已是该工作室的管理员"})
                    continue
                success, msg_text = ws_mod.submit_admin_request(ws_id, agent_id, reason)
                if not success:
                    await _send(ws, {"type": "error", "error": msg_text})
                    continue
                await _send(ws, {"type": "ack", "status": "submitted", "message": msg_text})
                # Notify all global admins
                requester_name = users.get(agent_id, {}).get("name", agent_id[:12])
                admin_ids = {aid for aid, u in users.items() if u.get("role") == "admin"}
                notify_payload = json.dumps({
                    "type": p.MSG_ADMIN_REQUEST,
                    "workspace_id": ws_id,
                    "requester_id": agent_id,
                    "requester_name": requester_name,
                    "reason": reason,
                    "ts": time.time(),
                })
                for admin_id in admin_ids:
                    for conn in list(_connections.get(admin_id, set())):
                        try:
                            if hasattr(conn, "send_str"):
                                await conn.send_str(notify_payload)
                            elif hasattr(conn, "send"):
                                await conn.send(notify_payload)
                        except Exception:
                            pass
                logger.info("Admin request from %s for workspace '%s': %s", agent_id[:12], ws_id, reason[:60])

            # ── R15: Workspace Admin Approved ─────────────────────
            elif msg_type == p.MSG_ADMIN_REQUEST_APPROVED and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") != "admin":
                    await _send(ws, {"type": "error", "error": "权限不足：仅全局管理员可审批"})
                    continue
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                target_id = msg.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                target_name = msg.get(p.FIELD_TARGET_AGENT, "").strip()
                if not ws_id or not target_id:
                    await _send(ws, {"type": "error", "error": "缺少 workspace_id 或 target_agent_id"})
                    continue
                # Resolve target_id by name if needed
                if not target_id and target_name:
                    for aid, u in users.items():
                        if u.get("name") == target_name:
                            target_id = aid
                            break
                if not target_id:
                    await _send(ws, {"type": "error", "error": f"未找到目标成员 {target_name}"})
                    continue
                # Update request status
                success, msg_text = ws_mod.approve_admin_request(ws_id, target_id, agent_id)
                if not success:
                    await _send(ws, {"type": "error", "error": msg_text})
                    continue
                # Call set_admin
                target_name_resolved = target_name or users.get(target_id, {}).get("name", target_id[:12])
                if not auth.set_workspace_admin(ws_id, target_id, agent_id):
                    await _send(ws, {"type": "error", "error": "设置管理员失败"})
                    continue
                # Notify the applicant
                notify_payload = json.dumps({
                    "type": p.MSG_ADMIN_NOTIFICATION,
                    "workspace_id": ws_id,
                    "status": "approved",
                    "message": f"✅ 你已成为 {ws_id} 的管理员",
                    "ts": time.time(),
                })
                for conn in list(_connections.get(target_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(notify_payload)
                        elif hasattr(conn, "send"):
                            await conn.send(notify_payload)
                    except Exception:
                        pass
                # Broadcast to workspace
                broadcast_payload = json.dumps({
                    "type": "broadcast",
                    "channel": ws_id,
                    "from_name": "系统",
                    "content": f"{target_name_resolved} 已成为 {ws_id} 的管理员",
                    "ts": time.time(),
                })
                for member_id in resolved.members if (resolved := ws_mod.get_workspace(ws_id)) else set():
                    for conn in list(_connections.get(member_id, set())):
                        try:
                            if hasattr(conn, "send_str"):
                                await conn.send_str(broadcast_payload)
                            elif hasattr(conn, "send"):
                                await conn.send(broadcast_payload)
                        except Exception:
                            pass
                await _send(ws, {"type": "ack", "message": f"✅ {target_name_resolved} 已成为管理员"})
                logger.info("Admin request approved: %s → admin of '%s' by %s", target_id[:12], ws_id, agent_id[:12])

            # ── R15: Workspace Admin Rejected ─────────────────────
            elif msg_type == p.MSG_ADMIN_REQUEST_REJECTED and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") != "admin":
                    await _send(ws, {"type": "error", "error": "权限不足：仅全局管理员可审批"})
                    continue
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                target_id = msg.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                target_name = msg.get(p.FIELD_TARGET_AGENT, "").strip()
                reject_reason = msg.get(p.FIELD_REASON, "").strip()
                if not ws_id or not target_id:
                    await _send(ws, {"type": "error", "error": "缺少 workspace_id 或 target_agent_id"})
                    continue
                if not target_id and target_name:
                    for aid, u in users.items():
                        if u.get("name") == target_name:
                            target_id = aid
                            break
                if not target_id:
                    await _send(ws, {"type": "error", "error": f"未找到目标成员 {target_name}"})
                    continue
                success, msg_text = ws_mod.reject_admin_request(ws_id, target_id, agent_id, reject_reason)
                if not success:
                    await _send(ws, {"type": "error", "error": msg_text})
                    continue
                # Notify the applicant
                reject_payload = json.dumps({
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
                await _send(ws, {"type": "ack", "message": f"✅ 已拒绝 {target_name or target_id[:12]} 的管理员申请"})
                logger.info("Admin request rejected: %s for '%s' by %s, reason: %s", target_id[:12], ws_id, agent_id[:12], reject_reason)

            elif msg_type == p.MSG_MANAGE_MEMBER and agent_id:
                # Workspace admin can add/remove members in their workspace
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                target_id = msg.get(p.FIELD_TARGET_AGENT_ID, "").strip()
                action = msg.get(p.FIELD_ACTION, "").strip()
                if ws_id and target_id and action:
                    resolved_workspace = ws_mod.get_workspace(ws_id)
                    if resolved_workspace and resolved_workspace.state == ws_mod.WorkspaceState.ACTIVE:
                        if auth.can_manage_workspace(ws_id, agent_id):
                            if action == "add":
                                if ws_mod.add_member(ws_id, target_id):
                                    await _send(ws, {"type": "ok", "workspace_id": ws_id, "member_id": target_id, "action": "add"})
                                    logger.info("Member %s added to workspace '%s' by admin %s", target_id[:20], ws_id, agent_id[:20])
                                else:
                                    await _send(ws, {"type": "error", "error": "Failed to add member"})
                            elif action == "remove":
                                if ws_mod.remove_member(ws_id, target_id):
                                    await _send(ws, {"type": "ok", "workspace_id": ws_id, "member_id": target_id, "action": "remove"})
                                    logger.info("Member %s removed from workspace '%s' by admin %s", target_id[:20], ws_id, agent_id[:20])
                                else:
                                    await _send(ws, {"type": "error", "error": "Failed to remove member"})
                            else:
                                await _send(ws, {"type": "error", "error": f"Unknown action '{action}': use 'add' or 'remove'"})
                        else:
                            await _send(ws, {"type": "error", "error": "Permission denied"})
                    else:
                        await _send(ws, {"type": "error", "error": "Workspace not found or not active"})
                else:
                    await _send(ws, {"type": "error", "error": "Missing workspace_id, target_agent_id, or action"})

            elif msg_type == p.MSG_WORKSPACE_ACK_CLOSE and agent_id:
                ws_id = msg.get("workspace_id", "").strip()
                if ws_id:
                    ws_mod.confirm_ack(ws_id, agent_id)
                    resolved_workspace = ws_mod.get_workspace(ws_id)
                    if resolved_workspace and resolved_workspace.closing_acks >= resolved_workspace.members:
                        await _broadcast_workspace_closing(ws_id, force_finalize=True)

            elif msg_type == "approve_web" and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    code = msg.get("code", "").strip().upper()
                    name = msg.get("name", "大宏")
                    result = auth.approve_web_bind_code(code, name)
                    if result.get("type") == "approve_ok":
                        persistence.save_web_bind_codes(config.DATA_DIR)
                        persistence.save_web_sessions(config.DATA_DIR)
                        logger.info("Web viewer '%s' approved via WS", name)
                    await _send(ws, result)

            elif msg_type == p.MSG_TOKEN_SET_MODE and agent_id:
                # Admin only: set token/free mode
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                    mode = msg.get(p.FIELD_TOKEN_MODE, "").strip()
                    if ws_id and mode:
                        if ws_mod.set_token_mode(ws_id, mode):
                            await _send(ws, {"type": p.MSG_TOKEN_MODE_SET, "workspace_id": ws_id, "mode": mode})
                            logger.info("Admin %s set workspace '%s' token mode → %s", agent_id[:20], ws_id, mode)
                        else:
                            await _send(ws, {"type": "error", "error": "Failed to set token mode"})
                    else:
                        await _send(ws, {"type": "error", "error": "Missing workspace_id or mode"})
                else:
                    await _send(ws, {"type": "error", "error": "Permission denied: only admin can change token mode"})

            elif msg_type == p.MSG_TOKEN_SET_ORDER and agent_id:
                # Admin only: set token order
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                    order = msg.get(p.FIELD_TOKEN_ORDER, [])
                    if ws_id and order:
                        if ws_mod.set_token_order(ws_id, order):
                            await _send(ws, {"type": p.MSG_TOKEN_ORDER_SET, "workspace_id": ws_id, "order": order})
                            logger.info("Admin %s set workspace '%s' token order", agent_id[:20], ws_id)
                    else:
                        await _send(ws, {"type": "error", "error": "Missing workspace_id or order"})
                else:
                    await _send(ws, {"type": "error", "error": "Permission denied"})

            elif msg_type == p.MSG_TOKEN_ADVANCE and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                    next_token = msg.get(p.FIELD_TOKEN_CURRENT, 0)
                    if ws_id:
                        if ws_mod.advance_token(ws_id, next_token):
                            stats = ws_mod.get_token_status(ws_id)
                            await _send(ws, {"type": p.MSG_TOKEN_ADVANCED, "workspace_id": ws_id, **stats})
                    else:
                        await _send(ws, {"type": "error", "error": "Missing workspace_id"})
                else:
                    await _send(ws, {"type": "error", "error": "Permission denied"})

            elif msg_type == p.MSG_TOKEN_SKIP and agent_id:
                users = auth.get_users()
                if users.get(agent_id, {}).get("role") == "admin":
                    ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                    if ws_id:
                        if ws_mod.skip_token(ws_id):
                            stats = ws_mod.get_token_status(ws_id)
                            await _send(ws, {"type": p.MSG_TOKEN_SKIPPED, "workspace_id": ws_id, **stats})
                        else:
                            await _send(ws, {"type": "error", "error": "Cannot skip: already at end of order"})
                else:
                    await _send(ws, {"type": "error", "error": "Permission denied"})

            elif msg_type == p.MSG_TOKEN_STATUS and agent_id:
                ws_id = msg.get(p.FIELD_WORKSPACE_ID, "").strip()
                if ws_id:
                    stats = ws_mod.get_token_status(ws_id)
                    if stats:
                        await _send(ws, {"type": p.MSG_TOKEN_STATUS_RESULT, "workspace_id": ws_id, **stats})
                    else:
                        await _send(ws, {"type": "error", "error": "Workspace not found"})

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


# ── Workspace Closing ──────────────────────────────────────────────

async def _broadcast_workspace_closing(ws_id: str, force_finalize: bool = False) -> None:
    """Notify workspace members of impending close and wait for ACKs."""
    resolved_workspace = ws_mod.get_workspace(ws_id)
    if not resolved_workspace or resolved_workspace.state != ws_mod.WorkspaceState.CLOSING:
        return

    deadline_ts = time.time() + p.WORKSPACE_CLOSING_TIMEOUT
    payload = json.dumps({
        "type": p.MSG_WORKSPACE_CLOSING,
        p.FIELD_WORKSPACE_ID: ws_id,
        p.FIELD_REASON: "task_completed",
        p.FIELD_DEADLINE_TS: deadline_ts,
        p.FIELD_ACK_REQUIRED: True,
    })

    # Broadcast to all members
    for agent_id in resolved_workspace.members:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(payload)
                elif hasattr(conn, "send"):
                    await conn.send(payload)
            except Exception:
                pass

    if force_finalize:
        ws_mod.finalize_close(ws_id)
        await _broadcast_workspace_archived(ws_id, resolved_workspace)
        return

    # Wait for ACKs with timeout
    await asyncio.sleep(p.WORKSPACE_CLOSING_TIMEOUT)

    # Force-close any unacked members
    resolved_workspace = ws_mod.get_workspace(ws_id)
    if resolved_workspace and resolved_workspace.state == ws_mod.WorkspaceState.CLOSING:
        unacked = resolved_workspace.members - resolved_workspace.closing_acks
        if unacked:
            logger.warning("Workspace '%s': force-closing unacked members: %s", ws_id, unacked)
            for aid in unacked:
                resolved_workspace.closing_acks.add(aid)
        ws_mod.finalize_close(ws_id)
        await _broadcast_workspace_archived(ws_id, resolved_workspace)


# ── Broadcast Workspace Archived ──────────────────────────────────


async def _broadcast_workspace_archived(ws_id: str, resolved_workspace=None) -> None:
    """Broadcast that workspace has been archived — Web UI uses to regroup tab."""
    if resolved_workspace is None:
        resolved_workspace = ws_mod.get_workspace(ws_id)
    if not resolved_workspace:
        return
    # R82: removed active channel reset — bot uses inbox only
    logger.info("R82: Workspace '%s' archived — no channel reset", ws_id)
    arch_payload = json.dumps({
        "type": "broadcast",
        "channel": ws_id,
        "from_name": "系统",
        "content": f"workspace {ws_id} 已归档",
        "_workspace_event": "archived",
        "workspace_id": ws_id,
        "ts": time.time(),
    })
    for agent_id in resolved_workspace.members:
        for conn in list(_connections.get(agent_id, set())):
            try:
                if hasattr(conn, "send_str"):
                    await conn.send_str(arch_payload)
                elif hasattr(conn, "send"):
                    await conn.send(arch_payload)
            except Exception:
                pass
