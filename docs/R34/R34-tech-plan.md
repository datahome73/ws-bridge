# R34 技术方案 — 工作室重置 + 消息状态透传

> **版本：** v1.0
> **架构师：** 架构师 🏗️
> **日期：** 2026-06-23
> **状态：** ⏳ 待全员评审
> **依赖：** [R34 需求文档](../R34-requirements.md) v0.1

---

## 1. 架构概览

### 1.1 改动范围

| 文件 | 改动类型 | 说明 |
|:-----|:--------|:-----|
| `server/handler.py` | 修改 | 需求 A：重写 `workspace_reset` 处理逻辑；需求 B：增强 ACK delivery 字段 |
| `server/__main__.py` | 修改 | 双入口同步 — `ws_handler()` 中同步需求 A/B 改动 |
| `shared/protocol.py` | 无需改动 | `MSG_WORKSPACE_RESET` 已在 R29 定义 |

### 1.2 关键数据流

```
需求 A — workspace_reset（工作室范围）:
  Admin → ws-bridge: {type: "workspace_reset", workspace_id: "R34-dev"}
  ws-bridge:
    1. Admin 权限检查
    2. 工作区状态检查 (CLOSING/ARCHIVED → reject)
    3. 构建 force broadcast → 在线成员直接推送
    4. 离线成员 → _offline_push_queue
    5. 所有成员 active_channel → workspace_id
    6. write_chat_log 记录
    7. 返回 ACK + delivery 统计

需求 B — ACK delivery 增强:
  发送者 → ws-bridge → 广播 → ACK 返回:
    {type: "ack", id: msg_id, delivery: {total, sent, offline, targets, offline_targets}}
```

---

## 2. 需求 A — 工作室重置机制（`workspace_reset` 扩展）

### 2.1 现状分析

R29 实现的 `workspace_reset`（`handler.py:1133-1167`）仅支持两类操作：

| 模式 | 参数 | 行为 |
|:----:|:-----|:-----|
| 全局重置 | `all: true` | 所有 agent channel → lobby |
| 单体重置 | `target: <agent_id>` | 指定 agent channel → lobby |

**缺陷：** 不支持按 `workspace_id` 工作区范围重置，不发送 `force: true` 广播，不检查工作区状态，不记录 chat log。

### 2.2 协议定义（不变）

**触发消息（管理员 → 服务端）：**
```json
{
  "type": "workspace_reset",
  "workspace_id": "R34-dev",
  "ts": 1712345678.0
}
```

**广播消息（服务端 → 工作室所有成员）：**
```json
{
  "type": "broadcast",
  "channel": "R34-dev",
  "subtype": "workspace_reset",
  "force": true,
  "from_name": "项目管理",
  "agent_id": "admin-xxx",
  "content": "⚠️ 工作室已重置，请各成员确认就位 🫡",
  "ts": 1712345678.0
}
```

### 2.3 实现方案

#### 2.3.1 整体流程

```
workspace_reset 消息到达
  │
  ├─ 1. 提取 workspace_id
  │    ├─ 未提供 → 回退到 R29 兼容模式 (all/target)
  │    └─ 已提供 → 进入工作区重置流程
  │
  ├─ 2. Admin 权限检查
  │    └─ 非 admin → error: "权限不足：仅管理员可执行 workspace_reset"
  │
  ├─ 3. 工作区查找
  │    └─ workspace_id 不存在 → error: "工作室 'xxx' 不存在"
  │
  ├─ 4. 状态检查
  │    ├─ CLOSING → error: "工作室 'xxx' 正在关闭中，无法重置"
  │    └─ ARCHIVED → error: "工作室 'xxx' 已归档，无法重置"
  │
  ├─ 5. 构建 force broadcast payload
  │    content = "⚠️ 工作室已重置，请各成员确认就位 🫡"
  │
  ├─ 6. 向所有成员推送
  │    ├─ 在线成员：直接通过 WebSocket 发送 broadcast
  │    └─ 离线成员：写入 _offline_push_queue（上线后自动补发）
  │
  ├─ 7. 更新 active_channel
  │    所有成员（含管理员自身）→ set_agent_channel(agent_id, workspace_id)
  │
  ├─ 8. 记录 chat log
  │    write_chat_log(from_name, content, channel=workspace_id)
  │
  └─ 9. 返回 ACK（含 delivery 统计）
       {type: "ack", id: <auto-gen>, delivery: {total, sent, offline, targets, offline_targets}}
```

