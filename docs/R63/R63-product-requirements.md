# R63 产品需求 — 多 Agent 协作基础设施（过渡轮次）

> **版本：** v1.0（初稿，待项目负责人审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-01
> **本轮改动范围：** `server/handler.py` + `server/timeout_tracker.py`（新增）+ `server/agent_card.py` + `server/config.py`
> **参考：** R62 需求文档、A2A 协议实践（多 Agent 协作模式）、R61 管线跳过 Step 状态丢失经验

---

## 1. 问题背景

### 1.1 多 Agent 协作模式的真实需求

ws-bridge 的开发模式本质是 **多 Agent 协作 = A2A 协议实践**：

| 角色 | 职责 |
|:----:|:------|
| 🧐 **PM / 需求分析师** | 需求分析 + 跨 Step 总协调/总调度 |
| 🏗️ **架构师 (arch)** | 技术方案 |
| 💻 **开发工程师 (dev)** | 编码实现 |
| 🔍 **审查工程师 (review)** | 代码审查 |
| 🦐 **测试工程师 (qa)** | 测试验证 |
| 🛠️ **项目管理 (admin)** | 合并部署归档 |
| 👤 **项目负责人** | TG 私聊决策，拍板方向 |

但当前实现存在 **三个核心断裂**：

### 1.2 断裂 1：无 Step 预期完成时间/倒计时

**现状：** WORK_PLAN 中写了各 step 的预期完成时间（如 `timeout_minutes: 15`），但管线引擎从不使用它。

**现有相关机制：**
- `config.py` 中有 `PIPELINE_STEP_MAP`，含 `timeout_hours` 字段（以小时为单位的超时阈值）
- `handler.py` 有 `_watchdog_loop()`，每 10 分钟扫描一次，超时后向 PM 告警
- `_PIPELINE_STATE` 记录 `started_at`，但**没有倒计时心跳**、**没有 step 切换时自动清除旧倒计时**

**问题：**
| 现象 | 根因 |
|:-----|:------|
| PM 不知道当前 step 还省多少时间 | 机器运行时没有倒计时状态，只有 10 分钟一次的扫描 |
| step 完成换到下一步，旧超时还在告警 | 没有 step-complete → 清除超时的关联逻辑 |
| 超时了只能被动等 watchDoc 扫描 | 没有 step 激活时立即启动的精确计时器 |

### 1.3 断裂 2：Agent Card 与 Step 路由未集成

**现状：** Agent Card 已存在但仅用于信息展示（`!agent_card list` / `!agent_card set`），**没有参与 Step 路由**。

| 组件 | 数据存储 | 用途 | 问题 |
|:-----|:---------|:-----|:-----|
| `handler.py` `_load_agent_cards()` | `data/agent_cards.json` | 管线启动时收集成员、显示名 | 不参与 step 流转查找 |
| `agent_card.py` | `config/agent_cards.json` | 静态配置加载 | 运行时索引可能不同步 |
| `_find_agents_by_role()` | 已实现但未被 `_cmd_step_complete` 调用 | 不存在于 step 流转路径中 | 🚫 |
| `auth.get_users().role` | 运行时用户表 | 当前 step 路由 | **所有 bot role=member，不匹配 arch/dev/review/qa → 自动点名失败 F-16** |

**核心 gap：** 没有 **"注册"** 流程——各 agent 在加入开发团队或报道时，应把自己的能力注册到服务端，形成一个 **角色 ↔ Agent 的映射表**。管线流转时通过角色名查映射表找到具体 agent 派活。

### 1.4 断裂 3：派活无 ACK 保障

**现状：** Step 交接时，系统发一条文本通知到工作室，期望被点名的 bot 看到后开始干活。但：

| 环节 | 当前行为 | 问题 |
|:-----|:---------|:-----|
| 消息发出 | `_send_to_agent()` 或工作室广播 | bot 在线但网关静默丢弃（`from_name="系统"` 问题） |
| bot 是否收到 | 无反馈确认 | 发了等于没发，PM 不知道 |
| bot 是否开始干 | 无 ACK 机制 | 干到一半停摆也无感知 |
| 超时后 | 10 分钟 watchdog 扫描 | 太长，且 notity 可能被忽略 |

**根本原因：** 派发 = 单向文本消息，不是双向确认的协议交互。

### 1.5 多轮教训汇总

