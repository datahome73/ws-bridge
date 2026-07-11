# R99 技术方案 — Bot 权限等级体系 🔒

> **版本：** v1.0
> **状态：** 📝 初稿
> **作者：** 🏗️ 小开 (arch)
> **日期：** 2026-07-13
> **基于需求文档：** `docs/R99/R99-product-requirements.md` v1.0
> **改动文件：** `server/auth.py`, `server/persistence.py`, `server/handler.py`, `server/agent_card.py`, 系统名统一
> **净增量：** ~+60 行

---

## 1. 核心设计

### 1.1 等级定义

| 等级 | 名称 | 进入条件 | 能力 |
|:----:|:-----|:---------|:-----|
| **L1** | 未注册 | — | 只能走注册流程，不能收发任何消息 |
| **L2** | 已注册 | 完成 R72 注册，获取 api_key | 不能给其他 bot 发消息，也不能收消息 |
| **L3** | 观察员 | L2 + 提交 Agent Card | **能收到**发给自己的消息，但不能主动给其他 bot 发消息 |
| **L4** | 活跃成员 | L3 + 人工/运维提升 | **能收能发** — 全权限 |

### 1.2 等级存储方案

#### 1.2.1 字段定义

`_api_key` 文件（`_api_keys.json`）中每个 agent 记录增加 `level` 字段：

```json
{
  "api_key": "sk_ws_...",
  "display_name": "agent_name",
  "description": "...",
  "created_at": 1234567890.0,
  "expires_at": null,
  "status": "active",
  "level": 2
}
```

#### 1.2.2 初始化值

- **新注册 bot**（`handle_register()` 中 `keys[agent_id]` 创建时）：`"level": 2`
- **已有 bot 无 level 字段**（存量 `_api_keys.json` 未迁移）：默认按 L4 处理（向后兼容）

#### 1.2.3 升级触发器

| 事件 | 旧等级 | 新等级 | 触发位置 | 触发方式 |
|:-----|:------:|:------:|:---------|:---------|
| 注册成功 | — | L2 | `handler.handle_register()` | 写入 `_api_key` 时直接设 level=2 |
| 提交 Agent Card | L2 | L3 | `agent_card.register_from_agent()` | 卡片保存后调用 `set_level(agent_id, 3)` |
| 运维手动 | L3 | L4 | 运维直接修改 `_api_keys.json` | 无代码改动（编辑 JSON 文件） |

---

## 2. 代码改动详述

### 2.1 `server/persistence.py` — 新增 `get_api_key_record()` ~+8 行

现有 `get_api_keys()` 返回完整 `_api_keys` dict。新增一个精确查询函数供 `auth.get_level()` 调用：

```python
# ── R99: 获取单个 api_key 记录 ──
def get_api_key_record(agent_id: str) -> dict | None:
    """返回指定 agent 的 api_key 完整记录，不存在返回 None。"""
    with _lock:
        return _api_keys.get(agent_id)
```

**位置：** 紧接 `set_api_keys()` 之后（约第 128 行后）。

### 2.2 `server/auth.py` — 新增 level 查询 + 迁移兼容 ~+15 行

```python
# ── R99: Level 权限等级 ──────────────────────────────────────────

def get_level(agent_id: str) -> int:
    """返回 agent 的权限等级 (1-4)。

    查询链路: agent_id → persistence.get_api_key_record() → .level
    规则：
      - 未在 _api_key 记录中 → L1（未注册）
      - 记录中无 level 字段 → L4（向后兼容存量 bot）
      - 有 level 字段 → 返回实际值
    """
    record = persistence.get_api_key_record(agent_id)
    if record is None:
        return 1  # L1 — 未注册
    return record.get("level", 4)  # 默认 L4 向后兼容


def set_level(agent_id: str, new_level: int) -> bool:
    """设置 agent 的 level 字段并持久化。

    Args:
        agent_id: 目标 agent
        new_level: 1-4 的新等级

    Returns:
        True  — 更新成功
        False — 该 agent 无 api_key 记录
    """
    keys = persistence.get_api_keys()
    if agent_id not in keys:
        return False
    keys[agent_id]["level"] = new_level
    persistence.set_api_keys(keys)
    persistence.save_api_keys(config.DATA_DIR)
    return True
```

**位置：** 紧接 `get_agent_name()` 之后（约第 117 行后），或放在 `is_approved()` 之前。

> **注意：** `is_approved()` 保持现有逻辑不变 — 只判断 `api_key` 是否存在且有效。`level` 由新的 `get_level()` 和 `handle_broadcast()` 中的检查逻辑使用，不会冲突。

### 2.3 `server/handler.py` — 安全检查插入（位置⑦）~+18 行

#### 2.3.1 消息入口链路

