"""Agent Card metadata loader — R38 Task State Machine + R63 Registration.

Loaded from config/agent_cards.json at project root.
Provides machine-readable agent capability info for task routing.
R63 Phase 3: Extended schema with registration, trigger_preference, capabilities.
R67: Auto-migration of legacy format, deep-copy getter, CardFileWatcher, mark_stale_offline.
"""

import copy
import json
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger("ws-bridge")

_cards: dict[str, dict] = {}
_cards_loaded: bool = False  # R67: startup guard

# Project root: server/agent_card.py -> server/../config/agent_cards.json
_CARDS_PATH = Path(__file__).parent.parent / "config" / "agent_cards.json"


def load_cards() -> None:
    """Load Agent Card definitions from config file.

    Idempotent — safe to call multiple times (e.g. on restart / config reload).
    R67: Auto-migrates legacy format on first load and persists migration.
    """
    global _cards, _cards_loaded
    if _CARDS_PATH.exists():
        try:
            raw_data = json.loads(_CARDS_PATH.read_text(encoding="utf-8"))
            migrated = migrate_legacy_format(raw_data)
            if migrated != raw_data:  # Migration happened -> persist
                _cards = migrated
                save_cards()
                logger.info("Migrated %d agent cards to new format", len(migrated))
            else:
                _cards = migrated
            logger.info("Loaded %d agent cards from %s", len(_cards), _CARDS_PATH)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load agent cards from %s: %s", _CARDS_PATH, e)
            _cards = {}
    else:
        logger.warning("Agent Card config not found at %s", _CARDS_PATH)
        _cards = {}
    _cards_loaded = True


def get_agent_card(agent_id: str) -> dict | None:
    """Get Agent Card by ID. Returns None if not found."""
    return _cards.get(agent_id)


def get_all_cards() -> dict[str, dict]:
    """Return all loaded Agent Cards as a deep copy.

    Returns a copy to prevent external mutation of internal cache.
    """
    return copy.deepcopy(_cards)


def get_cards_path() -> str:
    """Expose the cards file path (for CardFileWatcher)."""
    return str(_CARDS_PATH)


def reload_cards() -> None:
    """Force reload cards from disk (for config hot-reload)."""
    load_cards()


def is_loaded() -> bool:
    """Check if cards have been loaded at least once."""
    return _cards_loaded


def migrate_legacy_format(cards: dict) -> dict:
    """Convert legacy-format Agent Cards to current schema.

    Legacy format detection: card has "role" field (str) instead of
    "pipeline_roles" (list).  Idempotent: cards already in current format
    are returned unchanged.

    Args:
        cards: Raw dict loaded from JSON file.

    Returns:
        Migrated dict in current schema.
    """
    migrated = {}
    for agent_id, card in cards.items():
        if isinstance(card.get("pipeline_roles"), list):
            # Already migrated -- pass through
            migrated[agent_id] = card
            continue

        new_card: dict = {
            "display_name": card.get("display_name", agent_id[:12]),
            "pipeline_roles": [],
            "skills": [],
            "status": card.get("state", card.get("status", "unknown")),
            "trigger_preference": {
                "mode": "mention",
                "mention_keyword": card.get("display_name", agent_id[:12]),
            },
        }

        # Migrate role (str) -> pipeline_roles (list)
        if isinstance(card.get("role"), str):
            new_card["pipeline_roles"] = [card["role"]]
        elif isinstance(card.get("roles"), list):
            new_card["pipeline_roles"] = card["roles"]

        # Migrate skills: [{"id": "x", ...}] -> ["x"]
        raw_skills = card.get("skills", [])
        if isinstance(raw_skills, list):
            for s in raw_skills:
                if isinstance(s, dict):
                    sid = s.get("id", "")
                    if sid:
                        new_card["skills"].append(sid)
                elif isinstance(s, str):
                    new_card["skills"].append(s)

        # Migrate triggers -> trigger_preference.mention_keyword
        old_triggers = card.get("triggers", [])
        if old_triggers and isinstance(old_triggers, list) and len(old_triggers) > 0:
            trigger = old_triggers[0]
            if trigger.startswith("!"):
                trigger = trigger[1:]
            new_card["trigger_preference"]["mention_keyword"] = trigger

        # Preserve optional fields if present
        if "capabilities" in card:
            new_card["capabilities"] = card["capabilities"]
        if "registered_at" in card:
            new_card["registered_at"] = card["registered_at"]
        if "last_online" in card:
            new_card["last_online"] = card["last_online"]

        migrated[agent_id] = new_card

    return migrated


