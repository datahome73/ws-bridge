# R70 验证范围文档 — 验证轮 + F-9 诊断 🔍

> **版本：** v1.0
> **状态：** ✅ 初稿完成
> **作者：** 架构师
> **日期：** 2026-07-05
> **基线：** `bfbdc7e`（R69 合并部署完成）

---

## 1. 验证架构概述

### 1.1 本轮定位

**验证轮 — 零代码改动。** 核心目标不是产出代码，而是验证 R69 上线功能的完整性 + 定位 F-9 Web端 Tab 空白根因。

### 1.2 全链路走法

采用标准 6-Step 管线（WPS），6 个角色按序推进，每一步同时完成：

| 层 | 说明 |
|:--|:-----|
| 🅰️ **功能验证** | 每个 Step 执行时附带验证 V-1~V-9 对应项 |
| 🅱️ **F-9 诊断** | Step 6 由测试工程师执行 6 步法定位根因 |
| 🅲 **TODO 治理** | Step 7 由项目管理更新 TODO.md + 产出总结 |

### 1.3 验证覆盖矩阵

| V-# | 验证项 | Step1 | Step2 | Step3 | Step4 | Step5 | Step6 | Step7 |
|:---:|:-------|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|
| V-1 | `--summary/-s` | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| V-2 | `--artifact-url/-u` | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| V-3 | 向下兼容（无新参数） | — | — | — | ✅ | — | — | — |
| V-4 | 自动 URL 推断 | — | — | ✅(step2) | — | ✅(step4) | ✅(step5) | — |
| V-5 | 收件箱带前序上下文 | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| V-6 | step_outputs 结构 | — | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| V-7 | `!workspace_reset` | — | — | — | — | — | ✅ | ✅ |
| V-8 | inbox_payload 含 agent_id | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| V-9 | `!pipeline_status` 展示 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## 2. 每 Step 验证焦点

### Step 1 — 创建工作室 🦸 项目管理

| 验证项 | 操作 | 通过标准 |
|:-------|:-----|:---------|
| V-9 | 工作室创建后执行 `!pipeline_status` | 输出含成员列表、工作室名称、管线状态 |
| — | 6 位角色均被邀请加入工作室 | `!pipeline_status` 成员列表 = 6 人 |

### Step 2 — 点名 🦸 项目管理

| 验证项 | 操作 | 通过标准 |
|:-------|:-----|:---------|
| V-5 | 点名消息通过收件箱通道送达 | 成员收到含点名说明的 inbox 消息 |
| V-8 | 点名 inbox_payload 含 agent_id/from_agent | JSON 字段 `agent_id` + `from_agent` 存在 |
| V-9 | `!pipeline_status` 显示点名状态 | 输出含各角色点名状态（已确认/超时） |

### Step 3 — 验证范围 🏗️ 架构师（本轮）

| 验证项 | 操作 | 通过标准 |
|:-------|:-----|:---------|
| V-1 | `!step_complete --summary "验证范围确认"` | step_outputs.summary 值为 "验证范围确认" |
| V-2 | `!step_complete --artifact-url <url>` 或空值 | step_outputs.artifact_url 存值或自动推断 |
| V-4 | 自动推断 artifact_url（step3→verification-scope） | 不传 -u 时 URL = 上步产出的文档 URL |
| V-5 | 收件箱消息含前序 Step（PM点名）上下文 | 消息含 `🏗️ 前序 Step N「标题」产出 ✅` 段落 |
| V-6 | `!pipeline_status` 展示本 Step 产出 | 输出含 title/summary/URL 分行展示 |
| V-8 | inbox_payload 含 agent_id/from_agent | JSON 字段 `agent_id` + `from_agent` 存在 |
| V-9 | `!pipeline_status` 各 Step 状态 | 展示 Step3 状态为 ✅ 完成 |

### Step 4 — Dev 侧验证 💻 开发工程师

