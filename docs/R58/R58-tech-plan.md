# R58 技术方案 — 系统通知→自然 @mention 触发改造 + 管线自动推进修复

> **版本：** v1.0
> **状态：** ✅ 定稿
> **架构师：** 🏗️ arch
> **日期：** 2026-06-30
> **基于需求文档：** `docs/R58/R58-product-requirements.md` v0.1
> **基于工作计划：** `docs/R58/WORK_PLAN.md` v1.0
> **涉及源文件：** `server/handler.py`（仅第①类服务器代码）

---

## 目录

- [1. 概述](#1-概述)
- [2. 方向 A（P0）：Step 交接通知 → 自然 @mention 改造](#2-方向-ap0step-交接通知--自然-mention-改造)
  - [A1: PM 名称来源方案](#a1-pm-名称来源方案)
  - [A2: `_cmd_step_complete` — 主力通知路径改造](#a2-_cmd_step_complete--主力通知路径改造)
  - [A3: `_cmd_pipeline_start` — 初始点名 PM 身份通知](#a3-_cmd_pipeline_start--初始点名-pm-身份通知)
  - [A4: `_persist_broadcast` 从名统一](#a4-_persist_broadcast-从名统一)
  - [A5: 双保险保留 `_send_to_agent`](#a5-双保险保留-_send_to_agent)
  - [A6: 配置化 PM 名称](#a6-配置化-pm-名称)
- [3. 方向 B（P1）：初始点名 ACK 超时软检查](#3-方向-bp1初始点名-ack-超时软检查)
  - [B1: `_cmd_pipeline_start` 中的点名处理](#b1-_cmd_pipeline_start-中的点名处理)
  - [B2: `_cmd_rollcall_next` 的 ACK 超时不阻断](#b2-_cmd_rollcall_next-的-ack-超时不阻断)
- [4. 方向 C（P2）：通知状态跟踪 + `!pipeline_status` 增强](#4-方向-cp2通知状态跟踪--pipeline_status-增强)
  - [C1: pstate 通知状态字段](#c1-pstate-通知状态字段)
  - [C2: `_cmd_step_complete` 中记录通知状态](#c2-_cmd_step_complete-中记录通知状态)
  - [C3: `_cmd_pipeline_status` 展示通知状态](#c3-_cmd_pipeline_status-展示通知状态)
- [5. 备用方案：arch/dev 不响应的兜底](#5-备用方案archdev-不响应的兜底)
- [6. 改动汇总](#6-改动汇总)
- [7. 验证清单](#7-验证清单)

---

## 1. 概述

### 核心问题

`!step_complete` 当前通过 `_send_to_agent()` + `from_name: "系统"` 发送 Step 交接通知。bot 网关收到后将此消息视为"系统通知"——静默处理，**不触发 LLM 工作模式**。PM 人工在工作室内写自然 @mention 后 bot 立刻响应（已验证 5/5 次）。

### 修复理念

> 不改 bot 客户端——改服务器端发出的消息格式和传递路径。
> 让代码发的通知和 PM 手写的 @mention 效果一样。

### 方向总览

| 方向 | 优先级 | 说明 | 行数估计 |
|:----:|:------:|:-----|:--------:|
| **A** | 🔴 P0 | Step 交接通知 → PM 自然 @mention 格式改造 | ~30 行 |
| **B** | 🟡 P1 | 初始点名 ACK 超时降为软检查 | ~5 行 |
| **C** | 🟢 P2 | `!pipeline_status` 增加通知状态跟踪 | ~10 行 |

### 改动范围（仅 `server/handler.py`）

```
_cmd_step_complete     (~L1520-1540)   ← A2: 主力通知路径改造
_cmd_pipeline_start    (~L1290-1308)   ← A3: 初始点名 PM 通知 + B1: ACK 软检查
_cmd_rollcall_next     (~L810-813)     ← B2: ACK 超时不阻断
_persist_broadcast     (~L817-834)     ← A4: from_name 从名统一
_cmd_pipeline_status   (~L1922-1981)   ← C3: 展示通知状态
_pstate 记录点         (~L1549)        ← C2: 记录通知状态
config.py              (~L62-78)       ← A6: 新增 PM_NAME 配置
```

---

## 2. 方向 A（P0）：Step 交接通知 → 自然 @mention 改造

### A1: PM 名称来源方案

**方案：新增 `config.py` 常量 `PIPELINE_PM_NAME`，环境变量 `WS_PM_NAME` 可覆盖**

```python
# config.py 新增
PIPELINE_PM_NAME: str = os.environ.get("WS_PM_NAME", "PM")
```

**原因：**
1. 当前 `auth.get_users()` 中无显式 PM 角色——现有角色为 `admin/arch/dev/review/qa/member`
2. 管内线的 PM 由项目负责人指定，可能变化——配置化支持换人
3. `triggerer_id`（pstate 中保存）可辅助判断，但不作为主来源（触发者可能不是当轮 PM）
4. 默认值 "PM" 与环境现有的 @PM 角色名一致

**读取方式：**
```python
# 在 handler.py 中
pm_name = config.PIPELINE_PM_NAME  # 或从匹配的 triggerer_id 中获取实际用户名
```

### A2: `_cmd_step_complete` — 主力通知路径改造

**当前位置**：`handler.py` L1520-L1539

**改动说明：**

在 L1520-L1539 区域，`_cmd_step_complete` 已完成：
- Step 完成标记 → 查找下一角色 → 构造 `targeted_notify`
- 已通过 `_find_agents_by_role` 筛选 `target_agents`
- 已调用 `_send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)`（`from_name="系统"`）

**改造方案：在原有 `_send_to_agent` 调用之前（或之后），新增 PM 身份广播路径**

```
原代码（L1520-L1539）:
  targeted_notify = f"🎯 新任务：{round_name} {next_step} ({next_role})\n{context_summary}"
  for agent_id in target_agents:
      await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
  rollcall_result = f"📨 已通知 {next_role_display}（{len(target_agents)} 人）接管 {next_step}"

改后代码:
  # ── R58 A2: PM 自然 @mention 主力通知路径 ──
  # 构造 PM 身份的 @mention 格式通知（模拟人工 @mention）
  pm_name = config.PIPELINE_PM_NAME
  
  # 构造完整上下文模板
  next_role_mention = f"@{next_role_display}"  # @arch, @dev 等
  req_url = f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/{round_name}-product-requirements.md"
  plan_url = pstate.get("work_plan_url", f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/WORK_PLAN.md")
  
  mention_msg = (
      f"{next_role_mention} 🚨 R58 {next_step} 到你了！\n\n"
      f"📄 需求：{req_url}\n"
      f"📋 WORK_PLAN：{plan_url}\n"
      f"🔗 上一步产出：{output_ref}\n\n"
      f"请确认收到后开始工作。完成后调用 !step_complete {next_step} --output <sha>"
  )
  
  # 持久化 + 写入 chat_log（以 PM 身份）
  _persist_broadcast(sender_ch, pm_name, mention_msg)
  
  # 向工作室所有在线成员 WS 连接广播（with from_name=PM）
  broadcast_payload = json.dumps({
      "type": "broadcast",
      "channel": sender_ch,
      "from_name": pm_name,
      "from": pm_name,
      "content": mention_msg,
      "ts": time.time(),
  })
  for member_id in ws_obj.members:
      for conn in list(_connections.get(member_id, set())):
          try:
              if hasattr(conn, "send_str"):
                  await conn.send_str(broadcast_payload)
              elif hasattr(conn, "send"):
                  await conn.send(broadcast_payload)
          except Exception:
              pass
  
  # ── R55 F: 保留原定向通知路径（双保险回退）──
  targeted_notify = f"🎯 新任务：{round_name} {next_step} ({next_role})\n{context_summary}"
  for agent_id in target_agents:
      await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
  
  rollcall_result = f"📨 已通知 {next_role_display}（{len(target_agents)} 人）接管 {next_step}"
```

**关键设计点：**
- 广播到**工作室所有成员**（不只是 `target_agents`）——所有在线 bot 都会在工作室看到这条消息，但只有被 @mention 的目标角色响应。这与人工 PM @mention 的行为完全一致。
- `from_name` 设置为 PM 名称（非"系统"）——bot 网关识别为人类 @mention 并触发工作模式。
- 广播 payload 的 `type: "broadcast"` + `channel: sender_ch`——bot 端识别为工作室频道消息。
- `_persist_broadcast(sender_ch, pm_name, mention_msg)` — 写入 message_store 和 chat_log，离线 bot 重连后可读取。
- **原 `_send_to_agent` 调用保留不动**——双保险回退路径（R56 模式），一条消息同时走两条路径。

### A3: `_cmd_pipeline_start` — 初始点名 PM 身份通知

**当前位置**：`handler.py` L1288-L1308

**改动说明：**

当前逻辑（L1288-L1308）：
1. `await _broadcast_active_channel(ws_id)` — 发 MSG_SET_ACTIVE_CHANNEL 切频道
2. 然后 `await _cmd_rollcall_next(...)` — 点名架构师

**改造方案：`_broadcast_active_channel` 后追加一条 PM 身份的全员 @mention 广播**

```python
# ── R58 A3: 初始点名 PM 身份全员通知 ──
pm_name = config.PIPELINE_PM_NAME
req_url = f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/{round_name}-product-requirements.md"
plan_url = work_plan_url or f"https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/{round_name}/WORK_PLAN.md"

kickoff_msg = (
    f"@全员 🚀 {round_name} 管线已启动！\n"
    f"下一棒：{target_role} → {start_step}\n\n"
    f"📄 需求：{req_url}\n"
    f"📋 WORK_PLAN：{plan_url}\n\n"
    f"各 bot 请切换活跃频道到此工作室，确认就绪。"
)

_persist_broadcast(ws_id, pm_name, kickoff_msg)

# 广播到工作室所有在线连接
kickoff_payload = json.dumps({
    "type": "broadcast",
    "channel": ws_id,
    "from_name": pm_name,
    "from": pm_name,
    "content": kickoff_msg,
    "ts": time.time(),
})
for member_id in ws_obj.members:
    for conn in list(_connections.get(member_id, set())):
        try:
            if hasattr(conn, "send_str"):
                await conn.send_str(kickoff_payload)
            elif hasattr(conn, "send"):
                await conn.send(kickoff_payload)
        except Exception:
            pass
```

**放置位置：** 在 L1290（`_broadcast_active_channel`）**之后**、L1292（查 Step 映射表）**之前**。

**与现有点名关系：**
- `_broadcast_active_channel` (MSG_SET_ACTIVE_CHANNEL) — 继续负责频道切换 + ACK 等待（协议层）
- `kickoff_msg` (PM 身份 @mention) — 负责触发 bot 工作模式（业务层）
- `_cmd_rollcall_next` (L1304) — 继续点名架构师，附带文档 URL

> **三条路径并行：** 协议层同步（MSG_SET_ACTIVE_CHANNEL）+ 业务层触发（PM @mention）+ 角色指定（rollcall_next）。互不干扰。

### A4: `_persist_broadcast` 从名统一

`_persist_broadcast` 当前签名 `def _persist_broadcast(channel, from_name, content_text)` 已支持自定义 `from_name`。**无需修改。** 但要注意：当前所有调用点均传 `"系统"`。仅 R58 A2/A3 新增的调用传 PM 名称。

```python
# 现有调用（全部用"系统"）——保持不变
_persist_broadcast(sender_ch, "系统", ...)

# R58 新增调用——用 PM 名称
_persist_broadcast(sender_ch, config.PIPELINE_PM_NAME, mention_msg)
```

**检查事项：** 确保 `_persist_broadcast` 中 `write_chat_log` 的第二参数使用了正确的 `from_name`（已使用——`write_chat_log(from_name, content_text, ...)`）。

### A5: 双保险保留 `_send_to_agent`

`_send_to_agent` 中所有 `from_name` 硬编码为 `"系统"`。

```python
# _send_to_agent L1599, L1619 等
"from_name": "系统",
```

**R58 不修改 `_send_to_agent`**。两项原因：
1. `_send_to_agent` 保留为回退双保险（R56 模式）——主力路径（PM 身份广播）失败时，还有一条"系统"身份的直接通知
2. 某些 bot 网关对 `MSG_BROADCAST` 类型的系统消息有特殊处理（如持久化）——保留其原有语义

**但 `_send_to_agent` 的 fallback 路径（L1596-L1611）中 `from_name` 也保留了 `"系统"`。** 这是有意为之——主力 PM 广播 + 回退系统通知 = 双重保障。

### A6: 配置化 PM 名称

**`config.py` 新增常量：**

```python
# ── R58 A6: Pipeline PM display name ──
PIPELINE_PM_NAME: str = os.environ.get("WS_PM_NAME", "PM")
```

在 `handler.py` 中引用：`import config` → `config.PIPELINE_PM_NAME`（已有 `from . import config as config` 或其他导入方式，注意与现有导入一致）。

---

## 3. 方向 B（P1）：初始点名 ACK 超时软检查

### B1: `_cmd_pipeline_start` 中的点名处理

**当前位置：** `handler.py` L1288-L1308

当前 `_cmd_pipeline_start` 中 `_broadcast_active_channel(ws_id)` (L1290) 返回 ACK 结果 `{online_count, acked_members, timedout_members}`。但返回值**未使用**——不会阻断管线。

```python
await _broadcast_active_channel(ws_id)          # L1290 — 返回值未使用
```

**结论：管线不会因 ACK 超时而阻断。✅ 当前行为已符合要求。** 方向 B 不需要改 `_cmd_pipeline_start`。

但需要确认 `_cmd_rollcall_next` 中是否有阻断逻辑。

### B2: `_cmd_rollcall_next` 的 ACK 超时不阻断

**当前位置：** `handler.py` L810-L813

```python
_persist_broadcast(sender_ch, "系统", f"🏗️ 下一环节：{context_summary}\n📋 负责人：{names_str}")
ack_result = await _broadcast_active_channel(sender_ch)
return f"✅ 已点名 {names_str}（{ack_result['online_count']} 人在线），等待 ACK 确认..."
```

`_broadcast_active_channel` 内部有 30 秒 ACK 等待（`_channel_ack_timeout`），但此函数**不等待 ACK 结果才返回**——它开异步 task 等 ACK，返回 `{online_count, acked_members: set(), timedout_members: set()}`。

`_cmd_rollcall_next` 在收到结果后直接返回消息，**不检查是否全 ACK**。✅ 当前行为已符合要求。

**方向 B 实际不需要代码改动。** 但建议添加**日志记录**让运维可以追踪点名 ACK 状态：

```python
# B2: 记录点名 ACK 状态（不阻断）
if ack_result.get("timedout_members"):
    logger.info(
        "点名 %s 超时: %s (在线 %d, ACK %d, 超时 %d)",
        target_role,
        ",".join(ack_result.get("timedout_members", set())),
        ack_result.get("online_count", 0),
        len(ack_result.get("acked_members", set())),
        len(ack_result.get("timedout_members", set())),
    )
```

> **方向 B 总计改动：~2 行日志代码。** 核心需求（不阻断）已满足。

---

## 4. 方向 C（P2）：通知状态跟踪 + `!pipeline_status` 增强

### C1: pstate 通知状态字段

在 `_PIPELINE_STATE[round_name]` 中新增字段：

```python
_PIPELINE_STATE[round_name] = {
    ...  # 现有字段
    "step_notifications": {    # ← 新增
        "step_name": {
            "status": "notified" | "acknowledged" | "no_response",
            "notified_at": timestamp,
            "target_agents": [agent_id1, ...],
        }
    }
}
```

### C2: `_cmd_step_complete` 中记录通知状态

**位置：** 在 A2 的主力广播之后、`_update_pipeline_step` (L1549) 之前，追加记录。

```python
# ── R58 C2: 记录通知状态到 pstate ──
step_notifications = pstate.setdefault("step_notifications", {})
step_notifications[next_step] = {
    "status": "notified",
    "notified_at": time.time(),
    "target_agents": target_agents,
}
```

后续 ACK 确认逻辑（R53 已有的 `_channel_ack_state`）可在收到 ACK 时更新 `status` 为 `"acknowledged"`。但初始实现只记录 `"notified"` 状态即可——ACK 跟踪是 R53 协议层的能力，非 R58 核心。

### C3: `_cmd_pipeline_status` 展示通知状态

**位置：** `handler.py` L1950-L1977（Step 展示循环）

在当前 Step 展示循环中，在每个 Step 行后增加通知状态信息：

```python
for step_key, step_info in sorted(step_config.items(), ...):
    role = step_info["role"]
    # ... 现有 task_state 判断 ...

    current = " ◀ 当前" if step_key == pstate.get("current_step") else ""
    
    # ── R58 C3: 通知状态显示 ──
    step_notifications = pstate.get("step_notifications", {})
    notify_info = step_notifications.get(step_key, {})
    notify_status = notify_info.get("status", "")
    notify_mark = ""
    if notify_status == "notified":
        notify_mark = " 📨"
    elif notify_status == "acknowledged":
        notify_mark = " ✅ACK"
    elif notify_status == "no_response":
        notify_mark = " ❌静默"
    
    lines.append(f"  {task_state} {step_key} — {role}{notify_mark}{current}")
```

**效果示例：**
```
📊 R58 管线状态
  模式: 🚀 auto
  ✅ step1 — admin 📨 ◀ 当前
  🟢 step2 — arch
```

---

## 5. 备用方案：arch/dev 不响应的兜底

### 问题陈述

项目负责人反馈：arch 和 dev 几乎每轮都需要额外的 TG 触发，可能与它们自身的 Hermes 网关配置有关。`from_name` 改造（方向 A）解决了「系统消息被静默」的通用问题，但 arch/dev 可能有更深层的原因。

### 三级兜底方案

| 级别 | 方案 | 触发条件 | 实现复杂度 |
|:----:|:-----|:---------|:----------:|
| 1️⃣ | 保留手动 @mention 能力 | 方向 A 生效后仍不响应 | 0 行（现有能力） |
| 2️⃣ | 通知消息增加特殊标记 | 方向 A + 手动仍不响应 | ~2 行 |
| 3️⃣ | WS 直接命令触发 | 方向 A + 特殊标记仍失败 | ~5 行 |

### 方案 1️⃣：PM 手动 @mention 兜底（✅ 已有能力）

如果方向 A 改造后 arch/dev 仍不响应，PM 只需在工作室内写自然 @mention，与 R56/R57 过渡期相同。**无代码改动。**

### 方案 2️⃣：通知消息增加特殊标记

在 @mention 消息内容开头增加 `🚨` 或 `🔴` 等醒目标记，帮助 bot 网关的路由/过滤逻辑识别为"必须回复"的消息：

```python
# 在 A2 mention_msg 构造中
mention_msg = (
    f"{next_role_mention} 🚨 **R58 {next_step} 到你了！**\n\n"
    ...
)
```

**无需条件判断——对所有 bot 一视同仁。** 在 `_cmd_step_complete` 中已经是 `🚨` 前缀。

### 方案 3️⃣：WS 直接命令触发

如果 arch/dev 的消息级解析仍然失败，可在广播 PM 通知后**追加一条 MSG 协议消息**，直接触发 bot 的 `!step_complete` 监听点：

```python
# 在 PM 广播之后，追加一条 type: "message" 协议消息
# 模拟 bot 在工作室发送的文本消息——bot 网关会按聊天消息处理
direct_cmd_payload = json.dumps({
    "type": "message",
    "channel": sender_ch,
    "from_agent": "system",
    "from_name": pm_name,
    "content": f"@{next_role_display} R58 {next_step} 到了，请开始工作。",
    "ts": time.time(),
})
# 仅发给 target_agents
for agent_id in target_agents:
    for conn in list(_connections.get(agent_id, set())):
        try:
            if hasattr(conn, "send_str"):
                await conn.send_str(direct_cmd_payload)
            elif hasattr(conn, "send"):
                await conn.send(direct_cmd_payload)
        except Exception:
            pass
```

> **方案 3 当前不实现**——属于 edge case 兜底。先观察方向 A 的实际效果，如果 arch/dev 在方向 A 后仍不响应才启用。

---

## 6. 改动汇总

### 6.1 文件清单

| 文件 | 改动类型 | 说明 |
|:----|:--------|:------|
| `server/config.py` | ✅ 新增常量 | 增加 `PIPELINE_PM_NAME`（环境变量 `WS_PM_NAME` 可覆盖） |
| `server/handler.py` | ✅ 修改 | 方向 A/B/C 的代码改动 |

### 6.2 行级改动明细

| # | 函数 | 行号范围 | 改动 | 方向 |
|:-:|:-----|:--------:|:----|:---:|
| 1 | `_cmd_step_complete` | ~L1520-1539 | 新增 PM 身份 @mention 广播路径（主力） | A2 |
| 2 | `_cmd_step_complete` | ~L1520-1539 | 保留原 `_send_to_agent` 调用（回退） | A5 |
| 3 | `_cmd_step_complete` | ~L1549 前 | 通知状态记录到 pstate | C2 |
| 4 | `_cmd_pipeline_start` | ~L1290-1292 | 新增 PM 身份全员 @mention 广播 | A3 |
| 5 | `_cmd_pipeline_status` | ~L1950-1977 | 通知状态显示 | C3 |
| 6 | `_cmd_rollcall_next` | ~L810-813 | 可选：添加 ACK 超时日志 | B2 |
| 7 | `config.py` | ~L62-78 | 新增 PIPELINE_PM_NAME | A6 |

### 6.3 不改动清单（需确认）

| 项 | 原因 |
|:---|:------|
| `_send_to_agent` 函数 | 保留为回退双保险（R56 模式） |
| `_broadcast_active_channel` | MSG_SET_ACTIVE_CHANNEL 协议层不动 |
| `_persist_broadcast` 签名 | 已支持自定义 `from_name` |
| bot 客户端代码 | 不改 bot 端——改服务端发出的消息 |
| `_r57_*` 函数 | R57 逻辑（在线预检/主备换人/角色名显示）不动 |
| F-16 Agent Card 重构 | 架构层改，不纳入本轮 |

---

## 7. 验证清单

### 7.1 测试场景

| # | 场景 | 预期行为 | 对应验收 |
|:-:|:-----|:---------|:--------:|
| T1 | `!step_complete` 正常交接 | 工作室出现 PM 身份 @mention 通知 | A-1 |
| T2 | 通知内容检查 | 含 @bot名 + 需求 URL + WORK_PLAN URL + 上一步产出 | A-2 |
| T3 | 目标 bot 响应 | bot 回复 ACK + 开始工作 | A-3 |
| T4 | `_send_to_agent` 保留 | 服务器日志显示定向通知同时发送 | A-4 |
| T5 | `!pipeline_start` 初始点名 | 工作室出现 PM 身份全员 @mention | A-5 |
| T6 | `from_name` 可配置 | 修改环境变量 `WS_PM_NAME` 后重启，通知名称变化 | A-6 |
| T7 | 初始点名 ACK 超时 | 超时不阻断管线，仅记录日志 | B-1 |
| T8 | `!pipeline_status` 状态跟踪 | 显示 📨 已通知 / ✅ACK / ❌静默 状态 | C-1 |

### 7.2 回归检查

| # | 检查项 | 方法 |
|:-:|:-------|:-----|
| R-1 | R57 在线预检（A-2）不受影响 | 检查 `_cmd_rollcall_next` 调用点 |
| R-2 | R57 主备换人（A-1~A-9）不受影响 | 检查 `_find_agents_by_role` 逻辑 |
| R-3 | R57 角色名显示（C-1~C-4）不受影响 | 检查 `next_role_display` 变量 |
| R-4 | R56 双保险 `_send_to_agent` 未删除 | grep `_send_to_agent` 确认调用点 |
| R-5 | `_persist_broadcast` 保留系统身份调用 | 非 R58 新增的通知仍用"系统" |

---

> **版本历史：**
> - v1.0 — 初稿，基于 R58 需求文档 v0.1 + WORK_PLAN v1.0
>   - 方向 A：PM 身份 @mention 广播 + 初始化点名 + 配置化 PM 名称
>   - 方向 B：ACK 超时不阻断（已满足）——仅加日志
>   - 方向 C：pstate 通知状态记录 + `!pipeline_status` 展示
>   - 备用方案：三级兜底（手动 → 特殊标记 → WS 直接命令）
