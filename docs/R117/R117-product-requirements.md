# R117 自动派活修复轮 — agent_id 桥接 + Step 1→Step N 全自动链路

> **轮次：** R117
> **类型：** 代码修复轮
> **PM：** 小谷
> **基线：** R116（协议文档 v3.0 + 全自动就绪已闭环，7/7 ALL GREEN）
> **修复目标：** 解决 R116 实际验证中发现的 `_auto_dispatch` 断流问题

---

## 一、故障分析

### 1.1 R116 实战发现的断流现象

R116 使用 `##start##R116` 创建管线后：

| 步骤 | 结果 | 说明 |
|:-----|:-----|:------|
| `##start##R116` | ✅ 管线创建成功，Step 1 派活到小谷 | `_handle_hash_start()` 正常 |
| `已完成 ✅ R116 Step 1##work_plan_url=...` | ✅ Step 推进至 2 | `_try_advance_pipeline()` 成功 |
| `##status##R116` | ✅ current_step = 2 | Step 推进成功 |
| Step 2 自动派活到小开 | ❌ **小开未收到任何消息** | `_auto_dispatch()` 发送静默失败 |
| 手动 `_inbox:ws_3f7cdd736c1c` 直发 | ✅ 小开正常收到 | bot 在线，是寻址问题 |

### 1.2 根因链路

```
step_info.agent_id = "arch-bot"    ← card key（非 WS 连接 ID）
     ↓
_send_to_agent("arch-bot", payload)
     ↓
_connections.get("arch-bot")       ← 不存在（_connections 存的是 ws_xxx）
     ↓
sent = 0                           ← 消息静默丢失（try/except 吞掉）
```

**桥接失败位置：** `_handle_hash_start()` L2947-2950

```python
_real_id = name_to_ws.get(card.get("display_name", ""))  # ← 如果 display_name 不在 name_to_ws 中
if _real_id:
    agent_id_for_step = _real_id  # 否则保持 card key
```

`_build_name_to_ws_map()` 从 `persistence.get_api_keys()` 构建映射，但并非所有 bot 的 api_key 都在该存储中（或 display_name 不精确匹配），导致 bridge 失败时 `agent_id_for_step` 保留了 card key。

### 1.3 同类问题

| 位置 | 问题 | 影响 |
|:-----|:------|:------|
| `_handle_hash_start()` L2947-2950 | name_to_ws bridge 失败时 agent_id 留 card key | PipelineContext 中 step 的 agent_id 永久错误 |
| `_auto_dispatch()` L2551 | 直接从 step_info 取 agent_id，不校验格式 | 发送到错误 ID |
| `_send_to_agent()` L2352 | `_connections.get(target_agent_id)` 无 card key fallback | 消息静默丢失（sent=0） |

### 1.4 协议缺口

当前 `PM 完成 Step 1 → 通知 Server → Step 2 自动派活` 的链路在代码中存在，但 **未在任何文档中明确定义 PM 的完成消息格式**。

| 环节 | 当前状态 | 应有状态 |
|:-----|:---------|:---------|
| PM 完成 Step 1 | PM 知道发 `已完成 ✅ R{N} Step N` 到 `_inbox:server` | 明确定义在 `docs/inbox-message-protocol.md` |
| Server 收到完成信号 | `_try_advance_pipeline()` + `_auto_dispatch()` 已编码但寻址失败 | 修复 bridge 后链路完整 |
| 自动派活失败恢复 | PM 手动 L4 直发 | 补充 log 警示 + 自动 fallback 机制 |

---

## 二、修复方案

### 🅰️ `_auto_dispatch()` 增加 card key → WS ID fallback

**目标：** 当 `target_agent_id` 不是 `ws_` 前缀时自动反查真实 WS 连接 ID，不再静默失败。

**修改文件：** `server/ws_server/main.py` 的 `_auto_dispatch()` 函数

**修改逻辑（L2551 前插入）：**

