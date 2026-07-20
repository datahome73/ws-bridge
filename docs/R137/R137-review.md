# R137 Step 4 — 代码审查报告 🔍

> **轮次：** R137（引擎分拆轮 — engine2.py 创建）
> **审查人：** 🔍 小周
> **审查对象：** commit `ca758c9064ec`
> **依据：** `docs/R137/R137-product-requirements.md`, `docs/R137/R137-tech-plan.md`
> **审查基准：** dev HEAD `ca758c9064ec`

---

## ✅ 审查结论：通过

---

## 一、文件改动总览

| # | 文件 | 动作 | 行数变化 | 内容 |
|:-:|:-----|:----:|:--------:|:-----|
| 1 | `server/ws_server/engine2.py` | ✅ 新增 | **+1544** | A1~A7 全部管线逻辑 |
| 2 | `server/ws_server/main.py` | 🔧 精简 | **+1 -1445** | 2180→736 行（-66%），仅剩 handler 路由 |
| 3 | `server/ws_server/scenario_matcher.py` | 🔧 路由切换 | **+13 -13** | 4 处 `from .main` → `from . import engine2 as _e2` |
| **合计** | | | **+1558 -1458** | |

---

## 二、engine2.py 函数清单（A1~A7）

| 组 | 函数 | 行号 | 说明 |
|:--:|:-----|:----:|:-----|
| A1 | `_handle_hash_start` / `_handle_hash_status` / `_handle_hash_stop` / `_handle_hash_advance` / `_handle_hash_archive` / `_archive_pipeline` | L1149-L1534 | 6 个 `##` 命令 handler |
| A2 | `_retry_loop` / `_enqueue_retry` / `_auto_dispatch` / `_auto_re_notify` | L560-L971 | 自动调度 + 重试 |
| A3 | `_try_advance_pipeline` / `_auto_advance_pipeline` / `_verify_sha_remote` | L37-L159, L363-L478, L768-L812 | 管线推进 |
| A4 | `_notify_pm` / `_handle_reject` | L480-L559, L973-L1050 | 通知 + 驳回 |
| A5 | `_render_template` / `_build_step_summary` / `_build_rich_templates` / `_get_step_agent_name` | L612-L739, L1103-L1148 | 模板/展示 |
| A6 | `_extract_artifact_kv` / `_format_pipeline_context` / `_restore_pipeline_timers` / `_restore_pipeline_dispatches` / `_find_archive` / `_fmt_ts` / `_build_name_to_ws_map` / `_resolve_card_key_to_ws_id` / `_verify_git_commit` | L200-L335, L336-L362, L740-L1112 | 工具函数 |
| A7 | `_ensure_engine` / `_ensure_pipeline_manager` | L1536-L1545 | 转发到 `main._ensure_engine()` / `main._ensure_pipeline_manager()` |

---

## 三、Import 链验证

### 3.1 engine2.py → main.py（无循环依赖）

| engine2 导入 | 类型 | 说明 | 结果 |
|:-------------|:----:|:-----|:----:|
| `from .connection_manager import _connections, _send, _send_to_agent` | 模块级 | 纯数据/函数，无依赖 | ✅ |
| `from .pipeline_engine import PipelineEngine` | 模块级 | pipeline_engine 不依赖 main | ✅ |
| `from .pipeline_context import ...` | 模块级 | 纯数据类 | ✅ |
| `from .main import _send_to_agent`（_retry_loop 内部） | 惰性 | 运行时才导入 | ✅ |
| `from .main import _ensure_engine`（_ensure_engine 内部） | 惰性 | 运行时才导入 | ✅ |

⚠️ 等一等——engine2.py 模块级已经 `from .connection_manager import _connections, _send, _send_to_agent`，而 `_retry_loop` 内部又 `from .main import _send_to_agent`。但两者是同一个符号（main.py re-exports from connection_manager），所以无问题。

**关键：engine2.py 对 main.py 的所有依赖都是函数级（惰性）import，不会在模块加载时触发循环。**

### 3.2 scenario_matcher.py 路由切换

| 旧路由（main.py） | 新路由（engine2.py） | 位置 | 结果 |
|:------------------|:---------------------|:----:|:----:|
| `from .main import _handle_hash_start/...` | `from . import engine2 as _e2` + `_e2._handle_hash_*` | L407-418 | ✅ |
| `from .main import _ensure_pipeline_manager` | `_e2._ensure_pipeline_manager()` | L269, L284 | ✅ |
| `from .main import _ensure_engine` | `_e2._ensure_engine()` | L272, L274 | ✅ |
| `from .main import _connections` | 不变（`_connections` 仍由 main.py re-export） | L297, L327 | ✅ |
| `from .main import _audit_logger` | 不变 | L360 | ✅ |
| `from .main import _send` | 不变（`_send_reply` 内部） | L729 | ✅ |

