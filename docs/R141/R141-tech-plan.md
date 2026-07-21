# R141 技术方案 — 代码清理轮

> **起草人：** 小开 (Arch)
> **版本：** v1.0
> **日期：** 2026-07-21
> **依据：** [R141 产品需求](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R141/R141-product-requirements.md) | [WORK_PLAN](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R141/WORK_PLAN.md)

---

## 1. 可行性结论

**✅ 全部可行。** A 类（安全清理）+ B 类（确认清理）共计 13 处清理点，零行为变化。

| 类别 | 清理点数 | 风险 | 涉及文件 |
|:----:|:--------:|:----:|:---------|
| 🟢 A | 8 | 无 | `main.py` ×4, `__main__.py` ×2, `scenario_matcher.py` ×1, `message_store.py` ×1 |
| 🟡 B | 2 | 低 | `main.py` ~77 行死代码, `state.py` 1 行重复 |
| 🔴 C | 2 | 高 | 本轮不做（需独立轮） |

---

## 2. 各清理点详细分析

### 2.1 A-1: main.py 未使用导入（4处）

| 当前行 | 代码 | 验证结果 |
|:------:|:-----|:---------|
| L11 | `import os` | `os.` 在 main.py 中出现 **0 次** |
| L14 | `import re` | `re.` 在 main.py 中出现 **0 次** |
| L25 | `from . import task_store as ts` | `ts.` 在 main.py 中出现 **0 次**（`ts=` 是参数名） |
| L27 | `from . import timeout_tracker` | `timeout_tracker.` 在 main.py 中出现 **0 次** |

**操作：** 直接删除这 4 行。

### 2.2 A-2: `__main__.py` 未使用导入（2处）

| 当前行 | 代码 | 验证结果 |
|:------:|:-----|:---------|
| L24 | `save_approved_users` | `save_approved_users(` 在 `__main__.py` 中出现 **0 次** |
| L25 | `save_web_sessions` | `save_web_sessions(` 在 `__main__.py` 中出现 **0 次** |

**操作：** 从 L20-L27 的 `from server.common.persistence import (...)` 中移除这两行。

### 2.3 A-3: scenario_matcher.py 未使用导入（1处）

| 当前行 | 代码 | 验证结果 |
|:------:|:-----|:---------|
| L15 | `import uuid` | `uuid.` 在文件中出现 **0 次** |

**操作：** 删除 L15 `import uuid`。

### 2.4 A-4: message_store.py 死函数（1处）

| 当前行 | 函数 | 仓库引用数 |
|:------:|:-----|:----------:|
| L127 | `clear_messages_by_channel()` | 定义处 1 次，调用方 **0 次** |

**操作：** 删除 L127-L134 的整个函数体。

### 2.5 A-5: main.py nits（2处）

**① L157 `__import__("time").time()` → `time.time()`**

```python
# 当前（L157）：
content=content_text, ts=__import__("time").time(),
# 改为：
content=content_text, ts=time.time(),
```
`time` 已在 L15 `import time` 全局导入，无需 `__import__`。

**② L557 底部 `from .scenario_rules import register_all_rules`**

```python
# 当前（L557-L558，位于模块底部）：
from .scenario_rules import register_all_rules
register_all_rules()
```

当前 L557 的 `from .scenario_rules` import 在 main.py 底部执行，是在 `scenario_rules.py` 模块完全加载后才导入的（R139 防止循环依赖的设计）。但当前 main.py 对 `scenario_rules` 只有这一个入口，不存在循环依赖（scenario_rules 对 main 的依赖是函数体内 lazy import）。因此可以将 import 移到顶部。

**操作：** 在顶部 L22 附近追加 `from . import scenario_rules as _sr`，底部改为 `_sr.register_all_rules()`。

⚠️ **注意：** 需要确认 `scenario_rules` 没有在较晚的模块级代码中依赖 main.py 的模块级状态（如 `_connections`、`engine`）。检查证明：scenario_rules 仅通过函数体内 `from .main import _ensure_engine` 访问 main，此 import 是惰性的，不依赖 main 顶部加载完成。**移动安全。**

### 2.6 B-1: workspace 死代码块（~77行）

| 函数 | 行号 | 行数 | 外部引用 |
|:-----|:----:|:----:|:--------:|
| `_broadcast_workspace_closing()` | L474-L517 | ~44 | **0** — 仅内部自引用 |
| `_broadcast_workspace_archived()` | L523-L548 | ~26 | **0** — 仅被前者调用 |

**侧效应分析：**

| 清理项 | 影响 | 说明 |
|:-------|:----:|:------|
| 删除 `_broadcast_workspace_closing()` | 🟢 无 | 无外部调用方 |
| 删除 `_broadcast_workspace_archived()` | 🟢 无 | 无外部调用方 |
| 删除 `from . import workspace as ws_mod` (L26) | 🟢 安全 | workspace 模块本身仍被其他 5 个文件引用 |
| 删除 `p.WORKSPACE_CLOSING_TIMEOUT` 等协议常量引用 | 🟢 无 | `p` (shared.protocol) 仍被 main.py 其他 8 处引用 |

**需保留的 `p.` 引用（不在死代码块中）：** L282 `p.FIELD_CHANNEL`、L285 `p.INBOX_CHANNEL_PREFIX`、L287 `p.INBOX_CHANNEL_PREFIX`、L298 `p.INBOX_CHANNEL_PREFIX`、L412 `p.MSG_REGISTER`、L434 `p.INBOX_CHANNEL_PREFIX`、L450 `p.MSG_AGENT_CARD_REGISTER`。

### 2.7 B-2: state.py 重复变量定义

