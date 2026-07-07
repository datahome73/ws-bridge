# R75 工作计划 — 文档治理与归档 📚

> **版本：** v1.0
> **状态：** 🚀 待启动
> **项目协调人：** 🧐 PM
> **基于需求文档：** docs/R75/R75-product-requirements.md v1.0 ✅（已审核）

---

## 0. 本轮行为规则（全体必读）

### 0.1 Scope 纪律

**改动局域、严禁 scope creep**

- ✅ 改：`docs/R{NN}/WORK_PLAN.md` — 内容替换（内部名→通用角色名）
- ✅ 改：`docs/README.md` — 最新轮次更新 + 脱敏
- ✅ 新增：`scripts/desensitize-check.sh` — 脱敏验证脚本
- ✅ 确认：`gateway-plugin/plugin.yaml` — 已干净
- ❌ 不改入：`server/` `shared/` `config/` 等生产代码
- ❌ 不改出：不改文档目录结构，不改历史内容实质

### 0.2 主备映射

| Step | 角色 | 主角 | 备用 | 约束 |
|:----:|:----|:----:|:----:|:-----|
| Step 2 | 🏗️ 技术方案 | arch | dev | — |
| Step 3 | 💻 编码 | dev | arch | 写方案 ≠ 编码 ✅ |
| Step 4 | 🔍 审查 | review | qa | 编码者 ≠ 审查者 ✅ |
| Step 5 | 🦐 测试 | qa | review | 编码者 ≠ 测试者 ✅ |
| Step 6 | 🦸 合并部署 | operations | arch | — |

---

## 1. 管线总览

### 改动范围

仅 `docs/` 目录 + `scripts/desensitize-check.sh`，不碰任何生产代码。

| # | 方向 | 改动 | 位置 |
|:-:|:----:|:----|:----|
| 1 | A1 | 43 个 WORK_PLAN.md 内部名→通用角色名替换 | `docs/R{NN}/WORK_PLAN.md` |
| 2 | A2 | agent_id 清理（`ws_[0-9a-f]{12}`→`<agent_id>`） | `docs/` 下 .md 文件 |
| 3 | A3 | 新增脱敏检查脚本 | `scripts/desensitize-check.sh` |
| 4 | B | docs/README.md 更新（最新轮次 + 脱敏） | `docs/README.md` |
| 5 | D | 旧轮次归档标记 | `docs/R34-R44/WORK_PLAN.md` |

**总估算：** ~25 行净增 / ~0 行删除

---

## 2. 管线步骤

### Step 1：管线启动 + 配置通知（PM）

**n/a** — PM 在需求审核通过后执行 `!pipeline_start R75 --work_plan_url <raw_url>`

### Step 2：技术方案（Arch）

**主角：** arch / **备用：** dev

**任务：**
阅读需求文档 §2 四个方向（A/B/C/D），输出技术方案文档 `docs/R75/R75-tech-plan.md`，包含：

1. **方向 A 替换方案**：sed/python 替换脚本、替换映射表、精确匹配策略
2. **方向 A 验证方案**：`grep` 验证 + `scripts/desensitize-check.sh` 设计
3. **方向 B README 更新清单**：最新轮次、脱敏项
4. **方向 C Gateway 确认**：已干净，仅需标记 TODO.md
5. **方向 D 归档标记策略**：哪些轮次需要标记
6. **风险分析**：替换误伤风险、回滚方案

**完成条件：** 技术方案文档推 dev + SHA 汇报

### Step 3：编码 — 执行脱敏替换（Dev）

**主角：** dev / **备用：** arch

**任务：**
按技术方案逐项执行替换：

**方向 A（43 个 WORK_PLAN.md）：**
- 使用 sed/python 脚本执行替换
- 替换映射：小谷→需求分析师、小爱→项目管理、小开→架构师、爱泰→开发工程师、小周→审查工程师、泰虾→测试工程师、大宏→项目负责人
- 清理 `ws_[0-9a-f]{12}` agent_id → `<agent_id>`
- 提交前 `grep` 零残留验证

