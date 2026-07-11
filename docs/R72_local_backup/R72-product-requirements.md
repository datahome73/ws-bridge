# R72 产品需求 — Bot 统一认证与能力注册体系 🎯

> **版本：** v1.0（初稿，待审核）
> **状态：** 📝 草稿
> **产品经理：** 🧐 PM
> **日期：** 2026-07-06
> **基线：** 先 `git fetch origin dev` 确认远程最新代码
> **本轮改动范围：** `shared/protocol.py` + `server/auth.py`（或新增 `server/auth_v2.py`）+ `server/handler.py` + `server/agent_card.py` + `server/config.py`
> **参考：** ARCHITECTURE-REQUIREMENTS.md §3.8（Agent 注册认证体系）、TODO.md F-16（Agent 角色映射）

---

## 1. 问题背景

### 1.1 现状：老化的 meyo 认证体系

当前 ws-bridge 的认证体系仍然沿用最早期的模式——依赖 meyo 社区的 agent ID 和配对码机制：

| 组件 | 实现 | 问题 |
|:-----|:-----|:-----|
| Agent ID | 来自 meyo 社区平台（`01JXYZ...`），非 ws-bridge 自有签发 | 认证依赖外部平台，ws-bridge 无自有身份体系 |
| 认证方式 | `agent_id + app_id` 明文匹配 `_approved_users` 列表 | 无加密凭证，无真正「秘密」概念 |
| 注册流程 | 配对码（8位字母数字）→ admin `!approve` → 加入 `_approved_users.json` | 需要人工审批环节，新 bot 无法自主加入 |
| 角色含义 | 等级制（admin=4, member=2, workspace_admin=3） | 角色表达的是「权限等级」而非「能力分类」 |
| 能力声明 | 无 / admin 手动 `!agent_card set` 分配 | Bot 自身无法声明自己会什么 |
| app_id | meyo 社区遗留字段（`298621237`） | 对 ws-bridge 无实际意义，纯历史包袱 |
| admin bot 定位 | admin bot——负责审批绑定码、中转消息（旧体系） | 最初的权宜设计，现在服务端已足够强大 |
| 凭证管理 | 无 credentials 概念 | Agent 每次连接需要记住 agent_id + app_id |

**当前 `handle_auth()` 流程（要重构的）：**

```python
# handler.py L148-227 — 三种路径
# 1. 已注册（_approved_users 中有）→ auth_ok（靠记住 agent_id）
# 2. 有配对码 → auth.approve() → auth_ok
# 3. 未注册 → 生成配对码 → 等 admin !approve
# 4. (新增) 有 api_key → 验证 api_key → auth_ok  ← R72 新增路径
```

### 1.2 根因分析

| # | 根因 | 说明 |
|:-:|:-----|:------|
| 1 | **服务端能力与认证体系不匹配** | ws-bridge 服务端已经从早期「消息中转站」演进为完整的管线/工作室/Agent Card/超时/ACK 系统，但认证体系还是最原始的配对码模型 |
| 2 | **没有自有身份体系** | Agent ID 依赖 meyo 社区签发，ws-bridge 无法独立管理 bot 身份生命周期 |
| 3 | **等级制角色模型过时** | `admin > member` 的等级划分是临时方案，现在应转向**功能性角色**——角色描述的是能力，不是权限 |
| 4 | **bot 无法自荐** | Bot 的能力声明需要 admin 手动 `!agent_card set`，没有 bot 自主注册的路径，与「A2A 协议」的去中心化精神相悖 |

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:-----|:------|
| 🔴 **基础设施缺陷** | 认证是 ws-bridge 的基础设施层。管线、工作室、Agent Card 都已完备，但下层认证还是 meyo 时代的老代码——基础不牢 |
| 🔴 **阻碍去 meyo 化** | 只要认证依赖 meyo agent ID，ws-bridge 就永远无法成为独立平台 |
| 🔴 **阻碍 A2A 兼容** | Agent Card 自注册 + 统一协议是 A2A 兼容的前置条件，也是 ws-bridge 通用化（不限于软件开发）的关键基础 |
| 🟡 **改动大，需要过渡** | 认证 + 协议 + Agent Card 自注册三向联动，改动的代码路径贯穿 `shared/protocol.py` → `server/auth.py` → `server/handler.py` → `server/agent_card.py`。**不能在一个轮次内贸然完成硬切换**，需要两轮过渡 |

