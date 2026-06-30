# R58 产品需求 — 系统通知→自然 @mention 触发改造 + 管线自动推进修复

> **版本：** v0.1（初稿）
> **状态：** 📝 草稿（待项目负责人审核）
> **产品经理：** 🧐 PM
> **日期：** 2026-06-30
> **本轮改动范围：** 仅第①类（服务器代码 `server/handler.py`，集中于管线 Step 交接通知 + 初始点名触发链路）
> **R57 遗留项：** 💡 backup_active 清理（✅ 已在 R57 commit `8dacbb9` 修复）

---

## 1. 问题背景

### 1.1 R57 交付后管线运行实际状态

R57 实现了**在线状态预检 + 点名发现 + 主备自动换人**（方向 A）+ 角色名显示（方向 C），代码级 16/16 验收全绿，已合并部署 `ws-bridge:r57`。

但 R57 实操中暴露了一个**核心基础设施缺陷**：

| 场景 | R57 期望行为 | R57 实际行为 |
|:-----|:------------|:------------|
| `!pipeline_start` 初始化点名（点名全部 6 个 bot） | 各 bot 回复 ACK，确认活跃频道切换 | ❌ **全员超时** — 6/6 未回复 ACK |
| `!step_complete` Step 交接点名主角 | 主角 30s 内回复 ACK → 正常推进 | ❌ **主角不响应** — 系统通知送达但「看不见」 |
| `!step_complete` 定向通知下一角色 | 主角在线 → 收到 task 通知开始工作 | ❌ **收到但不工作** — 需 PM 手动 @mention |

### 1.2 实操暴露的触发失败全记录（R57 实证）

| Step | 目标角色 | 系统触发方式 | 结果 | 人工兜底方式 |
|:----:|:--------:|:------------|:-----|:------------|
| Step 1 启动 | 全员 | MSG_SET_ACTIVE_CHANNEL + 协议广播 | ❌ 全员 30s 超时 | 项目负责人 TG 协调+点名 |
| Step 2 技术方案 | arch | `_send_to_agent` 定向 + 广播 | ❌ 无响应 | PM 在工作室内 @arch 派活（含需求URL+WORK_PLAN）→ ✅ |
| Step 3 编码 | dev | `_send_to_agent` 定向 + 广播 | ❌ 无响应 | PM 在工作室内 @dev 派活（含技术方案URL）→ ✅ |
| Step 4 审查 | review | `_send_to_agent` 定向 + 广播 | ❌ 无响应 | PM 在工作室内 @review 派活 → ✅ |
| Step 5 测试 | qa | `_send_to_agent` 定向 + 广播 | ❌ 无响应 | PM 在工作室内 @qa 派活 → ✅ |
| Step 6 部署 | admin | `_send_to_agent` 定向 + 广播 | ❌ 无响应 | PM 在工作室内 @admin 派活 → ✅ |

> **关键数据点：** `_send_to_agent` 确认送达（`delivery: sent=5`），5 个 bot 都收到了 WebSocket 消息，但全部未触发工作模式。直到 PM 在工作室内写自然 @mention + 完整上下文，bot 才响应。

### 1.3 根因分析

```
系统通知链路（当前 ❌）:
  _cmd_step_complete
    → _send_to_agent(agent_id, text)           # 类型: MSG_BROADCAST
    → WebSocket 直接发给 bot                     # from_name: "系统"
    → bot 网关收到但视作 "系统通知"                  → 不触发 LLM 工作模式

人工 @mention 链路（已验证 ✅）:
  PM 在工作区写 "@bot名 Step X 到了..."
    → handle_broadcast
    → 工作室广播给所有成员                       # from_name: PM 角色名
    → bot 网关收到 "人类 @mention"               → 触发 LLM 工作模式
```

**根本差异：**

| 维度 | 系统通知（当前） | 人工 @mention（有效） |
|:----|:--------------|:--------------------|
| `from_name` | "系统" | PM 角色名 |
| 消息格式 | 结构化文本（`🎯 新任务：R57 step3 (dev)`） | 自然 @mention + 完整上下文 |
| 传递路径 | 直接 WS 协议发送（跳过 chat log） | 经过 handle_broadcast → chat log |
| bot 网关处理 | 系统消息 → 静默处理 | 人类 @mention → LLM 触发 |

### 1.4 核心理念

> **R57 实操铁律（已验证 5/5 次）：**
> - `_send_to_agent` + `from_name: "系统"` = ❌ bot 不工作
> - 自然 @mention + `from_name: PM 角色名` + 完整上下文 = ✅ bot 立刻工作
>
> **修复方向：** 让系统代码发出的任务交接通知，看起来和工作室内人类 PM 写的 @mention 消息完全一致。
> 不改 bot 客户端——改服务器端发出的消息格式和传递路径。

