# R72 技术方案 — Bot 统一认证与 Agent Card 自注册体系 🏗️

> **版本：** v1.0
> **状态：** 📝 初稿
> **架构师：** 👷 Arch
> **日期：** 2026-07-06
> **基线：** `git fetch origin dev` 确认最新代码
> **基于：** docs/R72/R72-product-requirements.md v1.0 ✅ + docs/R72/WORK_PLAN.md v1.0 ✅

---

## 1. 改动文件总览

| # | 方向 | 文件 | 改动类型 | 估算行 | 依赖 |
|:-:|:----:|:-----|:---------|:------:|:----:|
| 1 | A1 | `shared/protocol.py` | 新增 register/register_ok/agent_card_register/agent_card_register_ok 常量 + FIELD_API_KEY + deprecate 标记 | ~20 | 无 |
| 2 | A3 | `server/persistence.py` | 新增 `_api_keys` 模块变量 + load/save/get/set 四个函数 | ~25 | 无 |
| 3 | A1/A3 | `server/auth.py` | 新增 generate_agent_id / create_api_key / validate_api_key / revoke_api_key | ~80 | persistence |
| 4 | A2/A4 | `server/handler.py` | handle_auth 替换 + handle_register + handle_agent_card_register + 消息分发 + 旧路径清理 | ~80 | auth + protocol + agent_card |
| 5 | B1/B2 | `server/agent_card.py` | 新增 register_from_agent() + 自动更新 _ROLE_AGENT_MAP | ~50 | protocol |
| 6 | — | `server/config.py` | 无清理必要（无 PIPELINE_xxx_FROM_NAME 引用旧 bot 名需 deprecate） | ~0 | 无 |
| 7 | — | `server/__main__.py` | 增加 load_api_keys() 启动加载调用 | ~3 | 所有 |
| **合计** | | | | **~258 行净增** | |

---

## 2. 当前代码分析

### 2.1 当前 `handle_auth()` 流程（将被替换）

```python
# handler.py L148-220 — 4 条并行路径
async def handle_auth(ws, msg):
    agent_id = msg.get("agent_id")
    app_id = msg.get("app_id")
    code = msg.get("code")
    last_seen_ts = msg.get("last_seen_ts", 0)

    if not agent_id or not app_id:
        return auth_error("Missing agent_id or app_id")

    # 路径 1: 已注册 → auth_ok（带 role 等级）
    if auth.is_approved(agent_id):
        role = auth.get_users()[agent_id].get("role", "member")
        send auth_ok(agent_id, role)  ← **返回 role 等级字段**
        return agent_id

    # 路径 2: 有配对码 → approve → auth_ok
    if code:
        result = auth.approve(code)
        if approve_ok:
            send auth_ok(...)
            return agent_id
        return None

    # 路径 3: 未注册 → 生成配对码 → 走注册通道
    new_code = auth.generate_code()
    auth.create_pairing_code(...)
    send auth_ok(role=ROLE_UNREGISTERED, pairing_code=new_code)
    return None  ← **不登录，等 admin 手工 approve**
```

**问题：**
- 依赖 meyo `agent_id` + `app_id`（外部平台签发）
- role 字段表达「权限等级」而非「能力分类」
- 需要 admin 手工 approve，bot 不能自主登录
- 无 api_key 概念，无真正秘密

### 2.2 当前 handle_auth 调用点

**入口 1 — handler.py `handler()` (L5085)：**
```python
if msg_type == "auth" and agent_id is None:
    agent_id = await handle_auth(ws, msg)
    if agent_id:
        _connections.setdefault(agent_id, set()).add(ws)
```

**入口 2 — `__main__.py` `ws_handler()` (L92)：**
```python
if msg_type == "auth" and agent_id is None:
    agent_id = await handle_auth(ws, data)
```

**注意：** `__main__.py` 的 `ws_handler` 也调用了 `handle_auth`（从 handler.py import），所以替换 handler.py 的函数后两个入口都会自动用上新逻辑。

### 2.3 当前 handler 消息分发（L5085-5099）

```python
if msg_type == "auth" and agent_id is None:
    agent_id = await handle_auth(ws, msg)  # ← 替换
elif msg_type == "message" and agent_id:
    await handle_broadcast(ws, agent_id, msg)
elif msg_type == "approve" and agent_id:  # ← 删除
    # admin approve pairing code
elif msg_type == MSG_WORKSPACE_CREATE and agent_id:
    ...
```

