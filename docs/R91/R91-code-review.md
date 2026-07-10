# R91 代码审查报告 — 根治 workspace 阻塞 🔧

> **审查人：** 🔍 小周
> **审查基准：** `37dfe7a` (R90) → `2975e4e` (R91)
> **改动文件：** `server/workspace.py` (+3/-2) · `server/handler.py` (+15/-1)
> **参考文档：**
> - 技术方案: `docs/R91/R91-tech-plan.md`
> - 产品需求: `docs/R91/R91-product-requirements.md`
> - WORK_PLAN: `docs/R91/WORK_PLAN.md`

---

## 审查结论：🟢 通过

3/3 检查项全部通过，改动简洁且无回归风险。

---

## 🅰️ workspace.py max_per_person 上限变更安全

**判定：🟢 通过**

**改动 1 — `create_workspace()` (L267)：**

```python
# 改动前
max_per_person = 1  # configurable later

# 改动后
max_per_person = int(os.environ.get("MAX_ACTIVE_WORKSPACES", "3"))
```

**改动 2 — `can_create_for()` (L407)：**

```python
# 改动前
def can_create_for(owner_id: str, max_active: int = 1) -> bool:

# 改动后
def can_create_for(owner_id: str, max_active: int = 3) -> bool:
```

### 安全性分析

| 检查项 | 状态 | 证据 |
|:-------|:----:|:------|
| 默认 1→3 不破坏现有行为 | ✅ | 严格**更宽松**（允许更多工作室），0 回归风险 |
| `os` import 存在 | ✅ | `workspace.py` L9 `import os` |
| 环境变量读取 + 默认值 | ✅ | `os.environ.get("MAX_ACTIVE_WORKSPACES", "3")` |
| `int()` 转换安全 | ✅ | 数字字符串→int |
| `can_create_for` 默认参数同步 | ✅ | `max_active: int = 1` → `max_active: int = 3` |
| 外部调用者影响 | ✅ | `can_create_for` 仅定义于 workspace.py，**无外部调用**，默认参数修改无运行时影响 |

### 环境变量行为矩阵

| 环境变量值 | `max_per_person` | 行为 |
|:----------:|:----------------:|:-----|
| 不设 | 3 | 默认宽松 |
| `"5"` | 5 | Ops 可配置增大 |
| `"0"` | 0 | `active_count >= 0` 恒真 → 所有创建被阻断（管理员故意禁用） |
| `"-1"` | -1 | 同上（永远阻断） |
| `"abc"` | `ValueError` | 启动崩溃 — 预期 fail-fast 行为，配置错误立即暴露 |

---

## 🅱️ handler.py 错误信息修改不破坏现有调用者

**判定：🟢 通过**

**改动：** `_cmd_create_workspace()` (L700-715) 的 `if not result:` 分支返回值。

### 影响范围分析

| 调用者 / 解析者 | 影响 | 说明 |
|:---------------|:----:|:------|
| `!create_workspace` 命令用户 | ✅ 改善 | 收到精确错误信息（重名/超限），含操作建议 |
| R90 的 `"❌" in create_result` 检查 | ✅ 无影响 | 返回值仍以 `"❌ 创建失败：` 开头 |
| `_cmd_pipeline_start`（handler.py） | ✅ 无影响 | 该函数**不调用** `_cmd_create_workspace`，直接调用 `ws_mod.create_workspace()` |
| 任何解析返回值的代码 | ✅ 不存在 | `_cmd_create_workspace` 的返回值仅作为命令响应发送给用户，无程序化解析者 |

### 错误信息优先级

```
create_workspace() 返回 None
        │
        ├─ ws_mod.get_workspace(ws_id) 存在 → "工作室已存在" + 操作建议
        │
        └─ active_count 超限 → "已有 {N}/{M} 活跃工作室" + 操作建议
```

| 检查项 | 状态 | 证据 |
|:-------|:----:|:------|
| 字符串前缀不变 | ✅ | `"❌ 创建失败："` 保留 |
| 仅修改返回字符串 | ✅ | 不修改函数签名、参数、调用方式 |
| 使用已有变量 `ws_id` | ✅ | 复用 L675 的 `ws_id`，非新构造 |
| 使用已有 API | ✅ | `ws_mod.get_workspace()`、`ws_mod.get_all_workspaces()` |
| `os` import 存在 | ✅ | `handler.py` L3 `import os` |

---

## Scope 合规 — 仅 2 文件

**判定：🟢 通过**

| 文件 | 改动 | 净增行 |
|:-----|:-----|:------:|
| `server/workspace.py` | +3/-2 (L267 `max_per_person`, L407 `can_create_for` 默认参) | +1 |
| `server/handler.py` | +15/-1 (L700-715 `_cmd_create_workspace` 错误细化) | +14 |
| **合计** | **2 文件共 +18/-3 行** | **+15 净增** |

**零修改确认：** `config.py` ✅ · `auto_router.py` ✅ · `__main__.py` ✅ · `tests/` ✅

---

## 额外发现

### 代码质量观察

| # | 类型 | 描述 | 建议 |
|:-:|:----:|:-----|:-----|
| 1 | 🟢 风格 | `handler.py` 中 `max_ws = int(os.environ.get("MAX_ACTIVE_WORKSPACES", "3"))` 与环境变量名重复定义 | 与 workspace.py L267 的读取逻辑一致，无硬编码偏差风险。两处独立读不改坏 |
| 2 | 🟢 健壮性 | `get_workspace(ws_id)` 查重 + `get_all_workspaces()` 计数 — 两步独立检查 | 如果 ws_id 命名不一致（手动创建的场景），重名检查可能 miss → fallback 到超限消息。非阻断性，PM 仍能收到精确的操作建议 |

### 与技术方案一致性

| 技术方案条目 | 实现 | 状态 |
|:------------|:-----|:----:|
| 🅰️ `max_per_person = int(os.environ.get(...))` | workspace.py L267 | ✅ |
| 🅰️ `can_create_for` 默认 1→3 | workspace.py L407 | ✅ |
| 🅱️ 重名分支 + `get_workspace(ws_id)` | handler.py L702-707 | ✅ |
| 🅱️ 超限分支 + `get_all_workspaces()` 计数 | handler.py L708-714 | ✅ |
| 🅱️ 使用已有 `ws_id` 变量（非重算） | handler.py L702 复用 L675 的 ws_id | ✅ |

---

## 审查汇总

| 检查项 | 优先级 | 结果 | 备注 |
|:-------|:------:|:----:|:-----|
| 🅰️ `max_per_person` 上限变更 | 🔴 | 🟢 | 默认 1→3 更宽松，0 回归，可配置降级 |
| 🅱️ handler.py 错误信息 | 🔴 | 🟢 | 仅改返回字符串，无调用者受影响 |
| Scope 合规（仅 2 文件） | 🟢 | 🟢 | workspace.py + handler.py 共 +15 净增 |
| 与技术方案一致性 | 🟢 | 🟢 | 5/5 条目完全匹配 |

**最终结论：🟢 通过** — R91 改动干净利落。`max_per_person` 从 1 提升为可配置默认 3，`os` import 两文件均已存在无需新增，错误信息从模糊单条拆分为精确区分。总共 +15 净增行且零回归风险。可进入 Step 5 🦐 QA 测试。

---

*报告编写: 🔍 小周 · 2026-07-10*