```
R55: 管线代码正确但通信断裂 → 每 Step 需项目负责人 TG 私聊激活
  ↓
R56: 定向+回退双保险 + 过渡期SOP → 在线bot全自动，离线bot通知不丢
  ↓
R57: 在线预检 + 点名发现 + 主备换人 → 主角离线自动切备用
  ↓
R58: 系统通知 → 自然 @mention 格式改造
      → 代码发的通知和 PM 手写的 @mention 效果一样
      → 消除「通知送达但 bot 不工作」的最后一公里
```

---

## 2. 方向说明

### 方向 A（核心 🔴 P0）：Step 交接通知 → 自然 @mention 改造

| 项目 | 说明 |
|:-----|:------|
| **问题** | `!step_complete` 通过 `_send_to_agent` + `from_name: "系统"` 发送 Step 交接通知，bot 网关视作系统通知不触发工作模式。每 Step 需 PM 人工在工作室追加 @mention |
| **目标** | `!step_complete` 发出的任务交接通知，bot 收到后能像收到人类 @mention 一样自动触发工作模式 |
| **改动范围** | `server/handler.py` — `_cmd_step_complete` + `_send_to_agent` 调用点 |

#### 方向 A 设计详述

##### A1：通知发送方身份改造 — `from_name` 改为 PM 角色名

当前 `_cmd_step_complete` 中：

```python
# 当前（❌ 不触发工作模式）
rollcall_msg = f"@**{primary_name}** Step「{next_step}」轮到你了，请在 30 秒内回复确认"
_persist_broadcast(sender_ch, "系统", rollcall_msg)
for conn in conns:
    await _send(conn, {"type": "broadcast", "channel": sender_ch,
                       "from_name": "系统", "content": rollcall_msg, ...})

targeted_notify = f"🎯 新任务：{round_name} {next_step} ({next_role})\n{context_summary}"
await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)  # from_name="系统"
```

改造后：

```python
# 改造后（✅ 模拟 PM @mention 效果）
# 通知使用 PM 角色身份，走工作室广播（不走 _send_to_agent 直接连接）
pm_name = "PM"  # PM 名称，可从配置/环境变量读取

rollcall_msg = f"@{primary_name} 🚨 Step「{next_step}」到你了！\n\n📄 需求文档：{req_url}\n📋 WORK_PLAN：{plan_url}\n🔗 上一步产出：{output_ref}\n\n请确认收到并开始工作。"
_persist_broadcast(sender_ch, pm_name, rollcall_msg)

# 同时广播到所有在线成员的 WS 连接（from_name 用 PM 名）
for member_id in ws_obj.members:
    for conn in list(_connections.get(member_id, set())):
        try:
            await _send(conn, {"type": "broadcast", "channel": sender_ch,
                               "from_name": pm_name, "content": rollcall_msg, ...})
        except Exception:
            pass
```

**关键变化：**
- `from_name`: "系统" → PM 角色名
- 消息格式：简略文本 → 完整的 @mention + 需求文档 URL + WORK_PLAN URL + 上一步产出
- 传递路径：直接 WS 发送 → 工作室频道广播（走 handle_broadcast 路径）

> **设计哲学：** 既然人工 @mention 有效，就让代码发的通知长得和人工发的一模一样。不改 bot 端逻辑——只改服务端发出的消息。

##### A2：Step 交接完整上下文模板

每条 Step 交接通知包含（可配置）：

```
@{bot_name} 🚨 R{N} {step_name} 到你了！

📄 需求：{req_url}
📋 WORK_PLAN：{plan_url}
🔗 上一步产出：{output_ref}

请确认收到后开始工作。完成后调用 !step_complete {step_name} --output <sha>
```

**参数来源：**
- `req_url`: 从 `PIPELINE_STATE` 或 `_cmd_step_complete` 的 round_name 拼 `docs/R{N}/R{N}-product-requirements.md`
- `plan_url`: 从 `PIPELINE_STATE` 的 `work_plan_url` 字段拿（R48 已保存）
- `output_ref`: 上一步的 `--output <sha>` 参数

##### A3：pipeline_start 初始点名同等待遇

`_cmd_pipeline_start` 中调用 `_cmd_rollcall_next` 时，当前通过 `_broadcast_active_channel()` 发 MSG_SET_ACTIVE_CHANNEL 协议消息。这个协议消息 bot 网关内部处理（切频道）但不触发工作模式。

