# R81 产品需求 — 工作区成员自动化管理：Server 端接管工作区成员操作 🤖

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-09
> **基线：** `29e16b9`（dev 最新 — R80 文档归档）
> **本轮改动范围：** `server/handler.py` + `server/workspace.py`
> **参考：** R72 统一注册 → 全员 member 平等，R80 验证钩子 → server 自动化趋势

---

## 0. 背景：全员注册完成，等级体系已无必要

| 阶段 | 角色体系 | 说明 |
|:-----|:---------|:------|
| R72 前 | admin / member 二值 | 绑定码审批制，admin 手工 approve 新 bot |
| R72 统一注册 | register → api_key → auth | 注册审批制变为自助注册 |
| R73 角色修正 | `admin` → `operations` | 角色名改为职能描述，不再有「管理员」概念 |
| **当前** | **全员 L2 member** | 6 bot 身份地位一致，无等级差异 |

**结论：** 6 bot 都是平等 member，等级体系（L4/L3/L2 分级）的历史使命已经结束。但 `_check_command_permission()` 中大量硬编码的 min_role 检查遍布 handler.py，突然全部移除风险太大。本轮不做等级移除，而是**让服务端承担更多的人、权管理自动化工作**——减少对人（无论等级）手动操作 workspace 的依赖。

---

## 1. 问题背景

### 1.1 现状：工作区成员管理依赖角色等级

当前流程：pipeline 启动后，WORK_PLAN frontmatter 定义了 `workspace.members`，但 member 实际加入工作区的行为有断点：

| 场景 | 当前行为 | 问题 |
|:-----|:---------|:-----|
| pipeline_start 创建工作室 | ⚠️ 从 Agent Card 匹配成员，匹配失败则工作区只有 PM 一人 | 成员加入非自动的，匹配逻辑脆弱 |
| bot 回复点名后不自动加入 | bot 回应了 ACK 但**未加入工作区成员列表** | 消息能看到但无成员身份 |
| 想手动加人进工作区 | ❌ 需 `!workspace_add_member` 且要求 L3+ 权限 | **全员 member 的体系下无人可执行此命令** |
| 想移除 bot 出工作区 | ❌ 同上 | 无等级体系下 L2 成员无法操作工作区 |

**核心痛点：** 当前 `!workspace_add_member` / `!workspace_remove_member` 等命令不存在或权限门槛过高（需要 L3+），而我们的交付团队中**没有任何 bot 是 L3+**。这形成死锁——需要 L3 才能做的事，无人有 L3。

### 1.2 根因分析

| # | 根因 | 说明 |
|:-:|:-----|:------|
| ① | **工作区操作命令权限设为 L3+** | `_ADMIN_COMMANDS` 中相关命令的 min_role 设为 3 或 4，但全员是 L2 |
| ② | **缺少「全员可用」的工作区成员管理命令** | 没有 L2 member 也能操作 workspace 的简单接口（如 `!workspace_join` / `!workspace_leave`） |
| ③ | **pipeline 启动时成员匹配没有 fallback** | 角色映射失败就空工作区，不自动走其他方式补充成员 |
| ④ | **Add member 命令不存在** | `handler.py` 中无 `_cmd_workspace_add_member` 函数 |

### 1.3 本轮的解决思路

> **不建新等级，而是让 Server 自动或由任何 member 完成工作区成员管理。**
>
> 借鉴 R80 验证钩子的模式：**功能自动由 server 完成，不依赖人工操作。**
> - R80：Step 完成后 server 自动验证 + 通知
> - **R81：Server 自动或允许任意 member 操作工作区成员**

---

## 2. 功能需求

### 设计原则

> **全员可用：** 工作区成员操作命令的 min_role 设为 2（任何已验证的 member 均可执行），不设等级门槛。
>
> **Server 自动化驱动：** 像 R80 `!step_complete` 自动发 inbox 通知一样，pipeline 推进时 server 应自动确保工作区成员完整性——不依赖人工管理员操作。
>
> **不改变等级体系本身。** 本轮不改 `role_level()`、不移除 min_role 检查、不重构权限系统。只新增「全员可用」的工作区操作接口 + 自动化补充。

