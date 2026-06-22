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
