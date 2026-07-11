---
pipeline:
  steps:
    - step: 2
      role: architect
      task: 技术方案
    - step: 3
      role: developer
      task: 编码实现
    - step: 4
      role: reviewer
      task: 代码审查
    - step: 5
      role: qa
      task: 测试验证
    - step: 6
      role: admin
      task: 合并部署
  timeout_minutes: 30
workspace:
  name: R77-dev
  members:
    - name: 架构师
      role: architect
    - name: 开发工程师
      role: developer
    - name: 审查工程师
      role: reviewer
    - name: 测试工程师
      role: qa
    - name: 项目管理
      role: admin
---
# R77 工作计划 — PipelineContext：统一管线上下文对象 📋

> **版本：** v1.0（初稿）
> **状态：** 📝 待审核
> **项目协调人：** 🧐 需求分析师
> **基于需求文档：** [docs/R77/R77-product-requirements.md](https://raw.githubusercontent.com/datahome73/ws-bridge/287af9b/docs/R77/R77-product-requirements.md) v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**~200 行净增，严禁 scope creep**

| 本轮做 | 本轮不做 |
|:-------|:---------|
| `PipelineContext` dataclass 定义 + 状态机 | 修改 bot 行为 |
| `PipelineContextManager` 生命周期管理 | 修改 WebSocket 协议 |
| `!pipeline` 命令（status / list / advance / block / archive） | 修改 `shared/protocol.py` |
| 替换 handler.py 中 `_PIPELINE_STATE` 引用 | 修改 `_ROLE_AGENT_MAP` / `_step_ack_states`（留到下一轮） |
| JSON 持久化（pipeline_contexts.json） | 自动 resume 逻辑 |
| PipelineGitSync 接收 PipelineContext 替代零散配置参数 | bot 侧 PipelineContext 感知 |

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | 架构师 | 开发工程师 | — |
| Step 3 | 💻 编码实现 | 开发工程师 | 架构师 | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 代码审查 | 审查工程师 | 测试工程师 | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试验证 | 测试工程师 | 审查工程师 | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | 项目管理 | 架构师 | — |

---

## 1. 管线总览

### 核心架构

R77 新增一个模块 `server/pipeline_context.py`，包含 `PipelineContext` 数据模型 + `PipelineContextManager` 生命周期管理。同时修改 `server/handler.py` 将现有的模块级 `_PIPELINE_STATE` 全局状态迁移到 Manager 管理。

```
新增模块:
server/pipeline_context.py
  ├── PipelineStatus         枚举 (INIT / PLANNING / RUNNING / BLOCKED / COMPLETED / CANCELLED)
  ├── PipelineTaskKind       枚举 (DEV / REVIEW / DEPLOY / DOCS)
  ├── PipelineContext        dataclass（纯数据，含派生路径 property）
  └── PipelineContextManager 生命周期管理（CRUD + JSON 持久化 + 并发锁）

修改模块:
server/handler.py
  ├── _PIPELINE_STATE → _pipeline_manager.get().status
  ├── 新增 "!pipeline" 命令路由
  └── 现有 !pipeline_state / !status 兼容

server/pipeline_sync.py
  └── PipelineGitSync 接受 PipelineContext 替代配置字典
```

### 改动范围

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:-----|:----:|
| 1 | 核心 | 新增 `PipelineContext` dataclass + `PipelineStatus` / `PipelineTaskKind` 枚举 + 派生路径 property | `server/pipeline_context.py` | ~50 行 |
| 2 | 核心 | 新增 `PipelineContextManager` 生命周期（create/get/update/advance/archive + JSON 持久化 + 并发锁） | `server/pipeline_context.py` | ~80 行 |
| 3 | 集成 | handler.py 初始化时创建 Manager，注入到模块级 | `server/handler.py` | ~10 行 |
| 4 | 集成 | 新增 `!pipeline status/list/advance/block/archive` 命令路由 | `server/handler.py` | ~40 行 |
| 5 | 兼容 | `_PIPELINE_STATE` 读写逐步迁移到 Manager 读取（保留旧变量标记 deprecated） | `server/handler.py` | ~15 行 |
| 6 | 集成 | `PipelineGitSync` 构造函数接收 `PipelineContext` 替代零散 config 参数字典 | `server/pipeline_sync.py` | ~10 行 |

**总估算：** ~205 行净增

---

## 2. 分步计划

---

### Step 2 🏗️ 技术方案

**角色：** 架构师
**输入：** [需求文档](https://raw.githubusercontent.com/datahome73/ws-bridge/287af9b/docs/R77/R77-product-requirements.md) ✅
**产出：** 技术方案文档 + 代码实现计划

**要点：**
- 确定 `PipelineContext` 最终字段列表（与需求文档一致）
- 确定 JSON 持久化路径 (`DATA_DIR / "pipeline_contexts.json"`)
- 确定并发锁策略（asyncio.Lock，与 workspace 一致）
- 评估 `_PIPELINE_STATE` 所有引用点（grep handler.py 中 `_PIPELINE_STATE` 的出现位置）

---

### Step 3 💻 编码实现

**角色：** 开发工程师
**输入：** 技术方案 ✅
**产出：** `server/pipeline_context.py` + handler.py + pipeline_sync.py 改动

**实现要点：**

#### 3.1 PipelineContext

```python
@dataclass
class PipelineContext:
    round_name: str
    task_kind: PipelineTaskKind
    workspace_dir: Path
    task_dir: Path
    workspace_id: str
    pm_inbox_id: str
    status: PipelineStatus
    current_phase: str
    current_step: int
    total_steps: int
    blocked_reason: str | None
    role_agent_map: dict[str, str]
    agent_card_ids: dict[str, str]
    created_at: float
    updated_at: float
    created_by: str
    tags: dict[str, str]

    @property
    def work_plan_path(self) -> Path: ...
    @property
    def report_path(self) -> Path: ...

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "PipelineContext": ...
```

#### 3.2 PipelineContextManager

```python
class PipelineContextManager:
    _lock: asyncio.Lock
    _contexts: dict[str, PipelineContext]

    def get(self, round_name: str) -> PipelineContext | None
    def get_all_active(self) -> list[PipelineContext]
    def create(self, ...) -> PipelineContext
    def update_status(self, round_name, status) -> bool
    def advance_step(self, round_name) -> bool
    def archive(self, round_name) -> bool
    def get_history(self, limit=20) -> list[dict]

    def _save(self)       # 写 JSON
    def _load(self)       # 读 JSON（init 时调用）
```

#### 3.3 handler.py 集成

```python
# 模块级初始化
_pipeline_manager: PipelineContextManager | None = None

# server 初始化时
_pipeline_manager = PipelineContextManager(data_dir=DATA_DIR)

# Handler 路由 — "!pipeline" 命令
async def _handle_pipeline_command(...):
    if cmd == "status":
        ctx = _pipeline_manager.get(round_name)
        return format_context(ctx)
    elif cmd == "advance":
        _pipeline_manager.advance_step(round_name)
        ...
```

#### 3.4 pipeline_sync.py

```python
# 改动前:
PipelineGitSync(pipeline_id, config={'branch': ..., 'repo_path': ..., ...})

# 改动后:
PipelineGitSync(pipeline_id, context=PipelineContext)
# 内部从 context 读取 workspace_dir 等
```

---

### Step 4 🔍 代码审查

**角色：** 审查工程师
**输入：** 代码实现 ✅
**产出：** 审查报告

**审查要点：**
- [ ] `PipelineContext` 字段完整性 — 是否覆盖需求文档所有字段
- [ ] 状态机转换逻辑 — 所有合法转换是否覆盖
- [ ] 并发安全 — `_save` 在 lock 内
- [ ] JSON 序列化/反序列化 — Path 类型处理，enum 处理
- [ ] 异常处理 — IOError 不导致进程退出，回退到内存状态
- [ ] 向后兼容 — 旧命令不断，`_PIPELINE_STATE` 读写兼容
- [ ] 测试覆盖 — 状态机所有转换路径

---

### Step 5 🦐 测试验证

**角色：** 测试工程师
**输入：** 代码实现 ✅ + 审查报告 ✅
**产出：** 测试报告

**测试用例：**

| # | 用例 | 预期 |
|:-:|:-----|:-----|
| 1 | `!pipeline create R77 dev` | JSON 持久化，`!pipeline list` 可见 |
| 2 | `!pipeline status R77` | 返回 INIT 状态 |
| 3 | `!pipeline advance R77` | current_step +1，JSON 更新 |
| 4 | `!pipeline block R77 "等素材"` | status=BLOCKED，blocked_reason="等素材" |
| 5 | `!pipeline advance R77`（blocked→恢复） | status=RUNNING |
| 6 | `!pipeline archive R77` | 从活跃列表移除，出现在历史列表 |
| 7 | 旧命令 `!pipeline_state` | 至少返回当前状态快照，不崩溃 |
| 8 | server 重启 | `!pipeline list` 恢复所有活跃管线 |
| 9 | 并发调用 `advance` | 原子操作，状态不冲突 |
| 10 | JSON 写盘失败（模拟权限错误） | 进程不退出，回退内存状态 |

---

### Step 6 🦸 合并部署

**角色：** 项目管理
**输入：** 测试报告 ✅
**产出：** 合并到 main + Docker 部署

**检查清单：**
- [ ] 代码合并到 main 分支
- [ ] 项目管理从 main 拉取构建 Docker 镜像部署
- [ ] 验证 `!pipeline status R77` 在线上环境正常返回
- [ ] 验证旧 `!pipeline_state` 命令兼容
- [ ] 文档归档

---

## 3. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:----:|:----:|:---------|
| `_PIPELINE_STATE` 引用点遗漏 | 中 | 中 | Step 2 中 grep 所有引用点，逐步迁移而非重写 |
| JSON 写盘 IO 异常 | 低 | 中 | 所有写操作 `try/except`，IO 失败回退到内存状态 |
| 并行命令竞争条件 | 低 | 低 | `asyncio.Lock` 保护所有 Manager 操作 |
| 旧命令兼容遗漏 | 低 | 低 | Step 5 专门测试旧命令行为 |

---

## 4. 验收标准

- [ ] `!pipeline create R77 dev` → 创建且持久化
- [ ] `!pipeline status R77` → 当前状态快照
- [ ] `!pipeline advance R77` → step +1
- [ ] `!pipeline block R77 原因` → BLOCKED
- [ ] `!pipeline archive R77` → 归档
- [ ] 旧 `!pipeline_state` 不崩溃
- [ ] server 重启不丢状态
- [ ] PipelineGitSync 接收 PipelineContext
