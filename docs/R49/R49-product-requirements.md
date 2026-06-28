# R49 产品需求 — 管线工作频道命令路由 + 角色映射持久化

> **版本：** v0.1（草稿，待审核）
> **状态：** 📝 草稿（待审核）
> **产品经理：** 🧐 PM
> **日期：** 2026-06-28
> **本轮改动范围：** 仅第①类（服务器代码 —— `server/handler.py` + `server/auth.py` / 运维配置）

---

## 1. 问题背景

R48 完成了管线通用化（`--work-plan-url` 参数）和完成通知闭环（🔔 PIPELINE_COMPLETE），代码已合并部署到生产。但 R48 全流程的实操运行暴露了两个更底层的管线卡点：

### 1.1 `!` 命令路由仅限 `_admin` 频道（管线阻塞根因）

R48 的 6 步管线中，各角色需要在工作室完成工作后执行 `!step_complete` 推进状态机。但实际执行中，`!` 前缀命令的解析和调度**仅在 `_admin` 频道分支**生效（`handler.py` ≈行 1608-1649）。发到工作频道（workspace）的 `!step_complete` 被当做普通广播消息处理——服务端不会执行 `_cmd_step_complete`，不会更新管线状态，不会点名下一角色。

**R48 实操表现：**

| 场景 | 实际行为 | 预期行为 |
|:-----|:---------|:---------|
| 架构师在工作室发 `!step_complete Step2 --output abc123` | 消息广播但不被解析 | 服务端执行 step_complete，标记 Step 2 ✅，点名 dev |
| 开发者在工作室发 `!step_complete Step3 --output abc456` | 消息广播但不被解析 | 服务端执行 step_complete，标记 Step 3 ✅，点名 review |
| PM 在 lobby 发 `!pipeline_start R49` | 同样不被解析 | 仅 `_admin` 频道可执行 |

**这意味着：** 管线的自动接力机制（`!step_complete` → 标记完成 → 点名下一人）实际上在工作室环境中**完全不可用**。各角色只能：
1. 通过原始 WebSocket 直连 `_admin` 频道发 `!` 命令（PM 可以，但各开发角色没有这种操作方式）
2. 或者 PM 全程在场外替所有人执行 `!step_complete`

这两种方式都与「管线自动化」的初衷背道而驰。

### 1.2 角色映射缺失，管线点名匹配不到人

`PIPELINE_STEP_MAP` 硬编码了 `arch → dev → review → qa → admin` 五个管线角色。`!step_complete` 点名下一角色时，从工作区成员中按 `role` 字段匹配。但现有 agent 注册时的角色均为默认 `member`：

| 步骤 | 点名角色 | 工作区中实际 role | 结果 |
|:----:|:--------|:-----------------|:-----|
| Step 2 → Step 3 | `dev` | 无 agent 的 role=`dev` | ❌ 匹配失败 |
| Step 3 → Step 4 | `review` | 无 agent 的 role=`review` | ❌ 匹配失败 |
| Step 4 → Step 5 | `qa` | 无 agent 的 role=`qa` | ❌ 匹配失败 |

即使 `!` 命令路由修复了，角色映射缺失仍然导致管线停在原地。这个问题的本质是：**Agent 的角色信息与代码紧耦合，缺乏灵活的可配置化映射层。**

### 1.3 管线状态一致性和超时检测缺失

即使 `!` 命令路由和角色映射都修好了，管线仍然依赖「每个角色主动调用 `!step_complete`」的推动力。如果某人完成了工作但忘记/未调 `!step_complete`，管线永久阻塞。R48 已将 `min_role` 从 3 降为 1 让成员可自驱，但缺乏自动兜底机制：

- 没有 Step 超时检测（如「Step X 超过 N 分钟无进展 → 通知相关角色」）
- 没有状态一致性核查（如「Step 已完成但 `!step_complete` 未调用 → 自动推进」）
- 没有二次催办机制（超时后升级通知到项目负责人）

---

## 2. 需求范围

