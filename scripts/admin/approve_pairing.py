#!/usr/bin/env python3
"""Approve a bot pairing code (for WebSocket agent registration).

Usage:
  approve_pairing.py <code> [--role member|admin] [--name <name>] [--json]

Examples:
  approve_pairing.py ABCD1234
  approve_pairing.py ABCD1234 --role admin --json
  approve_pairing.py ABCD1234 --name admin-bot
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
        description="Approve a bot pairing code (WebSocket agent registration)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("code", nargs="?", help="Pairing code to approve")
    parser.add_argument("--code", dest="code_alt", help="Pairing code (alt)")
    parser.add_argument(
        "--role", default="member",
        choices=["member", "admin", "observer"],
        help="Role to assign (default: member)",
    )
    parser.add_argument("--name", default="admin", help="Approver name for audit log")
    parser.add_argument("--json", action="store_true", help="JSON output only")

    args = parser.parse_args()
    code = args.code or args.code_alt
    if not code:
        parser.print_help()
        sys.exit(1)

    data_dir = _get_data_dir()

    # ── Import server auth module ──────────────────────────────────
    sys.path.insert(0, str(PROJECT_ROOT))
    from server import auth
    from server import persistence as p
    import server.config as cfg

    cfg.DATA_DIR = data_dir.resolve()

    # Ensure pairing code store is loaded
    p.load_pairing_codes(data_dir)
    p.load_approved_users(data_dir)

    start = time.time()
    audit = AuditLogger(data_dir.parent / "logs")

    try:
        result_raw = auth.approve(code, args.role)
        if result_raw["type"] == "approve_ok":
            p.save_pairing_codes(data_dir)
            p.save_approved_users(data_dir)
            result = {
                "type": "ok",
                "agent_id": result_raw.get("agent_id", "?"),
                "role": args.role,
                "code": code,
            }
        else:
            result = {
                "type": "error",
                "error": result_raw.get("error", "审批失败"),
            }
    except Exception as e:
        result = {"type": "error", "error": str(e)}

    duration_ms = (time.time() - start) * 1000

    # ── Audit log ──────────────────────────────────────────────────
    audit.log(
        action="approve_pairing",
        agent_id=args.name,
        agent_name=args.name,
        params={"code": code, "role": args.role},
        result=result,
        duration_ms=duration_ms,
    )

    # ── Output ─────────────────────────────────────────────────────
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if result.get("type") == "ok":
        print(f"✅ 配对码 {code} 审批通过")
        print(f"   分配的 agent_id: {result['agent_id']}")
        print(f"   角色: {result['role']}")
    else:
        print(f"❌ 审批失败: {result.get('error', '未知错误')}")


if __name__ == "__main__":
    main()
