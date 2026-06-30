"""Admin audit logger — writes structured JSON to logs/admin-audit.log."""

import json
import time
from pathlib import Path
from typing import Any, Optional


class AuditLogger:
    """Append-only audit log for admin operations.

    Each operation appends one JSON line to the log file.
    """

    def __init__(self, log_dir: str | Path) -> None:
        self._log_path = Path(log_dir) / "admin-audit.log"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        action: str,
        agent_id: str,
        agent_name: str = "",
        params: Optional[dict] = None,
        result: Optional[dict] = None,
        duration_ms: Optional[float] = None,
    ) -> None:
        """Write one audit entry.

        Args:
            action: Operation type (e.g. 'approve_bind', 'create_workspace')
            agent_id: Agent that performed the operation
            agent_name: Human-readable agent name
            params: Input parameters for the operation
            result: Operation result
            duration_ms: Operation duration in milliseconds
        """
        entry = {
            "ts": time.time(),
            "agent_id": agent_id,
            "agent_name": agent_name,
            "action": action,
            "params": params or {},
            "result": result or {},
        }
        if duration_ms is not None:
            entry["duration_ms"] = round(duration_ms, 1)

        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def query(
        self,
        action: Optional[str] = None,
        from_ts: Optional[float] = None,
        to_ts: Optional[float] = None,
        tail: Optional[int] = None,
    ) -> list[dict]:
        """Read back audit entries with optional filters.

        Args:
            action: Filter by action type
            from_ts: Only entries after this timestamp
            to_ts: Only entries before this timestamp
            tail: Only the last N entries

        Returns:
            List of matching audit entries (newest first when tail is set)
        """
        if not self._log_path.exists():
            return []

        entries: list[dict] = []
        with open(self._log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if action and entry.get("action") != action:
                    continue
                if from_ts is not None and entry.get("ts", 0) < from_ts:
                    continue
                if to_ts is not None and entry.get("ts", 0) > to_ts:
                    continue
                entries.append(entry)

        if tail is not None and tail > 0:
            return entries[-tail:]

        return entries
