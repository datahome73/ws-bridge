# R117 工作计划

> **交付方式：** Step 1 审核通过后，按序推进各 Step。
> **各 Step 完成后：** 推 git dev → 回复 `已完成 ✅ R117 Step {N}##key=value` 到 `_inbox:server`

---

## Step 1 — 需求文档审核（PM：小谷）— ✅ 已完成

**任务：** 审核 R117 需求文档，确认后推 git，标记 WORK_PLAN 已审核。

**产出：**
- ✅ 需求文档已审核通过
- ✅ WORK_PLAN 已审核推 git

**完成消息：**
```
已完成 ✅ R117 Step 1##work_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/R117/WORK_PLAN.md
```

---

## Step 2 — 技术方案（架构师：小开）

**任务：** 设计 R117 修复方案。

**具体内容：**

### 需求范围

修复 `_auto_dispatch()` 中 card key → WS ID 桥接失败导致的消息静默丢失问题。

### 代码插入点

| # | 位置 | 行号（origin/dev） | 改动 |
|:-:|:-----|:------------------:|:-----|
| 1 | `_auto_dispatch()` | ~L2551 | 获取 `target_agent_id` 后检查 `ws_` 前缀，非 `ws_` 时调用 fallback |
| 2 | 新增 `_resolve_card_key_to_ws_id()` | 靠近 `_build_name_to_ws_map()` | 多策略解析：api_keys → `_r72_users` → `_connections` 扫描 |
| 3 | `_handle_hash_start()` | ~L2949 | name_to_ws bridge 失败后调用 fallback |
| 4 | `_send_to_agent()` | ~L2360 | sent=0 时输出 warning 日志 |
| 5 | `_try_advance_pipeline()` | ~L2452 | 增加推进 + 派活结果日志 |

### 三种 fallback 策略优先级

| 优先级 | 策略 | 说明 |
|:------:|:-----|:------|
| 1 | display_name → api_keys | `_build_name_to_ws_map()` 反向查询 |
| 2 | display_name → `_r72_users` | 从 `state._r72_users` 按 name 匹配 |
| 3 | `_connections` 扫描 | 遍历 `_connections` 中所有 `ws_xxx`，匹配 `_r72_users` 中的 name |

### 验收标准

- `_resolve_card_key_to_ws_id("arch-bot")` → `"ws_3f7cdd736c1c"` ✅
- fallback 全部失败时返回 `""`，`_auto_dispatch` 输出 warning 并 return False
- sent=0 日志不再被 `except Exception: pass` 吞掉

**参考文档：**
- `docs/R117/R117-product-requirements.md` §二·修复方案
- `references/r116-auto-dispatch-agent-id-bridge.md`

---

## Step 3 — 编码实现（开发工程师：爱泰）

**任务：** 按技术方案实现 5 处代码修改。

### 修改 1：新增 `_resolve_card_key_to_ws_id()`

在 `_build_name_to_ws_map()` 定义之后（~L2823）插入：

```python
def _resolve_card_key_to_ws_id(card_key: str) -> str:
    """多策略解析 card key → WS 连接 ID。
    
    优先级:
    1. display_name → api_keys (persistence.get_api_keys())
    2. display_name → _r72_users
    3. _connections 遍历 + _r72_users name 匹配
    """
    from . import agent_card as _ac_mod
    
    card = _ac_mod.get_agent_card(card_key)
    if not card:
        return ""
    display_name = card.get("display_name", "")
    
    # 策略 1: display_name → api_keys
    if display_name:
        name_to_ws = _build_name_to_ws_map()
        _id = name_to_ws.get(display_name, "")
        if _id and _id.startswith("ws_"):
            return _id
    
    # 策略 2: display_name → _r72_users
    if display_name:
        for _aid, _rec in state._r72_users.items():
            _rec_name = _rec.get("name", "")
            if _rec_name == display_name:
                return _aid
    
    # 策略 3: 遍历 _connections 中 ws_xxx，找匹配
    if display_name:
        for _aid in state._connections:
            if _aid.startswith("ws_"):
                _info = state._r72_users.get(_aid, {})
                if _info.get("name") == display_name:
                    return _aid
    
    return ""
```

