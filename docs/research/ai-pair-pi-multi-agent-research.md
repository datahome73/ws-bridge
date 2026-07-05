# 竞品 AI 协作项目调研报告

> **目的**：调研 GitHub 上多个 AI 多 Agent 协作项目，分析其看板 UI 和编排架构的亮点，作为 ws-bridge 后续改进的需求参考源。
>
> **状态**：📌 仅作参考，当前阶段不开发
>
> **调研日期**：2026-07-04

---

## 一、项目概览

| 项目 | Stars | 核心定位 | 编排方式 | 看板形态 |
|------|-------|----------|----------|----------|
| **axtonliu/ai-pair** | 288 | 异构 AI 模型团队协作（Claude+Codex+Gemini） | Claude Code Agent Teams | 无独立看板，CLI 输出 |
| **jwangkun/Pi-Multi-Agent** | 124 | 生产级多 Agent 编排框架 | TypeScript 框架 + WebSocket | 🖥️ Next.js Web 看板（三栏） |
| **BlackBeltTechnology/pi-agent-dashboard** | 182 | pi 编码 Agent 实时 Web 看板 | WebSocket 镜像 pi session | 🖥️ 独立 Web 看板 |
| **SeemSeam/claude_codex_bridge** | 3183 | 可见多 Agent CLI 工作台（CCB） | TUI 终端窗口布局 | 🖥️ TUI 工作台 + 手机 App |

---

## 二、各项目详细分析

### 2.1 axtonliu/ai-pair —— 异构模型团队

#### 核心思路

不同 AI 模型天然关注不同维度，组成团队协作时覆盖范围零重叠。一个创建，两个从不同角度审查。

```
团队领导 (Claude Code)
  ├─ 创作者 (Claude Code Agent)     → 写代码/内容
  ├─ Codex 审查者 (→ Codex CLI)      → bug/安全/性能/边界
  └─ Gemini 审查者 (→ Gemini CLI)    → 架构/设计模式/可维护性
```

#### 对 ws-bridge 的启示

| 借鉴点 | 说明 |
|--------|------|
| **异构模型分工** | 不同角色用不同模型，审查维度互补 |
| **退化重试协议** | CLI 超时后按 xhigh→high→medium→low→fallback 降级重试 |
| **文件传递内容** | 用 `mktemp` 临时文件传内容，禁止管道传递（防截断） |
| **预检机制** | 启动前验证所有 CLI 可用，不可用则警告降级 |

> **ws-bridge 现状**：爱泰（开发工程师）已在使用 OpenAI Codex，其他角色用 DeepSeek，已具备初步异构。缺退化重试和预检。

---

### 2.2 jwangkun/Pi-Multi-Agent —— 生产级编排框架（重点）

#### 架构

```
用户任务 → DeepPlanner (LLM 分解 N 子任务)
  → AgentCluster (并行/顺序执行，最多 10 Agent)
  → DeepEvaluator (4 维度质量评估)
  → 质量门禁：未达标 → Replan → Retry 循环
  → 最终输出
```

三种执行模式：Direct（简单对话）、Deep（研究型多 Agent）、Workflow（动态管线编排）。

#### 看板 UI 布局（三栏式）

```
┌─ 左栏 (w-72) ──────────┬─ 中间（聊天区）──────────┬─ 右栏 (w-96, Tab切换) ──┐
│ Agent Cluster          │  · Header               │ Plan / Workflow        │
│  - 总进度条            │    - 阶段 Badge          │ Tasks / Stats          │
│  - Thread 历史列表     │    - 模式选择器          │ Report                 │
│  - Agent 卡片          │    - 清空按钮            │                        │
│    - Avatar + 状态图标  │  · 消息流               │                        │
│    - Priority 标签      │    - 用户消息 (右对齐)   │                        │
│    - Tools 标签         │    - Agent 消息 (左对齐) │                        │
│  - WS 连接灯           │    - Tool Call 卡片       │                        │
│                        │    - Evaluation 评分卡    │                        │
│                        │    - Result 输出          │                        │
│                        │  · 输入框 + 发送按钮      │                        │
└────────────────────────┴─────────────────────────┴────────────────────────┘
```

#### 关键 UI 要素

| 要素 | 实现方式 | 价值 |
|------|----------|------|
| **Phase Badge** | 头部 `Planning→Executing→Evaluating→Completed/Failed` | 管线阶段一目了然 |
| **Thread 历史** | 左侧 session 列表 + 状态标签/时间/字数 | 支持历史恢复 |
| **状态图标集** | 🌀 running / ✅ completed / ❌ failed / 🔄 retrying / ⭕ pending | 比纯文字直观 |
| **进度条** | `completed/total` + 蓝色百分比条 | 管线进度可视化 |
| **Priority Badge** | critical🔴/high🟠/normal🔵/low⚪ 带色 | Step 优先级标记 |
| **Tool Call 卡片** | 蓝底消息气泡，显示调用名称+参数 | Agent 行为透明化 |
| **Evaluation 卡片** | 紫底边框，维度评分 + ✅/❌ + strengths/weaknesses | 审查报告高级展示 |
| **右栏 Tab 系统** | Plan / Workflow / Tasks / Stats / Report | 上下文面板灵活切换 |
| **子任务依赖图** | 可视化子任务间的依赖关系 | 管线拓扑可视化 |

