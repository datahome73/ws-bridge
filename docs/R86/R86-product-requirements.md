# R86 产品需求 — Agent API Key 注册认证加固 🛡️

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-09
> **基线：** `5b0d562`（dev — R85 测试记录）
> **前置条件：** R72 Agent API Key 认证体系已部署 ✅

---

## 1. 问题背景

### 1.1 现状

R72 已实现 Agent API Key 注册认证体系（`register` → `auth` 流程），但在实际运行中发现 3 个缺口：

| # | 现象 | 严重度 | 含义 |
|:-:|:-----|:------:|:------|
| 🔴 | **Bot 可以反复注册** — 同一名称的 bot 多次调用 `register`，每次都生成新的 `agent_id` + `api_key` | P0 | 「一虾多名」——注册不是一次性的，key 可无限生成 |
| 🔴 | **Register 后立即能发消息** — 新连接只要通过 `register` 获得 `agent_id`，该连接上所有消息都被接受，无需后续验证 | P0 | 注册环节本身成了 bypass——拿到 key 就能随便发 |
| 🟡 | **Auth_ok 含 role 字段** — R72 设计原则说 auth_ok 不含 role 字段（扁平角色），但实际可能因历史原因仍有 role 信息泄漏 | P1 | 设计原则与实际实现不一致 |

### 1.2 根因分析

| # | 根因 | 文件/行号 |
|:-:|:-----|:----------|
| 🔴 **A1** | `handle_register()` 不检查 `display_name` 是否已存在 `_api_keys.json` 中。每次调用生成新 `agent_id` + `api_key`，无重复注册防御 | `handler.py:L229-L270` |
| 🔴 **A2** | `handle_register()` 的 `agent_id` 生成用 `secrets.token_hex(6)`，每次随机生成——不基于 `display_name`，无法通过 display_name 查找到已有记录 | `auth.py:L131-L133` |
| 🟡 **B1** | `handler()` / `ws_handler()` 消息入口：`if msg_type == "message" and agent_id:` — 只要连接时通过了 `auth`/`register` 并设置了 `agent_id`，之后所有消息均无条件接受。无每消息 key 重验证 | `handler.py:L6165` / `__main__.py:L104` |
| 🟡 **B2** | `is_approved()` 只检查 `agent_id` 是否在 `_api_keys.json` 的 key 中——合法注册过的都返回 True。无额外活性/吊销检查 | `auth.py:L68-L74` |
| 🟢 **C1** | `handle_auth()` 可能在 auth_ok 响应中包含了 `role` 字段，与 R72 扁平角色设计原则冲突 | `handler.py:L188-L214` |

### 1.3 目标

> **R86 目标：Agent 注册认证体系加固——一虾一注册、无 key 不发信、吊销即封禁。** 与 meyo 社区模式对齐：未完成绑定的用户（无有效 key）不能发帖（发消息）。

---

## 2. 功能需求

### 设计原则

- **一虾一注册** — `display_name` 是唯一标识，同名不能重复注册
- **Key 即凭证** — 消息发送必须基于有效 key 验证
- **吊销即封禁** — 吊销 key 后即使连接还活着，消息也被拦截
- **非破坏性修复** — 不改变现有 `_api_keys.json` 数据结构，不删除已有 key

---

### 方向 A（核心）：一虾一注册守护 🔴 P0

#### A1 — `handle_register()` 加入 display_name 重复检测

**位置：** `server/handler.py` `async def handle_register()`

**当前代码（简化）：**
```python
async def handle_register(ws, msg):
    display_name = msg.get("display_name", "").strip()
    # ... 校验 display_name ...
    
    # 1. 生成新 agent_id（无重复检查）
    agent_id = auth.generate_agent_id()
    # 2. 生成新 api_key
    api_key = auth.create_api_key(agent_id)
    # 3. 直接持久化
    keys = persistence.get_api_keys()
    keys[agent_id] = { ... }
```

**改造后代码：**
```python
async def handle_register(ws, msg):
    display_name = msg.get("display_name", "").strip()
    if not display_name:
        await _send(ws, {"type": "auth_error", "error": "Missing display_name"})
        return None

    # A1: 检查 display_name 是否已注册
    keys = persistence.get_api_keys()
    existing = _find_agent_by_name(keys, display_name)
    if existing:
        await _send(ws, {
            "type": "auth_error",
            "error": f"'{display_name}' 已注册，请使用 auth 凭 api_key 登录。如需重新注册请联系管理员吊销旧 key。",
            "existing_agent_id": existing["agent_id"],
        })
        return None

    # ... 正常注册流程 ...
```