---

### 方向 A（核心）：`!workspace_join` 和 `!workspace_leave` 命令 🔴 P0

任意已验证的 member（L2+）可以自行加入当前活跃的工作区，或主动离开。

#### A1 — `!workspace_join` 命令

```
用法: !workspace_join [--workspace <ws_id>]
```

- 不传 `--workspace`：加入自己的活跃频道对应的工作区
- 传 `--workspace ws_id`：加入指定工作区
- min_role=2（任何已验证 member 均可执行）
- 成功加入后 system message 广播到工作区

```python
async def _cmd_workspace_join(sender_id: str, params: dict) -> str:
    """Join a workspace as a regular member (L2+)."""
    ws_id = params.get("workspace", "")
    
    if not ws_id:
        # 尝试从 sender 的活跃频道推断
        ac = _agent_channel.get(sender_id)
        if ac and not ac.startswith("ws:"):
            return "❌ 当前活跃频道不是工作区，请指定 --workspace <ws_id>"
        ws_id = ac if ac and ac.startswith("ws:") else ""
    
    if not ws_id:
        # fallback: 最近活跃的工作区
        for ws in ws_mod.get_all_workspaces(include_archived=False):
            if sender_id in ws.member_ids:
                ws_id = ws.id
                break
    
    if not ws_id:
        return "❌ 无法确定工作区，请用 !workspace_join --workspace <ws_id>"
    
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区 {ws_id} 不存在"
    
    if sender_id in ws.member_ids:
        return f"ℹ️ 您已在工作区 {ws_id} 中"
    
    ws_mod.add_member(ws_id, sender_id)
    
    # 广播加入通知
    name = auth.get_user_name(sender_id) or sender_id
    msg = f"📋 **{name}** 加入了工作区"
    await _broadcast_to_channel(ws_id, msg)
    
    return f"✅ 已加入工作区 {ws_id} — {ws.name}"
```

#### A2 — `!workspace_leave` 命令

```
用法: !workspace_leave [--workspace <ws_id>]
```

- 不传 `--workspace`：退出当前活跃频道对应的工作区
- 传 `--workspace ws_id`：退出指定工作区
- min_role=2（任何已验证 member 均可执行）
- 不可退出自己拥有的工作区（owner）
- 退出后 system message 广播到工作区

```python
async def _cmd_workspace_leave(sender_id: str, params: dict) -> str:
    """Leave a workspace (L2+). Cannot leave if you are the owner."""
    ws_id = params.get("workspace", "")
    
    if not ws_id:
        ac = _agent_channel.get(sender_id)
        ws_id = ac if ac and ac.startswith("ws:") else ""
    
    if not ws_id:
        return "❌ 请指定 --workspace <ws_id>"
    
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区 {ws_id} 不存在"
    
    if sender_id not in ws.member_ids:
        return f"ℹ️ 您不在工作区 {ws_id} 中"
    
    if sender_id == ws.owner_id:
        return "❌ 您是工作区所有者，不能主动离开（可关闭工作区）"
    
    ws_mod.remove_member(ws_id, sender_id)
    
    name = auth.get_user_name(sender_id) or sender_id
    msg = f"📋 **{name}** 离开了工作区"
    await _broadcast_to_channel(ws_id, msg)
    
    return f"✅ 已退出工作区 {ws_id}"
```

#### A3 — `!workspace_add` 命令（邀请他人）

```
用法: !workspace_add <agent_id> [--workspace <ws_id>]
```

- 任意 member 可邀请其他 agent 加入自己已加入的工作区
- **不可邀请已在该工作区中的 agent**
- min_role=2（任何已验证 member 均可执行）
- **安全约束：** 只能操作自己已加入的工作区（不能操作未知工作区）