### 2.4 当前旧注册路径（L5746）

```python
elif msg_type == MSG_REGISTER_AGENT and agent_id:
    # 仅 admin 可执行（R23 遗留路径）
    # 通过 _approved_users 注册
    # 标记 deprecated，不动
```

---

## 3. 改造后代码设计

### 3.1 新 `handle_auth()` — 纯 api_key 认证

```python
async def handle_auth(ws, msg: dict) -> str | None:
    """R72: api_key 认证。不再支持 agent_id + app_id + pairing_code。"""
    api_key = msg.get(p.FIELD_API_KEY, "").strip()
    if not api_key:
        await _send(ws, {"type": "auth_error", "error": "Missing api_key"})
        return None

    agent_id = auth.validate_api_key(api_key)
    if not agent_id:
        await _send(ws, {"type": "auth_error", "error": "Invalid api_key"})
        return None

    display_name = persistence.get_api_keys().get(agent_id, {}).get("display_name", agent_id)
    await _send(ws, {
        "type": "auth_ok",
        "agent_id": agent_id,
        "display_name": display_name,
        p.FIELD_ACTIVE_CHANNEL: persistence.get_agent_channel(agent_id) or p.LOBBY,
    })
    logger.info("Agent %s authenticated (api_key)", agent_id[:20])
    return agent_id
```

### 3.2 新 `handle_register()`

```python
async def handle_register(ws, msg: dict) -> str | None:
    """R72: 新 bot 注册。返回 agent_id + api_key，同一连接立即生效。"""
    display_name = msg.get("display_name", "").strip()
    if not display_name:
        await _send(ws, {"type": "auth_error", "error": "Missing display_name"})
        return None

    # 1. 生成 ws-bridge 自有 agent_id
    agent_id = auth.generate_agent_id()
    # 2. 生成 api_key
    api_key = auth.create_api_key(agent_id)
    # 3. 持久化到 _api_keys.json
    keys = persistence.get_api_keys()
    keys[agent_id] = {
        "api_key": api_key,
        "display_name": display_name,
        "description": msg.get("description", ""),
        "created_at": time.time(),
        "expires_at": None,
        "status": "active",
    }
    persistence.set_api_keys(keys)
    persistence.save_api_keys(config.DATA_DIR)

    # 4. 注册 inbox channel
    persistence.set_agent_channel(agent_id, persistence.get_inbox_channel(agent_id))

    # 5. 返回凭证（同一连接继续使用）
    await _send(ws, {
        "type": p.MSG_REGISTER_OK,
        "agent_id": agent_id,
        "api_key": api_key,
        "display_name": display_name,
        "created_at": time.time(),
        p.FIELD_ACTIVE_CHANNEL: p.LOBBY,
    })
    logger.info("Agent registered: %s (%s)", agent_id[:20], display_name)
    return agent_id
```

### 3.3 handle_auth 替换对比

| 维度 | 🔴 旧 | 🟢 新 |
|:-----|:------|:------|
| 入口参数 | `agent_id` + `app_id` + `code` | `api_key` 唯一 |
| 验证方式 | persistence.get_approved_users()  遍历 | auth.validate_api_key() 遍历 `_api_keys` |
| 成功应答 | `auth_ok` 含 `role` 字段（member/admin） | `auth_ok` **无** role 字段 |
| 失败处理 | 生成配对码→等 admin 手动 approve | 统一返回 `auth_error` |
| 重连 | 断连后 agent_id+app_id 重新认证 | 用 api_key 重新认证 |
| 关联旧代码 | 调用 auth.is_approved / auth.approve / auth.generate_code | **不调用** 任何旧 auth 函数 |

### 3.4 handle_register() 流程图

```
WSS connect
    │
    ├─ register msg received
    │     │
    │     ├─ display_name 为空? → auth_error("Missing display_name")
    │     │
    │     ├─ generate_agent_id()  → "ws_" + secrets.token_hex(6)
    │     ├─ create_api_key()     → "sk_ws_" + sha256(agent_id:signing_key:nonce)[:32]
    │     │
    │     ├─ 持久化到 _api_keys.json
    │     ├─ 设置 agent channel（含 inbox）
    │     │
    │     └─ send register_ok(agent_id, api_key, display_name)
    │         → 同一连接继续收发消息
    │
    └─ (后续) agent_card_register 声明能力
```

