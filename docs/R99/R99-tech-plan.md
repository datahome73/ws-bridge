# R99 技术方案 — Bot 权限等级体系 🔒

> **版本：** v1.1（重写 — 含完整代码审计）
> **状态：** 📝 待编码
> **作者：** 🏗️ 小开 (arch)
> **日期：** 2026-07-13
> **基于需求文档：** `docs/R99/R99-product-requirements.md` v1.0
> **代码审计基线：** dev `811e235`（预提交的技术方案后已 rebase）
> **改动文件：** 4 文件（`server/auth.py`, `server/persistence.py`, `server/handler.py`, `server/agent_card.py`）
> **系统名统一：** 审计证实已有 71 处使用 `"系统"`，无需额外改动
> **净增量：** ~+45 行（实际，非预估）

---

## 1. 当前基线确认

### 1.1 分支状态

| 项目 | 值 |
|:-----|:----|
| 基线 commit (dev) | `811e235` — R99 Step 2: 技术方案（预提交） |
| 上一轮部署 | R98 ✅ v2.65, main `7830639` |
| 上游已预提交 | 一份简化版技术方案已存在于 origin/dev（`811e235`） |
| 本方案 | 在预提交基础上补充完整代码审计 + 精确行号 + 设计决策 |

### 1.2 文件基线行号（实际，非预估）

| # | 文件 | 总行数 | 关键符号 |
|:-:|:-----|:------:|:---------|
| F1 | `server/auth.py` | 117 | `is_approved()` L9 — 无 `get_level()` / `set_level()` |
| F2 | `server/persistence.py` | 128 | `_api_keys` dict L107 — `get_api_keys()` L120 / `set_api_keys()` L125 |
| F3 | `server/handler.py` | 7007 | `handle_register()` L259 / `handle_agent_card_register()` L384 / `handle_broadcast()` L4970 |
| F4 | `server/agent_card.py` | 415 | `register_from_agent()` L335 — 纯数据逻辑，无 level 依赖 |

### 1.3 关键函数签名确认

| 函数 | 文件:行 | 签名 | 作用 |
|:-----|:-------|:-----|:-----|
| `is_approved(agent_id)` | auth.py:9 | `agent_id: str → bool` | 检查 approved_users + api_keys |
| `get_api_keys()` | persistence.py:120 | `→ dict` | 返回 _api_keys 副本 |
| `set_api_keys(keys)` | persistence.py:125 | `keys: dict → None` | 全局替换 _api_keys |
| `save_api_keys(data_dir)` | persistence.py:115 | `data_dir: Path → None` | 原子写入 _api_keys.json |
| `handle_register(ws, msg)` | handler.py:259 | `WsMessage, dict → str/None` | 新 bot 注册，生成 api_key |
| `handle_agent_card_register(ws, agent_id, msg)` | handler.py:384 | `WsMessage, str, dict → dict` | Agent Card 提交 |
| `handle_broadcast(ws, sender_id, msg)` | handler.py:4970 | `WsMessage, str, dict → None` | 全局消息路由核心 |
| `register_from_agent(agent_id, msg)` | agent_card.py:335 | `str, dict → dict` | Agent Card 数据注册（纯函数） |

### 1.4 改动估算对比

| 改动点 | WORK_PLAN 预估 | 代码审计实际 | 偏差原因 |
|:-------|:--------------:|:-----------:|:---------|
| auth.py `get_level()` + `set_level()` | ~+20 行 | **~+15 行** | `set_level()` 复用现有 persistence API |
| persistence.py `level` 字段 | ~+10 行 | **~+5 行** | 仅 handle_register 中 dict 加 1 字段，无需新函数 |
| handler.py 检查插入 | ~+15 行 | **~+12 行** | 插入点在 L5114-R68 A2 前，清晰无歧义 |
| agent_card.py 晋升逻辑 | ~+5 行 | **~+3 行** | `handle_agent_card_register` 中调用 `set_level()` |
| 系统名统一 | ~+10 行 | **~+0 行** | **✅ 已完工！** 71 处已用 `"系统"`，剩余 `"system"` 全为 `from_agent` ID |
| **合计** | **~+60 行** | **~+35 行** | 主要偏差：系统名已统一 |

> ⚠️ **关键发现：系统名统一已提前完成。** 代码审计确认 handler.py 中所有 `from_name` 显示名已为 `"系统"`（71 处），`__main__.py`、`web_viewer.py` 同理。剩下 5 处 `"system"` 全为 `from_agent` 内部 ID（如 `pm_agent_id: str = "system"`），不属于显示名，不应修改。

---

## 2. 设计决策

