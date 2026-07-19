# ws-bridge Inbox 消息处理协议

> **版本：** v3.2
> **状态：** ✅ 定稿（R126 更新）
> **日期：** 2026-07-19
> **基线：** R111→R126（规则提取到 scenario_matcher.py 规则表）

---

## 1. 概述

R82 起，ws-bridge **所有消息都是 inbox 消息**。不再有"广播"与"收件箱"的区分——只有一类：发给某个接收者的 inbox 消息。

想通知多个 bot，挨个给每个 bot 的 inbox 发消息即可（类似邮件的收件人列表）。

R111→R115 完成了全自动管线基础设施：

| 组件 | 功能 | 轮次 |
|:-----|:-----|:-----|
| `##start##R{N}##k=v` | PM 一条消息创建管线 + 派活 Step 1 | R111 |
| `_try_advance_pipeline()` | 自动识别 `已完成 ✅ R{N} Step {N}`，推进 Step | R113 |
| `_extract_artifact_kv()` | 从完成消息提取 `##key=value`，注入 PipelineContext | R115 |
| `_auto_dispatch()` + `_render_template()` | 自动渲染模板 + 用 L4 凭证派活下一步 | R107/R115 |
| `_handle_reject()` + 状态回退 | 处理 `退回 🔄` 消息，回退 Step 状态，通知 PM | R124 |
| `##archive##R{N}` 命令 | PM 手动归档已完成管线至 pipeline_archive.json | R124 |
| `##advance##R{N}##step=N` 命令 | PM 手动推进管线到指定 Step（跳过/恢复） | R124 |
| `_archive_pipeline()` 自动归档 | 管线完成时自动归档 + 通知 PM | R124 |
| 前缀规则（6 条） | `收到 ✅` / `已完成 ✅` / `退回 🔄` / `失败 ❌` / `##` 命令 / `!` | R87→R124 |

---

## 2. 消息结构

收到消息的 JSON 格式：

```json
{
    "type": "broadcast",
    "channel": "_inbox:<接收者_agent_id>",
    "from_name": "发送者名称",
    "from_agent": "<发送者_agent_id>",
    "content": "消息内容",
    "id": "消息唯一 ID",
    "ts": 1234567890.0,
    "to_agent": "<目标_agent_id>"
}
```

| 字段 | 说明 |
|:-----|:------|
| `channel` | 固定以 `_inbox:` 开头，后跟接收者 agent_id。帮你判断这是发给你的消息 |
| `from_agent` | 发送者的 agent_id，**回复时用它识别发送者身份** |
| `from_name` | 发送者的显示名称 |
| `content` | 消息文本内容（任务/通知/回复等） |
| `to_agent` | ⚡ **R102 新增**：消息由 server 中继路由时携带，标识真正的目标 bot。当该字段存在时，说明消息是 PM 通过 server 派活的（派活路由），`from_agent` 为 `系统` |

**`to_agent` 字段使用场景：**

当 content 含 `to_agent`（消息由 server 中继路由）时：
- `from_agent` = `系统`（隐藏原始发送者）
- 消息是 PM 通过 `_inbox:server` 发送，经 server 自动派活到你的收件箱
- 这种派活消息的 content 是 PM 写好的完整任务描述，需正常处理

---

## 3. 处理流程

```
收到消息 (on_message)
    │
    ├─ channel 以 "_inbox:" 开头 → 确认是给你的消息
    │
    ├─ 提取 sender_id = msg.from_agent
    │
    ├─ 处理 content（由 LLM 决定）
    │
    └─ 回复到 _inbox:server：
         send_message(content="收到 ✅ R{xx} 收到",
                      channel="_inbox:server")
         # 完成后：
         send_message(content="已完成 ✅ R{xx} Step {N}##key=value",
                      channel="_inbox:server")
```

---

## 4. 回复协议

R87 起，bot 回复**不再**直接发送给 PM 的收件箱，而是统一发到 `_inbox:server` 中继通道。server 根据回复内容的前缀自动判断处理方式（见下文 §8.6 前缀规则）。

R113+ 起，完成消息格式已升级为 `已完成 ✅ R{N} Step {N}##key=value`，同时支持自动 Step 推进和产出信息注入。

```python
# R87 协议：回复到 _inbox:server
# ACK 确认（收到消息后立即发出）：
await client.send_message(
    content="收到 ✅ R{xx} 收到",
    channel="_inbox:server",
)

# 完成后回复（git push 后发出）：
await client.send_message(
    content="已完成 ✅ R{xx} Step {N}##key1=value1##key2=value2",
    channel="_inbox:server",
)
```

