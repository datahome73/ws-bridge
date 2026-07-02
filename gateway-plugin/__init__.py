"""WS Bridge Gateway plugin — broadcast group chat for bots."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from gateway.config import Platform, PlatformConfig
from gateway.platform_registry import PlatformEntry, platform_registry
from gateway.platforms.base import BasePlatformAdapter, SendResult

from .ws_bridge_protocol import (
    MSG_AUTH,
    MSG_AUTH_OK,
    MSG_AUTH_ERROR,
    MSG_PAIRING_CODE,
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

# ── Env helpers (backward-compatible with WS_BRIDGE_*) ──────────────────────

def _env(key: str, default: str = "") -> str:
    """Read WS_IM_* env var with WS_BRIDGE_* fallback (1-week compat)."""
    im_key = f"WS_IM_{key}"
    bridge_key = f"WS_BRIDGE_{key}"
    return os.environ.get(im_key) or os.environ.get(bridge_key) or default


def check_requirements() -> bool:
    try:
        import websockets  # noqa: F401
        return True
    except ImportError:
        return False


def validate_config(config: PlatformConfig) -> bool:
    extra = config.extra or {}
    agent_id = extra.get("agent_id") or _env("AGENT_ID")
    url = extra.get("url") or _env("URL")
    if not agent_id:
        logger.warning("[WSBridge] AGENT_ID not configured")
        return False
    if not url:
        logger.warning("[WSBridge] URL not configured")
        return False
    return True


def is_connected(config: PlatformConfig) -> bool:
    extra = config.extra or {}
    return bool(extra.get("agent_id") or _env("AGENT_ID"))


def interactive_setup() -> None:
    print("\n--- WS Bridge Setup ---")
    url = input("WS Bridge URL (e.g. wss://example.com): ").strip()
    if url:
        print(f"Set env var: export WS_IM_URL={url}")
    agent_id = input("Your Agent ID: ").strip()
    if agent_id:
        print(f"Set env var: export WS_IM_AGENT_ID={agent_id}")
    print("Done.\n")


def _apply_yaml_config(yaml_cfg: dict, platform_cfg: dict) -> Optional[dict]:
    extra = platform_cfg.get("extra", {})
    if not isinstance(extra, dict):
        extra = {}
    seeded = {}
    for key in ("url", "agent_id", "app_id", "bot_name", "role"):
        val = extra.get(key) or _env(key.upper())
        if val:
            seeded[key] = val
    mention_mode = extra.get("mention_mode")
    if mention_mode is not None:
        seeded["mention_mode"] = bool(mention_mode)
    mention_keyword = extra.get("mention_keyword") or _env("MENTION_KEYWORD") or "admin-bot"
    seeded["mention_keyword"] = mention_keyword
    return seeded if seeded else None


def _env_enablement() -> Optional[dict]:
    extra = {}
    agent_id = _env("AGENT_ID")
    if agent_id:
        extra["agent_id"] = agent_id
    url = _env("URL")
    if url:
        extra["url"] = url
    return extra if extra else None


# ── Adapter ────────────────────────────────────────────────────────────


class WSBridgeAdapter(BasePlatformAdapter):
    """WS IM client adapter — connects to a self-hosted WS broadcast hub."""

    supports_code_blocks = True
    name = "ws_bridge"

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform("ws_bridge"))
        extra = config.extra or {}

        self._url = normalize_ws_url(
            extra.get("url") or _env("URL") or ""
        )
        self._agent_id = extra.get("agent_id") or _env("AGENT_ID") or ""
        self._app_id = extra.get("app_id") or _env("APP_ID") or ""
        self._bot_name = extra.get("bot_name") or _env("BOT_NAME") or "Hermes"
        self._role = extra.get("role") or "member"
        self._mention_mode = bool(extra.get("mention_mode", False))
        raw = extra.get("mention_keyword") or _env("MENTION_KEYWORD") or "admin-bot"
        self._mention_keywords = sorted(
            (kw.strip() for kw in raw.split(";") if kw.strip()),
            key=len, reverse=True,
        )
        self._last_msg_ts: float = 0.0
        self._active_channel: str = "lobby"

        # WS state
        self._ws: Optional[Any] = None
        self._ws_lock = __import__("asyncio").Lock()
        self._stop_event = __import__("asyncio").Event()
        self._should_reconnect = True

        logger.warning(
            "[WSBridge] Initialized (agent=%s url=%s role=%s mention=%s)",
            self._agent_id[:20], self._url, self._role, self._mention_mode,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """Connect with exponential backoff — single retry loop."""
        if not self._agent_id or not self._url:
            logger.error("[WSBridge] Missing agent_id or url")
            return False

        import asyncio
        import json as _json

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

            # Connected — send auth
            logger.warning("[WSBridge] CONNECTED — sending auth...")
            auth_msg = _json.dumps({
                "type": MSG_AUTH,
                "app_id": self._app_id,
                "agent_id": self._agent_id,
                "name": self._bot_name,
                "last_seen_ts": self._last_msg_ts,
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
                # R7: record active channel from server (owner only)
                self._active_channel = resp.get(FIELD_ACTIVE_CHANNEL, "lobby")
                logger.warning(
                    "[WSBridge] Auth OK — role=%s agent_id=%s channel=%s",
                    resp.get("role"), resp.get("agent_id", "")[:20], self._active_channel,
                )
                backoff = RECONNECT_BASE_DELAY
                # Start reader loop
                asyncio.create_task(self._reader_loop())
                return True
            elif resp_type == MSG_PAIRING_CODE:
                code = resp.get("code", "?")
                logger.warning(
                    "[WSBridge] PAIRING CODE — %s (send to admin for approval)", code
                )
                await self._ws.close()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_DELAY)
                continue
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

        import json, time

        channel = self._determine_channel(content, chat_id)

        payload = json.dumps({
            "type": MSG_MESSAGE,
            "from_name": self._bot_name,
            "agent_id": self._agent_id,
            "content": content,
            "channel": channel,
            "ts": time.time(),
        })

        async with self._ws_lock:
            if not self._ws:
                return SendResult(success=False, message_id="", error="Not connected")
            try:
                await self._ws.send(payload)
                logger.warning("[WSBridge] >> %s", content[:120])
                return SendResult(success=True, message_id=str(time.time()))
            except Exception as e:
                logger.error("[WSBridge] send error: %s", e)
                return SendResult(success=False, message_id="", error=str(e))

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        return {"name": "WS Bridge", "type": "group"}

    # ── Reader Loop ────────────────────────────────────────────────────

    async def _reader_loop(self) -> None:
        """Read messages and dispatch."""
        import asyncio, json

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
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("[WSBridge] raw: %s", str(raw)[:100])
                continue

            await self._handle_ws_message(msg)

        # Reader loop exited — reconnect
        if self._should_reconnect and not self._stop_event.is_set():
            logger.warning("[WSBridge] Reader loop ended — reconnecting...")
            await asyncio.sleep(RECONNECT_BASE_DELAY)
            asyncio.create_task(self.connect())

    # ── Message Handling ───────────────────────────────────────────────

    async def _handle_ws_message(self, msg: dict) -> None:
        """Handle incoming WS message."""
        msg_type = msg.get("type")

        if msg_type == MSG_BROADCAST:
            # Support both new and legacy field names
            content = msg.get("content", "")
            from_name = msg.get("from_name") or msg.get("from", "")
            from_agent = msg.get("agent_id") or msg.get("from_agent", "")

            if not content or not from_name:
                return

            # Track last message timestamp for reconnection catchup
            ts = msg.get("ts", 0)
            if ts > self._last_msg_ts:
                self._last_msg_ts = ts

            logger.warning("[WSBridge] << broadcast from=%s: %s", from_name, content[:200])

            # Filter self-messages
            if from_agent == self._agent_id or from_name == self._bot_name:
                return

            # Mention mode: only respond when keyword present
            if self._mention_mode:
                if not any(kw in content for kw in self._mention_keywords):
                    logger.warning(
                        "[WSBridge] Silent: no mention keyword in %s",
                        self._mention_keywords,
                    )
                    return

            # Strip mention prefix if present — try each keyword (longest first)
            text = content
            for kw in sorted(self._mention_keywords, key=len, reverse=True):
                if text.startswith(kw):
                    text = text[len(kw):].strip()
                    break

            await self._process_inbound_message(text, msg)

        elif msg_type == MSG_AUTH_OK:
            logger.warning("[WSBridge] Re-auth OK — role=%s", msg.get("role"))
            # R7: update active channel on re-auth
            self._active_channel = msg.get(FIELD_ACTIVE_CHANNEL, "lobby")

        elif msg_type == MSG_PAIRING_CODE:
            code = msg.get("code", "?")
            logger.warning("[WSBridge] PAIRING CODE — %s (forward to admin)", code)

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
        import json
        workspace_id = msg.get(FIELD_WORKSPACE_ID, "?")
        deadline_ts = msg.get("deadline_ts", 0)

        logger.warning(
            "[WSBridge] Workspace '%s' closing — deadline=%s, cleaning up",
            workspace_id, deadline_ts,
        )

        # Reset channel state
        self._active_channel = "lobby"

        # Send ACK
        ack = json.dumps({
            "type": MSG_WORKSPACE_ACK_CLOSE,
            "workspace_id": workspace_id,
            "agent_id": self._agent_id,
            "ts": __import__("time").time(),
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
        if "@admin" in content or any(f"@{kw}" in content for kw in self._mention_keywords):
            return "lobby"
        return self._active_channel or "lobby"

    async def _process_inbound_message(self, content: str, raw_msg: dict) -> None:
        """Build MessageEvent and dispatch to Gateway handler."""
        from datetime import datetime
        from gateway.platforms.base import MessageEvent, MessageType

        # R7: record channel from broadcast for reply routing
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


# ── Register ────────────────────────────────────────────────────────────

def register(ctx) -> None:
    ctx.register_platform(
        name="ws_bridge",
        label="WS Bridge",
        adapter_factory=lambda cfg: WSBridgeAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=is_connected,
        required_env=["WS_IM_URL", "WS_IM_AGENT_ID"],
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
