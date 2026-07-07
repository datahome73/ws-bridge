# DeepCode 架构研究报告 — agent-pipeline-orchestrator

> 研究日期：2026-07-09
> 来源仓库：https://github.com/HKUDS/DeepCode
> 研究目标：分析 DeepCode 的 agent-pipeline-orchestrator 设计，评估对 ws-bridge 管线的借鉴价值

---

## 一、项目概况

DeepCode 是一个「科研论文→代码实现」的全自动化管线，管理多个专用 Agent 协作完成端到端任务。其编排层设计成熟、模块化程度高，与 ws-bridge 的多 bot 管线协作场景有高度可比性。

## 二、核心架构发现

### 2.1 WorkflowContext — 统一管线上下文对象

**文件：** `workflows/workflow_context.py`

DeepCode 用单一的 `WorkflowContext` dataclass 承载管线所有阶段需要的数据，替代了之前散落在多个函数间的零散参数（`input_source: str`、`download_result: str (JSON)`、`dir_info: dict`）。

```python
@dataclass(slots=True)
class WorkflowContext:
    task_id: str
    input_source: str
    input_kind: InputKind         # "pdf" | "md" | "docx" | "txt" | "html" | "url"
    workspace_root: Path
    task_dir: Path
    enable_indexing: bool
    task_kind: TaskKind           # "paper2code" | "chat2code" | "text2web"
    skip_research_analysis: bool
    paper_path: Path | None
    paper_md_path: Path | None
    standardized_text: str | None

    # 派生路径用 @property 计算，不做 I/O
    @property
    def reference_path(self) -> Path: ...
    @property
    def initial_plan_path(self) -> Path: ...
```

**设计要点：**

- **纯数据对象** — 不含 I/O、LLM 调用或业务逻辑。所有副作用在 `workflows/environment.py` 中完成
- **路径用 `pathlib.Path`** — 杜绝字符串路径拼接错误
- **`to_dir_info()` 兼容桥** — 为旧代码提供向后兼容的 dict 格式
- **`@dataclass(slots=True)`** — 内存优化，属性不可动态添加

**对 ws-bridge 的启示：** 当前管线状态散落在各 bot 的 inbox 消息、handler.py 的模块级全局变量（`_PIPELINE_STATE`、`_ROLE_AGENT_MAP` 等）以及 WORK_PLAN 文档中。一个统一的 `PipelineContext` 可以：

- 让所有 bot 和 handler 函数通过同一个对象访问当前任务状态
- 消除靠 parse inbox 消息来推断状态的隐式协议
- 提供类型安全的派生路径（inbox_id、report_path、plan_path 等）

---

### 2.2 prepare_workflow_environment — 统一的初始化阶段

**文件：** `workflows/environment.py`

DeepCode 把所有**非 LLM 的前置工作**集中到一个 async 函数中，在进入任何 LLM 调用前一次性完成：

```
prepare_workflow_environment()
  ├── resolve_workspace_root()    # env > config > cwd 三级 fallback
  ├── _normalize_input()          # URL / file:// / 本地路径统一处理
  ├── _validate_input()           # 存在性、大小、扩展名白名单校验
  ├── _detect_resume()            # 发现已有任务目录 → resume 模式
  ├── _ensure_workspace()         # 创建目录 + 磁盘空间检查
  └── _register_workspace_for_filesystem_mcp()  # 注册 MCP 允许目录
```

**设计要点：**

- **Fail Fast** — 输入无效时不产生任何 LLM 费用
- **Resume 检测** — 用户重新输入已有任务目录时自动恢复，保留原有 task_id
- **Progress Callback** — 每个步骤回调进度（百分比 + 消息），支持同步和 async 两种形式
- **多级配置链** — `DEEPCODE_WORKSPACE` env > `workspace.root` in config > `cwd/deepcode_lab`

**对 ws-bridge 的启示：** 当前管线启动时没有正式的初始化阶段，每个 bot 各自检查环境。一个统一的 `init_pipeline()` 阶段可以：

- 在进入实际工作前验证所有 bot 在线、api_key 有效、workspace 可写
- 检测是否存在冲突或未完成的任务
- 一次性地创建所需目录和 inbox 频道

