"""JSON file-backed persistence for pairing codes and approved users.

Thread-safe: all reads/writes go through threading.Lock with atomic file writes.
"""
import json
import threading
import os
from pathlib import Path

_pairing_codes: dict = {}
_approved_users: dict = {}
_web_bind_codes: dict = {}
_web_sessions: dict = {}

_lock = threading.Lock()


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_json_atomic(path: Path, data: dict) -> None:
    """Atomic write: write to temp file then rename."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.rename(path)


def load_pairing_codes(data_dir: Path) -> None:
    global _pairing_codes
    _pairing_codes = _load_json(data_dir / "_pairing_codes.json")


def save_pairing_codes(data_dir: Path) -> None:
    with _lock:
        _save_json_atomic(data_dir / "_pairing_codes.json", _pairing_codes)


def load_approved_users(data_dir: Path) -> None:
    global _approved_users
    _approved_users = _load_json(data_dir / "_approved_users.json")


def save_approved_users(data_dir: Path) -> None:
    with _lock:
        _save_json_atomic(data_dir / "_approved_users.json", _approved_users)


def get_pairing_codes() -> dict:
    with _lock:
        return dict(_pairing_codes)


def set_pairing_codes(codes: dict) -> None:
    global _pairing_codes
    with _lock:
        _pairing_codes = dict(codes)


def get_approved_users() -> dict:
    with _lock:
        return dict(_approved_users)


def set_approved_users(users: dict) -> None:
    global _approved_users
    with _lock:
        _approved_users = dict(users)


# ── Web viewer bind codes & sessions ──────────────────────────────


def load_web_bind_codes(data_dir: Path) -> None:
    global _web_bind_codes
    _web_bind_codes = _load_json(data_dir / "_web_bind_codes.json")


def save_web_bind_codes(data_dir: Path) -> None:
    with _lock:
        _save_json_atomic(data_dir / "_web_bind_codes.json", _web_bind_codes)


def load_web_sessions(data_dir: Path) -> None:
    global _web_sessions
    _web_sessions = _load_json(data_dir / "_web_sessions.json")


def save_web_sessions(data_dir: Path) -> None:
    with _lock:
        _save_json_atomic(data_dir / "_web_sessions.json", _web_sessions)


def get_web_bind_codes() -> dict:
    with _lock:
        return dict(_web_bind_codes)


def set_web_bind_codes(codes: dict) -> None:
    global _web_bind_codes
    with _lock:
        _web_bind_codes = dict(codes)


def get_web_sessions() -> dict:
    with _lock:
        return dict(_web_sessions)


def set_web_sessions(sessions: dict) -> None:
    global _web_sessions
    with _lock:
        _web_sessions = dict(sessions)

# ── R68: Inbox channel helpers ─────────────────────────────────
def get_inbox_channel(agent_id: str) -> str:
    """Get agent's dedicated inbox channel ID."""
    import shared.protocol as p
    return f"{p.INBOX_CHANNEL_PREFIX}{agent_id}"

def is_inbox_channel(channel: str) -> bool:
    """Check if a channel ID is an inbox channel."""
    import shared.protocol as p
    return channel.startswith(p.INBOX_CHANNEL_PREFIX)

def resolve_inbox_owner(channel: str) -> str | None:
    """Extract agent_id from inbox channel ID, or None."""
    import shared.protocol as p
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
        return channel[len(p.INBOX_CHANNEL_PREFIX):]
    return None


# ── R82: Workspace store accessor ──────────────────────────────


def workspace_store():
    """Return reference to workspace module for cross-module queries.
    Delayed import to avoid circular dependency.
    """
    from server import workspace as _ws
    return _ws


# ── R72: API Key storage ──────────────────────────────────────────
_api_keys: dict = {}  # agent_id → {api_key, display_name, created_at, ...}


def load_api_keys(data_dir: Path) -> None:
    global _api_keys
    _api_keys = _load_json(data_dir / "_api_keys.json")


def save_api_keys(data_dir: Path) -> None:
    with _lock:
        _save_json_atomic(data_dir / "_api_keys.json", _api_keys)


def get_api_keys() -> dict:
    with _lock:
        return dict(_api_keys)


def set_api_keys(keys: dict) -> None:
    global _api_keys
    with _lock:
        _api_keys = dict(keys)
