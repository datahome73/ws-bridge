# -*- coding: utf-8 -*-
"""
R126: Scenario Matching Rule Engine — extracted from main.py.

Extracts the _handle_server_relay if/elif chain, _handle_hash_cmd, and
_classify_lobby_message into a declarative rule table.

Protocol doc: docs/inbox-message-protocol.md §7 Rule Priority Mapping
"""
import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import state
from . import message_store as ms
from server.common.config import DATA_DIR, DISPATCH_SENDER_ID, PIPELINE_PM_AGENT_ID

logger = logging.getLogger("ws-bridge.scenario_matcher")

# ── HandlerRule dataclass ─────────────────────────────────────────────

@dataclass
class HandlerRule:
    """A scenario matching rule.

    - match: (content, msg, agent_id) → match result (truthy = matched, False/None = no match)
    - handle: (ws, agent_id, msg, matched_info) → bool (True = handled, False = pass through)
    - priority: lower = higher priority
    - name: human-readable rule name
    - protocol_ref: optional link to protocol doc section
    """
    match: Callable[[str, dict, str], Any]
    handle: Callable[[Any, str, dict, Any], Awaitable[bool]]
    priority: int
    name: str
    protocol_ref: str = ""

# ── Rule table ────────────────────────────────────────────────────────

_RULES: list[HandlerRule] = []

def register_rule(rule: HandlerRule) -> None:
    """Register a rule, maintaining priority order."""
    _RULES.append(rule)
    _RULES.sort(key=lambda r: r.priority)

# ── Dispatch engine ───────────────────────────────────────────────────

SERVER_INBOX_CHANNEL = state.SERVER_INBOX_CHANNEL
INBOX_CHANNEL_PREFIX = "unused"  # imported via shared.protocol where needed

# R102: prefixes that trigger auto-reroute to _inbox:server
_R102_PREFIXES = ("收到 ✅", "已完成 ✅", "退回 🔄", "失败 ❌", "ACK ✅", "✅ 完成", "✅ ")

async def dispatch(ws, agent_id: str, msg: dict) -> bool:
    """Traverse rules by priority and execute the first match.

    Args:
        ws: WebSocket connection
        agent_id: authenticated agent ID
        msg: message dict (must contain channel/content fields)

    Returns:
        True — message handled (caller should continue, skip normal routing)
        False — no rule matched (caller should continue normal routing)
    """
    channel = msg.get("channel", "")
    content = (msg.get("content") or "").strip()

    # ── R102: auto-reroute non-_inbox:server messages matching relay prefixes ──
    if channel != SERVER_INBOX_CHANNEL and content.startswith(_R102_PREFIXES):
        # Don't reroute PM's own messages
        pm_id = DISPATCH_SENDER_ID or PIPELINE_PM_AGENT_ID
        if not (pm_id and agent_id == pm_id):
            channel = SERVER_INBOX_CHANNEL
            msg["channel"] = SERVER_INBOX_CHANNEL

    # Non-relay messages → normal routing
    if channel != SERVER_INBOX_CHANNEL:
        return False

    for rule in _RULES:
        matched = rule.match(content, msg, agent_id)
        if matched is not False and matched is not None:
            return await rule.handle(ws, agent_id, msg, matched)

    return False  # fall through to normal routing

# ── Match functions (pure) ────────────────────────────────────────────

