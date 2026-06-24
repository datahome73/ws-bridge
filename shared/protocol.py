import os
"""WS Bridge shared protocol constants and message types.

All clients and the server should reference this file for consistent
message field names and protocol constants.
"""

import os
# ── Message Types ────────────────────────────────────────────────

MSG_AUTH="***"           # Client → Server: authenticate
MSG_AUTH_OK="***"     # Server → Client: auth success
MSG_AUTH_ERROR="***"
MSG_PAIRING_CODE = "pairing_code"
MSG_APPROVE = "approve"
MSG_APPROVE_OK = "approve_ok"
MSG_APPROVE_ERROR = "approve_error"
MSG_MESSAGE = "message"    # Client → Server: send a message
MSG_BROADCAST = "broadcast"  # Server → Client: receive a broadcast
MSG_OFFLINE = "offline_messages"  # Server → Client: offline catchup batch
MSG_ACK = "ack"            # Server → Client: message acknowledged
MSG_PING = "ping"
MSG_PONG = "pong"
MSG_ERROR = "error"

# ── Field Names ──────────────────────────────────────────────────

FIELD_FROM_NAME = "from_name"     # Unified sender display name
FIELD_AGENT_ID = "agent_id"       # Unified sender agent ID
FIELD_CONTENT = "content"
FIELD_TS = "ts"
FIELD_TYPE = "type"

# Legacy field names (compat, prefer FIELD_* above)
FIELD_FROM = "from"               # Legacy sender name
FIELD_FROM_AGENT = "from_agent"   # Legacy sender agent ID

# ── Defaults ─────────────────────────────────────────────────────

DEFAULT_APP_ID = "298621237"
PING_INTERVAL = 20
ACK_TIMEOUT = 5.0
MAX_RETRIES = 2
RECONNECT_BASE_DELAY = 3.0
RECONNECT_MAX_DELAY = 300  # 5 minutes

# ── Auth / Role ──────────────────────────────────────────────────

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
PAIRING_CODE_TTL = 300  # 5 minutes


# ── Workspace / Channel Types ──────────────────────────────────────
MSG_WORKSPACE_CREATE = "workspace_create"
MSG_WORKSPACE_CREATE_APPROVED = "workspace_create_approved"
MSG_WORKSPACE_CLOSE = "workspace_close"
MSG_WORKSPACE_CLOSING = "workspace_closing"
MSG_WORKSPACE_ACK_CLOSE = "workspace_ack_close"

MSG_WORKSPACE_ADD_MEMBER = "workspace_add_member"
MSG_WORKSPACE_MEMBER_ADDED = "workspace_member_added"
MSG_WORKSPACE_REMOVE_MEMBER = "workspace_remove_member"
MSG_WORKSPACE_MEMBER_REMOVED = "workspace_member_removed"
MSG_WORKSPACE_ERROR = "workspace_error"
FIELD_MEMBER_ID = "member_id"
FIELD_TARGET_AGENT_ID = "target_agent_id"
FIELD_ACTION = "action"

# ── R6: Workspace Admin Messages ────────────────────────────────────────
MSG_SET_ADMIN = "workspace_set_admin"        # Set workspace admin
MSG_ADMIN_SET = "workspace_admin_set"        # Confirm admin set
MSG_MANAGE_MEMBER = "workspace_manage_member" # Add/remove member in workspace
# ── R7: Active Channel Messages ──────────────────────────────────────────
MSG_SET_ACTIVE_CHANNEL = "set_active_channel"  # Server → Bot: update active channel
MSG_CHANNEL_UPDATED = "channel_updated"        # Server confirm channel updated

# ── R15: Workspace admin request ─────────────────────────────────────────
MSG_ADMIN_REQUEST = "workspace_admin_request"              # Member → Server: apply
MSG_ADMIN_REQUEST_APPROVED = "workspace_admin_approved"    # Admin → Server → Member: approved
MSG_ADMIN_REQUEST_REJECTED = "workspace_admin_rejected"    # Admin → Server → Member: rejected
MSG_ADMIN_NOTIFICATION = "workspace_admin_notification"    # Server → All members: notification

