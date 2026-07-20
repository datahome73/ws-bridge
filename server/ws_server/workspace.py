"""R134: Minimal workspace stub — data model only.

All CRUD, admin, token ring, persistence, ! command handler code removed.
Keeps just what pipeline_engine.py and main.py's _on_git_sync need:
- Workspace dataclass with members/admin_ids/owner_id/state
- WorkspaceState enum
- get_workspace() / get_workspaces_for_agent() / get_workspace_members()
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("ws-bridge.workspace")


class WorkspaceState(enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass
class Workspace:
    id: str = ""
    name: str = ""
    owner_id: str = ""
    admin_ids: set[str] = field(default_factory=set)
    members: set[str] = field(default_factory=set)
    state: WorkspaceState = WorkspaceState.ACTIVE
    closing_acks: set[str] = field(default_factory=set)


# In-memory workspace registry (no persistence — workspace subsystem is deprecated)
_workspaces: dict[str, Workspace] = {}


def get_workspace(ws_id: str) -> Optional[Workspace]:
    """Return workspace by ID, or None."""
    return _workspaces.get(ws_id)


def get_workspaces_for_agent(agent_id: str) -> list[Workspace]:
    """Return all workspaces the agent is a member of."""
    return [ws for ws in _workspaces.values() if agent_id in ws.members]


def get_workspace_members(ws_id: str) -> set[str]:
    """Return member IDs for a workspace, or empty set."""
    ws = _workspaces.get(ws_id)
    return ws.members if ws else set()


def get_all_workspaces() -> list[Workspace]:
    """Return all workspaces (legacy — kept for compatibility)."""
    return list(_workspaces.values())


def init() -> None:
    """Initialize workspace module (no-op, registry starts empty)."""
    logger.info("R134: Workspace module initialized (minimal stub — no persistence)")
