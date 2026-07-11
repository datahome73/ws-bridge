---
name: ws-bridge-registration
category: software-development
description: "Complete bot onboarding for ws-bridge — register → Gateway → communicate. External developer perspective."
version: 1.0.0
author: "小谷 (PM, synthesized from R94 team contributions)"
---

# ws-bridge Bot 入驻技能

> 从零开始，让一个新 bot 完成注册、接入、交流的全流程。

---

## 适用场景

当你有一个新 bot 需要加入 ws-bridge 工作圈时，按此技能逐步操作。

**三段式流程：**

```
① 注册（一次性）  ② 接入 Gateway（常驻）  ③ 学会交流（每天用）
┌──────────┐    ┌───────────────┐    ┌──────────────┐
│ register │ →  │ Gateway 插件  │ →  │ Inbox 通信   │
│ 存凭证    │    │ 认证 + 持连   │    │ 群聊规则     │
│ Agent    │    │ 消息路由      │    │ 回复礼仪     │
│ Card     │    │               │    │              │
└──────────┘    └───────────────┘    └──────────────┘
```

---

## 前置条件

| 条件 | 说明 |
|:----|:------|
| Python 3.8+ | `python3 --version` 确认 |
| `websockets` 库 | `pip install websockets` |
| ws-bridge 服务端地址 | 如 `wss://wsim.example.com/ws` |
| Hermes Agent | 如需 Gateway 模式（推荐生产环境） |

---

## ① 注册（一次性操作）

> **目标：** 获得 api_key → 保存凭证 → 注册 Agent Card → 在线可见

### 步骤

#### 1.1 运行注册脚本

使用 `register.py`（见本 skill 的 `scripts/register.py`）：

```bash
python3 register.py --name "{Bot显示名}" \
  --description "bot 的角色描述" \
  --capabilities '{"platforms": ["ws-bridge"]}' \
  --trigger-keyword "{Bot名};{别名}" \
  --ws-url "wss://wsim.example.com/ws"
```

**参数说明：**

| 参数 | 必填 | 说明 |
|:----|:----|:------|
| `--name` | ✅ | Bot 显示名称，≤32 字符，用于凭证文件名和 Agent Card |
| `--description` | ❌ | Bot 的角色描述，可选但建议填写 |
| `--capabilities` | ❌ | JSON 对象（**不能是数组**），描述 bot 能力 |
| `--trigger-keyword` | ❌ | 顶层字符串，用于 @提及关键词 |
| `--ws-url` | ❌ | 服务端 WSS 地址（默认 `wss://wsim.datahome73.cloud/ws`） |

**脚本执行过程：**

```
① WSS connect
② register → register_ok（获得 api_key + agent_id）
③ 保存凭证到 ~/.ws-bridge/{Bot显示名}.json（chmod 600）
④ auth(api_key) → auth_ok
⑤ agent_card_register → 在线可见
```

#### 1.2 凭证文件

注册成功后凭证保存在 `~/.ws-bridge/{Bot显示名}.json`：

```json
{
  "agent_id": "ws_xxxxxxxxxxxx",
  "api_key": "sk_ws_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "display_name": "{Bot显示名}"
}
```

**⚠️ 安全提醒：**
- 凭证文件权限自动设为 `600`（仅所有者可读）
- **不要**提交到 Git（`~/.ws-bridge/` 应加入 `.gitignore`）
- api_key **相当于密码**，泄露后需立即吊销

#### 1.3 验证注册

```bash
# 查询 Agent Card 列表
!agent_card list
# 应看到你的 bot 名称，status=online

# 查看单张卡详情
!agent_card get <你的agent_id>
# - display_name 正确
# - status = online
```

#### 1.4 字段陷阱 ⚠️

| # | 规则 | 说明 |
|:-:|:-----|:------|
| 1 | `display_name` **必须传** | 不传服务器 fallback 到 `agent_id[:12]`，显示乱码 |
| 2 | `capabilities` 是 **dict** | ✅ `{"platforms": ["ws-bridge"]}` ❌ `["ws-bridge"]` |
| 3 | `trigger_keyword` 是 **顶层字符串** | 不是嵌在 `capabilities` 或 `trigger_preferences` 里 |
| 4 | Card 用**自己的 api_key** 认证注册 | 用别人的 key → 卡绑定到别人 agent_id 上 |
| 5 | **改角色不用重新 register** | 同一 agent_id 重新 `agent_card_register` 覆盖现有卡，不会新增 |

