# R117 自动派活修复轮 — 技术方案

> **轮次：** R117
> **类型：** 代码修复轮
> **架构师：** 小开
> **基线：** R116（全自动就绪已闭环，7/7 ALL GREEN）
> **参考文档：** [R117 需求文档](./R117-product-requirements.md)，[WORK_PLAN](./WORK_PLAN.md)

---

## 一、问题重申

### 1.1 断流现象

| 步骤 | 结果 | 说明 |
|:-----|:------|:------|
| `##start##R116` | ✅ 管线创建，Step 1 派活到小谷 | `_handle_hash_start()` 正常 |
| `已完成 ✅ R116 Step 1##...` | ✅ Step 推进至 2 | `_try_advance_pipeline()` 成功 |
| `##status##R116` | ✅ current_step = 2 | 推进成功 |
| Step 2 自动派活到小开 | ❌ **小开未收到消息** | `_auto_dispatch()` 发送静默失败 |
| 手动 `_inbox:ws_3f7cdd736c1c` | ✅ 小开正常收到 | bot 在线，寻址问题 |

### 1.2 根因链路（验证于 main.py）

```
step_info.agent_id = "arch-bot"    ← card key（非 WS 连接 ID）
     ↓
_auto_dispatch() → target_agent_id = next_step_info["agent_id"]
     ↓
_send_to_agent("arch-bot", payload)
     ↓
_connections.get("arch-bot")       ← None（_connections 存 ws_xxx）
     ↓
sent = 0                           ← 消息静默丢失（except pass 吞掉）
```

### 1.3 代码证据

#### 桥接失败点 ① — `_handle_hash_start()` L2947-2950

```python
if card:
    _real_id = name_to_ws.get(card.get("display_name", ""))
    if _real_id:
        agent_id_for_step = _real_id  # 桥接成功
    # else: agent_id_for_step 保持 card key ("arch-bot") ← 桥接失败
```

`_build_name_to_ws_map()` 只从 `persistence.get_api_keys()` 构建映射。并非所有 bot 都在 api_keys 中有 entry（或 display_name 不精确匹配），导致 bridge 失败时 `agent_id_for_step` 残留 card key。

#### 发送失败点 ② — `_auto_dispatch()` L2551

```python
target_agent_id = next_step_info["agent_id"]  # "arch-bot" — 不校验格式
```

#### 静默丢失点 ③ — `_send_to_agent()` L2352-2360

```python
for conn in list(_connections.get(target_agent_id, set())):  # _connections 无 "arch-bot"
    try:
        ...
    except Exception:
        pass  # ← sent=0，无任何日志
```

---

## 二、修改方案总览

**全部修改集中在 `server/ws_server/main.py`，不新增文件、不新增数据模型。**

| # | 位置 | 行号 | 改动类型 |
|:-:|:------|:----:|:---------|
| **①** | `_auto_dispatch()` | L2551 后 | card key → WS ID fallback |
| **②** | 新增 `_resolve_card_key_to_ws_id()` | `_build_name_to_ws_map()` 之后 | 多策略 fallback 函数 |
| **③** | `_handle_hash_start()` | L2949 else 分支 | 创建时 fallback |
| **④** | `_send_to_agent()` | L2360 后 | sent=0 warning 日志 |
| **⑤** | `_try_advance_pipeline()` | L2452 前 | 推进日志 |

---

## 三、详细设计

### 修改 ① — `_resolve_card_key_to_ws_id()`（新增函数）

**插入位置：** `_build_name_to_ws_map()` (L2823) 之后、`_build_default_templates()` (L2826) 之前。

**函数签名：**

```python
def _resolve_card_key_to_ws_id(card_key: str) -> str:
    """多策略解析 card key → WS 连接 ID。

    三种策略按优先级依次尝试：
    1. display_name → persistence.get_api_keys() 反向查询
    2. display_name → state._r72_users name 匹配
    3. _connections 遍历 + _r72_users name 匹配
    """
```

**策略树：**

```
输入: card_key = "arch-bot"
   │
   ├─ ac_mod.get_agent_card(card_key) → 获取 display_name
   │
   ├─ [策略1] name_to_ws = _build_name_to_ws_map()
   │   └─ name_to_ws.get(display_name) → "ws_3f7cdd736c1c" ✅ 命中返回
   │
   ├─ [策略2] state._r72_users 遍历
   │   └─ _rec["name"] == display_name → aid 命中返回
   │
   ├─ [策略3] _connections 中 ws_xxx 遍历
   │   └─ state._r72_users.get(aid)["name"] == display_name → aid 命中返回
   │
   └─ 全部未命中 → 返回 ""
```

**详细实现：**

