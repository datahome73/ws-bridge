---
pipeline:
  name: "R81 工作区成员自动化管理"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R81/WORK_PLAN.md"

  workspace:
    members:
      architect:
        mention_keyword: "小开;architect;架构师"
        rules: "输出技术方案文档"
      developer:
        mention_keyword: "爱泰;developer;开发"
        rules: "按技术方案编码"
      reviewer:
        mention_keyword: "小周;reviewer;审查"
        rules: "审查代码"
      qa:
        mention_keyword: "泰虾;qa;测试"
        rules: "测试验证"
      operations:
        mention_keyword: "小爱;operations;运维"
        rules: "合并部署归档"
      product-manager:
        mention_keyword: "小谷;pm;需求分析师"
        rules: "编写需求文档和工作计划"

  steps:
    step2:
      role: architect
      title: 技术方案
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R81/R81-product-requirements.md"
      timeout_minutes: 360

    step3:
      role: developer
      title: 编码实现
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R81/R81-product-requirements.md"
      timeout_minutes: 240

    step4:
      role: reviewer
      title: 代码审查
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R81/R81-product-requirements.md"
      timeout_minutes: 120

    step5:
      role: qa
      title: 测试验证
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R81/R81-product-requirements.md"
      timeout_minutes: 120

    step6:
      role: operations
      title: 合并部署归档
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R81/R81-product-requirements.md"
      timeout_minutes: 60
---

# R81 工作计划 — 工作区成员自动化管理 🤖

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** 📋 定稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R81/R81-product-requirements.md v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动极集中，严禁 scope creep**
- 不改入：管线状态机（`_PIPELINE_STATE` / `_PIPELINE_CONFIG`）
- 不改入：auth.py 角色等级逻辑（`role_level()`, `is_global_admin()` 等）
- 不改入：注册/认证协议（register / auth 消息类型）
- 不改入：Web 前端
- 不改入：bot 端代码
- 不改入：`worker_manager.py` / watchdog 模块

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | architect | developer | — |
| Step 3 | 💻 编码 | developer | architect | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | reviewer | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | reviewer | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | operations | architect | |

---

## 1. 管线总览

### 核心逻辑

本轮新增 **5 个新命令 + 2 处自动化补充**，全部 min_role=2（全员可用），无等级门槛。

### 改动范围

仅 `server/handler.py` + `server/workspace.py`（注：`workspace.py` 中 `add_member()`/`remove_member()` 已存在，仅确认接口）

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A | `!workspace_join` — 加入工作区 | `handler.py` 新增 `_cmd_workspace_join()` | ~25 行 |
| 2 | A | `!workspace_leave` — 退出工作区 | `handler.py` 新增 `_cmd_workspace_leave()` | ~25 行 |
| 3 | A | `!workspace_add` — 邀请他人加入 | `handler.py` 新增 `_cmd_workspace_add()` | ~25 行 |
| 4 | A | `!workspace_remove` — 踢出成员（仅 owner） | `handler.py` 新增 `_cmd_workspace_remove()` | ~30 行 |
| 5 | A | 命令注册 5 条 | `handler.py` `_ADMIN_COMMANDS` L4603+ | ~25 行 |
| 6 | B | ACK 后自动加入工作区 | `handler.py` `_cmd_rollcall` / `_cmd_rollcall_role` ACK 处理 | ~15 行 |
| 7 | B | pipeline_start 成员不足时 inbox 邀请 | `handler.py` `_cmd_pipeline_start` 末尾 | ~15 行 |
| 8 | C | `!workspace_list_members` — 成员列表查询 | `handler.py` 新增 `_cmd_workspace_list_members()` | ~25 行 |
| 9 | D | TODO.md F-3 状态更新 + min_role 评估记录 | `docs/TODO.md` | ~10 行 |

**总估算：** ~195 行净增

---

## 2. 管线步骤

### Step 1：需求文档（PM — 已完成 ✅）

需求文档 `docs/R81/R81-product-requirements.md` 已审核通过。

