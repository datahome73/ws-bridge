---
pipeline:
  name: "R91 自动化管线可用性验证 — 根治 workspace 阻塞 + AutoRouter 实测 🔧"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R91/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R91/R91-product-requirements.md"
  topology:
    auto_chain: true
    chain:
      - step: step2
        role: architect
        title: 技术方案
        context:
          requirements_url: "${pipeline.requirements_url}"
          work_plan_url: "${pipeline.work_plan_url}"
      - step: step3
        role: developer
        title: 编码实现
        context:
          requirements_url: "${pipeline.requirements_url}"
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step4
        role: reviewer
        title: 代码审查
        context:
          requirements_url: "${pipeline.requirements_url}"
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step5
        role: qa
        title: 测试验证
        context:
          requirements_url: "${pipeline.requirements_url}"
          code_review_url: "docs/{round}/{round}-code-review.md"
      - step: step6
        role: operations
        title: 合并部署+AutoRouter 全自动验证
        context:
          requirements_url: "${pipeline.requirements_url}"
          test_report_url: "docs/{round}/{round}-test-report.md"
  steps:
    step2:
      role: architect
      title: 技术方案
    step3:
      role: developer
      title: 编码实现
    step4:
      role: reviewer
      title: 代码审查
    step5:
      role: qa
      title: 测试验证
    step6:
      role: operations
      title: 合并部署+AutoRouter 全自动验证
  workspace:
    members:
      architect:
        mention_keyword: "architect;架构师"
        rules: "方案设计：max_per_person 瓶颈 + AutoRouter 全流程验证"
      developer:
        mention_keyword: "developer;开发"
        rules: "编码：workspace.py 上限 + handler.py 错误细化"
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查 workspace 上限变更 + AutoRouter 管线逻辑"
      qa:
        mention_keyword: "qa;测试"
        rules: "验收测试：AutoRouter 全自动管线完整闭环"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 dev→main + docker build + 重启服务 + 启动管线实测"
---

# R91 工作计划 — 自动化管线可用性验证 🔧

> **版本：** v1.0（初稿）
> **状态：** 📝 草稿
> **负责人：** 🧐 PM
> **前置条件：** R90 AutoRouter 坑位修补已部署 ✅（v2.56, main `6dbaad6`）

---

## 概述

**目标：** 修复 workspace 创建瓶颈（`max_per_person=1`），使 AutoRouter 全自动管线能正常启动运行。

### 根因发现

R89-R90 三次迭代后 AutoRouter 功能基本完整，但**从未走通过全自动模式**。核心阻塞点是：

```
server/workspace.py:267  max_per_person = 1
```

PM 小谷每轮 `!pipeline_start` 都会尝试创建新工作室，但老工作室（如 R88）仍为 ACTIVE 状态 → 创建失败 → 管线孤儿 → AutoRouter 无反应 → PM 手动 inbox。

### 三个改动项

| # | 问题 | 改动范围 | 估算 |
|:-:|:-----|:---------|:----:|
| 🅰️ | `max_per_person=1` 硬编码瓶颈 | `server/workspace.py` | ~+5 行 |
| 🅱️ | 创建失败错误信息模糊 | `server/handler.py` | ~+15 行 |
| 🅲 | AutoRouter 全自动管线实测 | 部署后操作 | — |
| **合计** | **2 文件** | | **~+20 行净增** |

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 |
|:----:|:-----|:---------|:-----|
| **Step 1** ✅ 完成 | 🧐 PM | 写需求 + WORK_PLAN → 推 dev | R91-product-requirements.md + WORK_PLAN.md |
| **Step 2** | 👷 Arch | 技术方案设计 | R91-tech-plan.md |
| **Step 3** | 👨‍💻 Dev | 编码实现（2 文件 ~+20 行） | workspace.py + handler.py 修改 |
| **Step 4** | 👀 Review | 代码审查 | R91-code-review.md |
| **Step 5** | 🦐 QA | 测试验证（9 项验收） | R91-test-report.md |
| **Step 6** | 🛠️ Ops | 合并 main + **启动 AutoRouter 全自动管线** | main merge + 验证结果 |

---

## 交付物要求

| 类别 | 要求 |
|:-----|:------|
| 代码 | `server/workspace.py` 修改（~+5 行，max_per_person + 可配置）+ `server/handler.py` 修改（~+15 行，错误细化）|
| 测试 | 9 项验收全部 🟢 通过 |
| 文档 | 各 Step 报告推 dev |
| 验证 | **Step 6 Ops 合并后必须启动一次 AutoRouter 管线验证** — 不通过视为 R91 未完成 |

---

## AutoRouter 全自动管线验证计划

### 验证流程

```python
# Step 6 完成后，执行：
# 1. 确认 AutoRouter systemd 服务在运行
# 2. 发起 !pipeline_start R91-test --work_plan_url <url>
# 3. 监听 2-3 分钟，观察：
#    - 小开 inbox 是否收到任务 ✓
#    - 小爱 ops inbox 是否收到部署任务 ✓
#    - PM 收件箱是否收到 🏁 全部完成 ✓
# 4. 检查 !list_workspaces 确认工作室存在
# 5. 如果失败则诊断并记录 bug-log
```

### 三级递进

| 层级 | 方式 | 条件 | 
|:----:|:-----|:------|
| ① | AutoRouter 全自动 | `!pipeline_start` → 等 2-3 分钟 |
| ② | Inbox 手动协调 | 层级①不触发 → PM inbox 逐 Step 派活 |
| ③ | TG 找大宏 | 层级②也卡住 |