改造：在 MSG_SET_ACTIVE_CHANNEL 之后，**追加一条自然 @mention 格式的广播**到工作室：
```
@全员 🚀 {round_name} 管线已启动！
下一棒：{target_role} → {start_step}

📄 需求：{req_url}
📋 WORK_PLAN：{plan_url}

各 bot 请切换活跃频道到此工作室，确认就绪。
```

这条广播用 PM 角色名（`from_name`）发送，走工作室频道广播路径。

##### A4：`_send_to_agent` 调用点评估

R57 中 `_send_to_agent` 在 `_cmd_step_complete` 中用于主力通知（当前 ❌ 无效）。如果方向 A 改造后通知通过工作室广播（`from_name: PM`）直接触发 bot，`_send_to_agent` 调用可以**保留作为回退**（R56 双保险模式），但不再依赖它作为主要通知路径。

| 通知路径 | 当前状态 | 改造后 | 说明 |
|:---------|:--------:|:------|:------|
| 工作室 @mention 广播 | ❌ 系统身份 | ✅ PM 身份 | 主力通知路径 |
| `_send_to_agent` 定向 | ❌ 系统身份 | 🟡 保留作回退 | 同时发送，作为双保险 |
| MSG_SET_ACTIVE_CHANNEL | ✅ 切频道 | ✅ 保留 | 只负责切频道，不负责触发工作 |

#### 验收标准

| # | 验收标准 | 验证方法 |
|:-:|:---------|:---------|
| A-1 | `!step_complete` 后工作室出现 PM 身份的 @mention 通知（`from_name` 非「系统」） | 检查工作室消息 `from_name` 字段 |
| A-2 | PM 身份的通知内容包含：bot @mention + 需求 URL + WORK_PLAN URL + 上一步产出 | 检查通知内容格式 |
| A-3 | 目标 bot 收到 PM 身份的通知后回复确认（触发工作模式）——期待与人工 @mention 相同效果 | 实操 Step 交接 |
| A-4 | `_send_to_agent` 定向通知同时发送（不删除，作为双保险保留） | 检查服务器日志 |
| A-5 | `!pipeline_start` 初始点名后，工作室出现 PM 身份的全员 @mention | 启动管线检查 |
| A-6 | `from_name` 可配置（PM 名称不在代码中硬编码）— 支持未来换 PM | 检查配置/常量定义 |

---

### 方向 B（辅助 🟡 P1）：初始点名响应增强

方向 A 覆盖了 Step 交接通知的触发问题。但初始点名（`!pipeline_start` 的 `_broadcast_active_channel`）用了 MSG_SET_ACTIVE_CHANNEL 协议消息，bot 网关内部处理切频道但不回应 ACK。

| 项目 | 说明 |
|:-----|:------|
| **问题** | `!pipeline_start` 后 `_broadcast_active_channel()` 发 MSG_SET_ACTIVE_CHANNEL 协议消息切频道，bot 网关切完频道后不回 ACK，导致「点名超时」 |
| **目标** | MSG_SET_ACTIVE_CHANNEL 后，bot 能回复 ACK 确认频道已切换。或降低对 ACK 的依赖——只要频道已切换、消息能到达，就不算点名失败 |

#### 方向 B 设计思路

**B1：ACK 超时阈值降低**（快速解决）

当前 ACK 等待 30 秒。如果初始点名时 6 个 bot 都静默（不响 PROTOCOL ACK），但频道切换生效了——PIPELINE_STATE 中活跃频道已经指向工作室。这种情况下，虽然点名「超时」但实际功能正常。

**方案：** 将 `!pipeline_start` 的初始点名 ACK 超时视为「软检查」——超时后不阻断管线启动，只记录「N 人未确认 ACK」。后续消息通过方向 A 的自然 @mention 格式发出后，bot 会在工作室内回复。

**B2：MSG_SET_ACTIVE_CHANNEL ACK 兼容扩展**

如果可能，在 MSG_SET_ACTIVE_CHANNEL 协议消息中增加一个 `require_ack` 字段，让 bot 网关在切换频道后自动回复 ACK（无需 LLM 参与）。这需要 bot 网关端的配合，属于跨端改动。

> **B2 可行性取决于 bot 网关实现。** 如果网关不支持，则优先 B1。

#### 验收标准

| # | 验收标准 | 验证方法 |
|:-:|:---------|:---------|
| B-1 | `!pipeline_start` 后初始点名不阻塞——超时 bot 不阻断管线，仅记录日志 | 启动管线点名超时后检查状态 |
| B-2 | 方向 A 的 PM 身份 @mention 广播后，bot 能正常响应 | 检查 bot 回复 |
| B-3 | `!pipeline_status` 正确反映各成员活跃频道（不因 ACK 超时而错误标记离线） | 检查状态输出 |