| 轮次 | 教训 | 指向 |
|:----|:-----|:-----|
| R55 | `_send_to_agent` 静默丢失 | ACK 机制缺失 |
| R57 | bot 被点名但不响应（`from_name` 问题） | 触发需 ACK 保障 |
| R58 | `from_name` 值决定 arch 是否触发 | Agent Card 应定义触发偏好 |
| R60 | Gateway 身份冲突（bot_name 设错） | 注册流程应写入映射表 |
| R61 | Step 跳过→管线状态丢失 | 定时器需在 step 切换时自动清理 |
| R62 | frontmatter 配置**未部署到代码** | R63 需实际落地参数化 |

---

## 2. 功能需求

### 设计原则

> **双轨过渡：** 新能力灰度上线，旧路径完整保留。条件不具备时静默退化到当前行为。
> **有状态的派发：** 从单向文本通知升级为双向确认协议。
> **人机分离：** Agent Card 是人可读、机器可用的结构化数据，不写在硬编码里。
> **倒计时驱动协调：** PM 的介入由精确计时触发，而非被动轮询。

---

### 方向 A（核心）：Step 倒计时参数 + 心跳机制 🔴 P0

**目标：** 将 WORK_PLAN 预期的 step 完成时间纳入管线运行时，step 激活时启动精确倒计时，心跳反馈剩余时间，超时触发 PM 协调，step 完成时自动清除。

#### A1 — 参数定义：WORK_PLAN frontmatter 集成 `timeout_minutes`

在 WORK_PLAN YAML frontmatter 的每个 step 定义中，已有 `timeout_minutes` 字段（R62 schema 定义但未部署）。R63 将其落地为可消费参数：

```yaml
steps:
  step2:
    role: arch
    title: 技术方案
    timeout_minutes: 15        # ✅ 已有字段
    escalation: notify_pm      # ✅ 已有字段
```

**消费路径：**
```
!pipeline_start → 读 WORK_PLAN
    ├─ 解析 frontmatter → 取 steps.stepN.timeout_minutes
    └─ 无 frontmatter → 退化：从 PIPELINE_STEP_MAP 读 timeout_hours（旧行为）
```

**参数定义在 `_PIPELINE_CONFIG` 中：**
```python
_PIPELINE_CONFIG[round_name] = {
    "steps": {
        "step2": {
            "role": "arch",
            "timeout_minutes": 15,
            ...
        },
        ...
    }
}
```

**⚠️ 注意：** `_PIPELINE_CONFIG` 和 `_parse_frontmatter()` 在 R62 已文档化但**实际代码未部署**。R63 需从头实现。

#### A2 — Step 级倒计时跟踪器

**新增文件：** `server/timeout_tracker.py`

独立模块管理倒计时，与 `_PIPELINE_STATE` 解耦：

```python
# timeout_tracker.py 概念设计

_timeout_timers: dict[str, dict] = {}
# key = "{round_name}/{step_name}"
# value = {"deadline": float, "notified": bool, "pm_escalated": bool}

def start_timer(round_name: str, step_name: str, timeout_minutes: int) -> None:
    """Start countdown for a step. Clears previous timer for same round."""
    clear_timer(round_name)  # 先清旧计时
    deadline = time.time() + timeout_minutes * 60
    _timeout_timers[f"{round_name}/{step_name}"] = {
        "deadline": deadline,
        "notified": False,
        "pm_escalated": False,
    }

def clear_timer(round_name: str) -> None:
    """Clear all timers for a round (called on step complete / handoff)."""
    keys = [k for k in _timeout_timers if k.startswith(f"{round_name}/")]
    for k in keys:
        del _timeout_timers[k]

def get_remaining(round_name: str, step_name: str) -> float:
    """Get remaining seconds for a step. Returns 0 if not set or expired."""
    timer = _timeout_timers.get(f"{round_name}/{step_name}")
    if not timer:
        return 0.0
    remaining = timer["deadline"] - time.time()
    return max(0.0, remaining)

def is_expired(round_name: str, step_name: str) -> bool:
    """Check if timer has expired."""
    remaining = get_remaining(round_name, step_name)
    return remaining <= 0
```

#### A3 — 倒计时心跳 + 超时触发

**心跳输出** — 通过 `!pipeline_status` 展示：

```
📊 R63 管线状态
  当前 Step: step2 (技术方案)
  ⏱ 剩余时间: 12分30秒 / 15分钟
  📨 状态: 已通知 (等待 ACK)
  ...
```

