# R72 工作计划 — Bot 统一认证与能力注册体系 🎯

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** 📋 定稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R72/R72-product-requirements.md v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动集中，严禁 scope creep**
- 不改入：前端 Web UI（仅确保 `auth_ok` 新格式不报错）
- 不改入：权限体系（RBAC）、a2a 协议兼容
- 不改入：Web 端 HTTP REST 端点（全部走 WSS 协议）
- 不改入：旧配对码/approved_users 代码的全量清理（仅标记 deprecated + 不再使用）
- 编码者超出 scope 的改动，审查者直接打回

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | admin | arch | — |

### 0.3 架构纪要（R72 关键设计）

**WSS 单协议注册流程：**
```
connect → register → register_ok (同一连接继续)
connect → auth(api_key) → auth_ok (已注册 bot 重连)
```

**处理 register 前连接可发 register；处理 auth 前连接不可收发消息（与旧 auth 一致）**

**handle_auth 改造：**
- 原 `handle_auth()` 接收 `agent_id + app_id` → 替换为接收 `api_key` 纯新路径
- 旧 `agent_id + app_id + pairing_code + approve` 路径全面移除
- 新函数增加 `handle_register()` 处理注册请求

**agent_card_register：** 在 handler.py 的消息分发中新增一个 `elif` 分支，不走被 `BROADCAST_ADMINS` 拦截的 `handle_broadcast` 路径——认证协议消息直接在 `handler()` 顶层分发。

---

## 1. 管线总览

### 改动范围

6 个文件，精确改动点：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A1 | protocol.py 新增注册/卡片消息类型 + FIELD_API_KEY + deprecate 标记 | `shared/protocol.py` L11-17, L160-162 | ~20 行 |
| 2 | A3 | persistence.py 新增 _api_keys 存储 + get/save/load 函数 | `server/persistence.py` | ~25 行 |
| 3 | A1/A3 | auth.py 新增 generate_agent_id / create_api_key / validate_api_key / revoke_api_key | `server/auth.py` | ~80 行 |
| 4 | A2/A4 | handler.py handle_auth 替换为纯 api_key + handle_register 新增 + 消息分发 | `server/handler.py` L148-230, L5072-5120, ~L5746 | ~80 行 |
| 5 | B1/B2 | agent_card.py 新增 register_from_agent() 接受 bot 自主注册 | `server/agent_card.py` | ~50 行 |
| 6 | — | config.py 清除旧配置项（如有） | `server/config.py` | ~3 行 |

**总估算：** ~258 行净增，~30 行修改，~20 行 deprecate，零行删除

### 编码顺序（依赖关系）

```
protocol.py (常量定义, 无依赖)
  ├─ persistence.py (_api_keys 存储, 依赖 protocol FIELD_API_KEY)
  ├─ auth.py (api_key 逻辑, 依赖 persistence)
  │   └─ handler.py handle_auth + handle_register (依赖 auth + protocol)
  └─ agent_card.py (自注册, 依赖 protocol)
      └─ handler.py agent_card_register 路由 (依赖 agent_card + protocol)
          └─ config.py (收尾清理)
```

### 改动细节

#### ① `shared/protocol.py` — 协议常量

```python
# ── R72: 注册/登录新体系 ──
MSG_REGISTER = "register"              # C→S: 新 bot 注册
MSG_REGISTER_OK = "register_ok"        # S→C: 注册成功
MSG_AGENT_CARD_REGISTER = "agent_card_register"        # C→S: bot 自主注册 Agent Card
MSG_AGENT_CARD_REGISTER_OK = "agent_card_register_ok"  # S→C: 卡片注册确认
FIELD_API_KEY = "api_key"

# ── 旧体系 deprecate（保留常量值但不使用）──
# MSG_PAIRING_CODE — 不再使用
# MSG_APPROVE / MSG_APPROVE_OK / MSG_APPROVE_ERROR — 不再使用
# ROLE_UNREGISTERED — 不再使用
```

**注意：** 不要删除常量定义，只加注释标记 deprecated。R74+ 再清理。

#### ② `server/persistence.py` — 新增 api_key 存储

新增模块级变量：

```python
_api_keys: dict = {}  # agent_id → {api_key, display_name, created_at, ...}
```

新增函数（仿照 `_pairing_codes` 的 `_load_json`/`_save_json_atomic` 模式）：

```python
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
    with _lock:
        _api_keys = dict(keys)
```

**注意：** 在 `__init__.py` 或 `__main__.py` 的启动加载路径中，增加 `load_api_keys(config.DATA_DIR)` 调用。

#### ③ `server/auth.py` — API Key 核心逻辑

新增函数：

