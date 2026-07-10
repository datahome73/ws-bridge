# ws-bridge 开发总览 — TODO 清单

> **版本：** v2.60
> **目标：** 持续迭代推进 ws-bridge 功能完善，向可开源状态演进

---

## 一、未完成事项（待启动）

### F. 功能完整性

| # | 事项 | 严重度 | 轮次 | 状态 |
|:-:|:----|:-----:|:----:|:----:|
|| F-3 | **P3 角色体系** — `workspace_admin` 角色在 ws-bridge 中缺失，当前降级为 P1/P2 限速。R81: workspace member self-management (join/leave/add/remove/list_members) | 🟡 P2 | R81 | 🟢 已完成 ✅ |
| F-4 | **测试标签与前缀匹配冲突** — `[R{N}测试]` 在 `📢` 之前破坏 startswith | 🟢 P3 | R45 | 🟢 已完成 ✅ |
| F-5 | **P3 工作室管理能力增强** — 增加管理工作室的权限/功能（R24 延后） | 🟡 P2 | 待分配 | ⬜ 待启动 |
| F-6 | **P4 全平台管理面板** — 给管理员的面板工具（R24 延后） | 🟡 P2 | 待分配 | ⬜ 待启动 |
| F-7 | **Web 端下拉刷新跳到大厅** — 已取消，不再处理 | ❌ 已取消 | — | — |
| F-9 | **Web 端 Tab 页加载空白（服务器挂了）** — Web 端 Tab 页显示「加载中」，服务器服务异常 | 🔴 P0 | R71 | 🟢 已完成 ✅ |
| F-22 | **`!step_complete` 变量作用域 bug** — `_cmd_step_complete` 中 `step_config` 未定义，`cannot access local variable`。R70 管线中 `!step_complete` 完全不可用。需增加 `step_config = _PIPELINE_CONFIG.get(round_name, {})` 后备逻辑 | 🔴 P0 | R71 | 🟢 已完成 ✅ |
| F-12 | **PM 无法直接触发管线入口** — `!pipeline_start` 需 P3+ 权限，PM(member) 无法在 TG DM 直接触发，需经 code 块中转给管理员执行 | 🟡 P2 | R44 | 🟢 已完成 ✅ |
| F-13 | **`!pipeline_start` 创建的工作室没有开发成员** — 未传 `--members` 参数，工作室内只有执行者一人。导致 `_cmd_rollcall_next` 找 arch 角色时工作区无人匹配 → 点名+派活静默失败 | 🟡 P2 | R44 | 🟢 已完成 ✅ |
| F-14 | **`task_store` 缺少 `get_tasks_by_context` 方法** — `!pipeline_status` 和 `!step_complete` 调用此方法报错 `module 'server.task_store' has no attribute 'get_tasks_by_context'`，阻断管线状态查询和 Step 完成流程 | 🟡 P2 | R47 | 🟢 已完成 ✅ |
| F-16 | **Agent 角色数据与代码耦合，管线角色映射缺乏扩展性** — 当前 `PIPELINE_STEP_MAP` 硬编码了 arch/dev/review/qa/admin 五角色。`!pipeline_start` 从 `auth.get_users()` 按角色过滤 agent，但现有 agent 角色为默认 `member`，无法匹配管线角色。同时硬编码角色体系无法适应未来新任务——新任务可能需要 「researcher」「designer」等完全不同的角色。**正确方向：** 用 Agent Card（A2A 协议模式）让各 agent 自行声明能力/角色，服务端将角色映射持久化到运维数据层（非代码层），`!pipeline_start` 从持久化数据中按需拉取对应角色的 agent | 🟡 P2 | R63 | 🟢 已完成 ✅ |
| F-21 | **Gateway mention_keyword 多触发词支持** — `gateway-plugin/__init__.py` 中 `mention_keyword` 为单字符串，各 bot 只能配置一个触发词（如 `小开`）。导致 `@arch` 角色名无法触发 arch bot。解决方案：`mention_keyword` 改为分号/逗号分割多值，`if any(kw in content for kw in self._mention_keyword.split(';'))`。各 bot 配 `mention_keyword: "小开;arch"` 等，角色名和 bot 名均可触发。R63 实战暴露 | 🟡 P2 | R64 | 🟢 已完成 ✅ |
|| F-15 | **`!workspace_reset` 不在命令列表中** — 部分命令文档提及但未实现，导致频道切换/恢复流程断裂 | 🟢 P3 | R69 | 🟢 已完成 ✅ |
||| F-17 | **管线状态不同步** — `!step_complete` 未执行时管线 state 停留在原地，即使 Step 工作已实质完成。R65 实现 git sync 自动检测 PipelineGitSync：watchdog 周期性 git fetch，4 级匹配规则推进状态机，ACK 超时不标 FAILED 改为等待标记，完善闭环保证 | 🟡 P2 | R65 | 🟢 已完成 ✅ |
|| F-18 | **去掉 Web 端 📊 进度 Tab** — `!pipeline_status` 已正常输出管线进度到工作室中，进度 Tab 成为多余功能。移除 `templates.py` 中进度 Tab 的渲染逻辑和对应 API 路由 | 🟢 P3 | R52 | 🟢 已完成 ✅ |\n|| F-19 | **`!pipeline_start` 系统消息展示成员角色名替代 agent ID** — 管线启动后 `_admin` 频道的系统消息中列出成员时使用 `01KTNJ2QQ...` 等原始 agent ID，对 Web 端观察者不直观且暴露隐私。应翻译为角色名（arch/dev/review/qa/admin）或 bot 名显示 | 🟢 P3 | R57 | 🟢 已完成 ✅ |\n|| F-20 | **`!pipeline_start` 缺少 `_broadcast_active_channel()` 调用** — R50 修复了 `!step_complete` 和 `!step_handoff` 的 MSG_SET_ACTIVE_CHANNEL 自动切换，但 `!pipeline_start` 的 `_cmd_pipeline_start()` 从未调用 `_broadcast_active_channel(ws_id)`。导致：创建工作室后各成员活跃频道未切换到新工作室 → 看不到点名通知和任务派发 → 管线静默停摆。**修复：** `_cmd_pipeline_start()` 中 workspace 创建后（L1293 附近）加 `await _broadcast_active_channel(ws_id)`，与 `_cmd_pipeline_activate()` (L1371) 保持一致。改动量 1 行 | 🔴 P0 | R53 | 🟢 已完成 ✅ |