**方向 B（docs/README.md）：**
- 更新「最新轮次：R74」
- 清理内部名

**方向 C（gateway-plugin）：**
- 已干净，无操作 ✅

**方向 D（归档标记）：**
- 在 R34~R44 的 WORK_PLAN.md 顶部添加 `🏁 已归档` 标记

**完成条件：** 替换完成推 dev + `grep` 零残留验证

### Step 4：审查（Review）

**主角：** review / **备用：** qa

**审查重点：**
1. ✅ 替换完整性 — 所有 43 个 WORK_PLAN.md 是否都覆盖
2. ✅ 替换准确性 — 未误伤代码、自然语言
3. ✅ agent_id 清理完整性
4. ✅ README.md 更新正确
5. ✅ 归档标记正确添加
6. ✅ 脱敏检查脚本功能正确
7. ✅ scope 合规 — 不碰生产代码

**完成条件：** 审查报告推 dev + 🟢 通过

### Step 5：测试（QA）

**主角：** qa / **备用：** review

**验收清单（从需求文档 §4 复制）：**

| # | 检查项 | 预期结果 | 测试方法 |
|:-:|:-------|:---------|:---------|
| ✅-1 | 全部 WORK_PLAN.md 零内部角色名残留 | `grep` → exit=1 | 运行脱敏检查脚本 |
| ✅-2 | 全部 .md 零 agent_id 残留 | `grep -rn 'ws_[0-9a-f]\{12\}' docs/` → exit=1 | grep 验证 |
| ✅-3 | 替换后的角色名与通用角色名一致 | 使用「需求分析师」等通用名 | 人工抽检 5 个文件 |
| ✅-4 | 脱敏检查脚本可执行 | `scripts/desensitize-check.sh` → ✅ | 运行脚本验证 |
| ✅-6 | docs/README.md 最新轮次更新 | 标注「最新轮次：R74」 | 人工审阅 |
| ✅-10 | 早期轮次已标记归档 | R34-R44 有 🏁 标记 | 抽检 3 个文件 |
| ✅-11 | 无空文件/空目录残留 | `find docs/ -empty` → 仅预期空目录 | find 命令检查 |

**完成条件：** 测试报告推 dev + 验收逐项标记 ✅/❌

### Step 6：合并部署归档（Operations）

**主角：** operations / **备用：** arch

**操作：**
1. 合并 dev→main
2. 重新 build Docker 镜像
3. 部署生产容器
4. 健康检查（`!pipeline_status R75`）
5. TODO.md 版本号更新 ✅ v2.42
6. 关闭工作室
7. 恢复大厅

---

## 3. 验收清单

| # | 验收标准 | 状态 |
|:-:|:---------|:----:|
| ✅-1 | 全部 WORK_PLAN.md 零内部名残留 | ⬜ 待测试 |
| ✅-2 | 全部 .md 零 agent_id 残留 | ⬜ 待测试 |
| ✅-3 | 通用角色名替换准确 | ⬜ 待测试 |
| ✅-4 | 脱敏检查脚本可执行 | ⬜ 待测试 |
| ✅-5 | R75 自身文档零内部名 | ⬜ 待测试 |
| ✅-6 | docs/README.md 最新轮次更新 | ⬜ 待测试 |
| ✅-7 | docs/README.md 零内部名 | ⬜ 待测试 |
| ✅-8 | plugin.yaml 已确认干净 | 🟢 已完成 ✅ |
| ✅-9 | TODO.md L-4 标记完成 | ⬜ 待更新 |
| ✅-10 | 早期轮次已标记归档 | ⬜ 待测试 |
| ✅-11 | 无空文件/空目录残留 | ⬜ 待测试 |

---

## 4. 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----|:------|
| v1.0 | 2026-07-07 | 初稿 — R75 文档治理与归档 WORK_PLAN |
