# R73 技术方案 — R72 认证体系修复 🛠️

> 版本：v1.0
> 作者：🏗️ 小开 (arch)
> 日期：2026-07-06

---

## 1. 当前基线确认

### 1.1 分支状态

- 基线 dev commit：`b8b3e8a`（`docs(R73): WORK_PLAN 状态更新 → 已审核`）
- 方向 B 离线恢复修复代码已推 dev：`9f353a9`（`R72 B: 修复在线状态显示问题`）
- 方向 A 权限打通和方向 C 文档修正：未编码

### 1.2 文件基线行号（实际）

| 文件 | 总行数 | 关键行号 |
|:-----|:------:|:---------|
| `server/auth.py` | 213 | `is_approved()` @ L68-69, `role_level()` @ L79-85, `persistence` import @ L8 |
| `server/handler.py` | 6026 | `_check_command_permission()` @ L408-443, `_ADMIN_COMMANDS` @ L3910-3946, `auth.is_approved()` 调用 @ L4121 |
| `docs/R72/REGISTRATION-GUIDE.md` | 185 | 小爱角色行 @ L133 |

### 1.3 函数签名确认

| 函数 | 位置 | 签名 | 备注 |
|:-----|:----:|:-----|:-----|
| `auth.is_approved()` | `auth.py:68` | `is_approved(agent_id) -> bool` | ⚠️ 函数名是 `is_approved` 而非 WORK_PLAN 中写的 `is_approved_user` |
| `auth.get_users()` | `auth.py:72` | `get_users() -> dict` | 实际调用 `persistence.get_approved_users()` |
| `auth.role_level()` | `auth.py:79` | `role_level(agent_id) -> int` | 对未找到 agent 默认返回 2 |
| `persistence.get_api_keys()` | `persistence.py:187` | `get_api_keys() -> dict` | 已被 R72 使用 |
| `_check_command_permission()` | `handler.py:408` | `(agent_id, cmd_name, cmd, params) -> (bool, str)` | 当前无 member 级别(L2)分支 |
| `_is_any_workspace_admin()` | `handler.py:392` | `(agent_id) -> bool` | 检查任意工作区的 admin/owner |

### 1.4 关键审计发现：WORK_PLAN 方案有设计缺口

| # | 问题 | 影响 |
|:-:|:-----|:-----|
| ⚠️ D1 | `is_approved()` 函数名是 `is_approved` 不是 `is_approved_user` | 不影响逻辑，但 WORK_PLAN/PRD 引用名不准确 |
| 🔴 D2 | `_check_command_permission()` **没有 member 级别（L2）分支** — `min_role <= 3` 的所有分支均要求 workspace admin | WORK_PLAN 说「降 min_role 3→2」单独无效：R72 agent 不是 workspace admin，降了还是会拒 |
| 🟡 D3 | `/opt/data/.ws-bridge/credentials.json` **已不存在** | 方向 D 无需操作 |

**D2 的详细分析：**

当前 `_check_command_permission` 结构：
```python
# L416-443
min_role = cmd.get("min_role", 4)
ws_scope = cmd.get("workspace_scope", False)
# → 所有 agent_card 命令 ws_scope=True

if min_role <= 3 and ws_scope:
    if _is_any_workspace_admin(agent_id) or auth.is_global_admin(agent_id):
        return True, ""
    return False, "..."  # ← R72 agent 即使 min_role=2 也走到这里

if min_role <= 3 and not ws_scope:
    if _is_any_workspace_admin(agent_id):
        return True, ""
    return False, "..."
```

min_role=3 和 min_role=2 走向**同一分支**，都要求 workspace admin。R72 api_key agent 不是 workspace admin → 永远拒绝。**单纯降 min_role 不解决任何问题。**

### 1.5 改动估算对比

| 项 | WORK_PLAN 预估 | 实际 | 偏差原因 |
|:---|:--------------:|:----:|:---------|
| `auth.py` `is_approved()` | ~3 行 | ~3 行 | 一致 |
| `handler.py` min_role 降级 | ~2 行 | ~2 行（注册表）+ **~4 行（`_check_command_permission` 新增 L2 分支）** | WORK_PLAN 未识别权限检查函数的设计缺口 |
| `REGISTRATION-GUIDE.md` | ~1 行 | ~1 行 | 一致 |
| 方向 D 删文件 | 删除 | **0 行 — 文件已不存在** | 方向 D 已提前完成 |
| **总净增行** | **~6 行** | **~10 行** | 多 4 行因 L2 权限分支 |

---

## 2. 设计决策

### D1 — `is_approved()` 函数名对齐

- **决策内容**：保持函数名 `is_approved()` 不变，在文档中修正引用名
- **理由**：改名需要改调用方 L4121，增加 scope creep；现有函数名已自我描述
- **位置**：`auth.py:68-69`

