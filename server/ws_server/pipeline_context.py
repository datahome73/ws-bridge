"""R77: PipelineContext — 统一管线上下文对象。

包含 PipelineStatus / PipelineTaskKind 枚举,
PipelineContext dataclass (to_dict / from_dict),
PipelineContextManager (CRUD + JSON 持久化 + 并发锁)。
"""

import asyncio
import enum
import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("ws-bridge.pipeline_context")


# ── R97: StepInfo dataclass ─────────────────────────────────────────────


@dataclass
class StepInfo:
    """单个管线步骤信息。"""
    step_key: str          # "step1", "step2", ...
    role: str              # "pm" | "arch" | "dev" | "review" | "qa" | "operations"
    title: str             # 步骤标题
    status: str = "pending"  # "pending" | "active" | "done" | "failed" | "skipped"
    agent_id: str = ""
    agent_name: str = ""
    output: dict | None = None       # {"sha": "abc1234"} 等
    result_msg: str = ""             # "✅ 完成，已推 dev: xxxx"


DEFAULT_STEP_ORDER = ["step1", "step2", "step3", "step4", "step5", "step6"]

DEFAULT_STEPS: dict[str, StepInfo] = {
    "step1": StepInfo(step_key="step1", role="pm",          title="标注 WORK_PLAN 已审核"),
    "step2": StepInfo(step_key="step2", role="arch",        title="技术方案"),
    "step3": StepInfo(step_key="step3", role="dev",         title="编码实现"),
    "step4": StepInfo(step_key="step4", role="review",      title="代码审查"),
    "step5": StepInfo(step_key="step5", role="qa",          title="测试验证"),
    "step6": StepInfo(step_key="step6", role="operations",  title="合并部署归档"),
}


# ── Enums ──────────────────────────────────────────────────────────────


class PipelineStatus(enum.StrEnum):
    """管线状态机 — 7 个状态，6 条合法转换路径。"""
    INIT = "init"
    PLANNING = "planning"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    STOPPED = "stopped"  # R95: 通过 !pipeline_stop 命令手动停止


# 合法转换矩阵
_VALID_TRANSITIONS: dict[PipelineStatus, set[PipelineStatus]] = {
    PipelineStatus.INIT: {PipelineStatus.PLANNING, PipelineStatus.RUNNING, PipelineStatus.CANCELLED},
    PipelineStatus.PLANNING: {PipelineStatus.RUNNING, PipelineStatus.BLOCKED, PipelineStatus.CANCELLED},
    PipelineStatus.RUNNING: {PipelineStatus.BLOCKED, PipelineStatus.COMPLETED, PipelineStatus.CANCELLED, PipelineStatus.STOPPED},
    PipelineStatus.BLOCKED: {PipelineStatus.RUNNING, PipelineStatus.CANCELLED},
    PipelineStatus.COMPLETED: set(),
    PipelineStatus.CANCELLED: set(),
    PipelineStatus.STOPPED: set(),
}


def _is_valid_transition(current: PipelineStatus, target: PipelineStatus) -> bool:
    """检查状态转换合法性。"""
    allowed = _VALID_TRANSITIONS.get(current, set())
    return target in allowed


class PipelineTaskKind(enum.StrEnum):
    """管线任务类型 — 影响路径默认值。"""
    DEV = "dev"          # 开发任务（默认）
    REVIEW = "review"    # 代码审查
    DEPLOY = "deploy"    # 部署
    DOCS = "docs"        # 文档治理


# ── Dataclass ──────────────────────────────────────────────────────────


