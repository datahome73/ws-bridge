#!/usr/bin/env python3
"""申请成为工作室管理员。

用法：
  request_workspace_admin.py --workspace <ws_id> [--reason "原因"]
  request_workspace_admin.py --workspace <ws_id> --status

例子：
  request_workspace_admin.py --workspace ws:R12开发工作室 --reason "参与管理"
  request_workspace_admin.py --workspace ws:R12开发工作室 --status
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
        description="申请成为工作室管理员",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace", required=True, help="工作室 ID")
    parser.add_argument("--reason", help="申请原因")
    parser.add_argument("--status", action="store_true", help="查看本人申请状态")
    parser.add_argument("--agent", help="申请人 agent ID（默认从凭证读取）")
    parser.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()

    data_dir = _get_data_dir()

    # Import server modules
    sys.path.insert(0, str(PROJECT_ROOT))
    from server import persistence as p
    from server.workspace import (
        _admin_requests, _load_admin_requests, submit_admin_request,
        get_pending_requests,
    )
    import server.config as cfg
    cfg.DATA_DIR = data_dir.resolve()

    p.load_approved_users(data_dir)
    _load_admin_requests()

    # Resolve agent
    agent_id = args.agent
    if not agent_id:
        users = p.get_approved_users()
        if not users:
            print("❌ 未找到已认证用户，请指定 --agent")
            sys.exit(1)
        # Use the first user as default
        agent_id = list(users.keys())[0]

    # ── Status mode ─────────────────────────────────────────
    if args.status:
        pending = get_pending_requests(args.workspace)
        user_requests = [r for r in pending if r.requester_id == agent_id]
        all_requests = [r for r in _admin_requests.values()
                        if r.workspace_id == args.workspace and r.requester_id == agent_id]

        if args.json:
            print(json.dumps(
                [{"workspace_id": r.workspace_id, "status": r.status,
                  "reason": r.reason, "created_at": r.created_at,
                  "reviewed_by": r.reviewed_by, "reject_reason": r.reject_reason}
                 for r in all_requests],
                ensure_ascii=False, indent=2,
            ))
            return

        if not all_requests:
            print(f"📭 无申请记录（{args.workspace}）")
            return

        for r in all_requests:
            status_mark = "⏳" if r.status == "pending" else "✅" if r.status == "approved" else "❌"
            print(f"{status_mark} 状态: {r.status}")
            print(f"   原因: {r.reason or '无'}")
            print(f"   提交时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r.created_at))}")
            if r.reviewed_by:
                print(f"   审批人: {r.reviewed_by}")
            if r.reject_reason:
                print(f"   拒绝原因: {r.reject_reason}")
        return

    # ── Submit mode ──────────────────────────────────────────
    success, message = submit_admin_request(args.workspace, agent_id, args.reason or "")

    if args.json:
        print(json.dumps({"success": success, "message": message}, ensure_ascii=False))
        return

    if success:
        print(f"✅ {message}")
        print(f"   工作室: {args.workspace}")
        if args.reason:
            print(f"   原因: {args.reason}")
    else:
        print(f"❌ {message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
