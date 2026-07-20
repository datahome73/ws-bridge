# R138 Step 4 — 代码审查报告 🔍

> **轮次：** R138（引擎合并轮 — engine2.py → pipeline_engine.py）
> **审查人：** 🔍 小周
> **审查对象：** commit `66ce2dbcf8b6`
> **依据：** `docs/R138/R138-product-requirements.md`, `docs/R138/R138-tech-plan.md`
> **审查基准：** dev HEAD `66ce2dbcf8b6`

---

## ✅ 审查结论：通过

---

## 一、文件改动总览

| # | 文件 | 动作 | 行数变化 | 内容 |
|:-:|:-----|:----:|:--------:|:-----|
| 1 | `server/ws_server/engine2.py` | ❌ 删除 | **-1544** | 原临时提取文件，内容已合并入 pipeline_engine.py |
| 2 | `server/ws_server/pipeline_engine.py` | 🔧 合并 | **+1678 -796** | 模块级函数 + PipelineEngine class 合体（~2200 行） |
| 3 | `server/ws_server/main.py` | 🔧 import | **+1 -1** | `from .engine2` → `from .pipeline_engine` |
| 4 | `server/ws_server/scenario_matcher.py` | 🔧 import | **+4 -4** | 4 处 `engine2 as _e2` → `pipeline_engine as _e2` |
| **合计** | | | **+1683 -2345（净 -662）** | |

---

## 二、审查项逐项验证

| # | 审查项 | 预期 | 结果 | 证据 |
|:-:|:-------|:-----|:----:|:-----|
| 1 | `engine2.py` 已从文件系统删除 | 磁盘和 API tree 无 engine2 | ✅ | GitHub API tree 确认：`server/ws_server/engine2.py` 不存在 |
| 2 | `main.py` import 已更新 | 不引用 engine2 | ✅ | `from .pipeline_engine import PipelineEngine` (L31)；`from .pipeline_engine import _resolve_card_key_to_ws_id, _extract_artifact_kv` (L48) — 无 engine2 引用 |
| 3 | `scenario_matcher.py` import 已更新 | engine2 → pipeline_engine | ✅ | 4 处 `from . import pipeline_engine as _e2`（L215, L266, L407, L503） |
| 4 | `_ensure_engine()` 模块级存在 | 可被 scenario_matcher 调用 | ✅ | `pipeline_engine.py` L2193-2196：模块级函数，惰性 import 转发到 `main._ensure_engine()` |
| 5 | `_ensure_pipeline_manager()` 模块级存在 | 可被 scenario_matcher 调用 | ✅ | `pipeline_engine.py` L2198-2201：模块级函数 |
| 6 | `_handle_hash_*` 模块级存在 | 可被 scenario_matcher 调用 | ✅ | `_handle_hash_start` L1295 / `_handle_hash_status` L1421 / `_handle_hash_stop` L1502 / `_handle_hash_advance` L1147 / `_handle_hash_archive` L1205 / `_archive_pipeline` L1238 |
| 7 | PipelineEngine class 接口不变 | 外部调用者使用的方法仍可用 | ✅ | 22 个方法：`start/stop`, `format_context`, `find_archive`, `auto_dispatch`, `handle_hash_*`, `notify_pm`, `handle_reject`, `render_template`, `try_advance`, `restore_*` 等 |
| 8 | B-5 PM fallback bug 已修复 | `auto_dispatch` 无危险 PM fallback | ✅ | `auto_dispatch` (class method) 以 engine2 版本为核心，无 PM fallback 链，返回 False+log warning |
| 9 | import 测试通过 | 无 ImportError | ✅ | `python3 -c "from server.ws_server import main; from server.ws_server import pipeline_engine as pe"` → ✅ |
| 10 | 无循环依赖 | engine2↔main 问题消除 | ✅ | engine2.py 已删除，pipeline_engine.py 的 `_ensure_engine`/`_ensure_pipeline_manager` 使用函数级惰性 import |

---

## 三、PipelineEngine class 对外接口

| 方法 | 对外类型 | 调用方 | 结果 |
|:-----|:--------:|:-------|:----:|
| `format_context(ctx)` | ✅ 公有方法 | scenario_matcher: `_e2._ensure_engine().format_context(ctx)` | ✅ |
| `find_archive(round_name)` | ✅ 公有方法 | scenario_matcher: `_e2._ensure_engine().find_archive(round_name)` | ✅ |
| `auto_dispatch(ctx, step_num)` | ✅ 公有方法 | `_ensure_engine().auto_dispatch()` | ✅ |
| `handle_hash_start(...)` | ✅ 公有方法 | 支持 scenario_matcher 通过 module-level 函数调用 | ✅ |
| `_ensure_git_scan()` / `_ensure_timeout_scanner()` | ✅ 公有方法 | `_ensure_engine()._ensure_git_scan()` | ✅ |
| `render_template(...)` / `build_step_summary(...)` | ✅ 公有方法 | 通过 `_ensure_engine()` 调用 | ✅ |

---

## 四、B-5 PM fallback bug 修复确认

```python
# pipeline_engine.py: auto_dispatch (class method)
async def auto_dispatch(self, ctx: PipelineContext, step_num: int) -> bool:
    ...
    next_step_key = f"step{step_num}"
    next_template = ctx.message_templates.get(next_step_key) if hasattr(ctx, "message_templates") else None
    ...
```

✅ 使用 engine2 版本的 `_auto_dispatch`（无 PM fallback 链）
✅ `ctx.steps` 找不到 agent_id 时 return False + log warning
✅ 不再静默发错人

---

## 五、场景路由验证

### scenario_matcher `handle_hash_cmd`（L407-418）

```
##start##R138##k=v  
  → _e2._handle_hash_start(round_name, kv, agent_id, ws)   ✅

##status##R138
  → _e2._handle_hash_status(round_name, agent_id, ws)       ✅

##stop##R138
  → _e2._handle_hash_stop(round_name, agent_id, ws)         ✅

##advance##R138
  → _e2._handle_hash_advance(round_name, kv, agent_id, ws)  ✅

##archive##R138
  → _e2._handle_hash_archive(round_name, agent_id, ws)      ✅
```

### scenario_matcher `handle_query` status（L266-274）

```
##query##status
  → _e2._ensure_pipeline_manager() → get(round_name)
  → _e2._ensure_engine().format_context(ctx)
  → _e2._ensure_engine().find_archive(round_name)           ✅
```

---

## 六、汇总 & 结论

### 亮点
- engine2.py 成功合并入 pipeline_engine.py，模块级函数 + PipelineEngine class 同文件共存
- scenario_matcher 路由切换完整（4 处 `engine2` → `pipeline_engine`）
- PipelineEngine class 22 个方法接口完整，向后兼容
- B-5 PM fallback bug 修复随合并完整保留
- import 测试通过，无循环依赖

### 结论
> **✅ 通过** — engine2.py 已删除，所有 import 路径正确更新，PipelineEngine class 接口完整，B-5 修复保留，import 验证通过。

---

*审查结束*
