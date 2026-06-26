# R42 代码审查报告 — 管线自动触发与 Step 接力

> **审查者：** 🔍 小周
> **审查日期：** 2026-06-26
> **审查对象：** `cf78673 feat(R42): A-!pipeline_start B-!step_complete C-!pipeline_status D-大厅隔离`
> **需求文档：** [R42-product-requirements.md](R42-product-requirements.md)
> **技术方案：** [R42-tech-plan.md](R42-tech-plan.md)

---

## 0. 审查结论

🔴 **有条件通过** — 1 个 🔴 Bug 需修复，2 个 🟡 留意点

| 分类 | 数量 |
|:----|:----:|
| 🔴 阻塞（P0/P1） | 1 |
| 🟡 留意（非阻塞） | 2 |
| 🟢 通过 | 7 |

---

## 1. 规范检查

| 检查项 | 状态 | 说明 |
|:-------|:----:|:------|
| Commit message 格式 | ✅ | `feat(R42): A-!pipeline_start B-!step_complete C-!pipeline_status D-大厅隔离` — 符合 Conventional Commits |
| 无 TODO/FIXME/debugger 残留 | ✅ | 纯服务端代码，无前端调试残留 |
| 文件范围符合方案 | ✅ | 变更文件：handler.py + config.py，与技术方案一致 |
| 双入口同步 | ✅ | 所有新命令通过 `_ADMIN_COMMANDS` 注册，由 `handle_broadcast()` 分发。`ws_handler()` (__main__.py) 中无等价处理路径 → **无同步问题** |
| Python 语法 | ✅ | 两次通过（`compile()` + `ast.parse()`） |
| 导入完整性 | ✅ | `config.PIPELINE_STEP_MAP` 可正常导入 |
| 技术方案改动坐标精确性 | ✅ | 方案标注的文件、行号范围与实际 diff 一致 |

---

## 2. 需求→方案→代码追溯矩阵

### 方向 A — `!pipeline_start`

| # | 验收标准 | 方案项 | 代码位置 | 状态 |
|:-:|:---------|:-------|:---------|:----:|
| A-1 | `_admin` 发 `!pipeline_start R42` → 工作室创建 | A-1 ③ `_cmd_create_workspace` | handler.py:919-928 `_cmd_pipeline_start()` | ✅ |
| A-2 | 创建后自动发起点名报道 | A-1 ④ `_auto_rollcall_notify` (在 `_cmd_create_workspace` 内部) | handler.py:432 `asyncio.create_task(...)` | ✅ |
| A-3 | 点名完成后自动点名架构师，附带需求文档 URL | A-1 ⑤ `_cmd_rollcall_next` | handler.py:935-942 `rollcall_result = await _cmd_rollcall_next(...)` | ✅ |
| A-4 | 架构师 task 可通过 `!task_query` 查到 | A-1 ⑥ `_cmd_task_create` | handler.py:944-949 | ✅ |
| A-5 | 非 `_admin` 频道发 `!pipeline_start` 返回拒绝 | _admin 路由拦截 | handler.py:1334 _admin intercept (仅 `_admin` 频道可触发 admin 命令) | ✅ |
| A-6 | 重复调用返回「已完成」 | A-1 ② `pipeline_is_active()` 锁 | handler.py:913-915 | ✅ |

### 方向 B — `!step_complete`

| # | 验收标准 | 方案项 | 代码位置 | 状态 |
|:-:|:---------|:-------|:---------|:----:|
| B-1 | `!step_complete Step3 --output 342c794` → 点名开发工程师 | A-2 ③ `_cmd_rollcall_next` | handler.py:1045-1051 | ✅ |
| B-2 | 开发工程师收到点名含 commit 引用 | A-2 ③ `context_summary` 包含 output_ref | handler.py:1044 | ✅ |
| B-3 | Step Task 被标记 completed | A-2 ① `_cmd_task_update` → COMPLETED | handler.py:1027-1031 | ⚠️ **见 W-1** |
| B-4 | `--output` 缺省返回用法提示 | `if not output_ref:` 分支 | handler.py:987-988 | ✅ |
| B-5 | Step 7 完成后标记管线结束 | A-2 末步分支：关闭工作室 + 恢复大厅 | handler.py:1036-1042 | ⚠️ **见 W-2** |

### 方向 C — `!pipeline_status`

| # | 验收标准 | 方案项 | 代码位置 | 状态 |
|:-:|:---------|:-------|:---------|:----:|
| C-1 | 返回 Step 进度表 | A-3 `_cmd_pipeline_status` | handler.py:1081-1121 | ✅ |
| C-2 | 活跃 Step 🟢，已完成 ✅，未轮到 ⏳ | 状态图标映射 | handler.py:1097-1106 | ✅ |
| C-3 | 无管线时返回「当前无活跃管线」 | 空 `_PIPELINE_STATE` 分支 | handler.py:1085, 1119 | ✅ |

### 方向 D — 大厅隔离

