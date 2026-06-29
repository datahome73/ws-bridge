# R51 开发计划

> **版本：** v0.2 ✅（项目负责人审核通过）
> **状态：** ✅ 已审核 — Step 1 管线启动中
> **编制人：** 🧐 PM
> **日期：** 2026-06-29
> **基于需求：** [R51-product-requirements.md v0.2 ✅](./R51-product-requirements.md)

---

## 一、轮次概览

| 维度 | 内容 |
|:----|:------|
| **轮次** | R51 |
| **需求文档** | 🔗 [R51-product-requirements.md v0.2 ✅](./R51-product-requirements.md) |
| **本轮改动范围** | 仅第①类（服务器代码 `server/handler.py`，1 行变更） |
| **轮次类型** | 验证 + 小功能修复轮 |
| **核心目标** | 修复 `!step_complete` 大小写 Bug + 通过完整管线流程验证自动化交接 |

---

## 二、参与角色

| 角色 | bot | 本轮任务 |
|:----|:----|:---------|
| 🧐 PM（需求/调度） | pm-bot | 触发管线、更新状态、通知项目负责人 |
| 🏗️ 架构师（技术方案） | arch-bot | 出技术方案（极小 — 1 行改动） |
| 💻 开发工程师（编码） | dev-bot | 实现 1 行 `.lower()` 代码修改 |
| 🔍 审查工程师（代码审查） | review-bot | 审查 1 行代码修改 |
| 🦐 测试工程师（测试验证） | qa-bot | dev 部署 + 全量验收（A-1~A-5）+ V-1~V-9 管线验证 |
| 🦸 管理员（合并部署） | admin-bot | 合并 dev→main + 生产部署 |

---

## 三、管线步骤

### Phase F — 修复（标准 6 步管线）

| Step | 名称 | 状态 | 责任人 | 产出 | 验收 |
|:----:|:-----|:----:|:------|:-----|:----:|
| 1 | 🔶 管线启动 | ⏳ | 服务端自动 | 建工作室 + 点名全员 + 派活 | A-1~A-5 |
| 2 | 🏗️ 技术方案 | ⏳ | arch-bot | `docs/R51/R51-tech-plan.md`（极简 — 1 行改动说明） | — |
| 3 | 💻 编码实现 | ⏳ | dev-bot | `server/handler.py` 第 1396 行 `step_name = positional[0].lower()` | A-1~A-4 |
| 4 | 🔍 代码审查 | ⏳ | review-bot | `docs/R51/R51-code-review.md` | A-1~A-5 |
| 5 | 🦐 测试验证 | ⏳ | qa-bot | dev 部署 + A-1~A-5 逐项验收 | A-1~A-5 |
| 6 | 🦸 合并部署归档 | ⏳ | admin-bot | 合并 dev→main + 生产部署 | ✅ |

### Phase V — 验证（纯执行，零代码改动）

Phase F 部署上线后，逐项执行 V-1~V-9 验证，产出 `docs/R51/R51-test-report.md`。

| V-# | 验证项 | 方法 | 预期 |
|:---:|:-------|:----|:-----|
| V-1 | `!pipeline_start R51 --from step2` | 在 `_admin` 频道触发 | 工作室创建 + 点名 |
| V-2 | 点名后活跃频道自动切换 | 点名前/后用 `!agent_status` 检查 | 频道变为 `ws:R51-dev` |
| V-3 | `!step_complete Step2 --output <sha>` 大小写不敏感 | 大写 S 输入 | ✅ 匹配成功 |
| V-4 | `!step_complete Step3` 后自动点名 review | 检查点名输出 | review 被点名 |
| V-5 | Step 交接时活跃频道自动切换 | `!agent_status` 检查 review 频道 | ✅ 自动切换 |
| V-6 | Agent Card 收集成员 | `!agent_card list` | 各角色有 `pipeline_roles` |
| V-7 | `!step_complete Step6` 管线关闭 | 执行命令 | 工作室关闭 |
| V-8 | 大厅恢复接收 | 发一条大厅消息 | ✅ 正常路由 |
| V-9 | V-1 管线指向 R51 验证轮次本身 | — | 全流程通过 |

---

## 四、变更日志

| 版本 | 日期 | 说明 |
|:----:|:----|:------|
| v0.1 | 2026-06-29 | 初稿 — 验证 + 小功能修复轮管线步骤 |

---

## 五、相关资源

- 需求文档：`docs/R51/R51-product-requirements.md`
- Agent Card 操作：`!agent_card list/get/set` 命令
- 管线命令：`!pipeline_start`、`!step_complete`、`!pipeline_status`、`!pipeline_activate`、`!step_handoff`
