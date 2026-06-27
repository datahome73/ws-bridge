# R44 产品需求 — 管线入口修复（Pipeline Entry Fix）

> **版本：** v0.1（草稿，待项目负责人审核）
> **状态：** 📝 草稿（待审核）
> **产品经理：** 🧐 PM
> **日期：** 2026-06-27
> **本轮改动范围：** 仅第①类（服务器代码 `server/handler.py`），修复管线启动入口和工作区成员填充

---

## 1. 问题背景

### R43 管线死锁复盘

R43 是 R42 管线自动触发系统上线后的首次实战运行。虽然看门狗、超时配置、三段通知均已实现并上线（39/39 测试通过），但管线启动环节暴露了两个断点，导致管线必须通过以下曲折流程完成：

```
PM 在 TG DM：写 code 块消息 → 项目负责人复制 → 项目负责人发给 admin-bot
  → admin-bot 在大厅执行 !pipeline_start R43
  → 工作室被创建（仅 admin-bot 一人在工作区）
  → _auto_rollcall_notify 点名通知只发给 admin-bot 本人
  → _cmd_rollcall_next 按角色查找工作区成员 → 找不到 arch 角色 → 静默失败
```

| 断点 | 现象 | 根因 |
|:-----|:-----|:------|
| **① 入口断点** | PM 无法直接在工作群触发 `!pipeline_start`，必须通过项目负责人 code 块中转 | `_admin` 频道不在 send_message 的 channel_directory 中；PM 角色为 member（P1），无权执行 `!` 前缀命令（需 P3+） |
| **② 成员断点** | 管线创建的工作室只有执行者一人，点名+派活静默失败 | `_cmd_pipeline_start` 硬编码 `create_params` 不传 `--members`，工作区只有 admin-bot 自己，`_cmd_rollcall_next` 按角色查找成员时空列表返回错误 |

### 对体验的影响

- **项目负责人每次启动管线都必须手动转发 code 块** — 本应一次命令完成的工作，变成了 PM→项目负责人→admin-bot 的三段传递
- **管线启动后预期行为不生效** — 工作室虽已创建，但点名和派活均失败，管线处于「看似活跃实则死锁」的状态
- **项目负责人投入的时间与管线自动化理念相悖** — 自动化管线的核心价值是减少人工介入，但当前启动环节的人工操作反而增加了

### 已有基础

| 已有能力 | 状态 | 说明 |
|:---------|:----:|:------|
| `!pipeline_start` 命令 | ✅ | 创建工作室 + 点名 + 派活的全流程已实现 |
| `_admin` 频道 | ✅ | 常驻频道，用于接收系统级 `!` 命令 |
| `_ADMIN_COMMANDS` 注册表 | ✅ | `handler.py` 中的 `!` 前缀命令调度系统 |
| `auth.get_users()` | ✅ | 可获取所有已注册用户的 agent_id、角色、权限 |
| `PIPELINE_STEP_MAP` | ✅ | `server/config.py` 中 6 步 Step→角色映射表 |
| 看门狗（R43 上线） | ✅ | 10 分钟扫描 + 超时通知 + 重复告警去重 |

### 不是问题的情况

- `!pipeline_start` 被 admin-bot 在 `_admin` 频道执行 → ✅ 管线启动正常（绕过桥接后仍可工作）
- 人工 `!create_workspace` + `!rollcall_role` 分步执行 → ✅ 旧流程继续可用
- 管线启动后的 Step 接力流程（`!step_complete`） → ✅ F-11 已修复，接力正常

---

## 2. 预期体验

### 改进后

```
PM(TG DM) → 发「!pipeline_start R44」
  ↓
系统自动：Gateway 识别到管线命令 → 路由到 _admin 频道
  → admin-bot (P4) 执行 !pipeline_start R44 --from step2
  → 自动获取 auth.get_users() 中所有开发角色（arch、dev、review、qa）加入工作区
  → 点名全员开麦
  → 点名架构师出技术方案

PM：一次操作，零中转，管线即时启动 ✅
```

### 关键改进

1. **PM 一次操作直达管线** — 不再需要 code 块 + 项目负责人转发
2. **工作区开箱即用** — 创建时自动包含所有开发角色，点名可直接匹配
3. **向后兼容** — 旧入口（`_admin` 频道直接发命令）继续可用
4. **权限透明** — PM 触发的命令仍然由 admin-bot（P4）权限执行，不改变认证体系

> 技术方案（Gateway 侧路由方式、服务端如何识别 PM 身份）由架构师决定。

---

## 3. 需求详述

### 方向 A — 管线入口直达 🟡 P2

让 PM 通过 TG DM 一次操作即可触发管线启动，取消三段式中转。

#### 用户旅程