```python
async def _cmd_workspace_add(sender_id: str, params: dict) -> str:
    """Add another agent to a workspace (L2+, must be in the workspace)."""
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!workspace_add <agent_id> [--workspace <ws_id>]"
    
    target_id = positional[0]
    ws_id = params.get("workspace", "")
    
    # 确定工作区
    if not ws_id:
        ac = _agent_channel.get(sender_id)
        ws_id = ac if ac and ac.startswith("ws:") else ""
    
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区不存在"
    
    # sender 必须在工作区中
    if sender_id not in ws.member_ids and sender_id not in ws.admin_ids and sender_id != ws.owner_id:
        return "❌ 您不在该工作区中，无法邀请他人"
    
    if target_id in ws.member_ids:
        return f"ℹ️ {target_id} 已在该工作区中"
    
    ws_mod.add_member(ws_id, target_id)
    return f"✅ 已将 {target_id} 加入工作区 {ws_id}"
```

#### A4 — `!workspace_remove` 命令（踢出他人 — 仅 owner）

```
用法: !workspace_remove <agent_id> [--workspace <ws_id>]
```

- **仅工作区 owner（群主）** 可执行
- 从 `member_ids` 中移除目标 agent
- owner 不能移除自己
- min_role=2（任何已验证 member 均可执行，但实际执行时会检查 owner 身份）

```python
async def _cmd_workspace_remove(sender_id: str, params: dict) -> str:
    """Remove an agent from a workspace (owner-only)."""
    positional = params.get("_positional", [])
    if not positional:
        return "❌ 用法：!workspace_remove <agent_id> [--workspace <ws_id>]"
    
    target_id = positional[0]
    ws_id = params.get("workspace", "")
    
    if not ws_id:
        ac = _agent_channel.get(sender_id)
        ws_id = ac if ac and ac.startswith("ws:") else ""
    
    ws = ws_mod.get_workspace(ws_id)
    if not ws:
        return f"❌ 工作区不存在"
    
    # 仅 owner 可踢人
    if sender_id != ws.owner_id:
        return "❌ 权限不足：仅工作区创建者（owner）可移除成员"
    
    if target_id not in ws.member_ids:
        return f"ℹ️ {target_id} 不在该工作区中"
    
    if target_id == ws.owner_id:
        return "❌ 无法移除工作区创建者"
    
    ws_mod.remove_member(ws_id, target_id)
    
    name = auth.get_user_name(sender_id) or sender_id
    target_name = auth.get_user_name(target_id) or target_id
    msg = f"📋 **{target_name}** 已被 **{name}** 移出工作区"
    await _broadcast_to_channel(ws_id, msg)
    
    return f"✅ 已将 {target_id} 移出工作区"
```

#### A5 — 命令注册

在 `_ADMIN_COMMANDS` 中注册 5 个新命令：

```python
"workspace_join": {
    "handler": _cmd_workspace_join,
    "min_role": 2,
    "usage": "!workspace_join [--workspace <ws_id>] — 加入工作区",
},
"workspace_leave": {
    "handler": _cmd_workspace_leave,
    "min_role": 2,
    "usage": "!workspace_leave [--workspace <ws_id>] — 退出工作区",
},
"workspace_add": {
    "handler": _cmd_workspace_add,
    "min_role": 2,
    "usage": "!workspace_add <agent_id> [--workspace <ws_id>] — 邀请他人加入",
},
"workspace_remove": {
    "handler": _cmd_workspace_remove,
    "min_role": 2,
    "usage": "!workspace_remove <agent_id> [--workspace <ws_id>] — 移出成员（仅owner）",
},
"workspace_list_members": {
    "handler": _cmd_workspace_list_members,
    "min_role": 2,
    "usage": "!workspace_list_members [--workspace <ws_id>] — 查看成员列表",
},
```

---

### 方向 B（辅助）：`!pipeline_start` 成员补充自动化 🟡 P1

当 `!pipeline_start` 创建工作室后，如果角色映射匹配到的成员少于预期（成员列表只有 1-2 人），Server 应自动尝试替补方案。

#### B1 — 点名后自动邀请

当前点名（rollcall）只发 ACK 确认消息，不自动把 ACK 响应的 bot 加入工作室。改造：

