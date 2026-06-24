"""Agent Card metadata loader — R38 Task State Machine.

Loaded from config/agent_cards.json at project root.
Provides machine-readable agent capability info for task routing.
"""

import json
import logging
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
