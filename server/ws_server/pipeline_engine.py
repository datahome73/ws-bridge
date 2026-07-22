# -*- coding: utf-8 -*-
"""R138: Unified pipeline engine — merged from engine2.py + pipeline_engine.py.

Contains all pipeline logic: ## commands, auto-dispatch, pipeline
advancement, PM notifications, template rendering, utility functions,
and the PipelineEngine class with lifecycle management.
"""
import asyncio
import json
import logging
import re
import time
import uuid
from typing import Optional, Callable, Awaitable, Any

from server.common import auth, config, persistence
from . import state
from . import message_store as ms
from . import task_store as ts
from . import workspace as ws_mod
from . import timeout_tracker
from . import pipeline_sync as pps
from . import agent_card as ac_mod
from .pipeline_context import (
    PipelineContext, PipelineContextManager,
    PipelineStatus, PipelineTaskKind,
)
from .connection_manager import _connections, _send, _send_to_agent
# PipelineEngine is defined in this file — no self-import

logger = logging.getLogger("ws-bridge.pipeline_engine")


# ── Extracted from main.py L221-341: async def _auto_advance_pipeline(round_name: str, result: dict) -> str: ──
async def _auto_advance_pipeline(round_name: str, result: dict) -> str:
    """Git sync 检测到新产出后自动推进状态机.

    Args:
        round_name: 管线标识
        result: PipelineGitSync.sync() 返回值

    Returns:
        广播消息文本.
    """
    pstate = state._PIPELINE_STATE.get(round_name)
    if not pstate:
        return ""

    step_config = _get_step_config(round_name)
    current_step = pstate.get("current_step", "")
    if not current_step:
        return ""

    # 获取当前 Step 在 step_config 中的索引
    step_keys = sorted(step_config.keys(), key=_step_sort_key)
    try:
        idx = step_keys.index(current_step)
    except ValueError:
        return ""

    if idx + 1 >= len(step_keys):
        return ""  # 已是最后一步

    next_step = step_keys[idx + 1]
    new_sha = result.get("new_sha", "")

    # 1. 状态机推进
    pstate["current_step"] = next_step
    pstate["last_output_sha"] = new_sha
    # 更新 Task state
    tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
    for t in tasks:
        if t.get("name") == current_step and t.get("state") != p.TaskState.COMPLETED.value:
            await _cmd_task_update("系统", {
                "_positional": [t["id"]],
                "state": p.TaskState.COMPLETED.value,
                "output": new_sha,
            })
        if t.get("name") == next_step and t.get("state") == p.TaskState.PENDING.value:
            await _cmd_task_update("系统", {
                "_positional": [t["id"]],
                "state": p.TaskState.WORKING.value,
            })

    # 2. 清理旧 ACK FAILED 标记
    old_ack_key = f"{round_name}/{current_step}"
    if old_ack_key in state._step_ack_states:
        if state._step_ack_states[old_ack_key].get("state") == "FAILED":
            state._step_ack_states.pop(old_ack_key, None)
            logger.info("[R65] 清除 %s 的 FAILED 标记（git sync 发现新产出）", old_ack_key)

    # 3. 广播自动同步消息
    ws_id = pstate.get("ws_id", "")
    commit_short = new_sha[:7] if new_sha else "?"
    mode = result.get("mode", "auto")
    mode_label = "" if mode == "default" else f"（{mode} 匹配）"

    msg = (
        f"💻 {round_name} {current_step} → {next_step} 已自动同步\n"
        f"  commit: {commit_short}{mode_label}\n"
        f"→ @{next_step} 到你了！"
    )

    if ws_id:
        pm_name = config.PIPELINE_PM_NAME
        _persist_broadcast(ws_id, pm_name, msg)
        payload = json.dumps({
            "type": "broadcast", "channel": ws_id,
            "from_name": pm_name, "from": pm_name,
            "content": msg, "ts": time.time(),
        })
        ws_obj = ws_mod.get_workspace(ws_id)
        if ws_obj:
            for member_id in ws_obj.members:
                for conn in list(_connections.get(member_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(payload)
                        elif hasattr(conn, "send"):
                            await conn.send(payload)
                    except Exception:
                        pass

    # 4. 点名下一角色（复用 R63 @role_name → @bot_name 机制）
    next_role = step_config[next_step].get("role", "")
    if next_role:
        cards = ac_mod.get_all_cards()
        ws_obj = ws_mod.get_workspace(ws_id) if ws_id else None
        if ws_obj and cards:
            matched = _find_agents_by_role(next_role, ws_obj.members, cards)
            users = auth.get_users()
            for aid in matched:
                name = users.get(aid, {}).get("name", aid[:12])
                mention = f"@{name} 🏗️ {round_name} {next_step} 到你了！"
                mention_payload = json.dumps({
                    "type": "broadcast", "channel": ws_id,
                    "from_name": pm_name, "from": pm_name,
                    "content": mention, "ts": time.time(),
                })
                for conn in list(_connections.get(aid, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(mention_payload)
                        elif hasattr(conn, "send"):
                            await conn.send(mention_payload)
                    except Exception:
                        pass

    # 5. 启动下一 Step timeout_tracker 倒计时
        timeout_min = step_config.get(next_step, {}).get("timeout_minutes", 20)
        timeout_tracker.start_timer(round_name, next_step, timeout_min)

    logger.info("[R65] 管线 %s 已自动推进：%s → %s (sha=%s)",
                round_name, current_step, next_step, commit_short)
    return msg


# ── Extracted from main.py L375-410: async def _verify_git_commit(commit_sha: str) -> tuple[bool, str]: ──
async def _verify_git_commit(commit_sha: str) -> tuple[bool, str]:
    """Check remote git dev branch for the given commit SHA via git ls-remote.
    Uses 10s timeout. On failure, degrades to a warning.
    Returns: (ok_to_proceed, message)
    """
    import subprocess
    repo_url = _r42cfg.GIT_REMOTE_URL
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "git", "ls-remote", repo_url, "refs/heads/dev",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ),
            timeout=10,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return True, (
                f"⚠️ git ls-remote 异常退出（{stderr.decode('utf-8', errors='replace')[:40]}），"
                f"已跳过验证，继续推进"
            )
        refs = stdout.decode("utf-8", errors="replace")
        if commit_sha in refs:
            return True, ""
        else:
            return False, (
                f"❌ Commit {commit_sha[:12]} 不存在于远程仓库 "
                f"（{repo_url}）的 dev 分支"
            )
    except asyncio.TimeoutError:
        return True, "⚠️ git ls-remote 超时（10s），已跳过验证，继续推进"
    except Exception as e:
        return True, f"⚠️ git 验证不可达（{str(e)[:40]}），已跳过验证，继续推进"


# ── R77: !pipeline command — unified pipeline context management ─────

# ── Extracted from main.py L414-485: def _format_pipeline_context(ctx: PipelineContext) -> str: ──
def _format_pipeline_context(ctx: PipelineContext) -> str:
    """格式化 PipelineContext 为人类可读文本.R78 D2: 增强版 ACK 展示."""
    from datetime import datetime
    lines = [
        f"📋 {ctx.round_name} [{ctx.task_kind.value}]",
        f"  状态: {ctx.status.value}",
        f"  Step: {ctx.current_step}/{ctx.total_steps}",
        f"  阶段: {ctx.current_phase}",
    ]
    # ── R106: Step-by-step status (role mapping) ──
    step_roles = ["pm", "arch", "dev", "review", "qa", "operations"]
    role_names = {"pm": "PM", "arch": "架构师", "dev": "开发",
                  "review": "审查", "qa": "测试", "operations": "运维"}
    step_parts = []
    for i in range(1, ctx.total_steps + 1):
        step_key = f"step{i}"
        role = step_roles[i - 1] if i - 1 < len(step_roles) else "?"
        role_name = role_names.get(role, role)
        # Determine status from current_step + ack_states
        ack = ctx.ack_states.get(step_key, {})
        ack_state = ack.get("state", "")
        if ack_state == "FAILED":
            icon = "❌"
            desc = "失败"
        elif ack_state == "ACKED" or i < ctx.current_step:
            icon = "✅"
            desc = "已完成"
        elif i == ctx.current_step:
            icon = "🔄"
            desc = "进行中"
        elif ack_state in ("SENT", "DELIVERED", "IN_PROGRESS"):
            icon = "🔄"
            desc = "进行中"
        else:
            icon = "⏳"
            desc = "待开始"
        step_parts.append(f"  Step{i} {icon} {role_name} → {desc}")
    if step_parts:
        lines.append("  步骤:")
        lines.extend(step_parts)
    # R78 D2: ACK 状态逐 step 展示（缩略版）
    ack_parts = []
    for i in range(1, ctx.total_steps + 1):
        step = f"step{i}"
        ack = ctx.ack_states.get(step, {})
        state = ack.get("state", "")
        role = ack.get("role_name", "")
        if state == "ACKED":
            ack_parts.append(f"step{i} ✅{role}")
        elif state == "PENDING":
            ack_parts.append(f"step{i} ⏳{role}")
        elif state == "FAILED":
            ack_parts.append(f"step{i} ❌{role}")
        elif state in ("SENT", "DELIVERED", "IN_PROGRESS", "ACKNOWLEDGED"):
            ack_parts.append(f"step{i} 🔄{role}")
        else:
            ack_parts.append(f"step{i} ⬜")
    lines.append(f"  ACK: {' | '.join(ack_parts)}")
    if ctx.blocked_reason:
        lines.append(f"  阻塞: {ctx.blocked_reason}")
    if ctx.role_agent_map:
        parts = []
        for role, agents in ctx.role_agent_map.items():
            agents_str = ",".join(a[:12] for a in agents)
            parts.append(f"{role}={agents_str}")
        lines.append(f"  成员: {'; '.join(parts)}")
    if ctx.workspace_id:
        lines.append(f"  工作室: {ctx.workspace_id}")
    if ctx.created_at:
        lines.append(f"  创建: {datetime.fromtimestamp(ctx.created_at).strftime('%m/%d %H:%M')}")
    return "\n".join(lines)



# ── Extracted from main.py L487-515: async def _restore_pipeline_timers() -> None: ──
async def _restore_pipeline_timers() -> None:
    """On server start, recover pipeline timeout timers from task store."""
    try:
        all_tasks = ts.list_tasks_by_context("", config.DATA_DIR)
        round_groups = {}
        for t in all_tasks:
            ctx = t.get("context", "")
            state = t.get("state", "")
            if ctx.startswith("R") and state not in ("completed", "cancelled"):
                if ctx not in round_groups:
                    round_groups[ctx] = []
                round_groups[ctx].append(t)
        for round_name, tasks in round_groups.items():
            if round_name in state._PIPELINE_STATE:
                continue
            tasks_sorted = sorted(tasks, key=lambda x: x.get("created_at", 0))
            current_step = tasks_sorted[0].get("name", "") if tasks_sorted else ""
            started_at = tasks_sorted[0].get("created_at", time.time())
            ws_id = "ws:" + round_name + "-dev"
            _set_pipeline_state(round_name, {
                "active": True,
                "current_step": current_step,
                "ws_id": ws_id,
                "started_at": started_at,
            })
            logger.info("R49 C restored timer: %s step=%s ws=%s", round_name, current_step, ws_id)
    except Exception:
        pass



# ── Extracted from main.py L520-545: async def _restore_pipeline_dispatches() -> None: ──
async def _restore_pipeline_dispatches() -> None:
    """On server start, re-dispatch the current step for all RUNNING pipelines
    whose current step is still pending.  Handles the case where a container
    restart lost the original auto-dispatch message."""
    try:
        mgr = _ensure_pipeline_manager()
        for ctx in mgr.get_all_active():
            if ctx.status != PipelineStatus.RUNNING:
                continue
            step_num = ctx.current_step
            if step_num < 1 or step_num > ctx.total_steps:
                continue
            step_key = f"step{step_num}"
            step_info = next(
                (s for s in (ctx.steps or []) if s.get("name") == step_key), None,
            )
            if not step_info or step_info.get("status") not in ("pending", "in_progress"):
                continue
            logger.info("[R119] 恢复派活: %s step%d → %s",
                        ctx.round_name, step_num,
                        step_info.get("agent_id", "?")[:20])
            _enqueue_retry(ctx, step_num)
            _enqueue_retry(ctx, step_num)
    except Exception:
        pass



# ── Extracted from main.py L651-674: def _extract_artifact_kv(content: str) -> dict[str, str]: ──
def _extract_artifact_kv(content: str) -> dict[str, str]:
    """从 '已完成 ✅ R{N} Step {N}##key=value##...' 中提取键值对。

    Args:
        content: 完整的完成消息文本

    Returns:
        提取的键值对 dict（不含 Step/round 信息）。
        无 ## 时返回空 dict。
    """
    if "##" not in content:
        return {}
    parts = content.split("##")
    result: dict[str, str] = {}
    for p in parts[1:]:  # parts[0] 是前缀段，跳过
        if "=" in p:
            key, value = p.split("=", 1)  # 仅第一个 = 做分隔
            key = key.strip()
            if key:
                result[key] = value
        else:
            logger.debug("[R115] 忽略不含 '=' 的 ## 段: %s", p[:50])
    return result



# ═══ R142: 容错完成消息匹配 ═══
def _try_extract_step_completion(content: str) -> tuple[Optional[int], Optional[int], dict]:
    """多模式容错匹配完成消息，提取 R{N}、Step {N} 和 ##key=value 参数。"""
    patterns = [
        r"已完成\s*✅?\s*R(\d+)\s*Step\s*(\d+)",
        r"✅\s*完成.*?R(\d+).*?Step\s*(\d+)",
        r"R(\d+)\s*Step\s*(\d+).*?(?:完成|已推|done)",
        r"已完成.*?R(\d+).*?Step\s*(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            round_num = int(m.group(1))
            step_num = int(m.group(2))
            kv = _extract_artifact_kv(content)
            return round_num, step_num, kv
    return None, None, {}

# ═══ R142: 完成消息格式提示 ═══
async def _send_format_hint(agent_id: str) -> None:
    """向 bot 发送完成消息格式提示。"""
    await _send_to_agent(agent_id, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": (
            "❌ 完成消息格式不识别。请使用以下格式之一：\n"
            "  ✅ 已完成 ✅ R142 Step 3##sha=xxx\n"
            "  ✅ ✅ 完成，R142 Step 3 已推 dev"
        ),
        "ts": time.time(),
    })
# ═══════════════════════════════

# ── Extracted from main.py L679-792: def _try_advance_pipeline(content: str, agent_id: str) -> tuple[bool, str]: ──
def _try_advance_pipeline(content: str, agent_id: str) -> tuple[bool, str]:
    """Parse 已完成 ✅ R{N} Step {N} and auto-advance pipeline context.

    Returns:
        (True, "round_name") on success, (False, reason) on skip.
    """
    _rn, _sn, _kv_comp = _try_extract_step_completion(content)
    if _rn is None:
        # ═══ R142: 格式提示（F-7）═══
        _lower = content.lower()
        if any(kw in _lower for kw in ("完成", "done", "推", "push", "merge", "deploy")):
            asyncio.ensure_future(_send_format_hint(agent_id))
        # ══════════════════════════
        return False, "no match"
    round_name = f"R{_rn}"
    completed_step = _sn
    try:
        mgr = _ensure_pipeline_manager()
        ctx = mgr.get(round_name)
        if not ctx:
            logger.info("[R106] 管线 %s 无上下文，跳过自动推进", round_name)
            return False, "no context"
        old_step = ctx.current_step
        # Only advance if completed_step matches current_step
        if completed_step == old_step:
            # ═══ R142: 使用 _try_extract_step_completion 返回的 kv ═══
            _kv = _kv_comp
            if _kv:
                _step_key = f"step{completed_step}"
                if not hasattr(ctx, 'artifacts') or not ctx.artifacts:
                    ctx.artifacts = {}
                ctx.artifacts[_step_key] = _kv
                try:
                    mgr.save()
                except Exception:
                    pass
                logger.info("[R115] %s step%d artifacts: %s", round_name, completed_step, _kv)
            # ═══ R123: advance 前记录 step output + result_msg ═══
            _step_idx = completed_step - 1
            _step_info = ctx.steps[_step_idx] if _step_idx < len(ctx.steps) else None
            if _step_info:
                _output = {}
                if _kv:
                    for _k in ("sha", "commit_msg", "tech_plan_url", "branch_name",
                                "test_scope", "test_report_url", "test_summary",
                                "review_url"):
                        if _k in _kv:
                            _output[_k] = _kv[_k]
                _step_info["output"] = _output if _output else None
                _step_info["result_msg"] = content[:200]
                _step_info["status"] = "done"
                _step_info["completed_at"] = time.time()  # ═══ R142: 记录完成时间 ═══
                try:
                    mgr.save()
                except Exception:
                    pass
            # ═══ R124: Step 产出基本验证（SHA 格式 + 可选远程 git）═══
            if _kv:
                _step_v = _step_info if _step_info else None
                if _step_v:
                    _out_v = _step_v.get("output")
                    if not isinstance(_out_v, dict):
                        _out_v = {}
                    _sha_v = _kv.get("sha", "")
                    if _sha_v:
                        import re as _re_sha124
                        if _re_sha124.match(r"^[0-9a-f]{7,40}$", _sha_v):
                            _out_v["sha_validation"] = "valid_format"
                        else:
                            _out_v["sha_validation"] = "invalid_format"
                        _step_v["output"] = _out_v if _out_v else None
                        try:
                            mgr.save()
                        except Exception:
                            pass
                    # 远程 git 验证（可选、异步、不阻塞）
                    if (config.PIPELINE_OUTPUT_VERIFICATION and _sha_v
                            and _out_v.get("sha_validation") == "valid_format"):
                        asyncio.ensure_future(
                            _verify_sha_remote(round_name, completed_step, _sha_v)
                        )
            # ════════════════════════════════════════════════════════════════
            asyncio.ensure_future(mgr.advance_step(round_name))
            logger.info(
                "[R106] %s Step %d → %d (auto-advance from completion)",
                round_name, old_step, old_step + 1,
            )
            # ── R107: 自动派活下一步（受 AUTO_DISPATCH_ENABLED 控制）──
            next_step = old_step + 1
            if next_step <= ctx.total_steps:
                logger.info(
                    "[R117] %s Step %d 已完成，尝试自动派活 Step %d",
                    round_name, old_step, next_step,
                )
                asyncio.ensure_future(_auto_dispatch_with_notify(ctx, next_step, agent_id))
            else:
                # 最后一步已完成，标记管线 completed
                asyncio.ensure_future(mgr.transition_to(round_name, PipelineStatus.COMPLETED))
                logger.info("[R107] %s 全管线已完成 ✅", round_name)
                asyncio.ensure_future(_notify_pm(ctx, ctx.total_steps, "completed"))
                # ═══ R124: 自动归档 ═══
                asyncio.ensure_future(_archive_pipeline(round_name))
                # ═══════════════════════
            return True, round_name
        elif completed_step < old_step:
            logger.info(
                "[R106] %s Step %d already past completed Step %d (skip)",
                round_name, old_step, completed_step,
            )
            return False, "already past"
        else:
            logger.info(
                "[R106] %s Step %d > current %d (gap, skip)",
                round_name, completed_step, old_step,
            )
            return False, "future step"
    except Exception as e:
        logger.warning("[R106] 自动推进异常: %s", e)
        return False, f"error: {e}"



# ── Extracted from main.py L797-871: async def _notify_pm(ctx: PipelineContext, step_num: int, status: str, detail: str = "") -> None: ──
async def _notify_pm(ctx: PipelineContext, step_num: int, status: str, detail: str = "") -> None:
    """发送管线通知给 PM。
    status: 'dispatched' | 'completed' | 'failed' | 'retrying'
    """
    pm_id = config.PIPELINE_PM_AGENT_ID
    role_names = {1: "📋 PM", 2: "📐 Arch", 3: "💻 Dev", 4: "👁 Review", 5: "🧪 QA", 6: "🚢 Ops"}
    step_role = role_names.get(step_num, "?")

    if status == "dispatched":
        agent_name = _get_step_agent_name(ctx, step_num)
        content = (
            f"✅ **{ctx.round_name} 管线自动推进**\n\n"
            f"Step {step_num} 🚀 已派活 → {agent_name}（{step_role}）\n"
            + (f"\n{detail}" if detail else "")
        )
    elif status == "completed":
        # 构造完成摘要
        step_lines = []
        for i, s in enumerate(ctx.steps, 1):
            role = role_names.get(i, "?")
            agent = s.get("agent_name", s.get("agent_id", "?")[:12])
            out = s.get("output") or {}
            if isinstance(out, dict):
                sha = out.get("sha", "")
                out_short = f"sha={sha[:12]}" if sha else "-"
            else:
                out_short = str(out)[:40]
            step_lines.append(f"| {i} | {role} | {agent} | {out_short} |")
        table_header = "| Step | 角色 | 执行者 | 产出 |\n|:---:|:-----|:-------|:-----|\n"
        content = (
            f"🎉 **{ctx.round_name} 管线已完成！**\n\n"
            f"{table_header}{chr(10).join(step_lines)}"
        )
    elif status == "failed":
        agent_name = _get_step_agent_name(ctx, step_num)
        content = (
            f"⚠️ **{ctx.round_name} 管线异常**\n\n"
            f"Step {step_num}（{step_role}）→ {agent_name} 离线，"
            f"自动派活失败（5 次重试）\n"
            + (f"\n{detail}" if detail else "")
        )
    elif status == "retrying":
        agent_name = _get_step_agent_name(ctx, step_num)
        content = (
            f"⏳ **{ctx.round_name} 派活排队中**\n\n"
            f"Step {step_num}（{step_role}）→ {agent_name} 离线，排队中（{detail}）"
        )
    # ═══ R124: 驳回/卡死通知 ═══
    elif status == "rejected":
        content = (
            f"⚠️ **{ctx.round_name} 管线回退**\n\n"
            f"Step {step_num}（{step_role}）被退回\n"
            + (f"{detail}" if detail else "")
        )
    elif status == "stuck":
        content = (
            f"🔴 **{ctx.round_name} 管线已卡死**\n\n"
            + (f"{detail}" if detail else "")
        )
    elif status == "archived":
        content = (
            f"📦 **{ctx.round_name} 管线已完成并归档**\n\n"
            + (f"{detail}" if detail else "")
        )
    # ═══════════════════════════════════════════════════
    else:
        return

    payload = {
        "type": "broadcast",
        "channel": f"_inbox:{pm_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": content,
        "ts": time.time(),
    }
    sent = await _send_to_agent(pm_id, payload)
    logger.info("[R118] 通知 PM step%d status=%s sent=%d", step_num, status, sent)



# ── Extracted from main.py L875-925: _pending_retries: dict[str, dict] = {}  # round_name → {ctx, step_num, retry_count, next_retry_at, notify_sent} ──
_pending_retries: dict[str, dict] = {}  # round_name → {ctx, step_num, retry_count, next_retry_at, notify_sent}

async def _retry_loop() -> None:
    """后台循环，每 30s 扫描待重试队列。最多重试 5 次，每次间隔 60s。"""
    while True:
        now = time.time()
        for round_name in list(_pending_retries.keys()):
            entry = _pending_retries[round_name]
            if now < entry["next_retry_at"]:
                continue
            ctx = entry["ctx"]
            step_num = entry["step_num"]
            entry["retry_count"] += 1
            logger.info("[R118] 重试派活 %s step%d (尝试 %d/5)",
                        round_name, step_num, entry["retry_count"])
            result = await _auto_dispatch(ctx, step_num)
            if result:
                del _pending_retries[round_name]
                logger.info("[R118] 重试成功: %s step%d", round_name, step_num)
            elif entry["retry_count"] >= 5:
                del _pending_retries[round_name]
                asyncio.ensure_future(
                    _notify_pm(ctx, step_num, "failed",
                               f"5 次重试均失败，目标 bot 持续离线"))
                logger.warning("[R118] 重试耗尽: %s step%d 5/5 失败", round_name, step_num)
            else:
                entry["next_retry_at"] = time.time() + 60
                if not entry.get("notify_sent"):
                    entry["notify_sent"] = True
                    asyncio.ensure_future(
                        _notify_pm(ctx, step_num, "retrying",
                                   f"尝试 {entry['retry_count']+1}/5"))
                logger.info("[R118] 重试排队: %s step%d 等待 60s",
                            round_name, step_num)
        await asyncio.sleep(30)


def _enqueue_retry(ctx: PipelineContext, step_num: int) -> None:
    """将失败的自动派活加入重试队列。"""
    round_name = ctx.round_name
    if round_name in _pending_retries:
        return  # 已在队列中
    _pending_retries[round_name] = {
        "ctx": ctx,
        "step_num": step_num,
        "retry_count": 0,
        "next_retry_at": time.time() + 60,
        "notify_sent": False,
    }
    logger.info("[R118] 入重试队列: %s step%d", round_name, step_num)



# ── Extracted from main.py L930-998: def _render_template(template: str, ctx: PipelineContext, step_num: int) -> str: ──
def _render_template(template: str, ctx: PipelineContext, step_num: int) -> str:
    """用 Pipeline Context 数据渲染模板字符串。

    变量来源优先级（高→低）:
    1. ctx.artifacts 中各 step 的产出 KV
    2. ctx.references 中的文档 URL
    3. ctx 基本信息 (round_name, round_title)

    R123 新增 {stepN:field} 变量语法，解析优先级:
    1. ctx.artifacts["step{N}"].get(field)
    2. ctx.steps[idx].output.get(field)   (当 output 是 dict 时)
    3. ctx.steps[idx].get(field)           (agent_name, result_msg 等)
    4. ctx.references.get(field)
    5. 空字符串
    """
    # ═══ R123: 先解析 {stepN:field} 占位符 ═══
    _step_placeholder_re = re.compile(r"\{step(\d+):(\w+)\}")

    def _resolve_step_var(m: re.Match) -> str:
        _sn = int(m.group(1))
        _field = m.group(2)
        _sk = f"step{_sn}"
        _idx = _sn - 1
        # 1. ctx.artifacts["step{N}"].get(field)
        _art = ctx.artifacts.get(_sk, {})
        if isinstance(_art, dict) and _field in _art:
            val = str(_art[_field])
            return val if val else ""
        # 2. ctx.steps[idx].output.get(field)
        if _idx < len(ctx.steps):
            _step = ctx.steps[_idx]
            if isinstance(_step, dict):
                _out = _step.get("output")
                if isinstance(_out, dict) and _field in _out:
                    val = str(_out[_field])
                    return val if val else ""
                # 3. ctx.steps[idx].get(field)
                if _field in _step:
                    val = str(_step[_field])
                    return val if val else ""
        # 4. ctx.references.get(field)
        if isinstance(ctx.references, dict) and _field in ctx.references:
            val = str(ctx.references[_field])
            return val if val else ""
        # 5. 空字符串
        return ""

    template = _step_placeholder_re.sub(_resolve_step_var, template)
    # ════════════════════════════════════════════════════════════════

    vars = {
        "round": ctx.round_name,
        "round_title": ctx.round_title,
        "requirements_url": ctx.references.get("requirements_url", ""),
        "work_plan_url": ctx.references.get("work_plan_url", ""),
    }
    # 补充来自 artifacts 的变量（覆盖同名变量）
    for step_key, step_artifacts in ctx.artifacts.items():
        if isinstance(step_artifacts, dict):
            vars.update(step_artifacts)
    # 填充模板中的 {var} 占位符
    for key, value in vars.items():
        template = template.replace(f"{{{key}}}", str(value))
    # ═══ R123: 清理空值字段行（##key## \n 残留）═══
    template = re.sub(r"^##\w+##\s*\n", "", template, flags=re.MULTILINE)
    template = template.strip()
    # ══════════════════════════════════════════════════
    return template



# ── Extracted from main.py L1000-1007: def _get_step_agent_name(ctx: PipelineContext, step_num: int) -> str: ──
def _get_step_agent_name(ctx: PipelineContext, step_num: int) -> str:
    """辅助函数：获取指定 step 的 agent 名称。"""
    step_key = f"step{step_num}"
    info = next((s for s in ctx.steps if s.get("name") == step_key), None)
    if info:
        return info.get("agent_name", info.get("agent_id", "?"))
    return "?"



# ── Extracted from main.py L1009-1017: # ═══ R123: 前置步骤摘要生成 ═══ ──
# ═══ R123: 前置步骤摘要生成 ═══
_ROLE_EMOJIS = {1: "📋", 2: "📐", 3: "💻", 4: "👁", 5: "🧪", 6: "🚢"}
_ROLE_NAMES = {1: "PM", 2: "Arch", 3: "Dev", 4: "Review", 5: "QA", 6: "Ops"}
_URL_FIELDS = {
    "tech_plan_url": "技术方案", "review_url": "审查报告",
    "test_report_url": "测试报告", "test_summary": "测试结果",
    "requirements_url": "需求文档", "work_plan_url": "工作计划",
}



# ── Extracted from main.py L1019-1048: def _build_step_summary(ctx: PipelineContext, step_num: int) -> str: ──
def _build_step_summary(ctx: PipelineContext, step_num: int) -> str:
    """为 step_num 构建前序步骤完成摘要。仅显示已完成（status=done）的前置 step。"""
    lines = ["══════ 前置步骤状态 ══════"]
    has_prev = False
    for i, s in enumerate(ctx.steps, 1):
        if i >= step_num:
            break
        if s.get("status") != "done":
            continue
        has_prev = True
        emoji = _ROLE_EMOJIS.get(i, "?")
        rname = _ROLE_NAMES.get(i, "?")
        agent = s.get("agent_name", s.get("agent_id", "?")[:12])
        lines.append(f"\nStep {i} {emoji} {rname}（{agent}）✅")
        output = s.get("output")
        if isinstance(output, dict):
            sha = output.get("sha", "")
            if sha:
                lines.append(f"  提交: `{sha}` — {output.get('commit_msg', '')}")
            for k, label in _URL_FIELDS.items():
                if output.get(k):
                    lines.append(f"  产出: [{label}]({output[k]})")
        result_msg = s.get("result_msg", "")
        if result_msg:
            lines.append(f"  结果: {result_msg[:80]}")
    if not has_prev:
        return ""
    lines.append("\n════════════════════\n")
    return "\n".join(lines)
# ════════════════════════════════════════════════════════════════


# ── Extracted from main.py L1053-1067: def _find_archive(round_name: str) -> dict | None: ──
def _find_archive(round_name: str) -> dict | None:
    """从 pipeline_archive.json 查找已归档轮次。"""
    from pathlib import Path
    archive_path = Path(config.DATA_DIR) / "pipeline_archive.json"
    if not archive_path.exists():
        return None
    try:
        records = json.loads(archive_path.read_text(encoding="utf-8"))
        for rec in records:
            if rec.get("round_name") == round_name:
                return rec
    except (OSError, json.JSONDecodeError):
        pass
    return None



# ── Extracted from main.py L1069-1075: def _fmt_ts(ts: float) -> str: ──
def _fmt_ts(ts: float) -> str:
    """格式化时间戳。"""
    if not ts:
        return "?"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except (ValueError, OSError):
        return str(ts)

# ── Extracted from main.py L1080-1121: async def _verify_sha_remote(round_name: str, step_num: int, sha: str) -> None: ──
async def _verify_sha_remote(round_name: str, step_num: int, sha: str) -> None:
    """异步验证 SHA 在远程 dev 分支的存在性。不阻断管线推进。"""
    try:
        mgr = _ensure_pipeline_manager()
        ctx = mgr.get(round_name)
        if not ctx:
            return
        _step = ctx.steps[step_num - 1] if step_num - 1 < len(ctx.steps) else None
        if not _step:
            return
        _output = _step.get("output") or {}
        if not isinstance(_output, dict):
            _output = {}
        async with asyncio.timeout(5):
            proc = await asyncio.create_subprocess_exec(
                "git", "ls-remote", "origin", "dev",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if sha in stdout.decode("utf-8", errors="replace"):
                _output["sha_validation"] = "verified"
            else:
                _output["sha_validation"] = "not_found"
                _step["output"] = _output
                mgr.save()
                return
            proc2 = await asyncio.create_subprocess_exec(
                "git", "log", "--oneline", sha, "-1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout2, _ = await proc2.communicate()
            _msg = stdout2.decode("utf-8", errors="replace")
            _output["commit_round_match"] = "matched" if round_name in _msg else "mismatched"
        _step["output"] = _output
        mgr.save()
    except asyncio.TimeoutError:
        if ctx and _step:
            _step["output"]["sha_validation"] = "unchecked"
            mgr.save()
    except Exception as e:
        logger.warning("[R124] SHA 验证异常: %s", e)



# ── Extracted from main.py L1123-1162: async def _auto_re_notify(ctx, step_key: str, step_num: int) -> None: ──
async def _auto_re_notify(ctx, step_key: str, step_num: int) -> None:
    """超时后重新发送派活消息给原 bot。"""
    step_idx = step_num - 1
    if step_idx < 0 or step_idx >= len(ctx.steps):
        return
    step_info = ctx.steps[step_idx]
    target_agent_id = step_info.get("agent_id", "")
    if not target_agent_id:
        return
    tmpl = ctx.message_templates.get(step_key)
    if tmpl:
        content = _render_template(tmpl, ctx, step_num)
    else:
        content = f"📋 {ctx.round_name} Step {step_num} — {step_info.get('role', '?')}，请继续完成"
    # 头部加重发标记
    content = f"🔄 消息重发 — {content}"
    payload = {
        "type": "broadcast",
        "channel": f"_inbox:{target_agent_id}",
        "content": content,
        "from_name": "小谷",
        "agent_id": "ws_f26e585f6479",
        "id": f"retry-{ctx.round_name}-step{step_num}-{int(time.time() * 1000)}",
        "ts": time.time(),
    }
    sent = await _send_to_agent(target_agent_id, payload)
    pm_id = config.PIPELINE_PM_AGENT_ID
    if pm_id:
        agent_name = step_info.get("agent_name", target_agent_id[:12])
        await _send_to_agent(pm_id, {
            "type": "broadcast",
            "channel": f"_inbox:{pm_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"🔄 {ctx.round_name} Step {step_key} 超时，已重新发送派活消息给 {agent_name}",
            "ts": time.time(),
        })
    logger.info("[R124] 超时重发: %s Step %s → %s (sent=%d)",
                ctx.round_name, step_key, target_agent_id[:12], sent if sent else 0)
# ═══════════════════════════════════════════════════════════


# ── Extracted from main.py L1165-1278: async def _auto_dispatch(ctx: PipelineContext, step_num: int) -> bool: ──
async def _auto_dispatch(ctx: PipelineContext, step_num: int,
                        notify_ws=None, notify_agent_id: Optional[str] = None) -> bool:
    """自动派活下一步。受 AUTO_DISPATCH_ENABLED 开关控制。

    R140 A-4/A-5: 派活失败时通过 notify_ws 或 notify_agent_id 通知发起者。
    """
    if not config.AUTO_DISPATCH_ENABLED:
        logger.info(
            "[R107] 自动派活已关闭，跳过 step%d 发送 (round=%s)",
            step_num, ctx.round_name,
        )
        # 模拟：仅打印渲染结果，不实际发送
        next_step_key = f"step{step_num}"
        next_template = ctx.message_templates.get(next_step_key, "")
        if next_template:
            rendered = _render_template(next_template, ctx, step_num)
            logger.info(
                "[R107] [模拟] 将派活 step%d 给 %s:\n%s",
                step_num,
                _get_step_agent_name(ctx, step_num),
                rendered,
            )
        # ═══ R140 A-4: 通知发起者 ═══
        await _send_dispatch_notify(notify_ws, notify_agent_id,
            f"⚠️ {ctx.round_name} Step {step_num} 派活失败：自动派活已禁用")
        return False

    # ← 实际发送逻辑（开关打开后才执行）
    next_step_key = f"step{step_num}"
    next_template = ctx.message_templates.get(next_step_key)
    if not next_template:
        logger.warning(
            "[R107] 管线 %s 缺少 step%d 模板，跳过自动派活",
            ctx.round_name, step_num,
        )
        # ═══ R140 A-5: 模板缺失通知 ═══
        await _send_dispatch_notify(notify_ws, notify_agent_id,
            f"⚠️ {ctx.round_name} Step {step_num} 派活失败：派活模板缺失（{_get_step_agent_name(ctx, step_num)}）")
        return False

    next_step_info = next(
        (s for s in (ctx.steps or []) if s.get("name") == next_step_key), None,
    )
    if not next_step_info or not next_step_info.get("agent_id"):
        logger.warning(
            "[R107] 管线 %s step%d 无 agent_id，跳过自动派活",
            ctx.round_name, step_num,
        )
        # ═══ R140 A-5: 通知发起者 ═══
        await _send_dispatch_notify(notify_ws, notify_agent_id,
            f"⚠️ {ctx.round_name} Step {step_num} 派活失败：未找到目标 agent（{_get_step_agent_name(ctx, step_num)}）")
        return False

    target_agent_id = next_step_info["agent_id"]

    # ═══ R117 fix: card key → WS ID fallback ═══
    if not target_agent_id.startswith("ws_"):
        _fallback_id = _resolve_card_key_to_ws_id(target_agent_id)
        if _fallback_id:
            logger.info("[R117] card key %s → WS ID %s (fallback)",
                        target_agent_id, _fallback_id)
            target_agent_id = _fallback_id
            next_step_info["agent_id"] = _fallback_id
        else:
            logger.warning(
                "[R117] 无法解析 card key %s 为 WS ID，跳过自动派活 step %d of %s",
                target_agent_id, step_num, ctx.round_name,
            )
            # ═══ R140 A-5: 通知发起者 ═══
            await _send_dispatch_notify(notify_ws, notify_agent_id,
                f"⚠️ {ctx.round_name} Step {step_num} 派活失败：无法解析 agent ID")
            return False

    content = _render_template(next_template, ctx, step_num)

    # ═══ R123: Step ≥ 3 时前置步骤摘要注入 ═══
    if step_num >= 3:
        _summary = _build_step_summary(ctx, step_num)
        if _summary:
            content = _summary + "\n" + content
    # ══════════════════════════════════════════════════════

    payload = {
        "type": "broadcast",
        "channel": f"_inbox:{target_agent_id}",
        "content": content,
        "from_name": "系统",
        "agent_id": state.SYSTEM_AGENT_ID,
        "to_agent": target_agent_id,
        "id": f"auto-{ctx.round_name}-step{step_num}-{int(time.time() * 1000)}",
        "ts": time.time(),
    }

    # ── R109 修复: 派活消息落库 ──
    try:
        ms.save_message(
            msg_id=payload["id"],
            msg_type="broadcast",
            from_agent=payload["agent_id"],
            from_name=payload["from_name"],
            content=content,
            ts=payload["ts"],
            data_dir=config.DATA_DIR,
            channel=f"_inbox:{target_agent_id}",
        )
    except Exception:
        pass  # 入库失败不阻塞派活

    sent = await _send_to_agent(target_agent_id, payload)
    logger.info("[R109] 自动派活 step%d → %s (%s): sent=%d",
                step_num, target_agent_id,
                next_step_info.get("agent_name", "?"), sent)
    # R118: 派活成功后通知 PM
    if sent > 0:
        # 标记 step 为进行中，防止重复派活
        next_step_info["status"] = "in_progress"
        # ═══ R122: 记录派活时间戳，供超时扫描 ═══
        next_step_info["dispatched_at"] = time.time()
        next_step_info["timeout_alerted"] = False
        try:
            mgr = _ensure_pipeline_manager()
            mgr.save()
        except Exception:
            pass
        asyncio.ensure_future(_notify_pm(ctx, step_num, "dispatched"))
    else:
        # R118: 离线重试
        _enqueue_retry(ctx, step_num)
        # ═══ R140 A-5: 离线通知 ═══
        await _send_dispatch_notify(notify_ws, notify_agent_id,
            f"⚠️ {ctx.round_name} Step {step_num} 派活失败：{next_step_info.get('agent_name', '?')} 离线，已加入重试队列")
    return sent > 0


# ── R140: 派活失败通知 ──


async def _send_dispatch_notify(notify_ws, notify_agent_id: Optional[str], msg: str) -> None:
    """Helper: send dispatch failure notification via WS or agent inbox."""
    if notify_ws:
        try:
            await _send(notify_ws, {
                "type": "broadcast",
                "channel": f"_inbox:{notify_agent_id or 'system'}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": msg,
                "ts": time.time(),
            })
        except Exception:
            pass
    elif notify_agent_id:
        try:
            await _send_to_agent(notify_agent_id, {
                "type": "broadcast",
                "channel": f"_inbox:{notify_agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": msg,
                "ts": time.time(),
            })
        except Exception:
            pass


async def _auto_dispatch_with_notify(ctx: PipelineContext, step_num: int,
                                     agent_id: str) -> None:
    """Wrap auto_dispatch with notification to agent on failure (R140 A-8)."""
    ok = await _auto_dispatch(ctx, step_num, notify_agent_id=agent_id)
    if ok:
        logger.info("[R140] %s step%d 派活成功 → %s",
                    ctx.round_name, step_num, agent_id[:12])
    else:
        logger.info("[R140] %s step%d 派活失败，已通知 %s",
                    ctx.round_name, step_num, agent_id[:12])



# ── Extracted from main.py L1282-1357: async def _handle_reject(content: str, sender_agent_id: str) -> None: ──
async def _handle_reject(content: str, sender_agent_id: str) -> None:
    """处理退回 🔄 R{N} Step {N} — 原因 消息。
    管线状态回退 + 通知 PM，不自动重新派活。
    异步后台执行（不阻塞 relay 返回）。
    """
    m = re.match(r"退回 🔄 (R\d+) Step (\d+)", content)
    if not m:
        logger.info("[R124] 退回消息格式不匹配: %s...", content[:60])
        return
    round_name = m.group(1)
    rejected_step = int(m.group(2))

    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        logger.info("[R124] 退回: 管线 %s 不存在，忽略", round_name)
        return

    # 已完成/已归档/已取消/已卡死 → 忽略
    from .pipeline_context import PipelineStatus as PS
    if ctx.status in (PS.COMPLETED, "cancelled", "stopped", "stuck"):
        logger.info("[R124] 退回: %s 状态=%s，忽略", round_name, ctx.status)
        return

    # 提取退回原因：支持全角 —、半角 --、-
    reject_reason = ""
    for sep in ("—", "--", "-"):
        if sep in content:
            reject_reason = content.split(sep, 1)[1].strip()[:200]
            break
    if not reject_reason:
        reject_reason = content[:100]

    # 轮次级退回计数检查（第 4 次 stuck）
    reject_count = getattr(ctx, "reject_count", 0) + 1
    ctx.reject_count = reject_count
    if reject_count >= 4:
        ctx.status = "stuck"
        mgr.save()
        logger.info("[R124] %s 第 4 次退回，标记 stuck", round_name)
        await _notify_pm(
            ctx, rejected_step, "stuck",
            f"🔴 {round_name} Step {rejected_step} 被退回。管线已卡死"
            f"（累计退回 {reject_count} 次），需要人工介入。\n原因: {reject_reason}",
        )
        return

    # 确定回退起点 index：Step 1/2 → index 0，Step 3+ → index 2
    rollback_start = 1 if rejected_step <= 2 else 2

    # 重置 affected steps
    for i in range(rollback_start, len(ctx.steps)):
        ctx.steps[i]["status"] = "pending"
        ctx.steps[i]["output"] = None
        ctx.steps[i]["result_msg"] = ""
        ctx.steps[i].pop("reject_reason", None)

    # 记录退回原因到回退目标 step
    ctx.steps[rollback_start]["reject_reason"] = reject_reason

    # 回退管线 current_step（1-indexed）
    ctx.current_step = rollback_start + 1

    # 持久化 + 通知 PM
    mgr.save()
    await _notify_pm(
        ctx, rejected_step, "rejected",
        f"🔄 {round_name} Step {rejected_step} 被退回（累计 {reject_count}/3）\n"
        f"原因: {reject_reason}\n"
        f"管线已退回到 Step {rollback_start + 1}（编码环节），未自动派活。\n"
        f"请 PM 决定下一步：派活 Dev 重做 or ##advance 跳过。",
    )
    logger.info("[R124] 退回处理完成: %s Step %d → rollback_to Step %d, reason=%s",
                round_name, rejected_step, rollback_start + 1, reject_reason)
# ════════════════════════════════════════════════════════════════════════════



# ── Extracted from main.py L1364-1372: def _build_name_to_ws_map() -> dict[str, str]: ──
def _build_name_to_ws_map() -> dict[str, str]:
    """从 persistence.get_api_keys() 构建 display_name → ws_agent_id 映射."""
    _name_to_ws: dict[str, str] = {}
    for _aid, _rec in persistence.get_api_keys().items():
        _dn = _rec.get("display_name", "")
        if _dn:
            _name_to_ws[_dn] = _aid
    return _name_to_ws



# ── Extracted from main.py L1374-1409: def _resolve_card_key_to_ws_id(card_key: str) -> str: ──
def _resolve_card_key_to_ws_id(card_key: str) -> str:
    """多策略解析 card key → WS 连接 ID。

    优先级:
    1. display_name → api_keys (persistence.get_api_keys())
    2. display_name → state._r72_users name 匹配
    3. _connections + _r72_users name 交叉匹配
    """
    card = ac_mod.get_agent_card(card_key)
    if not card:
        return ""
    display_name = card.get("display_name", "")

    # 策略 1: display_name → api_keys
    if display_name:
        name_to_ws = _build_name_to_ws_map()
        _id = name_to_ws.get(display_name, "")
        if _id and _id.startswith("ws_"):
            return _id

    # 策略 2: display_name → state._r72_users
    if display_name:
        for _aid, _rec in state._r72_users.items():
            if _rec.get("name", "") == display_name:
                return _aid

    # 策略 3: _connections 中 ws_xxx → _r72_users name 匹配
    if display_name:
        for _aid in list(_connections.keys()):
            if _aid.startswith("ws_"):
                _info = state._r72_users.get(_aid, {})
                if _info.get("name", "") == display_name:
                    return _aid

    return ""



# ── Extracted from main.py L1411-1453: def _build_rich_templates(round_name: str, references: dict = None, artifacts: dict = None) -> dict[str, str]: ──
def _build_rich_templates(round_name: str, references: dict = None, artifacts: dict = None) -> dict[str, str]:
    """返回 6 步富上下文模板组，引用 references（文档 URL）和 artifacts（前序步产出）."""
    ref = references or {}
    req_url = ref.get("requirements_url", "")
    wp_url = ref.get("work_plan_url", "")

    return {
        "step1": "",
        "step2": (
            f"📋 **{round_name} Step 2 — 技术方案**\n\n"
            + (f"##需求文档## {req_url}\n" if req_url else "")
            + (f"##工作计划## {wp_url}\n" if wp_url else "")
            + "\n请完成技术方案并推 dev，回复：已完成 ✅ {round} Step 2"
        ),
        "step3": (
            f"💻 **{round_name} Step 3 — 编码实现**\n\n"
            + (f"##需求文档## {req_url}\n" if req_url else "")
            + "##技术方案## {step2:tech_plan_url}\n"
            + "\n请完成编码并推 dev，回复：已完成 ✅ {round} Step 3"
        ),
        "step4": (
            f"👁 **{round_name} Step 4 — 代码审查**\n\n"
            + (f"##需求文档## {req_url}\n" if req_url else "")
            + "##技术方案## {step2:tech_plan_url}\n"
            + "\n请审查代码并回复审查报告，回复：已完成 ✅ {round} Step 4"
        ),
        "step5": (
            f"🧪 **{round_name} Step 5 — 测试验证**\n\n"
            + (f"##需求文档## {req_url}\n" if req_url else "")
            + "##测试范围## {step3:test_scope}\n"
            + "##分支## {step3:branch_name}\n"
            + "\n请进行测试验证，回复：已完成 ✅ {round} Step 5"
        ),
        "step6": (
            f"🚀 **{round_name} Step 6 — 合并部署归档**\n\n"
            + "##分支## {step5:branch}\n"
            + "##commit## {step5:commit_sha}\n"
            + "##测试结果## {step5:test_summary}\n"
            + "##测试报告## {step5:test_report_url}\n"
            + "\n请合并部署归档并推送 main，回复：已完成 ✅ {round} Step 6"
        ),
    }



# ── Extracted from main.py L1457-1511: async def _handle_hash_advance(round_name: str, kv: dict, agent_id: str, ws) -> bool: ──
async def _handle_hash_advance(round_name: str, kv: dict, agent_id: str, ws) -> bool:
    """处理 ##advance 命令：手动推进管线到指定步。

    R140 A-1: L4 级别即可使用（不限于 PM）。
    R140 A-2: 支持跨步推进，自动跳过中间步骤。
    """
    from .scenario_matcher import _get_agent_level  # lazy import

    # ═══ R140 A-1: L4 权限检查 ═══
    level = _get_agent_level(agent_id)
    if level < 4:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"❌ 权限不足：##advance 需要 L4 级别，你当前 L{level}",
            "ts": time.time(),
        })
        return True

    step_str = kv.get("step", "")
    if not step_str.isdigit():
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": "❌ 参数错误: 缺少 `step=N` 参数",
            "ts": time.time(),
        })
        return True
    step_num = int(step_str)

    # ═══ R140 A-2: 跨步推进（跳过中间步骤）═══
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    old_step = ctx.current_step if ctx else 0
    if ctx:
        for i, s in enumerate(ctx.steps):
            step_key = s.get("name", f"step{i+1}")
            step_num_i = i + 1
            if step_num_i < step_num and s.get("status") in ("pending",):
                s["status"] = "skipped"
                logger.info("[R140] %s step%d skipped（##advance 跨步）",
                            round_name, step_num_i)
            elif step_num_i == step_num:
                s["status"] = "in_progress"
                s["dispatched_at"] = time.time()

    # 构造完成消息并尝试推进
    content = f"已完成 ✅ {round_name} Step {step_num}"
    ok, reason = _try_advance_pipeline(content, agent_id)
    if ok:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"✅ **{round_name}** 已推进到 Step {step_num}" +
                       (f"（跳过 {step_num - old_step - 1} 步）" if ctx and step_num > old_step + 1 else ""),
            "ts": time.time(),
        })
        # ═══ R140: 带通知自动派活 ═══
        asyncio.ensure_future(_auto_dispatch(ctx, step_num, notify_ws=ws, notify_agent_id=agent_id))
        logger.info("[Pipeline] ##advance: %s step%d → step%d by %s (L%d)",
                    round_name, (old_step if ctx else 0), step_num, agent_id[:12], level)
    else:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"⚠️ 推进失败: {reason}",
            "ts": time.time(),
        })
    return True



