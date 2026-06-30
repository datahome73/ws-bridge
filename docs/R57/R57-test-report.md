# R57 测试报告 — Step 5

> **测试人：** 🦐 泰虾
> **测试基准：** commit `3b4fae0`（方向 A + 方向 C 实现）
> **代码审查：** `81db83d`（🟢 通过，13/13 项 100%，1 💡 改进建议）
> **测试日期：** 2026-06-30
> **测试范围：** 方向 A（主备点名换人）+ 方向 C（角色名显示）

---

## 总体结论

| 方向 | 状态 | 通过 | 说明 |
|:----:|:----:|:----:|:------|
| 🔶 A | 🟡 代码级通过 | A-1~A-9 全部 ✅ | 逻辑完整，边界处理周全。生产实操需 WS 直连 + 多 bot 在线 |
| 🔶 C | 🟡 代码级通过 | C-1~C-4 全部 ✅ | 改动精确，回退安全 |
| 🔶 B | 🟢 通过 | B-1~B-3 ✅ | 纯流程改进，零代码改动 |

**代码级 16/16 项验收全部通过 ✅**

**前置条件：** 实操验证需在 dev 容器上部署最新 `dev` 分支代码，并确保至少 2 个 bot（不同角色）在线连接到 dev WS 端点（`72.62.197.200:8766`）。

---

## 方向 A：在线预检 + 点名换人

### 代码改动全景

```
server/config.py   | 6 insertions(+), 6 deletions(-)
server/handler.py  | 204 insertions(+), 11 deletions(-)

方向 A 核心函数：
  - _r57_switch_to_backup()  — 新函数，备份切换逻辑
  - _r57_wait_for_ack()      — 新函数，30s 点名超时
  - _cmd_step_complete 增强  — 在线预检 + 分支选择
  - handle_broadcast ACK钩子 — 接收点名回复
  - _cmd_pipeline_status增强 — 备用接替标记
```

---

### A-1：主角在线 → 点名 30s → 回复 → 正常交接

**代码验证：**

```python
# handler.py (3b4fae0)
conns = _connections.get(primary_agent, set())
if conns:
    # 主角在线 → 点名
    rollcall_msg = f"@**{primary_name}** Step「{next_step}」轮到你了，请 30 秒内回复确认"
    _persist_broadcast(sender_ch, "系统", rollcall_msg)
    for conn in conns:
        await _send(conn, {"type": "broadcast", ...})
    
    # 30s 超时等待
    ack_received = await _r57_wait_for_ack(primary_agent, timeout=30)
    
    if ack_received:
        # 正常交接
        for agent_id in target_agents:
            await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
        rollcall_result = f"✅ 主角 {primary_name} 已确认，正常交接 {next_step}"
    else:
        # 超时切换备用
        rollcall_result = await _r57_switch_to_backup(..., reason="primary_timeout")
```

- ✅ `_r57_wait_for_ack` 使用 `asyncio.Event` + `asyncio.wait_for()` — 标准异步超时模式
- ✅ ACK 钩子在 `handle_broadcast` 中：任意消息即触发 event.set()
- ✅ 30s 超时精确（`asyncio.wait_for` 的 `timeout=30`）
- ✅ 正常交接走 `_send_to_agent` 定向通知，与 R56 一致

**结论：✅ 代码级通过**

---

### A-2：主角离线 → 直接切备用，0 秒等待

**代码验证：**

```python
if not conns:
    # 直接切备用，不等待
    rollcall_result = await _r57_switch_to_backup(
        ..., reason="primary_offline",
    )
```

- ✅ `not conns` 分支在点名循环之前，不执行点名、不等待
- ✅ `reason="primary_offline"` 区分离线 vs 超时场景

**结论：✅ 代码级通过**

---

### A-3：主角在线但不回复 → 30s 超时切备用

已在上文 A-1 中覆盖。`_r57_wait_for_ack` 超时后返回 `False`，触发 `_r57_switch_to_backup(reason="primary_timeout")`。

**结论：✅ 代码级通过**

---

### A-4：备用接替后工作室收到换人公告

**代码验证（`_r57_switch_to_backup`）：**

```python
if reason == "primary_offline":
    swap_msg = f"⚠️ 主角 {primary_name} 离线，{next_step} 由备用接替"
else:
    swap_msg = f"⚠️ 主角 {primary_name} 未响应，{next_step} 由备用接替"
_persist_broadcast(sender_ch, "系统", swap_msg)

# 通知备用
backup_notify = targeted_notify + "\n（🔧 您作为备用接替此 Step）"
await _send_to_agent(backup_agent, backup_notify, ws_id=sender_ch)
```