### 3.3 main.py 精简后保留的函数

| 函数组 | 说明 | 结果 |
|:-------|:-----|:----:|
| `_ensure_engine` / `_ensure_pipeline_manager` | 引擎单例工厂 | ✅ |
| `_refresh_role_agent_map` / `_broadcast_to_channel` / `_persist_broadcast` | 广播 + 角色映射 | ✅ |
| `_ensure_agent_cards_loaded` / `_ensure_card_watcher` / `_get_agent_display` | Agent Card 子系统 | ✅ |
| `handle_broadcast` / `handler` | WebSocket 入口 | ✅ |
| `_sm_handle_*` (9 个 handler 包装) | 规则引擎回调 | ✅ |
| 全部 `register_rule` 调用（规则注册） | 规则表 | ✅ |

### 3.4 Import 验证结果

| 验证项 | 结果 |
|:-------|:----:|
| `from server.ws_server import main` | ✅ Import OK |
| `import server.ws_server.engine2 as e2` | ✅ Import OK |
| `e2._ensure_engine.__doc__[:40]` = `"Forward to main._ensure_engine()...."` | ✅ （A7 转发正确） |

---

## 四、A7 回调转发验证

```python
# engine2.py L1536-1541
def _ensure_engine():
    \"\"\"Forward to main._ensure_engine().\"\"\"
    from .main import _ensure_engine
    return _ensure_engine()

def _ensure_pipeline_manager():
    \"\"\"Forward to main._ensure_pipeline_manager().\"\"\"
    from .main import _ensure_pipeline_manager
    return _ensure_pipeline_manager()
```

✅ 使用函数级惰性 import，避免循环。转发到 main 的单例工厂，确保引擎实例统一。

---

## 五、main.py 管线代码已无残留

全库 grep 确认已提取函数无残留定义：

| 函数 | 应移入 engine2 | main.py 残留 | 结果 |
|:-----|:--------------:|:-----------:|:----:|
| `_handle_hash_start/status/stop/advance/archive` | ✅ | 0 | ✅ |
| `_try_advance_pipeline` / `_auto_advance_pipeline` | ✅ | 0 | ✅ |
| `_auto_dispatch` / `_auto_re_notify` | ✅ | 0 | ✅ |
| `_handle_reject` / `_notify_pm` | ✅ | 0 | ✅ |
| `_retry_loop` / `_enqueue_retry` | ✅ | 0 | ✅ |
| `_render_template` / `_build_step_summary` | ✅ | 0 | ✅ |
| `_find_archive` / `_verify_sha_remote` | ✅ | 0 | ✅ |
| `_format_pipeline_context` / `_extract_artifact_kv` | ✅ | 0 | ✅ |

---

## 六、代码质量发现项

### 🟡 1: scenario_matcher.py 仍有 `match_query` / `handle_query` 重复定义

**位置：** L168 + L467（`match_query`），L186 + L467（`handle_query`）
**说明：** R132 审查已指出过此问题。第一个副本（L168-L259）是死代码——包含 `_format_query_status` 的旧版（调 `_e2`）和 `_QUERY_LEVEL_MAP` 权限检查。第二个副本（L467-L638+）是活跃版（调 `main_mod`）。提取未涉及此区域，问题延续。
**影响：** 功能正确，但冗余代码约 90 行。
**建议：** 建议后续轮次统一清理死代码副本。

---

## 七、汇总 & 结论

### 亮点
- engine2.py 创建干净（1544 行），A1~A7 所有管线函数签名与原 main.py 一致
- main.py 从 2180 行降至 **736 行**（-66%）
- scenario_matcher 路由切换完整——4 处 `from .main` → `from . import engine2 as _e2`
- A7 转发函数正确指向 main 单例工厂，无实例分裂
- Import 验证通过——无循环依赖
- 全库 0 残留已提取函数定义

### 建议
- 🟡 scenario_matcher.py 死代码 `match_query`/`handle_query` 副本建议后续清理

### 结论
> **✅ 通过** — engine2.py 提取完整，import 链无断裂，scenario_matcher 路由正确切换，main.py 精简至 736 行。

---

*审查结束*
