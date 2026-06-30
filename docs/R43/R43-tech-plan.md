# R43 技术方案 — Hot Standby 信号死锁

> **版本：** v1.0
> **作者：** 🏗️ 架构师
> **日期：** 2026-06-27
> **需求文档：** [R43-product-requirements.md](R43-product-requirements.md)
> **工作计划：** [WORK_PLAN.md](WORK_PLAN.md)

---

## 目录

- [Part A — 方案设计](#part-a--方案设计)
  - [A-1 方向 A：看门狗定时器](#a-1-方向-a看门狗定时器)
  - [A-2 方向 B：Step 超时配置](#a-2-方向-bstep-超时配置)
  - [A-3 方向 C：超时升级通知](#a-3-方向-c超时升级通知)
  - [A-4 方向 D：交接响应增强](#a-4-方向-d交接响应增强)
  - [A-5 配置文件变更：`config.py`](#a-5-配置文件变更configpy)
  - [A-6 全局状态扩展：`handler.py`](#a-6-全局状态扩展handlerpy)
- [Part B — 新增数据结构与常量](#part-b--新增数据结构与常量)
- [Part C — 验收标准映射](#part-c--验收标准映射)
- [Part D — 向后兼容分析](#part-d--向后兼容分析)
- [附录](#附录)
  - [改动清单](#改动清单)
  - [关键流程时序图](#关键流程时序图)

---

## Part A — 方案设计

### 核心架构概览

```
┌──────────────────────────────────────────────────────────┐
│                     handler.py 服务启动                        │
│                                                          │
│  asyncio.create_task(_watchdog_loop())  ← 后台看门狗协程      │
│                                                          │
│  ┌─────────────┐  每10min    ┌──────────────────────┐    │
│  │ _watchdog  │ ────────→ │ 扫描 _PIPELINE_STATE    │    │
│  │   _loop()  │            │ 遍历所有活跃管线        │    │
│  └─────────────┘            └──────────┬───────────┘    │
│                                        ↓                 │
│                              计算当前 Step 挂起时间        │
│                                        ↓                 │
│                              挂起 > timeout_hours?       │
│                              ├── 否 → 跳过               │
│                              └── 是 → 已告警过?          │
│                                       ├── 是 → 距上次告警>30min? │
│                                       │      ├── 是 → 重复通知     │
│                                       │      └── 否 → 跳过         │
│                                       └── 否 → 首次告警            │
│                                                ↓                   │
│                                        _admin 频道通知              │
│                                                                  │
│  !step_complete → 标记 Step 完成                                   │
│     → _clear_watchdog_alert(round_name, step) 清除告警标记          │
│     → 发解除通知到 _admin                                           │
│     → 点名下一角色（返回值增强：标注已点名<角色>）                     │
└──────────────────────────────────────────────────────────┘
```

### A-1 方向 A：看门狗定时器

#### 设计决策

| 决策 | 选择 | 理由 |
|:-----|:-----|:------|
| 实现方式 | `asyncio.create_task` 后台协程 | 与现有 `_rollcall_timeout` 模式一致 |
| 扫描周期 | 10 分钟 | 需求固定，硬编码，不配置 |
| 启动时机 | `on_message` 中首次调用时惰性启动（带已启动标志） | 避免改动入口启动逻辑 |
| 停止机制 | 协程内部 `try/except CancelledError` 优雅退出 | 服务关闭时 asyncio 自动取消 |
| 重复告警判断 | 内存字典 `{round_step_key: last_alert_ts}` | 轻量，服务重启后重置（可接受） |

#### 核心函数

```python
# handler.py — 新增看门狗模块

_watchdog_started: bool = False          # 看门狗已启动标志
_watchdog_task: asyncio.Task | None = None  # 看门狗协程引用
_watchdog_alerts: dict[str, float] = {}  # "{round_name}/{step}" → last_alert_ts

# 超时默认值配置（方向 B 提供，看门狗使用）
_STEP_TIMEOUT_DEFAULTS: dict[str, float] = {
    "step1": 2.0,    # 管线启动（操作类）
    "step2": 6.0,    # 技术方案
    "step3": 12.0,   # 编码
    "step4": 4.0,    # 代码审查
    "step5": 6.0,    # 测试验证
    "step6": 2.0,    # 合并部署归档（操作类）
}
```

#### 函数签名与行为

**`_ensure_watchdog()`**
- 作用：惰性启动看门狗后台协程
- 逻辑：检查 `_watchdog_started`，如未启动则 `asyncio.create_task(_watchdog_loop())`
- 调用点：`handle_broadcast` 入口处（与 `_rollcall_timers` 类似位置）
- 行数预估：10 行

**`async def _watchdog_loop()`**
```python
async def _watchdog_loop():
    """后台看门狗循环，每 10 分钟扫描一次活跃管线。"""
    try:
        while True:
            await asyncio.sleep(600)  # 10 分钟
            await _watchdog_scan()
    except asyncio.CancelledError:
        logger.info("R43 watchdog loop cancelled — shutting down")
```
- 行数预估：15 行（含异常处理）

**`async def _watchdog_scan()`**
- 遍历 `_PIPELINE_STATE` 中所有 `active=True` 的管线
- 对每个管线：
  1. 获取 `current_step`
  2. 从 `_load_step_config()` 获取该 Step 的配置
  3. 计算 `挂起时间 = now - pstate["started_at"]`
  4. 获取 `timeout_hours`（优先 Step 配置 → 默认值 _STEP_TIMEOUT_DEFAULTS）
  5. 如超时 → 调用 `_check_watchdog_alert(round_name, step_name, elapsed, timeout_hours)`
- 行数预估：40 行

**`def _get_step_timeout(step_name: str) -> float`**
- 从 `_load_step_config()[step_name]` 取 `timeout_hours`
- 如未配置，回退 `_STEP_TIMEOUT_DEFAULTS[step_name]`
- 如均无，返回 `float('inf')`（永不超时）
- 行数预估：10 行

**`def _get_step_elapsed(round_name: str) -> float`**
- 计算 `time.time() - _PIPELINE_STATE[round_name].get("started_at", time.time())`
- 转换为小时返回
- 行数预估：5 行

**`def _check_watchdog_alert(round_name: str, step_name: str, elapsed_hours: float, timeout_hours: float) -> str | None`**
- 检查 `_watchdog_alerts` 中是否有该 `round_name/step_name` 的记录
- 无记录 → 首次超时：存入 `{key: now}`，返回 `"first"`
- 有记录 → 距上次告警 > 30 分钟 → 更新 `{key: now}`，返回 `"repeat"`
- 有记录 → 距上次告警 ≤ 30 分钟 → 返回 `None`（跳过）
- 行数预估：15 行

**`def _clear_watchdog_alert(round_name: str, step_name: str) -> bool`**
- 从 `_watchdog_alerts` 中删除 `round_name/step_name`
- 返回 True 表示有清除操作（用于方向 C 的解除通知判断）
- 行数预估：5 行

---

### A-2 方向 B：Step 超时配置

#### PIPELINE_STEP_MAP 扩展

在 `config.py` 的 `PIPELINE_STEP_MAP` 中，每个 Step 增加两个字段：

```python
PIPELINE_STEP_MAP: dict[str, dict] = {
    "step1": {"role": "admin",   "name": "管线启动",         "timeout_hours": 2.0,  "escalation": "notify_pm"},
    "step2": {"role": "arch",    "name": "技术方案",         "timeout_hours": 6.0,  "escalation": "notify_pm"},
    "step3": {"role": "dev",     "name": "编码",            "timeout_hours": 12.0, "escalation": "notify_pm"},
    "step4": {"role": "review",  "name": "代码审查",         "timeout_hours": 4.0,  "escalation": "notify_pm"},
    "step5": {"role": "qa",      "name": "测试验证",         "timeout_hours": 6.0,  "escalation": "notify_pm"},
    "step6": {"role": "admin",   "name": "合并部署归档",      "timeout_hours": 2.0,  "escalation": "notify_pm"},
}
```

#### 环境变量覆盖

延续现有 `PIPELINE_STEP_MAP_OVERRIDE` JSON 格式，支持只传需要覆盖的字段：

```bash
# 环境变量格式：仅传要覆盖的字段
PIPELINE_STEP_MAP_OVERRIDE='{"step2": {"timeout_hours": 8.0}}'
```

现有 `config.py` 的 `_override_raw` 解析逻辑不变——`PIPELINE_STEP_MAP.update(override)` 自动合并部分字段。

#### 默认值回退链

```
1. 单个 Step 的 timeout_hours 字段（精确匹配）
2. _STEP_TIMEOUT_DEFAULTS 全局默认值（按 step_name）
3. float('inf')（永不超时，兜底）
```

---

### A-3 方向 C：超时升级通知

#### 三段通知流程

| 阶段 | 触发条件 | 消息格式 | 目标 |
|:----:|:---------|:---------|:----:|
| **首次告警** | 看门狗首次检测到 Step 超时 | `⚠️ R43 管线超时告警` 完整格式 | `_admin` 频道 |
| **重复告警** | 距上次告警 ≥ 30 分钟，仍超时 | 同上，追加 `（重复通知 #N）` | `_admin` 频道 |
| **解除通知** | `!step_complete` 标记 Step 完成 | `✅ R43 Step 2 已恢复` | `_admin` 频道 |

#### 告警消息格式（纯文本，无 Markdown code block）

```
⚠️ R43 管线超时告警
  Step: 技术方案（Step 2）
  责任人: arch-bot
  已挂起: 7.5 小时（超时阈值: 6h）
  启动时间: 2026-06-25 14:30
  建议操作: 联系 arch-bot 或考虑换人
```

#### 解除通知格式

```
✅ R43 Step 2 已恢复 — 已完成技术方案（commit: abc1234）
```

#### 核心函数

**`async def _send_watchdog_alert(round_name: str, step_name: str, elapsed_hours: float, timeout_hours: float, alert_type: str)`**

参数：
- `alert_type`: `"first"` | `"repeat"`
- 行为：构造告警消息 → 调用 `_persist_broadcast` 写入消息存储 → 返回消息文本
- 行数预估：25 行

**`async def _send_clear_alert(round_name: str, step_name: str, output_ref: str)`**

- 在 `!step_complete` 中检测到该 Step 有活跃告警时调用
- 行为：构造解除消息 → `_persist_broadcast` → 清除告警标记
- 行数预估：15 行

**`def _elapsed_hours_display(elapsed: float) -> str`**

- 浮点小时 → 友好显示 `"7.5 小时"`
- 行数预估：5 行

#### 通知去重机制

看门狗扫描周期 10 分钟，重复通知间隔 30 分钟（需求 C-4）。

```
时间线：
 T+0min  Step 2 启动
 T+360min（6h 阈值）→ 看门狗扫描 → 超时 → 首次告警
 T+370min               → 看门狗扫描 → 距上次告警 10min → 跳过（<30min）
 T+380min               → 看门狗扫描 → 距上次告警 20min → 跳过
 T+390min               → 看门狗扫描 → 距上次告警 30min → 重复告警 #2
 T+400min               → 看门狗扫描 → 距上次告警 10min → 跳过
 ...
 T+720min  Step 完成 → !step_complete → 清除告警 → 解除通知
```

去重标志在 `_watchdog_alerts` 字典中以 `"{round_name}/{step_name}"` 为键，值为 last_alert_ts。

---

### A-4 方向 D：交接响应增强

#### 需求回顾

`!step_complete` 点名下一角色后，返回消息中需明确告知「已点名 <角色>，等待确认」。

#### 当前返回格式

```python
# _cmd_step_complete 当前返回（handler.py 1059 附近）：
return (
    f"✅ **{step_name} 完成** → 交接给 {next_role} {next_step}\n"
    f"  {task_result}\n"
    f"  {rollcall_result}\n"
    f"  {next_task_result}"
)
```

#### 增强后返回格式

```python
return (
    f"✅ **{step_name} 完成** → 交接给 {next_role} {next_step}\n"
    f"  📋 已点名 {next_role_name}，等待确认「到」\n"
    f"  🎯 负责人请切到工作室频道回复「到」开始\n"
    f"  {task_result}\n"
    f"  {rollcall_result}\n"
    f"  {next_task_result}"
)
```

其中 `next_role_name` 从 `auth.get_users()` 中查询映射表获取角色对应的名称列表。

#### 实现改动

在 `_cmd_step_complete` 中找到下一角色名称，追加两行到返回值。

```python
# 获取下一角色名称（用于 D 方向增强）
next_role_names = [
    users.get(aid, {}).get("name", aid[:12])
    for aid in ws_obj.members
    if users.get(aid, {}).get("role", "member") == next_role
]
next_role_display = ", ".join(next_role_names) if next_role_names else next_role
```

- 行数预估：在 _cmd_step_complete 中增加 10 行

---

### A-5 配置文件变更：`config.py`

#### 新增代码

```python
# ── R43: Pipeline step timeout defaults ──────────────────────
# 当 PIPELINE_STEP_MAP 中某 Step 未配置 timeout_hours 时使用这些默认值
STEP_TIMEOUT_DEFAULTS: dict[str, float] = {
    "step1": 2.0,    # 管线启动（纯操作类）
    "step2": 6.0,    # 技术方案
    "step3": 12.0,   # 编码
    "step4": 4.0,    # 代码审查
    "step5": 6.0,    # 测试验证
    "step6": 2.0,    # 合并部署归档（纯操作类）
}
```

#### PIPELINE_STEP_MAP 字段扩展

| 现字段 | 类型 | 说明 |
|:-------|:----:|:------|
| `role` | str | ✅ 已存在 |
| `name` | str | ✅ 已存在 |
| `timeout_hours` | float | 🔄 新增，可选，默认回退 |
| `escalation` | str | 🔄 新增，可选，默认 `"notify_pm"` |

**向后兼容：** 旧配置（无 `timeout_hours`/`escalation`）照常工作，使用默认值。

---

### A-6 全局状态扩展：`handler.py`

#### 新增全局变量

```python
# ── R43: Watchdog state ─────────────────────────────────────
_watchdog_started: bool = False
_watchdog_task: asyncio.Task | None = None
_watchdog_alerts: dict[str, float] = {}  # "{round}/{step}" → last_alert_ts
```

#### 新增辅助函数（汇总）

| 函数 | 作用 | 行数 |
|:-----|:-----|:----:|
| `_ensure_watchdog()` | 惰性启动看门狗协程 | 10 |
| `_watchdog_loop()` | 看门狗主循环，每 10 分钟扫描 | 15 |
| `_watchdog_scan()` | 扫描所有活跃管线的 Step 状态 | 40 |
| `_get_step_timeout(step_name)` | 获取 Step 超时阈值 | 10 |
| `_get_step_elapsed(round_name)` | 获取 Step 已挂起时间 | 5 |
| `_check_watchdog_alert(key)` | 检查去重状态 | 15 |
| `_clear_watchdog_alert(key)` | 清除告警标记 | 5 |
| `_send_watchdog_alert(...)` | 发送告警通知 | 25 |
| `_send_clear_alert(...)` | 发送解除通知 | 15 |
| `_elapsed_hours_display(h)` | 格式化时间显示 | 5 |

**总计新增：~145 行**

#### 现有函数修改

| 函数 | 修改 | 行数增减 |
|:-----|:-----|:--------:|
| `_cmd_step_complete` | 追加方向 D 交接确认信息 + 解除通知调用 | +20 |
| `on_message` / `handle_broadcast` 入口 | 调用 `_ensure_watchdog()` | +2 |

**总计修改：~22 行**

---

## Part B — 新增数据结构与常量

### 全局变量表

```python
# handler.py 新增
_watchdog_started: bool = False              # 看门狗是否已启动
_watchdog_task: asyncio.Task | None = None   # 看门狗协程引用（可取消）
_watchdog_alerts: dict[str, float] = {}      # key="{round}/{step}" → last_alert_ts
```

### 配置常量表

```python
# config.py 新增
STEP_TIMEOUT_DEFAULTS: dict[str, float] = {
    "step1": 2.0, "step2": 6.0, "step3": 12.0,
    "step4": 4.0, "step5": 6.0, "step6": 2.0,
}

# handler.py 新增（或导入自 config）
WATCHDOG_SCAN_INTERVAL: int = 600        # 10 分钟（秒）
WATCHDOG_REALERT_INTERVAL: int = 1800    # 30 分钟（秒）
```

### PIPELINE_STATE 结构（无变化，沿用 R42）

```python
_PIPELINE_STATE[round_name] = {
    "active": True,
    "current_step": "step2",
    "ws_id": "__R43_ws",
    "started_at": 1234567890.0,     # time.time() 时间戳
}
```

---

## Part C — 验收标准映射

### 方向 A：看门狗定时器

| # | 验收标准 | 对应函数/机制 | 验证方式 |
|:-:|:---------|:-------------|:---------|
| A-1 | 服务启动后看门狗自动，每 10 分钟扫描 | `_ensure_watchdog()` + `_watchdog_loop()` sleep(600) | 启动后监控日志 |
| A-2 | 无活跃管线时零输出 | `_watchdog_scan()` 空 `_PIPELINE_STATE` → 直接 return | 无日志输出 |
| A-3 | 超时时生成告警 | `_check_watchdog_alert()` 返回 `"first"` → `_send_watchdog_alert()` | 单测 |
| A-4 | 同一 Step 不重复告警 | `_watchdog_alerts` 去重字典 | 单测去重逻辑 |
| A-5 | 服务停止时自动终止 | `_watchdog_loop()` try/except CancelledError | asyncio 内建 |

### 方向 B：Step 超时配置

| # | 验收标准 | 对应实现 | 验证方式 |
|:-:|:---------|:---------|:---------|
| B-1 | 每个 Step 可配 timeout_hours | `PIPELINE_STEP_MAP` 扩展 `timeout_hours` | 检查 config.py |
| B-2 | 每个 Step 有 escalation 字段 | `PIPELINE_STEP_MAP` 扩展 `escalation` | 检查 config.py |
| B-3 | 未配置超时使用默认值 | `_get_step_timeout()` 回退链 | 单测 |
| B-4 | PIPELINE_STEP_MAP 已 6 步 | R42 已更新为 step1~step6 | 检查 config.py |
| B-5 | 环境变量覆盖支持 | `PIPELINE_STEP_MAP_OVERRIDE` 已有机制 | 单测 |

### 方向 C：超时升级通知

| # | 验收标准 | 对应实现 | 验证方式 |
|:-:|:---------|:---------|:---------|
| C-1 | Step 超时 _admin 收到告警 | `_send_watchdog_alert()` 用 `_persist_broadcast` 写入 | 集成测试 |
| C-2 | 告警包含完整信息 | 消息模板含 name/role/elapsed/timeout/started_at | 单测消息格式 |
| C-3 | Step 完成时发解除通知 | `_cmd_step_complete` 调用 `_send_clear_alert()` | 集成测试 |
| C-4 | 首次后每 30 分钟重复 | `_check_watchdog_alert()` 30min 间隔判断 | 单测时间逻辑 |
| C-5 | 纯文本格式 | 消息中无 Markdown 代码块 | 单测格式校验 |

### 方向 D：交接响应增强

| # | 验收标准 | 对应实现 | 验证方式 |
|:-:|:---------|:---------|:---------|
| D-1 | `!step_complete` 含「已点名 <角色>，等待确认」 | `_cmd_step_complete` 返回值增强 | 检查返回值 |
| D-2 | 当前角色可判断下一角色响应 | 靠观察工作室活跃度（流程层面） | 人工确认 |
| D-3 | 无响应时通过项目负责人协调 | 流程规范（非代码） | 无 |
| D-4 | 转发消息用 code 块封装 | 流程规范（非代码） | 无 |

---

## Part D — 向后兼容分析

| 场景 | 兼容性 | 说明 |
|:-----|:------:|:------|
| 无活跃管线 | ✅ 完全兼容 | `_watchdog_scan()` 空 `_PIPELINE_STATE` → 零输出 |
| 旧配置无 timeout_hours | ✅ 完全兼容 | `_get_step_timeout()` 回退默认值 |
| 旧 PIPELINE_STEP_MAP_OVERRIDE | ✅ 完全兼容 | JSON update 语义不变 |
| R42 `!pipeline_start` / `!step_complete` | ✅ 完全兼容 | 命令接口不变，返回值增强 |
| `!pipeline_status` | ✅ 完全兼容 | 后台新增看门狗不影响查询命令 |
| 服务重启 | ⚠️ 告警状态重置 | `_watchdog_alerts` 在内存中，重启丢失。Step 挂起超过阈值的会在重启后 10 分钟内重新告警 |
| 人工接力流程 | ✅ 完全兼容 | 看门狗不影响已完成的 Step，不干涉人工触发 |

---

## 附录

### 改动清单

| 文件 | 操作 | 行数 |
|:-----|:----|:----:|
| `server/config.py` | 🔄 修改 PIPELINE_STEP_MAP 扩展字段 + 新增 STEP_TIMEOUT_DEFAULTS | +15 |
| `server/handler.py` | 🔄 新增全局变量 + 函数 + 修改 _cmd_step_complete | +155 |

**总计：~170 行新增/修改代码**

### 关键流程时序图

#### 正常流程

```
!pipeline_start R43
  → 创建工作室 R43-dev
  → 点名全员
  → 点名 arch-bot Step 2
    ↓
Step 2 技术方案完成 → !step_complete step2 --output abc123
  → 标记 Task completed
  → 看门狗清除告警标记（如有）
  → 发解除通知到 _admin（如有活跃告警）
  → 点名 dev-bot Step 3 ← 返回值增强显示「已点名 dev-bot」
    ↓
Step 3 编码完成 → !step_complete step3 --output def456
  → 同上
```

#### 异常流程（遗忘 !step_complete）

```
Step 2 启动 (T+0h)
  ... 6 小时后 ...
  看门狗首次检测超时 → _admin 告警「R43 Step 2 已挂起 6h」
  ... 30 分钟后 ...
  看门狗重复检测 → _admin 告警「重复通知 #2」
  ... 直到 ...
  PM 介入协调 → arch-bot 完成 → !step_complete step2
  → 解除通知「R43 Step 2 已恢复」
```

#### 异常流程（点名后无人响应）

```
!step_complete → 点名 dev-bot
  → 返回值「已点名 dev-bot，等待确认」
  → arch-bot 观察到 dev-bot 无动静 ~5 分钟
  → arch-bot 检查 → dev-bot 离线
  → TG DM 项目负责人
  → 项目负责人转发 code 块消息给 dev-bot
  → dev-bot 恢复 → 管线继续
```

---

> **方案签字：** 🏗️ 架构师
> **状态：** 📝 初稿（待审查）
