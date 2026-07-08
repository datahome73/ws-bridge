"""WS Bridge client — reusable async WebSocket client library (R72+).

Features:
  - R72 new auth: register → api_key → agent_card_register → auth(api_key)
  - Credential management via ``~/.ws-bridge/{name}.json``
  - WebSocket-level ping/pong keep-alive (ping_interval=20)
  - Automatic reconnection with exponential backoff
  - on_connect / on_disconnect / on_message callbacks
  - send_message returns a unique message ID
  - Thread-safe message deduplication via seen_ids
  - ACK waiting + retry on timeout
  - Offline catchup via last_seen_ts (persisted to JSON file)
  - Inbox message protocol (R82+):
    All received messages are inbox messages.
    Reply = send_message(content, channel=f"_inbox:{sender_agent_id}")
    sender_agent_id from msg.agent_id or msg.from_agent.
    See docs/inbox-message-protocol.md for details.
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
WS_URL = "wss://wsim.datahome73.cloud/ws"
MAX_SIZE = 2 ** 20          # 1 MB
MAX_READ_TIMEOUT = 60.0     # read timeout (generous, heartbeat keeps it alive)
RECONNECT_BASE_DELAY = 3.0
RECONNECT_MAX_DELAY = 30.0
ACK_TIMEOUT = 5.0
MAX_RETRIES = 2
STATE_FILENAME = "ws_bridge_state.json"
CRED_DIR = os.path.expanduser("~/.ws-bridge")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_cred_dir() -> str:
    """Create ``~/.ws-bridge/`` if it doesn't exist."""
    os.makedirs(CRED_DIR, exist_ok=True)
    return CRED_DIR


def cred_path(name: str) -> str:
    """Path to credential file for a given display name.

    Example: ``~/.ws-bridge/小谷.json``
    """
    return os.path.join(CRED_DIR, f"{name}.json")


def load_creds(name: str) -> dict:
    """Load credentials from ``~/.ws-bridge/{name}.json``.

    Returns ``{"agent_id": ..., "api_key": ..., "display_name": ...}``.

    Raises ``FileNotFoundError`` if the file doesn't exist.
    """
    path = cred_path(name)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Credentials not found at {path}. "
            f"Run register() first or place the JSON file manually."
        )
    with open(path) as f:
        return json.load(f)