### Step 2：技术方案（architect）

**输入：** 需求文档 URL + WORK_PLAN URL

**任务：** 输出技术方案文档 `docs/R81/R81-tech-plan.md`，需涵盖：

1. **方向 A 命令设计**（P0）：
   - 4 个新命令的函数签名、参数解析、返回值格式
   - 如何确定「当前活跃工作区」：`persistence.get_agent_channel(sender_id)`
   - `!workspace_remove` 的 owner 身份检查：`ws.owner_id == sender_id`
   - 参考 `_cmd_create_workspace()`（~L630）的实现模式

2. **方向 B 自动化补充**（P1）：
   - 点名 ACK 处理函数的入口位置（`_cmd_rollcall` / `_cmd_rollcall_role` 的接收响应部分）
   - pipeline_start 后成员不足检测 + inbox 通知：`_send_cmd_response()` 或 `_broadcast_to_channel()`
   - 参考 `_send_cmd_response()`（~L506）模式

3. **方向 C 成员列表查询**（P2）：
   - `!workspace_list_members` 返回格式：成员名 + 角色（owner/member）+ 在线状态
   - 角色标识：`ws.owner_id`（owner）、`ws.member_ids`（member）

4. **方向 D 治理评估**（P2）：
   - 评估哪些 `_ADMIN_COMMANDS` 中 min_role=3 的命令可安全降级到 2
   - 输出评估结果到 TODO.md 或单独文档

**参考代码位置：**
- `server/handler.py` L320 — `_broadcast_to_channel()` 广播通知模式
- `server/handler.py` L506 — `_send_cmd_response()` 发送响应模式
- `server/handler.py` L630 — `_cmd_create_workspace()` workspace 操作模式
- `server/handler.py` L4603-4800 — `_ADMIN_COMMANDS` 注册表
- `server/workspace.py` L179-214 — `Workspace` 类定义（owner_id, member_ids, admin_ids）
- `server/workspace.py` L332 — `add_member()`
- `server/workspace.py` L341 — `remove_member()`
- `server/auth.py` L68-74 — `is_approved()` 权限检查
- `server/persistence.py` — `get_agent_channel()` / `get_approved_users()`

**完成条件：**
- 技术方案文档推 dev
- `!step_complete step2 --output <sha>`

### Step 3：编码（developer）

**输入：** 需求文档 URL + WORK_PLAN URL + 技术方案 URL

**任务：** 在 `server/handler.py` 中实现以下改动：

**A1 — `_cmd_workspace_join()`**
```python
async def _cmd_workspace_join(sender_id: str, params: dict) -> str:
```
- 确定工作区：`--workspace <ws_id>` 参数或 `persistence.get_agent_channel(sender_id)` 活跃频道
- 检查工作区存在、已加入则提示
- 调用 `ws_mod.add_member(ws_id, sender_id)`
- 广播加入通知

**A2 — `_cmd_workspace_leave()`**
```python
async def _cmd_workspace_leave(sender_id: str, params: dict) -> str:
```
- 不可退出 owner（`sender_id == ws.owner_id`）
- 调用 `ws_mod.remove_member(ws_id, sender_id)`
- 广播离开通知

**A3 — `_cmd_workspace_add()`**
```python
async def _cmd_workspace_add(sender_id: str, params: dict) -> str:
```
- sender 必须在目标工作区中
- 调用 `ws_mod.add_member(ws_id, target_id)`
- 返回成功消息

**A4 — `_cmd_workspace_remove()`**（仅 owner）
```python
async def _cmd_workspace_remove(sender_id: str, params: dict) -> str:
```
- 仅 `sender_id == ws.owner_id` 可执行
- owner 不能移除自己
- 调用 `ws_mod.remove_member(ws_id, target_id)`
- 广播移除通知（含执行者名）

**A5 — 命令注册** 在 `_ADMIN_COMMANDS` 中添加 5 条：
- `workspace_join` (min_role=2)
- `workspace_leave` (min_role=2)
- `workspace_add` (min_role=2)
- `workspace_remove` (min_role=2)
- `workspace_list_members` (min_role=2)

