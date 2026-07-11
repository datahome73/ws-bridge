---
pipeline:
  name: "R95 — Auto Pipeline 停止命令 🛑"
  work_plan_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/R95/WORK_PLAN.md"
  requirements_url: "https://raw.githubusercontent.com/datahome73/ws-bridge/main/docs/R95/R95-product-requirements.md"

  topology:
    auto_chain: true
    chain:
      - step: step2
        role: architect
        title: pipeline_stop 技术方案
        context:
          requirements_url: "${pipeline.requirements_url}"
          work_plan_url: "${pipeline.work_plan_url}"
      - step: step3
        role: developer
        title: 实现 pipeline_stop 命令
        context:
          requirements_url: "${pipeline.requirements_url}"
          work_plan_url: "${pipeline.work_plan_url}"
      - step: step4
        role: reviewer
        title: 代码审查
        context:
          requirements_url: "${pipeline.requirements_url}"
          work_plan_url: "${pipeline.work_plan_url}"
      - step: step5
        role: qa
        title: 功能测试
        context:
          requirements_url: "${pipeline.requirements_url}"
          work_plan_url: "${pipeline.work_plan_url}"
      - step: step6
        role: admin
        title: 部署到生产
        context:
          requirements_url: "${pipeline.requirements_url}"
          work_plan_url: "${pipeline.work_plan_url}"

  steps:
    step2:  { role: architect,  title: pipeline_stop 技术方案 }
    step3:  { role: developer,  title: 实现 pipeline_stop 命令 }
    step4:  { role: reviewer,   title: 代码审查 }
    step5:  { role: qa,         title: 功能测试 }
    step6:  { role: admin,      title: 部署到生产 }

  workspace:
    members:
      architect:
        mention_keyword: "architect;架构师"
        rules: "输出 docs/R95/R95-tech-plan.md，设计 pipeline_stop 状态机、队列清理策略"
      developer:
        mention_keyword: "developer;开发"
        rules: "实现 !pipeline_stop 命令，含 handler、状态机、任务队列清空"
      reviewer:
        mention_keyword: "reviewer;审查"
        rules: "审查 R95 代码改动，输出 docs/R95/R95-code-review.md"
      qa:
        mention_keyword: "qa;测试"
        rules: "测试 pipeline_stop 全场景，输出 docs/R95/R95-test-report.md"
      admin:
        mention_keyword: "admin;运维"
        rules: "合并 main → 构建 Docker 镜像 → 部署到生产"
---

# R95 — Auto Pipeline 停止命令 WORK_PLAN

> **状态：** 📝 待审核
> **日期：** 2026-07-10
> **前置条件：** ✅ R95 需求文档已闭环

---

## 一、范围

| 项 | 值 |
|:---|:----|
| 轮次 | R95 |
| 类型 | 🛠 功能开发（代码改动） |
| 目标 | 实现 `!pipeline_stop R<N>` 命令，让发起者可停止卡死的 AutoRouter 管线 |
| 需求文档 | `docs/R95/R95-product-requirements.md` |

---

## 二、拓扑（派活链）

```
R95 → 架构师(技术方案) → 开发工程师(实现) → 审查工程师(审查) → 测试工程师(测试) → 项目管理(部署)
```

---

## 三、任务分解

### Step 2 — 架构师：pipeline_stop 技术方案

**输出：** `docs/R95/R95-tech-plan.md`
**推分支：** dev

内容：
- Server 端管线状态机设计（新增 `stopped` 状态，状态流转图）
- AutoRouter stop 逻辑：
  - 如何「停止调度」而不影响正在执行的 bot
  - 如何清空待发送的 inbox 任务队列
  - 已发出的 inbox 如何处理（视为 bot 离线消息被吞）
- `!pipeline_stop` handler 设计：
  - 命令解析 + 权限校验（仅发起者）
  - 幂等处理（重复 stop 同一管线）
  - 边界：对 idle/failed/success 管线执行 stop 的处理
- `!pipeline_status` 扩展：支持显示 `stopped` 状态
- 不涉及的部分（明确排除）：
  - ❌ 不新增 `--from` 参数
  - ❌ 不涉及工作区管理（使用已有关闭功能）
  - ❌ 不改变 bot 执行行为

### Step 3 — 开发工程师：实现 pipeline_stop 命令

**推分支：** dev

实现以下改动：
- 新增 `_cmd_pipeline_stop` handler
- 状态机扩展：添加 `stopped` 状态
- AutoRouter 修改：添加停止信号检测 + 任务队列清空逻辑
- `pipeline_status` 查询扩展
- 单元测试覆盖

### Step 4 — 审查工程师：代码审查

**输出：** `docs/R95/R95-code-review.md`
**推分支：** dev

审查重点：
- 状态机变更是否完整（idle → running → stopped → ...）
- 权限校验是否正确（仅发起者可 stop）
- 幂等处理是否正确
- 边界条件覆盖（idle/failed/success 管线 stop）
- 已发出 inbox 的消息吞没逻辑是否符合设计
- 不影响其他正在运行的管线

### Step 5 — 测试工程师：功能测试

**输出：** `docs/R95/R95-test-report.md`
**推分支：** dev

测试场景：
- [ ] running 管线 stop → 状态变 stopped，AutoRouter 停止调度
- [ ] stop 后已在执行的 bot 不受影响，产出保留
- [ ] 待发送的 inbox 被清空（无新消息发出）
- [ ] 已发出的 inbox 不等超时（视为消息被吞）
- [ ] idle 管线 stop → 报错
- [ ] 重复 stop → 幂等
- [ ] 非发起者 stop → 权限拒绝
- [ ] stop 后其他管线不受影响
- [ ] `!pipeline_status` 显示 stopped 状态
- [ ] 断点续跑：PM 手工派活 inbox → bot 完成 → AutoRouter 自动接管后续步骤

### Step 6 — 项目管理：部署到生产

**推分支：** main（从 dev 合并）

部署动作：
1. 代码审查 + 测试通过后，合并到 main 分支
2. 构建 Docker 镜像
3. 部署到生产环境
4. 验证 `!pipeline_stop` 可用
5. 通知项目负责人功能已上线

---

## 四、交付物

| # | 产出 | 负责人 | 位置 |
|:-:|:----|:-------|:-----|
| 1 | R95-tech-plan.md | 架构师 | `docs/R95/` |
| 2 | 代码改动 | 开发工程师 | server/ 下的相关文件 |
| 3 | R95-code-review.md | 审查工程师 | `docs/R95/` |
| 4 | R95-test-report.md | 测试工程师 | `docs/R95/` |
| 5 | 生产部署 | 项目管理 | main 分支 |

---

## 五、约束

1. **仅一个命令** — 不新增 `--from` 参数或第二个命令
2. **权限收窄** — 仅发起者可 stop（无 workspace 管理员概念）
3. **不影响 bot** — stop 停的是 AutoRouter，不是干活的 bot
4. **不限工作区** — 使用已有关闭功能，已支持多活跃工作区
5. **推 dev** — 所有初稿推 dev 分支
6. **推 main** — 最终代码合并到 main 分支部署
