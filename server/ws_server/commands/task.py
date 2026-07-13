"""R100: task domain commands — extracted from handler.py."""

from .. import state, command_utils
from server.common import auth
from .. import task_store as ts
from .. import workspace as ws_mod
from server.common import config
import asyncio
import shared.protocol as p

async def _cmd_task_create(sender_id: str, params: dict) -> str:
    """Create a new task in SUBMITTED state.
    Usage: !task_create --context <R{N}> --name <step> [--role <role>]"""
    context_id = params.get("context", "")
    name = params.get("name", "")
    if not context_id or not name:
        return "❌ 用法：!task_create --context <R{N}> --name <step> [--role <role>]"
    assigned_role = params.get("role", "")
    task = ts.create_task(
        context_id=context_id, name=name,
        assigned_role=assigned_role,
        created_by=sender_id,
        data_dir=config.DATA_DIR,
    )
    # R41 C: Broadcast task_notify on creation
    asyncio.create_task(_broadcast_task_notify(task, f"{task['state']} → {task['state']}"))
    return (f"✅ Task 已创建：{task['name']} ({task['state']})\n"
            f"  ID: {task['id']}\n"
            f"  Context: {task['context_id']}\n"
            f"  Role: {task.get('assigned_role', '未指定')}")



async def _cmd_task_update(sender_id: str, params: dict) -> str:
    """Update a task's state.
    Usage: !task_update <task_id> --state <new_state> [--output <path>]"""
    positional = params.get("_positional", [])
    task_id = params.get("_task_id", positional[0] if positional else "")
    new_state = params.get("state", "")
    if not task_id or not new_state:
        return "❌ 用法：!task_update <task_id> --state <new_state> [--output <path>]"
    task = ts.get_task(task_id, config.DATA_DIR)
    if not task:
        return f"❌ Task {task_id[:12]} 不存在"
    # Permission: assigned_role match or global admin bypass
    if task.get("assigned_role"):
        users = auth.get_users()
        sender_info = users.get(sender_id, {})
        if sender_info.get("role") != "admin":
            if task["assigned_role"] not in (sender_id, sender_info.get("name", "")):
                return f"❌ 权限不足：Task 分配给 {task['assigned_role']}，你不可更新"
    try:
        current = p.TaskState(task["state"])
        target = p.TaskState(new_state)
    except ValueError:
        valid = [s.value for s in p.TaskState]
        return f"❌ 无效状态：{new_state}。有效值：{', '.join(valid)}"
    allowed = p.TASK_VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        return f"❌ 不允许的转换：{current.value} → {target.value}"
    # Reject ceiling check
    if target == p.TaskState.INPUT_REQUIRED:
        ts.increment_reject_count(task_id, config.DATA_DIR)
        task_d = ts.get_task(task_id, config.DATA_DIR)
        if task_d["reject_count"] >= p.TASK_REJECT_CEILING:
            ts.update_state(task_id, p.TaskState.FAILED.value, config.DATA_DIR)
            task_d = ts.get_task(task_id, config.DATA_DIR)
            return (f"❌ 审查已达上限 ({p.TASK_REJECT_CEILING}次)，已锁定 FAILED\n"
                    f"  {task_d['name']}: {task_d['state']} (rejects: {task_d['reject_count']})")
    ts.update_state(task_id, new_state, config.DATA_DIR)
    output_ref = params.get("output", "")
    if output_ref:
        ts.add_output_ref(task_id, output_ref, config.DATA_DIR)
    task = ts.get_task(task_id, config.DATA_DIR)
    # R41 C: Broadcast task_notify on update
    asyncio.create_task(_broadcast_task_notify(task,
        f"{task['state']} → {new_state}"))
    refs = task.get("output_refs", [])
    refs_str = f", 产出: {', '.join(refs)}" if refs else ""
    return f"✅ Task 已更新：{task['name']} → {task['state']}{refs_str}"



