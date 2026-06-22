"""Workspace management — CRUD, state machine, persistence.

A workspace is a named channel with members, lifecycle states, and
automatic archival after inactivity.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import shared.protocol as p

logger = logging.getLogger("ws-bridge.workspace")

from server.config import DATA_DIR
WORKSPACES_FILE = "workspaces.json"


class WorkspaceState(enum.Enum):
    ACTIVE = "active"
    CLOSING = "closing"
    ARCHIVED = "archived"


@dataclass
class TokenRing:
    """Token ring state for workspace message flow control (R10)."""
    mode: str = "free"                    # "token" | "free"
    current_token: int = 0                # index in order that holds the floor
    order: list[str] = field(default_factory=list)  # [agent_id, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TokenRing":
        return cls(**d)


# ── R15: Admin Request ──────────────────────────────────────────


@dataclass
class AdminRequest:
    workspace_id: str
    requester_id: str
    reason: str = ""
    status: str = "pending"          # pending / approved / rejected
    created_at: float = 0.0
    reviewed_at: float | None = None
    reviewed_by: str | None = None
    reject_reason: str = ""

    def key(self) -> str:
        return f"{self.workspace_id}:{self.requester_id}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AdminRequest":
        return cls(**d)


ADMIN_REQUESTS_FILE = "admin_requests.json"
_admin_requests: dict[str, AdminRequest] = {}  # key: f"{ws_id}:{agent_id}"


def _save_admin_requests() -> None:
    """Write admin requests to JSON."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / ADMIN_REQUESTS_FILE
        data = {k: v.to_dict() for k, v in _admin_requests.items()}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to save admin requests: %s", e)


def _load_admin_requests() -> None:
    """Load admin requests from JSON into memory."""
    try:
        path = DATA_DIR / ADMIN_REQUESTS_FILE
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for k, v in data.items():
                _admin_requests[k] = AdminRequest.from_dict(v)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to load admin requests: %s", e)


def submit_admin_request(ws_id: str, agent_id: str, reason: str = "") -> tuple[bool, str]:
    """Submit admin request. Returns (success, message)."""
    key = f"{ws_id}:{agent_id}"
    existing = _admin_requests.get(key)
    if existing and existing.status == "pending":
        return False, "已有待审批的申请"
    req = AdminRequest(
        workspace_id=ws_id,
        requester_id=agent_id,
        reason=reason,
        status="pending",
        created_at=time.time(),
    )
    _admin_requests[key] = req
    _save_admin_requests()
    return True, "申请已提交"


def approve_admin_request(ws_id: str, target_id: str, reviewer_id: str) -> tuple[bool, str]:
    """Approve admin request. Returns (success, message)."""
    key = f"{ws_id}:{target_id}"
    req = _admin_requests.get(key)
    if not req:
        return False, "未找到申请"
    if req.status != "pending":
        return False, f"申请状态不是待审批（当前：{req.status}）"
    req.status = "approved"
    req.reviewed_at = time.time()
    req.reviewed_by = reviewer_id
    _save_admin_requests()
    return True, "审批通过"


def reject_admin_request(ws_id: str, target_id: str, reviewer_id: str, reason: str = "") -> tuple[bool, str]:
    """Reject admin request. Returns (success, message)."""
    key = f"{ws_id}:{target_id}"
    req = _admin_requests.get(key)
    if not req:
        return False, "未找到申请"
    if req.status != "pending":
        return False, f"申请状态不是待审批（当前：{req.status}）"
    req.status = "rejected"
    req.reviewed_at = time.time()
    req.reviewed_by = reviewer_id
    req.reject_reason = reason
    _save_admin_requests()
    return True, "已拒绝"


def get_pending_requests(ws_id: str | None = None) -> list[AdminRequest]:
    """Get all pending requests, optionally filtered by workspace."""
    result = []
    for req in _admin_requests.values():
        if req.status == "pending":
            if ws_id is None or req.workspace_id == ws_id:
                result.append(req)
    return result


