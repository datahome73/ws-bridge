"""Hermes WS Bridge - WebSocket broadcast server config."""
import os
from pathlib import Path

HOST = os.environ.get("WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_PORT") or os.environ.get("PORT", "8765"))
HTTP_PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8765"))
APP_ID = os.environ.get("WS_APP_ID", "hermes-ws")
DATA_DIR = Path(os.environ.get("WS_DATA_DIR", "./data"))
CHAT_LOG_DIR = DATA_DIR / "chat_logs"
BROADCAST_ADMINS: set[str] = set(
    filter(None, os.environ.get("BROADCAST_ADMINS", "").split(","))
)


ADMIN_AGENTS: set[str] = set(
    filter(None, os.environ.get("WS_ADMIN_AGENTS", "").split(","))
)


# ── R40: GitHub OAuth ─────────────────────────────────────────
GITHUB_OAUTH_CLIENT_ID=os.environ.get("GITHUB_OAUTH_CLIENT_ID", "")
GITHUB_OAUTH_CLIENT_SECRET=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "")
GITHUB_OAUTH_REDIRECT_URI=os.environ.get("GITHUB_OAUTH_REDIRECT_URI",
    os.environ.get("WS_PUBLIC_URL", "http://0.0.0.0:8765") + "/auth/github/callback",
)
# Map from GitHub username → bridge display name, JSON dict format
OAUTH_NAME_MAP: dict[str, str] = {}
_raw = os.environ.get("OAUTH_NAME_MAP", "")
if _raw.strip():
    import json as _json
    try:
        OAUTH_NAME_MAP.update(_json.loads(_raw))
    except _json.JSONDecodeError:
        pass

# ── R41 A: Web auth environment distinction ─────────────────────
WS_ENV = os.environ.get("WS_ENV", "dev")  # "dev" | "production"
IS_PRODUCTION = WS_ENV == "production"