---

## 2. 设计原则

> **WSS 单协议通路：** 注册、登录、消息通讯全部走同一套 WebSocket 协议（参考 MQTT 的 CONNECT/CONNACK/PUBLISH/SUBSCRIBE 模式），不引入独立的 HTTP REST 端点。
>
> **扁平角色模型：** 角色从「等级制（你能管多少）」转变为「功能制（你会什么）」。所有 bot 在认证层面平等，差异仅在于 Agent Card 上声明的能力。
>
> **无向后兼容——R72 部署即新体系：** R72 开发验证完成后部署上线的那一刻起，旧 `agent_id + app_id + pairing_code` 认证体系即被替代。不再保留旧路径。
>
> **R73 全员迁移+验证：** R72 部署后 → R73 轮所有 bot 统一重新注册 → 走完完整管线验证 → 发现 bug 就在 R73 内修完。

---

## 3. 功能需求

### 方向 A（核心）：统一 WSS 认证协议 🔴 P0

> 在现有 WSS 协议基础上，新增「注册」和「登录」两个消息类型，让 bot 可以自主注册并获得 API Key，后续用 API Key 认证。

#### A1 — 注册协议（register → register_ok）

新增一对消息类型，bot 通过 WSS 连接注册并获取凭证，注册后**在同一会话继续工作**，无需断连重连：

```json
// C→S: 注册请求
// 新建连接后第一个消息，相当于 MQTT 的 CONNECT
{
  "type": "register",
  "display_name": "架构师",
  "description": "架构师兼开发工程师"
}

// S→C: 注册成功（立即在同一连接上回复）
{
  "type": "register_ok",
  "agent_id": "ws_a1b2c3d4",
  "api_key": "sk_ws_xxxxxxxxxxxx...",
  "display_name": "架构师",
  "created_at": 1712345678
}
```

| 协议细节 | 说明 |
|:---------|:------|
| 消息类型 | 新增 `"register"` 和 `"register_ok"` 到 `shared/protocol.py` |
| agent_id 生成 | ws-bridge 自有签发，格式 `ws_{random}`（12位十六进制或随机字符串） |
| api_key 生成 | 格式 `sk_ws_` + `sha256(agent_id + server_secret + timestamp)[:32]`，含服务端密钥签名 |
| 会话状态 | register_ok 后该连接自动变为「已认证」状态，可直接收发消息 |
| 重连场景 | Bot 断开后重连时走 auth（见 A2），不走 register |

**与旧注册流程的对比：**

| 步骤 | 🔴 旧（配对码） | 🟢 新（register） |
|:-----|:-------------|:---------------|
| ① | 连接后未注册 → 生成配对码 → 通知 admin | 连接后发送 register → 服务端即时处理 |
| ② | admin `!approve ABC12345` 手动批准 | 无人工环节，即时注册 |
| ③ | 配对码的 agent 需断连重连后才能认证 | 同一连接直接变为已认证 |
| ④ | bot 无凭证文件概念 | 返回 api_key + agent_id，bot 可写入 `credentials.json` |

#### A2 — 登录协议（auth with api_key）

扩展现有的 `auth` 消息类型，支持 `api_key` 字段作为认证凭据：