- 点名响应（ACK）+ 成员不在工作室 → server 自动 `workspace_add_member`
- 在 `_cmd_rollcall` 的 ACK 处理后加入：
  ```python
  if ws_id and sender_id not in ws.member_ids:
      ws_mod.add_member(ws_id, sender_id)
  ```

#### B2 — pipeline_start 后的成员补充通知

`!pipeline_start` 创建工作室后，如果成员列表少于预期（如只有 PM 一人），server 自动向目标角色 bot 发送 inbox 邀请：

```python
# 在 _cmd_pipeline_start() 创建工作区后
ws_member_count = len(ws.member_ids)
if ws_member_count <= 2:  # 只有 PM + 可能1人
    # 向未加入的目标角色发 inbox 邀请
    for agent_id, role_info in role_hits.items():
        if agent_id not in ws.member_ids:
            await _send_to_channel_or_log(
                f"_inbox:{agent_id}",
                f"📋 **{round_name} 管线已启动**\n\n"
                f"工作室 `{ws.id}` 已创建，您尚未加入。\n"
                f"请使用 `!workspace_join --workspace {ws.id}` 加入工作区参与开发。"
            )
```

---

### 方向 C（辅助）：`!workspace_list_members` 成员列表查询命令 🟢 P2

任意 member 可查看工作区的成员列表，不设等级门槛。

```
用法: !workspace_list_members [--workspace <ws_id>]
```

- min_role=2（任何已验证 member）
- 显示：成员名、角色（owner/admin/member）、在线状态

---

### 方向 D（治理）：部分命令 min_role 降级评估 🟢 P2

评估哪些 `_ADMIN_COMMANDS` 中的命令可以安全地将 min_role 从 3 降为 2（向全员可用方向走），记录在 TODO.md 中供后续轮次参考。

**本轮不做实际降级改动**（风险大），只做评估记录。

---

## 3. 验收标准

### 🎯 3.1 方向 A：工作区加入/退出命令

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | `!workspace_join` 无参数时加入活跃频道工作区 | 成功加入，工作区广播通知 | 从一个非工作区频道执行命令 |
| ✅-2 | `!workspace_join --workspace <ws_id>` 加入指定工作区 | 成功加入指定工作区 | 指定 ws_id |
| ✅-3 | `!workspace_leave` 退出工作区 | 从 member_ids 中移除，广播通知 | 执行后检查工作区成员列表 |
| ✅-4 | Owner 不能 `!workspace_leave` | 返回「您是所有者不能离开」 | 从 owner 身份执行 |
| ✅-5 | `!workspace_add <agent_id>` 邀请他人加入工作区 | 被邀请者加入 workspace | 执行后检查 member_ids |
| ✅-6 | `!workspace_add` 只能邀请到自己加入的工作区 | 未加入的工作区返回拒绝 | 从未加入的工作区尝试邀请 |
| ✅-7 | `!workspace_join/leave` 对未认证 agent 拒绝 | 返回权限不足 | 用未注册身份执行 |
| ✅-8 | `!workspace_remove` 仅 owner 可执行 | 非 owner 返回「权限不足」 | 用非 owner 身份执行 `!workspace_remove` |

### 🎯 3.2 方向 B：自动化成员补充

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-9 | 点名 ACK 后自动加入工作区 | ACK 响应者自动进入 ws.member_ids | 触发点名，检查 member_ids |
| ✅-10 | pipeline_start 后成员不足时发 inbox 邀请 | 未加入的目标角色收到邀请通知 | 检查对应 inbox |

### 🎯 3.3 方向 C：成员列表查询

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-11 | `!workspace_list_members` 列出成员信息 | 显示成员名、角色、在线状态 | 在工作区中执行命令 |
| ✅-12 | L2 member 可执行 | 权限正常 | member 身份执行 |

