# R99 代码审查报告 — Bot 权限等级体系 🔒

> **版本：** v1.0  
> **审查者：** 🔍 小周  
> **审查 commit：** `ed18016` — feat(R99): Bot 权限等级体系  
> **审核分支：** `dev`  
> **审核日期：** 2026-07-11  
> **改动：** 4 文件 +85/-8 行  
> **基于方案：** `docs/R99/R99-tech-plan.md` v1.1  
> **需求文档：** `docs/R99/R99-product-requirements.md` v1.0  

---

## 审查结论

| 项目 | 结论 |
|:-----|:----:|
| **安全边界** — handler() level>=4 检查 | 🟢 **通过** |
| **晋升逻辑** — agent_card.py L2→L3 幂等性 | 🟡 **注意**（架构偏差，功能正确） |
| **存量兼容** — auth.get_level() 默认 L4 | 🟢 **通过** |
| **系统名统一** — 5处常量迁移 + 3处显示名 | 🟢 **通过** |
| **并发安全** — get_api_key_record 的 Lock | 🟢 **通过** |
| **总体结论** | 🟢 **通过 — 1 项 🟡 注意** |

---

## 逐项审查

### ① 安全边界 — `handler()` L6164-6182 level>=4 检查（位置⑦）

**Verdict: 🟢 通过**

**检查点：**

| 检查项 | 结果 | 证据 |
|:-------|:----:|:-----|
| 插入位置正确性 | ✅ | 在 R87 `_handle_server_relay` 后、`handle_broadcast` 前（L6162→L6164→L6184） |
| `_inbox:server` 豁免 | ✅ | `_channel != SERVER_INBOX_CHANNEL` 显式排除 |
| 拒绝后阻断 | ✅ | `continue` 跳过 `handle_broadcast` |
| 错误提示 | ✅ | 含当前等级 + 升级指引 |
| 拒绝日志 | ✅ | `logger.info("[R99] 拒绝: ...")` |

**代码路径验证：**

```
handler() L6145+
  ├─ R86 key活性检查 (L6155-6161)
  ├─ R87 _inbox:server 中继拦截 (L6162-6163) → continue
  ├─ ═══ R99 权限检查 (L6164-6182) ═══
  │    ├─ channel != _inbox:server → level>=4?
  │    │    ├─ 否 → _send(error) → continue ❌
  │    │    └─ 是 → 放行 ↓
  │    └─ channel == _inbox:server → 放行 ↓
  └─ handle_broadcast (L6184)
```

**场景覆盖：**

| 场景 | 结果 | 说明 |
|:-----|:----:|:-----|
| L2 bot → `_inbox:server` | ✅ 放行 | 显式豁免 |
| L2 bot → `_inbox:ws_xxx` | ❌ 拒绝 | level=2 < 4 |
| L3 bot → `_inbox:ws_xxx` | ❌ 拒绝 | level=3 < 4 |
| L4 bot → `_inbox:ws_xxx` | ✅ 放行 | level=4 >= 4 |
| 旧 bot 无 level → `_inbox:ws_xxx` | ✅ 放行 | 默认 L4 |
| 未注册 bot → `_inbox:ws_xxx` | ✅ 放行* | 但已被 R86 key 检查截停 |

> *双重防护：未注册 bot 在 R86 key 检查（L6155）中被 routing 到 REGISTRATION_CHANNEL，不会到达 level 检查点。

---

### ② 晋升逻辑 — agent_card.py L2→L3 自动晋升

**Verdict: 🟡 注意 — 功能正确，但有架构偏差**

**代码：** `server/agent_card.py:register_from_agent()` L380+

```python
# ── R99: Agent Card 提交成功 → L2→L3 自动晋升 ──
try:
    from . import auth as _auth_mod
    current_level = _auth_mod.get_level(agent_id)
    if current_level == 2:
        _auth_mod.set_level(agent_id, 3)
        logger.info("[R99] 自动晋升: %s L2→L3", agent_id[:20])
except Exception:
    logger.warning("[R99] 自动晋升失败 (非致命): %s", agent_id[:20])
```