```json
// C→S: 登录（已注册 bot 重连时使用，或 register 后的同一连接）
{
  "type": "auth",
  "api_key": "sk_ws_xxxxxxxxxxxx..."
}

// S→C: 登录成功（与现有 auth_ok 格式兼容，去除 role 字段）
{
  "type": "auth_ok",
  "agent_id": "ws_a1b2c3d4",
  "display_name": "架构师",
  "active_channel": "lobby"
}
```

| 关键变更 | 说明 |
|:---------|:------|
| **去除 `"role": "member"`** | 登录成功不再返回角色等级——角色由 Agent Card 决定，不是认证层的事 |
| **去除对 `app_id` 的依赖** | 新 auth 仅需 `api_key` 即可，无需 `app_id` |
| **旧路径保留** | `auth` 消息中带 `agent_id` + `app_id` 时，走旧认证逻辑（向后兼容） |
| **api_key 优先** | 如果 `auth` 消息同时有 `api_key` 和 `agent_id`/`app_id`，优先验证 `api_key` |

#### A3 — 服务端凭证管理

新增 `_api_keys.json` 持久化文件，管理所有签发的 API Key：

```json
{
  "ws_a1b2c3d4": {
    "api_key": "sk_ws_xxxxxxxxxxxx...",
    "display_name": "架构师",
    "description": "架构师兼开发工程师",
    "created_at": 1712345678,
    "expires_at": null,
    "status": "active"  // active | revoked
  }
}
```

| 文件/模块 | 说明 |
|:----------|:------|
| `server/auth.py`（扩展） | 新增 `create_api_key()`, `validate_api_key()`, `revoke_api_key()` |
| `server/persistence.py`（扩展） | 新增 `get_api_keys()`, `save_api_keys()` |
| `config/` 目录 | `_api_keys.json` 存放于 `DATA_DIR/config/` |

#### A4 — 服务端 auth 路由改造

`handle_auth()` 整体替换为 api_key 认证，不再保留旧路径：

```python
# handler.py handle_auth() — R72 新版（不再支持 agent_id + app_id）
async def handle_auth(ws, msg) -> str | None:
    api_key = msg.get("api_key", "").strip()
    
    if not api_key:
        await _send(ws, {"type": "auth_error", "error": "Missing api_key"})
        return None
    
    agent_id = validate_api_key(api_key)
    if not agent_id:
        await _send(ws, {"type": "auth_error", "error": "Invalid api_key"})
        return None
    
    # 验证通过 → auth_ok（无 role 字段）
    display_name = get_display_name(agent_id)
    await _send(ws, {
        "type": "auth_ok",
        "agent_id": agent_id,
        "display_name": display_name,
        p.FIELD_ACTIVE_CHANNEL: persistence.get_agent_channel(agent_id) or p.LOBBY,
    })
    return agent_id
```

同时新增 `handle_register()` 函数处理注册请求：

```python
async def handle_register(ws, msg) -> str | None:
    display_name = msg.get("display_name", "").strip()
    # 1. 生成 ws-bridge 自有 agent_id
    agent_id = generate_agent_id()
    # 2. 生成 api_key
    api_key = create_api_key(agent_id)
    # 3. 持久化
    save_api_key(agent_id, api_key, display_name, ...)
    # 4. 返回凭证
    await _send(ws, {"type": "register_ok", "agent_id": agent_id, "api_key": api_key, ...})
    # 5. 该连接自动视为已认证
    return agent_id
```

---

### 方向 B（核心）：Agent Card 自注册 🔴 P0

> Bot 注册获得凭证后，通过 WSS 自主向服务端声明自己的能力（角色、技能），替代当前 admin 手动 `!agent_card set` 模式。

#### B1 — Agent Card 自注册协议

```json
// C→S: 我有什么能力（auth 或 register 之后发送）
{
  "type": "agent_card_register",
  "pipeline_roles": ["arch", "dev"],
  "capabilities": ["微服务架构设计", "Python/Node.js开发", "系统设计与文档"],
  "trigger_preferences": {"mention_keyword": "架构师;arch"}
}

// S→C: 确认
{
  "type": "agent_card_register_ok",
  "agent_id": "ws_a1b2c3d4",
  "card_id": "card_xxxxx"
}
```