```python
def _resolve_card_key_to_ws_id(card_key: str) -> str:
    """多策略解析 card key → WS 连接 ID。

    优先级:
    1. display_name → api_keys (persistence.get_api_keys())
    2. display_name → state._r72_users name 匹配
    3. _connections + _r72_users name 交叉匹配
    """
    card = ac_mod.get_agent_card(card_key)
    if not card:
        return ""
    display_name = card.get("display_name", "")

    # 策略 1: display_name → api_keys
    if display_name:
        name_to_ws = _build_name_to_ws_map()
        _id = name_to_ws.get(display_name, "")
        if _id and _id.startswith("ws_"):
            return _id

    # 策略 2: display_name → state._r72_users
    if display_name:
        for _aid, _rec in state._r72_users.items():
            if _rec.get("name", "") == display_name:
                return _aid

    # 策略 3: _connections 中 ws_xxx → _r72_users name 匹配
    if display_name:
        for _aid in list(_connections.keys()):
            if _aid.startswith("ws_"):
                _info = state._r72_users.get(_aid, {})
                if _info.get("name", "") == display_name:
                    return _aid

    return ""
```

**设计考量：**
- 使用 `ac_mod`（module-level import，L18），无需额外 import
- `_connections` 和 `state._r72_users` 均为 module-level 可访问
- 三次策略全覆盖：api_keys 精确匹配 → R72 注册表 → 运行时连接扫描

---

### 修改 ② — `_auto_dispatch()` 加 card key 检查

**位置：** L2551 `target_agent_id = next_step_info["agent_id"]` **之后**，L2552 `content = _render_template(...)` **之前**。

```python
    target_agent_id = next_step_info["agent_id"]

    # ═══ R117 fix: card key → WS ID fallback ═══
    if not target_agent_id.startswith("ws_"):
        _fallback_id = _resolve_card_key_to_ws_id(target_agent_id)
        if _fallback_id:
            logger.info("[R117] card key %s → WS ID %s (fallback)",
                        target_agent_id, _fallback_id)
            target_agent_id = _fallback_id
            next_step_info["agent_id"] = _fallback_id
        else:
            logger.warning("[R117] 无法解析 card key %s 为 WS ID，跳过自动派活 step %d of %s",
                           target_agent_id, step_num, ctx.round_name)
            return False
```

**注意点：**
- `next_step_info["agent_id"]` 的修改只影响内存中的 `PipelineContext.steps`，不持久化回 DB（后续 `mgr.save()` 可能覆盖，但当前 flow 中 `_auto_dispatch` 返回后无人使用此值）
- `return False` 让 `auto_dispatch` 不发送，调用方 `_try_advance_pipeline()` 不会因异步的 `ensure_future` 返回值受影响

---

### 修改 ③ — `_handle_hash_start()` 补充 fallback

**位置：** L2949 `if _real_id:` 的 **else 分支**，在 append step 之前。

当前代码（L2947-2950）：
```python
if card:
    _real_id = name_to_ws.get(card.get("display_name", ""))
    if _real_id:
        agent_id_for_step = _real_id
```

修改后：
```python
if card:
    _real_id = name_to_ws.get(card.get("display_name", ""))
    if _real_id:
        agent_id_for_step = _real_id
    else:
        # ═══ R117 fix: card key → WS ID fallback ═══
        _fallback = _resolve_card_key_to_ws_id(agents[0])
        if _fallback:
            agent_id_for_step = _fallback
            logger.info("[R117] ##start fallback: %s → %s",
                        agents[0], _fallback)
```

**设计考量：**
- 这里只改写 `agent_id_for_step`，确保 `steps_list` 中 step 的 `agent_id` 从创建时就是正确的 WS ID
- 不修改 `name_to_ws` 或 `card` 对象，纯局部变量

---

### 修改 ④ — `_send_to_agent()` 加 sent=0 日志

**位置：** L2360 `pass` **之后**、L2361 注释之前。

当前代码（L2359-2360）：
```python
        except Exception:
            pass
```

修改后：
```python
        except Exception:
            pass
    if sent == 0:
        logger.warning("[R117] _send_to_agent(%s): 无目标连接 (sent=0)",
                       target_agent_id[:20])
```

**注意点：**
- agent_id 截断前 20 字符，避免日志泄露
- 日志级别为 `warning`，prometheus 可告警

---

### 修改 ⑤ — `_try_advance_pipeline()` 加推进日志

**位置：** L2452 之前。

当前代码（L2449-2452）：
```python
            # ── R107: 自动派活下一步（受 AUTO_DISPATCH_ENABLED 控制）──
            next_step = old_step + 1
            if next_step <= ctx.total_steps:
                asyncio.ensure_future(_auto_dispatch(ctx, next_step))
```

