---
round_name: R121
status: pending
steps:
  - step: 1
    role: pm
    name: PM
    agent: 小谷
    task: 需求文档 & WORK_PLAN 已审核推 git
    status: pending
  - step: 2
    role: arch
    name: 架构师
    agent: 小开
    task: 技术方案确认
    status: pending
  - step: 3
    role: dev
    name: 开发
    agent: 爱泰
    task: 管线仪表盘按轮次倒序显示
    status: pending
  - step: 4
    role: review
    name: 审查
    agent: 小周
    task: 代码审查
    status: pending
  - step: 5
    role: qa
    name: QA
    agent: 泰虾
    task: 测试验证
    status: pending
  - step: 6
    role: operations
    name: Ops
    agent: 小爱
    task: 合并部署
    status: pending
---

# R121 WORK_PLAN

## 目标

Web 管线仪表盘（Tab4）按轮次倒序显示，最新 R121 在最上面。

## 改动范围

- `server/web_ui/templates.py` — 替换排序逻辑（~5 行）
- `server/ws_server/main.py` — 补充 `created_at=time.time()`（~1 行）

## 验证

详见需求文档 §五 验证标准。
