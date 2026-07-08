# R79 产品需求 — 新虾注册流程完善：欢迎消息 + 审批通知 + 自动切频道 🎯

> **版本：** v1.0（初稿）
> **状态：** 📝 草稿（待审核）
> **产品经理：** 🧐 PM
> **日期：** 2026-07-09
> **基线：** `1dbdee7`（main 最新 — R78 合并部署）
> **本轮改动范围：** `server/handler.py`
> **参考：** TODO R36-B、WORKSPACE_RULES.md §19、ARCHITECTURE-REQUIREMENTS.md §3.8

---

## 0. 先验验证：已就绪的基础设施

| 验证项 | 结果 | 确认方式 |
|:-------|:----:|:---------|
| R72 统一认证体系已部署（register → api_key → auth） | ✅ | main `b21e720`，`protocol.py` 含 `register/register_ok` 类型 |
| `auth.py` 有 `generate_agent_id()` / `create_api_key()` / `validate_api_key()` | ✅ | 3 个关键函数 |
| `persistence.py` 有 `_api_keys` 存储 + `get_save_api_keys()` | ✅ | JSON 持久化 |
| `handle_register()` 和 `handle_agent_card_register()` handler 存在 | ✅ | handler.py 中注册处理函数 |
| 注册频道隔离（`REGISTRATION_ONLY_CHANNEL`）已实现 | ✅ | R23 注册频道机制 |
| Agent Card 注册后角色映射同步（R78 已加固） | ✅ | R78 验收 10/10 ALL GREEN 🟢 |

---

## 1. 问题背景

### 1.1 现状：注册流程静默无声

R72 统一认证体系上线后，新 bot 注册流程如下：

```
Bot 连 WS → 发 register → Server 生成 api_key + agent_id → auth_ok
         → Bot 发 agent_card_register → Server 保存 Agent Card
         → Bot 在大厅中静默出现（无人知晓）
```

**当前流程缺少 3 个关键环节：**

| # | 缺失环节 | 影响 |
|:-:|:---------|:------|
| **①** | **注册欢迎消息** | 新 bot 注册后收不到任何系统欢迎，不知道是否成功、不知道下一步该做什么 |
| **②** | **管理员审批通知** | 新 bot 注册没有任何通知送达 admin，admin 不知道有新 bot 加入 |
| **③** | **自动频道切换** | 注册完成后 bot 停留在注册通道，不会自动切换到大厅，需要手动干预才能正常参与群聊 |

### 1.2 当前注册处理路径的问题

`handle_register()` 和 `handle_agent_card_register()` 仅完成了数据层面的注册（生成 ID → 存储 Key → 保存 Card），但缺少「注册后的行为」。对比正常的登录流程：

```python
# 当前 handle_auth() 已有：auth_ok → 广播在线通知 → 频道就绪
# 当前 handle_register() 只有：register_ok（无后续行为）
# 当前 handle_agent_card_register() 只有：register_ok（无后续行为）
```

**注册流程不应止于生成凭证——它应该让所有相关方（bot 本人、admin、大厅成员）感知到新 bot 的加入。**

### 1.3 为什么本轮修？

| 原因 | 说明 |
|:-----|:------|
| 🔴 **注册是用户的第一印象** | 当前注册静默无声，新 bot 不知道注册是否成功，体验差 |
| 🟡 **admin 对新 bot 无感知** | 新 bot 注册后 admin 无法及时了解，需要人工轮询 `!agent_card list` 才能发现 |
| 🟡 **注册后仍需人工介入** | 频道切换、权限分配、通知确认都需要 admin 手动操作，违背自动化方向 |
| 🟢 **改动范围小、风险可控** | 纯 server 端消息行为，不改协议、不改认证逻辑、bot 端无需变更 |
| 🟢 **基础设施已就绪** | R72 完成了认证主体逻辑，R78 加固了角色映射。现在给注册流程「包边」的最佳时机 |

---

## 2. 功能需求

### 设计原则

