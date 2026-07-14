"""Workspace HTTP API endpoints for ws-bridge server."""
import json
import time
from aiohttp import web

from . import workspace as ws_mod
PERSISTENCE_DIR = str(ws_mod.DATA_DIR)


async def api_workspaces(request: web.Request) -> web.Response:
    """GET /api/workspaces — return all workspaces with status."""
    check_idle()
    workspaces = []
    for w in ws_mod.get_all_workspaces():
        workspaces.append({
            "id": w.id,
            "name": w.name,
            "owner_id": w.owner_id[:16] if w.owner_id else "",
            "owner_name": w.owner_name,
            "state": w.state.value,
            "member_count": len(w.members),
            "ack_count": 0,
            "created_at": w.created_at,
            "last_active_at": w.last_active_at,
            "closed_at": w.closed_at,
            "pipeline_round": w.pipeline_round,
            "roles": w.roles,
        })
    # Sort by last_active descending
    workspaces.sort(key=lambda x: x["last_active_at"], reverse=True)
    return web.json_response({"workspaces": workspaces, "count": len(workspaces)})


def check_idle():
    """Check all active workspaces for idle timeout."""
    for w in ws_mod.get_active_workspaces():
        ws_mod.check_idle(w.id)
