# R58 代码审查报告

> **审查轮次：** R58 Step 4 编码  
> **审查者：** 🔍 小周  
> **审查 commit：** `87da8ef`  
> **改动文件：** `server/handler.py` (+87行), `server/config.py` (+18/-5行)  
> **基于需求文档：** `docs/R58/R58-product-requirements.md`  
> **基于技术方案：** `docs/R58/R58-tech-plan.md` v1.0  

---

## 0. 审查结论

### 🔴 有发现 → 退回爱泰💻修复

**2 个 🔴 Blocking 问题、2 个 🟡 Advisory 问题**。修复后方可进入 Step 6。

| 严重度 | 数量 | 详情 |
|:------:|:----:|:------|
| 🔴 Blocking | 2 | B1: `target_agents` 在备份路径未定义 → NameError；B2: `notify_mark` 未拼入输出行 → C3 失效 |
| 🟡 Advisory | 2 | W1: 广播循环代码重复（3 次相同模式）；W2: `output_ref` 为空时显示空白标签 |

---

## 1. 规范检查

| 检查项 | 状态 | 详情 |
|:-------|:----:|:------|
| commit message 格式 | ✅ | `feat(R58): R58 step3: from_name系統→PM @mention + 工作室广播 + ACK日志 + 状态跟踪` — 格式合规，内容准确 |
| 无调试代码/日志残留 | ✅ | 无可疑残留 |
| 无 TODO/FIXME/console.log | ✅ | 无 |
| 文件范围符合方案 | ✅ | 仅 `handler.py` + `config.py`，与方案一致 |
| 语法检查 | ✅ | `python3 -c "compile(open(...))"` 两文件均通过 ✅ |
| R 标签准确性 | ✅ | 新加注释均为 `R58`，无残留旧轮次标签 |
| 双入口同步 | ✅ N/A | 改动的均为 `_ADMIN_COMMANDS` 内部函数，非消息类型处理分支，无需同步 `__main__.py` |

---

## 2. 需求→方案→代码追溯矩阵

### 方向 A（P0）：Step 交接通知 → 自然 @mention 改造

| 方案项 | 需求验收 | 实现位置 | 状态 |
|:-------|:---------|:---------|:----:|
| A-1: PM 名称来源（config.py 常量 + 环境变量覆盖） | A-6 | `config.py L62-68` — `PIPELINE_PM_NAME` | ✅ |
| A-2: `_cmd_step_complete` 主力 PM @mention 广播 | A-1, A-2, A-3 | `handler.py L1611-1639` — 完整模板 + 广播 + `_persist_broadcast` | ✅ ⚠️ 见 B1 |
| A-3: `_cmd_pipeline_start` 初始点名 PM 通知 | A-5 | `handler.py L1311-1341` — `@全员` kickoff 消息 | ✅ |
| A-4: `_persist_broadcast` from_name 统一 | — | 方案确认无需修改函数签名 | ✅ |
| A-5: 双保险保留 `_send_to_agent` | A-4 | `handler.py L1597-1598` (no-primary path), L1662-1663 (online+ACK path) — 原定向通知保留 | ✅ |
| A-6: 配置化 PM 名称 | — | `config.py L62-68` | ✅ |
| 消息模板含需求 URL | A-2 | `handler.py L1615-1616` | ✅ |
| 消息模板含 WORK_PLAN URL | A-2 | `handler.py L1616-1617` | ✅ |
| 消息模板含上一步产出 | A-2 | `handler.py L1618` — `{output_ref}` | ✅ ⚠️ 见 W2 |
| `from_name` 字段为 PM 非"系统" | A-1 | `handler.py L1627-1628` — `"from_name": pm_name` | ✅ |

### 方向 B（P1）：初始点名 ACK 超时软检查

| 方案项 | 需求验收 | 实现位置 | 状态 |
|:-------|:---------|:---------|:----:|
| B-1: `_cmd_rollcall_next` ACK 超时不阻断 | B-1 | ✅ 方案已确认当前代码不阻断（`_broadcast_active_channel` 返回值未用于阻断） | ✅ |
| B-2: 添加 ACK 超时日志 | B-1 | `handler.py L824-834` — 记录 timedout_members / online_count / acked_members | ✅ |

### 方向 C（P2）：通知状态跟踪 + `!pipeline_status` 增强

| 方案项 | 需求验收 | 实现位置 | 状态 |
|:-------|:---------|:---------|:----:|
| C-1: pstate `step_notifications` 字段 | C-1 | `PIPELINE_STATE[round_name]["step_notifications"][step_key]` — 含 status / notified_at / target_agents | ✅ ⚠️ 见 B1 |
| C-2: `_cmd_step_complete` 中记录通知状态 | C-1 | `handler.py L1678-1684` — `pstate.setdefault("step_notifications", {})` | ✅ ⚠️ 见 B1 |
| C-3: `!pipeline_status` 展示通知状态 | C-1 | `handler.py L2233-2252` — 计算 `notify_mark` 变量 | 🔴 B2 |