@dataclass
class PipelineContext:
    """统一管线上下文 — 纯数据对象，不含 I/O 或业务逻辑。"""

    # ── 身份信息（创建时确定，不可变）──
    round_name: str                                  # "R77"
    task_kind: PipelineTaskKind                      # 任务类型

    # ── 工作空间（创建时确定）──
    workspace_dir: Path                              # /opt/data/ws-bridge
    task_dir: Path                                   # workspace_dir / "pipeline_tasks" / round_name
    workspace_id: str                                # 工作室 ID
    pm_inbox_id: str                                 # PM 的 inbox channel ID

    # ── 管线运行时状态（随管线推进变化）──
    status: PipelineStatus = PipelineStatus.INIT     # 当前状态
    current_phase: str = "plan"                      # "plan" | "implement" | "review" | "deploy"
    current_step: int = 1                            # step 序号（1-indexed）
    total_steps: int = 6                             # 总 step 数
    blocked_reason: str | None = None                # status=BLOCKED 时的原因

    # ── 管线成员（角色 → agent_id）──
    role_agent_map: dict[str, list[str]] = field(default_factory=dict)  # {"architect": ["ws_xxx"], ...}
    agent_card_ids: dict[str, str] = field(default_factory=dict)     # {"ws_xxx": card_id, ...}

    # ── Git 同步状态 ──
    last_output_sha: str = ""                        # 上次处理的 commit SHA
    git_sync_branch: str = "dev"                     # 同步分支

    # ── R78: ACK 状态（step → ack_info）──
    ack_states: dict[str, dict] = field(default_factory=dict)  # {"step2": {"state": "ACKED", "by": "ws_xxx", ...}}

    # ── R78: Step 配置列表 ──
    steps: list[dict] = field(default_factory=list)  # [{"name": "step2", "executor_role": "arch", ...}]

    # ── 元信息（审计用）──
    created_at: float = 0.0
    updated_at: float = 0.0
    created_by: str = ""                             # 创建者 agent_id
    tags: dict[str, str] = field(default_factory=dict)  # 可扩展标签

    # ── R107: 自动派活元数据 ──
    round_title: str = ""                        # 人类可读标题
    references: dict = field(default_factory=dict)  # 文档 URL
    artifacts: dict = field(default_factory=dict)   # 每步产出 KV
    message_templates: dict = field(default_factory=dict)  # 派活模板

    # ── 派生路径（property，不持久化）──

    @property
    def work_plan_path(self) -> Path:
        """预期 WORK_PLAN.md 路径（物理文件）。"""
        return self.task_dir / "WORK_PLAN.md"

    @property
    def report_path(self) -> Path:
        """预期 test-report.md 路径。"""
        return self.task_dir / "test-report.md"

    @property
    def review_history_path(self) -> Path:
        """审查历史文件路径。"""
        return self.task_dir / "review-history.md"

    @property
    def inbox_channel(self) -> str:
        """当前管线的 inbox 通道 ID（供 bot 回复 PM）。"""
        return self.pm_inbox_id

    # ── 行为方法 ──

    def step_name(self) -> str:
        """返回当前 step 的名称（step2, step3, ...）。"""
        return f"step{self.current_step}"

    def advance(self) -> int:
        """推进一个 step。返回新的 current_step。"""
        self.current_step = min(self.current_step + 1, self.total_steps)
        return self.current_step

    def is_active(self) -> bool:
        """管线是否仍在活跃进行中。"""
        return self.status in {
            PipelineStatus.INIT,
            PipelineStatus.PLANNING,
            PipelineStatus.RUNNING,
            PipelineStatus.BLOCKED,
        }

    def to_dict(self) -> dict:
        """序列化到 JSON 字典（Path → str, enum → value）。"""
        return {
            "round_name": self.round_name,
            "task_kind": self.task_kind.value,
            "workspace_dir": str(self.workspace_dir),
            "task_dir": str(self.task_dir),
            "workspace_id": self.workspace_id,
            "pm_inbox_id": self.pm_inbox_id,
            "status": self.status.value,
            "current_phase": self.current_phase,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "blocked_reason": self.blocked_reason,
            "role_agent_map": self.role_agent_map,
            "agent_card_ids": self.agent_card_ids,
            "last_output_sha": self.last_output_sha,
            "git_sync_branch": self.git_sync_branch,
            "ack_states": self.ack_states,
            "steps": self.steps,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "tags": self.tags,
            # R107: 仅非空时序列化，保持向后兼容
            **({"round_title": self.round_title} if self.round_title else {}),
            **({"references": self.references} if self.references else {}),
            **({"artifacts": self.artifacts} if self.artifacts else {}),
            **({"message_templates": self.message_templates} if self.message_templates else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineContext":
        """从 JSON 字典反序列化（str → Path, value → enum）。"""
        # R78 A1: 兼容旧 JSON 格式（单值 str → 多值 list[str]）
        raw_role_map = d.get("role_agent_map", {})
        if raw_role_map and isinstance(next(iter(raw_role_map.values())), str):
            role_agent_map = {k: [v] for k, v in raw_role_map.items()}
        else:
            role_agent_map = raw_role_map
        return cls(
            round_name=d.get("round_name", ""),
            task_kind=PipelineTaskKind(d.get("task_kind", "dev")),
            workspace_dir=Path(d.get("workspace_dir", "")),
            task_dir=Path(d.get("task_dir", "")),
            workspace_id=d.get("workspace_id", ""),
            pm_inbox_id=d.get("pm_inbox_id", ""),
            status=PipelineStatus(d.get("status", "init")),
            current_phase=d.get("current_phase", "plan"),
            current_step=d.get("current_step", 1),
            total_steps=d.get("total_steps", 6),
            blocked_reason=d.get("blocked_reason"),
            role_agent_map=role_agent_map,
            agent_card_ids=d.get("agent_card_ids", {}),
            last_output_sha=d.get("last_output_sha", ""),
            ack_states=d.get("ack_states", {}),
            steps=d.get("steps", []),
            git_sync_branch=d.get("git_sync_branch", "dev"),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            created_by=d.get("created_by", ""),
            tags=d.get("tags", {}),
            round_title=d.get("round_title", ""),
            references=d.get("references", {}),
            artifacts=d.get("artifacts", {}),
            message_templates=d.get("message_templates", {}),
        )


# ── Manager ────────────────────────────────────────────────────────────

_PERSISTENT_FILE = "pipeline_contexts.json"
_HISTORY_FILE = "pipeline_contexts_history.jsonl"


class PipelineContextManager:
    """管理所有活跃 PipelineContext 的生命周期。

    与 handler.py 现有模式一致：
    - 活跃上下文在内存中维护（_contexts dict）
    - 每次变更写 JSON 持久化
    - 创建/归档通过锁保护
    """

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._lock = asyncio.Lock()
        self._contexts: dict[str, PipelineContext] = {}
        self._load()  # 从磁盘恢复

    # ── 查询 ──

    def get(self, round_name: str) -> PipelineContext | None:
        """按轮次名查询活跃上下文。"""
        return self._contexts.get(round_name)

    # ── R97: 通用上下文存取 ──

    def get_context(self, round_name: str) -> Any:
        """R97: 获取上下文（兼容旧 PipelineContext + 新 dict 上下文）。"""
        return self._contexts.get(round_name)

    def set_context(self, round_name: str, ctx: Any) -> None:
        """R97: 直接设置上下文（dict 或 PipelineContext 均可）。"""
        self._contexts[round_name] = ctx
        self._save()

    def save(self) -> None:
        """R97: 主动持久化。"""
        self._save()

    def get_all_active(self) -> list[PipelineContext]:
        """返回所有活跃上下文。"""
        return list(self._contexts.values())

    def exists(self, round_name: str) -> bool:
        """检查轮次是否存在（活跃或已归档）。"""
        return round_name in self._contexts

    # ── 写入（带锁） ──

    async def create(
        self,
        round_name: str,
        task_kind: PipelineTaskKind,
        workspace_dir: Path,
        workspace_id: str,
        pm_inbox_id: str = "",
        total_steps: int = 6,
        created_by: str = "",
        **kwargs,
    ) -> PipelineContext:
        """创建新管线上下文。"""
        async with self._lock:
            if round_name in self._contexts:
                raise ValueError(f"Pipeline {round_name} already exists")
            now = time.time()
            # Extract known kwargs, rest go to tags
            git_sync_branch = kwargs.pop("git_sync_branch", "dev")
            ctx = PipelineContext(
                round_name=round_name,
                task_kind=task_kind,
                workspace_dir=workspace_dir,
                task_dir=workspace_dir / "pipeline_tasks" / round_name,
                workspace_id=workspace_id,
                pm_inbox_id=pm_inbox_id,
                status=PipelineStatus.INIT,
                current_phase="plan",
                current_step=1,
                total_steps=total_steps,
                blocked_reason=None,
                role_agent_map={},
                agent_card_ids={},
                last_output_sha="",
                git_sync_branch=git_sync_branch,
                created_at=now,
                updated_at=now,
                created_by=created_by,
                tags=kwargs,
            )
            self._contexts[round_name] = ctx
            self._save()
            return ctx

    async def transition_to(
        self, round_name: str, new_status: PipelineStatus,
        blocked_reason: str | None = None,
    ) -> bool:
        """状态转换（校验合法性）。返回 True 表示转换成功。"""
        async with self._lock:
            ctx = self._contexts.get(round_name)
            if not ctx:
                return False
            if not _is_valid_transition(ctx.status, new_status):
                logger.warning(
                    "Invalid transition %s → %s for %s",
                    ctx.status.value, new_status.value, round_name,
                )
                return False
            ctx.status = new_status
            if new_status == PipelineStatus.BLOCKED:
                ctx.blocked_reason = blocked_reason
            elif new_status == PipelineStatus.RUNNING:
                ctx.blocked_reason = None
            ctx.updated_at = time.time()
            self._save()
            return True

    async def advance_step(self, round_name: str) -> bool:
        """推进一步。步数不超过 total_steps，返回是否成功推进。"""
        async with self._lock:
            ctx = self._contexts.get(round_name)
            if not ctx:
                return False
            old = ctx.current_step
            ctx.advance()
            if ctx.status == PipelineStatus.INIT:
                ctx.status = PipelineStatus.RUNNING
            if ctx.status == PipelineStatus.BLOCKED:
                ctx.status = PipelineStatus.RUNNING
                ctx.blocked_reason = None
            ctx.updated_at = time.time()
            self._save()
            logger.info(
                "Pipeline %s step advanced: %d → %d (status=%s)",
                round_name, old, ctx.current_step, ctx.status.value,
            )
            return True

    async def archive(self, round_name: str) -> bool:
        """归档管线：从活跃列表移除，追加到历史 JSONL。"""
        async with self._lock:
            ctx = self._contexts.pop(round_name, None)
            if not ctx:
                return False
            ctx.status = PipelineStatus.COMPLETED
            self._append_history(ctx)
            self._save()
            return True

    async def cancel(self, round_name: str) -> bool:
        """取消管线。"""
        async with self._lock:
            ctx = self._contexts.get(round_name)
            if not ctx:
                return False
            ctx.status = PipelineStatus.CANCELLED
            ctx.updated_at = time.time()
            self._save()
            return True

    # ── R78 A2: 全局角色映射（不关联具体轮次）──

    def set_global_role_map(self, role_agent_map: dict[str, list[str]]) -> None:
        """由 _refresh_role_agent_map() 调用，更新全局快照。"""
        self._global_role_map = role_agent_map

    def get_global_role_map(self) -> dict[str, list[str]]:
        """返回全局角色映射快照。"""
        return dict(getattr(self, "_global_role_map", {}))

    def get_role_agents(self, role: str, round_name: str | None = None) -> list[str]:
        """获取指定角色的 agent 列表。"""
        if round_name:
            ctx = self._contexts.get(round_name)
            if ctx and role in ctx.role_agent_map:
                return ctx.role_agent_map[role]
        return getattr(self, "_global_role_map", {}).get(role, [])

    async def update_role_agent_map_round(
        self, round_name: str, role: str, agent_ids: list[str],
    ) -> bool:
        """更新指定管线的单个角色映射。"""
        async with self._lock:
            ctx = self._contexts.get(round_name)
            if not ctx:
                return False
            ctx.role_agent_map[role] = agent_ids
            ctx.updated_at = time.time()
            self._save()
            return True

    # ── R78 B2: ACK 状态操作 ──

    async def set_ack_state(
        self, round_name: str, step: str, ack_info: dict,
    ) -> bool:
        """设置指定 step 的 ACK 状态。"""
        async with self._lock:
            ctx = self._contexts.get(round_name)
            if not ctx:
                return False
            ctx.ack_states[step] = ack_info
            ctx.updated_at = time.time()
            self._save()
            return True

    def has_ack_for_agent(
        self, round_name: str, step: str, agent_id: str,
    ) -> bool:
        """检查某 agent 是否已对某 step 回复了 ACK。"""
        ctx = self._contexts.get(round_name)
        if not ctx:
            return False
        ack = ctx.ack_states.get(step, {})
        return ack.get("state") == "ACKED" and ack.get("by") == agent_id

    # ── R78 C2: Step 配置操作 ──

    def get_step_config(self, round_name: str) -> dict:
        """获取 step 配置字典（name→dict 格式）。

        优先从 ctx.steps 读取，回退空 dict。
        """
        ctx = self._contexts.get(round_name)
        if ctx and ctx.steps:
            return {s["name"]: s for s in ctx.steps}
        return {}

    async def update_steps(
        self, round_name: str, steps: list[dict],
    ) -> bool:
        """更新管线的 step 配置列表。"""
        async with self._lock:
            ctx = self._contexts.get(round_name)
            if not ctx:
                return False
            ctx.steps = steps
            ctx.updated_at = time.time()
            self._save()
            return True

    async def restore_from_history(
        self, round_name: str,
    ) -> PipelineContext | None:
        """从历史 JSONL 恢复已归档管线。"""
        history = self.get_history(limit=200)
        for entry in history:
            if entry.get("round_name") == round_name:
                ctx = PipelineContext.from_dict(entry)
                if ctx.status in (PipelineStatus.COMPLETED, PipelineStatus.CANCELLED):
                    return None  # 终态不可恢复
                async with self._lock:
                    ctx.status = PipelineStatus.RUNNING if ctx.status == PipelineStatus.BLOCKED else ctx.status
                    ctx.blocked_reason = None if ctx.status == PipelineStatus.RUNNING else ctx.blocked_reason
                    ctx.updated_at = time.time()
                    self._contexts[round_name] = ctx
                    self._save()
                return ctx
        return None

    def get_history(self, limit: int = 20) -> list[dict]:
        """读取历史归档。"""
        path = self._data_dir / _HISTORY_FILE
        if not path.exists():
            return []
        entries = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass
        return entries[-limit:]

    # ── 持久化 ──

    def _save(self) -> None:
        """写活跃上下文到 JSON 文件。IO 异常不回退（logging warning）。"""
        path = self._data_dir / _PERSISTENT_FILE
        try:
            data = {
                round_name: ctx.to_dict() if hasattr(ctx, "to_dict") else ctx
                for round_name, ctx in self._contexts.items()
            }
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (OSError, PermissionError) as e:
            logger.warning("PipelineContext save failed (non-fatal): %s", e)

    def _load(self) -> None:
        """启动时从磁盘恢复活跃上下文。"""
        path = self._data_dir / _PERSISTENT_FILE
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for round_name, d in data.items():
                self._contexts[round_name] = PipelineContext.from_dict(d)
            if self._contexts:
                logger.info(
                    "Restored %d pipeline context(s) from disk",
                    len(self._contexts),
                )
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("PipelineContext load failed: %s", e)

    def _append_history(self, ctx: PipelineContext) -> None:
        """追加已归档上下文到 JSONL 历史文件。"""
        path = self._data_dir / _HISTORY_FILE
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ctx.to_dict(), ensure_ascii=False) + "\n")
        except (OSError, PermissionError) as e:
            logger.warning("PipelineContext history append failed: %s", e)