**核心变更：Agent Card 的所有权从 admin 转移到 bot 自身。**

| 行为 | 🔴 旧模式 | 🟢 新模式 |
|:-----|:---------|:---------|
| 谁创建卡片 | admin 执行 `!agent_card set` | Bot 自主发送 `agent_card_register` |
| 谁更新卡片 | admin 执行 `!agent_card set` | Bot 自主发送 `agent_card_register`（覆盖更新） |
| 谁删除卡片 | admin 执行 `!agent_card unset` | Bot 发送 `agent_card_unregister` 或 admin 吊销 |
| 角色映射建立 | server 从卡片被动重建 | server 注册卡片时自动更新 `_ROLE_AGENT_MAP` |
| 与管线匹配 | 无自动匹配 | 管线按 `pipeline_roles` 匹配 bot |

#### B2 — Agent Card → 管线角色映射

Bot 注册 Agent Card 后，服务端自动将其角色加入 `_ROLE_AGENT_MAP`：

```python
# 当前: admin 手动 !agent_card set
# R72: bot 注册卡片后自动建立映射

def _update_role_map_on_card_register(agent_id: str, card: dict):
    """Bot 注册/更新卡片时自动更新角色映射"""
    for role in card.get("pipeline_roles", []):
        if role not in _ROLE_AGENT_MAP:
            _ROLE_AGENT_MAP[role] = []
        if agent_id not in _ROLE_AGENT_MAP[role]:
            _ROLE_AGENT_MAP[role].append(agent_id)
```

**管线派活流程（改造后）：**

```
Step 需要角色 "arch"
  → 查 _ROLE_AGENT_MAP["arch"] → 得到 [agent_id_1, agent_id_2, ...]
  → 取在线优先 → 点名
  → Bot 收到点名 → 按 Agent Card 能力工作
```

#### B3 — Agent Card 数据结构升级

当前 Agent Card schema（`agent_card.py`）：

```python
{
    "agent_id": "...",
    "name": "...",
    "role": "member",              # ← 旧等级制角色
    "pipeline_roles": [],          # ← 功能性角色
    "capabilities": [],
    "trigger_preference": {},
}
```

R72 升级后（精简并聚焦）：

```python
{
    "agent_id": "ws_a1b2c3d4",
    "display_name": "架构师",
    "role": "member",              # 🔴 保留仅向后兼容，不参与任何新逻辑
    "pipeline_roles": ["arch", "dev"],  # ✅ 核心——决定能做什么管线 Step
    "capabilities": ["微服务架构设计", "Python/Node.js开发", "系统设计与文档"],
    "trigger_preference": {
        "mention_keyword": "架构师;arch"
    },
    "registered_at": 1712345678,
    "last_updated_at": 1712345678,
}
```

#### B4 — 管理命令更新

| 命令 | 行为变更 |
|:-----|:---------|
| `!agent_card list` | 继续保持——列出所有已注册卡片 |
| `!agent_card get <name>` | 继续保持——查看单个卡片详情 |
| `!agent_card set` | admin 手动覆盖——保留但标记为「手工干预」，后续建议弃用 |
| `!agent_card unset` | admin 手动移除——保留 |
| `!agent_card auto-register` | R63 功能保留——扫描在线未注册 bot 自动补全（降级为备用方案） |

**关键：** `!agent_card set` 不再是主流注册方式。Bot 自主注册是首选，admin 手动干预仅作为兜底。

---

### 方向 C（过渡）：R72 建 → R73 迁移验证 → R74+ 纯新体系 🟡 P1

> R72 的改动涉及认证全链路、协议层、Agent Card 系统。**R72 开发验证完成后部署上线那一刻起，旧认证体系即被替代**——无向后兼容、无过渡期。
>
> R73 轮是全员迁移+验证+修复轮：所有 bot 用新体系重新注册 → 跑完整管线 → 发现 bug 就在 R73 内逐个修完 → R74 起纯新体系运作。

