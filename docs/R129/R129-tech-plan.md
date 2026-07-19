# R129 技术方案 — PipelineAutoStarter 退役

> **轮次：** R129
> **类型：** 代码清理
> **作者：** 小开（架构师）
> **版本：** v1.0
> **日期：** 2026-07-19
> **状态：** ✅ 定稿
>
> **前置文档：**
> - [需求文档](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R129/R129-product-requirements.md)
> - [WORK_PLAN](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R129/WORK_PLAN.md)

---

## 1. 范围确认

### 1.1 删除文件

| 文件 | 行数 | 说明 |
|:-----|:----:|:------|
| `server/ws_server/pipeline_auto_starter.py` | 211 | 整个文件删除 |

### 1.2 修改文件

| 文件 | 改动点位 | 约行数 |
|:-----|:---------|:------:|
| `server/ws_server/__main__.py` | L18 import + L796-835 PAS init 块 | **-40** |
| `server/ws_server/pipeline_context.py` | 两段 `from_work_plan` 方法（R109 + R110） | **-221** |

> **⚠️ 重要发现：** `pipeline_context.py` 中存在两个同名 `from_work_plan` 方法：
> - **R109 版**（L431-582）：第一个定义，签名 `(work_plan_path, workspace_dir, ...)` — 已被 R110 版**覆盖**，运行时永远不可达
> - **R110 版**（L647-715）：第二个定义，签名 `(round_name, work_plan_path, repo_path, ...)` — 仅被 PAS 调用
>
> 两者均需删除，实际清理行数（**-221**）大于需求预估（-70）。具体分析见 §3。

### 1.3 文档清理

| 文件 | 检查结果 |
|:-----|:---------|
| `docs/inbox-message-protocol.md` | ✅ 无 PAS 引用，无需修改 |
| `docs/TODO.md` | ✅ 无 PAS 引用，无需修改 |

### 1.4 不修改

| 文件 | 原因 |
|:-----|:------|
| `server/ws_server/pipeline_engine.py` | 仅 docstring 注释提及（L27/L32/L82），§5 明确排除 |
| `docs/R110/*` | 历史轮次文档，不进本次 git 修改 |
| 根目录 `dispatch_r110_v*.py` / `trigger_r110.py` / `run_r110.py` | 独立历史脚本，不参与 server 启动 |

---

## 2. `from_work_plan()` 调用链分析

### 2.1 调用图

```
┌─────────────────────────────────────┐
│ pipeline_auto_starter.py (L190)     │ ← 唯一调用者
│   ctx = await self._ctx_mgr         │
│         .from_work_plan(...)        │
└──────────┬──────────────────────────┘
           │ 3 参数调用
           ▼
┌─────────────────────────────────────┐
│ pipeline_context.py: L649 (R110版)  │
│   async def from_work_plan(         │
│     round_name, work_plan_path,     │
│     repo_path, pm_agent_id,         │
│     role_to_agent_ids               │
│   )                                 │
└─────────────────────────────────────┘
```

### 2.2 确认结果

| 检查项 | 结果 |
|:-------|:----:|
| `from_work_plan` 在 `server/` 内的调用者 | 仅有 `pipeline_auto_starter.py` L190 |
| `from_work_plan` 在全仓库的调用者 | 除 `pipeline_auto_starter.py` + 自身定义外无其他 |
| `##start` 是否调用 `from_work_plan` | ❌ 不调用。`_handle_hash_start`（main.py L3507）直接构造 `PipelineContext(...)` + `mgr.set_context()` |
| `auto_router.py` 是否依赖 | ❌ 独立 CLI 脚本，无任何引用 |

**结论：** ✅ `from_work_plan()` 无外部调用者，可安全删除。

---

## 3. 代码分析 — 两个 `from_work_plan` 方法

### 3.1 现状分析

`PipelineContextManager` 类中存在两个同名的 `from_work_plan` 方法。Python 类定义按从上到下顺序执行，第二个定义**覆盖**第一个。因此：

