# R44 技术方案 — PM 管线入口 + 工作区自动组建

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-27
> **需求来源：** TODO.md F-12（PM 无法直接触发管线入口）、F-13（`!pipeline_start` 创建的工作室没有开发成员）
> **调研报告：** [R44-investigation-report.md](R44-investigation-report.md)（572 行，含完整调用链分析）
> **目标文件：** `server/handler.py`

---

## 目录

- [1. 问题综述](#1-问题综述)
- [2. 方案选型：三种路由方案论证](#2-方案选型三种路由方案论证)
  - [方案 A：`_admin` 频道准入降级（推荐）](#方案-a_admin-频道准入降级推荐)
  - [方案 B：Lobby 命令代理桥接](#方案-blobby-命令代理桥接)
  - [方案 C：Gateway 插件层拦截](#方案-cgateway-插件层拦截)
- [3. 推荐方案及理由](#3-推荐方案及理由)
- [4. 详细设计](#4-详细设计)
  - [4.1 方向 A：PM 管线入口（F-12）](#41-方向-apm-管线入口f-12)
  - [4.2 方向 B：工作区自动组建（F-13）](#42-方向-b工作区自动组建f-13)
- [5. 改动范围与行数预估](#5-改动范围与行数预估)
- [6. 风险分析与缓解措施](#6-风险分析与缓解措施)
- [7. 验收标准映射](#7-验收标准映射)
- [8. 向后兼容性分析](#8-向后兼容性分析)

---

## 1. 问题综述

### 1.1 已知的两个 Bug

| # | 问题 | 严重度 | 当前表现 |
|:-:|:-----|:-----:|:---------|
| **F-12** | PM（member/P1）无法直接触发 `!pipeline_start` | 🟡 P2 | PM 在 TG DM 发出命令 → 卡在 `_can_broadcast()` 的 `_admin` 频道拦截（需 P3+）→ 只能通过 code 块转发给小爱代执行 |
| **F-13** | `!pipeline_start` 创建的工作室无开发成员 | 🟡 P2 | 命令内部调用 `_cmd_create_workspace` 时不传 `--members` → 工区内只有管路启动者一人 → 点名下一角色时 `ws_obj.members` 不匹配 → 静默失败 |

### 1.2 调用链现状

```
PM TG DM → Hermes Gateway → handle_broadcast()
  ├── channel = msg.get("channel") → "_admin"
  ├── _can_broadcast()
  │     └── channel == ADMIN_CHANNEL → 仅 P3/P4 允许 → ❌ PM 被拦
  └── [如果通过] _check_command_permission("pipeline_start")
        └── min_role=3, workspace_scope=False → _is_any_workspace_admin() → ❌ PM 不满足
```

### 1.3 已有基础

| 已有能力 | 位置 | 说明 |
|:---------|:----:|:------|
| `_ADMIN_COMMANDS` 命令注册表 | handler.py:1388-1397 | `pipeline_start` 已注册，`min_role=3` |
| `_can_broadcast()` 频道准入 | handler.py:2331-2368 | `_admin` 频道仅 P3+ |
| `_check_command_permission()` 命令权限 | handler.py:382-404 | P3+ 检查 |
| `_cmd_create_workspace()` | handler.py:410-441 | 接受 `--members` 参数 |
| `_cmd_pipeline_start()` | handler.py:1075-1145 | 内部调用 `_cmd_create_workspace` 无 `--members` |
| `_cmd_rollcall_next()` | handler.py:791-834 | 点名前搜索 `ws_obj.members` |

---

## 2. 方案选型：三种路由方案论证

### 方案 A：`_admin` 频道准入降级（推荐）

**核心思路：** 不改变 `!pipeline_start` 的 `_admin` 频道入口，而是对 `pipeline_start` 这一个命令**放宽 `_admin` 频道准入**，使其允许 P1（member）级别的 PM 角色进入并执行。

#### 实现方式

两处改动：

**① `_can_broadcast()` — 增加 `pipeline_start` 例外（handler.py:2340）**

```python
if channel == p.ADMIN_CHANNEL:
    if auth.is_global_admin(agent_id):
        return True, ""
    if _is_any_workspace_admin(agent_id):
        return True, ""
    # ── R44 F-12: Allow PM to access _admin for pipeline_start ──
    # PM sends !pipeline_start from TG DM → lands in _admin channel.
    # Allow broadcast but command permission check (step 2) still applies.
    # We handle the permission flow in _check_command_permission instead.
    return True, ""  # Allow broadcast; permission enforced at command level
```

> **为什么可以放行？** `_admin` 频道拦截在 `_check_command_permission()` 之前。这里放行只会让 PM 看到命令分发界面（可用命令列表），`!pipeline_start` 之外的其他命令仍然会被 `_check_command_permission` 拦截。

**② `_check_command_permission()` — 对 `pipeline_start` 降级为 P1**（handler.py:382）

方案 A 有两种子选择：

| 子方案 | 实现 | 风险 |
|:------|:-----|:----:|
| **A1** 新增 `min_role_pm: int` 字段 | 在 `_ADMIN_COMMANDS` 中给 `pipeline_start` 加 `min_role_pm: 1`，`_check_command_permission` 检测 PM 角色 + 命令特殊标记 | 改动量适中 |
| **A2** 白名单 + P1 降级 | 在 `_check_command_permission` 中检查命令名是否为 `pipeline_start`，若是，允许 P1 通过 | 改动最小，硬编码一条 |

推荐 **A2**（改动最小，1 个 if 分支）：

```python
# ── R44 F-12: PM pipeline_start bypass ──
if cmd_name == "pipeline_start" and min_role <= 3:
    # Allow member-level PM to trigger pipeline start
    return True, ""
```

**原理：** `!pipeline_start` 本身是安全的——它只启动管线，不删除数据、不改权限、不关工作室。放开给 PM 的风险可控。

#### 优缺点

| 维度 | 评价 |
|:-----|:-----|
| ✅ 代码改动量 | **极小** — 2 个位置，~5 行 |
| ✅ 不涉及 Gateway 插件 | 纯 server 端改动，零部署依赖性 |
| ✅ 向后兼容 | 不影响已有 P3+ 管理员的权限行为 |
| ✅ 入侵性 | 最低——不改入口架构，不改消息类型 |
| ⚠️ `_admin` 频道入口放开 | 非 PM 的 member 也能进 `_admin`，但仅有 `!pipeline_start` 可用 |
| ⚠️ 安全性 | 仅放宽 1 个命令的权限，不影响其他管理命令 |

---

### 方案 B：Lobby 命令代理桥接

**核心思路：** 在 lobby 频道消息路径上加一条特殊路由：检测到 `!pipeline_start` 开头的内容时，不按普通 lobby 消息处理，而是直接转发到 `_cmd_pipeline_start` 执行。

#### 实现方式

在 `handle_broadcast()` 的 lobby 分支前（handler.py:1531 附近）增加：

```python
# ── R44 F-12: PM pipeline_start from lobby ──
if content.startswith("!pipeline_start"):
    if channel == p.ADMIN_CHANNEL:
        pass  # Already handled below
    else:
        # Relay to admin channel context for execution
        cmd_name, params = _parse_command(content)
        if cmd_name == "pipeline_start":
            allowed, reason = _check_command_permission(
                sender_id, cmd_name, _ADMIN_COMMANDS[cmd_name], params
            )
            if not allowed:
                await _send(ws, {"type": "error", "error": f"❌ {reason}"})
                return
            result = await _cmd_pipeline_start(sender_id, params)
            await _send(ws, {"type": "ack", "content": result})
            return
```

#### 优缺点

| 维度 | 评价 |
|:-----|:-----|
| ❌ 消息模型混乱 | Lobby 是公告/点名/求助频道，混入 `!` 命令破坏语义 |
| ❌ `_can_broadcast` 仍需放行 | 即使绕过频道检查，命令仍受 lobby 前缀分类限制 |
| ❌ Lobby 暂停冲突 | 管线启动后 `_LOBBY_PAUSED` 暂停大厅，PM 在大厅发命令可能被 R42 大厅暂停拦截（handler.py:1603） |
| ✅ 不调整 `_admin` 准入 | 保持管理频道纯粹性 |
| ⚠️ TG DM 映射依赖 | PM 的 TG DM 实际已映射到 `_admin`（`ws_bridge_group`），进入 lobby 需要额外配置 |

**结论：** 方案 B 引入的消息模型冲突多于解决的问题，不推荐。

---

### 方案 C：Gateway 插件层拦截

**核心思路：** 在 Hermes Gateway 的 `WSBridgeAdapter` 插件层中，对 PM 发出的 `!pipeline_start` 消息进行预处理：在消息到达 `handle_broadcast()` 之前，将 channel 强制设置为 `_admin` 且标记为来自已认证 PM。

#### 实现方式

在 `gateway-plugin/` 的 `_process_inbound_message()` 或预处理 hook 中：

```python
# ── R44 F-12: Gateway-level pipeline_start relay ──
if content.strip().startswith("!pipeline_start"):
    # Re-route to _admin channel
    msg["channel"] = "_admin"
    msg["_bypass_permission"] = True  # 或直接标记 sender 为临时 admin
```

#### 优缺点

| 维度 | 评价 |
|:-----|:-----|
| ❌ 部署耦合 | Gateway 插件需要重启服务端，无法独立部署 |
| ❌ 代码路径分散 | 逻辑跨 `gateway-plugin/` + `server/handler.py`，审查/维护成本高 |
| ❌ 强行覆写 channel | 如果 PM 的 agent_id 不是 `_admin` 频道成员，`_can_broadcast` 仍然会拦截 |
| ✅ 消息路径清晰 | 在入口层就完成了路由修正 |
| ⚠️ R43 看门狗耦合 | Gateway 插件改动需要同步看门狗测试 |

**结论：** 方案 C 引入跨层依赖，不够纯粹。对于 P2 严重度的问题，应该选择最简洁的方案。

---

## 3. 推荐方案及理由

### 🏆 推荐方案 A（`_admin` 频道准入降级）

| 维度 | 方案 A | 方案 B | 方案 C |
|:-----|:------:|:------:|:------:|
| 改动文件数 | 1（`handler.py`） | 1（`handler.py`） | 2（`handler.py` + `gateway-plugin/`）|
| 新增代码行 | ~10 行 | ~30 行 | ~20 + ~20 行 |
| 入侵性 | ⭐ 最低 | ⭐⭐ 中 | ⭐⭐⭐ 高 |
| 向后兼容 | ✅ 完全 | ⚠️ 可能 | ✅ 完全 |
| 测试覆盖 | ✅ 单元测试足矣 | ⚠️ 需集成测试 | ⚠️ 需端到端测试 |

**核心理由：**

1. **改动最小** — 2 处共 ~10 行代码，全部在 `handler.py` 中
2. **无部署依赖** — 不需要改 Gateway 插件，不需要重启网关
3. **安全可控** — 仅对 `!pipeline_start` 这一个命令降级，其他 `_admin` 命令不受影响
4. **符合 PM 当前工作流** — PM 已经在 TG DM 中发消息，消息已到达 `_admin` 频道，只是被拦截了。放开准入就解决了
5. **风险最低** — 不改变入口架构、不新增消息类型、不改协议

### 方案 A 的两个子方案对比

| 子方案 | 实现复杂度 | 扩展性 |
|:------|:---------:|:-------|
| **A1** — 新增 `min_role_pm` 字段 | 需要改命令注册表 + 权限检查逻辑，~15 行 | 好——未来任何命令都可以复用此机制 |
| **A2** — 白名单硬编码 | 1 个 if 分支，~3 行 | 差——仅供 `pipeline_start` 专用 |

推荐 **A2（白名单硬编码）**。原因是：
- F-12 是一个具体的、孤立的 Bug，不需要为它建一个通用框架
- 未来如有其他命令需要降级（目前无预期），届时再提取为通用字段
- YAGNI — 不做预期之外的设计

### F-13 解决方案

F-13 与方案选择无关，独立修复：

- 在 `_cmd_pipeline_start` 中，创建工作室前先收集 `PIPELINE_STEP_MAP` 中所有角色对应的 agent_id
- 将这些 agent_id 作为 `--members` 参数传递给 `_cmd_create_workspace`
- 同时将默认 `start_step` 从 `"step3"` 改为 `"step2"`（使管线正常从技术方案开始）

---

## 4. 详细设计

### 4.1 方向 A：PM 管线入口（F-12）

#### 改动点 1：`_can_broadcast()` — `_admin` 频道放开（handler.py:2340）

**当前代码：**

```python
if channel == p.ADMIN_CHANNEL:
    if auth.is_global_admin(agent_id):
        return True, ""
    if _is_any_workspace_admin(agent_id):
        return True, ""
    users = auth.get_users()
    name = users.get(agent_id, {}).get("name", agent_id[:12])
    return False, f"{name} 无权访问管理频道"
```

**修改后：**

```python
if channel == p.ADMIN_CHANNEL:
    if auth.is_global_admin(agent_id):
        return True, ""
    if _is_any_workspace_admin(agent_id):
        return True, ""
    # ── R44 F-12: Allow PM broadcast access to _admin channel ──
    # Pipeline_start is the only command available to members.
    # Command-level permission check (_check_command_permission)
    # still enforces that only !pipeline_start is allowed.
    return True, ""
```

> **重要：** 此处放行后，所有 member 都能进入 `_admin` 频道。命令级权限检查是第二道防线——只有 `!pipeline_start` 会通过。其他命令（`!close_workspace`、`!approve` 等）仍然被拦截。

#### 改动点 2：`_check_command_permission()` — `pipeline_start` 降级（handler.py:382）

**当前代码：**

```python
def _check_command_permission(
    agent_id: str, cmd_name: str, cmd: dict, params: dict,
) -> tuple[bool, str]:
    # P4 → always allowed
    if auth.is_global_admin(agent_id):
        return True, ""

    min_role = cmd.get("min_role", 4)
    ws_scope = cmd.get("workspace_scope", False)

    # P3: verify actual workspace admin before allowing ws_scope commands
    if min_role <= 3 and ws_scope:
        ...
```

**修改后（在 P4 检查后，min_role 判断前插入）：**

```python
    # P4 → always allowed
    if auth.is_global_admin(agent_id):
        return True, ""

    min_role = cmd.get("min_role", 4)
    ws_scope = cmd.get("workspace_scope", False)

    # ── R44 F-12: PM pipeline_start bypass ────────────────
    # Allow any authenticated member to trigger !pipeline_start
    # from the _admin channel. Only this one command is exempted.
    if cmd_name == "pipeline_start" and min_role <= 3:
        return True, ""

    # P3: verify actual workspace admin before allowing ws_scope commands
    ...
```

**预期的效果：**

| 用户角色 | `_admin` 频道可执行命令 |
|:---------|:------------------------|
| P4 全局管理员 | 全部（不变）|
| P3 工作区管理员 | 全部（不变）|
| P1/P2 member（PM） | **仅 `!pipeline_start`**（新增）|

#### 全景调用链（修改后）

```
PM TG DM → Hermes Gateway → handle_broadcast()
  ├── channel = "_admin"
  ├── _can_broadcast() → ✅ 通过（R44 放开）
  ├── ! 命令解析 → cmd_name = "pipeline_start"
  ├── _check_command_permission()
  │     └── cmd_name == "pipeline_start" → ✅ 通过（R44 降级）
  ├── _cmd_pipeline_start(sender_id, params)
  └── 返回结果 → ack 回 TG DM
```

### 4.2 方向 B：工作区自动组建（F-13）

#### 改动点 3：`_cmd_pipeline_start()` — 自动收集角色成员 + 修复默认 Step（handler.py:1075）

**当前代码问题：**

```python
# Line 1100-1103
create_params = {
    "_positional": [f"{round_name}-dev"],
}
create_result = await _cmd_create_workspace(sender_id, create_params)
# → 无 --members → 工区内只有 sender 一人

# Line 1110
start_step = from_step if from_step else "step3"
# → 默认从 step3 开始，跳过 step2 技术方案
```

**修改后：**

```python
# 查 Step 映射表，收集所有需要加入的角色
step_config = _load_step_config()
all_roles = set()
for step_key, step_cfg in step_config.items():
    role = step_cfg.get("role", "")
    if role and step_key != "step1":  # step1 admin 已作为 owner
        all_roles.add(role)

# 从 auth 用户表中查找各角色的 agent_id
users = auth.get_users()
member_ids = []
for aid, u in users.items():
    if u.get("role", "member") in all_roles:
        member_ids.append(aid)

# ── R44 F-13: Auto-populate workspace members ──
create_params = {
    "_positional": [f"{round_name}-dev"],
    "members": ",".join(member_ids),
}
create_result = await _cmd_create_workspace(sender_id, create_params)

# ── R44 F-13: Fix default start step ──
start_step = from_step if from_step else "step2"
```

**行为变化：**

| 场景 | 修改前 | 修改后 |
|:-----|:-------|:-------|
| 无 `--from` 参数 | 从 step3（编码）开始 | 从 step2（技术方案）开始 |
| 工作室成员 | 仅管线启动者一人 | 所有管线角色对应的 agent |
| 点名下一角色 | `ws_obj.members` 无匹配 → 静默失败 | 角色成员已在工区 → 点名正常 |

**成员选择逻辑：**

```
PIPELINE_STEP_MAP:
  step1: admin (owner = pipeline starter)
  step2: arch  ←
  step3: dev   ←  加入工作室成员
  step4: review←
  step5: qa    ←
  step6: admin (same as step1)

→ 从 auth.get_users() 中筛选 role=arch|dev|review|qa 的 agent
→ 排除 step1/starter agent（已是 owner/自动 admin）
→ 不重复添加
```

---

## 5. 改动范围与行数预估

### 总体统计

| 文件 | 操作 | 新增行 | 修改行 | 说明 |
|:-----|:----|:------:|:------:|:-----|
| `server/handler.py` | 🔄 修改 | ~10 | ~15 | 3 处改动点 |

**总计：约 25 行新增/修改代码**

### 详细改动清单

| # | 位置（行号） | 改动 | 类型 | 行数 |
|:-:|:------------|:-----|:----:|:----:|
| 1 | `_can_broadcast()` ~L2347 | 放开 `_admin` 频道准入——将 return False 改为 return True | 修改现有行 | 1 |
| 2 | `_check_command_permission()` ~L393 | 插入 `cmd_name == "pipeline_start"` 白名单分支 | 新增 | 3 |
| 3 | `_cmd_pipeline_start()` ~L1100 | 改为传递 `members` 参数，收集各角色 agent_id | 修改 | 8 |
| 4 | `_cmd_pipeline_start()` ~L1110 | 默认 `start_step` 从 `"step3"` 改为 `"step2"` | 修改 | 1 |
| — | 注释 + docstring | 补充 R44 改动注释 | 新增 | 3 |

### 不涉及的文件

| 文件 | 原因 |
|:-----|:------|
| `server/config.py` | 无新增配置项 |
| `server/auth.py` | 权限降级在 handler 层硬编码，不侵入 auth 系统 |
| `server/workspace.py` | `add_member` API 已存在，调用方式不变 |
| `gateway-plugin/` | 不改 Gateway 层 |
| `shared/protocol.py` | 无新消息类型 |

---

## 6. 风险分析与缓解措施

### 风险 R1：`_admin` 频道对所有 member 放开

| 维度 | 评估 |
|:-----|:------|
| **风险等级** | 🟡 P2 |
| **描述** | `_can_broadcast()` 放开后，所有 member 角色都能进入 `_admin` 频道发消息 |
| **影响** | 非 PM 的 member 也能看到 `_admin` 频道内容（命令提示等），但只能执行 `!pipeline_start` |
| **缓解措施** | 1) 命令级权限检查 `_check_command_permission` 是第二道防线——非 `pipeline_start` 命令会被拦截<br>2) 纯文本消息（不以 `!` 开头）会被 `_admin` 频道逻辑拒绝（handler.py:1546 `if not content.startswith("!"):`）<br>3) 当前只有受信任的 agent（各 bot）连接 ws-bridge，不存在「恶意用户」场景 |
| **验收条件** | P1 member 执行 `!close_workspace` → ❌ 权限不足 |

### 风险 R2：`!pipeline_start` 被非 PM 滥用

| 维度 | 评估 |
|:-----|:------|
| **风险等级** | 🟢 P3 |
| **描述** | 任何 member 都可以启动管线 |
| **影响** | 管线启动需要 `WORK_PLAN.md` 存在（handler.py:1089-1091），不会凭空创建。额外启动只是多一个工作室 |
| **缓解措施** | 1) 前端最远只有受信 agent，无人能绕过<br>2) WORK_PLAN.md 文件存在检查是安全阀<br>3) 工作室数量有上限（`max_per_person=1`） |
| **验收条件** | P1 非 PM 角色执行 `!pipeline_start R44` → ✅ 启动 |

### 风险 R3：工作区成员过多

| 维度 | 评估 |
|:-----|:------|
| **风险等级** | 🟢 P3 |
| **描述** | 如果某个角色有多名 agent（如多个 dev），所有人都会被加入工作室 |
| **影响** | 点名时所有同角色 agent 都会收到通知，但只有一人回复即可 |
| **缓解措施** | 当前点名机制已支持多人同角色场景——`_cmd_rollcall_next` 会通知所有匹配的 agent。这是已有行为，不是新问题 |
| **验收条件** | 同一 role 多名 agent 时工作室包含所有人 |

### 风险 R4：`!pipeline_start` 从 step2 开始，旧脚本依赖 step3

| 维度 | 评估 |
|:-----|:------|
| **风险等级** | 🟢 P3 |
| **描述** | 外部工作流显式传 `--from step3` 的会继续使用旧行为。`!pipeline_start` 无参数时默认从 step2 开始 |
| **影响** | 仅影响无 `--from` 的调用方 |
| **缓解措施** | 加入 R44 时更新 `docs/WORKFLOW.md` 中的默认行为描述 |

---

## 7. 验收标准映射

### 方向 A：PM 管线入口（F-12）

| # | 验收项 | 优先级 | 验证方式 | 预期 |
|:-:|:-------|:------:|:---------|:-----|
| A-1 | P1（member/PM）在 `_admin` 频道发 `!pipeline_start R44` 可执行 | 🔴 P1 | 模拟 PM agent 连接 → 发命令 | ✅ 返回管线启动成功 |
| A-2 | P1（member）在 `_admin` 频道发 `!close_workspace` 被拒绝 | 🔴 P1 | 同上 | ❌ 权限不足 |
| A-3 | P1（member）在 `_admin` 频道发普通文本消息被拒绝 | 🟡 P2 | 同发送非 `!` 开头内容 | ❌ 管理频道仅支持 ! 命令 |
| A-4 | P3+ 管理员权限不受影响 | 🔴 P1 | P3+ 执行 `!pipeline_start` + `!close_workspace` 等 | ✅ 全部正常 |
| A-5 | `!pipeline_start` 前置检查（WORK_PLAN.md 存在）仍然有效 | 🟡 P2 | 对不存在的轮次执行 | ❌ WORK_PLAN.md 未找到 |

### 方向 B：工作区自动组建（F-13）

| # | 验收项 | 优先级 | 验证方式 | 预期 |
|:-:|:-------|:------:|:---------|:-----|
| B-1 | `!pipeline_start` 不带 `--from` 默认从 step2 开始 | 🔴 P1 | 启动后 `!pipeline_status` 查询 | current_step = step2 |
| B-2 | 工作室成员包含 arch/dev/review/qa 角色 agent | 🔴 P1 | `!list_workspaces` 查看成员列表 | 包含各角色 agent |
| B-3 | 工作室成员不包含管线启动者（已是 owner） | 🟡 P2 | 查看工作室详情 | 启动者不在 member_ids 重复列表中 |
| B-4 | `!rollcall_next` 能成功匹配角色进行点名 | 🔴 P1 | 启动后点名 arch | ✅ 找到 arch 并通知 |
| B-5 | 带 `--from step3` 时仍从指定 step 开始 | 🟡 P2 | `!pipeline_start R44 --from step3` | current_step = step3 |

---

## 8. 向后兼容性分析

| 场景 | 兼容性 | 说明 |
|:-----|:------:|:------|
| P3+ 管理员 `!pipeline_start` | ✅ 完全兼容 | 权限检查前置返回 True，不受 R44 改动影响 |
| 已有活跃管线 | ✅ 完全兼容 | `!pipeline_start` 的重复检查（line 1093）不变 |
| 旧 `WORK_PLAN.md` 格式 | ✅ 完全兼容 | 文件存在检查不变 |
| Gateway plugin | ✅ 完全兼容 | 不改 gateway-plugin/ 任何代码 |
| Web 端管理面板 | ✅ 完全兼容 | 不涉及新消息类型 |
| R43 看门狗（`_ensure_watchdog`） | ✅ 完全兼容 | 看门狗启动逻辑不变 |
| `!pipeline_start --from step3` | ✅ 完全兼容 | 显式传参时使用参数值，不降级为 step2 |
| P1 member 其他 `!` 命令 | ✅ 完全兼容 | 只有 `pipeline_start` 有白名单豁免 |
| `_admin` 频道其他 member 消息 | ⚠️ 行为变更 | 之前 member 进 `_admin` 被拦截（返回错误），现在进入后仅 `!pipeline_start` 可通过。其他命令/消息仍被拦截 |

---

> **审核记录：**
> - v1.0 提交方向审查：2026-06-27
> - 方向审查结论：🟢 通过 / 🟡 条件通过 / 🔴 驳回