### D2 — `_check_command_permission` 新增 member 级别（L2）分支

- **决策内容**：在现有 `min_role <= 3` 分支之前插入 `min_role <= 2` 分支，检查 `auth.is_approved()` 而非 workspace admin
- **理由**：这是让 R72 agent 能执行只读命令的**唯一路径**。降 min_role 必须配合权限分支的语义化。方案见 D3。
- **位置**：`handler.py:419`（在 pipeline_start bypass 之后，workspace admin 检查之前）
- **备选方案**：
  - *修改 `_is_any_workspace_admin` 包含 api_key agent* → 错误，workpace admin 应该人工授予
  - *从 `_check_command_permission` 中移除 agent_card list/get 的权限检查* → 副作用大，不如显式 L2 分支
  - *让 `role_level()` 返回 3 级* → 改变语义，影响其他命令

### D3 — min_role 3→2 精确范围

- **决策内容**：仅 `agent_card`（别名）、`agent_card_list`、`agent_card_get` 三条命令降为 min_role=2
- **理由**：只读操作安全，set/unset/reload/register 保持 3 级
- **位置**：`handler.py:L3911, L3915, L3919`
- **确认**：`agent_card_set` (L3923)、`agent_card_unset` (L3927)、`agent_card_reload` (L3931)、`agent_card_register` (L3940)、`agent_card_auto_register` (L3944) **均保持 min_role=3 不变**

### D4 — 小爱角色 operations

- **决策内容**：`docs/R72/REGISTRATION-GUIDE.md` L133 行 `[\"admin\"]` → `[\"operations\"]`
- **理由**：仅影响文档展示的 pipeline_roles 映射，不改变权限逻辑

### D5 — 方向 D 无需操作

- **决策内容**：跳过 `/opt/data/.ws-bridge/credentials.json` 删除
- **理由**：文件已不存在

---

## 3. 方向 A — 核心改动

### A-① `server/auth.py:68-69` — `is_approved()` 增加 api_key fallback

**改前：**
```python
def is_approved(agent_id: str) -> bool:
    return agent_id in persistence.get_approved_users()
```

**改后：**
```python
def is_approved(agent_id: str) -> bool:
    if agent_id in persistence.get_approved_users():
        return True
    # R73: R72 api_key 注册的 agent 也视为已认证
    api_keys = persistence.get_api_keys()
    return agent_id in api_keys
```

**依赖：** 无 — `persistence` 已在 L8 import，`persistence.get_api_keys()` 存在（`persistence.py:187`）

### A-② `server/handler.py:408-443` — `_check_command_permission` 新增 L2 分支

**在 L422 后（pipeline_start 绕过之后），插入：**

```python
    # ── R73: Member-level commands (min_role=2) ───────────────
    # Any approved agent (including R72 api_key registered) can execute.
    if min_role <= 2:
        if auth.is_approved(agent_id):
            return True, ""
        return False, "权限不足：仅已认证成员可执行"
```

**位置精确：** 在 `if cmd_name == "pipeline_start"` 绕过段之后、`if min_role <= 3 and ws_scope` 之前。

**逻辑验证：**
| 场景 | min_role | 旧路径 | 新路径 | 结果 |
|:----|:--------:|:-------|:-------|:----:|
| R72 agent `!agent_card list` | 2 | 被 ws_scope 分支拒 | ⚡ 新 L2 分支 → `is_approved()`=True ✅ | 通过 |
| 旧 agent `!agent_card list` | 2 | 被 ws_scope 分支拒（旧 agent 也受制） | ✅ `is_approved()`=True → 通过 | 通过 |
| R72 agent `!agent_card set` | 3 | 被 ws_scope 分支拒 | 跳过 L2 分支 → 进入 ws_scope 分支 → 被拒 ✅ | 拒绝 |
| 旧 workspace admin `!agent_card set` | 3 | ws_scope 分支通过 ✅ | 不变 | 通过 |

### A-③ `server/handler.py:L3911, L3915, L3919` — min_role 3→2 降级

```diff
-    "agent_card":       { ..., "min_role": 3, ... },
-    "agent_card_list":  { ..., "min_role": 3, ... },
-    "agent_card_get":   { ..., "min_role": 3, ... },
+    "agent_card":       { ..., "min_role": 2, ... },
+    "agent_card_list":  { ..., "min_role": 2, ... },
+    "agent_card_get":   { ..., "min_role": 2, ... },
```

**其余 5 条命令保持不变（`min_role: 3`）：**
- `agent_card_set` (L3923)
- `agent_card_unset` (L3927)
- `agent_card_reload` (L3931)
- `agent_card_register` (L3940)
- `agent_card_auto_register` (L3944)

---

## 4. 方向 C — 文档修正

### C-① `docs/R72/REGISTRATION-GUIDE.md:133`

