# Agent Team 协作模式调研报告

> **时间：** 2026-07-01
> **目的：** 分析 Agent Team（多智能体协调团队）协作模式，提炼对 ws-bridge 多 Agent 开发现状的借鉴价值
> **参考文献：** Google A2A Protocol、OpenAI Agents SDK、Anthropic Claude Code Agent Team、CrewAI、AutoGen、LangGraph、Microsoft TaskWeaver
> **参考文章：** 《多智能体协作:一个 Agent 搞不定,就拆成一个团队》（微信公众平台）

---

## 目录

1. [Agent Team 模式总览](#1-agent-team-模式总览)
2. [典型模式分析](#2-典型模式分析)
   - [2.1 角色分工模式 (Role-Based Team)](#21-角色分工模式-role-based-team)
   - [2.2 编排-执行模式 (Orchestrator-Worker)](#22-编排-执行模式-orchestrator-worker)
   - [2.3 圆桌会议模式 (Roundtable/Debate)](#23-圆桌会议模式-roundtabledebate)
   - [2.4 层级委托模式 (Hierarchical Delegation)](#24-层级委托模式-hierarchical-delegation)
   - [2.5 流水线模式 (Pipeline/Assembly Line)](#25-流水线模式-pipelineassembly-line)
3. [各模式对比表](#3-各模式对比表)
4. [ws-bridge 现状映射](#4-ws-bridge-现状映射)
5. [可借鉴的设计模式](#5-可借鉴的设计模式)
   - [5.1 可直接引入](#51-可直接引入)
   - [5.2 可借鉴但需适配](#52-可借鉴但需适配)
   - [5.3 不适合当前场景](#53-不适合当前场景)
6. [建议下一步](#6-建议下一步)

---

## 1. Agent Team 模式总览

### 1.1 核心思路

> **「一个 Agent 搞不定，就拆成一个团队。」**

Agent Team 的核心思想是：**将复杂任务的「研发」「执行」「质检」等环节拆开，交给不同角色、不同能力的 Agent 协作完成**——这正是 ws-bridge 当前的开发模式。

### 1.2 Agent Team 与传统软件工程团队的映射

| Agent Team 概念 | 传统软件工程 | ws-bridge 当前实践 |
|:----------------|:-------------|:-------------------|
| 角色分工 | PM / 开发 / 测试 / 运维 | PM / arch / dev / review / qa / admin |
| 任务分解 | 需求→方案→编码→测试→部署 | Step1→Step2→...→Step6 |
| 编排/调度 | 项目经理派活 + 跟踪 | PM 协调 + `!step_complete` 流转 |
| 通信 | 会议 / IM / 文档 | WebSocket 工作室 / TG DM |
| 质量保障 | Code Review / QA | Code Review Step + QA Step |
| 异常处理 | 项目经理介入 | PM TG 协调 + 超时 watchdog |

### 1.3 当前业界主流框架

| 框架 | 组织 | 协作模式 | Agent Card | 任务路由 | ACK机制 |
|:----|:----|:---------|:----------:|:--------:|:-------:|
| **Google A2A** | Google/LF | 点对点发现 | ✅ Agent Card 标准 | HTTP JSON | ✅ 任务生命周期 |
| **OpenAI Agents SDK** | OpenAI | 编排+委托 | ❌ 无 | Handoff 函数 | ✅ 状态回调 |
| **AutoGen** | Microsoft | 圆桌/流水线 | ❌ 无 | 群聊消息 | ❌ 无内置 |
| **CrewAI** | CrewAI | 角色分工 | ✅ 角色+工具 | 顺序/层级 | ❌ 无 |
| **LangGraph** | LangChain | 状态机图 | ❌ 无 | 图边路由 | ❌ 无 |
| **Claude Code Agent Team** | Anthropic | 编排-执行 | ✅ 角色描述 | 自然语言 | ❌ 无 |
| **TaskWeaver** | Microsoft | 插件编排 | ❌ 无 | 代码生成 | ❌ 无 |

---

## 2. 典型模式分析

### 2.1 角色分工模式 (Role-Based Team)

**代表：** CrewAI / Claude Code Agent Team

**描述：**

将团队按职能切分为多个角色（Researcher, Writer, Reviewer, Coordinator 等），每个 Agent 有明确定义的角色、目标和能力。

```
                    ┌─────────────┐
                    │ Coordinator │  ← 总协调
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────┴──────┐ ┌──────┴──────┐ ┌──────┴──────┐
    │  Researcher │ │    Writer   │ │   Reviewer  │
    └─────────────┘ └─────────────┘ └─────────────┘
```

**关键设计：**
- 每个 Agent 有：**角色名** + **角色目标** + **能力列表** + **可分配工具**
- Coordinator 负责任务分解和分配
- 角色之间不直接通信，通过 Coordinator 协调

**对 ws-bridge 的启发：**
> ✅ ws-bridge 已有本质相同的角色分工（PM/arch/dev/review/qa/admin），但角色定义在代码中而非结构化数据中。

### 2.2 编排-执行模式 (Orchestrator-Worker)

**代表：** OpenAI Agents SDK / Google A2A / TaskWeaver

**描述：**

一个 Orchestrator Agent 负责接收任务、规划、分解、分派给 Worker Agent，并汇总结果。

```
  用户请求
     │
     ▼
┌──────────────┐
│ Orchestrator │ ← 规划 + 分解 + 跟踪
└──────┬───────┘
       │
       ├── Worker A (能力: 搜索)
       ├── Worker B (能力: 编码)
       ├── Worker C (能力: 测试)
       └── Worker D (能力: 部署)
```

**关键设计：**
- Orchestrator 持有完整上下文和任务状态
- Worker 是无状态的执行者，只做分配给自己的事
- Orchestrator 具有 **Plan→Execute→Verify→Re-plan** 循环

**对 ws-bridge 的启发：**
> ✅ 相当于：PM（Orchestrator）+ 各角色（Worker）。PM 持有管线全局状态（`_PIPELINE_STATE`），各角色只执行当前 Step。

### 2.3 圆桌会议模式 (Roundtable/Debate)

**代表：** AutoGen / ChatDev

**描述：**

多个 Agent 围绕同一问题展开多轮讨论，通过「辩论」收敛到最优方案。没有明确的协调者，Agent 之间平等、自洽地沟通。

```
  Agent A ──── Agent B
     │  \        /  │
     │    \    /    │
     │      \/      │
     │      /\      │
     │    /    \    │
     │  /        \  │
  Agent C ──── Agent D
```

**关键设计：**
- 无中心协调，Agent 同级双向通信
- 通过多轮讨论一致性收敛（投票/共识）
- 适合开放型问题、创新方案

**对 ws-bridge 的启发：**
> ⚠️ 不太适合 ws-bridge。ws-bridge 有多明确的 Step 流动方向（需求→方案→编码→审查→测试→部署），不需要 Agent 之间平等辩论。

### 2.4 层级委托模式 (Hierarchical Delegation)

**代表：** LangGraph / 多级编排

**描述：**

Agent 之间存在层级关系，高层 Agent 将子任务委托给下层 Agent，下层可以进一步委托给更下层，形成委托树。

```
       CEO Agent
     ┌────┴────┐
     │         │
  Director   Director
  ┌─┼──┐     ┌─┼──┐
  │ │  │     │ │  │
  W W  W     W W  W
```

**关键设计：**
- 每层有明确的授权范围
- 上层只关心结果，不下沉到细节
- 层数通常 ≤3（超过会严重延迟）

**对 ws-bridge 的启发：**
> ⚠️ 暂时不适合。ws-bridge 的 Step 是顺序流水线，不是树形委托。未来如果扩展为多项目并行，可能用得上。

### 2.5 流水线模式 (Pipeline/Assembly Line)

**代表：** 大多数 CI/CD 工具 / ws-bridge 当前模式

**描述：**

任务依次经过多个阶段，每个阶段由一个或多个 Agent 处理，输出作为下一阶段的输入。

```
 Step1 → Step2 → Step3 → Step4 → Step5 → Step6
 (需求)  (方案)  (编码)  (审查)  (测试)  (部署)
```

**关键设计：**
- 严格的先后顺序约束
- 每个阶段有明确的输入/输出契约
- 阶段间可通过缓冲区解耦

**对 ws-bridge 的启发：**
> ✅ ws-bridge 当前就是这个模式，也是 R63 要降序的目标。

---

## 3. 各模式对比表

| 特征 | 角色分工 | 编排-执行 | 圆桌会议 | 层级委托 | 流水线 |
|:----|:-------:|:--------:|:--------:|:--------:|:-----:|
| 协调方式 | 中心化 | 中心化 | 去中心化 | 层级中心化 | 顺序耦合 |
| 角色化程度 | 高 | 中 | 低 | 高 | 中 |
| 扩缩性 | 好 | 好 | 差 | 中 | 好 |
| 容错性 | 中（孤岛风险） | 中（Orchestrator 单点） | 高 | 中 | 低（前序失败阻塞后续） |
| 适用场景 | 多角色任务 | 复杂任务分解 | 创新/讨论 | 大规模组织 | 确定流程 |
| ws-bridge 对应度 | ✅ 高度吻合 | ✅ PM 对应 Ochestrator | ❌ 不适合 | ⏳ 未来可能 | ✅ 当前模式 |

---

## 4. ws-bridge 现状映射

### 4.1 当前的理想模式

**Role-Based + Orchestrator-Worker + Pipeline** 三合一：

```
                  ┌──────────┐
                  │  项目负责人  │ ← 大宏（TG 决策）
                  └─────┬────┘
                        │ 方向决策
                  ┌─────┴────┐
                  │ PM (协调) │ ← 小谷（管线调度）
                  └─────┬────┘
                        │ Step 流转
  ┌──────────────────────┼──────────────────────┐
  │       │       │       │       │       │      │
  Step1  Step2   Step3  Step4   Step5  Step6
  (需求)  (方案)  (编码)  (审查)  (测试)  (部署)
   PM     arch    dev    review   qa    admin
```

### 4.2 当前的断裂点（R63 要解决的核心问题）

| 断裂 | 根因 | 成熟 Agent Team 的做法 |
|:-----|:-----|:-----------------------|
| 角色未结构化 | Agent Card 存在但不参与路由 | CrewAI/Claude Code 有角色定义 → 自动路由 |
| 派活无 ACK | 单向文本通知，无确认 | A2A 任务生命周期 / Agents SDK 状态回调 |
| 超时无精确心跳 | 10 分钟 watchdog 扫描 | 精确倒计时 + 超时自动切人 |
| 协调者信息延迟 | PM 只能主动问状态 | 心跳推送 + 超时自动告警 |
| 没有注册流程 | Agent 加入不自动绑定 | 注册→能力声明→映射持久化 |

### 4.3 Agent Team 中「最接近」ws-bridge 的实现

**Claude Code Agent Team：**
- 模式：角色分工 + 编排-执行
- Coordinator Agent 持有上下文、分解任务、分配
- 每个角色有明确的工作描述（Role Prompt）
- 每个角色被自然语言 @mention 激活

> **这与 ws-bridge 的工作模式几乎一致**——Coordinator = PM（小谷），各角色 Agent 通过工作室被 @mention 激活执行任务。

**OpenAI Agents SDK：**
- Handoff 模式：当前 Agent 发现自己不擅长某项任务时，主动 Handoff 给另一个 Agent
- Guardrails：在执行前后验证输入/输出
- 状态管理：完整的对话+任务栈

> **Handoff 模式** 对应 ws-bridge 的 `!step_complete` 流转，但 SDK 是主动手递手，ws-bridge 是确认后才流转。

---

## 5. 可借鉴的设计模式

### 5.1 可直接引入

| # | 模式 | 来源 | 对应 ws-bridge 改进 | R63 方向 |
|:-:|:----|:-----|:--------------------|:--------:|
| 1 | **Agent Card 结构化** | A2A / CrewAI | 角色定义从代码抽离为数据结构，含能力、偏好、触发模式 | ✅ B |
| 2 | **注册-发现机制** | A2A Agent Card | 管线启动时 Agent 注册能力 → 服务端构建映射表 | ✅ B |
| 3 | **任务生命周期** | A2A Task Lifecycle | ACK 状态机：submitted→working→completed→failed | ✅ C |
| 4 | **超时 + 自动切人** | 通用 Agent Team 模式 | 精确倒计时 + 超时触发 PM 协调或自动切换备用 | ✅ A |
| 5 | **Coordination @mention** | Claude Code | 用自然语言 @mention 激活 Agent，而非纯系统消息 | ✅ R58 已部分 |
| 6 | **角色→Agent 映射表** | 所有 Agent Team 共通 | `_ROLE_AGENT_MAP` 替代 `auth.get_users().role` 查找 | ✅ B |

### 5.2 可借鉴但需适配

| # | 模式 | 来源 | 描述 | 适配建议 |
|:-:|:----|:-----|:-----|:---------|
| 7 | **Plan→Execute→Verify 循环** | OpenAI Agents SDK | Orchestrator 规划→执行→验证→再规划 | PM 可在 Step 交接时做 `快速验证 → 再分配` 的循环 |
| 8 | **Handoff 函数参数化** | OpenAI Agents SDK | Handoff 时传递上下文 + 工具 | `!step_complete` 已传 output_ref，可扩展传更多上下文 |
| 9 | **多级协调** | LangGraph / Hierarchical | 层级 Agent 树 | 暂不引入，未来多项目并行时考虑 |
| 10 | **Agent 互评** | AutoGen / Debate | Agent 之间互相审查建议 | 可适度引入：review 岗位可以对 dev 的输出给出改进建议（而非仅 pass/fail） |

### 5.3 不适合当前场景

| # | 模式 | 原因 |
|:-:|:----|:------|
| 11 | Agent 之间直接双向通信 | ws-bridge 是顺序流水线，不需要 A↔B↔C 自由对话 |
| 12 | 完全去中心化协调 | 需要中心 PM 对齐决策者和观察者（大宏） |
| 13 | 动态角色发现（A2A 点对点） | 我们的角色是预定义的，不需要运行时发现 |
| 14 | Agent 能力协商 | 我们的角色固定（每个人知道自己能做什么），不需要协商 |
| 15 | 长期工作记忆 | 当前 Step 粒度足够，不需要跨 Session 记忆 |
| 16 | Web 端 Agent UI 编辑 | CLI 命令更符合当前团队习惯 |

---

## 6. 建议下一步

### 6.1 R63 优先级排序

参考 Agent Team 模式成熟度：

| 优先级 | 事项 | 对应模式 | 预计效果 |
|:------:|:-----|:---------|:---------|
| 🔴 P0 | Step 倒计时心跳 | 超时+自动切人 | 解决「PM 只能被动等」的问题 |
| 🔴 P0 | Agent Card 注册 + 角色映射 | Card 结构化 + 注册发现 | 解决「派活找不到目标」的问题 |
| 🔴 P0 | ACK 保障触发 | 任务生命周期 | 解决「发了消息不知道对方有没有收到」的问题 |
| 🟡 P2 | 角色→Agent 映射表增强 | 角色分工 | 在主备映射中增加更多元数据 |
| 🟢 P3 | Handoff 参数扩展 | Handoff 通用 | 跨 Step 传递更多上下文 |
| 🟢 P3 | 快速验证循环 | Plan→Exe→Verify | 在 Step 交接前小验证 |

### 6.2 中期方向（R64+）

| 方向 | 目标 |
|:-----|:------|
| Agent Card 自我声明 | Agent 启动时自动注册能力，无需人工 `!agent_card set` |
| 多管线并行 | 支持同时跑多个 R{n} 管线，每个独立状态 |
| 交接上下文增强 | Step 之间传递的不只是一个 output_ref，而是结构化产出摘要 |
| PM 看板 | 可视化各 Step 状态、超时倒计时、ACK 状态（Web 端） |
| Agent 互评 + 改进建议 | 类似 Code Review 环节，不是单纯 pass/fail，而是给出具体建议 |

### 6.3 与技术无关的组织建议

> **「好的 Agent Team 和好的软件团队一样——不是靠工具，而是靠流程和默契。」**

| 建议 | 说明 |
|:-----|:------|
| **每个 Agent 固定身份** | 不要频繁换角色，让 Agent 的 prompt 积累对自身角色的理解 |
| **交接要有仪式感** | `!step_complete` + `@mention` 的仪式感让 Agent 知道「到我了」 |
| **PM 是决策者的眼线** | PM 不自己做决策，把发现的信息给决策者（大宏）判断 |
| **失败要有回退路径** | 每个 Step 的 Agent 挂了，自动回退到备用（已具备） |
| **书面化胜过口头化** | 所有交接产出是文档/commit，不是口头 OK |

---

## 附：关键概念速查表

| 概念 | 解释 | ws-bridge 对应 |
|:-----|:-----|:---------------|
| Agent Card | Agent 的身份和能力声明 | `data/agent_cards.json` |
| Orchestrator | 负责任务分解和调度的中心 Agent | PM 角色 |
| Handoff | 一个 Agent 将任务转给另一个 Agent | `!step_complete` + 点名下一角色 |
| Task State | 任务的完整生命周期状态 | ACK 状态机：SENT→DELIVERED→ACK→IN_PROGRESS |
| Worker | 执行具体任务的 Agent | arch/dev/review/qa/admin |
| Guardrail | 执行前后的输入/输出校验 | code review + QA 步骤 |
| Plan→Execute→Verify | 规划→执行→验证的迭代循环 | 需求审核→编码→审查验证 |
| Timeout | 任务执行超时后的处理策略 | 倒计时心跳 + PM 协调 |
| ACK | 确认收到任务并开始执行 | Bot 回复「到」/「收到」 |
| Pipeline | 多 Step 顺序执行的任务流水线 | R{n} 管线（Step1→Step2→...→Step6） |
