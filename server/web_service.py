#!/usr/bin/env python3
"""R101: Web HTTP service — standalone, no WebSocket.

Reads from SQLite DB (shared DATA_DIR), serves HTML + JSON APIs.
5-second polling replaces former WS push.

R102: Bot status cache — background poll from WSS core /api/status.
"""
import asyncio
import os
import time

import aiohttp
from aiohttp import web

from .config import DATA_DIR, HOST, PORT as WSS_PORT
from . import web_viewer
from . import persistence
from . import message_store as ms

MY_PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8766"))

# ── R102: In-memory bot status cache ─────────────────────────────────
# Background task polls WSS core's /api/status every N seconds.
_BOT_STATUS_CACHE: dict = {"agents": [], "_last_update": 0}
_BOT_POLL_INTERVAL = 10  # seconds


async def _fetch_bot_status() -> dict:
    """Fetch bot status from WSS core's /api/status endpoint."""
    url = f"http://127.0.0.1:{WSS_PORT}/api/status"
    try:
        async with asyncio.timeout(5):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
    except Exception:
        pass
    return {"agents": []}


async def _poll_bot_status_loop(app: web.Application) -> None:
    """Periodic background task: poll WSS core and cache result."""
    while True:
        try:
            data = await _fetch_bot_status()
            data["_last_update"] = time.time()
            _BOT_STATUS_CACHE.clear()
            _BOT_STATUS_CACHE.update(data)
        except Exception:
            pass
        await asyncio.sleep(_BOT_POLL_INTERVAL)


async def _api_status(request: web.Request) -> web.Response:
    """Return cached bot online/offline status."""
    return web.json_response({
        "agents": _BOT_STATUS_CACHE.get("agents", []),
        "cached_at": _BOT_STATUS_CACHE.get("_last_update", 0),
    })


# ── Main ──────────────────────────────────────────────────────────


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    persistence.load_web_sessions(DATA_DIR)
    ms.init_db(DATA_DIR)

    app = web.Application()
    web_viewer.setup_routes(app)

    # R102: register /api/bot_status + start background poll
    app.router.add_get("/api/bot_status", _api_status)
    app.on_startup.append(lambda a: asyncio.create_task(_poll_bot_status_loop(a)))

    print(f"WEB READY: http://{HOST}:{MY_PORT}/", flush=True)
    web.run_app(app, host=HOST, port=MY_PORT)


if __name__ == "__main__":
    main()
