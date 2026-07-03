"""WS Bridge Gateway Plugin — protocol constants."""
### ── Message Types ──────────────────────────────────────────────

MSG_AUTH = "auth"                    # Client → Server: authenticate
MSG_AUTH_OK = "auth_ok"              # Server → Client: auth success
MSG_AUTH_ERROR = "auth_error"        # Server → Client: auth failure
MSG_PAIRING_CODE = "pairing_code"
MSG_MESSAGE = "message"              # Client → Server: send a message
MSG_BROADCAST = "broadcast"          # Server → Client: receive a broadcast
MSG_ACK = "ack"                      # Server → Client: message acknowledged
MSG_PONG = "pong"
MSG_ERROR = "error"

### ── Workspace / Channel ──────────────────────────────────────────
MSG_WORKSPACE_CLOSING = "workspace_closing"
MSG_WORKSPACE_ACK_CLOSE = "workspace_ack_close"
MSG_SET_ACTIVE_CHANNEL = "set_active_channel"
MSG_CHANNEL_UPDATED = "channel_updated"

### ── Field Names ────────────────────────────────────────────────
FIELD_CHANNEL = "channel"
FIELD_ACTIVE_CHANNEL = "active_channel"
FIELD_WORKSPACE_ID = "workspace_id"

### ── Connection / Reconnect ────────────────────────────────────
PING_INTERVAL = 20
RECONNECT_BASE_DELAY = 3.0
RECONNECT_MAX_DELAY = 300  # 5 minutes


def normalize_ws_url(raw: str) -> str:
    """Normalize a URL to WebSocket scheme."""
    raw = raw.strip().rstrip("/")
    if raw.startswith("http://"):
        raw = raw.replace("http://", "ws://", 1)
    elif raw.startswith("https://"):
        raw = raw.replace("https://", "wss://", 1)
    elif not raw.startswith("ws://") and not raw.startswith("wss://"):
        raw = f"wss://{raw}"
    return raw
