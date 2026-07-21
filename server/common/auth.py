"""双进程认证 — api_key 验证、权限检查、agent 名称解析。
所有持久化通过 server.common.persistence 完成，不依赖 WS 运行时状态。
"""
import hashlib
import os
import secrets

from server.common import persistence

_SIGNING_KEY = os.environ.get("WS_API_SIGNING_KEY", secrets.token_hex(32))


def is_approved(agent_id: str) -> bool:
    """Check if agent is approved (approved_users or api_keys)."""
    if agent_id in persistence.get_approved_users():
        return True
    api_keys = persistence.get_api_keys()
    return agent_id in api_keys


def get_users() -> dict:
    return persistence.get_approved_users()


def is_workspace_admin(ws_id: str, agent_id: str) -> bool:
    """Check if agent is an admin of the given workspace.
    Uses lazy import of workspace module to avoid import-time dependency.
    """
    try:
        from server.ws_server import workspace as ws_mod
        ws = ws_mod.get_workspace(ws_id)
        if not ws:
            return False
        return agent_id in ws.admin_ids or agent_id == ws.owner_id
    except (ImportError, Exception):
        return False


def is_global_admin(agent_id: str) -> bool:
    """Check if agent is a global admin (L4)."""
    users = get_users()
    return users.get(agent_id, {}).get("role") == "admin"


def can_manage_workspace(ws_id: str, agent_id: str) -> bool:
    """Check if agent can manage a workspace (global admin or workspace admin)."""
    return is_global_admin(agent_id) or is_workspace_admin(ws_id, agent_id)


def set_workspace_admin(ws_id: str, agent_id: str, by_agent: str) -> bool:
    """Global admin by_agent appoints agent_id as workspace admin."""
    if not is_global_admin(by_agent):
        return False
    from server.ws_server import workspace as ws_mod
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return False
    ws_mod.set_admin(ws_id, agent_id)
    return True


# ── R72: API Key 核心逻辑 ────────────────────────────────────


def generate_agent_id() -> str:
    """生成 ws-bridge 自有 agent_id，格式 ws_{12位随机hex}"""
    return "ws_" + secrets.token_hex(6)


def create_api_key(agent_id: str) -> str:
    """生成 api_key，格式 sk_ws_{sha256(agent_id + signing_key + nonce)[:32]}"""
    nonce = secrets.token_hex(8)
    raw = f"{agent_id}:{_SIGNING_KEY}:{nonce}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"sk_ws_{key_hash}"


def validate_api_key(api_key: str) -> str | None:
    """验证 api_key 并返回对应的 agent_id，无效返回 None"""
    if not api_key.startswith("sk_ws_") or len(api_key) < 37:
        return None
    keys = persistence.get_api_keys()
    for agent_id, record in keys.items():
        if record.get("api_key") == api_key and record.get("status") != "revoked":
            return agent_id
    return None


def revoke_api_key(agent_id: str) -> bool:
    """吊销 agent 的 api_key"""
    keys = persistence.get_api_keys()
    if agent_id not in keys:
        return False
    keys[agent_id]["status"] = "revoked"
    persistence.set_api_keys(keys)
    return True


# ── R76: Agent ID → display name resolver ─────────────────


def get_level(agent_id: str) -> int:
    """返回 agent 的权限等级 (1-4)。"""
    record = persistence.get_api_key_record(agent_id)
    if record is None:
        return 1
    return record.get("level", 4)


def set_level(agent_id: str, new_level: int) -> bool:
    """设置 agent 的 level 字段并持久化。"""
    keys = persistence.get_api_keys()
    if agent_id not in keys:
        return False
    keys[agent_id]["level"] = new_level
    persistence.set_api_keys(keys)
    from server.common.config import DATA_DIR
    persistence.save_api_keys(DATA_DIR)
    return True


def get_agent_name(agent_id: str, default: str | None = None) -> str:
    """Return display name for an agent_id.

    Priority:
    1. Traditional approved users (pre-R72)
    2. api_keys display_name
    3. Truncated agent_id as fallback
    """
    users = get_users()
    name = users.get(agent_id, {}).get("name")
    if name:
        return name
    record = persistence.get_api_key_record(agent_id)
    if record:
        return record.get("display_name", default or agent_id[:12])
    return default or agent_id[:12]
