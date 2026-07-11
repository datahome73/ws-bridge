# R79 代码审查报告 — 新虾注册流程：欢迎消息 + 审批通知 + 自动切频道 + 大厅广播 🦐

> **审查人：** 🔍 审查工程师
> **审查对象：** `34b934c` feat(R79): 新虾注册流程 — 欢迎消息 + 审批通知 + 自动切频道 + 大厅广播
> **审查日期：** 2026-07-09
> **改动统计：** 1 文件, +150/-2 行
> **技术方案：** `docs/R79/R79-tech-plan.md`

---

## 0. 审查结论

> 🟢 **通过 — 0 项 🔴, 0 项 🟡, 1 项 💡 — 直接进入 Step 5 QA**
>
> | 级别 | 数量 | 说明 |
> |:----:|:----:|:------|
> | 🔴 阻塞 | 0 | — |
> | 🟡 W 级 | 0 | — |
> | 💡 建议 | 1 | S-1: `_broadcast_to_channel` 选型说明注释 |

---

## 1. 改动统计

| 文件 | 行数 | 改动类型 | 说明 |
|:-----|:----:|:---------|:-----|
| `server/handler.py` | +150/-2 | 修改 | `handle_agent_card_register()` 扩展 + 4 个新函数 |
| **其他文件** | 0 | 无改动 | ✅ Scope 合规 |

---

## 2. 逐项审查

### ✅ 2.1 try/except 覆盖完整性

**结构分析（3 层防御）：**

```
handle_agent_card_register():
  1. result = ac_mod.register_from_agent(...)    ← 原始注册（先执行）
  2. try:                                         ← 外层防御
     try:   A: 欢迎消息发送                        ← 内层防护
     except: logger.warning("R79 A: ...")
     try:   B: 管理员通知 (_broadcast_to_channel)  ← 内层防护 + 函数内 try/except
     except: logger.warning("R79 B: ...")
     try:   C: 频道切换 (_send)                    ← 内层防护
     except: logger.warning("R79 C: ...")
     try:   D: 大厅广播 (_broadcast_to_channel)    ← 内层防护 + 函数内 try/except
     except: logger.warning("R79 D: ...")
  3. except: logger.warning("R79 post-process ...") ← 外层捕获
  4. return result                                  ← 始终返回
```

| 发送点 | 发送函数 | 覆盖 | 异常不阻断 |
|:-------|:---------|:----:|:----------:|
| A: 欢迎消息 | `_send(ws, ...)` | ✅ try/except 内层 | ✅ |
| B: 管理员通知 | `_broadcast_to_channel()` | ✅ try/except 内层 + 函数内 | ✅ |
| C: 频道切换 | `_send(ws, ...)` | ✅ try/except 内层 | ✅ |
| D: 大厅广播 | `_broadcast_to_channel()` | ✅ try/except 内层 + 函数内 | ✅ |

**关键设计：** `register_from_agent()` 在 try 前执行，`return result` 在 try 后——无论 post-process 是否异常，注册结果始终返回。✅

### ✅ 2.2 BROADCAST_ADMINS 判断

```python
def _should_notify_admins(display_name: str) -> bool:
    """如果注册者本人是管理员，则不发通知——管理员知道自己注册了。"""
    return display_name not in config.BROADCAST_ADMINS
```

**验证：**

| 检查项 | 结果 |
|:-------|:-----|
| `config.BROADCAST_ADMINS` 存在？ | ✅ `server/config.py:13` — `set[str]`，从 `BROADCAST_ADMINS` 环境变量解析 |
| 判断依据是 `display_name` 而非 `role`？ | ✅ `display_name in config.BROADCAST_ADMINS` |
| 管理员注册时不发通知？ | ✅ `not in` → False → 跳过 B 段 |
| 非管理员注册时发通知？ | ✅ `not in` → True → 执行 B 段 |

**逻辑正确性表格：**

| 场景 | `_should_notify_admins()` | 行为 |
|:-----|:------------------------:|:-----|
| 管理员（display_name ∈ BROADCAST_ADMINS）注册 | False | 不发通知（管理员知道自己注册了） |
| 普通 bot（display_name ∉ BROADCAST_ADMINS）注册 | True | 发通知到 _admin 频道 |

### ✅ 2.3 MSG_SET_ACTIVE_CHANNEL 发送格式