**B1 — 点名自动加入：** 在点名 ACK 响应处理中（`_cmd_rollcall` 或 `_cmd_rollcall_role`），当 ACK 发送者在工作区活跃频道中且不在 member_ids 时，自动 `add_member()`

**B2 — pipeline_start 成员补充：** `_cmd_pipeline_start()` 创建工作区后，检查 `len(ws.member_ids) <= 2`，向未加入的角色 bot 发送 inbox 邀请通知

**C1 — `_cmd_workspace_list_members()`**：显示工作区所有成员的 agent_id、角色（owner/ member）、在线状态

**完成条件：**
- 代码推 dev 分支
- `!step_complete step3 --output <sha>`

### Step 4：审查（reviewer）

**审查重点：**

| # | 审查项 | 说明 |
|:-:|:-------|:------|
| ① | **owner 检查正确性** | `_cmd_workspace_remove` 必须只允许 `ws.owner_id == sender_id`，不可误放 |
| ② | **成员列表一致性** | `add_member` 后 member_ids 包含新成员，`remove_member` 后不含 |
| ③ | **活跃频道推断正确** | 当 sender 不在工作区活跃频道时，join/leave 应返回明确提示而非静默失败 |
| ④ | **owner 不能 leave 自己** | `_cmd_workspace_leave` 的 owner 守卫（`sender_id == ws.owner_id` → ❌） |
| ⑤ | **scope 合规** | 没有引入不在范围内的改动（管线状态机、auth.py 角色等级、前端） |
| ⑥ | **grep 零残留** | 代码中无内部名残留 |

**完成条件：**
- 审查报告推 dev
- 如发现 blocking 问题，标注并等待 dev 修复
- `!step_complete step4 --output <sha>`

### Step 5：测试（qa）

**验收项（从需求文档复制）：**

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
| ✅-9 | 点名 ACK 后自动加入工作区 | ACK 响应者自动进入 ws.member_ids | 触发点名，检查 member_ids |
| ✅-10 | pipeline_start 后成员不足时发 inbox 邀请 | 未加入的目标角色收到邀请通知 | 检查对应 inbox |
| ✅-11 | `!workspace_list_members` 列出成员信息 | 显示成员名、角色、在线状态 | 在工作区中执行命令 |
| ✅-12 | L2 member 可执行 | 权限正常 | member 身份执行 |
| ✅-13 | min_role 可降级命令清单输出 | TODO.md 或单独文档记录 | 自己看 |
| ✅-14 | 审计记录 5 个新命令操作 | _audit_logger 记录新命令调用 | 检查 audit 日志 |

**完成条件：**
- 测试报告推 dev
- 14 项验收全部通过或标注可接受的非阻塞项
- `!step_complete step5 --output <sha>`

### Step 6：合并部署归档（operations）

1. **合并** dev → main
2. **构建** 新 Docker 镜像（ws-bridge:r81）
3. **部署** 生产容器（stop → rm → run）
4. **健康检查**：
   - `!workspace_join` / `!workspace_leave` 命令可用
   - `!workspace_add` / `!workspace_remove` 命令可用
   - `!workspace_list_members` 命令可用
5. **TODO.md 更新**：F-3 标记为 🟢 R81 已完成，版本号 v2.47 → v2.48
6. **关闭工作区** + 恢复大厅

---

## 3. 验收清单（从需求文档复制）

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
| ✅-14 | 审计记录 5 个新命令操作 | _audit_logger 记录新命令调用 | 检查 audit 日志 |

---

## 4. 脱敏检查清单

- [ ] docs/R81/*.md 零内部名残留（frontmatter YAML 区 25 行外无真名）
- [ ] Step 描述中的主角/备用用角色名（architect/developer/reviewer/qa/operations）
- [ ] 代码中无内部 URL/端口/agent_id 硬编码
- [ ] 命令名用英文（`workspace_join` / `workspace_leave` 等）
