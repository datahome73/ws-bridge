# R33 开发计划（正式开发）

> **仓库：** `datahome73/ws-bridge`（公开仓库，MIT）
> **类型：** 🏗️ 正式开发（三项 Bug A/B/C 修复）
> **状态：** ✅ 已批准

---

## 开发目标

1. 修复 Bug A — 下拉刷新后活跃 Tab 丢失（`server/templates.py`）
2. 修复 Bug B — 部署后 Web 端登出（`server/web_viewer.py` + `server/persistence.py`）
3. 修复 Bug C — 重新登录后历史工作群错乱（`server/web_viewer.py` + `server/templates.py`）

## 需求文档

📄 [R33-product-requirements.md](./R33-product-requirements.md)（v0.2，已审核通过）

---

## 角色分工

| 角色 | 成员 | 职责 |
|:----:|:----:|:-----|
| 🧐 需求分析师 | 小谷 | 需求调研 → 产出需求文档 → 方向审查 |
| 🏗️ 架构师 | 小开 | 技术方案设计 → 协助编码审查 |
| 💻 开发工程师 | 爱泰 | 编码实现 |
| 🔍 审查工程师 | 小周 | 代码审查 |
| 🦐 测试工程师 | 泰虾 | Dev 测试 + 上线验证 |
| 🦸 项目管理 | 小爱 | 创建/关闭工作室 + Dev部署 + 合并发布 |

---

## 开发步骤

### Step 1 — 创建工作室 🦸 项目管理（小爱）
- 创建 R33 开发工作室，邀全体成员加入
- 项目负责人审批 WORK_PLAN

### Step 2 — 点名 🦐 工作室管理员（泰虾）
- 全员确认在线 → Step 3

### Step 3 — 需求文档 🧐 需求分析师（小谷）✅ 已完成
产出：→ `docs/R33/R33-product-requirements.md`
- ✅ 已审核通过

### Step 4 — 方案 🏗️ 架构师（小开）
产出：→ `docs/R33/tech-plan.md`
 - 覆盖三项 Bug 的技术方案、改法、向后兼容

### Step 5 — 方向审查 🧐 需求分析师（小谷）
产出：→ `docs/R33/direction-review.md`
- ✅ 🟢 通过 → Step 6 / 🟡 条件通过 / 🔴 驳回 → Step 4

### Step 6 — 编码 💻 开发工程师（爱泰）
- 按方案实现代码 → 推 dev 分支

### Step 7 — 开发审查 🔍 审查工程师（小周）
产出：→ `docs/R33/code-review.md`
- ✅ ⏭️ 通过 → Step 8 / ❌ 退回 Step 6

### Step 8 — Dev 部署 🦸 项目管理（小爱）
- 构建镜像 → 部署 ws-bridge-dev → 健康检查

### Step 9 — Dev 测试 🦐 测试工程师（泰虾）
产出：→ `docs/R33/test-report.md`
- P0核心 / P1兼容 / P2边界
- ✅ 全通过 → Step 10 / ❌ 退回对应环节

### Step 10 — 上线验证 🦸 项目管理 + 全员
产出：→ `docs/R33/release-verification.md`
- 全员验证
- ✅ 通过 → Step 11 / ❌ 退回

### Step 11 — 合并 main + 更新容器 🦸 项目管理（小爱）
- dev→main，更新生产容器

### Step 12 — 关闭工作室 🦸 项目管理（小爱）
- 全员 ACK → 归档 → 各成员回大厅待命
