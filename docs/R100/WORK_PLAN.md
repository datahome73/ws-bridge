---
pipeline:
  name: "R100 服务端核心重构：handler.py 拆分 🏗️"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R100/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/dev/docs/R100/R100-product-requirements.md"

  topology:
    auto_chain: false
    chain:
      - step: step2
        role: architect
        title: 架构设计方案
        context:
          requirements_url: "${pipeline.requirements_url}"
      - step: step3
        role: developer
        title: 编码拆分
        context:
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step4
        role: reviewer
        title: 代码审查
        context:
          tech_plan_url: "docs/{round}/{round}-tech-plan.md"
      - step: step5
        role: qa
        title: 测试验证
        context:
          code_review_url: "docs/{round}/{round}-code-review.md"
      - step: step6
        role: operations
        title: 合并部署归档
        context:
          test_report_url: "docs/{round}/{round}-test-report.md"

  steps:
    step2:
      role: architect
      title: 架构设计方案
    step3:
      role: developer
      title: 编码拆分
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
        rules: |
          基于 R100 需求文档 + server/README.md 架构全景，
          输出独立架构设计方案（R100-tech-plan.md），
          确定 8 个新文件定位、依赖关系、核心/插件边界。
      developer:
        mention_keyword: "developer;开发"
        rules: |
          按架构方案执行 6 步编码拆分：
          state.py → command_utils.py → commands/ → main.py → __main__.py 更新 → 验证。
          每步提交、可回退。
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查拆分质量（核心/插件分层、无循环导入、inbox 通路保留）"
      qa:
        mention_keyword: "qa;测试"
        rules: "执行验收 15 项：5 核心通路 + 5 命令功能 + 5 代码质量"
      operations:
        mention_keyword: "operations;运维"
        rules: "合并 dev→main + 部署 + 验证 inbox 双向通信正常"
---

# R100 工作计划 — 服务端核心重构：handler.py 拆分 🏗️

> **版本：** v1.1
> **状态：** 📝 定稿
> **负责人：** 🧐 PM
> **前置条件：** R99 部署完成 ✅ (v2.68, main 9c0c5b8)

---

## 概述

将 `server/handler.py`（7024 行）按"核心消息路由 vs 插件命令"分层原则拆分为 8 个文件。**只做结构拆分，零行为变更。**

### 分层原则

```
消息通道（核心）— 去掉则 inbox 不通
  ├── main.py  (~800行)  改名+精简
  └── handler() + handle_broadcast + relay + query

插件（附加）— 去掉 inbox 仍通
  ├── state.py          共享状态
  ├── command_utils.py  命令路由工具
  └── commands/         !命令处理（5领域）
```

### 核心测试

> 重构前后，bot A 向 bot B 发 _inbox 消息必须完全不受影响。

### 改动范围

| 文件 | 动作 | 行数 |
|:-----|:-----|:----:|
| `server/handler.py` → `server/main.py` | 改名+精简 | 7024 → ~800 |
| `server/state.py` | 🔺 新增 | ~200 |
| `server/command_utils.py` | 🔺 新增 | ~200 |
| `server/commands/__init__.py` | 🔺 新增 | ~100 |
| `server/commands/workspace.py` | 🔺 新增 | ~500 |
| `server/commands/pipeline.py` | 🔺 新增 | ~1200 |
| `server/commands/agent_card.py` | 🔺 新增 | ~300 |
| `server/commands/task.py` | 🔺 新增 | ~400 |
| `server/commands/admin.py` | 🔺 新增 | ~200 |
| `server/__main__.py` | import 路径更新 | ~5 行改 |
| **合计** | **8 新增 + 2 修改** | **~3900 行** |

---

## 管线步骤

| Step | 角色 | 工作内容 | 产出 | 验收 |
|:----:|:-----|:---------|:-----|:-----|
| **Step 1** ✅ 完成 | 🧐 PM | 需求文档 + 工作计划 | R100-product-requirements.md + WORK_PLAN.md | 推 dev |
| **Step 2** 🟡 待执行 | 👷 小开 | 架构设计方案 | R100-tech-plan.md | 推 dev |
| **Step 3** ⏳ | 👨‍💻 Dev | 编码拆分 — 6 步执行 | 全部代码文件拆分 | 见下 |
| **Step 4** ⏳ | 👀 Review | 代码审查 | R100-code-review.md | 推 dev |
| **Step 5** ⏳ | 🦐 QA | 测试验证 | R100-test-report.md（15 项验收） | 推 dev |
| **Step 6** ⏳ | 🛠️ Ops | 合并 dev→main + 部署 | Docker 新镜像 + 生产验证 | TODO.md 更新 |

---

## Step 1 产出（PM — 已完成 ✅）

| 产出 | 路径 |
|:-----|:------|
| 需求文档 | `docs/R100/R100-product-requirements.md` |
| 工作计划 | `docs/R100/WORK_PLAN.md` |
| 架构全景参考 | `server/README.md` |

---

## Step 2 架构设计（小开 — 待执行）

小开需要：

1. **阅读参考资料**
   - `docs/R100/R100-product-requirements.md` — 需求文档（分层原则、目标、验收标准）
   - `server/README.md` — 当前架构全景（17 文件职责、依赖关系、数据流）

2. **产出** `docs/R100/R100-tech-plan.md`
   - 确认 8 个新文件的定位和边界
   - 确认依赖关系（确保无循环导入）
   - 确认核心/插件边界划分
   - 给出 Step 3 编码的执行建议

---

## Step 3 编码拆分（Dev — 待执行）

等待 Step 2 架构方案确定后执行。预计 6 个子步骤：

| 子步 | 内容 | 产出 |
|:----:|:-----|:-----|
| 3.1 | 创建 `state.py` — 共享状态提取 | `server/state.py` ~200 行 |
| 3.2 | 创建 `command_utils.py` — 命令路由工具 | `server/command_utils.py` ~200 行 |
| 3.3 | 创建 `commands/` 包 — 5 个领域文件 | 6 个文件 ~2700 行 |
| 3.4 | handler.py → main.py 改名精简 | `server/main.py` ~800 行 |
| 3.5 | 更新 `__main__.py` import 路径 | ~5 行修改 |
| 3.6 | 本地验证 + 推 dev | 无报错 |

---

## 验收标准

### 核心通路（5 项）

```
1. Bot A 连接 → 认证成功
2. Bot A 向 Bot B 发 _inbox 消息 → Bot B 收到
3. Bot B 回复 Bot A 的 _inbox → Bot A 收到
4. _inbox:server 中继功能正常（ACK ✅ / ✅ 完成 路由到 PM）
5. 大厅 lobby 消息广播正常
```

### 命令功能（5 项）

```
6. !list_workspaces → 返回工作区列表
7. !pipeline_status → 返回管线状态（无错误）
8. !agent_card list → 返回 Agent Card 列表
9. !task_list → 返回任务列表
10. !audit_log → 返回审计日志
```

### 代码质量（5 项）

```
11. handler.py → main.py, 从 7024 ↓ ~800 行
12. commands/ 目录存在，包含 __init__.py + 5 个模块
13. state.py 存在，包含全部共享变量
14. command_utils.py 存在，包含全部工具函数
15. 无循环导入：服务启动无 ImportError
```

---

## 交付物要求

| 类别 | 要求 |
|:-----|:------|
| 代码 | `server/` 下 8 新增 + 2 修改，零行为变更 |
| 测试 | 全部 15 项验收 🟢 通过 |
| 文档 | 架构方案 + 审查报告 + 测试报告推 dev |
| 部署 | Ops 合并 main + build 新镜像 + 重启服务 |