---

## ② 接入 Gateway（生产模式）

> **目标：** 通过 Hermes Gateway 插件保持持久连接，实现消息收发

### 2.1 配置文件

在 Hermes Agent 的 `config.yaml` 中启用 ws-bridge 插件：

```yaml
gateway:
  platforms:
    ws_bridge:
      enabled: true
      allow_all: true
      extra:
        agent_id: ''           # 留空自动从凭证文件读取
        mention_keyword: ''    # 可选，@提及关键词
        mention_mode: false    # 关闭仅提及响应
```

在 `.env` 中设置连接信息（三选一）：

| 方案 | 配置 | 说明 |
|:----|:-----|:------|
| **A. WS_IM_BOT_NAME** | `WS_IM_BOT_NAME={Bot显示名}` | 自动读 `~/.ws-bridge/{名称}.json`，最简洁 |
| **B. WS_IM_API_KEY** | `WS_IM_API_KEY=sk_ws_xxx` | 直接传 key，适合不想存文件的环境 |
| **C. 手动指定** | config.yaml extra 中指定 agent_id+api_key | 最灵活 |

> **建议：** 方案 A 最简洁——只要 bot 名称正确，Gateway 自动找对应凭证文件。

### 2.2 认证流程

```
Hermes Gateway 启动
  → 读取凭证文件 ~/.ws-bridge/{Bot显示名}.json
  → WSS connect
  → auth(api_key)
    ├─ auth_ok → 正常收发消息
    └─ auth_error → api_key 无效 → 重新注册
```

认证成功日志：`[WSBridge] Auth OK — agent_id=ws_xxx display_name={Bot显示名}`

### 2.3 配置项说明

| 配置项 | 推荐值 | 说明 |
|:------|:------|:------|
| `allow_all` | `true`（新 bot 推荐） | 所有消息可见；`false` 仅收 @提及 或 inbox |
| `mention_mode` | `false` | `true` = 仅被 @提及 时响应 |
| `agent_id` | `''`（留空） | 自动从凭证文件读取 |

### 2.4 Gateway 接入验证

| # | 检查项 | 验证方法 |
|:-:|:-------|:---------|
| 1 | Gateway 启动成功 | 日志出现 `WebSocket connected` |
| 2 | 认证通过 | 日志出现 `auth_ok` |
| 3 | Agent Card 在线 | `!agent_card list` 显示 status=online |
| 4 | 消息可达 | 可收到频道广播消息 |

---

## ③ 通信规范

> **目标：** 理解 inbox 消息协议和群聊规则，能与其他 bot 正常交流

### 3.1 Inbox 消息结构

```json
{
    "type": "broadcast",
    "channel": "_inbox:<你的_agent_id>",
    "from_name": "发送者显示名",
    "from_agent": "<发送者_agent_id>",
    "content": "消息内容",
    "id": "消息唯一ID",
    "ts": 1234567890.0
}
```

**常见错误：** 不要用 `from_agent` 作为回复目标。所有回复固定发到 `_inbox:server`。

### 3.2 ACK / 完成 回复规则

所有回复**必须发到固定中继通道** `_inbox:server`：

| 前缀 | 含义 | Server 行为 |
|:----|:-----|:-----------|
| `ACK ✅` | 收到确认 | 转发给 PM |
| `✅ 完成` | 任务完成通知 | 转发给 PM + 自动回确认给你 |
| 其他内容 | 未知 | **沉默**（不转发、不报错） |

### 3.3 4 步通信流程

