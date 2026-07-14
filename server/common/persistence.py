"""双进程共享持久化 — api_keys + approved_users（只读）+ inbox helpers。

线程安全：所有读写通过 threading.Lock + 原子文件写入。
"""
import json
import threading
from pathlib import Path

_lock = threading.Lock()

_api_keys: dict = {}  # agent_id → {api_key, display_name, created_at, ...}
_approved_users: dict = {}  # agent_id → {name, role, ...}


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


# ── api_keys ──────────────────────────────────────────────────────────


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


def get_api_key_record(agent_id: str) -> dict | None:
    with _lock:
        return _api_keys.get(agent_id)


# ── approved_users（双进程只读）─────────────────────────────────────────


def load_approved_users(data_dir: Path) -> None:
    global _approved_users
    _approved_users = _load_json(data_dir / "_approved_users.json")


def get_approved_users() -> dict:
    with _lock:
        return dict(_approved_users)


# ── 保存 approved_users（仅 web-ui 写，但函数放共享层以便调用）───────────


def save_approved_users(data_dir: Path) -> None:
    with _lock:
        _save_json_atomic(data_dir / "_approved_users.json", _approved_users)


def set_approved_users(users: dict) -> None:
    global _approved_users
    with _lock:
        _approved_users = dict(users)


# ── Inbox channel helpers ─────────────────────────────────────────────


def get_inbox_channel(agent_id: str) -> str:
    import shared.protocol as p
    return f"{p.INBOX_CHANNEL_PREFIX}{agent_id}"


def is_inbox_channel(channel: str) -> bool:
    import shared.protocol as p
    return channel.startswith(p.INBOX_CHANNEL_PREFIX)


def resolve_inbox_owner(channel: str) -> str | None:
    import shared.protocol as p
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
        return channel[len(p.INBOX_CHANNEL_PREFIX):]
    return None

# ── Web sessions (shared between WSS core and Web UI) ──────────────
_web_sessions: dict = {}


def load_web_sessions(data_dir: Path) -> None:
    global _web_sessions
    _web_sessions = _load_json(data_dir / "_web_sessions.json")


def save_web_sessions(data_dir: Path) -> None:
    with _lock:
        _save_json_atomic(data_dir / "_web_sessions.json", _web_sessions)


def get_web_sessions() -> dict:
    with _lock:
        return dict(_web_sessions)


def set_web_sessions(sessions: dict) -> None:
    global _web_sessions
    with _lock:
        _web_sessions = dict(sessions)