### 3.5 新消息分发（handler.py L5085 附近）

```python
if msg_type == p.MSG_AUTH and agent_id is None:
    agent_id = await handle_auth(ws, msg)
    if agent_id:
        _connections.setdefault(agent_id, set()).add(ws)

elif msg_type == p.MSG_REGISTER and agent_id is None:   # 新增
    agent_id = await handle_register(ws, msg)
    if agent_id:
        _connections.setdefault(agent_id, set()).add(ws)

elif msg_type == p.MSG_AGENT_CARD_REGISTER and agent_id:   # 新增
    result = await handle_agent_card_register(agent_id, msg)
    await _send(ws, result)

elif msg_type == "message" and agent_id:
    await handle_broadcast(ws, agent_id, msg)

# ★ 删除：elif msg_type == "approve" and agent_id:  ← 旧 approve 路径移除
```

### 3.6 删除旧路径清单

| 位置 | 内容 | 操作 |
|:-----|:------|:-----|
| handler.py L148-227 | `handle_auth()` 函数体 | **完整替换**为纯 api_key 版本 |
| handler.py L5094-5098 | `elif msg_type == "approve" and agent_id:` 分支 | **删除** |
| handler.py L5746-5783 | `MSG_REGISTER_AGENT` 分支 | **不动**（标记 deprecated 注释） |
| auth.py L1-99 | `generate_code()`, `create_pairing_code()`, `approve()`, `is_approved()`, `get_users()`, `role_level()` | **不动**（保留但不再被 handler 调用） |

---

## 4. API Key 生成与验证算法

### 4.1 生成算法

```python
import secrets, hashlib, os

# 服务端签名密钥（环境变量覆写，保底随机值）
_SIGNING_KEY = os.environ.get("WS_API_SIGNING_KEY", secrets.token_hex(32))

def generate_agent_id() -> str:
    """ws_{12位随机hex}"""
    return "ws_" + secrets.token_hex(6)  # 12 hex chars

def create_api_key(agent_id: str) -> str:
    """sk_ws_{sha256(agent_id:signing_key:nonce)[:32]}"""
    nonce = secrets.token_hex(8)  # 16 hex chars, fresh per call
    raw = f"{agent_id}:{_SIGNING_KEY}:{nonce}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"sk_ws_{key_hash}"
```

**安全要点：**

| 要素 | 说明 |
|:-----|:------|
| 签名密钥 `_SIGNING_KEY` | 环境变量 `WS_API_SIGNING_KEY` 覆写，未设置则用 `secrets.token_hex(32)`（64 hex chars = 256 bits） |
| nonce | 每次调用 `secrets.token_hex(8)` 保证同一 agent_id 的不同 api_key 不可预测 |
| hash 截断 | sha256 输出前 32 hex chars = 128 bits 熵，平衡安全性与 API Key 长度 |
| api_key 格式 | `sk_ws_` 前缀（32 chars hash）= 总共 41 chars |
| 服务端重启 | hash 不依赖运行时状态，重启后同一 environment 下旧 key 仍然可验证 |

### 4.2 验证算法

```python
def validate_api_key(api_key: str) -> str | None:
    """遍历 _api_keys 匹配，返回 agent_id 或 None"""
    if not api_key.startswith("sk_ws_") or len(api_key) < 40:
        return None
    keys = persistence.get_api_keys()
    for agent_id, record in keys.items():
        if record.get("api_key") == api_key and record.get("status") != "revoked":
            return agent_id
    return None
```

**性能说明：** `_api_keys` 通常 < 100 条记录，线性遍历性能可接受。如需优化可新增 `{api_key → agent_id}` 反向索引。

---

## 5. 持久化格式

### 5.1 `_api_keys.json` 存储于 `{DATA_DIR}/config/`

```json
{
  "ws_a1b2c3d4": {
    "api_key": "sk_ws_a1b2...xxxx...",
    "display_name": "架构师",
    "description": "架构师兼开发工程师",
    "created_at": 1712345678.123,
    "expires_at": null,
    "status": "active"
  }
}
```

### 5.2 persistence.py 新增函数（仿照现有模式）