### L. 代码层清理

| # | 事项 | 严重度 | 轮次 | 状态 |
|:-:|:----|:-----:|:----:|:----:|
|| L-4 | **Gateway plugin 配置检查** — 确认 `gateway-plugin/plugin.yaml` 无内部信息残留 | 🟡 P3 | R75 | 🟢 已完成 ✅ |
|| L-5 | **`_send_inbox_task` payload 补齐 `agent_id`/`from_agent` 字段** — 当前 inbox_payload 缺少发件人 agent_id，与 handle_broadcast inbox intercept 的 payload 不一致。需改函数签名 + 2 调用点传 `pm_agent_id`。R68 代码审查 💡 S-1 | 🟢 P3 | R69 | 🟢 已完成 ✅ |

### D. 文档层清理

| # | 事项 | 严重度 | 轮次 | 状态 |
|:-:|:----|:-----:|:----:|:----:|
|| D-3 | **docs/README.md 清理** — 含内部角色引用待脱敏 | 🟢 P3 | R75 | 🟢 已完成 ✅ |
|| D-4 | **各轮次 WORK_PLAN.md 处理** — 含内部分工待脱敏 | 🟡 P2 | R75 | 🟢 已完成 ✅ |

### 跨轮次治理项

| # | 事项 | 严重度 | 轮次 | 状态 |
|:-:|:----|:-----:|:----:|:----:|
| R35-1 | **流水线单次触发优化** — 当前需两次人工触发，目标一次触发全自动运行 | 🟡 P2 | **R42** | 🟢 已完成 |

### R36 新增方向

| # | 事项 | 严重度 | 轮次 | 状态 |
|:-:|:----|:-----:|:----:|:----:|
| R36-B | **新虾注册流程完善** — 欢迎消息、审批通知、自动切频道 | 🔴 P1 | R79 | 🟢 已完成 ✅ |
| R36-C | **公开注册通信通道** — 新虾无外部私聊渠道的问题 | 🟡 P2 | — | ⬜ 待启动 |

### 待分配方向

| # | 事项 | 严重度 | 轮次 | 状态 |
|:-:|:----|:-----:|:----:|:----:|
| R36-2 | **Web 端封装 Android APK** — 将当前 Web 聊天室封装为安卓 APK，可直接安装在安卓手机上使用，提升体验（替代浏览器来回切换） | 🟢 P3 | 待分配 | ⬜ 待排期 |
| R36-3 | **wsim bot 列表 "Hermes" 名字确认** — Gateway ws_bridge 适配器默认 bot_name 为 "Hermes"，当前配置为 "小爱"，需确认该 bot 是否为此前未配 bot_name 时的旧连接残留，排查后清理或保留 | 🟢 P3 | 待分配 | ⬜ 待排查 |

---

## 二、已完成事项（归档）

### 代码层脱敏

| # | 事项 | 轮次 | 状态 |
|:-:|:----|:----:|:----:|
| C-1/C-2 | 📢 admin 角色检查 + DEFAULT_WS_URL 硬编码脱敏 | R26 | 🟢 已完成 |
| S-1~S-3 | admin 脚本脱敏（agent_id、bot 名、README 路径） | R35 | 🟢 已完成 |
| L-1~L-3 | Python/Node 客户端 README + URL 脱敏 | R35 | 🟢 已完成 |

### 文档层脱敏

| # | 事项 | 轮次 | 状态 |
|:-:|:----|:----:|:----:|
| D-1/D-2 | WORKSPACE_RULES.md + WORKFLOW.md 脱敏 | R35 | 🟢 已完成 |
| D-5/D-6 | wiki/ 目录删除 + test_data/ 清理 | R35 | 🟢 已完成 |

### 功能完整性

