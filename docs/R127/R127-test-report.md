# R127 Step 5 🧪 测试报告 — 管线状态机提取（PipelineEngine 模块化）

> **轮次：** R127 | **类型：** 代码重构轮  
> **测试角色：** 🦐 泰虾  
> **基线：** `8f5bdd0` (R126 Step 5) | **被测：** `02690c3` (R127 Step 3)  
> **日期：** 2026-07-19  

---

## 总览

| 分组 | P0 项 | 通过 | 失败 | 通过率 |
|:-----|:-----:|:----:|:----:|:------:|
| PE Pipeline Engine 提取 | 11 | 5 | **6** | 45% |
| RV 回归验证 | 5 | 2 | **3** | 40% |
| **合计** | **16** | **7** | **9** | **44%** |

> ⛔ **结论：不通过 — 4 个 Critical 缺陷，需修复后重新验证**

---

## 验收标准逐项验证

### PE-N: Pipeline Engine 提取

| # | 描述 | 结果 | 详情 |
|:-:|:-----|:----:|:-----|
| **PE-1** | `pipeline_engine.py` 存在且可导入 | 🟢 **通过** | `python -m py_compile server/ws_server/pipeline_engine.py` → exit 0 |
| **PE-2** | `PipelineEngine` 所有方法签名与旧函数一致 | 🟢 **通过** | 28+ 方法在 PipelineEngine 类中定义，签名与 main.py 旧函数一致 |
| **PE-3** | `main.py` 中所有管线函数引用替换为 `engine.*` 调用 | 🔴 **不通过** | ⛔ **Critical-2**: 28+ 旧函数定义仍全部保留在 main.py 中（`_try_advance_pipeline`, `_auto_dispatch`, `_notify_pm`, `_handle_hash_*` 等）。main.py 由期望的 ~3300 行仅减至 4918 行，实际删除 ~391 行（期望 ~2000 行）。 |
| **PE-4** | `##start` 创建管线 | 🔴 **不通过** | ⛔ **Critical-1**: scenario_matcher.py `_engine` 是局部变量永远为 None，`##` 命令全部无声失败 |
| **PE-5** | `##status` 返回管线状态 | 🔴 **不通过** | 同上 |
| **PE-6** | `##stop` 停止管线 | 🔴 **不通过** | 同上 |
| **PE-7** | `##advance` 推进 step | 🔴 **不通过** | 同上 |
| **PE-8** | `##archive` 归档管线 | 🔴 **不通过** | 同上 |
| **PE-9** | `engine.try_advance()` 处理 ✅ 完成 | 🟢 **通过** | `_sm_handle_complete` 已改为 `_ensure_engine().try_advance()` |
| **PE-10** | `engine.auto_dispatch()` 派活 | 🔴 **不通过** | ⛔ **Critical-4**: `__main__.py` `_pas_dispatch` 闭包捕获 `None` engine，`engine.auto_dispatch(ctx,1)` 会崩溃 |
| **PE-11** | `engine.notify_pm()` 通知 | 🟢 **通过** | 方法已正确重构到 PipelineEngine |

### RV-N: 回归验证

| # | 描述 | 结果 | 详情 |
|:-:|:-----|:----:|:-----|
| **RV-1** | `py_compile` 全量零错误 | 🟢 **通过** | `server/ws_server/*.py` 全部编译通过 |
| **RV-2** | 后台扫描循环正常启动 | 🔴 **不通过** | ⛔ **Critical-3**: `__main__.py:840` `engine._retry_loop()` 在 engine 为 None 时崩溃。line 848 `engine.restore_pipeline_dispatches()` 同理。**服务无法启动** |
| **RV-3** | `scenario_matcher.dispatch()` 调用 `engine.handle_hash_*` | 🔴 **不通过** | ✏️ 调用路径已改写，但因局部变量 bug（C-1），实际运行时 `_engine` 永远为 None |
| **RV-4** | `PipelineAutoStarter` 调用 `engine.auto_dispatch` | 🔴 **不通过** | `__main__.py` 传参已改，但捕获 `None` engine（C-4） |
| **RV-5** | R126 `scenario_matcher` 不受影响 | 🟢 **通过** | 文件结构未破坏，编译通过，旧代码路径正常 |

---

## ⛔ Critical 缺陷详情

### C-1: scenario_matcher.py `_engine` 局部变量永远为 None

**位置：** `server/ws_server/scenario_matcher.py:195`

```python
async def handle_hash_cmd(ws, agent_id: str, msg: dict, matched: Any) -> bool:
    ...
    # Import callbacks — set by main.py after engine init
    from .pipeline_engine import PipelineEngine
    _engine: PipelineEngine = None  # type: ignore   ← 函数体内局部变量！
    
    if cmd == "start":
        return await _engine.handle_hash_start(...) if _engine else False  # 永远 False
```

**根因：** `_engine: PipelineEngine = None` 声明在 `handle_hash_cmd` 函数体内，是**局部变量**。main.py 中的 `_sm._engine = engine` 设置的是**模块级属性**，二者无关。所有 `##` 命令返回 `False`（无声失败）。

**修复方案：** 
```python
# 方案 A: 模块级声明
_engine: Optional[PipelineEngine] = None  # 放在 import 之后
# 然后在函数内：global _engine 或直接引用
```

---

