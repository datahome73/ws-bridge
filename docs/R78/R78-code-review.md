# R78 代码审查报告 — 全局变量迁移补完：角色映射 + ACK 状态统一管理 📋

> **审查人：** 🔍 审查工程师
> **审查对象：** `083529b` feat(R78): 全局变量迁移补完 — 角色映射 + ACK 状态统一管理
> **审查日期：** 2026-07-09
> **改动统计：** 3 文件, +233/-18 行
> **技术方案：** `docs/R78/R78-tech-plan.md`

---

## 0. 审查结论

> 🔴 **退回 — 1 项 🔴 阻塞 + 2 项 🟡 + 2 项 💡**
>
> | 级别 | 数量 | 说明 |
> |:----:|:----:|:------|
> | 🔴 阻塞 | 1 | B-1: `PipelineContext.from_dict()` `raw_role_map` NameError |
> | 🟡 W 级 | 2 | W-1: `set_global_role_map()` 无锁保护 / W-2: `_step_ack_states` 未实际迁移 |
> | 💡 建议 | 2 | S-1: `from_dict` 简化写法建议 / S-2: agent_card.py 循环 import 模式 |

---

## 1. 改动统计

| 文件 | 行数 | 改动类型 | 说明 |
|:-----|:----:|:---------|:-----|
| `server/pipeline_context.py` | +122/-1 | 新增 + 修改 | 角色映射兼容 + ACK + step 配置 + restore |
| `server/handler.py` | +102/-18 | 修改 | 4 个读取点迁移 + `resume` 子命令 + DEPRECATED 标记 |
| `server/agent_card.py` | +9/-0 | **新增** | 双写 Manager 新路径 |
| **合计** | **+233/-19** | | |

---

## 2. PipelineContext — role_agent_map 类型兼容

### 🔴 2.1 B-1: `from_dict()` 中 `raw_role_map` NameError

**代码位置：** `pipeline_context.py:186-191`

```python
# R78 A1: 兼容旧 JSON 格式（单值 str → 多值 list[str]）
raw_role_map = d.get("role_agent_map", {}),   # ← kwarg, 非局部变量
role_agent_map=(
    {k: [v] for k, v in raw_role_map.items()}  # ← NameError
    if raw_role_map and isinstance(next(iter(raw_role_map.values())), str)
    else raw_role_map                           # ← NameError
),
```

**根因分析：**

| 问题 | 说明 |
|:-----|:------|
| `raw_role_map = d.get(...),` | 这是 `cls()` 调用的关键字参数 `raw_role_map=d.get(...)`，不是局部变量赋值 |
| `raw_role_map.items()` 中的 `raw_role_map` | Python 函数调用参数在**调用者作用域**中求值——`raw_role_map` 不在 `from_dict` 的局部/外层作用域中，抛出 NameError |
| 尾逗号 `,` | `kwarg=value,` 在函数调用中**不**将值变为元组——只是语法上的可选尾逗号 |

**修复前行为：** 任何对 `PipelineContext.from_dict()` 的调用均抛出 `NameError: name 'raw_role_map' is not defined`。

**修复：** 在 `cls()` 调用前声明为局部变量：

```python
@classmethod
def from_dict(cls, d: dict) -> "PipelineContext":
    # R78 A1: 兼容旧 JSON 格式（单值 str → 多值 list[str]）
    raw = d.get("role_agent_map", {})
    if raw and isinstance(next(iter(raw.values())), str):
        role_agent_map = {k: [v] for k, v in raw.items()}
    else:
        role_agent_map = raw
    return cls(
        ...
        role_agent_map=role_agent_map,
        ...
    )
```

**实际测试验证（3 种场景全部 NameError）：**

| 场景 | 预期 | 实际 | 状态 |
|:-----|:-----|:-----|:----:|
| 旧格式 `{'arch': 'ws_xxx'}` | → `{'arch': ['ws_xxx']}` | NameError | 🔴 |
| 新格式 `{'arch': ['ws_xxx']}` | → 原样通过 | NameError | 🔴 |
| 无 `role_agent_map` 字段 | → `{}` | NameError | 🔴 |

### ✅ 2.2 兼容逻辑本身（语法修复后正确）