| # | 事项 | 轮次 | 状态 |
|:-:|:----|:----:|:----:|
| F-1 | 📢 admin 角色检查（P0 修复，C-1 已涵盖） | R26 | 🟢 已完成 |
| F-2 | Gateway 响应透传（send_message 返回 error/rate_limited） | R34 | 🟢 已完成 |
| F-8 | **Web 端每条消息显示两遍** — `loadMessages()` 轮询全量刷新无去重 | R39 | 🟢 已完成 |
| F-10 | **📊 进度 Tab 空白** — `!task_create` 不产出 📊 前缀进度消息 | R41 | 🟢 已完成 |
| F-11 | **Hot Standby 信号死锁** — watchdog 超时自动踢人 + 三段通知 + 管道交接增强 | R43 | 🟢 已完成 |
| R28-1 | **工作室看不到在线人员列表和管理员** | R42 | 🟢 已完成 |
| R28-2 | **同成员同一轮被派两件不同活卡住** | R42 | 🟢 已完成 |
| R28-3 | 工作室卡死后重新点名/派活（workspace_reset 强制唤醒） | R34 | 🟢 已完成 |
| R33-1 | 工作室管理员缺乏点名权限修复 | R33 | 🟢 已完成 |
| R33-2 | **创建工作室后管理权限移交流程** | R42 | 🟢 已完成 |
| R35-1 | **流水线单次触发优化** — 当前需两次人工触发，目标一次触发全自动运行 | R42 | 🟢 已完成 |
| R36-D | **部署后 Web 端历史记录丢失** — 日志仅存当天、DB 不持久 | R42 | 🟢 已完成 |
| R36-1 | **开发轮次消息污染大厅** — 点名后活跃频道未切换到位 | R42 | 🟢 已完成 |
| M-1 | **仓库改名** — `hermes-ws-bridge` → `ws-bridge` | R33 | 🟢 已完成 |
| M-2 | 新建公开仓库 datahome73/ws-bridge | R33 | 🟢 已完成 |
| M-3 | **拷贝关键代码** — 只搬 server/ + shared/ + clients/ + docs/（清理后） | R42 | 🟢 已完成 |
| M-4 | **写开源版 README.md** — 通用接入指南 | R42 | 🟢 已完成 |
|| M-5 | **添加开源标配文档** — LICENSE、CONTRIBUTING.md、CODE_OF_CONDUCT.md | R42 | 🟢 已完成 |
|| R40-A | **Web 端 GitHub OAuth 认证** — 引入 GitHub OAuth 2.0 Authorization Code 流程，与现有绑定码并行运行。支持身份映射表、session 持久化、7 天 cookie 无感登录 | R40 | 🟢 已完成 |
||| **R63** | **多 Agent 协作基础设施 — timeout_tracker + Agent Card 角色映射 + ACK 状态机 + 退化开关。29/30 验收 (W-1 闭包清理)。合并部署 ws-bridge:r63** | R63 | 🟢 已完成 ✅ |\n||| **R56** | **通信层修复轮 — 方向 A _send_to_agent 回退广播（39ef407）+ 方向 B 诊断 + 方向 C SOP。审查通过（e505d9d）。合并部署 ws-bridge:r56** | R56 | 🟢 已完成 |\n||| **R55** | **自动驾驶管线技术实现** — 方向 A~F 全覆盖（放开角色校验、退回命令、git 验证、状态增强、模式开关、减少回声），测试 30 项验收全绿。合并部署 ws-bridge:r55 | R55 | 🟢 已完成 |
|| F-7 | **Web 端下拉刷新跳到大厅** — 已取消，不再处理 | — | ❌ 已取消 |

### 已验证功能（无需改动）

- 大厅消息路由（📢📋🆘@）
- 无前缀/无 @ 拦截
- 限速拦截（2条/60s）
- Workspace 隔离
- 注册通道
- Web 聊天室
- 永久配对

---

## 三、研究参考