# ── R110: WORK_PLAN.md frontmatter 解析 ──────────────────────────────

_ROLE_MAP_RE = re.compile(r"(\w+)=(\S+)")


def _parse_work_plan_frontmatter(work_plan_path: str) -> dict:
    """解析 WORK_PLAN.md frontmatter 返回结构化 dict。"""
    head = Path(work_plan_path).read_text(encoding="utf-8")[:500]
    result: dict = {}

    # 轮次名
    m = re.search(r"\*\*轮次：\*\*\s*(R\d+)", head)
    if m:
        result["round_name"] = m.group(1)

    # auto_chain
    m = re.search(r"\*\*auto_chain:\*\*\s*(true|false)", head, re.IGNORECASE)
    if m:
        result["auto_chain"] = m.group(1).lower() == "true"

    # auto_start
    m = re.search(r"\*\*auto_start:\*\*\s*(true|false)", head, re.IGNORECASE)
    if m:
        result["auto_start"] = m.group(1).lower() == "true"

    # 说明/标题
    m = re.search(r"\*\*说明：\*\*\s*(.+)", head)
    if m:
        result["title"] = m.group(1).strip()

    # 角色映射字符串 → dict
    m = re.search(r"\*\*角色映射：\*\*\s*(.+)", head)
    if m:
        raw = m.group(1)
        role_map: dict[str, str] = {}
        for rm in _ROLE_MAP_RE.finditer(raw):
            role_map[rm.group(1)] = rm.group(2)
        result["role_display_map"] = role_map

    return result