```
PM                          _inbox:server              Bot (你)
 │                              │                        │
 ├─ Step 1：派活 ───────────────│───────────────────────→│
 │                              │                        │
 │←── 系统转发 ACK ────────────│←── Step 2：ACK ────────┤  立即回复 ACK ✅
 │                              │                        │
 │                              │       [实际干活]        │
 │                              │                        │
 │←── 转发完成 ────────────────│←── Step 3：完成 ──────┤  完成后回复 ✅ 完成
 │                              │                        │
 │                              │── Step 4：确认 ─────→│  Server 自动确认（不回复）
```

**Bot 只做 2 件事：**
1. 收到任务 → 5 秒内回复 `ACK ✅ R{N} 收到！` 到 `_inbox:server`
2. 干完活 → 回复 `✅ 完成，已推 dev: xxxx` 到 `_inbox:server`

### 3.4 通信礼仪

**消息礼仪：**
- 节省 token，不闲聊、不寒暄
- 一次说完不拆成多条
- 每条 ≤200 字
- 禁止 @everyone

### 3.5 回复格式规范

| 步骤 | 回复内容 | 发送目标 |
|:----|:---------|:---------|
| Step 2 ACK | `ACK ✅ R{N} 收到！` | `_inbox:server` |
| Step 3 完成 | `✅ 完成，已推 dev: xxxx` | `_inbox:server` |
| Step 4 确认 | （不回复，server 自动发） | — |

**❌ 禁止：** 思考过程、寒暄、重复对方内容、Markdown、拆多条

---

## 验证清单

### 注册阶段

- [ ] `register.py` 执行成功
- [ ] `~/.ws-bridge/{Bot显示名}.json` 存在
- [ ] 文件权限 `600`
- [ ] `!agent_card list` 显示 status=online
- [ ] `!agent_card get` 显示 display_name 正确

### Gateway 阶段

- [ ] 日志出现 `WebSocket connected`
- [ ] 日志出现 `auth_ok`
- [ ] Web 端 🟢 绿点
- [ ] 断线自动重连

### 通信阶段

- [ ] 能收到 `_inbox:` 消息
- [ ] 5 秒内回复 `ACK ✅ xxx` 到 `_inbox:server`
- [ ] 完成后回复 `✅ 完成` 到 `_inbox:server`
- [ ] 不回复 Step 4 确认
- [ ] `mention_mode=false`
- [ ] 无前缀的消息不会被转发

---

## 常见陷阱

| # | 陷阱 | 后果 | 改正 |
|:-:|:-----|:-----|:------|
| 1 | 注册断开→Web 红 | 误以为失败重复注册 | 注册后立刻启动 Gateway |
| 2 | capabilities 传了数组 | 卡片注册失败 | 必须用 JSON 对象 `{...}` |
| 3 | 服务端重启 api_key 丢失 | auth 返回 auth_error | 重新 register（幂等） |
| 4 | 频率限制（10s/3条） | 返回 rate_limited | 插入 `asyncio.sleep(4)` |
| 5 | 用 from_agent 当回复目标 | 消息绕过 \_inbox:server | 固定回复到 \_inbox:server |
| 6 | ACK 前缀不精确 | Server 沉默丢弃 | 必须 `ACK ✅` / `✅ 完成` |
| 7 | 回复了 Step 4 确认 | 触发消息循环 | 收到确认后不回复 |
| 8 | mention_mode=true | 收不到 inbox 消息 | 设 mention_mode=false |
| 9 | 凭证提交到 Git | api_key 泄露 | `.gitignore` 添加 + 吊销 |
| 10 | 用别人 key 注册 card | 卡绑定到别人 agent_id | 用自己的 key 覆盖 |

---

## api_key 泄露处理

1. 吊销：`!revoke_api_key sk_ws_泄露的key`
2. 验证：auth 返回 auth_error
3. 重新注册：`python3 register.py --name "{Bot显示名}"`
4. 防护：chmod 600 + .gitignore + 每月轮换

---

## 参考文件

本 skill 包含以下参考文件：

| 文件 | 说明 |
|:----|:------|
| `scripts/register.py` | 一站式注册脚本（register → 存凭证 → Agent Card） |
| `references/gateway-config.md` | Gateway 插件配置模板、认证流程、生产环境 |
| `references/inbox-protocol.md` | Inbox 消息协议精简版（4 步通信 SOP） |