| 行号 | 代码 | 说明 |
|:----:|:-----|:------|
| L13 | `_PIPELINE_CONFIG: dict[str, dict] = {}` | 首次定义 |
| L30 | `_PIPELINE_CONFIG: dict[str, dict] = {}` | 重复定义（覆盖 L13） |

L30 的值覆盖 L13，行为等价。删除 L13 的首次定义。

### 2.8 C 类：DEPRECATED 变量迁移（本轮不做）

| 变量 | 行号 | 读取文件数 | 写入文件数 |
|:-----|:----:|:----------:|:----------:|
| `_ROLE_AGENT_MAP` | L36 | 4（agent_card, main, pipeline_engine, commands） | 2（agent_card, main） |
| `_step_ack_states` | L39 | 3（ack_machine, pipeline_engine, commands） | 2（ack_machine, commands） |

需独立轮完成迁移，本轮仅记录。

---

## 3. 改动范围

| 文件 | 操作 | 行数变化 | 说明 |
|:-----|:-----|:--------:|:------|
| `main.py` | 删除 L11, L14, L25, L27 | -4 | A-1 未使用导入 |
| `main.py` | L26 删除 `ws_mod` 导入 | -1 | B-1 依赖 |
| `main.py` | 删除 L472-L548（77 行死代码） | -77 | B-1 workspace 死代码 |
| `main.py` | L157 `__import__("time").time()` → `time.time()` | 0 | A-5 精简 |
| `main.py` | 顶部 L22 附近追加 `from . import scenario_rules as _sr` | +1 | A-5 import 上移 |
| `main.py` | 底部 L557 改为 `_sr.register_all_rules()` | 0 | A-5 调用 |
| `__main__.py` | L24-L25 移除 2 个导入 | -2 | A-2 |
| `scenario_matcher.py` | 删除 L15 `import uuid` | -1 | A-3 |
| `message_store.py` | 删除 L127-L134 死函数 | -8 | A-4 |
| `state.py` | 删除 L13 重复定义 | -1 | B-2 |

**净行数：** -4 - 1 - 77 + 0 + 1 + 0 - 2 - 1 - 8 - 1 = **-93 行**

---

## 4. 执行顺序（Step 3 编码）

```
commit 1 — A类安全清理：main.py (-4) + __main__.py (-2) + scenario_matcher.py (-1) + message_store.py (-8)
  → 验证：python3 -c "from server.ws_server import main, __main__, scenario_matcher, message_store"

commit 2 — B类确认清理：main.py L472-L548(-77) + ws_mod import(-1) + state.py L13(-1)
  → 重点确认：ws_mod 删除后，main.py 再无 workspace 调用
  → 重点确认：_broadcast_workspace_archived 无外部引用

commit 3 — A-5 nits：__import__("time") + import上移
  → 验证：python3 -c "from server.ws_server import main"
```

---

## 5. 验收检查表

| # | 验收项 | 验证方法 | 类型 |
|:-:|:-------|:---------|:----:|
| C1 | `from server.ws_server import main` 无错 | commit 1-3 后 | P0 |
| C2 | `from server.ws_server import scenario_matcher` 无错 | commit 1 后 | P0 |
| C3 | `from server.ws_server import message_store` 无错 | commit 1 后 | P0 |
| C4 | 所有 16 模块正常 import | `python3 -c "from server.ws_server import main, scenario_matcher, scenario_rules, pipeline_engine, connection_manager, ack_machine, watchdog, pipeline_timeout, git_sync_scheduler, state, message_store, task_store, audit, agent_card, workspace, timeout_tracker, pipeline_context, pipeline_sync, __main__"` | P0 |
| C5 | workspace 模块仍可被其他模块正常 import | ack_machine/pipeline_engine/commands/watchdog 仍能正常工作 | P1 |
| R1 | `test ✅` 回路测试正常 | 发 test ✅ → 回路回复 | P0 |
| R2 | `##start##R{N}` 正常创建+派活 | 管线创建 | P0 |
| R3 | `已完成 ✅ R{N} Step N` 正常推进 | 管线推进 | P0 |
| R4 | 归档管线可查询 | `##status##R{N}` 正常 | P1 |
| R5 | 编译无错误：`python3 -c "from server.ws_server import *"` | 全部模块 | P0 |

---

## 6. 不做事项

| ❌ 不做 | 原因 |
|:--------|:-----|
| C 类 DEPRECATED 变量迁移 | 需独立轮，涉及 4-6 个文件的多读写路径 |
| docs/R*/ 目录清理 | 已被 .gitignore 忽略，不影响仓库 |
| workspace.py 模块本身清理 | 其他 5 个文件仍在引用 |
| `p` (shared.protocol) 清理 | 在 main.py 有 8 处合法引用 |
| import 排序/分组整理 | 非本轮范畴 |

---

## 7. 侧效应矩阵

| 操作 | 侧效应 | 缓解措施 |
|:-----|:-------|:---------|
| 删除 `ws_mod` import | 若未来需要从 main.py 调用 workspace 需重新 import | 当前无调用路径，安全 |
| `scenario_rules` import 上移到顶部 | 若 scenario_rules 模块级代码依赖 main 未加载完毕的状态 | 已验证：scenario_rules 仅在 `register_all_rules()` 内通过函数体 lazy import 引用 main |
| 删除 `timeout_tracker` import | 已在 pipeline_engine.py 顶层 import 并使用 | 其他模块不受影响 |

---

> **审核记录：**
> - v1.0 提交审核
> - 关键决策：C 类 DEPRECATED 变量迁移独立轮；A-5 import 上移需验证无循环依赖
> - 结论：⬜ 待审核
