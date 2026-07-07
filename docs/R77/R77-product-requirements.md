# R77 产品需求 — PipelineContext：统一管线上下文对象 📋

> **版本：** v1.0（初稿）
> **状态：** 📝 待审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-09
> **基线：** `cfe129f`（dev 最新 — R76 合并部署归档）
> **本轮改动范围：** `server/` 新增 `pipeline_context.py` + 相关模块整合
> **参考：** `docs/research/deepcode-orchestrator-study.md`

---

## 0. 先验验证：已就绪的基础设施

| 验证项 | 结果 | 确认方式 |
|:-------|:----:|:---------|
| R76 管线功能完整（合并部署 v2.43） | ✅ | 基线 `cfe129f`，ws-bridge:latest |
| R72 认证体系 + Agent Card | ✅ | 持续稳定运行 |
| inbox 双向通信正常 | ✅ | 全线 bot 回复确认 |
| Git 推送（HTTPS token） | ✅ | `/opt/data/.env` 中 GITHUB_TOKEN |
| **小结** | ✅ | **基础设施稳固，可以进行架构升级** |

---

## 1. 问题背景

### 1.1 现状分析

经过 R32→R76 共 44 轮迭代，管线状态管理逐渐暴露出架构债：

| 问题 | 具体表现 | 严重度 |
|:-----|:---------|:------:|
| **状态散落各处** | `handler.py` 的模块级全局变量（`_PIPELINE_STATE`、`_ROLE_AGENT_MAP`、`_step_ack_states` 等）+ 各 bot 记忆 + WORK_PLAN frontmatter，三者之间无统一引用 | 🔴 P0 |
| **隐式协议耦合** | 靠解析 inbox 消息文本推断状态（"这轮完了看看情况"、"已推 dev ✅"→ SHA 提取），无类型安全的数据通路 | 🔴 P0 |
| **派生路径重复计算** | WORK_PLAN URL、inbox_id、report_path 在多个 bot 和脚本中重复拼接，一个改漏处处崩 | 🟡 P1 |
| **resume 无感知** | 管线中断后重新开始，无有效恢复机制，经常重复工作 | 🟡 P1 |
| **新 bot 接入成本高** | 新 bot 需要理解整个隐式状态协议才能参与管线 | 🟢 P2 |

### 1.2 根因分析

| # | 根因 | 说明 |
|:-:|:-----|:------|
| 1 | 管线状态从未被建模 | 44 轮迭代专注于功能推进，状态管理随需而加，没有统一设计 |
| 2 | WORK_PLAN 双重重任 | 既是文档又是状态容器，frontmatter 的机器可读字段与人类可读内容混合 |
| 3 | 无跨 bot 共享上下文 | 各 bot 通过 inbox 消息传递状态片段，无共享数据对象 |

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:-----|:------|
| 🔴 **P0 方向 — 为后续架构扩展打基础** | R78+ 计划引入更复杂的编排逻辑（多阶段规划、条件分支），需要可靠的状态管理 |
| 🟡 **每次管线卡住 debug 成本高** | 当前状态分散，每次故障需要同时查多个地方才能还原完整上下文 |
| 🟢 **R77 改动范围明确** | 纯 server 端新增一个模块 + 改动 handler.py 的管线相关函数，不改 bot 行为、不改协议、不改部署 |
| 🟢 **DeepCode 已验证可行** | WorkflowContext 模式在生产级项目 DeepCode 中运行稳定，有成熟参考 |

---

## 2. 功能需求

### 设计原则

> **PipelineContext 是一个纯数据对象，不包含 I/O、LLM 调用或业务逻辑。**
>
> 所有状态修改通过 handler.py 现有的消息处理流程驱动，PipelineContext 只做「读写」不决定「何时写」。

---

### 方向 A（核心）：PipelineContext 数据模型 🔴 P0

#### A1 — PipelineContext dataclass

