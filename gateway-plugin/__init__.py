"""WS Bridge Gateway plugin — broadcast group chat for bots (R72+).

Uses the new R72 auth: register → api_key → auth(api_key).
Credentials are stored in ``~/.ws-bridge/{display_name}.json``.
"""

from __future__ import annotations

import json as _json
import logging
import os
import time
from typing import Any, Dict, Optional

from gateway.config import Platform, PlatformConfig
from gateway.platform_registry import PlatformEntry, platform_registry
from gateway.platforms.base import BasePlatformAdapter, SendResult

from .ws_bridge_protocol import (
    MSG_AUTH,
    MSG_AUTH_OK,
    MSG_AUTH_ERROR,
    MSG_BROADCAST,
    MSG_MESSAGE,
    MSG_ACK,
    MSG_ERROR,
    MSG_PONG,
    MSG_WORKSPACE_CLOSING,
    MSG_WORKSPACE_ACK_CLOSE,
    MSG_SET_ACTIVE_CHANNEL,
    MSG_CHANNEL_UPDATED,
    FIELD_CHANNEL,
    FIELD_ACTIVE_CHANNEL,
    FIELD_WORKSPACE_ID,
    normalize_ws_url,
    RECONNECT_BASE_DELAY,
    RECONNECT_MAX_DELAY,
    PING_INTERVAL,
)

logger = logging.getLogger(__name__)

# ── Credential helpers ──────────────────────────────────────────────

CRED_DIR = os.path.expanduser("~/.ws-bridge")


def _cred_path(name: str) -> str:
    return os.path.join(CRED_DIR, f"{name}.json")


def _load_creds(name: str) -> Optional[dict]:
    """Load credentials from ``~/.ws-bridge/{name}.json``."""
    path = _cred_path(name)
    try:
        if os.path.exists(path):
            with open(path) as f:
                return _json.load(f)
    except Exception as e:
        logger.warning("[WSBridge] Failed to load creds from %s: %s", path, e)
    return None


# ── Env helpers ─────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    im_key = f"WS_IM_{key}"
    bridge_key = f"WS_BRIDGE_{key}"
    return os.environ.get(im_key) or os.environ.get(bridge_key) or default


# ── Platform callbacks ──────────────────────────────────────────────

def check_requirements() -> bool:
    try:
        import websockets  # noqa: F401
        return True
    except ImportError:
        return False


def validate_config(config: PlatformConfig) -> bool:
    extra = config.extra or {}
    url = extra.get("url") or _env("URL")
    if not url:
        logger.warning("[WSBridge] URL not configured")
        return False
    # api_key can be in env, config, or ~/.ws-bridge/{name}.json
    return True


def is_connected(config: PlatformConfig) -> bool:
    return True  # connected state managed by adapter instance


def interactive_setup() -> None:
    print("\n--- WS Bridge Setup (R72) ---")
    url = input("WS Bridge URL (e.g. wss://wsim.datahome73.cloud/ws): ").strip()
    if url:
        print(f"Set env var: export WS_IM_URL={url}")
    name = input("Your display name (e.g. 小谷): ").strip()
    if name:
        print(f"Set env var: export WS_IM_BOT_NAME={name}")
        print(f"Or place credentials at ~/.ws-bridge/{name}.json")
    api_key = input("API key (or leave blank to use cred file): ").strip()
    if api_key:
        print("Set env var: export WS_IM_API_KEY=...")
    print("Done.\n")


def _apply_yaml_config(yaml_cfg: dict, platform_cfg: dict) -> Optional[dict]:
    extra = platform_cfg.get("extra", {})
    if not isinstance(extra, dict):
        extra = {}
    seeded = {}
    for key in ("url", "api_key", "bot_name", "role"):
        val = extra.get(key) or _env(key.upper())
        if val:
            seeded[key] = val
    mention_mode = extra.get("mention_mode")
    if mention_mode is not None:
        seeded["mention_mode"] = bool(mention_mode)
    mention_keyword = extra.get("mention_keyword") or _env("MENTION_KEYWORD") or ""
    seeded["mention_keyword"] = mention_keyword
    return seeded if seeded else None


def _env_enablement() -> Optional[dict]:
    extra = {}
    url = _env("URL")
    if url:
        extra["url"] = url
    api_key = _env("API_KEY")
    if api_key:
        extra["api_key"] = api_key
    name = _env("BOT_NAME")
    if name:
        extra["bot_name"] = name
    return extra if extra else None


