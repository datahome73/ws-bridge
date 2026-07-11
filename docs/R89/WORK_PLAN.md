---
pipeline:
  name: "R89 AutoRouter 增强 — 消息完善与超时检测 🔧"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R89/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R89/R89-product-requirements.md"

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
        title: 合并部署归档
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
      title: 合并部署归档

  workspace:
    members:
      architect:
        mention_keyword: "architect;架构师"
        rules: "输出技术方案（payload 补全 + 超时检测设计）"
      developer:
        mention_keyword: "developer;开发"
        rules: "编码实现 auto_router.py 两处增强（~60 行）"
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查 auto_router.py（重点：payload 完整性、超时检测 correctness）"
      qa:
        mention_keyword: "qa;测试"
        rules: "输出测试报告（11 项验收 + 边界情况）"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 dev→main + 部署新版本 + 验证 AutoRouter 在线重连"
---

# R89 工作计划 — AutoRouter 增强 🔧

> **版本：** v1.0（初稿）
> **状态：** 📝 草稿
> **负责人：** 🧐 PM
> **前置条件：** R88 Pipeline AutoRouter 已部署 ✅

---

## 概述

对 R88 的 `server/auto_router.py` 做两处小增强：

| # | 增强 | 改动量 | 说明 |
|:-:|:-----|:------:|:------|
| 🅰️ | `_send_inbox()` payload 补全 | +4 字段 | 让 Bot 正确识别消息来源 |
| 🅱️ | Step 超时检测 ✅ | ~+50 行 | Bot 宕机时 PM 能收到告警 |

**总改动：** 仅 `server/auto_router.py`，~+60 行，零 handler.py 侵入。

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 | 验收 |
|:----:|:-----|:---------|:-----|:-----|
| **Step 1** ✅ 完成 | 🧐 PM | 写需求 + WORK_PLAN + `!pipeline_start` | R89-product-requirements.md + WORK_PLAN.md | 推 dev |
| **Step 2** | 👷 Arch | 技术方案设计 | R89-tech-plan.md | 推 dev |
| **Step 3** | 👨‍💻 Dev | 编码实现 | server/auto_router.py 增强 | 推 dev |
| **Step 4** | 👀 Review | 代码审查 | R89-code-review.md | 推 dev |
| **Step 5** | 🦐 QA | 测试验证 | R89-test-report.md | 推 dev |
| **Step 6** | 🛠️ Ops | 合并部署 | main merge + docker deploy | TODO.md 更新 |

---

## Step 1 产出（PM — 已完成 ✅）

| 产出 | 路径 |
|:-----|:------|
| 需求文档 | `docs/R89/R89-product-requirements.md` |
| 工作计划 | `docs/R89/WORK_PLAN.md` |

---

## 交付物要求

| 类别 | 要求 |
|:-----|:------|
| 代码 | 纯新增/修改 `server/auto_router.py`，零 handler.py 改动 |
| 测试 | 11 项验收全部 🟢 通过 |
| 文档 | 各 Step 报告推 dev |
| 部署 | Ops 合并 main + build 新镜像 + 重启 AutoRouter 服务 |