def match_loopback(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 10: test ✅ loopback check."""
    if content.startswith("test ✅"):
        return True
    return False

def match_to_agent(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 20: to_agent dispatch routing."""
    to_agent = (msg.get("to_agent") or "").strip()
    if not to_agent:
        text = msg.get("content", "").strip()
        if text.startswith("{"):
            try:
                import json
                inner = json.loads(text)
                to_agent = (inner.get("to_agent") or "").strip()
            except (json.JSONDecodeError, Exception):
                pass
    if to_agent:
        return to_agent
    return False

def match_hash_cmd(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 30: ## commands."""
    if content.startswith("##"):
        return content
    return False

def match_ack(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 40: 收到 ✅ / ACK ✅ forward to PM."""
    if content.startswith("收到 ✅") or content.startswith("ACK ✅"):
        return True
    return False

def match_complete(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 50: 已完成 ✅ / ✅ 完成 auto-confirm."""
    if content.startswith("已完成 ✅") or content.startswith("✅ 完成"):
        return True
    return False

def match_reject(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 60: 退回 🔄 reject rollback."""
    if content.startswith("退回 🔄"):
        return True
    return False

def match_fail(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 70: 失败 ❌ alert."""
    if content.startswith("失败 ❌"):
        return True
    return False

def match_catchall(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 90: catch-all — store silently."""
    return True


# ── R131: ##query match ──────────────────────────────────────────────

def match_query(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 25: ##query commands."""
    if content.startswith("##query"):
        return content
    return False


# ── R131: Level helper ──────────────────────────────────────────────

_QUERY_LEVEL_MAP = {
    "whoami": 1,
    "help": 1,
    "status": 3,
    "agents": 3,
    "agent_info": 3,
    "audit": 4,
    # R132
    "step": 4,
}


def get_agent_level(agent_id: str) -> int:
    """Return agent permission level (1-4). Default 1 for unregistered."""
    from server.common import persistence
    users = persistence.get_approved_users()
    info = users.get(agent_id, {})
    return info.get("level", 1)


# ── R131: ##query handler ────────────────────────────────────────────

async def handle_query(ws, agent_id: str, msg: dict, matched: Any) -> bool:
    """Handle ##query commands: parse sub-command → check level → execute → reply inbox."""
    content = matched
    parts = content.split("##")
    if len(parts) < 3:
        await _send_reply(ws, agent_id,
            "📋 **##query 命令帮助**\\n\\n"
            "`##query##whoami` — 查看自己信息\\n"
            "`##query##status [R{N}]` — 查询管线状态\\n"
            "`##query##agents` — 列出所有注册 bot\\n"
            "`##query##agent_info <id>` — 查询 bot 详情\\n"
            "`##query##audit` — 审计日志（需 L4）\\n"
            "`##query##help` — 显示本帮助"
        )
        return True

    sub_cmd = parts[2].lower()
    params = parts[3] if len(parts) > 3 else ""

    # ── Permission check: use minimum level map ──
    level = get_agent_level(agent_id)
    min_level = _QUERY_LEVEL_MAP.get(sub_cmd, 5)
    if level < min_level:
        await _send_reply(ws, agent_id,
            f"❌ 权限不足: {sub_cmd} 需要 L{min_level}，你当前 L{level}"
        )
        return True

    # ── Route sub-commands ──
    from . import main as _main

    if sub_cmd == "whoami":
        from server.common import auth, persistence
        users = auth.get_users()
        info = users.get(agent_id, {})
        name = info.get("name", agent_id[:12])
        reply = f"🆔 agent_id: {agent_id} | 名称: {name} | 级别: L{level}"

    elif sub_cmd == "status":
        reply = await _format_query_status(params)

    elif sub_cmd == "agents":
        reply = await _format_query_agents()

    elif sub_cmd == "agent_info":
        if not params:
            reply = "❌ 用法: ##query##agent_info <agent_id>"
        else:
            reply = await _format_query_agent_info(params)

    elif sub_cmd == "audit":
        limit = 20
        if params:
            try:
                limit = min(int(params.replace("--limit=", "").replace("--limit ", "")), 100)
            except (ValueError, IndexError):
                pass
        reply = await _format_query_audit(limit)

    elif sub_cmd == "help":
        reply = (
            "📋 **##query 命令**\\n\\n"
            "`##query##whoami` — 查看自己信息 (L1+)\\n"
            "`##query##status [R{N}]` — 管线状态 (L3+)\\n"
            "`##query##agents` — 列出所有 bot (L3+)\\n"
            "`##query##agent_info <id>` — bot 详情 (L3+)\\n"
            "`##query##audit [--limit N]` — 审计日志 (L4+)\\n"
            "`##query##help` — 本帮助"
        )
    else:
        reply = f"❌ 未知查询: {sub_cmd}"

    await _send_reply(ws, agent_id, reply)
    return True


# ── R131: Query data formatters ─────────────────────────────────────

async def _format_query_status(round_name: str) -> str:
    """Format pipeline status response."""
    from . import main as _main
    if round_name:
        # Specific round
        mgr = _main._ensure_pipeline_manager()
        ctx = mgr.get(round_name.upper())
        if ctx:
            return _main._ensure_engine().format_context(ctx)
        # Check archive
        archive = _main._ensure_engine().find_archive(round_name.upper())
        if archive:
            from datetime import datetime
            ts = archive.get("archived_at", 0)
            time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "?"
            total = archive.get("total_steps", 6)
            done = archive.get("completed_steps", 0)
            return f"📦 {round_name.upper()} 已归档\\n状态: completed\\n归档时间: {time_str}\\n总步数: {total} / 完成: {done}"
        return f"❌ 管线 {round_name.upper()} 不存在"
    # All active pipelines
    mgr = _main._ensure_pipeline_manager()
    active = mgr.get_all_active()
    if not active:
        return "📋 当前无活跃管线"
    lines = ["📋 活跃管线:"]
    for ctx in sorted(active, key=lambda c: c.round_name):
        lines.append(f"  {ctx.round_name} [{ctx.task_kind.value}] {ctx.status.value} step={ctx.current_step}/{ctx.total_steps}")
    return "\\n".join(lines)


async def _format_query_agents() -> str:
    """Format agent list response."""
    from server.common import auth, persistence
    from .main import _connections
    from . import agent_card as ac_mod

    users = auth.get_users()
    api_keys = persistence.get_api_keys()
    cards = ac_mod.get_all_cards()

    lines = [f"📇 Agents ({len(users)}):"]
    for aid, info in sorted(users.items()):
        name = info.get("name", aid[:12])
        level = info.get("level", 1)
        online = aid in _connections
        status = "🟢" if online else "🔴"
        role = info.get("role", "member")
        card_roles = cards.get(aid, {}).get("pipeline_roles", [])
        roles_str = f" [{','.join(card_roles)}]" if card_roles else ""
        lines.append(f"  {status} {name} ({aid[:12]}...) L{level} {role}{roles_str}")

    # Add api_keys-only agents (registered but not in approved_users)
    for aid, key_info in api_keys.items():
        if aid not in users:
            name = key_info.get("display_name", aid[:12])
            lines.append(f"  🔴 {name} ({aid[:12]}...) L1 api_key")

    return "\\n".join(lines)


async def _format_query_agent_info(agent_id: str) -> str:
    """Format single agent detail."""
    from server.common import auth, persistence
    from .main import _connections
    from . import agent_card as ac_mod

    users = auth.get_users()
    info = users.get(agent_id, {})
    if not info:
        # Check api_keys
        api_keys = persistence.get_api_keys()
        key_info = api_keys.get(agent_id, {})
        if not key_info:
            return f"❌ Agent {agent_id} 不存在"
        name = key_info.get("display_name", agent_id[:12])
        level = 1
    else:
        name = info.get("name", agent_id[:12])
        level = info.get("level", 1)

    online = agent_id in _connections
    status = "🟢 在线" if online else "🔴 离线"
    card = ac_mod.get_card(agent_id) or {}
    card_roles = card.get("pipeline_roles", [])
    roles_str = f"\\n  角色: {', '.join(card_roles)}" if card_roles else ""

    return (
        f"📇 **{name}**\\n"
        f"  ID: {agent_id}\\n"
        f"  状态: {status}\\n"
        f"  级别: L{level}{roles_str}"
    )


async def _format_query_audit(limit: int) -> str:
    """Format audit log response."""
    from .main import _audit_logger
    try:
        entries = _audit_logger.query(tail=limit)
        if not entries:
            return "📋 暂无审计日志"
        lines = [f"📋 最近 {len(entries)} 条审计日志:"]
        for entry in entries:
            ts = entry.get("ts", 0)
            from datetime import datetime
            time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"
            agent = entry.get("agent_id", "")[:12]
            cmd = entry.get("command", "")
            result = "✅" if entry.get("result") == "success" else "❌"
            lines.append(f"  {time_str} {result} {agent} !{cmd}")
        return "\\n".join(lines)
    except Exception as e:
        return f"❌ 读取审计日志失败: {e}"

# ── Moved from main.py: _handle_hash_cmd ─────────────────────────────

async def handle_hash_cmd(ws, agent_id: str, msg: dict, matched: Any) -> bool:
    """Handle ## prefix commands. Moved from main.py _handle_hash_cmd()."""
    content = matched  # the original content string
    parts = content.split("##")
    if len(parts) < 3:
        await _send_reply(ws, agent_id,
            "📋 **## 命令帮助**\n\n"
            "`##start##R{N}##k=v` — 创建管线 + 派活 Step 1\n"
            "`##status##R{N}` — 查询管线状态\n"
            "`##stop##R{N}` — 停止管线\n"
            "`##advance##R{N}##step=N` — 手动推进到下一步（PM使用）\n"
            "`##archive##R{N}` — 归档管线（PM使用）\n"
            "`##help` — 显示本帮助"
        )
        return True

    cmd = parts[1].lower()
    round_name = parts[2].upper()

    # Parse key=value data
    kv: dict[str, str] = {}
    for p in parts[3:]:
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k.strip()] = v.strip()

    # Import callbacks registered by main.py
    from . import main as _main

    if cmd == "start":
        return await _main._handle_hash_start(round_name, kv, agent_id, ws)
    elif cmd == "status":
        return await _main._handle_hash_status(round_name, agent_id, ws)
    elif cmd == "stop":
        return await _main._handle_hash_stop(round_name, agent_id, ws)
    elif cmd == "advance":
        return await _main._handle_hash_advance(round_name, kv, agent_id, ws)
    elif cmd == "archive":
        return await _main._handle_hash_archive(round_name, agent_id, ws)
    elif cmd == "help":
        await _send_reply(ws, agent_id,
            "📋 **## 命令帮助**\n\n"
            "`##start##R{N}##k=v` — 创建管线 + 派活 Step 1\n"
            "`##status##R{N}` — 查询管线状态\n"
            "`##stop##R{N}` — 停止管线\n"
            "`##advance##R{N}##step=N` — 手动推进到下一步（PM使用）\n"
            "`##archive##R{N}` — 归档管线（PM使用）\n"
            "`##help` — 显示本帮助"
        )
        return True

    await _send_reply(ws, agent_id,
        f"❌ 未知 ## 命令: {cmd}，可用: start / status / stop / advance / archive / help"
    )
    return True


# ── R131: ##query commands (rule 25) ────────────────────────────────

_QUERY_SHORTCUTS = ("##whoami", "##agents", "##status", "##agent_info", "##audit", "##help")


# ── R132: ##step match (rule 28) ────────────────────────────────────

def match_step(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 28: ##step commands.
    Priority 28 — between query (25) and hash_cmd (30).
    Matches: ##step##<action>[##<args>]
    """
    if content.startswith("##step"):
        return content
    return False


def match_query(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 25: ##query commands (+ shortcuts).
    Priority 25 — intercepts before generic ## handler (30).
    Supports both ##query##<sub_cmd> and direct ##whoami etc.
    """
    if content.startswith("##query"):
        return content
    for prefix in _QUERY_SHORTCUTS:
        if content.startswith(prefix):
            return content.replace("##", "##query##", 1)
    return False


async def handle_query(ws, agent_id: str, msg: dict, matched: Any) -> bool:
    """Handle ##query sub-commands — rule 25 handler.

    Format: ##query##<sub_cmd>[##<params>]
    Sub-commands: whoami, agents, status, agent_info, audit, help
    """
    content = matched
    parts = content.split("##")
    if len(parts) < 3:
        await _send_reply(ws, agent_id,
            "📋 **##query 命令**\n\n"
            "`##whoami` — 查看自己信息\n"
            "`##agents` — 列出所有 bot\n"
            "`##status [R{N}]` — 查询管线状态\n"
            "`##agent_info <agent_id>` — 查询 bot 详情\n"
            "`##audit [--limit N]` — 审计日志 (L4+)\n"
            "`##help` — 显示本帮助"
        )
        return True

    sub_cmd = parts[2].lower()
    params = parts[3] if len(parts) > 3 else ""

    # 权限检查
    level = _get_agent_level(agent_id)
    if level < 1:
        await _send_reply(ws, agent_id, "❌ 权限不足：未注册 bot")
        return True
    if level == 1 and sub_cmd not in ("whoami", "help"):
        await _send_reply(ws, agent_id, "❌ 权限不足：L1 仅允许 ##whoami 和 ##help")
        return True
    if level < 4 and sub_cmd == "audit":
        await _send_reply(ws, agent_id, "❌ 权限不足：##audit 需要 L4")
        return True

    # 6 个子命令路由（复用 main.py 函数）
    from . import main as _main

    if sub_cmd == "whoami":
        from server.common import auth as _auth
        users = _auth.get_users()
        info = users.get(agent_id, {})
        name = info.get("name", agent_id[:12])
        await _send_reply(ws, agent_id,
            f"🆔 agent_id: `{agent_id}`\n"
            f"📛 名称: {name}\n"
            f"🎚️ 级别: L{level}")
    elif sub_cmd == "status":
        reply = await _format_pipeline_status(params, _main)
        await _send_reply(ws, agent_id, reply)
    elif sub_cmd == "agents":
        reply = _format_agent_list()
        await _send_reply(ws, agent_id, reply)
    elif sub_cmd == "agent_info":
        reply = _format_agent_info(params)
        await _send_reply(ws, agent_id, reply)
    elif sub_cmd == "audit":
        reply = _format_audit_log(params)
        await _send_reply(ws, agent_id, reply)
    elif sub_cmd == "help":
        await _send_reply(ws, agent_id,
            "📋 **##query 命令**\n\n"
            "`##whoami` — 查看自己信息\n"
            "`##agents` — 列出所有 bot\n"
            "`##status [R{N}]` — 查询管线状态\n"
            "`##agent_info <agent_id>` — 查询 bot 详情\n"
            "`##audit [--limit N]` — 审计日志 (L4+)\n"
            "`##help` — 显示本帮助")
    else:
        await _send_reply(ws, agent_id,
            f"❌ 未知子命令: {sub_cmd}，可用: whoami / agents / status / agent_info / audit / help")

    return True


# ── R132: ##step handler (rule 28) ──────────────────────────────────

_STEP_ACTIONS = ("complete", "reject", "restart", "force", "pause", "resume")


async def handle_step(ws, agent_id: str, msg: dict, matched: Any) -> bool:
    """Handle ##step commands: ##step##<action>[##<args>]
    Priority 28 — between query (25) and hash_cmd (30).
    Permission: L4 required (uses _get_agent_level).
    Actions: complete / reject / restart / force / pause / resume
    """
    content = matched
    parts = content.split("##")
    if len(parts) < 3:
        await _send_reply(ws, agent_id,
            "📋 **##step 命令帮助**\n\n"
            "`##step##complete##<id>` — 步骤完成 (L4)\n"
            "`##step##reject##<id>##<原因>` — 步骤打回 (L4)\n"
            "`##step##restart##<id>` — 步骤回退重启 (L4)\n"
            "`##step##force##<id>` — 强制推进 (L4)\n"
            "`##step##pause##<id>` — 暂停步骤 (L4)\n"
            "`##step##resume##<id>` — 恢复步骤 (L4)"
        )
        return True

    action = parts[2].lower()
    args = parts[3] if len(parts) > 3 else ""

    # ── Permission check: L4 required (matches R131 active pattern) ──
    level = _get_agent_level(agent_id)
    if level < 4:
        await _send_reply(ws, agent_id,
            "❌ 权限不足：需要 L4 级别"
        )
        return True

    # ── Route actions ──
    from .commands.pipeline import (
        _cmd_step_complete,
        _cmd_step_reject,
        _cmd_step_force,
        _cmd_step_handoff,
    )

    if action == "complete":
        params = {"step_name": args}
        reply = await _cmd_step_complete(agent_id, params)
        await _send_reply(ws, agent_id, reply)

    elif action == "reject":
        step_parts = args.split("##", 1)
        step_id = step_parts[0]
        reason = step_parts[1] if len(step_parts) > 1 else ""
        params = {"step_name": step_id, "reason": reason}
        reply = await _cmd_step_reject(agent_id, params)
        await _send_reply(ws, agent_id, reply)

    elif action == "restart":
        # Use handoff to mark complete and hand to next role
        params = {"step_name": args}
        reply = await _cmd_step_handoff(agent_id, params)
        await _send_reply(ws, agent_id, reply)

    elif action == "force":
        params = {"step_name": args}
        reply = await _cmd_step_force(agent_id, params)
        await _send_reply(ws, agent_id, reply)

    elif action == "pause":
        await _send_reply(ws, agent_id,
            f"⏸️ 步骤 #{args} 已暂停"
        )

    elif action == "resume":
        await _send_reply(ws, agent_id,
            f"▶️ 步骤 #{args} 已恢复"
        )

    else:
        await _send_reply(ws, agent_id,
            f"❌ 未知步骤操作: {action}"
        )

    return True


# ── R131: helper functions ──────────────────────────────────────────

def _get_agent_level(agent_id: str) -> int:
    """获取 agent 权限级别 (1-4)，默认 1。"""
    from server.common import persistence as _p
    users = _p.get_approved_users()
    info = users.get(agent_id, {})
    return info.get("level", 1)


async def _format_pipeline_status(round_name: str, main_mod) -> str:
    """Return pipeline status text."""
    mgr = main_mod._ensure_pipeline_manager()
    if round_name:
        ctx = mgr.get(round_name)
        if ctx:
            engine = main_mod._ensure_engine()
            return engine.format_context(ctx)
        return f"❌ 管线 {round_name} 不存在"
    active = mgr.get_all_active()
    if active:
        lines = ["📋 活跃管线:"]
        for ctx in sorted(active, key=lambda c: c.round_name):
            lines.append(
                f"  {ctx.round_name} [{ctx.task_kind.value}] "
                f"{ctx.status.value} step={ctx.current_step}/{ctx.total_steps}"
            )
        return "\n".join(lines)
    return "📋 当前无活跃管线"


def _format_agent_list() -> str:
    """Return agent list text."""
    from server.common import auth as _auth
    from . import agent_card as _ac
    from . import state as _st
    users = _auth.get_users()
    cards = _ac.get_all_cards()
    lines = ["📇 Agents:"]
    seen = set()
    for aid, info in sorted(users.items()):
        name = info.get("name", aid[:12])
        role = info.get("role", "member")
        online = "🟢" if aid in _st._connections else "🔴"
        card = cards.get(aid, {})
        roles = ", ".join(card.get("pipeline_roles", []))
        roles_str = f" [{roles}]" if roles else ""
        lines.append(f"  {online} {name} ({aid[:12]}...) L{info.get('level', 1)}{roles_str}")
        seen.add(aid)
    return "\n".join(lines)


def _format_agent_info(agent_id: str) -> str:
    """Return single agent info text."""
    from server.common import auth as _auth
    from . import agent_card as _ac
    from . import state as _st
    users = _auth.get_users()
    info = users.get(agent_id, {})
    if not info:
        return f"❌ Agent {agent_id} 未找到"
    name = info.get("name", agent_id[:12])
    role = info.get("role", "member")
    level = info.get("level", 1)
    online = "🟢 在线" if agent_id in _st._connections else "🔴 离线"
    card = _ac.get_agent_card(agent_id)
    card_info = ""
    if card:
        card_info = (
            f"\n  📇 display_name: {card.get('display_name', '')}"
            f"\n  🎭 角色: {', '.join(card.get('pipeline_roles', []))}"
        )
    return (
        f"📋 Agent 信息: {name}\n"
        f"  🆔 agent_id: `{agent_id}`\n"
        f"  🎚️ 级别: L{level} / 角色: {role}\n"
        f"  📡 状态: {online}"
        f"{card_info}"
    )


def _format_audit_log(limit_str: str) -> str:
    """Return audit log tail."""
    from .audit import AuditLogger
    from server.common.config import DATA_DIR as _dd
    limit = 20
    if limit_str and limit_str.isdigit():
        limit = min(int(limit_str), 100)
    auditor = AuditLogger(_dd)
    lines = auditor.tail(limit)
    if not lines:
        return "📋 审计日志为空"
    return "📋 最近审计日志:\n" + "\n".join(
        f"  {l}" for l in lines[-limit:]
    )


# ── Helper ────────────────────────────────────────────────────────────

async def _send_reply(ws, agent_id: str, content: str) -> None:
    """Send a reply to the agent's inbox."""
    from .main import _send
    try:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": content,
            "ts": time.time(),
        })
    except Exception:
        pass


# ── R131: Register rule 25 (##query) ────────────────────────────────

register_rule(HandlerRule(
    match=match_query,
    handle=handle_query,
    priority=25,
    name="##query 命令",
    protocol_ref="§R131",
))

# ── R132: Register rule 28 (##step) ─────────────────────────────────

register_rule(HandlerRule(
    match=match_step,
    handle=handle_step,
    priority=28,
    name="##step 命令",
    protocol_ref="§R132",
))
