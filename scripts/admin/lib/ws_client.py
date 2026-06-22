"""Admin tool shared module — WebSocket communication with ws-bridge server."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore[assignment]

logger = logging.getLogger("admin.ws_client")


class AdminWSClient:
    """WebSocket client for admin tools that need server interaction.

    Connects to the ws-bridge WebSocket endpoint and sends/receives
    structured messages. Used for live queries like online agent status.
    """

    def __init__(self, ws_url: str, agent_id: str, app_id: str) -> None:
        if aiohttp is None:
            raise ImportError("aiohttp is required. Install with: pip install aiohttp")
        self._ws_url = ws_url
        self._agent_id = agent_id
        self._app_id = app_id
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> None:
        """Establish WebSocket connection and authenticate."""
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(self._ws_url)

        # Authenticate
        await self._ws.send_json({
            "type": "auth",
            "agent_id": self._agent_id,
            "app_id": self._app_id,
        })

    async def send_and_wait(
        self, msg: dict, timeout: float = 5.0
    ) -> Optional[dict]:
        """Send a message and wait for a matching response.

        Args:
            msg: Message dict to send
            timeout: Max seconds to wait for a response

        Returns:
            Response dict, or None on timeout
        """
        if self._ws is None or self._ws.closed:
            raise RuntimeError("WebSocket not connected")
        if self._session is None:
            raise RuntimeError("WebSocket session not created")

        await self._ws.send_json(msg)

        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            raw = await asyncio.wait_for(
                self._ws.receive(), timeout=remaining
            )
            if raw.type == aiohttp.WSMsgType.TEXT:
                try:
                    return json.loads(raw.data)
                except json.JSONDecodeError:
                    continue
            elif raw.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break

        return None

    async def close(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()

    async def __aenter__(self) -> AdminWSClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
