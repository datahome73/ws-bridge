# R45 工作计划 — 管线自动触发修复 + 测试标签前缀兼容

> **版本：** v2.0（草稿，待项目负责人审核）
> **状态：** 📋 草稿（基于实战发现重写）
> **产品经理：** 🧐 PM
> **日期：** 2026-06-27

---

## 角色分工

| 角色 | 职责 |
|:-----|:------|
| 🧐 PM | 需求文档 + 工作计划 + 协调推进 |
| 🏗️ arch-bot | 两方向技术方案（A: GitHub dev 读取 + B: F-4 前缀修复） |
| 💻 dev-bot | 方向 A + B 编码实现 |
| 🔍 review-bot | 代码审查 |
| 🦐 qa-bot | 全量测试 |

---

## 流水线步骤

| Step | 名称 | 负责人 | 产出 | 状态 |
|:----:|:-----|:------|:-----|:----:|
| 🔶 A | **需求文档** | 🧐 PM | `docs/R45/R45-product-requirements.md` v0.3（基于实战发现重写） | 🆕 待审核 |
| 🔶 B | **工作计划** | 🧐 PM | 本文档 v2.0 | 🆕 待审核 |
| 🟢 1 | **管线启动** | 🧐 PM | 方向 A 部署后通过 `_admin` 触发 `!pipeline_start R45` | ⏳ |
| 🟢 2 | **技术方案** | 🏗️ arch-bot | `docs/R45/R45-tech-plan.md` — 方向 A（GitHub dev 读取）+ 方向 B（F-4 前缀修复） | ⏳ |
| 🟢 3 | **编码** | 💻 dev-bot | `server/handler.py` — 方向 A: ~10 行 + 方向 B: ~8 行，推 dev | ⏳ |
| 🟢 4 | **代码审查** | 🔍 review-bot | `docs/R45/R45-code-review.md` | ⏳ |
| 🟢 5 | **测试** | 🦐 qa-bot | `docs/R45/R45-test-report.md` | ⏳ |
| 🟢 6 | **合并部署归档** | 🦸 admin-bot | 合并 dev→main，更新 TODO.md，归档 | ⏳ |

---

## 详细说明

### Step 1 — 管线启动

PM 在 `_admin` 频道执行 `!pipeline_start R45`，验证方向 A 的 GitHub dev 分支读取：
- `_check_command_permission` 白名单通过
- 从 GitHub dev 分支获取 WORK_PLAN.md → ✅ 成功
- 自动创建工作室 R45-dev + 收集角色成员
- 点名 arch-bot 附带上下文
- 创建 Step 2 task

### Step 2 — 技术方案

🏗️ arch-bot 出双方向方案：

**方向 A — GitHub dev 分支读取 WORK_PLAN.md**
在 `config.py` 新增 `WORK_PLAN_REPO_URL`（默认指向 `datahome73/ws-bridge/dev`，环境变量可覆盖，fork 友好），`_cmd_pipeline_start()` 中拼接 URL 从远程读取。保留本地文件系统作为 fallback。预估 ~12 行（+3 config + ~9 handler）。

**方向 B — F-4 测试标签前缀修复**
在 `_classify_lobby_message()` 中，strip 测试标签后再检查原始前缀。预估 ~8 行。

### Step 3 — 编码

方向 A + B 同文件修改（`server/handler.py`），可一起提交。

### Step 4 — 代码审查

🔍 review-bot 审查两方向改动的正确性和向后兼容性。

### Step 5 — 测试

🦐 qa-bot 一体完成：
1. 方向 A 验收（A-1~A-4）：GitHub 读取 + fallback + 超时
2. 方向 B 验收（B-1~B-6）：测试标签前缀兼容
3. 回归确认

### Step 6 — 合并部署归档

1. 合并 dev→main
2. 更新 `docs/TODO.md` 中 F-4 状态为 🟢 已完成
3. 归档 `docs/R45/` 文档
4. 关闭工作室

---

## 质量门

| 检查点 | 检查内容 | 责任人 |
|:------|:---------|:------|
| Step 3→4 质量门 | diff 审查：改动仅限 `_cmd_pipeline_start()` + `_classify_lobby_message()`，无 scope creep | 🧐 PM |
| Step 5→6 质量门 | 全部验收项 ✅ 通过后才允许合并 | 🦐 qa-bot |
| Step 6 脱敏检查 | 推远程前 grep 验证 docs/R45/*.md 无内部名/IP 残留 | 🧐 PM |

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
|| v1.0 | 2026-06-27 | 初稿 — R45 工作计划：Phase V 验证 + F-4 修复 |
|| v2.0 | 2026-06-27 | 🔄 重写：实战发现 `!pipeline_start` 依赖本地文件系统，新增方向 A（GitHub dev 分支读取 WORK_PLAN.md）。Phase V 验证推迟到 R46 |