```python
import hashlib, secrets, time

# 服务端签名密钥（从环境变量读取，保底用随机值）
_SIGNING_KEY = os.environ.get("WS_API_SIGNING_KEY", secrets.token_hex(32))

def generate_agent_id() -> str:
    """生成 ws-bridge 自有 agent_id，格式 ws_{12位随机hex}"""
    return "ws_" + secrets.token_hex(6)

def create_api_key(agent_id: str) -> str:
    """生成 api_key，格式 sk_ws_{sha256(agent_id + signing_key + nonce)}"""
    nonce = secrets.token_hex(8)
    raw = f"{agent_id}:{_SIGNING_KEY}:{nonce}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"sk_ws_{key_hash}"

def validate_api_key(api_key: str) -> str | None:
    """验证 api_key 并返回对应的 agent_id，无效返回 None"""
    # 1. 格式检查
    if not api_key.startswith("sk_ws_") or len(api_key) < 40:
        return None
    # 2. 遍历 _api_keys 匹配
    from . import persistence
    keys = persistence.get_api_keys()
    for agent_id, record in keys.items():
        if record.get("api_key") == api_key and record.get("status") != "revoked":
            return agent_id
    return None

def revoke_api_key(agent_id: str) -> bool:
    """吊销 agent 的 api_key"""
    from . import persistence
    keys = persistence.get_api_keys()
    if agent_id not in keys:
        return False
    keys[agent_id]["status"] = "revoked"
    persistence.set_api_keys(keys)
    return True
```

**注意：**
- `_SIGNING_KEY` 可使用环境变量 `WS_API_SIGNING_KEY` 覆写，保底用 `secrets.token_hex(32)`
- `validate_api_key` 遍历查找——`_api_keys` 通常 < 100 个 key，性能可接受
- 旧函数（`generate_code`, `create_pairing_code`, `approve`, `is_approved`）保持不动，但不再被 `handler.py` 调用

#### ④ `server/handler.py` — 服务端路由改造

**A. handle_auth() 替换（L148-190）**

```python
async def handle_auth(ws, msg: dict) -> str | None:
    """R72: api_key 认证。不再支持 agent_id + app_id + pairing_code。"""
    api_key = msg.get("api_key", "").strip()
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

**B. handle_register() 新增**

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
    
    # 4. 注册 inbox channel（继承 R68 机制）
    persistence.set_agent_channel(agent_id, persistence.get_inbox_channel(agent_id))
    
    # 5. 返回凭证（同一连接继续使用）
    await _send(ws, {
        "type": "register_ok",
        "agent_id": agent_id,
        "api_key": api_key,
        "display_name": display_name,
        "created_at": time.time(),
        p.FIELD_ACTIVE_CHANNEL: p.LOBBY,
    })
    logger.info("Agent registered: %s (%s)", agent_id[:20], display_name)
    return agent_id
```

**C. handler() 消息分发送新增 2 个 elif（L5086 附近）**

在现有 `if msg_type == "auth"` 分支后面，新增：

```python
elif msg_type == "register" and agent_id is None:
    agent_id = await handle_register(ws, msg)
    if agent_id:
        _connections.setdefault(agent_id, set()).add(ws)
        logger.info("Agent %s registered and connected (%d total)",
                    agent_id[:20], sum(len(c) for c in _connections.values()))

elif msg_type == p.MSG_AGENT_CARD_REGISTER and agent_id:
    # Bot 自主注册 Agent Card
    result = await handle_agent_card_register(agent_id, msg)
    await _send(ws, result)
```

**D. handle_agent_card_register() 新增**

```python
async def handle_agent_card_register(agent_id: str, msg: dict) -> dict:
    """R72: Bot 自注册/更新 Agent Card。"""
    pipeline_roles = msg.get("pipeline_roles", [])
    capabilities = msg.get("capabilities", [])
    trigger_prefs = msg.get("trigger_preferences", {})
    
    card = ac_mod.get_agent_card(agent_id) or {}
    card["pipeline_roles"] = pipeline_roles
    card["capabilities"] = capabilities
    if trigger_prefs:
        card["trigger_preference"] = trigger_prefs
    card["last_updated_at"] = time.time()
    
    ac_mod.update_card(agent_id, card)
    
    # 自动更新 _ROLE_AGENT_MAP
    for role in pipeline_roles:
        if role not in _ROLE_AGENT_MAP:
            _ROLE_AGENT_MAP[role] = []
        if agent_id not in _ROLE_AGENT_MAP[role]:
            _ROLE_AGENT_MAP[role].append(agent_id)
    
    return {"type": p.MSG_AGENT_CARD_REGISTER_OK, "agent_id": agent_id}
```

