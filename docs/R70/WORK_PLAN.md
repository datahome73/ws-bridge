# R70 开发计划 — 验证轮 + F-9 诊断 🔍

> **仓库：** `datahome73/ws-bridge`（ws-bridge 服务端）
> **状态：** 📝 草稿（待项目负责人审批）
> **日期：** 2026-07-05
> **基线 commit：** `bfbdc7e`（R69 合并部署完成）

---

## 本轮定性

> **核心目标不是「产出代码」，而是「验证全链路」。** 走标准 6-Step 管线，6 个 bot 每人都有真实任务，每一步都是对 Agent card + inbox 通道 + handoff 机制的实战检验。即使无代码产出，`!step_complete` 时用 `--summary` 标记验证结论，完成即标记通过。

---

## 角色分工

| 角色 | 称呼 | 本轮职责 |
|:----:|:-----|:---------|
| 🧐 需求分析师 | 需求分析师 | 需求文档 ✅ 已完成 |
| 🏗️ 架构师 | 架构师 | 编写验证范围文档（明确每 Step 验证焦点 + 验收条件） |
| 💻 开发工程师 | 开发工程师 | 确认 R69 代码已上线 + 初始化验证环境 + 跑 V-1~V-4 开发侧验证 |
| 🔍 审查工程师 | 审查工程师 | 审查验证方案 + 开发侧验证结果 |
| 🦐 测试工程师 | 测试工程师 | 全量 V-1~V-9 回归测试 + F-9 根因诊断 |
| 🦸 项目管理 | 项目管理 | 管线编排 + TODO 治理 + 归档 |
| 🎯 项目负责人 | 项目负责人 | 审核确认 |

---

## 验证焦点矩阵

每一步都在验证以下 R69 上线功能（编号 V-1~V-9）：

| # | 验证项 | 触发时机 | 验证方法 |
|:-:|:-------|:---------|:---------|
| V-1 | `!step_complete --summary/-s` 参数 | 每 Step 完成时 | 传 `--summary "验证结论"` → `step_outputs.summary` 存值 |
| V-2 | `!step_complete --artifact-url/-u` 参数 | 每 Step 完成时 | 传 `--artifact-url` 或空值 → 检查自动推断 |
| V-3 | 不传新参数时向下兼容 | 至少 1 步 | 某一步不传 --summary/--url → 不报错不阻塞 |
| V-4 | 自动 URL 推断（step2/4/5） | Step 2/4/5 | 不传 `-u` → 自动生成对应类型 URL |
| V-5 | 收件箱消息带前序 Step 上下文 | 每一步交接 | 收件箱消息含 `🏗️ 前序 Step N「标题」产出 ✅` |
| V-6 | step_outputs 含 title/summary/url | 每 Step 完成时 | grep pstate 结构检查 |
| V-7 | `!workspace_reset` 命令 | 轮次结束 | 执行 → 工作室关闭 + 回大厅 + 管线清理 |
| V-8 | inbox_payload 含 agent_id/from_agent | 每 Step 交接时 | payload JSON 字段 `agent_id` + `from_agent` 存在 |
| V-9 | `!pipeline_status` 展示结构化产出 | 随时 | 执行 → 输出含 title/summary/URL 分行展示 |

> **V-1~V-9 共 9 项，在 6 Step 全生命周期中反复交叉验证。** 某些项（如 V-7）只在末步触发一次，其余项在每步交接时都可验证。

---

## 执行步骤（标准管线）

### ✅ 需求审核（已完成）

- 项目负责人审核通过 R70 产品需求文档 v1.0  
- commit: `7942d02`

---

### Step 1 — 创建工作室 🦸 项目管理

- 创建 R70 开发工作室，邀请 6 位角色成员加入
- **项目负责人审批 WORK_PLAN**（创建工作室时确认）
- V-9 检查：`!pipeline_status` 输出成员列表

---

### Step 2 — 点名 🦸 项目管理

- 全员确认在线
- V-9 检查：`!pipeline_status` 显示点名状态
- 点名完成 → 推进 Step 3

---

### Step 3 — 方案/验证范围 🏗️ 架构师

**产出：** `docs/R70/R70-verification-scope.md`

