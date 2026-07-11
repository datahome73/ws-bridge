# R100 代码审计报告 — handler.py→main.py 分层重构

> **审计者：** 小谷（PM）
> **基线：** 本地 dev 未提交改动
> **审计日期：** 2026-07-11
> **范围：** 22 文件变更（+9,625 / -7,040），含 server/ 全部新文件 + 外部 import 更新

---

## TL;DR — 风险概览

| 等级 | 数量 | 描述 |
|:----:|:----:|:------|
| 🔴 | 7 | **运行时崩溃级** — import 缺失导致 NameError/ModuleNotFoundError |
| 🟡 | 3 | **缺失函数** — 旧 handler.py 即存在，refactoring 未新增（预存在 bug） |
| 🟢 | 5 | **结构良好** — state/command_utils/commands 包结构、main.py 分发逻辑 |

**结论：R100 结构拆分方向正确，但 commands/ 子包的 import 完整性存在系统性遗漏，必须修复后才能提交。**

---

## 🟢 结构良好项

### 1. state.py (126 行) ✅
- 纯数据容器，零业务逻辑，零函数定义
- 正确依赖：仅 `asyncio` + `PipelineContextManager`（类型标注用）
- 所有全局变量完整迁移（_PIPELINE_STATE, _r72_users, _connections* 保留在 main.py 等）

### 2. command_utils.py (207 行) ✅
- 工具函数干净提取，无循环依赖（延迟 import main._connections）
- 6 个函数覆盖：parse/permission/audit/broadcast/workspace/role-map-refresh

### 3. commands/__init__.py (202 行) ✅
- `_ADMIN_COMMANDS` 注册表正确，从 5 个子模块导入所有 handler
- 元数据完整（min_role/workspace_scope/usage）

### 4. main.py handle_broadcast 命令分发 (L1394-1415) ✅
- 延迟导入 `from .commands import _ADMIN_COMMANDS` 避免循环依赖
- parse→permission→dispatch→audit 链完整

### 5. __main__.py import 更新 ✅
- `from .main import handle_auth, handle_broadcast, ...` 正确
- 额外延迟导入 `from .main import handle_agent_card_register` (L103)，`from .main import handler as _handler_fn` (L119) 正确
- `from .state import _offline_push_queue` (L471) 正确

### 6. auth.py — 无旧 handler 引用 ✅

### 7. agent_card.py — 无旧 handler 引用 ✅

---

## 🔴 关键问题

### 问题 1: web_viewer.py L545 — 指向已删除文件 🔴

```python
# ❌ 当前代码（L545）
from . import handler as _handler
connections = _handler.get_connections()

# ✅ 应改为
from .main import get_connections
connections = get_connections()
```

**影响：** 访问 `/api/agents` 端点时触发 `ModuleNotFoundError`，因为 `handler.py` 已不存在。

---

### 问题 2: commands/admin.py — 缺失 5 项 import 🔴

```python
# 当前 import（L3）：from .. import state, auth, command_utils, persistence
# 实际使用：
#   _connections        — L8, L38  ⚠️  定义于 main.py L36
#   ws_mod (workspace)  — L39, L55...  ⚠️  未导入
#   _audit_logger       — L101, L103  ⚠️  定义于 main.py L39
#   time                — L110        ⚠️  标准库
#   _force_disconnect_revoked_agent  — L164  ⚠️  定义于 main.py L50
```

**修复：** 增加 `from .. import workspace as ws_mod` + `from ..main import _connections, _audit_logger, _force_disconnect_revoked_agent` + `import time`

> ⚠️ **注意：** `from ..main import ...` 可能导致循环依赖（command_utils.py 已使用延迟导入规避）。建议 commands/ 子包也使用延迟导入或在 main.py 中暴露公共接口。

---

### 问题 3: commands/task.py — 缺失 6 项 import/函数 🔴

```python
# 当前 import（L3-5）：from .. import state, auth, command_utils
#                       from .. import task_store as ts
#                       from .. import workspace as ws_mod
# 实际使用：
#   config.DATA_DIR     — L19, L38...  ⚠️  未导入
#   asyncio             — L22, L72     ⚠️  标准库
#   _broadcast_task_notify — L22, L72  ⚠️  定义于 main.py L1231
#   p (shared.protocol) — L49, L50...  ⚠️  未导入
#   _persist_broadcast  — L153, L188   ⚠️  定义于 main.py L369
```