# ── Extracted from main.py L1514-1543: async def _handle_hash_archive(round_name: str, agent_id: str, ws) -> bool: ──
async def _handle_hash_archive(round_name: str, agent_id: str, ws) -> bool:
    """处理 ##archive##R{N} — PM 手动归档管线。"""
    pm_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
    if pm_id and agent_id != pm_id:
        await _send(ws, {
            "type": "broadcast", "channel": f"_inbox:{agent_id}",
            "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
            "content": "❌ 无权限: ##archive 仅 PM 可用",
            "ts": time.time(),
        })
        return True
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        await _send(ws, {
            "type": "broadcast", "channel": f"_inbox:{agent_id}",
            "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"❌ {round_name} 管线不存在",
            "ts": time.time(),
        })
        return True
    await _archive_pipeline(round_name)
    await _send(ws, {
        "type": "broadcast", "channel": f"_inbox:{agent_id}",
        "from_name": "系统", "from_agent": state.SYSTEM_AGENT_ID,
        "content": f"📦 {round_name} 管线已手动归档",
        "ts": time.time(),
    })
    return True
# ════════════════════════════════════════════════════


# ── Extracted from main.py L1547-1600: async def _archive_pipeline(round_name: str) -> None: ──
async def _archive_pipeline(round_name: str) -> None:
    """归档已完成管线：从活跃上下文移除，追加到 pipeline_archive.json。"""
    from pathlib import Path
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        return
    now = time.time()
    archive_record = {
        "round_name": ctx.round_name,
        "status": "completed",
        "archived_at": now,
        "completed_at": getattr(ctx, "updated_at", now),
        "reject_count": getattr(ctx, "reject_count", 0),
        "steps": ctx.steps,
        "artifacts": getattr(ctx, "artifacts", {}),
        "references": getattr(ctx, "references", {}),
        "summary": {
            "total_steps": len(ctx.steps),
            "completed_steps": sum(
                1 for s in (ctx.steps or []) if s.get("status") == "done"
            ),
            "reject_count": getattr(ctx, "reject_count", 0),
            "total_duration_sec": int(
                now - getattr(ctx, "created_at", now)
            ) if getattr(ctx, "created_at", None) else 0,
        },
    }
    mgr._contexts.pop(round_name, None)
    mgr.save()
    archive_path = Path(config.DATA_DIR) / "pipeline_archive.json"
    records: list[dict] = []
    if archive_path.exists():
        try:
            records = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            records = []
    records.append(archive_record)
    MAX_ARCHIVE_TRIM = 50
    KEEP_ARCHIVE = 30
    if len(records) > MAX_ARCHIVE_TRIM:
        records = records[-KEEP_ARCHIVE:]
    try:
        archive_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[R124] 归档完成: %s → %s (%d 条归档)",
                    round_name, archive_path, len(records))
        await _notify_pm(ctx, len(ctx.steps), "archived",
                         f"📦 {round_name} 管线已完成并归档")
    except (OSError, PermissionError) as e:
        logger.warning("[R124] 归档写入失败: %s", e)