```python
_api_keys: dict = {}  # agent_id → {api_key, display_name, ...}

def load_api_keys(data_dir: Path) -> None:
    global _api_keys
    _api_keys = _load_json(data_dir / "_api_keys.json")

def save_api_keys(data_dir: Path) -> None:
    with _lock:
        _save_json_atomic(data_dir / "_api_keys.json", _api_keys)

def get_api_keys() -> dict:
    with _lock:
        return dict(_api_keys)

def set_api_keys(keys: dict) -> None:
    global _api_keys
    with _lock:
        _api_keys = dict(keys)
```

### 5.3 启动加载（`__main__.py` 入口）

在 `load_pairing_codes`, `load_approved_users` 等已有调用旁新增：

```python
from .persistence import load_api_keys  # 新增 import
load_api_keys(DATA_DIR)  # 在启动时加载
```

---

## 6. Agent Card 自注册与 _ROLE_AGENT_MAP 联动

### 6.1 `register_from_agent()` 新增

```python
def register_from_agent(agent_id: str, card_data: dict) -> dict:
    """Bot 自主注册/更新 Agent Card。"""
    now = time.time()
    existing = _cards.get(agent_id, {})

    _cards[agent_id] = {
        **existing,
        "agent_id": agent_id,
        "pipeline_roles": card_data.get("pipeline_roles", existing.get("pipeline_roles", [])),
        "capabilities": card_data.get("capabilities", existing.get("capabilities", [])),
        "trigger_preference": card_data.get("trigger_preferences", existing.get("trigger_preference", {})),
        "last_updated_at": now,
        "status": "online",
    }
    save_cards()
    return _cards[agent_id]
```

**与现有 `register_agent()` 的差异：**

| 维度 | `register_agent()` (旧) | `register_from_agent()` (新) |
|:-----|:------------------------|:-----------------------------|
| 调用者 | admin 手动 `!agent_card set` | Bot 自主通过 WSS 发送 `agent_card_register` |
| 参数 | `agent_id, name, role, force` | `agent_id, card_data` (pipeline_roles + capabilities + trigger_preferences) |
| 角色来源 | `role` 参数（单个 string） | `pipeline_roles` 数组 |
| 离线恢复 | force=False 时仅更新 last_online | 覆盖式更新（bot 自注册意味着完整声明） |

### 6.2 handler.py 中 `handle_agent_card_register()`

```python
async def handle_agent_card_register(agent_id: str, msg: dict) -> dict:
    pipeline_roles = msg.get("pipeline_roles", [])
    capabilities = msg.get("capabilities", [])
    trigger_prefs = msg.get("trigger_preferences", {})

    card = ac_mod.register_from_agent(agent_id, {
        "pipeline_roles": pipeline_roles,
        "capabilities": capabilities,
        "trigger_preferences": trigger_prefs,
    })

    # 自动更新 _ROLE_AGENT_MAP
    for role in pipeline_roles:
        if role not in _ROLE_AGENT_MAP:
            _ROLE_AGENT_MAP[role] = []
        if agent_id not in _ROLE_AGENT_MAP[role]:
            _ROLE_AGENT_MAP[role].append(agent_id)

    return {"type": p.MSG_AGENT_CARD_REGISTER_OK, "agent_id": agent_id}
```

### 6.3 管线匹配流程（改造后）

```
Step 需要角色 "arch"
  → 查 _ROLE_AGENT_MAP["arch"] → 得到 [ws_xxx, ws_yyy]
  → 过滤在线 → 取第一个 → @点名
  → Bot 按 Agent Card 能力工作
```

### 6.4 与现有 `_refresh_role_agent_map()` 的关系

```python
# 现有函数（从 agent_cards.json 重建映射）
def _refresh_role_agent_map():
    cards = ac_mod.get_all_cards()
    new_map = {}
    for agent_id, card in cards.items():
        for role in card.get("pipeline_roles", []):
            new_map.setdefault(role, []).append(agent_id)
    global _ROLE_AGENT_MAP
    _ROLE_AGENT_MAP = new_map

# 改造后：register_from_agent 写卡 → _ROLE_AGENT_MAP 增量更新
# _refresh_role_agent_map() 作为兜底恢复函数保留
```

---

## 7. 部署顺序与风险缓解

