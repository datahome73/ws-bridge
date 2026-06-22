#!/usr/bin/env python3
"""审批工作室管理员申请。

用法：
  approve_workspace_admin.py --list [--workspace <ws_id>]
  approve_workspace_admin.py --approve --workspace <ws_id> --agent <agent>
  approve_workspace_admin.py --reject --workspace <ws_id> --agent <agent> [--reason "原因"]

例子：
  approve_workspace_admin.py --list
  approve_workspace_admin.py --list --workspace ws:R12开发工作室
  approve_workspace_admin.py --approve --workspace ws:R12开发工作室 --agent pm-bot
  approve_workspace_admin.py --reject --workspace ws:R12开发工作室 --agent pm-bot --reason "权限不足"
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


def _get_data_dir() -> Path:
    env_dir = __import__("os").environ.get("WS_DATA_DIR", "")
    return Path(env_dir) if env_dir else PROJECT_ROOT / "data"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="审批工作室管理员申请",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list", action="store_true", help="查看待审批列表")
    parser.add_argument("--approve", action="store_true", help="审批通过")
    parser.add_argument("--reject", action="store_true", help="审批拒绝")
    parser.add_argument("--workspace", help="工作室 ID")
    parser.add_argument("--agent", help="目标成员 name 或 agent_id")
    parser.add_argument("--reason", help="拒绝原因")
    parser.add_argument("--reviewer", help="审批人 agent_id（默认从凭证读取）")
    parser.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()

    data_dir = _get_data_dir()

    # Import server modules
    sys.path.insert(0, str(PROJECT_ROOT))
    from server import auth, persistence as p
    from server.workspace import (
        _admin_requests, _load_admin_requests, get_pending_requests,
        approve_admin_request, reject_admin_request, list_workspace_admins,
    )
    import server.config as cfg
    cfg.DATA_DIR = data_dir.resolve()

    p.load_approved_users(data_dir)
    p.load_web_sessions(data_dir)
    # auth.load_users is not a real function; p.load_approved_users already loads
    _load_admin_requests()

    if not args.list and not args.approve and not args.reject:
        parser.print_help()
        sys.exit(1)

    # ── List mode ────────────────────────────────────────────
    if args.list:
        pending = get_pending_requests(args.workspace)
        users = p.get_approved_users()

        if args.json:
            result = []
            for r in pending:
                name = users.get(r.requester_id, {}).get("name", r.requester_id[:12])
                ws = r.workspace_id
                result.append({
                    "workspace_id": ws,
                    "requester_id": r.requester_id,
                    "requester_name": name,
                    "reason": r.reason,
                    "created_at": r.created_at,
                })
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        if not pending:
            print("📭 无待审批申请")
            return

        print(f"📋 待审批申请（共 {len(pending)} 条）:\n")
        for r in pending:
            name = users.get(r.requester_id, {}).get("name", r.requester_id[:12])
            ws = r.workspace_id
            created = time.strftime("%m-%d %H:%M", time.localtime(r.created_at))
            print(f"  🆔 {ws}")
            print(f"     申请人: {name} ({r.requester_id[:16]}...)")
            if r.reason:
                print(f"     原因: {r.reason}")
            print(f"     时间: {created}")
            print()
        return

    # ── Resolve reviewer ─────────────────────────────────────
    reviewer_id = args.reviewer
    if not reviewer_id:
        users = p.get_approved_users()
        # Find an admin
        for aid, info in users.items():
            if info.get("role") == "admin":
                reviewer_id = aid
                break
    if not reviewer_id:
        print("❌ 未找到审批人，请指定 --reviewer")
        sys.exit(1)

    if not args.workspace:
        print("❌ 请指定 --workspace")
        sys.exit(1)

    if not args.agent:
        print("❌ 请指定 --agent（目标成员 name 或 agent_id）")
        sys.exit(1)

    # Resolve target
    users = p.get_approved_users()
    target_id = args.agent
    target_name = args.agent
    # Check if it's a name, resolve to ID
    for aid, info in users.items():
        if info.get("name") == args.agent:
            target_id = aid
            target_name = info.get("name", aid)
            break

    # ── Approve mode ─────────────────────────────────────────
    if args.approve:
        success, msg_text = approve_admin_request(args.workspace, target_id, reviewer_id)
        if success:
            # 实际调用 set_workspace_admin 使权限生效
            auth.set_workspace_admin(args.workspace, target_id, reviewer_id)
            msg_text = f"✅ {target_name} 已成为 {args.workspace} 的管理员"
        if args.json:
            print(json.dumps({
                "success": success, "message": msg_text,
                "workspace_id": args.workspace, "target": target_name,
            }, ensure_ascii=False))
            return
        if success:
            print(f"✅ {msg_text}")
            print(f"   {target_name} → {args.workspace} 管理员")
        else:
            print(f"❌ {msg_text}")
            sys.exit(1)
        return

    # ── Reject mode ──────────────────────────────────────────
    if args.reject:
        success, msg_text = reject_admin_request(args.workspace, target_id, reviewer_id, args.reason or "")
        if args.json:
            print(json.dumps({
                "success": success, "message": msg_text,
                "workspace_id": args.workspace, "target": target_name,
                "reason": args.reason or "",
            }, ensure_ascii=False))
            return
        if success:
            print(f"✅ {msg_text}")
            print(f"   {target_name} 的管理员申请已拒绝")
            if args.reason:
                print(f"   原因: {args.reason}")
        else:
            print(f"❌ {msg_text}")
            sys.exit(1)
        return


if __name__ == "__main__":
    main()