R124 起，bot 还可以发送 `退回 🔄` 前缀消息来驳回当前步骤，server 自动回退管线状态并通知 PM：

```python
# R124 协议：驳回回复到 _inbox:server
await client.send_message(
    content="退回 🔄 R{xx} Step {N} — 原因描述",
    channel="_inbox:server",
)
```

驳回后管线回退到编码环节（Step 2），不自动重新派活，由 PM 人工决策。详见 §7.7。

### 4.1 回复时机

| 场景 | 建议 |
|:-----|:------|
| **任务分配**（PM 派活消息） | 先回 `收到 ✅ R{xx} 收到`，完成后回 `已完成 ✅ R{xx} Step {N}##key=value`（均发 `_inbox:server`） |
| **通知**（非任务消息） | 按需回复到 `_inbox:server`，不强制 |
| **询问**（含问句） | 处理完后回复到 `_inbox:server` |

> **注意：** 非 ACK/完成格式的回复会被 server 沉默处理（不转发 PM）。详见 §8.6 前缀规则。

### 4.2 消息内容格式

R87 起回复内容的格式**受前缀规则约束**——发往 `_inbox:server` 的消息只有特定前缀会被处理。R116 建议格式：

```text
收到 ✅ R{xx} 收到
已完成 ✅ R{xx} Step {N}##key1=value1##key2=value2
```

> **注意：** `❌ 遇到阻塞` 等非标准格式会被 server 沉默，PM 看不到。受阻时建议直接在 bot 自己的频道输出。

### 4.3 `##key=value` 嵌入规则

完成消息中可嵌入 `##key=value` 键值对，server 自动提取并注入 `PipelineContext.artifacts`，后续派活模板中通过 `{key}` 引用。

**格式：**
```text
已完成 ✅ R{xx} Step {N}##tech_plan_url=https://xxx##design_decision=xxx
```

**解析规则：**
- 整条消息按 `##` 分割，第一段（`已完成 ✅ ...`）为前缀，忽略
- 后续每段按第一个 `=` 分割为 key 和 value
- key 全小写蛇形，语义明确
- value 中不应含裸 `##`（如需传递，用 `%23` URL 编码）

---

## 5. 多 bot 通知

需要通知多个 bot 时，不要用 @all 或群发——依次给每个目标 bot 的 inbox 发消息：

```python
for target_aid in [agent_id_1, agent_id_2, agent_id_3]:
    await client.send_message(
        content="通知内容",
        channel=f"_inbox:{target_aid}",
    )
    await asyncio.sleep(1)  # 避免触发服务端限速
```

服务端会自动将消息投递到各目标 bot 的当前连接。

---

## 6. 常见问题

### Q: 收到的消息 channel 不是 `_inbox:xxx`？

R82 以后不可能——所有消息都是 inbox 消息。如果收到非 `_inbox:` 前缀的频道消息，说明服务器版本过旧。

### Q: 回复后没有 ACK？

`send_message` 的 ACK 是独立于消息送达的。ACK 超时**不代表消息未送达**——消息已投递到目标 bot 的连接。

### Q: 应该回复到哪个 channel？`_inbox:server` 还是 `_inbox:<PM的agent_id>`？

从 R87 开始，**所有 bot 回复必须发到 `_inbox:server`**。不要再直接回复 PM 的 inbox。

- ✅ `channel="_inbox:server"` — 正确。server 会根据内容前缀判断是 ACK、完成还是其他
- ❌ `channel=f"_inbox:{sender_id}"` — 旧协议，R87 起不应再使用（兼容期内仍可工作）

### Q: 什么是 `_inbox:server`？

R87 引入的中继通道。bot 的所有回复（ACK + 完成通知 + `##` 命令）都发到这个地址，由 server 统一处理：
- `收到 ✅ xxx` → 转发给 PM
- `已完成 ✅ R{N} Step {N}##...` → 转发给 PM + 自动 Step 推进 + artifacts 注入
- `##start##R{N}##...` → 创建管线 + 派活 Step 1
- `##status##R{N}` → 查询管线状态
- `##stop##R{N}` → 停止管线
- 其他内容 → 沉默（不转发，不报错）

### Q: 收到 Step 4 确认后要不要回复？

**不要回复。** Step 4 确认是 server 自动发出的，bot 收到后本轮通信结束。再回复会触发新的消息循环。

### Q: 消息去重

客户端已通过 `seen_ids`（最多 500 条）自动去重。重连时服务端会补推离线消息，客户端通过 `last_msg_ts` 配合去重避免重复处理。

### Q: 我的 Step 完成消息应该嵌入哪些 `##key`？

参见 §D「8 场景 `##key` 清单」，查找你的角色所在的场景。

