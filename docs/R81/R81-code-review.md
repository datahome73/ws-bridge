# R81 代码审查报告 — 🔍 小周

> **审查对象：** commit `3938e94`
> **审查文件：** `server/handler.py`（+284 行，净增）
> **对比基准：** R81 产品需求 + 技术方案 + WORK_PLAN
> **审查日期：** 2026-07-09

---

## 审查结论：✅ **通过**

全部 6 项审查项通过，0 blocking 问题，1 条建议。

---

## 逐项审查

### ① Owner 守卫正确性 — `_cmd_workspace_remove()` ✅

**检查：** 只允许 `ws.owner_id == sender_id` 执行移除。

```python
# _cmd_workspace_remove — 硬性守卫
if sender_id != ws.owner_id:
    return "❌ 权限不足：仅工作区所有者可移除成员"
```

- ✅ 守卫在参数解析后立即执行，无旁路
- ✅ 非 owner 返回明确拒绝消息
- ✅ `target_id == ws.owner_id` 额外守卫防止 owner 自移除
- ✅ 调用 `ws_mod.remove_member()` 前已做所有有效性检查

### ② Leave 的 Owner 检查 — `_cmd_workspace_leave()` ✅

**检查：** Owner 不能退出自己的工作室。

```python
# _cmd_workspace_leave — Owner 守卫
if sender_id == ws.owner_id:
    return "❌ 你是该工作区的所有者，不能退出。如需关闭请使用 !close_workspace"
```

- ✅ 守卫在确认成员身份后、执行 remove 前
- ✅ 返回消息明确指引使用 `!close_workspace`
- ✅ 普通成员可正常退出

### ③ `_broadcast_to_channel()` 第二参数类型 ✅

**检查：** `_broadcast_to_channel(channel, payload)` 的 payload 必须是 `dict` 而非 `str`。

函数签名验证（L320）：
```python
async def _broadcast_to_channel(channel: str, payload: dict) -> int:
```

全部 5 处新调用均使用 dict：
| 调用位置 | payload 类型 | 验证 |
|:--------|:------------|:----:|
| `_cmd_workspace_join` | `{ "type": "broadcast", "channel": ws_id, ... }` | ✅ dict |
| `_cmd_workspace_leave` | `{ "type": "broadcast", "channel": ws_id, ... }` | ✅ dict |
| `_cmd_workspace_add` | `{ "type": "broadcast", "channel": ws_id, ... }` | ✅ dict |
| `_cmd_workspace_remove` | `{ "type": "broadcast", "channel": ws_id, ... }` | ✅ dict |
| `_cmd_pipeline_start` B2 invite | `{ "type": "broadcast", "channel": target_ch, ... }` | ✅ dict |

> 💡 **注：** 产品需求文档中的伪代码使用了字符串形式（`await _broadcast_to_channel(ws_id, msg)`），但实际函数签名要求 dict。实现正确使用了 dict 格式。伪代码 vs 实现差异已在技术方案 §0.2 中指出，开发者已正确处理。

### ④ 审计日志 — 不由函数体手动调用 ✅

**检查：** 中央路由器 L5244 自动处理所有 `_ADMIN_COMMANDS` 注册命令的审计日志，函数体内不应手动 `_log_audit`。

- ✅ 中央路由器（L5237-5250）对所有 `_ADMIN_COMMANDS` 命令自动执行 `_log_audit(sender_id, cmd_name, params, "success", result)`
- ✅ 5 个新命令均已注册在 `_ADMIN_COMMANDS` 中，自动走此路径
- ✅ 新代码中**无任何**手动 `_log_audit()` 或 `_audit_logger.log()` 调用
- ✅ 技术方案 §0.2 已明确指出此约定，实现一致

### ⑤ Scope 合规 ✅

**检查：** 未改动 auth.py（角色等级）、管线状态机、Web 前端、bot 代码。

```
$ git diff 3938e94^..3938e94 --name-only
server/handler.py
```

