#!/usr/bin/env python3
"""List all approved agents.

Usage:
  list_agents.py [--role <role>] [--status online|offline] [--json]

Examples:
  list_agents.py
  list_agents.py --role admin
  list_agents.py --json
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


def _get_agent_channels(db: AdminDB) -> dict[str, str]:
    """Get channel info from active channels file."""
    try:
        return db.get_agent_channels()
    except Exception:
        return {}


def _get_workspace_names(db: AdminDB) -> dict[str, str]:
    """Build agent_id → workspace_name mapping."""
    workspaces = db.get_workspaces()
    result: dict[str, str] = {}
    for ws_id, ws in workspaces.items():
        name = ws.get("name", ws_id)
        for mid in ws.get("members", []):
            if mid not in result:
                result[mid] = name
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List approved agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--role", choices=["member", "admin", "observer"],
        help="Filter by role",
    )
    parser.add_argument(
        "--status", choices=["online", "offline"],
        help="Filter by online status (reads active channels file)",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()
    data_dir = _get_data_dir()
    db = AdminDB(data_dir)

    users = db.get_approved_users()
    channels = _get_agent_channels(db) if args.status else {}
    workspaces = _get_workspace_names(db)

    if not users:
        print("暂无已注册 agent")
        return

    # Build rows
    rows: list[dict] = []
    for agent_id, info in users.items():
        name = info.get("name", agent_id)
        role = info.get("role", "member")

        # Status: if agent has an active channel, consider online
        status = "online" if agent_id in channels else "offline"
        channel = channels.get(agent_id, "")
        ws_name = next(
            (wn for wid, wn in workspaces.items() if wn == channel),
            "",
        )

        rows.append({
            "name": name,
            "agent_id": agent_id[:20] + "..." if len(agent_id) > 20 else agent_id,
            "role": role,
            "status": status,
            "channel": channel,
        })

    # Filter
    if args.role:
        rows = [r for r in rows if r["role"] == args.role]
    if args.status:
        rows = [r for r in rows if r["status"] == args.status]

    # Output
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if not rows:
        print("没有匹配的 agent")
        return

    # Table
    col_w = max(len(r["name"]) for r in rows) + 2
    sep = f"+{'-'*4}+{'─'*(col_w+2)}+{'─'*26}+{'─'*8}+{'─'*20}+"
    hdr = f"| {'#':>2} | {'名称':^{col_w}}| {'Agent ID':^24} | {'角色':^6} | {'状态':^5} |"
    print(sep)
    print(hdr)
    print(sep)
    for i, r in enumerate(rows, 1):
        print(
            f"| {i:>2} | {r['name']:<{col_w}}| {r['agent_id']:<24} | {r['role']:<6} | {r['status']:<5} |"
        )
    print(sep)
    print(f"总计: {len(rows)} agent")


if __name__ == "__main__":
    main()
