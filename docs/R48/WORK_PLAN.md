# R48 开发计划

> **版本：** v0.1（初稿，待项目负责人审核）
> **状态：** 📝 草稿
> **编制人：** 🧐 PM
> **日期：** 2026-06-28
> **基于需求：** [R48-product-requirements.md v0.2 ✅](docs/R48/R48-product-requirements.md)

---

## 一、轮次概览

| 维度 | 内容 |
|:----|:------|
| **轮次** | R48 |
| **需求文档** | 🔗 [R48-product-requirements.md v0.2 ✅](docs/R48/R48-product-requirements.md) |
| **本轮改动范围** | 仅第①类（服务器代码 `server/handler.py` + `server/config.py`） |
| **改动类型** | 功能新增（双方向） |

---

## 二、方向分解 & 验收对照

### 方向 A — 通用化 Work Plan URL

`!pipeline_start` 新增 `--work-plan-url <URL>` 参数，使管线可接收任意项目的 WORK_PLAN 文档链接。

| 任务 | 内容 | 涉及文件 | 预估行数 |
|:----|:------|:---------|:--------:|
| A-1 | `_cmd_pipeline_start` 解析 `--work-plan-url` 参数 | `server/handler.py` | ~5 行 |
| A-2 | 有 `--work-plan-url` 时，发 HEAD 请求验证 URL 可达 | `server/handler.py` | ~10 行 |
| A-3 | URL 验证失败时返回明确错误提示 | `server/handler.py` | ~5 行 |
| A-4 | `_PIPELINE_STATE` 新增 `work_plan_url` 字段 | `server/handler.py` | ~3 行 |
| A-5 | 点名 Step 2 上下文改为使用 work_plan_url（如有） | `server/handler.py` | ~5 行 |
| A-6 | 未传 `--work-plan-url` 时走默认行为，完全向后兼容 | `server/handler.py` | 条件分支，零新增行 |

**方向 A 验收标准：** A-1 ~ A-7（见需求文档 §4.1）

### 方向 B — TG 私聊通知管线完成

Step 6 完成时，服务端在 `_admin` 频道写入 `🔔 [PIPELINE_COMPLETE]` 完结消息，PM 收到后 TG DM 项目负责人。

| 任务 | 内容 | 涉及文件 | 预估行数 |
|:----|:------|:---------|:--------:|
| B-1 | `_PIPELINE_STATE` 新增 `triggerer_id` 记录触发者 | `server/handler.py` | ~3 行 |
| B-2 | Step 6 完成后（最后一步），扩展完结消息为 `🔔 [PIPELINE_COMPLETE]` 格式 | `server/handler.py` | ~5 行 |
| B-3 | 完结消息包含管线名称、最终产出、工作室已关闭信息 | `server/handler.py` | ~5 行 |
| B-4 | 中间 Step 的 `_admin` 进度通知维持 `📋` 不变 | `server/handler.py` | 零新增（条件判断） |

**方向 B 验收标准：** B-1 ~ B-5（见需求文档 §4.2）

---

## 三、角色分工

| 角色 | 负责人 | 职责 |
|:----:|:------:|:-----|
| 🧐 **PM（需求分析师）** | PM | 编写需求文档 + WORK_PLAN → 推 dev → 触发管线 |
| 🏗️ **架构师** | 架构师 | 技术方案设计 |
| 💻 **开发工程师** | 开发工程师 | 编码实现（handler.py） |
| 🔍 **审查工程师** | 审查工程师 | 代码审查 |
| 🦐 **测试工程师** | 测试工程师 | Dev 部署 + 测试验证 |
| 🦸 **项目管理** | 项目管理 | 合并 dev→main + 部署 + 归档 |

---

## 四、开发步骤（6 步自动管线）

> 使用 R42+ 的自动管线流程。PM 在 `_admin` 频道触发 `!pipeline_start R48 --from step2`。

### Step 1 — 管线启动 🧐 PM
在 `_admin` 频道执行 `!pipeline_start R48 --from step2`

### Step 2 — 技术方案 🏗️ 架构师
产出：`docs/R48/R48-tech-plan.md`

### Step 3 — 编码实现 💻 开发工程师
产出：代码 commit（`server/handler.py` + `server/config.py`）

**改动位置：**
- `server/handler.py` `_cmd_pipeline_start()`（~行 1081-1145）— 解析 `--work-plan-url` + 远程 URL 验证优先 + 存储管线状态
- `server/handler.py` `_cmd_step_complete()` 最后一步分支（~行 1264-1269）— 完结消息格式升级为 `🔔 [PIPELINE_COMPLETE]`
- `server/config.py` — 无需改动（`WORK_PLAN_REPO_URL` 已存在，作为默认值）

**预估代码行数：** ~35 行新增 / 无删除

### Step 4 — 代码审查 🔍 审查工程师
产出：`docs/R48/R48-code-review.md`

### Step 5 — 测试验证 🦐 测试工程师
产出：`docs/R48/R48-test-report.md`
- 部署 dev 容器
- 全量验收：A-1 ~ A-7 + B-1 ~ B-5

### Step 6 — 合并部署归档 🦸 项目管理
- 合并 dev→main
- 部署生产容器
- 更新 TODO.md
- 关闭工作室

---

## 五、注意事项

1. **向后兼容是 P0** — `!pipeline_start R49 --from step2`（不传 `--work-plan-url`）的行为必须与 R47 完全一致
2. **双入口同步** — `__main__.py` 的 `ws_handler()` 不直接涉及（A/B 方向都走 `_cmd_*` 命令），但需确认 import 完整性
3. **context URL 格式变更** — 点名架构师时，上下文从 `需求: ... | WORK_PLAN: ...` 简化为 `WORK_PLAN: {url}`（需求文档已在策划阶段嵌入 WORK_PLAN 内部）
4. 参考：R45 WORK_PLAN_REPO_URL 远程验证模式（`references/r45-work-plan-remote-url-pattern.md`）

---

## 六、各 Step 输出对照

| Step | 角色 | 产出 | 验收覆盖 |
|:----:|:----:|:------|:--------:|
| 2 | 🏗️ 架构师 | `docs/R48/R48-tech-plan.md` | 方向 A + B 的设计方案 |
| 3 | 💻 开发工程师 | code commit（handler.py） | A-1~A-7 + B-1~B-4 |
| 4 | 🔍 审查工程师 | `docs/R48/R48-code-review.md` | 代码质量 + 验收覆盖 |
| 5 | 🦐 测试工程师 | `docs/R48/R48-test-report.md` | 逐项验证 A-1~B-5 |
| 6 | 🦸 项目管理 | 合并部署 | TODO.md 更新 |
