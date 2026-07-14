# R116 工作计划

> **交付方式：** Step 1 审核通过后，按序推进各 Step。
> **各 Step 完成后：** 推 git dev → 回复 `已完成 ✅ R116 Step {N}##key=value` 到 `_inbox:server`

---

## Step 1 — 需求文档审核（PM：小谷）

**任务：** 审核 R116 需求文档，确认后推 git，标记 WORK_PLAN 已审核。

**产出：** 
- ✅ 需求文档已审核通过
- ✅ WORK_PLAN 已审核推 git

**完成消息：**
```
已完成 ✅ R116 Step 1##work_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/R116/WORK_PLAN.md
```

---

## Step 2 — 协议文档重写 v3.0（架构师：小开）

**任务：** 将 `docs/inbox-message-protocol.md` 从 v2.0 重写为 v3.0。

**具体内容：**

### 一、需要删除的章节

| 章节 | 原因 |
|:-----|:------|
| §8.8 AutoRouter 服务模型 | AutoRouter 已被 Relay Prefix Protocol 取代（R111），不再使用 |
| §6 Gateway 整合参考 | 各 bot 已独立部署，无参考价值 |
| §8.6 前缀规则中 `✅ 完成` 格式 | 更新为 `已完成 ✅ R{N} Step {N}##key=value` |

### 二、需要新增的章节

#### 新增 §B：Relay Prefix Protocol

```
##start##R{N}##round_title=xxx##requirements_url=xxx    — 创建管线
##status##R{N}                                          — 查询管线状态
##stop##R{N}                                            — 停止管线
##help                                                   — 帮助
```

说明每个命令的格式、发送到 `_inbox:server`、解析方式。

#### 新增 §C：Step 完成协议

`已完成 ✅ R{N} Step {N}##key1=value1##key2=value2`

说明：
- 前缀必须精确匹配
- `##` 分隔键值对，第一个 `=` 分隔 key 和 value
- value 中不应含 `##`（URL 需编码 `%23`）
- key 全小写蛇形，语义明确

#### 新增 §D：8 场景 `##key` 清单

以表格形式列出场景 A~H：

| 场景 | Step | 发送者 | 前缀 | `##` keys |
|:-----|:----:|:-------|:-----|:----------|
| A — 创建管线 | — | PM | `##start##R{N}` | `round_title`, `requirements_url` |
| B — 工作计划 | 1 | PM | `已完成 ✅ R{N} Step 1` | `work_plan_url` |
| C — 设计方案 | 2 | 小开 | `已完成 ✅ R{N} Step 2` | `tech_plan_url`, `design_decision` |
| D — 编码提交 | 3 | 爱泰 | `已完成 ✅ R{N} Step 3` | `commit_sha`, `files_changed`, `commit_description`, `branch_name` |
| E — 代码审查 | 4 | 小周 | `已完成 ✅ R{N} Step 4` | `review_report_url`, `review_decision` |
| F — 测试报告 | 5 | 泰虾 | `已完成 ✅ R{N} Step 5` | `test_result`, `test_report_url`, `test_commit_sha` |
| G — 合并部署 | 6 | 小爱 | `已完成 ✅ R{N} Step 6` | `merge_commit_sha`, `deploy_version` |
| H — 关闭管线 | — | PM | `##stop##R{N}` | （无） |

每个场景附带一条完整示例消息。

#### 新增 §E：R114 Dev 上下文注入

Arch→Dev 派活 Step 3 时注入的 8 项上下文：

| # | 字段 | 说明 |
|:-:|:-----|:------|
| 1 | `tech_plan_url` | 技术方案文档 URL |
| 2 | `requirements_url` | 需求文档 URL |
| 3 | `scope_files` | 涉及文件列表（10+ 文件时缩写 `N files`） |
| 4 | `base_branch` | 目标合并分支 |
| 5 | `design_decision` | 关键技术决策 |
| 6 | `api_contract` | 接口定义 |
| 7 | `data_model_change` | 数据模型变更 |
| 8 | `test_scope` | 测试重点 |

#### 新增 §F：Step 6 部署 SOP

QA→Ops 交接的 7 字段 + 部署命令序列 + 验证清单。

#### 新增 §G：Bot 通信 Checklist

每个 bot 的 8 步 SOP，含 `##key=value` 嵌入要求。

### 三、保留并更新的章节

