# -*- coding: utf-8 -*-
"""
R127: Pipeline Engine — 管线状态机模块提取.

Extracts ~2000 lines of pipeline state-machine logic from main.py into
a dedicated PipelineEngine class, following the R127 tech plan.

┌───────────────────────┐
│    PipelineEngine     │
│  ┌─────────────────┐  │
│  │ 状态推进          │  │  try_advance / auto_advance
│  │ ## 命令           │  │  handle_hash_*
│  │ 自动调度          │  │  auto_dispatch / auto_re_notify
│  │ 通知/重试         │  │  notify_pm / handle_reject / retry
│  │ 后台扫描          │  │  git_sync / timeout / restore
│  │ 数据工具          │  │  format / render / summary
│  └─────────────────┘  │
│                        │
│  依赖: ctx_mgr(注入)    │
│        send_to_agent(回调)│
│        send_ws(回调)    │
└───────────────────────┘

协作关系:
  main.py → 初始化 PipelineEngine → 调用 engine.*()
  scenario_matcher.py → engine.handle_hash_*()
  pipeline_auto_starter.py → engine.auto_dispatch()

不包含:
  - WebSocket 连接管理（仍在 main.py）
  - 场景匹配规则（已在 scenario_matcher.py）
  - Git 管线自动启动器（已在 pipeline_auto_starter.py）
  - 管线数据模型（已在 pipeline_context.py）
"""
import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from server.common import config, persistence
from . import message_store as ms
from . import pipeline_sync as pps
from . import state
from . import task_store as ts
from . import timeout_tracker
from . import workspace as ws_mod
from . import agent_card as ac_mod
from server.common import auth
from .pipeline_context import (
    PipelineContext,
    PipelineContextManager,
    PipelineStatus,
    PipelineTaskKind,
)
import shared.protocol as p

