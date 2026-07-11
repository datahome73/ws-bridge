#!/usr/bin/env python3
"""R101: Web HTTP service — standalone, no WebSocket.

Reads from SQLite DB (shared DATA_DIR), serves HTML + JSON APIs.
5-second polling replaces former WS push.
"""
import os
from aiohttp import web
from .config import DATA_DIR, HOST
from . import web_viewer
from . import persistence
from . import message_store as ms

PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8766"))


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    persistence.load_web_sessions(DATA_DIR)
    ms.init_db(DATA_DIR)

    app = web.Application()
    web_viewer.setup_routes(app)

    print(f"WEB READY: http://{HOST}:{PORT}/", flush=True)
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
