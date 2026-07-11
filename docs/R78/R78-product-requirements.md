# R78 产品需求 — 全局变量迁移补完：角色映射 + ACK 状态统一管理 📐

> **版本：** v1.0（初稿）
> **状态：** ⏳ 待审核
> **产品经理：** 🧐 PM
> **日期：** 2026-07-09
> **基线：** `4baedba`（main 最新 — R77 合并部署 + step_complete PM inbox 通知）
> **本轮改动范围：** `server/handler.py` 全局变量迁移 + `server/pipeline_context.py` 扩展 + `server/agent_card.py` 角色映射适配
> **参考：** `docs/R77/R77-product-requirements.md` §6 Phase 2‑3

---

## 0. 先验验证：已就绪的基础设施

| 验证项 | 结果 | 确认方式 |
|:-------|:----:|:---------|
| R77 PipelineContextManager 稳定运行 | ✅ | 基线 `4baedba`，ws-bridge:latest |
| `!pipeline create/status/list/advance/block/archive/cancel` 指令正常 | ✅ | R77 验收 7/7 ALL GREEN 🟢 |
| 重启后 PipelineContext 从磁盘恢复 | ✅ | JSON 持久化 + 启动加载 |
| `_ROLE_AGENT_MAP` 通过 Agent Card pipeline_roles 构建 | ✅ | `_refresh_role_agent_map()` + CardFileWatcher |
| **小结** | ✅ | **Phase 1 底座已就位，可以开始 Phase 2 迁移** |

---

## 1. 问题背景

### 1.1 现状分析

R77 完成了 Phase 1（`_PIPELINE_STATE` → `PipelineContextManager`），但 handler.py 中仍残留 **3 组旧全局变量**，共 **58 处引用**：

| 变量 | 类型 | 引用数 | R77 标记 | 当前问题 |
|:-----|:-----|:------:|:---------|:---------|
| `_ROLE_AGENT_MAP` | `dict[str, list[str]]` | 19 (+5 in agent_card.py) | Phase 3 | 与 PipelineContext.role_agent_map 双写不一致 |
| `_step_ack_states` | `dict[str, dict]` | 11 | Phase 4 | 独立于 PipelineContext 之外，无持久化 |
| `_PIPELINE_CONFIG` | `dict[str, dict]` | 28 | Phase 5 | 每次从 WORK_PLAN frontmatter 重复解析，无缓存一致性 |

### 1.2 双写不一致风险

PipelineContext 已存在 `role_agent_map: dict[str, str]` 字段，但与 `_ROLE_AGENT_MAP` 类型不匹配：

```
PipelineContext.role_agent_map  →  dict[str, str]      # role → single agent_id
_ROLE_AGENT_MAP                  →  dict[str, list[str]]  # role → [agent_id, ...]
```

当前 `!pipeline status` 展示 `ctx.role_agent_map` 的数据来**源**可能滞后于 `_ROLE_AGENT_MAP`，二者各自更新容易出现「角色映射在管线上下文中是旧的」的问题，已在 R74/R75 实战中暴露。

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:-----|:------|
| 🔴 **双写散乱 → 数据不一致** | 同一份角色映射数据存在 2 个地方，修改点 24 处分散在两模块，改漏一处就导致角色路由静默失败 |
| 🟡 **ACK 状态无持久化** | `_step_ack_states` 全在内存，server 重启后丢失，管线恢复中断 |
| 🟡 **重复解析 WORK_PLAN 浪费** | 每次调用 `_PIPELINE_CONFIG.get(round_name)` 背后都有 frontmatter 重读开销 |
| 🟢 **改动范围明确可控** | 纯 server 端迁移，不改 bot 行为、不改 WS 协议、不改前端、不影响现有管线运行 |

---

## 2. 功能需求

### 设计原则