# ── R110: 消息模板自动生成 ─────────────────────────────────


def _generate_message_templates(
    round_name: str, work_plan_path: str, repo_path: str,
) -> dict[str, str]:
    """根据轮次名自动生成 6 步派活模板。"""
    r = round_name.lower()
    base = f"https://github.com/datahome73/ws-bridge/blob/main/docs/{round_name}"
    req_url = f"{base}/{round_name}-product-requirements.md"
    wp_url = f"{base}/WORK_PLAN.md"
    tech_url = f"{base}/{r}-step2-tech-plan.md"

    return {
        "step1": (
            f"📋 **{round_name} Step 1 — PM 审核**\n\n"
            f"需求文档已就绪：\n{req_url}\n\n"
            f"请审核后回复 ✅ 完成"
        ),
        "step2": (
            f"🏗️ **{round_name} Step 2 — 技术方案**\n\n"
            f"需求文档：{req_url}\n"
            f"WORK_PLAN：{wp_url}\n\n"
            f"请输出技术方案文档，推 dev 后回复 ✅ 完成"
        ),
        "step3": (
            f"💻 **{round_name} Step 3 — 编码实现**\n\n"
            f"技术方案：{tech_url}\n\n"
            f"按方案实现，推 dev 后回复 ✅ 完成"
        ),
        "step4": (
            f"🔍 **{round_name} Step 4 — 代码审查**\n\n"
            f"审查 Step 3 改动。通过后回复 ✅ 完成"
        ),
        "step5": (
            f"🧪 **{round_name} Step 5 — 测试验证**\n\n"
            f"验证验收标准。全部通过后回复 ✅ 完成"
        ),
        "step6": (
            f"🚀 **{round_name} Step 6 — 合并部署归档**\n\n"
            f"PR dev→main，重建镜像，部署。完成后回复 ✅ 完成"
        ),
    }