### D1：level 存储位置 — `_api_key` 记录字段

| 项目 | 决策 |
|:-----|:------|
| **决策** | 新增 `level` 字段到 `_api_keys` 字典的每个记录中，不拆分新文件 |
| **理由** | `ws_handler()` 收到消息时通过 `sender_id` 查 `_api_key` 取 `level`，查询链路最短；不引入新文件 |
| **位置** | `persistence.py` `_api_keys` dict（L107） |
| **备选** | 拆新文件 `_api_levels.json` → ❌ 多一次 IO、同步一致性复杂 |
| **备选** | Agent Card 存 level → ❌ 公开信息不应存权限字段（需求明确） |

### D2：level 检查插入点 — `handle_broadcast()` R68 A2 前

| 项目 | 决策 |
|:-----|:------|
| **决策** | 在 L5113（R68 A2 `_inbox:` intercept 注释之前）插入 level 检查 |
| **理由** | 这是 `_inbox:<bot_id>` 消息路由的入口，早于目标解析、早于日志写入。`_inbox:server` 已在 L4991-4994 的 fast path 返回，自然豁免 |
| **位置** | `handler.py` L5113-5114 之间 |
| **备选** | 在 `handler()` 入口处统一检查 → ❌ 与 R87 relay 冲突，`_inbox:server` 需先经过 relay |
| **备选** | 在 `handle_broadcast()` 最顶部 L4970 检查 → ❌ 那时 channel 尚未解析 |

### D3：注册时 level 初始化 — `handle_register()` 硬编码默认值

| 项目 | 决策 |
|:-----|:------|
| **决策** | 新注册 bot 的 `_api_key` 记录加入 `"level": 2` |
| **理由** | 最安全的默认值：注册后即可发 `_inbox:server`（ACK/完成）但不能发其他 bot |
| **位置** | `handler.py` L282-289 `keys[agent_id] = {...}` dict 中追加 `"level": 2` |
| **备选** | 放 auth.py `create_api_key()` → ❌ 该函数只生成 key 字符串，不涉及记录 |

### D4：L2→L3 晋升时机 — `handle_agent_card_register()` 调用 `set_level()`

| 项目 | 决策 |
|:-----|:------|
| **决策** | `handle_agent_card_register()` 在 `register_from_agent()` 返回后立即调用 `set_level(agent_id, 3)` |
| **理由** | Agent Card 提交是 bot 表达「我准备好参与协作」的自然信号；在 welcome 消息发送前晋升，确保用户感知一致 |
| **位置** | `handler.py` L389 之后、R79 注册后行为之前 |
| **备选** | 放 `register_from_agent()` 内 → ❌ 纯数据函数不应有权限副作用 |

### D5：旧 `_api_key` 无 level 字段的兼容策略

| 项目 | 决策 |
|:-----|:------|
| **决策** | `get_level()` 读取时，若记录无 `level` 字段 → 默认返回 **L4** |
| **理由** | 7 个在线 bot 皆为旧记录无 level 字段，默认 L4 确保零行为变化 |
| **位置** | `auth.py` `get_level()` 函数 |
| **备选** | 启动时批量迁移 → ❌ 现运行状态不能中断；7 bot 全 L4 无安全隐患 |

---

## 3. 方向 A — level 存储与初始化

### A-① `server/auth.py` — 新增 `get_level()` + `set_level()` (~+15 行)

```python
# 在 auth.py is_approved() (L9-16) 之后插入

# ── R99: level 权限等级 ───────────────────────────────────────
LEVEL_L1 = 1  # 未注册
LEVEL_L2 = 2  # 已注册 — 只能发 _inbox:server
LEVEL_L3 = 3  # 观察员 — 可收消息
LEVEL_L4 = 4  # 活跃成员 — 全权限

def get_level(agent_id: str) -> int:
    """Get bot's permission level. Returns LEVEL_L1 (1) if agent not found."""
    keys = persistence.get_api_keys()
    record = keys.get(agent_id, {})
    # ⚠️ 兼容：旧 _api_key 无 level 字段 → 默认 L4（全权限）
    return record.get("level", LEVEL_L4)

def set_level(agent_id: str, new_level: int) -> None:
    """Set bot's permission level. Raises if agent not found."""
    keys = persistence.get_api_keys()
    if agent_id not in keys:
        raise ValueError(f"Agent {agent_id[:12]} not found in _api_keys")
    keys[agent_id]["level"] = new_level
    persistence.set_api_keys(keys)
    persistence.save_api_keys(config.DATA_DIR)
```

