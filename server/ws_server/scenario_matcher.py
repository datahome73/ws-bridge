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

def match_pm_guard(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 35: PM safety guard — reject PM sending to _inbox:server."""
    pm_id = DISPATCH_SENDER_ID or PIPELINE_PM_AGENT_ID
    if pm_id and agent_id == pm_id:
        return True
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

def match_exclamation(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 80: ! command passthrough."""
    if content.startswith("!"):
        return True
    return False

def match_catchall(content: str, msg: dict, agent_id: str) -> Any:
    """Rule 90: catch-all — store silently."""
    return True

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

# ── Moved from main.py: _classify_lobby_message ──────────────────────

def classify_lobby_message(content: str) -> tuple[str, list[str]]:
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