def list_workspace_admins(ws_id: str) -> list[dict]:
    """Get workspace admin list with member info."""
    from . import auth
    users = auth.get_users()
    ws = get_workspace(ws_id)
    if not ws:
        return []
    result = []
    for agent_id in ws.members:
        user_info = users.get(agent_id, {})
        name = user_info.get("name", agent_id[:12])
        result.append({
            "agent_id": agent_id,
            "name": name,
            "is_admin": agent_id in ws.admin_ids or agent_id == ws.owner_id,
            "role": user_info.get("role", "member"),
        })
    return result


@dataclass
class Workspace:
    id: str
    name: str
    owner_id: str
    owner_name: str
    state: WorkspaceState = WorkspaceState.ACTIVE
    members: set[str] = field(default_factory=set)
    admin_ids: set[str] = field(default_factory=set)   # R6: workspace admins
    token_ring: TokenRing = field(default_factory=TokenRing)  # R10: token ring
    created_at: float = 0.0
    last_active_at: float = 0.0
    closed_at: float | None = None
    closing_acks: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["token_ring"] = self.token_ring.to_dict()
        d["state"] = self.state.value
        d["members"] = list(self.members)
        d["admin_ids"] = list(self.admin_ids)
        d["closing_acks"] = list(self.closing_acks)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Workspace":
        # Filter to only fields Workspace.__init__ accepts
        # This prevents crashes when JSON has extra fields (e.g. from scripts)
        allowed = {"id", "name", "owner_id", "owner_name", "state",
                   "members", "admin_ids", "token_ring",
                   "created_at", "last_active_at", "closed_at", "closing_acks"}
        extra = [k for k in d if k not in allowed]
        if extra:
            logger.warning("Workspace.from_dict(%s): ignoring unknown fields: %s", d.get("id","?"), extra)
        d["state"] = WorkspaceState(d["state"])
        d["members"] = set(d.get("members", []))
        d["admin_ids"] = set(d.get("admin_ids", []))
        d["closing_acks"] = set(d.get("closing_acks", []))
        tr = d.get("token_ring")
        if tr:
            d["token_ring"] = TokenRing.from_dict(tr)
        else:
            d["token_ring"] = TokenRing()
        clean = {k: v for k, v in d.items() if k in allowed}
        return cls(**clean)


# ── Store ──────────────────────────────────────────────────────────

_lock = asyncio.Lock()
_workspaces: dict[str, Workspace] = {}


def _data_path() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(str(DATA_DIR), WORKSPACES_FILE)


def _load():
    global _workspaces
    path = _data_path()
    if not os.path.exists(path):
        _workspaces = {}
        return
    try:
        with open(path) as f:
            raw = json.load(f)
        _workspaces = {ws_id: Workspace.from_dict(d) for ws_id, d in raw.items()}
        if len(_workspaces) == 0 and raw:
            logger.critical("Loaded 0/%d workspaces from %s — JSON may be corrupted or have incompatible fields!", len(raw), path)
    except Exception as e:
        logger.error("Failed to load workspaces: %s", e)
        _workspaces = {}


def _save():
    path = _data_path()
    raw = {ws_id: ws.to_dict() for ws_id, ws in _workspaces.items()}
    try:
        with open(path, "w") as f:
            json.dump(raw, f, indent=2)
    except Exception as e:
        logger.error("Failed to save workspaces: %s", e)


# ── Init ───────────────────────────────────────────────────────────

def init():
    """Load workspaces and admin requests from disk. Call once on server start."""
    _load()
    _load_admin_requests()
    logger.info("Loaded %d workspaces, %d admin requests from disk", len(_workspaces), len(_admin_requests))


# ── CRUD ───────────────────────────────────────────────────────────

def create_workspace(
    ws_id: str,
    name: str,
    owner_id: str,
    owner_name: str,
) -> Optional[Workspace]:
    """Create a new workspace. Returns None if owner already has an active one."""
    now = time.time()

    # Check max active per person
    active_count = sum(
        1 for w in _workspaces.values()
        if w.owner_id == owner_id and w.state == WorkspaceState.ACTIVE
    )
    max_per_person = 1  # configurable later
    if active_count >= max_per_person:
        logger.warning(
            "Owner %s already has %d active workspaces (max %d)",
            owner_id, active_count, max_per_person,
        )
        return None

    ws = Workspace(
        id=ws_id,
        name=name,
        owner_id=owner_id,
        owner_name=owner_name,
        members={owner_id},
        admin_ids={owner_id},  # R6: owner is automatically admin
        created_at=now,
        last_active_at=now,
    )
    _workspaces[ws_id] = ws
    _save()
    logger.info("Workspace '%s' created by %s (%s)", ws_id, owner_name, owner_id)
    return ws


