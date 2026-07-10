---
pipeline:
  name: "R92 AutoRouter 最终修复 — !pipeline_start 广播到 _admin 频道 📡"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R92/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R92/R92-product-requirements.md"
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
        title: 合并部署 + 全自动管线验证 🤞
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
      title: 合并部署 + 全自动管线验证
  workspace:
    members:
      architect:
        mention_keyword: "architect;架构师"
        rules: "方案设计：_cmd_pipeline_start 广播 + AutoRouter 信号匹配"
      developer:
        mention_keyword: "developer;开发"
        rules: "编码：handler.py ~+14 行 broadcast"
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查 broadcast 安全、重复消除"
      qa:
        mention_keyword: "qa;测试"
        rules: "验收：9 项 + 全自动管线闭环验证"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 main + 启动第一次 AutoRouter 全自动管线"
---

# R92 工作计划 — AutoRouter 最终修复 📡

> **版本：** v1.0（初稿）
> **状态：** 📝 草稿
> **负责人：** 🧐 PM
> **前置条件：** R91 workspace 修复已部署 ✅（main, `3fee1c5`）

---

## 概述

**目标：** 修复 AutoRouter 无法收到 `!pipeline_start` 信号的根因 —— `_send(ws, msg)` 只回复发送者，不广播到 `_admin` 频道。

### 根因回顾

```
R88-R90: AutoRouter 功能完整 + _admin 监听
       ↓ 但 workspace 创建失败 → 归因错误
R91: workspace 创建成功 ✅
       ↓ 但 AutoRouter 仍不触发 → 暴露真实根因
R92: _send → _broadcast_to_channel 补丁 📡
       ↓ 预计修复
```

### 改动项

| # | 问题 | 改动范围 | 估算 |
|:-:|:-----|:---------|:----:|
| 🅰️ | `_cmd_pipeline_start` 只 `_send` 回发送者，不 `_broadcast` 到 `_admin` | `server/handler.py` | ~+14 行 |
| 🅲 | 部署后验证第一次全自动管线 | 操作 | — |
| **合计** | **1 文件** | | **~+14 行净增** |

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 |
|:----:|:-----|:---------|:-----|
| **Step 1** | 🧐 PM | 写需求 + WORK_PLAN → 推 dev | R92 需求 + WORK_PLAN |
| **Step 2** | 👷 Arch | 技术方案：`_cmd_pipeline_start` 广播 + AutoRouter 信号确认 | R92-tech-plan.md |
| **Step 3** | 👨‍💻 Dev | 编码：handler.py ~+14 行（仅 1 文件）| handler.py 修改 |
| **Step 4** | 👀 Review | 代码审查（重点：try/except 安全）| R92-code-review.md |
| **Step 5** | 🦐 QA | 测试验证（9 项验收）| R92-test-report.md |
| **Step 6** | 🛠️ Ops | 合并 main + **第一次 AutoRouter 全自动管线验证** | main merge + 验证结果 |

---

## 交付物要求

| 类别 | 要求 |
|:-----|:------|
| 代码 | `server/handler.py` 修改（~+14 行，仅 `_cmd_pipeline_start` return 前）|
| 测试 | 9 项验收全部 🟢 通过 |
| 文档 | 各 Step 报告推 dev |
| 验证 | **Step 6: 必须走通一次 AutoRouter 全自动管线** — 这是 R92 的成败标准 |

---

## 全自动管线验证步骤

```python
# Step 6 部署后：
# 1. 确认 auto-router.service 🟢 active
# 2. 确认 0 活跃工作室
# 3. !pipeline_start R92-test --work_plan_url <url>
# 4. 观察 2-3 分钟：
#    - 小开 inbox 收到 Step 2 ✅
#    - 小开发完成 → 爱泰自动收到 Step 3 ✅
#    - 全线闭环 → PM 收 🏁 全部完成 ✅
# 5. 三级递进保底：失败→inbox→TG
```
