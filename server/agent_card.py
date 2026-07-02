"""Agent Card metadata loader — R38 Task State Machine + R63 Registration.

Loaded from config/agent_cards.json at project root.
Provides machine-readable agent capability info for task routing.
R63 Phase 3: Extended schema with registration, trigger_preference, capabilities.
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("ws-bridge")

_cards: dict[str, dict] = {}

# Project root: server/agent_card.py → server/../config/agent_cards.json
_CARDS_PATH = Path(__file__).parent.parent / "config" / "agent_cards.json"


def load_cards() -> None:
    """Load Agent Card definitions from config file.

    Idempotent — safe to call multiple times (e.g. on restart / config reload).
    """
    global _cards
    if _CARDS_PATH.exists():
        try:
            _cards = json.loads(_CARDS_PATH.read_text(encoding="utf-8"))
            logger.info("Loaded %d agent cards from %s", len(_cards), _CARDS_PATH)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load agent cards from %s: %s", _CARDS_PATH, e)
            _cards = {}
    else:
        logger.warning("Agent Card config not found at %s", _CARDS_PATH)
        _cards = {}


def get_agent_card(agent_id: str) -> dict | None:
    """Get Agent Card by ID. Returns None if not found."""
    return _cards.get(agent_id)


def get_all_cards() -> dict[str, dict]:
    """Return all loaded Agent Cards."""
    return _cards


def reload_cards() -> None:
    """Force reload cards from disk (for config hot-reload)."""
    load_cards()


# ── R63 Phase 3: Registration ──────────────────────────────────────


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
