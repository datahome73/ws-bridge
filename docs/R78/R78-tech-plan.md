# R78 技术方案 — 全局变量迁移补完：角色映射 + ACK 状态统一管理 📐

> **版本：** v1.0
> **状态：** ✅ 技术方案
> **架构师：** 👷 架构师
> **日期：** 2026-07-09
> **基于需求：** docs/R78/R78-product-requirements.md v1.0
> **基线：** `4baedba`（main — R77 合并部署）
> **改动范围：** `server/pipeline_context.py` `server/handler.py` `server/agent_card.py`

---

## 目录

1. [方向 A：_ROLE_AGENT_MAP → PipelineContext 统一](#1-方向-a_role_agent_map--pipelinecontext-统一)
   - [A1 — 类型修复](#a1--类型修复)
   - [A2 — Manager 新增方法](#a2--manager-新增方法)
   - [A3 — agent_card.py 5 行适配](#a3--agent_cardpy-5-行适配)
   - [A4 — handler.py 19 处引用迁移](#a4--handlerpy-19-处引用迁移)
2. [方向 B：_step_ack_states → PipelineContext.ack_states](#2-方向-b_step_ack_states--pipelinecontextack_states)
   - [B1 — dataclass 字段](#b1--dataclass-字段)
   - [B2 — Manager ACK 操作方法](#b2--manager-ack-操作方法)
   - [B3 — handler.py 11 处引用迁移](#b3--handlerpy-11-处引用迁移)
3. [方向 C：_PIPELINE_CONFIG steps 部分迁移](#3-方向-c_pipeline_config-steps-部分迁移)
   - [C1 — dataclass 字段](#c1--dataclass-字段)
   - [C2 — Manager 方法](#c2--manager-方法)
   - [C3 — handler.py 28 处引用中 10 处高频点迁移](#c3--handlerpy-28-处引用中-10-处高频点迁移)
4. [方向 D：!pipeline 命令增强](#4-方向-dpipeline-命令增强)
5. [改动汇总](#5-改动汇总)
6. [兼容性与循环 import 分析](#6-兼容性与循环-import-分析)
7. [风险与缓解](#7-风险与缓解)

---

## 1. 方向 A：_ROLE_AGENT_MAP → PipelineContext 统一

### A1 — 类型修复

**当前：** `PipelineContext.role_agent_map: dict[str, str]`（单值）
**目标：** `PipelineContext.role_agent_map: dict[str, list[str]]`（多值）

```python
@dataclass
class PipelineContext:
    # ...
    role_agent_map: dict[str, list[str]] = field(default_factory=dict)
    # {"architect": ["ws_xxx"], "developer": ["ws_yyy", "ws_zzz"], ...}
```

**向后兼容：** `from_dict()` 中检测旧 JSON 格式（单值 str），自动包装为 `[v]`。

```python
@classmethod
def from_dict(cls, d: dict) -> "PipelineContext":
    raw_role_map = d.get("role_agent_map", {})
    # R78 A1: 兼容旧格式（单值 str → 多值 list[str]）
    if raw_role_map and isinstance(next(iter(raw_role_map.values())), str):
        role_agent_map = {k: [v] for k, v in raw_role_map.items()}
    else:
        role_agent_map = raw_role_map
    # ...
```

**`_format_pipeline_context()` 同步更新：**

```python
# 旧: f"  成员: {r}={a[:12]}"
# 新: f"  成员: {r}={','.join(a[:12] for a in agents)}"
if ctx.role_agent_map:
    parts = []
    for role, agents in ctx.role_agent_map.items():
        agents_str = ",".join(a[:12] for a in agents)
        parts.append(f"{role}={agents_str}")
    lines.append(f"  成员: {'; '.join(parts)}")
```

### A2 — Manager 新增方法

```python
class PipelineContextManager:
    def __init__(self, data_dir: Path):
        # ... 现有初始化 ...
        self._global_role_map: dict[str, list[str]] = {}  # 角色→agent 列表全局快照

    # ── 全局角色映射（不关联具体轮次）──

    def set_global_role_map(self, role_agent_map: dict[str, list[str]]) -> None:
        """由 _refresh_role_agent_map() 调用，更新全局快照。"""
        self._global_role_map = role_agent_map

    def get_global_role_map(self) -> dict[str, list[str]]:
        """返回全局角色映射快照。"""
        return dict(self._global_role_map)

    def get_role_agents(self, role: str, round_name: str | None = None) -> list[str]:
        """获取指定角色的 agent 列表。

        有 round_name 时优先从对应 PipelineContext 读取。
        无 round_name 或对应管线不存在时回退到全局快照。
        """
        if round_name:
            ctx = self._contexts.get(round_name)
            if ctx and role in ctx.role_agent_map:
                return ctx.role_agent_map[role]
        return self._global_role_map.get(role, [])

    # ── 单个管线的角色映射更新 ──

    async def update_role_agent_map(
        self,
        role_agent_map: dict[str, list[str]],
    ) -> None:
        """全局更新所有活跃 PipelineContext 的 role_agent_map。

        由 _refresh_role_agent_map() 调用（Agent Card 变更时触发）。
        同时更新全局快照，保持双写一致性。
        """
        async with self._lock:
            self._global_role_map = role_agent_map
            for ctx in self._contexts.values():
                # 仅更新有 role_agent_map 的管线
                if ctx.is_active():
                    ctx.role_agent_map = {
                        role: agents
                        for role, agents in role_agent_map.items()
                        if role in ctx.role_agent_map  # 仅保留该管线已关联的角色
                    } or dict(role_agent_map)  # 无关联则全量
                    ctx.updated_at = time.time()
            self._save()

    async def update_role_agent_map_round(
        self,
        round_name: str,
        role: str,
        agent_ids: list[str],
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
```

### A3 — agent_card.py 5 行适配

**当前（L383-391）：**

```python
# Update _ROLE_AGENT_MAP from handler for role-based routing
if pipeline_roles:
    try:
        from . import handler as _handler_mod
        for r in pipeline_roles:
            if r not in _handler_mod._ROLE_AGENT_MAP:
                _handler_mod._ROLE_AGENT_MAP[r] = []
            if agent_id not in _handler_mod._ROLE_AGENT_MAP[r]:
                _handler_mod._ROLE_AGENT_MAP[r].append(agent_id)
    except Exception:
        pass
```

**改造后：**

```python
# R78 A3: Update role-agent map via PipelineContextManager
if pipeline_roles:
    try:
        # 先走 Manager（新路径）
        from . import pipeline_context as _pc_mod
        mgr = _get_pipeline_context_manager()
        if mgr:
            # 从当前全局角色映射读取
            current_map = mgr.get_global_role_map()
            for r in pipeline_roles:
                if agent_id not in current_map.setdefault(r, []):
                    current_map[r].append(agent_id)
            mgr.set_global_role_map(current_map)

        # 同时写旧变量（双写保险，过渡期后删除）
        from . import handler as _handler_mod
        _handler_mod._ROLE_AGENT_MAP = dict(current_map)
    except Exception:
        pass


def _get_pipeline_context_manager():
    """获取 PipelineContextManager 实例（避免循环 import）。"""
    try:
        from . import handler as _h
        if hasattr(_h, '_pipeline_manager'):
            return _h._pipeline_manager
    except Exception:
        pass
    try:
        import sys
        mod = sys.modules.get('server.handler')
        if mod and hasattr(mod, '_pipeline_manager'):
            return mod._pipeline_manager
    except Exception:
        pass
    return None
```

> **循环 import 分析：** `agent_card.py` 通过 `sys.modules.get('server.handler')` 或现有模式 `from . import handler as _handler_mod` 访问 handler 模块变量——不会触发新的 import cycle，因为 handler.py 在初始化时已经 `from . import agent_card as ac_mod`，循环 import 只会在「模块加载时相互 import 且构造函数在顶层执行」时发生，运行时惰性引用是安全的。

### A4 — handler.py 19 处引用迁移

**关键迁移点：**

| # | 位置 | 当前代码 | 迁移后 |
|:-:|:-----|:---------|:-------|
| L56 | 声明 | `_ROLE_AGENT_MAP: dict[str, list[str]] = {}` | 保留 `# DEPRECATED — use PipelineContextManager` |
| L986-1006 | `_refresh_role_agent_map()` | 直接写 `_ROLE_AGENT_MAP` | 改为写 `_pipeline_manager.set_global_role_map()` + 双写旧变量 |
| L1052 | `_get_agents_by_role()` | `_ROLE_AGENT_MAP.get(role, [])` | `_pipeline_manager.get_role_agents(role, round_name)` |
| L1650+ | _cmd_pipeline_info 等 | `_ROLE_AGENT_MAP.get(...)` | `mgr.get_role_agents(...)` |
| L4054 | `!agent_role_map` 展示 | 读 `_ROLE_AGENT_MAP` | 读 `mgr.get_global_role_map()` |
| L4057 | `!agent_role_map` 写入 | 直接写 `_ROLE_AGENT_MAP` | 改走 `mgr.set_global_role_map()` + 双写 |

**`_get_agents_by_role()` 改造：**

```python
def _get_agents_by_role(role: str, round_name: str | None = None) -> list[str]:
    """通过 PipelineContextManager 获取指定角色的 agent 列表。

    优先从管线上下文的 role_agent_map 读取（如果提供了 round_name）。
    无管线上下文时回退到全局角色映射快照。
    """
    mgr = _ensure_pipeline_manager()
    return mgr.get_role_agents(role, round_name)
```

---

## 2. 方向 B：_step_ack_states → PipelineContext.ack_states

### B1 — dataclass 字段

```python
@dataclass
class PipelineContext:
    # ...
    ack_states: dict[str, dict] = field(default_factory=dict)
    # Key: step_name (e.g. "step2")
    # Value: {
    #   "state": str,           # "PENDING" | "ACKED" | "TIMEOUT" | "FAILED"
    #   "assigned_to": str,     # agent_id
    #   "assigned_at": float,   # timestamp
    #   "acked_at": float | None,
    #   "role_name": str,       # display role for UI
    # }
```

**思路迁移：** 旧变量使用 `"{round}/{step}"` 作为 key（全局 key），新字段使用 `step_name` 作为 key（上下文内 key，round 已在 PipelineContext 中）。所有 `_step_ack_states[f"{round}/{step}"]` 改为 `ctx.ack_states[step]`。

### B2 — Manager ACK 操作方法

```python
class PipelineContextManager:
    async def set_ack_state(
        self, round_name: str, step_name: str,
        state: str, assigned_to: str = "",
        role_name: str = "",
    ) -> bool:
        """设置某个 step 的 ACK 状态。"""
        async with self._lock:
            ctx = self._contexts.get(round_name)
            if not ctx:
                return False
            existing = ctx.ack_states.get(step_name, {})
            existing["state"] = state
            existing["assigned_to"] = assigned_to or existing.get("assigned_to", "")
            if state == "PENDING" and "assigned_at" not in existing:
                existing["assigned_at"] = time.time()
            if state == "ACKED":
                existing["acked_at"] = time.time()
            existing["role_name"] = role_name or existing.get("role_name", "")
            ctx.ack_states[step_name] = existing
            ctx.updated_at = time.time()
            self._save()
            return True

    def get_ack_state(self, round_name: str, step_name: str) -> dict | None:
        """读取某个 step 的 ACK 状态。"""
        ctx = self._contexts.get(round_name)
        if not ctx:
            return None
        return ctx.ack_states.get(step_name)

    def has_ack_for_agent(self, round_name: str, agent_id: str) -> bool:
        """检查 agent 在当前管线是否有未完成的 ACK。"""
        ctx = self._contexts.get(round_name)
        if not ctx:
            return False
        return any(
            s.get("assigned_to") == agent_id and s.get("state") == "PENDING"
            for s in ctx.ack_states.values()
        )
```

### B3 — handler.py 11 处引用迁移

**写入点（L1493-1495, L2858）：**

```python
# L1493-1495 当前：
if old_ack_key in _step_ack_states:
    if _step_ack_states[old_ack_key].get("state") == "FAILED":
        _step_ack_states.pop(old_ack_key, None)

# 迁移后：
mgr = _ensure_pipeline_manager()
old_step = old_ack_key.split("/")[-1]  # "R77/step2" → "step2"
old_state = mgr.get_ack_state(round_name, old_step)
if old_state and old_state.get("state") == "FAILED":
    # 不需要删除，直接覆盖新状态
    pass
```

```python
# L2858 当前：
_step_ack_states[ack_key] = {
    "state": "PENDING",
    "assigned_to": target_agent_id,
    "assigned_at": time.time(),
    "role_name": role_name,
}

# 迁移后：
ack_round = round_name  # 从 ack_key "R77/step2" 中提取
ack_step = step_name
await mgr.set_ack_state(ack_round, ack_step, "PENDING",
    assigned_to=target_agent_id, role_name=role_name)
# 双写旧变量（过渡期）
_step_ack_states[ack_key] = {...}
```

**读取点（L1720, L1778, L1829, L1844, L1859, L1864）：**

最高频的读取点在 `_build_pipeline_info_lines()`（L1720）和 `_format_pipeline_info()`（L1829-1876）。

```python
# L1720 当前：
state = _step_ack_states.get(ack_key, {})

# 迁移后：
mgr = _ensure_pipeline_manager()
state = mgr.get_ack_state(round_name, step_name) or {}
```

```python
# L1844 当前（遍历所有 ack_states）：
for ack_key, ack_state in _step_ack_states.items():

# 迁移后（从 PipelineContext 读取）：
ctx = mgr.get(round_name)
all_ack_states = ctx.ack_states if ctx else {}
for step_name, ack_state in all_ack_states.items():
```

---

## 3. 方向 C：_PIPELINE_CONFIG steps 部分迁移

### C1 — dataclass 字段

```python
@dataclass
class PipelineContext:
    # ...
    steps: list[dict] = field(default_factory=list)
    # [
    #   {"name": "step1", "executor_role": "arch",
    #    "timeout_minutes": 120, "description": "技术方案"},
    #   {"name": "step2", "executor_role": "dev", ...},
    # ]
```

### C2 — Manager 方法

```python
class PipelineContextManager:
    async def update_steps(
        self, round_name: str, steps: list[dict],
    ) -> bool:
        """更新管线的 step 配置。"""
        async with self._lock:
            ctx = self._contexts.get(round_name)
            if not ctx:
                return False
            ctx.steps = steps
            ctx.total_steps = len(steps)
            ctx.updated_at = time.time()
            self._save()
            return True

    def get_step_config(self, round_name: str, step_name: str) -> dict:
        """获取指定 step 的配置。

        优先从 PipelineContext.steps 读取。
        读不到则回退到 _PIPELINE_CONFIG（旧路径）。
        """
        ctx = self._contexts.get(round_name)
        if ctx and ctx.steps:
            for s in ctx.steps:
                if s.get("name") == step_name:
                    return s
        # Fallback: 旧路径
        _pconfig = _PIPELINE_CONFIG.get(round_name, {})
        return _pconfig.get("steps", {}).get(step_name, {})
```

### C3 — handler.py 28 处引用中 10 处高频点迁移

**首批迁移的 10 处高频点：**

| # | 函数 | 行号 | 当前 | 迁移后 |
|:-:|:-----|:----:|:-----|:-------|
| 1 | `_cmd_pipeline_start` | L2148 | `pconfig = _PIPELINE_CONFIG.get(round_name, {})` | 复用本地变量 `config_data`（删除全局变量读取） |
| 2 | `_cmd_pipeline_start` 创建 ctx 后 | L2120+ | 无 steps 写入 | `await mgr.update_steps(round_name, steps)` |
| 3 | `_get_step_config()` | L1651 | `_PIPELINE_CONFIG.get(round, {}).get("steps", {}).get(step, {})` | `mgr.get_step_config(round, step)` |
| 4 | `_cmd_pipeline_info` | L1783 | `_PIPELINE_CONFIG.get` | `mgr.get_step_config()` |
| 5 | `_watchdog_scan` | L1600+ | `_PIPELINE_CONFIG.get` 读 timeout | `mgr.get_step_config().get("timeout_minutes")` |
| 6 | `_auto_advance_pipeline` | L1438 | `_get_step_config(round_name)`（间接读 _PIPELINE_CONFIG） | 走 Manager 同一方法 |
| 7 | `_cmd_step_complete` | L2393 | `_pconfig = _PIPELINE_CONFIG.get(round_name, {})` | `ctx = mgr.get(round_name); steps = ctx.steps` |
| 8 | `_cmd_step_fallback` | L2611 | `_PIPELINE_CONFIG.get` | `mgr.get_step_config()` |
| 9 | `_handle_status` | L1918 | `_PIPELINE_CONFIG.get(round_name, {}).get("work_plan_url")` | 从 `ctx.work_plan_path` 派生 |
| 10 | `_report_interrupted_context` | L3400 | `_PIPELINE_CONFIG.get(round_name, {}).get("work_plan_url")` | `mgr.get(round_name).work_plan_path` |

**`_cmd_pipeline_start` 中的写入集成（L2095-2148）：**

```python
# R78 C3: frontmatter 解析后，将 steps 写入 PipelineContext
if pipeline_ctx and parsed_steps:
    await mgr.update_steps(round_name, parsed_steps)
```

```python
def _extract_steps_from_frontmatter(frontmatter: dict) -> list[dict]:
    """从 WORK_PLAN frontmatter 提取 step 配置列表。
    
    frontmatter 格式:
      pipeline:
        steps:
          - step: 2
            role: architect
            task: 技术方案
    
    返回:
      [{"name": "step2", "executor_role": "arch", "description": "技术方案"}, ...]
    """
    pipeline = frontmatter.get("pipeline", {})
    raw_steps = pipeline.get("steps", [])
    # 也兼容 steps 为 dict 格式
    if isinstance(raw_steps, dict):
        return [
            {"name": k, "executor_role": v.get("role", ""), "description": v.get("title", "")}
            for k, v in raw_steps.items()
        ]
    return [
        {
            "name": f"step{s.get('step', i+1)}",
            "executor_role": s.get("role", ""),
            "description": s.get("task", ""),
            "timeout_minutes": s.get("timeout_minutes", 60),
        }
        for i, s in enumerate(raw_steps)
    ]
```

**`_get_step_config()` 改造：**

```python
def _get_step_config(round_name: str) -> dict:
    """获取指定轮次的 step 配置。

    R78: 优先从 PipelineContext.steps 读取（Key → value 格式）。
    读不到则回退到 _PIPELINE_CONFIG（旧格式兼容）。
    """
    mgr = _ensure_pipeline_manager()
    ctx = mgr.get(round_name)
    if ctx and ctx.steps:
        # 转换为 dict[str, dict] 格式（兼容旧代码预期的返回值格式）
        return {s["name"]: s for s in ctx.steps}
    # Fallback: 旧路径
    return _PIPELINE_CONFIG.get(round_name, {}).get("steps", {})
```

---

## 4. 方向 D：!pipeline 命令增强

### D1 — !pipeline resume

```python
async def _handle_pipeline_resume(
    sender_id: str, round_name: str
) -> str:
    """恢复已归档管线。

    !pipeline resume R77
    """
    mgr = _ensure_pipeline_manager()

    # 1. 检查是否已在活跃列表
    if mgr.exists(round_name):
        ctx = mgr.get(round_name)
        if ctx and ctx.is_active():
            return f"⚠️ {round_name} 已在活跃列表（status={ctx.status.value}），无需恢复"

    # 2. 从历史 JSONL 查找
    history = mgr.get_history(limit=100)
    target = None
    for entry in history:
        if entry.get("round_name") == round_name:
            target = entry
            break
    if not target:
        return f"❌ {round_name} 未在历史中找到"

    # 3. 从历史重建上下文
    ctx = PipelineContext.from_dict(target)
    # 状态重置
    if ctx.status in (PipelineStatus.COMPLETED, PipelineStatus.CANCELLED):
        return f"❌ {round_name} 已终态（{ctx.status.value}），不可恢复"
    if ctx.status == PipelineStatus.BLOCKED:
        ctx.status = PipelineStatus.RUNNING
        ctx.blocked_reason = None
    ctx.updated_at = time.time()

    # 4. 写回活跃列表
    async with mgr._lock:
        mgr._contexts[round_name] = ctx
        mgr._save()

    return (
        f"✅ {round_name} 已恢复\n"
        f"  状态: {ctx.status.value}\n"
        f"  Step: {ctx.current_step}/{ctx.total_steps}\n"
        f"  成员: {len(ctx.role_agent_map)} 个角色\n"
        f"  创建: {datetime.fromtimestamp(ctx.created_at).strftime('%m/%d %H:%M')}\n"
    )
```

### D2 — !pipeline status ACK 展示

```python
def _format_pipeline_context(ctx: PipelineContext) -> str:
    """增强版：展示 ACK 状态。"""
    lines = [
        f"📋 {ctx.round_name} [{ctx.task_kind.value}]",
        f"  状态: {ctx.status.value}",
        f"  Step: {ctx.current_step}/{ctx.total_steps}",
        f"  阶段: {ctx.current_phase}",
    ]
    # ACK 状态
    if ctx.ack_states:
        ack_lines = []
        for i in range(1, ctx.total_steps + 1):
            step = f"step{i}"
            ack = ctx.ack_states.get(step, {})
            state = ack.get("state", "N/A")
            role = ack.get("role_name", "")
            if state == "ACKED":
                ack_lines.append(f"step{i} ✅{role}")
            elif state == "PENDING":
                ack_lines.append(f"step{i} ⏳{role}")
            elif state == "FAILED":
                ack_lines.append(f"step{i} ❌{role}")
            elif state == "TIMEOUT":
                ack_lines.append(f"step{i} ⚠️{role}")
            else:
                ack_lines.append(f"step{i} ⬜")
        lines.append(f"  ACK: {' | '.join(ack_lines)}")

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
```

### D3 — !pipeline create 增强

```python
# !pipeline create R78 dev [--steps 6] [--ws ws_id] [--pm-inbox inbox_id]
await mgr.create(
    round_name=round_name,
    task_kind=PipelineTaskKind(task_kind),
    workspace_dir=Path(config.REPO_PATH),
    workspace_id=ws_id or "",
    pm_inbox_id=pm_inbox_id or "",
    total_steps=int(total_steps_str) if total_steps_str else 6,
    created_by=sender_id,
)
```

---

## 5. 改动汇总

### 5.1 文件清单

| 文件 | 改动 | 行数 | 说明 |
|:-----|:-----|:----:|:------|
| `server/pipeline_context.py` | PipelineContext 新增 role_agent_map 类型兼容 | ~10 | str→list[str] + from_dict 旧格式兼容 |
| `server/pipeline_context.py` | Manager 新增 set_global_role_map/get_role_agents/update_role_agent_map | ~35 | 全局角色映射+管线角色映射 |
| `server/pipeline_context.py` | PipelineContext 新增 ack_states 字段 | ~5 | 序列化自动处理空 dict |
| `server/pipeline_context.py` | Manager 新增 set_ack_state/get_ack_state/has_ack_for_agent | ~25 | ACK 状态 CRUD |
| `server/pipeline_context.py` | PipelineContext 新增 steps 字段 | ~5 | 序列化自动处理空 list |
| `server/pipeline_context.py` | Manager 新增 update_steps/get_step_config | ~20 | Step 配置读写 |
| `server/handler.py` | _refresh_role_agent_map 改造 | ~15 | 写 Manager + 双写旧变量 |
| `server/handler.py` | _get_agents_by_role 改造 | ~5 | 走 Manager 查询 |
| `server/handler.py` | 其他 _ROLE_AGENT_MAP 读取迁移 | ~15 | ~10 处读取点 |
| `server/handler.py` | _step_ack_states 写入迁移 | ~15 | L2858 + L1493 双写 |
| `server/handler.py` | _step_ack_states 读取迁移 | ~15 | L1720/L1844 等走 Manager |
| `server/handler.py` | _get_step_config 改造 | ~5 | 优先读 ctx.steps |
| `server/handler.py` | _cmd_pipeline_start steps 写入 | ~10 | 解析 frontmatter → Manager |
| `server/handler.py` | 高频 _PIPELINE_CONFIG 读取替换 | ~20 | 10 处换为 Manager 查询 |
| `server/handler.py` | !pipeline resume 子命令 | ~30 | 恢复归档管线 |
| `server/handler.py` | _format_pipeline_context ACK 展示 | ~15 | ACK 状态逐 step 展示 |
| `server/handler.py` | 旧变量标记 DEPRECATED | ~3 | L56-L57 加注释 |
| `server/agent_card.py` | role_agent_map 写入适配 | ~10 | 走 Manager + 双写 |
| **合计** | | **~265 行净改** | （含 ~130 行新增 + ~135 行替换） |

### 5.2 无改动项

| 模块 | 原因 |
|:-----|:------|
| `shared/protocol.py` | 本轮不新增消息类型 |
| `server/workspace.py` | workspace 管理独立 |
| `clients/python/ws_client.py` | 客户端不变 |
| `server/pipeline_sync.py` | Git sync 不直接使用这三变量 |
| 各 bot 代码 | 行为不变 |
| `server/config.py` | 不改配置 |

### 5.3 操作顺序

```bash
# Step 1: pipeline_context.py 扩展（方向 A+B+C 的 dataclass + Manager 方法）
# Step 2: handler.py _refresh_role_agent_map + _get_agents_by_role（方向 A）
# Step 3: agent_card.py 适配（方向 A 写入路径迁移）
# Step 4: handler.py _step_ack_states 写入 + 读取迁移（方向 B）
# Step 5: handler.py _get_step_config + _cmd_pipeline_start steps 写入（方向 C）
# Step 6: handler.py 高频 _PIPELINE_CONFIG 读取替换 + 旧变量 DEPRECATED 标记（方向 C）
# Step 7: !pipeline resume + status ACK 增强（方向 D）
```

---

## 6. 兼容性与循环 import 分析

### 6.1 循环 import 矩阵

| 场景 | 分析 | 风险 |
|:-----|:-----|:----:|
| `agent_card.py` → `handler.py`（直接 import） | 现有模式 `from . import handler as _handler_mod` 已在用，运行时惰性 | ✅ 安全 |
| `agent_card.py` → `pipeline_context.py` | 新路径：`from . import pipeline_context as _pc_mod`，`pipeline_context.py` 不 import agent_card | ✅ 安全 |
| `handler.py` → `pipeline_context.py` | 现有 import `from .pipeline_context import PipelineContextManager` | ✅ 安全 |
| `pipeline_context.py` → `handler.py` | `PipelineContextManager` 不 import handler | ✅ 安全 |
| `handler.py` → `agent_card.py` | 现有 import `from . import agent_card as ac_mod` | ✅ 安全 |

**结论：** 三个模块之间没有非循环依赖。`agent_card.py` → `handler.py` 的引用是运行时惰性（try/except 防御），理论安全。

### 6.2 双写保险机制

```python
# 过渡期内的写入模式——先写新、再写旧
# 1. 新路径
await mgr.set_ack_state(round_name, step_name, state, ...)
# 2. 旧路径（标记 DEPRECATED — 过渡期后删除）
_step_ack_states[ack_key] = current_state
```

**双写一致性保证：**
- 新路径写入成功后再写旧路径（如果旧路径失败，log warning 但不算错误）
- 读取时优先读新路径，读不到回退旧路径
- 全量迁移完成后（预计 R79），一次性删除旧变量声明和所有双写代码

### 6.3 旧 JSON 向前兼容

```python
# 从旧 JSON 恢复时，role_agent_map 可能是 str（单值）
# from_dict 中自动检测并包装
if raw_role_map and isinstance(next(iter(raw_role_map.values())), str):
    role_agent_map = {k: [v] for k, v in raw_role_map.items()}
```

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:-----|:---------|
| `agent_card.py` 运行时 import 失败 | 低 | 角色映射不更新 | try/except 防御，回退到旧路径（双写保险） |
| 旧 JSON 中 role_agent_map 为 str 无法反序列化 | 低 | 现有管线角色映射丢失 | from_dict 中做类型检测，str→list[str] 自动包装 |
| _step_ack_states key 格式不兼容 | 中 | step ACK 状态一时读不到 | `{round}/{step}` → `{step}` 转换桥接 |
| 双写期间读写时序不一致 | 低 | 读可能取到旧值 | 读取优先走新路径，旧路径仅 fallback |
| `_get_step_config()` 行为变化影响旧管线 | 低 | 旧管线 step 配置读不到 | Manager 读取回退到 `_PIPELINE_CONFIG` |
| 迁移完成后 handler.py 净减少不足 40 行 | 低 | 目标未达成 | R78 目标是迁移路径，代码量减少在旧变量声明删除后（R79） |
| `!pipeline resume` 恢复后 step 错过已推进的步骤 | 低 | 重复工作 | resume 只恢复当前状态，不自动推进 step |

---

## 8. 迁移状态追踪

| 变量 | 引用数 | 方向 | 本轮迁移 | 本轮后状态 |
|:-----|:-----:|:----:|:---------|:-----------|
| `_ROLE_AGENT_MAP` | 19+5 | A | 全部写入+读取迁移 | `# DEPRECATED` 标记，双写保险 |
| `_step_ack_states` | 11 | B | 全部写入+读取迁移 | `# DEPRECATED` 标记，双写保险 |
| `_PIPELINE_CONFIG` | 28 | C | 10 处高频点迁移 | 旧变量保留，新代码优先使用 ctx.steps |

---

## 9. 设计决策确认清单

| # | 决策项 | 决策 | 状态 |
|:-:|:-------|:-----|:----:|
| 1 | `role_agent_map` 类型修复 | `dict[str, str]` → `dict[str, list[str]]` | ✅ 确认 |
| 2 | 全局角色映射存放位置 | `PipelineContextManager._global_role_map` | ✅ 确认 |
| 3 | `agent_card.py` 循环 import 策略 | `sys.modules.get('server.handler')` 运行时惰性引用 | ✅ 确认 |
| 4 | 双写保险策略 | 先写新路径 → 再写旧变量 | ✅ 确认 |
| 5 | ACK 状态 key 格式 | `{step}`（上下文内 key，不再含 round 前缀） | ✅ 确认 |
| 6 | `_PIPELINE_CONFIG` 迁移策略 | 10 处高频点迁移，旧变量保留 fallback | ✅ 确认 |
| 7 | `!pipeline resume` 反归档逻辑 | 从 JSONL history 读取 → `from_dict` → 写回活跃列表 | ✅ 确认 |
| 8 | 旧 JSON 向前兼容 | `from_dict` 检测 str→list[str] | ✅ 确认 |

---

## 10. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-09 | 初稿 — R78 技术方案：3 组旧全局变量（~58 处引用）迁移到 PipelineContext |