def get_workspace(ws_id: str) -> Optional[Workspace]:
    return _workspaces.get(ws_id)


def get_workspaces_by_owner(owner_id: str) -> list[Workspace]:
    return [w for w in _workspaces.values() if w.owner_id == owner_id]


def get_workspaces_for_agent(agent_id: str) -> list[Workspace]:
    return [w for w in _workspaces.values() if agent_id in w.members]


def get_all_workspaces() -> list[Workspace]:
    return list(_workspaces.values())


def get_active_workspaces() -> list[Workspace]:
    return [w for w in _workspaces.values() if w.state == WorkspaceState.ACTIVE]


def add_member(ws_id: str, agent_id: str) -> bool:
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    ws.members.add(agent_id)
    _save()
    return True


def remove_member(ws_id: str, agent_id: str) -> bool:
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    ws.members.discard(agent_id)
    _save()
    return True


# ── Admin Management ───────────────────────────────────────────────

def set_admin(ws_id: str, agent_id: str) -> bool:
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    ws.admin_ids.add(agent_id)
    _save()
    logger.info("Agent %s set as admin of workspace '%s'", agent_id[:20], ws_id)
    return True


def remove_admin(ws_id: str, agent_id: str) -> bool:
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    ws.admin_ids.discard(agent_id)
    _save()
    logger.info("Agent %s removed as admin of workspace '%s'", agent_id[:20], ws_id)
    return True


def get_workspace_members(ws_id: str) -> set[str]:
    ws = _workspaces.get(ws_id)
    if not ws:
        return set()
    return ws.members


# ── Token Ring ──────────────────────────────────────────────────

def set_token_mode(ws_id: str, mode: str) -> bool:
    """Set token ring mode (\"token\" or \"free\")."""
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    if mode not in ("token", "free"):
        return False
    ws.token_ring.mode = mode
    _save()
    logger.info("Workspace '%s' token mode → %s", ws_id, mode)
    return True


def set_token_order(ws_id: str, order: list[str]) -> bool:
    """Set token ring order list."""
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    ws.token_ring.order = order[:]
    ws.token_ring.current_token = 0
    _save()
    logger.info("Workspace '%s' token order set: %s", ws_id, order)
    return True


def advance_token(ws_id: str, next_token: int) -> bool:
    """Advance token to a specific index."""
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    if next_token < 0 or next_token >= len(ws.token_ring.order):
        return False
    ws.token_ring.current_token = next_token
    _save()
    logger.info("Workspace '%s' token advanced → %d (%s)",
                ws_id, next_token, ws.token_ring.order[next_token])
    return True


def skip_token(ws_id: str) -> bool:
    """Skip current token: current_token += 1."""
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    next_idx = ws.token_ring.current_token + 1
    if next_idx >= len(ws.token_ring.order):
        return False  # already at end, can't skip further
    ws.token_ring.current_token = next_idx
    _save()
    logger.info("Workspace '%s' token skipped → %d (%s)",
                ws_id, next_idx, ws.token_ring.order[next_idx])
    return True


def can_send_in_token_mode(ws_id: str, agent_id: str, reply_to: str | None) -> tuple[bool, str]:
    """Check if agent can send a message in token mode.

    Returns (allowed: bool, reason: str).
    """
    ws = _workspaces.get(ws_id)
    if not ws:
        return False, "Workspace not found"
    if ws.token_ring.mode == "free":
        return True, ""
    order = ws.token_ring.order
    try:
        idx = order.index(agent_id)
    except ValueError:
        return False, "Not in token order"

    # Index 0 (admin) can always send
    if idx == 0:
        return True, ""

    # Check if this is a reply to a smaller-numbered agent
    if reply_to and reply_to in order:
        reply_idx = order.index(reply_to)
        if reply_idx < idx:
            return True, ""

    # Initiate new topic only if current_token == idx
    if ws.token_ring.current_token == idx:
        return True, ""

    return False, f"发言权当前在 #{ws.token_ring.current_token}（{order[ws.token_ring.current_token]}），请等待轮到你"


