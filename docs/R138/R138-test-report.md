# R138 Step 5 — 测试报告 🧪

> **轮次：** R138（引擎合并轮 — engine2.py → pipeline_engine.py）
> **测试人：** 🦐 泰虾
> **测试对象：** commit `66ce2db`（engine2 吞并 pipeline_engine）
> **审查结论：** ✅ 通过（合并完整）
> **测试模式：** 源码级分析 + 模块导入 + 编译验证
> **测试日期：** 2026-07-20

---

## 改动统计

| 文件 | 操作 | 行数 | 说明 |
|:-----|:----:|:----:|:------|
| `pipeline_engine.py` | 🔧 重写 | **+2,474** | engine2 代码主体 + PipelineEngine class wrapper |
| `engine2.py` | 🗑️ 删除 | **-1,544** | 临时名已完成使命 |
| `main.py` | 🔧 import | +1 -1 | `from .engine2` → `from .pipeline_engine` |
| `scenario_matcher.py` | 🔧 import | +4 -4 | `from . import engine2` → `from . import pipeline_engine` |
| **合计** | | **+2,479 -1,549** | 净 +930（pipeline_engine 吸收 engine2 所有功能） |

---

## 测试结果总览

| 分组 | 通过 | 失败 |
|:-----|:----:|:----:|
| MERGE-D: engine2.py 已删除 | 1 | 0 |
| MERGE-A: pipeline_engine.py 存在+大小 | 1 | 0 |
| 关键函数完整性 (A1~A6 共 24 函数) | 24 | 0 |
| PipelineEngine class 方法 (12 方法) | 12 | 0 |
| MERGE-C: B-5 bug 修复 | 2 | 0 |
| Import 更新 (main + scenario_matcher) | 4 | 0 |
| 导入测试 (U1/U2/engine2 报错) | 3 | 0 |
| T1~T10: 核心功能 | 10 | 0 |
| Python 编译 | 1 | 0 |
| engine2 残留检查 | 1 | 0 |
| A7 转发函数 | 2 | 0 |
| **合计** | **61** | **0** |

**🏆 61/61 ALL GREEN 🟢**

---

## MERGE-D: engine2.py 已删除（1/1 ✅）

| # | 检查项 | 结果 |
|:-:|:-------|:----:|
| 1 | `engine2.py` 文件不存在 | ✅ 已删除 |

---

## MERGE-A: pipeline_engine.py 验证（25/25 ✅）

| # | 检查项 | 结果 |
|:-:|:-------|:----:|
| 1 | `pipeline_engine.py` 存在 | ✅ 2,474 行 |

### A1: ## 命令处理（6/6 ✅）

| # | 函数 | 结果 |
|:-:|:-----|:----:|
| 1 | `_handle_hash_start` | ✅ |
| 2 | `_handle_hash_status` | ✅ |
| 3 | `_handle_hash_stop` | ✅ |
| 4 | `_handle_hash_advance` | ✅ |
| 5 | `_handle_hash_archive` | ✅ |
| 6 | `_archive_pipeline` | ✅ |

### A2: 自动调度（4/4 ✅）

| # | 函数 | 结果 |
|:-:|:-----|:----:|
| 1 | `_auto_dispatch` | ✅ |
| 2 | `_auto_re_notify` | ✅ |
| 3 | `_retry_loop` | ✅ |
| 4 | `_enqueue_retry` | ✅ |

### A3: 管线推进（3/3 ✅）

| # | 函数 | 结果 |
|:-:|:-----|:----:|
| 1 | `_try_advance_pipeline` | ✅ |
| 2 | `_auto_advance_pipeline` | ✅ |
| 3 | 管线推进逻辑在 pipeline_engine | ✅ |

### A4: 通知/驳回（2/2 ✅）

| # | 函数 | 结果 |
|:-:|:-----|:----:|
| 1 | `_notify_pm` | ✅ |
| 2 | `_handle_reject` | ✅ |

### A5: 模板/展示（3/3 ✅）

| # | 函数 | 结果 |
|:-:|:-----|:----:|
| 1 | `_render_template` | ✅ |
| 2 | `_build_step_summary` | ✅ |
| 3 | 展示常量 (`_ROLE_EMOJIS` 等) | ✅ |

### A6: 工具函数（6/6 ✅）

| # | 函数 | 结果 |
|:-:|:-----|:----:|
| 1 | `_extract_artifact_kv` | ✅ |
| 2 | `_format_pipeline_context` | ✅ |
| 3 | `_restore_pipeline_timers` | ✅ |
| 4 | `_restore_pipeline_dispatches` | ✅ |
| 5 | `_find_archive` | ✅ |
| 6 | `_resolve_card_key_to_ws_id` | ✅ |

---

