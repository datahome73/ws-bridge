# R136 Step 4 — 代码审查报告 🔍

> **轮次：** R136（纯提取轮 — 5 个新模块）
> **审查人：** 🔍 小周
> **审查对象：** commit `a68a94dfa3c4`（提取）+ `a82a4066dfc2`（bugfix）
> **依据：** `docs/R136/R136-product-requirements.md`, `docs/R136/R136-tech-plan.md`
> **审查基准：** dev HEAD `a82a4066dfc2`

---

## ✅ 审查结论：通过

---

## 一、文件改动总览

| # | 文件 | 动作 | 行数 | 内容 |
|:-:|:-----|:----:|:----:|:-----|
| 1 | `server/ws_server/main.py` | 🔧 精简 | **+59 -954** | 3092→2197行（-895行），提取 5 个模块 |
| 2 | `server/ws_server/connection_manager.py` | ✅ 新增 | **+302** | EXT-1: 连接管理 + auth/register/send 函数 |
| 3 | `server/ws_server/watchdog.py` | ✅ 新增 | **+308** | EXT-2: 看门狗循环/扫描/告警 |
| 4 | `server/ws_server/ack_machine.py` | ✅ 新增 | **+241** | EXT-3: ACK 状态机/超时检测 |
| 5 | `server/ws_server/pipeline_timeout.py` | ✅ 新增 | **+65** | EXT-4: 管线超时扫描 |
| 6 | `server/ws_server/git_sync_scheduler.py` | ✅ 新增 | **+65** | EXT-5: Git 同步调度 |
| 7 | `server/ws_server/__main__.py` | 🔧 微调 | **+2 -1** | 改从 `connection_manager` 导入 `_connections` |
| 8 | `server/ws_server/pipeline_engine.py` | 🔧 bugfix | **+22 -6** | auto_dispatch PM fallback 修复 |
| **合计** | | | **+1125 -961（净 +164）** | |

---

## 二、模块提取完整性验证

### 2.1 模块文件清单

| 模块 | 导出函数 | 行数 | 状态 |
|:-----|:---------|:----:|:----:|
| `connection_manager` | `_connections`, `get_connections`, `_send`, `handle_auth`, `handle_register`, `_send_to_agent`, `handle_agent_card_register`, `_build_registration_welcome`, `_build_admin_notification`, `_is_valid_agent_id`, `_force_disconnect_revoked_agent`, `_update_agent_online_status`, `_find_agent_by_name`, `_should_notify_admins` | 302 | ✅ |
| `watchdog` | `_ensure_watchdog`, `_watchdog_loop`, `_watchdog_scan`, `_get_step_timeout`, `_trigger_timeout_escalation`, `_check_watchdog_alert`, `_clear_watchdog_alert`, `_elapsed_hours_display`, `_send_watchdog_alert`, `_watchdog_rerollcall`, `_send_clear_alert` | 308 | ✅ |
| `ack_machine` | `ACK_TIMEOUT_SEC`, `_ack_timeout_task`, `_send_ack_timeout_info`, `_trigger_ack_escalation`, `_format_ack_status`, `_task_ack_timeout`, `_channel_ack_timeout`, `_resolve_ws_by_ack_task_id` | 241 | ✅ |
| `pipeline_timeout` | `_ensure_timeout_scanner`, `_start_timeout_scan_loop`, `_pipeline_timeout_scan` | 65 | ✅ |
| `git_sync_scheduler` | `_ensure_git_scan`, `_start_git_sync_loop`, `_pipeline_git_sync_scan` | 65 | ✅ |

### 2.2 main.py 保留函数清单（未提取的正确保留）

| 函数组 | 状态 | 说明 |
|:-------|:----:|:------|
| `_ensure_engine` / `_ensure_pipeline_manager` | ✅ 保留 | 管线上下文管理 |
| `_refresh_role_agent_map` / `_broadcast_to_channel` | ✅ 保留 | 角色映射 + 广播（R100） |
| `_persist_broadcast` / `_get_agent_display` | ✅ 保留 | 消息持久化 |
| `_ensure_agent_cards_loaded` / `_ensure_card_watcher` | ✅ 保留 | Agent Card 子系统 |
| `_auto_advance_pipeline` / `_verify_git_commit` | ✅ 保留 | 管线自动推进 + Git 验证 |
| `_format_pipeline_context` / `_restore_pipeline_timers` / `_restore_pipeline_dispatches` | ✅ 保留 | 管线状态 |
| `handle_broadcast` (L549) | ✅ 保留 | 消息路由中枢（～80行） |
| `_extract_artifact_kv` / `_try_advance_pipeline` | ✅ 保留 | 状态推进 |
| `_notify_pm` / `_retry_loop` / `_enqueue_retry` | ✅ 保留 | PM 通知 + 重试 |
| `_render_template` / `_get_step_agent_name` / `_build_step_summary` | ✅ 保留 | 邮件模板 |
| `_find_archive` / `_fmt_ts` / `_verify_sha_remote` | ✅ 保留 | 归档查询 |
| `_auto_re_notify` / `_auto_dispatch` / `_handle_reject` | ✅ 保留 | 自动派活 + 退回 |
| `_build_name_to_ws_map` / `_resolve_card_key_to_ws_id` | ✅ 保留 | 名称解析 |

