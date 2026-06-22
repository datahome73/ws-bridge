"""WS Bridge client — reusable async WebSocket client library.

Features:
  - Full auth handshake (auth + auth_ok / pairing_code)
  - Heartbeat (ping/pong) keep-alive
  - Automatic reconnection with exponential backoff
  - on_connect / on_disconnect / on_message callbacks
  - send_message returns a unique message ID
  - Thread-safe message deduplication via seen_ids
  - ACK waiting + retry on timeout
  - Offline catchup via last_seen_ts (persisted to JSON file)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    import websockets  # noqa: F401

logger = logging.getLogger("ws-bridge-client")

# Defaults
DEFAULT_PING_INTERVAL = 25.0       # seconds between app-level pings
DEFAULT_READ_TIMEOUT = 35.0        # read timeout (must exceed ping_interval)
RECONNECT_BASE_DELAY = 3.0
RECONNECT_MAX_DELAY = 30.0
ACK_TIMEOUT = 5.0
MAX_RETRIES = 2
STATE_FILENAME = "ws_bridge_state.json"


class WsBridgeClient:
    """Connect to a Hermes WS Bridge server and handle messages.

    Typical usage::

        client = WsBridgeClient(
            ws_url="wss://example.com/ws",
            app_id="myapp",
            agent_id="my-bot",
            name="BotName",
            on_message=lambda msg: print(msg),
        )
        await client.connect()
        await client.send_message("Hello everyone!")
        # ...
        await client.disconnect()
    """

    def __init__(
        self,
        ws_url: str,
        app_id: str,
        agent_id: str,
        name: str = "bot",
        *,
        on_message: Optional[Callable[[dict], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        on_offline: Optional[Callable[[list[dict]], None]] = None,
        ping_interval: float = DEFAULT_PING_INTERVAL,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        auto_reconnect: bool = True,
        state_file: Optional[str] = None,
    ):
        self.ws_url = ws_url
        self.app_id = app_id
        self.agent_id = agent_id
        self.name = name
        self.on_message = on_message or (lambda msg: None)
        self.on_connect = on_connect or (lambda: None)
        self.on_disconnect = on_disconnect or (lambda: None)
        self.on_offline = on_offline or (lambda msgs: None)
        self.ping_interval = ping_interval
        self.read_timeout = read_timeout
        self.auto_reconnect = auto_reconnect
        self.state_file = state_file

        # Internal state
        self._ws: Any = None
        self._ws_lock = asyncio.Lock()
        self._connected = False
        self._authed = False
        self._stop = asyncio.Event()
        self._reconnect_delay = RECONNECT_BASE_DELAY

        # Deduplication
        self._seen_ids: set[str] = set()
        self._seen_max = 500

        # ACK waiting
        self._pending_acks: dict[str, asyncio.Event] = {}
        self._pending_retries: dict[str, tuple[int, dict, float]] = {}

        # Offline catchup
        self._last_msg_ts: float = self._load_last_msg_ts()

        # Background tasks
        self._reader_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Open WebSocket connection and authenticate with the server.

        Returns ``True`` on success, ``False`` on failure.
        On success, fires ``on_connect()``.
        """
        import websockets

        self._stop.clear()
        self._authed = False

        try:
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=None,       # We send app-level pings
                ping_timeout=None,
                close_timeout=5,
            )
        except Exception as exc:
            logger.error("Connection failed: %s", exc)
            self._connected = False
            return False

        self._connected = True
        logger.info("Connected to %s", self.ws_url)

        # Send auth (with last_seen_ts for offline catchup)
        try:
            await self._ws.send(json.dumps({
                "type": "auth",
                "app_id": self.app_id,
                "agent_id": self.agent_id,
                "name": self.name,
                "last_seen_ts": self._last_msg_ts,
            }))
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
            resp = json.loads(raw)
            msg_type = resp.get("type", "")

            if msg_type == "auth_ok":
                self._authed = True
                logger.info("Auth OK (role=%s, last_seen_ts=%s)", resp.get("role"), self._last_msg_ts)
            elif msg_type == "pairing_code":
                code = resp.get("code", "???")
                logger.warning(
                    "Pairing code: %s — forward to admin for approval", code
                )
                # Return True but stay connected; admin may approve while
                # we are online. Individual adapters can decide to disconnect.
            elif msg_type == "auth_error":
                logger.error("Auth error: %s", resp.get("error", "unknown"))
                await self._close_ws()
                return False
            else:
                logger.warning("Unexpected auth response: %s", raw[:200])
        except asyncio.TimeoutError:
            logger.error("Auth timed out (no response within 10s)")
            await self._close_ws()
            return False
        except Exception as exc:
            logger.error("Auth failed: %s", exc)
            await self._close_ws()
            return False

        # Start background loops
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._reader_task = asyncio.create_task(self._reader_loop())

        # Fire callback
        try:
            self.on_connect()
        except Exception:
            pass

        return True

    async def disconnect(self) -> None:
        """Gracefully close the WebSocket connection.

        Fires ``on_disconnect()``.
        """
        self._stop.set()
        self._connected = False
        self._authed = False

        # Cancel background tasks
        for task in (self._heartbeat_task, self._reader_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._heartbeat_task = None
        self._reader_task = None

        await self._close_ws()
        logger.info("Disconnected")

        try:
            self.on_disconnect()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Send (with ACK)
    # ------------------------------------------------------------------

    async def send_message(
        self,
        content: str,
        to: str = "*",
    ) -> str:
        """Send a message to the WS Bridge.

        Returns a unique message ID on success, or ``""`` on failure.
        Waits for server ACK up to ``ACK_TIMEOUT`` seconds, retries on timeout.
        """
        msg_id = str(uuid.uuid4())
        payload = {
            "type": "message",
            "content": content,
            "to": to,
            "from_name": self.name,
            "agent_id": self.agent_id,
            "id": msg_id,
            "ts": time.time(),
        }

        # Register pending ACK
        event = asyncio.Event()
        self._pending_acks[msg_id] = event

        async with self._ws_lock:
            if not self._ws or not self._authed:
                logger.warning("send_message: not connected/authed")
                self._pending_acks.pop(msg_id, None)
                return ""
            try:
                await self._ws.send(json.dumps(payload))
                logger.info(">> %s (id=%s)", content[:120], msg_id[:8])
            except Exception as exc:
                logger.error("Send error: %s", exc)
                self._pending_acks.pop(msg_id, None)
                return ""

        # Wait for ACK (with retry)
        for attempt in range(1 + MAX_RETRIES):
            try:
                await asyncio.wait_for(event.wait(), timeout=ACK_TIMEOUT)
                self._pending_acks.pop(msg_id, None)
                return msg_id  # ACK received
            except asyncio.TimeoutError:
                logger.warning("No ACK for msg %s (attempt %d/%d)", msg_id[:8], attempt + 1, 1 + MAX_RETRIES)
                if attempt < MAX_RETRIES:
                    # Re-send
                    event.clear()
                    async with self._ws_lock:
                        if self._ws and self._authed:
                            try:
                                payload["ts"] = time.time()
                                await self._ws.send(json.dumps(payload))
                                logger.info(">> RETRY %s (id=%s)", content[:120], msg_id[:8])
                            except Exception:
                                pass
                else:
                    self._pending_acks.pop(msg_id, None)
                    logger.error("Msg %s failed after %d retries", msg_id[:8], MAX_RETRIES)

        return ""  # All retries exhausted

    # ------------------------------------------------------------------
    # Internal — Heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Send application-level ``{"type": "ping"}`` every *ping_interval*."""
        while not self._stop.is_set():
            await asyncio.sleep(self.ping_interval)
            async with self._ws_lock:
                ws = self._ws
            if ws is None:
                break
            try:
                await ws.send(json.dumps({"type": "ping"}))
            except Exception:
                # Will be caught by reader loop and trigger reconnect
                break

    # ------------------------------------------------------------------
    # Internal — Reader / Reconnect
    # ------------------------------------------------------------------

    async def _reader_loop(self) -> None:
        """Read incoming messages and dispatch them."""
        while not self._stop.is_set():
            async with self._ws_lock:
                ws = self._ws
            if ws is None:
                break

            raw: Optional[str] = None
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=self.read_timeout)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.warning("Read error: %s", exc)
                self._connected = False
                self._authed = False
                if self.auto_reconnect:
                    asyncio.create_task(self._reconnect_with_backoff())
                break

            if self._stop.is_set():
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Bad JSON from server: %s", raw[:100])
                continue

            await self._handle_message(msg)

    async def _reconnect_with_backoff(self) -> None:
        """Reconnect with exponential backoff (caps at RECONNECT_MAX_DELAY)."""
        delay = self._reconnect_delay
        self._reconnect_delay = min(delay * 1.5, RECONNECT_MAX_DELAY)
        await asyncio.sleep(delay)
        logger.info("Reconnecting in %.0fs...", delay)

        if self._stop.is_set():
            return

        ok = await self.connect()
        if ok:
            self._reconnect_delay = RECONNECT_BASE_DELAY
            logger.info("Reconnected successfully")

    # ------------------------------------------------------------------
    # Internal — Message dispatch
    # ------------------------------------------------------------------

    async def _handle_message(self, msg: dict) -> None:
        """Route incoming WS messages: auth_ok, ping/pong, broadcast, ack, offline, etc."""
        msg_type = msg.get("type", "")

        if msg_type == "auth_ok":
            self._authed = True
            role = msg.get("role", "member")
            logger.info("Re-auth OK (role=%s)", role)
            return

        if msg_type == "pong":
            return

        if msg_type == "pairing_code":
            code = msg.get("code", "???")
            logger.warning(
                "Pairing code received: %s — forward to admin", code
            )
            return

        if msg_type == "ack":
            ack_id = msg.get("id", "")
            if ack_id and ack_id in self._pending_acks:
                self._pending_acks[ack_id].set()
            return

        if msg_type == "offline_messages":
            msgs = msg.get("messages", [])
            count = msg.get("count", 0)
            logger.info("Received %d offline messages via catchup", count)
            if msgs:
                # Dispatch each offline message
                for m in msgs:
                    try:
                        self.on_message(m)
                    except Exception:
                        pass
                # Also fire on_offline callback if provided
                try:
                    self.on_offline(msgs)
                except Exception:
                    pass
            return

        if msg_type in ("broadcast", "message"):
            # Update last_msg_ts for offline catchup
            ts = msg.get("ts", 0)
            if ts > self._last_msg_ts:
                self._last_msg_ts = ts
                self._save_last_msg_ts()

            # Deduplication
            msg_id = msg.get("id", "")
            if msg_id:
                if msg_id in self._seen_ids:
                    return
                self._seen_ids.add(msg_id)
                if len(self._seen_ids) > self._seen_max:
                    self._seen_ids.clear()

            # Filter self-messages
            if msg.get("from") == self.agent_id or msg.get("agent_id") == self.agent_id:
                return

            # Dispatch
            try:
                self.on_message(msg)
            except Exception:
                logger.exception("on_message callback error")
            return

        if msg_type == "error":
            logger.error("Server error: %s", msg.get("error", ""))
            return

        logger.debug("Unhandled message type: %s", msg_type)

    # ------------------------------------------------------------------
    # Internal — P0: last_msg_ts persistence
    # ------------------------------------------------------------------

    def _state_file_path(self) -> str:
        """Path to the local JSON state file (alongside the bot's working dir)."""
        path = getattr(self, "state_file", None)
        if path:
            return path
        return os.path.join(os.getcwd(), STATE_FILENAME)

    def _load_last_msg_ts(self) -> float:
        """Load last_msg_ts from local JSON state file (gateway restart survival)."""
        try:
            path = self._state_file_path()
            if os.path.exists(path):
                with open(path) as f:
                    data = json.load(f)
                    return float(data.get("last_msg_ts", 0.0))
        except Exception:
            logger.debug("Failed to load state file", exc_info=True)
        return 0.0

    def _save_last_msg_ts(self) -> None:
        """Persist last_msg_ts atomically to local JSON state file."""
        try:
            path = self._state_file_path()
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"last_msg_ts": self._last_msg_ts}, f)
            os.replace(tmp, path)
        except Exception:
            logger.debug("Failed to save state file", exc_info=True)

    # ------------------------------------------------------------------
    # Internal — Utils
    # ------------------------------------------------------------------

    async def _close_ws(self) -> None:
        """Close the underlying socket (lock-protected)."""
        async with self._ws_lock:
            if self._ws:
                try:
                    await self._ws.close()
                except Exception:
                    pass
                self._ws = None

    @property
    def is_connected(self) -> bool:
        """``True`` if the client is currently connected."""
        return self._connected

    @property
    def is_authed(self) -> bool:
        """``True`` if the client has successfully authenticated."""
        return self._authed