兼容逻辑的设计是合理的，修复语法问题后：
- 旧格式（单值 `str`）→ `{'arch': 'ws_xxx'}` → `isinstance(next(iter(...)), str)` True → `{'arch': ['ws_xxx']}` ✅
- 新格式（`list[str]`）→ `isinstance(next(...), str)` False → 原样通过 ✅
- 空 dict → `raw and isinstance(...)` → False（空 dict 是 falsy）→ `else raw` → `{}` ✅

**字段类型变更映射：** `dict[str, str]` → `dict[str, list[str]]` ✅

---

## 3. Manager 新增方法 — 锁保护

### 🟡 3.1 W-1: `set_global_role_map()` 无锁保护

```python
def set_global_role_map(self, role_agent_map: dict[str, list[str]]) -> None:
    """由 _refresh_role_agent_map() 调用，更新全局快照。"""
    self._global_role_map = role_agent_map    # ← 无 async with self._lock
```

**影响分析：**
- `self._global_role_map` 仅在创建时首次初始化，后续由 `_refresh_role_agent_map()` 从后台线程/协程写入
- 写操作是 `dict` 引用赋值（CPython GIL 保护下原子操作），**当前无竞态风险**
- `_refresh_role_agent_map()` 非协程（是同步函数），即使想加锁也拿不到 `async with`

**建议：** 保持当前实现（GIL 保证原子性），但在 docstring 中注释「无锁——仅由 _refresh_role_agent_map 写，GIL 保护引用赋值」

### ✅ 3.2 其余方法锁保护

| 方法 | `async with self._lock` | 状态 |
|:-----|:----------------------:|:----:|
| `get_role_agents()` | 读操作，无需锁 | ✅ |
| `set_ack_state()` | ✅ | ✅ |
| `update_role_agent_map_round()` | ✅ | ✅ |
| `update_steps()` | ✅ | ✅ |
| `restore_from_history()` | ✅（写部分） | ✅ |
| `set_global_role_map()` | ❌ | 🟡 W-1 |

---

## 4. agent_card.py — 循环 import 处理

### ✅ 4.1 现有模式分析

```python
# agent_card.py
try:
    from . import handler as _handler_mod  # 局部导入（避免循环引用）
    mgr = _handler_mod._pipeline_manager
    if mgr is not None:
        current_map = mgr.get_global_role_map()
        for r in pipeline_roles:
            if agent_id not in current_map.setdefault(r, []):
                current_map[r].append(agent_id)
        mgr.set_global_role_map(current_map)
    # 双写旧变量
    for r in pipeline_roles:
        if r not in _handler_mod._ROLE_AGENT_MAP:
            _handler_mod._ROLE_AGENT_MAP[r] = []
        if agent_id not in _handler_mod._ROLE_AGENT_MAP[r]:
            _handler_mod._ROLE_AGENT_MAP[r].append(agent_id)
except Exception:
    pass
```

**验证：**

| 检查项 | 结果 |
|:-------|:-----|
| 局部导入避免循环引用 | ✅ `from . import handler as _handler_mod` 在函数体内 |
| `_handler_mod._pipeline_manager` 惰性检查 | ✅ `if mgr is not None` 保护 |
| `current_map.setdefault()` 模式 | ✅ 不重复添加 |
| 双写旧变量 | ✅ `_handler_mod._ROLE_AGENT_MAP` 同步更新 |
| try/except 兜底 | ✅ 导入或运行时异常不崩溃 |
| **结论** | ✅ 完全正确 |

### 💡 S-1: 循环 import 的替代模式

当前模式：从 `agent_card.py` 内部 `from . import handler` 使用 `handler._pipeline_manager`。这是从 handler 的**模块属性**反向访问没有公开 API 的 Manager。

建议（**非阻塞，后续阶段重构**）：在 `handler.py` 模块级公开 `get_pipeline_manager()` 函数（代替 `_ensure_pipeline_manager` 的私有前缀），或通过 `config` / `persistence` 中间层暴露 Manager。

---

## 5. 双写保险 — 新路径写入完整性

### ✅ 5.1 三处双写点覆盖

