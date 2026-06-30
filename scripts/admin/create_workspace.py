#!/usr/bin/env python3
"""Create a new workspace.

Usage:
  create_workspace.py <name> --owner <agent_id> [--members <id1,id2,...>] [--json]

Examples:
  create_workspace.py "R10开发工作室" --owner admin-bot --members pm-bot,dev-bot,qa-bot
  create_workspace.py "R10开发工作室" --owner admin-bot --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.admin.lib.audit import AuditLogger


def _get_data_dir() -> Path:
    env_dir = __import__("os").environ.get("WS_DATA_DIR", "")
    return Path(env_dir) if env_dir else PROJECT_ROOT / "data"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a new workspace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", nargs="?", help="Workspace name")
    parser.add_argument("--name", dest="name_alt", help="Workspace name (alt)")
    parser.add_argument(
        "--owner", required=True,
        help="Owner agent ID or name (required)",
    )
    parser.add_argument(
        "--members",
        help="Comma-separated list of member agent IDs",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()
    name = args.name or args.name_alt
    if not name:
        parser.print_help()
        sys.exit(1)

    data_dir = _get_data_dir()

    # ── Import server modules ──────────────────────────────────────
    sys.path.insert(0, str(PROJECT_ROOT))
    from server import workspace as ws_mod
    from server import persistence as p
    from server.config import DATA_DIR as SERVER_DATA_DIR

    # Override DATA_DIR to match our data directory
    import server.config as cfg
    cfg.DATA_DIR = data_dir.resolve()

    # Initialize workspace data
    p.load_pairing_codes(data_dir)
    p.load_approved_users(data_dir)

    # Initialize workspace module's data path
    # workspace.py uses its own _data_path() which reads from config.DATA_DIR
    ws_mod.init()

    start = time.time()
    audit = AuditLogger(data_dir.parent / "logs")

    member_ids = [m.strip() for m in args.members.split(",")] if args.members else []

    try:
        # Generate workspace ID: ws:{sanitized_name}
        import re
        safe_name = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff_-]', '_', name)
        ws_id = f"ws:{safe_name}"

        # Create workspace (owner is automatically a member)
        ws = ws_mod.create_workspace(ws_id, name, args.owner, args.owner)
        if not ws:
            result = {"type": "error", "error": "创建失败（可能已达上限）"}
        else:
            # Add extra members
            added_members = []
            for mid in member_ids:
                if mid != args.owner:
                    if ws_mod.add_member(ws_id, mid):
                        added_members.append(mid)
            result = {
                "type": "ok",
                "workspace_id": ws_id,
                "name": name,
                "owner": args.owner,
                "members": [args.owner] + added_members,
                "state": "active",
            }
    except Exception as e:
        result = {"type": "error", "error": str(e)}

    duration_ms = (time.time() - start) * 1000

    # ── Audit log ──────────────────────────────────────────────────
    audit.log(
        action="create_workspace",
        agent_id=args.owner,
        agent_name=args.owner,
        params={"name": name, "owner": args.owner, "members": member_ids},
        result=result,
        duration_ms=duration_ms,
    )

    # ── Output ─────────────────────────────────────────────────────
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if result.get("type") == "ok":
        print(f"✅ 工作室「{name}」已创建")
        print(f"   ID:    {result['workspace_id']}")
        print(f"   Owner: {args.owner}")
        if member_ids:
            print(f"   成员:  {', '.join(member_ids)}")
    else:
        print(f"❌ 创建失败: {result.get('error', '未知错误')}")


if __name__ == "__main__":
    main()