def update_card(agent_id: str, card_data: dict) -> None:
    """Update a single card in cache and persist. Sanctioned mutation path."""
    global _cards
    _cards[agent_id] = card_data
    save_cards()


def remove_card(agent_id: str) -> bool:
    """Remove a card by agent_id. Returns True if existed, False otherwise."""
    global _cards
    if agent_id in _cards:
        del _cards[agent_id]
        save_cards()
        return True
    return False


# ---- R63 Phase 3: Registration ----------------------------------------


def save_cards() -> None:
    """Persist current cards to disk."""
    try:
        _CARDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CARDS_PATH.write_text(
            json.dumps(_cards, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved %d agent cards to %s", len(_cards), _CARDS_PATH)
    except OSError as e:
        logger.warning("Failed to save agent cards to %s: %s", _CARDS_PATH, e)


def register_agent(agent_id: str, name: str, role: str,
                   force: bool = False) -> dict:
    """Register or update an agent card.

    If force=False and card already exists, only updates last_online/status.
    If force=True, overwrites all fields.

    Args:
        agent_id: Agent identifier.
        name: Agent display name.
        role: Pipeline role (arch/dev/review/qa/admin).
        force: Whether to overwrite existing card.

    Returns:
        The agent card dict (existing or newly created).
    """
    now = time.time()

    if agent_id in _cards and not force:
        # Update existing card
        _cards[agent_id]["last_online"] = now
        _cards[agent_id]["status"] = "online"
        return _cards[agent_id]

    _cards[agent_id] = {
        "name": name,
        "display_name": name,
        "pipeline_roles": [role] if role and role != "member" else [],
        "skills": [],
        "status": "online",
        "registered_at": now,
        "last_online": now,
        "trigger_preference": {
            "mode": "mention",
            "mention_keyword": name,
            "ack_timeout_sec": 60,
        },
        "capabilities": {
            "platforms": ["ws-bridge"],
            "can_code": role == "dev",
            "can_review": role in ("review", "qa"),
            "can_deploy": role == "admin",
        },
    }
    save_cards()
    logger.info("Agent card registered: %s (%s, role=%s)", agent_id, name, role)
    return _cards[agent_id]


def auto_register_missing(online_agents: list[str],
                          name_map: dict[str, str],
                          role_map: dict[str, str]) -> int:
    """Auto-register agents that don't have cards yet.

    Scans online agent IDs and creates cards for those missing.

    Args:
        online_agents: List of online agent IDs.
        name_map: {agent_id: display_name}.
        role_map: {agent_id: pipeline_role}.

    Returns:
        Number of new registrations.
    """
    count = 0
    for aid in online_agents:
        if aid not in _cards:
            name = name_map.get(aid, aid[:12])
            role = role_map.get(aid, "member")
            register_agent(aid, name, role)
            count += 1
    if count:
        save_cards()
    return count


# ---- R67 C2: Stale offline detection ----------------------------------


def mark_stale_offline(timeout: float = 300.0) -> int:
    """Mark agents with no heartbeat within `timeout` seconds as offline.

    Operates directly on _cards (not a copy) — this is intentional.
    Returns number of agents marked offline.
    """
    now = time.time()
    count = 0
    for aid, card in _cards.items():
        last = card.get("last_online", 0)
        if last > 0 and (now - last) > timeout and card.get("status") == "online":
            card["status"] = "offline"
            count += 1
    if count:
        save_cards()
    return count


# ---- R67 B2: Card file watcher ----------------------------------------


class CardFileWatcher:
    """Poll-based file change detector for agent_cards.json.

    Uses pure Python stdlib — no inotify dependency.
    Poll interval: 5 seconds.
    Runs in a daemon thread (auto-cleanup on process exit).
    """

    def __init__(self, file_path: str, on_change=None):
        self._path = file_path
        self._on_change = on_change
        self._mtime = 0.0
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        if not os.path.exists(self._path):
            logger.warning("CardFileWatcher: file %s not found, not starting", self._path)
            return
        self._mtime = os.path.getmtime(self._path)
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True, name="card-watcher")
        self._thread.start()
        logger.info("CardFileWatcher started for %s", self._path)

    def stop(self):
        self._running = False
        logger.info("CardFileWatcher stopped for %s", self._path)

    def is_running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())

    def _poll(self):
        while self._running:
            time.sleep(5)
            try:
                if os.path.exists(self._path):
                    mtime = os.path.getmtime(self._path)
                    if mtime != self._mtime:
                        self._mtime = mtime
                        logger.info("CardFileWatcher: file changed, reloading...")
                        # Reload cards into agent_card module first
                        load_cards()
                        if self._on_change:
                            self._on_change()
            except OSError:
                pass


