# R118 工作计划

> **轮次：** R118
> **类型：** 验证轮 + 微小前端改动
> **PM：** 小谷

---

## 概述

R118 有两个目标：
1. **P0 全流程验证** — 在生产环境跑通 `##start → Step 1→6 全自动`，验证 R117 auto-dispatch 功能
2. **P1 管线 Tab 倒序** — Web 仪表盘管线 Tab 卡片按最新在上排列（纯前端，改几行 JS）

验证在第 5 步（QA）集中执行，其余步骤完成一个标准的小前端改动。

## 角色映射

| Step | 角色 | Bot | 职责 |
|:----:|:-----|:----|:------|
| 1 | PM | 小谷 | 需求文档 + WORK_PLAN |
| 2 | Arch | 小开 | 技术方案（前端排序） |
| 3 | Dev | 爱泰 | 编码实现（`templates.py` JS 排序） |
| 4 | Review | 小周 | 代码审查 |
| 5 | QA | 泰虾 | 测试验证 + **全流程自动派活验证** |
| 6 | Ops | 小爱 → 用户 | 合并部署 |

## 各 Step 说明

### Step 1 — PM：标注工作计划已审核

- 产出：`docs/R118/R118-work-plan.md`
- 验收：git log 可看到本文档

### Step 2 — Arch：技术方案

- 产出：`docs/R118/R118-tech-plan.md`
- 内容：管线 Tab 倒序显示的前端方案
- 推 `dev` 分支

### Step 3 — Dev：编码实现

- 产出：`server/ws_server/templates.py` 中 JS 修改
- 内容：在渲染管线卡片的 JS 代码中加倒序排序逻辑
- 参考：已有 `sortNewestFirst()` 函数模式
- 推 `dev` 分支

### Step 4 — Review：代码审查

- 产出：审查报告（可选：推 docs/R118/R118-code-review.md）
- 审查 Step 3 的 JS 改动

### Step 5 — QA：测试验证 + 全流程自动派活验证

- 测试已部署容器的前端管线 Tab 倒序是否生效
- **核心：在生产环境执行一次完整自动派活验证**
  - `##start##R118` → 观察 Step 1→2 自动推进
  - 临时 bot 完成各 Step → 观察自动派活到下一棒
  - 记录每一步的耗时和阻塞点
- 产出：`docs/R118/R118-test-report.md`（含验证记录）

### Step 6 — Ops：合并部署

- 合并 dev → main
- 用户部署 Docker 镜像
- CDN/浏览器刷新验证

## 关键节点

| 节点 | 预计 | 验收 |
|:-----|:-----|:------|
| 需求审核 | ✅ 已通过 | — |
| WORK_PLAN 推 git | 即日 | git log |
| Step 2→5 完成 | TBD | 各 Step 产出 |
| 全流程验证完成 | TBD | 6 步全部自动推进 |
| 部署到生产 | TBD | 容器重启 + 浏览器验证 |