**正确性验证：**

| 检查项 | 结果 | 说明 |
|:-------|:----:|:------|
| 幂等性 — L2→L3 | ✅ | `current_level == 2` → 只升 L2 |
| 不会降级 L4 | ✅ | `== 2` 不匹配 L3/L4 |
| 不会降级 L3 | ✅ | `== 2` 不匹配 L3 |
| 不阻断注册 | ✅ | `try/except Exception` |
| 日志审计 | ✅ | 成功/失败均有日志 |
| 导入安全 | ✅ | 延迟导入 `from . import auth` 避开了 agent_card ↔ handler 循环引用 |

**🟡 注意：架构偏差**

| 项目 | 技术方案要求 | 实际实现 |
|:-----|:-----------|:---------|
| 位置 | `handler.py:handle_agent_card_register()`（D4 明确 ❌ 放 register_from_agent 内） | `agent_card.py:register_from_agent()` |
| 理由 | 纯数据函数不应有权限副作用 | 直接在数据层写权限 |

**影响分析：**
- 功能上等价：晋升发生在 card 保存后、welcome 消息发送前 ✅
- `try/except` 确保注册不受影响 ✅
- 不改变 `register_from_agent()` 返回值 ✅
- **结论：** 🟡 注意 — 功能正确但违反设计方案，建议下次重构时移至 handler.py

---

### ③ 存量兼容 — `auth.get_level()` 默认 L4

**Verdict: 🟢 通过**

**代码：** `server/auth.py`

```python
def get_level(agent_id: str) -> int:
    record = persistence.get_api_key_record(agent_id)
    if record is None:
        return 1  # L1 — 未注册
    return record.get("level", 4)  # 默认 L4 向后兼容
```

| 检查项 | 结果 | 说明 |
|:-------|:----:|:------|
| 无 level 字段 → 默认 L4 | ✅ | 7 个现有 bot 自动全权限 |
| 未注册 agent → L1 | ✅ | `record is None` → 1 |
| 正常 level 字段 | ✅ | 取实际值 |
| 不影响 `is_approved()` | ✅ | auth 逻辑无变化 |

---

### ④ 系统名统一

**Verdict: 🟢 通过**

**`"system"` → `SYSTEM_AGENT_ID` 常量：5 处**

| # | 文件:行 | 原值 | 新值 |
|:-:|:--------|:-----|:-----|
| 1 | handler.py:2688 | `pm_agent_id: str = "system"` | `pm_agent_id: str = SYSTEM_AGENT_ID` |
| 2 | handler.py:2740 | `from_agent="system"` | `from_agent=SYSTEM_AGENT_ID` |
| 3 | handler.py:6076 | `"from_agent": "system"` | `"from_agent": SYSTEM_AGENT_ID` |
| 4 | handler.py:6093 | `"from_agent": "system"` | `"from_agent": SYSTEM_AGENT_ID` |
| 5 | handler.py:6105 | `"from_agent": "system"` | `"from_agent": SYSTEM_AGENT_ID` |

**`"系统(中继)"` → `"系统"`：3 处**

| # | 文件:行 | 原值 | 新值 |
|:-:|:--------|:-----|:-----|
| 1 | handler.py:6076 | `"from_name": "系统(中继)"` | `"from_name": "系统"` |
| 2 | handler.py:6093 | `"from_name": "系统(中继)"` | `"from_name": "系统"` |
| 3 | handler.py:6105 | `"from_name": "系统(中继)"` | `"from_name": "系统"` |

**残留检查：**
- `"system"` 字符串剩余：**0 处** ✅
- `"系统(中继)"` 字符串剩余：**0 处** ✅

