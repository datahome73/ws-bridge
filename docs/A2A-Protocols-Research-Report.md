# A2A (Agent-to-Agent) 协议调研报告

> **时间：** 2026-06-24
> **目的：** 调查现有 A2A 开源协议/提案，分析对 ws-bridge 可借鉴点

---

## 目录

1. [协议总览](#1-协议总览)
2. [协议详解](#2-协议详解)
   - [2.1 Google A2A Protocol](#21-google-a2a-protocol)
   - [2.2 Anthropic MCP (Model Context Protocol)](#22-anthropic-mcp-model-context-protocol)
   - [2.3 OpenAI Agents SDK - 智能体编排](#23-openai-agents-sdk)
   - [2.4 FIPA / FIPA-ACL（历史标准）](#24-fipa--fipa-acl历史标准)
   - [2.5 其他相关](#25-其他相关)
3. [协议对比表](#3-协议对比表)
4. [ws-bridge 可借鉴点分析](#4-ws-bridge-可借鉴点分析)
   - [4.1 可直接借鉴的设计模式](#41-可直接借鉴的设计模式)
   - [4.2 可能适配的概念](#42-可能适配的概念)
   - [4.3 无需引入的部分](#43-无需引入的部分)
5. [建议下一步](#5-建议下一步)

---

## 1. 协议总览

| 协议 | 范围 | 组织 | 状态 | 关键特征 |
|:----|:----|:----|:----:|:---------|
| **Google A2A** | Agent ↔ Agent | Google / LF | ✅ v1.0 正式发布 | HTTP+JSON, 任务生命周期, Agent Card 发现 |
| **Anthropic MCP** | Agent ↔ 工具/数据 | Anthropic | ✅ 正式发布 | 工具暴露, 资源访问, Agent-to-Tool |
| **OpenAI Agents SDK** | Agent 编排 | OpenAI | ✅ 正式发布 | handoff, 沙盒, Guardrails |
| **FIPA / FIPA-ACL** | 多 Agent 系统 | IEEE（已休止） | ⏹ 历史标准 | ACL 消息格式, Agent 管理 |
| **AutoGen (AG2)** | 多 Agent 协作 | Microsoft | ✅ 活跃开发 | 对话式 Agent 协作模式 |

---

## 2. 协议详解

### 2.1 Google A2A Protocol

**GitHub：** https://github.com/a2aproject/A2A (24.4k ⭐, 579 commits)
**状态：** v1.0.1 已正式发布, 6 种语言官方 SDK

#### 核心设计

```
┌─────────────────────────────────────────────────────┐
│                    A2A 生态                          │
│                                                     │
│  用户 → A2A Client (Client Agent)                   │
│           → A2A Server (Remote Agent)               │
│               → 内部使用 MCP 调用工具                 │
│                                                     │
│  Agent Card: 自描述 JSON 清单（技能、接口、安全）      │
│  Task: 有状态工作单元 (Submitted → Working →        │
│                        Completed/Failed/Canceled)    │
│  Message: 单次通信 (role=user/agent, 含 Parts)       │
│  Part: 内容容器 (text/raw/url/data)                  │
└─────────────────────────────────────────────────────┘
```

#### 传输层

- **HTTP/2 + JSON**（核心绑定）
- 也支持 **gRPC** 和 **HTTP+JSON** 作为协议绑定（通过 `AgentInterface.protocol_binding`）
- 三种交互模式：
  1. **Request/Response (Polling)** — 客户端轮询
  2. **Streaming (SSE)** — 服务端事件流
  3. **Push Notifications** — 异步推送 Webhook

#### 关键概念

| 概念 | 作用 | 等价于 ws-bridge |
|:-----|:-----|:-----------------|
| **Agent Card** | 自我描述的 JWT 签名元数据，包含技能列表、接口 URL、安全需求 | — |
| **Task** | 有状态工作单元，有生命周期状态机 | 工作室任务/管道 |
| **contextId** | 跨多轮/多任务的分组 ID | 类似 session / 工作室 ID |
| **taskId** | 单个任务的唯一 ID | 类似消息/任务 ID |
| **Message** | 一次通信，含 role (user/agent) + Parts | 类似 ws-bridge 消息 |
| **Part** | 内内容容器（text/raw/url/data） | 类似 ws-bridge 消息部分 |
| **Artifact** | 任务的输出成果（文件、结构化数据） | 类似任务产出/报告 |
| **Skills** | Agent 能力描述（id, name, description, tags, examples） | 类似角色能力 |
| **SecurityScheme** | 认证（API Key, OAuth2, OIDC, mTLS, Bearer） | — |

#### 任务生命周期

```
SUBMITTED → WORKING → COMPLETED
                    → FAILED
                    → CANCELED
                    → REJECTED
                    → INPUT_REQUIRED（中断-等待输入）
                    → AUTH_REQUIRED（中断-等待认证）
```

#### Agent 发现

1. **Well-Known URI** — `/.well-known/agent.json`
2. **Curated Registry** — 注册中心目录
3. **Direct Configuration** — 直接配置

#### 安全模型

- API Key (query/header/cookie)
- HTTP Auth (Bearer, Basic, Digest)
- OAuth 2.0 (Auth Code + PKCE, Client Credentials, Device Code)
- OpenID Connect
- Mutual TLS
- Agent Card 支持 JWS 签名验证

#### 官方 SDK

Python, JavaScript, Java, C#/.NET, Golang, Rust

---

### 2.2 Anthropic MCP (Model Context Protocol)

**网站：** https://modelcontextprotocol.io
**状态：** 正式发布, 被 Claude, ChatGPT, VS Code, Cursor 等广泛支持

#### 设计定位

> MCP = Agent-to-Tool（不是 A2A）
> A2A = Agent-to-Agent

MCP 的核心是**给 AI 应用暴露工具和数据源**。每个 MCP 服务器暴露：
- **Tools** — 可调用函数 (function calling)
- **Resources** — 数据资源（文件、数据库、API）
- **Prompts** — 预定义模板

#### A2A 与 MCP 的关系

```
┌─────────────────────────────────────────────────┐
│                   A2A 协议                        │
│   Agent A ───────── Agent B ───────── Agent C    │
│               (A2A)          (A2A)               │
│                 │                                 │
│              ┌──┴──┐                              │
│              │ MCP │ (内部使用)                     │
│              │工具集│                               │
│              └─────┘                              │
└─────────────────────────────────────────────────┘
```

Google 官方定位：
> **MCP** 用于 Agent 连接工具、数据和 API（"USB-C for AI"）
> **A2A** 用于 Agent 之间直接对话协作（"open standard for inter-agent"）

两者互补：A2A agent 内部可以用 MCP 调用工具。

#### 对 ws-bridge 的启示

MCP 协议设计本身非常成熟，已经有标准的 JSON-RPC 消息格式和 Server/Client 架构。但其消息格式和传输设计可参考。

---

### 2.3 OpenAI Agents SDK

**网站：** https://developers.openai.com/agents
**状态：** 正式发布

#### 核心 Agent 编排模式

OpenAI 的 Agent 编排采用的是**同进程内 handoff 模式**（不是跨网络 A2A）：

- **Agent Handoff** — 一个 agent 将任务转移给另一个 agent
- **Orchestration** — 协调多 Agent 协作
- **Guardrails** — 安全边界检查
- **Sandbox Agents** — 隔离执行环境

#### 与 ws-bridge 的差异

OpenAI SDK 的 Agent 通信是在同一个进程内，通过函数调用/手递手完成，不需要网络协议。而 ws-bridge 的 Agent 是通过消息平台跨进程通信的。

---

### 2.4 FIPA / FIPA-ACL（历史标准）

**状态：** IEEE 标准, 1996-2000s, 现已休止

#### 关键贡献

FIPA（Foundation for Intelligent Physical Agents）是最早的多 Agent 系统标准，定义了：

1. **Agent Management** — Agent 平台、目录服务、Agent 生命周期
2. **Agent Communication Language (FIPA-ACL)** — 用 speech act 理论定义的消息格式
3. **Agent Interaction Protocols** — 协商、拍卖、合同网等交互协议

#### FIPA-ACL 消息结构

```json
{
  "performative": "request",
  "sender": "agentA",
  "receiver": "agentB",
  "content": "...",
  "language": "SL",
  "ontology": "travel",
  "protocol": "fipa-request"
}
```

**Performative 类型：** inform, request, query, propose, accept-proposal, reject-proposal, cancel, confirm, disconfirm 等 22 种

#### 与 ws-bridge 的关联

FIPA 的 **Agent 管理 / 目录服务 / 交互协议** 概念与 ws-bridge 的**角色体系 / 工作室管理 / 点名报到**在抽象层面有相似性。

---

### 2.5 其他相关

#### Microsoft AutoGen (AG2)

- 多 Agent 对话式协作框架
- 通过 `AssistantAgent` / `UserProxyAgent` 实现对话流转
- Agent 之间通过消息队列/事件驱动通信
- 没有标准化网络传输协议（框架内部）

#### 其他社区提案

- **Agent Communication Protocol (ACP)** — 部分社区提案，但尚未形成规范
- **Agent Network Protocol (ANP)** — 概念阶段，未见正式规范

---

## 3. 协议对比表

| 维度 | Google A2A | Anthropic MCP | OpenAI Agents SDK | FIPA-ACL |
|:----|:----------:|:-------------:|:-----------------:|:--------:|
| **交互方向** | Agent↔Agent | Agent→Tool | Agent↔Agent (进程内) | Agent↔Agent |
| **传输** | HTTP/2 + gRPC | stdio + SSE | 进程内函数调用 | IIOP/CORBA |
| **消息格式** | Protobuf/JSON | JSON-RPC | 函数调用 | ACL (SL) |
| **状态管理** | Task 状态机 | 无状态 | 会话级别 | 会话级别 |
| **发现机制** | Agent Card / Agent 注册表 | 本地配置 | 代码定义 | 目录服务 (DF) |
| **安全** | OAuth2/OIDC/mTLS/API Key | OAuth2 | API Key | — |
| **开源** | ✅ Apache 2.0 | ✅ MIT | ✅ MIT | — |
| **成熟度** | v1.0.1 正式版 | 正式版 | 正式版 | 历史标准 |
| **SDK 语言** | Python, JS, Java, C#, Go, Rust | Python, TS, Java, Kotlin | Python | Java (JADE) |
| **发布方** | Google / LF | Anthropic | OpenAI | IEEE |

---

## 4. ws-bridge 可借鉴点分析

ws-bridge 本质上已经是一个 **Agent-to-Agent 消息总线**——Agent 之间通过消息平台（Telegram）交换消息。这比大部分 A2A 协议更"实战"（Agent 已经在线上协作）。

以下按**应用可行性**排序：

### 4.1 可直接借鉴的设计模式

#### 🟢 A2A **Task 生命周期状态机**

A2A 定义的 Task 状态机（SUBMITTED → WORKING → COMPLETED/FAILED/CANCELED）与 ws-bridge 的**流水线步骤状态**高度吻合。当前 ws-bridge 的 Step 1→6 是线性前进的，没有明确的状态定义和异常处理。

**建议：**
- 引入类似 TaskState 的状态枚举，给每个流水线任务加上生命周期
- 当前 ws-bridge 的 Step 状态可以映射为：待启动 → 进行中 → 已完成/已驳回/已取消
- 特别借鉴 `INPUT_REQUIRED` 状态（对应 code review 驳回等待修复）

#### 🟢 A2A **contextId + taskId 双层 ID**

A2A 用 `contextId` 分组一组相关任务（如一个轮次的所有步骤），用 `taskId` 标识单个任务。

**建议：**
- ws-bridge 已经有 R{N} 轮次 ID，但缺少统一的 context 概念
- 可以引入 `contextId` → 对应一个轮次/一个问题
- 当前的消息 thread ID 可以类比 A2A 的 contextId

#### 🟢 A2A **Agent Card（自描述 Agent 元数据）**

A2A 的核心创新之一是 Agent Card——一个 JWT 签名的 JSON 元数据，描述 Agent 的身份、技能列表、接口和安全需求。

**建议：**
- ws-bridge 角色已经有了名称（admin-bot/PM-bot/arch-bot/dev-bot/review-bot/QA-bot）和职责，但没有**机器可读的元数据**
- 可以为每个角色定义一个轻量级别的 "Skill Card"，包含：
  - 角色 ID 和名称
  - 能力描述（can_review, can_test, can_code）
  - @ 触发前缀（!code、!qa、!review）
  - 可用/不可用时段
  - 当前状态（online/offline/busy）

#### 🟢 A2A **Part 容器设计**

A2A 的 Part 是一个灵活的**多模态内容容器** (text/raw/url/data)，可以用 MIME 类型标注。

**建议：**
- ws-bridge 消息目前主要是纯文本
- 可以引入 Part 概念：一条消息可以包含多个 Part（文本说明 + 代码片段 + 文件引用 + 结构化数据）
- 这正好可以用来支持更多样化的 Agent 协作（如：发送消息时附带结构化 JSON 数据）

#### 🟢 A2A **Streaming + Push 双模式**

A2A 支持同步轮询、SSE 流式、异步 Webhook 三种交互模式。

**建议：**
- ws-bridge 目前主要靠 Telegram 消息推送（可视为 Push 模式）
- 可以增加 Stream 模式概念：对长时间运行的任务（如测试），先返回 "working" 状态消息，完成后推送结果

### 4.2 可能适配的概念

#### 🟡 A2A **Agent 发现机制**

A2A 定义了 Well-Known URI (`/.well-known/agent.json`) 和注册表两种发现模式。

**建议：**
- ws-bridge 当前 Agent 是静态配置的
- 可以借鉴动态发现：新 Agent 上线时通过注册表广播自己的角色和能力
- 当前点名报到协议可以视为一种发现机制

#### 🟡 A2A **SecurityScheme 模型**

A2A 的认证模型非常完备（API Key、OAuth2、OIDC、mTLS）。

**建议：**
- ws-bridge 当前没有 Agent 级认证
- 可以引入轻量 API Key 认证，用于区分不同平台的 Agent 实例

#### 🟡 FIPA **Performative（语言行为）模型**

FIPA-ACL 的 22 种 performative 类型（inform, request, propose, etc.）为 Agent 通信提供语义层。

**建议：**
- ws-bridge 的前缀触发词（📢📋 !code !qa 等）本质上是 performative 的简化版
- 可以扩展 trigger 词到更多语义类型
- 但 ws-bridge 当前的前缀设计已经足够好用，**不推荐推翻重来**

### 4.3 无需引入的部分

| 概念 | 原因 |
|:-----|:-----|
| **A2A 的 Agent Card JWT 签名** | ws-bridge 在当前内网阶段不需要签名的 Agent 身份验证 |
| **FIPA 的 CORBA/IIOP 传输** | 已过时，ws-bridge 不需要 |
| **MCP 的 JSON-RPC 协议** | ws-bridge 走消息平台，不需要 RPC 层 |
| **OpenAI 的 guardrails 框架** | ws-bridge 的使用方式不同，直接在 prompt 层解决 |
| **复杂的 OAuth2 流程** | 当前阶段不需要，可以用简化的 API Key + 白名单 |

---

## 5. 建议下一步

### 短期（可立即实施的改造）

1. **给流水线步骤加上状态机**（借鉴 A2A Task State）
   - 每个 Step 加上 `state: pending | in_progress | completed | rejected | cancelled`
   - 审查驳回 = `INPUT_REQUIRED` 状态
2. **给每个角色加上 Agent Card 概念**（轻量级）
   - 在 `WORKSPACE_RULES.md` 或配置文件中定义机器可读的角色元数据
   - 用于动态路由消息到正确的 Agent
3. **引入 Part 容器到消息模型中**
   - 一条 Agent 消息可以携带多段内容（文本 + 代码 + JSON 数据）

### 中期（需要设计讨论）

4. **Agent 动态发现机制**
   - 新 Agent 加入时自动广播能力
   - 替代当前静态配置
5. **Streaming 任务模式**
   - 对长时间任务先返回 "已接收" 状态，完成后推送达结果
   - 适用于测试执行、代码 build 等

### 长期（可做可不做）

6. **规范化消息 performative 语义**（FIPA 启发）
   - 让消息不仅仅是文本，而是带有语义类型的结构化交换
7. **跨 ws-bridge 实例的 A2A 兼容**
   - 如果 ws-bridge 开源后被其他团队使用，多个 ws-bridge 实例之间需要 A2A
   - 那时 Google A2A 协议可以作为实例间通信的标准化方案

---

> **结论：** Google A2A v1.0 是目前最成熟、最完整的 A2A 协议提案，已经在 Linux Foundation 下开源。虽然 ws-bridge 的场景（消息平台上的 Agent 协作）与 A2A 的标准场景（HTTP API 上的 Agent 通信）不同，但 A2A 的设计模式（Task 状态机、Agent 自描述、Part 容器、Streaming/Push 模式）对 ws-bridge 很有参考价值，特别是**状态管理和角色元数据**这两个方向。