| 方向 | 问题 | 解决方案 | 代码类型 | 优先级 |
|:----:|:-----|:---------|:--------:|:------:|
| **A** | `!` 命令路由仅限 `_admin` 频道 | 工作频道也解析 `!` 命令，自动桥接到 handler | ① 服务器 | 🔴 P0 |
| **B** | Agent 角色映射硬编码，管线点名匹配不到人 | 服务端持久化角色映射表，`!pipeline_start` 从映射表拉取 | ① 服务器 | 🟡 P1 |
| **C** | 管线状态无超时/兜底 | Step 超时检测 + 自动催办通知 | ① 服务器 | 🟡 P2 |

> 技术方案（具体实现方式）由架构师决定。

---

## 3. 用户体验

### 3.1 方向 A：`!` 命令在工作频道可路由

**当前（R48）：**

各角色在工作室内完成工作后，无法通过 `!step_complete` 推进管线。消息被当作普通广播：

```
小开: 技术方案已完成，docs/R48/R48-tech-plan.md 已推 dev
       !step_complete Step2 --output 5f63177
       ↑ 这条消息在工作室里被广播给全员，服务端不做任何命令解析
```

**期望（R49）：**

工作频道（workspace）中的 `!` 前缀消息被服务端拦截解析：

```
小开: 技术方案已完成
       !step_complete Step2 --output 5f63177
       ↑ 服务端拦截 → 解析 → 权限校验 → 执行 handler
       ↑ 返回确认消息到工作室 + 更新管线状态 + 点名下一角色
```

**具体设计约束：**

1. `!` 命令在工作频道（workspace）和 `_admin` 频道都能被解析执行
2. 在工作频道执行 `!` 命令时，被 @ 的下一角色自动收到工作室内的点名消息
3. 权限检查（`_check_command_permission`）沿用现有规则——工作区成员只能操作其角色相关的 step
4. `_admin` 频道的 `!` 命令行为完全不变，不影响现有管理操作
5. 非 `!` 前缀的普通消息行为不变，仍走现有广播路由

**体验流程（开发者视角）：**

```
开发者完成编码 → 推 dev → 在工作室发：
  !step_complete Step3 --output 7a299a9

服务端响应（发回工作室）：
  ✅ Step 3（编码）已完成
  📋 点名下一位：审查工程师
  🏗️ 审查工程师请审查 commit 7a299a9

审查工程师收到点名 → 开始审查
```

### 3.2 方向 B：Agent 角色映射持久化

**当前（R48）：**

`PIPELINE_STEP_MAP` 硬编码角色体系，现有 agent 的 role 全部为 `member`。管线无法按角色匹配到对应成员。

**期望（R49）：**

服务端有可配置的角色映射表，将 agent_id 映射到管线角色：

```python
# 持久化到运维数据层（如 auth.json 或独立 config）
ROLE_MAPPING = {
    "01KT6EDS8PMF0FTK1FCJ8V4TPH": "arch",    # 小开
    "01KVJ87JDSZ6MDSHP8AYWZK694": "dev",     # 爱泰
    "01KVS0PJDSZ6MDS8PAYWZK695": "review",   # 小周
    "01KVT1QJDSZ6MDS9PAYWZK696": "qa",       # 泰虾
}
```

**设计约束：**

1. 角色映射表**不写在代码中**——存储在持久化数据层（如 `auth.json`、独立 JSON 配置文件、或环境变量）
2. `!pipeline_start` 创建工作室时，从角色映射表中收集所有管线角色对应的 agent_id 加入工作区
3. `!step_complete` 点名下一角色时，从映射表查找当前工作区中 role 匹配的 agent
4. 角色映射表的维护通过 `!role_map` 命令或手动编辑持久化文件完成
5. 向后兼容：当映射表为空时，回退到现有 `auth.get_users()` 按 role 字段匹配的行为

**角色映射表管理体验：**

```
管理员通过 _admin 频道管理映射表：
  !role_map list                    → 显示当前映射表
  !role_map set <agent_id> <role>  → 将 agent 映射到指定角色
  !role_map unset <agent_id>       → 取消映射
  !role_map reload                  → 从持久化文件重新加载

查看效果：
  !pipeline_status                  → 显示管线 + 各步骤当前角色分配
```

### 3.3 方向 C：管线 Step 超时检测