**超时触发** — 倒计时归零时：

1. 发送告警到工作室（`@PM` 点名）
2. 同步告警到 `_admin` 频道
3. 告警信息含：轮次、step、预期完成时长、已超时时间
4. 超时后状态更新为 `⏰ 超时待协调`

**触发 PM 协调消息格式：**

```
⏰ [超时告警] R63 Step2 技术方案
━━━━━━━━━━━━━━━
⏱ 预期完成时间: 15分钟
🕐 已超时: 2分钟
🎯 当前角色: arch
━━━━━━━━━━━━━━━
请 PM 协调：是否跳过 / 换人 / 手动干预
```

**PM 的协调响应链路：**
- PM 在 TG 私聊收到超时通知
- 决策方向：等待、换备选、跳过、手动驱动
- PM 的决策通过 TG DM 协调项目负责人后，再在工作室内执行

#### A4 — Step 切换时自动清理倒计时

在以下入口清除定时器：

| 触发点 | 函数 | 行为 |
|:------|:-----|:-----|
| `!step_complete` | `_cmd_step_complete()` | 完成当前 step → 清除当前 round 所有定时器 → 启动下一步定时器 |
| `!step_handoff` | `_cmd_step_handoff()` | 跳过当前 step → 同上 |
| `!pipeline_activate` | `_cmd_pipeline_activate()` | 激活管线 → 启动当前 step 定时器 |
| 管线关闭 | `!close_workspace` 路径 | 清除所有定时器 |

#### A5 — 依赖：R62 `_PIPELINE_CONFIG` 基础实现

由于 R62 的 `_PIPELINE_CONFIG` 和 frontmatter 解析器 **实际未部署到代码**，R63 需完成这个前置工作：

| # | 组件 | 说明 |
|:-:|:-----|:------|
| A5-a | `_PIPELINE_CONFIG: dict[str, dict] = {}` | 全局 dict，与 `_PIPELINE_STATE` 并列 |
| A5-b | `_parse_frontmatter(content) → dict` | 解析 WORK_PLAN 的 `---...---` 段 |
| A5-c | `_build_pipeline_config(fm, round, urls) → dict` | 填充 `${pipeline.xxx}` 模板变量 |
| A5-d | `_build_fallback_config(round, urls) → dict` | 旧格式退化，从 `PIPELINE_STEP_MAP` 生成 |
| A5-e | `_cmd_pipeline_start` → 解析 frontmatter → 生成 config | 管线启动入口 |
| A5-f | `_clear_pipeline_state()` → **不清理** `_PIPELINE_CONFIG` | 配置层/运行时层分离 |

**验收条件：** R62 ✅-1 ~ ✅-12 全部通过（见 §3.3）

---

### 方向 B（核心）：Agent Card 注册 + 角色↔Agent 映射表 🔴 P0

**目标：** 各 Agent 在加入开发团队时注册自己的能力，服务端维护一张角色↔Agent 绑定表。Step 流转通过映射表定向派活。

#### B1 — Agent Card schema 扩展

当前 Agent Card 结构：

```json
{
  "agent_id_123": {
    "name": "开发工程师",
    "display_name": "开发工程师",
    "pipeline_roles": ["dev"],
    "skills": ["coding", "python", "ws-bridge"],
    "status": "online"
  }
}
```

扩展为包含注册和触发偏好：

```json
{
  "agent_id_123": {
    "name": "开发工程师",
    "display_name": "开发工程师",
    "pipeline_roles": ["dev"],
    "skills": ["coding", "python", "ws-bridge"],
    "status": "online",
    "registered_at": 1734567890.0,
    "last_online": 1734567890.0,
    "trigger_preference": {
      "mode": "mention",       // "mention" | "direct" | "both"
      "mention_keyword": "开发工程师",
      "ack_timeout_sec": 60    // 期望 ACK 超时时间
    },
    "capabilities": {
      "platforms": ["ws-bridge", "telegram"],
      "can_code": true,
      "can_review": true,
      "can_deploy": false
    }
  }
}
```

#### B2 — 注册流程（报道即注册）

**入口设计：** 管线启动时的点名环节（`!rollcall` / `!rollcall_role`）同时作为注册触发点。

**注册流程：**