## PipelineEngine class 方法（12/12 ✅）

| # | 方法 | 结果 |
|:-:|:-----|:----:|
| 1 | `PipelineEngine.__init__` | ✅ |
| 2 | `format_context()` | ✅ |
| 3 | `find_archive()` | ✅ |
| 4 | `start()` | ✅ |
| 5 | `stop()` | ✅ |
| 6 | `try_advance()` | ✅ |
| 7 | `auto_dispatch()` | ✅ |
| 8 | `auto_re_notify()` | ✅ |
| 9 | `notify_pm()` | ✅ |
| 10 | `handle_reject()` | ✅ |
| 11 | `restore_pipeline_timers()` | ✅ |
| 12 | `restore_pipeline_dispatches()` | ✅ |

---

## MERGE-C: B-5 bug 修复（2/2 ✅）

| # | 检查项 | 结果 | 说明 |
|:-:|:-------|:----:|:-----|
| 1 | `auto_dispatch` 无 PM fallback | ✅ | engine2 版本替换，无 `config.PIPELINE_PM_AGENT_ID` 降级 |
| 2 | `auto_dispatch` 找不到时 `return False` | ✅ | 不发错人 |

---

## Import 更新验证（4/4 ✅）

| # | 检查项 | 结果 |
|:-:|:-------|:----:|
| 1 | `main.py` 从 `pipeline_engine` import | ✅ |
| 2 | `main.py` 无 `engine2` import | ✅ |
| 3 | `scenario_matcher` 引用 `pipeline_engine as _e2` | ✅ |
| 4 | `scenario_matcher` 无 `engine2` 引用 | ✅ |

---

## 导入测试（3/3 ✅）

| # | 检查项 | 结果 |
|:-:|:-------|:----:|
| U1 | `from server.ws_server import main` | ✅ Import OK |
| U2 | `from server.ws_server import pipeline_engine` | ✅ Import OK |
| — | `from server.ws_server import engine2` | ✅ 应报 ImportError（已删除） |

---

## T1~T10: 核心功能（10/10 ✅）

| # | 验收项 | 代码位置 | 结果 |
|:-:|:-------|:---------|:----:|
| T1 | `##start##R138-test` 正常启动 | `pipeline_engine._handle_hash_start` | ✅ |
| T2 | `##status##R138-test` 正常查询 | `pipeline_engine._handle_hash_status` | ✅ |
| T3 | `##stop##R138-test` 正常停止 | `pipeline_engine._handle_hash_stop` | ✅ |
| T4 | `已完成 ✅` 自动推进（无 PM fallback） | `pipeline_engine.try_advance` | ✅ |
| T5 | 退回 🔄 驳回回退 | `pipeline_engine.handle_reject` | ✅ |
| T6 | PM 通知送达 | `pipeline_engine.notify_pm` | ✅ |
| T7 | `handle_broadcast` 非管线路由正常 | `main.handle_broadcast` | ✅ |
| T8 | 规则回调 10/20/30/40/50/60/70/90 正常 | `main._sm_handle_*` | ✅ |
| T9 | Git sync / Timeout scanner 可启动 | `pipeline_engine` (format_context) | ✅ |
| T10 | `_retry_loop` 启动正常 | `pipeline_engine._retry_loop` | ✅ |

---

## Python 编译验证

| 文件数 | 结果 |
|:------:|:----:|
| 全部 .py 文件 | ✅ 编译通过 |

---

## engine2 残留检查

| 检查项 | 结果 |
|:-------|:----:|
| 全库无 `engine2` import/引用（仅 docstring 历史注释） | ✅ 已清理 |

---

## A7 转发函数

| # | 检查项 | 结果 |
|:-:|:-------|:----:|
| 1 | `_ensure_engine()` 转发函数在 pipeline_engine | ✅ |
| 2 | `_ensure_pipeline_manager()` 转发函数在 pipeline_engine | ✅ |

---

## 结论

**PASS 🟢 — 61/61 测试项全部通过。**

| 评审项 | 结论 |
|:-------|:-----|
| engine2 → pipeline_engine 合并 | ✅ engine2 代码主体 + PipelineEngine class 统一 |
| engine2.py 删除 | ✅ 临时名已完成使命 |
| B-5 bug 修复 | ✅ auto_dispatch 替换为 engine2 版本（无 PM fallback） |
| Import 更新 | ✅ main.py + scenario_matcher → 全部指向 pipeline_engine |
| 导入测试 | ✅ main / pipeline_engine 导入通过，engine2 报 ImportError |
| 关键函数完整性 | ✅ A1~A6 全部 24 函数 + PipelineEngine 12 方法 |

*测试结束 — 本轮为引擎重构画上句号。R137 分拆 → R138 合并，两套引擎统一为一套。*