**E. 旧路径清理：**
- 删除 `handle_auth()` 中 `agent_id + app_id` 认证分支
- 删除 `pairing_code` 自动审批分支
- 删除 `handler()` 中的 `"approve"` 消息分支（admin 不再能 `!approve`）
- handler() 消息循环中 `MSG_REGISTER_AGENT` 分支（L5746）标记 deprecated 但不删除

#### ⑤ `server/agent_card.py` — Agent Card 自注册

`register_agent()` 已支持 `pipeline_roles` 参数。新增一个更面向 bot 自主注册的封装：

```python
def register_from_agent(agent_id: str, card_data: dict) -> dict:
    """Bot 自主注册/更新 Agent Card。
    
    card_data 格式：
    {
        "pipeline_roles": ["arch", "dev"],
        "capabilities": ["...", "..."],
        "trigger_preferences": {...}
    }
    """
    now = time.time()
    existing = _cards.get(agent_id, {})
    
    # 保留已有字段（name, registered_at 等），更新能力字段
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

**注意：** `register_agent()` 与 `register_from_agent()` 共存——前者用于 admin 手动操作兜底，后者用于 bot 自主注册。

#### ⑥ `server/config.py` — 配置清理

- 确认 `PIPELINE_ARCH_FROM_NAME` 等引用旧 bot 名的配置项是否需要标记 deprecated
- 不新增配置开关（`ENABLE_API_KEY_AUTH` 不在本轮使用）

---

## 2. 管线步骤

### Step 1：管线启动 + 配置通知晨会（PM）

**前置条件：** 需求文档审核通过 ✅

**操作：**
- `!pipeline_start R72 --work_plan_url <raw_url>`
- 确认全员上线

### Step 2：技术方案（Arch）

**角色：** arch — 技术方案文档

**任务内容：**
1. 阅读需求文档方向 A/B/C 全部需求
2. 输出技术方案文档 `docs/R72/R72-tech-plan.md`，含：
   - 文件级改动列表（与 WORK_PLAN §1 一致）
   - `handle_auth()` 替换前后的完整代码对比
   - `handle_register()` 流程图
   - `_api_keys.json` 文件格式定义
   - api_key 生成/验证算法细节
   - Agent Card 自注册与 `_ROLE_AGENT_MAP` 联动方案
   - 部署上线顺序风险缓解方案
3. 验证编码顺序（协议→持久化→auth→handler→agent_card→config）合理

**交付物：** `docs/R72/R72-tech-plan.md` → push dev

### Step 3：编码（Dev）

**角色：** dev — 编码实现

**编码顺序（严格遵循依赖关系）：**

| 波次 | 文件 | 内容 | 依赖 |
|:----:|:-----|:------|:-----|
| 第一波 | `shared/protocol.py` | 新增 register/register_ok/agent_card_register/agent_card_register_ok + FIELD_API_KEY + deprecate 标记 | 无 |
| 第二波 | `server/persistence.py` | 新增 `_api_keys` 模块变量 + load_api_keys / save_api_keys / get_api_keys / set_api_keys | 无 |
| 第三波 | `server/auth.py` | 新增 generate_agent_id / create_api_key / validate_api_key / revoke_api_key | persistence |
| 第四波 | `server/handler.py` | 替换 handle_auth + 新增 handle_register + handle_agent_card_register + 消息分发 + 清理旧路径 | auth + protocol + agent_card |
| 第五波 | `server/agent_card.py` | 新增 register_from_agent() | protocol |
| 第六波 | `server/config.py` | 配置清理 | 无 |
| 第七波 | `__main__.py` / `handler.py` 入口 | 增加 `load_api_keys(config.DATA_DIR)` 启动加载 | 所有 |

**关键约束：**
1. **每波编码后 grep 验证：** 旧 `agent_id + app_id + pairing_code + approve` 引用是否已清理
2. **handle_auth 必须是原子替换：** 不能出现「部分替换」中间态，否则旧连接和新连接都失败
3. **register 应答后同一连接立即生效（`agent_id` 赋值 + `_connections` 注册）**
4. **旧 `MSG_REGISTER_AGENT` 路径（L5746）不动**——仅标记 deprecate 注释

**交付物：** commit SHA on dev

### Step 4：审查（Review）

**角色：** review — 代码审查

**审查重点：**
1. **scope 合规** — 没有引入不在范围内的改动（RBAC、HTTP 端点、前端 UI）
2. **handle_auth 原子替换** — 确认旧 agent_id + app_id + pairing_code 路径已完全移除
3. **register 同一连接生效** — `handle_register()` 后 `agent_id` 变量赋值 + `_connections` 注册
4. **api_key 安全** — `_SIGNING_KEY` 从环境变量读取，保底 `secrets.token_hex(32)`
5. **持久化正确** — `_api_keys.json` 写入 `DATA_DIR/config/` 目录
6. **agent_card_register → _ROLE_AGENT_MAP 联动**
7. **启动加载** — `load_api_keys()` 在 `__main__.py`/handler 入口执行

**交付物：** `docs/R72/R72-review-report.md` → push dev

### Step 5：测试（QA）

**角色：** QA — 全量测试

**测试矩阵（对应验收标准 15 项）：**

| # | 测试 | 方法 | 验证工具 |
|:-:|:-----|:------|:---------|
| ✅-A1 | register → register_ok | 原始 WS 发 register | 检查响应含 agent_id + api_key |
| ✅-A2 | agent_id 格式 ws_ | 检查 register_ok 的 agent_id | 前缀匹配 ws_ |
| ✅-A3 | api_key 格式 sk_ws_ | 查看 api_key 字段 | 前缀匹配 sk_ws_ |
| ✅-A4 | auth(api_key) → auth_ok 无 role | 用 api_key 发 auth | 响应无 role 字段 |
| ✅-A5 | register 后同一连接发消息 | register 后立即发 message | 消息送达 |
| ✅-A6 | 重启后 api_key 仍有效 | 记录 key → 重启 → auth | auth_ok |
| ✅-A7 | 无效 api_key → auth_error | 发 sk_ws_fake | auth_error |
| ✅-A8 | 旧 agent_id+app_id → auth_error | 用旧凭证 | auth_error |
| ✅-B1 | agent_card_register → ok | 注册后发卡片注册 | register_ok |
| ✅-B2 | 卡片注册后 _ROLE_AGENT_MAP 更新 | 查映射表 | !agent_role_map 验证 |
| ✅-B3 | 卡片持久化 | 注册 → 重启 → 查 | !agent_card_list |
| ✅-B4 | 重复注册覆盖 | 先 arch → 再 dev | 最后 role=dev |
| ✅-B5 | 管线按 pipeline_roles 匹配 | 注册 arch 卡片 → 启动管线 | 点名到 arch bot |
| ✅-C2 | 注册→auth→消息全流程 | 完整模拟 | 端到端 |
| ✅-C3 | 卡片出现在 !agent_card_list | 按 agent_id 查 | 存在 |
| ✅-C4 | 管线启动按卡片角色点名 | 注册卡片 → pipeline_start | 点名正确 |

**dev 环境测试：** 用测试 agent 在 dev 容器独立测试，不影响 main 生产环境。

**交付物：** `docs/R72/R72-test-report.md` → push dev

### Step 6：合并部署归档（Admin）

**角色：** admin — 合并部署

**操作：**
1. 确认 Step 5 测试全绿通过
2. `git fetch origin dev && git log --oneline dev..origin/dev` 确认无分歧
3. 合并 dev → main
4. **重新 build 镜像**（`docker build -t ws-bridge:r72 .`）
5. 替换生产容器
6. 验证新认证可用：PM bot 立即 register → auth → 发测试消息
7. 更新 TODO.md 版本号
8. 关闭工作室 + 归档

**⚠️ R70 教训：** git push 后必须 rebuild 镜像，仅 restart 容器不生效。

---

## 3. 验收清单（从需求文档复制）

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-A1 | register → register_ok 含 agent_id + api_key | ⏳ |
| ✅-A2 | agent_id 格式 ws_，非 meyo 01J 格式 | ⏳ |
| ✅-A3 | api_key 格式 sk_ws_ | ⏳ |
| ✅-A4 | auth(api_key) → auth_ok 无 role 字段 | ⏳ |
| ✅-A5 | register 后同一连接可收发消息（无需断连） | ⏳ |
| ✅-A6 | 持久化到 _api_keys.json，重启有效 | ⏳ |
| ✅-A7 | 无效 api_key → auth_error | ⏳ |
| ✅-A8 | 旧 agent_id+app_id → auth_error（不再接受） | ⏳ |
| ✅-B1 | agent_card_register → agent_card_register_ok | ⏳ |
| ✅-B2 | 卡片注册后 _ROLE_AGENT_MAP 自动更新 | ⏳ |
| ✅-B3 | 卡片持久化到 config/agent_cards.json | ⏳ |
| ✅-B4 | 同一 bot 重复注册覆盖旧卡片 | ⏳ |
| ✅-B5 | 管线按 pipeline_roles 匹配 bot | ⏳ |
| ✅-C1 | 部署后旧 agent_id+app_id 全线失效 | ⏳ |
| ✅-C2 | 新 bot 注册 → auth → 消息全流程 | ⏳ |
| ✅-C3 | 新 bot 卡片出现在 !agent_card_list | ⏳ |
| ✅-C4 | 管线启动按 Agent Card 角色点名 | ⏳ |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-06 | 初稿 — R72 工作计划 |