**辅助函数（在 handler.py 或 auth.py）：**
```python
def _find_agent_by_name(keys: dict, display_name: str) -> dict | None:
    """在所有 api_key 记录中查找 display_name 匹配项"""
    for agent_id, record in keys.items():
        if record.get("display_name") == display_name:
            return {"agent_id": agent_id, "record": record}
    return None
```

**比较：**

| 维度 | 当前 | 改造后 |
|:-----|:-----|:--------|
| 同名注册 | 允许多次，每次都生成新 key | 拒绝，提示已有注册 |
| 已有 key 的 bot 忘 key 了怎么办 | 无法找回，需管理员吊销旧 key 后重新注册 | 同上——需管理员介入（合理） |
| 误报检查 | 无 | `display_name` 全等比较，空格 trimmed |

#### A2 — `generate_agent_id()` 不修改，但增加 `_find_agent_by_name()` 辅助

`generate_agent_id()` 本身保持随机生成（`secrets.token_hex(6)`）——不影响。只需在 `handle_register` 中调用前先做 A1 检查。

**位置：** `server/auth.py`（或 `handler.py` 模块级函数）

---

### 方向 B（核心）：消息发送需经 key 验证 🔴 P0

#### B1 — 消息入口加入 per-connection key 活性检查

**位置：** `server/handler.py` `handler()` 和 `server/__main__.py` `ws_handler()`

**当前逻辑：**
```python
if msg_type == "message" and agent_id:
    await handle_broadcast(ws, agent_id, msg)
```

一旦 `agent_id` 设置，所有消息放行。即使该 key 已被吊销，当前连接仍能发消息。

**改造后：**
```python
if msg_type == "message" and agent_id:
    # B1: 检查此 agent 的 key 仍然有效
    agent_keys = persistence.get_api_keys()
    agent_key_record = agent_keys.get(agent_id)
    
    if not agent_key_record or agent_key_record.get("status") == "revoked":
        await _send(ws, {
            "type": "error",
            "error": "认证已失效：此 api_key 已被吊销。请重新注册。",
        })
        # 断开连接？或只拒绝消息？
        # 选择：只拒绝消息，不断连接（给客户端机会发新的 auth/register）
        continue  # skip this message, keep connection alive
    
    await handle_broadcast(ws, agent_id, msg)
```

**关键决策：**
| 选项 | 方案 | 选择理由 |
|:-----|:------|:---------|
| ❌ 断连 | 发现 key 吊销即关闭连接 | 过于激进——客户端可能只是想发 auth 重新认证 |
| ✅ **只拒绝消息** | 返回 error，连接保持 | 客户端可重新 auth/register，更友好 |
| ✅ **同类通道（inbox）也拦截** | inbox 消息同样检查 key 活性 | 无特殊豁免——所有消息都需有效 key |

**注意：** 此检查也覆盖 R82 inbox fast path——inbox 消息在 `handle_broadcast` 入口处（L5117）走 fast path 跳过 is_approved 检查，但 B1 检查在 `handler()`/`ws_handler()` 级别，在进入 `handle_broadcast` 之前就拦截了。

#### B2 — `handle_auth()` 确认 auth_ok 无 role 字段

**位置：** `server/handler.py` `handle_auth()`（L188-214）

检查 `auth_ok` 发送的 payload 是否包含 `role` 字段。如果包含，去掉。R72 设计原则：扁平角色模型，认证层不返回等级。

```python
# 检查当前 auth_ok payload
await _send(ws, {
    "type": "auth_ok",
    "agent_id": agent_id,
    "display_name": display_name,
    # 不应有: "role": "member" 或 "role": "admin"
})
```

---

### 方向 C（辅助）：吊销即封禁 🟡 P1

#### C1 — `revoke_api_key()` 后消息自动拦截

**位置：** B1 的 per-message 检查天然支持此功能。`revoke_api_key()` 将 `status` 设为 `"revoked"`，B1 的 `agent_key_record.get("status") == "revoked"` 即可拦截。

**额外保障：** 可选择在 `revoke_api_key()` 调用后主动关闭该 agent 的活跃连接：

```python
def _force_disconnect_revoked_agent(agent_id: str):
    """吊销 api_key 后立即断开该 agent 的所有连接"""
    for conn in list(_connections.get(agent_id, set())):
        try:
            if hasattr(conn, "close"):
                asyncio.create_task(conn.close())
        except Exception:
            pass
    _connections.pop(agent_id, None)
```

| 选项 | 方案 | 选择 |
|:-----|:------|:----:|
| ✅ 断开连接 | 吊销后立即关闭所有活跃连接 | 更干净——旧会话不再存在 |
| ❌ 只拒绝消息 | 连接保持但消息被拒 | 比较温和，但旧连接残留不安全 |
| **推荐：断开连接** | 吊销即踢下线 | 与 meyo「吊销即封禁」对齐 |