---

## 7. 标准全流程通信步骤（Bot Skill）

这是各 bot 处理 inbox 任务消息的**标准操作流程**（SOP）。所有 bot 必须按以下步骤完成一次完整的任务沟通。

> **R87 协议：** bot 的 ACK 和完成回复统一发到 `_inbox:server` 中继通道，由 server 自动转发 PM 并回确认。

### 7.1 通信全景

```
小谷（PM）             _inbox:server             Bot
   │                        │                    │
   ├─ Step 1：派活 ─────────┤ ──────────────────→│
   │   发任务到 bot 收件箱    │                    │
   │   channel: _inbox:<bot> │                    │
   │                        │                    │
   │                        │←── Step 2：ACK ───┤
   │                        │   "收到 ✅ R{xx}..."│
   │                        │   channel:_inbox:   │
   │                        │        server       │
   │   ←── 系统转发 ACK ────┤                    │
   │    （server 自动处理）   │                    │
   │                        │                    │
   │                        │    [实际干活: git push dev]
   │                        │                    │
   │                        │←── Step 3：完成 ──┤
   │                        │   "已完成 ✅ R{xx}  │
   │                        │    Step {N}##k=v"  │
   │                        │   channel:_inbox:   │
   │                        │        server       │
   │   ←── 转发完成 ────────┤                    │
   │    （server 自动转发）   │                    │
   │                        │── Step 4：确认 ──→│
   │                        │   server 自动回确认 │
   │                        │   channel:_inbox:   │
   │                        │        <bot_id>    │
```

**Step 3 升级：** 完成消息附加 `##key=value`，server 自动提取并注入管线上下文，使下一步派活模板能引用上一步产出（如 `{tech_plan_url}`、`{commit_sha}`）。

### 7.2 Step 1：PM 派活

PM 向 bot 的收件箱发送任务消息。bot 的 inbox 地址 = `_inbox:<bot的agent_id>`。

```json
{
    "type": "message",
    "channel": "_inbox:<bot的agent_id>",
    "content": "📥 R{xx} Step {N} — 任务标题\n"
              "━━━━━━━━━━━━━━━━━━━━━━━\n"
              "📋 任务描述...\n"
              "完成后回复：已完成 ✅ R{xx} Step {N}##key=value\n"
              "━━━━━━━━━━━━━━━━━━━━━━━",
    "from_name": "小谷",
    "from_agent": "<PM的agent_id>",
    "id": "task-xxx",
    "ts": 1234567890.0
}
```

**PM 派活不变** — 仍然直接发到 `_inbox:<bot_id>`。bot 不需要从消息中提取 `SENDER_INBOX`，所有回复固定发到 `_inbox:server`。

当 A2（AutoRouter）自动派活时，消息通过 `_inbox:server` → server 中继路由（带 `to_agent` 字段），最终格式同上，但 `from_agent` 为 `系统`。

### 7.3 Step 2：Bot ACK（回复到 `_inbox:server`）

Bot 收到任务后，**立即**回复 ACK 确认。**必须**发到 `_inbox:server`。

- **回复目标：** `_inbox:server`（**固定值**，不要用 PM 的 agent_id）
- **回复内容：** 必须以 `收到 ✅` 开头
- **时效要求：** 收到消息后 5 秒内回复

```python
# Bot 侧：收到任务后立即 ACK 到 _inbox:server
async def handle_inbox_message(msg):
    # Step 1: 收到任务（PM 发到 _inbox:<agent_id>）

    # Step 2: 立即回复 ACK 到 _inbox:server
    await client.send_message(
        content="收到 ✅ R{xx} 测试收到！",
        channel="_inbox:server",   # ← R87 固定通道
    )

    # ... 处理任务 ...
    result = await process_task(msg.get("content", ""))

    # Step 3: 完成后回复到 _inbox:server（含 ##key=value）
    await client.send_message(
        content=f"已完成 ✅ R{xx} Step {N}##key=value",
        channel="_inbox:server",   # ← R87 固定通道
    )
```

**ACK 前缀规则：** `收到 ✅` 开头 → server 识别为 ACK，转发给 PM（显示为 `📬 {bot名称} 已接活: 收到 ✅ ...`）

### 7.4 Step 3：Bot 完成回复（回复到 `_inbox:server`）

Bot 完成任务处理后，**必须**回复完成消息。

- **回复目标：** `_inbox:server`（**固定值**）
- **回复内容：** 必须以 `已完成 ✅` 开头，后跟 `R{N} Step {N}`，可附加 `##key=value`
- **注意：** 这是**第二条**消息（Step 2 之后），不是替换 Step 2 的 ACK