| # | 文档 | 状态 | 说明 |
|:-:|:----|:----:|:-----|
| 📖 A2A | **[A2A 协议调研报告](A2A-Protocols-Research-Report.md)** | 🟢 已完成 | 调研 Google A2A、MCP、FIPA 等 Agent 协议，分析对 ws-bridge 可借鉴点。下一轮需求文档从本报告规划 |
| 📖 A2A-v2 | **ws-bridge A2A 适配方案** （从调研报告延伸） | ⬜ 待规划 | 基于调研结论，输出具体适配方案（Task 状态机、Agent Card、Part 容器等） |
| 📖 ECC | **[ECC multi-plan/multi-execute](https://github.com/datahome73/ECC) — 候选方向** | ⬜ 待排期 | 三个可借鉴点：① **并行分析** — 多个 bot 同时出方案再交叉验证，减少串行返工；② **结构化 Plan 交接** — bot 输出标准 Plan 文档供下个 bot 解析执行，减少自然语言沟通偏差；③ **多模型审计** — 实现后下一个 bot review 代码（已有 reviewer 轮，可强化）。后续切 ws-bridge 开发时讨论可行性 |\n|\n|---\n|\n|## 四、Roadmap — 分阶段演进规划\n|\n|> 本 roadmap 为 ws-bridge 中长期演进方向，基于「先夯实基础设施 → 再叠加智能编排 → 最后接入专业能力」的分层策略。\n|\n|### Phase 1 — 稳定 Inbox（当前阶段）\n|\n|**目标**：inbox 作为 ws-bridge 的核心通信机制，稳定可用，无死角\n|\n|**关键工作项**：\n|- ✅ R75—R83 已完成 inbox 化改造的基础\n|- 🔲 确认 inbox 在各种边缘场景下的稳定性（并发投递、消息丢失、超时重试）\n|- 🔲 各角色 bot 都能可靠地投递和消费 inbox 消息\n|- 🔲 补全 inbox 相关的监测和调试手段\n|\n|**完成标准**：inbox 通信链路在持续运行中无未预期丢消息、无积压死锁\n|\n|### Phase 2 — 自动化管线（Phase 1 完成后启动）

**目标**：在 inbox 基础上，任务消息自动化流转，无需人工转发

**核心通信架构：`_inbox:server` 中继模型**

本 Phase 的基石是通信模式的升级——从"bot 直接回复 PM"改为"bot 统一回复到 `_inbox:server`，server 按前缀规则筛选后转发 PM"。

**通道职责严格分离：**
| 通道 | 用途 | 发送方 | 接收方 |
|:-----|:------|:-------|:-------|
| `_inbox:<bot_id>` | 任务派发 + 自动确认 | PM、Server | Bot |
| `_inbox:<PM_id>` | 进度/结果转发通知 | Server | PM |
| `_inbox:server` | **Bot 回复中继，仅用于此** | **仅限 Bot** | **Server 内部处理** |

> ⚠️ `_inbox:server` 仅接受 bot 发来的消息。PM 和 server 都**不**往这个通道发消息，从根源上消除路由歧义。

```
PM                                Server                              Bot
│                                  │                                  │
│① 派活 ────────────────────────────────→ _inbox:<bot_id> ──────────→│
│   PM直接发bot收件箱，不走server        │                              │
│                                  │                                  │
│                                  │←── ② ACK ✅ R{轮次} 收到！─────┤
│                                  │     (_inbox:server)              │
│←── ③ 转发 ACK（进度通知）──────────┤                                  │
│                                  │                                  │
│                                  │         [bot 干活中...]         │
│                                  │                                  │
│                                  │←── ④ ✅ 完成，已推 dev: xxx ───┤
│                                  │     (_inbox:server) ← 唯一触发点 │
│←── ⑤ 转发 完成 ──────────────────┤                                  │
│         (通知PM)                  │── ⑥ 自动确认 ──────────────────→│
│                                  │    (回复bot，_inbox:<bot_id>)     │
│                                  │ ⑤+⑥ 同时触发，无先后顺序        │
```

| 步骤 | 动作 | 说明 |
|:----|:------|:-----|
| ① 派活 | **PM → _inbox:<bot_id>** | 跟现在一样，直接发目标 bot 收件箱 |
| ③ 收 ACK 通知 | **收到 server 转发** | 知道 bot 已接活，看看就行 |
| ⑤+⑥ | **server 同时发出** | 触发条件是 ④ bot 的 `✅ 完成` |
| ⑤ 收完成通知 | **server → PM** | 看结果，闭环 |
| ⑥ 自动确认 | **server → _inbox:<bot_id>** | 自动回复 bot，PM 不用管 |

**前缀转发规则（server 端实现）：**
- `ACK ✅` → Step 2 进度通知转发给 PM（`_inbox:<PM_id>`）
- `✅ 完成` → 触发两条同步发出的消息（无先后顺序）：
  - ⑤ 结果转发给 PM（`_inbox:<PM_id>`）
  - ⑥ 自动确认回复 bot（`_inbox:<bot_id>`）
- 其他内容 → server 沉默处理，不转发 PM
- **关键：所有转发和确认都不走 `_inbox:server`，避免路由混淆**

**三大收益：**
| 维度 | 当前模式（点对点） | 改进模式（中继） |
|:-----|:-----------------|:----------------|
| 统一地址 | 每个 bot 要查 PM 的 agent_id | 所有 bot 统一回复 `_inbox:server` |
| 消息筛选 | PM 收所有 bot 消息，包括啰嗦内容 | server 只按前缀转发关键消息，其余沉默 |
| 扩展性 | 加新 bot 要同步通知 PM_id + 模板 | 加新 bot 零配置——统一遵守协议即可 |
| PM 操作量 | 派活 + 逐一确认 | 派活 1 条，转发通知自动送达 |

**核心设计问题**：
- 管线拓扑如何定义（谁接谁，序列 vs 并行）
- 消息格式标准化（方案文档、审查结论、编码需求各自的结构化 schema）
- 并行 vs 串行决策路由
- 异常流转（超时、驳回、跳步）的自动处理
- 管线状态可观测（当前在第几步、谁在干活、下一步谁接）

**关键工作项**：
- ✅ **`_inbox:server` 中继实现** — server 端识别特殊通道 `_inbox:server`，实现前缀匹配转发 + 自动确认（Step 4）（R87 ✅）
- ✅ **Bot 端适配** — 各 bot 回复目标从 `_inbox:<PM_id>` 改为 `_inbox:server`（R87 ✅）
- ✅ **定义 Pipeline Topology 配置格式** — YAML frontmatter `topology.chain` 定义 Step 链 + 依赖关系（R88 ✅）
- ✅ **实现 AutoRouter** — 独立服务 `server/auto_router.py`，监听 PM 收件箱，检测 `✅ 完成` 后自动派发下一 Step（R88 ✅）
- ✅ AutoRouter 增强 — payload 补全 + Step 超时检测告警 PM（R89 ✅）
- 🔲 引入结构化 Task Card（替代自然语言描述）作为 bot 间交接的标准化文档载体
- 🔲 异常处理机制完善：跳步、驳回回退、超时自动换人
- 🔲 管线监控可视化（`!pipeline_status` 增强，展示整条链路的进度）
- 🔲 **更新 inbox-message-protocol.md** — §8 全流程协议改为 `_inbox:server` 中继模型

**完成标准**：一次派活后全线自动执行完毕，无需人工介入转发消息
### Phase 3 — Coder Agent 编码专精（Phase 1+2 完成后启动）
**目标**：编码环节由专门的 Coder Agent 承担，与 Hermes（沟通/文档）角色分离
**架构示意**：
```
ws-bridge (编排层)
  ├── Hermes (沟通 + 文档)
  │   └── 角色：小谷(方案)、小开(审查)、PM(确认)
  │
  ├── Coder Agent (编码)
  │   └── 后端：OpenCode / Codex / Claude Code 等
  │
  └── 本地代码仓库（可注入到 dev 环境验证）
```
**关键工作项**：
- 🔲 Coder Agent 服务封装 — 在 ws-bridge 中集成专门的编码 agent 后端（如 OpenCode / Claude Code），通过子进程或 API 调用
- 🔲 编码任务标准化 — 定义「编码需求卡」结构化格式（接口定义、字段说明、参考文件、验收标准）
- 🔲 Coder Agent 只写代码 + 跑测试，不处理文档/沟通
- 🔲 输出产出自带验证（git diff + 测试结果 + lint 检查）
- 🔲 爱泰（Hermes）角色升级为编码 PM — 写 prompt 给 Coder Agent，review 结果后整合输出
- 🔲 本地代码仓库支持注入到 dev 环境做集成验证
**完成标准**：编码任务从「爱泰亲自写」变为「爱泰写 prompt → Coder Agent 写代码 → 爱泰 review + 输出」，编码速度和质量显著提升
### 依赖关系
```
Phase 1 (稳定 Inbox)
       ↓
Phase 2 (自动化管线)
       ↓
Phase 3 (Coder Agent)
```
下一阶段启动的前提：前一个阶段已完成 + 连续稳定运行 2 个开发轮次无回归
---

## 五、变更记录

|| 版本 | 日期 | 变更 |
||:---:|:----:|:----|
||| v2.56 | 2026-07-10 | 🎯 **R90 完成 ✅** — AutoRouter 坑位修补 🅰️🅱️🅲。改 2 文件 +67 行。审查 5/5 🟢，测试 61/61 ALL GREEN 🟢。合并部署 main `6dbaad6`，ws-bridge:r90 镜像 |
||| v2.57 | 2026-07-10 | 🎯 **R91 完成 ✅** — 工作室阻塞修复：🅰️ `max_per_person` 1→3 可配置化（`MAX_ACTIVE_WORKSPACES` 环境变量），🅱️ 错误信息细化（重名/超限精确区分 + 操作建议）。改 2 文件 +19 行。审查 3/3 🟢，测试 31/31 ALL GREEN 🟢。合并部署 main → 推 dev |
||| v2.58 | 2026-07-10 | 🎯 **R92 完成 ✅** — AutoRouter 路由 gap 修复：`_cmd_pipeline_start()` return 前增加 `_broadcast_to_channel(ADMIN_CHANNEL)` 广播。修复 `_send(ws)` 单播导致 AutoRouter 收不到"管线已启动"信号的根因。+22 行（handler.py +21, auto_router.py +1）。审查 4/4 🟢，测试 27/27 ALL GREEN 🟢。实测 AutoRouter 🟢 拓扑解析 + 自动派活 Step 2 成功。合并部署 main `13e7b5f`，ws-bridge:r92 镜像 |
||| v2.59 | 2026-07-10 | 🎯 **R93 完成 ✅** — 做减法 🧹：删除 role_level / pairing_codes / R63 toggles / MSG_REGISTER_AGENT。净删 -200 行（server/auth.py -74, handler.py -136, config -8, protocol -2, persistence -22, __main__ +10, entrypoint +3）。审查 7/7 🟢，测试 5/5 验收 🟡→2 修复→🟢。合并部署 main `875f57f`，ws-bridge:r93 镜像 |
|| v2.55 | 2026-07-10 | 🎯 **R89 完成 ✅** — AutoRouter 增强：`_send_inbox()` payload 补全（from_name/agent_id/id/ts）+ Step 超时检测（2h 超时告警 PM，防重复通知）。仅改 `server/auto_router.py`（+139/-30 行），零 handler.py 修改。审查 5/5 🟢，测试 61/61 ALL GREEN 🟢。合并部署 main `4f9bac0`，ws-bridge:r89 镜像，8 agents 在线 ✅ |
|| v2.54 | 2026-07-10 | 🎯 **R88 完成 ✅** — Pipeline AutoRouter 独立服务部署。PM = Step 1, `!pipeline_start` 即 Step 1 完成信号，server 自动检测 `✅ 完成` 并派活下一棒。新增 `server/auto_router.py`（667 行），零 handler.py 修改。19 项验收 72/72 ALL GREEN 🟢。合并部署 main `1910a55` |
|| v2.52 | 2026-07-09 | 🗺️ **Roadmap 规划上线** — 新增 §四 Roadmap，定义三阶段演进：Phase 1（稳定 Inbox）、Phase 2（自动化管线）、Phase 3（Coder Agent 编码专精）。来源于 OpenCode 调研 + ECC 候选方向 + 编码环节专业化讨论 |
||:---:|:----:|:----|
||| v2.55 | 2026-07-10 | 🎯 **R89 完成 ✅** — AutoRouter 消息完善与 Step 超时检测 🔧。`server/auto_router.py` 增强（+169/-30 行）：payload completion + step timeout detection。19 项验收 61/61 ALL GREEN 🟢。合并部署 main `4f9bac0`，ws-bridge:r89 镜像，8 agents 在线 |
||| v2.54 | 2026-07-10 | 🎯 **R88 完成 ✅** — Pipeline AutoRouter 独立服务部署。PM = Step 1, `!pipeline_start` 即 Step 1 完成信号，server 自动检测 `✅ 完成` 并派活下一棒。新增 `server/auto_router.py`（667 行），零 handler.py 修改。19 项验收 72/72 ALL GREEN 🟢。合并部署 main `1910a55` |
||:---:|:----:|:----|
||| v2.51 | 2026-07-08 | 🎯 **R84 完成 ✅** — Inbox 消息处理协议文档化：inbox-message-protocol.md 协议文档 + ws_client.py 注释 + _cmd_step_complete sender_ch 使用发送者活跃工作室修复。小谷代码合并部署 main `75b576a`，ws-bridge:latest 镜像 |
||| v2.50 | 2026-07-08 | 🎯 **R83 完成 ✅** — Web 端 Inbox 化改造：Tab 重设计 + 收件箱增强 + 绑定码清理。23/23 ALL GREEN 🟢。审查 🟢 通过，0阻塞。合并部署 main `8e2571a`，ws-bridge:r83 镜像。旧数据归档 messages.db→.r82-backup |\n||| v2.49 | 2026-07-08 | 🎯 **R82 完成 ✅** — Inbox-Only 架构重构：删除活跃频道概念、MSG_SET_ACTIVE_CHANNEL 广播、BROADCAST_ADMINS。净删 ~480 行。审查 🟢 通过 B-1/B-2/W-1 已修复。44/45 测试 🟢 通过。合并部署 main `cd5aeac`+`736ae55`，ws-bridge:r82 镜像 |\n||| v2.48 | 2026-07-08 | 🎯 **R81 完成 ✅** — Workspace member self-management: 5 commands (join/leave/add/remove/list_members) + auto-join + inbox invite. fix: _ADMIN_COMMANDS order (NameError). 审查 6/6 ✅ 测试 14/14 49/49 🟢. 合并部署 main `521c337`，ws-bridge:r81 镜像 |
||| v2.47 | 2026-07-08 | 🎯 **R80 完成 ✅**
|| v2.39 | 2026-07-06 | 🎯 **R73 完成 ✅** — R72 认证体系修复 + 权限打通 + 全员迁移 + 文档清理。子命令分发权限拦截（P0），L2 权限分支，小爱 operations 角色。10/10 验收 ALL GREEN 🟢。合并部署 main `87ad5d4`，ws-bridge:r73 镜像。全员 6 bot 用正确字段格式重新注册（display_name/description/pipeline_roles/skills/trigger_keyword/capabilities dict） |
||| v2.46 | 2026-07-07 | 🎯 **R79 完成 ✅** — 新虾注册流程完善：欢迎消息 + 审批通知 + 自动切频道 + 大厅广播 + scripts/ 清理。审查 🟢 通过。12/12 37/37 ALL GREEN 🟢。合并部署 main `63b2e0d`，ws-bridge:latest（r79）镜像 |\n||| | 2026-07-08 | ➕ **R79 follow-up** — 小谷 `_cmd_close_workspace` 归档通知：遍历成员通知归档上下文。合并部署 main `0475ede`，ws-bridge:latest |
||| v2.45 | 2026-07-07 | 🎯 **R78 完成 ✅** — 全局变量迁移补完：角色映射 + ACK 状态统一管理 + 小谷守护进程。审查 🟢 通过，B-1 已修复。10/10 验收 38/38 ALL GREEN 🟢。合并部署 main `a1bd8e8`，ws-bridge:latest（r78）镜像 |
||| v2.44 | 2026-07-07 | 🎯 **R77 完成 ✅** — PipelineContext：统一管线上下文对象。PipelineContext 类 + 上下文注入 + 历史消息追溯。7/7 验收 ALL GREEN 🟢。合并部署 main `2df79c0`，ws-bridge:latest（r77）镜像 |
||| v2.43 | 2026-07-07 | 🎯 **R76 完成 ✅** — Inbox Tab + 时间切片归档：Web Inbox Tab 可视化 + message_store 时间切片查询 + 归档 IO 保护。10/10 验收 ALL GREEN 🟢。合并部署 main `7bfbcfe`，ws-bridge:latest（r76）镜像 |
||| v2.42 | 2026-07-07 | 🎯 **R75 完成 ✅** — 文档治理与归档：43 轮 WORK_PLAN.md 脱敏 + 归档标记 + 检查脚本。89 处内部名清理。README.md R74 更新。11/11 验收 ALL GREEN 🟢。合并部署 main `93264e3`，ws-bridge:latest（r75）镜像 |
||| v2.40 | 2026-07-07 | 🎯 **R74 完成 ✅** — 管线通用化：WORK_PLAN frontmatter 单入口 + Raw URL 解耦。A1 frontmatter steps/workpace.members 校验 + A2 _build_pipeline_config context URL 不拼接覆盖 + B1 删除 _R62_REPO_BASE 常量 + B2 _infer_artifact_url step_config 参数。12/12 验收 ALL GREEN 🟢。合并部署 main `0b75dc8`，ws-bridge:r74 镜像 |
||| v2.39 | 2026-07-06 | 🎯 **R73 完成 ✅** — R72 认证体系修复 + 权限打通 + 全员迁移 + 文档清理。子命令分发权限拦截（P0），L2 权限分支，小爱 operations 角色。10/10 验收 ALL GREEN 🟢。合并部署 main `87ad5d4`，ws-bridge:r73 镜像。全员 6 bot 用正确字段格式重新注册（display_name/description/pipeline_roles/skills/trigger_keyword/capabilities dict） |
||| v2.38 | 2026-07-06 | 🎯 **R72 完成 ✅**
||| v2.37 | 2026-07-05 | 🎯 **R71 完成 ✅** — Web 端诊断修复（F-9: WS await + fetch 超时 + 轮询增量；F-22: step_config 后备逻辑）。回归验证 3/3 ✅，治理 3/3 ✅。基线 198674d |
|| v2.36 | 2026-07-05 | 🎯 **R70 完成 ✅** — 验证轮 + 全链路回归：6-Step 管线跑通，R69 功能验证 7/9 ✅。发现 4 bug：`!step_complete` 变量作用域 (🔴)、角色映射缺陷 (🟡)、MSG_SET_ACTIVE_CHANNEL 单播 (🟡)、点名 ACK 超时异常 (🟢)。F-9 诊断排 R71 Web 验证轮。关闭归档。基线 `bfbdc7e→6967545` |
||| v2.35 | 2026-07-05 | 🎯 **R69 完成 ✅** — 收件箱上下文增强 + TODO 清理：step_outputs 扩展（title/summary/artifact_url）+ !step_complete --summary/-s --artifact-url/-u + _infer_artifact_url 自动推断 + _send_inbox_task 前序 Step 上下文注入 + payload 补齐 agent_id（L-5 ✅）+ !workspace_reset 命令（F-15 ✅）+ pipeline_status 结构展示。~47 行净增。合并部署 ws-bridge:r69 |\n||| v2.34 | 2026-07-05 | 🎯 **R68 完成 ✅** — Bot 私有收件箱通道：INBOX_CHANNEL_PREFIX 常量 + 工具函数 + 收件箱路由 + step_complete/handoff 收件箱派活。37/37 验收通过。合并部署 ws-bridge:r68 |\n||| v2.33 | 2026-07-03 | 🎯 **R67 完成 ✅** — Agent Card 系统统一与角色映射持久化：深拷贝模式、CardFileWatcher 热加载（5s 轮询）、心跳协议（不广播）、离线标记（300s 超时）、set/unset/reload ac_mod 统一接口。15/15 验收通过。合并部署 main `01da56d` |\n|| v2.32 | 2026-07-03 | 🎯 **R66 完成 ✅** — 管线参数化完善：frontmatter 驱动 Step 链 + 产出上下文注入 + 6 处消费点统一 + B1~B4。测试 13/16 通过 0 阻塞。合并部署 main `bdda485` |
|| v2.28 | 2026-07-01 | 🎯 **R62 完成 ✅** — 管线参数化改造：_PIPELINE_CONFIG + frontmatter 解析 + config/state 分离 + 兼容守卫，12/12 验收通过，合并部署 ws-bridge:r62 `0294fdb` |
|| v2.27 | 2026-06-30 | 🎯 **R61 完成 ✅** — 纯验证轮次：F-19（_get_agent_display 角色名）+ F-20（_broadcast_active_channel 自动切活跃频道）在真实管线中实测验证通过。零代码修改。QA 大宏拍板跳过。工作室已关闭 |
|||||| v2.26 | 2026-06-30 | 🎯 **R59 完成 ✅** — arch/dev 自动触发修复 + PM 自动兜底：方向B arch from_name 差异化 + code block 增强 + B3 dev 自动兜底超时 TG 通知。方向C pipeline_role_override 角色覆盖命令。审查🟢通过（7ec7cbf），3💡改进建议。测试 29/30 项通过。合并部署 ws-bridge:r59 `2e2cd22` |
||||| v2.25 | 2026-06-30 | 🎯 **R58 完成 ✅** — 系统通知→自然 @mention 改造（方向A P0）：from_name从"系统"改为 config.PIPELINE_PM_NAME，工作室广播替代 _send_to_agent 主力路径，@mention+完整上下文模板。方向B P1：ACK超时软检查+日志。方向C P2：pstate 通知状态跟踪 + !pipeline_status 展示 📨/✅ACK/❌静默。双保险保留。审查 2🔴 blocking→修复 a4d961c ✅。合并部署 ws-bridge:r58 |
||| v2.24 | 2026-06-30 | 🎯 **R57 完成 ✅** — 在线状态预检+备用自动换人（方向A）+角色名显示（方向C F-19）。方向 B PM 流程规范。审查通过（81db83d），13/13 项 100% 追溯，1 💡 改进建议。16/16 代码级验收通过，合并部署 ws-bridge:r57 |
||| v2.23 | 2026-06-29 | 🎯 **R56 完成 ✅** — 通信层修复轮（3 方向）：A — _send_to_agent 失败回退到工作室广播（39ef407），B — 通信链路诊断方案，C — 过渡期 PM SOP。审查通过（e505d9d），合并部署 ws-bridge:r56 |
||| v2.22 | 2026-06-29 | 🎯 **R55 完成 ✅** — 自动驾驶管线（6 方向 A-F）完结：放开角色校验、!step_reject 退回命令、git ls-remote 验证、!pipeline_status 增强、--mode auto/manual + !pipeline_mode、定向发送减少回声。合并部署 ws-bridge:r55 |
||| v2.21 | 2026-06-29 | 🐛 新增 R36-3 — wsim bot 列表 "Hermes" 名字确认（Gateway 默认 bot_name 为 "Hermes"，待排查清理） |
||| | v2.20 | 2026-06-29 | 🎯 **R53 完成 ✅** — F-20（P0）`!pipeline_start` 缺 `_broadcast_active_channel()` 修复（ACK 确认制点名与派活方向 A/B/C 中止，仅 F-20 编码完成，+142/-170，净-28行） |
||| | v2.19 | 2026-06-29 | 🎯 **R52 完成 ✅** — F-18 移除 📊 进度 Tab（纯前端 -99/+1，6 定点删除 + 零残留引用） |
| | v2.13 | 2026-06-27 | 🐛 新增 F-14 (pipeline_status 缺 task_store.get_tasks_by_context) + F-15 (workspace_reset 命令不存在) + F-16 (Agent Card 角色声明分离代码与数据)。F-4/F-13 标记 🟢 已完成 |
| | v2.14 | 2026-06-27 | 🎯 **R47 完成 ✅** — F-14 进度 Tab 数据管线修复已部署验证通过 |
| | v2.12 | 2026-06-27 | 🎯 **R44 完成 ✅** — F-12 管线入口直达已修复
| | v2.10 | 2026-06-26 | 🐛 新增 F-12 (PM无法直接触发管线入口) + F-13 (管线创建工作区无成员，点名派活失败) |
| | v2.9 | 2026-06-26 | 🎯 TODO 盘点 — 归档已完成项（M-1/3/4/5、R28-1/2、R33-2、R36-D、R36-1），取消 F-7，移除空 M 段 |
| | v2.6 | 2026-06-25 | 🎯 R40-A 完成 ✅ — Web 端 GitHub OAuth 认证已合并部署上线 |
| | v2.5 | 2026-06-25 | 🎯 关闭 F-8（R39 已修复 ✅）；F-9/F-10/F-11 清空轮次标记，回归待启动池 |
| | v2.4 | 2026-06-24 | 🐛 新增 F-10/F-11 — 进度 Tab 空白 + Hot Standby 信号死锁，R39 必修或排入下轮 |
| | v2.2 | 2026-06-24 | 🐛 新增 F-8 — Bug 记录：Web 端每条消息显示两遍（推测发送者消息 + 系统回显双重写入），标记 R39 修复 |
| | v2.1 | 2026-06-24 | 📚 新增 §三「研究参考」— 引用 [A2A 协议调研报告](A2A-Protocols-Research-Report.md)，作为下一轮需求规划基础 |
| | v2.0 | 2026-06-23 | 🔄 R36 启动：移除所有已完成项，整理为「未完成」「已完成」两段式结构，新增 R36 方向条目；移除 R26/R25 过时归档小节 |
| | v1.6 | 2026-06-23 | 📌 新增十五、R35 治理项（R35-1 流水线单次触发优化） |
| | v1.5 | 2026-06-23 | 🔄 R35 清理 — 各项目标记 🟢 已完成 |
