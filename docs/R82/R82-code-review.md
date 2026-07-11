# R82 代码审查报告 — Inbox-Only 架构重构 📦

> **审查人：** 🔍 审查工程师
> **审查对象：** `2da55ae` feat(R82): Inbox-Only 架构重构 — 删除活跃频道、MSG_SET_ACTIVE_CHANNEL、BROADCAST_ADMINS
> **审查日期：** 2026-07-09
> **改动统计：** 5 文件, +194/-413 = **-219 行净删**

---

## 0. 审查结论

> 🔴 **退回 — 2 项 🔴 阻塞 + 1 项 🟡 + 0 项 💡**
>
> | 级别 | 数量 | 说明 |
> |:----:|:----:|:------|
> | 🔴 阻塞 | 2 | B-1: handler.py 6 处调用已删函数 / B-2: __main__.py 引用已删函数 |
> | 🟡 W 级 | 1 | W-1: `p.LOBBYY` 拼写错误（5 处） |
> | 💡 建议 | 0 | — |

---

## 1. 改动统计

| 文件 | + | - | 净 | 说明 |
|:-----|:-:|:-:|:--:|:-----|
| `server/handler.py` | | | -重写 | 核心——删除活跃频道依赖 |
| `server/persistence.py` | +14 | -45 | **-31** | 删除 agent_channel 全套函数，新增 `workspace_store()` |
| `server/workspace.py` | | | -简化 | 新增 `pipeline_round/workflow_url/roles` 元数据字段 |
| `server/config.py` | 0 | -5 | **-5** | 删除 `BROADCAST_ADMINS`、`PIPELINE_PM_AGENT_ID` |
| `shared/protocol.py` | 0 | -5 | **-5** | 删除 `MSG_SET_ACTIVE_CHANNEL`、`MSG_CHANNEL_UPDATED`、`FIELD_ACTIVE_CHANNEL` |
| **合计** | **+194** | **-413** | **-219** | ✅ 确实做了减法 |

---

## 2. 问题清单

| 级别 | 编号 | 描述 | 位置 | 修复方式 |
|:----:|:----:|:-----|:-----|:---------|
| 🔴 | B-1 | handler.py 残留 6 处 `save_agent_channels()` / `reset_agent_channel()` 调用，但函数已从 persistence.py 删除 | 见 §2.1 | 删除或注释掉 |
| 🔴 | B-2 | `__main__.py` 导入并调用已从 persistence.py 删除的函数，启动即崩溃 | 见 §2.2 | 更新 __main__.py 导入+调用 |
| 🟡 | W-1 | `p.LOBBYY`（双 Y）5 处，应为 `p.LOBBY` | handler.py:3038/3511/3806/3966/4318 | 删除多余 Y |

---

## 3. 逐项审查

### 🔴 2.1 B-1: handler.py 调用已删函数

从 `persistence.py` 完整删除的函数列表：
- `load_agent_channels()` ❌
- `save_agent_channels()` ❌
- `get_agent_channel()` ❌
- `set_agent_channel()` ❌
- `reset_agent_channel()` ❌
- `_agent_active_channels` dict ❌

**get/set_agent_channel 清理 ✅：** 全部引用已覆盖处理（0 残留）。

**save_agent_channels/reset_agent_channel 遗漏 🔴：**

| 行号 | 残留代码 | 问题 |
|:----:|:---------|:-----|
| 4827 | `persistence.save_agent_channels(config.DATA_DIR)` | 前一行 `set_agent_channel` 已删，本行漏删 |
| 6245 | `persistence.save_agent_channels(config.DATA_DIR)` | 同上 |
| 6392 | `persistence.save_agent_channels(config.DATA_DIR)` | 同上 |
| 6483 | `persistence.save_agent_channels(config.DATA_DIR)` | 同上 |
| 6817 | `persistence.save_agent_channels(config.DATA_DIR)` | 同上 |
| 7031 | `persistence.reset_agent_channel(resolved_workspace.owner_id)` | 前一行注释已删 save_agent_channels，但本行未删 |