#### 2.3.2 handler.py 改动（`handler()` 路径）

**位置：** 替换现有 `handler.py:1133-1167`（`elif msg_type == p.MSG_WORKSPACE_RESET` 分支）

**伪代码：**

```python
elif msg_type == p.MSG_WORKSPACE_RESET and agent_id:
    _users = auth.get_users()
    if _users.get(agent_id, {}).get("role") != "admin":
        await _send(ws, {"type": "error", "error": "权限不足：仅管理员可执行 workspace_reset"})
        continue

    workspace_id = msg.get("workspace_id", "").strip()
    all_flag = msg.get("all", False)
    target_id = msg.get("target", "").strip()

    # ── R34: 工作区范围重置 ──
    if workspace_id:
        ws_info = ws_mod.get_workspace(workspace_id)
        if not ws_info:
            await _send(ws, {"type": "error", "error": f"工作室 '{workspace_id}' 不存在"})
            continue
        if ws_info.state == ws_mod.WorkspaceState.CLOSING:
            await _send(ws, {"type": "error", "error": f"工作室 '{workspace_id}' 正在关闭中，无法重置"})
            continue
        if ws_info.state == ws_mod.WorkspaceState.ARCHIVED:
            await _send(ws, {"type": "error", "error": f"工作室 '{workspace_id}' 已归档，无法重置"})
            continue

        sender_name = _users.get(agent_id, {}).get("name", agent_id[:12])
        member_ids = ws_info.members
        online = set(_connections.keys())

        # 构建 force broadcast
        reset_content = f"⚠️ 工作室 {workspace_id} 已重置，请各成员确认就位 🫡"
        broadcast_payload = {
            "type": "broadcast",
            "channel": workspace_id,
            "subtype": "workspace_reset",
            "force": True,
            "from_name": sender_name,
            "agent_id": agent_id,
            "from": sender_name,       # legacy
            "from_agent": agent_id,     # legacy
            "content": reset_content,
            "ts": time.time(),
        }
        broadcast_json = json.dumps(broadcast_payload)

        sent = 0
        offline = 0
        target_names = []
        offline_names = []

        for mid in member_ids:
            name = _users.get(mid, {}).get("name", mid[:12])
            if mid in online:
                # 在线 → 直接推送
                for conn in list(_connections.get(mid, set())):
                    try:
                        if hasattr(conn, "send_str"):
                            await conn.send_str(broadcast_json)
                        elif hasattr(conn, "send"):
                            await conn.send(broadcast_json)
                        sent += 1
                    except Exception:
                        pass
                target_names.append(name)
            else:
                # 离线 → 写入离线队列
                offline += 1
                offline_names.append(name)
                _offline_push_queue.setdefault(mid, []).append({
                    "type": "broadcast",
                    "channel": workspace_id,
                    "subtype": "workspace_reset",
                    "force": True,
                    "from_name": sender_name,
                    "agent_id": agent_id,
                    "content": reset_content,
                    "ts": time.time(),
                })

            # 更新 active_channel 到该工作区
            persistence.set_agent_channel(mid, workspace_id)

        persistence.save_agent_channels(config.DATA_DIR)
        write_chat_log(sender_name, reset_content, channel=workspace_id)

        reset_id = str(uuid.uuid4())
        await _send(ws, {
            "type": "ack",
            "id": reset_id,
            "delivery": {
                "total": len(member_ids),
                "sent": sent,
                "offline": offline,
                "targets": target_names,
                "offline_targets": offline_names,
            }
        })
        logger.info("Admin %s reset workspace '%s': %d sent, %d offline",
                     agent_id[:12], workspace_id, sent, offline)

    # ── R29 兼容：all / target 模式（无 workspace_id 时）──
    elif all_flag or target_id:
        # ... (保留现有 R29 逻辑，不修改)
```

