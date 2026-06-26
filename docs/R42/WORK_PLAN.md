# R42 开发计划 — 管线自动触发与 Step 接力

> **版本：** v1.0 ✅（已审批）
> **状态：** ✅ 已审核
> **日期：** 2026-06-27
> **需求文档：** [R42-product-requirements.md](R42-product-requirements.md)

---

## 角色分工

| 角色 | 成员 |
|:----:|:----:|
| 🦸 项目管理 | admin-bot |
| 🧐 需求分析师 | pm-bot |
| 🏗️ 架构师 | arch-bot |
| 💻 开发工程师 | dev-bot |
| 🔍 审查工程师 | review-bot |
| 🦐 测试工程师 | qa-bot |

---

## 开发步骤

### 🔶 前置决策区（全部通过）

#### ✅ Step A — 需求文档 🧐 pm-bot ✅
- **v1.0 ✅（项目负责人审核通过）**
- 三个方向：A(`!pipeline_start`) / B(`!step_complete`) / C(`!pipeline_status`)
- 本轮定位：基础设施轮，R43 开始使用新流程
- 本轮开发使用旧流程（code 块 → TG DM 转发）

#### ✅ Step B — 工作计划 🧐 pm-bot ✅
- ✅ v1.0 已审核通过（本文件）

---

### 🟢 自动化管线

#### 🆕 Step 1 — 创建工作室 🦸 admin-bot

| 事项 | 说明 |
|:-----|:------|
| 工作室 | R42 开发工作室 |
| 目标 | 全员加入，准备技术方案讨论 |
| 备注 | 功能开发轮，正常流程 |

#### ⏳ Step 2 — 点名报道 🦐 qa-bot

| 事项 | 说明 |
|:-----|:------|
| 点名主持 | qa-bot |
| 关键操作 | 点名 arch-bot 出技术方案 |
| R41 多点点名 | 可用 `!rollcall_role` 点名指定角色 |

#### ⏳ Step 3 — 技术方案 🏗️ arch-bot

> **产出要求：** `docs/R42/R42-tech-plan.md`

**技术方案需覆盖：**

| 方向 | 内容 | 核心关注点 |
|:----:|:-----|:-----------|
| **A** | `!pipeline_start R{N}` 命令 | `_admin` 频道入口、验证前置决策、链式调用已有命令、Step 映射表（配置文件） |
| **B** | `!step_complete` 命令 | 完成标记、自动点名下一人、上下文传递（`--output` 参数传入 commit SHA） |
| **C** | `!pipeline_status` 命令 | task 状态聚合、格式输出 |
| **D** | 大厅隔离 | 管线启动时暂停大厅记录、结束时恢复、工作室自动关闭 |

**技术方案结构（参考 Bug 修复轮验证方案格式）：**

```
Part A — 方案设计
├── A-1 ~ A-3：每个方向的设计
├── 涉及文件、改动行号范围
└── 新增命令注册方式

Part B — 向后兼容分析
├── 已有命令影响评估
└── 旧流程是否仍可用
```

#### ⏳ Step 4 — 编码 💻 dev-bot

**改动范围预估：** 服务端代码 `server/handler.py` + `shared/protocol.py`

| 方向 | 预期改动量 |
|:----:|:----------:|
| A `!pipeline_start` | ~60-100 行（新命令注册 + 链式调用逻辑） |
| B `!step_complete` | ~60-80 行（完成标记 + 自动点名 + 上下文传递） |
| C `!pipeline_status` | ~30-50 行（状态聚合 + 格式化输出） |
| D 大厅隔离 | ~40-60 行（暂停/恢复大厅记录 + 自动关工作室） |

**Commit 格式：** `feat(R42): <方向字母>-<描述>`

#### ⏳ Step 5 — 代码审查 🔍 review-bot

**审查重点：**
- 方向 A：`_admin` 频道入口权限检查是否到位？非 admin 用户不能发 `!pipeline_start`
- 方向 B：Step 映射表正确性、上下文传递的完整性
- 方向 C：状态输出是否包含所有必要信息
- **向后兼容：** 旧流程（`!create_workspace`、`!rollcall_role`）不受影响

#### ⏳ Step 6 — 测试验证 🦐 qa-bot

> **产出要求：** `docs/R42/test-report.md`

| 序号 | 测试项 | 对应需求 |
|:----:|:-------|:--------:|
| T-A1 | PM 在 `_admin` 发 `!pipeline_start R42` → 工作室创建 | A-1 |
| T-A2 | 工作室自动点名 | A-2 |
| T-A3 | 点名完成后自动点名架构师，附带需求文档 URL | A-3 |
| T-A4 | 架构师的 task 可通过 `!task_query` 查到 | A-4 |
| T-A5 | 在非 `_admin` 频道发 `!pipeline_start` 返回拒绝 | A-5 |
| T-A6 | 重复 `!pipeline_start R42` 返回「已完成」提示 | A-6 |
| T-B1 | `!step_complete Step3 --output 342c794` → 自动点名开发工程师 | B-1 |
| T-B2 | 开发工程师收到点名含 commit 引用 | B-2 |
| T-B3 | 完成后 task 标记 completed | B-3 |
| T-C1 | `!pipeline_status` 返回 Step 进度表 | C-1 |
| T-D1 | `!pipeline_start` 后大厅不接收新消息 | D-1 |
| T-D2 | 管线期间消息自动路由到工作室 | D-2 |
| T-D3 | Step 7 完成后大厅记录恢复 | D-3 |
| T-D4 | 工作室自动关闭 | D-5 |

#### ⏳ Step 7 — 合并部署 + 归档 🦸 admin-bot

- `git checkout main && git merge dev`
- 部署到生产容器
- 验证所有 agent online, API healthy
- 更新 TODO.md（标记 R42 交付）
- 关闭 R42 开发工作室

---

## 关键约束

1. **只改第①类服务器代码** — 不涉及 Web 端、客户端脚本
2. **向后兼容** — 旧流程（人工 code 块转发、人工 @mention）继续可用
3. **纯服务端系统层** — 所有触发逻辑用 `_ADMIN_COMMANDS` 模式，零 token 消耗
4. **`_admin` 频道为入口** — 不依赖活跃工作室存在
5. **R43 才切换新流程** — 本轮开发和测试阶段全部用旧流程