| 验证项 | 操作 | 通过标准 |
|:-------|:-----|:---------|
| V-1 | `!step_complete --summary "Dev验证通过"` | step_outputs.summary 存值 |
| V-2 | `!step_complete --artifact-url <url>` | step_outputs.artifact_url 存值 |
| V-3 | 某一步不传 `--summary`/`--url` | 不报错、不阻塞管线 |
| V-4 | step3 不传 `-u` 触发自动推断（step3→rawURL） | URL 自动生成 |
| V-5 | 收件箱消息含前序 Step（架构师）上下文 | 消息含架构师 Step 产出摘要 |
| V-6 | step_outputs 含 title/summary/artifact_url | `{sha, title, summary, artifact_url, timestamp}` |
| V-8 | inbox_payload 含 agent_id/from_agent | JSON 字段存在 |
| V-9 | `!pipeline_status` 展示 | Step4 状态为 ✅ |

### Step 5 — 审查 🔍 审查工程师

| 验证项 | 操作 | 通过标准 |
|:-------|:-----|:---------|
| V-1 | `!step_complete --summary "审查通过"` | step_outputs.summary 存值 |
| V-2 | `!step_complete --artifact-url <url>` | step_outputs.artifact_url 存值 |
| V-4 | Step5 不传 `-u` → 自动推断（step5→review URL） | URL 自动生成 |
| V-5 | 收件箱消息含前序 Step（Dev）上下文 | 消息含 Dev Step 产出摘要 |
| V-6 | step_outputs 结构完整 | `{sha, title, summary, artifact_url, timestamp}` |
| V-8 | inbox_payload 字段检测 | agent_id + from_agent 存在 |
| V-9 | `!pipeline_status` 展示 | Step5 状态为 ✅ |

### Step 6 — 全量回归 + F-9 诊断 🦐 测试工程师

| 验证项 | 操作 | 通过标准 |
|:-------|:-----|:---------|
| V-1 | `!step_complete --summary "回归通过"` | step_outputs.summary 存值 |
| V-2 | `!step_complete --artifact-url <报告URL>` | step_outputs.artifact_url 存值 |
| V-4 | Step6 不传 `-u` → 自动推断（step6→test URL） | URL 自动生成 |
| V-5 | 收件箱消息含前序 Step（审查）上下文 | 消息含审查 Step 产出摘要 |
| V-6 | step_outputs 结构完整 | `{sha, title, summary, artifact_url, timestamp}` |
| V-7 | 确认 `!workspace_reset` 可用 | 命令可执行（不一定在本步执行） |
| V-8 | inbox_payload 字段检测 | agent_id + from_agent 存在 |
| V-9 | `!pipeline_status` 展示 | Step6 状态为 ✅ |
| 🅱️ | F-9 诊断 6 步法 | 产出诊断报告文档 |

### Step 7 — TODO 治理 + 总结 🦸 项目管理

| 验证项 | 操作 | 通过标准 |
|:-------|:-----|:---------|
| V-1 | `!step_complete --summary "治理完成"` | step_outputs.summary 存值 |
| V-2 | `!step_complete --artifact-url <治理URL>` | step_outputs.artifact_url 存值 |
| V-5 | 收件箱消息含前序 Step（测试）上下文 | 消息含测试 Step 产出摘要 |
| V-6 | step_outputs 结构完整 | 同上 |
| V-7 | 最终 `!workspace_reset` | 工作室关闭、管线清理、回大厅 |
| V-8 | inbox_payload 字段检测 | agent_id + from_agent 存在 |
| V-9 | `!pipeline_status` 展示 | 清理后管线为空 |

---

## 3. 验收条件表

### 3.1 V-1~V-9 逐项通过标准

| # | 验收条件 | 测量方法 |
|:--|:---------|:---------|
| V-1 | `!step_complete` 带 `-s`/`--summary` 参数时，step_outputs.summary 存储该值 | 执行后 grep `_PIPELINE_STATE` 或 `!pipeline_status` 输出展示 |
| V-2 | `!step_complete` 带 `-u`/`--artifact-url` 参数时，step_outputs.artifact_url 存储该值 | 同上 |
| V-3 | 不带 `--summary`/`--artifact-url` 时，`!step_complete` 不报错 | 命令返回正常完成消息 |
| V-4 | Step2/4/5 不传 `-u` 时，自动推断 URL 模板正确 | 检查 `_infer_artifact_url()` 返回值匹配预期模板 |
| V-5 | 收件箱消息中包含 `🏗️ 前序 Step N「标题」产出` 段落 | 查看收件箱消息内容 |
| V-6 | `step_outputs` 结构包含 sha/title/summary/artifact_url/timestamp | `!pipeline_status` 输出含完整字段 |
| V-7 | `!workspace_reset` 关闭工作室、清理管线、回大厅 | 执行后工作室不可达 + `!pipeline_status` 为空 |
| V-8 | inbox_payload JSON 含 `agent_id` + `from_agent` 字段 | 检查 payload 日志或 `!pipeline_status` 输出 |
| V-9 | `!pipeline_status` 输出含各 Step 的 title/summary/URL 分行展示 | 命令输出视觉确认 |