### 7.1 部署时序

```
Step 1: PM bot 本地适配新客户端
        └── 支持 register + api_key auth
        └── 保存 _api_key 到本地 credentials.json

Step 2: 服务端部署新版
        └── git merge dev → main
        └── docker build -t ws-bridge:r72 .
        └── 替换生产容器
        └── ⚠️ 此瞬间旧 agent_id+app_id 认证失效

Step 3: PM bot 立即 register
        └── 夺回指挥权
        └── 发测试消息验证

Step 4: 逐个协调其他 bot 注册
        └── 通知 admin/arch/dev/review/qa bot 管理员
        └── 各 bot 走 register → agent_card_register
```

### 7.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| 🔴 部署瞬间断线无指挥 | PM 无法协调注册 | PM 先适配，部署后第一时间 register |
| 🔴 `_api_keys.json` 写入失败 | 注册后重启 key 丢失 | 使用已有 `_save_json_atomic` 原子写入模式 |
| 🟡 agent_card_register 时序 | Bot 注册卡片但还未有 pipeline_roles | `pipeline_roles` 默认为空列表，`_ROLE_AGENT_MAP` 不更新 |
| 🟡 旧 approve 路径未清理 | 无效代码残留 | grep 验证删除 |
| 🟡 两入口同时使用 | handler.py 和 __main__.py 都调 handle_auth | 函数替换后两入口自动生效 |

### 7.3 回滚方案

如果部署后 PM 无法注册：
```bash
# 方案 A: 恢复旧镜像
docker stop ws-bridge
docker run -d --name ws-bridge-old <old-image-tag>

# 方案 B: 紧急恢复旧认证（设置 WS_API_KEY_AUTH 环境变量）
# 不实现——R72 clean break 设计
```

---

## 8. 编码序列验证

编码顺序严格遵循依赖关系：

```
① protocol.py (无依赖)         ── 常量定义
   ↓
② persistence.py (无依赖)       ── 持久化接口
   ↓
③ auth.py (依赖 persistence)    ── 核心逻辑
   ↓
④ agent_card.py (依赖 protocol) ── 自注册（无 handler 依赖）
   ↓
⑤ handler.py (依赖 1-4)         ── 服务端路由（依赖最多，最后编码）
   ↓
⑥ __main__.py (依赖 5)          ── 启动加载
   ↓
⑦ config.py (收尾检查)          ── 确认无需清理的配置项
```

**关键约束：**
- ①→②→③→⑤ 必须在同一波次（handle_auth + handle_register 必须一次做完）
- ④→⑤ 的第二部分（agent_card_register 路由）可以由不同人编码
- 每波编码后 grep 验证旧路径残留

---

## 9. grep 验证清单

编码中和编码后执行：

```bash
# 确认 handle_auth 中无旧代码残留
grep -n "agent_id.*app_id" server/handler.py           # 应只有 import 行
grep -n "pairing_code\|pairing\|approve" server/handler.py  # 应在旧路径标记处
grep -n "is_approved\|get_users" server/handler.py     # 应在旧 approve 分支删除后清零

# 确认新常量已定义
grep -n "MSG_REGISTER\|MSG_REGISTER_OK\|MSG_AGENT_CARD_REGISTER\|FIELD_API_KEY" shared/protocol.py
```

---

## 10. 栈跟踪（改动影响范围）

```
handle_auth 被替换
  └─ handler.py L5085 调用 (websockets 入口)
  └─ __main__.py L92 调用 (aiohttp 入口)    ← 两个入口自动受益

handle_register 新增
  └─ handler.py 消息分发新增 elif 分支

handle_agent_card_register 新增
  └─ handler.py 消息分发新增 elif 分支
  └─ 调用 agent_card.register_from_agent()
  └─ 更新 _ROLE_AGENT_MAP

旧 approve 路径删除
  └─ handler.py L5094-5098 elif 分支删除
  └─ handler.py handle_auth 中 code/pairing_code 路径删除
  └─ handler.py L5746 MSG_REGISTER_AGENT 标记 deprecated（不动）

persistence 新增
  └─ auth.py import persistence
  └─ handler.py handle_register 中调用 persistence.*
  └─ __main__.py 新增 load_api_keys()
```

---

## 11. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-06 | 初稿 — R72 技术方案 |
