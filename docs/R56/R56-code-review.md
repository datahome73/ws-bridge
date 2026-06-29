# R56 代码审查报告 — Step 4 方向 A

> **审查人：** 🔍 小周
> **审查对象：** commit `39ef407`（`_send_to_agent` 回退广播）
> **技术方案：** `docs/R56/R56-tech-plan.md`（commit `1688bb2`）
> **审查日期：** 2026-06-29

---

## 1. 审查结论

**✅ 通过 — 无阻塞问题**

方向 A 实现完整覆盖技术方案 4 项验收条件（A-1~A-4），逻辑正确，改动紧凑。

---

## 2. 改动全景

```
server/handler.py | 35 ++++++++++++++++++++++++++++-------
1 file changed, 28 insertions(+), 7 deletions(-)
```

| 改动点 | 行号（新） | 类型 | 说明 |
|:-------|:---------:|:----|:-----|
| `_send_to_agent` 签名 | +ws_id="" | 参数新增 | 默认留空保持向后兼容 |
| 离线回退 → 工作室广播 | ~25 行 | 逻辑重写 | ws_id 有值时走全广播，空值走旧 lobby write_chat_log |
| `_cmd_step_complete` 调用 | ws_id=sender_ch | 传参变更 | 定向通知传工作室 ID |
| `_cmd_step_reject` 调用 | ws_id=sender_ch | 传参变更 | 退回通知传工作室 ID |
| 注释清理 | 1 行删除 | 仅 cosmetic | `# W-4: ...` 注释移除 |

---

## 3. Spec-to-Code 对照

| # | 技术方案要求 | 实现 | Verdict |
|:-:|:------------|:-----|:-------:|
| 1 | `_send_to_agent` 加可选 `ws_id` 参数 | ✅ `ws_id: str = ""` | ✅ |
| 2 | 离线时 `ws_obj = ws_mod.get_workspace(ws_id)` | ✅ 实现一致 | ✅ |
| 3 | 遍历 `ws_obj.members` 广播 | ✅ `for member_id in ws_obj.members` | ✅ |
| 4 | 广播后 `write_chat_log` 写工作室频道 | ✅ `write_chat_log(..., channel=ws_id)` | ✅ |
| 5 | `_cmd_step_complete` 传 `ws_id` | ✅ `ws_id=sender_ch` | ✅ |
| 6 | `_cmd_step_reject` 传 `ws_id` | ✅ `ws_id=sender_ch` | ✅ * |
| 7 | 无 admin 日志重复 | ✅ `channel=ws_id`，非 `ADMIN_CHANNEL` | ✅ |
| 8 | 在线 bot 仍走定向 | ✅ 原 `conns` 非空路径完全未改 | ✅ |

> *`_cmd_step_reject` 采用 `ws_id=sender_ch`（发送者活跃频道）而非技术方案示例中的 `persistence.get_agent_channel(agent_id)`。**这是更优选择**——退回操作绑定命令发出的工作室上下文，而非目标 agent 可能过期的历史频道。ws_obj 已通过 `ws_mod.get_workspace(sender_ch)` 验证有效性（L1652）。不构成缺陷。

---

## 4. 四项重点审查

### 📌 重点①：离线回退时 `_broadcast` 的 ws_id 是否正确

**✅ 正确**

两条调用路径：

**`_cmd_step_complete`→`_send_to_agent`**：
- `sender_ch = persistence.get_agent_channel(sender_id)`（L1394）→ L1434 `ws_id = sender_ch` → L1538 传入
- `ws_mod.get_workspace(ws_id)` 在 L1395 已验证有效性
- 回退广播写 `channel=ws_id`（工作室频道）

**`_cmd_step_reject`→`_send_to_agent`**：
- `sender_ch = persistence.get_agent_channel(sender_id)`（L1651）→ L1755 传入
- `ws_mod.get_workspace(sender_ch)` 在 L1652 已验证有效性
- 回退广播写 `channel=ws_id`（工作室频道）

**边界情况：** 如果 `ws_id` 为空（遗留调用者未传参），则走旧路径 `write_chat_log("系统", f"[定向通知 @{agent_id[:12]}] {text}")`，保持 R55 行为。✅

---

### 📌 重点②：write_chat_log 写入的是否是工作室频道

**✅ 正确**

回退路径中的 `write_chat_log` 调用：
```python
write_chat_log("系统", f"[回退广播 @{ws_id}] {text}", channel=ws_id)
```

- `write_chat_log` 定义于 `server/web_viewer.py:35`：`def write_chat_log(sender_name, content, channel="lobby")`
- 写入文件：`chat_{today}_{safe_channel}.log`，其中 `safe_channel = channel.replace(":", "_")`
- 工作室 ID 如 `ws:R56-dev` → 文件名 `chat_2026-06-29_ws_R56-dev.log` ✅
- 同时写入 in-memory buffer，以 `channel` 为 key 索引 ✅
- 推送到 Web UI 的 WS 客户端时携带 `"channel": channel` ✅

---

### 📌 重点③：在线 bot 仍走定向（不影响）

**✅ 正确**

`conns = _connections.get(agent_id, set())` → 非空时执行的原路径完全未修改：

```python
payload = {
    "type": p.MSG_BROADCAST,
    "from_agent": "系统",
    "from_name": "系统",
    "content": text,
    "ts": time.time(),
}
for ws in conns:
    await _send(ws, payload)
```

- 仅遍历 `agent_id` 本人的连接（`conns`）— 非全广播 ✅
- `p.MSG_BROADCAST` 类型与原 R55 一致 ✅
- `_send_to_agent` 返回 `True`/`False` 不影响 caller 行为（忽略返回值）— 与 R55 一致 ✅

