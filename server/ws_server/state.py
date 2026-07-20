"""R100: Shared state container — module-level globals extracted from handler.py.

Zero business logic, zero function definitions.
Pure data structures shared across server/ modules.
No reverse dependencies on any server module.
"""

import asyncio
import os

from .pipeline_context import PipelineContextManager

_PIPELINE_CONFIG: dict[str, dict] = {}  # round_name -> read-only config from WORK_PLAN

# R79: 系统消息发送者标识
SYSTEM_AGENT_ID: str = "_system"
# R79 D: 注册后大厅广播开关（默认关闭）
REGISTRATION_BROADCAST_ENABLED: bool = (
    os.environ.get("REGISTRATION_BROADCAST_ENABLED", "0") == "1"
)

# ── R87: _inbox:server 中继通道 ──────────────────────────
SERVER_INBOX_CHANNEL = "_inbox:server"


# ── R42: Pipeline state ──────────────────────────────────────────
_PIPELINE_STATE: dict[str, dict] = {}  # round_name -> {active, current_step, ws_id, ...}

# ── R62: Pipeline config (read-only, separate from runtime state) ──
_PIPELINE_CONFIG: dict[str, dict] = {}  # round_name -> read-only config from WORK_PLAN

# ── R77: PipelineContextManager — 统一管线上下文管理 ──────────────
_pipeline_manager: PipelineContextManager | None = None

# R78: DEPRECATED — 迁移到 PipelineContextManager._global_role_map
_ROLE_AGENT_MAP: dict[str, list[str]] = {}  # role -> [agent_id, ...]

# R78 B: DEPRECATED — 迁移到 PipelineContext.ack_states
_step_ack_states: dict[str, dict] = {}  # "{round}/{step}" -> state info

# ── R65: Git pipeline sync state ───────────────────────────────
_GIT_SYNC_TASK: asyncio.Task | None = None

# ── R122 A: Timeout scan state ────────────────────────────────
_TIMEOUT_SCAN_TASK: asyncio.Task | None = None
_TIMEOUT_SCAN_STARTED: bool = False

# ── R43: Watchdog state ─────────────────────────────────────
_watchdog_started: bool = False
_watchdog_task: asyncio.Task | None = None
_watchdog_alerts: dict[str, float] = {}  # "{round}/{step}" → last_alert_ts

# ── R72 C: R72 认证 agent 的用户名映射（auth.get_users 不包含 R72 agent）──
_r72_users: dict[str, dict] = {}

# ── R12 P0.3: Task ack tracking ────────────────────────────────────────
_task_ack_timers: dict[str, asyncio.Task] = {}

# ── R32: Agent Card subsystem guards ──────────────────────────
_cards_loaded_guard: bool = False
_card_watcher: None = None  # initialized in main._ensure_card_watcher()

# ── R43: Watchdog constants ──────────────────────────────────
WATCHDOG_SCAN_INTERVAL: int = 600
WATCHDOG_REALERT_INTERVAL: int = 1800

# ── R44: Step timeout defaults ──────────────────────────────
_STEP_TIMEOUT_DEFAULTS: dict[str, float] = {}
