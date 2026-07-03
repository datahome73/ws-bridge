# 调研报告：oh-my-hermes × ws-bridge 整合分析

> 调研日期：2026-07-02
> 来源仓库：[witt3rd/oh-my-hermes](https://github.com/witt3rd/oh-my-hermes) (MIT)
> 作者：Donald Thompson | ⭐ 94 Forks 8 | 2026-04-07 创建
>
> **本文档仅作为背景参考保留，不构成当前或未来的整合计划。**

---

## 一、仓库概况

| 项 | 值 |
|---|---|
| 全称 | `oh-my-hermes` (OMH) |
| 许可 | MIT |
| 语言 | Python |
| 定位 | 为 Hermes Agent 提供多智能体编排技能集——灵感来自 oh-my-claudecode，用 Hermes 原生原语重写 |

## 二、OMH 架构总览

OMH 是一套可组合的 Hermes 技能 + 可选插件，把代码开发流程拆成四个独立阶段：

```
deep-research  →  deep-interview  →  ralplan  →  ralph
  (调研)           (需求访谈)      (共识计划)   (验证执行)
```

### 核心技能

| 技能 | 说明 |
|---|---|
| **omh-ralplan** | 三方共识计划：Planner 起草 → Architect 评审 → Critic 对抗辩论，最多 3 轮直到全员 APPROVE |
| **omh-ralph** | 验证执行：每轮调用做 1 个任务 → 执行 → 验证证据 → 更新状态。3-strike 断路器 |
| **omh-deep-interview** | 苏格拉底式需求访谈，覆盖 Goal/Constraints/Success Criteria/Context 四维度 |
| **omh-deep-research** | 多阶段调研：分解 → 并行搜索 → 综合 → 引文验证 |
| **omh-autopilot** | 端到端流水线：自动检测已有制品跳过已完成阶段，从需求走到验证 |

### OMH 插件 (`plugins/omh/`)

插件为技能提供基础设施层，注册 2 个工具 + 3 个钩子：

| 组件 | 职责 |
|---|---|
| `omh_state` (工具) | 8 个动作：init/read/write/clear/check/cancel/lock/unlock/load_role |
| `omh_gather_evidence` (工具) | 从安全白名单运行构建/测试/lint 命令，捕获截断输出 |
| `pre_llm_call` (钩子) | 检测 `[omh-role:X]` 标记并注入对应角色提示词到子智能体 system prompt |
| `pre_tool_call` (钩子) | 在 `delegate_task` 调用前校验角色名是否有效（fail-fast） |
| `on_session_end` (钩子) | 异常退出时在 `.omh/state/` 写入中断标记 |

### 核心模式

- **`[omh-role:executor]` 标记模式**：子智能体启动时自动注入角色提示词，父级上下文不膨胀
- **子智能体持久模式**：子智能体被要求在确定性路径写入文件，父级验证文件存在
- **原子状态管理**：`.omh/state/` 目录下 JSON，tmp+fsync+os.replace 写入
- **单次调用一个任务**：每次 Hermes 调用只做一件事，干净退出，下次续上

### 角色目录（10+ 个预定义）

| 角色 | 用途 |
|---|---|
| Planner | 任务分解、排序、风险标记 |
| Architect | 结构审查、边界清晰度、长期可维护性 |
| Critic | 对抗挑战、假设测试、压力测试 |
| Executor | 代码实现、测试优先、最小改动 |
| Verifier | 基于证据的完成检查、只读 |
| Security Reviewer | 漏洞、信任边界、注入向量 |
| Test Engineer | 测试策略、覆盖率、边缘情况 |
| Code Reviewer | Diff 审查、惯例、整体质量 |
| Debugger | 根因分析、假设检验、最小化修复 |
| Analyst | 需求提取、隐藏约束、验收标准 |

## 三、OMH 设计哲学

| 原则 | 表现 |
|---|---|
| 去中心化状态 | `.omh/state/` 在项目根，不依赖外部存储 |
| 验证驱动 | 每个任务通过证据验证（构建/测试/lint 通过）才标记完成 |
| 隔离安全 | 子智能体不可用 delegate_task/memory/execute_code/send_message |
| 断路器 | 3 次相同错误 → BLOCKED |
| 并发锁 | advisory lock 防止双会话竞争同一计划 |
| 角色明确 | 每个函数角色有独立提示词 |

## 四、与 ws-bridge 对比

| 维度 | ws-bridge | oh-my-hermes |
|---|---|---|
| 通信层 | WebSocket + Telegram（实时消息驱动） | Hermes 会话 + delegate_task（工具调用驱动） |
| 编排粒度 | Step 级（`!step_handoff` 推进） | 任务级（一次调用一个原子任务） |
| 状态持久化 | 内存 + 文件（task_store + pipeline_sync） | `.omh/state/` 原子写 + 锁 |
| 角色系统 | 需求分析师/项目管理员/架构师/开发工程师/审查工程师/测试工程师（团队角色） | Planner/Architect/Critic/Executor/Verifier（功能角色） |
| 验证机制 | 人工驱动（审查工程师审查 → 测试工程师测试） | 自动化（omh_gather_evidence 跑构建+测试+lint） |
| 超时处理 | timeout_tracker + ACK 状态机 + 二次催 | 3-strike 断路器 + max_iterations |
| 并发 | 串行 Step | 3 并行子智能体（batch） |
| 断点续做 | 管线状态 + `!step_handoff` | 状态文件 + 重新调用续做 |
| Git 集成 | PipelineGitSync (git fetch + 4级匹配) | 无（纯本地文件系统工作） |

## 五、潜在整合点（纯记录，不作为方案）

以下仅记录调研中发现的可能整合方向，不做方案推广：

1. **ralph 验证执行**：将 ws-bridge 某后端的编码 Step 委托给 ralph 自动完成代码编写+测试验证，减少纯手工编码量
2. **ralplan 辅助架构设计**：让架构师先触发 ralplan 跑三轮辩论，产出共识方案作为设计初稿
3. **gateway-plugin 角色注入**：gateway-plugin 可借鉴 `[omh-role:X]` 标记 + pre_llm_call hook 模式
4. **状态持久化加固**：task_store 可借鉴 omh_state 的原子写入 + 锁机制

## 六、差异与注意事项

- **通信 vs 会话驱动**：OMH 假设 Hermes 会话持续存在；ws-bridge 通过消息指令驱动
- **自动化验证 vs 人工审查**：OMH 自动跑测试/lint；ws-bridge 靠人工审查
- **本地文件 vs 容器部署**：OMH 状态在 `.omh/` 本地目录；ws-bridge 跑在 Docker 容器，需挂外部 volume
- **角色体系不同**：OMH 功能角色 vs ws-bridge 团队角色
- **OMH 仍在早期**（v2.0），gap list 中包含模型路由、百科持久化等未完成功能
- **模型开销**：ralplan 三轮辩论每次 3 个子智能体调用，算力成本较高
