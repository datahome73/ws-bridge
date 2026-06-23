"""R35: Admin audit logger — writes structured JSON Lines to DATA_DIR/_audit_log.jsonl.

Migrated from scripts/admin/lib/audit.py with adapted signature for server-side use.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ws-bridge.audit")


class AuditLogger:
    """Append-only audit log for admin operations (JSON Lines format).

    Each !command execution appends one JSON line to the log file.
    """

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "_audit_log.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        agent_id: str,
        command: str,
        params: Optional[dict] = None,
        result: str = "",
        detail: str = "",
    ) -> None:
        """Write one audit entry.

        Args:
            agent_id: Agent that executed the command
            command: Command name (e.g. 'create_workspace')
            params: Input parameters
            result: 'success' | 'error'
            detail: Human-readable result text (truncated to 200 chars)
        """
        entry = {
            "ts": time.time(),
            "agent_id": agent_id,
            "command": command,
            "params": params or {},
            "result": result,
            "detail": detail[:200],
        }
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.error("Audit log write failed: %s", e)

    def query(
        self,
        tail: int = 100,
        agent_id: Optional[str] = None,
        command: Optional[str] = None,
    ) -> list[dict]:
        """Read back audit entries with optional filters.

        Args:
            tail: Only the last N entries (newest first)
            agent_id: Filter by agent who performed the operation
            command: Filter by command name

        Returns:
            List of matching audit entries (newest first when tail is set)
        """
        if not self._path.exists():
            return []

        all_entries: list[dict] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if agent_id and entry.get("agent_id") != agent_id:
                    continue
                if command and entry.get("command") != command:
                    continue
                all_entries.append(entry)

        if tail and tail > 0:
            return all_entries[-tail:]
        return all_entries
