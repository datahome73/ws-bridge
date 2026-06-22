#!/usr/bin/env python3
"""Show detailed status for an agent.

Usage:
  agent_status.py <agent_id|name> [--json]

Examples:
  agent_status.py admin-bot
  agent_status.py ag-12345678 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.admin.lib.db import AdminDB


def _get_data_dir() -> Path:
    env_dir = __import__("os").environ.get("WS_DATA_DIR", "")
    return Path(env_dir) if env_dir else PROJECT_ROOT / "data"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show agent details",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("agent", nargs="?", help="Agent ID or name")
    parser.add_argument("--agent", dest="agent_alt", help="Agent ID or name (alt)")
    parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()
    agent_ref = args.agent or args.agent_alt
    if not agent_ref:
        parser.print_help()
        sys.exit(1)

    data_dir = _get_data_dir()
    db = AdminDB(data_dir)

    users = db.get_approved_users()
    channels = db.get_agent_channels()
    workspaces = db.get_workspaces()

    # Find matching agent(s)
    found = []
    for agent_id, info in users.items():
        name = info.get("name", "")
        if agent_ref in (agent_id, name) or agent_ref.lower() in name.lower():
            found.append((agent_id, info))

    if not found:
        print(f"❌ 未找到 agent: {agent_ref}")
        sys.exit(1)

    # Show best match or all
    best = found[0]
    if len(found) > 1:
        # Prefer exact match
        exact = [f for f in found if agent_ref in (f[0], f[1].get("name", ""))]
        best = exact[0] if exact else best

    agent_id, info = best
    name = info.get("name", agent_id)
    role = info.get("role", "member")
    channel = channels.get(agent_id, "")
    status = "✅ 在线" if channel else "⏹️ 离线"

    # Workspace membership
    ws_list = []
    for ws_id, ws in workspaces.items():
        members = ws.get("members", [])
        if agent_id in members:
            ws_list.append({"id": ws_id, "name": ws.get("name", ws_id), "state": ws.get("state", "unknown")})

    # Build output
    result = {
        "name": name,
        "agent_id": agent_id,
        "role": role,
        "status": "online" if channel else "offline",
        "active_channel": channel,
        "workspaces": ws_list,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"Agent: {name}")
    print(f"  ID:    {agent_id}")
    print(f"  角色:  {role}")
    print(f"  状态:  {status}")
    if channel:
        print(f"  频道:  {channel}")
    if ws_list:
        print(f"  工作室 ({len(ws_list)}):")
        for ws in ws_list:
            state_mark = "🟢" if ws["state"] == "active" else "🔴" if ws["state"] == "archived" else "🟡"
            print(f"    {state_mark} {ws['name']} ({ws['id'][:20]}... [{ws['state']}])")
    else:
        print("  工作室: 无")


if __name__ == "__main__":
    main()