- ✅ 仅 `server/handler.py` 一个文件改动
- ✅ auth.py 未触碰
- ✅ 管线状态机（`_PIPELINE_STATE` / `_PIPELINE_CONFIG`）未改动
- ✅ Web 前端未改动
- ✅ bot 端代码未改动
- ✅ `worker_manager.py` / watchdog 未改动

### ⑥ 代码零内部名残留 ✅

**检查：** 无内部组织名、测试名、占位符残留。

- ✅ 新代码中无可疑内部名
- ✅ 所有 `datahome73` 引用均为已有的 GitHub URL（`raw.githubusercontent.com/datahome73/ws-bridge/...`），属于基础设施引用而非内部名泄漏
- ✅ `test_agent`、`dummy`、`ACME`、`example` 等残留模式未出现

---

## 额外验证

### 函数/变量引用完整性

| 引用 | 来源 | 验证 |
|:----|:-----|:----:|
| `persistence.get_agent_channel()` | persistence.py:144 | ✅ 已定义 |
| `persistence.set_agent_channel()` | persistence.py | ✅ 已定义 |
| `persistence.save_agent_channels()` | persistence.py | ✅ 已定义 |
| `persistence.get_inbox_channel()` | persistence.py:155 | ✅ 已定义 |
| `auth.get_agent_name()` | auth.py:224 | ✅ 已定义 |
| `ws_mod.get_workspace()` | workspace.py | ✅ 已定义 |
| `ws_mod.add_member()` | workspace.py:332 | ✅ 已定义 |
| `ws_mod.remove_member()` | workspace.py:341 | ✅ 已定义 |
| `_get_step_config()` | handler.py:1481 | ✅ 已定义 |
| `_get_agents_by_role()` | handler.py:1250 | ✅ 已定义 |
| `SYSTEM_AGENT_ID` | handler.py:48 | ✅ 已定义 |
| `p.WORKSPACE_ID_PREFIX` | protocol.py:161 | ✅ 已定义 |

### 错误/异常处理

| 代码块 | 异常保护 | 验证 |
|:------|:---------|:----:|
| B1 — ACK 自动加入 | `try/except Exception` 包裹 | ✅ |
| B2 — pipeline_start inbox 邀请 | `try/except Exception` 包裹 | ✅ |

### 需求-方案追踪矩阵

| 需求 | 实现位置 | 状态 |
|:----|:---------|:----:|
| A1 — `!workspace_join` | `_cmd_workspace_join()` + `_ADMIN_COMMANDS` 注册 | ✅ |
| A2 — `!workspace_leave` | `_cmd_workspace_leave()` + `_ADMIN_COMMANDS` 注册 | ✅ |
| A3 — `!workspace_add` | `_cmd_workspace_add()` + `_ADMIN_COMMANDS` 注册 | ✅ |
| A4 — `!workspace_remove`（仅 owner） | `_cmd_workspace_remove()` + `_ADMIN_COMMANDS` 注册 | ✅ |
| A5 — 命令注册（min_role=2 x5） | `_ADMIN_COMMANDS` 5 条新条目 | ✅ |
| B1 — ACK 后自动加入 | MSG_ACK 分支追加检测 + add_member | ✅ |
| B2 — pipeline_start 成员不足发 inbox 邀请 | `_cmd_pipeline_start` 末尾追加 | ✅ |
| C — `!workspace_list_members` | `_cmd_workspace_list_members()` + 注册 | ✅ |

---

## 建议（非阻塞）

| # | 级别 | 位置 | 描述 |
|:-:|:----:|:-----|:-----|
| ⚪ | 💡 | `_resolve_workspace()` | 当 sender 活跃频道不是工作区时（如 lobby），`ws_mod.get_workspace()` 返回 None，错误消息为「工作区 lobby 不存在」。虽然功能正确（明确告知用户需要指定 `--workspace`），但消息可更精准：「当前活跃频道不是工作区，请使用 --workspace <ws_id> 指定」。这是纯 UX 改进，不影响正确性。 |

---

## 审查质检

| 指标 | 值 |
|:----|:---|
| 净增行数 | +284 |
| 审查项 | 6/6 ✅ |
| Blocking | 0 |
| 建议 | 1（💡 UX 改进） |

**签名：** 🔍 小周