```
PM 在 TG DM 对 ws-bridge 发：!pipeline_start R44
  ↓ 当前行为
  消息发送到大厅 → 被 broadcast 解释为普通文本 → 无反应 ❌
  ↓ 期望行为
  消息被系统识别 → 路由到 _admin 频道 → admin-bot 执行
  → 管线自动启动 ✅
```

#### 具体需求

| # | 需求 | 优先级 |
|:-:|:-----|:------:|
| A-1 | PM 在 TG DM 发送 `!pipeline_start R{N}` 时，系统自动将该命令路由到 ws-bridge 的 `_admin` 频道 | 🔴 P1 |
| A-2 | 命令到达 `_admin` 频道后由 admin-bot（P4 全局管理员）权限执行，不改变当前 `!` 命令的权限检查逻辑 | 🔴 P1 |
| A-3 | 路由仅限 `!pipeline_start` 管线命令，不影响其他 `!` 前缀命令（`!create_workspace` 等仍走现有逻辑） | 🟡 P2 |
| A-4 | PM 触发时自动增加 `--from step2` 参数（从技术方案 Step 开始），避免新 6 步配置下的 start_step 默认值偏移 | 🟡 P2 |
| A-5 | 命令执行结果（成功/失败消息）自动回传 PM 的 TG DM | 🟡 P2 |
| A-6 | 如果 `!pipeline_start` 后不跟轮次号（如 `!pipeline_start` 无参数），返回用法提示 | 🟢 P3 |

#### 实现方向（架构师评估）

| 方向 | 说明 |
|:-----|:------|
| **方案 1：Gateway 侧路由** | 在 ws-bridge adapter 中识别 `!pipeline_start` 命令，自动以 admin-bot 身份转发到 `_admin` 频道。PM 消息不进大厅广播 |
| **方案 2：服务端侧代理** | 在 handler.py 中为 `_ADMIN_COMMANDS` 增加代理机制：当 member 角色（P1）发 `!pipeline_start` 到 lobby 时，handler 自动以 admin-bot 身份在 `_admin` 频道执行 |
| **方案 3：权限降级** | 在 `_check_command_permission` 中为 `!pipeline_start` 单独设置 `min_role` 为 P1，允许 PM 直接在一级权限下执行 |

> 架构原则：方向 A 的实现不应引入新的认证机制，也不应降低 `!` 命令系统的整体安全性。具体方案由架构师在技术方案中决策。

---

### 方向 B — 工作区自动填充成员 🟡 P2

`!pipeline_start` 创建工作室时自动将所有开发角色（arch、dev、review、qa）加入工作区，确保点名可以直接匹配到人。

#### 用户旅程

```
!pipeline_start R44 ← 当前行为
  → 工作室 ws:R44-dev 被创建（成员：admin-bot 一人）❌
  → _auto_rollcall_notify → 只通知 admin-bot
  → _cmd_rollcall_next(arch) → 工作区无 arch → 返回错误 ❌

!pipeline_start R44 ← 期望行为
  → 工作室 ws:R44-dev 被创建（成员：arch-bot, dev-bot, review-bot, qa-bot, admin-bot）✅
  → _auto_rollcall_notify → 全员收到搬家通知
  → _cmd_rollcall_next(arch) → 找到 arch-bot → 点名成功 ✅
```

#### 具体需求

| # | 需求 | 优先级 |
|:-:|:-----|:------:|
| B-1 | `!pipeline_start` 创建工作室时，自动从 `auth.get_users()` 获取所有开发角色（arch、dev、review、qa）的 agent_id 加入工作区 | 🔴 P1 |
| B-2 | 获取成员后转为 `authorized_members` 列表，传入 `!create_workspace` 的 `--members` 参数 | 🔴 P1 |
| B-3 | 如果 `auth.get_users()` 中某个角色有多个 agent（如多个 dev-bot），全部加入工作区 | 🟡 P2 |
| B-4 | `!pipeline_start` 增加 `--members` 显式参数选项，覆盖自动获取（项目负责人可指定特定成员） | 🟡 P2 |
| B-5 | 如果 `auth.get_users()` 返回异常（为空或缺少必要角色），返回明确错误提示，不创建空工作区 | 🟡 P2 |
| B-6 | 不改变 `!create_workspace` 的现有行为，旧 API 保持向后兼容 | 🔴 P1 |

#### 实现说明

**数据来源：** `handler.py` 中已有 `auth.get_users()` 调用，返回 `dict[agent_id, UserInfo]`，其中 `UserInfo` 包含 `role` 字段。

**角色映射逻辑：**
```
PIPELINE_STEP_MAP = {
    "step2": {"name": "技术方案", "role": "arch", ...},
    "step3": {"name": "编码", "role": "dev", ...},
    "step4": {"name": "审查", "role": "review", ...},
    "step5": {"name": "测试", "role": "qa", ...},
    "step6": {"name": "合并部署", "role": "admin", ...},
}
```
从 `PIPELINE_STEP_MAP` 收集所有 unique 角色名，再从 `auth.get_users()` 中筛选匹配的用户加入工作区。

