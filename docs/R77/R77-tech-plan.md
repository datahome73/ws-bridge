# R77 技术方案 — PipelineContext：统一管线上下文对象 📋

> **版本：** v1.0
> **状态：** ✅ 技术方案
> **架构师：** 👷 架构师
> **日期：** 2026-07-09
> **基于需求：** docs/R77/R77-product-requirements.md v1.0
> **基线：** `cfe129f`（dev）
> **改动范围：** `server/pipeline_context.py`（新增）+ `server/handler.py` + `server/pipeline_sync.py`

---

## 目录

1. [PipelineContext 数据模型](#1-pipelinecontext-数据模型)
   - [PipelineStatus 枚举](#11-pipelinestatus-枚举)
   - [PipelineTaskKind 枚举](#12-pipelinetaskkind-枚举)
   - [PipelineContext dataclass](#13-pipelinecontext-dataclass)
   - [序列化/反序列化](#14-序列化反序列化)
2. [PipelineContextManager 生命周期](#2-pipelinecontextmanager-生命周期)
   - [CRUD 接口](#21-crud-接口)
   - [JSON 持久化](#22-json-持久化)
   - [并发锁策略](#23-并发锁策略)
3. [handler.py _PIPELINE_STATE 引用点评估](#3-handlerpy-_pipeline_state-引用点评估)
4. [handler.py 集成方案](#4-handlerpy-集成方案)
5. [pipeline_sync.py 改造方案](#5-pipeline_syncpy-改造方案)
6. [改动汇总](#6-改动汇总)
7. [风险与缓解](#7-风险与缓解)

---

## 1. PipelineContext 数据模型

### 1.1 PipelineStatus 枚举

```python
# server/pipeline_context.py

import enum

class PipelineStatus(enum.StrEnum):
    """管线状态机 — 6 个状态，5 条合法转换路径。"""
    INIT = "init"
    PLANNING = "planning"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
```

**合法状态转换矩阵：**

| 当前状态 | 允许的下一个状态 | 触发场景 |
|:---------|:-----------------|:---------|
| `INIT` | `PLANNING`, `CANCELLED` | `create` → WORK_PLAN 就绪 / 取消 |
| `PLANNING` | `RUNNING`, `BLOCKED`, `CANCELLED` | 方案完成进入执行 / 等素材 / 取消 |
| `RUNNING` | `BLOCKED`, `COMPLETED`, `CANCELLED` | 遇到阻塞 / 所有 step 完成 / 取消 |
| `BLOCKED` | `RUNNING`, `CANCELLED` | 阻塞恢复 / 放弃 |
| `COMPLETED` | （终态） | — |
| `CANCELLED` | （终态） | — |

> 合法转换由 `PipelineContextManager.transition_to()` 校验，非法转换返回 `False` 并记日志。

### 1.2 PipelineTaskKind 枚举

```python
class PipelineTaskKind(enum.StrEnum):
    """管线任务类型 — 影响路径默认值。"""
    DEV = "dev"        # 开发任务（默认）
    REVIEW = "review"  # 代码审查
    DEPLOY = "deploy"  # 部署
    DOCS = "docs"      # 文档治理
```

### 1.3 PipelineContext dataclass

```python
@dataclass
class PipelineContext:
    """统一管线上下文 — 纯数据对象，不含 I/O 或业务逻辑。"""

    # ── 身份信息（创建时确定，不可变）──
    round_name: str                     # "R77"
    task_kind: PipelineTaskKind         # 任务类型

    # ── 工作空间（创建时确定）──
    workspace_dir: Path                 # /opt/data/ws-bridge
    task_dir: Path                      # workspace_dir / "pipeline_tasks" / round_name
    workspace_id: str                   # 工作室 ID
    pm_inbox_id: str                    # PM 的 inbox channel ID（各 bot 通过此通道回复 PM）

    # ── 管线运行时状态（随管线推进变化）──
    status: PipelineStatus              # 当前状态（初始 INIT）
    current_phase: str                  # "plan" | "implement" | "review" | "deploy"
    current_step: int                   # step 序号（1-indexed）
    total_steps: int                    # 总 step 数
    blocked_reason: str | None          # status=BLOCKED 时的原因

    # ── 管线成员（角色 → agent_id）──
    role_agent_map: dict[str, str]      # {"architect": "ws_xxx", ...}
    agent_card_ids: dict[str, str]      # {"ws_xxx": card_id, ...}

    # ── Git 同步状态 ──
    last_output_sha: str                # 上次处理的 commit SHA（空 = 首次）
    git_sync_branch: str                # 同步分支（默认 "dev"）

    # ── 元信息（审计用）──
    created_at: float
    updated_at: float
    created_by: str                     # 创建者 agent_id
    tags: dict[str, str]                # 可扩展标签

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
```

### 1.4 序列化/反序列化

`Path` 和 `enum` 需要 JSON 序列化桥接：

```python
def to_dict(self) -> dict:
    """序列化到 JSON 字典（Path → str, enum → value）。"""
    d = {
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
    return d

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
```

---

## 2. PipelineContextManager 生命周期

### 2.1 CRUD 接口

```python
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
        pm_inbox_id: str,
        total_steps: int = 6,
        created_by: str = "",
        **kwargs,
    ) -> PipelineContext:
        """创建新管线上下文。"""
        async with self._lock:
            if round_name in self._contexts:
                raise ValueError(f"Pipeline {round_name} already exists")
            now = time.time()
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
                git_sync_branch=kwargs.pop("git_sync_branch", "dev"),
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

            # 校验转换合法性
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
                ctx.blocked_reason = None  # 清除阻塞原因
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
            # 如果 status 是 BLOCKED，推进时恢复为 RUNNING
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
        path = self._data_dir / "pipeline_contexts_history.jsonl"
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
```

### 2.2 JSON 持久化

```python
# 活跃上下文 — pipeline_contexts.json
_PERSISTENT_FILE = "pipeline_contexts.json"

def _save(self) -> None:
    """写活跃上下文到 JSON 文件。IO 异常不回退（logging warning）。"""
    path = self._data_dir / self._PERSISTENT_FILE
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
        # IO 异常不退出进程，回退到内存状态

def _load(self) -> None:
    """启动时从磁盘恢复活跃上下文。"""
    path = self._data_dir / self._PERSISTENT_FILE
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

# 历史归档 — pipeline_contexts_history.jsonl
def _append_history(self, ctx: PipelineContext) -> None:
    """追加已归档上下文到 JSONL 历史文件。"""
    path = self._data_dir / "pipeline_contexts_history.jsonl"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ctx.to_dict(), ensure_ascii=False) + "\n")
    except (OSError, PermissionError) as e:
        logger.warning("PipelineContext history append failed: %s", e)
```

**持久化文件结构：**

```json
// pipeline_contexts.json — 所有活跃管线
{
  "R77": {
    "round_name": "R77",
    "task_kind": "dev",
    "status": "running",
    "current_step": 2,
    "total_steps": 6,
    "role_agent_map": {
      "architect": "ws_3f7cdd736c1c",
      "developer": "ws_0bb747d3ea2a"
    },
    "created_at": 1749200000.0,
    "updated_at": 1749200500.0,
    ...
  },
  "R76": {
    "round_name": "R76",
    "task_kind": "dev",
    "status": "completed",
    ...
  }
}

// pipeline_contexts_history.jsonl — 已归档历史（追加写）
{"round_name": "R75", "task_kind": "docs", "status": "completed", ...}
{"round_name": "R74", "task_kind": "dev", "status": "completed", ...}
```

### 2.3 并发锁策略

| 锁 | 作用域 | 类型 | 说明 |
|:---|:-------|:-----|:------|
| `self._lock` | Manager 实例级 | `asyncio.Lock()` | 保护所有写操作（create/transition/advance/archive/cancel） |
| 读操作 | 无需锁 | — | `get()` / `get_all_active()` 不修改状态 |

**与 workspace 模块的一致性：** workspace 模块使用 `_lock` 保护 `update_agent()` 等写入，本方案采用相同模式。

**锁范围说明：**
- `create` → 加锁：检查存在性 → 写入 _contexts → _save()
- `advance_step` → 加锁：读取 → 修改 → _save()
- `_save()` → 在锁内调用（确保串行写盘）
- `_load()` → 初始化时调用（无并发）

---

## 3. handler.py _PIPELINE_STATE 引用点评估

### 3.1 引用点全量统计

对 `server/handler.py` 的 `_PIPELINE_STATE` 进行了全量 grep，共 **40+ 处引用**，分类如下：

| 类别 | 位置/函数 | 行号 | 用量 | Phase |
|:-----|:----------|:----:|:----:|:------|
| **初始定义** | 模块级 `= {}` | L47 | 1 | → Manager 替代 |
| **层次辅助函数** | `_set_pipeline_state()` | L1316 | 1 | → Manager.create |
| | `_update_pipeline_step()` | L1320 | 1 | → Manager.advance_step |
| | `_clear_pipeline_state()` | L1325 | 1 | → Manager.archive / cancel |
| | `pipeline_is_active()` | L1330 | 1 | → Manager.get().is_active() |
| | `pipeline_exists()` | L1335 | 1 | → Manager.exists() |
| **自动推进** | `_pipeline_git_sync_scan()` | L1401 | 5 | 读取 ws_id/active/step/last_sha/git_sync_ts |
| | `_auto_advance_pipeline()` | L1434 | 2 | 读取 pstate/current_step |
| **看门狗** | `_watchdog_scan()` | L1560 | 6 | 遍历活跃 + timeout/step/ws_id 读取 |
| **Admin 命令** | `_cmd_active_workspaces()` | L1729 | 1 | 遍历 |
| | `_cmd_pipeline_info()` | L1783 | 1 | 遍历 |
| | `_handle_status()` | L1918-1967 | 3 | pstate.get |
| | `_cmd_pipeline_start()` | L2352-2392 | 3 | ws_id/current_step/xz_info |
| **Pipeline 执行** | `_cmd_pipeline_start_loop()` | L2530/2539 | 2 | 遍历 + 读取 |
| | `_cmd_step_complete()` | L2587 | 1 | 读取 |
| | `_cmd_step_fallback()` | L2611 | 1 | triggerer_id 读取 |
| | `_cmd_agent_status()` | L2960 | 1 | 遍历 |
| | `_cmd_pipeline_block()` | L3039 | 1 | pstate.get |
| | `_cmd_pipeline_resume()` | L3122 | 1 | 遍历 |
| | `_cmd_pipeline_reject()` | L3175-3186 | 2 | setdefault + get |
| | `_cmd_close_workspace()` | L3255/3257 | 2 | 遍历 + active=False |
| | `_cmd_delegate_start()` | L3283 | 1 | 遍历 |
| | `_cmd_pipeline_shrink()` | L3358 | 1 | pstate.get |
| | `_report_interrupted_context()` | L3472 | 2 | 遍历 |
| | `_format_status()` 等 UI 函数 | L3488-3495 | 2 | 遍历 |
| | `_set_pipeline_mode()` | L3633-3640 | 2 | 遍历 + 写入 |
| | `task_notify()` | L4094 | 1 | 存在性检查 |

### 3.2 Phase 1 迁移范围（本轮）

| 迁移范围 | 函数/位置 | 行数 | 策略 |
|:---------|:----------|:----:|:-----|
| **全部迁移** | 6 个层次辅助函数 | L1316-L1337 | 替换为 Manager 调用 |
| **全部迁移** | `_save_pipeline_state()` 系列 | — | 由 Manager 内部处理 |
| **读路径迁移** | `_auto_advance_pipeline()` | L1434 | `_pipeline_manager.get().status` |
| **读路径迁移** | `_watchdog_scan()` | L1572 | `_pipeline_manager.get_all_active()` |
| **读路径迁移** | `_pipeline_git_sync_scan()` | L1401 | `_pipeline_manager.get_all_active()` |
| **读路径迁移** | `_cmd_pipeline_info()` / `_cmd_active_workspaces()` | L1729-1783 | 切换读取源 |
| **读路径迁移** | `_handle_status()` | L1918 | `_pipeline_manager.get().to_dict()` |
| **读路径迁移** | `_cmd_pipeline_start()` | L2352 | `_pipeline_manager.get().workspace_id` |
| **读路径迁移** | `_cmd_step_complete()` | L2587 | 从 context 读取 |
| **读路径迁移** | `_cmd_close_workspace()` | L3255 | 从 context 读取 ws_id |
| **写路径迁移** | `_cmd_pipeline_block()` | L3039 | `_pipeline_manager.transition_to(BLOCKED)` |
| **写路径迁移** | `_cmd_pipeline_reject()` | L3175 | Manager 统一管理 |
| **写路径迁移** | `_cmd_close_workspace()` | L3257 | Manager.archive / cancel |
| **写路径迁移** | `_cmd_pipeline_start()` 创建 | L2120 | `_pipeline_manager.create()` |
| **保留 deprecated** | `_cmd_pipeline_reject()` 细节 | L3176 | `_PIPELINE_STATE.setdefault` 包装 |

### 3.3 兼容策略：deprecated 桥接

```python
# 在初始阶段，保留 _PIPELINE_STATE 作为 Manager 的读取桥接
# 使所有现有读代码继续工作，零侵入

@property
def _PIPELINE_STATE(self) -> dict[str, dict]:
    """⚠️ Deprecated: 使用 _pipeline_manager 替代。
    
    桥接到 Manager，使现有读代码（~40 处引用）不动，
    逐步迁移到新接口。
    """
    bridge = {}
    for rn, ctx in self._contexts.items():
        d = ctx.to_dict()
        d["active"] = ctx.is_active()
        bridge[rn] = d
    return bridge
```

> **⚠️ 注意：** `_PIPELINE_STATE` 是模块级全局变量，不是实例属性。上述 bridge 是概念设计。实际实现中，可以选择：
>
> **方案 A（推荐）：** 在 handler.py 模块级保留 `_PIPELINE_STATE` 作为运行时桥接变量，由 Manager 的 `_save()` 同步更新。新代码读取 Manager，旧代码继续读 `_PIPELINE_STATE`。
>
> **方案 B：** 直接替换所有 ~40 处引用。本技术方案推荐**方案 A**——保留桥接但标记 deprecated，分批替换。

---

## 4. handler.py 集成方案

### 4.1 初始化集成

```python
# 在 handler.py 模块级初始化
from .pipeline_context import PipelineContextManager

_pipeline_manager: PipelineContextManager | None = None

def _ensure_pipeline_manager() -> PipelineContextManager:
    """惰性初始化 Manager。"""
    global _pipeline_manager
    if _pipeline_manager is None:
        _pipeline_manager = PipelineContextManager(data_dir=config.DATA_DIR)
    return _pipeline_manager

# 在 server 启动时调用（与 workspace 模块的 _ensure_workspace_manager 一致）
_ensure_pipeline_manager()
```

### 4.2 ！pipeline 命令路由

```python
# 在 _ADMIN_COMMANDS 中注册
"pipeline": {
    "handler": _handle_pipeline_command,
    "description": "管线上下文管理",
    "syntax": "!pipeline <create|status|list|advance|block|archive|cancel> [args]",
    "min_role": "admin",
}

async def _handle_pipeline_command(sender_id: str, params: str) -> str:
    """处理 !pipeline 子命令。"""
    parts = params.strip().split(maxsplit=2)
    subcmd = parts[0] if len(parts) >= 1 else ""
    mgr = _ensure_pipeline_manager()

    if subcmd == "create":
        # !pipeline create R77 dev [--total_steps 6]
        round_name = parts[1] if len(parts) >= 2 else ""
        task_kind = parts[2] if len(parts) >= 3 else "dev"
        if not round_name:
            return "❌ 用法: !pipeline create <round> <kind>"
        ctx = await mgr.create(
            round_name=round_name,
            task_kind=PipelineTaskKind(task_kind),
            workspace_dir=Path(config.REPO_PATH),
            workspace_id="",
            pm_inbox_id="",
            created_by=sender_id,
        )
        return f"✅ Pipeline {round_name} created (kind={task_kind}, status={ctx.status.value})"

    elif subcmd == "status":
        # !pipeline status [R77]
        round_name = parts[1] if len(parts) >= 2 else ""
        if round_name:
            ctx = mgr.get(round_name)
            if not ctx:
                return f"❌ Pipeline {round_name} not found"
            return _format_pipeline_context(ctx)
        # 无参数 → 显示所有活跃
        return _format_all_pipelines(mgr.get_all_active())

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

    return "❌ 未知子命令。支持: create, status, list, advance, block, archive, cancel"


def _format_pipeline_context(ctx: PipelineContext) -> str:
    """格式化 PipelineContext 为人类可读文本。"""
    lines = [
        f"📋 {ctx.round_name} [{ctx.task_kind.value}]",
        f"  状态: {ctx.status.value}",
        f"  Step: {ctx.current_step}/{ctx.total_steps}",
        f"  阶段: {ctx.current_phase}",
        f"  活跃: {'✅' if ctx.is_active() else '❌'}",
        f"  创建: {datetime.fromtimestamp(ctx.created_at).strftime('%m/%d %H:%M')}",
    ]
    if ctx.blocked_reason:
        lines.append(f"  阻塞原因: {ctx.blocked_reason}")
    if ctx.role_agent_map:
        roles = ", ".join(f"{r}={a[:12]}" for r, a in ctx.role_agent_map.items())
        lines.append(f"  成员: {roles}")
    return "\n".join(lines)
```

### 4.3 旧命令兼容

```python
# 现有命令保持兼容
async def _cmd_pipeline_state(sender_id: str, params: str) -> str:
    """旧 !pipeline_state 命令 → 桥接到 Manager。"""
    mgr = _ensure_pipeline_manager()
    round_name = params.strip()
    if round_name:
        ctx = mgr.get(round_name)
        if not ctx:
            return "❌ 管线不存在"
        return _format_pipeline_context(ctx)
    return _format_all_pipelines(mgr.get_all_active())
```

---

## 5. pipeline_sync.py 改造方案

### 5.1 当前接口

```python
# 当前:
class PipelineGitSync:
    def __init__(self, pipeline_id: str, config: dict):
        self.branch = config.get("branch", "dev")
        self.repo_path = config.get("repo_path", "/opt/data/ws-bridge")
        self.last_sha = config.get("last_sha", "")
        self.fallback_enabled = config.get("fallback_enabled", True)
```

### 5.2 改造后接口

```python
# 改造后:
class PipelineGitSync:
    def __init__(self, context: PipelineContext):
        """从统一上下文读取配置，替代零散 dict。"""
        self.pipeline_id = context.round_name
        self.branch = context.git_sync_branch
        self.repo_path = str(context.workspace_dir)
        self.last_sha = context.last_output_sha
        self.fallback_enabled = True  # 从 context.tags 可选读取
        self._lock = asyncio.Lock()
```

### 5.3 调用处改造

**`_pipeline_git_sync_scan()` 中的当前调用（L1401-L1420）：**

```python
# 当前:
for pid, pstate in list(_PIPELINE_STATE.items()):
    if not pstate.get("active"):
        continue
    pconfig = _PIPELINE_CONFIG.get(pid, {})
    sync_config = {
        "branch": pconfig.get("git_sync_branch", config.GIT_SYNC_BRANCH),
        "repo_path": pconfig.get("repo_path", config.REPO_PATH),
        "last_sha": pstate.get("last_output_sha", ""),
        "fallback_enabled": config.GIT_SYNC_FALLBACK,
    }
    syncer = PipelineGitSync(pid, sync_config)

# 改造后:
for ctx in _pipeline_manager.get_all_active():
    if not ctx.is_active():
        continue
    syncer = PipelineGitSync(ctx)
```

---

## 6. 改动汇总

### 6.1 文件清单

| 文件 | 改动类型 | 行数估算 | 说明 |
|:-----|:---------|:--------:|:-----|
| `server/pipeline_context.py` | **新增** | ~130 行 | dataclass + 枚举 + Manager + JSON 持久化 |
| `server/handler.py` | 新增初始化 | ~10 行 | `_ensure_pipeline_manager()` + `_pipeline_manager` |
| `server/handler.py` | 新增 `!pipeline` 命令路由 | ~60 行 | 7 个子命令处理 |
| `server/handler.py` | 旧命令桥接 | ~5 行 | `!pipeline_state` 兼容 |
| `server/handler.py` | `_pipeline_git_sync_scan()` 改造 | ~5 行 | 从 Dict → PipelineContext |
| `server/pipeline_sync.py` | 构造器改造 | ~5 行 | `config: dict` → `context: PipelineContext` |
| **合计** | | **~215 行净增** | |

### 6.2 无改动项

| 模块 | 原因 |
|:-----|:------|
| `server/shared/protocol.py` | 本轮不新增协议消息类型 |
| `server/workspace.py` | workspace 管理独立 |
| `server/task_store.py` | 任务存储独立 |
| `server/agent_card.py` | Agent Card 系统独立 |
| `clients/python/ws_client.py` | 客户端不变 |
| 各 bot 代码 | 行为不变 |

### 6.3 操作顺序

```
1. 新增 server/pipeline_context.py          — dataclass + 枚举 + Manager
2. handler.py 初始化集成                     — _ensure_pipeline_manager()
3. handler.py 新增 !pipeline 命令路由        — 7 个子命令
4. handler.py 旧命令桥接                    — !pipeline_state 兼容
5. server/pipeline_sync.py 构造器改造       — config → context
6. handler.py _pipeline_git_sync_scan 改造   — 遍历 Manager
7. 验证                                     — !pipeline 命令测试
8. commit + push
```

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:-----|:---------|
| `_PIPELINE_STATE` ~40 处引用点改造遗漏 | 中 | 功能异常或丢失状态 | Phase 1 使用 deprecated 桥接方案保留旧变量，新代码走 Manager |
| JSON 持久化 IO 异常导致进程退出 | 低 | 高 | 所有 `_save()` / `_load()` 写 try/except，IO 失败仅 log warning |
| Manager 未初始化时被 handler 调用 | 低 | 中 | `_ensure_pipeline_manager()` 惰性初始化模式 |
| `!pipeline create` 与 `!pipeline_start` 重复创建 | 中 | 中 | Manager.create() 检查 round_name 存在性，已存在则报错 |
| 并发 advance 导致 step 跳跃 | 低 | 低 | `asyncio.Lock` 确保原子操作 |
| 服务器在不恰当时间重启 | 低 | 低 | `_load()` 从磁盘恢复所有活跃上下文，状态与关闭前一致 |
| `datetime` → `float` 时间戳兼容 | 低 | 低 | 统一使用 `time.time()` 获取 float 时间戳 |

---

## 8. 设计决策确认清单

| # | 决策项 | 决策 | 状态 |
|:-:|:-------|:-----|:----:|
| 1 | PipelineContext dataclass 字段 | 18 个字段 + 5 个 property（见 §1.3） | ✅ 确认 |
| 2 | PipelineStatus 状态机 | 6 状态，5 条合法转换矩阵（见 §1.1） | ✅ 确认 |
| 3 | PipelineTaskKind 枚举 | 4 类型: dev/review/deploy/docs | ✅ 确认 |
| 4 | 持久化路径 | `DATA_DIR/pipeline_contexts.json` + `_history.jsonl` | ✅ 确认 |
| 5 | 并发锁 | `asyncio.Lock`（实例级，保护所有写操作） | ✅ 确认 |
| 6 | _PIPELINE_STATE 迁移策略 | Phase 1 保留旧变量标记 deprecated，~40 处引用分批迁移 | ✅ 确认 |
| 7 | PipelineGitSync 改造 | `config: dict` → `context: PipelineContext` | ✅ 确认 |

---

## 9. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-09 | 初稿 — R77 技术方案：PipelineContext dataclass + PipelineContextManager 生命周期 + handler.py 集成 + _PIPELINE_STATE 引用点评估（~40 处） |