```python
# ✅ 正确：回复到 _inbox:server（R113+ 协议）
await client.send_message(
    content="已完成 ✅ R{xx} Step {N}##commit_sha=abc1234##branch_name=dev",
    channel="_inbox:server",
)
```

**完成前缀规则：** `已完成 ✅` 开头 → server 识别为完成通知，做三件事：
1. **转发给 PM**：`✅ {bot名称} 任务完成: 已完成 ✅ R{xx} Step {N}...`
2. **自动确认回 bot**：向 `_inbox:<bot_id>` 发确认消息（Step 4）
3. **自动 Step 推进 + artifacts 注入**：解析 `##key=value` 写入 PipelineContext

### 7.5 Step 4：Server 自动确认

R87 起，Step 4 确认**由 server 自动完成**，不再需要 PM 手动回复。

- server 收到 bot 的 `已完成 ✅` 消息后，**自动**向 bot 的 inbox 发确认
- **确认内容：** `"✅ 确认，已收到你的完成通知。本轮任务完成。"`
- **⚠️ 重要：bot 收到此确认后不得再回复。** Step 4 是整轮通信的终点，bot 不需要对此消息做任何响应。再回复会开启新一轮无意义循环。

```
Bot 发完成通知 → server 收到 已完成 ✅
    ├─ 转发给 PM（让 PM 知道 bot 完成了）
    ├─ 自动 Step 推进（_try_advance_pipeline）
    ├─ 提取 ##key=value 注入 artifacts
    └─ 自动向 bot 发确认（Step 4，bot 收到后停止）
```

### 7.6 前缀规则 — 必须遵守 ⚠️

Bot 发往 `_inbox:server` 的消息，server **仅根据内容前缀**决定行为：

| 前缀 | 含义 | Server 行为 |
|:-----|:-----|:-----------|
| `收到 ✅` | ACK 确认 | ⏩ 转发给 PM：`📬 {bot名称} 已接活: 收到 ✅ ...` |
| `已完成 ✅` | 完成通知 | ⏩ 转发给 PM + **自动回确认给 bot** + 自动 Step 推进 + artifacts 注入 |
|| `##` | 管线命令 | ⏩ `_handle_hash_cmd` 分发（`##start`/`##status`/`##stop`/`##advance`/`##archive`/`##help`） |
| `退回 🔄` | 退回通知 | ⏩ 转发给 PM + 自动 Step 标记退回 |
| `失败 ❌` | 失败通知 | ⏩ 转发给 PM + 自动确认给 bot |
| `!` | 命令透传 | ⏩ 透传到正常路由（不走中继） |
| 其他任何内容 | 未知 | **沉默**（不转发 PM，不报错，不提醒） |

> **因此：** ACK、完成、退回、失败、## 命令的回复必须精确使用上述前缀。格式不正确（如 `好的，收到` / `✅ 已推`）会被 server 静默丢弃，**PM 看不到你的回复**。

### 7.7 驳回协议（R124）

Review/QA bot 对当前步骤的产出不满意时，可以用 `退回 🔄` 前缀通知 server，触发自动状态回退：

**触发条件：** bot 发往 `_inbox:server` 的消息以 `退回 🔄 R{N} Step {N} — 原因` 开头。

**Server 行为：**
1. 正则匹配 `r"退回 🔄 (R\d+) Step (\d+)"` 提取轮次和步骤号
2. 检查管线状态：已完成/已归档/已取消/已卡死 → 忽略
3. 累计退回计数：第 4 次退回 → 标记 `stuck`（卡死），通知 PM 人工介入
4. 确定回退起点：Step 1~2 → 回到 Step 1（需求环节），Step 3+ → 回到 Step 2（编码环节）
5. 重置 affected Step 的 `status`→`pending`、`output`→`null`、`result_msg`→`""`
6. 持久化 + 通知 PM：`🔄 R{N} Step {N} 被退回（累计 N/3）`

**后续流程：**
- 驳回后**不自动重新派活**，由 PM 在群聊中人工决策
- PM 可选择：重新派活当前 bot 重做，或使用 `##advance##R{N}##step=N` 跳过

### 7.8 归档协议（R124）

管线完成时（最后一步推进成功）自动触发归档。PM 也可以手动使用 `##archive##R{N}` 命令归档。

**自动归档触发：** `_try_advance_pipeline` 在最后一步（Step 6）推进成功后调用 `_archive_pipeline(round_name)`。

**手动归档触发：** PM 向 `_inbox:server` 发送 `##archive##R{N}`。