---

### 问题 4: commands/workspace.py — 缺失 5 项 import 🔴

```python
# 当前 import（L3-5）：from .. import state, auth, command_utils
#                       from .. import workspace as ws_mod
#                       from .. import config
# 实际使用：
#   p.WORKSPACE_ID_PREFIX — L19       ⚠️  未导入
#   _ensure_pipeline_manager — L158   ⚠️  定义于 main.py L40
#   _connections         — L180, L418 ⚠️  定义于 main.py L36
#   time, uuid           — 多处使用   ⚠️  标准库
#   ms.save_message      — L169 等    ⚠️  未导入
```

---

### 问题 5: commands/agent_card.py — 缺失 _connections import 🔴

```python
# 当前 import（L3-5）：from .. import state, auth, command_utils
#                       from .. import agent_card as ac_mod
#                       from .. import config
# 实际使用：
#   _connections         — L188, L238  ⚠️  定义于 main.py L36
```

---

### 问题 6: commands/pipeline.py — 缺失 6 项 import + 3 个缺失函数 🔴🟡

```python
# 当前 import（L8-17）：系统文件级 import 较完整但仍有遗漏
# 实际使用：
#   _connections         — L431, 456, 813, 945, 1237, 1479  ⚠️
#   _audit_logger        — L1013  ⚠️
#   _ensure_pipeline_manager — L30, 175, 302, 660...  ⚠️
#   _persist_broadcast   — L449, L1230  ⚠️
#   _send_clear_alert    — L959, L1276  ⚠️
```

#### 🟡 缺失函数（预存在 bug，R100 前已存在）

| 函数 | 调用位置 | 定义状态 |
|:-----|:---------|:---------|
| `_send_to_agent(agent_id, text, ws_id=)` | pipeline.py:807, 855, 1405 | ❌ 不存在 |
| `_r57_wait_for_ack(agent_id, timeout=30)` | pipeline.py:843 | ❌ 不存在 |
| `_r57_switch_to_backup(...)` | pipeline.py:817, 859 | ❌ 不存在 |

> **注意：** 以上 3 个函数在原始 handler.py 中也未定义（git show HEAD:server/handler.py 确认）。它们是 long-standing dead code——这些代码路径从未被执行过，或者是在某次删除中意外丢失了定义。

---

## 🟡 次要问题

### 问题 A: server/__main__.py L119 的延迟导入名

```python
from .main import handler as _handler_fn
```
`handler` 函数存在于 `main.py` 中。这是正确的——只是别名 `_handler_fn` 容易引起困惑（读代码时以为引自旧 handler.py）。

### 问题 B: commands/pipeline.py L187 的 import

```python
from .pipeline_context import StepInfo, DEFAULT_STEP_ORDER, DEFAULT_STEPS
```
这是**函数内延迟导入**，格式为 `from .pipeline_context`（相对于 commands/ 包），而非预期的 `from ..pipeline_context`。如果 `pipeline_context.py` 不在 `commands/` 子目录中，此导入会在运行时抛出 `ImportError`。

---

## 修复优先级

| 优先级 | 问题 | 修复难度 | 运行时影响 |
|:------:|:-----|:---------|:----------|
| P0 | web_viewer.py L545 handler 引用 | 1 行 | 🔴 /api/agents 崩溃 |
| P0 | commands/* 全部缺失 import | 每个文件 2-5 行 | 🔴 任何 !命令触发 NameError |
| P0 | pipeline.py L187 相对路径 | 1 行 | 🔴 _handle_pipeline_command 崩溃 |
| P1 | _send_to_agent 等 3 个缺失函数 | 需确认是否 dead code | 🟡 仅特定管线路径触发 |

---

## 建议

1. **使用延迟导入模式**：所有 commands/ 子包的 main.py 依赖（`_connections`, `_audit_logger`, `_ensure_pipeline_manager` 等）使用函数内 `from ..main import ...`，避免模块级循环依赖
2. **为缺失函数** `_send_to_agent` 补一个简单实现（WS 直发 + persistence），或标注 `@deprecated` 并删除调用
3. **提交策略**：建议分两步 commit——① 修复所有 import 缺失 ② 处理缺失函数，方便回退