| # | 写入点 | 新路径 | 旧路径 | 状态 |
|:-:|:-------|:-------|:-------|:----:|
| A2 | `_refresh_role_agent_map()` (handler.py:1025) | `mgr.set_global_role_map()` | `_ROLE_AGENT_MAP` | ✅ |
| A3 | `register_from_agent()` (agent_card.py:386-397) | `mgr.set_global_role_map()` | `_handler_mod._ROLE_AGENT_MAP` | ✅ |
| B3 | `_update_step_ack_state()` (handler.py:1898) | `mgr.set_ack_state()` | `_step_ack_states` | ✅ |
| C3 | `_get_step_config()` (handler.py:1298) | `mgr.get_step_config()` | `_PIPELINE_CONFIG` | ✅（读路径） |

### ✅ 5.2 A2: `_refresh_role_agent_map()` 同步

```python
# R78 A2: 同步写到 Manager 全局快照
try:
    mgr = _ensure_pipeline_manager()
    mgr.set_global_role_map(dict(_ROLE_AGENT_MAP))  # ← 从旧变量拷贝到新路径
except Exception:
    pass
```

**验证：** 每次 `_refresh_role_agent_map()` 运行时（启动/重载），旧 `_ROLE_AGENT_MAP` 的最新状态通过 `dict()` 快照复制到 Manager ✅

### ✅ 5.3 B3: `_update_step_ack_state()` — `asyncio.ensure_future` 火焰

```python
asyncio.ensure_future(mgr.set_ack_state(round_name, step, dict(ack_state)))
```

**验证：**
- `_update_step_ack_state()` 是同步函数（被从同步上下文调用）
- 使用 `asyncio.ensure_future()` 将协程抛入事件循环异步执行 ✅
- 不影响调用者的同步执行路径 ✅
- `try/except` 捕获 Exception 异常 ✅

---

## 6. 旧变量 DEPRECATED 标记

### ✅ 6.1 已标记的 DEPRECATED 变量

| 变量 | 行号 | 标记 | 说明 |
|:-----|:----:|:-----|:------|
| `_ROLE_AGENT_MAP` | handler.py:53 | `# R78 A: DEPRECATED — 迁移到 PipelineContextManager._global_role_map` | ✅ |
| `_step_ack_states` | handler.py:56 | `# R78 B: DEPRECATED — 迁移到 PipelineContext.ack_states` | ✅ |

### 🟡 6.2 W-2: `_step_ack_states` 未实际迁移到 Manager

`_step_ack_states` 虽标了 DEPRECATED，但：
- 数据流向是：旧路径（`_step_ack_states`）→ **双写** → Manager
- Manager 中 `PipelineContext.ack_states` 已定义
- 但 `_step_ack_states` 本身**没有被任何读路径替换**——旧读代码仍从 `_step_ack_states` 读取
- 注释写 `Phase 4`，说明这是预标记，实际迁移在后面轮次

**影响：** 符合设计方案中的分阶段迁移策略，不是功能缺陷但需注意 Phase 4 有具体读路径迁移任务。

### ✅ 6.3 读路径写入优先级迁移（A4/C3）

| 读路径 | 迁移前 | 迁移后 | 状态 |
|:-------|:-------|:-------|:----:|
| `_get_agents_by_role()` | `_ROLE_AGENT_MAP.get(role, [])` | ① `mgr.get_role_agents(role)` ② `_ROLE_AGENT_MAP.get(role, [])` | ✅ |
| `_get_step_config()` | `_PIPELINE_CONFIG.get().steps` | ① `mgr.get_step_config()` ② `_PIPELINE_CONFIG.get()` | ✅ |

**回退链完整：** 新路径不可用时降级到旧路径 ✅

---

## 7. Scope 合规

| 文件 | 原因 | 状态 |
|:-----|:------|:----:|
| `server/pipeline_context.py` | R78 核心——新增 Manager 方法 | ✅ |
| `server/handler.py` | 读路径迁移 + DEPRECATED + resume 命令 | ✅ |
| `server/agent_card.py` | 新路径双写 | ✅ |
| `server/pipeline_sync.py` | ❌ 未改动 | ✅ |
| `server/message_store.py` | ❌ 未改动 | ✅ |

**Scope：** 仅改 3 文件，完全符合技术方案 ✅

---

## 8. 代码质量审查

### 8.1 边界情况分析

