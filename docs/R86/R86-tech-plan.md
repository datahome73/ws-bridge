# R86 技术方案 — Agent API Key 注册认证加固 🛡️

> **版本：** v1.0
> **状态：** ✅ 终稿
> **作者：** 🏗️ 架构师（小开）
> **日期：** 2026-07-09
> **基于需求文档：** `docs/R86/R86-product-requirements.md`
> **涉及文件：** `server/handler.py` · `server/__main__.py` · `server/auth.py`

---

## 目录

1. [改动总览](#1-改动总览)
2. [A1 — display_name 重复检测](#2-a1--display_name-重复检测)
3. [A2 — `_find_agent_by_name()` 辅助函数](#3-a2--_find_agent_by_name-辅助函数)
4. [B1 — 消息入口 Key 活性检查](#4-b1--消息入口-key-活性检查)
5. [B2 — auth_ok 去除 role 字段](#5-b2--auth_ok-去除-role-字段)
6. [C1 — Revoke 后断连](#6-c1--revoke-后断连)
7. [兼容性分析](#7-兼容性分析)
8. [风险与回退](#8-风险与回退)

---

## 1. 改动总览

| # | 方向 | 文件 | 位置 | 性质 | 行数 |
|:-:|:----:|:----|:----|:----:|:----:|
| 1 | A1 | `server/handler.py` | `handle_register()` L229-270 | 新增 before L237 | ~12 行 |
| 2 | A2 | `server/auth.py` | 模块级（建议 L168-188 之后） | 新增函数 | ~8 行 |
| 3 | B1 | `server/handler.py` | `handler()` L6165 | 新增 before handle_broadcast | ~8 行 |
| 4 | B1 | `server/__main__.py` | `ws_handler()` L104 | 新增 before handle_broadcast | ~8 行 |
| 5 | B2 | `server/handler.py` | `handle_auth()` L200-206 | 确认/微调 | ~0-2 行 |
| 6 | C1 | `server/handler.py` | 模块级（新增 `_force_disconnect_revoked_agent()` + 调用处） | 新增函数 + 调用 | ~15 行 |

**净增量：** ~50 行，3 文件改动。

---

## 2. A1 — display_name 重复检测

### 2.1 位置

`handler.py` → `async def handle_register(ws, msg: dict) -> str | None:` 函数内，**L232 之后（display_name 空校验通过后）、L237 之前（生成 agent_id 之前）**。

### 2.2 改造前（当前代码 L230-237）

```python
    display_name = msg.get("display_name", "").strip()
    if not display_name:
        await _send(ws, {"type": "auth_error", "error": "Missing display_name"})
        return None

    # 1. 生成 ws-bridge 自有 agent_id
    agent_id = auth.generate_agent_id()
```

### 2.3 改造后

```python
    display_name = msg.get("display_name", "").strip()
    if not display_name:
        await _send(ws, {"type": "auth_error", "error": "Missing display_name"})
        return None

    # ═══ R86 A1: display_name 重复检测 ═══
    existing = auth.find_agent_by_name(display_name)
    if existing:
        await _send(ws, {
            "type": "auth_error",
            "error": f"display_name '{display_name}' already registered",
        })
        return None
    # ══════════════════════════════════════

    # 1. 生成 ws-bridge 自有 agent_id
    agent_id = auth.generate_agent_id()
```

### 2.4 设计说明

- **trimmed 后的全等比较**：`display_name` 已在 L231 `.strip()`，因此 `_find_agent_by_name()` 内部只需与已保存的 `display_name` 做 `.strip()` 全等比较即可
- **大小写敏感**：保持现有命名风格一致性，不追加 case-insensitive 逻辑（非需求范围）
- **返回 auth_error**：复用了 existing auth_error 类型，client 端可统一处理
- **不走 approve 路径**：只阻止注册，不改动已有 key 的状态

---

## 3. A2 — `_find_agent_by_name()` 辅助函数

### 3.1 位置选择

**结论：`server/auth.py` 模块级**

理由：
1. `auth.py` 已经拥有 API key 管理的完整核心逻辑（`create_api_key`, `validate_api_key`, `revoke_api_key`）
2. `persistence.get_api_keys()` 已在 `auth.py` 多处使用，不存在循环导入风险
3. `handler.py` 已 `from . import auth`，调用自然
4. 未来若增加其他基于 display_name 的查询（如 admin 管理面板），`auth.py` 是正确位置

### 3.2 插入位置

紧接 `revoke_api_key()` 之后（`auth.py` L165 之后），与现有 API key 函数形成自然分组。

### 3.3 代码

```python
def find_agent_by_name(display_name: str) -> dict | None:
    """R86 A2: 按 display_name 查找已注册 agent。

    Args:
        display_name: 待查找的显示名称（外部已 strip）

    Returns:
        {"agent_id": str, "record": dict} | None
    """
    from . import persistence
    keys = persistence.get_api_keys()
    target = display_name.strip()
    for agent_id, record in keys.items():
        if record.get("display_name", "").strip() == target:
            return {"agent_id": agent_id, "record": record}
    return None
```

### 3.4 设计说明

- **返回 dict 结构**：包含 `agent_id` + `record`，给未来扩展（如展示已注册信息、检查 status）预留空间
- **内部 strip**：防御性编程，即使调用方忘记 strip 也不影响匹配
- **遍历所有 api_keys**：目前规模小（~几十个），线性扫描开销可忽略。如果未来扩充，可考虑建 name→id 索引，但不在本需求范围内

---

## 4. B1 — 消息入口 Key 活性检查

### 4.1 插入点分析

**问题：B1 检查应放在 `handler()` 还是 `ws_handler()`？还是两者都要？**

| 维度 | `handler()` (websockets 库) L6165 | `ws_handler()` (aiohttp) L104 |
|:----|:-------------------------------:|:----------------------------:|
| 用户 | websockets 客户端 | aiohttp 客户端 |
| 活跃度 | ✅ 活跃路径（多 agent 使用） | ✅ 活跃路径（多 agent 使用） |
| 风险 | 不经 B1 检查则吊销后可继续发消息 | 同上 |

**结论：两者都加**。R72 设计了两套入口路径，任一入口绕过 B1 都可导致安全漏洞。

### 4.2 正确插入位置

**位置语义：** `msg_type == "message" and agent_id` 分支的**第一条语句**，在 `await handle_broadcast(...)` 之前。

理由（参考 WORK_PLAN）：
- ✅ B1 检查使用 `continue` 而非 `break`/`return`，保持连接不断
- ✅ 不影响 handle_broadcast 内部逻辑
- ✅ 当 key 被 revoke 后，agent 仍可接收服务端推送的 revoke 通知

### 4.3 改造前 → 改造后

#### `handler()` L6165-6166

**改造前：**
```python
        elif msg_type == "message" and agent_id:
            await handle_broadcast(ws, agent_id, msg)
```

**改造后：**
```python
        elif msg_type == "message" and agent_id:
            # ═══ R86 B1: 检查 API key 活性 ═══
            _keys = persistence.get_api_keys()
            _rec = _keys.get(agent_id)
            if _rec and _rec.get("status") == "revoked":
                await _send(ws, {"type": "error", "error": "API key revoked"})
                continue
            # ════════════════════════════════════
            await handle_broadcast(ws, agent_id, msg)
```

#### `ws_handler()` L104-105 （`server/__main__.py`）

**改造前：**
```python
        elif msg_type == "message" and agent_id:
            await handle_broadcast(ws, agent_id, data)
```

**改造后：**
```python
        elif msg_type == "message" and agent_id:
            # ═══ R86 B1: 检查 API key 活性 ═══
            from . import persistence as _persistence
            _keys = _persistence.get_api_keys()
            _rec = _keys.get(agent_id)
            if _rec and _rec.get("status") == "revoked":
                await ws.send_json({"type": "error", "error": "API key revoked"})
                continue
            # ════════════════════════════════════
            await handle_broadcast(ws, agent_id, data)
```

### 4.4 导入说明

- **`handler.py`**：已 `from . import persistence` 在模块顶部（L11），无需额外 import
- **`__main__.py`**：当前模块顶部未导入 persistence，有两种方案：

  | 方案 | 说明 | 选择 |
  |:---:|:-----|:----:|
  | 方案 A：模块顶部导入 `from . import persistence` | 干净，但引入模块级依赖 | ❌ 增加不必要的全局导入 |
  | 方案 B：**函数内 `from . import persistence as _persistence`** | 局部导入，清晰自包含 | ✅ 推荐 |

  选择方案 B，使用 `from . import persistence as _persistence` 在检查点前局部导入。

### 4.5 `validate_api_key` vs 直接读 `_api_keys.json`

不复用 `auth.validate_api_key()` 的原因：

| | `validate_api_key()` | 直接读 keys dict |
|:--|:--------------------:|:----------------:|
| 输入 | api_key 字符串 | agent_id |
| 已有 agent_id | ❌ 需反向推导 | ✅ 直接查表 |
| 多一步计算 | 是 | 否 |
| 清晰度 | 低（函数名暗示重验证） | 高（意图直接） |

B1 场景已有 `agent_id`，用 `persistence.get_api_keys().get(agent_id)` 直接查 `status` 最简洁。

---

## 5. B2 — auth_ok 去除 role 字段

### 5.1 当前代码（`handler.py` L200-206）

```python
    display_name = persistence.get_api_keys().get(agent_id, {}).get("display_name", agent_id)
    await _send(ws, {
        "type": "auth_ok",
        "agent_id": agent_id,
        "display_name": display_name,
    })
```

**审查结论：** ✅ 当前代码在 R72 api_key auth 路径下，`auth_ok` payload **已有且仅有** `type`, `agent_id`, `display_name` 三个字段，不存在 `role` 字段。无需改动。

### 5.2 风险点

- 需确认其他 auth 路径（如果有 `pairing_code` approve 路径或旧版 auth 路径）的 `auth_ok` 不含 `role` 字段
- 查询 `auth.py` 中的 `approve()` 函数（L35-54）：该路径返回 `{"type": "approve_ok", "agent_id": agent_id}`，不涉及 `auth_ok`，也不含 `role` 字段
- **结论：零改动**

> **安全保留：** 如果未来某条 auth 路径向 `auth_ok` 注入 `role` 字段，应当在代码审查（Step 4）时被拦截。此处只记录确认结果，不做代码修改。

---

## 6. C1 — Revoke 后断连

### 6.1 设计目标

当 admin 调用 `auth.revoke_api_key(agent_id)` 吊销某个 agent 的 key 后，**立即断开该 agent 的所有活跃 WebSocket 连接**，使其不能再发送/接收消息。

### 6.2 `_force_disconnect_revoked_agent()` 函数

#### 位置

`server/handler.py` 模块级，与 `_connections` 字典同层级（建议放在 L24 之后或 `handle_register` 之前）。

#### 函数签名

```python
async def _force_disconnect_revoked_agent(agent_id: str) -> int:
    """R86 C1: 吊销 agent 的所有活跃 WebSocket 连接。

    发送 revoke 通知后立即关闭连接，并从 _connections 中移除。

    Args:
        agent_id: 被吊销 agent 的 ID

    Returns:
        断开的连接数量
    """
    conns = list(_connections.get(agent_id, set()))
    for ws in conns:
        try:
            await _send(ws, {
                "type": "revoked",
                "reason": "API key revoked",
            })
            # 关闭 WebSocket（兼容 websockets & aiohttp）
            if hasattr(ws, "close"):
                await ws.close()
        except Exception:
            pass
    # 从 _connections 清理
    if agent_id in _connections:
        del _connections[agent_id]
    logger.info("R86 C1: Forcibly disconnected %d connection(s) for revoked agent %s",
                 len(conns), agent_id[:20])
    return len(conns)
```

### 6.3 调用时机

`_force_disconnect_revoked_agent()` 必须在 `auth.revoke_api_key()` 成功（返回 True）后立即自动调用。

由于当前代码中 `revoke_api_key()` 的调用点不在 handler.py 的直接消息循环中（推测由 admin 命令触发），C1 实现分为两种情况：

#### 情况 1：如果 revoke 在 handler 内触发（推荐）

```python
    # 在 revoke_api_key 调用后立即：
    if auth.revoke_api_key(target_agent_id):
        await _force_disconnect_revoked_agent(target_agent_id)
```

#### 情况 2：如果 revoke 在外部触发

需要在 handler 外暴露 `_force_disconnect_revoked_agent` 的引用，或在 handler 内通过 admin 消息处理路径调用。具体调用点需根据实际 admin revoke 命令的实现位置确定。

> **待确认：** 当前 `auth.revoke_api_key()` 的调用者是谁？（推测为 admin 的 `revoke` 消息处理分支，需在编码阶段定位精确调用点）

### 6.4 关闭方式兼容性

| WebSocket 库 | ws 对象 | close() 方法 |
|:-------------|:--------|:-------------|
| `websockets` (websockets库) | 原生 ws | `await ws.close()` ✅ |
| `aiohttp` | web.WebSocketResponse | `await ws.close()` ✅ |

两者都支持 `await ws.close()`，无需条件判断。

---

## 7. 兼容性分析

### 7.1 前向兼容

| 旧客户端行为 | 改造后表现 | 兼容性 |
|:-------------|:-----------|:------:|
| 正常 agent 发消息 | B1 检查通过，行为不变 | ✅ 完全兼容 |
| 已注册 agent 再次注册 | 同名被拒，返回 auth_error | ✅ 安全增强 |
| 已注册 agent auth | auth_ok 不变 | ✅ 完全兼容 |
| 未注册 agent 首次注册 | 正常通过 | ✅ 完全兼容 |
| auth_ok 无 role 字段 | 现状已无，不做改动 | ✅ 完全兼容 |

### 7.2 后向兼容（部署后旧连接）

| 场景 | 行为 | 说明 |
|:-----|:-----|:-----|
| 部署前已建立连接 | B1 只检查 `status=="revoked"`，正常 active key 不受影响 | ✅ 无影响 |
| 部署后才 revoke | 新 C1 机制生效 | ✅ 安全增强 |

### 7.3 scope 边界（严禁 creep）

| 不在此范围 | 原因 |
|:-----------|:-----|
| Web 端、客户端库 | 非服务端改动 |
| Agent Card、任务状态机、管线命令、workspace 逻辑 | 不相关模块 |
| API Key 轮转/过期机制 | 非需求要求 |
| 多设备登录 | 非需求要求 |
| 角色权限体系 | 非需求要求 |
| `_api_keys.json` 数据格式 | 不改动现有序列化格式 |
| `persistence.get_api_keys()` / `set_api_keys()` 接口 | 不改动现有 API |

---

## 8. 风险与回退

### 8.1 风险评估

| # | 风险 | 等级 | 缓解措施 |
|:-:|:-----|:----:|:---------|
| 1 | A1 全角/半角 display_name 误判为不同 | 🟡 中 | 文档注明：strip 后全等比较，全角空格不会被 trim，需要注册方自行规范 |
| 2 | C1 断连时 ws.close() 抛出异常 | 🟢 低 | try/except 包裹，逐连接容错 |
| 3 | B1 检查性能影响 | 🟢 低 | `persistence.get_api_keys()` 返回 dict 引用，get 是 O(1) 操作 |
| 4 | 部署后立即 B1 拦截正常连接 | 🟢 低 | B1 只拦截 `status=="revoked"` 的连接 |

### 8.2 回退方案

如果部署后出现异常：
1. 回退 A1：移除 `handle_register()` 中的 `find_agent_by_name()` 调用
2. 回退 B1：移除 `handler()` + `ws_handler()` 中的 B1 检查块
3. 回退 C1：移除 `_force_disconnect_revoked_agent()` 及其调用处
4. 最简回退：`git revert <commit-sha>` + `git push origin dev`

---

## 附录：完整改动对照表

| 文件 | 行号（当前） | 操作 | 代码摘要 |
|:----|:-----------|:----|:---------|
| `server/auth.py` | L165 之后 | ➕ 新增 | `find_agent_by_name()` 辅助函数 |
| `server/handler.py` | L232-L237 之间 | ➕ 插入 | A1: 调用 `auth.find_agent_by_name()` |
| `server/handler.py` | L6165 | ➕ 插入 | B1: key 活性检查 → continue |
| `server/__main__.py` | L104 | ➕ 插入 | B1: key 活性检查 → continue |
| `server/handler.py` | L200-206 | 无需改动 | B2: auth_ok 已无 role 字段 |
| `server/handler.py` | 模块级 | ➕ 新增 | C1: `_force_disconnect_revoked_agent()` |
| `server/handler.py` | revoke 调用处 | ➕ 插入 | C1: revoke 成功后调用断连 |

---

*本文档由 🏗️ 架构师（小开）编写，待 Step 3 💻 编码实现。*