> 技术方案（具体如何从 PIPELINE_STEP_MAP 提取角色列表、auth.get_users() 的调用时机、--members 参数优先级规则）由架构师决定。

---

### 方向 C — 启动上下文增强 🟢 P3

R43 实操中发现 `!pipeline_start` 传递的上下文不完整，架构师收到点名时缺少工作流文档。

| # | 需求 | 优先级 |
|:-:|:-----|:------:|
| C-1 | `!pipeline_start` 的 `context_urls` 自动追加 WORKFLOW.md URL 到上下文 | 🟢 P3 |
| C-2 | 默认 start_step 从旧 7 步残留的 `"step3"` 改为 `"step2"`（从 `PIPELINE_STEP_MAP` 的第一个非 step1 条目动态计算），消除 `--from step2` 的手动参数依赖 | 🟢 P3 |
| C-3 | `!pipeline_start` 的返回值增强：明确报告已加入工作区的成员列表 | 🟢 P3 |

---

## 4. 架构原则

### 4.1 管道入口语义不变

方向 A 修复的是**入口可达性**，不改变 `!pipeline_start` 命令本身的语义。命令仍然：
- 由 `_admin` 频道处理（由 admin-bot 权限执行）
- 创建工作室 + 点名 + 派活
- 入口路由后实际执行逻辑不变

### 4.2 权限体系不变

方向 A 不涉及降低权限要求。PM 的命令由 admin-bot（P4）代理执行，不修改 `_check_command_permission` 的权限阈值。

### 4.3 向后兼容

- `!pipeline_start` 在 `_admin` 频道直接执行（admin-bot 手动触发）继续可用
- 旧流程（人工 `!create_workspace` + `!rollcall_role` 分步执行）继续可用
- 未修改的命令（`!task_create`、`!step_complete`、`!pipeline_status`）行为不变

### 4.4 纯服务端系统层

方向 B、C 全部在服务端系统层（`handler.py`、`config.py`）完成，零 token 消耗。方向 A 可能需要少量的 Gateway 侧改动（adapter 路由）或 handler 加代理，但判定逻辑仍然是纯规则。

---

## 5. 验收标准

### 方向 A — 管线入口直达

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| A-1 | PM 从 TG DM 发 `!pipeline_start R44` 后，管线在 <5 秒内自动启动（工作室创建 + 点名） | 🔴 P1 |
| A-2 | 命令始终由 admin-bot（P4）权限执行，PM 的 member 角色不直接获得 `!` 命令权限 | 🔴 P1 |
| A-3 | 非管线命令（如 `!task_create`、`!create_workspace`）不会被错误路由到 `_admin` 频道 | 🟡 P2 |
| A-4 | 缺少轮次参数的 `!pipeline_start` 返回用法提示，不创建工作室 | 🟢 P3 |
| A-5 | 执行结果（成功/失败）通过 TG DM 回传给 PM | 🟡 P2 |

### 方向 B — 工作区自动填充成员

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| B-1 | `!pipeline_start` 创建的工作室包含所有开发角色（arch、dev、review、qa、admin），成员数 >= 5 | 🔴 P1 |
| B-2 | 点名阶段 _auto_rollcall_notify 通知到工作区所有成员 | 🔴 P1 |
| B-3 | `_cmd_rollcall_next(arch)` 在工作区中找到 arch 角色成员 | 🔴 P1 |
| B-4 | `--members` 显式参数可覆盖自动获取的成员列表 | 🟡 P2 |
| B-5 | `auth.get_users()` 为空或缺少必要角色时，返回明确错误提示，不创建工作室 | 🟡 P2 |
| B-6 | `!create_workspace` 单独调用时行为不受影响 | 🔴 P1 |

### 方向 C — 启动上下文增强

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| C-1 | 架构师收到的点名消息中包含 WORKFLOW.md URL 引用 | 🟢 P3 |
| C-2 | 默认 start_step 正确指向 Step 2（技术方案），无需手动 `--from step2` | 🟢 P3 |
| C-3 | `!pipeline_start` 返回值中包含已加入工作区的成员列表 | 🟢 P3 |

---

## 6. 不纳入本轮需求

| 事项 | 原因 |
|:-----|:------|
| `!` 命令整体权限体系改革（P3 角色系统） | 独立功能轮（F-3 待分配），本轮只修管线入口 |
| Gateway 适配器重构 | 变动过大，本轮只加路由规则 |
| 管线运行中的成员变更（执行中增减人员） | 非入口问题，独立优化项 |
| 多管线并行运行支持 | 当前架构仅支持单管线，独立功能轮 |
| Web 端管线管理面板 | 第④类，本轮只改第①类 |

---

## 7. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v0.1 | 2026-06-27 | 初稿，基于 R43 首轮管线试点的 F-12/F-13 断点分析 |