**影响：** `AttributeError: module 'server.persistence' has no attribute 'save_agent_channels'`。任何触达这些路径的操作（workspace_join、admin 操作、审批等）会崩溃。

**修复：** 6 行全部删除即可（`save_agent_channels` 对应 `set_agent_channel` 已删除，保存无意义；`reset_agent_channel` 不再需要）。

### 🔴 2.2 B-2: __main__.py 引用已删函数

**文件未在 diff 中（本次未改 __main__.py）：**

| 位置 | 引用 | 问题 |
|:----:|:-----|:-----|
| L20 | `load_agent_channels, load_api_keys` | import 失败 |
| L166 | `from .persistence import set_agent_channel as _set_ch, save_agent_channels as _save_ch` | import 失败 |
| L397 | 同上 | import 失败 |
| L487 | 同上 | import 失败 |
| L504 | 同上 | import 失败 |
| L695 | `from .persistence import reset_agent_channel as _reset_ch, save_agent_channels as _save_ch` | import 失败 |
| L822 | `from .persistence import load_agent_channels` | import 失败 |
| L830 | `load_agent_channels(DATA_DIR)` | 函数不存在 |
| L845 | `load_agent_channels(DATA_DIR)` | 函数不存在 |

**影响：** `ImportError: cannot import name 'save_agent_channels' from 'server.persistence'`。服务进程启动即崩溃。

**修复：** 从 __main__.py 删除所有对已删函数的引用与 import。

### 🟡 2.3 W-1: `p.LOBBYY` 拼写错误

```python
# 5 处，均为本次引入
sender_ch = p.LOBBYY   # ← 应为 p.LOBBY
```

`shared/protocol.py` 中仅有 `LOBBY = "lobby"`，无 `LOBBYY`。运行时报 `AttributeError`。

**影响：** 这些代码路径在 LINT 时未检查，运行时才会暴露。涉及 `_cmd_step_force`、`_cmd_step_verify` 等命令。

**修复：** `s/LOBBYY/LOBBY/g`（5 处）。

---

## 4. ✅ 通过项

### ✅ 4.1 Scope 合规

| 文件/模块 | 状态 |
|:----------|:-----|
| `server/handler.py` | ✅ 核心重构 |
| `server/persistence.py` | ✅ 函数删除 + workspace_store |
| `server/workspace.py` | ✅ 元数据新增 |
| `server/config.py` | ✅ BROADCAST_ADMINS 删除 |
| `shared/protocol.py` | ✅ 常量删除 |
| `clients/` | ❌ 未改动 ✅ |
| `server/web_viewer.py` | ❌ 未改动 ✅ |
| `server/auth.py` | ❌ 未改动 ✅ |
| `server/agent_card.py` | ❌ 未改动 ✅ |

**结论：** Scope 合规 ✅。（__main__.py 虽未入 diff，但 breakage 需修复）

### ✅ 4.2 删除完整性

| 函数/常量 | 原位置 | 删除状态 | handler.py 残留 | __main__.py 残留 |
|:----------|:-------|:--------:|:---------------:|:----------------:|
| `_broadcast_active_channel` | handler.py | ✅ 4 处仅注释残留 | — | — |
| `_agent_active_channels` | persistence.py | ✅ 已删 | — | — |
| `load_agent_channels()` | persistence.py | ✅ 已删 | — | 🔴 B-2 |
| `save_agent_channels()` | persistence.py | ✅ 已删 | 🔴 **B-1 (6)** | 🔴 **B-2** |
| `get_agent_channel()` | persistence.py | ✅ 已删 | ✅ **0** | 🔴 **B-2**（import 级） |
| `set_agent_channel()` | persistence.py | ✅ 已删 | ✅ **0** | 🔴 **B-2** |
| `reset_agent_channel()` | persistence.py | ✅ 已删 | 🔴 **B-1 (1)** | 🔴 **B-2** |
| `MSG_SET_ACTIVE_CHANNEL` | protocol.py | ✅ 已删 | ✅ 0 | ✅ |
| `MSG_CHANNEL_UPDATED` | protocol.py | ✅ 已删 | ✅ 0 | ✅ |
| `FIELD_ACTIVE_CHANNEL` | protocol.py | ✅ 已删 | ✅ 0 | ✅ |