### 修改 2：`_auto_dispatch()` 加 card key 检查

在 L2551 `target_agent_id = next_step_info["agent_id"]` 后插入：

```python
    # ═══ R117: card key → WS ID fallback ═══
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

### 修改 3：`_handle_hash_start()` 补充 fallback

在 L2949 `if _real_id:` 的 else 分支后插入：

```python
        # ═══ R117: card key → WS ID fallback ═══
        if not _real_id:
            _fallback = _resolve_card_key_to_ws_id(agents[0])
            if _fallback:
                agent_id_for_step = _fallback
                logger.info("[R117] ##start fallback: %s → %s",
                            agents[0], _fallback)
```

### 修改 4：`_send_to_agent()` 加 sent=0 日志

在 L2360 `pass` 后插入：

```python
    if sent == 0:
        logger.warning("[R117] _send_to_agent(%s): 无目标连接 (sent=0)",
                       target_agent_id[:20])
```

### 修改 5：`_try_advance_pipeline()` 加推进日志

在 L2449（`# ── R107: 自动派活下一步` 之前）插入：

```python
            logger.info(
                "[R117] %s Step %d 已完成，尝试自动派活 Step %d",
                round_name, old_step, next_step,
            )
```

### 提交格式

```
feat(R117): fix auto_dispatch card key → WS ID bridge

- _resolve_card_key_to_ws_id(): 3 策略 fallback
- _auto_dispatch(): card key 检查 + fallback
- _handle_hash_start(): 补充创建时 fallback
- _send_to_agent(): sent=0 warning 日志
- _try_advance_pipeline(): 推进日志
```

---

## Step 4 — 代码审查（审查工程师：小周）

**任务：** 审查 Step 3 的 5 处修改。

**重点关注：**
1. `_resolve_card_key_to_ws_id()` 三种策略是否完整覆盖所有情况
2. `_auto_dispatch()` 中修改 `next_step_info["agent_id"]` 是否有副作用（持久化问题）
3. sent=0 日志是否泄漏敏感信息（agent_id 截断 20 位 → ✅）
4. `_try_advance_pipeline()` 中 `ensure_future` + callback 的异常处理是否正确

---

## Step 5 — 测试验证（测试工程师：泰虾）

**任务：** 验证 R117 修复在 dev 环境的工作行为。

### 测试计划

| # | 用例 | 验证方法 | 预期 |
|:-:|:-----|:---------|:------|
| 1 | card key → WS ID 解析 | 调用 `_resolve_card_key_to_ws_id("arch-bot")` | `"ws_3f7cdd736c1c"` |
| 2 | 未知 card key 解析 | 调用 `_resolve_card_key_to_ws_id("unknown-bot")` | `""`（空字符串） |
| 3 | `##start##R117test` | 创建测试管线 | `##status` 查看所有 step agent_id 为 `ws_xxx` |
| 4 | Step 1 → Step 2 自动派活 | `已完成 ✅ R117test Step 1` → 发 `_inbox:server` | 小开收到任务消息 |
| 5 | sent=0 日志 | 关闭目标 bot 后发起自动派活 | 日志输出 `[R117] sent=0` |
| 6 | 已有管线不受影响 | `##status##R116` 正常 | 正常返回 |

---

## Step 6 — 合并部署归档（Ops：小爱）

**任务：** 合并 dev→main，部署到生产环境。

### 部署参数

- **image_tag:** `ws-bridge:r117`
- **health_check:** `##status##R117test` 确认 Step 2 agent_id 为 WS ID
- **测试命令：** `##start##R117test` → `##status##R117test` → `已完成 ✅ R117test Step 1` → 验证小开收到