**当前（R48）：**

管线状态完全依赖各角色主动调用 `!step_complete`。无人调用则永久阻塞，无任何告警或兜底。

**期望（R49）：**

服务端有 Step 超时检测机制，在 `!step_complete` 推进管线状态的同时注册**超时时钟**：

1. 每个 Step 被点名时（`!step_complete` 执行 → 点名下一人），服务端注册该 Step 的超时计时器（可配置，如 30 分钟 / 60 分钟）
2. 超时前 `(timeout - N)分钟` 在工作室发催办消息
3. 超时后未完成 → 在工作室发 ⚠️ 超时告警
4. 超时告警后仍无响应 (N 分钟后) → 向 `_admin` 频道写入升级通知，PM 看到后 TG 协调

**超时检测体验：**

```
点名审查工程师 - 开始计时 60 分钟

第 45 分钟（超时前 15 分钟）：
  ⏰ Step 4（代码审查）15 分钟后超时，审查工程师若需要帮助请联系 PM

第 60 分钟（超时）：
  ⚠️ Step 4（代码审查）已超时。审查工程师请尽快完成审查。

第 90 分钟（超时 +30 分钟）：
  🚨 Step 4 超时 30 分钟，已升级到 _admin 频道
  (PM 在 TG DM 协调)
```

**设计约束：**

1. 超时检测只能发送通知、不能自动跳过 Step（避免误推进破坏管线数据一致性）
2. 超时时间可配置（环境变量或 `PIPELINE_TIMEOUT_MINUTES`）
3. 超时通知只发到工作室频道（不直接 TG 大宏），防止干扰
4. 升级通知（超时后仍无响应）写入 `_admin` 频道，由 PM 人工协调
5. 前置决策区（Step A/B）没有超时检测——那是项目负责人参与的环节，不应自动催办
6. 超时计时器在服务端进程级 tracking 中管理（纯系统代码，零 token），参考 R43 Hot Standby 看门狗模式
7. 服务端重启后的超时场景：重新加载活跃管线状态，对比 `started_at` + 已过去的时间，决定是否触发超时通知

---

## 4. 架构原则

### 4.1 工作频道的 `!` 命令拦截是纯路由层改动

方向 A 只是在 `handle_broadcast` 的工作频道广播分支（≈行 1650+）中，在消息广播前增加一条 `!` 前缀检测分支：

```
工作频道收到消息
  → 如果 content 以 "!" 开头
    → 调用 _parse_command() 解析命令和参数
    → 调用 _check_command_permission() 检查权限
    → 调用对应的 _cmd_xxx() handler
    → 将 handler 返回值发回工作室
  → 否则（普通消息）
    → 走现有广播路由（不变）
```

这不会改变 `_admin` 频道现有的 `!` 命令处理路径，不会影响现有管理命令工作。

### 4.2 角色映射持久化是运维配置，非代码改动

方向 B 不修改 `PIPELINE_STEP_MAP` 的代码结构，而是增加一个可以从持久化文件读取的代理层：

```
!pipeline_start / !step_complete
  → 从持久化配置读取角色映射表（如有）
  → 映射表中有该 agent → 取其 role
  → 映射表中无该 agent → 回退到 auth.get_users().role（现有行为）
```

映射表格式使用 JSON（与现有 `auth.json` 同模式），存储到 `data/role_mapping.json`（或与 auth 同目录）。

### 4.3 超时检测是纯服务端系统层，零 token

方向 C 完全在 handler.py 的服务端 `_ADMIN_COMMANDS` 模式内实现，不涉及 AI 推理。超时计时器使用 `asyncio` 的 `call_later` 或 `asyncio.create_task` 实现，不引入外部依赖。参考 R43 Hot Standby 看门狗的实现模式（`references/r43-hot-standby-watchdog-pattern.md`）。

---

## 5. 验收标准