| 场景 | 预期 | 实现 | 状态 |
|:-----|:-----|:-----|:----:|
| `from_dict()` 旧格式 str | → list[str] | 🔴 **NameError (B-1)** | 🔴 |
| `from_dict()` 新格式 list[str] | 原样通过 | 🔴 **NameError (B-1)** | 🔴 |
| `from_dict()` 无 role_agent_map | → 默认 {} | 🔴 **NameError (B-1)** | 🔴 |
| `get_role_agents(round_name=...)` 查询轮次 | 轮次特有 | ✅ `ctx.role_agent_map.get(role)` | ✅ |
| `get_role_agents(round_name=None)` 全局 | 全局快照 | ✅ `_global_role_map.get(role)` | ✅ |
| `set_ack_state()` 不存在的 round | → False | ✅ `ctx is None → False` | ✅ |
| `restore_from_history()` COMPLETED | → None | ✅ `return None` | ✅ |
| `restore_from_history()` BLOCKED | → RUNNING | ✅ `BLOCKED→RUNNING` | ✅ |
| `_update_step_ack_state()` from sync context | 异步写 Manager | ✅ `asyncio.ensure_future()` | ✅ |
| `agent_card.py` handler 未初始化 | 安全降级 | ✅ `if mgr is not None` | ✅ |

### 8.2 安全/遗留物检查

| 检查项 | 结果 |
|:-------|:-----|
| 硬编码敏感信息 | ✅ 无 |
| 调试 print 残留 | ✅ 无 |
| TODO/FIXME 残留 | ✅ 无 |
| `except Exception: pass` | ✅ 合理使用（IO/导入降级） |
| R 标签准确 | ✅ 全部为 R78 |

---

## 9. 问题清单

| 级别 | 编号 | 描述 | 位置 | 修复方式 |
|:----:|:----:|:-----|:-----|:---------|
| 🔴 | B-1 | `from_dict()` 中 `raw_role_map = d.get(...)` 为关键字参数而非局部变量，后续引用抛出 NameError。**所有 from_dict() 调用均崩溃** | `pipeline_context.py:186-191` | 在 `cls()` 前声明为局部变量，详见 §2.1 |
| 🟡 | W-1 | `set_global_role_map()` 无锁保护，但 GIL 保证引用赋值原子性 | `pipeline_context.py:351` | 加 docstring 注释「无锁——GIL 保护」 |
| 🟡 | W-2 | `_step_ack_states` 标 DEPRECATED 未实际迁移读路径（Phase 4 任务） | `handler.py:56` | Phase 4 补完 |
| 💡 | S-1 | agent_card.py 通过 `handler._pipeline_manager` 访问 Manager（依赖模模块属性） | `agent_card.py:388` | 后续公开 `get_pipeline_manager()` |
| 💡 | S-2 | `get_role_agents()` 中 `round_name` 参数签名可读性 | `pipeline_context.py:359` | 当前可接受 |

---

## 10. 总结

### 🔴 必须修复（B-1）

`from_dict()` 的 `raw_role_map` NameError 是致命缺陷。**任何从持久化恢复上下文、`restore_from_history()`、`get_history()` 读取等路径都会崩溃。**

**修复预览（~8 行改动）：**
```python
@classmethod
def from_dict(cls, d: dict) -> "PipelineContext":
    raw = d.get("role_agent_map", {})
    if raw and isinstance(next(iter(raw.values())), str):
        role_agent_map = {k: [v] for k, v in raw.items()}
    else:
        role_agent_map = raw
    return cls(
        ...
        role_agent_map=role_agent_map,
        ...
    )
```

### ✅ 通过项摘要

| 审查项 | 结果 |
|:-------|:----:|
| 1️⃣ `role_agent_map` 类型兼容（str→list[str]） | 🔴 **B-1: from_dict 语法错误** |
| 2️⃣ Manager 新增方法锁保护 | 🟡 W-1: set_global_role_map 无锁（GIL 安全） |
| 3️⃣ `agent_card.py` 循环 import | ✅ 正确 |
| 4️⃣ 双写保险完整性 | ✅ 三处双写全覆盖 |
| 5️⃣ 旧变量 DEPRECATED 标记 | ✅ 两处已标记 |
| 6️⃣ Scope 合规 | ✅ 3 文件，零 scope creep |

> **总体：🔴 退回 — 请修复 B-1（8 行修改）后重新提交审查**
>
> 审查完毕：2026-07-09 🔍 审查工程师