# ── Extracted from main.py L1602-1724: async def _handle_hash_start(round_name: str, kv: dict, agent_id: str, ws) -> bool: ──
async def _handle_hash_start(round_name: str, kv: dict, agent_id: str, ws) -> bool:
    """处理 ##start 命令：创建 PipelineContext + 落盘 + 自动派活 Step 1."""
    mgr = _ensure_pipeline_manager()
    if mgr.exists(round_name):
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"❌ {round_name} 管线已存在，无法重复创建",
            "ts": time.time(),
        })
        return True

    # 1. 刷新角色映射
    try:
        _refresh_role_agent_map()
    except Exception:
        pass

    # 2. 构建 steps（从 DEFAULT_STEPS 填充 agent_id）
    from .pipeline_context import DEFAULT_STEPS, DEFAULT_STEP_ORDER
    from . import agent_card as _ac_mod

    role_map = mgr.get_global_role_map()
    if not role_map:
        role_map = dict(getattr(state, '_ROLE_AGENT_MAP', {}))
    name_to_ws = _build_name_to_ws_map()

    steps_list: list[dict] = []
    for sk in DEFAULT_STEP_ORDER:
        step_info = DEFAULT_STEPS[sk]
        agents = role_map.get(step_info.role, [])
        agent_card_name = ""
        agent_id_for_step = ""
        if agents:
            agent_id_for_step = agents[0]
            card = _ac_mod.get_agent_card(agents[0])
            agent_card_name = card.get("display_name", agents[0][:12]) if card else agents[0][:12]
            # 通过 display_name 桥接卡 key → WS 连接 ID
            if card:
                _real_id = name_to_ws.get(card.get("display_name", ""))
                if _real_id:
                    agent_id_for_step = _real_id
                else:
                    # ═══ R117 fix: card key → WS ID fallback ═══
                    _fallback = _resolve_card_key_to_ws_id(agents[0])
                    if _fallback:
                        agent_id_for_step = _fallback
                        logger.info("[R117] ##start fallback: %s → %s",
                                    agents[0], _fallback)

        steps_list.append({
            "name": sk,
            "step_key": sk,
            "role": step_info.role,
            "title": step_info.title,
            "status": "pending",
            "agent_id": agent_id_for_step,
            "agent_name": agent_card_name,
            "output": None,
            "result_msg": "",
        })

    # 3. 构建 references
    references: dict[str, str] = {}
    for ref_key in ("requirements_url", "work_plan_url"):
        if kv.get(ref_key):
            references[ref_key] = kv[ref_key]

    # 4. 构建 message_templates（R118: 富上下文模板）
    templates = _build_rich_templates(round_name, references, {})

    # 5. 创建 PipelineContext
    from pathlib import Path
    workspace_dir = Path(getattr(config, 'REPO_PATH', '/opt/data/ws-bridge'))
    task_dir = Path(config.DATA_DIR) / "pipeline_tasks" / round_name

    ctx = PipelineContext(
        round_name=round_name,
        task_kind=PipelineTaskKind.DEV,
        workspace_dir=workspace_dir,
        task_dir=task_dir,
        workspace_id="",
        pm_inbox_id=config.PIPELINE_PM_AGENT_ID,
        status=PipelineStatus.INIT,
        current_step=1,
        total_steps=len(DEFAULT_STEPS),
        steps=steps_list,
        references=references,
        message_templates=templates,
        round_title=kv.get("round_title", round_name),
        created_by=agent_id,
        created_at=time.time(),
    )

    # 6. 落盘
    mgr.set_context(round_name, ctx)
    await mgr.transition_to(round_name, PipelineStatus.RUNNING)

    # 7. 自动派活（R140 A-6: Step 1 自动确认，PM 发 ##start 表示需求已就绪）
    ctx.current_step = 2
    ctx.steps[0]["status"] = "done"
    ctx.steps[0]["result_msg"] = "需求已就绪（##start 创建时自动确认）"
    # ═══ R119 fix: 落盘 Step 1 自动确认状态，防止容器重启后丢失 ═══
    try:
        mgr.save()
    except Exception:
        pass

    # ═══ R140 A-6/A-7: 反馈真实派活状态，显示 agent 名称，失败时提示原因 ═══
    step2_agent_name = _get_step_agent_name(ctx, 2)
    dispatch_ok = await _auto_dispatch(ctx, 2, notify_ws=ws, notify_agent_id=agent_id)

    # 8. 回复发送者
    if dispatch_ok:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": (
                f"✅ {round_name} 管线已创建并启动\n"
                f"  Step 2（技术方案）已派活给 {step2_agent_name}"
            ),
            "ts": time.time(),
        })
    else:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": (
                f"✅ {round_name} 管线已创建\n"
                f"⚠️ Step 2 自动派活失败，请使用 ##advance##{round_name}##step=2 手动派活"
            ),
            "ts": time.time(),
        })
    logger.info("[R111] ##start: %s by %s, dispatch=%s", round_name, agent_id[:16], dispatch_ok)
    return True



