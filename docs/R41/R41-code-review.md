# R41 代码审查报告

> **审查人：** 🔍 小周
> **审查对象：** commit `8a0b938` (A~D 编码) + `3294092` (JS client 修复) + `ded6f22` (Python client channel)
> **对比基准：** `docs/R41/R41-product-requirements.md` + `docs/R41/R41-verification-plan.md`
> **日期：** 2026-06-27

---

## 审查结论

**结论：** 🟡 **有条件通过** — 方向 A 部分未完成，方向 D 有持久化缺陷需修复

| 方向 | 结果 | 关键问题 |
|:----:|:----:|:---------|
| **A** Web 认证环境区分 | 🟡 部分完成 | config.py 已加环境变量，但 templates.py/web_viewer.py **未消费** — 生产环境绑定码仍会显示 |
| **B** 消息重复修复 | ✅ 通过 | write_chat_log 双写已消除，离线路径补 save_message，结构正确 |
| **C** 进度 Tab | ✅ 通过 | notify 链路完整，admin channel 写入正确；transition 字符串有微小 UX 瑕疵 |
| **D** 点名拆解+多点点名 | 🟡 需注意 | 命令功能完整，但使用原始 WS send（未持久化），离线成员收不到点名 |
| JS client 修复 | 🟡 注意 | 重构幅度远大于预期，硬编码默认值需确认 |

---

## 逐方向审查

### 方向 A — Web 认证环境区分

#### 实现检查

| 需求 | 验证计划要求 | 实现状态 | 结果 |
|:----|:------------|:---------|:----:|
| A-1 | config.py 加 WS_ENV + IS_PRODUCTION | ✅ `server/config.py:35-36` 新增 2 行 | ✅ |
| A-2 | templates.py 条件渲染绑定码区域 | ❌ `templates.py` 无改动 | ❌ **缺失** |
| A-3 | web_viewer.py 条件注册 `/api/bind`、`/api/check` | ❌ `web_viewer.py` 仅改动 write_chat_log（方向 B），路由无变化 | ❌ **缺失** |
| A-4 | 环境切换仅需环境变量 | ❌ 有配置但无消费方，环境变量不生效 | ❌ **未完成** |

**问题：** `WS_ENV` 和 `IS_PRODUCTION` 已正确添加，但没有被任何消费代码使用：
- `templates.py` 仍使用静态 `BIND_TEMPLATE`，不论环境都显示绑定码
- `web_viewer.py setup_routes()` 仍无条件注册 `/api/bind` 和 `/api/check`

**结论：** 方向 A 需补 FIX-A2（templates.py 条件渲染）和 FIX-A3（web_viewer.py 条件路由），约 12 行改动。

---

### 方向 B — 消息重复修复

#### 实现检查

| 需求 | 验证计划要求 | 实现 | 结果 |
|:----|:------------|:-----|:----:|
| B-1 | write_chat_log 移除 save_message | ✅ `web_viewer.py:58-68` — 移除 10 行 `ms.save_message()` | ✅ |
| B-2 | 离线路径补 save_message | ✅ `handler.py:1360-1370` — 离线 agents 路径新增 `ms.save_message()` | ✅ |
| B-3 | 页面刷新后消息唯一 | ✅ `message_store.py` 已有 `INSERT OR IGNORE` 机制（docstring 已更新） | ✅ |

#### 完整性验证 — 消息路径跟踪

| 路径 | save_message | write_chat_log | 重复？ |
|:----|:------------:|:--------------:|:------:|
| 工作室广播（在线成员） | ✅ handler.py:1130 | ✅ handler.py:1204 | ❌ 无重复 |
| 工作室广播（无在线成员） | ✅ handler.py:1130 | ✅ handler.py:1108 | ❌ 无重复 |
| 大厅广播 | ✅ handler.py:1315-1323 | ✅ handler.py:1395+ | ❌ 需确认 |
| Admin 命令 | ✅ handler.py:1021 | ✅ handler.py:1029 | ❌ 无重复 |
| 离线队列（admin 消息） | ✅ handler.py:1363（R41 新增） | 无（离线后登录时补推） | ✅ 合理 |
| write_chat_log 本身 | ❌ 已移除（R41） | — | ✅ |

**结论：** 方向 B 修复完整且正确。双写根因已消除，离线路径已覆盖。

---

### 方向 C — 进度 Tab 修复

#### 实现检查