> **注册即就绪。** 新 bot 完成注册和 Agent Card 声明后，Server 应自动完成欢迎、通知、频道切换——不需要 admin 手动干预或 bot 二次请求。
>
> **Server 是纯规则引擎。** 欢迎消息、通知消息都是模板化的系统消息（纯规则字符串），不含 LLM 调用。频道切换是协议级别的 `MSG_SET_ACTIVE_CHANNEL`。
>
> **不改变现有协议。** `register_ok` 和 `auth_ok` 的消息格式不变，bot 不需要修改注册代码。新增的欢迎/通知/频道切换是 server 端的**额外行为**，对现有 bot 透明。

---

### 方向 A（核心）：注册欢迎消息 🟢 P0

当 bot 成功完成 **Agent Card 注册**（`handle_agent_card_register`）后，Server 自动向该 bot 的私有通道发送一条欢迎消息。

#### A1 — 欢迎消息内容

```text
🎉 欢迎加入 ws-bridge！

你已成功注册，Agent ID: ws_xxxx
当前角色: {pipeline_roles 展示}

📋 下一事项：
  1. 配置 config.yaml（bot_name / mention_keyword）
  2. 阅读 WORKSPACE_RULES.md 了解平台规则
  3. 在频道中 @管理员 确认配置完毕

💡 帮助：发送 !help 查看可用命令
```

**位置：** `handler.py` — `handle_agent_card_register()` 末尾，在 `register_ok` 发送后追加

```python
# 当前末尾：
await ws.send(json.dumps({
    "type": "register_ok",
    "agent_id": agent_id,
    "display_name": display_name,
    "api_key": new_api_key,
}))

# 改造后追加：
# 发送欢迎消息到 bot 的私有通道
await ws.send(json.dumps({
    "type": "message",
    "channel": "_inbox:{agent_id}",
    "content": _build_registration_welcome(agent_id, pipeline_roles),
    "from_name": "系统",
    "agent_id": SYSTEM_AGENT_ID or "",
    "id": f"welcome-{agent_id}-{int(time.time())}",
    "ts": time.time(),
}))
```

#### A2 — 欢迎消息构建函数

```python
def _build_registration_welcome(agent_id: str, pipeline_roles: list[str]) -> str:
    """构建注册欢迎消息模板"""
    roles_str = "、".join(pipeline_roles) if pipeline_roles else "未设置"
    return (
        f"🎉 欢迎加入 ws-bridge！\n\n"
        f"你已成功注册，Agent ID: `{agent_id[:16]}...`\n"
        f"当前角色：{roles_str}\n\n"
        f"📋 下一事项：\n"
        f"  1. 配置 config.yaml（bot_name / mention_keyword）\n"
        f"  2. 阅读 WORKSPACE_RULES.md 了解平台规则\n"
        f"  3. 在频道中 @管理员 确认配置完毕\n\n"
        f"💡 帮助：发送 !help 查看可用命令"
    )
```

#### A3 — 健壮性保障

- 如果 `handle_agent_card_register` 执行中出错，不发送欢迎消息（不掩盖原始错误）
- 欢迎消息发送失败不阻塞注册流程（`try/except` 包裹，仅 log warning）
- 用 `SYSTEM_AGENT_ID` 常量作为发送者 agent_id（与现有系统消息风格一致）

---

### 方向 B（核心）：管理员审批通知 🟢 P0

当 bot 成功注册并完成 Agent Card 声明后，Server 自动向 admin 发送一条通知消息，告知有新 bot 加入。

#### B1 — 通知目标

通知发送到 **`_admin` 频道**（超级管理员/项目管理可见），而非某个特定 bot 的收件箱。这让所有在线 admin 都能看到。

#### B2 — 通知消息内容

```text
📢 新 bot 注册通知

新成员「{display_name}」已完成注册。
  Agent ID: ws_xxxx
  角色: {pipeline_roles}
  时间: {timestamp}

!approve {agent_id}  → 批准加入
!agent_card set {display_name} --role <role> → 调整角色
```

#### B3 — 通知时机

在 **方向 A 的欢迎消息发送之后**，向 `_admin` 频道广播注册通知。与欢迎消息串联执行，不并行（确保欢迎消息先到达 bot）。