```
管线启动 → !rollcall → 全员点名
    │
    ├─ Agent 回复「到」
    ├─ 服务端收到回复
    │   ├─ Agent ID 已在映射表中 → 更新 last_online + status=online
    │   └─ Agent ID 不在映射表中 → 自动注册（走 B3 智能注册）
    └─ 注册完成后，输出映射表验证
```

#### B3 — 智能注册（第一阶段：自动发现）

当点名时新 agent 回复，但无已有 Agent Card：

| 步骤 | 行为 |
|:----|:-----|
| ① | 从 `auth.get_users()` 取 agent 的 `name`、`role` |
| ② | 从 `_connections` 确认在线 |
| ③ | 自动创建 Agent Card：`agent_id → {name, display_name=name, pipeline_roles=[role], status=online}` |
| ④ | 写 `data/agent_cards.json` 持久化 |

**智能注册不覆盖已有 card**——手动设置的 card 自动获得更高优先级。

#### B4 — 角色↔Agent 映射表

**运行时映射表：**

```python
_ROLE_AGENT_MAP: dict[str, list[str]] = {}
# key = pipeline_role (arch/dev/review/qa/admin)
# value = [agent_id_primary, agent_id_backup, ...]
```

建立方式（两个原则）：

| 原则 | 逻辑 |
|:----|:------|
| **明确绑定优先** | Agent Card 中 `pipeline_roles` 字段 → `_ROLE_AGENT_MAP[role] = [aid]` |
| **默认补全** | 无 card 的角色 → 从 `auth.get_users().role` 补全（当前行为，退化兼容） |

**查询 API：**

```python
def get_agents_by_role(role: str) -> list[str]:
    """Get registered agents for a pipeline role.
    Falls back to auth.get_users() if no card registered.
    """
    agents = _ROLE_AGENT_MAP.get(role, [])
    if agents:
        return agents
    # Fallback: auth users
    users = auth.get_users()
    return [aid for aid, u in users.items() if u.get("role", "") == role]
```

#### B5 — Step 路由改造

**`_cmd_step_complete()` 中查找下一角色 agent：**

```python
# 当前：auth.get_users().role 查找（F-16 失败）
next_agents = [
    aid for aid in ws_obj.members
    if auth.get_users().get(aid, {}).get("role", "") == next_role
]

# R63：通过映射表查找
next_agents = get_agents_by_role(next_role)
# 过滤出在工作区内的成员
next_agents = [a for a in next_agents if a in ws_obj.members]
```

**`!rollcall_role` 替换逻辑 - `_cmd_step_handoff` - 同理。**

#### B6 — 管理命令增强

| 命令 | 功能 |
|:-----|:------|
| `!agent_card register <agent_id>` | 强制注册/更新某 agent 的 card |
| `!agent_card auto-register` | 扫描所有在线 agent，自动补全缺失的 card |
| `!agent_role_map` | 展示当前角色↔Agent 映射表 |
| `!agent_role_map --refresh` | 从 Agent Card 重建映射表 |

---

### 方向 C（核心）：ACK 保障的触发机制 🔴 P0

**目标：** 向 Agent 派活不再是单向文本通知，而是带确认协议的递送链。

#### C1 — 发送状态机

```
         (1)              (2)              (3)                (4)
  SENT ──────→ DELIVERED ──────→ ACKNOWLEDGED ──────→ IN_PROGRESS
    │              │                 │                     │
    │              │                 │                     │
    └─ 超时 30s ───┘── 无 ACK → 标记 FAILED ─── 触发 PM 协调
                   │                               
                   └─ 有 ACK → 推进到 ACKNOWLEDGED
                                     │
                                     └─ bot 回复「收到」→ 推进到 IN_PROGRESS
```

| 状态 | 含义 | 存储位置 | 触发 |
|:----|:-----|:---------|:-----|
| `SENT` | 消息已通过 WS 发出 | `_PIPELINE_STATE[round]["assignment"][step]` | `_cmd_step_complete()` 发出通知时 |
| `DELIVERED` | delivery ACK 返回（`sent: N`） | 同上 | WS 返回 delivery 确认 |
| `ACKNOWLEDGED` | bot 回复了「到」/「收到」 | 同上 | bot 在工作室回消息 |
| `IN_PROGRESS` | bot 确认开始执行任务 | 同上 | bot 回复明确开始信号 |
| `FAILED` | 超时无人认领 | 同上 | 30 秒无 ACK 触发 |

#### C2 — Delivery ACK + Bot ACK 双通道

