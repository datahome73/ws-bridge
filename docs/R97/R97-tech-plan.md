---
pipeline:
  name: "R97 — AutoRouter 稳定化 🔧"
  state: step2
  author: "🏗️ 架构师"
---

# R97 技术方案 — PipelineContext 驱动 AutoRouter

> **版本：** v1.0
> **状态：** ✅ 设计审查通过
> **日期：** 2026-07-11
> **基线：** `dev@827755f`
> **净增：** ~+110 行（+280/-170）

---

## 1. 架构变化

### 旧架构（R88）

```
!pipeline_start --work_plan_url <url>
  → handler 从 URL 下载 WORK_PLAN.md
  → 解析 YAML frontmatter（LLM 解析）
  → 构建 _PIPELINE_CONFIG
  → 广播 _admin
  → AutoRouter HTTP GET WORK_PLAN raw URL
  → 再解析 frontmatter
  → 拼装任务（LLM 拼接）
```

### 新架构（R97）

```
!pipeline_start R97
  → handler 创建 PipelineContext（结构化 JSON）
  → 广播 _admin（"管线已启动 R97"）
  → AutoRouter 读取 PipelineContext
  → 从 context 读 step 角色+agent_id
  → 机械组装任务消息
  → 发 inbox
```

### 关键差异

| 维度 | 旧 (R88) | 新 (R97) |
|:-----|:---------|:---------|
| 拓扑来源 | YAML frontmatter（LLM 解析） | PipelineContext（结构化 JSON） |
| 任务组装 | LLM 拼接 | 机械模板替换 |
| 角色映射 | WORK_PLAN 静态定义 | Agent Card 动态查询 |
| workspace 角色 | 派活依据 | 时间切片，不影响派活 |
| PM 角色 | 外部协调者 | Step 1 执行者 |

---

## 2. PipelineContext 扩展

### StepInfo dataclass

```python
@dataclass
class StepInfo:
    name: str              # "step2"
    role: str              # "arch"
    status: str            # "pending" | "active" | "done" | "skipped"
    agent_id: str = ""     # 派活后设置
    agent_name: str = ""
    output: dict = field(default_factory=dict)
    dispatched_at: float = 0.0
    completed_at: float = 0.0
```

### PipelineContext 新增字段

```python
steps: dict[str, StepInfo]  # {"step2": StepInfo, ...}
step_order: list[str]        # ["step1", "step2", ..., "step6"]
references: dict[str, str]   # {"work_plan": "url", "requirements": "url"}
triggerer_id: str            # 发起者 agent_id（即 PM 角色）
```

### 默认管线 Steps

```python
DEFAULT_PIPELINE_STEPS = {
    "step1": StepInfo(name="step1", role="pm", status="pending"),
    "step2": StepInfo(name="step2", role="arch", status="pending"),
    "step3": StepInfo(name="step3", role="dev", status="pending"),
    "step4": StepInfo(name="step4", role="review", status="pending"),
    "step5": StepInfo(name="step5", role="qa", status="pending"),
    "step6": StepInfo(name="step6", role="ops", status="pending"),
}
```

---

## 3. 改动详情

### 3.1 `server/pipeline_context.py` +50 行

- 新增 `StepInfo` dataclass
- 新增 `DEFAULT_PIPELINE_STEPS` 常量
- 新增 `resolve_step_roles()` 从 Agent Card 查询角色→agent 映射
- `PipelineContextManager` 新增 `save_context()`/`get_context()` 方法

### 3.2 `server/handler.py` +30/-20 行

`_cmd_pipeline_start` 简化：

```python
# 改前：解析 frontmatter + 下载 WORK_PLAN
# 改后：创建 PipelineContext + 默认 steps
ctx = await _pipeline_manager.create(
    round_name=round_name,
    task_kind=PipelineTaskKind.DEV,
    workspace_dir=config.DATA_DIR,
    workspace_id=ws_id or f"ws:{round_name}-dev",
    created_by=sender_id,
    steps=deepcopy(DEFAULT_PIPELINE_STEPS),
    step_order=list(DEFAULT_PIPELINE_STEPS.keys()),
    triggerer_id=sender_id,
)
ctx.status = PipelineStatus.RUNNING
ctx.steps["step1"].status = "active"
```

### 3.3 `server/auto_router.py` +200/-150 行

核心重构：

| 旧函数 | 新函数 | 变化 |
|:-------|:-------|:-----|
| `_load_topology()` | `_on_pipeline_ready()` | HTTP GET → PipelineContext.get_context() |
| `_build_task()` | `_build_task_message()` | LLM 拼接 → 机械模板 |
| `_dispatch()` | `_dispatch_step()` | 角色解析从 frontmatter → PipelineContext |
| `_handle_step_complete()` | `_on_step_complete()` | 更新 context steps，持久化 |
| `_handle_message()` | 不变 | 只关心 _admin 频道 |

新增函数：
- `_refresh_role_map()` — 从 Agent Card 动态查询角色映射
- `_pick_agent_for_role()` — 多候选随机选择
- `_get_next_step()` / `_get_prev_step()` — step 导航

---

## 4. 任务消息模板

```python
TASK_TEMPLATE = """\
【{round_name} {step_key} 任务 — {role_name} 🎯】

角色: {agent_name}
{prev_info}
参考: {refs}

完成后推 dev。
**完成后请回复 _inbox:{pm_id} 告知 SHA。**
"""
```

机械替换，零 LLM 参与。

---

## 5. 向后兼容

| 旧用法 | R97 兼容 | 说明 |
|:-------|:---------|:------|
| `--work_plan_url` | ✅ 支持 | 存到 `ctx.references["work_plan"]` |
| WORK_PLAN frontmatter | ✅ 无害 | 被忽略 |
| `!create_workspace` | ✅ 保留 | 独立功能 |
| 旧 PipelineContext JSON | ✅ 兼容 | from_dict 适配旧字段 |

---

## 6. 验收清单

| # | 验收项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | `!pipeline_start R97` 零参数成功 | 只输轮次名 |
| 2 | PipelineContext 持久化 | get_context(R97) 返回完整结构 |
| 3 | AutoRouter 自动派活 step2 | arch inbox 出任务消息 |
| 4 | 任务含前一棒 SHA | `前一棒已完成: xxxxxx` |
| 5 | 全链 6 Step 自动走完 | PM 收 `🏁 全部完成` |
| 6 | 旧 `--work_plan_url` 兼容 | URL 出现在 refs 中 |

---

## 7. 风险

| 风险 | 缓解 |
|:-----|:------|
| AutoRouter 重构引入新 bug | 核心逻辑简化（读 context → 发 inbox → 等回复） |
| 角色映射增加延迟 | 60s 缓存 |
| 多 agent 同角色选错 | 随机策略，可升级 |