| # | 验收标准 | 方案项 | 代码位置 | 状态 |
|:-:|:---------|:-------|:---------|:----:|
| D-1 | `!pipeline_start` 后大厅停止接收新消息 | 大厅拦截 + `set_lobby_paused(True)` | handler.py:1406-1421 | ✅ |
| D-2 | 消息自动路由到工作室 | 拦截器检查活跃工作区并自动路由 | handler.py:1409-1414 | ✅ |
| D-3 | Step 7 完成后大厅恢复接收 | `set_lobby_paused(False)` | handler.py:1040 | ⚠️ **见 W-2** |
| D-4 | 恢复后已有历史不受影响 | 暂停时仅阻止新消息路由，不修改已有记录 | 代码设计层面 | ✅ |
| D-5 | 工作室在管线结束时自动关闭 | `_cmd_close_workspace(ws_id)` | handler.py:1038 | ⚠️ **见 W-2** |
| D-6 | 异常终止自动恢复大厅 | `_LOBBY_PAUSED` 模块变量重启后重置为 False | 天然满足 | ✅ |

### 追溯率统计

| 方向 | 验收项 | ✅ 通过 | ⚠️ 留意 | 追溯率 |
|:----|:-----:|:------:|:--------:|:------:|
| A | 6 | 6 | 0 | 100% |
| B | 5 | 3 | 2 | 100% |
| C | 3 | 3 | 0 | 100% |
| D | 6 | 4 | 2 | 100% |
| **合计** | **20** | **16** | **4** | **100%** |

---

## 3. 发现清单

### 🔴 F-1: `!pipeline_start` 权限检查配置不一致

**位置：**
- `_ADMIN_COMMANDS` pipeline_start 注册 (handler.py:1195) — `workspace_scope: False, min_role: 3`
- `_check_command_permission` (handler.py:404) — `if min_role <= 3 and not ws_scope: return False`

**描述：**
`pipeline_start` 注册为 `workspace_scope=False`（可在 `_admin` 频道触发）和 `min_role=3`（P3+ 可用）。但 `_check_command_permission` 的现有逻辑对非全局管理员(P4)的 P3 用户直接返回 `False`：

```python
# handler.py:404
if min_role <= 3 and not ws_scope:
    return False, "权限不足：该操作仅超级管理员可执行"
```

所有已有的 `workspace_scope=False` 命令 (`approve_pairing`, `approve_ws_admin`, `reject_ws_admin`, `list_pending`) 均为 `min_role=4`（全局管理员专用）。`min_role=3` + `workspace_scope=False` 的组合之前未被使用，导致 `_check_command_permission` 不识别此配置。

**影响：** P3 工作区管理员可进入 `_admin` 频道（`_can_broadcast` 通过），但输入 `!pipeline_start R42` 时被二次权限检查误拒。

**修复建议（选一）：**

| 方案 | 改动点 | 工作量 | 影响 |
|:----|:-------|:------:|:----:|
| **A** 将 `min_role` 改为 4 | handler.py:1195 `min_role: 4` | 1 行 | 仅全局管理员可启动管线 |
| **B** 修改 `_check_command_permission` | handler.py:404 将 `return False` 改为 `return True, ""` | 1 行 | 允许 P3+ 执行所有 `workspace_scope=False` 命令 |
| **C** 区分 `min_role=3` 和 `min_role=4` 对 `ws_scope=False` 的处理 | handler.py:401-407 重构 | ~5 行 | 仅允许 P3+ 执行 `pipeline_start` 等特定命令 |

建议采用 **方案 B**（最简单，且 `_admin` 频道的入口控制 `_can_broadcast` 已限制仅 P3+ 可进入，双重校验不是必须的）。

---

### 🟡 W-1: `_cmd_task_update` 中 `assigned_role` 权限检查可能不匹配

**位置：** handler.py:654-660 (`_cmd_task_update` 权限检查)

**描述：**
Task 创建时 `assigned_role` 设为 Step 映射表中的基础角色名（如 `"arch"`、`"dev"`、`"qa"`）。`_cmd_task_update` 的权限检查代码为：

```python
if task.get("assigned_role"):
    sender_info = users.get(sender_id, {})
    if sender_info.get("role") != "admin":
        if task["assigned_role"] not in (sender_id, sender_info.get("name", "")):
            return f"❌ 权限不足：Task 分配给 {task['assigned_role']}，你不可更新"
```

当 `_cmd_step_complete` 调用 `_cmd_task_update` 更新 Task 状态时，`sender_id` 是完成者的 ID，其 `name` 可能是 `"arch-bot"` 或类似格式。而 `task["assigned_role"]` 是 `"arch"`。三者比较：
- `"arch" == sender_id`? → 否（sender_id 是长字符串 `agent:main:...:arch_bot`）
- `"arch" == sender_name`? → 否（sender_name 是 `"arch-bot"`）