---

## 三、Import 链验证

### 3.1 main.py 自身 import

| 源模块 | import 方式 | 行号 | 结果 |
|:-------|:------------|:----:|:----:|
| `connection_manager._connections` | `from .connection_manager import _connections` | L35 | ✅ |
| `connection_manager.get_connections` | `from .connection_manager import get_connections` | L68 | ✅ |
| `connection_manager._send` / handle_auth / handle_register 等 | 批量 re-export | L129-136 | ✅ |
| `git_sync_scheduler.*` | `from .git_sync_scheduler import (...)` | L208-210 | ✅ |
| `pipeline_timeout.*` | `from .pipeline_timeout import (...)` | L215-217 | ✅ |
| `watchdog.*` | `from .watchdog import (...)` | L346-350, L368-371 | ✅ |
| `ack_machine.*` | `from .ack_machine import (...)` | L357-361, L631-633 | ✅ |
| `connection_manager._send_to_agent` | `from .connection_manager import (...)` | L640-642 | ✅ |

### 3.2 __main__.py import

| 旧路径 | 新路径 | 结果 |
|:-------|:-------|:----:|
| `from .main import _connections` | `from .connection_manager import _connections` | ✅ |
| `from .main import handle_auth, handle_broadcast, handle_register` | 不变（main.py re-export） | ✅ |

### 3.3 scenario_matcher.py import（惰性 import）

| 引用 | 路径 | 解析方式 | 结果 |
|:-----|:-----|:---------|:----:|
| `from .main import _connections` | main.py L35: `from .connection_manager import _connections` | 链式解析 | ✅ |
| `from .main import _audit_logger` | main.py module-level 定义 | 直接解析 | ✅ |
| `from .main import _send` | main.py re-export (L131) | 链式解析 | ✅ |

### 3.4 Import 验证结果

| 验证项 | 结果 |
|:-------|:----:|
| `python3 -c "from server.ws_server import main"` | ✅ Import OK |
| 所有惰性 import 路径有链式解析保证 | ✅ |

---

## 四、Bugfix 验证（a82a4066）

| 修复 | 描述 | 验证 |
|:-----|:-----|:----:|
| Fix 1 | `handle_hash_start` 创建 PipelineContext 时同步生成 `ctx.steps`，从 `role_agent_map + 6步角色映射` 填充各 step 的 agent_id/agent_name | ✅ 新增 ~16 行 steps 生成逻辑（L573-588） |
| Fix 2 | `auto_dispatch` 去掉危险的 PM fallback 链，`ctx.steps` 找不到 agent_id 时直接 return False 并 log 警告 | ✅ 原 6 行 fallback 替换为 4 行 warning + return False |

两个修复合理，根因确定，保护措施充分。

---

## 五、代码质量发现项

### 🟡 1: main.py 孤立 `pass` 语句（L204）

**位置：** `main.py` L204
**内容：** `    pass  # _ensure_watchdog extracted to watchdog.py`
**问题：** 模块级别遗留了一个缩进的 `pass`。原 `_ensure_watchdog` 函数定义被删除后留下的占位符未清理干净。不影响运行（Python 接受此语法），但代码整洁度可改进。
**建议：** 将行改为纯注释 `# _ensure_watchdog extracted to watchdog.py`。

---

## 六、汇总 & 结论

### 亮点
- 5 个新模块提取干净，函数签名一致，无语义变更
- main.py 从 3092 行降至 2197 行（-29%）
- Import 链完整——main.py 正确 re-export，所有外部引用方继续工作
- `python3 -c "from server.ws_server import main"` 验证通过
- Bugfix PR 解决 `auto_dispatch` PM fallback 发错人问题，修复彻底

### 建议
- 🟡 `main.py` L204 孤立 `pass` 可清理为纯注释

### 结论
> **✅ 通过** — 5 个模块提取完整，import 链无断裂，bugfix 修复合理，import 验证通过。

---

*审查结束*