**Delivery ACK（协议层确认）：**
- 消息发出后，WS 返回 `{"type": "ack", "delivery": {"total": 5, "sent": 5}}`
- 解析 delivery 字段，如果 `sent == 0` → 目标离线 → 立即切换备用
- 如果 `sent > 0` → `DELIVERED`

**Bot ACK（应用层确认）：**
- 被点名的 bot 在工作室内回复任何消息 → 视作 ACK
- 如果在 `ack_timeout_sec` 内无回复 → `FAILED`
- 如果 bot 的回复显式包含「收到」「好的」「在」「到」→ `ACKNOWLEDGED → IN_PROGRESS`

**超时计时器：**
```
派发 → 启动 30 秒 ACK 定时器
    ├─ 30 秒内收到 ACK → 清除定时器，状态 ACKNOWLEDGED
    ├─ 30 秒内收到 delivery sent=0 → 立即切换备用
    └─ 30 秒超时 → 标记 FAILED，触发 PM 协调
```

#### C3 — PM 协调触发

ACK 超时后：

| 触发场景 | PM 收到的消息 |
|:---------|:--------------|
| Failure: no delivery | `📮 [派发失败] R63 Step3 — 开发工程师 不在线，无法送达` |
| Failure: no ack | `🕐 [ACK 超时] R63 Step3 — 开发工程师 30 秒无确认` |

**PM 的决策：**

```
[ACK 超时] R63 Step3 开发工程师 30秒无确认
━━━━━━━━━━━━━━━
请 PM 协调：
1. 等待 → 继续等待（手动输入 wait）
2. 换备用 → 自动切换备用 Agent
3. 手动驱动 → PM 手动 @mention 任务
4. 跳过 → !step_handoff 跳过此步
```

#### C4 — Step 任务分配中的 ACK 集成

```python
# _cmd_step_complete 中派发任务的伪代码

async def _assign_step_agent(round_name, step_name, target_agent_id, context_msg):
    # 1. 发送消息到工作室
    ack_key = f"{round_name}/{step_name}/ack"
    _step_ack_states[ack_key] = {
        "state": "SENT",
        "agent_id": target_agent_id,
        "sent_at": time.time(),
        "deadline": time.time() + ACK_TIMEOUT_SEC,
    }
    
    # 2. 发消息
    await broadcast_to_workspace(ws_id, pm_name, context_msg)
    
    # 3. 启动 ACK 定时器
    asyncio.create_task(_ack_timeout_task(ack_key))
    
    # 4. 等待（函数返回，ack 由异步任务监控）
    return ack_key

async def _ack_timeout_task(ack_key: str) -> None:
    await asyncio.sleep(ACK_TIMEOUT_SEC)
    state = _step_ack_states.get(ack_key, {})
    if state.get("state") in ("SENT", "DELIVERED"):
        state["state"] = "FAILED"
        # 触发 PM 协调
        await _trigger_pm_escalation(ack_key, state)
```

#### C5 — ACK 状态展示

在 `!pipeline_status` 中集成：

```
📊 R63 管线状态
  当前 Step: step3 (编码实现)
  ⏱ 剩余: 18分 / 25分钟
  🎯 目标: 开发工程师
  📨 派发状态: ✅ DELIVERED → 等待 ACK (已过 8秒)
  ── 或 ──
  📨 派发状态: ✅ ACKNOWLEDGED (4秒确认)
```

---

### 方向 D（辅助）：过渡兼容 — 双轨并行 🟡 P2

**目标：** 在新基础设施（倒计时/Agent Card/ACK）条件不具备时，管线仍能使用旧路径完成开发工作。

**双轨策略：**

| 新能力 | 具备时 | 不具备时退化到 |
|:-------|:-------|:--------------|
| frontmatter + `_PIPELINE_CONFIG` | 参数化驱动 step 配置 | 从 `PIPELINE_STEP_MAP` + 硬编码 URL |
| step 倒计时 | 精确心跳 + 超时自动协调 | 10 分钟 watchdog 扫描 + PM 手动检查 |
| Agent Card 注册 → 角色映射表 | 映射表路由 + 自动派活 | `auth.get_users().role` + PM 手动 @mention |
| ACK 保障 | 状态机管理派发 | 单向文本通知 + PM 目视确认 |

**退化开关：** 引入全局 flag：