def save_creds(agent_id: str, api_key: str, display_name: str) -> str:
    """Save credentials to ``~/.ws-bridge/{display_name}.json``.

    Returns the file path.
    """
    ensure_cred_dir()
    path = cred_path(display_name)
    with open(path, "w") as f:
        json.dump({
            "agent_id": agent_id,
            "api_key": api_key,
            "display_name": display_name,
        }, f, indent=2)
    logger.info("Credentials saved to %s", path)
    return path


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class WsBridgeClient:
    """Connect to a WS Bridge server (R72+ new auth).

    Typical usage::

        # First-time registration
        client = WsBridgeClient(name="小谷")
        await client.register()
        # → credentials saved to ~/.ws-bridge/小谷.json
        # → Agent Card registered
        # → connection stays open

        # Subsequent runs (load existing credentials)
        client = WsBridgeClient(name="小谷")
        await client.connect()
        await client.send_message("Hello!")
        # ...
        await client.disconnect()
    """

    def __init__(
        self,
        ws_url: str = WS_URL,
        name: str = "bot",
        *,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        on_message: Optional[Callable[[dict], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        on_offline: Optional[Callable[[list[dict]], None]] = None,
        read_timeout: float = MAX_READ_TIMEOUT,
        auto_reconnect: bool = True,
        state_file: Optional[str] = None,
    ):
        self.ws_url = ws_url
        self.name = name
        self.api_key = api_key
        self._agent_id = agent_id
        self.on_message = on_message or (lambda msg: None)
        self.on_connect = on_connect or (lambda: None)
        self.on_disconnect = on_disconnect or (lambda: None)
        self.on_offline = on_offline or (lambda msgs: None)
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

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def agent_id(self) -> Optional[str]:
        return self._agent_id

    @property
    def is_connected(self) -> bool:
        """``True`` if the client is currently connected."""
        return self._connected

    @property
    def is_authed(self) -> bool:
        """``True`` if the client has successfully authenticated."""
        return self._authed

    # ------------------------------------------------------------------
    # Register (first time)
    # ------------------------------------------------------------------

    async def register(
        self,
        description: str = "",
        pipeline_roles: Optional[list[str]] = None,
        skills: Optional[list[str]] = None,
        trigger_keyword: Optional[str] = None,
        capabilities: Optional[dict] = None,
    ) -> dict:
        """R72 first-time registration.

        Steps:
          1. ``register`` → get ``agent_id`` + ``api_key``
          2. Save credentials to ``~/.ws-bridge/{name}.json``
          3. ``agent_card_register`` → declare capabilities

        Returns the server's registration response dict.

        After calling this, use ``connect()`` on subsequent runs.
        """
        import websockets

        logger.info("Registering bot '%s' ...", self.name)

        async with websockets.connect(
            self.ws_url, max_size=MAX_SIZE,
            ping_interval=20, ping_timeout=10,
        ) as ws:
            # ── 1. register ──
            await ws.send(json.dumps({
                "type": "register",
                "display_name": self.name,
                "description": description or f"{self.name} bot",
            }))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if resp.get("type") != "register_ok":
                raise RuntimeError(f"Register failed: {resp}")

            agent_id = resp["agent_id"]
            api_key = resp["api_key"]
            self._agent_id = agent_id
            self.api_key = api_key

            logger.info("Registered: agent_id=%s display_name=%s",
                        agent_id, resp.get("display_name"))

            # Save credentials
            save_creds(agent_id, api_key, self.name)

            # Drain residual messages
            await asyncio.sleep(0.5)
            for _ in range(3):
                try:
                    await asyncio.wait_for(ws.recv(), timeout=0.3)
                except (asyncio.TimeoutError, Exception):
                    break

            # ── 2. agent_card_register ──
            card_payload: dict[str, Any] = {
                "type": "agent_card_register",
                "display_name": self.name,
                "description": description or f"{self.name} bot",
                "pipeline_roles": pipeline_roles or [],
                "skills": skills or [],
                "trigger_keyword": trigger_keyword or self.name,
                "capabilities": capabilities or {
                    "platforms": ["ws-bridge"],
                    "skills": skills or [],
                },
            }
            await ws.send(json.dumps(card_payload))
            card = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))

            got_name = card.get("display_name", "")
            assert got_name == self.name, (
                f"display_name mismatch: got '{got_name}' != expected '{self.name}'"
            )
            logger.info("Agent Card registered: status=%s agent_id=%s",
                        card.get("status"), card.get("agent_id"))

            return card

    # ------------------------------------------------------------------
    # Connect (subsequent runs)
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Open WebSocket connection and authenticate via R72 api_key.

        Loads credentials from ``~/.ws-bridge/{name}.json`` if ``api_key``
        was not passed to the constructor.

        Returns ``True`` on success, ``False`` on failure.
        On success, fires ``on_connect()``.
        """
        import websockets

        self._stop.clear()
        self._authed = False

        # Load credentials from file if not provided
        if not self.api_key:
            try:
                creds = load_creds(self.name)
                self.api_key = creds["api_key"]
                self._agent_id = creds.get("agent_id", self._agent_id)
            except FileNotFoundError as exc:
                logger.error("No credentials for '%s': %s", self.name, exc)
                return False

        if not self.api_key:
            logger.error("No api_key available for '%s'", self.name)
            return False

        try:
            self._ws = await websockets.connect(
                self.ws_url,
                max_size=MAX_SIZE,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            )
        except Exception as exc:
            logger.error("Connection failed: %s", exc)
            self._connected = False
            return False

        self._connected = True
        logger.info("Connected to %s", self.ws_url)

        # Send auth with api_key (R72)
        try:
            await self._ws.send(json.dumps({
                "type": "auth",
                "api_key": self.api_key,
            }))
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
            resp = json.loads(raw)
            msg_type = resp.get("type", "")

            if msg_type == "auth_ok":
                self._authed = True
                self._agent_id = resp.get("agent_id", self._agent_id)
                logger.info("Auth OK: agent_id=%s display_name=%s",
                            self._agent_id, resp.get("display_name"))
            elif msg_type == "auth_error":
                logger.error("Auth error: %s", resp.get("error", "unknown"))
                await self._close_ws()
                return False
            else:
                logger.warning("Unexpected auth response: %s", raw[:200])
                await self._close_ws()
                return False
        except asyncio.TimeoutError:
            logger.error("Auth timed out (no response within 10s)")
            await self._close_ws()
            return False
        except Exception as exc:
            logger.error("Auth failed: %s", exc)
            await self._close_ws()
            return False

        # Start reader loop
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

        # Cancel background task
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
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
        channel: str | None = None,
    ) -> str:
        """Send a message to the WS Bridge.

        Use ``channel`` to send to a workspace (e.g. ``ws:01KT...``).
        Use ``to`` (default ``"*"``) for lobby broadcast or ``@user`` for DM.
        When ``channel`` is set, ``to`` is ignored (workspace routing).

        Returns a unique message ID on success, or ``""`` on failure.
        Waits for server ACK up to ``ACK_TIMEOUT`` seconds, retries on timeout.
        """
        msg_id = str(uuid.uuid4())
        payload = {
            "type": "message",
            "content": content,
            "from_name": self.name,
            "agent_id": self._agent_id or "",
            "id": msg_id,
            "ts": time.time(),
        }
        if channel:
            payload["channel"] = channel
        else:
            payload["to"] = to

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
                logger.warning("No ACK for msg %s (attempt %d/%d)",
                               msg_id[:8], attempt + 1, 1 + MAX_RETRIES)
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
                    logger.error("Msg %s failed after %d retries",
                                 msg_id[:8], MAX_RETRIES)

        return ""  # All retries exhausted

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
        """Route incoming WS messages: auth_ok, pong, broadcast, ack, offline, etc."""
        msg_type = msg.get("type", "")

        if msg_type == "auth_ok":
            self._authed = True
            self._agent_id = msg.get("agent_id", self._agent_id)
            logger.info("Re-auth OK: agent_id=%s", self._agent_id)
            return

        if msg_type == "pong":
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
            sender = msg.get("from") or msg.get("agent_id") or ""
            if sender == self._agent_id:
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
    # Internal — last_msg_ts persistence
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