def _generate_references(round_name: str) -> dict:
    """生成 references 字典。"""
    base = f"https://github.com/datahome73/ws-bridge/blob/main/docs/{round_name}"
    return {
        "requirements_url": f"{base}/{round_name}-product-requirements.md",
        "work_plan_url": f"{base}/WORK_PLAN.md",
        "tech_plan_url": f"{base}/{round_name.lower()}-step2-tech-plan.md",
    }


def _generate_steps(round_name: str) -> list[dict]:
    """生成默认的 6 步配置列表。"""
    return [
        {"name": "step1", "executor_role": "pm",          "title": "PM 审核"},
        {"name": "step2", "executor_role": "arch",        "title": "技术方案"},
        {"name": "step3", "executor_role": "dev",         "title": "编码实现"},
        {"name": "step4", "executor_role": "review",      "title": "代码审查"},
        {"name": "step5", "executor_role": "qa",          "title": "测试验证"},
        {"name": "step6", "executor_role": "operations",  "title": "合并部署归档"},
    ]


def _find_agent_ids_by_display_name(display_name: str) -> list[str]:
    """从 Agent Card 反向查找 display_name 对应的 agent_id 列表。"""
    try:
        from .agent_card import get_all_cards
        found = []
        for agent_id, info in get_all_cards().items():
            if info.get("display_name") == display_name:
                found.append(agent_id)
        return found
    except (ImportError, Exception):
        return []
