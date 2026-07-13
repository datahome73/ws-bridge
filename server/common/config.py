"""双进程共享配置 — 仅 env 读取，无逻辑。"""
import os
from pathlib import Path

HOST = os.environ.get("WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_PORT") or os.environ.get("PORT", "8765"))
HTTP_PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8765"))
APP_ID = os.environ.get("WS_APP_ID", "hermes-ws")
DATA_DIR = Path(os.environ.get("WS_DATA_DIR", "./data"))

ADMIN_AGENTS: set[str] = set(
    filter(None, os.environ.get("WS_ADMIN_AGENTS", "").split(","))
)
HIDDEN_AGENTS: set[str] = set(
    filter(None, os.environ.get("WS_HIDDEN_AGENTS", "bot-hermes").split(","))
)

WS_ENV = os.environ.get("WS_ENV", "dev")
IS_PRODUCTION = WS_ENV == "production"

SERVER_INBOX_CHANNEL = "_inbox:server"
DISPATCH_SENDER_ID: str = os.environ.get(
    "DISPATCH_SENDER_ID",
    os.environ.get("WS_PM_AGENT_ID", ""),
)
