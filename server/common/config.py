"""双进程共享配置 — 仅 env 读取，无逻辑。"""
import os
from pathlib import Path

HOST = os.environ.get("WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_PORT") or os.environ.get("PORT", "8765"))
HTTP_PORT = int(os.environ.get("WS_HTTP_PORT") or os.environ.get("PORT", "8765"))
APP_ID = os.environ.get("WS_APP_ID", "hermes-ws")
DATA_DIR = Path(os.environ.get("WS_DATA_DIR", "./data"))
CHAT_LOG_DIR = DATA_DIR / "chat_logs"

ADMIN_AGENTS: set[str] = set(
    filter(None, os.environ.get("WS_ADMIN_AGENTS", "").split(","))
)
HIDDEN_AGENTS: set[str] = set(
    filter(None, os.environ.get("WS_HIDDEN_AGENTS", "bot-hermes").split(","))
)

WS_ENV = os.environ.get("WS_ENV", "dev")
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
PIPELINE_PM_NAME: str = os.environ.get("WS_PM_NAME", "PM")

# ── R42: Pipeline step map ────────────────────────────────────────
PIPELINE_STEP_MAP: dict[str, dict] = {
    "step1": {"role": "operations",   "name": "管线启动",       "timeout_hours": 2.0,  "escalation": "notify_pm"},
    "step2": {"role": "arch",    "name": "技术方案",       "timeout_hours": 6.0,  "escalation": "notify_pm",
              "primary": "arch", "backup": "dev"},
    "step3": {"role": "dev",     "name": "编码",          "timeout_hours": 12.0, "escalation": "notify_pm",
              "primary": "dev",  "backup": "arch"},
    "step4": {"role": "review",  "name": "代码审查",       "timeout_hours": 4.0,  "escalation": "notify_pm",
              "primary": "review", "backup": "qa"},
    "step5": {"role": "qa",      "name": "测试验证",       "timeout_hours": 6.0,  "escalation": "notify_pm",
              "primary": "qa",   "backup": "review"},
    "step6": {"role": "operations",   "name": "合并部署归档",    "timeout_hours": 2.0,  "escalation": "notify_pm",
              "primary": "operations", "backup": "arch"},
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
PIPELINE_ARCH_FROM_NAME: str = os.environ.get("WS_ARCH_FROM_NAME", "小谷")

# ── R59 C: Pipeline role overrides ─────────────────────────────
PIPELINE_ROLE_OVERRIDES: dict[str, str] = {}
_raw_c = os.environ.get("PIPELINE_ROLE_OVERRIDE", "")
if _raw_c.strip():
    try:
        import json as _jsonc
        PIPELINE_ROLE_OVERRIDES.update(_jsonc.loads(_raw_c))
    except Exception:
        pass

# ── R65: Git pipeline sync ──────────────────────────────────
ENABLE_GIT_SYNC: bool = os.environ.get("R65_ENABLE_GIT_SYNC", "1") == "1"
GIT_SYNC_INTERVAL: int = int(os.environ.get("R65_GIT_SYNC_INTERVAL", "120"))
GIT_SYNC_BRANCH: str = os.environ.get("R65_GIT_SYNC_BRANCH", "dev")
GIT_SYNC_FALLBACK: bool = os.environ.get("R65_GIT_SYNC_FALLBACK", "1") == "1"
REPO_PATH: str = os.environ.get("R65_REPO_PATH", "/opt/data/ws-bridge")

# ── R80: Validation hook system ────────────────────────────────
ENABLE_VALIDATION_HOOK: bool = (
    os.environ.get("R80_ENABLE_VALIDATION", "0") == "1"
)
VALIDATION_DEFAULT_SCRIPT: str = os.environ.get(
    "R80_VALIDATION_SCRIPT",
    "python3 scripts/verify_default.py {output_ref}",
)
VALIDATION_DEFAULT_TIMEOUT: int = int(
    os.environ.get("R80_VALIDATION_TIMEOUT", "30")
)

PIPELINE_PM_AGENT_ID: str = os.environ.get("WS_PM_AGENT_ID", "")

# ── R87: _inbox:server 中继通道 ────────────────────────────
SERVER_INBOX_CHANNEL: str = "_inbox:server"

# ── R107/R108: 自动派活开关 — R108 永久开启 ─────────────────
AUTO_DISPATCH_ENABLED: bool = True

# ── R122: 管线超时告警 ────────────────────────────────────
PIPELINE_TIMEOUT_ALERT_MINUTES: int = int(
    os.environ.get("R122_TIMEOUT_ALERT_MINUTES", "30")
)
PIPELINE_TIMEOUT_SCAN_INTERVAL: int = int(
    os.environ.get("R122_TIMEOUT_SCAN_INTERVAL", "300")
)
# ── R130: 状态栏 Agent 白名单 ──────────────────────────────
AGENT_WHITELIST: set[str] = {"小爱", "小谷", "小开", "爱泰", "小周", "泰虾", "经理"}
# ── R124: Step 产出基本验证（默认关闭，0=off 1=on）───
PIPELINE_OUTPUT_VERIFICATION: bool = os.environ.get("PIPELINE_OUTPUT_VERIFICATION", "0") == "1"
DISPATCH_SENDER_ID: str = os.environ.get(
    "DISPATCH_SENDER_ID",
    os.environ.get("WS_PM_AGENT_ID", ""),
)