#### 2.3.3 __main__.py 改动（`ws_handler()` 路径）

**位置：** 替换现有 `__main__.py:487-521`（`elif msg_type == p.MSG_WORKSPACE_RESET` 分支）

**要求：** 与 handler.py 逻辑完全一致，差异仅在于：
- 使用 `await ws.send_json(data)` 代替 `await _send(ws, data)`
- `_connections` 直接可用（已在文件头 import）
- 需要 `import uuid`、`import json`
- `write_chat_log` 需要在文件头 import

### 2.4 向后兼容

| 场景 | R29 行为 | R34 行为 |
|:-----|:--------|:--------|
| `workspace_id` 有值 | N/A | → 工作区范围重置（新逻辑） |
| `all: true`（无 `workspace_id`） | 全局重置到 lobby | ✅ 保留不变 |
| `target: <id>`（无 `workspace_id`） | 单体重置到 lobby | ✅ 保留不变 |
| 旧客户端发 `all: true` | 正常 | ✅ 正常（走 R29 兼容分支） |

---

## 3. 需求 B — 消息状态透传（ACK delivery 增强）

### 3.1 现状分析

当前 ACK 格式：
```json
{"type": "ack", "id": "msg-uuid-xxx"}
```

问题：
- 发送者不知道消息投递了几个人
- 不知道谁在线、谁离线
- 管理员才收到独立的 `delivery_status`（非标准 ACK 字段）

当前发送 ACK 的 2 个位置：

| 位置 | 行号 | 场景 |
|:-----|:----:|:-----|
| handler.py | 392 | 工作区消息广播后 |
| handler.py | 566 | 大厅消息广播后 |

两处格式相同：`{"type": "ack", "id": msg_id}`

### 3.2 目标格式

```json
{
  "type": "ack",
  "id": "msg-uuid-xxx",
  "delivery": {
    "total": 5,
    "sent": 3,
    "offline": 2,
    "targets": ["架构师", "开发工程师", "审查工程师"],
    "offline_targets": ["测试工程师"]
  }
}
```

### 3.3 实现方案

#### 3.3.1 位置一：工作区消息广播后（`handler.py:390-392`）

**现状：**
```python
# Send ACK
if msg_id:
    await _send(ws, {"type": "ack", "id": msg_id})
```

**改动为：**
```python
# Send ACK with delivery stats
if msg_id:
    online = set(_connections.keys())
    sent_list = []
    offline_list = []
    for aid in member_ids:
        if aid == sender_id:
            continue
        name = users.get(aid, {}).get("name", aid[:12])
        if aid in online:
            sent_list.append(name)
        else:
            offline_list.append(name)
    ack_payload = {
        "type": "ack",
        "id": msg_id,
        "delivery": {
            "total": len(member_ids) - 1,  # 不含发送者自身
            "sent": len(sent_list),
            "offline": len(offline_list),
            "targets": sent_list,
            "offline_targets": offline_list,
        }
    }
    await _send(ws, ack_payload)
```

**说明：** `member_ids` 来自 `resolved_workspace.members`（已在第 330 行定义）。需要将其作用域提升（或重新获取）。

#### 3.3.2 位置二：大厅消息广播后（`handler.py:564-566`）

**现状：**
```python
# Send ACK to the original sender
if msg_id:
    await _send(ws, {"type": "ack", "id": msg_id})
```