```python
# ── R117 fix: card key → WS ID fallback ──
if not target_agent_id.startswith("ws_"):
    _fallback_id = _resolve_card_key_to_ws_id(target_agent_id)
    if _fallback_id:
        logger.info("[R117] card key %s → WS ID %s (fallback)",
                     target_agent_id, _fallback_id)
        target_agent_id = _fallback_id
        # 同步更新 step_info 中的 agent_id
        next_step_info["agent_id"] = _fallback_id
    else:
        logger.warning("[R117] 无法解析 card key %s 为 WS ID，跳过自动派活",
                       target_agent_id)
        return False
```

### 🅱️ 新增 `_resolve_card_key_to_ws_id()` 辅助函数

**目标：** 集中 card key → WS ID 的三种解析策略，供 `_auto_dispatch()` 和 `_handle_hash_start()` 复用。

**新增函数位置：** `server/ws_server/main.py`，在 `_build_name_to_ws_map()` 附近

**解析策略（按优先级）：**

| 优先级 | 策略 | 实现 |
|:------:|:-----|:------|
| 1 | display_name → api_keys 桥接 | `_build_name_to_ws_map()` 反向查询 |
| 2 | display_name → `_r72_users` 桥接 | 从 `state._r72_users` 按 name 匹配 agent_id |
| 3 | agent card → direct WS connection 扫描 | 遍历 `state._connections` 匹配 agent card 中所有已知 ID |

```python
def _resolve_card_key_to_ws_id(card_key: str) -> str:
    """多策略解析 card key → WS 连接 ID。"""
    # 策略 1: display_name → api_keys
    card = _ac_mod.get_agent_card(card_key)
    if not card:
        return ""
    display_name = card.get("display_name", "")
    if display_name:
        name_to_ws = _build_name_to_ws_map()
        _id = name_to_ws.get(display_name, "")
        if _id and _id.startswith("ws_"):
            return _id
    # 策略 2: display_name → _r72_users
    if display_name:
        for _aid, _rec in state._r72_users.items():
            if _rec.get("name") == display_name or _rec.get("display_name") == display_name:
                return _aid
    # 策略 3: 遍历 _connections 中所有 ws_xxx，找匹配
    for _aid in state._connections:
        if _aid.startswith("ws_"):
            _info = state._r72_users.get(_aid, {})
            if _info.get("name") == display_name:
                return _aid
    return ""
```

### 🅲 同步更新 `_handle_hash_start()` 桥接代码

**目标：** 在 `_handle_hash_start()` 的 L2947-2950 处，name_to_ws bridge 失败后立即使用 `_resolve_card_key_to_ws_id()` fallback，确保创建 PipelineContext 时 agent_id 就是正确的 WS ID。

**修改位置：** `_handle_hash_start()` L2949 之后、append step 之前

```python
if _real_id:
    agent_id_for_step = _real_id
else:
    # ═══ R117: card key → WS ID fallback ═══
    _fallback = _resolve_card_key_to_ws_id(agents[0])
    if _fallback:
        agent_id_for_step = _fallback
```

### 🅳 `_send_to_agent()` 补充 sent=0 日志

**目标：** 消除静默失败。当 `target_agent_id` 无 WS 连接时输出 warning 日志。

**修改位置：** `_send_to_agent()` L2360-2361，`for` 循环结束后

```python
if sent == 0:
    logger.warning("[R117] _send_to_agent(%s): 无目标连接 (sent=0). _connections keys: %s",
                   target_agent_id[:20],
                   [k for k in list(_connections.keys())[:10]])
```

### 🅴 `_handle_server_relay` 规则 2 增加日志

**目标：** PM 看到步骤推进但不知道是否触发了自动派活时，日志可查。

**修改位置：** `_try_advance_pipeline()` L2452 前后加日志

当前已有日志 L2446-2448，但 `_auto_dispatch` 内部失败时无日志（因 `ensure_future` 异步执行且内部有 try/except）。补充一个日志标记推进结果：

```python
# 在 _auto_dispatch 异步调用后加日志
logger.info("[R117] %s Step %d 已完成 → 尝试自动派活 Step %d",
            round_name, old_step, next_step)
```

---

## 三、通知协议：Step 1 完成 → Step 2 自动派活

### 3.1 PM 完成 Step 1 的格式

PM（小谷）完成 Step 1（编写需求文档 + 推 git）后，发以下消息到 `_inbox:server`：