# ── Extracted from main.py L1726-1803: async def _handle_hash_status(round_name: str, agent_id: str, ws) -> bool: ──
async def _handle_hash_status(round_name: str, agent_id: str, ws) -> bool:
    """处理 ##status 命令：查询管线当前状态."""
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        # ═══ R124: 尝试从归档文件查找 ═══
        _archive_info = _find_archive(round_name)
        if _archive_info:
            await _send(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": (
                    f"📦 {round_name} 已归档\n"
                    f"状态: {_archive_info.get('status', 'completed')}\n"
                    f"归档时间: {_fmt_ts(_archive_info.get('archived_at', 0))}\n"
                    f"总步数: {_archive_info.get('summary', {}).get('total_steps', 0)}"
                    f" / 完成: {_archive_info.get('summary', {}).get('completed_steps', 0)}"
                ),
                "ts": time.time(),
            })
            return True
        # ════════════════════════════════════════════
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"❌ {round_name} 管线不存在",
            "ts": time.time(),
        })
        return True

    # 拼装状态文本
    step_lines = []
    status_icons = {
        "pending": "⬜",
        "active": "🟢",
        "in_progress": "🔄",   # R142 新增
        "done": "✅",
        "failed": "❌",
        "skipped": "⏭",
    }
    step_names = {
        "pm": "小谷",
        "arch": "小开",
        "dev": "爱泰",
        "review": "小周",
        "qa": "泰虾",
        "operations": "小爱",
    }

    for step in ctx.steps:
        step_key = step.get("step_key", step.get("name", "?"))
        step_num = step_key.replace("step", "")
        st = step.get("status", "pending")
        icon = status_icons.get(st, "⬜")
        role = step.get("role", "?")
        name = step_names.get(role, role)
        step_lines.append(f"  Step {step_num}: {icon} {name}")
    # ═══ R142: 状态证据 ═══
    for step in ctx.steps:
        evidence_parts = []
        st = step.get("status", "pending")
        if st == "done" and step.get("completed_at"):
            evidence_parts.append(f"完成于: {_fmt_ts(step['completed_at'])}")
        if st == "in_progress" and step.get("dispatched_at"):
            elapsed = int(time.time() - step["dispatched_at"])
            evidence_parts.append(f"已进行: {elapsed//60}分{elapsed%60}秒")
        if step.get("result_msg"):
            msg_snippet = step["result_msg"][:60].replace("\n", " ")
            evidence_parts.append(f"消息: {msg_snippet}")
        if evidence_parts:
            step_lines.append("  " + " | ".join(evidence_parts))
    # ══════════════════════

    status_text = (
        f"📊 **{round_name} 管线状态**\n"
        f"  状态: {ctx.status.value}\n"
        f"  当前步: Step {ctx.current_step}\n"
        + "\n".join(step_lines)
    )

    await _send(ws, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": status_text,
        "ts": time.time(),
    })
    return True



