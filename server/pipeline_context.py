"""R77: PipelineContext — 统一管线上下文对象。

包含 PipelineStatus / PipelineTaskKind 枚举,
PipelineContext dataclass (to_dict / from_dict),
PipelineContextManager (CRUD + JSON 持久化 + 并发锁)。
"""

import asyncio
import enum
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("ws-bridge.pipeline_context")


# ── Enums ──────────────────────────────────────────────────────────────


class PipelineStatus(enum.StrEnum):
    """管线状态机 — 6 个状态，5 条合法转换路径。"""
    INIT = "init"
    PLANNING = "planning"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# 合法转换矩阵
_VALID_TRANSITIONS: dict[PipelineStatus, set[PipelineStatus]] = {
    PipelineStatus.INIT: {PipelineStatus.PLANNING, PipelineStatus.CANCELLED},
    PipelineStatus.PLANNING: {PipelineStatus.RUNNING, PipelineStatus.BLOCKED, PipelineStatus.CANCELLED},
    PipelineStatus.RUNNING: {PipelineStatus.BLOCKED, PipelineStatus.COMPLETED, PipelineStatus.CANCELLED},
    PipelineStatus.BLOCKED: {PipelineStatus.RUNNING, PipelineStatus.CANCELLED},
    PipelineStatus.COMPLETED: set(),
    PipelineStatus.CANCELLED: set(),
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
    role_agent_map: dict[str, str] = field(default_factory=dict)     # {"architect": "ws_xxx", ...}
    agent_card_ids: dict[str, str] = field(default_factory=dict)     # {"ws_xxx": card_id, ...}

    # ── Git 同步状态 ──
    last_output_sha: str = ""                        # 上次处理的 commit SHA
    git_sync_branch: str = "dev"                     # 同步分支

    # ── 元信息（审计用）──
    created_at: float = 0.0
    updated_at: float = 0.0
    created_by: str = ""                             # 创建者 agent_id
    tags: dict[str, str] = field(default_factory=dict)  # 可扩展标签

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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineContext":
        """从 JSON 字典反序列化（str → Path, value → enum）。"""
        return cls(
            round_name=d["round_name"],
            task_kind=PipelineTaskKind(d["task_kind"]),
            workspace_dir=Path(d["workspace_dir"]),
            task_dir=Path(d["task_dir"]),
            workspace_id=d["workspace_id"],
            pm_inbox_id=d.get("pm_inbox_id", ""),
            status=PipelineStatus(d["status"]),
            current_phase=d.get("current_phase", "plan"),
            current_step=d.get("current_step", 1),
            total_steps=d.get("total_steps", 6),
            blocked_reason=d.get("blocked_reason"),
            role_agent_map=d.get("role_agent_map", {}),
            agent_card_ids=d.get("agent_card_ids", {}),
            last_output_sha=d.get("last_output_sha", ""),
            git_sync_branch=d.get("git_sync_branch", "dev"),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            created_by=d.get("created_by", ""),
            tags=d.get("tags", {}),
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
                round_name: ctx.to_dict()
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
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("PipelineContext load failed: %s", e)

    def _append_history(self, ctx: PipelineContext) -> None:
        """追加已归档上下文到 JSONL 历史文件。"""
        path = self._data_dir / _HISTORY_FILE
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ctx.to_dict(), ensure_ascii=False) + "\n")
        except (OSError, PermissionError) as e:
            logger.warning("PipelineContext history append failed: %s", e)