**调用时机：** `revoke_api_key()` 末尾（`handler.py` 中调用处）。

---

## 3. 验收标准

### 🎯 3.1 方向 A：一虾一注册

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 同名重复注册被拒 | bot 发 `register{display_name="小开"}` 第二次时，返回 `auth_error`：`"小开" 已注册` | WS 发 2 次 register，检查第 2 次响应 |
| ✅-2 | 首次注册正常 | 新 display_name 正常注册，返回 `agent_id` + `api_key` | WS 发 register 并检查 register_ok |
| ✅-3 | _api_keys.json 无重复名 | 同名注册失败后，文件中该 display_name 只有一条记录 | 读 `_api_keys.json` 确认 |
| ✅-4 | 空格 trimmed 后仍可检测同名 | `display_name=" 小开"` 和 `"小开"` 视为重复 | 测试带前后空格的 register |
| ✅-5 | 已有 key 的 bot 可正常 auth | 用正确的 api_key auth，正常通过 | WS 发 auth(api_key) → auth_ok |

### 🎯 3.2 方向 B：消息 key 验证

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-6 | 有效 key 消息正常发送 | 正常 register/auth 后的连接，消息正常路由 | 发 message → 消息送达 |
| ✅-7 | 吊销 key 后消息被拒 | B1 拦截，返回 `error: 认证已失效`，连接不断 | register → revoke → 发 message → 看到 error |
| ✅-8 | 吊销后重 auth 恢复 | 发新的 auth(新 api_key) 成功后，消息正常 | revoke → auth(new_key) → message → 正常 |
| ✅-9 | auth_ok 无 role 字段 | `auth_ok` 不包含 `"role"` 字段 | grep/auth_ok payload 确认 |

### 🎯 3.3 方向 C：吊销即封禁

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-10 | `revoke_api_key` 后连接断开 | agent 的 WS 连接被关闭（或至少被拒消息） | register → revoke → 观察连接状态 |
| ✅-11 | 吊销后重新 register 正常 | 旧 key 吊销后，同名 bot 可以重新 register（新 agent_id+key） | revoke → register(同名) → register_ok |
| ✅-12 | 旧 key 不可用 | 吊销后携旧 key auth 被拒 | revoke → auth(旧 key) → auth_error |

---

## 4. 不纳入范围

| 事项 | 原因 |
|:-----|:------|
| **Web 端改动** | 纯服务端认证加固，Web 端无影响 |
| **API Key 轮转/过期机制** | B1 只做吊销检查，key 过期自动轮转是后续功能 |
| **多设备同 bot 登录** | 当前体系允许同一 display_name 多连接（连接级 agent_id 不同）——但方向 A 禁止同名注册后，每个 display_name 对应一个 agent_id，多设备连接都 auth 同一个 agent_id 是允许的 |
| **角色/权限体系变更** | B2 只检查 auth_ok 的 role 字段，不改动角色判断逻辑 |
| **前端 bot 配置修改** | key 相关的 bot 配置由各 bot 自己管理 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 5min |
| **2** | 👷 Arch | 技术方案 | 10min |
| **3** | 👨‍💻 Dev | 编码实现 | 15min |
| **4** | 👀 Review | 代码审查 | 10min |
| **5** | 🦐 QA | 测试报告 | 10min |
| **6** | 🛠️ Operations | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **修改** — `handle_register()` 增加重复名检查 + 消息入口加 per-message key 活性检查 | ~25 行 |
| `server/__main__.py` | **修改** — `ws_handler()` 消息入口加 per-message key 活性检查 | ~15 行 |
| `server/auth.py` | **新增** — `find_agent_by_name()` 辅助函数（或在 handler.py 中实现） | ~10 行 |
| **合计** | | **~50 行净增** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| 部署后旧设备连接被吊销拦截 | 正在运行的 bot 突然发不了消息 | B1 只检查 active/revoked 状态，已注册的 active key 不受影响。只在管理员手动 revoke 后才会拦截 |
| A1 重复注册检查误拦 | display_name 空格/全角半角问题 | A1-4 要求空格 trimmed 后传入 |
| **部署顺序风险** | 服务端先部署 B1 但客户端未更新配置 | B1 只影响 key 被 `revoke` 的 agent——正常 active key 不受影响，部署后零影响 |

---

## 6. 脱敏检查清单

- [ ] docs/R86/*.md 零内部名残留（frontmatter 除外）
- [ ] `grep -nE '^(小|@)\w+' docs/R86/*.md` 零匹配（frontmatter 区允许）
- [ ] 使用通用角色名（PM / arch / dev / review / QA / operations）
- [ ] 不包含真实 agent_id / token / URL
