# 管线 Step 完成消息协议

> **轮次：** R114
> **类型：** 通信协议定义（bot 视角）
> **日期：** 2026-07-14

---

## 一、概述

本文档从 **bot 视角** 定义管线中各场景下，bot 应向 `_inbox:server` 发送什么格式的完成消息。

**规则：** 各场景已定义 → 无歧义 → 下一轮按此编码实现。

---

## 二、前置约定

- 所有 bot 回复统一发送到通道 `_inbox:server`
- 所有完成消息统一以 `已完成 ✅` 开头
- 嵌入的上下文信息用 `##key=value` 格式，跟在第一行末尾，依次拼接
- `##key=value` 中 key 全小写蛇形，value 不含 `##`

---

## 三、场景列表

### 场景 A — 创建管线任务

| 项目 | 内容 |
|:-----|:------|
| **触发者** | PM（小谷） |
| **发送到** | `_inbox:server`（含 `to_agent` 派活） |
| **消息格式** | `##start##R{N}##round_title=xxx##requirements_url=xxx` |
| **场景说明** | PM 启动一个新的开发轮次 |

**示例：**
```
##start##R114##round_title=管线自动化闭环##requirements_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R114/R114-product-requirements.md
```

---

### 场景 B — 工作计划提交（Step 1 完成）

| 项目 | 内容 |
|:-----|:------|
| **触发者** | PM（小谷） |
| **发送到** | `_inbox:server` |
| **消息格式** | `已完成 ✅ R{N} Step 1##work_plan_url=xxx` |
| **嵌入信息** | | |
| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `work_plan_url` | WORK_PLAN 文档的 raw URL | ✅ |
| **场景说明** | PM 审核完需求文档后，推 git 并标记 WORK_PLAN 已审核 |

**示例：**
```
已完成 ✅ R114 Step 1##work_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R114/WORK_PLAN.md
```

---

### 场景 C — 设计方案提交（Step 2 完成）

| 项目 | 内容 |
|:-----|:------|
| **触发者** | 架构师（小开） |
| **发送到** | `_inbox:server` |
| **消息格式** | `已完成 ✅ R{N} Step 2##tech_plan_url=xxx##design_decision=xxx` |
| **嵌入信息** | | |
| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `tech_plan_url` | 技术方案文档的 raw URL | ✅ |
| `design_decision` | 关键设计决策的文字摘要 | 可选 |
| **场景说明** | 架构师编写完技术方案文档，推 git 后发出 |

**示例：**
```
已完成 ✅ R114 Step 2##tech_plan_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R114/R114-tech-plan.md##design_decision=重构 handler 为纯函数模式
```

---

### 场景 D — 编码提交（Step 3 完成）

| 项目 | 内容 |
|:-----|:------|
| **触发者** | 开发（爱泰） |
| **发送到** | `_inbox:server` |
| **消息格式** | `已完成 ✅ R{N} Step 3##commit_sha=xxx##files_changed=xxx##commit_description=xxx` |
| **嵌入信息** | | |
| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `commit_sha` | 提交的 commit SHA（推荐全量，至少 7 位） | ✅ |
| `files_changed` | 本次变更的文件列表，逗号分隔 | ✅ |
| `commit_description` | 提交说明文字 | 可选 |
| `branch_name` | 推送的目标分支名（默认 dev） | 可选 |
| **场景说明** | 开发编码完成后 git push dev，发出完成通知 |

**示例：**
```
已完成 ✅ R114 Step 3##commit_sha=abc1234def5678##files_changed=server/main.py,server/handler.py##commit_description=Add pipeline auto-archive feature##branch_name=dev
```

---

### 场景 E — 代码审查提交（Step 4 完成）