**改动为：**
```python
# Send ACK with delivery stats
if msg_id:
    online = set(_connections.keys())
    sent_list = []
    offline_list = []
    # 大厅目标 = admin_ids（🆘 / 📋）或全体在线（📢）
    for aid in target_agent_ids:  # 需收集目标列表
        name = users.get(aid, {}).get("name", aid[:12])
        if aid in online:
            sent_list.append(name)
        else:
            offline_list.append(name)
    ack_payload = {
        "type": "ack",
        "id": msg_id,
        "delivery": {
            "total": len(target_agent_ids),
            "sent": len(sent_list),
            "offline": len(offline_list),
            "targets": sent_list,
            "offline_targets": offline_list,
        }
    }
    await _send(ws, ack_payload)
```

**说明：** 大厅广播的 `targets` 已在前面路由阶段构建（变量名取决于路由分支）。需要在广播前收集目标 agent_id 列表。

#### 3.3.3 补充：限速/错误路径不变

限速、无前缀、权限不足等错误路径已返回 `{"type": "error", ...}`，无需改动。错误消息不触发 ACK。

#### 3.3.4 向后兼容

- 新增 `delivery` 字段为可选字段
- 旧 Gateway 读取 `type: "ack"` + `id` → 正常处理，忽略 `delivery`
- 新 Gateway 可按需解析 `delivery` 字段
- 不带 `id` 的匿名消息不返回 `delivery`（与需求 3.3.4 一致）

### 3.4 __main__.py 双入口说明

**需求 B 的改动在 `handle_broadcast()` 函数内部**，该函数被 `handler()` 调用。`ws_handler()` 在第 98 行调用 `await handle_broadcast(ws, agent_id, data)`，因此 **需求 B 只需改 handler.py**，`__main__.py` 无需为需求 B 单独改动。

| 需求 | handler.py 改动 | __main__.py 改动 |
|:----:|:--------------:|:--------------:|
| A — workspace_reset | ✅ 重写分支 | ✅ 同步重写 |
| B — ACK delivery | ✅ 修改 ACK 构建 | ❌ 无需改动（复用 handle_broadcast） |

---

## 4. 实施要点

### 4.1 编码顺序

1. **需求 B 优先**（风险低，不改变消息路由，仅增强 ACK 格式）
2. **需求 A 其次**（新增 workspace_id 分支，保留 R29 all/target 兼容）

### 4.2 关键风险点

| # | 风险 | 缓解 |
|:-:|:-----|:-----|
| 1 | `member_ids` 变量作用域 | 在工作区广播路径中将 `member_ids` 提前声明，确保 ACK 构建可访问 |
| 2 | 离线队列消息格式 | 确保 `_offline_push_queue` 中的消息与在线 broadcast 格式一致（含 `force: true`、`subtype`） |
| 3 | 管理员自身 channel 更新 | `workspace_reset` 应更新所有成员（含管理员自身）的 active_channel |
| 4 | 大厅广播 target 列表构建 | 各路由分支（📢/📋/🆘/@mention）需要独立收集 `target_agent_ids`，在 ACK 构建时复用 |
| 5 | 双入口不同步 | `__main__.py` 中 `workspace_reset` 分支必须与 `handler.py` 逻辑完全一致 |

### 4.3 回退方案

- `workspace_id` 缺失时走 R29 兼容逻辑 → 功能无损
- `delivery` 字段为 ACK 可选扩展 → 旧客户端忽略，功能无损
- 若 workspace_reset 新逻辑出问题，可回退到仅保留 R29 all/target 行为

---

## 5. 测试要点

### 5.1 需求 A 测试用例

