# -*- coding: utf-8 -*-
"""R136 EXT-1: Connection management — extracted from main.py.

Pure extraction — no semantic changes. Covers WebSocket auth, registration,
connection tracking, sending, and agent-directed unicast.
"""
import asyncio
import json
import time
import uuid
import logging

from . import state
from server.common import auth, config, persistence
from . import message_store as ms
import shared.protocol as p

logger = logging.getLogger("ws-bridge")

# ── R72: Connection management ──

_connections: dict[str, set] = {}


def get_connections() -> dict[str, set]:
    return _connections


async def _send(ws, data: dict) -> None:
    """Send JSON to a WebSocket (compatible with both websockets & aiohttp)."""
    if hasattr(ws, "send_json"):
        await ws.send_json(data)
    elif hasattr(ws, "send_str"):
        await ws.send_str(json.dumps(data))
    elif hasattr(ws, "send"):
        await ws.send(json.dumps(data))


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
    from . import agent_card as ac_mod
    cards = ac_mod.get_all_cards()
    card = cards.get(agent_id)
    if card:
        card["status"] = "online"
        card["last_online"] = time.time()
        ac_mod.update_card(agent_id, card)


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


# ── R79: Registration helpers ──


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
    from .main import _broadcast_to_channel
    from . import agent_card as ac_mod

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
                notify_ = _build_admin_notification(agent_id, display_name, pipeline_roles)
                await _broadcast_to_channel(p.ADMIN_CHANNEL, {
                    "type": p.MSG_BROADCAST, "channel": p.ADMIN_CHANNEL,
                    "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
                    "content": notify_, "ts": time.time(),
                })
                logger.info("R79 B: Admin notified for %s", agent_id[:20])
        except Exception as e:
            logger.warning("R79 B: Admin notification failed: %s", e)

        # C: R82 removed — active channel management no longer needed (bot uses inbox)

        # D: 大厅广播（默认关闭）
        if state.REGISTRATION_BROADCAST_ENABLED:
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


# ── R87: _inbox:server 中继转发 ──


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
    if sent == 0:
        logger.warning(
            "[R117] _send_to_agent(%s): 无目标连接 (sent=0)",
            target_agent_id[:20],
        )
    # 同时持久化到 DB（R129 B-6: 去重 — 同 channel 同 content 在 1s 内不重复存）
    try:
        if not ms.is_duplicate(
            channel=payload.get("channel", ""),
            content=payload.get("content", ""),
            window_sec=1.0,
            data_dir=config.DATA_DIR,
        ):
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
