# A2A 核心机制落地分析 — 补充报告

> **时间：** 2026-07-01
> **目的：** 基于《A2A 协议深度解读》文章，提炼 A2A 核心机制中可直接用于 ws-bridge 的设计模式
> **版本：** 与 `docs/A2A-Protocols-Research-Report.md` 互为补充，本文聚焦「如何落地」
> **参考文章：** 微信公众平台《A2A 协议——让 AI 从单打独斗变成团队作战》

---

## 1. 文章核心要旨

文章把 MCP 和 A2A 的关系总结得很好：

> **MCP gives your agent hands. A2A gives your agent colleagues.**
> MCP = 给 AI 装「手」（连工具）| A2A = 给 AI 找「同事」（连其他 AI）

对应到 ws-bridge：

| 概念 | A2A 术语 | ws-bridge 对应 | 状态 |
|:-----|:---------|:---------------|:----:|
| Agent 间通信 | A2A — 协议层 | WebSocket + TG 消息 | ✅ 已有 |
| Agent 能力声明 | Agent Card | `data/agent_cards.json` | ⚠️ 有但不完整（见下文） |
| 任务派发 | Task Delegation | `!step_complete` + @mention | ⚠️ 待 ACK 化 |
| 任务生命周期 | Submitted→Working→Completed→Failed | `_step_ack_states` (R63 方向 C) | 🔴 建设中 |
| 结果返回 | Result Return | `!step_complete --output <sha>` | ⚠️ 待结构化 |
| Agent 发现 | Well-Known URI + Registry | 点名注册（R63 方向 B） | 🔴 建设中 |

---

## 2. A2A 三大核心机制 — 逐项对标 ws-bridge

### 2.1 Agent Card（发名片）

**A2A 标准做法：**

每个 Agent 在固定地址发布一张「电子名片」：

```
URL: https://你的agent域名/.well-known/agent.json
内容:
  - name: 我叫什么
  - capabilities: 我擅长什么（能力列表）
  - endpoint: 怎么联系我（端点地址）
  - auth: 需要什么认证
```

别的 Agent 访问这个地址，就知道你是谁、能干什么。

**对标 ws-bridge 现状：**

| A2A Agent Card 字段 | ws-bridge 现有 | R63 改进方向 |
|:--------------------|:---------------|:-------------|
| `name` | `display_name` ✅ | — |
| `capabilities` | `skills` + `pipeline_roles` ✅ | — |
| `endpoint` | 无 ❌ | Agent 需声明通信通道（ws-bridge / TG / 其他） |
| `auth` | 应用层不感知 ❌ | Agent 需声明认证方式 |
| `well-known URL` | 无 ❌ | 静态配置 vs 动态发现 |
| 注册触发 | `!agent_card set` 手动 | 点名即注册（R63 B2） |

**关键差异分析：**

A2A 的 Agent Card 是 **主动发布 + 被动发现**——Agent 启动时在自己的 URL 上放好 card，别的 Agent 主动来查。ws-bridge 的 Agent Card 是 **被动存储 + 主动查询**——服务端在 `data/agent_cards.json` 里维护，Agent 自己不"发布"。

**对于 ws-bridge，后一种（服务端存储）更合适**——因为 Agent 是多容器分布式部署，不共享文件系统，不适合各自维护 `/.well-known/agent.json`。服务端作为注册中心是更好的架构。

### 2.2 任务派发（Task Delegation）

**A2A 做法：**

```
Agent A 发现有个活自己干不了
  → 查通讯录，找到能干的 Agent B
  → 发标准格式任务请求：
      - 任务是什么
      - 输入是什么
      - 期望输出是什么
  → Agent B 开始干
  → 同步/异步（先回"收到了"，干完再通知）
```

**对标 ws-bridge 现状（R63 C 方向）：**

| A2A 流程 | ws-bridge 当前 | R63 改进 |
|:---------|:---------------|:---------|
| 查通讯录 → 找目标 | `auth.get_users().role` → ❌ 失败 | `_ROLE_AGENT_MAP` ✅ |
| 发任务请求 | 工作室广播文本消息 | 状态机 SENT → DELIVERED |
| 同步/异步 | 异步（PM 等消息） | 异步 + ACK 超时 |
| "收到了"确认 | 无 | 30 秒 ACK 超时 |
| 干完通知 | 目标 Agent 自行 `!step_complete` | 同上 + ACK 状态流转 |

**文章中的重要启发：**

> "这个过程可以是同步的（等它干完），也可以是异步的（先回复'收到了'，干完再通知你）。"

ws-bridge 的管线本质上就是 `sync delegation` 的变体——PM 发出任务，目标 Agent 收到后开始干，干完 `!step_complete` 通知。这里可以借鉴 A2A 的 `INPUT_REQUIRED` 状态——如果 Agent B 需要补充信息才能继续，可以反向向 PM 请求更多上下文，而不是卡死。

### 2.3 结果返回（Result Return）

**A2A 做法：**

- Agent B 干完，用标准格式把结果发回来
- 如果中间需要补充信息，可以多轮对话
- 支持各种内容类型（text/url/data）

**对标 ws-bridge：**

当前 `!step_complete step2 --output <sha>` 只传一个 commit SHA，过于简陋。A2A 的结构化结果返回值得借鉴：

```json
{
  "task_id": "step2",
  "status": "completed",
  "outputs": {
    "doc_url": "https://raw.githubusercontent.com/.../tech-plan.md",
    "commit_sha": "abc123",
    "summary": "技术方案采用纯标准库解析 frontmatter，不做 pyyaml 依赖",
    "artifacts": ["docs/R63/R63-tech-plan.md"]
  }
}
```