架构师编写验证范围文档，内容包括：

| 章节 | 内容 |
|:-----|:------|
| 验证架构 | 本轮 6-Step 全链路走法概述 |
| 每 Step 验证焦点 | 每一步具体验证哪些 V-# 项、如何操作 |
| 验收条件表 | 每个 V-# 的通过标准 |
| 降级方案 | 某步卡死时的应对策略 |

**此 Step 的验证价值：**
- ✅ Agent card：架构师在线、被正确指派
- ✅ 收件箱通道：收件箱消息送达
- ✅ V-5：消息带前序 Step（需求）上下文 `🏗️`
- ✅ V-1/V-2：`!step_complete --summary "验证范围确认" --artifact-url <url>`
- ✅ V-4：自动推断 artifact_url（step2 → tech-plan URL）
- ✅ V-6/V-9：step_outputs 结构 + `!pipeline_status` 展示
- ✅ V-8：inbox_payload 含 agent_id/from_agent

---

### Step 4 — 验证环境确认 + Dev 侧验证 💻 开发工程师

**产出：** 验证环境确认报告（写入 `docs/R70/R70-dev-verification.md`）

开发工程师任务：

| 任务 | 验证价值 |
|:-----|:---------|
| ① 代码确认：grep 线上 handler.py 含 R69 所有改动点 | V-6 静态检查 |
| ② 检查 `_infer_artifact_url()` 函数存在 | V-4 前提 |
| ③ 检查 `_send_inbox_task` 含 `pm_agent_id` 参数 | V-8 前提 |
| ④ 检查 `!workspace_reset` 在 `_ADMIN_COMMANDS` 中注册 | V-7 前提 |
| ⑤ 运行 **V-3**：调用一次不传参数的 `!step_complete` → 不报错 | V-3 验证 |
| ⑥ 文档产出：记录环境确认结果 | 归档 |

**此 Step 的验证价值：**
- ✅ Agent card：开发工程师在线、被正确指派
- ✅ 收件箱通道：收到架构师的验证范围文档
- ✅ V-1~V-6：真实调用 `!step_complete` 带/不带参数
- ✅ V-5：消息带前序 Step（架构师）上下文
- ✅ V-8/V-9

---

### Step 5 — 验证方案审查 🔍 审查工程师

**产出：** `docs/R70/R70-code-review.md` — 审查验证方案 + 开发侧结果

审查内容：

| 审查项 | 说明 |
|:-------|:------|
| R70-verification-scope.md 完整性 | 验收条件是否全面？降级方案是否合理？ |
| R70-dev-verification.md 正确性 | 代码确认结果是否准确？V-3 测试是否通过？ |
| V-4 自动推断规则验证 | step2/4/5 的 URL 模板是否符合预期 |
| 审查结论 | 🟢 通过 / 🟡 条件通过 / 🔴 退回 |

**此 Step 的验证价值：**
- ✅ Agent card：审查工程师在线
- ✅ 收件箱通道：收到开发工程师产出
- ✅ V-5：消息带前序 Step（开发）上下文
- ✅ V-1/V-2：`!step_complete --summary "审查通过" --artifact-url <url>`
- ✅ V-4：自动推断 step4 artifact_url
- ✅ V-8/V-9

---

### Step 6 — 全量回归测试 + F-9 诊断 🦐 测试工程师

**产出：**
- `docs/R70/R70-test-report.md` — V-1~V-9 全量回归结果
- `docs/R70/R70-f9-diagnosis.md` — F-9 根因诊断

测试工程师任务：

| 阶段 | 任务 | 覆盖项 |
|:-----|:------|:------:|
| 回顾 | 逐条验证 V-1~V-9 在整个管线中是否全部通过 | V-1~V-9 |
| 补充验证 | 补测前序 Step 未覆盖的验证项（如有） | 全量 |
| V-7 | 确认！workspace_reset 命令可执行 | V-7 |
| 🅱️ | F-9 诊断 6 步法（容器/端口/日志/DevTools/WS/Gateway） | — |
| 输出 | 汇总测试报告 + 诊断报告 | 归档 |