---

### 📌 重点④：admin 日志无重复

**✅ 正确**

回退路径中的日志操作链：

| 层 | 写入内容 | 目标频道 | 工具 |
|:---|:---------|:--------:|:----:|
| `_cmd_step_complete` | `📋 R56 进度：Step N ✅ → ...` | `p.ADMIN_CHANNEL` | `ms.save_message()` |
| `_send_to_agent` 回退 | `[回退广播 @ws_id] ...` | **`channel=ws_id`**（工作室） | `write_chat_log()` |
| `_cmd_step_reject` | `📋 R56 退回：Step N ❌ ...` | `p.ADMIN_CHANNEL` | `ms.save_message()` |

- ✅ admin 日志始终由上层 `_cmd_step_complete` / `_cmd_step_reject` 管理（`ms.save_message(channel=p.ADMIN_CHANNEL)`）
- ✅ 回退路径仅写 `channel=ws_id`，绝不触达 `p.ADMIN_CHANNEL`
- ✅ 技术方案 D3 明确：「admin日志已经在 _cmd_step_complete / _cmd_step_reject 的上层逻辑中写入。回退广播只写工作室频道 chat_log」

---

## 5. 差异分析（实现 vs 技术方案）

| # | 技术方案 | 实现 | 分析 | 严重性 |
|:-:|:---------|:-----|:----|:------:|
| D1 | `_cmd_step_reject` 用 `persistence.get_agent_channel(agent_id)` | 用 `ws_id=sender_ch` | **更优**。`sender_ch` 是命令发出的工作区通道，已验证存在。`get_agent_channel(agent_id)` 可能返回过期值 | ⚪ 无 |
| D2 | 回退广播用 `_send(conn, {"type": p.MSG_BROADCAST, ...})` | 用 `conn.send_str(json.dumps({...}))` | payload 内容等价（`"broadcast"` 与 `p.MSG_BROADCAST` 同值）。省略 `send_json` 检查，但与现有 `_broadcast_stage_completed` 模式一致 | ⚪ 无 |
| D3 | 回退广播消息用 `broadcast_text = f"📢 [回退通知 @{agent_id[:12]}] {text}"` | 广播 payload 直接用原 `text`，prefix 仅用在 `write_chat_log` | **更好**。保留原通知内容在 WS 消息中不污染，log 中加 prefix 便于追溯 | ⚪ 无 |
| D4 | 技术方案示例含 `_broadcast_to_members` 辅助函数 | 直接内联在 `_send_to_agent` 中 | 改动集中在一处，无需额外函数。~5 行 → ~28 行，但全部集中在离线分支 | ⚪ 无 |

---

## 6. 代码质量检查

### 正确性
- ✅ `ws_mod.get_workspace(ws_id)` 返回 `None` 时优雅跳过（不崩溃、fallback 不生效）
- ✅ `_connections.get(member_id, set())` 安全处理空集合
- ✅ `hasattr(conn, "send_str")` / `hasattr(conn, "send")` 双重兼容
- ✅ `list(_connections.get(member_id, set()))` 防止迭代中修改集合

### 安全性
- ✅ 无硬编码密钥或凭证
- ✅ 广播内容不包含敏感信息

### 消息合规
- ✅ 在线定向通知消息格式与 R55 一致
- ✅ 离线回退写 `[回退广播 @ws_id]` prefix + 原内容，结构清晰
- ✅ 无多余 emoji，无不规范 prefix/suffix

### 向后兼容
- ✅ `ws_id: str = ""` 默认值 → 遗留调用者（如未来新增的其他 `_send_to_agent` 调用点）行为不变
- ✅ `return False` 不变 — 调用者忽略返回值的行为与 R55 一致

### 性能
- ✅ 回退广播仅在目标 agent 离线时触发（非空 `_connections.get(agent_id, set())` 快速返回）
- ✅ 离线时遍历 `ws_obj.members`，每个成员只对其在线连接发送（不重连、不持久化到所有）

---

## 7. 边界分析与验收验证矩阵

| # | 验收项 | 预期 | 实现验证 | Verdict |
|:-:|:-------|:-----|:---------|:-------:|
| A-1 | 目标 bot 在线时定向送达 | 只有目标 bot 收到 | 在线路径完全未改，`conns` 非空走原定向 | ✅ |
| A-2 | 目标 bot 离线时回退广播 | 工作室出现 `[回退广播]` | `if not conns:` + `ws_id` 非空 → 全广播 + chat_log | ✅ |
| A-3 | 离线 bot 重连后读到通知 | chat_log 有记录 | `write_chat_log(..., channel=ws_id)` 写入工作室日志文件 | ✅ |
| A-4 | admin 日志完整 | Step 交接日志不因回退缺失或重复 | admin 日志由上层写入，回退仅写工作室频道 | ✅ |

---

## 8. 总结

```
改动文件：server/handler.py (+28 / -7)

┌─ _send_to_agent 签名
│   +ws_id: str = ""
│
├─ 离线回退逻辑（~25 行新增）
│   ws_id 有值 ──→ 遍历 ws_obj.members → 全广播 → write_chat_log(channel=ws_id)
│   ws_id 空值 ──→ 旧 lobby write_chat_log（向后兼容）
│
├─ _cmd_step_complete → 传 ws_id=sender_ch ✅
├─ _cmd_step_reject    → 传 ws_id=sender_ch ✅
└─ 在线定向路径       → 未修改 ✅

结论：✅ 通过。改动精确、测试路径清晰、向后兼容。无阻塞问题。
```
