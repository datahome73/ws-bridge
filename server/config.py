"""
Hermes WS Bridge - WebSocket broadcast server config.
"""
import os
from pathlib import Path

HOST = os.environ.get("WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_PORT") or os.environ.get("PORT", "8765"))
HTTP_PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8765"))
APP_ID = os.environ.get("WS_APP_ID", "hermes-ws")
DATA_DIR = Path(os.environ.get("WS_DATA_DIR", "./data"))
CHAT_LOG_DIR = DATA_DIR / "chat_logs"
BROADCAST_ADMINS: set[str] = set(
    filter(None, os.environ.get("BROADCAST_ADMINS", "").split(","))
)


ADMIN_AGENTS: set[str] = set(
    filter(None, os.environ.get("WS_ADMIN_AGENTS", "").split(","))
)


# System agents hidden from API status / web UI
# Comma-separated list of agent_ids to exclude from agent list endpoints
HIDDEN_AGENTS: set[str] = set(
    filter(None, os.environ.get("WS_HIDDEN_AGENTS", "bot-hermes").split(","))
)

# ── R40: GitHub OAuth ─────────────────────────────────────────
GITHUB_OAUTH_CLIENT_ID = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "")
GITHUB_OAUTH_CLIENT_SECRET = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "")
GITHUB_OAUTH_REDIRECT_URI = os.environ.get(
    "GITHUB_OAUTH_REDIRECT_URI",
    os.environ.get("WS_PUBLIC_URL", "http://0.0.0.0:8765") + "/auth/github/callback",
)
# Map from GitHub username → bridge display name, JSON dict format
OAUTH_NAME_MAP: dict[str, str] = {}
_raw = os.environ.get("OAUTH_NAME_MAP", "")
if _raw.strip():
    import json as _json
    try:
        OAUTH_NAME_MAP.update(_json.loads(_raw))
    except _json.JSONDecodeError:
        pass

# ── R41 A: Web auth environment distinction ─────────────────────
WS_ENV = os.environ.get("WS_ENV", "dev")  # "dev" | "production"
IS_PRODUCTION = WS_ENV == "production"


# ── R55 C: Git commit verification ─────────────────────────────────
GIT_REMOTE_URL: str = os.environ.get(
    "WS_BRIDGE_GIT_REMOTE",
    "https://github.com/datahome73/ws-bridge.git",
)


# ── R45 A: Pipeline WORK_PLAN remote source ────────────────────────
WORK_PLAN_REPO_URL: str = os.environ.get(
    "WORK_PLAN_REPO_URL",
    "https://raw.githubusercontent.com/datahome73/ws-bridge/dev",
)


# ── R58 A6: Pipeline PM display name ───────────────────────────────
# The name used as from_name when system sends natural @mention notifications.
# Mimics human PM messages so bot gateways treat them as human @mention.
# Environment variable WS_PM_NAME overrides the default "PM".
PIPELINE_PM_NAME: str = os.environ.get("WS_PM_NAME", "PM")


# ── R42: Pipeline step map ────────────────────────────────────────
PIPELINE_STEP_MAP: dict[str, dict] = {
    # step1 is auto-step, no primary/backup needed
    "step1": {"role": "admin",   "name": "管线启动",       "timeout_hours": 2.0,  "escalation": "notify_pm"},
    "step2": {"role": "arch",    "name": "技术方案",       "timeout_hours": 6.0,  "escalation": "notify_pm",
              "primary": "arch", "backup": "dev"},
    "step3": {"role": "dev",     "name": "编码",          "timeout_hours": 12.0, "escalation": "notify_pm",
              "primary": "dev",  "backup": "arch"},
    "step4": {"role": "review",  "name": "代码审查",       "timeout_hours": 4.0,  "escalation": "notify_pm",
              "primary": "review", "backup": "qa"},
    "step5": {"role": "qa",      "name": "测试验证",       "timeout_hours": 6.0,  "escalation": "notify_pm",
              "primary": "qa",   "backup": "review"},
    "step6": {"role": "admin",   "name": "合并部署归档",    "timeout_hours": 2.0,  "escalation": "notify_pm",
              "primary": "admin", "backup": "arch"},
}
_override_raw = os.environ.get("PIPELINE_STEP_MAP_OVERRIDE", "")
if _override_raw.strip():
    import json as _json2
    try:
        override = _json2.loads(_override_raw)
        PIPELINE_STEP_MAP.update(override)
    except _json2.JSONDecodeError:
        pass


# ── R59 B: Arch display name override ──────────────────────────
# R59 方向 A 实验确定 arch 需要 from_name=小谷 才能触发。
# Environment variable WS_ARCH_FROM_NAME overrides the default.
PIPELINE_ARCH_FROM_NAME: str = os.environ.get("WS_ARCH_FROM_NAME", "小谷")


# ── R59 C: Pipeline role overrides ─────────────────────────────
# JSON map: { step_key: executor_role }
# Example: {"step3": "arch"} means Step 3 is executed by arch instead of dev.
# Environment variable PIPELINE_ROLE_OVERRIDE overrides (JSON).
PIPELINE_ROLE_OVERRIDES: dict[str, str] = {}
_raw_c = os.environ.get("PIPELINE_ROLE_OVERRIDE", "")
if _raw_c.strip():
    try:
        import json as _jsonc
        PIPELINE_ROLE_OVERRIDES.update(_jsonc.loads(_raw_c))
    except Exception:
        pass


# ── R65: Git pipeline sync ──────────────────────────────────
# 管线 git 同步自动检测开关
ENABLE_GIT_SYNC: bool = os.environ.get("R65_ENABLE_GIT_SYNC", "1") == "1"
# git 检测间隔（秒）
GIT_SYNC_INTERVAL: int = int(os.environ.get("R65_GIT_SYNC_INTERVAL", "120"))
# 默认工作分支
GIT_SYNC_BRANCH: str = os.environ.get("R65_GIT_SYNC_BRANCH", "dev")
# 兜底开关（任意新 commit 即推进）
GIT_SYNC_FALLBACK: bool = os.environ.get("R65_GIT_SYNC_FALLBACK", "1") == "1"
# Git 仓库本地路径
REPO_PATH: str = os.environ.get("R65_REPO_PATH", "/opt/data/ws-bridge")


# ── R63 Phase 5: Feature toggle switches ──────────────────────────
# Environment variables to enable/disable R63 features independently.
# Default: all enabled ("1").
R63_ENABLE_TIMEOUT: bool = os.environ.get("R63_ENABLE_TIMEOUT", "1") == "1"
R63_ENABLE_AGENT_MAP: bool = os.environ.get("R63_ENABLE_AGENT_MAP", "1") == "1"
R63_ENABLE_ACK: bool = os.environ.get("R63_ENABLE_ACK", "1") == "1"