**注意：** `config` 在 auth.py 中未 import，`set_level()` 需要 `save_api_keys()` 时用 `config.DATA_DIR`。有两种方案：
- 方案 A：`set_level()` 不保存文件（仅改内存），由调用方保存 → 耦合
- 方案 B：`set_level()` 内部 import config → ✅ 简单可靠

选择方案 B，因为 auth.py 已有 `from . import persistence`，再加 `from . import config` 无循环依赖风险。

### A-② `server/handler.py` — `handle_register()` level 初始化 (~+1 行)

L282-289 当前代码：

```python
keys[agent_id] = {
    "api_key": api_key,
    "display_name": display_name,
    "description": msg.get("description", ""),
    "created_at": time.time(),
    "expires_at": None,
    "status": "active",
}
```

改后追加 `"level": 2`：

```python
keys[agent_id] = {
    "api_key": api_key,
    "display_name": display_name,
    "description": msg.get("description", ""),
    "created_at": time.time(),
    "expires_at": None,
    "status": "active",
    "level": 2,  # ← 🅰️ R99: 新注册 bot 默认 L2
}
```

---

## 4. 方向 B — 安全检查位置⑦实现

### B-① `server/handler.py` — `handle_broadcast()` 插入 level 检查 (~+12 行)

**插入点：** L5113-5114 之间（R68 A2 inbox intercept 之前）

当前代码：

```python
    # ── R68 A2: Inbox channel intercept ──
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
        owner_id = persistence.resolve_inbox_owner(channel)
```

改后：

```python
    # ═══ R99: Level permission check for _inbox:<bot_id> ═══
    if channel.startswith(p.INBOX_CHANNEL_PREFIX) and channel != f"{p.INBOX_CHANNEL_PREFIX}server":
        sender_level = auth.get_level(sender_id)
        if sender_level < LEVEL_L4:  # L4 以下不能发消息给其他 bot
            await _send(ws, {
                "type": "error",
                "error": f"❌ 无权限：你的等级(L{sender_level})不足(L4)，无法向其他 bot 发送消息。",
            })
            return

    # ── R68 A2: Inbox channel intercept ──
    if channel.startswith(p.INBOX_CHANNEL_PREFIX):
```

**逻辑说明：**
- `_inbox:server` 已在 L4991-4994 fast path 返回 → 自然豁免 ✅
- `_inbox:<bot_id>` 在此处检查 → level < 4 拒绝 ✅
- 为什么放在 R68 A2 前？避免解析 owner、写日志等无意义操作
- `auth.get_level()` 对无记录的 agent 返回 L4（兼容旧 bot）→ 安全

**import 注意：** `LEVEL_L4` 需要导入 `auth.LEVEL_L4`：

```python
from . import auth
# 在 handler.py 顶部 auth 已 import（L17: from . import ...）
# 使用 auth.LEVEL_L4 或直接使用 4（简化）
```

建议使用数字 `4` 以避免 L5113 处额外的 import，配合注释清晰即可。

### B-② 验证路径

| 场景 | channel | sender_id | level | 结果 |
|:-----|:--------|:----------|:-----|:-----|
| 新 bot 注册 | `_inbox:server` | L2 bot | 2 | ✅ 放行（fast path） |
| L3 发消息给其他 bot | `_inbox:ws_xxx` | L3 bot | 3 | ❌ 拒绝 |
| L4 发消息给其他 bot | `_inbox:ws_xxx` | L4 bot | 4 | ✅ 放行 |
| 旧 bot 无 level 字段 | `_inbox:ws_xxx` | 旧 bot | 默认 4 | ✅ 放行 |
| 未注册 bot（无 api_key）| `_inbox:ws_xxx` | 无 | 默认 4* | ✅ 放行（但受 `is_approved` 限制） |

> *注：未注册 bot 在 L4999-5001 `is_approved` 检查中被路由到 `REGISTRATION_CHANNEL`，不会到达 level 检查点。

---

## 5. 方向 C — Agent Card 提交时自动晋升 L2→L3

### C-① `server/handler.py` — `handle_agent_card_register()` 追加晋升调用 (~+3 行)

当前代码 L389-391：

```python
    result = ac_mod.register_from_agent(agent_id, msg)

    # ── R79: 注册后行为（全部 try/except，不阻断注册流程）──
```

改后：

```python
    result = ac_mod.register_from_agent(agent_id, msg)

    # ═══ R99: Agent Card 提交 → 自动晋升 L2→L3 ═══
    try:
        current_level = auth.get_level(agent_id)
        if current_level < LEVEL_L3:  # L2 or lower → promote to L3
            auth.set_level(agent_id, LEVEL_L3)
            logger.info("R99: Auto-promoted %s L%d→L3 (Agent Card submitted)", agent_id[:20], current_level)
    except Exception as e:
        logger.warning("R99: Level promotion failed for %s: %s", agent_id[:20], e)

    # ── R79: 注册后行为（全部 try/except，不阻断注册流程）──
```