> **渐进替换，双写保护。** 每完成一个变量的迁移，旧变量保留但标记为 `# DEPRECATED — use PipelineContextManager`，新代码统一从 Manager 读取。全部迁移完成后一次性清理旧变量声明。
>
> **不改变现有行为语义。** 迁移不改数据结构含义，不改函数签名（除非签名直接使用了旧变量名）。

---

### 方向 A（核心）：`_ROLE_AGENT_MAP` → PipelineContext 统一 🔴 P0

#### A1 — 修复类型不匹配

当前 PipelineContext.role_agent_map 类型 `dict[str, str]`（单值）与 `_ROLE_AGENT_MAP` 类型 `dict[str, list[str]]`（多值）不兼容。**改为 `dict[str, list[str]]`**：

```python
@dataclass
class PipelineContext:
    # ...
    role_agent_map: dict[str, list[str]] = field(default_factory=dict)
    # {"architect": ["ws_xxx"], "developer": ["ws_yyy", "ws_zzz"], ...}
```

同时修复 `_format_pipeline_context()` 中角色展示（从 `r=a[:12]` 改为 `r=a1,a2` 逗号分隔多值）。

#### A2 — 迁移双向写入点

`_ROLE_AGENT_MAP` 有两个写入入口：

| 入口 | 位置 | 当前 | 迁移后 |
|:----|:-----|:-----|:-------|
| Agent Card 注册/更新 | `agent_card.py:388-391` | 直接写 `handler._ROLE_AGENT_MAP` | 改为通过 PipelineContextManager 的 `update_role_agent_map()` 方法 |
| `!agent_role_map` 命令 | `handler.py:4054-4057` | 直接写 `_ROLE_AGENT_MAP` | 同样走 Manager 方法 |

新增 Manager 方法：

```python
class PipelineContextManager:
    async def update_role_agent_map(self, role_agent_map: dict[str, list[str]]) -> None:
        """
        全局更新所有活跃 PipelineContext 的 role_agent_map。
        由 _refresh_role_agent_map() 调用（Agent Card 变更时触发）。
        update_role_agent_map_round(round_name, ...) 针对单个管线。
        """
```

#### A3 — 迁移读取点

`_ROLE_AGENT_MAP` 有 **3 个主要读取消费点**：

| 消费函数 | 位置 | 当前 | 迁移后 |
|:---------|:-----|:-----|:-------|
| `_get_agents_by_role()` | handler.py:1052 | 读 `_ROLE_AGENT_MAP.get(role, [])` | 读 `PipelineContextManager.get_role_agents(round_name, role)`，有 round 就用管线上下文，无 round 则读全局快照 |
| `!agent_role_map` 展示 | handler.py:4059 | 读 `_ROLE_AGENT_MAP` | 读 `mgr.get_global_role_map()` |
| `_cmd_rollcall_next() / _cmd_step_complete()` 角色查找 | handler.py 多个位置 | 通过 `_get_agents_by_role()` 间接读 | 统一走 Manager |

#### A4 — 全局角色映射快照

有一部分场景**不关联具体轮次**（如 `!agent_role_map` 展示、`_get_agents_by_role()` 全局查找），需要保留**全局角色映射快照**，放在 Manager 中：

```python
class PipelineContextManager:
    def __init__(self, data_dir):
        # ...
        self._global_role_map: dict[str, list[str]] = {}  # role → [agent_id, ...]
    
    def set_global_role_map(self, role_agent_map: dict[str, list[str]]) -> None:
        """由 _refresh_role_agent_map() 调用，更新全局快照。"""
    
    def get_global_role_map(self) -> dict[str, list[str]]:
        """返回全局角色映射快照。"""
    
    def get_role_agents(self, role: str, round_name: str | None = None) -> list[str]:
        """
        获取指定角色的 agent 列表。
        有 round_name 时优先从对应 PipelineContext 读取。
        无 round_name 或对应管线不存在时回退到全局快照。
        """
```

#### A5 — 迁移步骤

