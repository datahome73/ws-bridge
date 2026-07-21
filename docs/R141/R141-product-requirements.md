# R141 代码清理轮 — 产品需求文档

## 概述

在 R137~R140 多轮重构后，main 分支遗留了一些死代码、未使用导入和弃用变量。本轮聚焦清理这些已知的、无副作用的代码残骸。

---

## 排查方法

逐文件 grep 检查：
- 每条 import 是否有对应符号引用（`mod.fn`, `from . import X as Y` 的 `Y.`）
- 每个函数/变量是否有调用方（`search_files` 全局扫描）
- 每个标记为 DEPRECATED 的变量的实际引用位置

---

## A 类 — 安全清理（无行为变化）

### A-1. main.py 未使用的导入（4处）

| 行号 | 导入 | 原因 |
|------|------|------|
| L11 | `import os` | `os.` 在 main.py 中从未出现 |
| L14 | `import re` | `re.` 在 main.py 中从未出现 |
| L25 | `from . import task_store as ts` | `ts.` 从未被调用；所有 `ts` 匹配实为 `ts=` 参数名 |
| L27 | `from . import timeout_tracker` | `timeout_tracker.` 在 main.py 中从未出现 |

**影响**: 0。Python 导入开销可忽略，但清除后减少 lint 噪声。

### A-2. __main__.py 未使用的导入（2处）

| 行号 | 导入 | 原因 |
|------|------|------|
| L24 | `save_approved_users` | 仅在 viewer.py 中被调用，__main__ 中未使用 |
| L25 | `save_web_sessions` | 同上 |

**影响**: 0。

### A-3. scenario_matcher.py 未使用的导入（1处）

| 行号 | 导入 | 原因 |
|------|------|------|
| L15 | `import uuid` | `uuid.` 在文件中从未出现 |

**影响**: 0。

### A-4. message_store.py 死函数（1处）

| 行号 | 函数 | 调用方 |
|------|------|--------|
| L127 | `clear_messages_by_channel()` | **无** — 全仓库 0 引用 |

**影响**: 0。可安全删除该函数。

### A-5. main.py 中的精简 nits（2处）

| 位置 | 内容 | 建议 |
|------|------|------|
| L157 | `__import__("time").time()` | 改为 `time.time()` — `time` 已在 L15 全局导入 |
| L557 | `from .scenario_rules import register_all_rules` (late import) + `register_all_rules()` | 移到顶部导入，底部仅调用 `register_all_rules()` |

**影响**: 0。

---

## B 类 — 需确认的清理

### B-1. 废弃的 workspace 关闭/归档代码块（main.py L472~L548）

两函数：

| 函数 | 行号区间 | 行数 |
|------|----------|------|
| `_broadcast_workspace_closing()` | L474~L517 | ~44 |
| `_broadcast_workspace_archived()` | L523~L548 | ~26 |

**调用方**: **无** — 全仓库 0 引用。workspace 子系统已在 R134 退役为存根。
`workspace.py` 自身注释：`"In-memory workspace registry (no persistence — workspace subsystem is deprecated)"`

**建议**: 确认 `workspace` 子系统是否仍有其他路径调用这两个函数。已确认无调用后删除整个代码块（L472~L548）及 `ws_mod` 导入中仅被此代码块使用的引用。

### B-2. state.py 重复变量定义

| 行号 | 代码 | 说明 |
|------|------|------|
| L13 | `_PIPELINE_CONFIG: dict[str, dict] = {}` | 初始定义（无注释） |
| L30 | `_PIPELINE_CONFIG: dict[str, dict] = {}` | 第二次定义（R62 注释版）— 覆盖第一行 |

**影响**: 0。两行定义相同的空字典。但清理后提高可维护性。

**建议**: 删除 L13 的首次定义，保留 L30 的 R62 版本。

---

## C 类 — 需独立轮的弃用变量迁移

### C-1. `state._ROLE_AGENT_MAP`（L36，标记 DEPRECATED）

注释写道：`R78: DEPRECATED — 迁移到 PipelineContextManager._global_role_map`

但当前仍然：
- ✅ 在 `agent_card.py` L409~L414 中每次注册都双写（注释"双写旧变量（过渡期后删除）"）
- ✅ 在 `main.py` `_refresh_role_agent_map()` 中全量重建
- ✅ 在 `commands/pipeline.py` L914 中作为 `PipelineContextManager` 的 fallback 读取

**影响**: 需独立轮完成迁移，本轮不做。

### C-2. `state._step_ack_states`（L39，标记 DEPRECATED）

注释写道：`R78 B: DEPRECATED — 迁移到 PipelineContext.ack_states`

但当前仍然：
- ✅ 在 `ack_machine.py` L34、L155 中读写
- ✅ 在 `commands/pipeline.py` L456 中写入
- ✅ 在 `pipeline_engine.py` L87~L89 中读取

**影响**: 同上，需独立轮。

---

## D 类 — 文档（不在本轮 git 内）

### D-1. 本地 docs/ 目录旧版本文档

`docs/R72/` ~ `docs/R99/` 共 **133 个 .md 文件**，约 **~2MB**。

`.gitignore` 中已有 `docs/R*/`，这些文件不会被提交到 git。不影响仓库。

---

## 建议优先级

| 优先级 | 条目 | 风险 | 工作量 |
|--------|------|------|--------|
| P0 | A 类（安全清理） | 🟢 无 | ~5 分钟 |
| P1 | B-1 workspace 死代码 | 🟡 需确认 | ~3 分钟 |
| P2 | B-2 state.py 重复定义 | 🟢 无 | ~1 分钟 |
| P3 | C 类迁移 | 🔴 非本轮 | — |

---

*文档版本: v1.0 | 基于 main 分支 commit b443c49 分析*