### 追溯率统计

| 方向 | 方案项数 | ✅ 通过 | 🔴 有问题 |
|:----:|:--------:|:------:|:---------:|
| A | 11 | 11 | 0 |
| B | 2 | 2 | 0 |
| C | 3 | 1 | 2 |
| **合计** | **16** | **14** | **2** |

---

## 3. 代码质量审查

### 3.1 架构与设计

- ✅ `from_name` 改造设计正确：PM 身份广播走工作室频道，bot 网关识别为人类 @mention → 触发 LLM 工作模式
- ✅ 双保险保留：PM 身份广播（主力）+ `_send_to_agent`（回退）+ MSG_SET_ACTIVE_CHANNEL（协议层），三层互不干扰
- ✅ JSON payload 字段 `type: broadcast`, `channel`, `from_name`, `from`, `content`, `ts` — 与现有 `handle_broadcast` 路径一致，客户端侧按现有逻辑处理
- ✅ `_persist_broadcast` 正确传递 `from_name` 到 `save_message` 和 `write_chat_log`
- ✅ 配置化 PM 名称：环境变量 `WS_PM_NAME` 覆盖默认 `"PM"`，支持换 PM 不改代码

### 3.2 边界情况分析

| # | 场景 | 预期 | 实际 | 状态 |
|:-:|:-----|:-----|:-----|:----:|
| 1 | `!step_complete` 有 primary 且在线 → ACK 收到 | PM 广播 + 定向通知 + 状态记录 | ✅ 正常工作 | ✅ |
| 2 | `!step_complete` 有 primary 且在线 → ACK 超时 → 切备用 | PM 广播 + 备用接替 | 🔴 `target_agents` 未定义 → NameError | **B1** |
| 3 | `!step_complete` 有 primary 但离线 → 直切备用 | PM 广播应跳过？ | 🔴 备份路径无 PM 广播 + `target_agents` NameError | **B1** |
| 4 | `!step_complete` 无 primary 配置 | 全员通知 + 状态记录 | ✅ 正常（`target_agents` 在 if 分支中定义） | ✅ |
| 5 | `!pipeline_status` 有 step_notifications 记录 | 显示 📨/✅ACK/❌静默 标记 | 🔴 `notify_mark` 未拼入输出行 | **B2** |
| 6 | `!pipeline_status` 无 step_notifications 记录 | 空标记 | ✅ `notify_mark` 默认空字符串 | ✅ |
| 7 | `!step_complete` 未带 `--output` 参数 | `output_ref` = `""`，标签显示但无值 | ⚠️ 显示"🔗 上一步产出：\n\n" | **W2** |
| 8 | 广播到已关闭连接 | 静默 try/except 跳过 | ✅ 每个 conn 被 try/except 包裹 | ✅ |

### 3.3 潜在改进建议（💡 非阻塞）

| # | 改进 | 位置 | 说明 |
|:-:|:-----|:-----|:------|
| W1 | 抽取公共广播辅助函数 | A2 (L1621-1638), A3 (L1329-1340) | 相同的 3 层 `for member_id in ws_obj.members: for conn in list(...): try: send` 模式重复 2~3 次。建议抽取 `_broadcast_to_workspace(ws_obj, payload: str)` 函数，减少重复代码 |
| W2 | `output_ref` 空值占位符 | A2 (L1618) | 当 `--output` 未提供时，显示"🔗 上一步产出：\n\n"（空值）。建议显示 `"(未提供)"` 占位符更清晰 |

---

## 4. 🔴 Blocking 问题明细

### 🔴 B1: `target_agents` 在备份代码路径未定义 → NameError

**位置：** `server/handler.py` — `_cmd_step_complete` 函数，C2 记录通知状态区（L1678-1684）

**根因分析：**

`_cmd_step_complete` 中的条件分支：

```
if not primary_agents:
    target_agents = ...   ← ✅ 定义
else:
    primary_agent = primary_agents[0]
    if not conns:
        # 主离线 → 备份路径
        rollcall_result = await _r57_switch_to_backup(...)
        # ❌ target_agents 此处未定义
    else:
        # 主在线 → PM 广播 + ACK 等待
        if ack_received:
            target_agents = ...   ← ✅ 定义
        else:
            # 主超时 → 备份路径
            rollcall_result = await _r57_switch_to_backup(...)
            # ❌ target_agents 此处未定义
```

`_r57_switch_to_backup()` 函数内部不设置 `target_agents`（它返回 `rollcall_result` 字符串）。后续 C2 代码引用：