```diff
- | 运维 小爱 | `小爱` | `["admin"]` | ... |
+ | 运维 小爱 | `小爱` | `["operations"]` | ... |
```

---

## 5. 改动汇总

### 5.1 文件改动一览表

| # | 文件 | 改动类型 | 行号 | 内容 | 净增行 |
|:-:|:-----|:---------|:----:|:-----|:-----:|
| 1 | `server/auth.py` | **修改** | L68-72 | `is_approved()` 增加 api_key fallback | ~3 行 |
| 2 | `server/handler.py` | **修改** | L425-431（新增段） | `_check_command_permission` 新增 L2 member 分支 | ~4 行 |
| 3 | `server/handler.py` | **修改** | L3911, L3915, L3919 | 3 处 min_role: 3→2 | ~3 值改 |
| 4 | `docs/R72/REGISTRATION-GUIDE.md` | **修改** | L133 | `["admin"]` → `["operations"]` | ~1 值改 |
| | **总净增行** | | | | **~10 行** |

### 5.2 Scope 合规检查

| 边界文件 | 是否改动 | 说明 |
|:---------|:--------:|:-----|
| `server/auth.py` ✅ | 改 | `is_approved()` api_key fallback |
| `server/handler.py` ✅ | 改 | L2 权限分支 + min_role 降级 |
| `docs/R72/REGISTRATION-GUIDE.md` ✅ | 改 | 小爱角色 operations |
| `server/persistence.py` ❌ | 不改 | 无需修改 — `get_api_keys()` 已存在 |
| `server/agent_card.py` ❌ | 不改 | 已在 scope 外 |
| `server/config.py` ❌ | 不改 | 已在 scope 外 |
| `server/workspace.py` ❌ | 不改 | 已在 scope 外 |
| `server/timeout_tracker.py` ❌ | 不改 | 已在 scope 外 |

**零新依赖、零 scope 外文件改动。**

---

## 6. 风险与缓解

| 风险 | 影响 | 缓解 |
|:-----|:-----|:-----|
| **R1**: L2 分支添加后旧 agent 行为变化 | 旧 agent 从未显式被 L2 分支影响 — 它们之前被 ws_scope 分支拒绝（需 workspace admin），L2 分支反而**放开了**它们也能执行 list/get | ✅ 预期行为 — 对旧 agent 是权限提升（可执行只读命令），属于正确改动 |
| **R2**: `persistence.get_api_keys()` 在 auth.py 中导入路径 | 循环导入 | ✅ `from . import persistence` 已在 auth.py L8 导入，无环 |
| **R3**: L2 分支插入位置错误影响现有 bypass | `pipeline_start` 和 `step_complete` 已有独立 bypass（L422-430），新 L2 分支插入其后不影响它们 | ✅ 插入在 L422-430 之后（已在代码中确认） |
| **R4**: `is_approved()` 修改后 REGISTRATION_CHANNEL 路由变化 | R72 注册流程中使用 REGISTRATION_CHANNEL 的逻辑依赖 is_approved()=False | ✅ 刚注册成功的 agent 通过 `handle_register` 写入 api_keys，auth 时 is_approved() 才返回 True。注册流程中 handler 还未读到 api_keys 新条目？→ `handle_register` 调用写 api_keys 后再设置 card，is_approved 在后续命令时检查，时序正确 |

---

## 7. 验证方案

### 7.1 单元验证

| # | 验证项 | 方法 | 预期 |
|:-:|:-------|:-----|:-----|
| V-1 | `auth.is_approved(agent_id)` 对 api_key agent 返回 True | Python REPL: `auth.is_approved("ws_xxx")` | True |
| V-2 | `auth.is_approved(agent_id)` 对旧 approved_user 不变 | Python REPL: `auth.is_approved("old_agent")` | True（仍在 get_users 中） |
| V-3 | `_check_command_permission` L2 分支对 api_key agent 通过 | 构造测试调用 | True |
| V-4 | `_check_command_permission` L3 命令对 api_key agent 拒绝 | 构造测试调用 | False |
| V-5 | min_role 3→2 精确：只改 3 条命令 | grep handler.py min_role 确认 | list/get 为 2，其余为 3 |

### 7.2 管线集成验证

| # | 验证项 | 方法 | 预期 |
|:-:|:-------|:-----|:-----|
| V-6 | 用 api_key agent 连接后发 `!agent_card list` | 部署后实际测试 | 返回卡片列表，不报权限不足 |
| V-7 | 用 api_key agent 发 `!agent_card set` | 同上 | 权限不足被拒 |

---

## 8. 脱敏检查清单

- [x] 文档使用角色名（小开/arch、小谷/pm、爱泰/dev、小周/review、泰虾/qa、小爱/operations）
- [x] 不包含真实用户名、密码、token、api_key
- [x] 代码片段使用通用 agent_id（`ws_xxx`、`old_agent`）