| # | 用例 | 前置条件 | 操作 | 预期结果 |
|:-:|:-----|:--------|:-----|:--------|
| A-1 | 管理员对活跃工作区发 `workspace_reset` | 工作区 ACTIVE，有 3 在线 + 1 离线成员 | `{"type":"workspace_reset","workspace_id":"R34-dev"}` | 在线成员收到 `force:true` broadcast；离线成员入队；管理员收到 ACK `delivery.sent=3, offline=1` |
| A-2 | 管理员对 CLOSING 工作区发重置 | 工作区 CLOSING | 同上 | 收到 error: "工作室 'xxx' 正在关闭中，无法重置" |
| A-3 | 管理员对 ARCHIVED 工作区发重置 | 工作区 ARCHIVED | 同上 | 收到 error: "工作室 'xxx' 已归档，无法重置" |
| A-4 | 管理员对不存在的工作区发重置 | workspace_id = "nonexistent" | 同上 | 收到 error: "工作室 'xxx' 不存在" |
| A-5 | 非管理员发 workspace_reset | sender role = member | 同上 | 收到 error: "权限不足：仅管理员可执行 workspace_reset" |
| A-6 | 重置后成员 active_channel 更新 | 重置前成员在 lobby | 管理员重置 R34-dev | 所有成员 active_channel → R34-dev |
| A-7 | R29 兼容：`all: true`（无 workspace_id） | — | `{"type":"workspace_reset","all":true}` | 所有 agent channel → lobby（行为不变） |
| A-8 | R29 兼容：`target: <id>`（无 workspace_id） | — | `{"type":"workspace_reset","target":"agent-xxx"}` | 指定 agent channel → lobby（行为不变） |

### 5.2 需求 B 测试用例

| # | 用例 | 前置条件 | 操作 | 预期结果 |
|:-:|:-----|:--------|:-----|:--------|
| B-1 | 工作区消息 — 全部在线 | 工作区 3 成员全在线 | 任一成员发消息 | ACK `delivery.total=2, sent=2, offline=0` |
| B-2 | 工作区消息 — 部分离线 | 工作区 3 成员，1 离线 | 任一成员发消息 | ACK `delivery.sent=1, offline=1, targets=[在线名], offline_targets=[离线名]` |
| B-3 | 大厅 📢 公告 | admin 发 📢 | 5 人在线，2 人离线 | ACK `delivery.total=7, sent=5, offline=2` |
| B-4 | 限速后发消息 | 触发大厅限速 | 发消息 | 收到 `type: "rate_limited"` error，不收到 ack |
| B-5 | 无前缀大厅消息 | — | 发纯文本到大厅 | 收到 error: "大厅消息需要明确类型"，不收到 ack |
| B-6 | 匿名消息（无 id） | — | 发消息不含 id 字段 | 不返回 ACK（仅限非匿名消息） |
| B-7 | 向后兼容 — 旧客户端忽略 delivery | — | 正常发消息 | ACK 含 delivery 字段，旧客户端正常解析 type+id |

---

## 6. 验收对照表

对照需求文档 §2.5 和 §3.4 逐项验收：

| PRD 编号 | 验收项 | 对应测试用例 |
|:--------|:------|:----------|
| A-T1 | 管理员对活跃工作室发 `workspace_reset` → 所有成员收到含 `force: true` 的广播 | A-1 |
| A-T2 | 管理员对 CLOSING 工作室发 `workspace_reset` → 返回 error | A-2 |
| A-T3 | 非管理员对工作室发 `workspace_reset` → 权限不足 error | A-5 |
| A-T4 | 卡住工作室重置后，成员重新活跃 | A-1 + A-6 |
| B-T1 | 消息到 3 人在线的工作室 → delivery.sent=3, offline=0 | B-1 |
| B-T2 | 消息到 2 人在线 + 1 人离线 → delivery.sent=2, offline=1 | B-2 |
| B-T3 | 限速时发消息 → 收到 error，不收到 ack | B-4 |
| B-T4 | 无前缀消息发大厅 → 收到 error "大厅消息需要明确类型" | B-5 |

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:-----|
| v1.0 | 2026-06-23 | 初稿 — 双需求技术方案（workspace_reset 扩展 + ACK delivery 增强） |