**结论：** 只有当发送者的 auth 角色为 `"admin"` 时才能绕过此检查。如果 bots 的 auth 角色均为 `"admin"`，则无实际影响。若非，则 `_cmd_step_complete` 将无法将 Task 标记为 COMPLETED。

**建议：** 确认 auth 系统中各 bot 的角色配置。如果角色不是 `"admin"`，建议在 `_cmd_step_complete` 中绕过 `_cmd_task_update` 的权限检查（因为命令本身的 `_admin` 路由和 `workspace_scope` 检查已确保发送者有权限）。

---

### 🟡 W-2: 管线末步关闭工作室时返回值被丢弃

**位置：** handler.py:1036-1042 (`_cmd_step_complete` 末步处理)

**描述：**
当 Step 7 完成触发管线结束时：

```python
await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})
set_lobby_paused(False)
_clear_pipeline_state(round_name)
return (
    f"🏁 **{round_name} 管线已完成！**\n"
    ...
)
```

`_cmd_close_workspace` 的返回值（字符串）被完全丢弃。如果关闭失败（如权限不足：非工作区管理员的 qa-bot 完成 Step 6 触发管线结束；或工作室已被手动删除），函数仍会清除管线状态并返回成功消息。实际上工作室未被关闭，大厅也未被恢复。

**修复建议：**
```python
close_result = await _cmd_close_workspace(sender_id, {"_positional": [ws_id]})
if "❌" in str(close_result):
    return f"❌ 管线关闭失败，请手动处理：\n{close_result}"
```

---

### 🟢 代码质量观察

| 观察项 | 说明 |
|:-------|:------|
| 大厅拦截器位置 | 正确放置在 `_can_broadcast` 权限检查之后、工作区路由 (channel-scoped routing) 之前。与技术方案一致 |
| `_cmd_create_workspace` 自动设置频道 | `persistence.set_agent_channel(sender_id, ws_id)` (handler.py:426) 确保 `_cmd_pipeline_start` 后续调用 `_cmd_rollcall_next` 时能正确获取工作区频道 |
| 非 `_admin` 频道拒绝 `!pipeline_start` | `workspace_scope: False` 确保只在 `_admin` 频道触发；且 admin 命令路由 (handler.py:1334) 也做了频道检查 |
| 状态变量均为模块级内存变量 | `_PIPELINE_STATE`, `_LOBBY_PAUSED` — 重启后丢失，符合 D-6 设计（重启天然恢复） |
| Step 映射表配置化 | `config.PIPELINE_STEP_MAP` + 环境变量覆盖 (handler.py:861): 与技术方案一致 |
| `--from <step>` 参数支持 | 可指定起始 Step（默认 step3），支持灵活启动点 |
| 评论缩进漂移 | handler.py:1405 `# ── R42 D: Lobby pause intercept ──` 注释在 8 格缩进位置（位于 `if not allowed:` 块内 `return` 之后），属于死代码区域，无功能影响。可考虑移到正确缩进处。 |

---

## 4. 安全/遗留物检查

| 检查项 | 状态 | 说明 |
|:-------|:----:|:------|
| 硬编码敏感信息 | ✅ | 无 |
| 调试日志/print | ✅ | 使用 `logger.info()` 标准日志 |
| 权限校验遗漏 | ✅ | `_admin` 频道路由 + `_check_command_permission` 双保险 |
| TODO/FIXME 残留 | ✅ | 无 |
| XSS 风险 | ✅ | 纯服务端代码，不涉及 Web 渲染 |

---

## 5. 验证命令执行结果

```bash
# 语法检查
$ python3 -c "compile(open('server/handler.py').read(),'handler.py','exec'); print('OK')"
OK

$ python3 -c "compile(open('server/config.py').read(),'config.py','exec'); print('OK')"
OK

# AST 无错误
$ python3 -c "import ast; ast.parse(open('server/handler.py').read()); print('AST OK')"
AST OK

# 配置模块导入
$ python3 -c "from server import config; print(list(config.PIPELINE_STEP_MAP.keys()))"
['step1', 'step2', 'step3', 'step4', 'step5', 'step6', 'step7']

# 双入口确认
$ grep -n 'pipeline_start\|pipeline_status\|step_complete' server/__main__.py
(无输出) ✅ 不存在——无双入口问题
```

---

## 6. 总结

| 层级 | 发现 | 退回给 |
|:-----|:-----|:------:|
| 🔴 F-1 | `!pipeline_start` 权限 `workspace_scope=False` + `min_role=3` 配置不被 `_check_command_permission` 支持 | 💻 爱泰 |
| 🟡 W-1 | `_cmd_task_update` 的 `assigned_role` 权限检查可能与 R42 Task 的 `role` 字段不匹配 | 💻 爱泰（确认） |
| 🟡 W-2 | 管线末步 `_cmd_close_workspace` 返回值被丢弃 | 💻 爱泰 |

**修复建议优先级：** F-1 为阻塞项 → 修复后进入 Step 6 测试验证