**对 ws-bridge 的启发：** `!step_complete` 的 output 字段可以扩展为支持更丰富的结构化产出，但 R63 不做（scope creep），作为 R64+ 候选。

---

## 3. A2A Agent Card → ws-bridge Agent Card 映射方案

### 3.1 当前 Agent Card 结构（R63 前）

```json
{
  "agent_id_xxx": {
    "name": "开发工程师",
    "display_name": "开发工程师",
    "pipeline_roles": ["dev"],
    "skills": ["coding", "python", "ws-bridge"],
    "status": "online"
  }
}
```

### 3.2 A2A 风格扩展建议（R63+ 候选）

```json
{
  "agent_id_xxx": {
    "name": "开发工程师",
    "display_name": "开发工程师",
    "pipeline_roles": ["dev"],
    "skills": ["coding", "python", "ws-bridge"],
    "status": "online",
    "endpoint": {
      "platforms": ["ws-bridge", "telegram"],
      "ws_connection_id": "conn_xxxx",
      "bot_name": "开发工程师"
    },
    "card": {
      "version": "1.0",
      "well_known_url": null,
      "registered_at": 1734567890.0,
      "last_online": 1734567890.0
    },
    "trigger": {
      "mode": "mention",
      "keyword": "开发工程师",
      "ack_timeout_sec": 60
    },
    "auth": null
  }
}
```

### 3.3 对比：A2A vs ws-bridge

| 维度 | A2A（通用跨组织） | ws-bridge（内部团队） |
|:-----|:-----------------|:---------------------|
| 发现方式 | 固定 URL + 注册中心 | 服务端统一存储 |
| 认证 | API Key / OAuth2 / mTLS | 应用层 auth（agent_id + app_id）|
| 能力描述 | JSON Skill 列表 | pipeline_roles + skills |
| 通信 | HTTP/2 + JSON | WebSocket + TG |
| 任务状态机 | 6 种状态 | 4 种（R63）→ 可扩展 |
| 安全性 | 独立认证层 → 防冒充 | 内部网络 + agent_id 验证 |

**核心结论：** ws-bridge 不需要全盘照搬 A2A 的发现+认证+传输层，但可以**借鉴其数据结构设计**——特别是 Agent Card 的字段定义和任务生命周期状态机。

---

## 4. 文章中的场景 vs ws-bridge 管线

文章给的发布会策划场景，跟我们的管线几乎一模一样：

```
用户请求 → Agent A 分析 → 查通讯录 → 派活 Agent B、C → 收集产出 → 整合交付
（项目负责人）   （PM 分析）    （查角色映射） （@arch + @dev）    （!step_complete）  （归档）
```

| 文章场景 | ws-bridge 管线 |
|:---------|:---------------|
| 你跟 Agent A 说「帮我策划发布会」 | 项目负责人审批需求文档 |
| Agent A 分析任务，发现需要文案和设计 | PM 拆分为 Step2~Step6 |
| 查 Agent B 和 C 的名片 | 查 `_ROLE_AGENT_MAP` |
| 给 Agent B 派活「写文案」| `@arch` Step2 |
| 给 Agent C 派活「做设计」| `@dev` Step3 |
| Agent B 查知识库 | Agent 自读需求文档和 WORK_PLAN |
| 两人把成果发回给 Agent A | `!step_complete step2/3 --output <sha>` |
| Agent A 整合结果交给你 | Admin 合并部署归档 |

> **这说明文章描述的 A2A 场景与 ws-bridge 的管线设计在概念层面完全一致。** 区别只在于 ws-bridge 是顺序 Step（先方案再编码），文章是并行派活（文案+设计同时跑）。

---

## 5. 对 ws-bridge 的具体建议

### 5.1 立即可以做的（R63 已有）

| 建议 | 文章对应 | 所在 R63 方向 |
|:-----|:---------|:-------------|
| Agent Card 结构扩展 | Agent Card 字段 | B1 ✅ |
| 点名即注册 | Agent Card 发现 | B2 ✅ |
| 角色→Agent 映射表 | 查通讯录 | B4 ✅ |
| ACK 状态机 | 任务生命周期 Submitted→Working→Completed | C1-C4 ✅ |

### 5.2 建议纳入 R64 规划

| 建议 | 文章启发 | 价值 |
|:-----|:---------|:-----|
| `!step_complete` 支持结构化产出（JSON 而非仅 SHA） | Result Return 标准格式 | 跨 Step 传递更丰富的上下文 |
| 支持 `INPUT_REQUIRED` 状态（目标 Agent 请求更多上下文） | 中间可多轮对话 | 减少因信息不足导致的卡顿 |
| `!pipeline_status` 展示任务生命周期状态（Submitted/Working/Completed/Failed） | Task 状态机 | PM 一目了然当前派发状态 |
| Agent 间并行派活（某些 Step 可同时跑） | 文章中的并行例子 | 缩短管线总耗时 |

### 5.3 不建议做的

| A2A 特性 | 不适合原因 |
|:---------|:-----------|
| Well-Known URI + 固定 URL 发现 | Agent 在 ws-bridge 内部，不需要 HTTP 端点发现 |
| OAuth2 / mTLS 认证 | ws-bridge 已有 app 级 auth |
| 跨组织互联 Agent 发现 | 当前团队固定，不需要外部 Agent 加入 |

---

## 6. 一句话总结

> **A2A 协议是标准化的「Agent 通讯录 + 工单系统」。** ws-bridge 已经做了这事的 60%——有通讯录雏形（Agent Card）、有工单系统（Step 管线）、有协作流程（PM 协调）。R63 补上剩下的 40%：Agent Card 结构化和注册、ACk 保障、倒计时心跳，就从「人肉协调」进化到「协议驱动」。
