# R132 产品需求文档 — !命令全面迁移（## 统一化收官）

| 字段 | 内容 |
|:-----|:------|
| **版本** | v2.0 |
| **作者** | Hermes Agent |
| **状态** | 开发中 |
| **关联管线** | R132 |

---

## 1. 背景与目标

### 1.1 背景

R131 已验证 `##query` 模式走通（whoami / status / agents / agent_info / help / audit），确认规则引擎 + 权限矩阵 + inbox 回复整条链路由一个场景匹配器 + 一个 handler 搞定。

目前剩余部分 `!` 命令仍然走旧 `commands/` 目录处理。两套模式并存的窗口期越短越好——避免开发者混淆，也避免 `!` 命令的拦截逻辑持续消耗维护成本。

### 1.2 本轮目标

> **将剩余 `!` 命令一次性迁移或清理，使 `!` 命令体系接近废弃状态。**

本轮仅新增 **1 个规则组**（`##step`）。`##admin` 和 `##task` 规则组已取消——`admin` 角色已不存在，`task` 功能已被管线任务替代。

### 1.3 变更范围

| 规则组 | 操作 | 原因 |
|:-------|:----:|:------|
| `##step`（步骤操作） | ✅ **迁移** | 管线步骤操作仍需使用 |
| `##admin`（管理操作） | ❌ **废弃** | admin 角色已不存在 |
| `##task`（任务操作） | ❌ **废弃** | 已被管线任务替代 |

### 1.4 成功标准

| # | 标准 |
|:--|:-----|
| 1 | 步骤相关 `!` 命令有对应的 `##step##<action>##<args>` 等价物 |
| 2 | 旧 `!` 命令仍可工作（兼容期），走 commands 目录 |
| 3 | 新增规则组通过 `scenario_matcher.handle_query()` 路由 |
| 4 | 权限检查：L1 只能发 test；L3 只收不发；L4 才能写操作 |
| 5 | 所有命令回复到查询 bot 的 `_inbox` |

---

## 2. 命令迁移映射

### 2.1 本次迁移：`##step`（管线步骤操作）— 优先级 32

| 旧 `!` 命令 | 新 `##step` 命令 | 级别 | 说明 |
|:-----------|:-----------------|:----:|:-----|
| `!step_complete <id>` | `##step##complete##<id>` | L4 | 步骤完成 |
| `!step_reject <id> <原因>` | `##step##reject##<id>##<原因>` | L4 | 步骤打回 |
| `!step_back <id>` | `##step##restart##<id>` | L4 | 步骤回退 |
| `!step_force <id>` | `##step##force##<id>` | L4 | 强制推进 |
| `!step_pause <id>` | `##step##pause##<id>` | L4 | 暂停步骤 |
| `!step_resume <id>` | `##step##resume##<id>` | L4 | 恢复步骤 |

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
|:------|:------|
| `!set_card` | admin 角色已不存在 |
| `!approve` | admin 角色已不存在 |
| `!reject` | admin 角色已不存在 |
| `!revoke_key` | admin 角色已不存在 |
| `!purge_history` | admin 角色已不存在 |
| `!set_pipeline_config` | admin 角色已不存在 |
| `!reset_pipeline` | admin 角色已不存在 |
| `!reset_board` | admin 角色已不存在 |
| `!reload_agents` | admin 角色已不存在 |
| `!broadcast` | 工作室已不存在 |
| `!task_create` | 已被管线任务替代 |
| `!task_assign` | 已被管线任务替代 |
| `!task_status` | 已被管线任务替代 |
| `!task_list` | 已被管线任务替代 |
| `!task_comment` | 已被管线任务替代 |
| `!task_del` | 已被管线任务替代 |
| `!roll_call` | 已被管线任务替代 |
| `!create_workspace` | 工作室已不存在 |
| `!invite_to_workspace` | 工作室已不存在 |
| `!leave_workspace` | 工作室已不存在 |
| `!workspace_info` | 工作室已不存在 |

---

## 3. `##step` Handler 设计

### 3.1 签名

```python
def handle_step(agent_id: str, action: str, args: str, level: int) -> dict:
    """
    处理 ##step 命令
    
    返回: {"reply": "..."} 或 {"error": "..."}
    """
```

### 3.2 伪代码

```
function handle_step(agent_id, action, args, level):
    if level < 4:
        return {"error": "权限不足：需要 L4 级别"}
    
    switch action:
        case "complete":
            step_id = args
            更新 pipeline_engine 中步骤状态为 completed
            return {"reply": f"步骤 #{step_id} 已完成 ✅"}
        
        case "reject":
            parts = args.split("##", 1)
            step_id = parts[0]
            reason = parts[1] if len(parts) > 1 else ""
            更新步骤状态为 rejected，记录原因
            return {"reply": f"步骤 #{step_id} 已打回：{reason}"}
        
        case "restart":
            step_id = args
            恢复步骤到上一个未关闭状态
            return {"reply": f"步骤 #{step_id} 已重启"}
        
        case "force":
            step_id = args
            跳过当前步骤检查，强制推进
            return {"reply": f"步骤 #{step_id} 已强制推进"}
        
        case "pause":
            step_id = args
            标记步骤暂停
            return {"reply": f"步骤 #{step_id} 已暂停 ⏸️"}
        
        case "resume":
            step_id = args
            取消暂停标记
            return {"reply": f"步骤 #{step_id} 已恢复 ▶️"}
        
        default:
            return {"error": f"未知步骤操作: {action}"}
```

### 3.3 权限

在 `_QUERY_LEVEL_MAP` 中追加：

```python
_QUERY_LEVEL_MAP = {
    # R131
    "whoami": 1, "help": 1,
    "status": 3, "agents": 3, "agent_info": 3,
    "audit": 4,
    # R132
    "step": 4,
}
```

---

## 4. 规则注册

在 `scenario_matcher.py` 的 `MATCH_RULES` 表中追加：

```python
# R132 — 步骤操作（优先级 32）
QueryRule(
    priority=32,
    patterns=[
        r"^##step##(?P<step_action>\w+)(?:##(?P<step_args>.+))?$",
    ],
    handler="handle_step",
),
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
| R132 迁移（##step） | 6 |
| 废弃（admin / task / workspace） | 21 |
| **合计** | **33** |

### 7.2 新旧对照速查表

```
用户输入                           →  规则路由         →  处理函数
──────────────────────────────────────────────────────────────────
##step##complete##R131             →  handle_step()   →  更新步骤状态
##step##reject##R131##bug太多      →  handle_step()   →  步骤打回
##step##restart##R131              →  handle_step()   →  步骤回退重启
##step##force##R132                →  handle_step()   →  强制推进
##step##pause##R132               →  handle_step()   →  暂停步骤
##step##resume##R132              →  handle_step()   →  恢复步骤
```

---

*文档结束*