---

### 方向 C（可选 🟢 P2）：错误回溯时按角色搜索工作区历史消息

R57 实操中发现：当需要判断某 bot 是否已收到 Step 通知时，PM 需要回溯工作室历史。但系统通知和人工 @mention 都存在，区分不出来哪个被 bot 响应了。

| 项目 | 说明 |
|:-----|:------|
| **问题** | Step 交接时 PM 无法快速判断 bot 是否已响应——需要在工作室聊天记录里翻找 |
| **目标** | `!pipeline_status` 增加各 Step 的通知状态：已通知 / 已确认 ACK / 无响应 |
| **改动量** | ~10 行 `handler.py`——在 `_cmd_step_complete` 的 ACK 检测点记录通知+确认状态到 `pstate` |

#### 验收标准

| # | 验收标准 |
|:-:|:---------|
| C-1 | `!pipeline_status` 显示每个 Step 的通知状态：📨 已通知 / ✅ 已确认 / ❌ 无响应 |
| C-2 | R57 现有功能（主备换人、角色名显示）不受影响 |

---

## 3. 方向间依赖关系

```
方向 A（通知触发改造）← 核心修复，不依赖 B/C
方向 B（初始点名响应）← 与 A 互补，可独立编码
方向 C（状态增强）    ← 纯展示层，独立
```

**优先次序：** **A 第一核心**（解决「通知送达但 bot 不工作」的根本矛盾），**B 过渡期**（降低初始点名阻断），**C 兜底**（方便 PM 监控）。

---

## 4. R57 遗留项状态确认

| 遗留项 | R57 状态 | R58 处置 |
|:-------|:---------|:---------|
| 💡 `backup_active` 清理 | ✅ R57 commit `8dacbb9` 已修复（2 行） | 无需再处理 |
| 🔴 系统通知无法触发 bot 工作模式 | ❌ 未修复（跨轮次基础设施问题） | **本轮方向 A 核心** |
| `_connections` 在线预检 (A-2) | ✅ R57 已实现（0s 离线切备用） | 保留 |
| 主备点名换人 (A-1~A-9) | ✅ R57 已实现 | 保留 |
| 角色名显示 (C-1~C-4) | ✅ R57 已实现 | 保留 |

---

## 5. 不纳入本次需求

| 事项 | 原因 | 去向 |
|:-----|:------|:-----|
| Agent Card 角色映射持久化重构（F-16） | 架构层改造 | TODO.md F-16 |
| 多管线并行支持 | 单管线先跑通 | 后续轮次 |
| F-3 P3 角色体系 | 独立项 | TODO.md F-3 |
| F-15 workspace_reset | 独立项 | TODO.md F-15 |
| 修改 bot 网关代码处理系统通知 | 跨系统改动，ws-bridge 不应负责 | ❌ 不纳入 |

---

## 6. 设计哲学

### 系统通知要伪装成人

bot 网关把 `from_name: "系统"` 的消息静默处理掉了。既然改网关困难，就改消息本身——让系统发的通知看起来和 PM 发的一模一样。**不改接收方，改发送方。**

### @mention + 完整上下文是黄金标准

R57 五次实操验证：仅仅 `@bot名 干活` 不够，必须附上全部上下文（需求文档 URL + WORK_PLAN URL + 上一步产出）。方向 A 模板包含这些。

### ACK 超时是软信号不是硬阻断

点名 ACK 超时不代表 bot 不在工作。MSG_SET_ACTIVE_CHANNEL 切频道是有效的，bot 的 LLM 不开 ACK 自动回复而已。方向 B 降低初始点名的硬阻断性。

### 保留双保险不删旧路径

方向 A 改造后不删除 `_send_to_agent` 调用——保留它作为离线回退（R56 双保险模式）。主力路径从 `_send_to_agent` 切换为工作室广播（PM 身份）。

---

## 7. 开放问题

| # | 问题 | 说明 | 状态 |
|:-:|:-----|:------|:----:|
| Q1 | PM 名称从哪获取？从配置/环境变量读取，还是从 auth.get_users() 的 PM 角色成员获取？ | 决定 from_name 的值来源 | ⏳ 待决策 |
| Q2 | 是否需要支持多 PM 场景（项目负责人和 PM 交替发通知）？ | from_name 动态选择 | ⏳ 待决策 |
| Q3 | MSG_SET_ACTIVE_CHANNEL 能否增加 `require_ack` 协议字段？ | 需要看 bot 网关是否支持 | ⏳ 待技术评估 |

> 纯技术方案类问题（通知消息的广播函数实现、from_name 的来源、上下文 URL 的拼接方式）由架构师决定。