### 方向 A：`!` 命令在工作频道可路由

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| A-1 | 工作频道（workspace）中发 `!step_complete StepN --output xxx` 被执行，状态机推进，点名下一角色 | 🔴 P0 |
| A-2 | 工作频道中发 `!pipeline_status` 返回正确的管线状态表格 | 🔴 P0 |
| A-3 | `!step_complete` 在工作频道执行时，权限校验仍有效（成员仅能完成自己的 Step） | 🔴 P0 |
| A-4 | 非 `!` 前缀的普通消息在工作频道中行为不变（仍按现有路由广播） | 🔴 P0 |
| A-5 | `_admin` 频道的 `!` 命令行为完全不变 | 🔴 P0 |
| A-6 | 工作频道中 `!` 命令的执行结果消息发回工作室，不污染 `_admin` 频道 | 🟡 P1 |
| A-7 | **（端到端）** 完整跑一轮管线：工作室中 `!step_complete` → 状态推进 → 点名 → 下一人在工作室中收到点名 → 继续 | 🔴 P0 |

### 方向 B：Agent 角色映射持久化

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| B-1 | 角色映射表存储在持久化 JSON 文件中（非代码层），重启不丢失 | 🔴 P0 |
| B-2 | `!pipeline_start` 创建工作室时，从映射表收集所有管线角色的 agent_id 加入工作区 | 🔴 P0 |
| B-3 | `!step_complete` 点名下一角色时，从映射表找出工作区中 role 匹配的 agent | 🔴 P0 |
| B-4 | 映射表为空时，回退到 `auth.get_users()` 按 role 字段匹配（向后兼容） | 🔴 P0 |
| B-5 | `!role_map list` 显示当前映射表 | 🟡 P1 |
| B-6 | `!role_map set <agent_id> <role>` 写入持久化文件 | 🟡 P1 |
| B-7 | `!role_map unset <agent_id>` 从映射表移除 | 🟡 P1 |
| B-8 | `!role_map reload` 不重启服务端重新加载持久化文件 | 🟡 P1 |

### 方向 C：管线 Step 超时检测

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| C-1 | `!step_complete` 点名下一角色时，自动注册该 Step 的超时计时器 | 🟡 P1 |
| C-2 | 超时前 N 分钟在工作室发催办通知（N 可配置） | 🟡 P1 |
| C-3 | 超时后在工作室内发 ⚠️ 超时告警 | 🟡 P1 |
| C-4 | 超时升级后向 `_admin` 频道写入升级通知 | 🟡 P1 |
| C-5 | 超时时间可配置（环境变量） | 🟢 P2 |
| C-6 | 超时检测不自动跳过 Step——只能通知，不能推进状态 | 🟢 P2 |
| C-7 | 服务端重启后恢复活跃管线的超时计时器（基于 `started_at` 计算剩余时间） | 🟡 P1 |
| C-8 | 前置决策区（Step A/B）无超时检测 | 🟢 P2 |

---

## 6. 不纳入本轮需求

- **❌ 纯自动化 TG 通知中间 Step 完成** — 方向 C 的超时通知只发到工作室和 `_admin`，不直接 TG 大宏。中间 Step 的进度汇报由 PM 在工作群看到后主动汇总给项目负责人
- **❌ Agent Card A2A 完整实现** — F-16 的「正确方向」（A2A 协议模式）范围太大。本轮只解决「角色映射持久化」让管线能匹配到人，Agent Card 完整声明机制留待后续调研
- **❌ 多 Step 并行执行** — 保持管线串行 6 步模式不变
- **❌ 管线自动跳过空闲 Step** — 所有 Step 按顺序执行，即使某角色不在线，超时后也只是通知，不跳过
- **❌ Web 端 Tab 修复（F-9）** — 不属本轮管线基础设施修复范畴
- **❌ 新虾注册流程完善（R36-B/C）** — 独立方向，非本轮范围
- **❌ 文档/代码脱敏（L-4/D-3/D-4）** — 不属本轮管线修复范畴

---

## 7. 设计要点

### 7.1 方向 A 的实现路径

`handle_broadcast` 函数中，在工作频道分支（当 `channel != p.LOBBY` 且 workspace 解析成功）的广播前添加：