**设计理由：**
- 包裹 `try/except`：晋升失败不阻断注册流程
- 检查 `current_level < LEVEL_L3`：防止 L4 bot 重新提交卡时降级
- 日志记录：方便运维审计晋升链路

**注意：** `LEVEL_L3` 从 `auth` 模块导入。

---

## 6. 方向 D — 系统名称统一

### 6.1 代码审计结论

| 检查项 | 结果 |
|:-------|:-----|
| `handler.py` 中 `from_name` 为 `"系统"` | ✅ **71 处** 已统一 |
| `web_viewer.py` 中 `from_name` 为 `"系统"` | ✅ L476 已统一 |
| `__main__.py` 中 `from_name` 为 `"系统"` | ✅ L327 已统一 |
| 剩余 `from_agent="system"` 共 5 处 | 🔴 **不改** — 是内部 agent ID 非显示名 |
| `auto_router.py` 中 `"系统(管线)"` | 🔴 **不改** — 是管线服务的特定标识名 |
| Web 前端 | ✅ 无单独的 web 前端目录，web viewer 在 server/web_viewer.py 中 |

### 6.2 结论

**系统名称统一方向无需额外编码。** 代码审计确认所有 `from_name` 显示名已使用 `"系统"`。剩余 5 处 `"system"` 全为 `from_agent` 内部 ID：

| 位置 | 行 | 值 | 含义 | 改否 |
|:-----|:---|:---|:-----|:----:|
| `handler.py` | 2687 | `pm_agent_id: str = "system"` | PM 默认 agent ID | ❌ 不改 |
| `handler.py` | 2739 | `from_agent="system"` | 内部 agent ID | ❌ 不改 |
| `handler.py` | 6078 | `from_agent="system"` | 内部 agent ID | ❌ 不改 |
| `handler.py` | 6096 | `from_agent="system"` | 内部 agent ID | ❌ 不改 |
| `handler.py` | 6108 | `from_agent="system"` | 内部 agent ID | ❌ 不改 |

---

## 7. 改动汇总

### 7.1 文件改动一览表

| # | 文件 | 改动类型 | 行号 | 内容 | 净增行 |
|:-:|:-----|:---------|:-----|:-----|:------:|
| A-① | `server/auth.py` | 🆕 新增 | L9 之后 | `get_level()` + `set_level()` + 4 个等级常量 | **+15** |
| A-② | `server/handler.py` | 🔧 修改 | L282-289 | `handle_register()` 追加 `"level": 2` | **+1** |
| B-① | `server/handler.py` | 🆕 插入 | L5113-5114 | `handle_broadcast()` level 检查 | **+12** |
| C-① | `server/handler.py` | 🆕 插入 | L389-391 | `handle_agent_card_register()` 晋升 L2→L3 | **+7** |
| D | 系统名 | ✅ 无需改动 | — | 代码审计确认已统一 | **+0** |
| | **合计** | | | | **~+35** |

### 7.2 Scope 合规检查

| Scope 边界文件 | 零改动确认 |
|:---------------|:-----------|
| `server/workspace.py` | ✅ 零改动 |
| `server/config.py` | ✅ 零改动 |
| `server/timeout_tracker.py` | ✅ 零改动 |
| `server/persistence.py` | ✅ 零改动（仅利用现有 API `set_api_keys`） |
| `server/agent_card.py` | ✅ 零改动（晋升在 handler.py 侧） |
| `shared/protocol.py` | ✅ 零改动 |
| `gateway-plugin/__init__.py` | ✅ 零改动 |

### 7.3 不引入新依赖

| 检查项 | 结果 |
|:-------|:-----|
| 新 pip 包 | ✅ 无 |
| 新环境变量 | ✅ 无 |
| 新配置文件 | ✅ 无 |
| 新 JSON 文件 | ✅ 无（复用在 `_api_keys.json`） |

---

## 8. 兼容性分析

### 8.1 旧 bot 场景

| 场景 | 改造前 | 改造后 | 兼容性 |
|:-----|:-------|:-------|:-------|
| 7 个在线 bot（旧无 level） | 全权限 | `get_level()` 返回默认 L4 | ✅ 完全兼容 |
| 旧注册 bot 重新 auth | `is_approved()` True | 不变 | ✅ |
| 旧 bot 发 `_inbox:server` | 放行 | fast path 不变 | ✅ |
| 旧 bot 发 `_inbox:<id>` | 放行 | `get_level()`=L4 → 放行 | ✅ |
| 旧 bot 提交 Agent Card | 注册成功 | `set_level()` 尝试升 L3 但已在 L4 | ✅ 幂等 |