| 原有章节 | 更新内容 |
|:---------|:---------|
| §2 消息结构 | 补充 `to_agent` 字段 |
| §4 回复协议 | 更新完成格式为 `已完成 ✅ R{N} Step {N}` |
| §8 Bot 标准流程 | 重写通信全景图，加入 `##key=value` |
| §8.6 前缀规则 | 增加 `已完成 ✅`、`##` 两条规则 |

### 四、编辑原则

- 保持 Markdown 纯文本格式（bot 可直接读取）
- 所有示例消息使用粗体标注发送通道
- 增加章节编号，便于 bot 引用（如「详见 §D 场景 D」）
- 删除多余空行和过长的代码注释

**资料来源：**
- R114 `inbox-communication-protocol` skill（8 场景全表）
- R115 协议（artifacts 注入）
- R111 relay 协议（`##start`/`##status`/`##stop`/`##help`）
- R114 Dev 上下文文档（`references/r114-dev-dispatch-context.md`）
- R115 Step 6 部署 SOP（`references/r115-step6-handoff-protocol.md`）

**完成消息：**
```
已完成 ✅ R116 Step 2##tech_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/R116/inbox-message-protocol-v3.md##design_decision=§B~§G 新增，§6/§8.8 删除，§4/§8 更新
```

---

## Step 3 — 协议文档同步 skill（开发：爱泰）

**任务：** 将 Hermes skill `inbox-communication-protocol` 与 repo 文档同步。

**具体内容：**

1. 用 `skill_view('inbox-communication-protocol')` 读取当前 skill 内容
2. 用 `skill_manage(action='edit')` 更新 skill，使其与 `docs/inbox-message-protocol.md` v3.0 一致
3. 确认 v3.0 协议文档已经推送到 `main` 分支，GitHub raw URL 可访问

**完成消息：**
```
已完成 ✅ R116 Step 3##commit_sha=xxx##files_changed=docs/inbox-message-protocol.md,skills/software-development/inbox-communication-protocol/SKILL.md##branch_name=dev
```

---

## Step 4 — 协议文档审查（审查：小周）

**任务：** 审查协议文档 v3.0 的完整性和正确性。

**审查清单：**

| # | 审查项 |
|:-:|:-------|
| 1 | 8 场景（A~H）全覆盖，无遗漏 |
| 2 | 每场景的前缀格式与 server 端正则匹配一致 |
| 3 | `##key` 字段名与 R115 `_extract_artifact_kv()` 兼容（全小写蛇形） |
| 4 | AutoRouter 章节已删除，无残留引用 |
| 5 | 所有示例消息格式正确（`已完成 ✅` 在前，`##key=value` 拼接） |
| 6 | R114 Dev 上下文 8 字段完整无误 |
| 7 | Step 6 部署 SOP 7 字段完整无误 |
| 8 | `##start` / `##status` / `##stop` / `##help` 命令格式正确 |
| 9 | §G Bot Checklist 覆盖所有角色的 `##key` 输出要求 |
| 10 | 文档中没有指向废弃协议的引用 |

**完成消息：**
```
已完成 ✅ R116 Step 4##review_report_url=xxx##review_decision=通过/需修改
```

---

## Step 5 — 协议文档验证（QA：泰虾）

**任务：** 从各 bot 视角验证协议文档的完整性和可读性。

**验证清单：**

| # | 验证项 |
|:-:|:-------|
| 1 | 小开 Step 2 视角：能找到自己需要输出的 `tech_plan_url` + `design_decision` |
| 2 | 爱泰 Step 3 视角：能找到 `commit_sha` + `files_changed` + `commit_description` + `branch_name` |
| 3 | 小周 Step 4 视角：能找到 `review_report_url` + `review_decision` + QA 附加字段 |
| 4 | 泰虾 Step 5 视角：能找到 `test_result` + `test_report_url` |
| 5 | 小爱 Step 6 视角：能找到 7 字段 + 部署 SOP |
| 6 | PM 视角：能找到 `##start` / `##stop` / `##status` / `##help` 命令和 `work_plan_url` |
| 7 | 协议文档 raw URL 可公开访问（不依赖 auth） |

**完成消息：**
```
已完成 ✅ R116 Step 5##test_result=PASS##test_report_url=xxx##test_commit_sha=xxx
```

---

## Step 6 — 通知各 bot 重新学习 + 全自动验证（运维：小爱）

**任务：** 向 5 个 bot 派发学习任务 + 等待确认 + 启动全自动管线验证。

### 6.1 通知所有 bot 重新学习协议

向每个 bot 的 inbox 发送学习任务：

