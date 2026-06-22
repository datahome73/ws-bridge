"""Pairing code generation and approval logic."""
import secrets
import string
import time

from . import persistence

PAIRING_CODE_TTL = 300  # 5 minutes


def _code_expired(entry: dict) -> bool:
    """Check if a pairing code entry has expired."""
    created = entry.get("created_at", 0)
    return time.time() - created > PAIRING_CODE_TTL


def generate_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(8))


def create_pairing_code(agent_id: str, app_id: str, name: str, code: str) -> None:
    codes = persistence.get_pairing_codes()
    codes[code] = {
        "agent_id": agent_id,
        "app_id": app_id,
        "name": name,
        "created_at": time.time(),
    }
    persistence.set_pairing_codes(codes)


def approve(code: str, role: str = "member") -> dict:
    codes = persistence.get_pairing_codes()
    if code not in codes:
        return {"type": "approve_error", "error": "Code not found or expired"}

    entry = codes[code]
    if _code_expired(entry):
        del codes[code]
        persistence.set_pairing_codes(codes)
        return {"type": "approve_error", "error": "Code expired"}

    agent_id = entry["agent_id"]
    users = persistence.get_approved_users()
    users[agent_id] = {"name": entry.get("name", agent_id), "role": role}
    persistence.set_approved_users(users)
    del codes[code]
    persistence.set_pairing_codes(codes)
    return {"type": "approve_ok", "agent_id": agent_id}


def cleanup_expired_codes() -> int:
    """Remove expired pairing codes. Returns count of removed codes."""
    codes = persistence.get_pairing_codes()
    expired = [code for code, entry in codes.items() if _code_expired(entry)]
    for code in expired:
        del codes[code]
    if expired:
        persistence.set_pairing_codes(codes)
    return len(expired)


def is_approved(agent_id: str) -> bool:
    return agent_id in persistence.get_approved_users()


def get_users() -> dict:
    return persistence.get_approved_users()


# ── R6: Role Level System ──────────────────────────────────────────────


def role_level(agent_id: str) -> int:
    """Return role level: 4=global_admin, 3=workspace_admin, 2=member, 1=observer."""
    users = get_users()
    user = users.get(agent_id, {})
    if user.get("role") == "admin":
        return 4
    return 2  # All authenticated agents default to L2 member


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


# ── Web viewer bind codes ──────────────────────────────

WEB_CODE_PREFIX = "WEB-"


def generate_web_bind_code() -> str:
    """Generate a web viewer bind code (e.g. WEB-A1B2)."""
    chars = string.ascii_uppercase + string.digits
    return WEB_CODE_PREFIX + "".join(secrets.choice(chars) for _ in range(4))


def create_web_bind_code(code: str) -> None:
    """Create a bind code entry awaiting admin approval."""
    codes = persistence.get_web_bind_codes()
    codes[code] = {
        "created_at": time.time(),
        "approved": False,
    }
    persistence.set_web_bind_codes(codes)


def approve_web_bind_code(code: str, name: str = "大宏") -> dict:
    """Admin approves a web bind code. Returns a session token."""
    import hashlib

    codes = persistence.get_web_bind_codes()
    if code not in codes:
        return {"type": "error", "error": "Bind code not found"}
    if codes[code].get("approved"):
        return {"type": "error", "error": "Already approved"}
    if _code_expired(codes[code]):
        del codes[code]
        persistence.set_web_bind_codes(codes)
        return {"type": "error", "error": "Bind code expired"}

    # Generate session token
    raw = f"{code}:{name}:{time.time()}:{secrets.token_hex(8)}"
    token = hashlib.sha256(raw.encode()).hexdigest()

    sessions = persistence.get_web_sessions()
    sessions[token] = {
        "name": name,
        "created_at": time.time(),
    }
    persistence.set_web_sessions(sessions)

    codes[code]["approved"] = True
    codes[code]["token"] = token
    codes[code]["name"] = name
    persistence.set_web_bind_codes(codes)

    return {"type": "approve_ok", "token": token, "name": name}