| 版本 | 行号 | 签名 | 运行时状态 |
|:-----|:----:|:-----|:----------:|
| R109 | L431-582 | `(self, work_plan_path, workspace_dir, workspace_id, pm_inbox_id, created_by)` | **❌ 死代码** — 被 R110 版覆盖，永不执行 |
| R110 | L647-715 | `(self, round_name, work_plan_path, repo_path, pm_agent_id, role_to_agent_ids)` | **❌ 死代码** — 仅 PAS 调用，PAS 自 R119 起禁用 |

### 3.2 清理方案

两段代码全部删除：

| 删除范围 | 行号 | 行数 | 原因 |
|:---------|:----:|:----:|:------|
| R109 代码段 | L431-582 | 152 | 被覆盖的死代码 + `created_by` 参数 |
| R110 代码段 | L647-715 | 69 | PAS 专用，PAS 退役后不可达 |
| **合计** | | **-221** | |

### 3.3 是否保留 R109 版作为 `##start` 的备用入口？

**不保留。** 理由：
- `##start`（`_handle_hash_start`）完全不调用 `from_work_plan`
- `##start` 创建 PipelineContext 的方式已成熟：手动构建 steps_list + references + templates，通过 `mgr.set_context()` 落盘
- 保留 152 行死代码徒增维护负担和认知开销
- 需求文档 §5 明确：不重构 from_work_plan 替代逻辑

---

## 4. `__main__.py` 清理确认

### 4.1 需删除代码段

**① L18 — import 语句**
```python
from .pipeline_auto_starter import PipelineAutoStarter  # R110
```
删除此行。

**② L796-835 — PAS 初始化和启动块**
```python
    # ── R110: PipelineAutoStarter — Git 感知管线自动启动 ──
    _pas_enabled = os.environ.get("PAS_ENABLED", "1") == "1"
    if _pas_enabled:
        _pas = PipelineAutoStarter(...)
        async def _start_pas(app): ...
        app.on_startup.append(_start_pas)
        app.on_shutdown.append(lambda _: _pas.stop())
        logger.info("[PAS] enabled, poll_interval=60s")
    else:
        logger.info("[PAS] disabled (PAS_ENABLED=0)")
```
删除 L796-835 整块（含注释 + 空行前后衔接）。

### 4.2 不改动的相邻代码

| 代码 | 行号 | 处理 |
|:-----|:----:|:------|
| `app = web.Application()` | L794 | 保留 |
| `##start` → `_start_retry_loop` 间隔空行 | L836 | 微调确保无缝衔接 |
| `# ── R118: 启动离线重试循环 ──` | L837 | 保留 |

---

## 5. 删除后影响分析

### 5.1 直接影响

| 依赖 | 删除后状态 |
|:-----|:-----------|
| import 链 | 无其他文件 import `pipeline_auto_starter` |
| `from_work_plan` 调用 | 无其他调用者，删除安全 |
| `created_by="system:pipeline_auto_starter"` | 此值只在 `from_work_plan` 中出现，删除后无残留 |
| `os.environ["PAS_ENABLED"]` | 从环境变量读取处删除，其他部署脚本若设置此变量将被忽略（不影响运行） |

### 5.2 间接影响

| 影响面 | 分析 |
|:-------|:------|
| `engine.auto_dispatch()` | PAS 内部包装调用 `engine.auto_dispatch(ctx, 1)`，但 `_auto_dispatch` 本身在 `##start` / `try_advance` 中正常使用，不受影响 |
| `_send_to_agent` (PAS dispatch 包装) | PAS 内部包装函数，删除后不影响 `main.py` 的 `_send_to_agent` |
| 模块加载时序 | 删除 PAS 后，`__main__.py` 启动流程更简洁，无任何新依赖 |

---

## 6. 改动清单（精确）

### 文件 A: 删除 `pipeline_auto_starter.py`

| 操作 | 影响 |
|:-----|:------|
| `git rm server/ws_server/pipeline_auto_starter.py` | -211 行 |