# ── Extracted from main.py L1805-1831: async def _handle_hash_stop(round_name: str, agent_id: str, ws) -> bool: ──
async def _handle_hash_stop(round_name: str, agent_id: str, ws) -> bool:
    """处理 ##stop 命令：停止/取消管线."""
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if not ctx:
        await _send(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"❌ {round_name} 管线不存在",
            "ts": time.time(),
        })
        return True

    await mgr.cancel(round_name)
    await _send(ws, {
        "type": "broadcast",
        "channel": f"_inbox:{agent_id}",
        "from_name": "系统",
        "from_agent": state.SYSTEM_AGENT_ID,
        "content": f"🛑 {round_name} 管线已停止（CANCELLED）",
        "ts": time.time(),
    })
    logger.info("[R111] ##stop: %s by %s", round_name, agent_id[:16])
    return True




# ═══════════════════════════════════════════════════════════════════════
# PipelineEngine class — unified engine with lifecycle management
# ═══════════════════════════════════════════════════════════════════════

class PipelineEngine:
    """管线状态机引擎 — 统一管理管线全生命周期。

    职责范围：
    - 管线状态推进（try_advance / auto_advance）
    - 自动调度（auto_dispatch / auto_re_notify）
    - ## 命令处理（start / stop / status / advance / archive）
    - 归档管理（archive / find）
    - PM 通知（notify / reject / retry）
    - 模板渲染（render / summary / agent_name）
    - 后台扫描循环（git sync / timeout / restore）
    - 状态格式化（format_context）

    所有管线模块级函数（_auto_advance_pipeline 等）与本 class 共存于
    同一文件，class 方法通过薄包装器调用模块级函数。
    """

    def __init__(
        self,
        context_mgr: PipelineContextManager,
        send_to_agent: Callable[[str, dict], Awaitable[int]],
        send_ws: Callable[[Any, dict], Awaitable[None]],
        resolve_card_key: Optional[Callable[[str], Optional[str]]] = None,
        # ── 以下回调为非管线函数依赖（保留在 main.py） ──
        get_step_config: Optional[Callable[[str], dict]] = None,
        persist_broadcast: Optional[Callable[[str, str, str], None]] = None,
        find_agents_by_role: Optional[Callable[[str, set, list], list]] = None,
        set_pipeline_state: Optional[Callable[[str, dict], None]] = None,
        extract_artifact_kv: Optional[Callable[[str], dict]] = None,
    ):
        self._ctx_mgr = context_mgr
        self._send_to_agent = send_to_agent
        self._send_ws = send_ws
        self._resolve_card_key = resolve_card_key
        # ── 非管线回调 ──
        self._get_step_config = get_step_config
        self._persist_broadcast = persist_broadcast
        self._find_agents_by_role = find_agents_by_role
        self._set_pipeline_state = set_pipeline_state
        self._extract_artifact_kv = extract_artifact_kv

        # ── 内部状态（原 main.py 模块级状态） ──
        self._pending_retries: dict[str, dict] = {}
        self._git_sync_task: Optional[asyncio.Task] = None
        self._timeout_scan_task: Optional[asyncio.Task] = None
        self._timeout_scan_started: bool = False

    # ═══════════════════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════════════════

    def start(self) -> None:
        """统一启动后台扫描循环（git sync + timeout scanner）."""
        self._ensure_git_scan()
        self._ensure_timeout_scanner()

    def stop(self) -> None:
        """停止所有后台扫描循环."""
        if self._git_sync_task:
            self._git_sync_task.cancel()
            self._git_sync_task = None
        if self._timeout_scan_task:
            self._timeout_scan_task.cancel()
            self._timeout_scan_task = None
        self._timeout_scan_started = False

    # ═══════════════════════════════════════════════════════════════════
    # 🅰️ 数据/工具函数
    # ═══════════════════════════════════════════════════════════════════

    async def _cmd_task_update(self, sender_id: str, task_id: str, new_state: str, output_ref: str = "") -> str:
        """Update a task's state (internal method)."""
        import shared.protocol as _p
        task = ts.get_task(task_id, config.DATA_DIR)
        if not task:
            return f"❌ Task {task_id[:12]} 不存在"
        try:
            current = _p.TaskState(task["state"])
            target = _p.TaskState(new_state)
        except ValueError:
            valid = [s.value for s in _p.TaskState]
            return f"❌ 无效状态：{new_state}。有效值：{', '.join(valid)}"
        allowed = _p.TASK_VALID_TRANSITIONS.get(current, [])
        if target not in allowed:
            return f"❌ 不允许的转换：{current.value} → {target.value}"
        if target == _p.TaskState.INPUT_REQUIRED:
            ts.increment_reject_count(task_id, config.DATA_DIR)
            task_d = ts.get_task(task_id, config.DATA_DIR)
            if task_d["reject_count"] >= _p.TASK_REJECT_CEILING:
                ts.update_state(task_id, _p.TaskState.FAILED.value, config.DATA_DIR)
                task_d = ts.get_task(task_id, config.DATA_DIR)
                return (f"❌ 审查已达上限 ({_p.TASK_REJECT_CEILING}次)，已锁定 FAILED\n"
                        f"  {task_d['name']}: {task_d['state']} (rejects: {task_d['reject_count']})")
        ts.update_state(task_id, new_state, config.DATA_DIR)
        if output_ref:
            ts.add_output_ref(task_id, output_ref, config.DATA_DIR)
        task = ts.get_task(task_id, config.DATA_DIR)
        refs = task.get("output_refs", [])
        refs_str = f", 产出: {', '.join(refs)}" if refs else ""
        return f"✅ Task 已更新：{task['name']} → {task['state']}{refs_str}"

    def format_context(self, ctx: PipelineContext) -> str:
        """格式化 PipelineContext 为人类可读文本."""
        from datetime import datetime
        lines = [
            f"📋 {ctx.round_name} [{ctx.task_kind.value}]",
            f"  状态: {ctx.status.value}",
            f"  Step: {ctx.current_step}/{ctx.total_steps}",
            f"  阶段: {ctx.current_phase}",
        ]
        step_roles = ["pm", "arch", "dev", "review", "qa", "operations"]
        role_names = {"pm": "PM", "arch": "架构师", "dev": "开发",
                      "review": "审查", "qa": "测试", "operations": "运维"}
        step_parts = []
        for i in range(1, ctx.total_steps + 1):
            step_key = f"step{i}"
            role = step_roles[i - 1] if i - 1 < len(step_roles) else "?"
            role_name = role_names.get(role, role)
            ack = ctx.ack_states.get(step_key, {})
            ack_state = ack.get("state", "")
            if ack_state == "FAILED":
                icon = "❌"
                desc = "失败"
            elif ack_state == "ACKED" or i < ctx.current_step:
                icon = "✅"
                desc = "已完成"
            elif i == ctx.current_step:
                icon = "🔄"
                desc = "进行中"
            elif ack_state in ("SENT", "DELIVERED", "IN_PROGRESS"):
                icon = "🔄"
                desc = "进行中"
            else:
                icon = "⏳"
                desc = "待开始"
            step_parts.append(f"  Step{i} {icon} {role_name} → {desc}")
        if step_parts:
            lines.append("  步骤:")
            lines.extend(step_parts)
        ack_parts = []
        for i in range(1, ctx.total_steps + 1):
            step = f"step{i}"
            ack = ctx.ack_states.get(step, {})
            state_val = ack.get("state", "")
            role = ack.get("role_name", "")
            if state_val == "ACKED":
                ack_parts.append(f"step{i} ✅{role}")
            elif state_val == "PENDING":
                ack_parts.append(f"step{i} ⏳{role}")
            elif state_val == "FAILED":
                ack_parts.append(f"step{i} ❌{role}")
            elif state_val in ("SENT", "DELIVERED", "IN_PROGRESS", "ACKNOWLEDGED"):
                ack_parts.append(f"step{i} 🔄{role}")
            else:
                ack_parts.append(f"step{i} ⬜")
        lines.append(f"  ACK: {' | '.join(ack_parts)}")
        if ctx.blocked_reason:
            lines.append(f"  阻塞: {ctx.blocked_reason}")
        if ctx.role_agent_map:
            parts = []
            for role, agents in ctx.role_agent_map.items():
                agents_str = ",".join(a[:12] for a in agents)
                parts.append(f"{role}={agents_str}")
            lines.append(f"  成员: {'; '.join(parts)}")
        if ctx.workspace_id:
            lines.append(f"  工作室: {ctx.workspace_id}")
        if ctx.created_at:
            lines.append(
                f"  创建: {datetime.fromtimestamp(ctx.created_at).strftime('%m/%d %H:%M')}"
            )
        return "\n".join(lines)

    def render_template(self, template: str, ctx: PipelineContext, step_num: int) -> str:
        """用 Pipeline Context 数据渲染模板字符串。"""
        return _render_template(template, ctx, step_num)

    def get_step_agent_name(self, ctx: PipelineContext, step_num: int) -> str:
        """获取指定 step 的 agent 名称。"""
        return _get_step_agent_name(ctx, step_num)

    def build_step_summary(self, ctx: PipelineContext, step_num: int) -> str:
        """构建前置步骤完成摘要。"""
        return _build_step_summary(ctx, step_num)

    def find_archive(self, round_name: str) -> Optional[dict]:
        """从 pipeline_archive.json 查找已归档轮次。"""
        return _find_archive(round_name)

    @staticmethod
    def _step_sort_key(step_name: str) -> tuple:
        """Sort step keys numerically."""
        import re as _re
        m = _re.search(r"(\d+)", step_name)
        return (int(m.group(1)),) if m else (0, step_name)

    # ═══════════════════════════════════════════════════════════════════
    # 🅱️ 状态推进
    # ═══════════════════════════════════════════════════════════════════

    def try_advance(self, content: str, agent_id: str) -> tuple[bool, str]:
        """Parse 已完成 ✅ R{N} Step {N} and auto-advance pipeline context.

        Delegates to _try_advance_pipeline (engine2 version) for the core logic.
        Uses the engine2 regex (已完成 ✅ R) which handles the primary case.

        Returns:
            (True, "round_name") on success, (False, reason) on skip.
        """
        return _try_advance_pipeline(content, agent_id)

    async def auto_advance(self, round_name: str, result: dict) -> str:
        """Git sync 检测到新产出后自动推进状态机。

        Delegates to _auto_advance_pipeline (engine2 version).
        """
        return await _auto_advance_pipeline(round_name, result)

    # ═══════════════════════════════════════════════════════════════════
    # 🅲 ## 命令
    # ═══════════════════════════════════════════════════════════════════

    async def handle_hash_start(self, round_name: str, kv: dict, agent_id: str, ws) -> bool:
        """处理 ##start 命令。"""
        return await _handle_hash_start(round_name, kv, agent_id, ws)

    async def handle_hash_status(self, round_name: str, agent_id: str, ws) -> bool:
        """处理 ##status 命令。"""
        return await _handle_hash_status(round_name, agent_id, ws)

    async def handle_hash_stop(self, round_name: str, agent_id: str, ws) -> bool:
        """处理 ##stop 命令。"""
        return await _handle_hash_stop(round_name, agent_id, ws)

    async def handle_hash_advance(self, round_name: str, kv: dict, agent_id: str, ws) -> bool:
        """处理 ##advance 命令。"""
        return await _handle_hash_advance(round_name, kv, agent_id, ws)

    async def handle_hash_archive(self, round_name: str, agent_id: str, ws) -> bool:
        """处理 ##archive 命令。"""
        return await _handle_hash_archive(round_name, agent_id, ws)

    async def archive_pipeline(self, round_name: str) -> None:
        """归档已完成管线。"""
        await _archive_pipeline(round_name)

    async def broadcast_workspace_archived(self, ws_id: str, resolved_workspace=None) -> None:
        """广播工作区已归档 — Web UI 用此重组 tab。"""
        if resolved_workspace is None:
            resolved_workspace = ws_mod.get_workspace(ws_id)
        payload = json.dumps({
            "type": "workspace_archived",
            "workspace_id": ws_id,
            "ts": time.time(),
        })
        if resolved_workspace:
            for agent_id in resolved_workspace.members:
                for conn in list(state._connections.get(agent_id, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(payload)
                        elif hasattr(conn, "send"):
                            await conn.send(payload)
                    except Exception:
                        pass

    # ═══════════════════════════════════════════════════════════════════
    # 🅳 自动调度
    # ═══════════════════════════════════════════════════════════════════

    async def auto_dispatch(self, ctx: PipelineContext, step_num: int) -> bool:
        """自动派活下一步。受 AUTO_DISPATCH_ENABLED 开关控制。

        以 engine2 的 _auto_dispatch 为核心，增加了模板不存在时的
        默认消息回退（旧 pipeline_engine 特性），修复 B-5 PM fallback bug。
        """
        if not config.AUTO_DISPATCH_ENABLED:
            logger.info("[R107] 自动派活已关闭，跳过 step%d (round=%s)",
                        step_num, ctx.round_name)
            return False

        next_step_key = f"step{step_num}"
        next_template = ctx.message_templates.get(next_step_key) if hasattr(ctx, "message_templates") else None

        if not next_template:
            # ── 默认模板回退（旧版特性） ──
            agent_name = _get_step_agent_name(ctx, step_num)
            summary = _build_step_summary(ctx, step_num)
            rendered = (
                f"💻 **{ctx.round_name} Step {step_num}** — {agent_name}\n\n"
                f"{summary}\n\n"
                f"请完成当前步骤后回复：已完成 ✅ {ctx.round_name} Step {step_num}"
            ) if step_num != 1 else (
                # Step 1 通常是 PM/需求，给默认提示
                f"📋 **{ctx.round_name} Step {step_num}** — {agent_name}\n\n"
                f"{summary}\n\n"
                f"请完成当前步骤后回复：已完成 ✅ {ctx.round_name} Step {step_num}"
            )
        else:
            rendered = _render_template(next_template, ctx, step_num)
            # ═══ R123: Step ≥ 3 时前置步骤摘要注入 ═══
            if step_num >= 3:
                _summary = _build_step_summary(ctx, step_num)
                if _summary:
                    rendered = _summary + "\n" + rendered

        # 查找 target_agent_id
        target_agent_id = ""
        step_info = next(
            (s for s in (ctx.steps or []) if s.get("name") == next_step_key), None
        )
        if step_info:
            target_agent_id = step_info.get("agent_id", "")

        if not target_agent_id:
            logger.warning("[R106] %s step%d: ctx.steps 中未找到 agent_id，跳过自动派活",
                           ctx.round_name, step_num)
            return False

        # R117 fix: card key → WS ID fallback
        if not target_agent_id.startswith("ws_"):
            _fallback_id = _resolve_card_key_to_ws_id(target_agent_id)
            if _fallback_id:
                logger.info("[R117] card key %s → WS ID %s (fallback)",
                            target_agent_id, _fallback_id)
                target_agent_id = _fallback_id
                if step_info:
                    step_info["agent_id"] = _fallback_id
            else:
                logger.warning("[R117] 无法解析 card key %s → WS ID", target_agent_id)
                return False

        payload = {
            "type": "broadcast",
            "channel": f"_inbox:{target_agent_id}",
            "content": rendered,
            "from_name": "系统",
            "agent_id": state.SYSTEM_AGENT_ID,
            "to_agent": target_agent_id,
            "id": f"auto-{ctx.round_name}-step{step_num}-{int(time.time() * 1000)}",
            "ts": time.time(),
        }

        # 派活消息落库
        try:
            ms.save_message(
                msg_id=payload["id"], msg_type="broadcast",
                from_agent=payload["agent_id"], from_name=payload["from_name"],
                content=rendered, ts=payload["ts"],
                data_dir=config.DATA_DIR, channel=f"_inbox:{target_agent_id}",
            )
        except Exception:
            pass

        sent = await self._send_to_agent(target_agent_id, payload) if self._send_to_agent else 0
        logger.info("[R109] 自动派活 step%d → %s: sent=%d",
                    step_num, target_agent_id, sent)

        if sent > 0:
            if step_info:
                step_info["status"] = "in_progress"
                step_info["dispatched_at"] = time.time()
                step_info["timeout_alerted"] = False
                try:
                    self._ctx_mgr.save()
                except Exception:
                    pass
            await self.notify_pm(ctx, step_num, "dispatched",
                                f"→ {_get_step_agent_name(ctx, step_num)}（{target_agent_id[:12]}）")
            return True
        else:
            logger.info("[R106 B-5 fix] auto_dispatch 返回 False — 无 PM fallback 风险")
            self.enqueue_retry(ctx, step_num)
            return False

    async def auto_re_notify(self, ctx, step_key: str, step_num: int) -> None:
        """超时后重新发送派活消息给原 bot。"""
        return await _auto_re_notify(ctx, step_key, step_num)

    # ═══════════════════════════════════════════════════════════════════
    # 🅴 通知/排队
    # ═══════════════════════════════════════════════════════════════════

    async def notify_pm(self, ctx: PipelineContext, step_num: int,
                        status: str, detail: str = "") -> None:
        """发送管线通知给 PM。"""
        await _notify_pm(ctx, step_num, status, detail)

    async def handle_reject(self, content: str, sender_agent_id: str) -> None:
        """处理退回 🔄 R{N} Step {N} 消息。"""
        await _handle_reject(content, sender_agent_id)

    def enqueue_retry(self, ctx: PipelineContext, step_num: int) -> None:
        """将失败的自动派活加入重试队列。"""
        _enqueue_retry(ctx, step_num)

    async def _retry_loop(self) -> None:
        """后台循环，每 15s 扫描待重试队列。R128 B-2: 退避 + PM 通知。"""
        while True:
            now = time.time()
            for round_name in list(self._pending_retries.keys()):
                entry = self._pending_retries[round_name]
                if now < entry["next_retry_at"]:
                    continue
                ctx = entry["ctx"]
                step_num = entry["step_num"]
                entry["retry_count"] += 1
                attempt = entry["retry_count"]
                logger.info("[R128] 重试派活 %s step%d (尝试 %d/5)",
                            round_name, step_num, attempt)
                result = await self.auto_dispatch(ctx, step_num)
                if result:
                    del self._pending_retries[round_name]
                    logger.info("[R128] 重试成功: %s step%d", round_name, step_num)
                elif attempt >= 5:
                    del self._pending_retries[round_name]
                    asyncio.ensure_future(
                        self.notify_pm(ctx, step_num, "stuck",
                                       f"重试 5 次均失败，目标 bot 持续离线。管线已标记为卡死。")
                    )
                    logger.warning("[R128] 重试耗尽: %s step%d 5/5 失败", round_name, step_num)
                else:
                    backoff = min(15 * (2 ** (attempt - 1)), 180)
                    entry["next_retry_at"] = time.time() + backoff
                    if attempt >= 3 and not entry.get("pm_notified_3"):
                        entry["pm_notified_3"] = True
                        asyncio.ensure_future(
                            self.notify_pm(ctx, step_num, "stuck",
                                           f"重试 {attempt}/5 次失败，目标 bot 离线。")
                        )
                    if not entry.get("notify_sent"):
                        entry["notify_sent"] = True
                        asyncio.ensure_future(
                            self.notify_pm(ctx, step_num, "retrying",
                                           f"尝试 {attempt+1}/5，退避 {backoff}s")
                        )
                    logger.info("[R128] 重试排队: %s step%d 等待 %ds",
                                round_name, step_num, backoff)
            await asyncio.sleep(15)

    # ═══════════════════════════════════════════════════════════════════
    # 🅵 后台扫描
    # ═══════════════════════════════════════════════════════════════════

    def _ensure_git_scan(self) -> None:
        """启动 git 同步定时循环。"""
        if not config.ENABLE_GIT_SYNC:
            logger.info("[R65] Git 同步已禁用（ENABLE_GIT_SYNC=0）")
            return
        self._git_sync_task = asyncio.create_task(self._start_git_sync_loop())
        logger.info("[R65] Git 同步已启动（interval=%ds）", config.GIT_SYNC_INTERVAL)

    async def _start_git_sync_loop(self) -> None:
        """独立的 git 同步定时循环。"""
        while True:
            await asyncio.sleep(config.GIT_SYNC_INTERVAL)
            try:
                await self._pipeline_git_sync_scan()
            except Exception as e:
                logger.warning("[R65] git_sync_scan error: %s", e)

    async def _pipeline_git_sync_scan(self) -> None:
        """遍历所有活跃管线，检查 git 同步。"""
        for pid, pstate in list(state._PIPELINE_STATE.items()):
            if not pstate.get("active"):
                continue
            if not config.ENABLE_GIT_SYNC:
                continue
            pconfig = state._PIPELINE_CONFIG.get(pid, {})
            sync_config = {
                "branch": pconfig.get("git_sync_branch", config.GIT_SYNC_BRANCH),
                "repo_path": pconfig.get("repo_path", config.REPO_PATH),
                "last_sha": pstate.get("last_output_sha", ""),
                "fallback_enabled": config.GIT_SYNC_FALLBACK,
            }
            syncer = pps.PipelineGitSync(pid, sync_config)
            result = await syncer.sync()
            if result and result.get("synced"):
                await self.auto_advance(pid, result)
                pstate["_last_git_sync_ts"] = time.time()

    def _ensure_timeout_scanner(self) -> None:
        """启动超时扫描定时循环。"""
        timeout_min = config.PIPELINE_TIMEOUT_ALERT_MINUTES
        scan_interval = config.PIPELINE_TIMEOUT_SCAN_INTERVAL
        if timeout_min <= 0:
            logger.info("[R122] 管线超时告警已禁用（PIPELINE_TIMEOUT_ALERT_MINUTES=%d）",
                        timeout_min)
            return
        if self._timeout_scan_started:
            return
        self._timeout_scan_task = asyncio.create_task(
            self._start_timeout_scan_loop(timeout_min, scan_interval)
        )
        self._timeout_scan_started = True
        logger.info("[R122] 管线超时扫描已启动（timeout=%dmin, interval=%ds）",
                    timeout_min, scan_interval)

    async def _start_timeout_scan_loop(self, timeout_min: int, scan_interval: int) -> None:
        """独立的超时扫描定时循环。"""
        while True:
            await asyncio.sleep(scan_interval)
            try:
                await self._pipeline_timeout_scan(timeout_min)
            except Exception as e:
                logger.warning("[R122] 超时扫描错误: %s", e)

    async def _pipeline_timeout_scan(self, timeout_min: int) -> None:
        """遍历所有 RUNNING 管线，检查 in_progress step 是否超时。"""
        from .pipeline_context import PipelineStatus as PS

        now = time.time()
        threshold = timeout_min * 60.0
        alerted = 0

        for ctx in self._ctx_mgr.get_all_active():
            if ctx.status != PS.RUNNING:
                continue
            for step in (ctx.steps or []):
                if step.get("status") != "in_progress":
                    continue
                dispatched_at = step.get("dispatched_at")
                if not dispatched_at:
                    continue
                elapsed = now - dispatched_at
                step_key = step.get("name", step.get("step_key", ""))
                try:
                    step_num = int(step_key.replace("step", ""))
                except (ValueError, TypeError):
                    step_num = 0
                pm_id = config.PIPELINE_PM_AGENT_ID

                # R122: 30min 首次告警
                if elapsed >= threshold and not step.get("timeout_alerted"):
                    step["timeout_alerted"] = True
                    alerted += 1
                    if pm_id:
                        alert_content = (
                            f"⏰ 管线超时告警\n\n"
                            f"**{ctx.round_name}** Step {step_key} 已超时 "
                            f"（{int(elapsed // 60)} 分钟无回复）\n\n"
                            f"状态: 已派活 → {step.get('agent_name', '?')}\n"
                            f"请检查 bot 状态或手动处理。"
                        )
                        try:
                            await self._send_to_agent(pm_id, {
                                "type": "broadcast",
                                "channel": f"_inbox:{pm_id}",
                                "from_name": "系统",
                                "from_agent": state.SYSTEM_AGENT_ID,
                                "content": alert_content,
                                "ts": time.time(),
                            })
                            logger.info("[R122] 超时告警: %s Step %s → PM (%s)",
                                        ctx.round_name, step_key, pm_id[:12])
                        except Exception as e:
                            logger.warning("[R122] 告警发送失败: %s", e)

                # R124: 30min 重发派活
                _retry_min = getattr(config, "PIPELINE_TIMEOUT_RETRY_MINUTES", 30)
                if (_retry_min > 0
                        and elapsed >= _retry_min * 60
                        and step.get("timeout_alerted")
                        and not step.get("re_notified")):
                    step["re_notified"] = True
                    alerted += 1
                    asyncio.ensure_future(
                        self.auto_re_notify(ctx, step_key, step_num)
                    )

                # R124: 45min timeout 标记
                _mark_min = getattr(config, "PIPELINE_TIMEOUT_MARK_MINUTES", 45)
                if (_mark_min > 0
                        and elapsed >= _mark_min * 60
                        and step.get("re_notified")
                        and step.get("status") != "timeout"):
                    step["status"] = "timeout"
                    alerted += 1
                    if pm_id and step_num:
                        await self._send_to_agent(pm_id, {
                            "type": "broadcast",
                            "channel": f"_inbox:{pm_id}",
                            "from_name": "系统",
                            "from_agent": state.SYSTEM_AGENT_ID,
                            "content": (
                                f"⏰ {ctx.round_name} Step {step_key} bot 已 "
                                f"{int(elapsed // 60)} 分钟未响应，已标记 timeout。\n"
                                f"请 PM 处理。"
                            ),
                            "ts": time.time(),
                        })

        if alerted:
            try:
                self._ctx_mgr.save()
                logger.info("[R124] 超时扫描完成（%d 条变更），状态已持久化", alerted)
            except Exception:
                pass

    async def restore_pipeline_timers(self) -> None:
        """On server start, recover pipeline timeout timers from task store."""
        try:
            all_tasks = ts.list_tasks_by_context("", config.DATA_DIR)
            round_groups = {}
            for t in all_tasks:
                ctx_name = t.get("context", "")
                t_state = t.get("state", "")
                if ctx_name.startswith("R") and t_state not in ("completed", "cancelled"):
                    if ctx_name not in round_groups:
                        round_groups[ctx_name] = []
                    round_groups[ctx_name].append(t)
            for round_name, tasks in round_groups.items():
                if round_name in state._PIPELINE_STATE:
                    continue
                tasks_sorted = sorted(tasks, key=lambda x: x.get("created_at", 0))
                current_step = tasks_sorted[0].get("name", "") if tasks_sorted else ""
                started_at = tasks_sorted[0].get("created_at", time.time())
                ws_id = "ws:" + round_name + "-dev"
                if self._set_pipeline_state:
                    self._set_pipeline_state(round_name, {
                        "active": True,
                        "current_step": current_step,
                        "ws_id": ws_id,
                        "started_at": started_at,
                    })
                logger.info(
                    "R49 C restored timer: %s step=%s ws=%s",
                    round_name, current_step, ws_id,
                )
        except Exception:
            pass

    async def restore_pipeline_dispatches(self) -> None:
        """On server start, re-dispatch the current step for all RUNNING pipelines."""
        from .pipeline_context import PipelineStatus as PS
        try:
            for ctx in self._ctx_mgr.get_all_active():
                if ctx.status != PS.RUNNING:
                    continue
                step_num = ctx.current_step
                if step_num < 1 or step_num > ctx.total_steps:
                    continue
                step_key = f"step{step_num}"
                step_info = next(
                    (s for s in (ctx.steps or []) if s.get("name") == step_key), None
                )
                if not step_info or step_info.get("status") not in ("pending", "in_progress"):
                    continue
                logger.info("[R119] 恢复派活: %s step%d → %s",
                            ctx.round_name, step_num,
                            step_info.get("agent_id", "?")[:20])
                self.enqueue_retry(ctx, step_num)
        except Exception:
            pass


# ── R137: Forwarders for scenario_matcher ──

def _ensure_engine():
    """Forward to main._ensure_engine()."""
    from .main import _ensure_engine
    return _ensure_engine()

def _ensure_pipeline_manager():
    """Forward to main._ensure_pipeline_manager()."""
    from .main import _ensure_pipeline_manager
    return _ensure_pipeline_manager()