# ── R12: Task Assignment ────────────────────────────────────────────────
MSG_TASK_ASSIGNMENT = "task_assignment"   # Admin → Server → Target: assign task
MSG_TASK_ACK = "task_ack"                # Target → Server → Admin: confirm/reject
MSG_WORKSPACE_READY = "workspace_ready"  # Server → All members: workspace created
MSG_STAGE_COMPLETED = "stage_completed"  # Server → Next holder: stage done
MSG_RATE_LIMITED = "rate_limited"        # Server → Sender: rate limited

# ── R29: Task Switch & Workspace Reset ───────────────────────────────────
MSG_TASK_SWITCH = "task_switch"              # Admin → Server: fire-and-forget, reset target to lobby
MSG_WORKSPACE_RESET = "workspace_reset"      # Admin → Server: reset agent(s) to lobby

# ── R12: Task Assignment Fields ─────────────────────────────────────────
FIELD_TARGET_AGENT = "target_agent"       # Target agent name
FIELD_TARGET_AGENT_ID = "target_agent_id" # Target agent ID
FIELD_TASK_STATUS = "status"              # "accepted" | "rejected"
FIELD_TASK_REASON = "reason"              # Rejection reason
FIELD_TASK_STEP = "step"                  # Step name (e.g. "Step 1 需求调研")
FIELD_TASK_DESC = "description"           # Task description
FIELD_TASK_DEADLINE = "deadline"          # Optional deadline
FIELD_TASK_ID = "task_id"                 # Identifies which assignment this ack is for
FIELD_NEXT_HOLDER = "next_holder"         # Next token holder for stage_completed
FIELD_NEXT_STAGE = "next_stage"           # Next stage name
FIELD_RETRY_AFTER = "retry_after"         # Rate limit retry seconds


# ── R11: Delivery confirmation + status ─────────────────────────────────────
MSG_DELIVERY_STATUS = "delivery_status"  # Server → Admin: delivery report
FIELD_DELIVERY_STATUS = "status"         # "sent" | "read"
DELIVERY_SENT = "sent"
DELIVERY_READ = "read"

# ── R11: Mentions / task assignment ────────────────────────────────────────
FIELD_MENTIONS = "mentions"
FIELD_IS_TASK = "is_task_assignment"

# ── R11: Membership changes ────────────────────────────────────────────────
MSG_MEMBER_CHANGED = "member_changed"
MSG_WORKSPACE_ASSIGNED = "workspace_assigned"
FIELD_MEMBER_EVENT = "event"  # "joined" | "removed"

# ── R10: Token Ring ───────────────────────────────────────────────────────
MSG_TOKEN_SET_MODE="***"       # Admin → Server: set token/free mode
MSG_TOKEN_MODE_SET="***"        # Server → Admin: confirm mode set
MSG_TOKEN_SET_ORDER="***"      # Admin → Server: set order
MSG_TOKEN_ORDER_SET="***"      # Server → Admin: confirm order set
MSG_TOKEN_ADVANCE="***"          # Admin → Server: advance token
MSG_TOKEN_ADVANCED="***"        # Server → Admin: confirm advance
MSG_TOKEN_SKIP="***"               # Admin → Server: skip current
MSG_TOKEN_SKIPPED="***"          # Server → Admin: confirm skip
MSG_TOKEN_STATUS="***"           # Any → Server: query status
MSG_TOKEN_STATUS_RESULT="***"  # Server → Any: status response
FIELD_TOKEN_MODE="***"                    # "token" | "free"
FIELD_TOKEN_CURRENT="***"        # int
FIELD_TOKEN_ORDER="***"                  # list[str]
FIELD_TOKEN_REPLY_TO="***"            # str | None

# ── Workspace / Channel Fields ────────────────────────────────────
FIELD_CHANNEL = "channel"
FIELD_ACTIVE_CHANNEL = "active_channel"
FIELD_WORKSPACE_ID = "workspace_id"
FIELD_DEADLINE_TS = "deadline_ts"
FIELD_ACK_REQUIRED = "ack_required"
FIELD_MEMBERS = "members"
FIELD_REASON = "reason"
FIELD_OWNER_ID = "owner_id"
FIELD_OWNER_NAME = "owner_name"

# ── Workspace / Channel Defaults ──────────────────────────────────
LOBBY = "lobby"
WORKSPACE_ID_PREFIX = "ws:"
WORKSPACE_CLOSING_TIMEOUT = 30  # seconds
WORKSPACE_IDLE_TTL = 48 * 3600  # 48h