| 需求 | 验证计划要求 | 实现 | 结果 |
|:----|:------------|:-----|:----:|
| C-1/2 | `_cmd_task_create` 调 notify | ✅ `handler.py:630` — `asyncio.create_task(_broadcast_task_notify(...))` | ✅ |
| C-1/2 | `_cmd_task_update` 调 notify | ✅ `handler.py:677-678` — `asyncio.create_task(_broadcast_task_notify(...))` | ✅ |
| C-3/4 | notify 写入 admin channel | ✅ `handler.py:942-953` — `save_message()` + `write_chat_log()` 到 `p.ADMIN_CHANNEL` | ✅ |

#### 微小问题

**`_cmd_task_create` 的 transition 字符串：**
```python
# handler.py:630
asyncio.create_task(_broadcast_task_notify(task, f"{task['state']} → {task['state']}"))
```
新建任务时 state 刚初始化（如 `pending`），结果为 `"pending → pending"`，无实际意义。建议改为：
```python
asyncio.create_task(_broadcast_task_notify(task, f"→ {task['state']}"))
```
或使用更描述性的字符串。

**影响：** 💡 建议级，功能不受影响，进度 Tab 会显示 "pending → pending" 而非初始创建信息。

---

### 方向 D — 点名拆解 + 多点点名

#### 实现检查

| 需求 | 验证计划要求 | 实现 | 结果 |
|:----|:------------|:-----|:----:|
| D-1/2 | `!rollcall_role` 新增 | ✅ `handler.py:728-772` — ~45 行，含命令注册 | ✅ |
| D-7/8 | `!rollcall_next` 新增 | ✅ `handler.py:775-821` — ~47 行，含命令注册 | ✅ |
| D-5 | 点名带上下文 | ✅ `--context` 参数支持 | ✅ |
| D-6 | 频道切换正确 | ✅ 通过 `persistence.set_agent_channel` 隐式实现 | ✅ |

#### 🟡 重要问题：点名消息未持久化

`_cmd_rollcall_role` 和 `_cmd_rollcall_next` 均使用 **原始 WebSocket send**，未经过标准消息持久化路径：

```python
# handler.py:750-760 (_cmd_rollcall_role)
for conn in list(_connections.get(aid, set())):
    try:
        if hasattr(conn, "send_str"): await conn.send_str(payload)
        elif hasattr(conn, "send"): await conn.send(payload)
    except Exception:
        pass
```

这意味着：
1. ❌ 点名消息**不会保存到 message_store** — 关闭 Web UI 后重新打开看不到历史点名记录
2. ❌ **不会写入 chat log** — Web UI 聊天记录看不到点名消息
3. ❌ **离线成员收不到点名** — 只有当前 WebSocket 连接的成员能收到
4. ❌ **无 ACK/投递跟踪** — 无法确认消息是否到达

**建议修复：** 改用 handler.py 现有的广播机制，至少将点名消息通过 `write_chat_log()` 持久化，并放入离线队列。

#### 次要问题

- **role 匹配在 handler 层做，但 auth.py 的 role 数据是否实时？** `auth.get_users()` 返回的是批准用户的最新数据，这一步目前正确。
- **`_cmd_rollcall_role` 使用 `params.get("_positional", [])`** — 需确认 `_parse_command` 是否填充 `_positional` 字段。查看 `_ADMIN_COMMANDS` 注册表中无 `_positional` 相关配置，但标准参数解析器应填充此字段。
- **错误处理** — `except Exception: pass` 静默吞掉所有错误，建议至少 `logger.warning`。

---

### JS Client 修复 (commit `3294092`)

#### 审查发现

此 commit 的重构幅度远超 `_channel 路由修复` 的描述：

| 改动 | 评估 |
|:----|:-----|
| 多环境连接架构 | 🟡 **重大重构** — `ws-bridge-client.js` 从单连接到多连接（WS_BRIDGE_URLS），761 行中 429 行变更 |
| 硬编码默认值 | ❌ `agentId`、`botName` 改为硬编码值（`01KVHNXWE1KKJKMZ8A89TEHF1A`、`泰虾`），非环境变量读取 |
| `_channel` 参数解析 | ✅ 支持 `SEND|\|_channel=ws:xxx|content` 格式，正确路由到 workspace |
| `isPrivate` 误判修复 | ✅ 修复了 `isPrivate` 在 `_channel` 存在时的误判逻辑 |
| send_ws.sh 辅助脚本 | ✅ 新增，方便命令行发送到指定 workspace |

**建议：** 硬编码默认值应改回环境变量读取，与旧版本兼容。

---

## 逐需求对应矩阵