```python
@dataclass
class PipelineContext:
    # ── 身份信息（创建时确定，不可变）──
    round_name: str                  # "R77"
    task_kind: PipelineTaskKind      # "dev" | "review" | "deploy" | "docs"

    # ── 工作空间（创建时确定）──
    workspace_dir: Path              # /opt/data/ws-bridge
    task_dir: Path                   # workspace_dir / "pipeline_tasks" / "R77"
    inbox_id_prefix: str             # 本管线使用的 inbox ID 前缀

    # ── 管线运行时状态（随管线推进变化）──
    status: PipelineStatus           # "init" | "planning" | "running" | "blocked" | "completed" | "cancelled"
    current_phase: str               # "plan" | "implement" | "review" | "deploy"
    current_step: int                # step 序号（0-indexed）
    total_steps: int                 # 总 step 数
    blocked_reason: str | None       # 当 status=blocked 时的原因

    # ── 工作产物路径（派生 property，不持久化）──
    @property
    def work_plan_path(self) -> Path: ...
    @property
    def report_path(self) -> Path: ...
    @property
    def review_history_path(self) -> Path: ...

    # ── 管线成员（角色 → agent_id）──
    role_agent_map: dict[str, str]   # {"architect": "ws_xxx", "developer": "ws_yyy", ...}
    agent_card_ids: dict[str, str]   # {"ws_xxx": card_id, ...}

    # ── 元信息（审计用）──
    created_at: float
    updated_at: float
    created_by: str                  # agent_id
    tags: dict[str, str]             # 可扩展标签
```

#### A2 — PipelineStatus 状态机

```
INIT ──→ PLANNING ──→ RUNNING ──→ COMPLETED
                         │
                         ├──→ BLOCKED ──→ RUNNING（恢复）
                         │
                         └──→ CANCELLED
```

| 状态 | 含义 | 触发条件 |
|:-----|:-----|:---------|
| `INIT` | 已创建但未开始 | pipeline init 命令 |
| `PLANNING` | 规划阶段 | WORK_PLAN 创建 |
| `RUNNING` | 执行中 | 某个 bot 被指派工作 |
| `BLOCKED` | 等待外部输入 | PM 审批 / 修复阻塞问题 |
| `COMPLETED` | 所有步骤完成 | 最后一步完成确认 |
| `CANCELLED` | 人工取消 | cancel 命令 |

#### A3 — PipelineTaskKind 类型

```python
class PipelineTaskKind(enum.Enum):
    DEV = "dev"           # 开发任务（默认）
    REVIEW = "review"     # 代码审查
    DEPLOY = "deploy"     # 部署
    DOCS = "docs"         # 文档治理
```

---

### 方向 B：PipelineContext 存储与生命周期 🟡 P1

#### B1 — 持久化

| 方式 | 格式 | 路径 |
|:-----|:-----|:-----|
| 活跃上下文 | JSON | `DATA_DIR / "pipeline_contexts.json"` |
| 历史归档 | JSONL | `DATA_DIR / "pipeline_contexts_history.jsonl"` |

活跃的 PipelineContext 在内存中维护（类似现有 `_workspaces` 模式），每次变更写 JSON 持久化。管线完成/取消后归档到 JSONL，从活跃列表中移除。

#### B2 — PipelineContextManager 生命周期

```python
class PipelineContextManager:
    """管理所有活跃 PipelineContext 的生命周期"""

    def get(self, round_name: str) -> PipelineContext | None: ...
    def get_all_active(self) -> list[PipelineContext]: ...
    def create(self, ...) -> PipelineContext: ...
    def update_status(self, round_name: str, status: PipelineStatus, ...) -> bool: ...
    def advance_step(self, round_name: str) -> bool: ...
    def archive(self, round_name: str) -> bool: ...
    def get_history(self, limit: int = 20) -> list[dict]: ...
```

#### B3 — handler.py 集成

在 `handler.py` 中：

```python
# 替换现有的模块级管线全局变量：
#   _PIPELINE_STATE: dict[str, dict]
#   _ROLE_AGENT_MAP: dict[str, list[str]]
#   _step_ack_states: dict[str, dict]
# 改为：
#   _pipeline_manager: PipelineContextManager

# handler 函数中通过 _pipeline_manager.get(round_name) 访问当前状态
# 状态变更统一走 manager.update_status() / manager.advance_step()
```

---

### 方向 C（渐进式）：现有全局变量迁移 🟡 P1

不建议一次性全部重构。分步迁移：

| 阶段 | 迁移内容 | 目标 |
|:-----|:---------|:-----|
| **Phase 1**（本轮） | `_PIPELINE_STATE` → `PipelineContextManager` | 最核心的管线状态管理 |
| **Phase 2**（R78 可选） | `_ROLE_AGENT_MAP` → `PipelineContext.role_agent_map` | 角色映射统一 |
| **Phase 3**（R79 可选） | `_step_ack_states` → `PipelineContext.ack_states` | step ack 集中管理 |
| **Phase 4**（后续） | `_PIPELINE_CONFIG` 重读逻辑 | 减少重复解析 WORK_PLAN frontmatter |

