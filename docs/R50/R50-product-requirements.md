# R50 产品需求 — 管线频道自动切换 + 过渡期调度命令

> **版本：** v0.1 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-06-28
> **本轮改动范围：** 仅第①类（服务器代码 `server/handler.py`）

---

## 1. 问题背景

R49 交付了管线基础设施的三项关键修复：`!` 命令全频道路由、Agent Card 角色映射持久化、超时告警闭环。39/39 验收全通过。

但实操运行中暴露了管线的最后一个断点——**每轮 Step 交接时，被点名角色的活跃频道不自动切换到工作室**。

### 1.1 点名报道的本质是频道切换

点名报道不是仪式性的「到」——它的实质操作是 `MSG_SET_ACTIVE_CHANNEL`，将 bot 的收发频道切换到工作室。不切换则：

- 工作室里的消息各角色收不到
- 各角色回复的消息落入 lobby 而非工作室
- 消息传递断裂，管线卡死

R49 实际运行中，全靠 admin-bot 在后台手动协调各角色切频道，管线才勉强推进。**每一次手动切频道，就证明管线自动化还缺一环。**

### 1.2 现有机制仅在点名报道时切换，管线交接时不切

`handler.py` 中 R37 已实现了 `MSG_SET_ACTIVE_CHANNEL` 自动发送（≈行 2402-2437），但它的触发点是**点名报道**（`!rollcall_role`），而不是**管线 Step 交接**。

管线自动流转路径是：

```
!step_complete Step2 --output xxx
  ↓
服务端：标记 Step 2 ✅
点名下一角色（dev）
  → 调用 _cmd_rollcall_next 或等效逻辑
  → 发送文本通知到 dev 当前频道
  → ⚠️ **不发 MSG_SET_ACTIVE_CHANNEL**
  → dev 活跃频道不变
  ↓
dev 切频道才能收到后续消息
  → 不切 → 管线卡住
```

### 1.3 过渡期需要 admin 可执行的频道切换命令

方向 A 的自动切换需要开发+部署，有时间差。在它上线之前，管线不能停摆。需要一个 admin-bot 可执行的过渡命令——在管线启动后、Step 交接时，手动触发批量频道切换。

**过渡期操作流程：**

```
PM 发 !pipeline_start R50 --from step2
  ↓
PM 在工作群 @admin-bot：执行 !pipeline_activate R50
  ↓
admin-bot 在 _admin 执行 !pipeline_activate R50
  ↓
服务端对 R50 管线所有参与角色批量发 MSG_SET_ACTIVE_CHANNEL
全员切到 R50-dev 工作室
  ↓
管线正常推进

Step 交接时：
架构师完成方案 → !step_complete Step2 --output xxx
  ↓
（方向 A 未部署时）PM @admin-bot：执行 !step_handoff R50
  ↓
admin-bot 在 _admin 执行 !step_handoff R50
  ↓
服务端将下一角色（dev）的活跃频道切到工作室
```

---

## 2. 需求范围

| 方向 | 问题 | 解决方案 | 代码类型 | 优先级 |
|:----:|:-----|:---------|:--------:|:------:|
| **A** | Step 交接时不自动切活跃频道 | `!step_complete` / `!rollcall_next` 调用时，自动发 MSG_SET_ACTIVE_CHANNEL 给被点名角色 | ① 服务器 | 🔴 P0 |
| **B** | 过渡期无手动切频道工具 | 新增 `!pipeline_activate` 和 `!step_handoff` admin 命令，批量/单角色频道切换 | ① 服务器 | 🟡 P1 |

> 技术方案（具体实现方式）由架构师决定。

---

## 3. 用户体验

### 3.1 方向 A：Step 交接自动切活跃频道

**当前（R49）：**

```
架构师完成方案 → !step_complete Step2 --output abc123
  ↓
服务端：标记 Step 2 ✅
点名 dev（开发工程师）
  → 发文本通知到开发工程师当前频道
  → 开发工程师活跃频道不变（可能在 lobby 或旧工作室）
  → 开发工程师看不到工作室消息

⚠️ 靠 admin-bot 手动协调开发工程师切频道
```

**期望（R50）：**

```
架构师完成方案 → !step_complete Step2 --output abc123
  ↓
服务端：标记 Step 2 ✅
点名 dev（开发工程师）
  → 自动发 MSG_SET_ACTIVE_CHANNEL 到开发工程师
  → 开发工程师活跃频道切换到 R50-dev 工作室
  → 同时发文本通知：「📋 Step 3（编码）轮到你了」
  ↓
开发工程师直接在工作室中收到通知，开始编码
```

**具体设计约束：**

