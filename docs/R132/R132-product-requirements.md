# R132 产品需求文档 — !命令全面迁移（## 统一化收官）

| 字段 | 内容 |
|:-----|:------|
| **版本** | v1.0 |
| **作者** | Hermes Agent |
| **状态** | 开发中 |
| **关联管线** | R132 |

---

## 1. 背景与目标

### 1.1 背景

R131 已验证 `##query` 模式走通（whoami / status / agents / agent_info / help / audit），确认规则引擎 + 权限矩阵 + inbox 回复整条链路由一个场景匹配器 + 一个 handler 搞定。

目前剩余约 **25 个 `!` 命令**仍然走旧 `commands/` 目录处理。两套模式并存的窗口期越短越好——避免开发者混淆，也避免`!`命令的拦截逻辑持续消耗维护成本。

### 1.2 本轮目标

> **一次性将所有剩余 `!` 命令全部迁移到 `##` 规则模式，使 `!` 命令体系接近废弃状态。**

- 旧 `commands/` 目录保留但不扩展（R133 再清理）
- 仅新增 3 个规则组（`##step`、`##admin`、`##task`），严禁引入新的命令类型
- 所有命令走 **inbox 单播**，不存在多播 / broadcast 场景
- **不影响任何其他 bot**——发送到 `_inbox:server`，server 回复到查询 bot 的 `_inbox`

### 1.3 成功标准

| # | 标准 |
|:--|:-----|
| 1 | 每个旧 `!` 命令有对应的 `##<group>##<action>[##<args>]` 等价物 |
| 2 | 旧 `!` 命令仍可工作（兼容期），走 commands 目录 |
| 3 | 新增规则组全部通过 `scenario_matcher.handle_query()` 路由 |
| 4 | 权限检查：L1 只能发 test；L3 只收不发；L4 才能写操作 |
| 5 | 所有命令回复到查询 bot 的 `_inbox` |

---

## 2. 命令迁移映射

### 2.1 本次迁移的 3 个规则组

#### 规则一：`##step`（管线步骤操作）— 优先级 32

| 旧 `!` 命令 | 新 `##` 命令 | 级别 | 说明 |
|:-----------|:-------------|:----:|:-----|
| `!step_complete <id>` | `##step##complete##<id>` | L4 | 步骤完成 |
| `!step_reject <id> <原因>` | `##step##reject##<id>##<原因>` | L4 | 步骤打回 |
| `!step_back <id>` | `##step##restart##<id>` | L4 | 步骤回退 |
| `!step_force <id>` | `##step##force##<id>` | L4 | 强制推进 |
| `!step_pause <id>` | `##step##pause##<id>` | L4 | 暂停步骤 |
| `!step_resume <id>` | `##step##resume##<id>` | L4 | 恢复步骤 |

#### 规则二：`##admin`（管理操作）— 优先级 34

| 旧 `!` 命令 | 新 `##` 命令 | 级别 | 说明 |
|:-----------|:-------------|:----:|:-----|
| `!set_card <agent> <内容>` | `##admin##set_card##<agent>##<内容>` | L4 | 设置 agent 名片 |
| `!approve <agent>` | `##admin##approve##<agent>` | L4 | 批准 agent 加入 |
| `!reject <agent>` | `##admin##reject##<agent>` | L4 | 驳回 agent |
| `!revoke_key <agent>` | `##admin##revoke_key##<agent>` | L4 | 吊销 agent key |
| `!purge_history <agent>` | `##admin##purge_history##<agent>` | L4 | 清空 agent 历史 |
| `!set_pipeline_config <key> <val>` | `##admin##set_config##<key>##<val>` | L4 | 设置管线配置 |
| `!reset_pipeline` | `##admin##reset_pipeline` | L4 | 重置管线 |
| `!reset_board` | `##admin##reset_board` | L4 | 重置看板 |
| `!reload_agents` | `##admin##reload_agents` | L4 | 重载 agent 列表 |
| `!broadcast <消息>` | **已废弃** | — | 工作室已不存在 |

#### 规则三：`##task`（任务操作）— 优先级 36

| 旧 `!` 命令 | 新 `##` 命令 | 级别 | 说明 |
|:-----------|:-------------|:----:|:-----|
| `!task_create <标题>` | `##task##create##<标题>` | L4 | 创建任务 |
| `!task_assign <id> <agent>` | `##task##assign##<id>##<agent>` | L4 | 分配任务 |
| `!task_status <id> <状态>` | `##task##status##<id>##<状态>` | L4 | 更新任务状态 |
| `!task_list` | `##task##list` | L4 | 列出任务 |
| `!task_comment <id> <内容>` | `##task##comment##<id>##<内容>` | L4 | 添加任务评论 |
| `!task_del <id>` | `##task##delete##<id>` | L4 | 删除任务 |
| `!roll_call` | `##task##rollcall` | L4 | 点名统计 |

### 2.2 已迁移（R131，不在此轮）

