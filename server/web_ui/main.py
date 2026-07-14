#!/usr/bin/env python3
"""R101: Web HTTP service — standalone, no WebSocket.

Reads from SQLite DB (shared DATA_DIR), serves HTML + JSON APIs.
5-second polling replaces former WS push.

R102: Bot status cache — background poll from WSS core /api/status.
"""
import asyncio
import logging
import os
import time

import aiohttp
from aiohttp import web

from server.common.config import DATA_DIR, HOST, PORT as WSS_PORT, HTTP_PORT
from server.common import persistence
from server.common import message_store as ms
from server.web_ui import viewer

MY_PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8766"))

# ── R102: In-memory bot status cache ─────────────────────────────────
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


async def _wait_for_wss_ready(max_wait=30):
    """启动时等待 WS 进程的 /api/status 就绪。"""
    url = f"http://127.0.0.1:{WSS_PORT}/api/status"
    for i in range(max_wait):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=2) as resp:
                    if resp.status == 200:
                        return True
        except Exception:
            pass
        await asyncio.sleep(1)
    logger = logging.getLogger("ws-bridge.web")
    logger.warning("WSS not ready after %ds — bot status cache will start empty", max_wait)
    return False


async def _run_app(app: web.Application) -> None:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, MY_PORT)
    await site.start()
    print(f"WEB READY: http://{HOST}:{MY_PORT}/", flush=True)
    await asyncio.Event().wait()


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    persistence.load_api_keys(DATA_DIR)
    persistence.load_approved_users(DATA_DIR)
    viewer.load_web_sessions(DATA_DIR)

    app = web.Application()
    viewer.setup_routes(app)

    # R102: register /api/bot_status + start background poll
    app.router.add_get("/api/bot_status", _api_status)
    async def _start_poll(app):
        asyncio.ensure_future(_poll_bot_status_loop(app))
    app.on_startup.append(_start_poll)

    async def _wait_wss(app):
        await _wait_for_wss_ready()
    app.on_startup.append(_wait_wss)

    asyncio.run(_run_app(app))


if __name__ == "__main__":
    main()