1. `!step_complete` 点名下一角色时，先发 MSG_SET_ACTIVE_CHANNEL 再发文本通知
2. `!rollcall_next`（手动点名下一人）同样触发 MSG_SET_ACTIVE_CHANNEL
3. 仅在管线活跃期间的点名触发频道切换，非管线场景的普通点名不影响
4. `persistence.set_agent_channel()` 同步持久化，让重连后的 agent 自动回到正确频道
5. 向后兼容：不改变现有 MSG_SET_ACTIVE_CHANNEL 的调用方式，只是增加触发点

### 3.2 方向 B：过渡期频道切换命令

**新增两条 admin 命令：**

**`!pipeline_activate <round_name>`** — 对管线中所有参与角色批量发 MSG_SET_ACTIVE_CHANNEL 到管线工作室

```
!pipeline_activate R50
  ↓
服务端：从 _PIPELINE_STATE 读取 R50 的管线信息
  获取工作室 ID（ws_id）
  从 Agent Card 获取管线所有角色列表
  对每个角色：
    persistence.set_agent_channel(agent_id, ws_id)
    send MSG_SET_ACTIVE_CHANNEL → agent_id
  返回 ✅ 激活完成：N 人频道已切换
```

**`!step_handoff <round_name>`** — 对当前 Step 的下一角色发 MSG_SET_ACTIVE_CHANNEL

```
!step_handoff R50
  ↓
服务端：从 _PIPELINE_STATE 读取 R50 的当前 Step
  获取下一角色（如 Step2 → dev）
  从 Agent Card 找到该角色的 agent_id
  persistence.set_agent_channel(agent_id, ws_id)
  send MSG_SET_ACTIVE_CHANNEL → agent_id
  返回 ✅ dev 频道已切换至工作室
```

**操作流程（过渡期场景）：**

```
场景 1：管线启动
  PM: !pipeline_start R50 --from step2 ✅
  PM: @admin-bot 请执行 !pipeline_activate R50 🔄
  admin-bot: !pipeline_activate R50 ✅
  全员到位 → 启动正常

场景 2：Step 交接
  架构师: !step_complete Step2 --output abc123 ✅
  PM: @admin-bot 请执行 !step_handoff R50 🔄
  admin-bot: !step_handoff R50 ✅
  dev 频道已切 → 收到点名通知
```

---

## 4. 架构原则

### 4.1 方向 A 利用已有 R37 机制

方向 A 不是从头写频道切换代码。`handler.py` 的 R37 B-1 代码段（≈行 2402-2437）已经实现了完整的 MSG_SET_ACTIVE_CHANNEL 发送逻辑：遍历工作区成员、持久化 `persistence.set_agent_channel()`、向在线连接发 switch_payload。方向 A 只需在 `!step_complete` 和 `!rollcall_next` 的下一角色指派路径中，调用相似逻辑。

### 4.2 方向 B 是方向 A 的子集

方向 B 的 `!step_handoff` 与方向 A 的自动切换共享同一段 MSG_SET_ACTIVE_CHANNEL 代码。方向 B 是显式调用，方向 A 是隐式自动触发。两个方向可平行开发：

- 先写 MSG_SET_ACTIVE_CHANNEL 发送函数（可复用 R37 代码块）
- 然后注册两条 admin 命令（方向 B）
- 再在 `!step_complete` / `!rollcall_next` 中挂载自动调用（方向 A）

### 4.3 过渡期管线的运转不需要等部署

方向 B 不需要等容器部署即可生效——代码在 dev 分支上开发完成后，admin-bot 即可在开发容器中执行 `!step_handoff` 和 `!pipeline_activate`。R50 的管线开发本身可以靠方向 B 自我驱动，形成「用新命令开发新功能」的自举模式。

---

## 5. 验收标准

### 方向 A：Step 交接自动切活跃频道

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| A-1 | `!step_complete StepN --output xxx` 点名下一角色时，自动发送 MSG_SET_ACTIVE_CHANNEL 到该角色的活跃连接 | 🔴 P0 |
| A-2 | MSG_SET_ACTIVE_CHANNEL 的目标频道为当前管线工作室（ws_id） | 🔴 P0 |
| A-3 | `persistence.set_agent_channel()` 同步持久化，agent 重连后自动进入工作室 | 🔴 P0 |
| A-4 | `!rollcall_next` 手动点名时也触发 MSG_SET_ACTIVE_CHANNEL | 🟡 P1 |
| A-5 | 仅活跃管线的 Step 交接触发频道切换，非管线场景普通点名不触发 | 🟡 P1 |
| A-6 | 频道切换后发文本跟进通知（如「📋 Step 3 轮到你了」） | 🟡 P1 |
| A-7 | **（端到端）** 完整跑一轮管线：Step 2 → 3 → 4 → 5 → 6，每步交接后下一角色活跃频道自动切换，不需要外部干预 | 🔴 P0 |

### 方向 B：过渡期频道切换命令