---

### 2.3 InteractionPlugin — 用户参与点作为插件

**文件：** `workflows/plugins/base.py`、`workflows/plugins/integration.py`

这是最值得借鉴的架构模式。DeepCode 定义了 `InteractionPoint` 枚举（钩子点）和 `InteractionPlugin` 基类（插件），管线中只调用 `await plugins.run_hook(point, context)`，实现了**零侵入的用户参与点插入**。

```
InteractionPoint 枚举:
  BEFORE_PLANNING / AFTER_PLANNING
  BEFORE_RESEARCH_ANALYSIS / AFTER_RESEARCH_ANALYSIS
  BEFORE_IMPLEMENTATION / AFTER_IMPLEMENTATION
  AFTER_CODE_PLANNING
```

```python
class InteractionPlugin(ABC):
    name: str = "base_plugin"
    hook_point: InteractionPoint = InteractionPoint.BEFORE_PLANNING
    priority: int = 100

    @abstractmethod
    async def should_trigger(self, context: dict) -> bool: ...
    @abstractmethod
    async def create_interaction(self, context: dict) -> InteractionRequest: ...
    @abstractmethod
    async def process_response(self, response, context) -> dict: ...

    async def on_skip(self, context) -> dict: ...     # 用户跳过
    async def on_timeout(self, context) -> dict: ...  # 超时处理
```

```python
class PluginRegistry:
    def register(self, plugin: InteractionPlugin): ...
    def run_hook(self, hook_point, context, task_id) -> dict:
        for plugin in self._plugins[hook_point]:
            if not await plugin.should_trigger(context):
                continue
            interaction = await plugin.create_interaction(context)
            response = await self._interaction_callback(task_id, interaction)
            context = await plugin.process_response(response, context)
        return context
```

```python
class WorkflowPluginIntegration:
    # 桥接插件系统和 WebSocket/API 层
    # 处理 asyncio.wait_for 超时
    # 通过 _broadcast() 发送交互请求到前端
    # submit_response() 接收用户回复
```

**设计要点：**

- **管线代码不改** — 只加一行 `await plugins.run_hook(...)`，具体行为由插件决定
- **自动跳过** — 无 callback 时非必须交互自动跳过
- **优先级排序** — 同 hook 点的插件按 priority 执行
- **完整异常隔离** — 单个插件抛异常不影响其他插件

**对 ws-bridge 的启示：** 当前的「PM 手动协调」模式可以升级为 hook + plugin 模式：

```
管道阶段:          Start → Plan → Implement → Review → Deploy
                   │        │       │           │        │
插件注入点:     BEFORE   AFTER   BEFORE      AFTER   AFTER
                 PLAN     PLAN    IMPL        REVIEW  DEPLOY
```

例如：
- `BEFORE_WORK_PLAN` → 需求分析插件（自动补全需求 or 等 PM 输入）
- `AFTER_WORK_PLAN` → Plan Review 门（PM 确认/修改/驳回）
- `BEFORE_IMPLEMENT` → 前置条件检查
- `AFTER_IMPLEMENT` → Code Review 门
- 每个插件可以 `should_trigger()` 根据上下文决定是否触发

---

### 2.4 Plan Review Gate — 正式的计划审批门

**文件：** `workflows/plan_review_runtime.py`

DeepCode 为计划审批设计了完整的版本管理流程：

```python
async def run_plan_review_gate(*, initial_plan_path, paper_dir, callback, max_rounds=3):
    # 1. 保存 v00 版本（初始 plan）
    # 2. 回调前端请求审批
    while interaction_count < max_interactions:
        decision = await callback(request)
        action = _normalise_action(decision)

        if action == "approve":
            # 保存最终版本，记录 meta
            return {"status": "approved", ...}

        if action == "modify":
            # AI 修订：revise_plan_with_feedback(current_plan, feedback)
            # 保存为 v01, v02, ...
            modification_round += 1

        if action == "replace":
            # 手动替换：用户提供完整新 plan
            # 验证 YAML 结构，保存版本

        if action == "cancel":
            raise PlanReviewCancelled(reason)
```

**设计要点：**