```
Step 1: 修复 PipelineContext.role_agent_map 类型 (str→list[str])
Step 2: Manager 新增 set_global_role_map() + get_role_agents() + update_role_agent_map()
Step 3: agent_card.py 写入改走 Manager
Step 4: handler.py 读取改走 Manager (3 个消费点 + 2 个写入入口)
Step 5: 旧 _ROLE_AGENT_MAP 标记 # DEPRECATED，保留兼容守卫
```

---

### 方向 B（扩展）：`_step_ack_states` → PipelineContext 统一 🟡 P1

#### B1 — PipelineContext 新增 ack_states 字段

```python
@dataclass
class PipelineContext:
    # ...（现有字段）
    ack_states: dict[str, dict] = field(default_factory=dict)
    # Key: "{step_name}"  (不再用 "{round}/{step}" 前缀，round 已在上下文)
    # Value: {
    #   "state": str,           # "PENDING" | "ACKED" | "TIMEOUT" | "FAILED"
    #   "assigned_to": str,     # agent_id
    #   "assigned_at": float,   # timestamp
    #   "acked_at": float | None,
    #   "role_name": str,       # display role for UI
    # }
```

#### B2 — Manager 新增 ACK 操作方法

```python
class PipelineContextManager:
    async def set_ack_state(
        self, round_name: str, step_name: str,
        state: str, assigned_to: str = "", **extra
    ) -> bool: ...
    
    async def get_ack_state(self, round_name: str, step_name: str) -> dict | None: ...
    
    def has_ack_for_agent(self, round_name: str, agent_id: str) -> bool:
        """检查 agent 在当前管线是否有未完成的 ACK。""" 
```

#### B3 — 迁移步骤

```
Step 1: PipelineContext 新增 ack_states 字段 + to_dict/from_dict 序列化
Step 2: Manager 新增 set_ack_state / get_ack_state
Step 3: handler.py 中 _step_ack_states 的写入（~L3047）改为走 Manager
Step 4: handler.py 中 _step_ack_states 的读取（~L1732, 1841, 1856, 1871, 1876）改为走 Manager
Step 5: 旧 _step_ack_states 标记 # DEPRECATED
```

#### B4 — 持久化保障

加入 JSON 持久化后，server 重启不再丢失 ACK 状态：

```
重启前:
  PipelineContext.round_name = "R77"
  PipelineContext.ack_states = {"step2": {"state": "ACKED", ...}}

重启后:
  从 pipeline_contexts.json 恢复 → ack_states 完好
```

---

### 方向 C（渐进）：`_PIPELINE_CONFIG` 轻量化 🟡 P1

#### C1 — 问题分析

`_PIPELINE_CONFIG` 本质是 WORK_PLAN frontmatter 解析结果，在 `_cmd_pipeline_start` 时通过 `_parse_work_plan_frontmatter()` 解析并存入全局变量。之后 28 处读取点每次都 `_PIPELINE_CONFIG.get(round_name, {})`。

其数据大部分已可以被 PipelineContext 替代（steps → total_steps, workspace.members → role_agent_map, roles → role_agent_map keys），但仍有一部分**Step 级细粒度配置**（每个 step 的 `executor_role`, `timeout_minutes`, `description` 等）不在 PipelineContext 中。

#### C2 — PipelineContext 新增 step_configs 字段

```python
@dataclass
class PipelineContext:
    # ...（现有字段 + B1 新增字段）
    steps: list[dict] = field(default_factory=list)
    # [
    #   {"name": "step1", "executor_role": "arch", "timeout_minutes": 120, "description": "..."},
    #   {"name": "step2", "executor_role": "dev", ...},
    #   ...
    # ]
```

#### C3 — 复用现有解析逻辑

不重写 frontmatter 解析，而是让 `_cmd_pipeline_start` 在解析完 frontmatter 后，将 step 配置写入 PipelineContext.steps：

```python
# 在 _cmd_pipeline_start 中，pipeline_context 创建后：
ctx = await mgr.create(...)
# 解析 frontmatter 获得 steps list
parsed_steps = _extract_steps_from_frontmatter(frontmatter_data)
await mgr.update_steps(round_name, parsed_steps)
```

