"""R100: Command routing utility functions — extracted from handler.py.

Pure utility functions for !command parsing, permission checking,
response sending, audit logging, channel broadcasting, and workspace resolution.
No domain-specific command logic (those go in commands/).
"""

import json
import time
import uuid

from . import state, auth, workspace as ws_mod
from . import message_store as ms
from .web_viewer import write_chat_log


async def _broadcast_to_channel(channel: str, payload: dict) -> int:
    """向指定频道的所有连接广播消息。返回发送数。同时持久化。"""
    payload_json = json.dumps(payload)
    sent = 0
    # Delayed import from main to avoid circular import
    from .main import _connections
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
            data_dir=__import__("server.config", fromlist=[""]).DATA_DIR,
            channel=channel,
        )
        write_chat_log("系统", payload.get("content", ""), channel=channel)
    except Exception:
        pass
    return sent


async def _send_cmd_response(ws, sender_id: str, from_name: str, content: str, channel: str) -> None:
    """Send command response to the source channel (any channel, not just _admin).
    Used by R49 universal ! command routing."""
    from .main import _send
    msg = {
        "type": "broadcast",
        "channel": channel,
        "from_name": from_name,
        "from": from_name,
        "agent_id": "",
        "from_agent": "",
        "content": content,
    }
    await _send(ws, msg)
    try:
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent=sender_id, from_name=from_name,
            content=content, ts=time.time(),
            data_dir=__import__("server.config", fromlist=[""]).DATA_DIR, channel=channel,
        )
    except Exception:
        pass
    write_chat_log(from_name, content, channel=channel)


def _parse_command(content: str) -> tuple[str | None, dict]:
    """Parse '!<command> [args...]' into (command_name, params dict)."""
    if not content.startswith("!"):
        return None, {}

    parts = content[1:].strip().split()
    if not parts:
        return None, {}

    cmd = parts[0].lower()
    params: dict = {"_raw": content}
    positional: list[str] = []
    i = 1
    while i < len(parts):
        token = parts[i]
        if token.startswith("--"):
            key = token[2:]
            i += 1
            if i < len(parts):
                val = parts[i]
                if (val.startswith('"') and val.endswith('"')) or \
                   (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                params[key] = val
            else:
                params[key] = ""
        else:
            positional.append(token)
        i += 1

    if positional:
        params["_positional"] = positional
    return cmd, params


def _is_any_workspace_admin(agent_id: str) -> bool:
    """Check if agent is a workspace admin of ANY workspace (P3 level)."""
    for ws in ws_mod.get_all_workspaces():
        if agent_id in ws.admin_ids or agent_id == ws.owner_id:
            return True
    return False


def _log_audit(
    agent_id: str, command: str, params: dict,
    result: str, detail: str = "",
) -> None:
    """Log an admin command execution to the audit logger."""
    from .main import _audit_logger
    _audit_logger.log(agent_id, command, params, result, detail)


def _check_command_permission(
    agent_id: str, cmd_name: str, cmd: dict, params: dict,
) -> tuple[bool, str]:
    """Check if agent has permission to run this command."""
    # P4 → always allowed
    if auth.is_global_admin(agent_id):
        return True, ""

    min_role = cmd.get("min_role", 4)
    ws_scope = cmd.get("workspace_scope", False)

    # ── R44 F-12: PM pipeline_start bypass ────────────────
    # Allow any authenticated member to trigger !pipeline_start
    # from the _admin channel. Only this one command is exempted.
    if cmd_name == "pipeline_start" and min_role <= 3:
        return True, ""

    # ── R55 A: step_complete auto-mode bypass ──────────────
    # Any workspace member can advance a pending step in auto mode.
    # The actual step-level validity + mode check happens inside
    # _cmd_step_complete, where we have the round context.
    if cmd_name == "step_complete" and min_role <= 1:
        return True, ""

    # ── R73: Member-level commands (min_role=2) ───────────────
    if min_role <= 2:
        if auth.is_approved(agent_id):
            return True, ""
        return False, "权限不足：仅已认证成员可执行"

    # P3: verify actual workspace admin before allowing ws_scope commands
    if min_role <= 3 and ws_scope:
        if _is_any_workspace_admin(agent_id) or auth.is_global_admin(agent_id):
            return True, ""
        return False, "权限不足：仅工作区管理员或超级管理员可执行"

    if min_role <= 3 and not ws_scope:
        if _is_any_workspace_admin(agent_id):
            return True, ""
        return False, "权限不足：仅工作区管理员或超级管理员可执行"

    return False, "权限不足：管理操作仅限管理员"


def _resolve_workspace(sender_id: str, params: dict) -> tuple[str | None, str]:
    """R82: 确定目标工作区 ID — 仅用 --workspace 参数，不再依赖活跃频道。"""
    ws_id = params.get("workspace", "") or ""
    if not ws_id:
        return (None, "❌ 无法确定工作区。请使用 --workspace <ws_id> 指定。")
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return (None, f"❌ 工作区 {ws_id} 不存在")
    return (ws_id, "")

# ── R99/100: Role-Agent Map Refresh ─────────────────────────────────
logger = __import__('logging').getLogger(__name__)

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
    logger.info("R63 role-agent map refreshed: %d roles, %d entries",
                len(state._ROLE_AGENT_MAP),
                sum(len(v) for v in state._ROLE_AGENT_MAP.values()))
    # R78 A2: 同步写到 Manager 全局快照
    try:
        from .pipeline_context import PipelineContextManager
        mgr = PipelineContextManager.get_instance()
        mgr.set_global_role_map(dict(state._ROLE_AGENT_MAP))
    except Exception:
        pass
