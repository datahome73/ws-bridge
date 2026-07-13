"""R100: agent_card domain commands — extracted from handler.py."""

from .. import state, command_utils
from server.common import auth
from .. import agent_card as ac_mod
from server.common import config
from ..command_utils import _refresh_role_agent_map
_card_watcher = None  # R100: module-level variable for _cmd_agent_card_watch

async def _cmd_agent_card_list(sender_id: str, params: dict) -> str:
    """Display all current agent cards.
    Also serves as subcommand dispatcher for !agent_card <sub> ... syntax.
    """
    # R49 A: Subcommand dispatch — allow !agent_card get/set/unset/reload/watch
    positional = params.get("_positional", [])
    if positional and positional[0] in ("get", "set", "unset", "reload", "watch"):
        sub_cmd = positional[0]
        # ── R73 B: Write subcommands require workspace_admin ──
        if sub_cmd in ("set", "unset") and not auth.is_global_admin(sender_id):
            if not command_utils._is_any_workspace_admin(sender_id):
                return "❌ 权限不足：仅工作区管理员可修改 Agent Card"
        sub_params = dict(params)
        sub_params["_positional"] = positional[1:]
        handler_map = {
            "get": _cmd_agent_card_get,
            "set": _cmd_agent_card_set,
            "unset": _cmd_agent_card_unset,
            "reload": _cmd_agent_card_reload,
            "watch": _cmd_agent_card_watch,
        }
        return await handler_map[sub_cmd](sender_id, sub_params)
    # Otherwise list all cards
    cards = ac_mod.get_all_cards()
    if not cards:
        return "No agent cards found."
    lines = ["Agent Cards ({0}):".format(len(cards))]
    for aid, card in sorted(cards.items()):
        name = card.get("display_name", card.get("name", aid[:12]))
        roles = ", ".join(card.get("pipeline_roles", []))
        skills = ", ".join(card.get("skills", []))
        status = card.get("status", "unknown")
        line = "  {0} [{1}] status={2}".format(name, roles, status)
        if skills:
            line += " skills=[{0}]".format(skills)
        lines.append(line)
    return "\n".join(lines)



async def _cmd_agent_card_get(sender_id: str, params: dict) -> str:
    """Show a single agent card.
    Usage: !agent_card get <agent_id>
    """
    positional = params.get("_positional", [])
    if not positional:
        return "Usage: !agent_card get <agent_id>"
    agent_id = positional[0]
    cards = ac_mod.get_all_cards()
    card = cards.get(agent_id)
    if not card:
        return "No card for agent " + agent_id[:24]
    name = card.get("display_name", card.get("name", agent_id[:12]))
    roles = ", ".join(card.get("pipeline_roles", []))
    skills = ", ".join(card.get("skills", []))
    status = card.get("status", "unknown")
    updated = card.get("updated_at", "")
    return "\n".join([
        "Card for " + agent_id[:24],
        "  Name: " + name,
        "  Roles: [" + roles + "]",
        "  Skills: [" + skills + "]",
        "  Status: " + status,
        "  Updated: " + str(updated),
    ])



async def _cmd_agent_card_set(sender_id: str, params: dict) -> str:
    """Set or update an agent card.
    Usage: !agent_card set <agent_id> --role <r1,r2> [--name <display>] [--skills <s1,s2>]
    """
    positional = params.get("_positional", [])
    if not positional:
        return "Usage: !agent_card set <agent_id> --role <r1,r2> [--name <n>] [--skills <s1,s2>]"
    agent_id = positional[0]
    role_str = params.get("role", "")
    if not role_str:
        return "--role is required"
    name = params.get("name", "")
    skills_str = params.get("skills", "")

    cards = ac_mod.get_all_cards()
    card = cards.get(agent_id, {})
    card["pipeline_roles"] = [r.strip() for r in role_str.split(",") if r.strip()]
    if name:
        card["display_name"] = name
    if skills_str:
        card["skills"] = [s.strip() for s in skills_str.split(",") if s.strip()]
    card["status"] = card.get("status", "online")
    card["updated_at"] = time.time()

    ac_mod.update_card(agent_id, card)
    _refresh_role_agent_map()
    roles_display = ", ".join(card["pipeline_roles"])
    name_display = card.get("display_name", agent_id[:12])
    return "Card set: {0} -> {1} roles=[{2}]".format(agent_id[:24], name_display, roles_display)



async def _cmd_agent_card_unset(sender_id: str, params: dict) -> str:
    """Delete an agent card.
    Usage: !agent_card unset <agent_id>
    """
    positional = params.get("_positional", [])
    if not positional:
        return "Usage: !agent_card unset <agent_id>"
    agent_id = positional[0]
    if ac_mod.remove_card(agent_id):
        _refresh_role_agent_map()
        return "Deleted card for " + agent_id[:24]
    return "No card for agent " + agent_id[:24]