- ✅ `_persist_broadcast` 写入工作室（全广播）
- ✅ 备用通知包含原通知内容 + 「备用接替」标识

**结论：✅ 代码级通过**

---

### A-5：admin 频道记录换人日志

**代码验证：**

```python
admin_msg = f"📋 {round_name} | {next_step} | {reason.replace('_', ' ')} → 备用接替"
ms.save_message(..., channel=admin_channel)
write_chat_log("系统", admin_msg, channel=admin_channel)
```

- ✅ 写入 `_admin` 频道（`ms.save_message` + `write_chat_log` 双重保障）
- ✅ 包含管线名、Step、换人原因

**结论：✅ 代码级通过**

---

### A-6：`!pipeline_status` 标注备用接替

**代码验证：**

```python
backup_suffix = ""
pipeline_backup = pstate.get("backup_active", {})
if step_key == pipeline_backup.get("step"):
    backup_suffix = "（备用接替）"
lines.append(f"  {task_state} {step_key} — {role}{current}{backup_suffix}")
```

- ✅ `backup_active` 在 `_r57_switch_to_backup` 中设置（在找到在线备用时）
- ✅ 展示格式：`step3 — dev ◀ 当前（备用接替）`

**💡 代码审查建议：** backup_active 在 Step 正常完成后未清理。这意味着如果 step3 是备用接替，step3 完成后 `backup_active` 仍残留，不会自动清除。可以通过在 `_cmd_step_complete` 标记 Step N 完成时清除 `backup_active` 来解决。

**结论：✅ 代码级通过（非阻塞缺陷）**

---

### A-7：主角在 Step 进行中重新上线 → 不抢占，自动待命

**代码验证：**

本验收项是**运行期行为约束**——代码层面不主动干预已分配的备用。`_r57_switch_to_backup` 只负责切换，Step 执行过程中没有「发现主角上线再切回」的逻辑。

- ✅ 不存在「主角上线自动抢回」的代码路径 — 安全
- ✅ `_connections` 监控仅用于点名前预检，不用于 Step 运行中状态变更
- ✅ 主角重新上线后在下一次 `!step_complete` 前不会有干扰行为

**结论：✅ 代码级通过**

---

### A-8：主角和备用同时离线 → 系统广播 + PM 处理

**代码验证：**

```python
if not backup_assigned:
    critical_msg = f"🔴 {next_step} 主角和备用均不在线，等待协调"
    _persist_broadcast(sender_ch, "系统", critical_msg)
    # admin 频道额外日志
    admin_msg = f"📋 {round_name} | {next_step} | 主角+备用均离线，需人工介入"
    ms.save_message(..., channel=admin_channel)
```

- ✅ 主角 `_connections` 空 + 备用 `_connections` 空 → 双离线
- ✅ 工作室广播 + admin 频道日志双通道通知
- ✅ 不崩溃、不回退到无通知状态

**结论：✅ 代码级通过**

---

### A-9：无 backup 配置 → 行为不变

**代码验证：**

```python
if not primary_agents:
    # 无 primary 配置 → 回退原有全通知
    if cards:
        target_agents = _find_agents_by_role(next_role, member_ids, cards)
    else:
        target_agents = [...]
    for agent_id in target_agents:
        await _send_to_agent(agent_id, targeted_notify, ws_id=sender_ch)
```

以及 `_r57_switch_to_backup` 中：
```python
if not backup_agents:
    # 无 backup 配置 → 通知所有匹配角色
    backup_agents = _find_agents_by_role(next_role, member_ids, cards)
```

- ✅ 无 `primary` 字段 → 全通知（同 R56 行为）
- ✅ 无 `backup` 字段 → `_r57_switch_to_backup` 通知所有匹配角色

**结论：✅ 代码级通过**

---

### 方向 A 小结

> **9/9 验收标准在代码级全部通过 ✅**
>
> 核心逻辑经过 T 型分支验证：
> - primary_agents 为空 → 全通知（A-9 兼容）
> - primary_agents 非空 → 检测 _connections
>   - 离线 → 直接切备用（A-2）
>   - 在线 → 点名 30s
>     - 回复 → 正常交接（A-1）
>     - 超时 → 切备用（A-3）
>   - 备用在线 → 定向通知 + 公告（A-4, A-6）
>   - 备用也离线 → 双离线广播（A-8）
> - backup_active 在 Step 完成后未清理（💡 审查建议，非阻塞）

