#!/usr/bin/env python3
"""查看工作室管理员列表。

用法：
  list_workspace_admins.py --workspace <ws_id>

例子：
  list_workspace_admins.py --workspace ws:R12开发工作室
  list_workspace_admins.py --workspace ws:R12开发工作室 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _get_data_dir() -> Path:
    env_dir = __import__("os").environ.get("WS_DATA_DIR", "")
    return Path(env_dir) if env_dir else PROJECT_ROOT / "data"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="查看工作室管理员列表",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace", required=True, help="工作室 ID")
    parser.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()

    data_dir = _get_data_dir()

    sys.path.insert(0, str(PROJECT_ROOT))
    from server import auth, persistence as p
    from server.workspace import list_workspace_admins
    import server.config as cfg
    cfg.DATA_DIR = data_dir.resolve()

    p.load_approved_users(data_dir)
    p.load_web_sessions(data_dir)
    # auth.load_users is not a real function; p.load_approved_users already loads

    admins = list_workspace_admins(args.workspace)

    if args.json:
        print(json.dumps(admins, ensure_ascii=False, indent=2))
        return

    if not admins:
        print(f"📭 工作室 {args.workspace} 无成员")
        return

    print(f"📋 {args.workspace} 成员列表（共 {len(admins)} 人）:\n")
    for a in admins:
        mark = "⭐" if a["is_admin"] else "  "
        role_text = "管理员" if a["is_admin"] else "成员"
        print(f"  {mark} {a['name']:<8} | {role_text:<6} | {a['agent_id']}")


if __name__ == "__main__":
    main()
