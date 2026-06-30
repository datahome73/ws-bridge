#!/usr/bin/env python3
"""Approve a web bind code or bot pairing code.

Usage:
  approve_bind.py <code> [--name <name>] [--role member|admin] [--json]
  approve_bind.py --code <code> [--name <name>] [--role member|admin] [--json]

Examples:
  approve_bind.py WEB-A1B2 --name admin-bot
  approve_bind.py GJK43EZH --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Add project root to path so we can import server modules
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.admin.lib.audit import AuditLogger


def _get_data_dir() -> Path:
    """Determine ws-bridge data directory."""
    env_dir = __import__("os").environ.get("WS_DATA_DIR", "")
    if env_dir:
        return Path(env_dir)
    # Fallback: relative to project root
    return PROJECT_ROOT / "data"


def approve_pairing_code(code: str, role: str, db_dir: Path) -> dict:
    """Approve a bot pairing code by importing server.auth directly."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from server import auth
    from server import persistence as p

    data_dir = db_dir.resolve()
    p.load_pairing_codes(data_dir)
    p.load_approved_users(data_dir)

    result = auth.approve(code, role)
    if result["type"] == "approve_ok":
        p.save_pairing_codes(data_dir)
        p.save_approved_users(data_dir)
    return result


def approve_web_code(code: str, name: str, db_dir: Path) -> dict:
    """Approve a web bind code (WEB-* prefix)."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from server import auth
    from server import persistence as p

    data_dir = db_dir.resolve()
    p.load_web_bind_codes(data_dir)
    p.load_web_sessions(data_dir)

    result = auth.approve_web_bind_code(code, name)
    if result.get("type") == "approve_ok":
        p.save_web_bind_codes(data_dir)
        p.save_web_sessions(data_dir)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Approve a web bind code or bot pairing code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  approve_bind.py WEB-A1B2 --name admin-bot\n"
            "  approve_bind.py GJK43EZH --json\n"
        ),
    )
    parser.add_argument("code", nargs="?", help="Binding code to approve")
    parser.add_argument("--code", dest="code_alt", help="Binding code (alt)")
    parser.add_argument("--name", default="admin", help="Approver name (default: admin)")
    parser.add_argument(
        "--role",
        default="member",
        choices=["member", "admin", "observer"],
        help="Role to assign (default: member)",
    )
    parser.add_argument("--json", action="store_true", help="JSON output only")

    args = parser.parse_args()
    code = args.code or args.code_alt
    if not code:
        parser.print_help()
        sys.exit(1)

    data_dir = _get_data_dir()
    audit = AuditLogger(data_dir.parent / "logs")
    start = time.time()

    # ── Determine code type ────────────────────────────────────────
    is_web = code.startswith("WEB-")

    try:
        if is_web:
            result = approve_web_code(code, args.name, data_dir)
        else:
            result = approve_pairing_code(code, args.role, data_dir)
    except Exception as e:
        result = {"type": "error", "error": str(e)}

    duration_ms = (time.time() - start) * 1000

    # ── Audit log ──────────────────────────────────────────────────
    audit.log(
        action="approve_bind",
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

    if result.get("type") in ("approve_ok",):
        agent_id = result.get("agent_id", "?")
        print(f"✅ 绑定码 {code} 审批通过")
        print(f"   分配的 agent_id: {agent_id}")
        print(f"   角色: {args.role}")
        if is_web:
            print(f"   用户名: {args.name}")
    elif result.get("type") == "approve_error":
        print(f"❌ 审批失败: {result.get('error', '未知错误')}")
    else:
        print(f"❌ 错误: {result.get('error', '未知错误')}")


if __name__ == "__main__":
    main()