# ── R23: Registration Channel (P0→P1 upgrade) ──────────────────────
REGISTRATION_CHANNEL = "__registration__"
MSG_REGISTER_AGENT = "register_agent"
MSG_REGISTRATION_CONFIRMED = "registration_confirmed"
ROLE_UNREGISTERED = "unregistered"

# ── R35: Admin Channel ──────────────────────────────────────────
ADMIN_CHANNEL = "_admin"
MSG_ADMIN_AUDIT = "admin_audit"    # Server → Web: audit feed

# ── R37: Rollcall & Workspace-Lifecycle ──────────────────────────────────
MSG_ROLLCALL_CONFIRM = "rollcall_confirm"   # Agent → Server: rollcall channel confirm
MSG_ROLLCALL_VERIFY = "rollcall_verify"     # Server → Agent: rollcall verification

# ── R38: Task State Machine ───────────────────────────────────────────
from enum import Enum

class TaskState(str, Enum):
    """Task lifecycle states — pure-rule transitions enforced server-side."""
    SUBMITTED = "submitted"          # ⬜ 已排入流水线，等待执行者
    WORKING = "working"              # ▶ 正在处理
    COMPLETED = "completed"          # ✅ 完成（终态）
    FAILED = "failed"                # ❌ 锁定失败（终态）
    CANCELED = "canceled"            # ⛔ 已取消（终态）
    INPUT_REQUIRED = "input_required"  # 🟡 退回修复

# Valid state transitions (pure-rule matrix per §2.1 requirements)
TASK_VALID_TRANSITIONS = {
    TaskState.SUBMITTED:       {TaskState.WORKING},
    TaskState.WORKING:         {TaskState.COMPLETED, TaskState.INPUT_REQUIRED,
                                 TaskState.FAILED, TaskState.CANCELED},
    TaskState.INPUT_REQUIRED:  {TaskState.WORKING, TaskState.FAILED},
    # COMPLETED, FAILED, CANCELED are terminal — no outgoing transitions
}

# State → display icon mapping (for WORK_PLAN alignment)
TASK_STATE_ICONS = {
    "submitted": "⬜",
    "working": "▶",
    "completed": "✅",
    "failed": "❌",
    "canceled": "⛔",
    "input_required": "🟡",
}

# R38: Task state machine message types
MSG_TASK_CREATE = "task_create"    # Create new Task instance
MSG_TASK_UPDATE = "task_update"    # Update Task state (validated transition)
MSG_TASK_QUERY = "task_query"      # Query Tasks by context
MSG_TASK_NOTIFY = "task_notify"    # Push notification on state change

# R38: Task-specific field constants
FIELD_CONTEXT_ID = "context_id"       # Round ID (e.g. "R38")
FIELD_TASK_STATE = "state"            # Current TaskState value
FIELD_TASK_NAME = "name"              # Task display name
FIELD_ASSIGNED_ROLE = "assigned_role" # Executor role ID
FIELD_OUTPUT_REFS = "output_refs"     # Output references (JSON array)
FIELD_REJECT_COUNT = "reject_count"   # Rejection counter (max 2)

# Max reject count before auto-FAILED (§2.1 requirements)
TASK_REJECT_CEILING = 2


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


def make_message(content: str, msg_id: str = "") -> dict:
    """Build a minimal message payload."""
    payload: dict = {"type": MSG_MESSAGE, FIELD_CONTENT: content}
    if msg_id:
        payload["id"] = msg_id
    return payload


def make_broadcast(from_id: str, from_name: str, content: str, ts: float) -> dict:
    """Build a broadcast payload with unified field names."""
    return {
        FIELD_TYPE: MSG_BROADCAST,
        FIELD_AGENT_ID: from_id,
        FIELD_FROM_NAME: from_name,
        FIELD_CONTENT: content,
        FIELD_TS: ts,
    }


def make_broadcast_legacy(from_id: str, from_name: str, content: str, ts: float) -> dict:
    """Build a broadcast payload with legacy field names (for backward compat)."""
    return {
        FIELD_TYPE: MSG_BROADCAST,
        FIELD_FROM: from_name,
        FIELD_FROM_AGENT: from_id,
        FIELD_CONTENT: content,
        FIELD_TS: ts,
    }


def make_ack(msg_id: str) -> dict:
    """Build an ACK response."""
    return {"type": MSG_ACK, "id": msg_id}