| 项目 | 内容 |
|:-----|:------|
| **触发者** | 审查（小周） |
| **发送到** | `_inbox:server` |
| **消息格式** | `已完成 ✅ R{N} Step 4##review_report_url=xxx##review_decision=xxx` |
| **嵌入信息** | | |
| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `review_report_url` | 审查报告的 raw URL | ✅ |
| `review_decision` | 审查结论：`通过` / `需修改` / `退回` | ✅ |
| **场景说明** | 审查完成并推 git 审查报告文档后发出 |

**示例：**
```
已完成 ✅ R114 Step 4##review_report_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R114/R114-review-report.md##review_decision=通过
```

---

### 场景 F — 测试报告提交（Step 5 完成）

| 项目 | 内容 |
|:-----|:------|
| **触发者** | QA（泰虾） |
| **发送到** | `_inbox:server` |
| **消息格式** | `已完成 ✅ R{N} Step 5##test_result=xxx##test_report_url=xxx##test_commit_sha=xxx` |
| **嵌入信息** | | |
| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `test_result` | 测试结果：`PASS` / `FAIL` | ✅ |
| `test_report_url` | 测试报告的 raw URL | ✅ |
| `test_commit_sha` | 测试提交的 commit SHA | 可选 |
| **场景说明** | QA 运行测试验证，推 git 测试报告后发出 |

**示例：**
```
已完成 ✅ R114 Step 5##test_result=PASS##test_report_url=https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R114/R114-test-report.md##test_commit_sha=def5678
```

---

### 场景 G — 合并部署（Step 6 完成）

| 项目 | 内容 |
|:-----|:------|
| **触发者** | 运维（小爱） |
| **发送到** | `_inbox:server` |
| **消息格式** | `已完成 ✅ R{N} Step 6##merge_commit_sha=xxx##deploy_version=xxx` |
| **嵌入信息** | | |
| `##` key | 说明 | 必填 |
|:---------|:-----|:----:|
| `merge_commit_sha` | 合并 dev→main 的 merge commit SHA | ✅ |
| `deploy_version` | 部署版本号 / Docker Tag | 可选 |
| **场景说明** | 运维合并 dev→main、Docker 构建部署后发出 |

**示例：**
```
已完成 ✅ R114 Step 6##merge_commit_sha=ghi9012##deploy_version=v2.73
```

---

### 场景 H — 关闭管线

| 项目 | 内容 |
|:-----|:------|
| **触发者** | PM（小谷） |
| **发送到** | `_inbox:server` |
| **消息格式** | `##stop##R{N}` |
| **场景说明** | PM 手动停止管线 |

**示例：**
```
##stop##R114
```

---

## 四、Quick Reference

### 所有 `##` key 一览

| 场景 | Step | 发送者 | `##` keys |
|:-----|:----:|:-------|:----------|
| A — 创建管线 | — | PM | `round_title`, `requirements_url`（两条 kv 在 `##start` 命令中） |
| B — 工作计划提交 | 1 | PM | `work_plan_url` |
| C — 设计方案提交 | 2 | 小开 | `tech_plan_url`, `design_decision` |
| D — 编码提交 | 3 | 爱泰 | `已完成 ✅ R{N} Step 3` | `commit_sha`, `files_changed`, `commit_description`, `branch_name` |
| E — 代码审查提交 | 4 | 小周 | `review_report_url`, `review_decision` |
| F — 测试报告提交 | 5 | 泰虾 | `test_result`, `test_report_url`, `test_commit_sha` |
| G — 合并部署 | 6 | 小爱 | `merge_commit_sha`, `deploy_version` |
| H — 关闭管线 | — | PM | （无，`##stop` 命令） |

### 消息前缀一览

| 场景 | 消息开头 | |
|:-----|:---------|:--|
| A / H | `##` 开头 | 管线命令，走 `_handle_hash_cmd` |
| B~G | `已完成 ✅` 开头 | 完成通知，走中继 + 自动推进 |

---

## 五、变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:-----|
| v1.0 | 2026-07-14 | R114 初版 — 8 场景协议定义，纯 bot 视角 |
