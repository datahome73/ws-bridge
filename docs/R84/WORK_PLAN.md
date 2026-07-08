---
pipeline:
  name: "R84 Inbox 消息处理协议文档化"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R84/WORK_PLAN.md"

  workspace:
    members:
      architect:
        mention_keyword: "小开;architect;架构师"
        rules: "审核工作量，确认文档方向"
      developer:
        mention_keyword: "爱泰;developer;开发"
        rules: "写协议文档 + 注释"
      reviewer:
        mention_keyword: "小周;reviewer;审查"
        rules: "审查文档准确性"
      qa:
        mention_keyword: "泰虾;qa;测试"
        rules: "确认文档可读性，验证协议准确性"
      operations:
        mention_keyword: "小爱;operations;运维"
        rules: "合并部署"

  steps:
    step2:
      role: architect
      title: 技术方案
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R84/R84-product-requirements.md"
      timeout_minutes: 30
    step3:
      role: developer
      title: 编码实现
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R84/R84-product-requirements.md"
      timeout_minutes: 60
    step4:
      role: reviewer
      title: 代码审查
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R84/R84-product-requirements.md"
      timeout_minutes: 30
    step5:
      role: qa
      title: 测试
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R84/R84-product-requirements.md"
      timeout_minutes: 30
    step6:
      role: operations
      title: 合并部署
      context:
        work_plan_url: "${pipeline.work_plan_url}"
        requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R84/R84-product-requirements.md"
      timeout_minutes: 15
---

# R84 工作计划 — Inbox 消息处理协议文档化

> **版本：** v1.0 ✅
> **状态：** 📋 定稿
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R84/R84-product-requirements.md v1.0 ✅

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**零代码逻辑改动，纯文档+注释。**

- 不改 `server/`（handler.py/protocol.py/workspace.py 等全部不动）
- 不改 `clients/python/ws_client.py` 逻辑（只加注释）
- 不改 `clients/node/` 
- 不新增 daemon
- 不新增独立工具函数

**核心产出：** `docs/inbox-message-protocol.md` —— ws-bridge inbox 消息处理协议参考文档。

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | architect | developer | — |
| Step 3 | 💻 编码 | developer | architect | 写文档 ≠ 编码 ❌（文档即编码） |
| Step 4 | 🔍 审查 | reviewer | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | reviewer | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | operations | architect | |

### 0.3 脱敏规则

- frontmatter（`---` 包围的 YAML 块）保留机器解析用名 ✅
- 正文使用角色名（架构师/开发工程师/审查工程师/测试工程师/运维）
- 推前 `grep` 检查正文零内部名残留

---

## 1. 管线总览

### 改动范围

仅文档+注释：

| # | 方向 | 改动 | 位置 | 估算 |
|:-:|:----:|:----|:----|:----:|
| 1 | A | 新增 inbox 消息处理协议文档 | `docs/inbox-message-protocol.md` | ~50 行 |
| 2 | A | WsBridgeClient 注释追加 inbox 协议说明 | `clients/python/ws_client.py` 类注释 | ~10 行 |

**总估算：~60 行（纯文档+注释）**

---

## 2. 管线步骤

### Step 2 — 技术方案（架构师）

**主角：** 架构师 | **备用：** 开发工程师

完成条件：审核本需求文档，确认改动量合理。方案文档即为 `docs/inbox-message-protocol.md` 的草稿，确认应包含：
1. 协议概述：所有消息都是 inbox 消息
2. 消息结构说明（JSON 字段含义）
3. 处理流程（收到→提取 sender_id→处理→回复）
4. 回复协议 = `send_message(channel="_inbox:<sender_id>")`
5. 多 bot 通知方式
6. Gateway 整合代码示例

**修改文件：** `docs/inbox-message-protocol.md`（可作为方案文档产出）

### Step 3 — 编码实现（开发工程师）

**主角：** 开发工程师 | **备用：** 架构师

完成条件：
1. 创建 `docs/inbox-message-protocol.md`，包含协议完整说明和代码示例
2. 更新 `clients/python/ws_client.py` 类注释，追加 inbox 协议说明
3. 推 dev

**修改文件：**
- `docs/inbox-message-protocol.md`（新增，~50 行）
- `clients/python/ws_client.py`（注释，~10 行）

### Step 4 — 代码审查（审查工程师）

**主角：** 审查工程师 | **备用：** 测试工程师

审查重点：
1. 协议描述准确：回复就是 `channel="_inbox:<sender_id>"`
2. 文档不含内部名
3. 代码示例可读且正确
4. ws_client.py 注释位置正确、格式合规

### Step 5 — 测试（测试工程师）

**主角：** 测试工程师 | **备用：** 审查工程师

验收项：
1. ✅ 协议文档存在且完整
2. ✅ 协议准确描述「只有 inbox 一类消息」
3. ✅ 回复协议写清楚 = 发 `_inbox:<sender_id>`
4. ✅ docstring 提及 inbox 协议
5. ✅ 正文零内部名残留

### Step 6 — 合并部署归档（运维）

**主角：** 运维 | **备用：** 架构师

完成条件：
- `git checkout main && git merge dev`
- `git push origin main`
- TODO.md 更新版本号
- `!close_workspace` 关闭工作室

---

## 3. 验收清单

| # | 验收标准 | 预期结果 |
|:-:|:---------|:---------|
| ✅-1 | 协议文档存在 | `docs/inbox-message-protocol.md` 包含完整协议说明 |
| ✅-2 | 协议准确描述「只有 inbox 一类消息」 | 文档明确不再区分 broadcast vs inbox |
| ✅-3 | 回复协议写清楚 | 文档包含回复 = `channel="_inbox:<sender_id>"` 示例 |
| ✅-4 | `WsBridgeClient` docstring 提及协议 | 类注释末尾有 inbox 协议说明 |
| ✅-5 | 无内容泄露 | grep 验证正文零内部名残留 |
