# R45 工作计划 — R44 实战验证 + F-4 测试标签前缀修复

> **版本：** v1.0 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核
> **产品经理：** 🧐 PM
> **日期：** 2026-06-27

---

## 角色分工

| 角色 | 职责 |
|:-----|:------|
| 🧐 PM | 需求文档 + 工作计划 + 协调推进 |
| 🦸 admin-bot | 执行 `!pipeline_start` / 合并 main / 部署 / 归档 |
| 🏗️ arch-bot | 验证方案（Phase V）+ F-4 修复方案 |
| 💻 dev-bot | F-4 编码实现 |
| 🔍 review-bot | F-4 代码审查 |
| 🦐 qa-bot | F-4 全量测试 + R44 实战验证 |

---

## 流水线步骤

| Step | 名称 | 负责人 | 产出 | 状态 |
|:----:|:-----|:------|:-----|:----:|
| 🔶 A | **需求文档** | 🧐 PM | `docs/R45/R45-product-requirements.md` v0.2 ✅ 项目负责人审核通过 | ✅ |
| 🔶 B | **工作计划** | 🧐 PM | 本文档 v1.0 ✅ 项目负责人审核通过 | ✅ |
| 🟢 1 | **管线启动** | 🧐 PM → 🦸 admin-bot | `!pipeline_start R45` 触发管线自动创建工作室 + 点名 | 🆕 |
| 🟢 2 | **验证方案** | 🏗️ arch-bot | `docs/R45/R45-validation-plan.md` — Phase V 实战验证方案（验证 R44 端到端链路）+ F-4 修复方案 | ⏳ |
| 🟢 3 | **F-4 编码** | 💻 dev-bot | 修复 `handler.py` 中 `_classify_lobby_message()` 前缀匹配逻辑，推 dev | ⏳ |
| 🟢 4 | **代码审查** | 🔍 review-bot | `docs/R45/R45-code-review.md` — F-4 改动审查 | ⏳ |
| 🟢 5 | **全面验证** | 🦐 qa-bot | `docs/R45/R45-test-report.md` — Phase V 验证结果 + F-4 验收测试 | ⏳ |
| 🟢 6 | **合并部署归档** | 🦸 admin-bot | 合并 dev→main，更新 TODO.md F-4 状态，归档文档，关闭工作室 | ⏳ |

---

## 详细说明

### Step 1 — 管线启动

PM 在 `_admin` 频道执行 `!pipeline_start R45`，验证 R44 修复的端到端链路：
- Gateway 识别命令 → 路由到 `_admin` 频道
- `_check_command_permission` 白名单通过
- 自动创建工作室 R45-dev
- 自动从 `auth.get_users()` 收集开发角色成员
- 点名 arch-bot 附带上下文
- 创建 Step 2 task

### Step 2 — 验证方案

🏗️ arch-bot 出两份方案：

**Part A — Phase V 验证方案（`docs/R45/R45-validation-plan.md`）**
列出 V-1~V-6 每条验收标准的实战验证方法。由于 F-4 涉及前缀匹配，验证过程中可直接用 `[R45测试] 📢` 等带测试标签的消息进行。

**Part B — F-4 修复方案**
在 `handler.py` 中修改 `_classify_lobby_message()`，使内容中任意位置出现 `📢` / `📋` / `🆘` 前缀时均能被识别。具体方式（strip 标签再 match / 改用 find / 正则提取）由架构师决定。

### Step 3 — F-4 编码

仅修改 `server/handler.py` 中的 `_classify_lobby_message()` 和相关前缀匹配逻辑（line ~2100）。改动范围预估 5~10 行。

### Step 4 — 代码审查

🔍 review-bot 审查 F-4 改动的正确性和向后兼容性。

### Step 5 — 全面验证

🦐 qa-bot 一体完成：
1. F-4 验收测试（A-1~A-6）
2. Phase V 实战验证（V-1~V-6）
3. 回归确认（无测试标签的消息正常）

产出 `docs/R45/R45-test-report.md`，包含两组验收结果。

### Step 6 — 合并部署归档

1. 合并 dev→main
2. 部署生产环境
3. 更新 `docs/TODO.md` 中 F-4 状态为 🟢 已完成
4. 归档 `docs/R45/` 文档
5. 关闭工作室

---

## 质量门

| 检查点 | 检查内容 | 责任人 |
|:------|:---------|:------|
| Step 3→4 质量门 | diff 审查：改动仅限 `_classify_lobby_message()`，无 scope creep | 🧐 PM |
| Step 5→6 质量门 | 全部验收项 ✅ 通过后才允许合并 | 🦐 qa-bot |
| Step 6 脱敏检查 | 推远程前 grep 验证 docs/R45/*.md 无内部名/IP 残留 | 🧐 PM |

---

## 变更记录

| 版本 | 日期 | 变更 |
|:----:|:----:|:------|
| v1.0 | 2026-06-27 | 初稿 — R45 工作计划：Phase V 验证 + F-4 修复 |
