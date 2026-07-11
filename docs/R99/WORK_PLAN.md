---
pipeline:
  name: "R99 Bot 权限等级体系 🔒"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R99/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R99/R99-product-requirements.md"

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
        rules: "输出技术方案（4 级权限体系设计 + level 存储 + 检查逻辑）"
      developer:
        mention_keyword: "developer;开发"
        rules: "编码实现 auth/permission/level 全流程（~60 行净增）"
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查权限体系（重点：安全边界、升级逻辑、系统名统一）"
      qa:
        mention_keyword: "qa;测试"
        rules: "输出测试报告（全部验收项 + 边界情况）"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 dev→main + 部署新版本 + 验证 7 bot 在线正常"
---

# R99 工作计划 — Bot 权限等级体系 🔒

> **版本：** v1.0（初稿）
> **状态：** 📝 草稿
> **负责人：** 🧐 PM
> **前置条件：** R98 部署完成 ✅ (v2.65, main 7830639)

---

## 概述

建立 **4 级 Bot 权限体系**，替代原有的全局管理员 + workspace_member 模式，让新 bot 从注册到活跃有渐进过程。

### 改动范围

| 文件 | 改动内容 | 估算 |
|:-----|:---------|:----:|
| `server/auth.py` | 新增 `get_level()` + 修改 `is_approved()` | **~+20 行** |
| `server/persistence.py` | `_api_key` 记录支持 `level` 字段 | **~+10 行** |
| `server/handler.py` | `_inbox:server` auto 放行 + `_inbox:<id>` 检查 level>=4 | **~+15 行** |
| `server/agent_card.py` | Agent Card 提交时自动晋升 L2→L3 | **~+5 行** |
| Web 端+服务端系统名 | 统一为 `"系统"` | **~+10 行** |
| **合计** | | **~+60 行净增** |

### 核心逻辑

```
channel = msg.get("channel", "")

如果 channel.starts_with("_inbox:"):
    如果 channel == "_inbox:server" → auto（所有等级均允许）
    否则（channel 是 _inbox:<其他 bot 的 ID>）:
        需要发送者 level >= 4 才允许
```

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 | 验收 |
|:----:|:-----|:---------|:-----|:-----|
| **Step 1** ✅ 完成 | 🧐 PM | 写需求 + WORK_PLAN + `!pipeline_start` | R99-product-requirements.md + WORK_PLAN.md | 推 dev |
| **Step 2** | 👷 Arch | 技术方案设计 | R99-tech-plan.md | 推 dev |
| **Step 3** | 👨‍💻 Dev | 编码实现 | 5 文件改动（~60 行净增） | 推 dev |
| **Step 4** | 👀 Review | 代码审查 | R99-code-review.md | 推 dev |
| **Step 5** | 🦐 QA | 测试验证 | R99-test-report.md | 推 dev |
| **Step 6** | 🛠️ Ops | 合并部署 | main merge + docker deploy | TODO.md 更新 v2.68 |

---

## Step 1 产出（PM — 已完成 ✅）

| 产出 | 路径 |
|:-----|:------|
| 需求文档 | `docs/R99/R99-product-requirements.md` |
| 工作计划 | `docs/R99/WORK_PLAN.md` |

---

## 交付物要求

| 类别 | 要求 |
|:-----|:------|
| 代码 | `server/` + 系统名统一，~60 行净增 |
| 测试 | 验收全部 🟢 通过，现有 7 bot 行为不受影响 |
| 文档 | 各 Step 报告推 dev |
| 部署 | Ops 合并 main + build 新镜像 + 重启服务 |
