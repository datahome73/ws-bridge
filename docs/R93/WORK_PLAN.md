---
pipeline:
  name: "R93 做减法 — 清理等级体系/配对码/R63 toggles/旧注册路径 🧹"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R93/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R93/R93-product-requirements.md"

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
        title: 编码清理
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
    step2:  { role: architect,    title: 技术方案 }
    step3:  { role: developer,    title: 编码清理 }
    step4:  { role: reviewer,     title: 代码审查 }
    step5:  { role: qa,           title: 测试验证 }
    step6:  { role: operations,   title: 合并部署归档 }

  workspace:
    members:
      architect:
        mention_keyword: "architect;架构师"
        rules: "确认 4 项删除的安全范围 + 异常情况分析"
      developer:
        mention_keyword: "developer;开发"
        rules: "纯删除清理 — auth.py / persistence.py / handler.py / __main__.py / protocol.py"
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查 5 文件的删除改动，确认零功能回归"
      qa:
        mention_keyword: "qa;测试"
        rules: "回归测试 + 12 项验收 + 确认清理无害"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 dev→main + docker build + 重启 AutoRouter"
---

# R93 工作计划 — 做减法 🧹

> **版本：** v1.0（初稿）
> **状态：** 📝 草稿
> **负责人：** 🧐 PM
> **前置条件：** R92 AutoRouter 全信号路径闭环已部署 ✅（main `0333fef`）

---

## 概述

R93 是「减法轮」——不打新功能，只删旧代码。R92 自动化管线通车后回头看，清理 4 项已被替代的旧体系：

| 类别 | 内容 | 删除行预估 | 原因 |
|:-----|:-----|:----------:|:-----|
| 🅰️ | L1-L4 等级体系 `role_level()` | ~-15 | 零调用者，项目负责人已确认等级过时 |
| 🅱️ | 配对码系统（R6 时代） | ~-125 | R72 API Key 已全面替代 |
| 🅲 | R63 Feature Toggles | ~-11 | 永远为真，`AGENT_MAP` 零读取 |
| 🅳 | MSG_REGISTER_AGENT 旧路径 | ~-30 | 已标 DEPRECATED，R72 register 替代 |
| **合计** | | **~-181 行** | **纯删除，零新增** |

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 |
|:----:|:-----|:---------|:-----|
| **Step 1** ✅ | 🧐 PM | 写需求 + WORK_PLAN + `!pipeline_start` | R93-product-requirements.md + WORK_PLAN.md |
| **Step 2** | 👷 Arch | 技术方案（确认删除安全范围） | R93-tech-plan.md |
| **Step 3** | 👨‍💻 Dev | 编码清理（纯删除，5 文件） | 5 文件清理完成 |
| **Step 4** | 👀 Review | 代码审查 | R93-code-review.md |
| **Step 5** | 🦐 QA | 回归测试 + 验收 | R93-test-report.md |
| **Step 6** | 🛠️ Ops | 合并部署 | main merge + docker build + 重启 AutoRouter |

---

## 交付物要求

| 类别 | 要求 |
|:-----|:------|
| 代码 | **纯删除，零新增。** 5 文件清理：`auth.py` / `persistence.py` / `handler.py` / `__main__.py` / `protocol.py` |
| 测试 | 回归测试全部通过。重点：bot 认证不受影响 |
| 文档 | 各 Step 报告推 dev |
| 部署 | Ops 合并 main + build 新镜像 + 重启 AutoRouter |

---

## 风险与缓解

| 风险 | 等级 | 缓解 |
|:-----|:----:|:------|
| 删了 `handle_approve` 但 Web 端还有入口引用 | 🟡 | Arch 确认 handler 中唯一入口是 `_cmd_approve_pairing` 命令 |
| `_pairing_codes.json` 文件残留 | 🟢 | 服务不再加载，文件可安全手动删除 |
| `MSG_PAIRING_CODE` 客户端还在用 | 🟢 | protocol.py 中已标 DEPRECATED，客户端已迁移到 R72 register |