```python
_ENABLE_R63_TIMEOUT: bool = True      # True=新倒计时, False=退回 watchdog
_ENABLE_R63_AGENT_MAP: bool = True    # True=映射表路由, False=旧 auth lookup
_ENABLE_R63_ACK: bool = True          # True=ACK 状态机, False=单向通知
```

每个开关独立——A 能力已经就绪但 C 还不成熟时，不影响 A 的使用。

**配置方式：** 环境变量 `R63_ENABLE_TIMEOUT=1` / `R63_ENABLE_AGENT_MAP=1` / `R63_ENABLE_ACK=1`

---

### 方向 E（辅助）：旧 bug 顺手修复 🟡 P2

在实现 A/B/C/D 的过程中，顺手修复以下长期遗留问题：

| # | Bug | 位置 | 修复方式 |
|:-:|:-----|:-----|:---------|
| E1 | `_send_to_agent` with `from_name="系统"` → bot 不触发工作模式 | handler.py | 所有 Step 交接通知改用 `config.PIPELINE_PM_NAME` 作为 `from_name`（R58 方向但 arch/dev 仍不响应，需验证） |
| E2 | F-16: `auth.get_users().role` 全部为 `member`，角色匹配失败 | handler.py | 方向 B 的 Agent Card 映射表解决此问题 |
| E3 | `!step_handoff` 跳过 Step 后状态丢失 | handler.py | 方向 A 的 `_PIPELINE_CONFIG` 分离解决 |
| E4 | WS 心跳超时被动（10 分钟扫描） | handler.py | 方向 A 的精确倒计时替代 |

---

## 3. 验收标准

### 🎯 3.1 方向 A（倒计时 + 心跳）

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-1 | `timeout_minutes` 参数从 frontmatter 读入 `_PIPELINE_CONFIG` | 带 frontmatter 的 WORK_PLAN → step config 含 timeout_minutes |
| ✅-2 | 无 frontmatter 的旧 WORK_PLAN → 从 PIPELINE_STEP_MAP 读 timeout_hours | 静默退化，不报错 |
| ✅-3 | step 激活后启动精确倒计时（不是 10 分钟扫描） | step 切换到！step_complete → 立即启动定时器 |
| ✅-4 | `!pipeline_status` 显示剩余时间 | 格式：`⏱ 剩余：12分30秒 / 15分钟` |
| ✅-5 | 倒计时归零触发 PM 告警 | 工作室收到 `@PM` 通知 + `_admin` 频道告警 |
| ✅-6 | Step 完成（!step_complete）→ 自动清除旧倒计时，启动下一步倒计时 | 定时器不叠加，剩余时间正确 |
| ✅-7 | Step 跳过（!step_handoff）→ 清除当前 round 定时器 | 无残留定时器干扰 |
| ✅-8 | 管线关闭后所有定时器清除 | `!close_workspace` 后 `get_remaining()` 全返回 0 |

### 🎯 3.2 方向 B（Agent Card + 角色映射）

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-9 | Agent 回复点名 → 自动注册/更新 Agent Card | 不在映射表中 → 自动创建；已在 → 更新 last_online |
| ✅-10 | Agent Card schema 扩展含 trigger_preference / capabilities / registered_at | 新增字段可选（不破坏旧 card 读取） |
| ✅-11 | `_ROLE_AGENT_MAP` 从 Agent Card pipeline_roles 构建 | 映射表正确反映 arc/dev/review/qa/admin 对应关系 |
| ✅-12 | `get_agents_by_role()` 先查映射表，回退 auth.get_users() | 有 card → 映射表；无 card → 旧角色字段 |
| ✅-13 | `!step_complete` 用映射表查找下一角色 agent | 不再报「工作区中未找到角色为 dev 的成员」(F-16 解决) |
| ✅-14 | `!agent_role_map` 展示映射表 | 格式：`dev → 开发工程师 | review → 审查工程师 | ...` |

### 🎯 3.3 方向 C（ACK 保障）

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-15 | Step 交接消息发出后 → 状态 SENT → delivery ack → DELIVERED | 状态机顺序正确 |
| ✅-16 | 目标 bot 回复「到」/「收到」→ ACKNOWLEDGED → IN_PROGRESS | 应用层 ACK 正确解析 |
| ✅-17 | 30 秒无 ACK → 触发 PM 协调 | PM 收到超时告警 |
| ✅-18 | delivery sent=0 → 立即切换备用 | 目标离线时不等待 30 秒 |
| ✅-19 | `!pipeline_status` 显示派发状态 | `📨 SENT → DELIVERED → ✅ ACK (4秒)` |