修改后：
```python
            # ── R107: 自动派活下一步（受 AUTO_DISPATCH_ENABLED 控制）──
            next_step = old_step + 1
            if next_step <= ctx.total_steps:
                logger.info(
                    "[R117] %s Step %d 已完成，尝试自动派活 Step %d",
                    round_name, old_step, next_step,
                )
                asyncio.ensure_future(_auto_dispatch(ctx, next_step))
```

---

## 四、数据流图

```
PM 发送 "已完成 ✅ R117 Step 1##..."
  │
  ▼
_handle_server_relay() 规则 2 (L2710)
  │
  ├─ 转发 PM
  ├─ 自动确认 bot
  │
  ▼
_try_advance_pipeline() (L2734)
  │  ┌─ 正则匹配 round=R117, step=1
  │  ├─ _extract_artifact_kv() → artifacts
  │  ├─ mgr.advance_step() → current_step=2
  │  └─ ✅ [R117] R117 Step 1 已完成，尝试自动派活 Step 2
  │
  ▼
_auto_dispatch(ctx, step_num=2)
  │
  ├─ next_step_info["agent_id"] = "arch-bot"          (card key)
  │
  ├─ ═══ R117 fix ═══
  │  └─ "arch-bot" 不以 ws_ 开头 → _resolve_card_key_to_ws_id("arch-bot")
  │       ├─ 策略 1: name_to_ws.get(display_name) → "ws_3f7cdd736c1c" ✅
  │       └─ target_agent_id ← "ws_3f7cdd736c1c"
  │
  ├─ content = _render_template()
  ├─ payload = {..., "to_agent": "ws_3f7cdd736c1c"}
  │
  ▼
_send_to_agent("ws_3f7cdd736c1c", payload)
  │
  └─ _connections.get("ws_3f7cdd736c1c") → {conn}     ✅ 命中
       └─ await conn.send_str(payload_json)            ✅ 小开收到
```

---

## 五、验收标准

| # | 标准 | 验证方法 | 预期结果 |
|:-:|:-----|:---------|:---------|
| V-1 | `_resolve_card_key_to_ws_id("arch-bot")` | 函数调用 | `"ws_3f7cdd736c1c"` |
| V-2 | 未知 card key | `_resolve_card_key_to_ws_id("unknown-bot")` | `""`（空字符串） |
| V-3 | `##start##R117test` 创建后 agent_id 均为 ws_xxx | `##status##R117test` | 所有 step 的 agent_id 为 ws_ 前缀 |
| V-4 | Step 1 → Step 2 自动派活 | `已完成 ✅ R117test Step 1` 发 `_inbox:server` | `[R117] R117test Step 1 已完成` 日志 |
| V-5 | 目标 bot 实际收到 | 小开回复 `收到 ✅` | 消息送达 |
| V-6 | card key 无对应 WS 连接时 | 日志检查 | `[R117] 无法解析 card key` warning |
| V-7 | sent=0 日志（目标离线） | 关闭目标 bot 后触发自动派活 | `[R117] _send_to_agent(...): 无目标连接` warning |
| V-8 | 已有管线不受影响 | `##status##R116` | 正常返回管线状态 |

---

## 六、副作用分析

| 修改 | 副作用 | 风险等级 |
|:-----|:-------|:---------|
| `_auto_dispatch()` 修改 `next_step_info["agent_id"]` | 内存中 PipelineContext 的 agent_id 被改写为 ws_xxx；但当前 flow 中 `_auto_dispatch` 是末端调用，后续无代码依赖此字段 | 🟢 低 |
| `_handle_hash_start()` 中 `agent_id_for_step` 改写 | 仅在 `steps_list.append()` 之前影响此局部变量 | 🟢 低 |
| `_send_to_agent()` sent=0 日志 | 纯日志，无逻辑变更 | 🟢 低 |
| `_resolve_card_key_to_ws_id()` 中 `_build_name_to_ws_map()` 调用 | 每次 fallback 触发时构建映射，约 O(n) 遍历 API keys。正常管线 N≤10，开销可忽略 | 🟢 低 |

---

## 七、不纳入范围

| 条目 | 原因 |
|:-----|:------|
| 协议文档更新 | R116 已交付 v3.0（`docs/inbox-message-protocol.md`），本轮不改 |
| Bot 重新学习 | R116 已派发通知 |
| AutoRouter 代码清理 | 属于后续技术债轮 |
| `_handle_server_relay` 两副本消除 | 属于后续技术债轮 |

---

> **拟定者：** 小开
> **日期：** 2026-07-15
> **状态：** 定稿
