"""R100: pipeline domain commands — extracted from handler.py."""

import json
import time
import uuid
import os

from ..state import SYSTEM_AGENT_ID
from .. import state, auth, command_utils, config
from .. import task_store as ts
from .. import message_store as ms
from .. import workspace as ws_mod
from .. import timeout_tracker
from .. import pipeline_sync as pps
from .. import agent_card as ac_mod
from ..pipeline_context import PipelineContext, PipelineStatus, PipelineTaskKind, PipelineContextManager

# Lazy import from main to avoid circular dependency
def _get_pipeline_manager() -> PipelineContextManager:
    from ..main import _ensure_pipeline_manager
    return _ensure_pipeline_manager()

async def _handle_pipeline_command(sender_id: str, params: dict) -> str:
    """处理 !pipeline 子命令。

    用法: !pipeline <create|status|list|advance|block|archive|cancel> [args]
    """
    from pathlib import Path
    raw = params.get("_raw", "")
    # Strip the leading "!pipeline "
    rest = raw[len("!pipeline "):] if raw.startswith("!pipeline ") else raw
    parts = rest.strip().split(maxsplit=2)
    subcmd = parts[0] if len(parts) >= 1 else ""
    mgr = _get_pipeline_manager()

    if subcmd == "create":
        # R78 D3: !pipeline create R78 dev [--steps 6] [--ws ws_id] [--pm-inbox inbox_id]
        round_name = parts[1] if len(parts) >= 2 else ""
        task_kind = parts[2] if len(parts) >= 3 else "dev"
        extra_args = parts[3] if len(parts) >= 4 else ""
        total_steps = 6
        ws_id = ""
        pm_inbox = ""
        if "--steps" in extra_args:
            try:
                total_steps = int(extra_args.split("--steps")[1].strip().split()[0])
            except (IndexError, ValueError):
                pass
        if "--ws" in extra_args:
            try:
                ws_id = extra_args.split("--ws")[1].strip().split()[0]
            except (IndexError, ValueError):
                pass
        if "--pm-inbox" in extra_args:
            try:
                pm_inbox = extra_args.split("--pm-inbox")[1].strip().split()[0]
            except (IndexError, ValueError):
                pass
        if not round_name:
            return "❌ 用法: !pipeline create <round> <kind> [--steps N] [--ws id] [--pm-inbox id]"
        try:
            ctx = await mgr.create(
                round_name=round_name,
                task_kind=PipelineTaskKind(task_kind),
                workspace_dir=Path(config.REPO_PATH) if hasattr(config, 'REPO_PATH') else Path("/opt/data/ws-bridge"),
                workspace_id=ws_id,
                pm_inbox_id=pm_inbox,
                total_steps=total_steps,
                created_by=sender_id,
            )
            return f"✅ Pipeline {round_name} created (kind={task_kind}, status={ctx.status.value}, steps={total_steps})"
        except ValueError as e:
            return f"❌ {e}"
        except Exception as e:
            return f"❌ 创建失败: {e}"

    elif subcmd == "status":
        # !pipeline status [R77]
        round_name = parts[1] if len(parts) >= 2 else ""
        if round_name:
            ctx = mgr.get(round_name)
            if not ctx:
                return f"❌ Pipeline {round_name} not found"
            return _format_pipeline_context(ctx)
        active = mgr.get_all_active()
        if not active:
            return "📋 当前无活跃管线"
        out = ["📋 活跃管线:"]
        for ctx in sorted(active, key=lambda c: c.round_name, reverse=True):
            out.append(f"  • {ctx.round_name} [{ctx.task_kind.value}] status={ctx.status.value} step={ctx.current_step}/{ctx.total_steps}")
        return "\n".join(out)

    elif subcmd == "list":
        active = mgr.get_all_active()
        if not active:
            return "📋 当前无活跃管线"
        lines = ["📋 活跃管线:"]
        for ctx in sorted(active, key=lambda c: c.round_name):
            lines.append(f"  • {ctx.round_name} [{ctx.task_kind.value}] status={ctx.status.value} step={ctx.current_step}/{ctx.total_steps}")
        return "\n".join(lines)

    elif subcmd == "advance":
        # !pipeline advance [R77]
        round_name = parts[1] if len(parts) >= 2 else ""
        if not round_name:
            return "❌ 用法: !pipeline advance <round>"
        ok = await mgr.advance_step(round_name)
        if not ok:
            return f"❌ 推进失败: {round_name} 不存在或已结束"
        ctx = mgr.get(round_name)
        return f"✅ {round_name} advanced to step {ctx.current_step}/{ctx.total_steps}"

    elif subcmd == "block":
        # !pipeline block R77 等素材
        round_name = parts[1] if len(parts) >= 2 else ""
        reason = parts[2] if len(parts) >= 3 else "阻塞（无原因）"
        ok = await mgr.transition_to(round_name, PipelineStatus.BLOCKED, blocked_reason=reason)
        if not ok:
            return f"❌ 阻塞失败: {round_name} 不存在或状态转换非法"
        return f"⏸️ {round_name} blocked: {reason}"

    elif subcmd == "archive":
        round_name = parts[1] if len(parts) >= 2 else ""
        if not round_name:
            return "❌ 用法: !pipeline archive <round>"
        ok = await mgr.archive(round_name)
        return f"📦 {round_name} archived {'✅' if ok else '❌ not found'}"

    elif subcmd == "cancel":
        round_name = parts[1] if len(parts) >= 2 else ""
        if not round_name:
            return "❌ 用法: !pipeline cancel <round>"
        ok = await mgr.cancel(round_name)
        return f"🚫 {round_name} cancelled {'✅' if ok else '❌ not found'}"

    elif subcmd == "resume":
        # R78 D1: !pipeline resume R77 — 从历史恢复已归档管线
        round_name = parts[1] if len(parts) >= 2 else ""
        if not round_name:
            return "❌ 用法: !pipeline resume <round>"
        ctx = await mgr.restore_from_history(round_name)
        if ctx is None:
            return f"❌ {round_name} 不存在或已终态（COMPLETED/CANCELLED），不可恢复"
        return (
            f"✅ {round_name} 已恢复\n"
            f"  状态: {ctx.status.value}\n"
            f"  Step: {ctx.current_step}/{ctx.total_steps}\n"
            f"  成员: {len(ctx.role_agent_map)} 个角色\n"
        )

    elif subcmd == "history":
        entries = mgr.get_history(limit=10)
        if not entries:
            return "📋 暂无历史记录"
        lines = ["📋 最近归档:"]
        for e in reversed(entries):
            lines.append(f"  • {e.get('round_name', '?')} [{e.get('task_kind', '?')}] status={e.get('status', '?')}")
        return "\n".join(lines)

    return "❌ 未知子命令。支持: create, status, list, advance, block, archive, cancel, history"


# ── R42: Pipeline commands ─────────────────────────────────────────


async def _cmd_pipeline_start(sender_id: str, params: dict) -> str:
    """启动管线 — R97 简化版。

    用法：!pipeline_start <R{N}>
    仅需 round_name，零 frontmatter/workspace 依赖。
    通过 PipelineContextManager + AutoRouter 自动调度 Step 链。
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!pipeline_start <R{N}>"
    round_name = positional[0].upper()

    # 防重复
    mgr = _get_pipeline_manager()
    existing = mgr.get_context(round_name)
    if existing and isinstance(existing, dict):
        if existing.get("status") in ("running",):
            return f"❌ {round_name} 管线已活跃，不可重复启动"
    elif existing and hasattr(existing, "is_active") and existing.is_active():
        return f"❌ {round_name} 管线已活跃，不可重复启动"

    # 获取发起者名称
    sender_name = auth.get_users().get(sender_id, {}).get("name", sender_id[:16])

    # 创建 R97 PipelineContext（dict 格式，轻量）
    from ..pipeline_context import StepInfo, DEFAULT_STEP_ORDER, DEFAULT_STEPS
    ctx = {
        "round_name": round_name,
        "status": "running",
        "created_at": time.time(),
        "triggerer_id": sender_id,
        "triggerer_name": sender_name,
        "steps": {
            k: {
                "step_key": v.step_key,
                "role": v.role,
                "title": v.title,
                "status": "pending",
                "agent_id": "",
                "agent_name": "",
                "output": None,
                "result_msg": "",
            }
            for k, v in DEFAULT_STEPS.items()
        },
        "step_order": list(DEFAULT_STEP_ORDER),
        "work_plan_url": "",
        "references": {},
    }

    # 持久化
    mgr.set_context(round_name, ctx)

    # 广播 _admin
    step_chain = " → ".join(
        f"{s['step_key']}({s['role']})"
        for s in ctx["steps"].values()
    )
    try:
        await _broadcast_to_channel(p.ADMIN_CHANNEL, {
            "type": "broadcast",
            "channel": p.ADMIN_CHANNEL,
            "from_name": "系统",
            "from_agent": SYSTEM_AGENT_ID,
            "content": (
                f"🚀 **{round_name} 管线已启动**\n"
                f"  发起者: {sender_name}\n"
                f"  Step 链: {step_chain}"
            ),
            "ts": time.time(),
        })
    except Exception as e:
        logger.warning("R97: _admin 广播失败: %s", e)

    return (
        f"🚀 **{round_name} 管线已启动**\n"
        f"  Step 链: {step_chain}\n"
        f"  AutoRouter 将自动派活 Step 1 → PM（{DEFAULT_STEPS['step1'].role}）"
    )


# ── R50: Pipeline activate command ────────────────────────────────



async def _cmd_pipeline_activate(sender_id: str, params: dict) -> str:
    """激活已启动但未活跃的管线。
    用法：!pipeline_activate <R{N}> [--ws <workspace_id>]
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!pipeline_activate <R{N}> [--ws <workspace_id>]"
    round_name = positional[0].upper()
    ws_id = params.get("ws", "")

    if not pipeline_exists(round_name):
        return f"❌ {round_name} 管线不存在，请先执行 !pipeline_start {round_name}"
    if pipeline_is_active(round_name):
        return f"❌ {round_name} 管线已激活，无需重复激活"

    # Use provided --ws or fallback to pipeline state
    if not ws_id:
        ws_id = state._PIPELINE_STATE.get(round_name, {}).get("ws_id", "")
    if not ws_id:
        return f"❌ {round_name} 未找到工作室 ID，请用 --ws <workspace_id> 指定"

    ws_obj = ws_mod.get_workspace(ws_id)
    if not ws_obj:
        return f"❌ 工作室 {ws_id} 不存在"

    # R82: removed MSG_SET_ACTIVE_CHANNEL broadcast
    # Activate pipeline
    _set_pipeline_state(round_name, {
        "active": True,
        "current_step": state._PIPELINE_STATE.get(round_name, {}).get("current_step", "step1"),
        "ws_id": ws_id,
        "activated_at": __import__("time").time(),
    })

    return (
        f"🚀 **{round_name} 管线已激活**\n"
        f"  工作室: {ws_id}\n"
        f"  任务将通过 inbox 分发给各成员"
    )