### 8.2 `_api_keys.json` 格式兼容性

```json
{
  "ws_abc123...": {
    "api_key": "sk_ws_...",
    "display_name": "小开",
    "status": "active",
    "created_at": 1234567890.0,
    "level": 2  // ← 🆕 R99 新增，旧记录无此字段
  }
}
```

`get_level()` 对无 `level` 字段 → 默认 L4，旧 `_api_keys.json` 零改动。

### 8.3 `is_approved()` 不受影响

| 检查 | 结果 |
|:-----|:------|
| `is_approved()` 变更 | ❌ 不变 — 仍用 approved_users + api_keys |
| level 与 approval 分离 | ✅ level 是独立维度，不影响现有 auth 逻辑 |

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|:-----|:-----|:------|
| **R1:** `get_level()` 对不存在 agent_id 默认 L4 | 未注册 bot 跳过 level 检查 | 实际未注册 bot 在 level 检查前已被 `is_approved()` 路由到 REGISTRATION_CHANNEL（L4999-5001），双重防护 |
| **R2:** L2→L3 晋升时 `set_level()` 写文件失败 | 晋升丢失 | `try/except` 包裹，日志记录，下次 Agent Card 提交可重试 |
| **R3:** L4 bot 提交 Agent Card 被降级 | L4→L3 错误降权 | `if current_level < LEVEL_L3` 保护，L4 不会被降 |
| **R4:** 并发注册时 `get_api_keys/set_api_keys` 竞态 | 写覆盖 | 现有 `set_api_keys()` 已用 `_lock`（persistence.py L116）；此风险与 R72 注册一致 |

---

## 10. Phase-Based 执行顺序

### Phase 1 — auth.py 基础设施（零运行时影响）
- [ ] `server/auth.py`: 新增 `LEVEL_L1~L4` 常量 + `get_level()` + `set_level()`
- **验证：** `python3 -c "from server.auth import get_level, set_level, LEVEL_L4; print('OK')"` 不报错

### Phase 2 — handler.py 注册初始化 + 晋升 + 检查（核心改动）
- [ ] `server/handler.py` L282: `handle_register()` 追加 `"level": 2`
- [ ] `server/handler.py` L389: `handle_agent_card_register()` 晋升 L2→L3
- [ ] `server/handler.py` L5113: `handle_broadcast()` level 检查

### Phase 3 — 验证
1. **V-1:** 模拟新注册 → 检查 _api_keys.json 中 level=2
2. **V-2:** 模拟 Agent Card 提交 → 检查 _api_keys.json 中 level=3
3. **V-3:** 模拟 L3 bot 发 `_inbox:<id>` → ❌ 应收到 rejection
4. **V-4:** 模拟 L4 bot 发 `_inbox:<id>` → ✅ 应路由到目标

---

## 11. 验收清单

| # | 验收项 | 对应需求 | 验证方法 |
|:-:|:-------|:---------|:---------|
| T-1 | 新注册 bot level=2 | 需求 A | 注册后检查 `_api_keys.json` |
| T-2 | Agent Card 提交后自动升 L3 | 需求 C | 提交卡后检查 level 变更为 3 |
| T-3 | L3 发 `_inbox:<id>` → ❌ 拒绝 | 需求 B | 模拟发送，验证 error 响应 |
| T-4 | L4 发 `_inbox:<id>` → ✅ 放行 | 需求 B | 模拟发送，验证 ack 响应 |
| T-5 | `_inbox:server` 全部放行 | 需求 E | 任何 level 发到 server 都通过 |
| T-6 | 7 现存 bot 不受影响 | 兼容性 | 旧 `_api_key` 无 level → 默认 L4 |
| T-7 | 系统名统一 | 需求 D | **代码审计已确认 ✅ 无需编码** |

---

## 变更记录

| 版本 | 日期 | 作者 | 说明 |
|:----|:----|:-----|:------|
| v1.0 | 2026-07-13 | 🏗️ 小开 | 初稿（预提交） |
| v1.1 | 2026-07-13 | 🏗️ 小开 | 完成代码审计：精确行号 + 设计决策 D1-D5 + Phase 执行顺序 + 系统名审计确认无需改动 |

---

*本文档由 🏗️ 小开编写，待 Step 3 💻 编码实现。*