#### C1 — R72（本轮）：架构搭建 + 功能完备 + 开发测试 + 部署上线

**目标：** 构建完整的新认证 + Agent Card 自注册体系，开发测试验收通过后部署上线。

| 阶段 | 内容 | 说明 |
|:-----|:------|:------|
| 协议定义 | `shared/protocol.py` 新增 register/register_ok/agent_card_register/agent_card_register_ok + 标记旧 MSG_PAIRING_CODE/MSG_APPROVE 为 deprecated（保留但不再使用） | 协议层是基础设施 |
| 凭证系统 | `server/auth.py` 扩展：`create_api_key()`/`validate_api_key()`/`revoke_api_key()`/`generate_agent_id()` + `_api_keys.json` 持久化 | 可独立测试 |
| 服务端路由 | `server/handler.py`：替换 `handle_auth()` 为纯 api_key 认证 + 新增 `handle_register()` + 新增 agent_card_register 路由 | 核心逻辑 |
| Agent Card 自注册 | `server/agent_card.py` 扩展：新增 `register_from_agent()` 让 bot 自主声明能力 + 自动更新 `_ROLE_AGENT_MAP` | 替代手动 `!agent_card set` |
| 旧认证废弃 | 清理 handler.py 中 `agent_id + app_id + pairing_code` 认证路径。`_approved_users.json` / `_pairing_codes.json` 标记为只读保留（现有数据可手动迁移，不自动使用） | 旧登录路径下线 |
| 前端适配 | `auth_ok` 新格式（无 role 字段）兼容 Web 端渲染 | 确保 Web UI 不报错 |

**R72 开发期测试策略（上线前）：**
- PM bot 先用旧连接参与 R72 管线开发和测试
- 新认证逻辑在 dev 容器用测试 agent 独立验证
- 验证全部 15 项验收标准通过后，部署上线

**部署上线那一刻：**
- 旧 `agent_id + app_id` 认证失效
- 所有 bot 需要走 `register` 重新注册
- PM 先注册 → 然后逐个协调其他 bot 注册

#### C2 — R73（下一轮）：全员迁移 + 全链路验证 + 随手修复

**目标：** 全员注册新体系 → 跑通完整管线 → 发现 bug 顺手修复 → 验收通过后 R74 起纯新体系运作。

**R73 不是纯验证轮——它是迁移+验证+修复混合轮。**

| 阶段 | 内容 | 说明 |
|:------|:------|:------|
| ① PM 注册 | PM 走 `register` 获得新 api_key + 注册 Agent Card | PM 先上线 |
| ② 逐个 bot 注册 | admin、arch、dev、review、qa bot 逐个走 register + Agent Card 自注册 | 按 pipeline_roles 声明能力 |
| ③ 管线验证 | 启动一条完整 6 步管线，验证全角色参与 | 覆盖 arch/dev/review/qa/admin |
| ④ Bug 修复 | 管线中发现的任何问题在 R73 内修完 | 不等到 R74 |
| ⑤ 验收确认 | 管线全绿通过 → R73 归档 | OK 则 R74 纯新体系 |

**R73 管线计划（简化）：**

| Step | 角色 | 内容 | 说明 |
|:-----|:-----|:------|:------|
| 1 | PM | 编写 R73 migration 计划 + 全员点名 | 启动迁移 |
| 2 | arch | 验证 new auth + agent card 架构完整性，输出验证方案 | 非编码 |
| 3 | dev | 如果发现 bug，编码修复 | 条件执行 |
| 4 | review | 审查修复代码 | 条件执行 |
| 5 | QA | 全量回归 + 管线验证 | 核心 |
| 6 | admin | 确认迁移完成 + 归档 | 确认下线旧体系 |