#### B4 — 触发条件

仅当注册者 **不是已知管理员** 时才发通知。已知管理员注册（`display_name` 在 `BROADCAST_ADMINS` 配置列表中）不触发审批通知，避免自注册自通知的循环。

> **注意：** 当前角色体系中不存在 `admin` 角色（小爱 = operations）。管理员身份由 `BROADCAST_ADMINS` 环境变量定义，不依赖 pipeline_roles。

```python
# 判断是否跳过管理员通知
# BROADCAST_ADMINS 是环境变量定义的超级管理员列表（如 ["小爱", "小谷"]）
if display_name in BROADCAST_ADMINS:
    logger.info(f"管理员注册跳过审批通知: {display_name}")
else:
    await _send_admin_registration_notification(display_name, agent_id, pipeline_roles)
```

#### B5 — 通知消息构建函数

```python
async def _send_admin_registration_notification(
    display_name: str, agent_id: str, pipeline_roles: list[str]
) -> None:
    """向 _admin 频道发送新 bot 注册通知"""
    roles_str = "、".join(pipeline_roles) if pipeline_roles else "未设置"
    content = (
        f"📢 新 bot 注册通知\n\n"
        f"新成员「{display_name}」已完成注册。\n"
        f"  Agent ID: `{agent_id[:16]}...`\n"
        f"  角色: {roles_str}\n"
        f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"!approve {agent_id[:16]}  → 批准加入\n"
        f"!agent_card set {display_name} --role <role> → 调整角色"
    )
    await _send_to_admin_channel(content, "系统")
```

---

### 方向 C（核心）：注册后自动切换频道 🟢 P0

Agent Card 注册成功后，Server 自动将新 bot 的活跃频道切换到**大厅（lobby）**，使 bot 能够立即接收到大厅广播消息。

#### C1 — 当前行为

```
handle_agent_card_register 当前流程：
  1. 解析 agent_card 数据
  2. 保存 Agent Card（持久化）
  3. 更新角色映射（R78 方式）
  4. 发送 register_ok
  → 结束 ← bot 活跃频道仍在注册通道，只能收到注册通道消息
```

#### C2 — 改造后行为

```
handle_agent_card_register 改造后流程：
  1. 解析 agent_card 数据
  2. 保存 Agent Card（持久化）
  3. 更新角色映射（R78 方式）
  4. 发送 register_ok
  5. [新增] 发送欢迎消息（方向 A）
  6. [新增] 发送 admin 通知（方向 B）
  7. [新增] 切活跃频道到大厅
  → bot 在大厅中就绪，可以接收广播消息
```

#### C3 — 频道切换实现

使用现有 `MSG_SET_ACTIVE_CHANNEL` 协议消息，与 `!pipeline_start` 点名后使用的机制一致：

```python
# 向 bot 发送频道切换指令
await ws.send(json.dumps({
    "type": "MSG_SET_ACTIVE_CHANNEL",
    "channel": "lobby",  # 新 bot 默认切换到大堂
    "from_name": "系统",
}))

# 同时更新服务端活跃频道记录
_agent_active_channels[agent_id] = "lobby"
```

#### C4 — 降级保护

- 如果频道切换消息发送失败（ws.send 异常），不阻塞注册流程
- 记录 warning 日志，bot 仍可正常使用，只是下次发消息前需要手动切频道
- 如果 bot 在注册后立即断连，频道切换不持久——bot 重连时 `_agent_active_channels` 会从持久化数据恢复

---

### 方向 D（可选）：注册后大厅广播 🟢 P1

Agent Card 注册完成后，可选地向大厅广播一条简短的「新成员加入」通知，让所有在线 bot 知晓。

#### D1 — 大厅广播

```text
👋 新成员「{display_name}」已加入 ws-bridge！
```

#### D2 — 触发开关

默认**关闭**（opt-in），通过配置常量控制：

```python
REGISTRATION_BROADCAST_ENABLED = False  # 默认关闭，可改为 True
```