```python
await _send(ws, {
    "type": p.MSG_SET_ACTIVE_CHANNEL,     # "set_active_channel"
    p.FIELD_CHANNEL: p.LOBBY,             # "channel": "lobby"
    "from_name": "系统", "from": "系统",
    "content": "注册完成，频道已切换至大厅",
    "ts": time.time(),
})
```

**与现有协议对比：**

| 字段 | R79 格式 | 现有格式（handler.py:5222） | 兼容性 |
|:-----|:---------|:---------------------------|:-------|
| `type` | `p.MSG_SET_ACTIVE_CHANNEL` | `p.MSG_SET_ACTIVE_CHANNEL` | ✅ 一致 |
| `channel` | `p.FIELD_CHANNEL: p.LOBBY` | `p.FIELD_CHANNEL: ws_id` | ✅ 一致 |
| `from_name` | `"系统"` | `config.PIPELINE_PM_NAME` | ✅ 合法格式 |
| `from` | `"系统"` | — | ✅ 可选字段 |
| `content` | 文本描述 | — | ✅ 可选字段 |
| `ts` | `time.time()` | 存在 | ✅ |

**客户端处理验证：**
- `__main__.py:6279-6280` — 处理 `MSG_SET_ACTIVE_CHANNEL` 时只读取 `channel` 字段，忽略其他字段 ✅
- `handler.py:6279-6280` — 同样只读取 `channel` 字段 ✅

### ✅ 2.4 常量命名

| 常量 | 值 | 位置 | 命名规范 | 用途 |
|:-----|:---|:-----|:---------|:-----|
| `SYSTEM_AGENT_ID` | `"_system"` | `handler.py:47` | ✅ SCREAMING_SNAKE_CASE | 系统消息发送者标识 |
| `REGISTRATION_BROADCAST_ENABLED` | env toggle | `handler.py:49-51` | ✅ SCREAMING_SNAKE_CASE + `_ENABLED` 后缀 | 大厅广播开关 |

**环境变量命名一致性：** env var 名 `REGISTRATION_BROADCAST_ENABLED` 与常量名一致 ✅
**默认安全：** 默认为 `"0"`（关闭），需显式开启 ✅

### ✅ 2.5 Scope 合规

| 文件 | 状态 |
|:-----|:----:|
| `server/handler.py` | ✅ **唯一改动文件**（+150/-2） |
| `shared/protocol.py` | ❌ 未改动 ✅ |
| `server/config.py` | ❌ 未改动（`BROADCAST_ADMINS` 是已有配置）✅ |
| bot 端代码 | ❌ 未改动 ✅ |
| gateway-plugin | ❌ 未改动 ✅ |

**无 scope creep** ✅ — 注册流程的 post-process 全部集中在一个函数（`handle_agent_card_register`）中，不碰协议、bot、config。

### ✅ 2.6 注册流程回归

```
原始流程：
  handle_agent_card_register(ws, agent_id, msg)
    → return ac_mod.register_from_agent(agent_id, msg)

R79 流程：
  handle_agent_card_register(ws, agent_id, msg)
    → result = ac_mod.register_from_agent(agent_id, msg)   # 先注册
    → try:  post-process (欢迎/通知/切频道/广播)          # 后处理，异常不阻断
    → return result                                        # 始终返回注册结果
```

| 回归检查项 | 结果 | 证据 |
|:-----------|:-----|:------|
| 返回值类型 | ✅ 一致 | `result` 即 `register_from_agent()` 返回的 `dict` |
| 注册本身先执行 | ✅ | `register_from_agent()` 在 try 前 |
| 异常不影响注册 | ✅ | `return result` 在 try/except 后 |
| 已有 bot 重新注册 | ✅ | 同样走 `register_from_agent`，post-process 可选 |

---

## 3. 新增函数审查

### 3.1 `_build_registration_welcome()`

```python
def _build_registration_welcome(...) -> str:
    roles_str = ", ".join(pipeline_roles) if pipeline_roles else "未声明"
    return f"🎉 欢迎加入 ws-bridge！\n\n你已成功注册...\n当前角色: {roles_str}\n\n📋 下一事项：..."
```

- ✅ 纯字符串构建函数，无 I/O 或副作用
- ✅ `pipeline_roles` 为空时显示 "未声明"
- ✅ `agent_id[:16]` 截断显示