def get_token_status(ws_id: str) -> dict | None:
    """Get token ring status dict."""
    ws = _workspaces.get(ws_id)
    if not ws:
        return None
    return {
        "mode": ws.token_ring.mode,
        "current_token": ws.token_ring.current_token,
        "order": ws.token_ring.order,
    }


# ── State Machine ──────────────────────────────────────────────────

def start_closing(ws_id: str) -> bool:
    """Initiate closing of a workspace. Returns False if not found or not ACTIVE."""
    ws = _workspaces.get(ws_id)
    if not ws or ws.state != WorkspaceState.ACTIVE:
        return False
    ws.state = WorkspaceState.CLOSING
    _save()
    logger.info("Workspace '%s' → CLOSING", ws_id)
    return True


def confirm_ack(ws_id: str, agent_id: str) -> bool:
    """Member acknowledges cleaning up."""
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    ws.closing_acks.add(agent_id)
    _save()
    return True


def finalize_close(ws_id: str) -> bool:
    """Finalize: set state to ARCHIVED."""
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    ws.state = WorkspaceState.ARCHIVED
    ws.closed_at = time.time()
    _save()
    logger.info("Workspace '%s' → ARCHIVED", ws_id)
    return True


def force_close(ws_id: str) -> bool:
    """Admin force-close without waiting for ACKs."""
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    # Auto-ack all members
    ws.closing_acks.update(ws.members)
    ws.state = WorkspaceState.ARCHIVED
    ws.closed_at = time.time()
    _save()
    logger.info("Workspace '%s' force-closed", ws_id)
    return True


def touch(ws_id: str) -> bool:
    """Update last_active_at timestamp."""
    ws = _workspaces.get(ws_id)
    if not ws:
        return False
    ws.last_active_at = time.time()
    return True


def check_idle(ws_id: str) -> bool:
    """Check if workspace has been idle beyond TTL. If so, archive it."""
    ws = _workspaces.get(ws_id)
    if not ws or ws.state != WorkspaceState.ACTIVE:
        return False
    if time.time() - ws.last_active_at >= p.WORKSPACE_IDLE_TTL:
        ws.state = WorkspaceState.ARCHIVED
        ws.closed_at = time.time()
        _save()
        logger.info("Workspace '%s' auto-archived after %ds idle", ws_id, p.WORKSPACE_IDLE_TTL)
        return True
    return False


def can_create_for(owner_id: str, max_active: int = 1) -> bool:
    """Check if owner can create a new workspace."""
    active_count = sum(
        1 for w in _workspaces.values()
        if w.owner_id == owner_id and w.state == WorkspaceState.ACTIVE
    )
    return active_count < max_active


# ── Cleanup ────────────────────────────────────────────────────────

ARCHIVED_RETENTION_DAYS = 7  # R6: 7 days after close


def cleanup_archived(max_age_days: int = ARCHIVED_RETENTION_DAYS):
    """Remove archived workspaces older than max_age_days and their message stores."""
    now = time.time()
    cutoff = now - max_age_days * 86400
    to_delete = [
        ws_id for ws_id, ws in _workspaces.items()
        if ws.state == WorkspaceState.ARCHIVED and ws.closed_at and ws.closed_at < cutoff
    ]
    for ws_id in to_delete:
        # Clear message store for this channel
        from . import message_store as ms
        try:
            ms.clear_messages_by_channel(ws_id, DATA_DIR)
        except Exception:
            pass
        del _workspaces[ws_id]
    if to_delete:
        _save()
        logger.info("Cleaned up %d archived workspaces (max_age=%dd)", len(to_delete), max_age_days)


# ── R12 P0.4: Workspace Ready Notification ──────────────────────────────


def build_workspace_ready(ws_id: str, name: str, owner_name: str, members: set[str]) -> dict:
    """Build workspace_ready notification payload."""
    return {
        "type": "workspace_ready",
        "workspace_id": ws_id,
        "name": name,
        "owner_name": owner_name,
        "members": list(members),
        "ts": time.time(),
    }


# R15: expose admin requests store for CLI
def get_admin_requests() -> dict[str, AdminRequest]:
    return _admin_requests