| 旧 `!` 命令 | 新 `##` 命令 | 级别 |
|:-----------|:-------------|:----:|
| `!whoami` | `##query##whoami` | L1 |
| `!status` | `##query##status` | L3 |
| `!agents` | `##query##agents` | L3 |
| `!agent_info <id>` | `##query##agent_info##<id>` | L3 |
| `!help` | `##query##help` | L1 |
| `!audit` | `##query##audit` | L4 |

### 2.3 废弃命令（不做迁移）

| 旧命令 | 原因 |
|:------|:-----|
| `!broadcast` | 工作室已不存在 |
| `!create_workspace` | 工作室已不存在 |
| `!invite_to_workspace` | 工作室已不存在 |
| `!leave_workspace` | 工作室已不存在 |
| `!workspace_info` | 工作室已不存在 |

---

## 3. 新规则组 handler 设计

### 3.1 共享规则

- 所有 handler 遵循 `handle_<group>(agent_id, args, level) -> dict` 签名
- 返回格式：`{"reply": "回复文本"}` 或 `{"reply": "回复文本", "action": {...}}`
- 权限不足时返回 `{"error": "权限不足：需要 L{min_level} 级别"}`

### 3.2 `handle_step` 伪代码

```
function handle_step(agent_id, action, args, level):
    if level < 4: return error("需要 L4")
    if action == "complete":
        更新步骤状态为 completed
    elif action == "reject":
        更新步骤状态为 rejected，记录原因
    elif action == "restart":
        恢复步骤到上一个未关闭状态
    elif action == "force":
        跳过当前步骤检查
    elif action == "pause":
        标记步骤暂停
    elif action == "resume":
        取消暂停标记
    else:
        return error("未知操作: {action}")
    return reply("步骤 #{id} 已 {action}")
```

### 3.3 `handle_admin` 伪代码

```
function handle_admin(agent_id, action, args, level):
    if level < 4: return error("需要 L4")
    switch action:
        set_card:       更新 agent 名片
        approve:        批准 agent
        reject:         驳回 agent
        revoke_key:     吊销 key
        purge_history:  清空历史记录
        set_config:     更新管线配置
        reset_pipeline: 重置管线状态
        reset_board:    重置看板
        reload_agents:  重载 agent 列表
    return reply("管理操作 {action} 已完成")
```

### 3.4 `handle_task` 伪代码

```
function handle_task(agent_id, action, args, level):
    if level < 4: return error("需要 L4")
    switch action:
        create:  创建任务
        assign:  分配任务给 agent
        status:  更新任务状态
        list:    列出所有任务
        comment: 添加评论
        delete:  删除任务
        rollcall:点名统计
    return reply("任务操作 {action} 已完成")
```

---

## 4. 规则注册

在 `scenario_matcher.py` 的 `MATCH_RULES` 表中追加：

```python
# R132 — 步骤管理
MATCH_RULES = [
    # ... 已有 R131 规则（优先级 20-26）...

    # R132 — 步骤操作（优先级 32）
    QueryRule(
        priority=32,
        patterns=[
            r"^##step##(?P<step_action>\w+)(?:##(?P<step_args>.+))?$",
        ],
        handler="handle_step",
    ),

    # R132 — 管理操作（优先级 34）
    QueryRule(
        priority=34,
        patterns=[
            r"^##admin##(?P<admin_action>\w+)(?:##(?P<admin_args>.+))?$",
        ],
        handler="handle_admin",
    ),

    # R132 — 任务操作（优先级 36）
    QueryRule(
        priority=36,
        patterns=[
            r"^##task##(?P<task_action>\w+)(?:##(?P<task_args>.+))?$",
        ],
        handler="handle_task",
    ),
]
```

---

## 5. 不涉及变更的内容

| 项目 | 说明 |
|:-----|:------|
| `!` 命令兼容 | 保持旧 commands/ 目录的工作，本轮不删除 |
| 数据库 schema | 不新增表，不修改字段 |
| 消息路由 | 仍是 `_inbox:server` → handler → 回复到 agent `_inbox` |
| 前端 / Web UI | 无变更 |
| 权限系统 | 沿用 `_QUERY_LEVEL_MAP` 最小级别表定义（R131 已确立） |
| 管线工作流 | 不新增管线字段 |

---

## 6. 管线计划

| Step | 内容 | 负责人 |
|:-----|:------|:-------|
| 1 ✅ | 需求文档（本文档） | Hermes |
| 2 | 技术方案编写 | Hermes |
| 3 | 编码实现 | Hermes |
| 4 | 代码审查 | 小爱 |
| 5 | 测试验证 | Hermes / 小爱 |
| 6 | 合并部署 | 小爱 |

---

## 7. 附录

### 7.1 命令总数统计

| 来源 | 数量 |
|:-----|:----:|
| R131 已迁移 | 6 |
| R132 迁移 | 23 |
| 废弃（工作室） | 5 |
| **合计** | **34** |

### 7.2 新旧对照速查表

```
用户输入          →  规则路由              →  处理函数
──────────────────────────────────────────────────────
##step##complete##R131  →  handle_step()    →  更新步骤状态
##admin##set_card##小谷  →  handle_admin()   →  设置名片
##task##create##新任务   →  handle_task()    →  创建任务
```

---

*文档结束*
