"""R100: !command registry — _ADMIN_COMMANDS dictionary."""

from .workspace import (
    _cmd_create_workspace, _cmd_close_workspace, _cmd_list_workspaces,
    _cmd_workspace_join, _cmd_workspace_leave, _cmd_workspace_add,
    _cmd_workspace_remove, _cmd_workspace_list_members, _cmd_workspace_reset,
)
from .pipeline import (
    _cmd_pipeline_start, _cmd_pipeline_stop, _cmd_pipeline_activate,
    _cmd_pipeline_status, _cmd_pipeline_mode, _cmd_pipeline_role_override,
    _cmd_step_complete, _cmd_step_force, _cmd_step_handoff,
    _cmd_step_verify, _cmd_step_reject,
    _handle_pipeline_command,
)
from .agent_card import (
    _cmd_agent_card_list, _cmd_agent_card_get, _cmd_agent_card_set,
    _cmd_agent_card_unset, _cmd_agent_card_reload, _cmd_agent_card_watch,
    _cmd_agent_role_map, _cmd_agent_card_register, _cmd_agent_card_auto_register,
)
from .task import (
    _cmd_task_create, _cmd_task_update, _cmd_task_query,
    _cmd_task_list, _cmd_rollcall_role, _cmd_rollcall_next,
)
from .admin import (
    _cmd_list_agents, _cmd_agent_status, _cmd_approve_ws_admin,
    _cmd_reject_ws_admin, _cmd_list_pending, _cmd_audit_log,
    _cmd_list_workspace_admins, _cmd_revoke_api_key,
)
_ADMIN_COMMANDS: dict[str, dict] = {
    "create_workspace": {
        "handler": _cmd_create_workspace, "min_role": 3, "workspace_scope": True,
        "usage": "!create_workspace <name> --members <ids>",
    },
    "close_workspace": {
        "handler": _cmd_close_workspace, "min_role": 3, "workspace_scope": True,
        "usage": "!close_workspace <ws_id> [--reason <text>]",
    },
    "list_workspaces": {
        "handler": _cmd_list_workspaces, "min_role": 3, "workspace_scope": True,
        "usage": "!list_workspaces",
    },
    "list_agents": {
        "handler": _cmd_list_agents, "min_role": 3, "workspace_scope": True,
        "usage": "!list_agents [--role <role>]",
    },
    "agent_status": {
        "handler": _cmd_agent_status, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_status <agent_id>",
    },
    "approve_ws_admin": {
        "handler": _cmd_approve_ws_admin, "min_role": 4, "workspace_scope": False,
        "usage": "!approve_ws_admin --workspace <ws_id> --agent <agent>",
    },
    "reject_ws_admin": {
        "handler": _cmd_reject_ws_admin, "min_role": 4, "workspace_scope": False,
        "usage": "!reject_ws_admin --workspace <ws_id> --agent <agent> --reason <text>",
    },
    "list_pending": {
        "handler": _cmd_list_pending, "min_role": 4, "workspace_scope": False,
        "usage": "!list_pending",
    },
    "audit_log": {
        "handler": _cmd_audit_log, "min_role": 3, "workspace_scope": True,
        "usage": "!audit_log [--limit <n>]",
    },
    "list_workspace_admins": {
        "handler": _cmd_list_workspace_admins, "min_role": 3, "workspace_scope": True,
        "usage": "!list_workspace_admins [--workspace <ws_id>]",
    },
    # ── R38: Task commands ──
    "task_create": {
        "handler": _cmd_task_create, "min_role": 3, "workspace_scope": True,
        "usage": "!task_create --context <R{N}> --name <step> [--role <role>]",
    },
    "task_update": {
        "handler": _cmd_task_update, "min_role": 3, "workspace_scope": True,
        "usage": "!task_update <task_id> --state <new_state> [--output <path>]",
    },
    "task_query": {
        "handler": _cmd_task_query, "min_role": 3, "workspace_scope": True,
        "usage": "!task_query <task_id> | !task_query --context <R{N}>",
    },
    "task_list": {
        "handler": _cmd_task_list, "min_role": 3, "workspace_scope": True,
        "usage": "!task_list [--limit <n>]",
    },
    # ── R77: Pipeline context management ──
    "pipeline": {
        "handler": _handle_pipeline_command, "min_role": 2, "workspace_scope": False,
        "usage": "!pipeline <create|status|list|advance|block|archive|cancel> [args]",
    },
    "pipeline_stop": {
        "handler": _cmd_pipeline_stop, "min_role": 2, "workspace_scope": False,
        "usage": "!pipeline_stop <R{N}>",
    },
        # ── R49 B: Agent Card commands ──
    "agent_card": {
        "handler": _cmd_agent_card_list, "min_role": 2, "workspace_scope": True,
        "usage": "!agent_card [list|get|set|unset|reload] ...",
    },
    "agent_card_list": {
        "handler": _cmd_agent_card_list, "min_role": 2, "workspace_scope": True,
        "usage": "!agent_card list",
    },
    "agent_card_get": {
        "handler": _cmd_agent_card_get, "min_role": 2, "workspace_scope": True,
        "usage": "!agent_card get <agent_id>",
    },
    "agent_card_set": {
        "handler": _cmd_agent_card_set, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card set <agent_id> --role <r1,r2> [--name <n>]",
    },
    "agent_card_unset": {
        "handler": _cmd_agent_card_unset, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card unset <agent_id>",
    },
    "agent_card_reload": {
        "handler": _cmd_agent_card_reload, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card reload",
    },
    # ── R63 Phase 3: Agent role map + card registration ──
    "agent_role_map": {
        "handler": _cmd_agent_role_map, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_role_map [--refresh]",
    },
    "agent_card_register": {
        "handler": _cmd_agent_card_register, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card register <agent_id> [--name <name>] [--role <role>]",
    },
    "agent_card_auto_register": {
        "handler": _cmd_agent_card_auto_register, "min_role": 3, "workspace_scope": True,
        "usage": "!agent_card auto-register",
    },
    # ── R63 Phase 3: End ──
# ── R41 D: Roll-call commands ──
    "rollcall_role": {
        "handler": _cmd_rollcall_role, "min_role": 3, "workspace_scope": True,
        "usage": "!rollcall_role <role> [--context <msg>]",
    },
    "rollcall_next": {
        "handler": _cmd_rollcall_next, "min_role": 3, "workspace_scope": True,
        "usage": "!rollcall_next <role> --context <摘要>",
    },
    # ── R42: Pipeline commands ──
    "pipeline_start": {
        "handler": _cmd_pipeline_start, "min_role": 3, "workspace_scope": False,
        "usage": "!pipeline_start <R{N}> [--from <step>]",
    },
    "step_complete": {
        "handler": _cmd_step_complete, "min_role": 1, "workspace_scope": True,
        "usage": "!step_complete <step_name> [--output <commit/file>]",
    },
    "pipeline_status": {
        "handler": _cmd_pipeline_status, "min_role": 3, "workspace_scope": False,
        "usage": "!pipeline_status",
    },
    # ── R50: Pipeline activation & step handoff ──
    "pipeline_activate": {
        "handler": _cmd_pipeline_activate, "min_role": 3, "workspace_scope": False,
        "usage": "!pipeline_activate <R{N}> [--ws <workspace_id>]",
    },
    "step_handoff": {
        "handler": _cmd_step_handoff, "min_role": 3, "workspace_scope": True,
        "usage": "!step_handoff <step_name> --output <commit/file>",
    },
    # ── R55 B: Step reject ──
    "step_reject": {
        "handler": _cmd_step_reject, "min_role": 1, "workspace_scope": True,
        "usage": "!step_reject <step_name> --reason <原因>",
    },
    # ── R55 E: Pipeline mode switch ──
    "pipeline_mode": {
        "handler": _cmd_pipeline_mode, "min_role": 3, "workspace_scope": True,
        "usage": "!pipeline_mode <auto|manual>",
    },
    # ── R59 C: Pipeline role override ──
    "pipeline_role_override": {
        "handler": _cmd_pipeline_role_override, "min_role": 3, "workspace_scope": True,
        "usage": "!pipeline_role_override <step> --executor <role>",
    },
    # ── R69 B2: Workspace reset ──
    "workspace_reset": {
        "handler": _cmd_workspace_reset, "min_role": 3, "workspace_scope": True,
        "usage": "!workspace_reset — 关闭当前工作室 + 清理管线状态 + 回大厅",
    },
    # ── R80: Validation hook commands ──
    "step_force": {
        "handler": _cmd_step_force, "min_role": 3,
        "desc": "强制推进 Step（跳过验证）",
        "usage": "!step_force <step_name> --output <sha> [--reason <text>]",
    },
    "step_verify": {
        "handler": _cmd_step_verify, "min_role": 2,
        "desc": "BLOCKED 状态下重新执行验证",
        "usage": "!step_verify <step_name> [--output <sha>]",
    },
}

# ── R81: Workspace member self-management commands ──────────────



