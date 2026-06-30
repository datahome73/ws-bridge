"""Admin tool shared module — read ws-bridge persistence data files."""

import json
import time
from pathlib import Path
from typing import Any, Optional


class AdminDB:
    """Read-only interface to ws-bridge persistent data files.

    Reads the JSON files that server/persistence.py maintains.
    Thread-safe on the server side; tools read at-a-time.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)

    # ── helpers ────────────────────────────────────────────────────

    def _read_json(self, name: str) -> dict[str, Any]:
        path = self._data_dir / name
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    # ── data accessors ─────────────────────────────────────────────

    def get_approved_users(self) -> dict[str, dict]:
        """Return mapping: agent_id → {"name": str, "role": str}"""
        return self._read_json("_approved_users.json")

    def get_pairing_codes(self) -> dict[str, dict]:
        """Return mapping: code → {agent_id, app_id, name, ts, approved?}"""
        return self._read_json("_pairing_codes.json")

    def get_web_bind_codes(self) -> dict[str, dict]:
        """Return mapping: code → {name, ts, approved?}"""
        return self._read_json("_web_bind_codes.json")

    def get_web_sessions(self) -> dict[str, dict]:
        return self._read_json("_web_sessions.json")

    def get_agent_channels(self) -> dict[str, str]:
        """Return mapping: agent_id → channel_id"""
        return self._read_json("_agent_active_channels.json")

    def get_workspaces(self) -> dict[str, dict]:
        """Return mapping: ws_id → workspace dict.
        The server stores workspaces in workspaces.json via workspace.py.
        """
        return self._read_json("workspaces.json")