| # | 验收标准 | 优先级 |
|:-:|:---------|:------:|
| B-1 | `!pipeline_activate R50` 将 R50 管线所有角色的活跃频道切换到管线工作室 | 🔴 P0 |
| B-2 | `!pipeline_activate` 的 `min_role` 为 3（仅 admin/workspace_admin 可执行） | 🔴 P0 |
| B-3 | `!step_handoff R50` 将下一角色的活跃频道切换到管线工作室 | 🔴 P0 |
| B-4 | `!step_handoff` 的 `min_role` 为 3 | 🔴 P0 |
| B-5 | 两条命令都调用 `persistence.set_agent_channel()` 持久化频道切换 | 🟡 P1 |
| B-6 | 两条命令返回明确的执行结果（已切换人数 / 无活跃管线 / 角色不可达） | 🟡 P1 |
| B-7 | 当 _PIPELINE_STATE 中无活跃管线时，返回 `❌ 无活跃管线` | 🟡 P1 |
| B-8 | 当管线工作区已不存在时，返回 `❌ 工作室已不存在` | 🟡 P1 |

---

## 6. 不纳入本轮需求

- **❌ 非管线场景的点名自动切频道** — 只在 `!step_complete` / `!rollcall_next` / `!pipeline_activate` 中触发。普通 `!rollcall_role` 保持现有行为
- **❌ 大厅隔离自动恢复** — `!pipeline_start` 暂停大厅接收的机制已存在（R42），不在本轮优化范围
- **❌ Agent Card 管理增强** — R49 的 `!agent_card list/get/set/unset/reload` 已够用
- **❌ 超时检测增强** — R49 已有超时告警 + rerollcall，不在本轮范围
- **❌ Web 端改进（F-9）** — 不属本轮管线范畴
- **❌ 文档/代码脱敏** — 不属本轮管线范畴

---

## 7. 设计要点

### 7.1 方向 A 的改动位置

在 `_cmd_step_complete` 中，当判断当前 Step 为最后一步以外的 Step 时，调用 `_cmd_rollcall_next` 点名下一角色：

- 当前点名代码（≈行 1290-1320）只发了文本通知到目标角色的当前频道
- 需要在此处增加：获取目标角色在工作区中的 agent_id → 发 MSG_SET_ACTIVE_CHANNEL → 持久化频道 → 再发文本通知

**建议代码结构：**

```python
# 在 _cmd_step_complete 中，点名下一角色后立即切频道
if next_role_agent_id:
    # 1. 持久化切换
    persistence.set_agent_channel(next_role_agent_id, ws_id)
    persistence.save_agent_channels(config.DATA_DIR)
    # 2. 在线连接发 MSG_SET_ACTIVE_CHANNEL
    switch_payload = json.dumps({
        "type": p.MSG_SET_ACTIVE_CHANNEL,
        p.FIELD_CHANNEL: ws_id,
        "from_name": "系统",
        "content": f"请确认活跃频道已切换至工作室",
        "ts": time.time(),
    })
    for conn in _connections.get(next_role_agent_id, set()):
        try:
            await conn.send_str(switch_payload)
        except Exception:
            pass
    # 3. 再发文本通知
    # 已有在此处的文本通知代码
```

> 建议将这套逻辑提取为独立函数 `_switch_agent_channel(agent_id, target_ch)`，使方向 A 和方向 B 可共用。

### 7.2 方向 B 的改动范围

在 `_ADMIN_COMMANDS` 注册表中新增两条命令：

```python
_ADMIN_COMMANDS = {
    # ... 现有命令 ...
    "pipeline_activate": {
        "min_role": 3,
        "description": "将管线所有参与者切到工作室",
        "handler": "_cmd_pipeline_activate",
        "workspace_scope": False,
    },
    "step_handoff": {
        "min_role": 3,
        "description": "将下一角色切到工作室",
        "handler": "_cmd_step_handoff",
        "workspace_scope": False,
    },
}
```

两条命令的 handler 均复用 `_switch_agent_channel` 函数。

---

## 8. 决策记录

> 以下 Q&A 由项目负责人在 2026-06-28 TG DM 中逐条确认。

| # | 问题 | 决策 | 体现位置 |
|:-:|:-----|:----|:---------|
| Q1 | 方向 A 和 B 是否都纳入本轮？ | ✅ **都做。** B 是过渡方案，确保方向 A 开发部署前管线不卡死。A 开发完部署后，B 退化为备选。 | §2 需求范围 |
| Q2 | 方向 B 命令的 `min_role` 设多少？ | ✅ **3（工作室管理员）。** 仅 admin-bot 和 workspace_admin 可执行。管线启动者（PM）如需执行，需在工作群 @admin-bot。 | §5 B-2/B-4 |
| Q3 | 过渡期管线如何自举开发？ | ✅ 方向 B 在 dev 容器开发完成后即可使用。admin-bot 用 `!pipeline_activate` + `!step_handoff` 驱动 R50 管线自己。 | §4.3 |

> 技术方案（具体实现方式）由架构师决定。