```
已完成 ✅ R117 Step 1##work_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/R117/WORK_PLAN.md
```

### 3.2 Server 侧的处理链

```
收到 "已完成 ✅ R117 Step 1##work_plan_url=..."
  ↓ _handle_server_relay 规则 2 (L2710)
  ↓ 转发 PM + 自动确认 bot (L2711-2732)
  ↓ _try_advance_pipeline() (L2734)
      ↓ 正则匹配: round=R117, step=1
      ↓ _extract_artifact_kv() 提取 ##key=value
      ↓ 注入 ctx.artifacts
      ↓ mgr.advance_step() → current_step = 2
      ↓ _auto_dispatch(ctx, 2)  ← ⚠️ 此处有 card key bug
          ↓ _resolve_card_key_to_ws_id() 修复
          ↓ _send_to_agent(ws_xxx, payload)
          ↓ bot 收到任务消息
```

### 3.3 PM 确认协议

PM 发送完成消息后，Server 自动回复 `✅ 确认` 到 PM inbox。PM 应：

| 检查项 | 方法 |
|:-------|:------|
| Server 确认收到 | 收到 `✅ 确认` 回复 |
| Step 推进成功 | `##status##R117` → current_step 应为 2 |
| 下一 Step 已派活 | 目标 bot 收到任务消息（或等待 bot 回复 `收到 ✅`） |
| 派活失败 | 若 bot 长时间未回复，检查日志 `[R117] 无法解析 card key` |

---

## 四、修改文件清单

| 文件 | 改动 | 估算行数 |
|:-----|:------|:---------|
| `server/ws_server/main.py` | 新增 `_resolve_card_key_to_ws_id()` | ~30 行 |
| | `_auto_dispatch()` 加 card key fallback | ~15 行 |
| | `_handle_hash_start()` 加 fallback 调用 | ~5 行 |
| | `_send_to_agent()` 加 sent=0 日志 | ~5 行 |
| | `_try_advance_pipeline()` 加推进日志 | ~3 行 |

**全部在 `main.py` 内完成，无需新增文件，无需新建数据模型。**

---

## 五、验收标准

| # | 标准 | 验证方法 |
|:-:|:-----|:---------|
| 1 | `##start##R117test` 创建后，Step 1 agent_id 为 `ws_f26e585f6479`（小谷的真 WS ID） | `##status##R117test` 输出检查 |
| 2 | Step 2~6 的 agent_id 均为 `ws_xxx` 格式（非 card key） | `##status##R117test` 输出检查 |
| 3 | `已完成 ✅ R117test Step 1` 后，current_step 推进至 2 | `##status##R117test` 输出检查 |
| 4 | Step 2 目标 bot（小开）实际收到派活消息 | bot 回复 `收到 ✅` |
| 5 | card key 无对应 WS 连接时日志输出 `[R117] 无法解析 card key` | 检查日志 |
| 6 | `_send_to_agent()` 目标离线时输出 `[R117] sent=0` 日志（不崩溃） | 检查日志 |

---

## 六、不纳入范围

| 条目 | 原因 |
|:-----|:------|
| 前端排序 bug | 已修复（`sortNewestFirst`），属于前端纯 JS 问题，非本轮目标 |
| 协议文档更新 | R116 已交付 v3.0（`docs/inbox-message-protocol.md`），本轮不改 |
| Bot 重新学习 | R116 已派发通知 |
| AutoRouter 代码清理 | 属于后续技术债轮 |
| `_handle_server_relay` 两副本消除 | 属于后续技术债轮 |

---

## 七、不纳入范围

| 条目 | 原因 |
|:-----|:------|
| 前端排序 bug | 已修复（`sortNewestFirst`），属于前端纯 JS 问题，非本轮目标 |
| 协议文档更新 | R116 已交付 v3.0（`docs/inbox-message-protocol.md`），本轮不改 |
| Bot 重新学习 | R116 已派发通知 |
| AutoRouter 代码清理 | 属于后续技术债轮 |
| `_handle_server_relay` 两副本消除 | 属于后续技术债轮 |

--- 

> **拟定者：** 小谷
> **日期：** 2026-07-14
> **状态：** 初稿，待审核