# ── Adapter ─────────────────────────────────────────────────────────

class WSBridgeAdapter(BasePlatformAdapter):
    """WS Bridge adapter (R72+ new auth via api_key).

    Connects to a self-hosted WS Bridge hub using the new R72 auth flow.
    Credentials are loaded from:
      1. ``api_key`` config field / ``WS_IM_API_KEY`` env var
      2. ``~/.ws-bridge/{bot_name}.json`` (automatic fallback)
    """

    supports_code_blocks = True
    name = "ws_bridge"

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform("ws_bridge"))
        extra = config.extra or {}

        self._url = normalize_ws_url(
            extra.get("url") or _env("URL") or ""
        )
        self._bot_name = extra.get("bot_name") or _env("BOT_NAME") or "bot"
        self._role = extra.get("role") or "member"
        self._mention_mode = bool(extra.get("mention_mode", False))
        raw = extra.get("mention_keyword") or _env("MENTION_KEYWORD") or ""
        self._mention_keywords = sorted(
            (kw.strip() for kw in raw.split(";") if kw.strip()),
            key=len, reverse=True,
        )

        # ── Resolve api_key ──
        api_key = extra.get("api_key") or _env("API_KEY") or ""
        agent_id = ""

        # Fallback: load from ~/.ws-bridge/{name}.json
        if not api_key:
            creds = _load_creds(self._bot_name)
            if creds:
                api_key = creds.get("api_key", "")
                agent_id = creds.get("agent_id", "")
                logger.info(
                    "[WSBridge] Loaded creds from ~/.ws-bridge/%s.json (agent=%s)",
                    self._bot_name, agent_id[:16],
                )

        self._api_key = api_key
        self._agent_id = agent_id

        # If we didn't get api_key yet, fail gracefully at connect time
        self._last_msg_ts: float = 0.0
        self._active_channel: str = "lobby"

        # WS state
        self._ws: Optional[Any] = None
        self._ws_lock = __import__("asyncio").Lock()
        self._stop_event = __import__("asyncio").Event()
        self._should_reconnect = True

        logger.warning(
            "[WSBridge] Initialized (bot=%s url=%s %s%s)",
            self._bot_name, self._url,
            "api_key=***" if self._api_key else "NO API KEY",
            f" agent_id={agent_id[:16]}" if agent_id else "",
        )

    # ── Lifecycle ──────────────────────────────────────────────────

    async def connect(self, **kwargs) -> bool:
        """Connect with exponential backoff — single retry loop.

        Uses R72 auth: send ``{"type": "auth", "api_key": ...}``.
        """
        if not self._url:
            logger.error("[WSBridge] URL not configured")
            return False
        if not self._api_key:
            logger.error(
                "[WSBridge] No api_key for '%s'. Set WS_IM_API_KEY "
                "or place ~/.ws-bridge/%s.json", self._bot_name, self._bot_name
            )
            return False

        import asyncio

        self._stop_event.clear()
        self._should_reconnect = True
        backoff = RECONNECT_BASE_DELAY

        try:
            import websockets
        except ImportError:
            logger.error("[WSBridge] websockets not installed")
            return False

        while self._should_reconnect:
            try:
                self._ws = await websockets.connect(
                    self._url,
                    ping_interval=PING_INTERVAL,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2 ** 20,
                )
            except asyncio.CancelledError:
                self._should_reconnect = False
                break
            except Exception as e:
                logger.error(
                    "[WSBridge] Connection failed: %s — retry in %ds", e, backoff
                )
                if self._should_reconnect:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, RECONNECT_MAX_DELAY)
                continue

            # Connected — send R72 auth (just api_key)
            logger.warning("[WSBridge] CONNECTED — sending R72 auth...")
            auth_msg = _json.dumps({
                "type": MSG_AUTH,
                "api_key": self._api_key,
            })
            try:
                await self._ws.send(auth_msg)
            except Exception as e:
                logger.error("[WSBridge] Auth send failed: %s", e)
                await self._ws.close()
                continue

            # Wait for auth response
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
                resp = _json.loads(raw)
            except Exception as e:
                logger.error("[WSBridge] No auth response: %s", e)
                await self._ws.close()
                continue

            resp_type = resp.get("type")
            if resp_type == MSG_AUTH_OK:
                self._agent_id = resp.get("agent_id", self._agent_id)
                self._active_channel = resp.get(FIELD_ACTIVE_CHANNEL, "lobby")
                logger.warning(
                    "[WSBridge] Auth OK — agent_id=%s display_name=%s channel=%s",
                    self._agent_id[:20], resp.get("display_name", "?"),
                    self._active_channel,
                )
                backoff = RECONNECT_BASE_DELAY
                asyncio.create_task(self._reader_loop())
                return True
            elif resp_type == MSG_AUTH_ERROR:
                logger.error(
                    "[WSBridge] Auth error: %s", resp.get("error", "unknown")
                )
                await self._ws.close()
                # Don't retry on auth error — credentials are wrong
                self._should_reconnect = False
                return False
            else:
                logger.error("[WSBridge] Unexpected auth response: %s", str(resp)[:200])
                await self._ws.close()
                continue

        return False

    async def disconnect(self) -> None:
        """Disconnect and stop reconnection."""
        self._stop_event.set()
        self._should_reconnect = False
        import asyncio
        async with self._ws_lock:
            if self._ws:
                try:
                    await self._ws.close()
                except Exception:
                    pass
                self._ws = None
        logger.warning("[WSBridge] Disconnected")

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Broadcast a message to all connected bots."""
        if not self._ws:
            return SendResult(success=False, message_id="", error="Not connected")

        channel = self._determine_channel(content, chat_id)
        msg_id = str(time.time())

        payload = _json.dumps({
            "type": MSG_MESSAGE,
            "from_name": self._bot_name,
            "agent_id": self._agent_id,
            "content": content,
            "channel": channel,
            "id": msg_id,
            "ts": time.time(),
        })

        async with self._ws_lock:
            if not self._ws:
                return SendResult(success=False, message_id="", error="Not connected")
            try:
                await self._ws.send(payload)
                logger.warning("[WSBridge] >> %s", content[:120])
                return SendResult(success=True, message_id=msg_id)
            except Exception as e:
                logger.error("[WSBridge] send error: %s", e)
                return SendResult(success=False, message_id="", error=str(e))

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        return {"name": "WS Bridge", "type": "group"}

    # ── Reader Loop ────────────────────────────────────────────────

    async def _reader_loop(self) -> None:
        """Read messages and dispatch."""
        import asyncio

        while not self._stop_event.is_set():
            async with self._ws_lock:
                ws = self._ws
            if not ws:
                break

            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning("[WSBridge] Read error: %s", e)
                break

            if self._stop_event.is_set():
                break

            try:
                msg = _json.loads(raw)
            except _json.JSONDecodeError:
                logger.warning("[WSBridge] raw: %s", str(raw)[:100])
                continue

            await self._handle_ws_message(msg)

        # Reader loop exited — reconnect
        if self._should_reconnect and not self._stop_event.is_set():
            logger.warning("[WSBridge] Reader loop ended — reconnecting...")
            await asyncio.sleep(RECONNECT_BASE_DELAY)
            asyncio.create_task(self.connect())

    # ── Message Handling ───────────────────────────────────────────

    async def _handle_ws_message(self, msg: dict) -> None:
        """Handle incoming WS message."""
        msg_type = msg.get("type")

        if msg_type == MSG_BROADCAST:
            content = msg.get("content", "")
            from_name = msg.get("from_name") or msg.get("from", "")
            from_agent = msg.get("agent_id") or msg.get("from_agent", "")

            if not content or not from_name:
                return

            ts = msg.get("ts", 0)
            if ts > self._last_msg_ts:
                self._last_msg_ts = ts

            logger.warning(
                "[WSBridge] << broadcast from=%s: %s", from_name, content[:200]
            )

            # Filter self-messages
            if from_agent == self._agent_id or from_name == self._bot_name:
                return

            # Mention mode: only respond when keyword present
            if self._mention_mode and self._mention_keywords:
                if not any(kw in content for kw in self._mention_keywords):
                    logger.warning(
                        "[WSBridge] Silent: no mention keyword in %s",
                        self._mention_keywords,
                    )
                    return

            # Strip mention prefix if present
            text = content
            for kw in sorted(self._mention_keywords, key=len, reverse=True):
                if text.startswith(kw):
                    text = text[len(kw):].strip()
                    break

            await self._process_inbound_message(text, msg)

        elif msg_type == MSG_AUTH_OK:
            self._agent_id = msg.get("agent_id", self._agent_id)
            self._active_channel = msg.get(FIELD_ACTIVE_CHANNEL, "lobby")
            logger.warning(
                "[WSBridge] Re-auth OK — agent_id=%s", self._agent_id[:20]
            )

        elif msg_type == MSG_ERROR:
            logger.warning("[WSBridge] Server error: %s", msg.get("error", ""))

        elif msg_type == MSG_WORKSPACE_CLOSING:
            await self._handle_workspace_closing(msg)

        elif msg_type == MSG_SET_ACTIVE_CHANNEL:
            self._active_channel = msg.get(FIELD_CHANNEL, "lobby")
            logger.warning(
                "[WSBridge] Active channel set to: %s", self._active_channel
            )

        elif msg_type == MSG_CHANNEL_UPDATED:
            new_channel = msg.get(FIELD_ACTIVE_CHANNEL, "lobby")
            self._active_channel = new_channel
            logger.warning("[WSBridge] Active channel updated to '%s'", new_channel)

    async def _handle_workspace_closing(self, msg: dict) -> None:
        """Handle workspace closing notification — clean up and ACK."""
        workspace_id = msg.get(FIELD_WORKSPACE_ID, "?")
        deadline_ts = msg.get("deadline_ts", 0)

        logger.warning(
            "[WSBridge] Workspace '%s' closing — deadline=%s, cleaning up",
            workspace_id, deadline_ts,
        )

        self._active_channel = "lobby"

        ack = _json.dumps({
            "type": MSG_WORKSPACE_ACK_CLOSE,
            "workspace_id": workspace_id,
            "agent_id": self._agent_id,
            "ts": time.time(),
        })

        async with self._ws_lock:
            if self._ws:
                try:
                    await self._ws.send(ack)
                    logger.warning(
                        "[WSBridge] Workspace '%s' ACK sent", workspace_id
                    )
                except Exception as e:
                    logger.error(
                        "[WSBridge] Workspace ACK send failed: %s", e
                    )

    def _determine_channel(self, content: str, context_channel: str) -> str:
        """Determine channel: @admin goes to lobby, others use active channel."""
        if any(f"@{kw}" in content for kw in self._mention_keywords):
            return "lobby"
        return self._active_channel or "lobby"

    async def _process_inbound_message(self, content: str, raw_msg: dict) -> None:
        """Build MessageEvent and dispatch to Gateway handler."""
        from datetime import datetime
        from gateway.platforms.base import MessageEvent, MessageType

        broadcast_channel = raw_msg.get(FIELD_CHANNEL, "lobby")
        if broadcast_channel != "lobby":
            self._active_channel = broadcast_channel

        source = self.build_source(
            chat_id=broadcast_channel,
            chat_name="WS Bridge",
            chat_type="group",
            user_id="ws_bridge_user",
            user_name="WS Bridge",
            message_id=str(raw_msg.get("ts", "")),
        )

        event = MessageEvent(
            text=content,
            message_type=MessageType.TEXT,
            source=source,
            raw_message=raw_msg,
            message_id=str(raw_msg.get("ts", "")),
            timestamp=datetime.now(),
        )

        logger.warning("[WSBridge] Dispatching to handle_message")
        try:
            await self.handle_message(event)
        except Exception as e:
            logger.error("[WSBridge] handle_message error: %s", e, exc_info=True)


# ── Register ────────────────────────────────────────────────────────

def register(ctx) -> None:
    ctx.register_platform(
        name="ws_bridge",
        label="WS Bridge",
        adapter_factory=lambda cfg: WSBridgeAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=is_connected,
        required_env=["WS_IM_URL"],
        install_hint="pip install websockets",
        setup_fn=interactive_setup,
        env_enablement_fn=_env_enablement,
        apply_yaml_config_fn=_apply_yaml_config,
        emoji="🌉",
        allow_update_command=False,
        platform_hint=(
            "You are chatting via WS Bridge — a self-hosted broadcast group chat for bots. "
            "STRICT RULES: "
            "1. This is a shared channel — ALL connected bots see your messages. "
            "2. Text-only — NO files, images, voice, or media. "
            "3. Do NOT output internal thinking, reasoning traces, or tool calls. "
            "4. Keep responses concise and conversational. "
            "5. If the message doesn't start with your name, it may not be directed at you."
        ),
    )