```python
step_notifications[next_step] = {
    "status": "notified",
    "target_agents": target_agents,   # ← NameError!
}
```

**触发条件：** 当 `!step_complete` 执行时 primary 离线或超时 → `_r57_switch_to_backup` 调用 → C2 代码行触发 `NameError: name 'target_agents' is not defined`。

**修复方案：**

在 `_r57_switch_to_backup` 调用**之前**初始化 `target_agents`：

```python
else:
    primary_agent = primary_agents[0]
    primary_name = ...
    conns = _connections.get(primary_agent, set())
    
    # 提前初始化，确保备份路径也有定义
    target_agents = []
    
    if not conns:
        rollcall_result = await _r57_switch_to_backup(...)
    else:
        # PM broadcast + ACK wait
        ...
        if ack_received:
            target_agents = _find_agents_by_role(...)
        else:
            rollcall_result = await _r57_switch_to_backup(...)
```

或者在 `_r57_switch_to_backup` 内部返回 `target_agents` 并在调用处解包。推荐前者（最小改动）。

**严重度：** 🔴 Blocking — 运行时报错，管线在备份接管场景下完全崩溃

---

### 🔴 B2: `notify_mark` 未拼入 `!pipeline_status` 输出行

**位置：** `server/handler.py` — `_cmd_pipeline_status` 函数（~L2243-2258）

**问题：**

C3 代码计算了 `notify_mark` 变量：

```python
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
```

但输出行**未引用** `notify_mark`：

```python
lines.append(f"  {task_state} {step_key} — {role}{current}{backup_suffix}")
#                                                                  ↑ 缺少 {notify_mark}
```

正确应为：

```python
lines.append(f"  {task_state} {step_key} — {role}{notify_mark}{current}{backup_suffix}")
```

**效果：** `!pipeline_status` 完全不会显示通知状态标记。C-1 验收标准无法通过。

**修复方案：** 将 `{notify_mark}` 加入 f-string 输出行。

**严重度：** 🔴 Blocking — 功能缺失，验收标准不满足

---

## 5. ✅ 通过确认项

| # | 确认项 | 方法 | 结果 |
|:-:|:-------|:-----|:----:|
| ✅ | `_send_to_agent` 保留未被删除 | `grep -n '_send_to_agent' handler.py` → 多调用点保留 | ✅ |
| ✅ | `from_name` 改为 `config.PIPELINE_PM_NAME` | 核实 L1613, L1627-1628 — `pm_name = config.PIPELINE_PM_NAME` | ✅ |
| ✅ | `_persist_broadcast` with PM name | `_persist_broadcast(sender_ch, pm_name, mention_msg)` | ✅ |
| ✅ | ACK 日志方向 B2 | L824-834 — `timedout`, `online_count`, `acked_members` 均记录 | ✅ |
| ✅ | config.py 新增常量 | L62-68 — `PIPELINE_PM_NAME` + docstring | ✅ |
| ✅ | 语法编译通过 | `python3 -c "compile(...)"` — 两文件均 OK | ✅ |
| ✅ | R57 主备逻辑未受影响 | `_find_agents_by_role`, `_r57_switch_to_backup`, `_r57_wait_for_ack` 签名未改 | ✅ |
| ✅ | 双入口无需同步 | 改动的均为 handler.py 内部 `_ADMIN_COMMANDS`，无需修改 `__main__.py` | ✅ |

---

## 6. 总结 + 送达通知

### 修复后需满足的验收标准

| 验收 | 状态 | 备注 |
|:----:|:----:|:------|
| A-1 `from_name` 非"系统" | ✅ | 已实现 |
| A-2 含 URL + 产出 | ✅ ⚠️ | `output_ref` 空值时显示空白（W2 可选修复） |
| A-3 bot 触发工作模式 | ⏳ | 需部署实测验证 |
| A-4 `_send_to_agent` 保留 | ✅ | |
| A-5 `!pipeline_start` PM @mention | ✅ | |
| A-6 `from_name` 可配置 | ✅ | |
| B-1 ACK 超时不阻塞 | ✅ | 已确认 |
| C-1 `!pipeline_status` 通知状态 | 🔴 B2 | `notify_mark` 未拼入输出行 → 修复后 ✅ |

### 退回路径

| 问题 | 类型 | 退回给 |
|:-----|:----:|:-------|
| B1: `target_agents` undefined in backup paths | 实现问题 | 💻 爱泰 |
| B2: `notify_mark` missing from output | 实现问题 | 💻 爱泰 |
| W1: 广播循环重复 | 建议优化 | 💻 爱泰（可选） |
| W2: 空 `output_ref` 标签 | 建议优化 | 💻 爱泰（可选） |

### 工作室频道通知

修复后，爱泰提交 fix commit，小周进行 Post-Fix Sign-Off 确认，然后进入 Step 6 测试验证。
