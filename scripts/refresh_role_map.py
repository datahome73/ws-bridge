"""Refresh role-agent map from within the running server process."""
import sys
sys.path.insert(0, "/app")

from server.ws_server import state as _state
from server.ws_server.command_utils import _refresh_role_agent_map
from server.ws_server import agent_card as ac_mod

print(f"Cards: {len(ac_mod.get_all_cards())} loaded")
for aid, card in ac_mod.get_all_cards().items():
    print(f"  {aid}: {card.get('display_name','?')} roles={card.get('pipeline_roles',[])}")

print(f"\nBEFORE _ROLE_AGENT_MAP: {dict(_state._ROLE_AGENT_MAP)}")
_refresh_role_agent_map()
print(f"AFTER  _ROLE_AGENT_MAP: {dict(_state._ROLE_AGENT_MAP)}")
print(f"Total roles: {len(_state._ROLE_AGENT_MAP)}, entries: {sum(len(v) for v in _state._ROLE_AGENT_MAP.values())}")