**小开（arch）：**
```
📢 R116 协议更新通知 — 架构师

docs/inbox-message-protocol.md 已更新至 v3.0：
https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/inbox-message-protocol.md

请重点关注：
- §C: Step 完成协议（##key=value 格式）
- §D 场景 C: 设计方案提交（tech_plan_url + design_decision）
- §E: R114 Dev 上下文注入（准备 Step 3 派活时使用）

阅读后回复：已完成 ✅ R116 学习 小开
```

**爱泰（dev）：**
```
📢 R116 协议更新通知 — 开发

docs/inbox-message-protocol.md v3.0：
https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/inbox-message-protocol.md

请重点关注：
- §D 场景 D: 编码提交 — 必须带上 commit_sha + files_changed + branch_name
- §C: Step 完成协议的 ##key=value 格式

阅读后回复：已完成 ✅ R116 学习 爱泰
```

**小周（review）：**
```
📢 R116 协议更新通知 — 审查

docs/inbox-message-protocol.md v3.0：
https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/inbox-message-protocol.md

请重点关注：
- §D 场景 E: 代码审查提交 — review_decision + review_report_url
- 场景 E.2: QA 附加字段（commit_sha + changed_files + review_notes + test_focus）

阅读后回复：已完成 ✅ R116 学习 小周
```

**泰虾（qa）：**
```
📢 R116 协议更新通知 — 测试

docs/inbox-message-protocol.md v3.0：
https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/inbox-message-protocol.md

请重点关注：
- §D 场景 F: 测试报告提交 — test_result + test_report_url

阅读后回复：已完成 ✅ R116 学习 泰虾
```

**小爱（ops）：**
```
📢 R116 协议更新通知 — 运维

docs/inbox-message-protocol.md v3.0：
https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/inbox-message-protocol.md

请重点关注：
- §D 场景 G: 合并部署 — merge_commit_sha + deploy_version
- §F: Step 6 部署 SOP（7 字段交接协议 + 部署命令序列 + 验证清单）

阅读后回复：已完成 ✅ R116 学习 小爱
```

### 6.2 确认所有 bot 完成学习

收到各 bot 的学习确认（`已完成 ✅ R116 学习 {角色}`）后，更新管线进度。

超时（24h）未回复的 bot 记录归档，可后续补发。

### 6.3 启动全自动管线验证

所有 bot 确认后，PM 发：
```
##start##R116-auto##round_title=全自动管线验证
```

**预期全自动链：**
```
##start → Server 创建管线 → 派活 Step 1 给小谷
         → PM 发 "已完成 ✅ R116-auto Step 1"
         → _try_advance_pipeline() 推进 Step 1→2
         → _auto_dispatch() 派活 Step 2 给小开
         → 小开完成 → _try_advance_pipeline() 推进 → _auto_dispatch() 派活 Step 3
         → ...（Step 2~6 依次自动推进，无需手动干预）
         → Step 6 完成后管线自动归档
```

**验证点：**
- 每 step 完成，server 自动推进并派活下一步
- ##status##R116-auto 能正确显示当前 step
- 管线完成后自动归档

**完成消息：**
```
已完成 ✅ R116 Step 6##merge_commit_sha=xxx##deploy_version=正式启用全自动管线
```

---

## Pipeline Steps 总览

| Step | 角色 | 任务 | 产出 |
|:----:|:-----|:-----|:-----|
| 1 | 🟢 小谷(PM) | 审核需求文档 + WORK_PLAN | ✅ 审核通过，推 git |
| 2 | 🏗️ 小开(arch) | 重写协议文档 v3.0 | `docs/inbox-message-protocol.md` v3.0 |
| 3 | 💻 爱泰(dev) | 同步 Hermes skill | `inbox-communication-protocol` skill 同步 |
| 4 | 👀 小周(review) | 审查协议文档 | 审查报告 |
| 5 | 🦐 泰虾(qa) | 验证协议文档完整可读 | 验证报告 |
| 6 | 🚢 小爱(ops) | 通知各 bot + 全自动验证 | 5 bot 学习确认 + 全自动管线通过 |

---

## 说明

- **Step 2（小开）** 是核心产出步骤——重写协议文档
- **Step 3（爱泰）** 是轻量同步——skill 与 repo 文档对齐
- **Step 6（小爱）** 分两个子任务：1) 通知各 bot 学习 2) 全自动管线验证
- 本管线**零代码改动**，纯文档 + 协调轮
