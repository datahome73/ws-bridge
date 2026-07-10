---
pipeline:
  round_name: R97
  branch: dev
  steps: 6
  topology:
    auto_chain: true
    chain:
      - step: step2
        role: arch
        title: 技术方案
      - step: step3
        role: dev
        title: 编码实现
---

# R97 技术方案 — AutoRouter 稳定化：PipelineContext 驱动 🔧

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-11
> **基于需求文档：** `docs/R97/R97-product-requirements.md`
> **基线：** `main` latest
> **文件：** `server/pipeline_context.py` · `server/handler.py` · `server/auto_router.py`

---

## 目录

1. [改动总览](#1-改动总览)
2. [🅰️ PipelineContext 新结构](#️-pipelinecontext-新结构)
3. [🅱️ `_cmd_pipeline_start` 简化](#️-_cmd_pipeline_start-简化)
4. [🅲 AutoRouter 重构](#️-autorouter-重构)
5. [🅳 角色映射 — Agent Card 实时查询](#️-角色映射--agent-card-实时查询)
6. [授权模型 — step1 PM 执行者链条](#6-授权模型--step1-pm-执行者链条)
7. [改动对照表](#7-改动对照表)
8. [验收清单](#8-验收清单)

---

## 1. 改动总览

### 1.1 核心架构变化

| 维度 | 旧（R88） | 新（R97） |
|:-----|:----------|:----------|
| 拓扑来源 | WORK_PLAN frontmatter YAML 解析 | `PipelineContext.steps` 结构化 |
| 角色映射 | `config/agent_cards.json` | AutoRouter 实时查询 Agent Card |
| 任务消息 | LLM 拼接上下文 | 机械模板替换 |
| `!pipeline_start` | `--work_plan_url` 必传 | 零参数，默认 Step 链 |
| PM 角色 | 管线外协调 | Step 1 执行者 |

### 1.2 文件改动

| 文件 | 改动 | 净变化 | 说明 |
|:-----|:-----|:------:|:------|
| `server/pipeline_context.py` | 新增 `StepInfo` dataclass + `DEFAULT_STEP_ORDER` | +50 | 新结构 |
| `server/handler.py` | `_cmd_pipeline_start` 重写 | +30/-20 | 简化 |
| `server/auto_router.py` | 核心重构 — `_dispatch_step`/`_build_task_message`/`_resolve_agent_by_role` | +200/-150 | 大改 |
| **合计** | **3 文件** | **+280/-170** | **净+110** |

### 1.3 默认 Step 链（6 步）

```python
DEFAULT_STEP_ORDER = ["step1", "step2", "step3", "step4", "step5", "step6"]

DEFAULT_STEPS = {
    "step1": StepInfo(role="pm",          title="标注 WORK_PLAN 已审核"),
    "step2": StepInfo(role="arch",        title="技术方案"),
    "step3": StepInfo(role="dev",         title="编码实现"),
    "step4": StepInfo(role="review",      title="代码审查"),
    "step5": StepInfo(role="qa",          title="测试验证"),
    "step6": StepInfo(role="operations",  title="合并部署归档"),
}
```

---

## 2. 🅰️ PipelineContext 新结构

### 2.1 `StepInfo` dataclass

```python
@dataclass
class StepInfo:
    step_key: str          # "step1", "step2", ...
    role: str              # "pm" | "arch" | "dev" | "review" | "qa" | "operations"
    title: str             # 步骤标题
    status: str = "pending"  # "pending" | "active" | "done" | "failed" | "skipped"
    agent_id: str = ""
    agent_name: str = ""
    output: dict | None = None       # commit_sha, report_path 等
    result_msg: str = ""             # "✅ 完成，已推 dev: xxxx"
```

### 2.2 `PipelineContext` dataclass

```python
@dataclass
class PipelineContext:
    round_name: str                    # "R97"
    status: str = "running"            # "running" | "stopped" | "done"
    created_at: float = 0.0
    triggerer_id: str = ""             # 发起 !pipeline_start 的 agent_id
    triggerer_name: str = ""           # 发起者显示名
    steps: dict[str, StepInfo] = field(default_factory=lambda: {})
    step_order: list[str] = field(default_factory=lambda: list(DEFAULT_STEP_ORDER))
    work_plan_url: str = ""            # 可选，向后兼容
    references: dict[str, str] = field(default_factory=dict)
```

### 2.3 序列化兼容

```python
def to_dict(self) -> dict:
    return {
        "round_name": self.round_name,
        "status": self.status,
        "created_at": self.created_at,
        "triggerer_id": self.triggerer_id,
        "triggerer_name": self.triggerer_name,
        "steps": {k: asdict(v) for k, v in self.steps.items()},
        "step_order": self.step_order,
        "work_plan_url": self.work_plan_url,
        "references": self.references,
    }

@classmethod
def from_dict(cls, d: dict) -> "PipelineContext":
    steps = {}
    for k, v in d.get("steps", {}).items():
        steps[k] = StepInfo(**v)
    return cls(
        round_name=d["round_name"],
        status=d.get("status", "running"),
        created_at=d.get("created_at", 0.0),
        triggerer_id=d.get("triggerer_id", ""),
        triggerer_name=d.get("triggerer_name", ""),
        steps=steps,
        step_order=d.get("step_order", list(DEFAULT_STEP_ORDER)),
        work_plan_url=d.get("work_plan_url", ""),
        references=d.get("references", {}),
    )
```

### 2.4 持久化

使用现有 `PipelineContextManager` 的存储机制（`_contexts` 字典 + JSON 序列化到 `DATA_DIR`）。

```python
# 保存到 pipeline_contexts/{round_name}.json
# 启动时加载全部
# 每次更新后 writeback
```

---

## 3. 🅱️ `_cmd_pipeline_start` 简化

### 3.1 新旧对比

```python
# 旧（R88）:
async def _cmd_pipeline_start(sender_id, params):
    round_name = params["_positional"][0]
    work_plan_url = params.get("--work-plan-url") or params.get("--work_plan_url")
    # ① 解析 frontmatter ← 删除
    # ② 创建 workspace ← 删除
    # ③ 成员匹配 ← 删除
    # ④ 创建 PipelineContext + task ✓
    # ⑤ _broadcast_to_channel _admin ✓
    # ⑥ return response ✓

# 新（R97）:
async def _cmd_pipeline_start(sender_id, params):
    round_name = params["_positional"][0].upper()
    # ① 创建 PipelineContext（默认 Step 链）
    ctx = PipelineContext(
        round_name=round_name,
        status="running",
        created_at=time.time(),
        triggerer_id=sender_id,
        triggerer_name=get_agent_name(sender_id),
        steps={k: StepInfo(step_key=k, **v) for k, v in DEFAULT_STEPS.items()},
    )
    # ② 持久化
    pipeline_manager.set_context(round_name, ctx)
    pipeline_manager.save()
    # ③ 广播 _admin
    await _broadcast_to_channel(p.ADMIN_CHANNEL, {
        "type": "broadcast", "channel": p.ADMIN_CHANNEL,
        "from_name": "系统", "from_agent": SYSTEM_AGENT_ID,
        "content": f"🚀 **{round_name} 管线已启动**\n默认 Step 链: step1→...→step6\n发起者: {sender_id[:16]}",
        "ts": time.time(),
    })
    return f"🚀 **{round_name} 管线已启动**\nStep 1: PM 审核标记\n..."
```

### 3.2 删除项

| 删除项 | 理由 |
|:-------|:------|
| WORK_PLAN frontmatter 解析 | PipelineContext 自带 steps |
| workspace 创建 | 管线不依赖 workspace |
| workspace 成员匹配 | 角色映射从 Agent Card 实时查询 |
| `--work_plan_url` 强依赖 | 改为可选，存在 references 里 |
| rollcall 变量 | 不再需要点名 |

### 3.3 保留项

| 保留项 | 位置 |
|:-------|:------|
| `_broadcast_to_channel(_admin, ...)` | handler.py (R92) |
| `_send_cmd_response(ws, ...)` | handler.py (原始回复) |
| `_send_inbox` 发送 | AutoRouter |

---

## 4. 🅲 AutoRouter 重构

### 4.1 新数据流

```
_on_pipeline_ready(round_name)
  │
  ├─ _pipeline_manager.get_context(round_name)
  │     → PipelineContext (steps, step_order, role_agent_map)
  │
  ├─ 找到 step_order 中第一个 status="pending" 的 step
  │     → step1 → role="pm" → title="标注 WORK_PLAN 已审核"
  │
  ├─ _resolve_agent_by_role("pm")
  │     → Agent Card 实时查询 → agent_id
  │
  ├─ 更新 step1.status = "active"
  │
  └─ _dispatch_step(ctx, step1, agent_id)
        → _build_task_message(ctx, step1, prev_sha="")
        → _send_inbox(agent_id, task_message)
```

### 4.2 方法清单

| 方法 | 职责 | 与旧对比 |
|:-----|:-----|:---------|
| `_on_pipeline_ready()` | 读 context → 激活第一 step | 不再解析 frontmatter |
| `_dispatch_step()` | 更新 context → 发送 inbox | 精简（不再拼接上下文） |
| `_build_task_message()` | 模板变量替换 | 🆕 机械组装，不涉及 LLM |
| `_on_step_complete()` | 完成 step → 激活下一步 | 更新 context，不再解析 content 提取 role/sha |
| `_resolve_agent_by_role()` | Agent Card 实时查询角色映射 | 🆕 替代 `_resolve_agent_id()` |
| `_refresh_role_map()` | 每次派活前刷新角色映射缓存 | 🆕 |

### 4.3 `_build_task_message()` 模板

```python
def _build_task_message(self, ctx: PipelineContext, step: StepInfo, prev_sha: str) -> str:
    """机械组装任务消息，不涉及 LLM。"""
    lines = [
        f"【{ctx.round_name} Step {step.step_key} 任务 — {step.title} 🎯】",
        "",
        f"角色: {step.role}",
        f"前一棒已完成: {prev_sha or '（无）'}",
        "",
        f"请按流程完成任务后推 dev 分支。",
        f"完成后请回复 _inbox:server 告知 SHA。",
    ]
    return "\n".join(lines)
```

### 4.4 `_on_step_complete()` 更新逻辑

```python
async def _on_step_complete(self, content: str, from_agent: str) -> None:
    # ① 提取 round_name + sha
    round_name = self._extract_round(content)
    sha = self._extract_sha(content)
    if not round_name:
        return

    # ② 读 context
    ctx = self._pipeline_manager.get_context(round_name)
    if not ctx or ctx.status != "running":
        return

    # ③ 找 from_agent 对应的 step
    for step_key, step_info in ctx.steps.items():
        if step_info.agent_id == from_agent and step_info.status == "active":
            # 标记完成
            step_info.status = "done"
            step_info.result_msg = content
            step_info.output = {"sha": sha} if sha else {}

            # ④ 激活下一步
            next_idx = ctx.step_order.index(step_key) + 1
            if next_idx < len(ctx.step_order):
                next_key = ctx.step_order[next_idx]
                next_step = ctx.steps.get(next_key)
                if next_step:
                    next_step.status = "active"
                    next_agent = self._resolve_agent_by_role(next_step.role)
                    next_step.agent_id = next_agent or ""
                    await self._dispatch_step(ctx, next_step, sha or "")
            else:
                # 全部完成
                ctx.status = "done"
                await self._notify_all_done(round_name)

            self._pipeline_manager.set_context(round_name, ctx)
            self._pipeline_manager.save()
            return
```

### 4.5 删除的旧方法

| 旧方法 | 替代 |
|:-------|:-----|
| `_fetch_topology()` | PipelineContext 自带 steps |
| `_parse_topology()` | 删除（不再解析 YAML frontmatter） |
| `_find_role_in_chain()` | `step_order.index()` |

---

## 5. 🅳 角色映射 — Agent Card 实时查询

### 5.1 `_resolve_agent_by_role()`

```python
async def _resolve_agent_by_role(self, role: str) -> str | None:
    """从 Agent Card 实时查询 role 对应的 agent_id。"""
    # ① 刷新角色映射缓存
    await self._refresh_role_map()
    
    # ② 精确匹配
    if role in self._role_index:
        agents = self._role_index[role]
        # 选择最近在线的
        return agents[0] if agents else None
    
    # ③ 子串匹配（"arch" ↔ "architect"）
    for known_role, agents in self._role_index.items():
        if role in known_role or known_role in role:
            return agents[0] if agents else None
    
    return None
```

### 5.2 `_refresh_role_map()`

```python
async def _refresh_role_map(self) -> None:
    """通过 !agent_card list 或直接查询服务端 Agent Card 信息。"""
    # 方案 A: 发送 !agent_card list 命令
    # 方案 B: 查询服务端 API
    # 方案 C: 缓存 TTL + 惰性刷新
    
    # 推荐 C: 缓存 60s，派活前只刷新过期条目
    now = time.time()
    if now - self._last_role_refresh < 60:
        return
    
    # 实际查询逻辑
    self._role_index = await self._query_agent_cards()
    self._last_role_refresh = now
```

### 5.3 角色映射优先级

| 优先级 | 来源 | 示例 |
|:------:|:-----|:------|
| 1 | Agent Card `pipeline_roles` 精确匹配 | `["pm", "arch"]` |
| 2 | Agent Card `role` 字段 | `"reviewer"` |
| 3 | 子串近似匹配 | `"arch"` ↔ `"architect"` |

---

## 6. 授权模型 — step1 PM 执行者链条

### 6.1 `!pipeline_start` 作为授权按钮

```
项目负责人（大宏）:
  !pipeline_start R97
       │
       ▼
  创建 PipelineContext
  广播 _admin
       │
       ▼
  AutoRouter 派活 step1 → PM 收件箱
       │
       ▼
  PM: 标注 WORK_PLAN 已审核 → 推 git → ✅ 完成
       │
       ▼
  AutoRouter 自动接力 step2→...→step6
```

### 6.2 step1 的特殊性

| 属性 | step1 | step2-6 |
|:-----|:------|:---------|
| 角色 | `pm` | `arch` / `dev` / `review` / `qa` / `operations` |
| 任务内容 | 标注已审核 + 推 git | 正常开发交付 |
| 响应格式 | `✅ 完成，已推 dev: <sha>` | 同左 |

### 6.3 向后兼容

```python
# 支持旧 --work_plan_url 参数
if work_plan_url:
    ctx.work_plan_url = work_plan_url
    ctx.references["work_plan"] = work_plan_url
    
# AutoRouter 检测
if ctx.work_plan_url:
    # 可以作为 _build_task_message 的额外上下文
    pass
```

---

## 7. 改动对照表

| 文件 | 改动 | 行数 | 说明 |
|:-----|:-----|:----:|:------|
| `pipeline_context.py` | `StepInfo` dataclass | +15 | 步骤信息结构 |
| `pipeline_context.py` | `PipelineContext` dataclass | +20 | 管线上下文结构 |
| `pipeline_context.py` | `to_dict()` / `from_dict()` | +15 | 序列化 |
| `handler.py` | `_cmd_pipeline_start()` 重写 | +30/-20 | 简化，去 frontmatter |
| `auto_router.py` | `_on_pipeline_ready()` 重写 | +30/-40 | 读 context 取代解析 |
| `auto_router.py` | `_dispatch_step()` 简化 | +20/-30 | 机械组装 |
| `auto_router.py` | `_build_task_message()` 🆕 | +15 | 模板替换 |
| `auto_router.py` | `_on_step_complete()` 重写 | +40/-30 | context 驱动 |
| `auto_router.py` | `_resolve_agent_by_role()` 🆕 | +30 | Agent Card 查询 |
| `auto_router.py` | `_refresh_role_map()` 🆕 | +20 | 缓存刷新 |
| `auto_router.py` | 删除 `_fetch_topology()` | -20 | 不再需要 |
| `auto_router.py` | 删除 `_parse_topology()` | -30 | 不再需要 |
| **合计** | **3 文件** | **+200/-170** | **净+30** |

---

## 8. 验收清单

| # | 验收项 | 验证方法 | 期望 |
|:-:|:-------|:---------|:-----|
| ✅-1 | `!pipeline_start R97` 零参数成功 | 只输轮次名 | 创建 PipelineContext |
| ✅-2 | PipelineContext 含默认 Step 链 | `get_context()` 查 steps | step1~step6 全部存在 |
| ✅-3 | AutoRouter 收到广播后派活 step1→PM | PM inbox 出现任务 | 角色=pm，标题=标注 |
| ✅-4 | 角色映射从 Agent Card 实时查询 | 晓周上线后自动识别 | 无需配置 |
| ✅-5 | 任务消息机械组装 | 消息含 `Step step1` + 角色 | 无 LLM 内容 |
| ✅-6 | `✅ 完成` 后自动接力下一步 | step1 done → step2 派活 | 不卡住 |
| ✅-7 | 全链 6 Step 自动闭环 | PM 收 `🏁 全部完成` | step6→done |
| ✅-8 | 旧 `--work_plan_url` 兼容 | 带 URL 启动 | references 含 URL |
| ✅-9 | `_fetch_topology()` 已删除 | `grep '_fetch_topology'` | 空 |
| ✅-10 | `_parse_topology()` 已删除 | `grep '_parse_topology'` | 空 |