```
handler() (WS 主循环, 第 6126 行)
  └─ msg_type == "message" and agent_id:
       ├─ ① key 活性检查（R86）
       ├─ ② _handle_server_relay() — _inbox:server 中继拦截（R87）
       │    └─ True → continue (消费)
       ├─ ═══ R99 位置⑦ 检查插入 ═══
       │    └─ _inbox:<bot_id> + level<4 → reject + continue
       └─ await handle_broadcast() — 正常路由
```

#### 2.3.2 具体插入代码

**文件：** `server/handler.py`
**位置：** 第 6163 行（`_handle_server_relay` 检查之后），第 6165 行（`handle_broadcast` 之前）

```python
                # ═══ R87: _inbox:server 中继拦截 ═══
                if await _handle_server_relay(ws, agent_id, msg):
                    continue
                # ════════════════════════════════════════

                # ═══ R99: 权限检查 — _inbox:<bot_id> 需要 level>=4 ═══
                _channel = msg.get(p.FIELD_CHANNEL, "")
                if _channel.startswith(p.INBOX_CHANNEL_PREFIX) and _channel != SERVER_INBOX_CHANNEL:
                    _sender_level = auth.get_level(agent_id)
                    if _sender_level < 4:
                        await _send(ws, {
                            "type": "error",
                            "error": f"❌ 无权限：当前等级 L{_sender_level}，需 L4 才能向其他 Bot 发消息。请提交 Agent Card 或联系管理员提升等级。",
                        })
                        logger.info(
                            "[R99] 拒绝: %s (L%d) 试图发消息到 %s",
                            agent_id[:12], _sender_level, _channel,
                        )
                        continue
                # ════════════════════════════════════════════════════

                await handle_broadcast(ws, agent_id, msg)
```

**检查逻辑：**
1. 从 `msg` 提取 `channel` 字段
2. 判断是否以 `_inbox:` 开头且不等于 `_inbox:server`
3. 调用 `auth.get_level(agent_id)` 获取发送者等级
4. `level < 4` → 发送 error 消息给发送者 + `continue`（不路由）
5. `level >= 4` → 放行，继续 `handle_broadcast()`

#### 2.3.3 影响评估

| 场景 | 流量 | 检查结果 | 行为 |
|:-----|:-----|:---------|:-----|
| L4 bot 发 `_inbox:<id>` | 7 在线 bot | level>=4 ✅ 放行 | 零影响 |
| L3 bot 发 `_inbox:<id>` | 无此场景 | ❌ 拒绝 | 正确拦截 |
| L1/L2 bot 发 `_inbox:<id>` | 无此场景 | ❌ 拒绝 | 正确拦截 |
| 任意等级发 `_inbox:server` | ACK/完成 | 非 `<bot_id>` 不触检查 | 零影响 |
| 非 inbox 消息 | 大厅/工作区 | 非 `_inbox:` 前缀不触检查 | 零影响 |

### 2.4 `server/agent_card.py` — L2→L3 自动晋升 ~+5 行

**文件：** `server/agent_card.py`
**位置：** `register_from_agent()` 函数末尾，`save_cards()` 之后（第 381 行后）

```python
    _cards[agent_id] = card
    save_cards()

    # ── R99: Agent Card 提交成功 → L2→L3 自动晋升 ──
    try:
        from . import auth as _auth_mod
        current_level = _auth_mod.get_level(agent_id)
        if current_level == 2:
            _auth_mod.set_level(agent_id, 3)
            logger.info(
                "[R99] 自动晋升: %s L2→L3 (Agent Card 提交)",
                agent_id[:20],
            )
    except Exception:
        logger.warning("[R99] 自动晋升失败 (非致命): %s", agent_id[:20])
    # ──────────────────────────────────────────────

    # Update _ROLE_AGENT_MAP from handler for role-based routing
```

**晋升条件：**
- 当前 `level == 2`（已注册）→ 升到 `level == 3`
- 已经是 L3/L4 的不触发（幂等）
- 未注册的（level==1 或无记录）不触发

### 2.5 `handler.handle_register()` — 新 bot 默认 level=2 ~+2 行

**文件：** `server/handler.py`
**位置：** `handle_register()` 中 `keys[agent_id]` 创建 dict 处（第 282-289 行）

```python
    keys[agent_id] = {
        "api_key": api_key,
        "display_name": display_name,
        "description": msg.get("description", ""),
        "created_at": time.time(),
        "expires_at": None,
        "status": "active",
        "level": 2,  # ── R99: 新注册默认 L2 ──
    }
```

---

## 3. 系统名称统一

### 3.1 现状

| 目标 | 当前值 | 应为 | 位置 |
|:-----|:-------|:-----|:-----|
| 协议标识 | `_inbox:server` | 不变 | 通信协议 MD，不实质显示 |
| 中文显示名 | `"系统"` | ✅ 已统一 | 40 处已正确使用 |
| 中继显示名 | `"系统(中继)"` | → `"系统"` | 3 处 |
| `from_agent` 值 | `"system"` (小写) | → `SYSTEM_AGENT_ID` (`"_system"`) | 4 处 |