# ── R95: Pipeline stop command ────────────────────────────────



async def _cmd_pipeline_stop(sender_id: str, params: dict) -> str:
    """停止 AutoRouter 管线调度。
    用法：!pipeline_stop <R{N}>
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!pipeline_stop <R{N}>"
    round_name = positional[0].upper()

    # 1. 从 PipelineContextManager 查找
    mgr = _get_pipeline_manager()
    ctx = mgr.get(round_name)

    # 2. 从 state._PIPELINE_STATE 查找（旧系统）
    pstate = state._PIPELINE_STATE.get(round_name)

    if not ctx and not pstate:
        return f"❌ 管线 {round_name} 不存在"

    # 3. 权限校验：仅发起者可 stop
    creator = ""
    if ctx:
        creator = ctx.created_by if hasattr(ctx, "created_by") else ctx.get("created_by", "")
    elif pstate:
        creator = pstate.get("triggerer_id", "")
    if creator and sender_id != creator:
        return f"❌ 只有发起者可以 stop 此管线"

    # 4. 状态检查
    if ctx:
        _ctx_status = ctx.status.value if hasattr(ctx, "status") and hasattr(ctx.status, "value") else \
                      ctx.status if hasattr(ctx, "status") else \
                      ctx.get("status", "")
        if _ctx_status in ("stopped", "done"):
            return f"✅ Pipeline {round_name} 已停止（无需操作）"
    if pstate and not pstate.get("active", False):
        # 旧系统中 inactive = 已结束/停止
        return f"✅ Pipeline {round_name} 已停止（无需操作）"

    # 5. 执行停止
    if ctx:
        ok = await mgr.transition_to(round_name, PipelineStatus.STOPPED)
        if not ok:
            return f"❌ 无法停止 {round_name}（状态转换失败）"
    if pstate:
        pstate["active"] = False
        pstate["stopped_at"] = __import__("time").time()

    # 6. 广播到 _admin
    try:
        await _broadcast_to_channel(p.ADMIN_CHANNEL, {
            "type": "broadcast",
            "channel": p.ADMIN_CHANNEL,
            "from_name": "系统",
            "from_agent": SYSTEM_AGENT_ID,
            "content": f"🛑 Pipeline {round_name} 已停止（发起者: {sender_id[:12]}...）",
            "ts": time.time(),
        })
    except Exception:
        pass  # 不阻断 return

    return f"🛑 Pipeline {round_name} 已停止"


# ── R68 A3: Send inbox task assignment + workspace notification ──

async def _send_inbox_task(
    target_agent_id: str,
    round_name: str,
    next_step: str,
    step_config: dict,
    output_ref: str,
    workspace_id: str,
    pm_name: str,
    pm_agent_id: str = SYSTEM_AGENT_ID,  # ← R69 B1 / R99: 常量统一
) -> None:
    """Send full task to target agent's inbox + lightweight workspace notification."""
    inbox_ch = persistence.get_inbox_channel(target_agent_id)
    _pstate = state._PIPELINE_STATE.get(round_name, {})
    _pconfig = state._PIPELINE_CONFIG.get(round_name, {})

    # Collect context URLs
    req_url = _pconfig.get("requirements_url",
        f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/{round_name}-product-requirements.md")
    plan_url = _pconfig.get("work_plan_url",
        _pstate.get("work_plan_url",
            f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/WORK_PLAN.md"))

    # ── R69 A3: Build rich context from step_outputs ──
    _pstate_step_outputs = _pstate.get("step_outputs", {})
    _prev_step_key = None
    if _pstate_step_outputs:
        for _sk in reversed(sorted(_pstate_step_outputs.keys(), key=_step_sort_key)):
            if _sk != next_step:
                _prev_step_key = _sk
                break
    _prev_section = ""
    if _prev_step_key:
        _prev_out = _pstate_step_outputs[_prev_step_key]
        _prev_sha = _prev_out.get("sha", "")[:7]
        _prev_title = _prev_out.get("title", _prev_step_key)
        _prev_summary = _prev_out.get("summary", "")
        _prev_url = _prev_out.get("artifact_url", "")
        _prev_section = f"🏗️ 前序 Step {_prev_step_key.replace('step','')}「{_prev_title}」✅ ({_prev_sha})\n"
        if _prev_summary:
            _prev_section += f"  └ 💡 {_prev_summary}\n"
        if _prev_url:
            _prev_section += f"  └ 🔗 {_prev_url}\n"

    _step_title = _pconfig.get("steps", {}).get(next_step, {}).get("title", next_step)
    inbox_msg = (
        f"📥 任务分配 — {round_name} Step「{_step_title}」\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_prev_section}\n"
        f"📄 参考资料:\n"
        f"  📄 需求：{req_url}\n"
        f"  📋 WORK_PLAN：{plan_url}\n\n"
        f"🎯 你的任务: 请按技术方案完成 {next_step}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"完成后: git push dev → !step_complete {next_step} --output <sha>"
    )

    # Persist inbox message
    ms.save_message(
        msg_id=str(uuid.uuid4()), msg_type="broadcast",
        from_agent=SYSTEM_AGENT_ID, from_name=pm_name,
        content=inbox_msg, ts=time.time(),
        data_dir=config.DATA_DIR, channel=inbox_ch,
    )

    # Send to target agent's connections (unicast)
    inbox_payload = json.dumps({
        "type": "broadcast", "channel": inbox_ch,
        "from_name": pm_name, "from": pm_name,
        "agent_id": pm_agent_id,       # ← R69 B1
        "from_agent": pm_agent_id,     # ← R69 B1
        "content": inbox_msg, "ts": time.time(),
    })
    conns = _connections.get(target_agent_id, set())
    for conn in list(conns):
        try:
            if hasattr(conn, "send_str"):
                await conn.send_str(inbox_payload)
            elif hasattr(conn, "send"):
                await conn.send(inbox_payload)
        except Exception:
            pass

    logger.info("Inbox task [%s] %s → %s", round_name, pm_name, target_agent_id[:12])

    # 🏠 工作室轻量通知
    ws_obj = ws_mod.get_workspace(workspace_id)
    if ws_obj:
        users = auth.get_users()
        target_name = users.get(target_agent_id, {}).get("name", target_agent_id[:12])
        notify_msg = f"@{target_name} 🔔 Step「{_step_title}」已分配，请查看收件箱 📥"
        _persist_broadcast(workspace_id, "系统", notify_msg)
        notify_payload = json.dumps({
            "type": "broadcast", "channel": workspace_id,
            "from_name": "系统", "from": "系统",
            "content": notify_msg, "ts": time.time(),
        })
        for member_id in ws_obj.members:
            for conn in list(_connections.get(member_id, set())):
                try:
                    if hasattr(conn, "send_str"):
                        await conn.send_str(notify_payload)
                    elif hasattr(conn, "send"):
                        await conn.send(notify_payload)
                except Exception:
                    pass


# ── R80: Validation hook helpers ─────────────────────────────────────



def _check_pm_or_admin(sender_id: str) -> bool:
    """检查发送者是否有「强制推进」权限。

    满足任一条件即可：
    1. 全局管理员（auth.is_global_admin）
    2. PM Agent（sender_id == config.PIPELINE_PM_AGENT_ID，如有配置）
    """
    if auth.is_global_admin(sender_id):
        return True
    pm_agent = getattr(config, "PIPELINE_PM_AGENT_ID", None)
    if pm_agent and sender_id == pm_agent:
        return True
    return False



async def _run_validation_hook(
    round_name: str, step_name: str, output_ref: str, step_config: dict,
) -> tuple[bool, str]:
    """执行验证钩子。从 step_config 读取 validation 配置，执行子进程验证脚本。"""
    val_config = step_config.get(step_name, {}).get("validation", {})
    if not val_config:
        return (True, "⏭️ 无验证脚本，跳过")

    script_template = val_config.get("script", config.VALIDATION_DEFAULT_SCRIPT)
    if not script_template:
        return (True, "⏭️ 验证脚本为空，跳过")
    timeout = val_config.get("timeout", config.VALIDATION_DEFAULT_TIMEOUT)
    required = val_config.get("required", True)

    # 模板渲染
    script = script_template.replace("{output_ref}", output_ref or "")
    script = script.replace("{step_name}", step_name)
    script = script.replace("{round_name}", round_name)

    try:
        proc = await asyncio.create_subprocess_shell(
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        if proc.returncode == 0:
            return (True, "✅ 验证通过（exit=0）")
        err_msg = (stderr.decode().strip()[:300]
                   or stdout.decode().strip()[:300])
        if required:
            return (False, f"❌ 验证失败（exit={proc.returncode}）: {err_msg}")
        return (True, f"⚠️ 验证警告（exit={proc.returncode}，非必需）: {err_msg}")
    except asyncio.TimeoutError:
        if required:
            return (False, f"❌ 验证超时（>{timeout}s）")
        return (True, f"⚠️ 验证超时（非必需）")
    except Exception as e:
        if required:
            return (False, f"❌ 验证异常: {e}")
        return (True, f"⚠️ 验证异常（非必需）: {e}")



async def _cmd_step_complete(sender_id: str, params: dict) -> str:
    """标记 Step 完成，自动点名下一人。
    用法：!step_complete <step_name> [--output <commit/file>]
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_complete <step_name> [--output <commit/file>]"
    step_name = positional[0].lower()
    output_ref = params.get("output", "")

    # ── R65 B1: Auto-detect SHA when --output is missing ──
    if not output_ref and config.ENABLE_GIT_SYNC:
        try:
            branch = config.GIT_SYNC_BRANCH
            proc = await asyncio.create_subprocess_exec(
                "git", "log", "-1", "--format=%H", f"origin/{branch}",
                cwd=config.REPO_PATH,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode == 0:
                sha = stdout.decode().strip()
                if sha:
                    output_ref = sha
                    logger.info("[R65 B1] 自动检测最新 SHA: %s", sha)
            else:
                logger.warning("[R65 B1] git log 失败: %s", stderr.decode().strip())
        except Exception as e:
            logger.warning("[R65 B1] 自动检测 SHA 异常: %s", e)
    # ── R65 B1: End ──

    if not output_ref:
        return "❌ 缺少 --output <sha>，且无法自动检测最新 commit"

    # ── R84 FIX: 用发送者所在的工作区取代 lobby ──
    active_workspaces = ws_mod.get_workspaces_for_agent(sender_id)
    active_ws = [w for w in active_workspaces if w.state == ws_mod.WorkspaceState.ACTIVE]
    if not active_ws:
        return "❌ 请在工作区中使用此命令（你不在任何活跃工作室中）"
    sender_ch = active_ws[0].id
    ws_obj = ws_mod.get_workspace(sender_ch)
    if not ws_obj:
        return "❌ 请在工作区中使用此命令"

    # 从 ws name 提取 round_name
    round_name = None
    for rname, pstate in state._PIPELINE_STATE.items():
        if pstate.get("ws_id") == sender_ch:
            round_name = rname
            break
    if not round_name:
        return "❌ 当前工作区无活跃管线（可能已结束或被手动创建）"

    # ── R55 E: Mode check ──
    # In manual mode, only the step's role can advance
    pstate = state._PIPELINE_STATE.get(round_name, {})
    # ── R70 Fix: step_config always defined (was inside manual block) ──
    step_config = _get_step_config(round_name)
    if pstate.get("mode", "auto") == "manual":
        step_role = step_config.get(step_name, {}).get("role", "")
        if step_role:
            users = auth.get_users()
            sender_role = users.get(sender_id, {}).get("role", "member")
            if sender_role != step_role and not auth.is_global_admin(sender_id):
                return f"❌ manual 模式下仅 {step_role} 可推进 Step「{step_name}」"

    # ── R55 C: Git commit verification ──
    if output_ref:
        git_ok, git_msg = await _verify_git_commit(output_ref)
        if not git_ok:
            return git_msg  # ❌ prevents advance

    # ── R55 A: 2s serialization buffer ──
    buffer_key = f"{round_name}:{step_name}"
    last_ts = _step_advance_buffer.get(buffer_key, 0.0)
    if time.time() - last_ts < 2.0:
        return f"❌ {step_name} 正在被推进中（2 秒序列化缓冲），请稍后重试"
    _step_advance_buffer[buffer_key] = time.time()

    # 提取 ws_id
    ws_id = sender_ch

    # 标记当前 Task completed
    tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
    current_task = None
    for t in tasks:
        if t.get("name") == step_name and t.get("state") != p.TaskState.COMPLETED.value:
            current_task = t
            break
    if not current_task:
        return f"❌ 未找到 Step「{step_name}」的活跃 Task（可能已完成）"

    task_update_params = {
        "_positional": [current_task["id"]],
        "state": p.TaskState.COMPLETED.value,
        "output": output_ref,
    }
    task_result = await _cmd_task_update(sender_id, task_update_params)

    # ── R57: Clear backup_active marker on step completion ──
    pstate.pop("backup_active", None)

    # ── R66 B1 + R69 A1: Record step output with context ──
    pstate_b1 = state._PIPELINE_STATE.get(round_name)
    if pstate_b1:
        step_outputs = pstate_b1.setdefault("step_outputs", {})
        step_outputs[step_name] = {
            "sha": output_ref or "",
            "title": step_config.get(step_name, {}).get("title", step_name),
            "output_desc": step_config.get(step_name, {}).get("output_desc", ""),
            "summary": params.get("summary", step_config.get(step_name, {}).get("output_desc", "")),
            "artifact_url": params.get("artifact_url",
                _infer_artifact_url(step_name, round_name, step_config)),
            "timestamp": time.time(),
        }

    # ── R80 A: Validation hook gate ──────────────────────────────
    force_bypass = (
        params.get("_force_mode", False)
        and _check_pm_or_admin(sender_id)
    )
    if config.ENABLE_VALIDATION_HOOK and not force_bypass:
        val_passed, val_msg = await _run_validation_hook(
            round_name, step_name, output_ref, step_config
        )
        if not val_passed:
            # Block the pipeline
            mgr = _get_pipeline_manager()
            try:
                await mgr.transition_to(
                    round_name, PipelineStatus.BLOCKED,
                    blocked_reason=val_msg,
                )
            except Exception:
                pass
            # Notify PM
            pm_agent_id = getattr(config, "PIPELINE_PM_AGENT_ID", "")
            if pm_agent_id:
                pm_inbox = f"_inbox:{pm_agent_id}"
                try:
                    await _broadcast_to_channel(pm_inbox, {
                        "type": "broadcast",
                        "channel": pm_inbox,
                        "from_name": "系统",
                        "from_agent": SYSTEM_AGENT_ID,
                        "content": (
                            f"🔴 {round_name} {step_name} 验证失败\n\n"
                            f"{val_msg}\n\n"
                            f"操作：`!step_force {step_name} --output {output_ref}` 强制推进\n"
                            f"或修复后 `!step_verify {step_name}` 重新验证"
                        ),
                        "ts": time.time(),
                    })
                except Exception:
                    pass
            return f"🔴 **{round_name} {step_name} 验证失败** ❌\n\n{val_msg}\n\n管线已进入 BLOCKED 状态。"
    # ── R80 A: End ──

    # 查 Step 映射表 → 找下一角色
    step_config = _get_step_config(round_name)
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
    current_idx = None
    for i, k in enumerate(step_keys):
        if k == step_name:
            current_idx = i
            break
    if current_idx is None or current_idx + 1 >= len(step_keys):
        # 最后一步 → 管线结束
        # R48 B: 在清理前提取触发者信息
        triggerer_id = state._PIPELINE_STATE.get(round_name, {}).get("triggerer_id", "")

        close_result = await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})
        if "❌" in str(close_result):
            return f"❌ 管线关闭失败，请手动处理：\n{close_result}"
        set_lobby_paused(False)

        # ── R48 B: 写入 _admin 频道完结通知 ──
        try:
            admin_channel = p.ADMIN_CHANNEL
            cleanup_msg = (
                f"🔔 [PIPELINE_COMPLETE] {round_name} — 所有 Step 已完结 ✅\n"
                f"最终产出: {output_ref}\n"
                f"工作室已关闭，大厅已恢复接收"
            )
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=cleanup_msg, ts=time.time(),
                data_dir=config.DATA_DIR, channel=admin_channel,
            )
        except Exception:
            pass
        # ── R48 B: End ──

        _clear_pipeline_state(round_name)

        return (
            f"🏁 **{round_name} 管线已完成！**\n"
            f"  🎯 产出: {output_ref}\n"
            f"  {task_result}\n"
            f"  工作室已关闭，大厅已恢复接收"
        )

    next_step = step_keys[current_idx + 1]
    next_role = step_config[next_step]["role"]
    # ── R59 C: Apply role override if configured ──
    _role_overrides = getattr(config, "PIPELINE_ROLE_OVERRIDES", {})
    if next_step in _role_overrides:
        next_role = _role_overrides[next_step]
    # ── R59 C: End role override ──

    # ── R43 D: Resolve next role display name ──
    # ── R49 B: Use agent cards if available ──
    users = auth.get_users()
    cards = ac_mod.get_all_cards()
    if cards:
        matched = _find_agents_by_role(next_role, ws_obj.members, cards)
        next_role_names = [
            users.get(aid, {}).get("name", aid[:12])
            for aid in matched
        ]
    else:
        next_role_names = [
            users.get(aid, {}).get("name", aid[:12])
            for aid in ws_obj.members
            if users.get(aid, {}).get("role", "member") == next_role
        ]
    next_role_display = ", ".join(next_role_names) if next_role_names else next_role

    # ── R66 B2: Render context for rollcall ──
    _b2_step_outputs = pstate.get("step_outputs", {}) if pstate else {}
    _b2_next_context = step_config.get(next_step, {}).get("context", {})
    _b2_rendered = _render_context(_b2_next_context, round_name, _b2_step_outputs)
    _b2_context_lines = []
    for _k, _v in _b2_rendered.items():
        if _v:
            _labels = {
                "requirements_url": "📄 需求",
                "work_plan_url": "📋 WORK_PLAN",
                "tech_plan_url": "🏗️ 技术方案",
                "bug_report_url": "🐛 Bug 报告",
            }
            _label = _labels.get(_k, f"📎 {_k}")
            _b2_context_lines.append(f"  {_label}: {_v}")
    _b2_suffix = "\n" + "\n".join(_b2_context_lines) if _b2_context_lines else ""

    # ── R55 F: Targeted handoff (replace broadcast rollcall) ──
    # Send MSG_SET_ACTIVE_CHANNEL + task notification only to next step's agents
    context_summary = f"上一 Step「{step_name}」产出: {output_ref}"
    targeted_notify = f"🎯 新任务：{round_name} {next_step} ({next_role})\n{context_summary}{_b2_suffix}"

    # ── R57 A: Online pre-check + rollcall with backup fallback ──
    member_ids = list(ws_obj.members)

    # Read primary/backup config
    primary_role = step_config[next_step].get("primary")
    backup_role = step_config[next_step].get("backup")

    # Resolve primary agent
    primary_agents: list[str] = []
    if cards and primary_role:
        primary_agents = _find_agents_by_role(primary_role, member_ids, cards)

    if not primary_agents:
        # No primary config → fallback to original full-notify behaviour (A-9 compat)
        if cards:
            target_agents = _find_agents_by_role(next_role, member_ids, cards)
        else:
            target_agents = [
                aid for aid in member_ids
                if users.get(aid, {}).get("role", "member") == next_role
            ]
        for agent_id in target_agents:
            await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
        rollcall_result = f"📨 已通知 {next_role_display}（{len(target_agents)} 人）接管 {next_step}"
    else:
        target_agents = []
        primary_agent = primary_agents[0]
        primary_name = users.get(primary_agent, {}).get("name", primary_agent[:12])
        conns = _connections.get(primary_agent, set())

        if not conns:
            # ── Primary offline → direct backup, 0s wait ──
            rollcall_result = await _r57_switch_to_backup(
                round_name, next_step, next_role,
                backup_role, member_ids, cards, users,
                ws_obj, sender_ch, targeted_notify, primary_name,
                reason="primary_offline",
            )
        else:
            # ── R68 A3: inbox task assignment + workspace notification ──
            if next_role == "arch":
                pm_name = config.PIPELINE_ARCH_FROM_NAME
            else:
                pm_name = config.PIPELINE_PM_NAME

            # Send full task to inbox
            await _send_inbox_task(
                target_agent_id=primary_agent,
                round_name=round_name,
                next_step=next_step,
                step_config=step_config,
                output_ref=output_ref,
                workspace_id=sender_ch,
                pm_name=pm_name,
                pm_agent_id=sender_id,  # ← R69 B1
            )

            # Start 30s rollcall timer (keep existing rollcall logic)
            ack_received = await _r57_wait_for_ack(primary_agent, timeout=30)

            if ack_received:
                # Primary confirmed ✓ normal handoff
                if cards:
                    target_agents = _find_agents_by_role(next_role, member_ids, cards)
                else:
                    target_agents = [
                        aid for aid in member_ids
                        if users.get(aid, {}).get("role", "member") == next_role
                    ]
                for agent_id in target_agents:
                    await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
                rollcall_result = f"✅ 主角 {primary_name} 已确认，正常交接 {next_step}"
            else:
                # Primary 30s no response → switch to backup
                rollcall_result = await _r57_switch_to_backup(
                    round_name, next_step, next_role,
                    backup_role, member_ids, cards, users,
                    ws_obj, sender_ch, targeted_notify, primary_name,
                    reason="primary_timeout",
                )

    # 创建下一步的 Task
    next_task_result = await _cmd_task_create(sender_id, {
        "context": round_name,
        "name": next_step,
        "role": next_role,
    })

    # ── R58 C2: Record notification status to pstate ──
    step_notifications = pstate.setdefault("step_notifications", {})
    step_notifications[next_step] = {
        "status": "notified",
        "notified_at": time.time(),
        "target_agents": target_agents,
    }
    # ── R58 C2: End notification status ──

    # ── R59 B3: PM auto-fallback monitor for dev ──
    # dev(爱泰) 无法通过 ws-bridge 代码自动触发（方向 A 实验确认任何 from_name 均无效）。
    # B3 兜底成为 dev 触发的主要通道（而非备用）。
    if next_role == "dev" and next_step != "step6":
        asyncio.create_task(_r59_auto_fallback_monitor(
            round_name=round_name,
            next_step=next_step,
            next_role=next_role,
            primary_agent=locals().get('primary_agent', None),
            primary_name=locals().get('primary_name', next_role),
            sender_ch=sender_ch,
            ws_obj=ws_obj,
            timeout_minutes=5,
        ))
    # ── R59 B3: End ──

    # 更新管线状态
    _update_pipeline_step(round_name, next_step)

    # 通知 PM（在 _admin 频道发进度）
    try:
        admin_channel = p.ADMIN_CHANNEL
        notify_msg = (
            f"📋 {round_name} 进度：{step_name} ✅ → "
            f"下一棒 {next_role}（{next_step}）产出: {output_ref or '(未提供)'}"
        )
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent="系统", from_name="系统",
            content=notify_msg, ts=time.time(),
            data_dir=config.DATA_DIR, channel=admin_channel,
        )
    except Exception:
        pass

    # ── Notify PM inbox of step progress (同步通知小谷收件箱) ──
    try:
        pm_users = auth.get_users()
        pm_agent_id = None
        for aid_u, u in pm_users.items():
            if u.get("name") == config.PIPELINE_PM_NAME:
                pm_agent_id = aid_u
                break
        if pm_agent_id:
            pm_inbox_ch = persistence.get_inbox_channel(pm_agent_id)
            _out_short = output_ref[:7] if output_ref else "(未提供)"
            pm_notify = (
                f"📋 {round_name} 进度：{step_name} ✅ → "
                f"下一棒 {next_role_display}（{next_step}）\n"
                f"  🎯 产出: {_out_short}"
            )
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=pm_notify, ts=time.time(),
                data_dir=config.DATA_DIR, channel=pm_inbox_ch,
            )
            pm_payload = json.dumps({
                "type": "broadcast", "channel": pm_inbox_ch,
                "from_name": "系统", "from": "系统",
                "content": pm_notify, "ts": time.time(),
            })
            for conn in list(_connections.get(pm_agent_id, set())):
                try:
                    if hasattr(conn, "send_str"):
                        await conn.send_str(pm_payload)
                    elif hasattr(conn, "send"):
                        await conn.send(pm_payload)
                except Exception:
                    pass
            logger.info("PM inbox notified: %s %s ✅ → %s", round_name, step_name, next_step)
    except Exception:
        pass

    # ── R43 C: Send clear alert if watchdog was active ──
    if _clear_watchdog_alert(round_name, step_name):
        await _send_clear_alert(round_name, step_name, output_ref)

    # ── Step-complete: clear old timer, start next step timer ──
    timeout_tracker.clear_timer(round_name)
    _step_timeout_mins = step_config.get(next_step, {}).get("timeout_minutes",
        int(step_config.get(next_step, {}).get("timeout_hours", 6) * 60))
    timeout_tracker.start_timer(round_name, next_step, int(_step_timeout_mins))

    # ── Start ACK state machine for next step assignment ──
    ack_key = f"{round_name}/{next_step}"
    state._step_ack_states[ack_key] = {
        "state": "SENT",
        "agent_id": primary_agent if 'primary_agent' in dir() and primary_agents else "",
        "sent_at": time.time(),
        "deadline": time.time() + 30,
        "delivery_sent": 0,
    }
    asyncio.create_task(_ack_timeout_task(ack_key))

    # ── R53 D: Enhanced return value with ACK confirm ──
    # ── R55 F: Use targeted handoff result ──
    return (
        f"✅ **{step_name} 完成** → 交接给 {next_role} {next_step}\n"
        f"  📨 已定向通知 {next_role_display}（{len(target_agents)} 人）接管\n"
        f"  {task_result}\n"
        f"  {next_task_result}"
    )


# ── R80 B: Step force command ────────────────────────────────



async def _cmd_step_force(sender_id: str, params: dict) -> str:
    """强制推进 Step（跳过验证钩子）。

    用法：!step_force <step_name> --output <sha> [--reason "原因"]
    权限：仅 PM 或全局管理员可执行。
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_force <step_name> --output <sha> [--reason \"原因\"]"

    step_name = positional[0].lower()
    output_ref = params.get("output", "")
    reason = params.get("reason", "无说明")

    if not output_ref:
        return "❌ 缺少 --output <sha>"

    if not _check_pm_or_admin(sender_id):
        return "❌ 权限不足：仅 PM 或管理员可强制推进"

    # 审计日志
    _audit_logger.log(
        sender_id, "step_force",
        {"step": step_name, "output": output_ref, "reason": reason},
        "forced",
    )

    # 传给 _cmd_step_complete，携带 _force_mode 标志
    params["_force_mode"] = True
    return await _cmd_step_complete(sender_id, params)


# ── R80 C: Step verify command ───────────────────────────────



async def _cmd_step_verify(sender_id: str, params: dict) -> str:
    """BLOCKED 状态下重新执行验证钩子。

    用法：!step_verify <step_name> [--output <sha>]
    若不传 --output，从 step_outputs 复用上次的 SHA。
    验证通过后将管线从 BLOCKED 恢复为 RUNNING。
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_verify <step_name> [--output <sha>]"

    step_name = positional[0].lower()
    output_ref = params.get("output", "")

    # 确定 round_name（从发送者的活跃频道推断）
    sender_ch = p.LOBBY
    round_name = next(
        (r for r, s in state._PIPELINE_STATE.items() if s.get("ws_id") == sender_ch),
        None,
    )
    if not round_name:
        return "❌ 当前工作区无活跃管线"

    # 未提供 --output 时，从 step_outputs 复用
    if not output_ref:
        pstate = state._PIPELINE_STATE.get(round_name, {})
        output_ref = (
            pstate.get("step_outputs", {})
            .get(step_name, {})
            .get("sha", "")
        )
        if not output_ref:
            return f"❌ 未找到 {step_name} 的历史产出 SHA，请使用 --output 指定"

    step_config = _get_step_config(round_name)
    val_passed, val_msg = await _run_validation_hook(
        round_name, step_name, output_ref, step_config,
    )

    if val_passed:
        # 恢复管线运行
        mgr = _get_pipeline_manager()
        try:
            await mgr.transition_to(round_name, PipelineStatus.RUNNING)
        except Exception:
            pass
        return (
            f"✅ **{round_name} {step_name} 验证通过** ✓\n\n"
            f"{val_msg}\n\n"
            f"管线已恢复 RUNNING 状态。"
        )

    return f"🔴 **{round_name} {step_name} 验证仍失败** ❌\n\n{val_msg}"


# ── R55 F: Targeted send helper ────────────────────────────



async def _cmd_step_handoff(sender_id: str, params: dict) -> str:
    """标记 Step 完成并交接给下一角色，同时广播 MSG_SET_ACTIVE_CHANNEL。
    用法：!step_handoff <step_name> --output <commit/file>
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_handoff <step_name> --output <commit/file>"
    step_name = positional[0].lower()
    output_ref = params.get("output", "")
    if not output_ref:
        return "❌ --output 为必填参数，请提供 commit SHA 或文件路径"

    sender_ch = p.LOBBY
    ws_obj = ws_mod.get_workspace(sender_ch)
    if not ws_obj:
        return "❌ 请在工作区中使用此命令"

    # Extract round_name from pipeline state
    round_name = None
    for rname, pstate in state._PIPELINE_STATE.items():
        if pstate.get("ws_id") == sender_ch:
            round_name = rname
            break
    if not round_name:
        return "❌ 当前工作区无活跃管线（可能已结束或被手动创建）"

    ws_id = sender_ch

    # Mark current Task completed
    tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
    current_task = None
    for t in tasks:
        if t.get("name") == step_name and t.get("state") != p.TaskState.COMPLETED.value:
            current_task = t
            break
    if not current_task:
        return f"❌ 未找到 Step「{step_name}」的活跃 Task（可能已完成）"

    task_update_params = {
        "_positional": [current_task["id"]],
        "state": p.TaskState.COMPLETED.value,
        "output": output_ref,
    }
    task_result = await _cmd_task_update(sender_id, task_update_params)

    # Look up next step
    step_config = _get_step_config(round_name)
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
    current_idx = None
    for i, k in enumerate(step_keys):
        if k == step_name:
            current_idx = i
            break
    if current_idx is None or current_idx + 1 >= len(step_keys):
        # Final step → pipeline complete
        close_result = await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})
        if "❌" in str(close_result):
            return f"❌ 管线关闭失败，请手动处理：\n{close_result}"
        set_lobby_paused(False)
        _clear_pipeline_state(round_name)

        # Cleanup progress notification (R47 A4)
        try:
            cleanup_msg = f"📊 {round_name} 管线已完成 ✅ 所有 Step 已完结，工作室已关闭"
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=cleanup_msg, ts=time.time(),
                data_dir=config.DATA_DIR, channel=p.ADMIN_CHANNEL,
            )
        except Exception:
            pass

        return (
            f"🏁 **{round_name} 管线已完成！**\n"
            f"  {task_result}\n"
            f"  工作室已关闭，大厅已恢复接收"
        )

    next_step = step_keys[current_idx + 1]
    next_role = step_config[next_step]["role"]

    # Resolve next role display names
    users = auth.get_users()
    next_role_names = [
        users.get(aid, {}).get("name", aid[:12])
        for aid in ws_obj.members
        if users.get(aid, {}).get("role", "member") == next_role
    ]
    next_role_display = ", ".join(next_role_names) if next_role_names else next_role

    # Rollcall next role
    # ── R66 B2/B3: Render context for handoff rollcall ──
    _h_pstate = state._PIPELINE_STATE.get(round_name, {})
    _h_step_outputs = _h_pstate.get("step_outputs", {})
    _h_next_context = step_config.get(next_step, {}).get("context", {})
    _h_rendered = _render_context(_h_next_context, round_name, _h_step_outputs)
    _h_context_lines = []
    for _k, _v in _h_rendered.items():
        if _v:
            _h_context_lines.append(f"  📎 {_k}: {_v}")
    _h_suffix = "\n" + "\n".join(_h_context_lines) if _h_context_lines else ""
    context_summary = f"上一 Step「{step_name}」产出: {output_ref}"
    rollcall_result = await _cmd_rollcall_next(sender_id, {
        "_positional": [next_role],
        "context": f"{round_name} {next_step}: {context_summary}{_h_suffix}",
    })

    # ── R68 A3: Send inbox task to primary agent (with workspace fallback) ──
    _h_cards = ac_mod.get_all_cards()
    _h_member_ids = list(ws_obj.members)
    _h_primary_role = step_config.get(next_step, {}).get("primary")
    _h_primary_agents = (
        _find_agents_by_role(_h_primary_role, _h_member_ids, _h_cards)
        if _h_cards and _h_primary_role else []
    )
    if _h_primary_agents:
        await _send_inbox_task(
            target_agent_id=_h_primary_agents[0],
            round_name=round_name,
            next_step=next_step,
            step_config=step_config,
            output_ref=output_ref,
            workspace_id=ws_id,
            pm_name="PM",
            pm_agent_id=sender_id,  # ← R69 B1
        )
    else:
        _h_fb_users = auth.get_users()
        _h_fb_role_names = [
            _h_fb_users.get(aid, {}).get("name", aid[:12])
            for aid in ws_obj.members
            if _h_fb_users.get(aid, {}).get("role", "member") == next_role
        ]
        _h_fb_display = ", ".join(_h_fb_role_names) if _h_fb_role_names else next_role
        _h_fb_plan_url = state._PIPELINE_CONFIG.get(round_name, {}).get("work_plan_url", "")
        _h_fb_msg = (
            f"@{_h_fb_display} 🚨 Step「{next_step}」到你了！\n\n"
            f"📋 WORK_PLAN：{_h_fb_plan_url}\n"
            f"🔗 上一步产出：{output_ref}\n\n"
            f"请确认收到后开始工作。完成后调用 !step_complete {next_step} --output <sha>"
        )
        _persist_broadcast(ws_id, "系统", _h_fb_msg)
        _h_fb_payload = json.dumps({
            "type": "broadcast", "channel": ws_id,
            "from_name": "系统", "from": "系统",
            "content": _h_fb_msg, "ts": time.time(),
        })
        for _h_fb_mid in ws_obj.members:
            for _h_fb_conn in list(_connections.get(_h_fb_mid, set())):
                try:
                    if hasattr(_h_fb_conn, "send_str"):
                        await _h_fb_conn.send_str(_h_fb_payload)
                    elif hasattr(_h_fb_conn, "send"):
                        await _h_fb_conn.send(_h_fb_payload)
                except Exception:
                    pass
        logger.info("R68 inbox fallback: broadcast @mention to workspace %s (no primary agent for %s)", ws_id, next_role)

    # Create next step Task
    next_task_result = await _cmd_task_create(sender_id, {
        "context": round_name,
        "name": next_step,
        "role": next_role,
    })

    # Update pipeline state
    _update_pipeline_step(round_name, next_step)

    # R82: removed MSG_SET_ACTIVE_CHANNEL broadcast
    # Notify PM in _admin channel
    try:
        admin_channel = p.ADMIN_CHANNEL
        notify_msg = (
            f"📋 {round_name} 进度：{step_name} ✅ → "
            f"下一棒 {next_role}（{next_step}）产出: {output_ref or '(未提供)'}"
        )
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent="系统", from_name="系统",
            content=notify_msg, ts=time.time(),
            data_dir=config.DATA_DIR, channel=admin_channel,
        )
    except Exception:
        pass

    # Clear watchdog alert if active
    if _clear_watchdog_alert(round_name, step_name):
        await _send_clear_alert(round_name, step_name, output_ref)

    return (
        f"✅ **{step_name} 完成 → 交接给 {next_role} {next_step}**\n"
        f"  产出: {output_ref}\n"
        f"  R82: 任务已通过 inbox 发送\n"
        f"  {rollcall_result}\n"
        f"  {next_task_result}"
    )



async def _cmd_step_reject(sender_id: str, params: dict) -> str:
    """退回 Step N 到 pending 状态，附退回理由。
    用法：!step_reject <step_name> --reason <原因>
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!step_reject <step_name> --reason <原因>"
    step_name = positional[0].lower().strip()
    reason = params.get("reason", "")
    if not reason:
        return "❌ 退回必须附理由：!step_reject <step_name> --reason <原因>"

    # 解析管线上下文
    sender_ch = p.LOBBY
    ws_obj = ws_mod.get_workspace(sender_ch)
    if not ws_obj:
        return "❌ 请在工作区中使用此命令"

    round_name = None
    for rname, pstate in state._PIPELINE_STATE.items():
        if pstate.get("ws_id") == sender_ch:
            round_name = rname
            break
    if not round_name:
        return "❌ 当前工作区无活跃管线（可能已结束或被手动创建）"

    # 前置校验：step 必须在 PIPELINE_STEP_MAP 中
    step_config = _get_step_config(round_name)
    if step_name not in step_config:
        return f"❌ Step「{step_name}」不存在于管线映射中"

    # 找到当前 active task for this step
    tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
    current_task = None
    for t in tasks:
        if t.get("name") == step_name and t.get("state") != p.TaskState.COMPLETED.value:
            current_task = t
            break
    if not current_task:
        return f"❌ Step「{step_name}」没有活跃 Task，无法退回"

    # 检查退回次数上限
    reject_count = current_task.get("reject_count", 0) + 1
    if reject_count >= p.TASK_REJECT_CEILING:
        # R55 W-3: 第 TASK_REJECT_CEILING 次退回 → 升级给 PM
        # TASK_REJECT_CEILING=2 表示第 2 次退回（即 2 次机会后）升级
        # 第 3 次退回 → 升级给 PM
        try:
            admin_channel = p.ADMIN_CHANNEL
            escalation_msg = (
                f"🚨 [ESCALATION] {round_name} {step_name} 已被退回 "
                f"{reject_count} 次，需 PM 介入协调\n"
                f"最近理由: {reason}\n"
                f"退回者: {sender_id[:12]}"
            )
            ms.save_message(
                msg_id=str(uuid.uuid4()), msg_type="broadcast",
                from_agent="系统", from_name="系统",
                content=escalation_msg, ts=time.time(),
                data_dir=config.DATA_DIR, channel=admin_channel,
            )
        except Exception:
            pass
        return (
            f"🚨 {step_name} 已被退回 {reject_count} 次，"
            f"超过上限（{p.TASK_REJECT_CEILING}），自动升级给 PM 协调"
        )

    # 处理原 task: 标记 INPUT_REQUIRED + 写入 reject_count
    ts.update_state(current_task["id"], p.TaskState.INPUT_REQUIRED.value, config.DATA_DIR)
    ts.increment_reject_count(current_task["id"], config.DATA_DIR)

    # 写入退回记录到 state._PIPELINE_STATE
    pstate = state._PIPELINE_STATE.setdefault(round_name, {})
    rejected_steps = pstate.setdefault("rejected_steps", {})
    rejected_steps[step_name] = {
        "reject_count": reject_count,
        "last_reason": reason,
        "rejected_by": sender_id,
        "rejected_at": time.time(),
    }

    # 更新 step 指针（如果当前已推进到此 step 之后，回退）
    current_pstate = state._PIPELINE_STATE.get(round_name, {})
    current_step = current_pstate.get("current_step", "")
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
    current_idx = None
    target_idx = None
    for i, k in enumerate(step_keys):
        if k == step_name:
            target_idx = i
        if k == current_step:
            current_idx = i
    if target_idx is not None and current_idx is not None and current_idx > target_idx:
        _update_pipeline_step(round_name, step_name)

    # 创建新 task（重新从 SUBMITTED 开始）
    next_task_result = await _cmd_task_create(sender_id, {
        "context": round_name,
        "name": step_name,
        "role": step_config[step_name].get("role", ""),
    })

    # 通知被退回角色（方向 F：定向发送）
    users = auth.get_users()
    step_role = step_config[step_name].get("role", "")
    cards = ac_mod.get_all_cards()
    member_ids = list(ws_obj.members)
    if cards:
        target_agents = _find_agents_by_role(step_role, member_ids, cards)
    else:
        target_agents = [
            aid for aid in member_ids
            if users.get(aid, {}).get("role", "member") == step_role
        ]
    reject_notify = f"🔄 {step_name} 被退回（第 {reject_count} 轮）：{reason}"
    for agent_id in target_agents:
        await _send_to_agent(agent_id, reject_notify, ws_id=sender_ch)

    # _admin 频道记录退回日志（PM 可见）
    try:
        admin_channel = p.ADMIN_CHANNEL
        log_msg = (
            f"📋 {round_name} 退回：{step_name} ❌（第 {reject_count} 轮）\n"
            f"  理由：{reason}\n"
            f"  退回者：{sender_id[:12]}"
        )
        ms.save_message(
            msg_id=str(uuid.uuid4()), msg_type="broadcast",
            from_agent="系统", from_name="系统",
            content=log_msg, ts=time.time(),
            data_dir=config.DATA_DIR, channel=admin_channel,
        )
    except Exception:
        pass

    return f"🔄 {step_name} 已退回（第 {reject_count} 轮）：{reason}\n{next_task_result}"


# ── R69 B2: Workspace reset ──

async def _cmd_pipeline_status(sender_id: str, params: dict) -> str:
    """查询当前所有活跃管线的 Step 进度表。"""
    lines = []

    # ── R62: Config-only mode (no state, but config exists) ──
    if state._PIPELINE_CONFIG and not state._PIPELINE_STATE:
        for round_name, pconfig in sorted(state._PIPELINE_CONFIG.items()):
            if round_name in state._PIPELINE_STATE:
                continue
            lines.append(f"📊 **{round_name} 管线配置（state 不存在，config 仍在）**")
            lines.append(f"  目标: {pconfig.get('goal', '')}")
            step_config_c = pconfig.get("steps", {})
            for step_key, step_info in sorted(
                step_config_c.items(),
                key=lambda item: _step_sort_key(item[0]),
            ):
                role = step_info.get("role", "?")
                title = step_info.get("title", step_key)
                lines.append(f"  ⏳ {step_key} — {role}（{title}）")
            lines.append("")

    if not state._PIPELINE_STATE and not lines:
        # ── R62: If verbose is requested but no state/config, show empty
        if params.get("verbose") or params.get("dump"):
            lines.append("📊 当前无活跃管线（无 state._PIPELINE_CONFIG）")
        else:
            return "📊 当前无活跃管线"

    for round_name, pstate in sorted(state._PIPELINE_STATE.items()):
        if not pstate.get("active"):
            continue
        lines.append(f"📊 **{round_name} 管线状态**")
        # R48 A: 展示 work_plan_url（如有）
        if pstate.get("work_plan_url"):
            lines.append(f"  📎 WORK_PLAN: {pstate['work_plan_url']}")
        # ── R55 D: Mode marker ──
        mode = pstate.get("mode", "auto")
        mode_icon = "🚀" if mode == "auto" else "📋"
        lines.append(f"  模式: {mode_icon} {mode}")
        # ── R57 C-2: Display member names with online status ──
        ws_id = pstate.get("ws_id", "")
        if ws_id:
            ws_obj_from_state = ws_mod.get_workspace(ws_id)
            if ws_obj_from_state:
                users_for_status = auth.get_users()
                member_info = []
                for mid in ws_obj_from_state.members:
                    name = users_for_status.get(mid, {}).get("name", "")
                    role_label = users_for_status.get(mid, {}).get("role", "")
                    label = name if name else (role_label if role_label else mid[:12])
                    online = "🟢" if mid in _connections and _connections[mid] else "🔴"
                    member_info.append(f"{online}{label}")
                if member_info:
                    lines.append(f"  成员: {' · '.join(member_info)}")
        # ── R55 D: Rejected steps context ──
        rejected_steps = pstate.get("rejected_steps", {})
        if rejected_steps:
            lines.append(f"  🔄 退回记录:")
            for rstep, rinfo in rejected_steps.items():
                lines.append(
                    f"    {rstep}: 第{rinfo['reject_count']}轮 — {rinfo['last_reason'][:40]}"
                )
        step_config = _get_step_config(round_name)
        tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)

        for step_key, step_info in sorted(
            step_config.items(),
            key=lambda item: _step_sort_key(item[0]),
        ):
            role = step_info["role"]

            matched = [t for t in tasks if t.get("name") == step_key]
            task_state = "⏳"
            if matched:
                t = matched[0]
                ts_state = t.get("state", "")
                if ts_state == p.TaskState.COMPLETED.value:
                    task_state = "✅"
                elif ts_state == p.TaskState.WORKING.value:
                    task_state = "🟢"
                elif ts_state == p.TaskState.FAILED.value:
                    task_state = "❌"
                elif ts_state == p.TaskState.SUBMITTED.value:
                    # ★ R53 B-4: Check for active ACK timer
                    if t["id"] in _task_ack_timers:
                        task_state = "⏳"  # waiting_ack
                    else:
                        task_state = "⬜"  # submitted, no pending ack
                elif ts_state == p.TaskState.INPUT_REQUIRED.value:
                    task_state = "🔄"  # R55 B: rejected, needs rework

            current = " ◀ 当前" if step_key == pstate.get("current_step") else ""
            # ── Countdown display on current step ──
            if current:
                remaining_str = timeout_tracker.format_remaining(round_name, step_key)
                current += f" ({remaining_str})"
            # ── ACK state display on current step ──
            if current:
                ack_status = _format_ack_status(f"{round_name}/{step_key}")
                if ack_status:
                    current += f" | {ack_status}"
            # ── R63 Phase 4: End ──
            # ── R58 C3: Notification status display ──
            step_notifications = pstate.get("step_notifications", {})
            notify_info = step_notifications.get(step_key, {})
            notify_status = notify_info.get("status", "")
            notify_mark = ""
            if notify_status == "notified":
                notify_mark = " 📨"
            elif notify_status == "acknowledged":
                notify_mark = " ✅ACK"
            elif notify_status == "no_response":
                notify_mark = " ❌静默"
            # ── R58 C3: End notification status ──
            # ── R57 A-6: Backup takeover marker ──
            backup_suffix = ""
            pipeline_backup = pstate.get("backup_active", {})
            if step_key == pipeline_backup.get("step"):
                backup_suffix = "（备用接替）"
            lines.append(f"  {task_state} {step_key} — {role}{current}{backup_suffix}{notify_mark}")

        # ── R65 A4: Git sync status line ──
        if config.ENABLE_GIT_SYNC and state._GIT_SYNC_TASK is not None:
            last_sync_ts = pstate.get("_last_git_sync_ts", 0)
            if last_sync_ts:
                delta = int(time.time() - last_sync_ts)
                sync_display = f"{delta}s 前" if delta < 120 else f"{delta // 60}m 前"
            else:
                sync_display = "—"
            pconfig = state._PIPELINE_CONFIG.get(round_name, {})
            branch = pconfig.get("git_sync_branch", config.GIT_SYNC_BRANCH) if state._PIPELINE_CONFIG.get(round_name, {}) else config.GIT_SYNC_BRANCH
            lines.append(f"  🔄 Git 同步: 启用 ✅（最后检查: {sync_display}, {branch}）")
        # ── R65 A4: End ──

    if not lines:
        return "📊 当前无活跃管线"
    # ── R62: --verbose / --dump: show state._PIPELINE_CONFIG summary ──
    if params.get("verbose") or params.get("dump"):
        lines.append("")
        lines.append("📋 state._PIPELINE_CONFIG:")
        if state._PIPELINE_CONFIG:
            for _rname, _pconf in sorted(state._PIPELINE_CONFIG.items()):
                lines.append(f"  [{_rname}] round={_pconf.get('round','')} | goal={_pconf.get('goal','')} | work_plan_url={_pconf.get('work_plan_url','')} | requirements_url={_pconf.get('requirements_url','')}")
                for _sk in sorted(_pconf.get('steps', {}).keys(), key=_step_sort_key):
                    _sc = _pconf['steps'][_sk]
                    lines.append(f"    {_sk}: role={_sc.get('role','')} | title={_sc.get('title','')}")
        else:
            lines.append("  无 state._PIPELINE_CONFIG")
    return "\n".join(lines)


# ── R55 E: Pipeline mode switch ─────────────────────────────



async def _cmd_pipeline_mode(sender_id: str, params: dict) -> str:
    """切换管线模式。
    用法：!pipeline_mode <auto|manual>
    """
    positional = params.get("_positional", [])
    if not positional or positional[0] not in ("auto", "manual"):
        return "❌ 用法：!pipeline_mode auto|manual"
    target_mode = positional[0]

    sender_ch = p.LOBBY
    round_name = None
    for rname, pstate in state._PIPELINE_STATE.items():
        if pstate.get("ws_id") == sender_ch:
            round_name = rname
            break
    if not round_name:
        return "❌ 当前工作区无活跃管线"

    state._PIPELINE_STATE[round_name]["mode"] = target_mode
    icon = "🚀" if target_mode == "auto" else "📋"
    return f"✅ 管线 {round_name} 已切换为 {icon} {target_mode} 模式"


# ── R59 C: Pipeline role override ────────────────────────────



async def _cmd_pipeline_role_override(sender_id: str, params: dict) -> str:
    """覆盖指定 Step 的执行角色。
    用法：!pipeline_role_override <step> --executor <role>

    示例：
      !pipeline_role_override step3 --executor arch
      → Step 3（编码）由 arch 执行而非 dev
    """
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!pipeline_role_override <step> --executor <role>"
    step = positional[0].lower()
    executor = params.get("executor", "")
    if not executor:
        return "❌ 请指定 --executor <role>"

    # 验证 step 存在
    step_config = _load_step_config()
    if step not in step_config:
        return f"❌ Step「{step}」不存在"

    # 保存覆盖到配置
    if not hasattr(config, "PIPELINE_ROLE_OVERRIDES"):
        config.PIPELINE_ROLE_OVERRIDES = {}
    config.PIPELINE_ROLE_OVERRIDES[step] = executor

    original_role = step_config[step]["role"]
    return (
        f"✅ Step「{step}」执行角色覆盖为「{executor}」（原：{original_role}）\n"
        f"📋 约束提醒：若覆盖导致写方案者=编码者，请在 WORK_PLAN 中显式豁免"
    )


# ── R49 B: Agent Card commands ──────────────────────────────────────




def _get_agent_display(agent_id: str) -> str:
    """统一 agent 显示名：display_name > name > role > agent_id[:12]"""
    cards = ac_mod.get_all_cards()
    card = cards.get(agent_id, {})
    if card.get("display_name"):
        return card["display_name"]
    users = auth.get_users()
    u = users.get(agent_id, {})
    if u.get("name"):
        return u["name"]
    if u.get("role"):
        return u["role"]
    return agent_id[:12]



def _get_agent_card_roles(agent_id: str, cards: dict = None) -> list[str]:
    """Get pipeline roles for an agent from cards. Returns [] if not found."""
    if cards is None:
        cards = ac_mod.get_all_cards()
    card = cards.get(agent_id, {})
    return card.get("pipeline_roles", [])



def _find_agents_by_role(role: str, member_ids: list[str], cards: dict) -> list[str]:
    """Find workspace members whose agent card has the given pipeline role."""
    return [
        aid for aid in member_ids
        if role in _get_agent_card_roles(aid, cards)
    ]


# ── R63 Phase 3: Role-agent mapping ────────────────────────────────



# ---- R67 B1: Startup card load + watcher ------------------------------
# These run at module import time (R100: _refresh_role_agent_map moved to command_utils.py).
_cards_loaded_guard: bool = False
_card_watcher: "ac_mod.CardFileWatcher | None" = None  # type: ignore[name-defined]



def _get_agents_by_role(role: str,
                        workspace_members: list[str] = None) -> list[str]:
    """Find agents by pipeline role.

    Priority chain:
    1. PipelineContextManager.get_role_agents() (R78 new path)
    2. state._ROLE_AGENT_MAP (DEPRECATED fallback)
    3. Fallback: auth.get_users().role (legacy compat)
    4. Optional: filter by workspace_members

    Args:
        role: Pipeline role name (arch/dev/review/qa/admin).
        workspace_members: Optional list of member IDs to filter by.

    Returns:
        List of matching agent IDs.
    """
    # R78 A4: 优先走 Manager 查询
    try:
        mgr = _get_pipeline_manager()
        agents = mgr.get_role_agents(role)
    except Exception:
        agents = []
    if not agents:
        agents = state._ROLE_AGENT_MAP.get(role, [])
    if not agents:
        # Fallback to auth roles
        users = auth.get_users()
        agents = [aid for aid, u in users.items()
                  if u.get("role", "member") == role]
    if workspace_members:
        agents = [a for a in agents if a in workspace_members]
    return agents



def _parse_scalar(value: str):
    """Parse a scalar YAML value."""
    value = value.strip()
    if not value:
        return value
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    if value.lower() in ('true', 'yes', 'on'):
        return True
    if value.lower() in ('false', 'no', 'off'):
        return False
    try:
        if '.' in value:
            return float(value)
        return int(value)
    except ValueError:
        pass
    return value



def _parse_frontmatter(content: str) -> dict:
    """Extract and parse YAML frontmatter from WORK_PLAN.md content.
    Supports: strings, nested dicts via indentation, list values.
    Returns: pipeline section dict or raises NoFrontmatterError.
    """
    parts = content.split('---')
    if len(parts) < 3:
        raise NoFrontmatterError("No YAML frontmatter block found")
    frontmatter_text = parts[1].strip()
    lines = frontmatter_text.split('\n')
    result = {}
    stack = [(0, None, result)]
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(line) - len(line.lstrip(' '))
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if stripped.startswith('- '):
            item_text = stripped[2:].strip()
            if stack and stack[-1][2] is not None:
                parent_key = stack[-1][1]
                parent_dict = stack[-1][2]
                if parent_key and parent_key not in parent_dict:
                    parent_dict[parent_key] = []
                if parent_key:
                    parent_dict[parent_key].append(_parse_scalar(item_text))
        elif ':' in stripped:
            key, _, value = stripped.partition(':')
            key = key.strip()
            value = value.strip()
            if stack:
                parent_dict = stack[-1][2]
                if value:
                    parent_dict[key] = _parse_scalar(value)
                    stack.append((indent, key, {}))
                else:
                    parent_dict[key] = {}
                    stack.append((indent, key, parent_dict[key]))
    return result



def _build_pipeline_config(frontmatter: dict, round_name: str, base_urls: dict) -> dict:
    """Build state._PIPELINE_CONFIG from frontmatter dict.

    R74 A2: frontmatter 中的 URL 字段优先，base_urls 仅作为无定义时的补充。
    不再拼接 docs/轮次/ 路径。
    """
    config = frontmatter.get("pipeline", {})
    if not config:
        raise ValueError("Frontmatter missing 'pipeline' key")
    config["round"] = round_name

    # R74 A2: 仅当 frontmatter 无定义时才从 base_urls 获取
    if not config.get("work_plan_url"):
        config["work_plan_url"] = base_urls.get("work_plan_url", "")
    if not config.get("requirements_url"):
        config["requirements_url"] = base_urls.get("requirements_url", "")

    config["steps"] = config.get("steps", {})
    for step_key, step_cfg in config["steps"].items():
        context = step_cfg.get("context", {})
        for ctx_key, ctx_value in list(context.items()):
            if isinstance(ctx_value, str) and "${pipeline." in ctx_value:
                ref_key = ctx_value.replace("${pipeline.", "").rstrip("}")
                if ref_key in config:
                    context[ctx_key] = str(config[ref_key])
    return config



def _build_fallback_config(round_name: str, base_urls: dict) -> dict:
    """Build state._PIPELINE_CONFIG from hardcoded PIPELINE_STEP_MAP (old format compat)."""
    step_map = _r42cfg.PIPELINE_STEP_MAP
    work_plan_url = base_urls.get("work_plan_url", "")
    requirements_url = base_urls.get("requirements_url",
        f"{_r42cfg.WORK_PLAN_REPO_URL}/docs/{round_name}/{round_name}-product-requirements.md")
    steps = {}
    for step_key, step_cfg in step_map.items():
        if step_key == "step1":
            continue
        role = step_cfg.get("role", "")
        steps[step_key] = {
            "role": role,
            "title": step_cfg.get("name", step_key),
            "context": {
                "requirements_url": requirements_url,
                "work_plan_url": work_plan_url,
            },
            "output_desc": "",
            "feedback_channel": "_admin",
            "timeout_minutes": int(step_cfg.get("timeout_hours", 6) * 60),
            "escalation": step_cfg.get("escalation", "notify_pm"),
        }
    return {
        "round": round_name,
        "goal": "",
        "work_plan_url": work_plan_url,
        "requirements_url": requirements_url,
        "steps": steps,
    }



def _step_sort_key(step_name: str) -> tuple:
    """Sort step1, step2, ..., step10 naturally."""
    import re
    m = re.match(r'step(\d+)', step_name.lower())
    return (int(m.group(1)),) if m else (0, step_name)


# ── R69 A1 + R74 B2: Auto-infer artifact URL by step type ──

def _infer_artifact_url(step_name: str, round_name: str, step_config: dict | None = None) -> str:
    """Auto-infer artifact URL based on step type. Returns '' if unknown.

    R74 B2: 优先从 frontmatter step_config 读取 artifact_url，无配置时走硬编码回退（main 分支）。
    """
    # R74 B2: 优先读 frontmatter 的 artifact_url
    if step_config and step_name in step_config:
        art = step_config.get(step_name, {}).get("artifact_url", "")
        if art:
            return art

    # Fallback: hardcoded paths (main branch — R72/R73 already merged)
    step_urls = {
        "step2": f"https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/{round_name}/{round_name}-tech-plan.md",
        "step4": f"https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/{round_name}/{round_name}-review-report.md",
        "step5": f"https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/{round_name}/test-report.md",
    }
    return step_urls.get(step_name, "")


# lazy import moved inside _load_step_config to break circular import


def _load_step_config() -> dict[str, dict]:
    """Load step map from config."""
    from . import config as _r42cfg
    return _r42cfg.PIPELINE_STEP_MAP




def _get_step_config(round_name: str) -> dict[str, dict]:
    """Unified step config reader: prefer PipelineContext.steps, then frontmatter, then legacy fallback.

    R78 C3: 优先从 PipelineContext.steps 读取。
    """
    # R78 C3: 优先走 Manager
    try:
        mgr = _get_pipeline_manager()
        ctx_steps = mgr.get_step_config(round_name)
        if ctx_steps:
            return ctx_steps
    except Exception:
        pass
    pconfig = state._PIPELINE_CONFIG.get(round_name, {})
    psteps = pconfig.get("steps", {})
    if psteps:
        return psteps
    return _build_fallback_steps(round_name)



def _build_fallback_steps(round_name: str) -> dict[str, dict]:
    """Build fallback steps from PIPELINE_STEP_MAP, syncing primary/backup."""
    step_map = config.PIPELINE_STEP_MAP
    steps = {}
    for step_key, step_cfg in step_map.items():
        if step_key == "step1":
            continue
        steps[step_key] = {
            "role": step_cfg.get("role", ""),
            "title": step_cfg.get("name", step_key),
            "primary": step_cfg.get("primary"),
            "backup": step_cfg.get("backup"),
            "context": {
                "requirements_url": _get_requirements_url(round_name),
                "work_plan_url": _get_work_plan_url(round_name),
            },
            "output_desc": "",
            "feedback_channel": "_admin",
            "timeout_minutes": int(step_cfg.get("timeout_hours", 6) * 60),
            "escalation": step_cfg.get("escalation", "notify_pm"),
        }
    return steps



def _render_context(context: dict, round_name: str, step_outputs: dict) -> dict:
    """Resolve template variables like ${steps.stepN.sha} in context values."""
    resolved = {}
    for ctx_key, ctx_value in context.items():
        if not isinstance(ctx_value, str):
            resolved[ctx_key] = ctx_value
            continue
        value = ctx_value
        if "${steps." in value:
            for match in _find_template_refs(value, "${steps."):
                parts = match.split(".", 1)
                if len(parts) == 2:
                    step_key, field = parts
                    step_out = step_outputs.get(step_key, {})
                    replacement = str(step_out.get(field, ""))
                    value = value.replace("${steps." + match + "}", replacement)
        resolved[ctx_key] = value
    return resolved



def _find_template_refs(template_str: str, prefix: str) -> list[str]:
    """Extract all template variable references from a string."""
    refs = []
    start = 0
    while True:
        pos = template_str.find(prefix, start)
        if pos == -1:
            break
        end = template_str.find("}", pos)
        if end == -1:
            break
        ref = template_str[pos + len(prefix):end]
        refs.append(ref)
        start = end + 1
    return refs



def _set_pipeline_state(round_name: str, state: dict) -> None:
    state._PIPELINE_STATE[round_name] = state



def _update_pipeline_step(round_name: str, step: str) -> None:
    if round_name in state._PIPELINE_STATE:
        state._PIPELINE_STATE[round_name]["current_step"] = step



def _clear_pipeline_state(round_name: str) -> None:
    state._PIPELINE_STATE.pop(round_name, None)
    # R62: state._PIPELINE_CONFIG is NOT cleared here — config/state separation



def pipeline_is_active(round_name: str) -> bool:
    state = state._PIPELINE_STATE.get(round_name)
    return bool(state and state.get("active"))



def pipeline_exists(round_name: str) -> bool:
    """Check if pipeline exists (created but may or may not be active)."""
    return round_name in state._PIPELINE_STATE



def set_lobby_paused(paused: bool, round_name: str = "") -> None:
    state._LOBBY_PAUSED = paused
    state._LOBBY_PAUSED_ROUND = round_name if paused else ""
    logger.info("R42 lobby-pause: %s (round=%s)", paused, state._LOBBY_PAUSED_ROUND)


# ── R43: Watchdog helpers ──────────────────────────────────────────


WATCHDOG_SCAN_INTERVAL: int = 600       # 10 分钟（秒）
WATCHDOG_REALERT_INTERVAL: int = 1800   # 30 分钟（秒）

# 超时默认值（与 config.py STEP_TIMEOUT_DEFAULTS 保持一致）