后续代码可以从 `ctx.steps` 读取 step 配置，不再需要 `_PIPELINE_CONFIG.get(round_name, {}).get("step2", {})`。

#### C4 — 迁移步骤

```
Step 1: PipelineContext 新增 steps 字段 + 序列化
Step 2: Manager 新增 update_steps() / get_step_config(round_name, step_name)
Step 3: _cmd_pipeline_start 在创建 PipelineContext 后写入 steps
Step 4: 逐步替换 _PIPELINE_CONFIG 读取点（28 处 → 分阶段，本轮回至少 10 处高频率点）
```

---

### 方向 D（新能力）：`!pipeline` 命令增强 🟢 P2

#### D1 — `!pipeline create` 集成 workspace

当前 `!pipeline create` 创建 PipelineContext 但不绑定 workspace_id 和 pm_inbox_id。增强为可选参数：

```
!pipeline create R78 dev [--steps 6] [--ws <workspace_id>] [--pm-inbox <inbox_id>]
```

如果 `!pipeline_start` 之后执行的，可以在 `_cmd_pipeline_start` 中自动调用 `mgr.create` 或 `mgr.update` 补全 workspace_id。

#### D2 — `!pipeline resume` 恢复命令

新子命令，用于管线中断后快速恢复：

```
!pipeline resume R77
```

行为：
1. 从 `pipeline_contexts_history.jsonl` 找到 R77 的归档上下文
2. 反归档（从历史移回活跃）
3. 如果在 BLOCKED 状态，自动转 RUNNING
4. 输出当前进度 + 下一步要做的工作

#### D3 — `!pipeline status` 展示 ACK 状态

当前 `_format_pipeline_context()` 只展示基本状态和成员。增强为：

```
📋 R77 [dev]
  状态: running
  Step: 3/6 (step3)
  阶段: implement
  成员: arch=ws_xxx, dev=ws_yyy, ...
  ACK: step1 ✅ACKED(小开), step2 ✅ACKED(爱泰), step3 ⏳PENDING(小周), ...
  工作室: ws_xxx-R77-dev
  创建: 07/09 14:30
```

通过方向 B 迁移后，ACK 状态统一从 `pipeline_context.ack_states` 读取，自然就能展示。

---

## 3. 验收标准

| # | 验收项 | 通过条件 |
|:-:|:------|:---------|
| 1 | `_ROLE_AGENT_MAP` 不再被新代码直接读写（仅兼容守卫） | grep `_ROLE_AGENT_MAP` 结果仅出现在旧变量声明行 + `# DEPRECATED` 注释附近 |
| 2 | Agent Card 注册/更新后 PipelineContext.role_agent_map 同步更新 | `!agent_card list` 后再 `!pipeline status R78` 显示正确角色 |
| 3 | `_get_agents_by_role()` 通过 Manager 读取 | 无 `_ROLE_AGENT_MAP.get(role)` 调用 |
| 4 | `_step_ack_states` 不再被新代码直接读写 | grep `_step_ack_states` 结果仅出现在旧变量声明 + DEPRECATED 注释 |
| 5 | ACK 状态持久化 | 新建管线 → 推进到 step2 → 重启 server → `!pipeline status RR` 显示 step2 ACK 状态 |
| 6 | PipelineContext 新增字段序列化完整 | `to_dict()` → `from_dict()` 往返不丢数据（role_agent_map 多值 + ack_states + steps） |
| 7 | `!pipeline status` 展示 ACK 状态 | 至少展示每个 step 的 ACK 状态 ✅⏳❌+角色名 |
| 8 | `!pipeline resume` 恢复归档管线 | 已归档管线可以恢复到活跃状态，step 和 ACK 状态正确 |
| 9 | 旧 `!pipeline_start` 命令行为不变 | 管线启动正常，步骤推进正常，`_PIPELINE_CONFIG` 解析兼容 |
| 10 | 所有旧命令回归正常 | 现有 41 个命令 + 6 个 pipeline 子命令全部可用 |

