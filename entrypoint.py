#!/usr/bin/env python3
"""Minimal ws-bridge server entrypoint for Railway."""
import sys, os, asyncio, logging
from aiohttp import web

logging.basicConfig(level=logging.INFO, format='%(name)s %(levelname)s %(message)s')

HOST = os.environ.get("WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_PORT") or os.environ.get("PORT", "8765"))
DATA_DIR = os.environ.get("WS_DATA_DIR", "./data")

os.makedirs(DATA_DIR, exist_ok=True)

from server.persistence import load_pairing_codes, load_approved_users, load_web_bind_codes, load_web_sessions, load_api_keys
import server.config as cfg

load_pairing_codes(cfg.DATA_DIR)
load_approved_users(cfg.DATA_DIR)
load_web_bind_codes(cfg.DATA_DIR)
load_web_sessions(cfg.DATA_DIR)
load_api_keys(cfg.DATA_DIR)  # R72: API Key 存储

from server.web_viewer import setup_routes
from server.__main__ import ws_handler, _api_status, _api_search, _api_health, _auth_callback, init_db

app = web.Application()
app.router.add_get("/ws", ws_handler)
setup_routes(app)

# Initialise workspace module
import server.workspace as ws_mod
ws_mod.init()
from server import workspace_api as _ws_api

# ── Round 3 routes (P1 online status, P2 auth callback, P3 search, P5 health)
app.router.add_get("/api/status", _api_status)
app.router.add_get("/auth-callback", _auth_callback)
app.router.add_get("/api/chat/search", _api_search)
app.router.add_get("/api/health", _api_health)
# ── R4: Workspace API
app.router.add_get("/api/workspaces", _ws_api.api_workspaces)

# Init message store DB
init_db(cfg.DATA_DIR)

# R38: Init Task store + Agent Cards
from server.task_store import init_db as init_task_store
init_task_store(cfg.DATA_DIR)
from server.agent_card import load_cards
load_cards()

print(f"READY: http://{HOST}:{PORT}/", flush=True)

web.run_app(app, host=HOST, port=PORT, print=lambda *a: None)
