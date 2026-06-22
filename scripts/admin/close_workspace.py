#!/usr/bin/env python3
"""Close (archive) a workspace.

Usage:
  close_workspace.py <workspace_id> [--force] [--reason <text>] [--json]

Examples:
  close_workspace.py ws:abc123
  close_workspace.py ws:abc123 --force
  close_workspace.py ws:abc123 --json
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
        description="Close a workspace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("ws_id", nargs="?", help="Workspace ID to close")
    parser.add_argument("--id", dest="id_alt", help="Workspace ID (alt)")
    parser.add_argument(
        "--force", action="store_true",
        help="Force close (skip ack)",
    )
    parser.add_argument("--reason", default="", help="Reason for closing")
    parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()
    ws_id = args.ws_id or args.id_alt
    if not ws_id:
        parser.print_help()
        sys.exit(1)

    data_dir = _get_data_dir()

    # ── Import server modules ──────────────────────────────────────
    sys.path.insert(0, str(PROJECT_ROOT))
    from server import workspace as ws_mod
    from server import persistence as p
    import server.config as cfg

    cfg.DATA_DIR = data_dir.resolve()

    p.load_pairing_codes(data_dir)
    p.load_approved_users(data_dir)

    ws_mod.init()

    start = time.time()
    audit = AuditLogger(data_dir.parent / "logs")

    try:
        # Check workspace exists
        ws = ws_mod.get_workspace(ws_id)
        if not ws:
            result = {"type": "error", "error": f"Workspace not found: {ws_id}"}
        elif ws.state != ws_mod.WorkspaceState.ACTIVE:
            result = {
                "type": "error",
                "error": f"Workspace is not active (current: {ws.state.value})",
            }
        else:
            if args.force:
                success = ws_mod.force_close(ws_id)
            else:
                success = ws_mod.start_closing(ws_id)

            if success:
                result = {
                    "type": "ok",
                    "workspace_id": ws_id,
                    "state": "archived",
                    "force": args.force,
                }
            else:
                result = {"type": "error", "error": "关闭操作失败"}
    except Exception as e:
        result = {"type": "error", "error": str(e)}

    duration_ms = (time.time() - start) * 1000

    # ── Audit log ──────────────────────────────────────────────────
    audit.log(
        action="close_workspace",
        agent_id="admin",
        agent_name="admin",
        params={"workspace_id": ws_id, "force": args.force, "reason": args.reason},
        result=result,
        duration_ms=duration_ms,
    )

    # ── Output ─────────────────────────────────────────────────────
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if result.get("type") == "ok":
        print(f"✅ 工作室 {ws_id} 已关闭")
        print(f"   状态: ARCHIVED")
    else:
        print(f"❌ 关闭失败: {result.get('error', '未知错误')}")


if __name__ == "__main__":
    main()