---

### 2.3 pi-agent-dashboard —— 独立 Web 看板

#### 核心功能

| 功能 | 描述 |
|------|------|
| 🖥️ **Diff Viewer** | side-by-side + unified 两种模式，带文件树导航 |
| 📝 **Markdown + Mermaid** | 聊天区渲染流程图 + LaTeX 公式 |
| 💰 **Token/Cost 仪表** | 实时 token 花销 + context usage 进度条 |
| 📁 **图片内联** | Agent 可直接引用本地截图在聊天渲染 |
| ⚡ **Force Kill 升级** | 先软中止 → 再按强制 SIGKILL，会话保留 |
| 🔌 **Extension UI** | 插件声明 table/grid/form 模态 UI，无需写 React |
| 🖥️ **集成终端** | xterm.js + node-pty 完整终端 |
| 📱 **移动端适配** | 响应式 + swipe drawer + 触控优化 |
| 🌐 **mDNS 发现** | 局域网自动发现其他服务器 |
| 🔄 **实时 WebSocket** | session 输出实时流式推送到浏览器 |

---

### 2.4 CCB (claude_codex_bridge) —— TUI 工作台

#### 特色

| 功能 | 描述 |
|------|------|
| 🪟 **Window 布局** | 配置文件用 `A,B;C,D` 定义四宫格，每个 pane 一个 Agent |
| 📍 **侧栏面板** | 每个窗口显示 agent 状态、通信日志、操作提示 |
| 🎭 **Agent Roles Spec** | 角色封装成可安装/挂载/卸载的 Role Pack |
| 📱 **手机远程控制** | Flutter APK，配对后远程操作 agent/发指令/传文件 |
| 📋 **共享记忆文件** | `.ccb/ccb_memory.md` 跨 agent 共享协作规则 |
| 🔧 **自维护 Agent** | `ccb_self` 角色可诊断/恢复/配置 CCB 本身 |

---

## 三、对 ws-bridge 的借鉴建议

### 🥇 最优先借鉴（高价值 + 低实现成本）

| 建议 | 来源 | 说明 |
|------|------|------|
| **1. 管线状态看板** | Pi-Multi-Agent | `/status` 命令返回结构化进度表（进度条 + 各 Step 状态 + 时间 + token 花销） |
| **2. 执行阶段视觉标记** | Pi-Multi-Agent | 消息用 emoji 标记阶段：📋需求→🏗️架构→💻开发→🔍审查→🧪测试→✅完成 |
| **3. 状态图标集** | Pi-Multi-Agent | 统一 🔄/✅/❌/⭕ 标识 Step 状态，替代纯文字 |
| **4. Evaluation 审查评分卡** | Pi-Multi-Agent | 审查/测试完成后发维度和分摘要卡片 |

### 🥈 中期参考（高价值 + 中等实现成本）

| 建议 | 来源 | 说明 |
|------|------|------|
| **5. Thread 历史与恢复** | Pi-Multi-Agent | Session 分配 ID，支持 `/history` `/restore <id>` |
| **6. 子任务依赖图** | Pi-Multi-Agent | 可视化 Step 间依赖关系 |
| **7. Diff 摘要** | pi-agent-dashboard | 审查完成后发关键 diff 摘要（文件数+行数+变更点） |
| **8. 退化重试协议** | ai-pair | Step 超时后降级重试，非直接卡死 |

### 🥉 远期方向（高价值 + 高实现成本）

| 建议 | 来源 | 说明 |
|------|------|------|
| **9. Web 管理看板** | pi-agent-dashboard | 独立 Web 页面，实时管线监控 |
| **10. 手机远程控制** | CCB | 移动端查看/操作管线 |
| **11. 共享记忆文件** | CCB | 跨会话、跨 Agent 持久化上下文 |
| **12. Extension 插件系统** | pi-agent-dashboard | 角色/工具可插拔 |

---

## 四、与 ws-bridge 路线图的关系

```
当前阶段（基础功能开发）
  └─ 优先完成管线闭环：Step 推进 → 执行 → 结果返回
      └─ 不引入上述任何看板/UI 功能

下一阶段（体验优化）
  └─ 可考虑：阶段 emoji 标记、状态图标集、/status 看板

远期（平台化）
  └─ 可考虑：Web 看板、手机 App、插件系统
```

> **原则**：上述建议全部来源于竞品分析，当前仅为需求参考源。具体采纳时机和实现方案由 ws-bridge 架构文档（`docs/ARCHITECTURE-REQUIREMENTS.md`）和 TODO 管理。