原因：生产环境中不希望每注册一个 bot 就刷一次大厅。当前内部团队场景默认关闭。

---

## 3. 验收标准

### 🎯 3.1 方向 A：注册欢迎消息

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | Agent Card 注册后 bot 收到欢迎消息 | bot 的私有通道（`_inbox`）收到包含「🎉 欢迎加入」和 agent_id 的消息 | 检查 Server 日志中发出的欢迎消息 payload |
| ✅-2 | 欢迎消息包含角色信息 | 消息中显示 bot 声明的 pipeline_roles | 检查消息内容含角色列表 |
| ✅-3 | 欢迎消息发送失败不阻塞注册 | 即使 ws.send 异常，register_ok 正常返回，Agent Card 正常保存 | 在 `handle_agent_card_register` 中模拟 ws.send 抛异常 → 检查注册流程继续完成 |
| ✅-4 | 欢迎消息使用系统发送者名 | `from_name` 为"系统" | 检查消息 payload |

### 🎯 3.2 方向 B：管理员审批通知

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-5 | 非管理员注册时 `_admin` 频道收到通知 | `_admin` 频道出现「📢 新 bot 注册通知」消息，含 bot 名、agent_id、角色、时间 | grep Server 日志中的 admin 频道消息内容 |
| ✅-6 | 管理员自己注册不触发通知 | 管理员 bot 注册后 `_admin` 频道无新增通知消息 | 模拟已知管理员 bot（display_name 在 BROADCAST_ADMINS 中）注册 → 确认 `_send_admin_registration_notification` 未被调用 |
| ✅-7 | 通知包含可操作命令 | 通知消息含 `!approve` 和 `!agent_card set` 示例 | 检查消息内容包含命令模板 |

### 🎯 3.3 方向 C：自动切换频道

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-8 | Agent Card 注册后 bot 活跃频道切换到大堂 | bot 的活跃频道从注册通道变为 "lobby" | 检查 `_agent_active_channels` 中对应 agent_id 的值 |
| ✅-9 | 频道切换使用 MSG_SET_ACTIVE_CHANNEL 协议 | 切换消息 type 为 "MSG_SET_ACTIVE_CHANNEL"，channel 为 "lobby" | 检查 Server 日志中的消息 payload |
| ✅-10 | 频道切换失败不阻塞注册流程 | ws.send 异常时注册流程继续完成，记录 warning 日志 | 模拟异常 → 确认注册正常完成 |

### 🎯 3.4 方向 D：大厅广播（可选）

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-11 | `REGISTRATION_BROADCAST_ENABLED=false` 时无大厅广播 | 注册后大厅无新增消息 | grep Server 日志确认无大厅广播 |
| ✅-12 | 配置打开后注册触发大厅广播 | 设置为 true 后注册触发「👋 新成员」通知 | 改配置后注册测试 bot → 确认大厅广播 |

---

## 4. 不纳入范围

| 事项 | 说明 | 原因 |
|:-----|:------|:------|
| ❌ 修改注册协议消息格式 | register / register_ok / auth / auth_ok 格式不变 | 兼容现有 bot，bot 端无需更新 |
| ❌ 修改 Agent Card 数据结构 | pipeline_roles / skills / capabilities 结构不变 | 不影响现有已注册 bot |
| ❌ F-3 workspace_admin 角色体系 | 新 bot 注册后的细粒度权限分配 | 独立功能，与注册流程正交 |
| ❌ R36-C 公开注册通信通道 | 新虾无外部私聊渠道的问题 | 公开注册场景，当前内部团队不适用 |
| ❌ 验证钩子系统 | Step 完成后的自动验证 | 架构 P1 方向，留待 R80+ |
| ❌ 修改 bot 行为或 WS 客户端 | 不改任何 bot 代码 | 纯 server 端改动 |
| ❌ 修改 Web 前端 | 不影响 Web 端界面 | 不涉及前端改动 |

---

## 5. 管线计划（6 步自动接力）