---

## 4. 非功能性需求

| # | 要求 | 指标 |
|:-:|:-----|:-----|
| 1 | 兼容性 | 所有现有命令在迁移前后行为一致（不因变量迁移改变回显内容） |
| 2 | 双写保险 | 迁移过渡期内，旧变量和 Manager 同时写入（先写新、再写旧），出现差异时以新为准 |
| 3 | 数据完整性 | JSON 写盘异常不导致进程退出，回退到内存状态（与现有模式一致） |
| 4 | 性能 | `!pipeline status` 查询 ≤ 500ms（含 ACK 状态聚合） |
| 5 | 代码精简 | 迁移完成后 handler.py 净减少 ≥ 40 行（删除旧变量声明 + 重复解析逻辑） |

---

## 5. 不包含在本轮的内容

| 事项 | 原因 |
|:-----|:------|
| ❌ 修改 bot 行为或 WS 协议 | R78 纯 server 端清理，bot 与管线交互流程不变 |
| ❌ 修改前端或 Web 端 | 不涉及前端改动 |
| ❌ Agent Card 数据结构变更 | Agent Card 的 pipeline_roles 结构保持不变，仅迁移写入路径 |
| ❌ WORK_PLAN frontmatter 格式变更 | 格式不变，仅将解析结果存入 PipelineContext.steps |
| ❌ F-3 workspace_admin 角色体系 | 与全局变量迁移正交，留给后续轮次 |
| ❌ R36-B 新虾注册流程 | 独立功能，与管线状态管理不相关 |
| ❌ 架构扩展（条件分支/多阶段规划） | R78 为架构扩展打好底座，业务逻辑本身留给 R79+ |

---

## 6. 影响范围

| 模块 | 影响 | 说明 |
|:-----|:-----|:------|
| `server/pipeline_context.py` | 🔴 中等 | 扩展 dataclass 字段（role_agent_map 类型修复 + ack_states + steps） + Manager 新增方法 |
| `server/handler.py` | 🔴 较大 | 3 组旧变量 58 处引用逐点迁移，新增 `!pipeline resume` 命令 |
| `server/agent_card.py` | 🟡 小 | 角色映射写入路径从直接写 handler 模块变量改为走 Manager（5 行改动） |
| `server/pipeline_sync.py` | ℹ️ 无影响 | PipelineGitSync 不直接使用这三个变量 |
| `shared/protocol.py` | ℹ️ 无影响 | 不新增消息类型 |
| `clients/python/ws_client.py` | ℹ️ 无影响 | 客户端不变 |
| 各 bot 代码 | ✅ 无影响 | bot 行为不变 |

---

## 7. 迁移路线图（总览）

```
Phase 1 (R77 ✅):   _PIPELINE_STATE → PipelineContextManager  ✔️
Phase 2 (R78 🎯):   _ROLE_AGENT_MAP → PipelineContext.role_agent_map (方向 A)
Phase 3 (R78 🎯):   _step_ack_states → PipelineContext.ack_states (方向 B)
Phase 4 (R78 🎯):   _PIPELINE_CONFIG steps → PipelineContext.steps 部分迁移 (方向 C)
Phase 5 (R79+):     剩余 _PIPELINE_CONFIG 读取点 + 条件分支/多阶段规划
```

---

## 8. 技术方案参考

- R77 `server/pipeline_context.py` — 现有 PipelineContext 和 Manager 实现
- `server/handler.py` L51-69 — 3 组旧全局变量声明
- `server/handler.py` L998-1018 — `_refresh_role_agent_map()` 当前实现
- `server/agent_card.py` L383-391 — agent_card 写 `_ROLE_AGENT_MAP` 的 5 行
- `server/handler.py` L3047 — `_step_ack_states` 写入点
- `server/handler.py` L1505-1507, L1732, L1790, L1841, L1856, L1871, L1876 — `_step_ack_states` 读取点