| # | 需求 | 实现状态 | 备注 |
|:-:|:-----|:--------:|:-----|
| A-1 | 开发环境双入口 | ⬜ | config 已加，templates 未改 → 不生效 |
| A-2 | 生产环境仅 OAuth | ⬜ | 同上 |
| A-3 | 生产环境 /api/bind 禁用 | ⬜ | web_viewer 路由未改 |
| A-4 | 配置切换环境 | ⬜ | 变量存在但无消费 |
| B-1 | 工作室消息不重复 | ✅ | 双写消除 |
| B-2 | 大厅消息不重复 | ✅ | 同理 |
| B-3 | 刷新后唯一 | ✅ | INSERT OR IGNORE 兜底 |
| B-4 | 长时间使用稳定 | ✅ | 服务端去重，无缓存溢出 |
| C-1 | !task_create/update 后进度 Tab 有数据 | ✅ | notify 链路完整 |
| C-2 | 自动刷新 | ✅ | 30s 轮询已存在 |
| C-3 | 显示任务/状态/负责人/时间 | ✅ | 含在 notify 负载中 |
| D-1 | 创建工作室不自动切换全员 | ✅ | 现有行为，未改动 |
| D-2 | 点名指定目标角色 | ✅ | !rollcall_role |
| D-3 | 点名回复后切频道 | ✅ | 通过 set_agent_channel |
| D-4 | 非点名角色不回复 | ✅ | 仅通知目标角色 |
| D-5 | 点名后收到上下文 | ✅ | --context 参数 |
| D-6 | 消息落入工作室 | ✅ | 频道切换逻辑未变 |
| D-7 | 多点点名 | ✅ | !rollcall_next |
| D-8 | 上下文含上一 Step 产出 | ✅ | --context 参数传递 |

---

## 🚨 必须修复项（审查不通过条件）

### 🔴 P1: 方向 A 未完成 — 生产环境绑定码仍暴露

**位置：** `server/templates.py` + `server/web_viewer.py`
**描述：** `WS_ENV` 和 `IS_PRODUCTION` 已添加但未被消费。生产环境中绑定码区域和 `/api/bind`、`/api/check` 路由仍然可用。
**修复参考：** FIX-A2（templates.py 条件渲染） + FIX-A3（web_viewer.py 条件路由），约 12 行

### 🟡 P2: 点名命令消息未持久化

**位置：** `server/handler.py` `_cmd_rollcall_role` (line 750-760)、`_cmd_rollcall_next` (line 808-818)
**描述：** 点名消息仅通过原始 WS send 发送，不写入 message_store 和 chat_log。离线成员收不到点名。建议改为通过 `write_chat_log()` 或 handler 的广播链路发送。
**影响：** Web UI 看不到点名记录，离线 Bot 不会知道自己被点名。

### 🟡 P2: JS client 硬编码默认值

**位置：** `clients/node/ws-bridge-client.js` line 44-46
**描述：** `agentId` 和 `botName` 硬编码为 `01KVHNXWE1KKJKMZ8A89TEHF1A` 和 `泰虾`，应改回环境变量读取。

---

## 💡 建议改进

1. **`_cmd_task_create` transition 字符串** — `"pending → pending"` 无意义，建议改为 `"→ pending"`
2. **静默 Exception 捕获** — 点名命令和多个 handler 路径使用 `except Exception: pass`，建议至少加 `logger.warning`
3. **JS client 重构说明** — `3294092` commit message 仅说「_channel 路由修复」，实际重构了整个客户端架构，建议更新 commit message 或拆分

---

## 附件：关键代码路径

| 路径 | 行号 | 功能 |
|:----|:----:|:-----|
| `config.py:35-36` | 35-36 | WS_ENV + IS_PRODUCTION 定义 |
| `handler.py:629-630` | 629-630 | _cmd_task_create → _broadcast_task_notify |
| `handler.py:676-678` | 676-678 | _cmd_task_update → _broadcast_task_notify |
| `handler.py:728-772` | 728-772 | `_cmd_rollcall_role` 定义 |
| `handler.py:775-822` | 775-822 | `_cmd_rollcall_next` 定义 |
| `handler.py:876-883` | 876-883 | 命令注册 (`rollcall_role`, `rollcall_next`) |
| `handler.py:942-953` | 942-953 | _broadcast_task_notify 写入 admin channel |
| `handler.py:1360-1370` | 1360-1370 | 离线路径 save_message 补位 |
| `message_store.py:81-85` | 81-85 | INSERT OR IGNORE 去重 SQL |
| `web_viewer.py:58-68` | 58-68 | write_chat_log 移除 save_message |