async def _cmd_agent_card_reload(sender_id: str, params: dict) -> str:
    """Reload agent cards from disk (no restart needed). R67: also refresh role map."""
    ac_mod.reload_cards()
    _refresh_role_agent_map()
    cards = ac_mod.get_all_cards()
    return "Reloaded agent cards: {0} records, role map refreshed".format(len(cards))



async def _cmd_agent_card_watch(sender_id: str, params: dict) -> str:
    """启动/停止文件变动监听。
    用法：!agent_card watch [start|stop|status]
    """
    global _card_watcher
    positional = params.get("_positional", ["status"])
    if not positional:
        return "用法：!agent_card watch [start|stop|status]"
    sub = positional[0]

    if sub == "start":
        if _card_watcher and _card_watcher.is_running():
            return "✅ 文件监听已在运行"
        _card_watcher = ac_mod.CardFileWatcher(
            ac_mod.get_cards_path(),
            on_change=_refresh_role_agent_map,
        )
        _card_watcher.start()
        return "✅ 文件监听已启动"
    elif sub == "stop":
        if _card_watcher and _card_watcher.is_running():
            _card_watcher.stop()
            return "✅ 文件监听已停止"
        return "⚠️ 无运行中的文件监听"
    else:
        running = _card_watcher is not None and _card_watcher.is_running()
        return "📋 文件监听状态：{}".format("🟢 运行中" if running else "🔴 已停止")


# ── R63 Phase 3: Agent role map + card registration commands ─────



async def _cmd_agent_role_map(sender_id: str, params: dict) -> str:
    """展示当前角色↔Agent 映射表。
    用法：!agent_role_map [--refresh]
    """
    if params.get("refresh"):
        _refresh_role_agent_map()
        cards = ac_mod.get_all_cards()
        # Also rebuild from auth for roles not in cards
        users = auth.get_users()
        for aid, u in users.items():
            role = u.get("role", "member")
            if role and role != "member":
                if role not in state._ROLE_AGENT_MAP:
                    state._ROLE_AGENT_MAP[role] = []
                if aid not in state._ROLE_AGENT_MAP[role]:
                    state._ROLE_AGENT_MAP[role].append(aid)

    lines = [f"📋 角色↔Agent 映射表 ({len(state._ROLE_AGENT_MAP)} 个角色):"]
    for role, agents in sorted(state._ROLE_AGENT_MAP.items()):
        names = []
        for aid in agents:
            display = _get_agent_display(aid)
            online = "🟢" if aid in _connections and _connections[aid] else "🔴"
            names.append(f"{online}{display}")
        lines.append(f"  {role} → {' | '.join(names) if names else '(无)'}")

    # Show unregistered roles
    all_roles = {v.get("role") for v in auth.get_users().values()
                 if v.get("role") and v.get("role") != "member"}
    registered_roles = set(state._ROLE_AGENT_MAP.keys())
    unregistered = all_roles - registered_roles
    if unregistered:
        lines.append(f"  ⚠️ 未注册角色: {', '.join(sorted(unregistered))}")

    return "\n".join(lines) if len(lines) > 1 else "📋 当前无角色映射"



async def _cmd_agent_card_register(sender_id: str, params: dict) -> str:
    """强制注册/更新 Agent Card。
    用法：!agent_card register <agent_id> [--name <name>] [--role <role>]
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!agent_card register <agent_id> [--name <name>] [--role <role>]"
    target_id = positional[0]
    name = params.get("name", "")
    role = params.get("role", "")

    users = auth.get_users()
    u = users.get(target_id, {})
    if not name:
        name = u.get("name", target_id[:12])
    if not role:
        role = u.get("role", "member")

    from . import agent_card as ac_mod
    card = ac_mod.register_agent(target_id, name, role, force=True)
    _refresh_role_agent_map()
    return (
        f"✅ Agent Card 已注册：{target_id}\n"
        f"  名称: {name}\n"
        f"  角色: {role}\n"
        f"  pipeline_roles: {card.get('pipeline_roles', [])}"
    )



async def _cmd_agent_card_auto_register(sender_id: str, params: dict) -> str:
    """扫描所有在线 agent，自动补全缺失的 card。
    用法：!agent_card auto-register
    """
    online_agents = list(_connections.keys())
    users = auth.get_users()
    name_map = {aid: users.get(aid, {}).get("name", aid[:12]) for aid in online_agents}
    role_map = {aid: users.get(aid, {}).get("role", "member") for aid in online_agents}

    from . import agent_card as ac_mod
    count = ac_mod.auto_register_missing(online_agents, name_map, role_map)
    _refresh_role_agent_map()

    if count:
        return f"✅ 自动注册了 {count} 个 Agent Card\n  !agent_role_map 查看最新映射表"
    return "✅ 所有在线 Agent 已有 Card，无需注册"


# ── R63 Phase 3: End ──


# ── R35: Admin command registry ──────────────────────────────────


