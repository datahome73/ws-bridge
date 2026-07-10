"""Agent authentication and permission checking."""
import hashlib
import os
import secrets

from . import persistence


def is_approved(agent_id: str) -> bool:
    """Check if agent is approved."""
    # R73: Check approved users first
    if agent_id in persistence.get_approved_users():
        return True
    # R73: Agents registered via R72 api_key are also considered approved
    api_keys = persistence.get_api_keys()
    return agent_id in api_keys


def get_users() -> dict:
    return persistence.get_approved_users()


def is_workspace_admin(ws_id: str, agent_id: str) -> bool:
    """Check if agent is an admin of the given workspace."""
    from . import workspace as ws_mod
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return False
    return agent_id in ws.admin_ids or agent_id == ws.owner_id


def is_global_admin(agent_id: str) -> bool:
    """Check if agent is a global admin (L4)."""
    users = get_users()
    return users.get(agent_id, {}).get("role") == "admin"


def can_manage_workspace(ws_id: str, agent_id: str) -> bool:
    """Check if agent can manage a workspace (global admin or workspace admin)."""
    return is_global_admin(agent_id) or is_workspace_admin(ws_id, agent_id)


def set_workspace_admin(ws_id: str, agent_id: str, by_agent: str) -> bool:
    """Global admin by_agent appoints agent_id as workspace admin. Returns False if not authorized."""
    if not is_global_admin(by_agent):
        return False
    from . import workspace as ws_mod
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return False
    ws_mod.set_admin(ws_id, agent_id)
    return True


# ── R72: API Key 核心逻辑 ────────────────────────────────────────

# 服务端签名密钥（从环境变量读取，保底用随机值）
_SIGNING_KEY = os.environ.get("WS_API_SIGNING_KEY", secrets.token_hex(32))


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
    from . import persistence
    keys = persistence.get_api_keys()
    for agent_id, record in keys.items():
        if record.get("api_key") == api_key and record.get("status") != "revoked":
            return agent_id
    return None


def revoke_api_key(agent_id: str) -> bool:
    """吊销 agent 的 api_key"""
    from . import persistence
    keys = persistence.get_api_keys()
    if agent_id not in keys:
        return False
    keys[agent_id]["status"] = "revoked"
    persistence.set_api_keys(keys)
    return True


# ── R76: Agent ID → display name resolver ──────────────────────────


def get_agent_name(agent_id: str, default: str | None = None) -> str:
    """Return display name for an agent_id.

    Priority:
    1. Traditional users (pre-R72)
    2. R72 users (registered via api_key, stored in handler._r72_users)
    3. Truncated agent_id as fallback (e.g. 'ws_xxxxxxxxxxxx')
    """
    users = get_users()
    name = users.get(agent_id, {}).get("name")
    if name:
        return name
    try:
        from . import handler as _handler
        r72 = getattr(_handler, "_r72_users", {})
        return r72.get(agent_id, {}).get("name", default or agent_id[:12])
    except ImportError:
        return default or agent_id[:12]