**Phase 1 后旧变量保留但标记为 deprecated**，新代码统一从 Manager 读取。

---

### 方向 D：新命令与 inbox 消息格式扩展 🟢 P2

#### D1 — 新增 `!pipeline` 命令

| 子命令 | 参数 | 说明 |
|:-------|:-----|:------|
| `!pipeline status [round]` | 可选轮次名 | 查看管线当前状态快照 |
| `!pipeline list` | — | 列出所有活跃管线 |
| `!pipeline advance [round]` | 可选轮次名 | 推进一步（向 manager 发送 advance） |
| `!pipeline block [round] reason` | 轮次名 + 原因 | 将管线置为 BLOCKED 状态 |

#### D2 — Inbox 消息自动关联

当 bot 在 inbox 频道中回复内容含特定格式（如 `R77 Step 3 continue`），Manager 自动识别并推进 `current_step`。此功能为 Phase 2 可选。

---

## 3. 验收标准

| # | 验收项 | 通过条件 |
|:-:|:------|:---------|
| 1 | PipelineContext 创建 | `!pipeline create R77 dev` 创建后，JSON 持久化到磁盘 |
| 2 | 状态查询 | `!pipeline status R77` 返回当前状态和当前 step |
| 3 | 状态推进 | `!pipeline advance R77` 将 current_step +1，JSON 同步更新 |
| 4 | 阻塞与恢复 | `!pipeline block R77` 后 status=BLOCKED，`advance` 恢复为 RUNNING |
| 5 | 归档 | `!pipeline archive R77` 后该上下文进入 JSONL 历史 |
| 6 | legacy 兼容 | `!pipeline_state` 和 `!status` 等旧命令至少返回当前状态快照 |
| 7 | 重启不丢数据 | server 重启后 `!pipeline list` 正确恢复所有活跃管线状态 |

---

## 4. 非功能性需求

| # | 要求 | 指标 |
|:-:|:-----|:-----|
| 1 | 兼容性 | 现有 `!pipeline_state` / `!status` 等命令至少不崩溃，不影响现有功能 |
| 2 | 数据完整性 | JSON 写盘异常（IOError）不应导致进程退出，应回退到内存状态 |
| 3 | 并发安全 | Manager 操作需加 `asyncio.Lock`（与现有 workspace 模式一致） |
| 4 | 测试覆盖 | 新增模块覆盖率 ≥ 80%，至少覆盖状态机所有转换 |

---

## 5. 不包含在本轮的内容

| 事项 | 原因 |
|:-----|:------|
| ❌ 修改 bot 行为 | R77 只改 server 端，bot 依然通过 inbox 消息驱动管线 |
| ❌ 修改 WebSocket 协议 | 新增 `!pipeline` 命令复用现有消息路由，不新增消息类型 |
| ❌ 自动 resume | resume 逻辑需要更多设计，留给后续轮次 |
| ❌ bot 侧 PipelineContext 感知 | bot 侧引入共享 dataclass 需要版本同步，本轮不做 |

---

## 6. 影响范围

| 模块 | 影响 | 说明 |
|:-----|:-----|:------|
| `server/handler.py` | ⚠️ 中等 | 新增 `!pipeline` 命令路由 + 逐步替换 `_PIPELINE_STATE` 引用 |
| `server/pipeline_sync.py` | ⚠️ 中等 | `PipelineGitSync.__init__` 可接收 `PipelineContext` 替代零散配置参数 |
| `server/task_store.py` | ℹ️ 无影响 | 任务存储独立于管线上下文 |
| `server/workspace.py` | ℹ️ 无影响 | workspace 管理独立 |
| `shared/protocol.py` | ℹ️ 无影响 | 本轮不新增协议消息类型 |
| `clients/python/ws_client.py` | ℹ️ 无影响 | 客户端不变 |
| 各 bot 代码 | ✅ 无影响 | bot 行为不变 |

---

## 7. 技术方案参考

详见 `docs/research/deepcode-orchestrator-study.md` §2.1 WorkflowContext 章节。

核心参考代码：
- DeepCode `WorkflowContext`：`workflows/workflow_context.py`（dataclass + derived paths + legacy bridge）
- DeepCode `prepare_workflow_environment`：`workflows/environment.py`（统一初始化 + fail fast + resume detection）