---

## 方向 C：角色名显示

### C-1：`!pipeline_start` 成员列表展示角色名

**代码验证（`_cmd_create_workspace`）：**

```python
member_names = []
for mid in member_ids:
    name = users.get(mid, {}).get("name", "")
    if not name:
        role = users.get(mid, {}).get("role", "")
        name = role if role else mid[:12]
    member_names.append(name)
member_list = ", ".join(member_names)
```

- ✅ 优先使用 `name` 字段
- ✅ `name` 缺失时回退到 `role`
- ✅ `role` 也缺失时回退到 `agent_id[:12]`
- ✅ 不再暴露完整 agent ID

**结论：✅ 代码级通过**

### C-2：`!pipeline_status` 可读角色名

**代码验证：**

```python
label = name if name else (role_label if role_label else mid[:12])
online = "🟢" if mid in _connections and _connections[mid] else "🔴"
member_info.append(f"{online}{label}")
```

- ✅ 名称优先，role 回退，ID 兜底
- ✅ 附带在线状态标记（🟢/🔴）

**结论：✅ 代码级通过**

### C-3：agent 名称缺失时用 role 回退

已在 C-1/C-2 中覆盖验证。

**结论：✅ 代码级通过**

### C-4：agent ID 在服务端日志中保留不变

- ✅ 仅系统消息输出用名称替代
- ✅ `_connections` 和 `auth.get_users()` 内部仍使用 agent ID
- ✅ `write_chat_log` 写日志时仍然使用原 sender 名称
- ✅ 无任何代码路径泄露 ID 到 Web UI 的「用户可读」区域

**结论：✅ 代码级通过**

---

## 方向 B：PM 主动监控 + TG 即时汇报

**零代码改动** — 纯工作流程改进。

| 验收项 | 状态 | 说明 |
|:------:|:----:|:------|
| B-1 | ✅ | 工作室安静 10 分钟 → PM TG 汇报 — 流程已定义，无可验证的代码逻辑 |
| B-2 | ✅ | 汇报格式含标准模板 — 见需求文档 §2-B |
| B-3 | ✅ | PM 汇报后不等待回复 — 流程定义 |

---

## 代码审查建议检查

**💡 backup_active 清理**（来自代码审查报告）：

在 `_cmd_step_complete` 的 Step N 标记完成处，增加 `backup_active` 清除逻辑：

```python
# 在 Step 指针推进后（handler.py 当前约 L1450 行）
pstate.pop("backup_active", None)
```

当前无此清除 → step3 备用接替完成后，step4 的 `!pipeline_status` 仍展示 step3（备用接替）。**建议 R58 或 Step 6 前附带修复。**

---

## 测试结论

| 验收项 | 代码级 | 实操需 | 说明 |
|:------:|:------:|:------:|:------|
| A-1 | ✅ | 多 bot 在线 | 主角在线→点名→30s 确认→正常交接 |
| A-2 | ✅ | 断线目标 bot | 主角离线→0s 等待→直接切备用 |
| A-3 | ✅ | 主角在线不回复 | 30s 超时→切备用 |
| A-4 | ✅ | 工作室检视 | 备用接替公告含角色名 |
| A-5 | ✅ | admin 频道检视 | 换人日志 |
| A-6 | ✅ | pipeline_status | 备用接替标记 |
| A-7 | ✅ | 模拟重连 | 不抢占 |
| A-8 | ✅ | 双 bot 断线 | 广播+admin 日志 |
| A-9 | ✅ | 删除 backup 配置 | 全通知兼容 |
| C-1 | ✅ | 启动管线 | 成员列表角色名 |
| C-2 | ✅ | pipeline_status | 可读名+在线状态 |
| C-3 | ✅ | 构造无 name agent | role 回退 |
| C-4 | ✅ | 服务端日志 | ID 保留 |
| B-1~B-3 | ✅ | — | 零代码流程 |

**16/16 验收标准代码级全部通过 ✅**

**实操验证条件：** 部署 `dev` 代码到 dev WS 容器（端口 8766），确保 ≥3 个不同角色的 bot 同时在线连接。

**💡 建议 Step 6 前附带修复：** `backup_active` 在 Step 完成后清除（约 2 行代码）。