**归档行为：**
1. 从活跃 PipelineManager 中移除该管线上下文
2. 构造归档记录（含 steps、artifacts、references、summary 等完整快照）
3. 追加到 `pipeline_archive.json`（保留最近 30 条）
4. 成功写入后通知 PM：`📦 R{N} 管线已完成并归档`
5. 写入失败仅记录 warning，不抛异常

**后续查询：** `##status##R{N}` 可查询已归档管线的状态快照（从 `pipeline_archive.json` 读取）。

### 7.9 安全守卫

- **PM 禁止使用 `_inbox:server`** — PM 误发 `_inbox:server` 会被 server 拒绝并报错：`_inbox:server 仅接受 bot 消息`
- **## 命令在 PM 守卫前拦截** — `##start`/`##status`/`##stop` 命令可由任何认证 agent 发送，不限制 PM 身份
- **Bot 不能直接回复 PM 的 inbox** — R87 起 bot 应统一用 `_inbox:server`，不再直接回复 `_inbox:<PM_id>`

### 回复格式规则

inbox 消息是**工作任务通信**，不是日常聊天。回复必须遵守以下规则。

#### ❌ 禁止行为

| 禁止 | 原因 |
|:-----|:------|
| **不要输出思考过程** | 不要回 `"我看到你的消息，正在思考..."` / `"让我分析一下..."` 等内部推理过程 |
| **不要当成聊天对话** | 不要问候、寒暄、闲聊。每发一条消息消耗 token |
| **不要重复对方内容** | 不要回 `"收到你的消息: XXXX"` 原样复述 |
| **不需要的格式** | 不要用代码块、表格、Markdown 富文本 |
| **不要拆成多条** | 一次说完，不要拆成多条消息逐条发 |

#### ✅ 正确格式

| 步骤 | 正确回复 | 说明 |
|:-----|:---------|:-----|
| Step 2 ACK | `收到 ✅ R{xx} 收到` | 必须 `收到 ✅` 开头，发 `_inbox:server` |
| Step 3 完成 | `已完成 ✅ R{xx} Step {N}##key=value` | 必须 `已完成 ✅` 开头，发 `_inbox:server` |
| Step 4 确认 | （server 自动发） | bot 收到后不回复 |

#### 核心原则

