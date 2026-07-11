# R91 技术方案 — 根治 workspace 阻塞 🔧

> **版本：** v1.0
> **状态：** 📝 初稿
> **作者：** 🏗️ 架构师
> **日期：** 2026-07-10
> **基于需求文档：** `docs/R91/R91-product-requirements.md` v1.0
> **基于工作计划：** `docs/R91/WORK_PLAN.md` v1.0
> **改动文件：** `server/workspace.py`（~+7 行） · `server/handler.py`（~+15 行）

---

## 目录

1. [改动总览](#1-改动总览)
2. [🅰️ workspace.py: max_per_person 可配置化](#️-workspacepy-max_per_person-可配置化)
3. [🅱️ handler.py: 创建失败错误信息细化](#️-handlerpy-创建失败错误信息细化)
4. [改动对照表](#4-改动对照表)
5. [兼容性分析](#5-兼容性分析)
6. [风险与缓解](#6-风险与缓解)
7. [验收清单](#7-验收清单)

---

## 1. 改动总览

### 1.1 根因

```python
# server/workspace.py L267
max_per_person = 1  # configurable later
```

PM 每轮 `!pipeline_start` 创建新工作室时，因为旧工作室（如 R88/R89/R90）仍为 ACTIVE 状态，创建总是返回 None → 管线孤儿 → AutoRouter 无信号 → PM 手动 inbox 协调全流程。

### 1.2 两处改动

| # | 改动 | 文件 | 净增行 | 修改函数数 |
|:-:|:-----|:-----|:------:|:----------:|
| 🅰️ | `max_per_person` 从硬编码 `1` → 读取 `MAX_ACTIVE_WORKSPACES` 环境变量，默认 `3` | `workspace.py` | ~+7 | 2（`create_workspace` + `can_create_for`） |
| 🅱️ | `_cmd_create_workspace` 失败信息细化（区分重名 vs 超限） | `handler.py` | ~+15 | 1 |
| **合计** | | **2 文件** | **~+22 行净增** | **3 函数** |

### 1.3 文件全景

```
server/workspace.py
│
├── create_workspace()  L253         ← 🅰️: max_per_person=MAX_ACTIVE
│       max_per_person = _get_max_active_workspaces()
│       # 移除旧的 "configurable later" 注释
│
└── can_create_for()    L407         ← 🅰️: 默认参数 1 → 3
        def can_create_for(owner_id, max_active=3):

server/handler.py
│
└── _cmd_create_workspace()  L701    ← 🅱️: None → 区分重名/超限
        if not result:
            # 检查重名
            # 检查超限
            return 细化错误消息
```

---

## 2. 🅰️ workspace.py: max_per_person 可配置化

### 2.1 改动位置

**文件：** `server/workspace.py`
**函数：** `create_workspace()` — L267

### 2.2 改动内容

#### 方案 A（✅ 选定）：读取环境变量

```python
# workspace.py 文件顶（import 区附近）

import os  # 通常已在文件顶，确认后无需新增


# L267: 改动前
max_per_person = 1  # configurable later

# L267: 改动后（R91 🅰️）
max_per_person = int(os.environ.get("MAX_ACTIVE_WORKSPACES", "3"))
```

#### 同时修改 `can_create_for()` L407 默认参数

```python
# L407: 改动前
def can_create_for(owner_id: str, max_active: int = 1) -> bool:

# L407: 改动后（R91 🅰️ 保持一致）
def can_create_for(owner_id: str, max_active: int = 3) -> bool:
```

#### 完整改动 diff

```diff
# ═══ workspace.py ═══

 # L1-10: import 区确认是否有 os
+import os  # ← 如已有则不需新增，用于读取环境变量

 # L267: create_workspace()
-    max_per_person = 1  # configurable later
+    # R91 🅰️: 从环境变量读取，默认 3 个活跃工作室
+    max_per_person = int(os.environ.get("MAX_ACTIVE_WORKSPACES", "3"))

 # L407: can_create_for()
-def can_create_for(owner_id: str, max_active: int = 1) -> bool:
+def can_create_for(owner_id: str, max_active: int = 3) -> bool:
```

### 2.3 环境变量行为矩阵

| `MAX_ACTIVE_WORKSPACES` | `max_per_person` | 行为 |
|:-----------------------:|:----------------:|:-----|
| 不设 | `3` | 每人最多 3 个活跃工作室 |
| `5` | `5` | 5 个 |
| `0` | `0` | 永远无法创建（等价禁用，不推荐） |
| `-1` | `-1` | 永远大于 `active_count >= 0` → 永远无法创建 |
| `abc` | `int()` 抛 ValueError | ⚠️ 启动崩溃（预期行为：环境变量错误立即暴露） |

### 2.4 设计理由

1. **轻量级：** 只需修改 2 行 + 7 字符。不加 config.py、不修改其他模块
2. **Ops 可控：** 环境变量部署时设定，无需改代码
3. **向后兼容：** 不设环境变量时默认为 3（比原来宽松），不破坏现有行为

---

## 3. 🅱️ handler.py: 创建失败错误信息细化

### 3.1 改动位置

**文件：** `server/handler.py`
**函数：** `_cmd_create_workspace()` — L701-702
**精确行：** L701（`if not result:` 分支内的 return 字符串）

### 3.2 当前代码

```python
# handler.py L699-702
result = ws_mod.create_workspace(ws_id, ws_name, sender_id, sender_name)
if not result:
    return f"❌ 创建失败：{ws_name} 可能已存在，或管理员名下活跃工作区过多"
```

### 3.3 改动后代码

```python
# handler.py L699-715
result = ws_mod.create_workspace(ws_id, ws_name, sender_id, sender_name)
if not result:
    # R91 🅱️: 区分重名 vs 超限
    name_id = f"ws_{sender_id[:8]}-{ws_name[:20]}"
    existing_ws = ws_mod.get_workspace(name_id)
    if existing_ws:
        return (
            f"❌ 创建失败：工作室「{ws_name}」已存在。\n"
            f"  使用 --workspace-id {name_id} 附着，或先 !close_workspace {name_id}"
        )
    # 检查活跃工作区数量
    active_count = sum(
        1 for w in ws_mod.get_all_workspaces()
        if w.owner_id == sender_id and w.state == ws_mod.WorkspaceState.ACTIVE
    )
    max_ws = int(os.environ.get("MAX_ACTIVE_WORKSPACES", "3"))
    return (
        f"❌ 创建失败：管理者名下已有 {active_count}/{max_ws} 活跃工作室。\n"
        f"  请先 !close_workspace 关闭旧工作室后再创建"
    )
```

### 3.4 详细 diff

```diff
 # handler.py L699-702
 result = ws_mod.create_workspace(ws_id, ws_name, sender_id, sender_name)
 if not result:
-    return f"❌ 创建失败：{ws_name} 可能已存在，或管理员名下活跃工作区过多"
+    # R91 🅱️: 区分重名 vs 超限
+    name_id = f"ws_{sender_id[:8]}-{ws_name[:20]}"
+    existing_ws = ws_mod.get_workspace(name_id)
+    if existing_ws:
+        return (
+            f"❌ 创建失败：工作室「{ws_name}」已存在。\n"
+            f"  使用 --workspace-id {name_id} 附着，或先 !close_workspace {name_id}"
+        )
+    active_count = sum(
+        1 for w in ws_mod.get_all_workspaces()
+        if w.owner_id == sender_id and w.state == ws_mod.WorkspaceState.ACTIVE
+    )
+    max_ws = int(os.environ.get("MAX_ACTIVE_WORKSPACES", "3"))
+    return (
+        f"❌ 创建失败：管理者名下已有 {active_count}/{max_ws} 活跃工作室。\n"
+        f"  请先 !close_workspace 关闭旧工作室后再创建"
+    )
```

### 3.5 ws_id 构建一致性

`ws_id` 的构建逻辑在 `_cmd_create_workspace` 中已在 L675 定义：

```python
ws_id = f"{p.WORKSPACE_ID_PREFIX}{sender_id[:8]}-{ws_name[:20]}"
```

但在 R91 🅱️ 错误细化代码中，我们需要用同样的逻辑去 `get_workspace` 检查。因为 `create_workspace` 返回 None 时，`ws_id` 可能已被占用但查不到（如重名时的 ws_id 来自名称而非 ID）。简化起见，使用 L675 已定义的 ws_id 变量即可：

```python
# ws_id 已在 L675 定义，直接复用
existing_ws = ws_mod.get_workspace(ws_id)
```

### 3.6 错误消息示例

**场景 1：重名**

```
❌ 创建失败：工作室「R90-dev」已存在。
  使用 --workspace-id ws_abc12345-R90-dev 附着，或先 !close_workspace ws_abc12345-R90-dev
```

**场景 2：超限（3 个活跃中）**

```
❌ 创建失败：管理者名下已有 3/3 活跃工作室。
  请先 !close_workspace 关闭旧工作室后再创建
```

**场景 3：超限（可调上限）**

```
❌ 创建失败：管理者名下已有 3/5 活跃工作室。
  请先 !close_workspace 关闭旧工作室后再创建
```

---

## 4. 改动对照表

### 4.1 workspace.py 改动

| # | 位置 | 行号 | 操作 | 说明 |
|:-:|:-----|:----:|:----|:------|
| 1 | `create_workspace()` | L267 | ✏️ 修改 1 行 | `max_per_person = 1` → `int(os.environ.get("MAX_ACTIVE_WORKSPACES", "3"))` |
| 2 | `can_create_for()` 签名 | L407 | ✏️ 修改默认参数 | `max_active: int = 1` → `max_active: int = 3` |
| **合计** | | | **+2 行净增** | |

### 4.2 handler.py 改动

| # | 位置 | 行号 | 操作 | 说明 |
|:-:|:-----|:----:|:----|:------|
| 1 | `_cmd_create_workspace()` | L700-702 | ✏️ 替换 return 字符串 | `"❌ 创建失败：{ws_name} 可能已存在..."` → 分支判断 + 细化消息 |
| **合计** | | | **〜+15 行净增** | |

---

## 5. 兼容性分析

### 5.1 向后兼容矩阵

| 场景 | 旧行为 | R91 后行为 | 兼容性 |
|:-----|:-------|:-----------|:------:|
| `create_workspace` 首次调用 | `max_per_person=1` | `max_per_person=3` | ✅ 更宽松 |
| 已有 1 个活跃工作室再创建 | ❌ 返回 None | ✅ 可创建第 2 个 | ✅ 修复 |
| 已有 2 个活跃工作室再创建 | ❌ 返回 None | ✅ 可创建第 3 个 | ✅ 修复 |
| 已有 3 个活跃工作室再创建 | ❌ 返回 None | ❌ 返回 None（与旧行为一致） | ✅ 一致 |
| `!create_workspace` 重名 | 模糊错误 | 精确「已存在」+ 操作建议 | ✅ 改善 |
| `!create_workspace` 超限 | 模糊错误 | 精确「3/3 活跃」+ 操作建议 | ✅ 改善 |
| 不设环境变量 | N/A | 默认 3 | ✅ 宽松但合理 |
| handler.py 调用者 | 不识别错误类型 | 不改变调用方式 | ✅ 返回值字符串优化 |

### 5.2 已知的遗留问题

| 问题 | 影响 | 计划 |
|:-----|:-----|:------|
| 旧工作室不会自动 close | 用户需手动 `!close_workspace` | 建议后续轮次加管线完成自动归档 |
| 3 个上限可能仍然不够（长期运行） | 环境变量可调大 | 无需改代码 |

---

## 6. 风险与缓解

### 6.1 风险评估

| # | 风险 | 等级 | 缓解措施 |
|:-:|:-----|:----:|:---------|
| R1 | `MAX_ACTIVE_WORKSPACES` 设为 0 或负数 → 永远无法创建 | 🟢 低 | 文档说明正确取值范围 ≥1。设为 0 属管理员故意禁用 |
| R2 | `MAX_ACTIVE_WORKSPACES=abc` → `int()` 抛 ValueError → 进程崩溃 | 🟡 中 | **预期行为**：环境变量错误应使进程崩溃重启，不退化为静默错误。部署时可自动暴露 |
| R3 | 3 个活跃工作室占满后旧工作室不自动释放（无自动归档） | 🟡 中 | `!close_workspace` 手动释放，或等 7 天自动清理（`ARCHIVED_RETENTION_DAYS`）。建议下一轮加管线完成自动归档 |
| R4 | handler.py 中硬编码了 `os.environ.get()` 而非引用常量 | 🟢 低 | 两处的环境变量名一致，同步修改只需搜索 `MAX_ACTIVE_WORKSPACES` |
| R5 | `_cmd_create_workspace` 中重名检查用 `ws_mod.get_workspace(name_id)` 可能不精确 | 🟢 低 | `_cmd_create_workspace` 中 `ws_id` 已在 L675 定义，可直接复用。后续通过单元测试验证 |

### 6.2 回退方案

| 级别 | 操作 | 复杂度 |
|:----:|:-----|:------:|
| 🟢 浅回退 🅰️ | `max_per_person` 改回硬编码 `1` | 1 行 |
| 🟢 浅回退 🅱️ | 恢复原 `return f"❌ 创建失败：..."` 字符串 | ~15 行注释 |
| 🔴 全回退 | `git revert <commit-sha>` | 1 命令 |

---

## 7. 验收清单

### 🅰️ max_per_person 可配置化（3 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🅰️-1 | 不设 `MAX_ACTIVE_WORKSPACES` → 可创建第 2 个工作室 | `!create_workspace test2` 第 2 次成功 | 创建成功 ✅ |
| 🅰️-2 | 设 `MAX_ACTIVE_WORKSPACES=5` → 环境变量生效 | 设 env=5 → 可创建第 4、5 个 | 创建成功 ✅ |
| 🅰️-3 | 超过上限后无法创建 | 第 4 个（默认 3）→ 返回 None | 创建失败 ❌ |

### 🅱️ 错误信息细化（3 项）

| # | 验收项 | 验证方法 | 预期 |
|:-:|:-------|:---------|:-----|
| 🅱️-1 | 重名时消息含「已存在」+ 操作建议 | 创建同名工作室 | ❌ 「已存在」+ `--workspace-id` / `!close_workspace` |
| 🅱️-2 | 超限时消息含活跃数量 / 上限 | 超限触发 | ❌ 「已有 3/3 活跃工作室...!close_workspace」|
| 🅱️-3 | 超限时显示真实活跃数 | count 检查 | 如 `已有 2/3` 或 `已有 3/3` 正确 |

---

*本文档由 🏗️ 架构师编写，待 Step 3 👨‍💻 编码实现。*
