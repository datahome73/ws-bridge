#!/usr/bin/env python3
"""Query admin audit log.

Usage:
  audit_log.py [--action <type>] [--tail <N>] [--from <ts>] [--to <ts>] [--json]

Examples:
  audit_log.py
  audit_log.py --action approve_bind
  audit_log.py --tail 5 --json
  audit_log.py --from 1718600000 --to 1718700000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.admin.lib.audit import AuditLogger


def _get_log_dir() -> Path:
    env_dir = __import__("os").environ.get("WS_DATA_DIR", "")
    data_dir = Path(env_dir) if env_dir else PROJECT_ROOT / "data"
    return data_dir.parent / "logs"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query admin audit log",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--action", help="Filter by action type")
    parser.add_argument("--tail", type=int, help="Last N entries")
    parser.add_argument("--from", dest="from_ts", type=float, help="Start timestamp")
    parser.add_argument("--to", dest="to_ts", type=float, help="End timestamp")
    parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()
    log_dir = _get_log_dir()
    audit = AuditLogger(log_dir)

    entries = audit.query(
        action=args.action,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        tail=args.tail,
    )

    if not entries:
        print("审计日志为空")
        return

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return

    # Human-readable output
    print(f"审计日志 ({len(entries)} 条)")
    print(f"{'─'*70}")
    for e in entries:
        import datetime
        ts = e.get("ts", 0)
        dt = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        action = e.get("action", "?")
        agent = e.get("agent_name", e.get("agent_id", "?"))
        status = "✅" if e.get("result", {}).get("type") in ("ok", "approve_ok") else "❌"
        print(f"  {status} [{dt}] {agent}: {action}")
        if e.get("params"):
            params_str = json.dumps(e["params"], ensure_ascii=False)
            print(f"     参数: {params_str}")
        if e.get("result", {}).get("error"):
            print(f"     错误: {e['result']['error']}")


if __name__ == "__main__":
    main()