**此 Step 的验证价值：**
- ✅ Agent card：测试工程师在线
- ✅ 收件箱通道：收到审查工程师产出
- ✅ V-1~V-9：全量回归
- ✅ V-4：自动推断 step5 artifact_url
- ✅ V-8/V-9

---

### Step 7 — TODO 治理 + 轮次总结 🦸 项目管理

**产出：** `docs/TODO.md` + `docs/R70/R70-closure-summary.md`

| 事项 | 说明 |
|:-----|:------|
| F-9 诊断结论 | 写入 TODO 或标记为下一步行动 |
| TODO.md v2.36 | 追加 R70 完成记录 |
| R70 轮次总结 | 验证结论 + 诊断结论 + 下轮建议 |

**此 Step 的验证价值：**
- ✅ Agent card：项目管理在线
- ✅ 收件箱通道：收到测试报告
- ✅ V-1/V-2：`!step_complete` 携带完整信息
- ✅ V-7：最终关闭工作室

---

### Step 8 — ✅ 项目负责人审核确认 🎯 项目负责人

- 审核全量验证报告 + 诊断报告 + TODO 更新
- ✅ 通过 → 归档 / ❌ 修改意见

---

### Step 9 — 归档关闭 🦸 项目管理

- !workspace_reset → 归档 R70 → 各成员切回大厅待命
- **V-7 最终验证**：工作室关闭 + 管线清理 + 回大厅

---

## 产出物清单

| 文件 | 说明 | 产出 Step |
|:-----|:------|:---------:|
| `docs/R70/R70-product-requirements.md` | 产品需求文档 ✅ 已审核 | 🅰️ |
| `docs/R70/WORK_PLAN.md` | 本文件 — 工作计划 | Step 1 |
| `docs/R70/R70-verification-scope.md` | 验证范围与验收条件 | Step 3 🏗️ |
| `docs/R70/R70-dev-verification.md` | 环境确认 + 开发侧验证 | Step 4 💻 |
| `docs/R70/R70-code-review.md` | 审查报告 | Step 5 🔍 |
| `docs/R70/R70-test-report.md` | V-1~V-9 全量回归报告 | Step 6 🦐 |
| `docs/R70/R70-f9-diagnosis.md` | F-9 根因诊断 | Step 6 🦐 |
| `docs/TODO.md` | TODO v2.36 | Step 7 |
| `docs/R70/R70-closure-summary.md` | 轮次总结 | Step 7 |

---

## V-# 在各 Step 的覆盖矩阵

| 验证项 | Step 3 🏗️ | Step 4 💻 | Step 5 🔍 | Step 6 🦐 | Step 7 🦸 | Step 9 🦸 |
|:------:|:--------:|:--------:|:--------:|:--------:|:--------:|:--------:|
| V-1 (--summary) | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| V-2 (--artifact-url) | ✅ | 🤷 | ✅ | 🤷 | ✅ | — |
| V-3 (向下兼容) | — | ✅ | ✅ | ✅ | — | — |
| V-4 (自动推断) | ✅ (step2) | — | ✅ (step4) | ✅ (step5) | — | — |
| V-5 (上下文注入) | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| V-6 (outputs 结构) | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| V-7 (workspace_reset) | — | — | — | — | — | ✅ |
| V-8 (payload agent_id) | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| V-9 (pipeline_status) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

> ✅ = 必测　🤷 = 可测可不测（由执行者决定）

---

## 零代码原则

- 本轮不改任何 `.py` 文件
- F-9 顺手修仅限 **配置/部署级 ≤10 行**，且不影响验证目标
- 所有「产出」是验证结论文档，不是代码

---

## 注意事项

1. **全链路优先** — 优先确保每一 Step 能完整跑完（收件箱 → 执行 → step_complete → handoff），再关注具体验证项细节
2. **卡住时降级** — 某 Step 的 bot 不响应时，用 `!step_handoff` 强制推进 + 记录为 ❌
3. **基线固定** — 全程在 `bfbdc7e` 基础上操作，不拉新部署
4. 参考：已知问题（见 WORKFLOW.md / TODO.md）

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-05 | 初稿 — 简化版（仅测试+诊断） |
| v2.0 | 2026-07-05 | 全链路版 — 6 bot 全角色参与，V-# 覆盖矩阵，标准管线 |