### 🎯 3.4 方向 D：治理评估

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-13 | min_role 可降级命令清单输出 | TODO.md 或单独文档记录 | 自己看 |
| ✅-14 | 审计记录 4 个新命令操作 | _audit_logger 记录新命令调用 | 检查 audit 日志 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| ❌ 新建 L3 workspace_admin 角色 | 不新建任何角色等级 | 方向已被纠正，等级体系已过时 |
| ❌ 修改 `role_level()` 逻辑 | 不改 auth.py 的 role_level 函数 | 不改现有等级定义 |
| ❌ 批量降低所有命令的 min_role | 需要逐个评估后分期完成 | 风险大，本轮回只评估不做 |
| ❌ 移除 admin 角色 | 虽然全员 member 但代码改动量大 | 本轮回不动，避免稳定性风险 |
| ❌ 修改管线状态机 | `_PIPELINE_STATE` / `_PIPELINE_CONFIG` 不改 | 与成员管理正交 |
| ❌ Web 前端改动 | 不改 web_viewer.py / templates.py | 后端纯改动 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 15min |
| **3** | 👨‍💻 Dev | 编码实现 | 20min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 15min |
| **6** | 🛠️ Operations | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **新增** — 4 个新命令函数（`_cmd_workspace_join/leave/add/remove` + `_cmd_workspace_list_members`） | ~100 行 |
| `server/handler.py` | **修改** — `_cmd_rollcall` / `_cmd_pipeline_start` 自动成员补充 | ~30 行 |
| `server/handler.py` | **修改** — `_ADMIN_COMMANDS` 注册 5 个新命令 | ~25 行 |
| `server/workspace.py` | **检查** — `add_member()`/`remove_member()` 是否存在，不存在则新增 | ~20 行 |
| `docs/TODO.md` | **修改** — F-3 方向更新 + min_role 评估记录 | ~10 行 |
| **合计** | | **~185 行净增** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| `!workspace_remove` 误操作移除关键成员 | 工作区成员丢失 | 限制不可移除 owner，使用者只能移除自己工作区的人 |
| 点名自动加入覆盖旧成员检查 | 非活跃 agent 被自动加入 | 只补充「不在 member_ids 中」的 agent，不覆盖现有成员 |
| 全员可用命令被滥用 | 频繁 join/leave 产生噪音 | 自然约束：bot 无动机频繁操作 |

---

## 6. 影响范围

| 模块 | 影响 | 说明 |
|:-----|:-----|:------|
| `server/handler.py` | 🟡 中等 | 5 个新命令 + 2 处自动补充逻辑 |
| `server/workspace.py` | ℹ️ 轻微 | 可能需确认/新增 `add_member()` 和 `remove_member()` |
| `server/auth.py` | ✅ 无影响 | 不改角色等级 |
| `server/config.py` | ✅ 无影响 | 不改配置常量 |
| `shared/protocol.py` | ✅ 无影响 | 不新增消息类型 |
| 各 bot 代码 | ✅ 无影响 | bot 无需更新 |
| Web 前端 | ✅ 无影响 | 不涉及前端 |

---

## 7. 技术方案参考

- `server/handler.py` ~L630-648 — `_cmd_create_workspace()`，参考 workspace 创建逻辑
- `server/handler.py` ~L567-572 — `_is_any_workspace_admin()` 当前 P3 检查（非本轮回目标）
- `server/handler.py` ~L4600+ — `_ADMIN_COMMANDS` 命令注册表位置
- `server/handler.py` ~L575-580 — `_log_audit()` audit 日志记录函数参考
- `server/handler.py` — `_cmd_rollcall()` ACK 处理位置（B1 自动加入点）
- `server/workspace.py` — `get_workspace()` / `add_member()` / `remove_member()`，当前 workspace 管理接口
- `server/workspace.py` — `member_ids` 字段：workspace 对象的成员列表属性

---

## 8. 脱敏检查清单

- [ ] docs/R81/*.md 零内部名残留
- [ ] `grep -nE '内部名模式' docs/R81/*.md` 零匹配
- [ ] 使用通用名（全局管理员 / workspace_admin / 成员）
- [ ] 不包含真实 agent_id / token / URL
- [ ] 新命令名用英文短横线格式（`workspace_join` / `workspace_leave`）

---

*需求文档生成：2026-07-09 🧐 PM*
