---
pipeline:
  name: "R90 AutoRouter 坑位修补 — 信号监听 + 环境变量 + 失败通知 🔧"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R90/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R90/R90-product-requirements.md"

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
        rules: "输出技术方案（3 处改动：admin 监听、env var、失败通知）"
      developer:
        mention_keyword: "developer;开发"
        rules: "编码实现 auto_router.py ~+40 行 + handler.py ~+15 行"
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查 auto_router.py + handler.py（重点：admin 频道监听安全、env var 集成）"
      qa:
        mention_keyword: "qa;测试"
        rules: "输出测试报告（12 项验收 + 回归测试）"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 dev→main + docker build + 重启 AutoRouter 服务"
---

# R90 工作计划 — AutoRouter 坑位修补 🔧

> **版本：** v1.0（初稿）
> **状态：** 📝 草稿
> **负责人：** 🧐 PM
> **前置条件：** R89 AutoRouter 增强已部署 ✅（v2.55, main `0a6d2e4`）

---

## 概述

修复 R89 实战发现的 3 个遗留问题：

| # | 问题 | 改动范围 | 估算 |
|:-:|:-----|:---------|:----:|
| 🅰️ | AutoRouter 监听范围不足（只监听 PM inbox） | `server/auto_router.py` | ~+25 行 |
| 🅱️ | 工作区创建失败无 PM 通知 | `server/handler.py` | ~+15 行 |
| 🅲 | `STEP_TIMEOUT=0` + 环境变量集成 | `server/auto_router.py` | ~+15 行 |
| **合计** | | **2 文件** | **~+55 行净增** |

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 |
|:----:|:-----|:---------|:-----|
| **Step 1** ✅ 完成 | 🧐 PM | 写需求 + WORK_PLAN + `!pipeline_start` | R90-product-requirements.md + WORK_PLAN.md |
| **Step 2** | 👷 Arch | 技术方案设计 | R90-tech-plan.md |
| **Step 3** | 👨‍💻 Dev | 编码实现（2 文件） | auto_router.py + handler.py 修改 |
| **Step 4** | 👀 Review | 代码审查 | R90-code-review.md |
| **Step 5** | 🦐 QA | 测试验证 | R90-test-report.md |
| **Step 6** | 🛠️ Ops | 合并部署 | main merge + docker build + 重启 AutoRouter |

---

## 交付物要求

| 类别 | 要求 |
|:-----|:------|
| 代码 | `server/auto_router.py` 修改（~+40 行）+ `server/handler.py` 最小侵入（~+15 行，仅 `_cmd_pipeline_start` 末尾）|
| 测试 | 12 项验收全部 🟢 通过 |
| 文档 | 各 Step 报告推 dev |
| 部署 | Ops 合并 main + build 新镜像 + 重启 AutoRouter 服务（改环境变量需要） |