> **R73 的具体方案在 R73 需求文档中详细展开。R72 只定过渡路线。**

#### C3 — R74+（后续）：纯新体系运作

- 所有 bot 使用 `register` → `auth` api_key 流程
- `_approved_users.json` / `_pairing_codes.json` / `MSG_PAIRING_CODE` / `MSG_APPROVE` 等遗留代码可安全清理
- 管线按 Agent Card 的 `pipeline_roles` 匹配 bot
- 认证就是 api_key，不做其他任何途径

---

## 4. 验收标准

### 🎯 4.1 方向 A — 统一 WSS 认证协议

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-A1 | 未认证连接发送 `register` → 收到 `register_ok` 含 agent_id + api_key | 返回格式正确，同一连接可继续收发消息 | 原始 WebSocket 发送 register → 验证响应 |
| ✅-A2 | `register_ok` 中 agent_id 格式为 `ws_` 开头，非 meyo `01J` 格式 | ws-bridge 自有签发 | 检查 agent_id 前缀 |
| ✅-A3 | `api_key` 格式为 `sk_ws_` 开头 | 符合预期格式 | 检查前缀和长度 |
| ✅-A4 | 新连接发送 `auth` + `api_key` → `auth_ok` | 认证成功，返回无 `"role":"member"` 字段 | 验证 `auth_ok` 响应中无 `role` |
| ✅-A5 | `register` 后同一连接可直接收发消息（无需断连重连） | 注册即认证 | 注册后立即发送普通消息 → 验证送达 |
| ✅-A6 | 注册成功的 agent_id + api_key 持久化到 `_api_keys.json`，服务端重启后仍有效 | 重启后可用 api_key 连接 | 注册 → 记录 api_key → 重启容器 → 用 api_key 连接 |
| ✅-A7 | 无效 api_key 连接 → `auth_error` | 返回错误 | 发假的 `sk_ws_fake_xxx` |
| ✅-A8 | 旧 `agent_id + app_id` 连接 → `auth_error`（不再接受） | 旧体系不可用 | 用旧凭证连接 → 验证被拒 |

### 🎯 4.2 方向 B — Agent Card 自注册

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-B1 | 已认证 bot 发送 `agent_card_register` → 收到 `agent_card_register_ok` | 卡片注册成功 | 注册 → 注册卡片 |
| ✅-B2 | 卡片注册后 `_ROLE_AGENT_MAP` 自动更新 | 角色映射即时生效 | `!agent_role_map` 验证 |
| ✅-B3 | 卡片数据持久化到 `config/agent_cards.json` | 重启后不丢失 | 注册 → 重启 → `!agent_card_list` |
| ✅-B4 | 同一 bot 重复发送 `agent_card_register` 覆盖旧卡片 | 更新而非追加 | 先注册 arch → 再注册 dev → 验证角色为 dev |
| ✅-B5 | 管线 Step 按 `pipeline_roles` 匹配 bot | 场景：Step 需要 arch → 点名到声明 arch 的 bot | 注册 arch 卡片 → 启动管线 |

### 🎯 4.3 方向 C — 迁移验证 + 端到端

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-C1 | 部署后旧 `agent_id + app_id` 认证全线失效 | 旧 bot 无法连接 | 部署后立刻用旧 agent_id 连接 |
| ✅-C2 | 新 bot 注册 → auth → push 消息被服务端接受 | 全流程通信正常 | 注册 → auth → 发消息到大厅 |
| ✅-C3 | 新 bot 注册 Agent Card 后出现在 `!agent_card_list` | 卡片可查询 | 注册 → 查卡片列表 |
| ✅-C4 | 管线启动: 按 Agent Card `pipeline_roles` 匹配并点名 | 角色匹配工作 | 注册 arch 卡片 → `!pipeline_start` → 验证点名到对应 bot |

---