### 🎯 3.4 方向 D（过渡兼容）

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-20 | 关闭所有 R63 开关 → 管线行为与 R61 一致 | 旧路径完整可用 |
| ✅-21 | 单独开 timeout 但关 agent_map → 倒计时工作，路由走旧路径 | 开关独立生效 |
| ✅-22 | 无 frontmatter 旧 WORK_PLAN → 无报错启动 | 静默退化 |

### 🎯 3.5 R62 恢复验收（方向 A5）

| # | 检查项 | 预期结果 |
|:-:|:-------|:---------|
| ✅-23 | `!pipeline_start` 解析 frontmatter → 生成 `_PIPELINE_CONFIG` | 无报错 |
| ✅-24 | `_PIPELINE_CONFIG` 与 `_PIPELINE_STATE` 分离 | state 清空后 config 独立存在 |
| ✅-25 | `!step_complete` 从 config 读参数（URL/role/title） | 非硬编码 |
| ✅-26 | `!step_handoff` 从 config 读下一 step | 非硬编码排序 |
| ✅-27 | state 丢失后 `!pipeline_status` 仍可读 config | 展示 step 列表 |
| ✅-28 | 旧格式 WORK_PLAN → 退化到 `_build_fallback_config` | 写一条日志通知 |
| ✅-29 | frontmatter 格式错误 → 静默退化 | 不阻塞管线 |
| ✅-30 | 正常流转与改造前一致 | step1→step2→...→step6 完整链条 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| 持久化 `_PIPELINE_CONFIG` 到磁盘 | 只保存在进程内存 | 服务重启后由下次 `!pipeline_start` 重建 |
| Web 端倒计时 UI | 不修改前端 | 纯后端能力，前端展示延后 |
| 多项目配置模板 | 不为其他项目创建 pipeline_config 模板 | 先通用化，再模板化 |
| Agent Card 间自动协商 | 不实现 Agent 之间自动分配任务 | 手动 PM 配置映射表 |
| `!step_reject` 参数化改造 | 不改造退回命令 | 影响较小 |
| LLM Agent 自感知功能变更 | 不改造 bot 端代码 | 纯服务端改动 |
| Agent Card Web 编辑器 | 不写前端 | CLI 命令 `!agent_card set` 已够用 |
| 历史 WORK_PLAN.md 增加 frontmatter | 不改造 R1-R61 文档 | 旧文档退化兼容即可 |

---

## 5. 管线计划

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 30min |
| **2** | 👷 Arch | 技术方案 | 20min |
| **3** | 👨‍💻 Dev | 编码 + 测试 | 40min |
| **4** | 👀 Review | 代码审查 | 20min |
| **5** | 🦐 QA | 测试报告 | 20min |
| **6** | 🛠️ Admin | 合并 dev→main，部署，归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/timeout_tracker.py` | **新增** — 倒计时模块 | ~80 行 |
| `server/handler.py` | **新增/修改** — `_PIPELINE_CONFIG`、frontmatter 解析器、step 路由映射表、ACK 状态机 | ~200 行 |
| `server/agent_card.py` | **增强** — schema 扩展 + 注册逻辑 | ~50 行 |
| `server/config.py` | **新增** — 退化开关 + timeout_minutes 参数 | ~15 行 |
| `docs/R63/WORK_PLAN.md` | **新增** — 含 frontmatter 示例 | ~30 行 |
| **合计** | | **~375 行净增** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| R62 `_PIPELINE_CONFIG` 需从头实现，比单纯 R63 工作量大 | 工期拉长 | 方向 A5 已纳入改动估算，R62 验收标准也纳入 R63 |
| ACK 状态机影响现有 bot 行为 | 已有管线异常 | 方向 D 退化开关，`_ENABLE_R63_ACK=False` 时零影响 |
| 定时器与 watchdog 并行运行可能冲突 | 双重告警 |  watchdog 检查 `_timeout_timers` 是否已超时，已超时则不重复告警 |
| Agent Card 注册失败导致路由断裂 | 管线卡死 | `get_agents_by_role()` 回退 `auth.get_users()`，不阻塞管线 |

---

## 6. 脱敏检查清单

- [ ] docs/R63/*.md 零内部名残留
- [ ] 代码 diff 零内部名/URL/端口泄露
- [ ] `grep` 内部名/域名模式 零匹配