- **每轮审批的 plan 都存版本快照** — `initial_plan.v01.modified.txt`、`initial_plan.v02.manual.txt`
- **Approval/Modify/Replace/Cancel 四种路径**
- **最大轮数限制**（默认 3 轮）
- **Review history** 写入 JSONL 日志，完整追踪
- **Final validation** — 审批通过后再做一次 YAML 结构校验才放行到实现阶段
- **no callback = auto skip** — UI 层没有连接审批回调时自动跳过

**对 ws-bridge 的启示：** 当前 PM → bot 的审批流是隐式的（PM 回复 inbox 视为确认/修改）。可以显式化为：

- 每轮 WORK_PLAN 变更自动保存版本 (`plan_v01.md`，`plan_v02.md`)
- 审批动作标准化（approve / modify / replace / cancel）
- review history 持久化到 JSONL
- 最大修改轮数限制，防止无限循环

---

### 2.5 Planning Runtime — 规划阶段的 checkpoints

**文件：** `workflows/planning_runtime.py`

```python
planning_paths(paper_dir) -> {
    "checkpoint": paper_dir / "planning_checkpoint.json",
    "attempts": paper_dir / "planning_attempts.jsonl",
    "meta": paper_dir / "planning_result_meta.json",
}
```

- **Checkpoint 回调** — `_generate_plan_with_single_agent` 期间定期写 checkpoint，提供恢复点
- **Attempt 日志** — 每次规划尝试写入 JSONL，包含 token 用量、耗时、验证结果
- **Plan 验证** — `validate_plan_text()` 检查 YAML 结构和必需的 5 个 section
- **Fallback 计划** — `coerce_text_to_minimal_plan()` 当 LLM 输出不合规时自动生成保守计划
- **重试参数衰减** — `_adjust_params_for_retry()` 随重试次数减少 max_tokens、降低 temperature

---

### 2.6 AgentRunner 内核 — 统一的执行引擎

**文件：** `core/agent_runtime/runner.py`、`core/agent_runtime/hook.py`

所有 Agent（规划、实现、记忆）都跑在同一个 `AgentRunner` 核心上：

- **AgentHook** — 工具调用前后拦截器（pre/post tool call hooks）
- **should_stop_callback** — 提前终止条件
- **injection_callback** — 注入领域特定行为
- **Tool Aliasing** — `AliasedTool` 同一工具不同视角不同名称
- **Loop Detector** — 检测重复工具调用模式
- **Permission Engine** — 工具调用权限控制

**对 ws-bridge 的启示：** ws-bridge 的 bot agent 各自独立运行，但 hook 模式可以应用到管线编排层——例如每个 step 之前检查前置条件、之后验证产出物。

---

## 三、对比总结：DeepCode vs ws-bridge 管线

| 维度 | DeepCode | ws-bridge | 借鉴建议 |
|------|----------|-----------|----------|
| 上下文传递 | `WorkflowContext` dataclass | 模块级全局变量 + inbox 消息解析 | **引入 PipelineContext** |
| 阶段初始化 | `prepare_workflow_environment()` | 各 bot 各自检查 | **统一 init_pipeline()** |
| 用户参与点 | InteractionPlugin 插件系统 | PM 手动在群里协调 | **引入 Hook + Plugin** |
| 审批流程 | Plan Review Gate（版本化+4种动作+超时） | 隐式 inbox 回复 | **显式化审批动作 + 版本快照** |
| 规划检查点 | JSON checkpoint/attempts/meta | 无 | **可逐步引入** |
| 执行引擎 | 统一 AgentRunner + Hook | 各 bot 独立，通过 inbox 通信 | **编排层借用 Hook 模式** |

## 四、落地建议（按优先级）

1. **高优先级：PipelineContext** — 统一的数据对象是最基础的抽象，解决「管线状态在哪」的问题
2. **高优先级：统一 init phase** — 在进入实际工作前一次性地做所有检查和初始化
3. **中优先级：Plan Review Gate** — 将审批流标准化、版本化
4. **低优先级：Plugin/Hook 系统** — 最灵活的架构但也是最大的改动，可在 1-3 稳定后再做

---

*本报告基于 DeepCode commit a3b895a（2026-07-09 最新）分析。*