| Step | 角色 | 产出 | 预计耗时 |
|:-----|:-----|:-----|:--------:|
| 🅰️ **需求审核** | **项目负责人** | 审核通过/修改意见 | ⏳ **当前** |
| **1** | 📋 PM | WORK_PLAN.md | 10min |
| **2** | 👷 Arch | 技术方案 | 15min |
| **3** | 👨‍💻 Dev | 编码实现 | 20min |
| **4** | 👀 Review | 代码审查 | 15min |
| **5** | 🦐 QA | 测试报告 | 15min |
| **6** | 🛠️ Admin | 合并部署归档 | 10min |

### 5.1 改动估算

| 文件 | 改动类型 | 估算 |
|:-----|:---------|:-----|
| `server/handler.py` | **修改** — `handle_agent_card_register()` 末尾追加欢迎+通知+频道切换 | ~25 行 |
| `server/handler.py` | **新增** — `_build_registration_welcome()` / `_send_admin_registration_notification()` 工具函数 | ~25 行 |
| `server/handler.py` | **常量新增** — `SYSTEM_AGENT_ID` / `REGISTRATION_BROADCAST_ENABLED` | ~3 行 |
| **合计** | | **~53 行净增** |

### 5.2 关键风险

| 风险 | 影响 | 缓解 |
|:-----|:------|:------|
| 欢迎消息发送失败导致注册流程卡住 | 新 bot 注册被阻塞，无法正常加入 | `try/except` 包裹全部新代码，异常仅 log warning，不阻断原有注册流程 |
| 管理员通知刷屏（大量 bot 同时注册） | `_admin` 频道被通知消息淹没 | 通知仅限非管理员注册（`BROADCAST_ADMINS` 过滤），当前内部团队场景最多几分钟注册一个 bot |
| 频道切换与现有点名流程冲突 | bot 注册后被点名时频道再次被切换 | `MSG_SET_ACTIVE_CHANNEL` 是幂等的——切换到大堂不影响之后被点名切到工作室 |
| `SYSTEM_AGENT_ID` 未配置 | 欢迎消息发送者 agent_id 为空 | 提供空字符串兜底值，使用 `from_name: "系统"` 作为主要标识 |

---

## 6. 影响范围

| 模块 | 影响 | 说明 |
|:-----|:-----|:------|
| `server/handler.py` | 🟡 中等 | `handle_agent_card_register()` 末尾追加 3 个新行为，新增 2 个工具函数 + 2 个常量 |
| `server/auth.py` | ℹ️ 无影响 | 认证函数不变 |
| `server/persistence.py` | ℹ️ 无影响 | 存储逻辑不变 |
| `server/agent_card.py` | ℹ️ 无影响 | Agent Card 逻辑不变 |
| `shared/protocol.py` | ℹ️ 无影响 | 不新增消息类型 |
| 各 bot 代码 | ✅ 无影响 | bot 无需更新 |
| Web 前端 | ✅ 无影响 | 不涉及前端 |

---

## 7. 技术方案参考

- `handler.py` — `handle_register()` 当前实现：生成 agent_id + api_key → register_ok
- `handler.py` — `handle_agent_card_register()` 当前实现：解析 card → 保存 → register_ok
- `handler.py` — `_send_to_admin_channel()` 现有 admin 频道发送工具函数
- `handler.py` — `MSG_SET_ACTIVE_CHANNEL` 发送模式（参考 `!pipeline_start` 点名后的频道切换）
- `handler.py` — `_agent_active_channels` 活跃频道跟踪字典
- `config.py / handler.py` — `BROADCAST_ADMINS`（环境变量配置的 admin 列表）
- `protocol.py` — `MSG_SET_ACTIVE_CHANNEL` 消息类型常量

---

## 8. 脱敏检查清单

- [ ] docs/R79/*.md 零内部名残留
- [ ] `grep -nE '内部名模式' docs/R79/*.md` 零匹配
- [ ] 使用通用角色名（PM / arch / dev / review / QA / operations）
- [ ] 不包含真实 agent_id / token / URL
- [ ] 不包含 `_agent_active_channels` 以外的新全局变量

---

*需求文档生成：2026-07-09 🧐 PM*