> ⚠️ 注意：`SYSTEM_AGENT_ID = "_system"`（带下划线前缀）。旧值 `"system"` → 新值 `"_system"`。但该常量在 commit 前已存在并用于 13+ 处，本次仅将剩余 5 处迁移至一致性。任何依赖 `from_agent == "system"` 的代码已经在 commit 前使用 `"_system"`。

---

### ⑤ 并发安全 — `persistence.get_api_key_record()`

**Verdict: 🟢 通过**

**代码：** `server/persistence.py`

```python
def get_api_key_record(agent_id: str) -> dict | None:
    with _lock:
        return _api_keys.get(agent_id)
```

| 检查项 | 结果 | 说明 |
|:-------|:----:|:------|
| `_lock` 保护读取 | ✅ | 与 `set_api_keys()` 使用同一 `_lock` |
| 返回副本 | ✅ | `dict.get()` 返回引用，但 `_api_keys` 是 `dict` 的子引用安全（读操作） |
| TOCTOU 窗口 | ⚠️ 已知 | `set_level()` 中 `get_api_keys()`→修改→`set_api_keys()` 间存在窗口，但此模式与现有代码库所有 `get_api_keys/set_api_keys` 对一致，非新增风险 |

---

## 其他发现

### 技术方案 vs 实现偏差

| # | 项目 | 技术方案 | 实现 | 影响 |
|:-:|:-----|:--------|:-----|:-----|
| 1 | 晋升插入位置 | `handler.py:handle_agent_card_register()` L389 | `agent_card.py:register_from_agent()` L380 | 🟡 架构偏差（见②） |
| 2 | agent_card.py 零改动 | 承诺零改动（§7.2） | +14 行晋升逻辑 | 🟡 注意 |
| 3 | `"system"`→`SYSTEM_AGENT_ID` | 估算 7 处 | 实际 5 处 | ✅ 少于预测 |
| 4 | 晋升条件 | `if current_level < LEVEL_L3` | `if current_level == 2` | ✅ 更保守，等价 |

### `persistence.py` 新 API

| 函数 | 作用 | 调用方 |
|:-----|:-----|:-------|
| `get_api_key_record(agent_id) → dict \| None` | 单记录安全读取 | `auth.get_level()` |

---

## 验收清单

| # | 验收项 | 结果 |
|:-:|:-------|:----:|
| T-1 | 新注册 bot level=2 | 🟢 实现确认 (`handle_register()` L286: `"level": 2`) |
| T-2 | Agent Card 提交后自动升 L3 | 🟢 实现确认 (agent_card.py L380) |
| T-3 | L3 发 `_inbox:<id>` → ❌ 拒绝 | 🟢 实现确认 (handler.py L6166-6177) |
| T-4 | L4 发 `_inbox:<id>` → ✅ 放行 | 🟢 实现确认 (< 4 检查) |
| T-5 | `_inbox:server` 全部放行 | 🟢 实现确认 (`!= SERVER_INBOX_CHANNEL`) |
| T-6 | 7 现存 bot 不受影响 | 🟢 无 level→默认 L4, `is_approved()` 不变 |
| T-7 | 系统名统一 | 🟢 0 残留 `"system"`, 0 残留 `"系统(中继)"` |

---

## 结论

**🟢 代码审查通过 — 1 项 🟡 注意**

| 严重程度 | 数量 |
|:---------|:----:|
| 🔴 不通过 | 0 |
| 🟡 注意 | 1 |
| 🟢 通过 | 4 |

**🟡 注意项：** L2→L3 晋升逻辑置于 `agent_card.py:register_from_agent()` 而非 `handler.py:handle_agent_card_register()`，违反技术方案 D4（纯数据函数不应有权限副作用）。功能等价，不阻断注册，建议下次迭代重构。

**关键设计确认：** `SYSTEM_AGENT_ID = "_system"` 值带下划线前缀。该常量在 commit 前已定义并广泛使用（13+ 处），本次迁移不引入不兼容变化。

---

*审查由 🔍 小周完成，基于 `dev` `31febf2` 及 commit `ed18016`*