### 3.2 需要修复的 7 处

#### 3.2.1 `handler.py` — 4 处 `from_agent="system"` 应为 `SYSTEM_AGENT_ID`

**位置 1：** 第 2739 行 (R69 inbox 任务分配)

```python
# 原：
    from_agent="system", from_name=pm_name,
# 改：
    from_agent=SYSTEM_AGENT_ID, from_name=pm_name,
```

**位置 2-4：** 第 6077-6078、6095-6096、6107-6108 行 (R87 relay)

```python
# 原（3 处）：
    "from_name": "系统(中继)",   # → "系统"
    "from_agent": "system",      # → SYSTEM_AGENT_ID
# 改：
    "from_name": "系统",
    "from_agent": SYSTEM_AGENT_ID,
```

#### 3.2.2 统一总表

| # | 文件 | 行号 | 原值 | 目标值 | 字段 |
|:-:|:-----|:----:|:-----|:-------|:----:|
| 1 | `handler.py` | 2687 | `"system"` (default param) | `SYSTEM_AGENT_ID` | `pm_agent_id` |
| 2 | `handler.py` | 2739 | `"system"` | `SYSTEM_AGENT_ID` | `from_agent` |
| 3 | `handler.py` | 6077 | `"系统(中继)"` | `"系统"` | `from_name` |
| 4 | `handler.py` | 6078 | `"system"` | `SYSTEM_AGENT_ID` | `from_agent` |
| 5 | `handler.py` | 6095 | `"系统(中继)"` | `"系统"` | `from_name` |
| 6 | `handler.py` | 6096 | `"system"` | `SYSTEM_AGENT_ID` | `from_agent` |
| 7 | `handler.py` | 6107 | `"系统(中继)"` | `"系统"` | `from_name` |
| 8 | `handler.py` | 6108 | `"system"` | `SYSTEM_AGENT_ID` | `from_agent` |

> **说明：** `pm_agent_id="system"` (2687) 是函数默认参数。使用 `SYSTEM_AGENT_ID` 常量可确保系统标识一致。Web 端（`templates.py`）JS 中已用 `"系统"` 判断，无需改动。

---

## 4. 迁移 & 兼容性

### 4.1 存量 `_api_keys.json` 处理

已有 bot 的 `_api_key` 记录**不**包含 `level` 字段（新结构才写入）。`auth.get_level()` 中通过 `record.get("level", 4)` 默认返回 L4，保证：

- 现有 7 个在线 bot → level=4（全权限，零影响）✅
- 所有已注册但无 level 字段的 bot → level=4（不影响现有功能）✅

**不进行自动迁移脚本** — 运行时默认足够，且减少部署复杂性。

### 4.2 并发安全

| 操作 | 锁机制 |
|:-----|:-------|
| 注册写 level=2 | `persistence.set_api_keys()` 内部已有 `threading.Lock` |
| Agent Card 晋升写 level=3 | 调用 `auth.set_level()` → `persistence.set_api_keys()` + `save_api_keys()` 加锁 |
| 运维手动改 level=4 | 直接编辑 JSON 文件，`set_api_keys()` 下次写时全量覆盖（不影响运行时缓存） |

---

## 5. 验收清单

| # | 验收项 | 预期结果 |
|:-:|:-------|:---------|
| T-1 | 新注册 bot 自动 level=2 | `_api_keys.json` 中 `"level": 2` |
| T-2 | 提交 Agent Card 后自动升 L3 | `auth.get_level()` 返回 3 |
| T-3 | L3 bot 发 `_inbox:<bot_id>` | ❌ `error` 消息，消息不路由 |
| T-4 | L4 bot 发 `_inbox:<bot_id>` | ✅ 正常转发 |
| T-5 | 任意等级发 `_inbox:server` | ✅ 全部放行 |
| T-6 | 在线 7 bot 不受影响 | 行为完全不变（默认 L4） |
| T-7 | 系统名统一为 `"系统"` | 无 `"系统(中继)"`、`"system"` 残留 |
| T-8 | 旧 `_api_key` 无 level 字段 | 自动兼容为 L4 |

---

## 6. 改动文件汇总

| 文件 | 行数 | 改动内容 |
|:-----|:----:|:---------|
| `server/persistence.py` | **+8** | 新增 `get_api_key_record()` |
| `server/auth.py` | **+15** | 新增 `get_level()`, `set_level()` |
| `server/handler.py` handler() | **+18** | 位置⑦ level 检查 |
| `server/handler.py` handle_register() | **+2** | `"level": 2` 初始化 |
| `server/agent_card.py` | **+8** | Agent Card 提交后 L2→L3 晋升 |
| `server/handler.py` 系统名修复 | **~7** | 4 处 `"system"` → `SYSTEM_AGENT_ID`, 3 处 `"系统(中继)"` → `"系统"` |
| **合计** | **~+58** | |

---

*本文档由 🏗️ 小开编写，待 Step 3 💻 编码实现。*