### 文件 B: 修改 `__main__.py`

| 操作 | 行号 | 行数 |
|:-----|:----:|:----:|
| 删除 `from .pipeline_auto_starter import PipelineAutoStarter` | L18 | -1 |
| 删除 PAS init 块（注释 + PAS_ENABLED 读取 + if/else 分支 + _start_pas + on_startup/on_shutdown） | L796-L835 | -40 |
| 调整 L836 空行（缩至 1 行） | L836 | -1 |

**实际删除：-41 行**（需求预估 -35，差异源自注释 + 空行精算）

### 文件 C: 修改 `pipeline_context.py`

| 操作 | 行号 | 行数 |
|:-----|:----:|:----:|
| 删除 R109 `from_work_plan`（注释 + 方法体） | L431-L582 | -152 |
| 删除 R110 `from_work_plan`（注释 + 方法体 + 尾部注释） | L647-L715 | -69 |

**实际删除：-221 行**（需求预估 -70，差异原因见 §3 分析）

### 合计

| 文件 | 行数 | 需求预估 |
|:-----|:----:|:--------:|
| `pipeline_auto_starter.py` | -211 | -211 |
| `__main__.py` | -41 | -35 |
| `pipeline_context.py` | -221 | -70 |
| 文档 | 0 | -10 |
| **净删除** | **-473** | **-326** |

> 差异原因：`pipeline_context.py` 中存在两段 `from_work_plan`（R109 + R110），需求文档只估算了 R110 一段。

---

## 7. 操作步骤（Dev 角度）

### Step 3.1 — 删除文件
```bash
git rm server/ws_server/pipeline_auto_starter.py
```

### Step 3.2 — 清理 `__main__.py`
1. 删除 L18 的 `from .pipeline_auto_starter import PipelineAutoStarter`
2. 删除 L796-L835 的整个 PAS init 块
3. `py_compile` 验证

### Step 3.3 — 清理 `pipeline_context.py`
1. 删除 L431-L582（R109 `from_work_plan` 方法 + 注释）
2. 删除 L647-L715（R110 `from_work_plan` 方法 + 注释）
3. `py_compile` 验证

### Step 3.4 — 全局验证
```bash
grep -rn "PipelineAutoStarter\|pipeline_auto_starter\|PAS_ENABLED\|from_work_plan" server/
```
应仅返回历史轮次文档和 `pipeline_engine.py` 注释中的引用。

---

## 8. 验收确认

### 8.1 架构师确认

| # | 检查项 | 状态 |
|:-:|:-------|:----:|
| V-1 | 删除范围确认：3 个文件改动点（pipeline_auto_starter.py 删除 + __main__.py 清理 + pipeline_context.py 清理） | ✅ |
| V-2 | `from_work_plan()` 无其他调用者：仅 PAS 一处调用 | ✅ |
| V-3 | `pipeline_context.py` 中存在两段 `from_work_plan`（R109 + R110），均需删除 | ✅ |
| V-4 | 文档（inbox-message-protocol.md / TODO.md）无 PAS 引用，无需修改 | ✅ |
| V-5 | `pipeline_engine.py` 注释引用明确排除在本轮之外 | ✅ |

### 8.2 技术方案要点

- **实际净删 473 行**（vs 需求预估 326 行，差异来自 `pipeline_context.py` 双方法）
- **零新增行** ✅
- **零行为变更**（PAS 已自 R119 起禁用）

---

## 9. 技术债务说明

本次清理消除的技术债务：

| 债务项 | 说明 |
|:-------|:------|
| 废弃代码 | PipelineAutoStarter 211 行完整模块 |
| 伪代码（被覆盖的方法） | R109 `from_work_plan` 152 行 — 定义存在但永不执行 |
| 冗余配置 | `PAS_ENABLED` 环境变量不再需要 |
| 误导性 import | `__main__.py` 中的 PAS import 让人误以为该功能仍活跃 |

---

*文档版本：v1.0 · 2026-07-19 · 小开*