### ✅ 4.3 handle_broadcast → lobby/admin 路由

```
handle_broadcast:
  - R82 A1: Inbox fast path (跳过所有 filter, 直接发送)
  - 非 inbox → 现有 lobby/admin/workspace 路由逻辑保持不变
```

lobby（`p.LOBBY`）和 admin（`p.ADMIN_CHANNEL`）路由路径保留。✅

### ✅ 4.4 _handle_server_query 覆盖

| 命令 | 处理 | 状态 |
|:-----|:-----|:----:|
| `!agent_card list` | ✅ 列出所有卡片 |
| `!pipeline_status [R]` | ✅ 查询指定/全部管线 |
| `!list_workspaces` | ✅ 列出工作区 |
| `!my_id` | ✅ 查自身 agent_id |
| `!help` | ✅ 帮助信息 |

### ✅ 4.5 workspace.py 元数据模型

| 字段 | 类型 | 用途 | 状态 |
|:-----|:-----|:------|:----:|
| `pipeline_round` | `str` | 关联管线轮次 | ✅ |
| `workflow_url` | `str` | WORK_PLAN URL | ✅ |
| `roles` | `list[str]` | 所需角色列表 | ✅ |
| `created_at` | `float` | 创建时间 | ✅ |
| `closed_at` | `float \| None` | 关闭时间 | ✅ |
| `from_dict` 兼容 | — | 静默忽略旧字段 | ✅ |

### ✅ 4.6 管线状态机不受影响

`_PIPELINE_STATE`、`pipeline_is_active()`、`pipeline_exists()` 等核心管线函数未改动，无依赖冲突 ✅

### ✅ 4.7 无内部名/agent_id 泄漏

`git diff | grep 内部名` → 零匹配 ✅

### ✅ 4.8 净减 -219 行

+194 / -413 = -219 净删 ✅ 确实做了减法。

---

## 5. 总结

### 🔴 阻塞修复结果

| # | 问题 | 修复工作量 | 说明 |
|:-:|:-----|:----------:|:-----|
| B-1 | handler.py 6 处调用已删函数 | ~2 分钟 | 直接删除对应行 |
| B-2 | __main__.py 引用已删函数 | ~5 分钟 | 删除 import + 调用 |
| W-1 | `LOBBYY` 拼写错误 5 处 | ~1 分钟 | 全局替换 |

**总修复量：** 约 8 分钟，零逻辑变更。

| 审查项 | 结果 |
|:-------|:-----|
| 1️⃣ Scope 合规 | ✅ 五文件，未改客户端/auth/agent_card |
| 2️⃣ `_broadcast_active_channel` 零残留 | ✅ 仅注释残留 |
| 3️⃣ agent_channel 函数零残留 | 🔴 **B-1/B-2: handler.py+__main__.py 未清** |
| 4️⃣ 协议常量零残留 | ✅ MSG_SET / MSG_CHANNEL / FIELD 全清 |
| 5️⃣ handle_broadcast 路由正确 | ✅ lobby/admin 保留 |
| 6️⃣ _handle_server_query 覆盖 | ✅ agent_card/pipeline/workspace/my_id/help |
| 7️⃣ workspace.py 元数据完整 | ✅ 5 字段齐全 |
| 8️⃣ 管线状态机无依赖 | ✅ |
| 9️⃣ 脱敏 | ✅ 零内部名 |
| 🔟 净减 | ✅ -219 行 |

---

> **总体：🔴 退回 — B-1/B-2/W-1 需修复后重新提交**
>
> 审查完毕：2026-07-09 🔍 审查工程师