logger = logging.getLogger("ws-bridge.pipeline_engine")


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

    不包含：
    - WebSocket 连接管理（仍在 main.py）
    - 场景匹配规则（已在 scenario_matcher.py）
    - Git 管线自动启动器（已在 pipeline_auto_starter.py）
    - 管线数据模型（已在 pipeline_context.py）
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

    # ════════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════════

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

    # ════════════════════════════════════════════════════════════════
    # 🅰️ 数据/工具函数
    # ════════════════════════════════════════════════════════════════

    async def _cmd_task_update(self, sender_id: str, task_id: str, new_state: str, output_ref: str = "") -> str:
        """Update a task's state (R134: migrated from commands/task.py as internal method)."""
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
        replacements = {
            "{round_name}": ctx.round_name,
            "{round_title}": getattr(ctx, "round_title", ctx.round_name) or ctx.round_name,
            "{round}": ctx.round_name,  # R129 B-5: 旧模板用 {round}
            "{step_num}": str(step_num),
            "{num_steps}": str(ctx.total_steps),
        }
        # 注入 artifacts 中各 step 的产出 KV
        artifacts = getattr(ctx, "artifacts", {})
        if artifacts:
            for step_key, kv in artifacts.items():
                if isinstance(kv, dict):
                    for k, v in kv.items():
                        replacements.setdefault(f"{{artifacts.{step_key}.{k}}}", str(v))
        # 注入 references 中的文档 URL
        references = getattr(ctx, "references", {})
        if references:
            for ref_key, ref_url in references.items():
                replacements.setdefault(f"{{ref.{ref_key}}}", str(ref_url))
        result = template
        for placeholder, value in replacements.items():
            if placeholder in result:
                result = result.replace(placeholder, value)
        return result

    def get_step_agent_name(self, ctx: PipelineContext, step_num: int) -> str:
        """获取指定 step 的 agent 名称。"""
        step_key = f"step{step_num}"
        step_info = next(
            (s for s in (ctx.steps or []) if s.get("name") == step_key), None
        )
        if step_info:
            return step_info.get("agent_name", step_info.get("agent_id", "?")[:20])
        role_map = getattr(ctx, "role_agent_map", {})
        if step_num == 1:
            pm_id = config.PIPELINE_PM_AGENT_ID
            users = getattr(state, "_r72_users", {})
            display_name = users.get(pm_id, {}).get("name", pm_id[:12])
            return display_name or pm_id[:12]
        return "?"

    def build_step_summary(self, ctx: PipelineContext, step_num: int) -> str:
        """构建前置步骤完成摘要。"""
        lines = ["══════ 前置步骤状态 ══════"]
        role_names = {
            1: "📋 PM", 2: "📐 Arch", 3: "💻 Dev",
            4: "👁 Review", 5: "🧪 QA", 6: "🚢 Ops",
        }
        has_any = False
        for i in range(1, step_num):
            step_key = f"step{i}"
            step_info = next(
                (s for s in (ctx.steps or []) if s.get("name") == step_key), None
            )
            if step_info and step_info.get("status") == "done":
                role = role_names.get(i, "?")
                has_any = True
                agent = step_info.get("agent_name", step_info.get("agent_id", "?")[:12])
                line = f"Step {i} ✅ {role}（{agent}）已完成"
                out = step_info.get("output", "")
                if out:
                    if isinstance(out, dict) and "sha" in out:
                        line += f" | sha={out['sha'][:7]}"
                    elif isinstance(out, str):
                        line += f" | {out[:30]}"
                lines.append(line)
        if not has_any:
            lines.append("暂无已完成步骤")
        lines.append("═" * len("══════ 前置步骤状态 ══════"))
        return "\n".join(lines)

    def find_archive(self, round_name: str) -> Optional[dict]:
        """从 pipeline_archive.json 查找已归档轮次。"""
        archive_path = Path(config.DATA_DIR) / "pipeline_archive.json"
        if not archive_path.exists():
            return None
        try:
            data = json.loads(archive_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict) and entry.get("round_name") == round_name:
                        return entry
            elif isinstance(data, dict):
                for key, entry in data.items():
                    if key == round_name or (
                        isinstance(entry, dict) and entry.get("round_name") == round_name
                    ):
                        return entry
        except (json.JSONDecodeError, Exception):
            pass
        return None

    # ════════════════════════════════════════════════════════════════
    # 🅱️ 状态推进
    # ════════════════════════════════════════════════════════════════

    def try_advance(self, content: str, agent_id: str) -> tuple[bool, str]:
        """Parse 已完成 ✅ R{N} Step {N} and auto-advance pipeline context.

        Returns:
            (True, "round_name") on success, (False, reason) on skip.
        """
        m = re.search(r"(?:已完成|完成)\s*[✅✔️]\s*R(\d+)\s*[Ss]tep\s*(\d+)", content)

        # ── R128 B-4: 容错匹配，不匹配的透传但不报错 ──
        if not m:
            # 不记录 warning（正常流量）
            return False, "no match"
        round_name = f"R{m.group(1)}"
        completed_step = int(m.group(2))
        try:
            ctx = self._ctx_mgr.get(round_name)
            if not ctx:
                logger.info("[R106] 管线 %s 无上下文，跳过自动推进", round_name)
                return False, "no context"
            old_step = ctx.current_step
            if completed_step == old_step:
                _kv = {}
                if self._extract_artifact_kv:
                    _kv = self._extract_artifact_kv(content) or {}
                if _kv:
                    _step_key = f"step{completed_step}"
                    if not hasattr(ctx, 'artifacts') or not ctx.artifacts:
                        ctx.artifacts = {}
                    ctx.artifacts[_step_key] = _kv
                    try:
                        self._ctx_mgr.save()
                    except Exception:
                        pass
                    logger.info("[R115] %s step%d artifacts: %s",
                                round_name, completed_step, _kv)
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
                    try:
                        self._ctx_mgr.save()
                    except Exception:
                        pass
                # Advance to next step
                if completed_step < ctx.total_steps:
                    next_step = completed_step + 1
                    ctx.current_step = next_step
                    try:
                        self._ctx_mgr.save()
                    except Exception:
                        pass
                    asyncio.ensure_future(self.auto_dispatch(ctx, next_step))
                    logger.info("[R106] %s advance: step%d → step%d",
                                round_name, completed_step, next_step)
            return True, round_name
        except Exception as e:
            logger.warning("[R106] advance error: %s", e)
            return False, str(e)

    async def auto_advance(self, round_name: str, result: dict) -> str:
        """Git sync 检测到新产出后自动推进状态机。

        Args:
            round_name: 管线标识
            result: PipelineGitSync.sync() 返回值

        Returns:
            广播消息文本.
        """
        pstate = state._PIPELINE_STATE.get(round_name)
        if not pstate:
            return ""

        step_config = (self._get_step_config(round_name)
                       if self._get_step_config else {})
        current_step = pstate.get("current_step", "")
        if not current_step:
            return ""

        step_keys = sorted(step_config.keys(), key=self._step_sort_key)
        try:
            idx = step_keys.index(current_step)
        except ValueError:
            return ""

        if idx + 1 >= len(step_keys):
            return ""

        next_step = step_keys[idx + 1]
        new_sha = result.get("new_sha", "")

        # 1. 状态机推进
        pstate["current_step"] = next_step
        pstate["last_output_sha"] = new_sha
        tasks = ts.list_tasks_by_context(round_name, config.DATA_DIR)
        for t in tasks:
            if t.get("name") == current_step and t.get("state") != p.TaskState.COMPLETED.value:
                await self._cmd_task_update("系统", t["id"], p.TaskState.COMPLETED.value, output_ref=new_sha)
            if t.get("name") == next_step and t.get("state") == p.TaskState.PENDING.value:
                await self._cmd_task_update("系统", t["id"], p.TaskState.WORKING.value)

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

        if ws_id and self._persist_broadcast:
            pm_name = config.PIPELINE_PM_NAME
            self._persist_broadcast(ws_id, pm_name, msg)
            payload = json.dumps({
                "type": "broadcast", "channel": ws_id,
                "from_name": pm_name, "from": pm_name,
                "content": msg, "ts": time.time(),
            })
            ws_obj = ws_mod.get_workspace(ws_id)
            if ws_obj:
                for member_id in ws_obj.members:
                    for conn in list(state._connections.get(member_id, set())):
                        try:
                            if hasattr(conn, "send_str"):
                                await conn.send_str(payload)
                            elif hasattr(conn, "send"):
                                await conn.send(payload)
                        except Exception:
                            pass

        # 4. 点名下一角色
        next_role = step_config[next_step].get("role", "")
        if next_role and ws_id and self._find_agents_by_role:
            cards = ac_mod.get_all_cards()
            ws_obj = ws_mod.get_workspace(ws_id) if ws_id else None
            if ws_obj and cards:
                matched = self._find_agents_by_role(next_role, ws_obj.members, cards)
                users = auth.get_users()
                pm_name = config.PIPELINE_PM_NAME
                for aid in matched:
                    name = users.get(aid, {}).get("name", aid[:12])
                    mention = f"@{name} 🏗️ {round_name} {next_step} 到你了！"
                    mention_payload = json.dumps({
                        "type": "broadcast", "channel": ws_id,
                        "from_name": pm_name, "from": pm_name,
                        "content": mention, "ts": time.time(),
                    })
                    for conn in list(state._connections.get(aid, set())):
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

    @staticmethod
    def _step_sort_key(step_name: str) -> tuple:
        """Sort step keys numerically."""
        m = re.search(r"(\d+)", step_name)
        return (int(m.group(1)),) if m else (0, step_name)

    # ════════════════════════════════════════════════════════════════
    # 🅲 ## 命令
    # ════════════════════════════════════════════════════════════════

    async def handle_hash_start(
        self, round_name: str, kv: dict, agent_id: str, ws
    ) -> bool:
        """处理 ##start 命令：创建 PipelineContext + 落盘 + 自动派活 Step 1."""
        round_name = round_name.upper()

        # 检查是否已存在
        existing = self._ctx_mgr.get(round_name)
        if existing and existing.status == PipelineStatus.RUNNING:
            await self._send_ws(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": f"❌ 管线 {round_name} 已在运行中（status={existing.status.value}）",
                "ts": time.time(),
            })
            return True

        # 从 role_agent_map 创建映射
        role_agent_map = {}
        for k, v in kv.items():
            if k in ("pm", "arch", "dev", "review", "qa", "ops", "operations"):
                role_agent_map[k] = [v]

        # 解析 task= 参数
        task_kind_str = kv.get("task", "dev")
        try:
            task_kind = PipelineTaskKind(task_kind_str)
        except ValueError:
            task_kind = PipelineTaskKind.DEV

        # 解析 total_steps
        total_steps = int(kv.get("steps", 6))

        ctx = PipelineContext(
            round_name=round_name,
            task_kind=task_kind,
            total_steps=total_steps,
            current_step=1,
            current_phase="planning",
            status=PipelineStatus.RUNNING,
            role_agent_map=role_agent_map,
            created_at=time.time(),
        )
        # ═══ 生成 ctx.steps: 从 role_agent_map 填充各 step 的 agent_id ═══
        _step_role_map = ["pm", "arch", "dev", "review", "qa", "ops"]
        steps = []
        for i in range(1, total_steps + 1):
            role = _step_role_map[i - 1] if i - 1 < len(_step_role_map) else "?"
            agent_ids = role_agent_map.get(role, [])
            agent_id = agent_ids[0] if agent_ids else ""
            step_name = config.PIPELINE_PM_NAME if role == "pm" else agent_id
            steps.append({
                "name": f"step{i}",
                "role": role,
                "agent_id": agent_id,
                "agent_name": step_name,
                "status": "pending",
            })
        ctx.steps = steps
        self._ctx_mgr.add(ctx)
        try:
            self._ctx_mgr.save()
        except Exception:
            pass

        await self._send_ws(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": (
                f"✅ 管线 {round_name} 已创建并启动\n"
                f"  任务类型: {task_kind.value}\n"
                f"  总步数: {total_steps}\n"
                f"  Step 1 已开始"
            ),
            "ts": time.time(),
        })

        # 自动派活 Step 1
        asyncio.ensure_future(self.auto_dispatch(ctx, 1))

        logger.info("[Pipeline] ##start: %s (task=%s, steps=%d) by %s",
                    round_name, task_kind.value, total_steps, agent_id[:12])
        return True

    async def handle_hash_status(
        self, round_name: str, agent_id: str, ws
    ) -> bool:
        """处理 ##status 命令：查询管线当前状态."""
        round_name = round_name.upper()
        ctx = self._ctx_mgr.get(round_name)
        if ctx:
            formatted = self.format_context(ctx)
            await self._send_ws(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": formatted,
                "ts": time.time(),
            })
            return True
        # 检查归档
        archived = self.find_archive(round_name)
        if archived:
            ctx_data = archived.get("context", archived)
            lines = [f"📋 {round_name} [已归档]"]
            if isinstance(ctx_data, dict):
                lines.append(f"  状态: {ctx_data.get('status', 'archived')}")
                lines.append(f"  归档时间: {archived.get('archived_at', '?')}")
            await self._send_ws(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": "\n".join(lines),
                "ts": time.time(),
            })
            return True
        await self._send_ws(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"❌ 未找到管线 `{round_name}`（既不活跃也未归档）",
            "ts": time.time(),
        })
        return True

    async def handle_hash_stop(
        self, round_name: str, agent_id: str, ws
    ) -> bool:
        """处理 ##stop 命令：停止/取消管线."""
        round_name = round_name.upper()
        ctx = self._ctx_mgr.get(round_name)
        if not ctx:
            await self._send_ws(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": f"❌ 未找到活跃管线 `{round_name}`",
                "ts": time.time(),
            })
            return True
        try:
            self._ctx_mgr.remove(round_name)
            self._ctx_mgr.save()
            await self._send_ws(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": f"✅ 管线 {round_name} 已停止并移除",
                "ts": time.time(),
            })
            logger.info("[Pipeline] ##stop: %s by %s", round_name, agent_id[:12])
        except Exception as e:
            await self._send_ws(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": f"❌ 停止管线 {round_name} 失败: {e}",
                "ts": time.time(),
            })
        return True

    async def handle_hash_advance(
        self, round_name: str, kv: dict, agent_id: str, ws
    ) -> bool:
        """处理 ##advance 命令：PM 手动推进管线到下一步。"""
        round_name = round_name.upper()
        ctx = self._ctx_mgr.get(round_name)
        if not ctx:
            await self._send_ws(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": f"❌ 未找到活跃管线 `{round_name}`",
                "ts": time.time(),
            })
            return True
        target = int(kv.get("step", ctx.current_step + 1))
        if target < 1 or target > ctx.total_steps:
            await self._send_ws(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": f"❌ 无效 step: {target}（范围: 1-{ctx.total_steps}）",
                "ts": time.time(),
            })
            return True
        ctx.current_step = target
        try:
            self._ctx_mgr.save()
        except Exception:
            pass
        await self._send_ws(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"✅ {round_name} 已推进到 Step {target}",
            "ts": time.time(),
        })
        asyncio.ensure_future(self.auto_dispatch(ctx, target))
        logger.info("[Pipeline] ##advance: %s → step%d by %s",
                    round_name, target, agent_id[:12])
        return True

    async def handle_hash_archive(
        self, round_name: str, agent_id: str, ws
    ) -> bool:
        """处理 ##archive##R{N} — PM 手动归档管线。"""
        round_name = round_name.upper()
        pm_id = config.DISPATCH_SENDER_ID or config.PIPELINE_PM_AGENT_ID
        if pm_id and agent_id != pm_id:
            await self._send_ws(ws, {
                "type": "broadcast",
                "channel": f"_inbox:{agent_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": f"❌ 仅 PM（{pm_id[:12]}）可归档管线",
                "ts": time.time(),
            })
            return True
        await self.archive_pipeline(round_name)
        await self._send_ws(ws, {
            "type": "broadcast",
            "channel": f"_inbox:{agent_id}",
            "from_name": "系统",
            "from_agent": state.SYSTEM_AGENT_ID,
            "content": f"✅ 管线 {round_name} 已归档",
            "ts": time.time(),
        })
        return True

    async def archive_pipeline(self, round_name: str) -> None:
        """归档已完成管线：从活跃上下文移除，追加到 pipeline_archive.json。"""
        round_name = round_name.upper()
        ctx = self._ctx_mgr.get(round_name)
        if not ctx:
            return
        archive_path = Path(config.DATA_DIR) / "pipeline_archive.json"
        archive_entry = {
            "round_name": round_name,
            "context": {
                "task_kind": ctx.task_kind.value if hasattr(ctx, "task_kind") else "dev",
                "total_steps": ctx.total_steps,
                "current_step": ctx.current_step,
                "status": "archived",
                "steps": ctx.steps,
                "artifacts": getattr(ctx, "artifacts", {}),
                "created_at": ctx.created_at,
            },
            "archived_at": time.time(),
        }
        try:
            existing = []
            if archive_path.exists():
                try:
                    existing = json.loads(archive_path.read_text(encoding="utf-8"))
                    if not isinstance(existing, list):
                        existing = [existing] if isinstance(existing, dict) else []
                except (json.JSONDecodeError, Exception):
                    existing = []
            existing.append(archive_entry)
            archive_path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("[Pipeline] 归档写入失败 %s: %s", round_name, e)
        # 从活跃列表移除
        try:
            self._ctx_mgr.remove(round_name)
            self._ctx_mgr.save()
        except Exception:
            pass
        await self.notify_pm(ctx, 0, "archived")
        logger.info("[Pipeline] 管线 %s 已归档", round_name)

    async def broadcast_workspace_archived(
        self, ws_id: str, resolved_workspace=None
    ) -> None:
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

    # ════════════════════════════════════════════════════════════════
    # 🅳 自动调度
    # ════════════════════════════════════════════════════════════════

    async def auto_dispatch(self, ctx: PipelineContext, step_num: int) -> bool:
        """自动派活下一步。受 AUTO_DISPATCH_ENABLED 开关控制。"""
        if not config.AUTO_DISPATCH_ENABLED:
            logger.info("[R106] 自动派活已禁用（AUTO_DISPATCH_ENABLED=0）")
            return False
        round_name = ctx.round_name
        step_key = f"step{step_num}"
        agent_name = self.get_step_agent_name(ctx, step_num)
        logger.info("[R106] 自动派活: %s step%d → %s",
                    round_name, step_num, agent_name)

        # 查找 target_agent_id
        target_agent_id = ""
        step_info = next(
            (s for s in (ctx.steps or []) if s.get("name") == step_key), None
        )
        if step_info:
            target_agent_id = step_info.get("agent_id", "")

        if not target_agent_id:
            logger.warning(
                "[R106] %s step%s: ctx.steps 中未找到 agent_id，跳过自动派活。"
                "请确认 ##start 时传入了正确的 role_agent_map 参数",
                round_name, step_key,
            )
            return False

        if not target_agent_id:
            logger.warning("[R106] %s step%d: 找不到目标 agent", round_name, step_num)
            return False

        # 构建派活消息
        summary = self.build_step_summary(ctx, step_num)
        template_key = f"step{step_num}"
        template = ""
        if hasattr(ctx, "message_templates"):
            template = ctx.message_templates.get(template_key, "")
        rendered = self.render_template(template, ctx, step_num) if template else (
            f"💻 **{round_name} Step {step_num}** — {agent_name}\n\n"
            f"{summary}\n\n"
            f"请完成当前步骤后回复：已完成 ✅ {round_name} Step {step_num}"
        )

        payload = {
            "type": "message",
            "channel": f"_inbox:{target_agent_id}",
            "content": rendered,
        }
        sent = await self._send_to_agent(target_agent_id, payload)
        if sent == 0:
            logger.warning("[R106] %s step%d → %s 在线连接数为 0",
                           round_name, step_num, target_agent_id[:20])
            self.enqueue_retry(ctx, step_num)
            return False

        # 更新 step 状态
        if step_info:
            step_info["status"] = "in_progress"
            step_info["dispatched_at"] = time.time()
            try:
                self._ctx_mgr.save()
            except Exception:
                pass

        await self.notify_pm(ctx, step_num, "dispatched",
                             f"→ {agent_name}（{target_agent_id[:12]}）")
        return True

    async def auto_re_notify(
        self, ctx, step_key: str, step_num: int
    ) -> None:
        """超时后重新发送派活消息给原 bot。"""
        step_idx = step_num - 1
        step_info = ctx.steps[step_idx] if step_idx < len(ctx.steps) else None
        if not step_info:
            return
        target_id = step_info.get("agent_id", "")
        if not target_id:
            return
        payload = {
            "type": "message",
            "channel": f"_inbox:{target_id}",
            "content": (
                f"⏰ **{ctx.round_name} Step {step_num} 重发提醒**\n\n"
                f"此步骤已超过 30 分钟未收到回复。\n"
                f"请继续完成：{ctx.round_name} Step {step_num}\n\n"
                f"完成后回复：已完成 ✅ {ctx.round_name} Step {step_num}"
            ),
        }
        await self._send_to_agent(target_id, payload)

    # ════════════════════════════════════════════════════════════════
    # 🅴 通知/排队
    # ════════════════════════════════════════════════════════════════

    async def notify_pm(
        self, ctx: PipelineContext, step_num: int,
        status: str, detail: str = ""
    ) -> None:
        """发送管线通知给 PM。"""
        pm_id = config.PIPELINE_PM_AGENT_ID
        role_names = {
            1: "📋 PM", 2: "📐 Arch", 3: "💻 Dev",
            4: "👁 Review", 5: "🧪 QA", 6: "🚢 Ops",
        }
        step_role = role_names.get(step_num, "?")
        content = ""

        if status == "dispatched":
            agent_name = self.get_step_agent_name(ctx, step_num)
            content = (
                f"✅ **{ctx.round_name} 管线自动推进**\n\n"
                f"Step {step_num} 🚀 已派活 → {agent_name}（{step_role}）\n"
                + (f"\n{detail}" if detail else "")
            )
        elif status == "completed":
            step_lines = []
            for i, s in enumerate(ctx.steps, 1):
                role = role_names.get(i, "?")
                agent = s.get("agent_name", s.get("agent_id", "?")[:12])
                out = s.get("output", s.get("result_msg", ""))
                out_short = str(out)[:40] + "..." if len(str(out)) > 40 else out
                step_lines.append(f"| {i} | {role} | {agent} | {out_short} |")
            table_header = (
                "| Step | 角色 | 执行者 | 产出 |\n"
                "|:---:|:-----|:-------|:-----|\n"
            )
            content = (
                f"🎉 **{ctx.round_name} 管线已完成！**\n\n"
                f"{table_header}{chr(10).join(step_lines)}"
            )
        elif status == "failed":
            agent_name = self.get_step_agent_name(ctx, step_num)
            content = (
                f"⚠️ **{ctx.round_name} 管线异常**\n\n"
                f"Step {step_num}（{step_role}）→ {agent_name} 离线，"
                f"自动派活失败（5 次重试）\n"
                + (f"\n{detail}" if detail else "")
            )
        elif status == "retrying":
            content = (
                f"⏳ **{ctx.round_name} 派活排队中**\n\n"
                f"Step {step_num}（{step_role}）排队中（{detail}）"
            )
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

        if content and pm_id:
            await self._send_to_agent(pm_id, {
                "type": "broadcast",
                "channel": f"_inbox:{pm_id}",
                "from_name": "系统",
                "from_agent": state.SYSTEM_AGENT_ID,
                "content": content,
                "ts": time.time(),
            })

    async def handle_reject(
        self, content: str, sender_agent_id: str
    ) -> None:
        """处理退回 🔄 R{N} Step {N} 消息。"""
        m = re.match(r"退回 🔄 R(\d+) Step (\d+)(.*)", content)
        if not m:
            return
        round_name = f"R{m.group(1)}"
        step_num = int(m.group(2))
        reason = m.group(3).strip()
        ctx = self._ctx_mgr.get(round_name)
        if not ctx:
            return
        # 回退状态
        if step_num > 1:
            ctx.current_step = step_num - 1
        try:
            self._ctx_mgr.save()
        except Exception:
            pass
        detail = ""
        if reason:
            detail = f"原因: {reason}"
        await self.notify_pm(ctx, step_num, "rejected", detail)
        logger.info("[Pipeline] 退回: %s step%d by %s, reason=%s",
                    round_name, step_num, sender_agent_id[:12], reason)

    def enqueue_retry(self, ctx: PipelineContext, step_num: int) -> None:
        """将失败的自动派活加入重试队列。R128 B-2: 15s 首轮间隔 + 退避。"""
        round_name = ctx.round_name
        if round_name in self._pending_retries:
            return
        self._pending_retries[round_name] = {
            "ctx": ctx,
            "step_num": step_num,
            "retry_count": 0,
            "next_retry_at": time.time() + 15,  # R128 B-2: 15s 首轮
            "notify_sent": False,
            "pm_notified_3": False,
        }
        logger.info("[R128] 入重试队列: %s step%d（首轮 15s）", round_name, step_num)

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
                    logger.warning("[R128] 重试耗尽: %s step%d 5/5 失败，标记卡死",
                                   round_name, step_num)
                else:
                    # 退避: 15s → 30s → 60s → 120s → 180s
                    backoff = min(15 * (2 ** (attempt - 1)), 180)
                    entry["next_retry_at"] = time.time() + backoff
                    # 3 次后通知 PM
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

    # ════════════════════════════════════════════════════════════════
    # 🅵 后台扫描
    # ════════════════════════════════════════════════════════════════

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

    async def _start_timeout_scan_loop(
        self, timeout_min: int, scan_interval: int
    ) -> None:
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
        try:
            for ctx in self._ctx_mgr.get_all_active():
                if ctx.status != PipelineStatus.RUNNING:
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