### 3.2 🅱️ F-9 诊断验收条件

| # | 验收条件 | 测量方法 |
|:--|:---------|:---------|
| F-1 | 确定 Web 端 Tab 空白的根因（区分容器/网络/代码/配置） | 诊断报告含「根因结论」章节 |
| F-2 | 修复预估（小/中/大） | 诊断报告含「修复预估」 |
| F-3 | 影响面评估 | 诊断报告含「影响面」 |
| F-4 | 本轮顺手修复 vs 留 R71 建议 | 诊断报告含「修复建议」 |

### 3.3 🅲 TODO 治理验收条件

| # | 验收条件 | 测量方法 |
|:--|:---------|:---------|
| T-1 | TODO.md 版本号 v2.35 → v2.36 | 文件头部版本号 |
| T-2 | R69 完成记录移入「已完成事项」 | TODO.md 对应条目位置 |
| T-3 | F-9 状态更新为「🔄 诊断中」 | TODO.md F-9 条目 |
| T-4 | R70 轮次总结存档 | `docs/R70/R70-closure-summary.md` 存在 |

---

## 4. 降级方案

### 4.1 管线启动失败

| 场景 | 降级策略 |
|:-----|:---------|
| 工作室创建失败 | 手动指定 channel_id，绕过自动创建 |
| 邀请成员失败 | 各 bot 手动加入工作室 channel |
| `!pipeline_status` 无响应 | 直接检查 `_PIPELINE_STATE` JSON 文件 |

### 4.2 某 Step 卡死（10min 无输出）

| 场景 | 降级策略 |
|:-----|:---------|
| 角色未收到收件箱消息 | 手动 @mention 角色点名 + 直接沟通传达任务 |
| `!step_complete` 报错 | 记录错误信息，跳过该 V- 项，继续推进 |
| 角色离线 | `!step_handoff` 手动跳过该角色，责任累积至 Step6 测试工程师 |

### 4.3 验证项失败

| 场景 | 处理方式 |
|:-----|:---------|
| 单项失败但非阻塞 | 记录失败详情 + 日志 → R71 修复，本轮继续 |
| 关键路径失败（V-5/V-6/V-9） | 汇报项目负责人决定中止或继续 |
| V-7 `!workspace_reset` 失败 | 手动删除工作室 + 清理 `_PIPELINE_STATE` |

### 4.4 F-9 诊断受阻

| 场景 | 降级策略 |
|:-----|:---------|
| 无法访问 Web 容器 | 通过 `ps aux` 和 `ss` 命令间接推断 |
| 端口监听正常但页面空白 | 浏览器 DevTools Network + Console 分析 |
| 诊断工具不可用 | 仅通过日志分析 + 代码审查推断 |

---

## 5. 各 Step artifact_url 自动推断模板

`_infer_artifact_url(step_num)` 预期映射如下：

| Step Num | 产出类型 | 预期 URL 模式 |
|:--------:|:---------|:--------------|
| 2 | tech-plan | `https://github.com/datahome73/ws-bridge/blob/dev/docs/R70/R70-verification-scope.md` |
| 3 | dev-verification | `https://github.com/datahome73/ws-bridge/blob/dev/docs/R70/R70-dev-verification.md` |
| 4 | code-review | `https://github.com/datahome73/ws-bridge/blob/dev/docs/R70/R70-code-review.md` |
| 5 | test-report | `https://github.com/datahome73/ws-bridge/blob/dev/docs/R70/R70-test-report.md` |
| 6 | closure-summary | `https://github.com/datahome73/ws-bridge/blob/dev/docs/R70/R70-closure-summary.md` |

> **注意：** Step 1（工作室创建）和 Step 7（治理）无 artifact（产出为状态变更，非文档）

---

## 6. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-05 | 初稿 — R70 验证范围文档 |