```python
# 在 workspace 广播之前
if content.startswith('!'):
    cmd_info = _parse_command(content)
    if cmd_info and cmd_info.get('workspace_scope'):
        # 调用权限校验
        perm = _check_command_permission(cmd_info, sender_role, cmd_info.get('min_role', 4))
        if perm:
            result = _execute_command(cmd_info, content, ws_id, ...)
            # 返回结果到工作室
            ...
            return
    # 如果 workspace_scope=False 的 ! 命令 → 忽略（仅 _admin 可执行）
```

> **⚠️ 重要：** `_parse_command` 对 `content` 的解析是纯字符串处理（去除 `!` 前缀，按空格分割命令名和参数），不增加 AI 推理。此处的改动全部是纯系统层路由逻辑。

### 7.2 方向 B 的存储设计

持久化文件路径：`data/role_mapping.json`

```json
{
  "mappings": {
    "01KT6EDS8PMF0FTK1FCJ8V4TPH": "arch",
    "01KVJ87JDSZ6MDSHP8AYWZK694": "dev",
    "01KVS0PJDSZ6MDS8PAYWZK695": "review",
    "01KVT1QJDSZ6MDS9PAYWZK696": "qa"
  },
  "version": 1
}
```

`handler.py` 中新增 `_load_role_mapping()` 和 `_save_role_mapping()` 函数，并在 `_cmd_pipeline_start` 中按映射表收集工作区成员。

### 7.3 方向 C 的超时管理

使用 `asyncio` 的 `call_later` 实现超时调度：

```python
_pipeline_timeouts = {}  # round_name → asyncio.TimerHandle

def _schedule_timeout(round_name, step_name, timeout_minutes):
    # 取消已有计时器
    _cancel_timeout(round_name)
    # 注册新计时器
    loop = asyncio.get_event_loop()
    handle = loop.call_later(timeout_minutes * 60, _on_step_timeout, round_name, step_name)
    _pipeline_timeouts[round_name] = handle

def _on_step_timeout(round_name, step_name):
    # 发 ⏰ 催办到工作室
    # 再等升级时间 → 发 🚨 升级到 _admin
```

> **状态恢复：** 服务端启动时扫描 `_PIPELINE_STATE`，对有活跃管线的 Round 重新计算已过去时间并注册超时计时器。

---

## 8. 决策记录

> 以下决策由项目负责人在设计评审中确认：

| # | 问题 | 决策 | 体现位置 |
|:-:|:-----|:----|:---------|
| Q1 | 三个方向是否全部纳入本轮？ | ⏳ 待决策 | — |
| Q2 | 方向 A 的 `!` 路由是否要同时支持 lobby 中对 `!pipeline_start` 的解析？ | ⏳ 待决策 | — |
| Q3 | 角色映射表的管理是否必须通过 `!role_map` 命令，还是可以先手动编辑 JSON 文件？ | ⏳ 待决策 | — |
| Q4 | 超时时间默认值（30分钟/60分钟/其他）？ | ⏳ 待决策 | — |
| Q5 | 超时升级到 `_admin` 后，是否需要自动向 TG 发送通知？（当前设计是 PM 手动协调） | ⏳ 待决策 | 方向 C 约束 |

---

## 9. 风险与注意事项

- **🔴 方向 A 可能引入的命令冲突：** 工作频道中如果用户发的普通消息恰好以 `!` 开头（如提示 `!注意！xxx`），会被服务端误解析为命令。需确认 `!` 前缀在工作频道中的命中率，或要求命令格式必须是 `!command` 后跟空格（`!注意` → 不是空格后有命令名 → 忽略）
- **🟡 方向 B 的映射表管理运维负担：** 新增 `!role_map` 命令后，初始配置需要管理员逐条录入。可以提供 `!role_map import` 批量导入功能降低初始成本
- **🟡 方向 C 的超时与 restful 模式：** 容器重启后 `_pipeline_timeouts` 全部丢失。方向 C 的 §7.3 设计了恢复逻辑，但在 `_on_step_timeout` 回调触发前如果又有新的管线操作（`!step_complete`/`!pipeline_stop`），需要处理好竞争条件防止重复通知
- **🟢 三个方向无代码依赖冲突：** 方向 A（路由层）、方向 B（配置层）、方向 C（定时器层）在 handler.py 中影响不同的函数和模块，无代码冲突风险，可以平行开发
