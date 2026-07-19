---
pipeline:
  name: "R126 场景匹配规则提取 🏗️"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R126/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R126/R126-product-requirements.md"
  topology:
    auto_chain: true
    chain:
      - step: step2
        role: architect
        title: 架构设计方案
      - step: step3
        role: developer
        title: 编码实现
      - step: step4
        role: reviewer
        title: 代码审查
      - step: step5
        role: qa
        title: 测试验证
      - step: step6
        role: operations
        title: 合并部署归档

steps:
  step2:
    title: "架构设计方案"
    role: architect
    status: pending
    output: docs/R126/R126-tech-plan.md
    verify: 架构方案需明确规则表定义、HandlerRule 签名、dispatch 调度逻辑、双入口统一方案
  step3:
    title: "编码实现"
    role: developer
    status: pending
    output: server/ws_server/scenario_matcher.py
    verify: 7 条规则全部搬入，双入口统一调用 dispatch()，main.py -~225 行，ALL GREEN
  step4:
    title: "代码审查"
    role: reviewer
    status: pending
    output: docs/R126/R126-code-review.md
    verify: 按审查清单逐项检查
  step5:
    title: "测试验证"
    role: qa
    status: pending
    output: docs/R126/R126-test-report.md
    verify: 22 项验收 ALL GREEN
  step6:
    title: "合并部署归档"
    role: operations
    status: pending
    output: (dev → main merge + Docker rebuild + deploy + archive)
    verify: 部署后双向通信正常，##status 可用
---

# R126 工作计划 — 场景匹配规则提取

> **版本：** v1.0
> **状态：** 📋 需求已审核通过 ✅ | WORK_PLAN 已审核通过 ✅
> **负责人：** 🧐 PM 小谷

---

## 概述

本轮将 `main.py`（4934 行）中的场景匹配规则（`_handle_server_relay` 的 7 条 inbox 中继规则 + `_handle_hash_cmd` 的 6 条 `##` 命令路由 + 大厅前缀分类）提取到独立的 `scenario_matcher.py` 规则表模块中。

**核心收益：** main.py -225 行、规则显式声明优先级、双入口不再维护两份副本。

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 | 验收 |
|:----:|:-----|:---------|:-----|:-----|
| **Step 1** ✅ 完成 | 🧐 PM | 需求文档 + WORK_PLAN | `R126-product-requirements.md`, `WORK_PLAN.md` | 推 dev |
| **Step 2** 🟡 待执行 | 👷 小开 | 架构设计方案 | `R126-tech-plan.md`（含规则表定义、dispatch 签名、双入口统一方案） | 推 dev |
| **Step 3** ⏳ | 👨‍💻 爱泰 | 编码实现 `scenario_matcher.py` | `server/ws_server/scenario_matcher.py` + main.py 适配 | 推 dev，22/22 ALL GREEN |
| **Step 4** ⏳ | 👀 小周 | 代码审查 | `R126-code-review.md` | 推 dev |
| **Step 5** ⏳ | 🦐 泰虾 | 测试验证 | `R126-test-report.md` | 22 项验收 ALL GREEN 🟢 |
| **Step 6** ⏳ | 🛠️ 小爱 | 合并 main + Docker build + 部署 + 归档 | TODO.md 更新 + 部署验证 | 双向通信正常 |

---

## 上下文资料

| 资料 | 链接 | 说明 |
|:-----|:------|:------|
| 需求文档 | [R126-product-requirements.md](https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R126/R126-product-requirements.md) | 7 章完整需求 |
| 当前 main.py | [`server/ws_server/main.py`](https://github.com/datahome73/ws-bridge/blob/dev/server/ws_server/main.py) | 4934 行，97 个函数 |
| Inbox 协议文档 | [`docs/inbox-message-protocol.md`](https://github.com/datahome73/ws-bridge/blob/dev/docs/inbox-message-protocol.md) | §7 规则表映射（R126 新增） |
| 模块拆分参考 | `software-development/ws-bridge-dev-tips` skill §🏛️ 核心/插件架构原则 | main.py 只保留核心 WS 路由的原则 |
| 双入口核对清单 | `references/dual-entry-point-paths.md` | handler() + ws_handler() 两处必须同步 |
| 包拆分重构验证 | `references/package-split-refactoring-verification.md` | 新模块导入路径完整检查清单 |

---

## Step 1 产出（PM — 已完成 ✅）

| 产出 | 路径 |
|:-----|:------|
| 需求文档 | `docs/R126/R126-product-requirements.md` |
| 工作计划 | `docs/R126/WORK_PLAN.md` |

---

## 验收标准（22 项，摘自需求文档 §7）

| 分组 | P0 项 | P1 项 | 合计 |
|:-----|:-----:|:-----:|:----:|
| SC 规则提取 | 11 | 0 | 11 |
| LO 大厅前缀 | 5 | 0 | 5 |
| RV 回归验证 | 3 | 0 | 3 |
| DO 文档同步 | 0 | 3 | 3 |
| **合计** | **19** | **3** | **22** |

详见需求文档 §5 验收标准和 §7 验收检查表。
