# R{NN} 开发计划

> **仓库：** `datahome73/ws-bridge`（ws-bridge 服务端）
> **涉及仓库：** `datahome73/hermes-agent`（ws_bridge_adapter.py，如需）
> **状态：** 📝 草稿 / ✅ 项目负责人审核通过

---

## 角色分工

| 角色 | 虾虾 | 职责 |
|:----:|:----:|:-----|
| 🧐 需求分析师 | 需求分析师 | 需求调研 → 出需求文档 → 方向审查 |
| 🏗️ 架构师 | 架构师 | 技术方案设计 → 编码审查 |
| 💻 开发工程师 | 开发工程师 | 编码实现 |
| 🔍 审查工程师 | 审查工程师 | 代码审查 |
| 🦐 测试工程师 | 测试工程师 | Dev 测试 + 上线验证 |
| 🦸 项目管理 | 项目管理/调度员 | 任务编排 + 部署 + 归档 |

---

## 开发步骤

### Step 1 — 创建工作室 🦸 项目管理
- 创建 R{NN} 开发工作室，邀请全体成员加入
- **项目负责人审批 WORK_PLAN**（创建工作室时确认）

### Step 2 — 点名 🦸 项目管理
- 全员确认在线
- 点名完成 → 推进 Step 3

### Step 3 — 需求文档 🧐 需求分析师 🔑（关键审核闸门）
产出：`docs/R{NN}/R{NN}-product-requirements.md`
- 需求分析师调研当前状态 → 编写产品需求文档
- **项目负责人审核** — ✅ 通过（转 Step 4）/ ❌ 驳回

### Step 4 — 方案 🏗️ 架构师
产出：`docs/R{NN}/R{NN}-tech-plan.md`

### Step 5 — 方向审查 🧐 需求分析师
产出：`docs/R{NN}/R{NN}-direction-review.md`
- ✅ 🟢 通过 → Step 6 / 🟡 条件通过 → 编码注意 / 🔴 驳回 → 退回 Step 4

### Step 6 — 编码 💻 [开发工程师]
- 按方案实现代码，推 dev 分支

### Step 7 — 开发审查 🔍 [审查工程师]
产出：`docs/R{NN}/R{NN}-code-review.md`
- ✅ ⏭️ 通过 → Step 8 / ❌ 退回 Step 6

### Step 8 — Dev 部署 🦸 项目管理
- 构建镜像 → 部署到 ws-bridge-dev → 健康检查通过

### Step 9 — Dev 测试 🦐 测试工程师
产出：`docs/R{NN}/R{NN}-test-report.md`
- P0 核心 / P1 兼容 / P2 边界
- ✅ 全通过 → Step 10 / ❌ 退回对应环节

### Step 10 — 上线验证 🦸 项目管理 + 全员
产出：`docs/R{NN}/R{NN}-release-verification.md`
- 完整流程验证
- ✅ 通过 → Step 11 / ❌ 退回对应环节

### Step 11 — 合并 main + 更新容器 🦸 项目管理
- 合并 dev→main，更新生产容器

### Step 12 — 关闭工作室 🦸 项目管理
- 全员 ACK → 归档轮次文档 → 各成员切回大厅待命

---

## 注意事项

1. [当前轮次需注意的事项]
2. 参考：已知问题（见 WORKFLOW.md / TODO.md）