### C-2: main.py 旧管线函数未删除（~2000 行重复代码）

**位置：** `server/ws_server/main.py` — 以下旧函数全部保留：

| 函数 | 行号 | 说明 |
|:-----|:----:|:------|
| `_start_git_sync_loop` | 523 | 已搬到 engine |
| `_pipeline_git_sync_scan` | 533 | 已搬到 engine |
| `_start_timeout_scan_loop` | 578 | 已搬到 engine |
| `_pipeline_timeout_scan` | 588 | 已搬到 engine |
| `_auto_advance_pipeline` | 686 | 已搬到 engine |
| `_format_pipeline_context` | 1307 | 已搬到 engine |
| `_restore_pipeline_timers` | 1380 | 已搬到 engine |
| `_restore_pipeline_dispatches` | 1413 | 已搬到 engine |
| `_try_advance_pipeline` | 2584 | 已搬到 engine |
| `_notify_pm` | 2702 | 已搬到 engine |
| `_retry_loop` | 2782 | 已搬到 engine |
| `_enqueue_retry` | 2817 | 已搬到 engine |
| `_render_template` | 2835 | 已搬到 engine |
| `_get_step_agent_name` | 2905 | 已搬到 engine |
| `_build_step_summary` | 2924 | 已搬到 engine |
| `_find_archive` | 2958 | 已搬到 engine |
| `_auto_re_notify` | 3028 | 已搬到 engine |
| `_auto_dispatch` | 3070 | 已搬到 engine |
| `_handle_reject` | 3187 | 已搬到 engine |
| `_handle_hash_advance` | 3362 | 已搬到 engine |
| `_handle_hash_archive` | 3419 | 已搬到 engine |
| `_archive_pipeline` | 3452 | 已搬到 engine |
| `_handle_hash_start` | 3507 | 已搬到 engine |
| `_handle_hash_status` | 3631 | 已搬到 engine |
| `_handle_hash_stop` | 3710 | 已搬到 engine |
| `_broadcast_workspace_archived` | 4612 | 已搬到 engine |

**总计 28 个函数残留，~2000 行重复代码。**

---

### C-3: `__main__.py` 启动时 `engine` 为 None 导致崩溃

**位置：** `server/ws_server/__main__.py:839-840, 847-848`

```python
async def _start_retry_loop(app):
    from .main import engine    # engine = None
    asyncio.create_task(engine._retry_loop())  # ❌ AttributeError!

async def _restore_dispatches(app):
    from .main import engine    # engine = None
    await engine.restore_pipeline_dispatches()  # ❌ AttributeError!
```

**根因：** `engine` 在 main.py 中初始化为 `None`，仅通过 `_ensure_engine()` 惰性初始化（在首次收到消息时调用）。启动回调直接访问 `engine._retry_loop()` 时 engine 仍为 None。

---

### C-4: `_start_pas` 闭包捕获 `None` engine

**位置：** `server/ws_server/__main__.py:809-826`

```python
async def _start_pas(app):
    from .main import _ensure_pipeline_manager, engine  # engine = None
    ...
    async def _pas_dispatch(round_name, agent_id, content):
        ...
        await engine.auto_dispatch(ctx, 1)  # ❌ 闭包中的 engine 永远为 None
```

**根因：** `_pas_dispatch` 闭包在 `_start_pas` 中定义时捕获了 `engine = None`，即使后续 `_ensure_engine()` 被调用，闭包引用不会更新。

---

## ✅ 通过的测试

| 编号 | 描述 |
|:----|:-----|
| PE-1 | `pipeline_engine.py` 存在且编译通过 |
| PE-2 | PipelineEngine 方法签名完整 |
| PE-9 | `try_advance()` 调用路径改造正确 |
| PE-11 | `notify_pm()` 已正确迁移 |
| RV-1 | 全量 `py_compile` 零错误 |
| RV-5 | R126 scenario_matcher 未受影响 |
| ✅ | `pipeline_engine.py` 自身代码质量良好，1267 行结构清晰 |

---

## 修复建议（按优先级）

### P0 — 启动即崩溃

| # | 修复 | 文件 | 改动量 |
|:-:|:-----|:-----|:------:|
| 1 | `__main__.py` 启动回调改为 `_ensure_engine()` 获取 engine | `__main__.py:839,847` | ~5 行 |
| 2 | 同上修复 `_start_pas` 闭包 | `__main__.py:809` | ~3 行 |

### P0 — 功能不可用

| # | 修复 | 文件 | 改动量 |
|:-:|:-----|:-----|:------:|
| 3 | 将 `_engine` 移到模块级 + 移除局部声明 | `scenario_matcher.py` | ~5 行 |
| 4 | 注入 engine 引用到 scenario_matcher 模块 | `main.py:_ensure_engine()` | ~3 行 |

### P0 — 代码重复

| # | 修复 | 文件 | 改动量 |
|:-:|:-----|:-----|:------:|
| 5 | 删除 main.py 中全部 28 个旧函数定义 | `main.py` | **~2000 行删除** |

---

## 交付物

- [x] 测试报告：`docs/R127/R127-test-report.md`
- [ ] 修复 commit（待开发修复）
- [ ] 验证后推送

---

*测试完成：9/16 FAIL ⛔ — 4 Critical 缺陷，需修复后重新验证*