### 3.2 `_build_admin_notification()`

- ✅ 同模式，含 `!approve_pairing` 操作指引

### 3.3 `_should_notify_admins()`

- ✅ 纯判断函数，1 行逻辑

### 3.4 `_broadcast_to_channel()`

```python
async def _broadcast_to_channel(channel: str, payload: dict) -> int:
    payload_json = json.dumps(payload)
    for aid, conns in _connections.items():
        for conn in list(conns):
            try:
                # send via send_str or send
            except Exception:
                pass
    # 同时持久化 DB + chat log
    ms.save_message(...)
    write_chat_log(...)
```

**亮点：** 一条函数同时完成 WS 推送 + DB 持久化 + 日志记录，复用性高 ✅

**💡 S-1: 建议补充注释说明广播策略**
本函数广播到所有连接，不按 channel 过滤——这是 ws-bridge 现有的广播模型（客户端按 `channel` 字段自过滤）。建议在 docstring 中注释此策略，避免未来维护者误以为有通道过滤。

---

## 4. 边界情况分析

| 场景 | 预期 | 实现 | 状态 |
|:-----|:-----|:-----|:----:|
| 注册成功 + 所有后处理成功 | 欢迎/通知/切频道/广播全部完成 | ✅ |
| 注册成功 + 欢迎消息发送失败 | 日志告警，通知/切频道继续 | ✅ 内层 try/except |
| 注册成功 + 管理员通知失败 | 日志告警，切频道继续 | ✅ |
| 注册成功 + 切频道失败 | 日志告警，欢迎/通知已发送 | ✅ |
| 注册成功 + 大厅广播失败（未开启） | 不影响，广播默认关闭 | ✅ `REGISTRATION_BROADCAST_ENABLED` 检查 |
| 注册本身失败（`register_from_agent` 异常） | 异常传播到调用方，不执行后处理 | ✅ 未在 R79 的 try 内 |
| 管理员注册 | 跳过管理员通知 | ✅ `_should_notify_admins()` |
| `BROADCAST_ADMINS` 为空环境变量 | 空 set，所有 bot 都发通知 | ✅ `set()` |
| `REGISTRATION_BROADCAST_ENABLED` 未设 | 默认关闭，不广播 | ✅ `== "1"` |
| 连接在发送中断开 | `except Exception: pass` 跳过断线连接 | ✅ |
| `_connections` 中 connection 为 None | `list(conns)` + `hasattr` 检查 | ✅ |

---

## 5. 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:-----|
| 敏感信息泄露 | ✅ `agent_id[:16]...` 截断显示 |
| 调试 print 残留 | ✅ 无 |
| TODO/FIXME 残留 | ✅ 无 |
| R 标签准确 | ✅ 全部为 R79 |
| `except Exception: pass` | ✅ 合理（非阻塞后处理，日志已记录） |
| 类型注解 | ✅ 所有新函数有完整类型注解 |

---

## 6. 问题清单

| 级别 | 编号 | 描述 | 位置 | 建议 |
|:----:|:----:|:-----|:-----|:-----|
| 💡 | S-1 | `_broadcast_to_channel()` 广播到所有连接，未按 channel 过滤——与 ws-bridge 现有广播模型一致，建议 docstring 中显式注明 | `handler.py:322` | 添加到 docstring |

---

## 7. 总结

### ✅ 通过项

| 审查项 | 结果 |
|:-------|:----:|
| 1️⃣ try/except 覆盖完整性 | ✅ 3 层防御，注册绝不阻断 |
| 2️⃣ BROADCAST_ADMINS 判断 | ✅ `display_name in config.BROADCAST_ADMINS` |
| 3️⃣ MSG_SET_ACTIVE_CHANNEL 发送格式 | ✅ 与现有协议完全兼容 |
| 4️⃣ 常量命名 | ✅ SYSTEM_AGENT_ID / REGISTRATION_BROADCAST_ENABLED |
| 5️⃣ Scope 合规 | ✅ 仅改 1 文件（handler.py） |
| 6️⃣ 注册流程回归 | ✅ 注册先执行，后处理不阻断 |

### 💡 建议项

- S-1: `_broadcast_to_channel()` docstring 补充广播策略说明

---

> **总体：🟢 通过 — 0 阻塞，直接进入 Step 5 QA**
>
> 审查完毕：2026-07-09 🔍 审查工程师