## 5. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| 🔴 **非 R72 的 HTTP REST 端点** | 不添加 HTTP `POST /api/v1/agents/register` | 统一走 WSS 协议，不引入双协议 |
| 🔴 **权限体系重构（RBAC）** | 不做权限声明、permission 检查链、细粒度 scope | R72 只做「认证 + Agent Card」，不做「授权」。权限体系是后续方向 |
| 🔴 **迁移现有 bot** | R72 内不替各 bot 注册 | R72 完成开发和部署，R73 才全员迁移 |
| 🔴 **前端 UI 改造** | Web 端认证界面 | R72 仅确保 Web UI 不因 `auth_ok` 新格式报错 |
| 🔴 **配对码代码的全量清理** | `pairing_code`、`MSG_APPROVE`、`_approved_users.json` 等遗留代码标记为 deprecated 但不删除 | R74+ 再清理，R72 只保证退出活跃使用 |

---

## 6. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 20min |
| **3** | 👨‍💻 Dev | 编码实现 | 30min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 20min |
| **6** | 🛠️ Admin | 合并部署归档 | 10min |

### 6.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `shared/protocol.py` | **修改** — 新增 register/register_ok/agent_card_register/agent_card_register_ok 类型 + FIELD_API_KEY + 标记 MSG_PAIRING_CODE/MSG_APPROVE 为 deprecated | ~20 行净增 |
| `server/auth.py` | **扩展** — 新增 `create_api_key()`, `validate_api_key()`, `revoke_api_key()`, `generate_agent_id()` + `_read/write_api_keys()` 本地方法 | ~80 行净增 |
| `server/persistence.py` | **扩展** — 新增 `get_api_keys()`, `save_api_keys()` 读写 `_api_keys.json` | ~15 行净增 |
| `server/handler.py` | **修改** — 替换 `handle_auth()` 为纯 api_key 认证 + 新增 `handle_register()` + 新增 `handle_agent_card_register()` 路由 + 消息类型分发 | ~80 行净增 |
| `server/agent_card.py` | **扩展** — 新增 `register_from_agent()` / `update_card_from_agent()` + `_auto_update_role_map()` | ~50 行净增 |
| `server/config.py` | **修改** — 移除不再使用的旧配置项（如有） | ~3 行
| **合计** | | **~248 行净增** |

### 6.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| 🔴 api_key 生成算法强度不足 | 伪造 api_key 可以绕过认证 | 用 `secrets.token_urlsafe(32)` + `hashlib.sha256` 双重保证 |
| 🔴 **部署瞬间所有 bot 断线** | 旧认证失效 + 新认证上线之间 gap，所有 bot 掉线，PM 无法通过 ws-bridge 协调注册 | **先升级 PM bot 的客户端支持新认证**。部署顺序：① PM bot 本地更新客户端代码 → ② 服务端部署新版 → ③ PM bot 立即 register → ④ 逐个协调其他 bot 迁移。此顺序确保无指挥真空 |
| 🟡 Agent Card 自注册与 `_ROLE_AGENT_MAP` 不一致 | 角色映射不同步 | 注册后立即写映射表 + persistence |
| 🟡 R72 开发期 PM bot 依赖旧连接参与管线 | 旧连接在工作，但新认证替换后旧路径消失 | 开发期间 PM bot 先用旧连接参与管线编码测试。新认证逻辑在 dev 容器独立验证。上线前 PM bot 本地先适配好新客户端 |

---

## 7. 脱敏检查清单

- [ ] docs/R72/*.md 零内部名残留
- [ ] `grep -nE '^(PM|admin|arch|dev|review|qa)\b' docs/R72/*.md` 零匹配
- [ ] 使用通用角色名（PM/arch/dev/review/QA/admin）
- [ ] api_key 示例值使用 `sk_ws_xxxx` 而非真实密钥
- [ ] agent_id 示例值使用 `ws_xxxx` 而非真实 ID

---

## 8. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-06 | 初稿 — R72 Bot 统一认证与能力注册体系需求文档 |