async def _cmd_task_query(sender_id: str, params: dict) -> str:
    """Query tasks by context or single task.
    Usage: !task_query --context <R{N}> | !task_query <task_id>"""
    positional = params.get("_positional", [])
    task_id = params.get("_task_id", positional[0] if positional else "")
    context_id = params.get("context", "")
    if task_id:
        task = ts.get_task(task_id, config.DATA_DIR)
        if not task:
            return f"❌ Task {task_id[:12]} 不存在"
        refs = task.get("output_refs", [])
        refs_str = f", 产出: {'; '.join(refs)}" if refs else ""
        return (f"📋 Task：{task['name']}\n"
                f"  State: {task['state']}\n"
                f"  Context: {task['context_id']}\n"
                f"  Assigned: {task.get('assigned_role', '未指定')}\n"
                f"  Rejects: {task.get('reject_count', 0)}{refs_str}\n"
                f"  Updated: {task['updated_at']}")
    elif context_id:
        tasks = ts.list_tasks_by_context(context_id, config.DATA_DIR)
        if not tasks:
            return f"📋 Context {context_id} 暂无 Task"
        lines = [f"📋 {context_id} 任务列表 ({len(tasks)}):"]
        for t in tasks:
            icon = p.TASK_STATE_ICONS.get(t["state"], "❓")
            lines.append(f"  {icon} {t['name']:20s} [{t['state']}]  {t['id'][:8]}")
        return "\n".join(lines)
    else:
        return "❌ 用法：!task_query <task_id> | !task_query --context <R{N}>"



async def _cmd_task_list(sender_id: str, params: dict) -> str:
    """List recent tasks across all contexts.
    Usage: !task_list [--limit <n>]"""
    limit = int(params.get("limit", "10"))
    tasks = ts.list_all_tasks(config.DATA_DIR, limit)
    if not tasks:
        return "📋 暂无 Task"
    lines = [f"📋 最近 {len(tasks)} 个 Task:"]
    for t in tasks:
        icon = p.TASK_STATE_ICONS.get(t["state"], "❓")
        lines.append(f"  {icon} [{t['context_id']}] {t['name']:20s} [{t['state']}]  {t['id'][:8]}")
    return "\n".join(lines)



async def _cmd_rollcall_role(sender_id: str, params: dict) -> str:
    """点名指定角色成员 — 使用 ACK 确认制代替文本「到」。
    Usage: !rollcall_role <role> [--context <msg>]
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法: !rollcall_role <role> [--context <msg>]"
    target_role = positional[0].lower()
    context_msg = params.get("context", "")
    ws_id = params.get("workspace", "")
    if not ws_id:
        return "❌ 请使用 --workspace <ws_id> 指定工作区"
    ws_obj = ws_mod.get_workspace(ws_id)
    if not ws_obj:
        return f"❌ 工作区 {ws_id} 不存在或已归档"
    sender_ch = ws_id
    users = auth.get_users()
    matched = [aid for aid in ws_obj.members
               if users.get(aid, {}).get("role", "member") == target_role]
    if not matched:
        return f"❌ 工作区中未找到角色为「{target_role}」的成员"
    sender_name = users.get(sender_id, {}).get("name", sender_id[:12])
    names = [users.get(aid, {}).get("name", aid[:12]) for aid in matched]
    names_str = ", ".join(names)
    suffix = f"（背景：{context_msg}）" if context_msg else ""
    # ★ R53: Use ACK-driven broadcast instead of text "回复到"
    _persist_broadcast(sender_ch, "系统", f"📋 {sender_name} 点名 {target_role} 成员{suffix}")
    # R82: removed _broadcast_active_channel
    return f"✅ 已点名 {target_role}：{names_str}"



async def _cmd_rollcall_next(sender_id: str, params: dict) -> str:
    """点名下一环节负责人 — 使用 ACK 确认制代替文本「到」。
    Usage: !rollcall_next <role> --context <摘要>
    
    不再发送「请回复到开始」文本消息。
    改为通过 _broadcast_active_channel(ws_id) 启动 ACK 等待。
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法: !rollcall_next <role> --context <摘要>"
    target_role = positional[0].lower()
    context_summary = params.get("context", "")
    if not context_summary:
        return "❌ 请提供 --context <摘要>"
    ws_id = params.get("workspace", "")
    if not ws_id:
        return "❌ 请使用 --workspace <ws_id> 指定工作区"
    ws_obj = ws_mod.get_workspace(ws_id)
    if not ws_obj:
        return f"❌ 工作区 {ws_id} 不存在或已归档"
    sender_ch = ws_id
    users = auth.get_users()
    matched = [aid for aid in ws_obj.members
               if users.get(aid, {}).get("role", "member") == target_role]
    if not matched:
        return f"❌ 工作区中未找到角色为「{target_role}」的成员"
    names = [users.get(aid, {}).get("name", aid[:12]) for aid in matched]
    names_str = ", ".join(names)
    # Persist the rollcall context for audit
    _persist_broadcast(sender_ch, "系统", f"🏗️ 下一环节：{context_summary}\n📋 负责人：{names_str}")
    # R82: removed _broadcast_active_channel
    return f"🏗️ 下一环节：{context_summary}\n📋 负责人：{names_str}"