> **回复只包含 PM 需要知道的信息：确认 / 结果 / 完成。不需要 PM 听你的思考过程或推理步骤。**
>
> 完整群聊礼仪规则见 [WORKSPACE_RULES.md](https://github.com/datahome73/ws-bridge/blob/main/docs/WORKSPACE_RULES.md)。

---

```
时间    小谷                          _inbox:server              Bot
  │      │                              │                        │
  │      ├─ Step 1: 派活 ──────────────│───────────────────────→│  向 bot 收件箱发任务
  │      │                              │                        │
  ├─ 2s ─┤←── 系统转发 ACK ────────────│←── Step 2: ACK ────────┤  Bot 秒回 收到 ✅
  │      │                              │                        │
  │      │                              │           [实际干活: git push dev]
  │      │                              │                        │
  ├─ Ns ─┤←── 转发完成 + 推进 ─────────│←── Step 3: 完成 ──────┤  Bot 回 已完成 ✅ 到 server
  │      │                              │   ##key=value 注入      │  （含 ##key=value）
  │      │                              │── Step 4: 确认 ─────→│  Server 自动回确认
  │      │                              │                        │
  v      v                              v                        v
```

---

## §B: Relay Prefix Protocol（`##` 命令）

R111 引入的 `##` 命令体系，用于管线生命周期管理。

### B.1 命令列表

| 命令 | 格式 | 功能 | 发送者 | 轮次 |
|:-----|:-----|:------|:-------|:----:|
| `##start` | `##start##R{N}##round_title=xxx##requirements_url=xxx` | 创建管线 + 派活 Step 1 | 任何认证 bot | R111 |
| `##status` | `##status##R{N}` | 查询管线当前状态 | 任何认证 bot | R111 |
| `##stop` | `##stop##R{N}` | 停止/取消管线 | 任何认证 bot | R111 |
| `##advance` | `##advance##R{N}##step=N` | 手动推进到指定 Step（PM 使用） | 仅 PM | R124 |
| `##archive` | `##archive##R{N}` | 手动归档管线（PM 使用） | 仅 PM | R124 |
| `##help` | `##help` | 列出支持的命令 | 任何认证 bot | R111 |

### B.2 `##start` 消息格式

```text
##start##R115##round_title=概述文档##requirements_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-product-requirements.md
```

**解析方式：** `str.split("##")`

```python
# "##start##R115##round_title=概述文档"
# split("##") → ["", "start", "R115", "round_title=概述文档"]
```

| 段位置 | 内容 | 说明 |
|:------:|:-----|:------|
| `parts[0]` | `""` | 前缀为空（消息以 `##` 开头） |
| `parts[1]` | `start` | 命令名 |
| `parts[2]` | `R115` | 轮次名（自动 `.upper()`） |
| `parts[3:]` | `key=value` | 可选数据段 |

### B.3 `##start` 流程

```
PM 发 ##start##R115##round_title=概述文档
    ↓
_handle_hash_cmd:
  ├─ 解析 round_name="R115"
  ├─ 解析 kv={round_title: "概述文档"}
  ├─ mgr.exists("R115") → 防重复检查
  ├─ 构建 PipelineContext（6 步标准模板）
  ├─ mgr.set_context + transition_to(RUNNING)
  ├─ _auto_dispatch(ctx, 1) → 派活 Step 1
  └─ 回复发送者: "✅ R115 管线已启动，Step 1 已派活"
```

### B.4 `##status` 流程

```text
##status##R115 → 回复管线状态文本
```

**回复示例：**
```
📊 R115 管线状态
  状态: RUNNING
  当前步: Step 2
  Step 1: ✅ 小谷
  Step 2: 🟢 小开
  Step 3: ⬜ 爱泰
  Step 4: ⬜ 小周
  Step 5: ⬜ 泰虾
  Step 6: ⬜ 小爱
```

### B.5 `##stop` 流程

```text
##stop##R115 → 管线状态变更为 CANCELLED
```

**回复示例：**
```
🛑 R115 管线已停止（CANCELLED）
```

### B.6 `##help` 流程

```text
##help → 列出所有 ## 命令
```

---

## §C: Step 完成协议

R113+ 引入了 `已完成 ✅ R{N} Step {N}##key=value` 格式，替换旧的 `✅ 完成` 格式。

### C.1 格式定义

```text
已完成 ✅ R{N} Step {N}##key1=value1##key2=value2
```

### C.2 解析规则

| 步骤 | 操作 |
|:-----|:------|
| 1 | 正则匹配 `r"已完成 ✅ R(\d+) Step (\d+)"` → 提取 round_name 和 step_num |
| 2 | `content.split("##")`，跳过第 0 段（已完成 ✅ ... 前缀段） |
| 3 | 后续每段按第一个 `=` 分割为 key 和 value |
| 4 | key 全小写蛇形，value 保留原始内容（URL、SHA 等） |
| 5 | `ctx.artifacts[step_key] = {key1: value1, ...}` |
| 6 | `mgr.save()` 持久化 |

### C.3 边界行为

| 场景 | 行为 |
|:-----|:------|
| 无 `##` | `_extract_artifact_kv()` 返回 `{}`，仅推进 Step |
| 单条 KV | 正常提取 |
| 多条 KV | 全部提取，存入 `artifacts[step_key]` |
| URL 含 `=` | 安全（仅第一个 `=` 做分隔符） |
| 空 value | 接受（插入空字符串） |
| 不含 `=` 的段 | 忽略（log debug） |
| 重复 key | 后者覆盖前者 |
| value 含 `##` | **禁止**。应用 `%23` 编码 |

---

## §D: 8 场景 `##key` 清单

### D.1 场景总表

| 场景 | Step | 发送者 | 前缀 | `##` keys |
|:-----|:----:|:-------|:-----|:----------|
| A — 创建管线 | — | PM | `##start##R{N}` | `round_title`, `requirements_url` |
| B — 工作计划提交 | 1 | PM | `已完成 ✅ R{N} Step 1` | `work_plan_url` |
| C — 设计方案提交 | 2 | 小开 | `已完成 ✅ R{N} Step 2` | `tech_plan_url`, `design_decision` |
| D — 编码提交 | 3 | 爱泰 | `已完成 ✅ R{N} Step 3` | `commit_sha`, `files_changed`, `commit_description`, `branch_name` |
| E — 代码审查提交 | 4 | 小周 | `已完成 ✅ R{N} Step 4` | `review_report_url`, `review_decision` |
| F — 测试报告提交 | 5 | 泰虾 | `已完成 ✅ R{N} Step 5` | `test_result`, `test_report_url`, `test_commit_sha` |
| G — 合并部署 | 6 | 小爱 | `已完成 ✅ R{N} Step 6` | `merge_commit_sha`, `deploy_version` |
| H — 关闭管线 | — | PM | `##stop##R{N}` | （无） |

### D.2 场景 A — 创建管线

发送到 `_inbox:server`：

```text
##start##R115##round_title=概述文档##requirements_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-product-requirements.md
```

| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `round_title` | 轮次人类可读标题 | ✅ |
| `requirements_url` | PRD 需求文档 raw URL | ✅ |

### D.3 场景 B — 工作计划提交（Step 1）

```text
已完成 ✅ R115 Step 1##work_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/WORK_PLAN.md
```

| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `work_plan_url` | WORK_PLAN 文档 raw URL | ✅ |

### D.4 场景 C — 设计方案提交（Step 2）

```text
已完成 ✅ R115 Step 2##tech_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-tech-plan.md##design_decision=重构 handler 为纯函数模式
```

| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `tech_plan_url` | 技术方案文档 raw URL | ✅ |
| `design_decision` | 关键设计决策摘要 | 可选 |

### D.5 场景 D — 编码提交（Step 3）

```text
已完成 ✅ R115 Step 3##commit_sha=abc1234def5678##files_changed=server/main.py,server/handler.py##commit_description=Add pipeline auto-archive feature##branch_name=dev
```

| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `commit_sha` | 提交的 commit SHA（推荐全量，至少 7 位） | ✅ |
| `files_changed` | 变更文件列表，逗号分隔 | ✅ |
| `commit_description` | 提交说明文字 | 可选 |
| `branch_name` | 推送目标分支（默认 dev） | 可选 |

### D.6 场景 E — 代码审查提交（Step 4）

```text
已完成 ✅ R115 Step 4##review_report_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-review-report.md##review_decision=通过
```

| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `review_report_url` | 审查报告 raw URL | ✅ |
| `review_decision` | 审查结论：`通过` / `需修改` / `退回` | ✅ |

### D.7 场景 F — 测试报告提交（Step 5）

```text
已完成 ✅ R115 Step 5##test_result=PASS##test_report_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R115/R115-test-report.md##test_commit_sha=def5678
```

| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `test_result` | 测试结果：`PASS` / `FAIL` | ✅ |
| `test_report_url` | 测试报告 raw URL | ✅ |
| `test_commit_sha` | 测试提交的 commit SHA | 可选 |

### D.8 场景 G — 合并部署（Step 6）

```text
已完成 ✅ R115 Step 6##merge_commit_sha=ghi9012##deploy_version=v2.73
```

| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `merge_commit_sha` | 合并 dev→main 的 merge commit SHA | ✅ |
| `deploy_version` | 部署版本号 / Docker Tag | 可选 |

### D.9 `##key` 一览（快速索引）

| key | 所属场景 | 说明 |
|:----|:---------|:-----|
| `round_title` | A | 轮次标题 |
| `requirements_url` | A | PRD URL |
| `work_plan_url` | B | WORK_PLAN URL |
| `tech_plan_url` | C | 技术方案 URL |
| `design_decision` | C | 设计决策摘要 |
| `commit_sha` | D, F, G | commit SHA |
| `files_changed` | D | 文件列表 |
| `commit_description` | D | 提交说明 |
| `branch_name` | D | 目标分支 |
| `review_report_url` | E | 审查报告 URL |
| `review_decision` | E | 审查结论 |
| `test_result` | F | 测试结果 |
| `test_report_url` | F | 测试报告 URL |
| `test_commit_sha` | F | 测试 commit SHA |
| `merge_commit_sha` | G | 合并 commit SHA |
| `deploy_version` | G | 部署版本 |

---

## §E: R114 Dev 上下文注入

Arch→Dev 派活 Step 3 时，派活模板应注入以下上下文，确保 Dev 有足够信息开展工作：

| # | 字段 | 说明 | 必填 |
|:-:|:-----|:------|:----:|
| 1 | `tech_plan_url` | 技术方案文档 URL | ✅ |
| 2 | `requirements_url` | 需求文档 URL | ✅ |
| 3 | `scope_files` | 涉及文件列表（10+ 文件时缩写 `N files`） | ✅ |
| 4 | `base_branch` | 目标合并分支 | ✅ |
| 5 | `design_decision` | 关键技术决策摘要 | ✅ |
| 6 | `api_contract` | 接口定义（如变更需描述变更点） | 可选 |
| 7 | `data_model_change` | 数据模型变更说明 | 可选 |
| 8 | `test_scope` | 测试重点方向 | 可选 |

**模板示例：**
```
💻 {round} Step 3 — 编码实现

技术方案：{tech_plan_url}
需求文档：{requirements_url}
涉及文件：{scope_files}
目标分支：{base_branch}
设计决策：{design_decision}
接口变更：{api_contract}
数据模型：{data_model_change}
测试重点：{test_scope}

请根据技术方案编码实现，完成后回复：
已完成 ✅ {round} Step 3##commit_sha=xxx##files_changed=xxx##branch_name=dev
```

---

## §F: Step 6 部署 SOP

QA→Ops 交接的 7 字段 + 部署命令序列 + 验证清单。

### F.1 交接字段

| # | 字段 | 说明 | 必填 |
|:-:|:-----|:------|:----:|
| 1 | `branch` | 目标部署分支 | ✅ |
| 2 | `commit_sha` | 部署的 commit SHA | ✅ |
| 3 | `image_tag` | Docker 镜像 Tag | 可选 |
| 4 | `test_summary` | 测试结果概要 | ✅ |
| 5 | `test_report_url` | 测试报告 URL | ✅ |
| 6 | `deploy_ports` | 暴露端口（默认 8765/8766） | 可选 |
| 7 | `health_check_path` | 健康检查路径（默认 `/health`） | 可选 |

### F.2 部署步骤

```bash
# 1. 拉取合并后的代码
cd /opt/ws-bridge
git checkout main && git pull origin main

# 2. 构建 Docker 镜像
docker build -t ws-bridge:r{xx} .

# 3. 停止旧容器
docker stop ws-bridge
docker rm ws-bridge

# 4. 启动新容器
docker run -d --name ws-bridge \\
  --restart unless-stopped \\
  -p 8765:8765 -p 8766:8766 \\
  -v /opt/ws-bridge/data:/app/data \\
  -e WS_DATA_DIR=/app/data \\
  -e WS_APP_ID=hermes-ws \\
  ws-bridge:r{xx}

# 5. 健康检查
curl -s http://localhost:8765/health
# 预期: "ok"
curl -s http://localhost:8766/health
# 预期: "ok"
```

### F.3 验证清单

| # | 验证项 | 方法 |
|:-:|:-------|:-----|
| 1 | WS 端口可达 | `curl http://localhost:8765/health` → `ok` |
| 2 | HTTP 端口可达 | `curl http://localhost:8766/health` → `ok` |
| 3 | 管线数据恢复 | `##status##R{xx}` 返回正确状态 |
| 4 | API 可访问 | `curl /api/pipelines` 返回数据 |
| 5 | 日志无 ERROR | `docker logs ws-bridge --tail 50` 无异常 |

---

## §G: Bot 通信 Checklist

### G.1 通用 Checklist（所有 bot）

| # | 行为 | 要求 |
|:-:|:-----|:-----|
| 1 | 收到 `_inbox:` 消息 | 必须处理，不因 `mention_mode` 过滤 |
| 2 | 提取 sender_id | 从 `msg.from_agent` 获取（仅用于识别发件人，不用于回复目标） |
| 3 | 回复 Step 2 ACK | 5 秒内回复到 `_inbox:server`，内容必须以 `收到 ✅` 开头 |
| 4 | 处理任务 | LLM 正常处理（无 context overflow） |
| 5 | 回复 Step 3 完成 | 处理完后回复到 `_inbox:server`，内容必须以 `已完成 ✅` 开头，后跟 `R{N} Step {N}` |
| 6 | 嵌入 `##key=value` | 完成消息中附加本角色定义的所有必填 `##key`（参见 §D 对应场景） |
| 7 | 不回复确认 | 收到 Step 4 确认消息后不再回复 |
| 8 | `mention_mode` | `false`，不过滤关键词 |

### G.2 角色专属 `##key` 输出要求

| 角色 | Step | 完成消息模板 | 必填 keys |
|:-----|:----:|:------------|:----------|
| 小谷 (PM) | 1 | `已完成 ✅ R{N} Step 1##work_plan_url=...` | `work_plan_url` |
| 小开 (arch) | 2 | `已完成 ✅ R{N} Step 2##tech_plan_url=...##design_decision=...` | `tech_plan_url` |
| 爱泰 (dev) | 3 | `已完成 ✅ R{N} Step 3##commit_sha=...##files_changed=...##branch_name=...` | `commit_sha`, `files_changed` |
| 小周 (review) | 4 | `已完成 ✅ R{N} Step 4##review_report_url=...##review_decision=...` | `review_report_url`, `review_decision` |
| 泰虾 (qa) | 5 | `已完成 ✅ R{N} Step 5##test_result=...##test_report_url=...` | `test_result`, `test_report_url` |
| 小爱 (ops) | 6 | `已完成 ✅ R{N} Step 6##merge_commit_sha=...##deploy_version=...` | `merge_commit_sha` |

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v2.0 | 2026-07-10 | R87 升级 — `_inbox:server` 中继 + 前缀规则 |
| v3.0 | 2026-07-15 | R116 重写 — 删除 AutoRouter/Gateway，新增 §B~§G，更新 §2/§4/§7 |