# ── R72: Bot-initiated Agent Card Registration ────────────────────


def register_from_agent(agent_id: str, msg: dict) -> dict:
    """R72: bot 自主注册/更新自己的 Agent Card。

    由 handle_agent_card_register() 调用，register 认证后 bot 可自主声明能力。
    返回确认消息 dict。

    Args:
        agent_id: 已认证的 agent ID。
        msg: 客户端发送的 agent_card_register 消息。
            支持字段:
            - display_name: 展示名称
            - description: 描述
            - pipeline_roles: 管线角色列表 (list[str])
            - skills: 技能列表 (list[str])
            - trigger_keyword: @触发关键词
            - capabilities: 能力声明 dict
    """
    global _cards
    now = time.time()

    display_name = msg.get("display_name", "").strip() or agent_id[:12]
    description = msg.get("description", "").strip()
    pipeline_roles = msg.get("pipeline_roles", [])
    skills = msg.get("skills", [])
    trigger_keyword = msg.get("trigger_keyword", "").strip() or display_name
    capabilities = msg.get("capabilities", {})

    card = {
        "display_name": display_name,
        "description": description,
        "pipeline_roles": pipeline_roles if isinstance(pipeline_roles, list) else [],
        "skills": skills if isinstance(skills, list) else [],
        "status": "online",
        "registered_at": _cards.get(agent_id, {}).get("registered_at", now),
        "last_online": now,
        "trigger_preference": {
            "mode": "mention",
            "mention_keyword": trigger_keyword,
            "ack_timeout_sec": 60,
        },
        "capabilities": capabilities or {
            "platforms": ["ws-bridge"],
        },
    }

    _cards[agent_id] = card
    save_cards()

    # ── R99: Agent Card 提交成功 → L2→L3 自动晋升 ──
    try:
        from . import auth as _auth_mod
        current_level = _auth_mod.get_level(agent_id)
        if current_level == 2:
            _auth_mod.set_level(agent_id, 3)
            logger.info(
                "[R99] 自动晋升: %s L2→L3 (Agent Card 提交)",
                agent_id[:20],
            )
    except Exception:
        logger.warning("[R99] 自动晋升失败 (非致命): %s", agent_id[:20])
    # ──────────────────────────────────────────────

    # Update _ROLE_AGENT_MAP from handler for role-based routing
    if pipeline_roles:
        try:
            # R78 A3: 先走 PipelineContextManager（新路径）
            from . import handler as _handler_mod
            mgr = _handler_mod._pipeline_manager
            if mgr is not None:
                current_map = mgr.get_global_role_map()
                for r in pipeline_roles:
                    if agent_id not in current_map.setdefault(r, []):
                        current_map[r].append(agent_id)
                mgr.set_global_role_map(current_map)
            # 双写旧变量（过渡期后删除）
            for r in pipeline_roles:
                if r not in _handler_mod._ROLE_AGENT_MAP:
                    _handler_mod._ROLE_AGENT_MAP[r] = []
                if agent_id not in _handler_mod._ROLE_AGENT_MAP[r]:
                    _handler_mod._ROLE_AGENT_MAP[r].append(agent_id)
        except Exception:
            pass

    logger.info(
        "Agent card registered by bot: %s (%s, roles=%s)",
        agent_id[:20], display_name, pipeline_roles,
    )

    return {
        "type": "agent_card_register_ok",
        "agent_id": agent_id,
        "display_name": display_name,
        "pipeline_roles": pipeline_roles,
        "status": "online",
    }
